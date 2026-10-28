"""Read the account's own group-sign attachments via its IM service.

Independent Python adapter for observed HTTP/attachment formats. No third-party
implementation, protobuf schema, or ordinary chat archive is bundled or stored.
"""
import base64
import json
import re
import time
from urllib.parse import quote

import requests
from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.primitives import padding

from .chaoxing import PlatformError, SessionExpired

IM_ROOT = 'https://a1-vip6.easemob.com/cx-dev/cxstudy'
HISTORY_ROOT = 'https://a1-vip6.easecdn.com/cx-dev/cxstudy'


def sign_attachments(encoded):
    """Extract only structured sign attachments from a bounded binary message.

    Attachment JSON is a UTF-8 string within the IM wire message. We don't need
    the surrounding protocol schema or keep the ordinary message body.
    """
    if not isinstance(encoded, str) or len(encoded) > 1024*1024:
        return []
    try:
        raw = base64.b64decode(encoded, validate=True).decode('utf-8', errors='ignore')
    except (ValueError, TypeError):
        return []
    decoder, found = json.JSONDecoder(), []
    for match in list(re.finditer(r'\{', raw))[:100]:
        snippet = raw[match.start():]
        if 'attachmentType' not in snippet[:500] or 'att_chat_course' not in snippet[:20000]:
            continue
        try:
            value, _ = decoder.raw_decode(snippet)
        except ValueError:
            continue
        item = value.get('att_chat_course') if isinstance(value, dict) and str(value.get('attachmentType')) == '15' else None
        if isinstance(item, dict) and str(item.get('atype')) in {'2', '74'} and re.fullmatch(r'[1-9][0-9]{0,24}', str(item.get('aid', ''))):
            found.append(item)
    return found


class GroupSignClient:
    def __init__(self, platform):
        self.platform = platform
        self.http = requests.Session()
        self.http.trust_env = False
        self.http.headers['User-Agent'] = 'Easemob-SDK(Android) 4.9.0.1'
        self.username = None

    def request(self, method, url, **kwargs):
        try:
            response = self.http.request(method, url, timeout=(5, 15), allow_redirects=False, **kwargs)
            if response.status_code != 200 or len(response.content) > 8*1024*1024:
                raise ValueError()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (requests.RequestException, ValueError):
            raise PlatformError('群聊消息服务暂不可用，请稍后重试；课程签到不受影响') from None

    def login(self):
        response = self.platform.request('GET', 'https://sso.chaoxing.com/apis/login/userLogin4Uname.do')
        value = self.platform.json(response).get('msg')
        if not isinstance(value, dict):
            raise SessionExpired('超星登录已失效，请重新登录后获取群聊签到')
        info_account = value.get('accountInfo')
        account = info_account.get('imAccount') if isinstance(info_account, dict) else None
        if not isinstance(account, dict):
            raise PlatformError('当前登录未提供群聊凭据，请在网页重新登录超星账户')
        password = account.get('password')
        username = str(value.get('uid') or '')
        if not isinstance(password, str) or not password or not re.fullmatch(r'[0-9]{1,24}', username):
            raise PlatformError('当前登录未提供群聊凭据，请在网页重新登录超星账户')
        if re.fullmatch(r'[0-9a-fA-F]+', password) and len(password) % 16 == 0:
            try:
                decryptor = Cipher(TripleDES(b'SL2(M/eD'*3), modes.ECB()).decryptor()
                padded = decryptor.update(bytes.fromhex(password)) + decryptor.finalize()
                unpadder = padding.PKCS7(64).unpadder()
                password = (unpadder.update(padded) + unpadder.finalize()).decode('utf-8')
            except ValueError:
                raise PlatformError('群聊凭据格式已变化，请重新登录或更新适配器') from None
        token = self.request('POST', IM_ROOT+'/token', json={'grant_type':'password', 'username':username, 'password':password})
        if not isinstance(token.get('access_token'), str) or not token['access_token']:
            raise PlatformError('群聊身份认证失败，请重新登录超星账户')
        self.username = quote(str((token.get('user') or {}).get('username') or username), safe='')
        self.http.headers['Authorization'] = 'Bearer '+token['access_token']

    def groups(self):
        if self.username is None:
            self.login()
        result, seen = [], set()
        for page in range(1, 101):
            value = self.request('GET', IM_ROOT+'/users/'+self.username+'/joined_chatgroups', params={'detail':'true', 'version':'v3', 'pagenum':page, 'pagesize':200})
            rows = value.get('data')
            if not isinstance(rows, list):
                raise PlatformError('群聊列表格式已变化，请更新适配器')
            for row in rows:
                group_id = str(row.get('id', '')) if isinstance(row, dict) else ''
                if re.fullmatch(r'[0-9]{1,30}', group_id) and group_id not in seen:
                    seen.add(group_id)
                    result.append({'id':group_id, 'name':str(row.get('name') or '未命名群聊')[:200]})
            if len(rows) < 200:
                return result
        raise PlatformError('群聊数量过多，本次未能完整获取，请稍后重试')

    def history(self, group):
        cursor, seen, result = '-1', set(), []
        # Recent message pages, not an unbounded private-chat archive.
        for _ in range(5):
            value = self.request('POST', HISTORY_ROOT+'/users/'+self.username+'/messageroaming', json={'start':str(cursor), 'end':'-1', 'queue':group['id']+'@conference.easemob.com'})
            body = value.get('data')
            if not isinstance(body, dict) or not isinstance(body.get('msgs'), list):
                raise PlatformError('群聊消息格式已变化，请更新适配器')
            for message in body['msgs']:
                if isinstance(message, dict):
                    result.extend(sign_attachments(message.get('msg')))
            cursor = body.get('next_key')
            if body.get('is_last') in (True, 'true', 1, '1') or not cursor:
                break
            if not isinstance(cursor, (str, int)):
                raise PlatformError('群聊消息分页格式已变化，请更新适配器')
            if cursor in seen:
                break
            seen.add(cursor)
        return result

    def activity(self, group, item):
        active_id = str(item['aid'])
        response = self.platform.request('GET', 'https://mobilelearn.chaoxing.com/v2/apis/active/getPPTActiveInfo', params={'activeId':active_id})
        self.platform.check_login_page(response)
        value = self.platform.json(response)
        info = value.get('data')
        if not isinstance(info, dict):
            return None
        end = info.get('endtime') or info.get('endTime') or 0
        try:
            end = float(end)
        except (ValueError, TypeError):
            end = 0
        if end > 0 and (end/1000 if end > 100000000000 else end) < time.time():
            return None
        kind = {'0':'normal','2':'qr','3':'gesture','4':'location','5':'code'}.get(str(info.get('otherId')))
        if kind is None:
            return None
        course_info = item.get('courseInfo') if isinstance(item.get('courseInfo'), dict) else {}
        course = {'key':'group:'+group['id'], 'courseId':str(info.get('courseId') or course_info.get('courseid') or '0'),
                  'clazzId':str(info.get('clazzid') or info.get('classId') or course_info.get('classid') or '0'), 'cpi':'', 'title':group['name']}
        return {'id':active_id, 'title':str(info.get('name') or item.get('title') or '群聊签到'), 'kind':kind,
                'phase':'out' if str(info.get('signInId') or '').isdigit() and int(info['signInId'])>0 else 'in',
                'photo':str(info.get('ifphoto','0'))=='1', 'course':course, 'source':'group',
                'group_id':group['id'], 'group_name':group['name'], 'start_time':info.get('starttime'), '_group_item':{'aid':active_id, 'courseInfo':{'courseid':course['courseId'], 'classid':course['clazzId']}}}

    def activities(self):
        try:
            result, seen = [], set()
            for group in self.groups():
                for item in self.history(group):
                    if str(item['aid']) in seen:
                        continue
                    seen.add(str(item['aid']))
                    activity = self.activity(group, item)
                    if activity:
                        result.append(activity)
            return result
        finally:
            self.http.close()

    def live(self, selected):
        try:
            group = next((g for g in self.groups() if g['id'] == selected.get('group_id')), None)
            return self.activity(group, selected['_group_item']) if group else None
        finally:
            self.http.close()
