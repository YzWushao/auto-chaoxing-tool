"""Fixed QQ scanner address, numeric codes and isolated temporary sessions."""
import hashlib
import hmac
import secrets
import threading
import time
from collections import deque
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from .camera_sign import CameraRateLimit, qr_parameters, sign_requirement_message
from .chaoxing import CaptchaRequired, PlatformError, SessionExpired, SignRequirement
from .config import ROOT
from .qr_frames import FrameBusy, MAX_FRAME_BYTES
from .preferences import account_label
from .location_presets import school_points, resolve_point


class ScanLinkExpired(Exception):
    pass


class ScanCodeRateLimit(Exception):
    pass


def validate_scan_base_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('扫码入口地址无效')
    value = value.strip().rstrip('/')
    if not value:
        return ''
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == 'https' or (parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1', '::1'}))
        valid = valid and parsed.hostname and not (parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path)
        valid = valid and (parsed.port is None or 1 <= parsed.port <= 65535)
    except ValueError:
        valid = False
    if not valid or any(ord(c) < 33 or ord(c) > 126 for c in value) or '\\' in value:
        raise ValueError('扫码入口请填写可访问的 HTTPS 根地址（含端口），本机调试可用 HTTP localhost')
    return value


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class ScanLinks:
    ttl = 300

    def __init__(self, store, camera, settings):
        self.store, self.camera, self.settings = store, camera, settings
        self.lock = threading.RLock()
        self.tickets, self.sessions = {}, {}
        self.codes, self.code_attempts = {}, {}
        self.recent_codes = {}
        self.code_global_attempts = deque()
        self.code_secret = secrets.token_bytes(32)

    def _prune(self):
        now = time.monotonic()
        self.recent_codes = {k:v for k,v in self.recent_codes.items() if v>now}
        for records in (self.tickets, self.codes, self.sessions):
            for key, entry in list(records.items()):
                result_window = records is self.sessions and entry.get('stream_result_access') and entry['expires']+60 > now
                if not result_window and (not entry['active'] or entry['expires'] <= now):
                    records.pop(key, None)

    def revoke(self, qq):
        with self.lock:
            for entry in (*self.tickets.values(), *self.codes.values(), *self.sessions.values()):
                if entry['qq'] == qq:
                    entry['active'] = False
                    entry['stream_done'] = False
                    entry['stream_result_access'] = False
            self._prune()

    def revoke_all(self):
        with self.lock:
            for entry in (*self.tickets.values(), *self.codes.values(), *self.sessions.values()):
                entry['active'] = False
            self.tickets.clear()
            self.codes.clear()
            self.sessions.clear()

    def _code_key(self, value):
        return hmac.new(self.code_secret,value.encode(),hashlib.sha256).hexdigest()

    def _with_code(self, link):
        if not link:
            return None
        parsed = urlsplit(link)
        with self.lock:
            entry = self.tickets.pop(digest(parsed.fragment),None)
            self._alive(entry)
            if len(self.recent_codes)>=4096:
                raise ValueError('验证码生成过于频繁，请稍后重试')
            for _ in range(32):
                code = f'{secrets.randbelow(100000000):08d}'
                key = self._code_key(code)
                if key not in self.codes and key not in self.recent_codes:
                    break
            else:
                raise ValueError('暂时无法生成新验证码，请重试')
            self.codes[key] = entry
            self.recent_codes[key] = entry['expires']
        return {'url':link.partition('#')[0], 'code':code}

    def issue_picker_code(self, qq):
        return self._with_code(self.issue_picker(qq))

    def issue_code(self, qq, owner, account_id, activities):
        return self._with_code(self.issue(qq,owner,account_id,activities))

    def issue_many_code(self, qq, targets):
        return self._with_code(self.issue_many(qq,targets))

    def issue(self, qq, owner, account_id, activities):
        return self.issue_many(qq,[dict(owner=owner,account_id=account_id,activities=activities)])

    def issue_many(self, qq, targets):
        config = self.settings()
        base = validate_scan_base_url(config.get('scan_base_url', ''))
        self.revoke(qq)
        if not targets or len(targets)>200:
            return None
        allowed = None
        accounts = {}
        for target in targets:
            permitted = frozenset(a['id'] for a in target['activities'] if a['kind']=='qr' and not a.get('photo') and not a.get('signed'))
            allowed = permitted if allowed is None else allowed & permitted
            accounts[(target['owner'],target['account_id'])] = dict(owner=target['owner'],id=target['account_id'])
        if not base or not allowed or not config['enabled'] or qq not in config['allowed_qqs']:
            return None
        accounts = tuple(accounts.values())
        return self._mint(qq, base, accounts, allowed)

    def issue_picker(self, qq):
        """Authorize a snapshotted user picker, not a console or arbitrary owners."""
        config = self.settings()
        base = validate_scan_base_url(config.get('scan_base_url', ''))
        self.revoke(qq)
        if not base or not config.get('enabled') or qq not in config.get('allowed_qqs', []):
            return None
        admin = self.store.administrator()
        mode = self.store.preferences(self.camera.signing.preference_owner)['account_label']
        accounts = tuple(dict(owner=a['owner'], id=a['id'], alias=secrets.token_urlsafe(12),
                              name=account_label(a, mode)[:160])
                         for owner in self.store.managed_owners(admin['id']) for a in self.store.accounts(owner))
        if not accounts or len(accounts) > 200:
            return None
        locations = tuple(dict(alias=secrets.token_urlsafe(12),school=p['school'],name=p['name'])
                          for p in school_points(self.store.location_presets(self.camera.signing.preference_owner)))
        return self._mint(qq, base, accounts, None, picker=True, locations=locations)

    def _mint(self, qq, base, accounts, allowed, picker=False, locations=()):
        owner,account_id = accounts[0]['owner'],accounts[0]['id']
        with self.lock:
            self._prune()
            if len(self.tickets) + len(self.codes) + len(self.sessions) >= 128:
                return None
            token = secrets.token_urlsafe(32)
            self.tickets[digest(token)] = dict(qq=qq, owner=owner, account_id=account_id, accounts=accounts, allowed=allowed,
                picker=picker, locations=locations, active=True, expires=time.monotonic()+self.ttl, lock=threading.Lock(), bound=None)
        # Fragments are never sent in HTTP requests, access logs or Referer.
        return base + '/scan#' + token

    def _alive(self, entry):
        config = self.settings()
        if (not entry or not entry['active'] or entry['expires'] <= time.monotonic()
                or not config['enabled'] or entry['qq'] not in config['allowed_qqs']):
            raise ScanLinkExpired()
        if any(not self.store.account(a['owner'],a['id']) for a in entry['accounts']):
            entry['active'] = False
            raise ScanLinkExpired()
        if entry.get('picker'):
            owners = self.store.managed_owners(self.store.administrator()['id'])
            if any(a['owner'] not in owners for a in entry['accounts']):
                entry['active'] = False
                raise ScanLinkExpired()

    def claim(self, token):
        if not isinstance(token, str) or len(token) != 43:
            raise ScanLinkExpired()
        with self.lock:
            self._prune()
            entry = self.tickets.pop(digest(token), None)
            return self._bind(entry)

    def _bind(self, entry):
        self._alive(entry)
        cookie, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        entry['csrf'] = csrf
        self.sessions[digest(cookie)] = entry
        return cookie, csrf, entry

    def verify_code(self, code, client):
        with self.lock:
            self._prune()
            now = time.monotonic()
            while self.code_global_attempts and now-self.code_global_attempts[0]>=60:
                self.code_global_attempts.popleft()
            self.code_attempts = {k:v for k,v in self.code_attempts.items() if v and now-v[-1]<60}
            client_key = self._code_key(str(client)[:200])
            if client_key not in self.code_attempts and len(self.code_attempts)>=2048:
                raise ScanCodeRateLimit()
            attempts = self.code_attempts.setdefault(client_key,deque())
            while attempts and now-attempts[0]>=60:
                attempts.popleft()
            if len(attempts)>=10 or len(self.code_global_attempts)>=60:
                raise ScanCodeRateLimit()
            attempts.append(now);self.code_global_attempts.append(now)
            if not isinstance(code,str) or len(code)!=8 or any(c not in '0123456789' for c in code):
                raise ScanLinkExpired()
            entry = self.codes.pop(self._code_key(code),None)
            result = self._bind(entry)
            attempts.clear()
            return result

    def authorize(self, cookie, csrf, allow_result=False):
        if not isinstance(cookie, str) or len(cookie) != 43 or not isinstance(csrf, str):
            raise ScanLinkExpired()
        with self.lock:
            self._prune()
            entry = self.sessions.get(digest(cookie))
            if allow_result and entry and entry.get('stream_result_access'):
                self._alive({**entry, 'active':True, 'expires':entry['expires']+60})
            else:
                self._alive(entry)
            if not hmac.compare_digest(csrf, entry['csrf']):
                raise ScanLinkExpired()
            return entry

    def status(self, entry):
        self._alive(entry)
        if entry['allowed'] and any(all(self.store.signed(a['owner'],a['id'],aid) for a in entry['accounts']) for aid in entry['allowed']):
            entry['active'] = False
            raise ScanLinkExpired()
        prefs = self.store.preferences(self.camera.signing.preference_owner)
        result = {'remaining_seconds': max(0, entry['expires']-time.monotonic()),
                  'scan_interval': prefs['camera_scan_interval']}
        if entry.get('picker'):
            result.update(select_users=True, concurrency=prefs['camera_concurrency'], accounts=[
                dict(id=a['alias'], name=a['name'], status=self.store.account(a['owner'], a['id'])['status']) for a in entry['accounts']])
            current = {(p['school'],p['name']):p for p in school_points(self.store.location_presets(self.camera.signing.preference_owner))}
            result['locations'] = [dict(id=p['alias'],school=p['school'],name=p['name'],address=current[(p['school'],p['name'])]['address'])
                                   for p in entry.get('locations',()) if (p['school'],p['name']) in current]
        return result

    def location_reference(self, entry, alias):
        if alias is None:
            return None
        if not isinstance(alias,str):
            raise ValueError()
        item = next((p for p in entry.get('locations',()) if p['alias']==alias),None)
        if item is None:
            raise ValueError()
        reference = dict(school=item['school'],name=item['name'])
        resolve_point(self.store,self.camera.signing.preference_owner,reference)
        return reference

    def select_users(self, entry, aliases):
        if (not isinstance(aliases, list) or not 1 <= len(aliases) <= 200
                or any(not isinstance(a, str) for a in aliases) or len(set(aliases)) != len(aliases)):
            raise ValueError()
        candidates = {a['alias']: a for a in entry['accounts']}
        if any(alias not in candidates for alias in aliases):
            raise ValueError()
        selected = tuple(candidates[alias] for alias in aliases)
        if any(self.store.account(a['owner'], a['id'])['status'] != 'active' for a in selected):
            raise ValueError()
        return selected

    def snapshot(self, entry, run):
        result = run.snapshot(private=True)
        if entry.get('picker'):
            result['accounts'] = [dict(row, id=a['alias'], name=a['name'])
                                  for row, a in zip(result['accounts'], entry['accounts'])]
        return result

    def submit(self, entry, data):
        if set(data) != {'qr'} or len(entry['accounts'])!=1 or entry.get('picker'):
            raise ValueError()
        activity_id, _ = qr_parameters(data['qr'])
        # Bound on the server: no IDs, owners, sources or proof IDs from callers.
        with entry['lock']:
            self.status(entry)
            if activity_id not in entry['allowed'] or entry['bound'] not in {None, activity_id}:
                raise ValueError()
            entry['bound'] = activity_id
            self.camera.submit(entry['owner'], entry['account_id'], data['qr'])
            entry['active'] = False
            return {'completed': True, 'message': '本次签到已完成，入口已失效。'}


def install_scan_routes(app, links):
    page = Blueprint('scan_link', __name__)
    cookie_name = 'ac_scan'

    @page.before_request
    def guard():
        if request.path == '/scan':
            return
        # TLS terminates at Nginx; the loopback WSGI connection remains HTTP.
        # Use the operator's HTTPS configuration, never an untrusted forwarded header.
        scheme = 'https' if app.config['SESSION_COOKIE_SECURE'] else request.scheme
        origin = scheme + '://' + request.host
        if (request.headers.get('X-Scan-Request') != '1' or
                (request.method == 'POST' and request.headers.get('Origin') != origin)):
            return jsonify(error='扫码请求来源无效'), 403
        if request.path == '/scan-api/frame' and request.method == 'POST':
            if request.mimetype != 'image/jpeg' or (request.content_length or 0) > MAX_FRAME_BYTES:
                return jsonify(error='视频帧需为 768 KB 以内的 JPEG'), 400
        elif request.method == 'POST' and (not request.is_json or (request.content_length or 0) > 8192):
            return jsonify(error='扫码请求格式无效'), 400

    @page.after_request
    def privacy(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        return response

    @page.errorhandler(ScanLinkExpired)
    def expired(error):
        response = jsonify(error='验证码已使用、过期或本次扫码已结束，请回 QQ 重新获取验证码。', code='expired')
        response.status_code = 410
        return response

    @page.errorhandler(ScanCodeRateLimit)
    def code_throttled(error):
        response = jsonify(error='验证码尝试过于频繁，请稍后重试。',code='rate_limited')
        response.status_code = 429
        response.headers['Retry-After'] = '60'
        return response

    @page.errorhandler(CameraRateLimit)
    def throttled(error):
        return jsonify(error='请稍候，正在等待下一次扫码提交。'), 429

    @page.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error='请扫描本次 QQ 列表中所选活动的有效签到二维码。'), 400

    @page.errorhandler(PlatformError)
    def platform(error):
        # Never expose upstream messages, account labels, face or captcha data.
        if isinstance(error, SessionExpired):
            return jsonify(error='本次用户登录已失效，请联系控制台管理员。', code='stop'), 422
        if isinstance(error, CaptchaRequired):
            return jsonify(error='自动滑块验证未通过，请在签到中心或学习通处理验证', code='stop'), 422
        if isinstance(error, SignRequirement):
            return jsonify(error=sign_requirement_message(error.code), code='stop'), 422
        return jsonify(error='平台尚未确认签到成功，请继续对准最新二维码。'), 502

    @page.errorhandler(Exception)
    def failed(error):
        if isinstance(error, HTTPException):
            return jsonify(error=error.name), error.code
        return jsonify(error='本次请求未确认，请先核对官方结果再继续。', code='stop'), 503

    def payload():
        data = request.get_json()
        if not isinstance(data, dict):
            raise ValueError()
        return data

    def entry(allow_result=False):
        return links.authorize(request.cookies.get(cookie_name), request.headers.get('X-Scan-CSRF'), allow_result)

    @page.get('/scan')
    def index():
        return send_from_directory(ROOT / 'web', 'scan-link.html')

    @page.post('/scan-api/claim')
    def claim():
        data = payload()
        if set(data) != {'token'}:
            raise ValueError()
        cookie, csrf, record = links.claim(data['token'])
        response = jsonify(csrf=csrf, **links.status(record))
        response.set_cookie(cookie_name, cookie, max_age=links.ttl+60, httponly=True,
                            secure=app.config['SESSION_COOKIE_SECURE'], samesite='Strict', path='/scan-api')
        return response

    @page.post('/scan-api/verify')
    def verify_code():
        data = payload()
        code = data.get('code') if set(data)=={'code'} else None
        # Never trust caller-supplied forwarding headers for rate-limit identity.
        try:
            cookie, csrf, record = links.verify_code(code,request.remote_addr or 'unknown')
        except ScanLinkExpired:
            return jsonify(error='验证码错误、已使用或过期，请回 QQ 发送“扫码签到”获取新验证码。',code='expired'),410
        response = jsonify(csrf=csrf,**links.status(record))
        response.set_cookie(cookie_name,cookie,max_age=links.ttl+60,httponly=True,
                            secure=app.config['SESSION_COOKIE_SECURE'],samesite='Strict',path='/scan-api')
        return response

    @page.get('/scan-api/session')
    def status():
        return jsonify(links.status(entry()))

    @page.post('/scan-api/submit')
    def submit():
        return jsonify(links.submit(entry(), payload()))

    @page.post('/scan-api/start')
    def start_stream():
        record = entry()
        options = payload()
        fields = {'input', 'account_ids', 'location','device_location'} if record.get('picker') else {'input'}
        if set(options)-fields or options.get('input','jpeg') not in ('jpeg','native'):
            raise ValueError()
        links.status(record)
        with record['lock']:
            streams = app.extensions['camera_streams']
            if record.get('stream_id'):
                run = streams.get(('scan',id(record)),record['stream_id'])
                if options.get('input',run.input_mode) != run.input_mode:
                    raise ValueError()
                if record.get('picker') and options.get('account_ids') != [a['alias'] for a in record['accounts']]:
                    raise ValueError()
                if options.get('location') != record.get('selected_location'):
                    raise ValueError()
                if options.get('device_location') != record.get('device_location'):
                    raise ValueError()
                return jsonify(links.snapshot(record, run))
            def finished(summary):
                with links.lock:
                    if record['active']:
                        record['stream_done'] = True
                        record['active'] = False
            prefs = links.store.preferences(links.camera.signing.preference_owner)
            accounts = links.select_users(record, options.get('account_ids')) if record.get('picker') else record['accounts']
            location = links.location_reference(record,options.get('location')) if record.get('picker') else None
            from .device_location import device_location
            location = device_location(options.get('device_location'),input_mode=options.get('input','jpeg'),preset=location) or location
            selected = [dict(id=a['id'],owner=a['owner'],name='当前用户') for a in accounts]
            run = streams.start(('scan',id(record)),selected,concurrency=prefs['camera_concurrency'],
                                expires=record['expires'],allowed=record['allowed'],authority=lambda:links._alive(record),finished=finished,
                                interval=prefs['camera_scan_interval'],location=location,retry_interval=prefs['camera_retry_interval'],
                                input_mode=options.get('input','jpeg'))
            record['accounts'] = accounts
            record['selected_location'] = options.get('location')
            record['device_location'] = options.get('device_location')
            record['stream_id'] = run.id
            record['stream_result_access'] = True
            return jsonify(links.snapshot(record, run))

    @page.get('/scan-api/status')
    def stream_status():
        record = entry(allow_result=True)
        if not record.get('stream_id'):
            return jsonify(state='ready',terminal=False,message='点击开始扫描')
        return jsonify(links.snapshot(record, app.extensions['camera_streams'].get(('scan',id(record)),record['stream_id'])))

    @page.post('/scan-api/frame')
    def upload_frame():
        record = entry()
        run = app.extensions['camera_streams'].get(('scan',id(record)),record.get('stream_id'))
        run.upload(request.get_data(cache=False))
        return jsonify(links.snapshot(record, run)), 202

    @page.post('/scan-api/qr')
    def native_qr():
        record = entry()
        run = app.extensions['camera_streams'].get(('scan',id(record)),record.get('stream_id'))
        run.native(payload())
        return jsonify(links.snapshot(record, run)), 202

    @page.post('/scan-api/close')
    def close():
        record = entry()
        record['active'] = False
        if record.get('stream_id'):
            app.extensions['camera_streams'].get(('scan',id(record)),record['stream_id']).finish('stopped','本次扫码已结束')
        response = jsonify(closed=True)
        if not record.get('stream_id'):
            response.delete_cookie(cookie_name, path='/scan-api')
        return response

    app.register_blueprint(page)
