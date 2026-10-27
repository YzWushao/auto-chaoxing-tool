"""Private-message OneBot 11 conversation. No study control or passive pushes."""
from __future__ import annotations

import copy
import json
import logging
import queue
import re
import threading
import time
import uuid
from collections import deque
from urllib.parse import urlsplit

from websockets.sync.client import connect

from .chaoxing import PlatformError, SessionExpired
from .config import MASK
from .sign_coordinates import location_parameters
from .sign_images import qq_picture

DEFAULT = {'enabled': False, 'ws_url': '', 'token': '', 'allowed_qqs': []}
KINDS = {'normal': '普通', 'qr': '二维码', 'location': '位置', 'gesture': '手势（请用网页）', 'code': '签到码（请用网页）'}


def validate_settings(data, current):
    if not isinstance(data, dict) or set(data) - set(DEFAULT):
        raise ValueError('NapCat 配置含未知字段')
    value = copy.deepcopy({**DEFAULT, **current})
    value.update(data)
    if type(value['enabled']) is not bool:
        raise ValueError('启用状态无效')
    if not isinstance(value['ws_url'], str) or len(value['ws_url']) > 2048:
        raise ValueError('请填写 WebSocket 地址')
    value['ws_url'] = value['ws_url'].strip()
    try:
        parsed = urlsplit(value['ws_url'])
        valid = parsed.scheme in {'ws', 'wss'} and parsed.hostname and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            valid = False
    except ValueError:
        valid = False
    if value['ws_url'] and (not valid or any(ord(c) < 33 for c in value['ws_url'])):
        raise ValueError('地址需为 ws:// 或 wss://，不能携带 Token、用户信息或查询参数')
    token = value['token']
    if token == MASK:
        token = current.get('token', '')
    if not isinstance(token, str) or len(token) > 512 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError('Token 需为不含空白的可打印英文字符')
    value['token'] = token
    qqs = value['allowed_qqs']
    if not isinstance(qqs, list) or len(qqs) > 100 or any(not isinstance(q, str) or not re.fullmatch(r'[1-9][0-9]{4,14}', q) for q in qqs):
        raise ValueError('授权 QQ 需为有效 QQ 号列表，最多 100 个')
    value['allowed_qqs'] = list(dict.fromkeys(qqs))
    if value['enabled'] and not (value['ws_url'] and token and qqs):
        raise ValueError('启用前请填写地址、Token 和至少一个授权 QQ')
    return value


def public_settings(value):
    return {**value, 'token': MASK if value.get('token') else ''}


def open_connection(value):
    # Disable environment proxies and redirects (sync client doesn't follow HTTP
    # redirects). Credentials go only to the operator-configured WS endpoint.
    logger = logging.getLogger('auto_chaoxing.napcat.transport')
    logger.setLevel(logging.CRITICAL)
    return connect(value['ws_url'], additional_headers={'Authorization': 'Bearer ' + value['token']},
                   proxy=None, open_timeout=8, close_timeout=1, max_size=2*1024*1024,
                   max_queue=32, compression=None, logger=logger)


def test_connection(value):
    try:
        with open_connection(value) as socket:
            echo = uuid.uuid4().hex
            socket.send(json.dumps({'action': 'get_login_info', 'params': {}, 'echo': echo}))
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                response = json.loads(socket.recv(timeout=max(.1, deadline-time.monotonic())))
                if response.get('echo') == echo:
                    if response.get('retcode') != 0 or response.get('status') != 'ok' or not isinstance(response.get('data'), dict):
                        raise ValueError('NapCat 未确认登录信息，请核对 QQ 在线状态与接口配置')
                    return {'ok': True, 'bot_qq': str(response['data'].get('user_id', '')), 'message': '鉴权及读取登录信息成功；未发送 QQ 消息'}
    except ValueError:
        raise ValueError('NapCat 返回异常，请核对服务端类型、Token 和 QQ 在线状态') from None
    except Exception:
        raise ValueError('无法连接 NapCat，请检查 WS 地址、Token、端口映射和网络') from None
    raise ValueError('NapCat 登录信息查询超时')


class SignConversation:
    def __init__(self, store, signing, owner, rpc, settings):
        self.store, self.signing, self.owner, self.rpc, self.settings = store, signing, owner, rpc, settings
        self.sessions, self.rates = {}, {}

    def accounts(self):
        admin = self.store.administrator()
        return [a for owner in self.store.managed_owners(admin['id']) for a in self.store.accounts(owner)]

    def send(self, qq, message):
        # OneBot text segment, not a CQ-code-interpreted string.
        self.rpc('send_private_msg', {'user_id': int(qq), 'message': [{'type': 'text', 'data': {'text': message}}]})

    def show(self, qq, state):
        choices, page = state['choices'], state.get('page', 0)
        size = 12
        title = {'account': '为谁签到？回复用户序号：', 'activity': f"{state.get('name', '')} 的签到列表，回复活动序号：", 'point': '选择你实际所在的预设点位，回复序号：'}[state['phase']]
        lines = [title]
        for i in range(page*size, min(len(choices), (page+1)*size)):
            item = choices[i]
            if state['phase'] == 'account':
                label = item['name'] + ('（登录失效）' if item['status'] != 'active' else '')
            elif state['phase'] == 'activity':
                mode = '拍照（请用网页）' if item.get('photo') else KINDS.get(item['kind'], '请用网页')
                label = f"{item['course']['title']} · {item['title']} [{mode}]" + ('（已签到）' if item['signed'] else '')
            else:
                label = item['school'] + ' · ' + item['name']
            lines.append(f'{i+1}. {label[:200]}')
        if len(choices) > size:
            lines.append(f'第 {page+1}/{(len(choices)+size-1)//size} 页；可回复“下一页”或“上一页”，序号跨页不变。')
        lines.append('回复“签到”重新选择用户，回复“取消”结束。5 分钟未操作会过期。')
        self.send(qq, '\n'.join(lines))

    def handle(self, event):
        config = self.settings()
        qq, bot = str(event.get('user_id', '')), str(event.get('self_id', ''))
        if (not config.get('enabled') or event.get('post_type') != 'message' or event.get('message_type') != 'private'
                or qq not in config.get('allowed_qqs', []) or qq == bot):
            return
        stamp, message_id = event.get('time'), str(event.get('message_id', ''))
        if not isinstance(stamp, (int, float)) or abs(time.time()-stamp) > 120 or not re.fullmatch(r'-?[0-9]{1,30}', message_id):
            return
        if not self.store.claim_napcat_message(bot, qq, message_id):
            return
        bucket = self.rates.setdefault(qq, deque())
        now = time.monotonic()
        while bucket and now-bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= 30:
            return
        bucket.append(now)
        segments = event.get('message')
        if not isinstance(segments, list) or len(segments) > 20:
            return
        segments = [s for s in segments if isinstance(s, dict) and isinstance(s.get('data'), dict)]
        text = ''.join(str(s['data'].get('text', '')) for s in segments if s.get('type') == 'text').strip()
        if len(text) > 2048:
            return
        images = [s for s in segments if s.get('type') == 'image']
        state = self.sessions.get(qq)
        if state and now-state['touched'] > 300:
            self.sessions.pop(qq, None)
            state = None
        if text == '取消':
            self.sessions.pop(qq, None)
            self.send(qq, '已取消本次签到会话。')
            return
        if text == '签到':
            choices = [{'id': a['id'], 'owner': a['owner'], 'name': a['name'], 'status': a['status']} for a in self.accounts()]
            self.sessions.pop(qq, None)
            if not choices:
                self.send(qq, '还没有超星用户，请先在网页控制台添加并登录。')
                return
            state = {'phase': 'account', 'choices': choices, 'touched': now, 'page': 0}
            self.sessions[qq] = state
            self.show(qq, state)
            return
        if state is None:
            if text.isdecimal() or images:
                self.send(qq, '当前没有有效签到会话，请先发送“签到”。')
            return
        state['touched'] = now
        try:
            if text in {'下一页', '上一页'} and state['phase'] in {'account', 'activity', 'point'}:
                state['page'] = min(max(0, state['page']+(1 if text == '下一页' else -1)), (len(state['choices'])-1)//12)
                self.show(qq, state)
                return
            if state['phase'] == 'qr':
                if len(images) != 1:
                    self.send(qq, '请直接上传一张签到二维码图片（不是文件或合并转发），或回复“取消”。')
                    return
                supplied = {'kind': 'qr', 'qr': qq_picture(self.rpc, images[0])}
            else:
                if images or not re.fullmatch(r'[0-9]{1,8}', text) or not 1 <= int(text) <= len(state['choices']):
                    self.send(qq, '请输入列表中的有效序号，或回复“签到”重新开始。')
                    return
                item = state['choices'][int(text)-1]
                if state['phase'] == 'account':
                    if not any(a['id'] == item['id'] and a['owner'] == item['owner'] for a in self.accounts()):
                        raise ValueError('用户已移除，请重新发送“签到”')
                    self.send(qq, '正在刷新该用户的课程签到列表…')
                    activities = self.signing.refresh(item['owner'], item['id'])
                    if not activities:
                        self.sessions.pop(qq, None)
                        self.send(qq, '当前没有进行中的课程签到。回复“签到”可重新刷新。')
                        return
                    state.update(phase='activity', choices=activities, owner=item['owner'], account_id=item['id'], name=item['name'], page=0)
                    self.show(qq, state)
                    return
                if state['phase'] == 'activity':
                    if item['signed']:
                        self.send(qq, '该活动已签到，无需重复提交。可选择其他活动或回复“签到”。')
                        return
                    if item.get('photo') or item['kind'] not in {'normal', 'qr', 'location'}:
                        self.send(qq, '该活动需要拍照、手势或签到码，请在网页端处理；也可选择其他活动。')
                        return
                    state['activity_id'] = item['id']
                    if item['kind'] == 'qr':
                        state['phase'] = 'qr'
                        self.send(qq, '请上传本次签到二维码图片。收到后会本地解码并提交，平台结果会回复到这里；回复“取消”可结束。')
                        return
                    if item['kind'] == 'location':
                        choices = [dict(p, school=s['school']) for s in self.store.location_presets(self.owner) for p in s['points']]
                        if not choices:
                            self.send(qq, '没有已保存的预设点位，请先到设置 → 预设点位添加，再重新选择活动。')
                            return
                        state.update(phase='point', choices=choices, page=0)
                        self.show(qq, state)
                        return
                    supplied = {'kind': 'normal'}
                else:
                    latest = next((p for s in self.store.location_presets(self.owner) if s['school'] == item['school'] for p in s['points'] if p['name'] == item['name']), None)
                    if latest is None or any(latest.get(k) != item.get(k) for k in ('longitude', 'latitude', 'address', 'coordinate_system')):
                        raise ValueError('预设点位已被修改或删除，请重新发送“签到”')
                    supplied = {'kind': 'location', **location_parameters(latest)}
            supplied.update(activity_id=state['activity_id'], _detected_kind=supplied['kind'])
            result = self.signing.submit(state['owner'], state['account_id'], supplied)
            self.sessions.pop(qq, None)
            self.send(qq, state['name'] + '：' + result['message'] + '\n回复“签到”可继续。')
        except SessionExpired:
            self.sessions.pop(qq, None)
            self.send(qq, '所选超星用户登录已失效，请在网页端重新登录后再发送“签到”。')
        except (ValueError, PlatformError) as error:
            message = str(error).replace(config.get('token') or '\0', '[redacted]')[:220]
            self.send(qq, message + '\n可重试；回复“签到”重新开始，回复“取消”结束。')


class NapCatManager:
    def __init__(self, store, signing):
        self.store, self.signing = store, signing
        self.owner = store.administrator()['owner']
        self.lock = threading.RLock()
        self.pending, self.socket, self.threads = {}, None, []
        self.stop_event = threading.Event()
        self.queue = queue.Queue(maxsize=128)
        self.status_value = {'state': 'disabled', 'message': '未启用', 'bot_qq': ''}
        self.conversation = SignConversation(store, signing, self.owner, self.rpc, self.settings)

    def settings(self):
        return self.store.napcat_settings(self.owner)

    def status(self):
        with self.lock:
            return dict(self.status_value)

    def set_status(self, state, message, bot_qq=''):
        with self.lock:
            self.status_value = {'state': state, 'message': message, 'bot_qq': bot_qq}

    def start(self):
        with self.lock:
            if self.threads or not self.settings()['enabled']:
                return
            self.stop_event = threading.Event()
            self.queue = queue.Queue(maxsize=128)
            self.conversation = SignConversation(self.store, self.signing, self.owner, self.rpc, self.settings)
            self.threads = [threading.Thread(target=self.run, daemon=True, name='napcat-receive'), threading.Thread(target=self.work, daemon=True, name='napcat-conversation')]
            for thread in self.threads:
                thread.start()

    def stop(self):
        self.stop_event.set()
        with self.lock:
            socket = self.socket
            for entry in self.pending.values():
                entry['error'] = 'NapCat 已断开，未确认的操作不会自动重试'
                entry['event'].set()
        if socket:
            socket.close()
        for thread in self.threads:
            thread.join(timeout=35)
        if any(thread.is_alive() for thread in self.threads):
            raise ValueError('NapCat 正在完成已接收的操作，请稍后再保存设置')
        self.threads = []
        self.set_status('disabled', '未启用')

    def rpc(self, action, params):
        echo, entry = uuid.uuid4().hex, {'event': threading.Event()}
        with self.lock:
            socket = self.socket
            if socket is None or self.stop_event.is_set():
                raise ValueError('NapCat 尚未连接，请稍后重试')
            self.pending[echo] = entry
        try:
            socket.send(json.dumps({'action': action, 'params': params, 'echo': echo}))
            if not entry['event'].wait(10):
                raise ValueError('NapCat 请求超时，未确认的操作不会自动重发')
            if entry.get('error'):
                raise ValueError(entry['error'])
            response = entry['response']
            if response.get('retcode') != 0 or response.get('status') != 'ok':
                raise ValueError('NapCat 接口未确认成功，请检查机器人状态后重试')
            return response.get('data') or {}
        except (ValueError, PlatformError):
            raise
        except Exception:
            raise ValueError('NapCat 连接中断，请稍后重试') from None
        finally:
            with self.lock:
                self.pending.pop(echo, None)

    def run(self):
        while not self.stop_event.is_set():
            self.set_status('connecting', '正在连接 NapCat')
            try:
                with open_connection(self.settings()) as socket:
                    with self.lock:
                        self.socket = socket
                    echo = uuid.uuid4().hex
                    socket.send(json.dumps({'action': 'get_login_info', 'params': {}, 'echo': echo}))
                    ready = False
                    deadline = time.monotonic()+10
                    while not self.stop_event.is_set():
                        try:
                            raw = socket.recv(timeout=1)
                        except TimeoutError:
                            if not ready and time.monotonic() > deadline:
                                raise ValueError('login info timeout')
                            continue
                        value = json.loads(raw)
                        if not isinstance(value, dict):
                            continue
                        if value.get('echo') == echo:
                            if value.get('retcode') != 0 or not isinstance(value.get('data'), dict) or not value['data'].get('user_id'):
                                raise ValueError('login info failed')
                            ready = True
                            self.set_status('connected', '已连接，等待授权 QQ 的私聊“签到”指令', str(value['data']['user_id']))
                        elif isinstance(value.get('echo'), str):
                            with self.lock:
                                entry = self.pending.get(value['echo'])
                                if entry is not None:
                                    entry['response'] = value
                                    entry['event'].set()
                        elif ready and str(value.get('self_id')) == self.status()['bot_qq'] and value.get('post_type') == 'message' and value.get('message_type') == 'private' and str(value.get('user_id')) in self.settings()['allowed_qqs']:
                            try:
                                self.queue.put_nowait(value)
                            except queue.Full:
                                pass
            except Exception:
                if not self.stop_event.is_set():
                    self.set_status('disconnected', 'NapCat 连接失败或断开，5 秒后重试；请检查地址、Token 和网络')
            finally:
                with self.lock:
                    self.socket = None
                    for entry in self.pending.values():
                        entry['error'] = 'NapCat 连接已断开，未确认的操作不会自动重试'
                        entry['event'].set()
            self.stop_event.wait(5)

    def work(self):
        while not self.stop_event.is_set():
            try:
                value = self.queue.get(timeout=.5)
            except queue.Empty:
                continue
            try:
                self.conversation.handle(value)
            except Exception as error:
                # Never log message bodies, image URLs, token, cookies, or QR enc.
                logging.getLogger('auto_chaoxing.napcat').warning('NapCat conversation failed (%s)', type(error).__name__)
                if str(value.get('user_id')) in self.settings()['allowed_qqs']:
                    try:
                        self.conversation.send(str(value['user_id']), '签到会话处理失败，请重新发送“签到”；若刚才正在提交，请先在官方客户端核对结果。')
                    except Exception:
                        pass
