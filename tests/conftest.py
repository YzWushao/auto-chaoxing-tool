import copy

import pytest

from server.app import create_app
from server.chaoxing import SessionExpired


class FakeClient:
    """In-memory platform fixture. Never contacts Chaoxing."""

    expired = False
    sign_calls = 0

    def __init__(self, cookies=None):
        self.jar = copy.deepcopy(cookies or [])

    def login_password(self, phone, password):
        self.jar = [{"name": "_uid", "value": phone, "domain": ".chaoxing.com", "path": "/"},
                    {"name": "vc3", "value": "private-session-fixture", "domain": ".chaoxing.com", "path": "/"}]
        return {"uid": phone, "name": "测试用户" + phone[-4:], "phone": phone}

    def cookies(self):
        return self.jar

    def courses(self):
        if self.expired:
            raise SessionExpired("登录失效")
        return [{"key": "101:201", "courseId": "101", "clazzId": "201", "cpi": "301", "title": "计算机基础（测试）", "teacher": "测试教师"},
                {"key": "102:202", "courseId": "102", "clazzId": "202", "cpi": "302", "title": "大学英语（测试）", "teacher": "测试教师"}]

    def activities(self, courses):
        return [{"id": "901", "title": "课堂签到（测试）", "kind": "normal", "course": courses[0], "photo": False, "start_time": None}]

    def sign(self, activity, supplied, name):
        type(self).sign_calls += 1
        return "签到成功（离线测试）"

    def sign_requirements(self, activity):
        return {'phase': activity.get('phase', 'in'), 'needs_face': False, 'needs_location': False, 'needs_captcha': False,
                'sign_in_id': None, 'sign_out_id': None, 'sign_out_publish_at': None, 'photo': False,
                'official_url': 'https://mobilelearn.chaoxing.com/newsign/preSign?activePrimaryId='+activity['id']}

    def sign_confirmed(self, activity):
        return False


@pytest.fixture
def app(tmp_path):
    FakeClient.expired = False
    FakeClient.sign_calls = 0
    application = create_app({"TESTING": True, "DATA_DIR": tmp_path}, FakeClient)
    yield application
    application.extensions["tasks"].shutdown()


class Browser:
    def __init__(self, app):
        self.client = app.test_client()
        self.csrf = self.client.get("/api/session").json["csrf"]

    def get(self, path):
        return self.client.get("/api" + path)

    def send(self, path, data=None, method="POST"):
        return self.client.open("/api" + path, method=method, json={} if data is None else data,
                                headers={"X-CSRF-Token": self.csrf, "Origin": "http://localhost"})

    def login(self, phone="13800000001"):
        if not self.get("/session").json["authenticated"]:
            self.admin_login()
        response = self.send("/auth/password", {"phone": phone, "password": "fixture-password"})
        assert response.status_code == 200, response.json
        return response.json["account"]

    def admin_login(self, username="admin", password="admin"):
        response = self.send("/admin/login", {"username": username, "password": password})
        if response.status_code == 200:
            self.csrf = response.json["csrf"]
        return response


@pytest.fixture
def browser(app):
    return Browser(app)
