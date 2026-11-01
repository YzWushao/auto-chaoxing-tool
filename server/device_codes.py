"""Persistent account-scoped device codes, independent of platform cookies.

Wire format / persistence reference: ChaoxingSignFaker, AGPL-3.0,
0346adf72dde1d3fea5600232c575ad2211641c3. No Android hardware proof is fabricated.
"""
import base64
import re
import secrets
from datetime import datetime, timezone


SOURCES = {'generated', 'manual', 'unified', 'browser', 'imported'}


def validate_device_code(value, allow_empty=False):
    if not isinstance(value, str):
        raise ValueError('设备码需要为文本')
    value = value.strip()
    if allow_empty and not value:
        return ''
    if not re.fullmatch(r'[A-Za-z0-9+/_=\-]{16,512}', value):
        raise ValueError('设备码需为 16～512 位字母、数字或 + / _ = -，不能填写链接或账号密码')
    return value


def random_device_code():
    data = secrets.token_bytes(32)
    return base64.b64encode(data + data).decode('ascii')


def record(code, source):
    return {'code': code, 'source': source, 'updated_at': datetime.now(timezone.utc).isoformat()}


class DeviceBindings:
    def device_settings(self, owner):
        with self.connect() as db:
            row = db.execute('SELECT value FROM device_settings WHERE owner=?', (owner,)).fetchone()
            return self.unseal(row['value']) if row else {'code': '', 'updated_at': None}

    def device_binding(self, owner, account_id):
        # A transaction ensures simultaneous first use never creates two codes.
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM accounts WHERE owner=? AND id=?', (owner, account_id)).fetchone():
                raise KeyError(account_id)
            row = db.execute('SELECT value FROM account_devices WHERE owner=? AND account_id=?', (owner, account_id)).fetchone()
            if row:
                return self.unseal(row['value'])
            admin = db.execute('SELECT owner FROM administrators WHERE id=1').fetchone()
            default = db.execute('SELECT value FROM device_settings WHERE owner=?', (admin['owner'],)).fetchone()
            code = self.unseal(default['value']).get('code', '') if default else ''
            value = record(code or random_device_code(), 'unified' if code else 'generated')
            db.execute('INSERT INTO account_devices VALUES (?,?,?)', (account_id, owner, self.seal(value)))
            return value

    def bind_device(self, owner, account_id, code=None, source='manual'):
        if not isinstance(source, str) or source not in SOURCES:
            raise ValueError('设备码来源无效')
        code = random_device_code() if source == 'generated' else validate_device_code(code)
        value = record(code, source)
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM accounts WHERE owner=? AND id=?', (owner, account_id)).fetchone():
                raise KeyError(account_id)
            db.execute('INSERT INTO account_devices VALUES (?,?,?) ON CONFLICT(account_id) DO UPDATE SET value=excluded.value',
                       (account_id, owner, self.seal(value)))
        return value

    def set_device_default(self, owner, code, apply_accounts=()):
        code = validate_device_code(code, allow_empty=True)
        if not code and apply_accounts:
            raise ValueError('统一绑定前请填写设备码；留空只能停用新账户的统一默认码')
        stamp = record(code, 'unified')['updated_at']
        settings = {'code': code, 'updated_at': stamp}
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO device_settings VALUES (?,?) ON CONFLICT(owner) DO UPDATE SET value=excluded.value',
                       (owner, self.seal(settings)))
            for account_owner, account_id in apply_accounts:
                if not db.execute('SELECT 1 FROM accounts WHERE owner=? AND id=?', (account_owner, account_id)).fetchone():
                    raise KeyError(account_id)
                value = {'code': code, 'source': 'unified', 'updated_at': stamp}
                db.execute('INSERT INTO account_devices VALUES (?,?,?) ON CONFLICT(account_id) DO UPDATE SET value=excluded.value',
                           (account_id, account_owner, self.seal(value)))
        return settings
