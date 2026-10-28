"""Camera requests contain decoded QR text only; frames never leave the browser."""
import re
import time
from urllib.parse import parse_qs, urlsplit


class CameraRateLimit(ValueError):
    pass


def qr_parameters(raw):
    if not isinstance(raw, str) or not 1 <= len(raw) <= 4096:
        raise ValueError('请扫描包含活动编号与 enc 的签到二维码')
    text = raw.strip()
    # Two observed payload formats: URL query fields and the SIGNIN wire form.
    query = parse_qs(text[7:].partition('-')[0] if text.startswith('SIGNIN:') else urlsplit(text).query)
    activity_id = next((query.get(key, [''])[0] for key in ('id', 'aid', 'activeId', 'activePrimaryId') if query.get(key)), '')
    enc = query.get('enc', [''])[0]
    if not re.fullmatch(r'[1-9][0-9]{0,24}', activity_id) or not re.fullmatch(r'[A-Za-z0-9_-]{8,256}', enc):
        raise ValueError('请扫描包含活动编号与 enc 的签到二维码')
    return activity_id, enc


class CameraSignService:
    def __init__(self, signing):
        self.signing = signing
        self.discovery = {}
        self.last_attempt = {}

    def submit(self, owner, account_id, raw, verification_id=None, location=None):
        activity_id, enc = qr_parameters(raw)
        key = (owner, account_id)
        with self.signing.locks[account_id]:
            self.signing.account(owner, account_id)
            if self.signing.store.signed(owner, account_id, activity_id):
                return {'message': '该活动已签到，无需重复提交', 'duplicate': True, 'activity_id': activity_id}
            now = time.monotonic()
            if now - self.last_attempt.get(key, -100) < 2:
                raise CameraRateLimit('请稍候再重试，单个用户的请求至少间隔 2 秒')
            self.last_attempt[key] = now
            enabled = self.signing.store.preferences(self.signing.preference_owner)['include_group_sign']
            stamp, previous_mode, previous_id, activities, warnings = self.discovery.get(key, (0, None, None, [], []))
            if now - stamp >= 60 or previous_mode != enabled or previous_id != activity_id:
                activities = self.signing.refresh(owner, account_id, 'all')
                warnings = self.signing.warnings.get((owner, account_id, 'all'), [])
                self.discovery[key] = (time.monotonic(), enabled, activity_id, activities, warnings)
            selected = next((a for a in activities if a['id'] == activity_id), None)
            if not selected:
                raise ValueError(warnings[0] if warnings else '该用户没有此进行中的签到活动，请确认课程或群聊归属')
            if selected['kind'] != 'qr' or selected.get('photo'):
                raise ValueError('此活动不是单独的二维码签到，请在普通签到页面处理')
            parameters = {'activity_id': activity_id, 'source': selected['source'], 'kind': 'qr', 'qr': enc,
                          '_detected_kind': 'qr', 'verification_id': verification_id}
            if location:
                if not isinstance(location, dict) or set(location) != {'school', 'name'} or not all(isinstance(v, str) for v in location.values()):
                    raise ValueError('预设位置选择无效')
                point = next((p for s in self.signing.store.location_presets(self.signing.preference_owner)
                              if s['school'] == location['school'] for p in s['points'] if p['name'] == location['name']), None)
                if not point:
                    raise ValueError('预设点位已变更或移除，请重新选择')
                from .sign_coordinates import location_parameters
                parameters.update(location_parameters(point))
            result = self.signing.submit(owner, account_id, parameters)
            return {**result, 'activity_id': activity_id, 'title': selected['title']}
