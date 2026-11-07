"""Explicit activity + users, background batch over the shared signing service."""
import re
import secrets
import threading
import time

from .camera_sign import sign_requirement_message
from .chaoxing import CaptchaRequired, PlatformError, SessionExpired, SignRequirement

TERMINAL={'completed','partial','stopped'}


class BatchRun:
    def __init__(self, manager, identity, users, activity_id, kind, phase, supplied, concurrency, authority):
        self.manager,self.identity,self.authority=manager,identity,authority
        self.id=secrets.token_urlsafe(24)
        self.activity_id,self.kind,self.phase,self.supplied=activity_id,kind,phase,supplied
        self.concurrency=concurrency;self.expires=time.monotonic()+900
        self.lock=threading.RLock();self.wake=threading.Event();self.state='running';self.inflight=0;self.stopping=False
        self.entries=[dict(id=a['id'],owner=a['owner'],name=a['name'],state='pending',code='',message='等待提交') for a in users]
        self.thread=threading.Thread(target=self.run,daemon=True,name='batch-sign-'+self.id[:6])
        self.thread.start()

    def snapshot(self):
        with self.lock:
            return dict(id=self.id,state=self.state,terminal=self.state in TERMINAL,activity_id=self.activity_id,kind=self.kind,phase=self.phase,
                        accounts=[{k:v for k,v in row.items() if k!='owner'} for row in self.entries])

    def stop(self):
        with self.lock:
            if self.state in TERMINAL:return
            self.stopping=True;self.state='stopping'
            for row in self.entries:
                if row['state']=='pending':row.update(state='cancelled',message='已停止，未提交')
        self.wake.set()

    def allowed(self):
        self.authority()
        if self.stopping or time.monotonic()>=self.expires:raise ValueError()

    def run(self):
        try:
            while True:
                try:self.allowed()
                except Exception:self.stop()
                with self.lock:
                    pending=[row for row in self.entries if row['state']=='pending']
                    if not pending and not self.inflight:break
                    for row in pending:
                        if self.stopping or self.inflight>=self.concurrency:break
                        if not self.manager.streams.sign_slots.acquire(blocking=False):break
                        row.update(state='submitting',message='正在检查并提交');self.inflight+=1
                        try:self.manager.streams.executor.submit(self.submit,row)
                        except RuntimeError:
                            self.manager.streams.sign_slots.release();self.inflight-=1
                            row.update(state='cancelled',message='服务正在停止');self.stop()
                self.wake.wait(.1);self.wake.clear()
        finally:
            with self.lock:
                self.supplied.clear()
                self.state='stopped' if self.stopping else 'completed' if all(r['state']=='succeeded' for r in self.entries) else 'partial'

    def submit(self,row):
        status,code,message='failed','','平台未确认成功，请在单用户签到入口核对'
        try:
            self.allowed()
            activities=self.manager.signing.refresh(row['owner'],row['id'],'course')
            selected=next((a for a in activities if a['id']==self.activity_id and a['kind']==self.kind
                           and not a.get('photo') and a.get('phase','in')==self.phase and a.get('source','course')=='course'),None)
            if not selected:
                status,code,message='skipped','activity_unavailable','该用户没有此方式的进行中活动，已跳过'
            else:
                self.allowed()
                result=self.manager.signing.submit(row['owner'],row['id'],dict(self.supplied,activity_id=self.activity_id,
                    kind=self.kind,source='course',_detected_kind=self.kind,_detected_phase=self.phase))
                status,message='succeeded','已完成，无需重复提交' if result.get('duplicate') else '签到成功' if self.phase=='in' else '签退成功'
        except SessionExpired:status,code,message='attention','session_expired','登录失效，请重新登录此用户'
        except CaptchaRequired:status,code,message='attention','verification_required','需要逐人完成滑块验证，请进入单用户签到'
        except SignRequirement as error:
            status='failed' if error.code=='location_rejected' else 'attention';code=error.code
            message=sign_requirement_message(error.code)
        except ValueError:
            if self.stopping:status,message='cancelled','已停止，未提交'
            else:status,code,message='attention','activity_changed','活动、账户或操作权限已变化，请刷新后核对'
        except PlatformError:pass
        except Exception:status,message='attention','请求结果未确认，请先在学习通核对'
        finally:
            with self.lock:
                row.update(state=status,code=code,message=message);self.inflight-=1
            self.manager.streams.sign_slots.release();self.wake.set()


class BatchSigns:
    def __init__(self,signing,streams):
        self.signing,self.streams=signing,streams;self.runs={};self.lock=threading.RLock()
        streams.shutdown_hooks.append(self.shutdown)

    def start(self,identity,users,data,concurrency,authority):
        if set(data)-{'account_ids','activity_id','kind','phase','code','location','device_location'}:
            raise ValueError('批量签到包含未知参数')
        activity_id=data.get('activity_id');kind=data.get('kind');phase=data.get('phase','in')
        if (not isinstance(activity_id,str) or not re.fullmatch(r'[1-9][0-9]{0,24}',activity_id)
                or not isinstance(kind,str) or kind not in {'normal','location','gesture','code'}
                or not isinstance(phase,str) or phase not in {'in','out'}):
            raise ValueError('请选择本次需要提交的签到活动和方式')
        supplied={}
        if kind in {'gesture','code'}:
            code=data.get('code')
            if not isinstance(code,str) or not re.fullmatch(r'[0-9]{1,20}',code):raise ValueError('请填写当前活动的手势数字或签到码')
            supplied['code']=code
        elif data.get('code') is not None:raise ValueError('当前签到方式不使用手势或签到码')
        preset=data.get('location');fix=data.get('device_location')
        if kind=='location':
            from .device_location import device_location
            if fix is not None:supplied.update(device_location(fix,input_mode='native',preset=preset)['device'])
            elif preset is not None:
                from .location_presets import resolve_point
                from .sign_coordinates import location_parameters
                supplied.update(location_parameters(resolve_point(self.signing.store,self.signing.preference_owner,preset)))
                supplied['location_preset']=preset
            else:raise ValueError('请先选择实际所在位置')
        elif preset is not None or fix is not None:raise ValueError('当前签到方式不使用位置参数')
        with self.lock:
            now=time.monotonic();self.runs={k:r for k,r in self.runs.items() if r.state not in TERMINAL or r.expires>now}
            if any(r.identity==identity and r.state not in TERMINAL for r in self.runs.values()):raise ValueError('已有批量签到执行中，请先查看结果或停止')
            if len(self.runs)>=128 or sum(r.state not in TERMINAL for r in self.runs.values())>=16:raise ValueError('批量签到队列已满，请稍后重试')
            run=BatchRun(self,identity,users,activity_id,kind,phase,supplied,concurrency,authority);self.runs[run.id]=run;return run

    def get(self,identity,run_id):
        with self.lock:
            run=self.runs.get(run_id)
            if not run or run.identity!=identity:raise KeyError(run_id)
            return run

    def shutdown(self):
        with self.lock:runs=list(self.runs.values())
        for run in runs:run.stop()
        for run in runs:run.thread.join(timeout=2)
