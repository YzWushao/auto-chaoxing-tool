import json

import pytest

from server.config import MASK
from tests.conftest import Browser, FakeClient


def test_guards_and_headers(app, browser):
    assert browser.get("/bootstrap").status_code == 401
    assert browser.client.post("/api/auth/password", json={}).status_code == 403
    assert browser.client.post("/api/auth/password", json={}, headers={"X-CSRF-Token": browser.csrf, "Origin": "https://evil.example"}).status_code == 403
    assert browser.client.get("/api/session", headers={"Host": "evil.example"}).status_code == 400
    response = browser.client.get("/")
    assert response.status_code == 200
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert browser.get("/session").headers["Cache-Control"] == "no-store"
    for path in ("license", "sources", "notice", "sign-mit"):
        assert browser.client.get("/legal/" + path).status_code == 200
    assert browser.client.get("/legal/not-a-file").status_code == 404


def test_multiple_accounts_require_administrator(app, browser):
    first = browser.login()
    second = browser.login("13800000002")
    assert len(browser.get("/bootstrap").json["accounts"]) == 2
    outsider = Browser(app)
    assert outsider.send("/auth/password", {"phone": "13800000003", "password": "fixture-password"}).status_code == 401
    for suffix in ("/courses", "/activities"):
        assert outsider.get(f"/accounts/{first['id']}" + suffix).status_code == 401
    assert outsider.send(f"/accounts/{first['id']}/config", {}, "PUT").status_code == 401
    assert outsider.send(f"/accounts/{second['id']}", {}, "DELETE").status_code == 401
    # The same administrator, not a platform identity, owns the console.
    secondary = Browser(app)
    secondary.admin_login()
    assert len(secondary.get("/bootstrap").json["accounts"]) == 2


def test_encrypted_storage_and_masked_updates(app, browser):
    account = browser.login()
    response = browser.send("/settings", {"api": {"provider": "AI", "key": "secret-global-key", "endpoint": "https://example.invalid/v1", "model": "test-model"}}, "PUT")
    assert response.json["api"]["key"] == MASK
    browser.send("/settings", {"api": {"key": MASK, "model": "updated"}}, "PUT")
    store = app.extensions["store"]
    assert store.settings(store.managed_owners(1)[0])["api"]["key"] == "secret-global-key"
    visible = json.dumps(browser.get("/bootstrap").json)
    assert "secret-global-key" not in visible and "private-session-fixture" not in visible
    with store.connect() as db:
        raw = " ".join(str(tuple(r)) for r in db.execute("SELECT * FROM accounts"))
        raw += " ".join(str(tuple(r)) for r in db.execute("SELECT * FROM settings"))
    for secret in ("secret-global-key", "private-session-fixture", "fixture-password"):
        assert secret not in raw
    browser.send("/settings", {"api": {"key": ""}}, "PUT")
    assert store.settings(store.managed_owners(1)[0])["api"]["key"] == ""


def test_config_targets_and_api_inheritance(app, browser, monkeypatch):
    account = browser.login()
    path = f"/accounts/{account['id']}"
    captured = []
    monkeypatch.setattr(app.extensions["tasks"], "start", lambda owner, account, api, courses: captured.append((account, api, courses)) or {"id": "offline"})
    assert browser.send(path + "/study").status_code == 400
    browser.send(path + "/config", {"course_keys": ["missing:class"]}, "PUT")
    assert browser.send(path + "/study").status_code == 400
    assert not captured
    browser.send("/settings", {"api": {"model": "global", "key": "global-secret"}}, "PUT")
    browser.send(path + "/config", {"course_keys": ["101:201"], "api": {"model": "local", "key": "local-secret"}}, "PUT")
    assert browser.send(path + "/study").status_code == 202
    assert captured[-1][1]["model"] == "global"
    assert [c["key"] for c in captured[-1][2]] == ["101:201"]
    browser.send(path + "/config", {"inherit_api": False}, "PUT")
    assert browser.send(path + "/study").status_code == 202
    assert captured[-1][1]["key"] == "local-secret"
    repeated = browser.login()
    assert repeated["id"] == account["id"]
    assert repeated["config"]["course_keys"] == ["101:201"]
    assert repeated["config"]["inherit_api"] is False


@pytest.mark.parametrize("changes", [{"study": {"speed": 100}}, {"study": {"speed": None}}, {"study": {"jobs": True}}, {"study": {"jobs": 1.5}}, {"study": {"retry_interval": "nan"}}, {"study": {"alien": 1}}, {"inherit_api": "yes"}, {"course_keys": "101"}, {"api": {"endpoint": "file:///tmp"}}, {"api": {"provider": "unknown"}}, {"api": {"cover_rate": 2}}, {"owner": "other"}])
def test_reject_invalid_configuration(browser, changes):
    account = browser.login()
    assert browser.send(f"/accounts/{account['id']}/config", changes, "PUT").status_code == 400


def test_sign_requires_owned_current_activity_and_deduplicates(browser):
    account = browser.login()
    path = f"/accounts/{account['id']}"
    assert browser.send(path + "/sign", {"activity_id": "901"}).status_code == 400
    assert browser.get(path + "/activities").status_code == 200
    assert browser.send(path + "/sign", {"activity_id": "902"}).status_code == 400
    assert browser.send(path + "/sign", {"activity_id": "901"}).status_code == 200
    duplicate = browser.send(path + "/sign", {"activity_id": "901"})
    assert duplicate.json["duplicate"] is True
    assert FakeClient.sign_calls == 1
    assert browser.get(path + "/activities").json["activities"][0]["signed"] is True


def test_expiry_relogin_and_logout(browser):
    account = browser.login()
    FakeClient.expired = True
    assert browser.get(f"/accounts/{account['id']}/courses").status_code == 502
    assert browser.get("/bootstrap").json["accounts"][0]["status"] == "expired"
    assert any(e["kind"] == "login_expired" for e in browser.get("/bootstrap").json["events"])
    FakeClient.expired = False
    browser.login()
    assert browser.get("/bootstrap").json["accounts"][0]["status"] == "active"
    browser.send("/auth/logout")
    assert browser.get("/bootstrap").status_code == 401
