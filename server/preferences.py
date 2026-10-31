"""Display preferences never alter the account's real platform identity."""
import re
import math

DEFAULT_PREFERENCES = {'account_label': 'phone_tail', 'include_group_sign': False,
                       'camera_concurrency': 1, 'camera_scan_interval': 0.1}
LABEL_MODES = {'phone_tail', 'surname_mask', 'full_name', 'masked_surname', 'surname_tail'}
COMPOUND_SURNAMES = set('欧阳 司马 上官 诸葛 东方 皇甫 尉迟 公孙 慕容 司徒 司空 夏侯 令狐 宇文 长孙 轩辕 闻人 赫连 澹台 宗政 濮阳 公冶 太史 仲孙 申屠 端木 申公 南宫 万俟'.split())


def validate_preferences(data, current):
    if not isinstance(data, dict) or set(data)-set(DEFAULT_PREFERENCES):
        raise ValueError('显示与签到设置包含未知字段')
    value = {**DEFAULT_PREFERENCES, **current, **data}
    if not isinstance(value['account_label'], str) or value['account_label'] not in LABEL_MODES or type(value['include_group_sign']) is not bool:
        raise ValueError('用户显示方式或群聊签到开关无效')
    if type(value['camera_concurrency']) is not int or not 1 <= value['camera_concurrency'] <= 5:
        raise ValueError('扫码签到并发数需要是 1～5 的整数')
    interval = value['camera_scan_interval']
    if type(interval) not in (int, float) or not math.isfinite(interval) or not 0.05 <= interval <= 10:
        raise ValueError('两次识别间隔需要在 0.05～10 秒之间')
    return value


def account_label(value, mode='phone_tail'):
    name = str(value.get('name') or '').strip()
    phone = re.sub(r'\D', '', str(value.get('phone') or ''))
    uid = str(value.get('uid') or value.get('id') or '')[-4:]
    surname_length = 2 if name[:2] in COMPOUND_SURNAMES else min(1, len(name))
    surname, given = name[:surname_length], name[surname_length:]
    tail = phone[-4:] if len(phone) >= 4 else ''
    fallback = 'UID 尾号 ' + (uid or '未知')
    if mode == 'phone_tail':
        return '手机尾号 ' + tail if tail else fallback
    if mode == 'surname_tail':
        return surname + ' ' + tail if surname and tail else (surname+' · ' if surname else '')+fallback
    if not name:
        return fallback
    if mode == 'surname_mask':
        return surname + '*'*len(given)
    if mode == 'masked_surname':
        return '*'*surname_length + given
    return name
