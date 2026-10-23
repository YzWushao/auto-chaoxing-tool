from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet


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
            """)
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
