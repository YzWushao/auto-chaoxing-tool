"""Subprocess fixture for TaskManager tests; not used by the application."""
import json
import sys
import time


def emit(kind, **fields):
    print(json.dumps({"type": kind, **fields}), flush=True)


spec = json.loads(sys.stdin.readline())
mode = spec["api"]["model"]
emit("log", message="vc3=" + spec["cookies"][-1]["value"])
if mode == "crash":
    sys.exit(1)
if mode == "expired":
    emit("expired")
    emit("finished", state="failed")
    sys.exit(1)
if mode == "wait":
    time.sleep(120)
if mode == "input":
    for i in range(2):
        emit("input", prompt=f"Question {i}")
        answer = json.loads(sys.stdin.readline())["answer"]
        emit("log", message="received: " + answer)
emit("progress", progress={"done": 2, "total": 2, "failed": 0, "skipped": 0})
emit("finished", state="succeeded")
