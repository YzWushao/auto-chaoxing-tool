"""Server-owned signing queues fed by JPEG or explicitly selected native QR input."""
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .camera_sign import CameraRateLimit, qr_parameters, sign_requirement_message
from .chaoxing import CaptchaRequired, PlatformError, SessionExpired, SignRequirement
from .qr_frames import FrameBusy


TERMINAL = {'completed', 'stopped', 'expired', 'attention', 'error'}


class CameraRun:
    def __init__(self, manager, identity, accounts, concurrency, expires, allowed=None, location=None, authority=None, finished=None, interval=.1, input_mode='jpeg', retry_interval=2.5):
        self.manager, self.identity, self.expires = manager, identity, expires
        self.id = secrets.token_urlsafe(24)
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.state, self.message = 'running', '等待手机上传摄像头画面'
        self.entries = {a['id']:dict(id=a['id'],owner=a['owner'],name=a['name'],state='pending',attempts=0,
            failures=0,pass_failures=0,next_retry=0,retry_code='',message='等待扫码') for a in accounts}
        self.order = list(self.entries)
        self.concurrency = concurrency
        self.retry_interval = retry_interval
        if input_mode not in {'jpeg','native'}:
            raise ValueError('扫码输入方式无效')
        self.input_mode = input_mode
        self.frame_interval = max(.1 if input_mode=='native' else .2, interval)
        self.native_at = 0
        self.allowed, self.location, self.authority, self.finished = allowed, location, authority, finished
        self.pending = self.qr = self.box = None
        self.activity_id = ''
        self.frame_at = time.monotonic()
        self.frame_count = self.decoded_count = self.inflight = 0
        self.created = time.monotonic()
        self.thread = threading.Thread(target=self.run, daemon=True, name='server-camera-'+self.id[:6])
        self.thread.start()

    def finish(self, state, message):
        with self.lock:
            if self.state in TERMINAL:
                return
            self.state, self.message = state, message
            self.pending = self.qr = self.box = None
            callback = self.finished
        self.wake.set()
        if callback:
            callback(self.snapshot(private=True))

    def snapshot(self, private=False):
        with self.lock:
            items = [dict(id=a['id'],name=a['name'],state=a['state'],attempts=a['attempts'],failures=a['failures'],message=a['message'],retry_code=a['retry_code'])
                     for a in self.entries.values()]
            if private:
                items = [{**a,'id':str(index),'name':'当前用户' if len(items)==1 else f'用户 {index+1}'} for index,a in enumerate(items)]
            return {'id':self.id,'state':self.state,'terminal':self.state in TERMINAL,'message':self.message,
                    'frame_interval':self.frame_interval,'input':self.input_mode,
                    'location_mode':('device' if self.location and 'device' in self.location else 'preset' if self.location else 'none'),
                    'remaining_seconds':max(0,self.expires-time.monotonic()),'frames':self.frame_count,
                    'decoded_frames':self.decoded_count,'accounts':items,'detection':self.box}

    def upload(self, content):
        from .qr_frames import MAX_FRAME_BYTES
        if not 0 < len(content) <= MAX_FRAME_BYTES:
            raise ValueError('视频帧需小于 768 KB')
        with self.lock:
            if self.input_mode != 'jpeg':
                raise ValueError('本次会话使用原生扫码')
            if self.state in TERMINAL:
                return self.snapshot()
            self.frame_at = time.monotonic()
            # Drop the older queued frame; never build a video backlog.
            self.pending = (content,self.frame_at)
            self.frame_count += 1
        self.wake.set()
        return self.snapshot()

    def native(self, data):
        if not isinstance(data,dict) or set(data)!={'qr'} or not isinstance(data['qr'],str) or len(data['qr'])>4096:
            raise ValueError('原生扫码数据无效')
        raw = data['qr']
        parsed = qr_parameters(raw) if raw else None
        with self.lock:
            if self.input_mode != 'native':
                raise ValueError('本次会话使用服务器图像识别')
            if self.state in TERMINAL:
                return self.snapshot()
            if parsed and ((self.allowed is not None and parsed[0] not in self.allowed) or self.activity_id not in {'',parsed[0]}):
                raise ValueError('请对准本次所选活动的签到二维码')
            now = time.monotonic()
            if now-self.native_at < min(self.frame_interval,.5)*.8:
                raise CameraRateLimit('正在等待下一次识别')
            self.native_at = self.frame_at = now
            self.frame_count += 1
            self.box = self.qr = None
            if parsed:
                self.activity_id = parsed[0]
                self.qr = (raw,now)
                self.decoded_count += 1
                self.message = '安卓已识别二维码，服务器正在处理签到'
            elif not self.inflight:
                self.message = '等待安卓识别签到二维码'
        self.wake.set()
        return self.snapshot()

    def run(self):
        try:
            while self.state not in TERMINAL:
                self.wake.wait(.1);self.wake.clear()
                now = time.monotonic()
                if now >= self.expires:
                    self.finish('expired','本次扫码已超时');break
                if now-self.frame_at > max(10,self.frame_interval*3):
                    self.finish('stopped','手机已停止上传画面，服务器扫码已结束');break
                if self.authority:
                    try:
                        self.authority()
                    except Exception:
                        self.finish('expired','本次扫码权限已失效');break
                with self.lock:
                    frame,self.pending = self.pending,None
                if frame:
                    try:
                        found = self.manager.detector.detect(frame[0], ('stream',self.id), self.activity_id)
                    except FrameBusy:
                        found = None
                    except ValueError:
                        with self.lock:
                            self.message='无法读取本帧，请保持二维码清晰';self.qr=None;self.box=None
                        found = None
                    if found is not None:
                        with self.lock:
                            if self.state in TERMINAL:
                                break
                            self.box = {'corners':found['corners'],'width':found['width'],'height':found['height'],
                                        'decoded':bool(found['text'])} if found['corners'] else None
                            self.qr = None
                            if found['text']:
                                try:
                                    activity_id,_ = qr_parameters(found['text'])
                                    permitted = (self.allowed is None or activity_id in self.allowed) and self.activity_id in {'',activity_id}
                                except ValueError:
                                    permitted = False
                                if permitted:
                                    self.activity_id = activity_id
                                    self.qr = (found['text'],frame[1])
                                    self.decoded_count += 1
                                    self.message='服务器已识别二维码，正在处理签到'
                                else:
                                    self.message='请对准本次所选活动的签到二维码'
                            elif not self.inflight:
                                self.message='服务器正在寻找二维码，请保持画面清晰'
                self.dispatch()
        except Exception:
            self.finish('error','服务器扫码发生异常，已停止，请核对官方结果后重试')

    def dispatch(self):
        with self.lock:
            if self.state in TERMINAL:
                return
            if not self.order and not self.inflight:
                complete = all(a['state']=='succeeded' for a in self.entries.values())
                self.finish('completed' if complete else 'attention',
                            '所有所选用户已签到成功' if complete else '部分用户未完成签到，请查看每位用户的原因')
                return
            if not self.qr or time.monotonic()-self.qr[1] > 1.5:
                return
            for account_id in self.order[:self.concurrency]:
                item=self.entries[account_id]
                if self.inflight >= self.concurrency:
                    break
                if item['state']!='pending' or item['next_retry'] > time.monotonic():
                    continue
                if not self.manager.sign_slots.acquire(blocking=False):
                    break
                item['state']='submitting';item['attempts']+=1;item['message']='服务器正在签到';self.inflight+=1
                try:
                    self.manager.executor.submit(self.sign,item['id'],self.qr[0])
                except RuntimeError:
                    self.manager.sign_slots.release();self.inflight-=1;item['state']='pending'

    def sign(self, account_id, raw):
        item=self.entries[account_id]
        outcome,message='pending','平台尚未确认成功，将使用最新画面重试'
        rate_limited=False
        retry_code=''
        try:
            with self.lock:
                if self.state in TERMINAL:
                    outcome,message='cancelled','已停止，未提交'
                    return
            if self.authority:
                self.authority()
            self.manager.camera.submit(item['owner'],account_id,raw,location=self.location,retry_interval=self.retry_interval)
            outcome,message='succeeded','签到成功'
        except CameraRateLimit:
            rate_limited=True;message='正在等待该用户的重试间隔'
        except SessionExpired:
            outcome,message='waiting','超星登录已失效，请到用户管理重新登录'
        except CaptchaRequired:
            outcome,message='waiting','自动验证未通过，请在签到中心或官方客户端处理验证'
        except SignRequirement as error:
            message=sign_requirement_message(error.code)
            if error.code == 'location_rejected':
                retry_code=error.code
            else:
                outcome='waiting'
        except (ValueError,PlatformError):
            pass
        except Exception:
            outcome,message='waiting','本次请求未确认，请核对官方结果后再操作'
        finally:
            with self.lock:
                self.inflight-=1
                item['state'],item['message']=outcome,message
                item['retry_code']=retry_code
                item['next_retry']=time.monotonic()+self.retry_interval
                if outcome in {'succeeded','waiting'}:
                    self.order=[v for v in self.order if v!=account_id]
                elif rate_limited or outcome=='cancelled':
                    item['attempts']-=1
                else:
                    item['failures']+=1;item['pass_failures']+=1
                    if item['pass_failures']>10:
                        self.order=[v for v in self.order if v!=account_id]+[account_id]
                        item['pass_failures']=0;item['message']=('上报失败，' if retry_code else '')+'本轮失败 11 次，已移至队尾'
            self.manager.sign_slots.release();self.wake.set()
            if outcome == 'waiting':
                self.manager.camera.signing.store.event(
                    item['owner'], account_id, 'sign_attention',
                    f'扫码签到未完成（活动 {self.activity_id}）：{message}',
                )


class CameraStreams:
    def __init__(self, camera, detector):
        self.camera,self.detector=camera,detector
        self.lock=threading.RLock()
        self.runs={}
        self.shutdown_hooks=[]
        self.executor=ThreadPoolExecutor(max_workers=20,thread_name_prefix='camera-sign-server')
        self.sign_slots=threading.BoundedSemaphore(20)

    def start(self, identity, accounts, concurrency=5, expires=None, **options):
        with self.lock:
            for run in self.runs.values():
                if run.identity==identity:
                    run.finish('stopped','本次扫码已被新的扫描替代')
            now=time.monotonic()
            self.runs={k:v for k,v in self.runs.items() if v.state not in TERMINAL or v.expires+30>now}
            if sum(v.state not in TERMINAL for v in self.runs.values())>=16 or len(self.runs)>=128:
                raise ValueError('服务器扫码会话已满，请稍后重试')
            run=CameraRun(self,identity,accounts,concurrency,expires or now+900,**options)
            self.runs[run.id]=run
            return run

    def get(self, identity, run_id):
        with self.lock:
            run=self.runs.get(run_id)
            if not run or run.identity!=identity:
                raise KeyError(run_id)
            return run

    def shutdown(self):
        for hook in self.shutdown_hooks:hook()
        with self.lock:
            values=list(self.runs.values())
        for run in values:
            run.finish('stopped','服务正在停止')
        for run in values:
            run.thread.join(timeout=2)
        self.executor.shutdown(wait=True,cancel_futures=False)
