"""Paced media reporting: completion acknowledgements never replace elapsed time.

Counters describe this worker's actual elapsed runtime. Platform learning-time
accounting is separate and cannot be inferred from an `isPassed` response.

Reporting protocol adapted from Samueli924/chaoxing (GPL-3.0), commit
45d2106b16764231c2de2038fb042e71b23d878f, api/base.py. Modified 2026-10-23:
remove early end probes; pace reports with monotonic time and expose Web progress.
"""
import math
import time


def pace_media(*, duration, start_position, speed, report_interval, report, update,
               clock=None, sleep=None):
    """Advance position only with monotonic elapsed time, then require final ACK.

    report(position, phase) -> (is_passed, HTTP_status). All intermediate
    is_passed flags are deliberately ignored until the playback clock reaches
    the end. Injectable clocks let offline tests exercise full-length sessions.
    """
    clock = clock or time.monotonic
    sleep = sleep or time.sleep
    if not math.isfinite(duration) or duration <= 0 or not math.isfinite(start_position) or not 1 <= speed <= 2:
        raise ValueError("媒体时长或倍速无效")
    start_position = max(0.0, min(float(start_position), duration))
    try:
        interval = float(report_interval)
    except (ValueError, TypeError):
        interval = 60.0
    interval = max(5.0, min(interval if math.isfinite(interval) else 60.0, 120.0))
    started = clock()
    position = start_position
    last_report = started
    phase = "error"
    acknowledged = False

    def publish(state):
        update(state=state, position=round(position, 2), duration=duration,
               elapsed_seconds=round(max(0.0, clock() - started), 2), speed=speed,
               played_seconds=round(max(0.0, position - start_position), 2),
               acknowledged=acknowledged)

    publish("starting")
    try:
        # Start at the actual position; never probe with duration before waiting.
        _, status = report(int(position), "start")
        if status != 200:
            return False
        while True:
            tick = clock()
            position = min(duration, start_position + max(0.0, tick - started) * speed)
            publish("running")
            if position >= duration:
                break
            if tick - last_report >= interval:
                _, status = report(int(position), "progress")
                if status != 200:
                    return False
                last_report = clock()
            sleep(max(0.001, min(1.0, (duration - position) / speed)))
        # The end is reported only after the required real time has elapsed.
        for attempt in range(3):
            passed, status = report(int(duration), "end")
            if status != 200:
                return False
            if passed:
                acknowledged = True
                phase = "completed"
                return True
            if attempt < 2:
                sleep(2.0)
        return False
    finally:
        publish(phase)


def timed_study_video(self, course, job, job_info, _speed=1.0, _type="Video"):
    """Instance adapter for the original engine's media-reporting API."""
    from api.base import SessionManager, StudyResult
    from api.config import GlobalConst as gc
    from api.logger import logger

    session = SessionManager.get_session()
    headers = gc.VIDEO_HEADERS if _type == "Video" else gc.AUDIO_HEADERS
    info = self._refresh_video_status(session, job, _type)
    if not info or not info.get("dtoken") or not info.get("duration"):
        logger.error("未取得有效媒体信息，无法开始计时：{}", job.get("name", "未知媒体"))
        return StudyResult.ERROR
    duration = int(info["duration"])
    media_id = f"{course['courseId']}:{course['clazzId']}:{job.get('jobid', '')}:{job['objectid']}"
    callback = self.kwargs["media_progress"]
    resume = self.kwargs.setdefault("media_resume", {})
    initial = 0 if self.kwargs.get("replay_completed_media") else int(job.get("playTime", 0)) / 1000
    start_position = resume.get(media_id, initial)

    def update(**event):
        resume[media_id] = event["position"]
        callback({"id": media_id, "title": job.get("name", "音视频任务"), "course": course["title"], **event})

    def report(position, phase):
        passed, status = self.video_progress_log(session, course, job, job_info, info["dtoken"],
                                                 duration, position, _type,
                                                 _isdrag={"start": 0, "progress": 3, "end": 4}[phase], headers=headers)
        if status == 403:
            refreshed = self._recover_after_forbidden(session, job, _type)
            if refreshed and refreshed.get("dtoken") and int(refreshed.get("duration", 0)) == duration:
                info["dtoken"] = refreshed["dtoken"]
                passed, status = self.video_progress_log(session, course, job, job_info, info["dtoken"],
                                                         duration, position, _type, headers=headers,
                                                         _isdrag={"start": 0, "progress": 3, "end": 4}[phase])
        return passed, status

    logger.info("按时长运行：{}，媒体 {} 秒，从 {} 秒开始，{} 倍速", job.get("name"), duration, start_position, _speed)
    ok = pace_media(duration=duration, start_position=start_position, speed=_speed,
                    report_interval=job_info.get("reportTimeInterval", 60), report=report, update=update)
    if ok:
        logger.info("媒体计时完成，平台已确认任务点：{}；平台观看时长请以官方统计为准", job.get("name"))
        return StudyResult.SUCCESS
    logger.warning("媒体上报未获确认：{}", job.get("name"))
    return StudyResult.ERROR
