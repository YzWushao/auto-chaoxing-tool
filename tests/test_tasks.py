import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from server.config import API_DEFAULTS, account_defaults
from server.store import Store
from server.tasks import TaskManager, redact


def wait_until(predicate, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.03)
    raise AssertionError("Timed out waiting for subprocess state")


@pytest.fixture
def manager(tmp_path, monkeypatch):
    original = subprocess.Popen
    fixture = Path(__file__).with_name("protocol_worker.py")
    def launch(args, **kwargs):
        return original([sys.executable, "-u", str(fixture)], **kwargs)
    monkeypatch.setattr("server.tasks.subprocess.Popen", launch)
    store = Store(tmp_path)
    tasks = TaskManager(store)
    account = store.save_account("owner", {"uid": "1", "name": "离线测试"}, [{"name": "vc3", "value": "sensitive-test-cookie"}], account_defaults())
    yield tasks, account
    tasks.shutdown()
    wait_until(lambda: not tasks.running)


@pytest.mark.parametrize("mode, expected", [("success", "succeeded"), ("crash", "failed"), ("expired", "failed")])
def test_process_results_and_secrets(manager, mode, expected):
    tasks, account = manager
    job = tasks.start("owner", account, {**API_DEFAULTS, "model": mode}, [{"title": "测试"}])
    wait_until(lambda: tasks.job("owner", job["id"])["finished_at"])
    assert tasks.job("owner", job["id"])["state"] == expected
    assert "sensitive-test-cookie" not in json.dumps(tasks.logs("owner", job["id"]))
    assert not list(tasks.store.directory.rglob("cookies.txt"))
    with pytest.raises(KeyError):
        tasks.logs("other", job["id"])
    if mode == "expired":
        wait_until(lambda: tasks.store.account("owner", account["id"])["status"] == "expired")


def test_manual_input_can_ask_twice_without_race(manager):
    tasks, account = manager
    job = tasks.start("owner", account, {**API_DEFAULTS, "model": "input"}, [])
    for i in range(2):
        wait_until(lambda: tasks.job("owner", job["id"])["prompt"] == f"Question {i}")
        with pytest.raises(ValueError):
            tasks.answer("other", job["id"], "bad")
        tasks.answer("owner", job["id"], "A")
    wait_until(lambda: tasks.job("owner", job["id"])["state"] == "succeeded")


def test_cancel_and_one_job_per_account(manager):
    tasks, account = manager
    job = tasks.start("owner", account, {**API_DEFAULTS, "model": "wait"}, [])
    with pytest.raises(ValueError):
        tasks.start("owner", account, API_DEFAULTS, [])
    with pytest.raises(ValueError):
        tasks.stop("other", job["id"])
    tasks.stop("owner", job["id"])
    wait_until(lambda: tasks.job("owner", job["id"])["state"] == "cancelled")


def test_store_recovers_interrupted_jobs(tmp_path):
    store = Store(tmp_path)
    with store.connect() as db:
        db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)", ("id", "owner", "account", "running", "{}", "now", None, "input"))
    store = Store(tmp_path)
    assert TaskManager(store).job("owner", "id")["state"] == "interrupted"


def test_redaction():
    assert "top-secret" not in redact("token=top-secret password='top-secret'", ["top-secret"])


def test_clear_history_logs_requires_confirmation_and_preserves_active_and_foreign_jobs(app,browser):
    assert browser.send('/logs/history',{'confirm':True},'DELETE').status_code==401
    browser.admin_login()
    store=app.extensions['store']
    owner=store.administrator()['owner']
    with store.connect() as db:
        for job_id,job_owner,state in [('old',owner,'succeeded'),('active',owner,'running'),('foreign','outside','failed')]:
            db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)',
                       (job_id,job_owner,'account',state,'{}','now',None,None))
            db.execute('INSERT INTO logs(job_id,level,message,created_at) VALUES (?,?,?,?)',
                       (job_id,'info','historical entry','now'))
    for invalid in [{},{'confirm':False},{'confirm':1},{'confirm':True,'owner':'outside'}]:
        assert browser.send('/logs/history',invalid,'DELETE').status_code==400
    assert browser.client.delete('/api/logs/history',json={'confirm':True}).status_code==403
    result=browser.send('/logs/history',{'confirm':True},'DELETE')
    assert result.status_code==200 and result.json['deleted']==1
    with store.connect() as db:
        assert {row[0] for row in db.execute('SELECT job_id FROM logs')}=={'active','foreign'}
        assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==3
    assert browser.send('/logs/history',{'confirm':True},'DELETE').json['deleted']==0
