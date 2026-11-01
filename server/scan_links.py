"""Short-lived, one-use QQ capabilities. Never grant a console session."""
import hashlib
import hmac
import secrets
import threading
import time
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from .camera_sign import CameraRateLimit, qr_parameters
from .chaoxing import CaptchaRequired, PlatformError, SessionExpired, SignRequirement
from .config import ROOT


class ScanLinkExpired(Exception):
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

    def _prune(self):
        now = time.monotonic()
        for records in (self.tickets, self.sessions):
            for key, entry in list(records.items()):
                if not entry['active'] or entry['expires'] <= now:
                    records.pop(key, None)

    def revoke(self, qq):
        with self.lock:
            for entry in (*self.tickets.values(), *self.sessions.values()):
                if entry['qq'] == qq:
                    entry['active'] = False
            self._prune()

    def revoke_all(self):
        with self.lock:
            for entry in (*self.tickets.values(), *self.sessions.values()):
                entry['active'] = False
            self.tickets.clear()
            self.sessions.clear()

    def issue(self, qq, owner, account_id, activities):
        config = self.settings()
        base = validate_scan_base_url(config.get('scan_base_url', ''))
        allowed = frozenset(a['id'] for a in activities if a['kind'] == 'qr' and not a.get('photo') and not a.get('signed'))
        self.revoke(qq)
        if not base or not allowed or not config['enabled'] or qq not in config['allowed_qqs']:
            return None
        with self.lock:
            self._prune()
            if len(self.tickets) + len(self.sessions) >= 128:
                return None
            token = secrets.token_urlsafe(32)
            self.tickets[digest(token)] = dict(qq=qq, owner=owner, account_id=account_id, allowed=allowed,
                active=True, expires=time.monotonic()+self.ttl, lock=threading.Lock(), bound=None)
        # Fragments are never sent in HTTP requests, access logs or Referer.
        return base + '/scan#' + token

    def _alive(self, entry):
        config = self.settings()
        if (not entry or not entry['active'] or entry['expires'] <= time.monotonic()
                or not config['enabled'] or entry['qq'] not in config['allowed_qqs']):
            raise ScanLinkExpired()
        if not self.store.account(entry['owner'], entry['account_id']):
            entry['active'] = False
            raise ScanLinkExpired()

    def claim(self, token):
        if not isinstance(token, str) or len(token) != 43:
            raise ScanLinkExpired()
        with self.lock:
            self._prune()
            entry = self.tickets.pop(digest(token), None)
            self._alive(entry)
            cookie, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            entry['csrf'] = csrf
            self.sessions[digest(cookie)] = entry
            return cookie, csrf, entry

    def authorize(self, cookie, csrf):
        if not isinstance(cookie, str) or len(cookie) != 43 or not isinstance(csrf, str):
            raise ScanLinkExpired()
        with self.lock:
            self._prune()
            entry = self.sessions.get(digest(cookie))
            self._alive(entry)
            if not hmac.compare_digest(csrf, entry['csrf']):
                raise ScanLinkExpired()
            return entry

    def status(self, entry):
        self._alive(entry)
        if any(self.store.signed(entry['owner'], entry['account_id'], aid) for aid in entry['allowed']):
            entry['active'] = False
            raise ScanLinkExpired()
        prefs = self.store.preferences(self.camera.signing.preference_owner)
        return {'remaining_seconds': max(0, entry['expires']-time.monotonic()),
                'scan_interval': prefs['camera_scan_interval']}

    def submit(self, entry, data):
        if set(data) != {'qr'}:
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
        if request.method == 'POST' and (not request.is_json or (request.content_length or 0) > 8192):
            return jsonify(error='扫码请求格式无效'), 400

    @page.after_request
    def privacy(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        return response

    @page.errorhandler(ScanLinkExpired)
    def expired(error):
        response = jsonify(error='入口已领取、过期或失效，请回 QQ 重新获取。', code='expired')
        response.status_code = 410
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
        if isinstance(error, (CaptchaRequired, SignRequirement)):
            return jsonify(error='平台需要额外验证，请通过官方客户端或控制台完成后重试。', code='stop'), 422
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

    def entry():
        return links.authorize(request.cookies.get(cookie_name), request.headers.get('X-Scan-CSRF'))

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
        response.set_cookie(cookie_name, cookie, max_age=links.ttl, httponly=True,
                            secure=app.config['SESSION_COOKIE_SECURE'], samesite='Strict', path='/scan-api')
        return response

    @page.get('/scan-api/session')
    def status():
        return jsonify(links.status(entry()))

    @page.post('/scan-api/submit')
    def submit():
        return jsonify(links.submit(entry(), payload()))

    @page.post('/scan-api/close')
    def close():
        record = entry()
        record['active'] = False
        response = jsonify(closed=True)
        response.delete_cookie(cookie_name, path='/scan-api')
        return response

    app.register_blueprint(page)
