"""Explicit QQ multi-selection and bounded batches over the shared signing service."""
import re
import time

from .chaoxing import CaptchaRequired, PlatformError, SessionExpired, SignRequirement
from .sign_coordinates import location_parameters
from .location_presets import school_points, resolve_point
from .sign_images import qq_picture

ALL_SELECTIONS = {'全选', '全部', '一键全选', '全部选择'}
MAX_USERS = 200
MAX_TASKS = 1000


def selection(text, count):
    if not isinstance(text,str) or not isinstance(count,int) or count<1:
        raise ValueError('当前没有可选择的项目，请重新发送“签到”')
    if text in ALL_SELECTIONS:
        return list(range(count))
    if re.search(r'[,，、;；]\s*[,，、;；]',text):
        raise ValueError('请输入列表中的有效序号，多个序号之间使用一个分隔符')
    parts = re.split(r'[\s,，、;；]+', text.strip())
    indexes = []
    for part in parts:
        match = re.fullmatch(r'([0-9]{1,8})(?:[-~～至]([0-9]{1,8}))?', part)
        if not match:
            raise ValueError('请输入列表中的有效序号，例如 1,3,5 或 1-5；也可回复“全选”')
        start, end = int(match[1]), int(match[2] or match[1])
        if not 1 <= start <= end <= count:
            raise ValueError('请输入列表中的有效序号；范围不能越界或倒序')
        indexes.extend(range(start-1, end))
        if len(indexes) > MAX_TASKS*2:
            raise ValueError('选择内容过长，请使用范围或“全选”')
    return list(dict.fromkeys(indexes))


class BatchConversation:
    def batch_error(self, error):
        if isinstance(error, CaptchaRequired):
            return '自动滑块验证未通过，请在网页签到中心完成滑块验证', False
        if isinstance(error, SessionExpired):
            return '超星登录已失效，请在网页端重新登录', False
        if isinstance(error, SignRequirement):
            return str(error)[:220]+'，请在网页端处理', False
        if isinstance(error, (ValueError, PlatformError)):
            token = self.settings().get('token') or '\0'
            return str(error).replace(token, '[redacted]')[:220], isinstance(error, PlatformError)
        return '本次请求未确认，请先在官方客户端核对结果', False

    def batch_accounts(self, qq, state, users):
        if len(users) > MAX_USERS and not state.get('all_accounts'):
            raise ValueError('一次最多选择 200 位用户，请缩小选择范围')
        owned = {(a['owner'], a['id']) for a in self.accounts()}
        if any((u['owner'], u['id']) not in owned for u in users):
            raise ValueError('用户已移除，请重新发送“签到”')
        self.send(qq, f"正在检查{'全部' if state.get('all_accounts') else '所选'} {len(users)} 位用户的签到信息…")
        groups, failures, count = {}, [], 0
        for user in users:
            if not self.settings().get('enabled') or qq not in self.settings().get('allowed_qqs', []):
                self.sessions.pop(qq, None)
                self.revoke_scan(qq)
                return
            try:
                activities = self.signing.refresh(user['owner'], user['id'])
            except Exception as error:
                failures.append(user['name']+'：'+self.batch_error(error)[0])
                continue
            warnings = self.signing.warnings.get((user['owner'], user['id'], 'all'), [])
            failures.extend(user['name']+'：'+str(w)[:180] for w in warnings)
            if state.get('want_phase') == 'out':
                activities = [a for a in activities if a.get('phase') == 'out']
            for activity in activities:
                count += 1
                if count > MAX_TASKS and not state.get('all_accounts'):
                    raise ValueError('本次活动过多，请减少所选用户后重新刷新；尚未提交签到')
                key = (activity['id'], activity.get('phase', 'in'), activity.get('source', 'course'), activity['kind'], bool(activity.get('photo')))
                group = groups.setdefault(key, {**activity, 'targets': [], 'signed': True})
                group['targets'].append(dict(owner=user['owner'], account_id=user['id'], name=user['name'], activity=activity))
                group['signed'] &= activity['signed']
        if failures:
            self.send(qq, '部分列表读取需要处理：\n'+'\n'.join(failures[:8])+ (f'\n另有 {len(failures)-8} 条提示。' if len(failures)>8 else ''))
        if not groups:
            self.sessions.pop(qq, None)
            self.send(qq, '所选用户当前没有可列出的进行中签到；读取失败的用户请处理后重试。')
            return
        self.revoke_scan(qq)
        state.update(batch=True, phase='activity', choices=sorted(groups.values(),key=lambda a:-len(a['targets'])), page=0,
                     name=f"{'全部' if state.get('all_accounts') else '所选'} {len(users)} 位用户", scan_entry='', touched=time.monotonic())
        self.show(qq, state)

    def batch_start(self, qq, state, groups):
        if sum(len(g['targets']) for g in groups) > MAX_TASKS:
            raise ValueError('一次最多处理 1000 条用户活动，请缩小选择范围')
        self.revoke_scan(qq)
        state.update(batch=True, batch_jobs=list(groups), batch_results=[], batch_current=None)
        self.send(qq, f"已选择 {len(groups)} 个活动，共 {sum(len(g['targets']) for g in groups)} 条用户任务，开始逐项处理。")
        self.batch_advance(qq, state)

    def batch_record(self, state, target, status, message):
        state['batch_results'].append(dict(name=target['name'], title=target['activity']['title'], status=status, message=message))

    def batch_authorized(self, qq, state):
        config = self.settings()
        if (self.sessions.get(qq) is not state or not config.get('enabled') or qq not in config.get('allowed_qqs', [])
                or time.monotonic()-state['touched'] > 300):
            self.revoke_scan(qq)
            self.sessions.pop(qq, None)
            return False
        return True

    def batch_remaining(self, state, group):
        owned = {(a['owner'], a['id']) for a in self.accounts()}
        remaining = []
        for target in group['targets']:
            if (target['owner'], target['account_id']) not in owned:
                self.batch_record(state, target, 'failed', '用户已移除或已不在授权范围')
            elif self.store.signed(target['owner'], target['account_id'], target['activity']['id']):
                self.batch_record(state, target, 'duplicate', '已完成，无需重复提交')
            else:
                remaining.append(target)
        group['targets'] = remaining
        return remaining

    def batch_progress(self, state):
        records = state['batch_results']
        counts = {key: sum(r['status']==key for r in records) for key in ('success','duplicate','failed','skipped')}
        return f"成功 {counts['success']} · 已完成 {counts['duplicate']} · 失败/待处理 {counts['failed']} · 跳过 {counts['skipped']}"

    def batch_report(self, qq, state, title):
        records = state['batch_results']
        problems = [r for r in records if r['status'] in {'failed','skipped'}]
        lines = [title, self.batch_progress(state)]
        lines.extend(f"{r['name']} · {r['title']}：{r['message']}" for r in problems[:8])
        if len(problems)>8:
            lines.append(f'另有 {len(problems)-8} 条失败或跳过记录，请在网页按用户核对。')
        self.send(qq, '\n'.join(lines))

    def batch_submit(self, qq, state, supplied, retry_qr=False):
        group = state['batch_current']
        pending = []
        for target in self.batch_remaining(state, group):
            if not self.batch_authorized(qq, state):
                return False
            activity = target['activity']
            data = {**supplied, 'activity_id': activity['id'], 'source': activity.get('source','course'), '_detected_kind': activity['kind']}
            try:
                result = self.signing.submit(target['owner'], target['account_id'], data)
                self.batch_record(state, target, 'duplicate' if result.get('duplicate') else 'success', result['message'])
            except Exception as error:
                message, retry = self.batch_error(error)
                if retry_qr and retry:
                    pending.append({**target, 'last_error': message})
                else:
                    self.batch_record(state, target, 'failed', message)
            state['touched'] = time.monotonic()
        group['targets'] = pending
        return True

    def batch_scan_entry(self, qq, group):
        if not self.scan_links:
            return ''
        targets = [dict(owner=t['owner'], account_id=t['account_id'], activities=[t['activity']]) for t in group['targets']]
        link = self.scan_links.issue_many(qq, targets)
        return ('\n一次性摄像头扫码入口（免控制台登录）：\n'+link+
                '\n仅限本活动的所选用户，5 分钟有效。入口完成后，回 QQ 回复“继续”处理下一项。') if link else ''

    def batch_advance(self, qq, state):
        self.revoke_scan(qq)
        while self.batch_authorized(qq, state) and state['batch_jobs']:
            group = state['batch_jobs'].pop(0)
            state['batch_current'] = group
            targets = self.batch_remaining(state, group)
            if not targets:
                continue
            if group.get('photo') or group['kind'] not in {'normal','qr','location'}:
                for target in targets:
                    self.batch_record(state, target, 'skipped', '需要拍照、手势或签到码，请在网页端处理')
                continue
            if group['kind'] == 'normal':
                if not self.batch_submit(qq, state, {'kind':'normal'}):
                    return
                continue
            names = '、'.join(t['name'] for t in targets[:12])+(f' 等 {len(targets)} 位用户' if len(targets)>12 else '')
            self.send(qq, self.batch_progress(state)+f"\n当前活动：{group['title']}\n用户：{names}")
            if group['kind'] == 'qr':
                state['phase'] = 'qr'
                self.send(qq, '请上传本活动的二维码图片，将为以上所选用户依次提交；仅重试未成功用户。'+
                          '\n回复“跳过”处理下一项，回复“取消”结束。'+self.batch_scan_entry(qq, group))
                return
            points = school_points(self.store.location_presets(self.owner))
            if not points:
                for target in targets:
                    self.batch_record(state, target, 'skipped', '没有已保存的预设点位，请到设置 → 预设点位添加')
                continue
            state.update(phase='point', choices=points, page=0)
            self.show(qq, state)
            return
        if self.sessions.get(qq) is state:
            self.sessions.pop(qq, None)
            self.batch_report(qq, state, '本次批量处理结束。回复“签到”可重新选择。')

    def batch_handle(self, qq, state, text, images):
        if state['phase'] == 'activity':
            if images:
                raise ValueError('请先选择签到活动序号')
            self.batch_start(qq, state, [state['choices'][i] for i in selection(text,len(state['choices']))])
            return
        group = state['batch_current']
        if text == '跳过':
            for target in self.batch_remaining(state, group):
                self.batch_record(state, target, 'skipped', target.get('last_error','用户跳过本项'))
            self.batch_advance(qq, state)
            return
        if state['phase'] == 'qr':
            if text == '继续':
                if not self.batch_remaining(state, group):
                    self.batch_advance(qq, state)
                else:
                    self.send(qq, '当前活动仍有用户未完成，请上传二维码、使用扫码入口，或回复“跳过”。')
                return
            if len(images) != 1:
                self.send(qq, '请直接上传本活动的一张二维码图片；也可回复“继续”核对入口结果，或回复“跳过”。')
                return
            self.send(qq, '图片已收到，正在转换并识别二维码…')
            self.revoke_scan(qq)
            supplied = {'kind':'qr','qr':qq_picture(self.rpc, images[0], self.image_stream)}
            if not self.batch_submit(qq, state, supplied, retry_qr=True):
                return
            if group['targets']:
                self.send(qq, self.batch_progress(state)+f"\n仍有 {len(group['targets'])} 位用户未完成，请重发最新二维码；回复“跳过”可继续。\n"+
                          '\n'.join(t['name']+'：'+t['last_error'] for t in group['targets'][:8]))
                return
        else:
            if images or not re.fullmatch(r'[0-9]{1,8}',text) or not 1<=int(text)<=len(state['choices']):
                raise ValueError('位置请选择一个有效序号；回复“跳过”可继续')
            item = state['choices'][int(text)-1]
            reference = {'school':item['school'],'name':item['name']}
            point = resolve_point(self.store, self.owner, reference)
            if point is None or any(point.get(k)!=item.get(k) for k in ('longitude','latitude','address','coordinate_system')):
                raise ValueError('预设点位已被修改或删除，请重新发送“签到”')
            if not self.batch_submit(qq, state, {'kind':'location',**location_parameters(point),'location_preset':reference}):
                return
        self.batch_advance(qq, state)
