"""Offline UI QA ONLY. Explicitly launched with `python -m tests.preview`.

This server uses fake platform responses; run.py never imports this module.
Test credentials are labels, not real platform credentials.
"""
import tempfile
import subprocess
from unittest.mock import patch

from waitress import serve

from server.app import create_app
from tests.conftest import FakeClient


if __name__ == "__main__":
    app = create_app({"DATA_DIR": tempfile.mkdtemp(prefix="auto-chaoxing-ui-test-")}, FakeClient)

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

    with patch("server.tasks.subprocess.Popen", offline_worker):
        serve(app, host="127.0.0.1", port=8766, threads=4)
