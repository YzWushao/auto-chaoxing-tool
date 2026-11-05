from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import uuid

from .config import ROOT, SECRET_FIELDS
from .store import now

ACTIVE = {"queued", "running", "waiting", "stopping"}


def redact(message, secrets=()):
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(message))
    for secret in sorted((s for s in secrets if isinstance(s, str) and len(s) >= 4), key=len, reverse=True):
        text = text.replace(secret, "[已隐藏]")
    text = re.sub(r"(?i)(cookie|authorization|password|api[_-]?key|vc3|_d|token)([\s'\"]*[:=][\s'\"]*)[^\s;,}\n]+", r"\1\2[已隐藏]", text)
    return text[:4000]


class TaskManager:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.running = {}

    def jobs(self, owner):
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM jobs WHERE owner=? ORDER BY created_at DESC LIMIT 50", (owner,))
            return [self._job(row) for row in rows]

    def _job(self, row):
        if not row:
            return None
        result = dict(row)
        result["progress"] = json.loads(result["progress"])
        return result

    def job(self, owner, job_id):
        with self.store.connect() as db:
            return self._job(db.execute("SELECT * FROM jobs WHERE owner=? AND id=?", (owner, job_id)).fetchone())

    def logs(self, owner, job_id, after=0):
        if not self.job(owner, job_id):
            raise KeyError("任务不存在")
        with self.store.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM logs WHERE job_id=? AND id>? ORDER BY id LIMIT 500", (job_id, after))]

    def log(self, job_id, message, level="info"):
        with self.store.connect() as db:
            db.execute("INSERT INTO logs(job_id,level,message,created_at) VALUES (?,?,?,?)", (job_id, level, message, now()))
            db.execute("DELETE FROM logs WHERE job_id=? AND id NOT IN (SELECT id FROM logs WHERE job_id=? ORDER BY id DESC LIMIT 2000)", (job_id, job_id))

    def start(self, owner, account, api, courses):
        with self.lock:
            if any(r["owner"] == owner and r["account"] == account["id"] for r in self.running.values()):
                raise ValueError("此用户已有运行中的任务")
            if len(self.running) >= 4:
                raise ValueError("最多同时运行四个用户的任务，请等待其他任务完成")
            job_id = uuid.uuid4().hex
            job_dir = self.store.directory / "jobs" / job_id
            job_dir.mkdir(parents=True)
            with self.store.connect() as db:
                db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)", (job_id, owner, account["id"], "queued", json.dumps({"done": 0, "total": 0, "failed": 0, "skipped": 0}), now(), None, None))
            spec = {"cookies": account["cookies"], "api": api, "study": account["config"]["study"],
                    "courses": courses, "directory": str(job_dir)}
            env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
            try:
                proc = subprocess.Popen([sys.executable, "-u", "-m", "server.worker"], cwd=ROOT,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                entry = {"process": proc, "owner": owner, "account": account["id"], "stopped": False,
                         "secrets": [c["value"] for c in account["cookies"]] + [api.get(k, "") for k in SECRET_FIELDS]}
                self.running[job_id] = entry
                with self.store.connect() as db:
                    db.execute("UPDATE jobs SET state='running' WHERE id=?", (job_id,))
                proc.stdin.write(json.dumps(spec, ensure_ascii=False) + "\n")
                proc.stdin.flush()
                threading.Thread(target=self._read, args=(job_id, entry), daemon=True).start()
            except Exception:
                if job_id in self.running:
                    self.running.pop(job_id)["process"].terminate()
                with self.store.connect() as db:
                    db.execute("UPDATE jobs SET state='failed',finished_at=? WHERE id=?", (now(), job_id))
                raise RuntimeError("启动刷课进程失败，请检查 Python 环境") from None
        self.store.event(owner, account["id"], "study_started", f"已启动 {len(courses)} 门课程的任务")
        return self.job(owner, job_id)

    def _read(self, job_id, entry):
        proc = entry["process"]
        final = None
        expired = False
        state = "failed"
        try:
            for line in proc.stdout:
                try:
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError()
                except ValueError:
                    self.log(job_id, redact(line.strip(), entry["secrets"]), "warning")
                    continue
                kind = event.get("type")
                if kind == "progress":
                    with self.store.connect() as db:
                        db.execute("UPDATE jobs SET progress=? WHERE id=?", (json.dumps(event["progress"]), job_id))
                elif kind == "input":
                    with self.store.connect() as db:
                        db.execute("UPDATE jobs SET state='waiting',prompt=? WHERE id=? AND state='running'", (redact(event.get("prompt", "请输入"), entry["secrets"]), job_id))
                elif kind == "finished":
                    if event.get("state") in {"succeeded", "partial", "failed"}:
                        final = event["state"]
                elif kind == "expired":
                    expired = True
                else:
                    message = redact(event.get("message", ""), entry["secrets"])
                    if message.strip():
                        self.log(job_id, message, event.get("level", "info"))
            code = proc.wait()
            state = "cancelled" if entry["stopped"] else (final or "failed") if code == 0 else "failed"
        except Exception:
            state = "failed"
            self.log(job_id, "任务进程连接中断", "error")
        finally:
            with self.lock:
                if entry["stopped"]:
                    state = "cancelled"
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                proc.stdout.close()
                proc.stdin.close()
                self.running.pop(job_id, None)
                with self.store.connect() as db:
                    db.execute("UPDATE jobs SET state=?, finished_at=?,prompt=NULL WHERE id=?", (state, now(), job_id))
            if expired:
                self.store.update_account(entry["owner"], entry["account"], status="expired")
                self.store.event(entry["owner"], entry["account"], "login_expired", "刷课会话已过期，请重新登录")
            labels = {"succeeded": "刷课完成", "partial": "刷课结束，部分章节未完成", "failed": "刷课失败，请查看日志", "cancelled": "刷课已停止"}
            self.store.event(entry["owner"], entry["account"], "study_" + state, labels[state])

    def stop(self, owner, job_id):
        with self.lock:
            entry = self.running.get(job_id)
            if not entry or entry["owner"] != owner:
                raise ValueError("任务已结束或不存在")
            entry["stopped"] = True
            with self.store.connect() as db:
                db.execute("UPDATE jobs SET state='stopping',prompt=NULL WHERE id=?", (job_id,))
            entry["process"].terminate()

    def answer(self, owner, job_id, value):
        with self.lock:
            entry = self.running.get(job_id)
            job = self.job(owner, job_id)
            if not entry or entry["owner"] != owner or not job or job["state"] != "waiting":
                raise ValueError("此任务当前没有等待输入")
            try:
                # Commit before unblocking the worker; it may immediately ask again.
                with self.store.connect() as db:
                    db.execute("UPDATE jobs SET state='running',prompt=NULL WHERE id=?", (job_id,))
                entry["process"].stdin.write(json.dumps({"answer": value}, ensure_ascii=False) + "\n")
                entry["process"].stdin.flush()
            except (OSError, ValueError):
                raise ValueError("任务已经结束") from None

    def shutdown(self):
        with self.lock:
            for entry in list(self.running.values()):
                entry["stopped"] = True
                if entry["process"].poll() is None:
                    entry["process"].terminate()
