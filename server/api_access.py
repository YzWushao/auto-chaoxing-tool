"""Revocable plugin keys, bounded audit metadata and persistent request deduplication."""
import hashlib
import json
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque

from flask import g, jsonify, request
from flask.sessions import SecureCookieSessionInterface


class ConsoleSessionInterface(SecureCookieSessionInterface):
    """The plugin API never loads or refreshes a caller's console cookie."""
    def open_session(self, app, req):
        if req.path.startswith('/api/v1/'):
            return self.session_class()
        return super().open_session(app, req)

    def save_session(self, app, session, response):
        if not request.path.startswith('/api/v1/'):
            super().save_session(app, session, response)


SCOPES = {
    'read': '读取用户、课程、活动、任务、设置与运行状态',
    'sign:write': '签到、签退、照片与平台验证、摄像头扫码',
    'study:write': '修改刷课配置、启动和停止任务、提交任务输入',
    'accounts:write': '添加、重新登录及删除超星账户',
    'settings:write': '修改全局配置、地图、点位、设备码及 NapCat 设置',
    'admin:write': '更改管理员凭据（仍需当前密码）',
}

API_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_access_settings (admin_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS api_tokens (
    id TEXT PRIMARY KEY, admin_id INTEGER NOT NULL, name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
    prefix TEXT NOT NULL, scopes TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
    last_used_at REAL, revoked INTEGER NOT NULL DEFAULT 0, rate_limit INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS api_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER NOT NULL, token_id TEXT NOT NULL,
    operation TEXT NOT NULL, method TEXT NOT NULL, status INTEGER NOT NULL,
    created_at REAL NOT NULL, duration_ms INTEGER NOT NULL, request_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_requests (
    token_id TEXT NOT NULL, key_hash TEXT NOT NULL, fingerprint TEXT NOT NULL,
    response TEXT, status INTEGER, created_at REAL NOT NULL, expires_at REAL NOT NULL,
    PRIMARY KEY(token_id,key_hash)
);
"""


class ApiTokens:
    def api_enabled(self, admin_id):
        with self.connect() as db:
            row = db.execute('SELECT enabled FROM api_access_settings WHERE admin_id=?', (admin_id,)).fetchone()
        return bool(row and row[0])

    def set_api_enabled(self, admin_id, enabled):
        if type(enabled) is not bool:
            raise ValueError('API 开关需要为布尔值')
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO api_access_settings VALUES (?,?)', (admin_id, int(enabled)))

    @staticmethod
    def _api_public(row):
        return {key: (json.loads(row[key]) if key == 'scopes' else bool(row[key]) if key == 'revoked' else row[key])
                for key in ('id','name','prefix','scopes','created_at','expires_at','last_used_at','revoked','rate_limit')}

    def api_tokens(self, admin_id):
        with self.connect() as db:
            return [self._api_public(row) for row in db.execute(
                'SELECT * FROM api_tokens WHERE admin_id=? ORDER BY created_at DESC', (admin_id,))]

    def create_api_token(self, admin_id, data):
        if (not isinstance(data,dict) or set(data)-{'name','scopes','expires_days','rate_limit'}
                or not isinstance(data.get('name'),str) or not 1 <= len(data['name'].strip()) <= 64
                or any(ord(c)<32 for c in data['name'])):
            raise ValueError('请填写 1～64 字的密钥名称')
        scopes = data.get('scopes', ['read','sign:write'])
        days, rate = data.get('expires_days',90), data.get('rate_limit',600)
        if (not isinstance(scopes,list) or not scopes or any(not isinstance(s,str) or s not in SCOPES for s in scopes)
                or len(set(scopes))!=len(scopes)):
            raise ValueError('请选择有效且不重复的 API 权限')
        if type(days) is not int or not 1 <= days <= 365 or type(rate) is not int or not 10 <= rate <= 6000:
            raise ValueError('有效期需为 1～365 天，限流需为每分钟 10～6000 次')
        token, ident, stamp = 'act_'+secrets.token_urlsafe(32), uuid.uuid4().hex, time.time()
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM api_tokens WHERE admin_id=? AND revoked=0 AND expires_at>?', (admin_id,stamp)).fetchone()[0]>=100:
                raise ValueError('最多保留 100 个有效 API 密钥，请先撤销旧密钥')
            db.execute('INSERT INTO api_tokens VALUES (?,?,?,?,?,?,?,?,?,0,?)',
                       (ident,admin_id,data['name'].strip(),hashlib.sha256(token.encode()).hexdigest(),token[:12],
                        json.dumps(scopes),stamp,stamp+days*86400,None,rate))
            row = db.execute('SELECT * FROM api_tokens WHERE id=?', (ident,)).fetchone()
        return {'token':token,'key':self._api_public(row)}

    def api_token(self, token):
        if not isinstance(token,str) or not re.fullmatch(r'act_[A-Za-z0-9_-]{43}',token):
            return None
        with self.connect() as db:
            row = db.execute('SELECT t.* FROM api_tokens t JOIN api_access_settings s ON s.admin_id=t.admin_id '
                             'WHERE t.token_hash=? AND t.revoked=0 AND t.expires_at>? AND s.enabled=1',
                             (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
            if not row:
                return None
            admin = db.execute('SELECT * FROM administrators WHERE id=?', (row['admin_id'],)).fetchone()
        return {'key':self._api_public(row),'admin':self._public_admin(admin)} if admin else None

    def revoke_api_token(self, admin_id, ident):
        with self.connect() as db:
            changed = db.execute('UPDATE api_tokens SET revoked=1 WHERE admin_id=? AND id=?', (admin_id,ident)).rowcount
        if not changed:
            raise KeyError(ident)

    def api_audit(self, admin_id):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT a.*,t.name AS key_name FROM api_audit a '
                'LEFT JOIN api_tokens t ON t.id=a.token_id WHERE a.admin_id=? ORDER BY a.id DESC LIMIT 100', (admin_id,))]


class ApiAccess:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.rate = defaultdict(deque)
        self.operations = {}

    def authenticate(self):
        g.api_request_id = uuid.uuid4().hex
        g.api_started = time.monotonic()
        auth = request.headers.get('Authorization','')
        token = auth[7:] if auth.lower().startswith('bearer ') else ''
        record = self.store.api_token(token)
        if not record:
            response = jsonify(error='API 未启用，或 Bearer 密钥无效、过期或已撤销',code='invalid_api_key')
            response.status_code=401;response.headers['WWW-Authenticate']='Bearer'
            return response
        g.api_key, g.admin = record['key'], record['admin']
        g.owners = self.store.managed_owners(g.admin['id'])
        name = (request.endpoint or '').removeprefix('external.')
        operation = self.operations.get((name,'GET' if request.method=='HEAD' else request.method))
        if operation is None:
            return jsonify(error='API 操作不存在',code='not_found'),404
        g.api_operation = operation['operationId']
        if operation['scope'] and operation['scope'] not in g.api_key['scopes']:
            return jsonify(error='API 密钥没有此操作的权限',code='insufficient_scope',required_scope=operation['scope']),403
        now = time.monotonic()
        with self.lock:
            self.rate = defaultdict(deque,{k:v for k,v in self.rate.items() if v and now-v[-1]<60})
            bucket = self.rate[g.api_key['id']]
            while bucket and now-bucket[0]>=60:bucket.popleft()
            if len(bucket)>=g.api_key['rate_limit']:
                response=jsonify(error='API 请求过于频繁',code='rate_limited')
                response.status_code=429;response.headers['Retry-After']='60'
                return response
            bucket.append(now)
        with self.store.connect() as db:
            db.execute('UPDATE api_tokens SET last_used_at=? WHERE id=?',(time.time(),g.api_key['id']))
        if request.method in {'POST','PUT','PATCH','DELETE'}:
            if name=='location_presets_import':
                request.max_content_length=16*1024*1024
            frame = name=='camera_stream_frame'
            if frame:
                from .qr_frames import MAX_FRAME_BYTES
                if request.mimetype!='image/jpeg' or (request.content_length or 0)>MAX_FRAME_BYTES:
                    return jsonify(error='视频帧需为 768 KB 以内的 JPEG'),400
            elif not request.is_json:
                return jsonify(error='请求需要 JSON 格式'),415
            elif request.headers.get('Idempotency-Key'):
                return self.reserve_request()

    def reserve_request(self):
        key = request.headers['Idempotency-Key']
        if not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',key):
            return jsonify(error='Idempotency-Key 需为 1～128 位字母、数字或 . _ : -'),400
        # Never persist credentials or request bodies, including natural-language text.
        key_hash = hashlib.sha256(key.encode()).hexdigest()
        fingerprint = hashlib.sha256(request.method.encode()+b'\0'+request.full_path.encode()+b'\0'+request.get_data()).hexdigest()
        stamp = time.time();identity=(g.api_key['id'],key_hash)
        with self.store.lock,self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM api_requests WHERE expires_at<=?', (stamp,))
            row=db.execute('SELECT * FROM api_requests WHERE token_id=? AND key_hash=?', identity).fetchone()
            if row:
                if row['fingerprint']!=fingerprint:
                    return jsonify(error='同一 Idempotency-Key 已用于其他参数',code='idempotency_conflict'),409
                if row['response'] is None:
                    return jsonify(error='此请求仍在执行或上次执行结果未知，请先查询状态',code='idempotency_in_progress'),409
                result=self.store.unseal(row['response'])
                response=jsonify(result);response.status_code=row['status'];response.headers['Idempotency-Replayed']='true'
                return response
            if db.execute('SELECT count(*) FROM api_requests').fetchone()[0]>=10000:
                return jsonify(error='请求去重记录已满，请稍后重试',code='rate_limited'),429
            db.execute('INSERT INTO api_requests VALUES (?,?,?,NULL,NULL,?,?)', (*identity,fingerprint,stamp,stamp+86400))
        g.api_reservation=identity

    def finish(self, response):
        response.headers['X-Request-ID']=g.api_request_id
        if hasattr(g,'api_reservation') and response.is_json:
            value=self.store.seal(response.get_json())
            with self.store.connect() as db:
                db.execute('UPDATE api_requests SET response=?,status=? WHERE token_id=? AND key_hash=?',
                           (value,response.status_code,*g.api_reservation))
        if getattr(g,'api_key',None):
            duration=max(0,int((time.monotonic()-g.api_started)*1000))
            with self.store.connect() as db:
                db.execute('INSERT INTO api_audit(admin_id,token_id,operation,method,status,created_at,duration_ms,request_id) VALUES (?,?,?,?,?,?,?,?)',
                           (g.admin['id'],g.api_key['id'],getattr(g,'api_operation','unknown'),request.method,response.status_code,time.time(),duration,g.api_request_id))
                db.execute('DELETE FROM api_audit WHERE id NOT IN (SELECT id FROM api_audit ORDER BY id DESC LIMIT 5000)')
        return response
