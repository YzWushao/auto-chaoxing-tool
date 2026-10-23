import time

import pytest

from server.media import pace_media


class Clock:
    def __init__(self):
        self.seconds = 0.0
    def now(self):
        return self.seconds
    def sleep(self, seconds):
        self.seconds += seconds


def run_paced(duration=120, start=0, speed=1, passed=True, status=200):
    clock = Clock()
    reports, updates = [], []
    def report(position, phase):
        reports.append((clock.now(), position, phase))
        return passed, status
    success = pace_media(duration=duration, start_position=start, speed=speed,
                         report_interval=15, report=report, update=lambda **e: updates.append(e),
                         clock=clock.now, sleep=clock.sleep)
    return success, clock, reports, updates


@pytest.mark.parametrize("duration,start,speed,required", [(120, 0, 1, 120), (120, 0, 2, 60), (120, 50, 1, 70)])
def test_early_passed_never_skips_required_elapsed_time(duration, start, speed, required):
    success, clock, reports, updates = run_paced(duration, start, speed)
    assert success
    assert clock.now() >= required
    assert reports[0] == (0, start, "start")
    assert all(stamp >= required for stamp, _, phase in reports if phase == "end")
    assert all(position <= start + stamp * speed for stamp, position, _ in reports)
    assert len([r for r in reports if r[2] == "progress"]) >= 2
    assert updates[-1]["acknowledged"] is True
    assert updates[-1]["played_seconds"] == duration - start
    assert all(e["acknowledged"] is False for e in updates[:-1])


def test_completion_requires_platform_acknowledgement_after_wait():
    success, clock, reports, updates = run_paced(duration=10, passed=False)
    assert not success
    assert clock.now() >= 10
    assert [r[2] for r in reports].count("end") == 3
    assert updates[-1]["state"] == "error"
    assert not updates[-1]["acknowledged"]


def test_rejected_report_does_not_claim_elapsed_playback():
    success, clock, reports, updates = run_paced(status=403)
    assert not success
    assert clock.now() == 0
    assert updates[-1]["played_seconds"] == 0
    assert updates[-1]["state"] == "error"


def test_network_failure_and_stop_preserve_partial_time():
    clock = Clock()
    updates = []
    def report(position, phase):
        if phase == "progress":
            raise OSError("test connection closed")
        return True, 200
    with pytest.raises(OSError):
        pace_media(duration=120, start_position=0, speed=1, report_interval=5,
                   report=report, update=lambda **e: updates.append(e), clock=clock.now, sleep=clock.sleep)
    assert updates[-1]["state"] == "error"
    assert 0 < updates[-1]["position"] < 120
    assert not updates[-1]["acknowledged"]


def test_real_wall_clock_does_not_finish_instantly():
    started = time.monotonic()
    assert pace_media(duration=1, start_position=0, speed=1, report_interval=60,
                      report=lambda *args: (True, 200), update=lambda **event: None)
    assert time.monotonic() - started >= 1


@pytest.mark.parametrize("duration,start,speed", [(0, 0, 1), (float("nan"), 0, 1), (10, float("nan"), 1), (10, 0, 20)])
def test_invalid_timing_parameters(duration, start, speed):
    with pytest.raises(ValueError):
        run_paced(duration, start, speed)
