"""Camera requests contain decoded QR text only; frames never leave the browser."""
import re
import time
from urllib.parse import parse_qs, urlsplit
from .chaoxing import SignRequirement


class CameraRateLimit(ValueError):
    pass


SIGN_REQUIREMENT_MESSAGES = {
    'activity_ended': '平台提示活动已截止或迟到，请在学习通核对结果',
    'no_permission': '平台提示该用户无此活动的签到权限，请核对课程归属',
    'face_required': '此用户需要本人照片或人脸验证，请在签到中心或学习通处理',
    'official_face_required': '此用户需要在学习通完成官方人脸验证',
    'location_required': '平台要求位置或未接受已提交位置，请核对实际所在位置',
    'captcha_unavailable': '无法获取或校验滑块验证码，请在学习通核对活动状态并处理验证',
}


def sign_requirement_message(code):
    return SIGN_REQUIREMENT_MESSAGES.get(code, '平台要求额外处理，请在学习通核对活动要求')


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

    def submit(self, owner, account_id, raw, verification_id=None, location=None, face_id=None, retry_interval=None):
        activity_id, enc = qr_parameters(raw)
        key = (owner, account_id)
        with self.signing.locks[account_id]:
            self.signing.account(owner, account_id)
            if self.signing.store.signed(owner, account_id, activity_id):
                return {'message': '该活动已完成，无需重复提交', 'duplicate': True, 'activity_id': activity_id}
            now = time.monotonic()
            if retry_interval is None:
                retry_interval = self.signing.store.preferences(self.signing.preference_owner)['camera_retry_interval']
            if key in self.last_attempt and now - self.last_attempt[key] < retry_interval:
                raise CameraRateLimit('请稍候，正在等待设置的扫码失败重试间隔')
            self.last_attempt[key] = now
            enabled = False
            stamp, previous_mode, previous_id, activities, warnings = self.discovery.get(key, (0, None, None, [], []))
            if now - stamp >= 60 or previous_mode != enabled or previous_id != activity_id:
                activities = self.signing.refresh(owner, account_id, 'all')
                warnings = self.signing.warnings.get((owner, account_id, 'all'), [])
                self.discovery[key] = (time.monotonic(), enabled, activity_id, activities, warnings)
            selected = next((a for a in activities if a['id'] == activity_id and a.get('source','course')=='course'), None)
            if not selected:
                raise ValueError(warnings[0] if warnings else '该用户没有此进行中的签到活动，请确认课程归属')
            if selected['kind'] != 'qr' or selected.get('photo'):
                raise ValueError('此活动不是单独的二维码签到，请在普通签到页面处理')
            parameters = {'activity_id': activity_id, 'source': selected['source'], 'kind': 'qr', 'qr': enc,
                          '_detected_kind': 'qr', 'verification_id': verification_id, 'face_id': face_id}
            if location:
                if not isinstance(location, dict) or set(location) != {'school', 'name'} or not all(isinstance(v, str) for v in location.values()):
                    raise ValueError('预设位置选择无效')
                from .location_presets import resolve_point
                point = resolve_point(self.signing.store, self.signing.preference_owner, location)
                from .sign_coordinates import location_parameters
                parameters.update(location_parameters(point))
                parameters['location_preset'] = location
            try:
                result = self.signing.submit(owner, account_id, parameters)
            except SignRequirement as error:
                error.activity = {'id': activity_id, 'source': selected['source'], 'phase': selected.get('phase', 'in')}
                raise
            return {**result, 'activity_id': activity_id, 'title': selected['title'], 'source': selected['source'], 'phase': selected.get('phase', 'in')}
