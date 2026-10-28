"""User-supplied face photos. No stored portraits or fabricated liveness result."""
import base64
import io
import json
import re
import secrets
import threading
import time

from PIL import Image, ImageOps

from .chaoxing import PlatformError, SignRequirement


def photo_bytes(encoded):
    if not isinstance(encoded, str) or not encoded.startswith('data:image/jpeg;base64,') or len(encoded) > 900000:
        raise ValueError('请拍摄或选择 600 KB 以内的本人照片')
    try:
        data = base64.b64decode(encoded.split(',', 1)[1], validate=True)
        if not 0 < len(data) <= 600*1024:
            raise ValueError()
        with Image.open(io.BytesIO(data)) as original:
            if original.format != 'JPEG' or not 64 <= min(original.size) or original.width*original.height > 12000000:
                raise ValueError()
            image = ImageOps.exif_transpose(original).convert('RGB')
            image.thumbnail((1280, 1280))
            output = io.BytesIO();image.save(output, format='JPEG', quality=85)
            return output.getvalue()
    except (ValueError, OSError, Image.DecompressionBombError):
        raise ValueError('照片无法读取或尺寸不合适，请重新拍摄') from None


def upload_photo(client, data):
    response = client.request('GET', 'https://pan-yz.chaoxing.com/api/token/uservalid', allow_redirects=False)
    client.check_login_page(response)
    token = client.json(response).get('_token')
    if not isinstance(token, str) or not 1 <= len(token) <= 1024:
        raise PlatformError('超星未提供照片上传凭据，请重新登录后重试')
    response = client.request('POST', 'https://pan-yz.chaoxing.com/upload', params={'_from': 'mobilelearn', '_token': token},
                              data={'puid': client.cookie('_uid') or client.cookie('UID')},
                              files={'file': (secrets.token_hex(12)+'.jpg', data, 'image/jpeg')}, allow_redirects=False)
    value = client.json(response)
    object_id = value.get('objectId')
    if not isinstance(object_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', object_id):
        raise PlatformError('平台未确认照片上传成功，请重新拍摄或使用官方客户端')
    return object_id


def face_context(client, activity_id, object_id):
    # A still photo is collected, but it is not a successful liveness test.
    result = {'currentFaceId': object_id, 'LiveDetectionStatus': 0, 'collectStatus': 1, 'cxtime': str(int(time.time()*1000))}
    response = client.request('GET', client.SIGN_BASE+'/pptSign/check-face-result',
                              params={'DB_STRATEGY': 'PRIMARY_KEY', 'STRATEGY_PARA': 'activeId', 'activeId': activity_id,
                                      'faceResult': json.dumps(result, separators=(',', ':'))}, allow_redirects=False)
    value = client.json(response)
    enc = value.get('enc')
    if value.get('result') is False or value.get('status') is False or not isinstance(enc, str) or not 1 <= len(enc) <= 2048:
        raise SignRequirement('official_face_required', '平台未接受照片验证，可能需要官方活体或设备校验，请在官方客户端完成后核对结果')
    # This is a context for final submission, never a claim that a face matched.
    return {'object_id': object_id, 'enc': enc}


class SignFaces:
    def __init__(self, signing):
        self.signing = signing
        self.lock = threading.RLock()
        self.records, self.requests = {}, {}

    def require(self, owner, account_id, activity_id, enc2=None):
        with self.lock:
            self.requests = {k: r for k, r in self.requests.items() if r[0] > time.monotonic()}
            if len(self.requests) >= 128:
                self.requests.pop(next(iter(self.requests)))
            self.requests[(owner, account_id, activity_id)] = (time.monotonic()+180, enc2)

    def context(self, owner, account_id, activity_id, nonce):
        with self.lock:
            item = self.records.get(nonce) if isinstance(nonce, str) else None
            if not item or item['key'] != (owner, account_id, activity_id) or item['expires'] <= time.monotonic():
                raise ValueError('照片凭据已过期或不属于此用户和活动，请重新拍摄')
            return item['value']

    def discard(self, nonce):
        with self.lock:
            self.records.pop(nonce, None)

    def cancel(self, owner, account_id, nonce):
        with self.lock:
            item = self.records.get(nonce)
            if item and item['key'][:2] == (owner, account_id):
                self.records.pop(nonce, None)

    def upload(self, owner, account_id, activity_id, source, encoded, consent):
        if consent is not True:
            raise ValueError('请确认照片为当前用户本人，并同意发送至超星进行本次验证')
        data = photo_bytes(encoded)
        with self.signing.locks[account_id]:
            selected = self.signing.selection(owner, account_id, activity_id, source)
            value = self.signing.account(owner, account_id)
            def current_requirements(client):
                live = client.group_activity(selected) if source == 'group' else next((a for a in client.activities([selected['course']]) if a['id'] == activity_id), None)
                if not live:
                    raise ValueError('当前用户的此活动已经结束或不再可用，不会上传照片')
                return client.sign_requirements(live)
            requirements = self.signing.use_client(value, current_requirements)
            key = (owner, account_id, activity_id)
            with self.lock:
                deadline, enc2 = self.requests.get(key, (0, None))
            if not requirements['needs_face'] and deadline <= time.monotonic():
                raise ValueError('此活动当前未要求人脸照片，不会上传')
            def send(client):
                object_id = upload_photo(client, data)
                return {**face_context(client, activity_id, object_id), 'enc2': enc2}
            context = self.signing.use_client(value, send)
            del data
            now = time.monotonic();nonce = secrets.token_urlsafe(24)
            with self.lock:
                self.records = {k: r for k, r in self.records.items() if r['expires'] > now and r['key'] != key}
                self.requests = {k: r for k, r in self.requests.items() if r[0] > now}
                if len(self.records) >= 64:
                    self.records.pop(min(self.records, key=lambda k: self.records[k]['expires']))
                self.records[nonce] = {'key': key, 'expires': now+120, 'value': context}
            return {'face_id': nonce, 'expires_in': 120, 'message': '照片已提交给超星，继续签到后以平台最终结果为准'}
