from __future__ import annotations

import json
import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet
from werkzeug.security import check_password_hash, generate_password_hash


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    """SQLite transactions + encrypted platform sessions and configuration."""

    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "console.sqlite3"
        self.lock = threading.RLock()
        key_path = self.directory / "secret.key"
        if not key_path.exists():
            try:
                with key_path.open("xb") as handle:
                    handle.write(Fernet.generate_key())
                os.chmod(key_path, 0o600)
            except FileExistsError:
                pass
        key = key_path.read_bytes()
        self.cipher = Fernet(key)
        self.session_key = key
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, uid TEXT NOT NULL,
                    name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
                    cookies TEXT NOT NULL, config TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, UNIQUE(owner, uid)
                );
                CREATE TABLE IF NOT EXISTS settings (owner TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, account_id TEXT NOT NULL,
                    state TEXT NOT NULL, progress TEXT NOT NULL, created_at TEXT NOT NULL,
                    finished_at TEXT, prompt TEXT
                );
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                    level TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL,
                    account_id TEXT, kind TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS signs (
                    owner TEXT NOT NULL, account_id TEXT NOT NULL, activity_id TEXT NOT NULL,
                    signed_at TEXT NOT NULL, PRIMARY KEY(owner, account_id, activity_id)
                );
                CREATE INDEX IF NOT EXISTS logs_job ON logs(job_id, id);
                CREATE INDEX IF NOT EXISTS events_owner ON events(owner, id);
                CREATE TABLE IF NOT EXISTS administrators (
                    id INTEGER PRIMARY KEY CHECK(id=1), username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL, owner TEXT NOT NULL,
                    default_password INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS admin_workspaces (
                    admin_id INTEGER NOT NULL, owner TEXT NOT NULL UNIQUE,
                    PRIMARY KEY(admin_id, owner)
                );
                CREATE TABLE IF NOT EXISTS admin_sessions (
                    token_hash TEXT PRIMARY KEY, admin_id INTEGER NOT NULL,
                    created_at REAL NOT NULL, expires_at REAL NOT NULL
                );
            """)
            # Claim legacy workspaces without rewriting accounts, IDs, or secrets.
            # Only the local administrator can access them after this upgrade.
            db.execute("BEGIN IMMEDIATE")
            admin = db.execute("SELECT id FROM administrators WHERE id=1").fetchone()
            if admin is None:
                owners = [r[0] for r in db.execute("SELECT owner FROM accounts GROUP BY owner ORDER BY COUNT(*) DESC, MIN(created_at)")]
                for table in ("settings", "jobs", "events", "signs"):
                    for row in db.execute(f"SELECT DISTINCT owner FROM {table}"):
                        if row[0] not in owners:
                            owners.append(row[0])
                primary = owners[0] if owners else "workspace:" + uuid.uuid4().hex
                db.execute("INSERT INTO administrators VALUES (1,?,?,?,?,?)",
                           ("admin", generate_password_hash("admin", method="scrypt"), primary, 1, now()))
                db.executemany("INSERT INTO admin_workspaces VALUES (1,?)", [(o,) for o in set([primary, *owners])])
            # A server restart never silently restarts an operation against a real account.
            db.execute("UPDATE jobs SET state='interrupted', finished_at=?, prompt=NULL WHERE state IN ('queued','running','waiting','stopping')", (now(),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def seal(self, value):
        return self.cipher.encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()

    def unseal(self, value):
        return json.loads(self.cipher.decrypt(value.encode()))

    def _public_admin(self, row):
        return {"id": row["id"], "username": row["username"], "owner": row["owner"],
                "default_password": bool(row["default_password"])}

    def managed_owners(self, admin_id):
        with self.connect() as db:
            return [r[0] for r in db.execute("SELECT owner FROM admin_workspaces WHERE admin_id=?", (admin_id,))]

    def authenticate_admin(self, username, password, lifetime=30 * 86400):
        with self.connect() as db:
            row = db.execute("SELECT * FROM administrators WHERE id=1").fetchone()
        valid_password = check_password_hash(row["password_hash"], password)
        if not hmac.compare_digest(row["username"].encode(), username.encode()) or not valid_password:
            return None
        token = secrets.token_urlsafe(32)
        stamp = time.time()
        with self.lock, self.connect() as db:
            # Do not issue a session against credentials changed during verification.
            current = db.execute("SELECT * FROM administrators WHERE id=1").fetchone()
            if current["password_hash"] != row["password_hash"] or current["username"] != username:
                return None
            db.execute("DELETE FROM admin_sessions WHERE expires_at<=?", (stamp,))
            db.execute("INSERT INTO admin_sessions VALUES (?,?,?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(), row["id"], stamp, stamp + lifetime))
        return token, self._public_admin(row)

    def admin_session(self, token):
        if not isinstance(token, str) or not token or len(token) > 200:
            return None
        with self.connect() as db:
            row = db.execute("SELECT a.* FROM administrators a JOIN admin_sessions s ON s.admin_id=a.id "
                             "WHERE s.token_hash=? AND s.expires_at>?",
                             (hashlib.sha256(token.encode()).hexdigest(), time.time())).fetchone()
        return self._public_admin(row) if row else None

    def revoke_admin_session(self, token):
        if isinstance(token, str):
            with self.connect() as db:
                db.execute("DELETE FROM admin_sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))

    def update_admin(self, admin_id, username, current_password, new_password=""):
        if not isinstance(username, str) or not 1 <= len(username.strip()) <= 64 or any(c.isspace() or ord(c) < 32 for c in username):
            raise ValueError("管理员名称需为 1–64 个非空白字符")
        if not isinstance(current_password, str) or not 1 <= len(current_password) <= 200:
            raise ValueError("请输入当前管理员密码")
        if not isinstance(new_password, str) or (new_password and (not 8 <= len(new_password) <= 200 or not new_password.strip())):
            raise ValueError("新管理员密码需为 8–200 个字符")
        with self.connect() as db:
            row = db.execute("SELECT * FROM administrators WHERE id=?", (admin_id,)).fetchone()
        if not row or not check_password_hash(row["password_hash"], current_password):
            raise ValueError("当前管理员密码不正确")
        password_hash = generate_password_hash(new_password, method="scrypt") if new_password else row["password_hash"]
        with self.lock, self.connect() as db:
            current = db.execute("SELECT * FROM administrators WHERE id=?", (admin_id,)).fetchone()
            if current["password_hash"] != row["password_hash"] or current["username"] != row["username"]:
                raise ValueError("管理员信息已更新，请重新登录后再试")
            db.execute("UPDATE administrators SET username=?,password_hash=?,default_password=?,updated_at=? WHERE id=?",
                       (username.strip(), password_hash, 0 if new_password else row["default_password"], now(), admin_id))
            db.execute("DELETE FROM admin_sessions WHERE admin_id=?", (admin_id,))

    def save_account(self, owner, profile, cookies, defaults):
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM accounts WHERE owner=? AND uid=?", (owner, profile["uid"])).fetchone()
            account_id = row["id"] if row else uuid.uuid4().hex
            stamp = now()
            if row:
                db.execute("UPDATE accounts SET name=?, phone=?, status='active', cookies=?, updated_at=? WHERE id=?",
                           (profile["name"], profile.get("phone") or row["phone"], self.seal(cookies), stamp, account_id))
            else:
                db.execute("INSERT INTO accounts VALUES (?,?,?,?,?,?,?,?,?,?)", (account_id, owner, profile["uid"], profile["name"], profile.get("phone", ""), "active", self.seal(cookies), self.seal(defaults), stamp, stamp))
        return self.account(owner, account_id)

    def _account(self, row):
        if not row:
            return None
        result = dict(row)
        result["cookies"] = self.unseal(result["cookies"])
        result["config"] = self.unseal(result["config"])
        return result

    def account(self, owner, account_id):
        with self.connect() as db:
            return self._account(db.execute("SELECT * FROM accounts WHERE id=? AND owner=?", (account_id, owner)).fetchone())

    def accounts(self, owner):
        with self.connect() as db:
            return [self._account(row) for row in db.execute("SELECT * FROM accounts WHERE owner=? ORDER BY created_at", (owner,))]

    def update_account(self, owner, account_id, *, config=None, cookies=None, status=None):
        parts, values = [], []
        for name, value in (("config", config), ("cookies", cookies), ("status", status)):
            if value is not None:
                parts.append(f"{name}=?")
                values.append(self.seal(value) if name in ("cookies", "config") else value)
        if not parts:
            return
        with self.connect() as db:
            db.execute(f"UPDATE accounts SET {','.join(parts)}, updated_at=? WHERE owner=? AND id=?", (*values, now(), owner, account_id))

    def settings(self, owner):
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE owner=?", (owner,)).fetchone()
            return self.unseal(row["value"]) if row else {}

    def set_settings(self, owner, value):
        with self.connect() as db:
            db.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(owner) DO UPDATE SET value=excluded.value", (owner, self.seal(value)))

    def event(self, owner, account_id, kind, message):
        with self.connect() as db:
            db.execute("INSERT INTO events(owner,account_id,kind,message,created_at) VALUES (?,?,?,?,?)", (owner, account_id, kind, message, now()))
            db.execute("DELETE FROM events WHERE owner=? AND id NOT IN (SELECT id FROM events WHERE owner=? ORDER BY id DESC LIMIT 500)", (owner, owner))

    def events(self, owner):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM events WHERE owner=? ORDER BY id DESC LIMIT 60", (owner,))]

    def signed(self, owner, account_id, activity_id):
        with self.connect() as db:
            return bool(db.execute("SELECT 1 FROM signs WHERE owner=? AND account_id=? AND activity_id=?", (owner, account_id, activity_id)).fetchone())

    def mark_signed(self, owner, account_id, activity_id):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO signs VALUES (?,?,?,?)", (owner, account_id, activity_id, now()))
