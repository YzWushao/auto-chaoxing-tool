"""One account lock and activity cache shared by the web UI and QQ workflow."""
import threading
import time
from collections import defaultdict


class SignService:
    def __init__(self, store, use_client, locks=None):
        self.store, self.use_client = store, use_client
        self.locks = locks if locks is not None else defaultdict(threading.RLock)
        self.cache = {}

    def account(self, owner, account_id):
        value = self.store.account(owner, account_id)
        if value is None:
            raise ValueError('超星用户已移除，请重新发送“签到”')
        return value

    def refresh(self, owner, account_id):
        with self.locks[account_id]:
            value = self.account(owner, account_id)
            result = self.use_client(value, lambda client: client.activities(client.courses()))
            self.cache[(owner, account_id)] = (time.monotonic(), result)
            return [a | {'signed': self.store.signed(owner, account_id, a['id'])} for a in result]

    def submit(self, owner, account_id, supplied):
        activity_id = str(supplied.get('activity_id', ''))
        with self.locks[account_id]:
            value = self.account(owner, account_id)
            if self.store.signed(owner, account_id, activity_id):
                return {'message': '该活动已签到，无需重复提交', 'duplicate': True}
            stamp, cached = self.cache.get((owner, account_id), (0, []))
            selected = next((a for a in cached if a['id'] == activity_id), None)
            if not selected or time.monotonic() - stamp > 300:
                raise ValueError('活动列表已过期，请刷新后选择签到活动')
            def do_sign(client):
                live = next((a for a in client.activities([selected['course']]) if a['id'] == activity_id), None)
                if not live:
                    raise ValueError('该签到活动已结束或不再可用')
                # QQ cannot silently reuse a stale activity mode after it changes.
                if supplied.get('_detected_kind') and (live['kind'] != supplied['_detected_kind'] or live.get('photo')
                        or selected['kind'] != supplied['_detected_kind']):
                    raise ValueError('签到方式已变化，请重新发送“签到”并选择活动')
                return client.sign(live, {k: v for k, v in supplied.items() if not k.startswith('_')}, value['name'])
            message = self.use_client(value, do_sign)
            self.store.mark_signed(owner, account_id, activity_id)
            self.store.event(owner, account_id, 'sign_success', selected['title'] + '：签到成功')
            return {'message': message}
