"""Offline UI QA ONLY. Explicitly launched with `python -m tests.preview`.

This server uses fake platform responses; run.py never imports this module.
Test credentials are labels, not real platform credentials.
"""
import tempfile
import os
import subprocess
import base64
from types import SimpleNamespace
from unittest.mock import patch

from waitress import serve

from server.app import create_app
from server.chaoxing import PlatformError, CaptchaRequired
from tests.conftest import FakeClient


class PreviewClient(FakeClient):
    """Fake QR image/status for local UI checks; never contacts the platform."""

    def request(self, method, url, **kwargs):
        return SimpleNamespace(text='<input id="uuid" value="offline"><input id="enc" value="offline">',
                               content=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+cGOcAAAAASUVORK5CYII='),
                               headers={'Content-Type': 'image/png'}, json=lambda: {'status': False, 'type': '4'})

    @staticmethod
    def json(response):
        return response.json()

    def activities(self, courses):
        return [*super().activities(courses), {"id": "902", "title": "二维码签到（离线测试）", "kind": "qr",
                                              "course": courses[0], "photo": False, "start_time": None},
                {"id": "903", "title": "位置签到（离线测试）", "kind": "location",
                 "course": courses[0], "photo": False, "start_time": None},
                {"id": "904", "title": "滑块验证（离线测试）", "kind": "normal",
                 "course": courses[0], "photo": False, "start_time": None}]

    def sign(self, activity, supplied, name):
        if activity['id']=='904' and not supplied.get('_verification'):
            from tests.test_sign_verification import challenge
            raise CaptchaRequired(challenge(), 'offline-enc2')
        if 'EXPIRED_TEST_TOKEN' in str(supplied.get('qr', '')):
            raise PlatformError('签到未成功：二维码已过期（离线模拟）')
        return super().sign(activity, supplied, name)


if __name__ == "__main__":
    app = create_app({"DATA_DIR": os.getenv('AUTO_CHAOXING_PREVIEW_DATA_DIR') or tempfile.mkdtemp(prefix="auto-chaoxing-ui-test-"),
                      "SESSION_COOKIE_NAME": "ac_console_preview"}, PreviewClient)

    @app.after_request
    def mark_preview(response):
        if response.mimetype == "text/html":
            response.direct_passthrough = False
            response.set_data(response.get_data().replace(b"<title>", "<title>[离线测试] ".encode()))
        return response

    print("OFFLINE TEST PREVIEW ONLY: http://127.0.0.1:8766", flush=True)
    original_popen = subprocess.Popen

    def offline_worker(args, **kwargs):
        if args[-1] != "server.worker":
            raise RuntimeError("Preview must not launch an unexpected worker")
        return original_popen([*args[:-1], "tests.ui_media_worker"], **kwargs)

    from tests.test_sign_verification import challenge
    with patch("server.tasks.subprocess.Popen", offline_worker), patch('server.sign_captcha.check_challenge', lambda *args: 'offline-preview-proof'), patch('server.sign_captcha.create_challenge', lambda *args: challenge()):
        serve(app, host="127.0.0.1", port=8766, threads=4)
