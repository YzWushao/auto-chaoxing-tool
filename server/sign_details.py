"""Sign-in/out metadata and explicit platform acknowledgement parsing."""
import re
from urllib.parse import urlencode

KINDS = {'0': 'normal', '2': 'qr', '3': 'gesture', '4': 'location', '5': 'code'}


def activity_id(value):
    text = str(value or '')
    return text if re.fullmatch(r'[1-9][0-9]{0,24}', text) else None


def phase(activity, info=None):
    info = info or {}
    return 'out' if activity.get('phase') == 'out' or activity_id(info.get('signInId')) else 'in'


def action_name(activity, info=None):
    return '签退' if phase(activity, info) == 'out' else '签到'


def pre_query(client, activity):
    return {'courseId': activity['course']['courseId'], 'classId': activity['course']['clazzId'],
            'activePrimaryId': activity['id'], 'general': '1', 'sys': '1', 'ls': '1', 'appType': '15',
            'uid': client.cookie('_uid') or client.cookie('UID'), 'isTeacherViewOpen': '0'}


def pre_status(text):
    found = re.search(r'"primaryAttend"\s*:\s*\{[^{}]*?"status"\s*:\s*(\d+)', text)
    found = found or re.search(r'\bsignstatus\s*=\s*([0-9]+)', text)
    return int(found.group(1)) if found else None


def details(client, activity):
    from .sign_protocol import sign_info
    info = sign_info(client, activity['id'])
    publish = info.get('signOutPublishTimeStamp')
    try:
        publish = float(publish)
        publish = None if publish <= 0 or publish == 4999 else publish/1000 if publish > 100000000000 else publish
    except (ValueError, TypeError):
        publish = None
    return {'phase': phase(activity, info), 'needs_face': str(info.get('openCheckFaceFlag', '0')) == '1',
            'needs_location': str(info.get('ifopenAddress', '0')) == '1',
            'needs_captcha': str(info.get('ifNeedVCode', '0')) == '1',
            'sign_in_id': activity_id(info.get('signInId')), 'sign_out_id': activity_id(info.get('signOutId')),
            'sign_out_publish_at': publish, 'photo': str(info.get('ifphoto', '0')) == '1',
            'official_url': client.SIGN_BASE+'/newsign/preSign?'+urlencode(pre_query(client, activity))}


def confirmed(client, activity):
    query = pre_query(client, activity)
    response = client.request('POST', client.SIGN_BASE+'/newsign/preSign', params=query, data={'ext': activity.get('_ext', '')})
    client.check_login_page(response)
    return pre_status(response.text) in {1, 2, 3, 9}
