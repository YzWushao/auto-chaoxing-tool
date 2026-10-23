"""Explicit offline preview fixture. Reports are local; no platform requests."""
import json
import sys

from server.media import pace_media


def emit(kind, **fields):
    print(json.dumps({"type": kind, **fields}, ensure_ascii=False), flush=True)


spec = json.loads(sys.stdin.readline())
emit("log", message="离线界面验收：20 秒真实计时，不连接超星平台")


def update(**event):
    item = {"id": "offline-preview", "title": "20 秒计时演示（离线测试）", "course": spec["courses"][0]["title"], **event}
    completed = int(event["state"] == "completed")
    emit("progress", progress={"done": completed, "total": 1, "failed": 0, "skipped": 0,
                              "watch": {"elapsed_seconds": event["elapsed_seconds"], "completed": completed, "total": 1,
                                        "active": [] if completed else [item], "last": item}})


ok = pace_media(duration=20, start_position=0, speed=spec["study"]["speed"], report_interval=5,
                report=lambda *args: (True, 200), update=update)
emit("log", message="离线计时结束")
emit("finished", state="succeeded" if ok else "failed")
