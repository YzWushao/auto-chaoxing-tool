"""Pre-sign, activity requirements, analysis acknowledgements and verification."""
import re
from urllib.parse import urlencode

from .chaoxing import PlatformError, SessionExpired, CaptchaRequired, SignRequirement


def sign_info(client, activity_id):
    response = client.request('GET', client.SIGN_BASE+'/v2/apis/active/getPPTActiveInfo', params={'activeId': activity_id})
    client.check_login_page(response)
    info = client.json(response).get('data')
    if not isinstance(info, dict):
        raise PlatformError('未能获取签到要求，请刷新活动后重试')
    return info


def execute_sign(client, activity, params, supplied):
    from .sign_captcha import resolve_challenge
    from .sign_details import action_name, pre_status
    course = activity['course']
    info = sign_info(client, activity['id'])
    from .sign_details import phase
    activity['phase'] = phase(activity, info)
    label = action_name(activity, info)
    query = {'courseId': course['courseId'], 'classId': course['clazzId'], 'activePrimaryId': activity['id'],
             'general': '1', 'sys': '1', 'ls': '1', 'appType': '15', 'uid': params['uid'], 'isTeacherViewOpen': '0'}
    referer = client.SIGN_BASE+'/newsign/preSign?'+urlencode(query)
    context = supplied.get('_verification')
    if not context:
        pre = client.request('POST', client.SIGN_BASE+'/newsign/preSign', params=query, data={'ext': activity.get('_ext', '')})
        client.check_login_page(pre)
        if '下次早点哦' in pre.text or '签到已截止' in pre.text:
            raise SignRequirement('activity_ended', '此签到已截止')
        if '校验失败，未查询到活动数据' in pre.text:
            raise SignRequirement('no_permission', '当前用户没有此活动的签到权限')
        if pre_status(pre.text) in {1, 2, 3, 9}:
            return '平台确认该用户已'+label
        analysis = client.request('GET', client.SIGN_BASE+'/pptSign/analysis', headers={'Referer': referer}, params={'vs': '1', 'DB_STRATEGY': 'RANDOM', 'aid': activity['id']})
        client.check_login_page(analysis)
        match = re.search(r'\bcode\s*=\s*[\'\"]\+[\'\"]([a-f0-9]{8,128})[\'\"]', analysis.text, re.I)
        match = match or re.search(r'\bcode\s*=\s*[\'\"]([a-f0-9]{8,128})[\'\"]', analysis.text, re.I)
        if not match:
            raise PlatformError('预签到校验未返回有效 code，请稍后重试')
        confirmed = client.request('GET', client.SIGN_BASE+'/pptSign/analysis2', headers={'Referer': referer}, params={'DB_STRATEGY': 'RANDOM', 'code': match.group(1)})
        client.check_login_page(confirmed)
    face = supplied.get('_face')
    if str(info.get('openCheckFaceFlag', '0')) == '1' and not face:
        raise SignRequirement('face_required', '此活动需要本人照片验证，请拍摄本人照片，或在官方客户端完成后核对结果')
    if str(info.get('ifopenAddress', '0')) == '1' and params.get('latitude') == '-1':
        raise SignRequirement('location_required', '此二维码签到同时要求位置，请先选择实际所在的预设点位')
    proof = context.get('validate') if context else None
    enc2 = (context.get('enc2') if context else None) or (face.get('enc2') if face else None)
    need_verification = str(info.get('ifNeedVCode', '0')) == '1' and not proof
    for attempt in range(2):
        if need_verification:
            proof, challenge = resolve_challenge(client, referer)
            if not proof:
                raise CaptchaRequired(challenge, enc2)
        final = dict(params)
        if proof:
            final['validate'] = proof
        if enc2:
            final['enc2'] = enc2
        if face:
            final.update(currentFaceId=face['object_id'], faceEnc=face['enc'], ifCFP='0', faceCode='', faceEncAid='')
        final['courseId'] = course['courseId']
        response = client.request('GET', client.SIGN_BASE+'/pptSign/stuSignajax', headers={'Referer': referer}, params=final)
        client.check_login_page(response)
        result = response.text.strip()
        if result in {'success', '您已签到过了'}:
            return label+'成功' if result == 'success' else '平台确认该用户已'+label
        if result.lower() in {'please login', 'login', 'notlogin'} or '请先登录' in result:
            raise SessionExpired('超星登录已失效，请重新登录')
        if result.startswith('validate'):
            enc2 = result.partition('_')[2] or None
            need_verification = True
            proof = None
            if attempt == 0:
                continue
            from .sign_captcha import create_challenge
            raise CaptchaRequired(create_challenge(client, referer), enc2)
        if result.startswith(('checkFace_', '[face]')):
            raise SignRequirement('face_required', '平台尚未接受此人脸验证，请重新拍摄或在官方客户端完成后核对结果', result.partition('_')[2] if result.startswith('checkFace_') else None)
        if result == 'success2':
            raise SignRequirement('activity_ended', '签到已结束或迟到，平台未确认本次成功')
        if result.startswith('errorLocation'):
            raise SignRequirement('location_required', '平台未接受此位置，请核对实际所在的预设点位')
        from bs4 import BeautifulSoup
        text = BeautifulSoup(result, 'html.parser').get_text(' ', strip=True)[:200]
        raise PlatformError('签到未成功：'+(text or '平台未确认成功'))
