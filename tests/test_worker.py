import builtins
import copy
import enum
import io
import json
import sys
import types

import pytest

from server.config import API_DEFAULTS, STUDY_DEFAULTS
from server import worker


@pytest.mark.parametrize("mode, final, expected", [("complete", "succeeded", {"done": 2, "failed": 0, "skipped": 0}), ("unconfirmed", "partial", {"done": 0, "failed": 2, "skipped": 0}), ("stop", "partial", {"done": 0, "failed": 0, "skipped": 2}), ("failure", "partial", {"done": 0, "failed": 2, "skipped": 0}), ("duration-none", "partial", {"done": 2, "failed": 0, "skipped": 0}), ("duration-media", "succeeded", {"done": 2, "failed": 0, "skipped": 0})])
def test_worker_adapts_engine_and_verifies_progress(tmp_path, monkeypatch, mode, final, expected):
    class Result(enum.Enum):
        SUCCESS = 0
        NOT_OPEN = 1
        ERROR = 2
    class Client:
        def __init__(self):
            self.kwargs = {}
        def login(self, **kwargs):
            return {"status": True}
        def get_course_point(self, *args):
            return {"points": [{"id": str(i), "title": f"章节{i}", "has_finished": mode in {"complete", "duration-none", "duration-media"}} for i in range(2)]}
    calls = []
    def process(*args):
        calls.append(args)
        if mode == "duration-media":
            callback = args[0].kwargs["media_progress"]
            callback({"id": "media1", "state": "starting", "elapsed_seconds": 0, "played_seconds": 0})
            callback({"id": "media1", "state": "completed", "elapsed_seconds": 10, "played_seconds": 10})
        return Result.NOT_OPEN if mode == "stop" else Result.ERROR if mode == "failure" else Result.SUCCESS
    engine = types.ModuleType("main")
    engine.init_chaoxing = lambda *a: Client()
    engine.ChapterResult = Result
    engine.process_chapter = process
    engine.increase_learning_count_for_course = lambda *a: None
    api = types.ModuleType("api")
    api.__path__ = []
    cookies = types.ModuleType("api.cookies")
    fonts = types.ModuleType("api.cxsecret_font")
    logger_module = types.ModuleType("api.logger")
    logger_module.logger = types.SimpleNamespace(remove=lambda: None, add=lambda *a, **k: None)
    api.cookies, api.cxsecret_font, api.logger = cookies, fonts, logger_module
    for name, module in {"main": engine, "api": api, "api.cookies": cookies, "api.cxsecret_font": fonts, "api.logger": logger_module}.items():
        monkeypatch.setitem(sys.modules, name, module)
    output = io.StringIO()
    monkeypatch.setattr(worker, "wire", output)
    monkeypatch.setattr(worker.time, "sleep", lambda *a: None)
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"answer":"n"}\n'))
    # Register the original globals for restoration after run's process-local patches.
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(builtins, "input", builtins.input)
    monkeypatch.chdir(tmp_path)
    worker.run({"cookies": [], "api": copy.deepcopy(API_DEFAULTS), "study": {**STUDY_DEFAULTS, "notopen_action": "ask", "study_mode": "duration" if mode.startswith("duration-") else "task"}, "courses": [{"title": "测试课程", "courseId": "1", "clazzId": "2", "cpi": "3"}], "directory": str(tmp_path)})
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert events[-1] == {"type": "finished", "state": final}
    progress = [e["progress"] for e in events if e["type"] == "progress"][-1]
    for key, value in expected.items():
        assert progress[key] == value
    if mode == "stop":
        assert len(calls) == 1
    if mode == "duration-media":
        assert progress["watch"]["elapsed_seconds"] == 20
        assert progress["watch"]["completed"] == 1
