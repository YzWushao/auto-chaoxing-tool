"""One account lock and activity cache shared by the web UI and QQ workflow."""
import threading
import time
import secrets
from collections import defaultdict
from .chaoxing import PlatformError, CaptchaRequired, SignRequirement


class SignService:
    def __init__(self, store, use_client, locks=None):
        self.store, self.use_client = store, use_client
        self.locks = locks if locks is not None else defaultdict(threading.RLock)
        self.cache = {}
        self.warnings = {}
        self.challenges = {}
        self.challenge_lock = threading.RLock()
        self.preference_owner = store.administrator()['owner']
        from .sign_faces import SignFaces
        self.faces = SignFaces(self)

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
                return {'message': '该活动已完成，无需重复提交', 'duplicate': True}
            source = supplied.get('source', 'course')
            if not isinstance(source, str) or source not in {'course', 'group'}:
                raise ValueError('签到来源无效')
            if source == 'group' and not self.store.preferences(self.preference_owner)['include_group_sign']:
                raise ValueError('群聊签到已关闭，请重新选择活动')
            stamp, cached = self.cache.get((owner, account_id, source), (0, []))
            selected = next((a for a in cached if a['id'] == activity_id), None)
            if not selected or time.monotonic() - stamp > 300:
                raise ValueError('活动列表已过期，请刷新后选择签到活动')
            face_id = supplied.get('face_id')
            face = self.faces.context(owner, account_id, activity_id, face_id) if face_id else None
            proof_id = supplied.get('verification_id')
            proof = None
            if proof_id:
                record = self._challenge(owner, account_id, proof_id)
                if record['activity_id'] != activity_id or not record.get('validate'):
                    raise ValueError('验证结果不属于此活动或尚未完成，请重新验证')
                proof = {'validate': record['validate'], 'enc2': record['enc2']}
            def do_sign(client):
                live = client.group_activity(selected) if source == 'group' else next((a for a in client.activities([selected['course']]) if a['id'] == activity_id), None)
                if not live:
                    raise ValueError('该签到活动已结束或不再可用')
                # QQ cannot silently reuse a stale activity mode after it changes.
                if supplied.get('_detected_kind') and (live['kind'] != supplied['_detected_kind'] or live.get('photo')
                        or selected['kind'] != supplied['_detected_kind']):
                    raise ValueError('签到方式已变化，请重新发送“签到”并选择活动')
                parameters = {k: v for k, v in supplied.items() if not k.startswith('_') and k not in {'source', 'verification_id', 'face_id'}}
                if proof:
                    parameters['_verification'] = proof
                if face:
                    parameters['_face'] = face
                try:
                    return client.sign(live, parameters, value['name'])
                finally:
                    selected['phase'] = live.get('phase', selected.get('phase', 'in'))
            try:
                message = self.use_client(value, do_sign)
            except CaptchaRequired as error:
                from .sign_captcha import public_challenge
                now = time.monotonic()
                with self.challenge_lock:
                    self.challenges = {k: r for k, r in self.challenges.items() if r['expires'] > now
                                       and (r['owner'], r['account_id'], r['activity_id']) != (owner, account_id, activity_id)}
                    if len(self.challenges) >= 128:
                        self.challenges.pop(min(self.challenges, key=lambda k: self.challenges[k]['expires']))
                    nonce = secrets.token_urlsafe(24)
                    self.challenges[nonce] = {'owner': owner, 'account_id': account_id, 'activity_id': activity_id,
                        'challenge': error.challenge, 'enc2': error.enc2, 'expires': now+180, 'last_check': 0, 'validate': None}
                error.public = public_challenge(error.challenge, nonce)
                raise
            except SignRequirement as error:
                if error.code in {'face_required', 'official_face_required'}:
                    self.faces.require(owner, account_id, activity_id, error.enc2)
                    if face_id:
                        self.faces.discard(face_id)
                raise
            self._mark(owner, account_id, selected)
            if face_id:
                self.faces.discard(face_id)
            if proof_id:
                with self.challenge_lock:
                    self.challenges.pop(proof_id, None)
            return {'message': message, 'phase': selected.get('phase', 'in')}

    def _mark(self, owner, account_id, selected):
        from .sign_details import action_name
        self.store.mark_signed(owner, account_id, selected['id'])
        kind = 'sign_out_success' if selected.get('phase') == 'out' else 'sign_success'
        self.store.event(owner, account_id, kind, selected['title']+'：'+action_name(selected)+'成功')

    def selection(self, owner, account_id, activity_id, source, max_age=300):
        self.account(owner, account_id)
        if not isinstance(source, str) or source not in {'course', 'group'}:
            raise ValueError('签到来源无效')
        if source == 'group' and not self.store.preferences(self.preference_owner)['include_group_sign']:
            raise ValueError('群聊签到已关闭')
        stamp, items = self.cache.get((owner, account_id, source), (0, []))
        selected = next((a for a in items if a['id'] == activity_id), None)
        if not selected or time.monotonic()-stamp > max_age:
            raise ValueError('活动列表已过期，请刷新后重新选择')
        return selected

    def requirements(self, owner, account_id, activity_id, source):
        with self.locks[account_id]:
            selected = self.selection(owner, account_id, activity_id, source)
            value = self.account(owner, account_id)
            result = self.use_client(value, lambda c: c.sign_requirements(selected))
            selected['phase'] = result['phase']
            return {**result, 'activity_id': activity_id, 'source': source}

    def related(self, owner, account_id, activity_id, source, relation):
        if relation not in {'in', 'out'}:
            raise ValueError('关联活动方向无效')
        with self.locks[account_id]:
            details = self.requirements(owner, account_id, activity_id, source)
            target = details.get('sign_in_id' if relation == 'in' else 'sign_out_id')
            if not target or target == activity_id:
                raise ValueError('关联活动尚未发布')
            activities = self.refresh(owner, account_id, source)
            found = next((a for a in activities if a['id'] == target), None)
            if not found:
                raise ValueError('关联活动尚未开始、已经结束，或当前用户没有访问权限')
            return found

    def confirm(self, owner, account_id, activity_id, source):
        with self.locks[account_id]:
            selected = self.selection(owner, account_id, activity_id, source, max_age=3600)
            value = self.account(owner, account_id)
            def check(client):
                if source == 'course' and selected['course']['key'] not in {c['key'] for c in client.courses()}:
                    raise ValueError('此用户已不在该课程中，无法核对结果')
                if source == 'group' and not client.group_activity(selected):
                    raise ValueError('此群聊活动已不可用，无法核对结果')
                return client.sign_confirmed(selected)
            signed = self.use_client(value, check) is True
            if signed and not self.store.signed(owner, account_id, activity_id):
                self._mark(owner, account_id, selected)
            from .sign_details import action_name
            return {'signed': signed, 'phase': selected.get('phase', 'in'),
                    'message': '平台已确认'+action_name(selected) if signed else '平台尚未确认完成，请在官方客户端核对后重试'}

    def _challenge(self, owner, account_id, nonce):
        with self.challenge_lock:
            record = self.challenges.get(nonce) if isinstance(nonce, str) else None
            if (not record or (record['owner'], record['account_id']) != (owner, account_id)
                    or record['expires'] <= time.monotonic()):
                raise ValueError('验证已过期或不属于此用户，请重新提交以获取验证')
            return record

    def verify(self, owner, account_id, nonce, supplied):
        from .sign_captcha import check_challenge, create_challenge, public_challenge
        if set(supplied) - {'action', 'x'} or supplied.get('action') not in {'check', 'refresh', 'cancel'}:
            raise ValueError('验证操作无效')
        with self.locks[account_id]:
            record = self._challenge(owner, account_id, nonce)
            action = supplied['action']
            if action == 'cancel':
                with self.challenge_lock:
                    self.challenges.pop(nonce, None)
                return {'cancelled': True}
            if time.monotonic() - record['last_check'] < 1:
                raise ValueError('验证请求过于频繁，请稍候再试')
            record['last_check'] = time.monotonic()
            value = self.account(owner, account_id)
            if action == 'refresh':
                record['challenge'] = self.use_client(value, lambda c: create_challenge(c, record['challenge']['referer']))
                record['validate'] = None
                record['expires'] = time.monotonic()+180
                return {'verification': public_challenge(record['challenge'], nonce)}
            proof = self.use_client(value, lambda c: check_challenge(c, record['challenge'], supplied.get('x')))
            if not proof:
                raise ValueError('滑块验证未通过，请调整位置或刷新验证图片')
            record['validate'] = proof
            return {'verified': True, 'id': nonce}
