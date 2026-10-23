"""Isolated study adapter; one process per account, a structured stdout protocol.

Only the initial stdin message carries credentials. No command-line arguments,
environment variables or plaintext config/cookie files carry these credentials.
"""
import builtins
import concurrent.futures
import json
import os
import sys
import threading
import time

from .config import ENGINE
from .tasks import redact

wire = sys.stdout
output_lock = threading.Lock()
input_lock = threading.Lock()
secret_values = []


def emit(kind, **value):
    with output_lock:
        wire.write(json.dumps({"type": kind, **value}, ensure_ascii=False) + "\n")
        wire.flush()


class Output:
    encoding = "utf-8"

    def write(self, message):
        if str(message).strip():
            emit("log", message=redact(message, secret_values))
        return len(message)

    def flush(self):
        pass

    def isatty(self):
        return False


def ask(prompt=""):
    with input_lock:
        emit("input", prompt=redact(prompt, secret_values))
        line = sys.stdin.readline()
        if not line:
            raise EOFError("控制台已断开")
        return str(json.loads(line)["answer"])


def run(spec):
    global secret_values
    secret_values = [c["value"] for c in spec["cookies"]]
    secret_values += [v for k, v in spec["api"].items() if k in {"tokens", "key", "siliconflow_key", "go_authorization"} and v]
    os.chdir(spec["directory"])
    sys.path.insert(0, str(ENGINE))
    sys.stdout = sys.stderr = Output()
    builtins.input = ask
    from api.logger import logger
    logger.remove()
    logger.add(lambda message: emit("log", level=message.record["level"].name.lower(), message=redact(message.record["message"], secret_values)), level="INFO")
    import api.cookies as cookie_module
    memory_cookies = {c["name"]: c["value"] for c in spec["cookies"]}
    cookie_module.use_cookies = lambda: dict(memory_cookies)
    cookie_module.save_cookies = lambda session: memory_cookies.update(session.cookies.get_dict())
    import api.cxsecret_font as fonts
    fonts.resource_path = lambda relative: str(ENGINE / relative)
    import main as engine
    common = {**spec["study"], "use_cookies": True, "username": "", "password": ""}
    client = engine.init_chaoxing(common, spec["api"])
    if not client.login(login_with_cookies=True).get("status"):
        emit("expired")
        raise RuntimeError("登录已失效，请重新登录")
    courses = spec["courses"]
    if not courses:
        raise ValueError("未选择课程，任务不会启动")
    progress = {"done": 0, "total": 0, "failed": 0, "skipped": 0}
    progress_lock = threading.Lock()
    course_points = []
    for course in courses:
        emit("log", message="读取课程章节：" + course["title"])
        points = client.get_course_point(course["courseId"], course["clazzId"], course["cpi"])["points"]
        course_points.append((course, points))
        progress["total"] += len(points)
    emit("progress", progress=progress)

    def process_course(course, points):
        completed = []
        course_ok = True
        for index, point in enumerate(points):
            outcome = "failed"
            for attempt in range(3):
                try:
                    result = engine.process_chapter(client, course, point, common["speed"])
                    if result == engine.ChapterResult.SUCCESS:
                        outcome = "done"
                        break
                    if result == engine.ChapterResult.NOT_OPEN:
                        action = common["notopen_action"]
                        if action == "continue" or (action == "ask" and ask(f"章节 {point['title']} 未开放，输入 y 跳过，其他输入停止本课程：").lower() == "y"):
                            outcome = "skipped"
                            break
                        if action == "ask":
                            emit("log", level="warning", message="已停止此课程，剩余章节记为跳过")
                            with progress_lock:
                                progress["skipped"] += len(points) - index
                                emit("progress", progress=dict(progress))
                            return
                except Exception as exc:
                    emit("log", level="error", message=redact(f"章节 {point['title']}：{type(exc).__name__}: {exc}", secret_values))
                if attempt < 2:
                    time.sleep(common["retry_interval"])
            with progress_lock:
                progress[outcome] += 1
                emit("progress", progress=dict(progress))
            if outcome == "done":
                completed.append(str(point["id"]))
            else:
                course_ok = False
        # A handled chapter is not necessarily complete (e.g. answers only saved).
        # Re-read platform progress before reporting success to the dashboard.
        latest = client.get_course_point(course["courseId"], course["clazzId"], course["cpi"])["points"]
        confirmed = {str(p["id"]) for p in latest if p.get("has_finished") or (str(p.get("jobCount")) == "0" and not p.get("need_unlock"))}
        unconfirmed = len(set(completed) - confirmed)
        if unconfirmed:
            course_ok = False
            emit("log", level="warning", message=f"{course['title']} 有 {unconfirmed} 个章节尚未被平台确认完成，请在官方页面核对")
            with progress_lock:
                progress["done"] -= unconfirmed
                progress["failed"] += unconfirmed
                emit("progress", progress=dict(progress))
        if common["add_learning_count"] and course_ok and points:
            engine.increase_learning_count_for_course(client, course, common)

    # Preserve chapter ordering within each course so locked chapters can unlock.
    # Separate courses can run concurrently; the Web UI labels this explicitly.
    with concurrent.futures.ThreadPoolExecutor(max_workers=common["jobs"]) as executor:
        futures = [executor.submit(process_course, course, points) for course, points in course_points]
        for future in concurrent.futures.as_completed(futures):
            future.result()
    if not progress["total"]:
        emit("log", level="warning", message="所选课程未返回章节，无法确认任务完成")
        state = "partial"
    else:
        state = "partial" if progress["failed"] or progress["skipped"] else "succeeded"
    emit("finished", state=state)


if __name__ == "__main__":
    try:
        run(json.loads(sys.stdin.readline()))
    except BaseException as exc:
        emit("log", level="error", message=redact(f"{type(exc).__name__}: {exc}", secret_values))
        emit("finished", state="failed")
        sys.exit(1)
