import base64
import time
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from server.chaoxing import ChaoxingClient, PlatformError, QRLogin, SessionExpired, encrypt_login, parse_courses


def response(text="", payload=None, url="https://mobilelearn.chaoxing.com/test"):
    return SimpleNamespace(text=text, url=url, json=lambda: payload, headers={"Content-Type": "image/jpeg"}, content=b"test-image")


def test_login_encryption_matches_aes_cbc():
    value = "13800000000密码"
    key = b"u2oh6Vu^HWe4_AES"
    decryptor = Cipher(algorithms.AES(key), modes.CBC(key)).decryptor()
    plain = decryptor.update(base64.b64decode(encrypt_login(value))) + decryptor.finalize()
    assert plain[:-plain[-1]].decode() == value


def test_parse_courses_keeps_classes_and_cpi():
    html = ''.join(f'<div class="course"><input class="courseId" value="1"><input class="clazzId" value="{n}"><a href="/course?cpi=99&amp;x=1"><span class="course-name" title="课程">name</span></a><p class="color3">教师</p></div>' for n in (2, 3))
    courses = parse_courses(html)
    assert [c["key"] for c in courses] == ["1:2", "1:3"]
    assert all(c["cpi"] == "99" for c in courses)


def test_activity_filters_all_not_only_first(monkeypatch):
    client = ChaoxingClient()
    data = {"data": {"activeList": [{"id": n, "status": status, "otherId": kind, "type": typ} for n, status, kind, typ in [(1, 2, 0, 2), (2, 1, 2, 2), (3, 1, 0, 1), (4, 1, 5, 2)]]}}
    monkeypatch.setattr(client, "request", lambda *a, **k: response(payload=data))
    found = client.activities([{"courseId": "1", "clazzId": "2"}])
    assert [(a["id"], a["kind"]) for a in found] == [("2", "qr"), ("4", "code")]


@pytest.mark.parametrize("kind, supplied, expected", [("normal", {}, None), ("qr", {"qr": "https://mobilelearn.chaoxing.com/?enc=abcdefgh12345"}, "enc"), ("gesture", {"code": "1234"}, "signCode"), ("code", {"code": "4321"}, "signCode"), ("location", {"latitude": 31.2, "longitude": 121.4, "address": "当前位置"}, "address"), ("photo", {"object_id": "imageObject123"}, "objectId")])
def test_sign_request_and_positive_ack_only(monkeypatch, kind, supplied, expected):
    client = ChaoxingClient()
    calls = []
    def request(*args, **kwargs):
        calls.append((args, kwargs))
        return response("success")
    monkeypatch.setattr(client, "request", request)
    activity = {"id": "1", "kind": kind, "course": {"courseId": "2", "clazzId": "3"}}
    assert client.sign(activity, supplied, "测试") == "签到成功"
    assert len(calls) == 2
    if expected:
        assert expected in calls[-1][1]["params"]
    monkeypatch.setattr(client, "request", lambda *a, **k: response("需要验证码"))
    with pytest.raises(PlatformError, match="签到未成功"):
        client.sign(activity, supplied, "测试")


@pytest.mark.parametrize("supplied", [{"latitude": "nan", "longitude": 0}, {"latitude": None, "longitude": 0}, {"latitude": 91, "longitude": 0}])
def test_location_invalid(supplied):
    with pytest.raises(ValueError):
        ChaoxingClient().sign({"kind": "location", "id": "1", "course": {}}, supplied, "测试")


def test_expiry_detection():
    with pytest.raises(SessionExpired):
        ChaoxingClient.check_login_page(response('<title>用户登录</title>'))


def test_qr_binding_expiry_and_confirmation():
    class QRClient:
        status = {"status": False, "type": "4"}
        def request(self, method, url, **kwargs):
            return response('<input id="uuid" value="test-uuid"><input id="enc" value="test-enc">', self.status)
        json = staticmethod(ChaoxingClient.json)
        def profile(self):
            return {"uid": "1", "name": "测试"}
    qr = QRLogin(QRClient)
    created = qr.create("browser-a")
    token = created["id"]
    with pytest.raises(ValueError):
        qr.poll("browser-b", token)
    assert qr.poll("browser-a", token)[0]["state"] == "scanned"
    qr.entries[token]["last_poll"] = 0
    QRClient.status = {"status": True}
    state, client = qr.poll("browser-a", token)
    assert state["state"] == "confirmed" and client is not None
    assert token not in qr.entries
    token = qr.create("browser-a")["id"]
    qr.entries[token]["expires"] = time.time() - 1
    assert qr.poll("browser-a", token)[0]["state"] == "expired"


def test_cancelling_qr_during_confirmation_never_returns_credentials():
    class Client:
        def request(self, method, url, **kwargs):
            return response('<input id="uuid" value="u"><input id="enc" value="e">', {"status": True})
        json = staticmethod(ChaoxingClient.json)
        def profile(self):
            qr.cancel_browser('browser-a')
            return {'uid': '1', 'name': '测试'}
    qr = QRLogin(Client)
    token = qr.create('browser-a')['id']
    state, client = qr.poll('browser-a', token)
    assert state == {'state': 'cancelled'}
    assert client is None
