"""One account lock and activity cache shared by the web UI and QQ workflow."""
import threading
import time
from collections import defaultdict
from .chaoxing import PlatformError


class SignService:
    def __init__(self, store, use_client, locks=None):
        self.store, self.use_client = store, use_client
        self.locks = locks if locks is not None else defaultdict(threading.RLock)
        self.cache = {}
        self.warnings = {}
        self.preference_owner = store.administrator()['owner']

    def account(self, owner, account_id):
        value = self.store.account(owner, account_id)
        if value is None:
            raise ValueError('超星用户已移除，请重新发送“签到”')
        return value

    def refresh(self, owner, account_id, source='all'):
        if not isinstance(source, str) or source not in {'all', 'course', 'group'}:
            raise ValueError('签到来源无效')
        enabled = self.store.preferences(self.preference_owner)['include_group_sign']
        if source == 'group' and not enabled:
            raise ValueError('请先在设置中开启获取超星群聊签到')
        with self.locks[account_id]:
            value = self.account(owner, account_id)
            warnings = []
            def fetch(client):
                result = []
                if source != 'group':
                    courses = [dict(a, source='course') for a in client.activities(client.courses())]
                    self.cache[(owner, account_id, 'course')] = (time.monotonic(), courses)
                    result.extend(courses)
                if enabled and source != 'course':
                    self.cache[(owner, account_id, 'group')] = (0, [])
                    try:
                        groups = client.group_activities()
                        self.cache[(owner, account_id, 'group')] = (time.monotonic(), groups)
                        result.extend(groups)
                    except PlatformError as error:
                        warnings.append('群聊签到读取失败：'+str(error))
                return result
            result = self.use_client(value, fetch)
            self.warnings[(owner, account_id, source)] = warnings
            # A course sign posted to a group must not appear twice in QQ.
            merged = {}
            for item in result:
                if item['id'] not in merged:
                    merged[item['id']] = item
                elif item.get('source') == 'group':
                    merged[item['id']] = {**merged[item['id']], 'from_group': True}
            return [a | {'signed': self.store.signed(owner, account_id, a['id'])} for a in merged.values()]

    def submit(self, owner, account_id, supplied):
        activity_id = str(supplied.get('activity_id', ''))
        with self.locks[account_id]:
            value = self.account(owner, account_id)
            if self.store.signed(owner, account_id, activity_id):
                return {'message': '该活动已签到，无需重复提交', 'duplicate': True}
            source = supplied.get('source', 'course')
            if not isinstance(source, str) or source not in {'course', 'group'}:
                raise ValueError('签到来源无效')
            if source == 'group' and not self.store.preferences(self.preference_owner)['include_group_sign']:
                raise ValueError('群聊签到已关闭，请重新选择活动')
            stamp, cached = self.cache.get((owner, account_id, source), (0, []))
            selected = next((a for a in cached if a['id'] == activity_id), None)
            if not selected or time.monotonic() - stamp > 300:
                raise ValueError('活动列表已过期，请刷新后选择签到活动')
            def do_sign(client):
                live = client.group_activity(selected) if source == 'group' else next((a for a in client.activities([selected['course']]) if a['id'] == activity_id), None)
                if not live:
                    raise ValueError('该签到活动已结束或不再可用')
                # QQ cannot silently reuse a stale activity mode after it changes.
                if supplied.get('_detected_kind') and (live['kind'] != supplied['_detected_kind'] or live.get('photo')
                        or selected['kind'] != supplied['_detected_kind']):
                    raise ValueError('签到方式已变化，请重新发送“签到”并选择活动')
                return client.sign(live, {k: v for k, v in supplied.items() if not k.startswith('_') and k != 'source'}, value['name'])
            message = self.use_client(value, do_sign)
            self.store.mark_signed(owner, account_id, activity_id)
            self.store.event(owner, account_id, 'sign_success', selected['title'] + '：签到成功')
            return {'message': message}
