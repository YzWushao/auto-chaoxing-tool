from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from server.config import ENGINE
from server import media
from tests.test_media import Clock


@pytest.fixture
def engine(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(ENGINE))
    import main
    import api.base
    import api.decode
    return SimpleNamespace(main=main, base=api.base, decode=api.decode)


@pytest.mark.parametrize("job_field", ["missing", True, None])
def test_completed_media_decoding_is_opt_in(engine, job_field):
    video = {"type": "video", "isPassed": True, "jobid": "v1", "mid": "m1", "objectId": "o1", "property": {"name": "已完成视频", "type": ".mp4"}}
    if job_field != "missing":
        video["job"] = job_field
    work = {"type": "workid", "isPassed": True, "job": True, "jobid": "exam1"}
    assert engine.decode._process_attachment_cards([video, work]) == []
    jobs = engine.decode._process_attachment_cards([video, work], include_completed_media=True)
    assert len(jobs) == 1 and jobs[0]["objectid"] == "o1"


def test_full_card_page_with_passed_video_without_job_marker(engine):
    # Sanitized structure verified against an authenticated, read-only response.
    # No platform identifiers, cookies or credentials are included in fixtures.
    import json
    card = {"aid": "test", "type": "video", "isPassed": True, "jobid": "v1", "mid": "m1", "objectId": "o1", "playTime": 120000,
            "property": {"name": "测试视频", "type": ".mp4", "_jobid": "v1", "module": "insertvideo"}}
    html = "<html><script>var mArg=" + json.dumps({"defaults": {"knowledgeid": "chapter1"}, "attachments": [card]}) + ";</script></html>"
    jobs, _ = engine.decode.decode_course_card(html, include_completed_media=True)
    assert len(jobs) == 1 and jobs[0]["type"] == "video" and jobs[0]["jobid"] == "v1"
    assert engine.decode.decode_course_card(html)[0] == []


def test_completed_chapter_replays_media_without_repeating_exam(engine, monkeypatch):
    video = {"type": "video", "jobid": "v1", "objectid": "o1"}
    jobs = [video, dict(video), {"type": "workid", "jobid": "exam1"}, {"type": "document", "jobid": "doc1"}]
    client = SimpleNamespace(kwargs={"replay_completed_media": True}, rate_limiter=SimpleNamespace(limit_rate=lambda **kw: None), get_job_list=lambda *a: (jobs, {}))
    calls = []
    monkeypatch.setattr(engine.main, "process_job", lambda _client, _course, job, *_: calls.append(job) or engine.base.StudyResult.SUCCESS)
    result = engine.main.process_chapter(client, {}, {"title": "已完成章节", "has_finished": True}, 1)
    assert result == engine.main.ChapterResult.SUCCESS
    assert calls == [video]
    client.kwargs = {}
    calls.clear()
    assert engine.main.process_chapter(client, {}, {"title": "已完成章节", "has_finished": True}, 1) == engine.main.ChapterResult.SUCCESS
    assert not calls


def test_timed_adapter_uses_real_engine_reporting_signature(engine, monkeypatch):
    clock = Clock()
    core = media.pace_media
    monkeypatch.setattr(media, "pace_media", lambda **kwargs: core(**kwargs, clock=clock.now, sleep=clock.sleep))
    monkeypatch.setattr(engine.base.SessionManager, "get_session", lambda: object())
    events, calls = [], []
    def report(*args, **kwargs):
        calls.append((clock.now(), args[6], kwargs["_isdrag"]))
        return True, 200  # The server says passed from the very first request.
    client = engine.base.Chaoxing()
    client.kwargs.update(replay_completed_media=True, media_progress=events.append)
    client._refresh_video_status = Mock(return_value={"duration": 20, "dtoken": "offline-fixture"})
    client.video_progress_log = report
    course = {"courseId": "1", "clazzId": "2", "title": "测试课程"}
    job = {"jobid": "v1", "objectid": "o1", "name": "视频", "playTime": 20000}
    result = media.timed_study_video(client, course, job, {"reportTimeInterval": 5}, _speed=1)
    assert result == engine.base.StudyResult.SUCCESS
    assert clock.now() == 20
    assert calls[0] == (0, 0, 0)
    assert calls[-1] == (20, 20, 4)
    assert events[-1]["acknowledged"] and events[-1]["elapsed_seconds"] == 20


def test_retried_media_resumes_without_double_waiting(engine, monkeypatch):
    clock = Clock()
    core = media.pace_media
    monkeypatch.setattr(media, "pace_media", lambda **kwargs: core(**kwargs, clock=clock.now, sleep=clock.sleep))
    monkeypatch.setattr(engine.base.SessionManager, "get_session", lambda: object())
    client = engine.base.Chaoxing()
    client.kwargs.update(replay_completed_media=True, media_progress=lambda event: None)
    client._refresh_video_status = Mock(return_value={"duration": 10, "dtoken": "offline-fixture"})
    client.video_progress_log = lambda *args, **kwargs: (False, 200)
    course, job = {"courseId": "1", "clazzId": "2", "title": "测试"}, {"jobid": "v1", "objectid": "o1", "name": "视频"}
    assert media.timed_study_video(client, course, job, {}) == engine.base.StudyResult.ERROR
    waited = clock.now()
    client.video_progress_log = lambda *args, **kwargs: (True, 200)
    assert media.timed_study_video(client, course, job, {}) == engine.base.StudyResult.SUCCESS
    assert clock.now() == waited
