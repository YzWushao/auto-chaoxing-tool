from __future__ import annotations

import copy
import hmac
import importlib.util
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.exceptions import HTTPException

from .chaoxing import ChaoxingClient, PlatformError, QRLogin, SessionExpired
from .config import API_DEFAULTS, PROVIDERS, ROOT, VERSION, account_defaults, public_api, public_config, validate_api, validate_config
from .store import Store
from .tasks import ACTIVE, TaskManager


def create_app(config=None, client_factory=ChaoxingClient):
    app = Flask(__name__, static_folder=str(ROOT / "web"), static_url_path="/static")
    app.config.update(SECRET_KEY=None, MAX_CONTENT_LENGTH=1024 * 1024,
                      SESSION_COOKIE_NAME="ac_console", SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_SECURE=os.getenv("AUTO_CHAOXING_HTTPS") == "1",
                      PERMANENT_SESSION_LIFETIME=timedelta(days=30),
                      TRUSTED_HOSTS=os.getenv("AUTO_CHAOXING_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(","),
                      DATA_DIR=os.getenv("AUTO_CHAOXING_DATA_DIR", str(ROOT / "data")))
    if config:
        app.config.update(config)
    store = Store(app.config["DATA_DIR"])
    app.secret_key = store.session_key
    tasks = TaskManager(store)
    qr = QRLogin(client_factory)
    app.extensions.update(store=store, tasks=tasks, qr=qr)
    activities_cache = {}
    account_locks = defaultdict(threading.RLock)
    rate = defaultdict(deque)
    rate_lock = threading.Lock()

    @app.before_request
    def guard():
        if not request.path.startswith("/api/"):
            return
        session.permanent = True
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
            session["browser_id"] = secrets.token_urlsafe(24)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("Origin")
            if origin and urlsplit(origin).netloc != request.host:
                return jsonify(error="请求来源不匹配"), 403
            if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), session["csrf"]):
                return jsonify(error="页面会话已更新，请刷新页面"), 403
            if not request.is_json:
                return jsonify(error="请求需要 JSON 格式"), 415
        public = {"/api/session", "/api/auth/password", "/api/auth/qr", "/api/health"}
        if request.path not in public and not request.path.startswith("/api/auth/qr/") and not session.get("owner"):
            return jsonify(error="请先登录控制台"), 401

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(ValueError)
    def validation_error(exc):
        return jsonify(error=str(exc)[:250]), 400

    @app.errorhandler(KeyError)
    def missing_error(exc):
        return jsonify(error="记录不存在或不属于当前控制台"), 404

    @app.errorhandler(PlatformError)
    def platform_error(exc):
        return jsonify(error=str(exc)[:250], code="platform_error"), 502

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify(error=exc.name), exc.code

    def body():
        value = request.get_json()
        if not isinstance(value, dict):
            raise ValueError("请求内容需要为对象")
        return value

    def limit_login():
        key = request.remote_addr or "local"
        with rate_lock:
            bucket = rate[key]
            while bucket and bucket[0] < time.time() - 60:
                bucket.popleft()
            if len(bucket) >= 12:
                raise ValueError("登录请求过于频繁，请一分钟后再试")
            bucket.append(time.time())

    def account(account_id):
        result = store.account(session["owner"], account_id)
        if not result:
            raise KeyError(account_id)
        return result

    def public_account(value):
        return {k: v for k, v in value.items() if k not in {"owner", "cookies", "config", "phone"}} | {
            "phone": re.sub(r"(\d{3})\d+(\d{4})", r"\1****\2", value["phone"]), "config": public_config(value["config"])}

    def use_client(value, action):
        client = client_factory(value["cookies"])
        try:
            result = action(client)
            store.update_account(value["owner"], value["id"], cookies=client.cookies(), status="active")
            return result
        except SessionExpired:
            store.update_account(value["owner"], value["id"], status="expired")
            if value["status"] != "expired":
                store.event(value["owner"], value["id"], "login_expired", f"{value['name']} 登录已失效，请重新登录")
            raise

    def finish_login(client, profile):
        # The first verified platform identity owns this console workspace.
        # Adding accounts while authenticated does not change that ownership.
        owner = session.get("owner") or profile["uid"]
        session["owner"] = owner
        value = store.save_account(owner, profile, client.cookies(), account_defaults())
        store.event(owner, value["id"], "login_success", f"{value['name']} 登录成功")
        return {"account": public_account(value), "csrf": session["csrf"]}

    @app.get("/")
    def index():
        return send_from_directory(ROOT / "web", "index.html")

    @app.get("/legal/<document>")
    def legal(document):
        documents = {"license": ROOT / "LICENSE", "notice": ROOT / "NOTICE.md",
                     "sources": ROOT / "THIRD_PARTY.md", "sign-mit": ROOT / "licenses" / "chaoxing-sign-cli-MIT.txt"}
        path = documents.get(document)
        if path is None:
            raise KeyError(document)
        return send_from_directory(path.parent, path.name, mimetype="text/plain; charset=utf-8")

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", version=VERSION)

    @app.get("/api/session")
    def current_session():
        return jsonify(authenticated=bool(session.get("owner")), csrf=session["csrf"])

    @app.post("/api/auth/password")
    def login_password():
        limit_login()
        data = body()
        phone, password = str(data.get("phone", "")).strip(), data.get("password", "")
        if not re.fullmatch(r"\d{5,20}", phone) or not isinstance(password, str) or not 1 <= len(password) <= 200:
            raise ValueError("请填写有效手机号与密码")
        client = client_factory()
        profile = client.login_password(phone, password)
        return jsonify(finish_login(client, profile))

    @app.post("/api/auth/qr")
    def qr_create():
        limit_login()
        return jsonify(qr.create(session["browser_id"]))

    @app.post("/api/auth/qr/<token>/poll")
    def qr_poll(token):
        state, client = qr.poll(session["browser_id"], token)
        if client:
            return jsonify(state="confirmed", **finish_login(client, state["profile"]))
        return jsonify(state)

    @app.post("/api/auth/logout")
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/bootstrap")
    def bootstrap():
        settings = {"api": copy.deepcopy(API_DEFAULTS), **store.settings(session["owner"])}
        return jsonify(accounts=[public_account(a) for a in store.accounts(session["owner"])],
                       settings={"api": public_api(settings["api"])},
                       schema={"api": public_api(API_DEFAULTS), "providers": PROVIDERS},
                       jobs=tasks.jobs(session["owner"]), events=store.events(session["owner"]),
                       system={"version": VERSION, "ocr": importlib.util.find_spec("ddddocr") is not None},
                       integrations=[{"name": "NapCat", "state": "planned", "description": "获取签到二维码、辅助登录和状态消息"},
                                     {"name": "第三方推送", "state": "planned", "description": "登录失效、刷课完成、签到结果通知"}])

    @app.put("/api/settings")
    def settings_save():
        current = store.settings(session["owner"]).get("api", API_DEFAULTS)
        data = body()
        if set(data) != {"api"}:
            raise ValueError("需要提供 API 配置")
        value = validate_api(data["api"], current)
        store.set_settings(session["owner"], {"api": value})
        return jsonify(api=public_api(value))

    @app.put("/api/accounts/<account_id>/config")
    def account_config(account_id):
        value = account(account_id)
        config_value = validate_config(body(), value["config"])
        store.update_account(session["owner"], account_id, config=config_value)
        return jsonify(config=public_config(config_value))

    @app.delete("/api/accounts/<account_id>")
    def account_remove(account_id):
        account(account_id)
        if any(j["account_id"] == account_id and j["state"] in ACTIVE for j in tasks.jobs(session["owner"])):
            raise ValueError("请先停止该用户的刷课任务")
        with store.connect() as db:
            db.execute("DELETE FROM accounts WHERE owner=? AND id=?", (session["owner"], account_id))
        return jsonify(ok=True)

    @app.get("/api/accounts/<account_id>/courses")
    def courses(account_id):
        value = account(account_id)
        with account_locks[account_id]:
            return jsonify(courses=use_client(value, lambda client: client.courses()))

    @app.get("/api/accounts/<account_id>/activities")
    def activities(account_id):
        value = account(account_id)
        with account_locks[account_id]:
            result = use_client(value, lambda client: client.activities(client.courses()))
            activities_cache[(session["owner"], account_id)] = (time.time(), result)
            return jsonify(activities=[a | {"signed": store.signed(session["owner"], account_id, a["id"])} for a in result])

    @app.post("/api/accounts/<account_id>/sign")
    def sign(account_id):
        value, supplied = account(account_id), body()
        activity_id = str(supplied.get("activity_id", ""))
        with account_locks[account_id]:
            if store.signed(session["owner"], account_id, activity_id):
                return jsonify(message="该活动已签到，无需重复提交", duplicate=True)
            stamp, cached = activities_cache.get((session["owner"], account_id), (0, []))
            selected = next((a for a in cached if a["id"] == activity_id), None)
            if not selected or time.time() - stamp > 300:
                raise ValueError("活动列表已过期，请刷新后选择签到活动")
            def do_sign(client):
                live = next((a for a in client.activities([selected["course"]]) if a["id"] == activity_id), None)
                if not live:
                    raise ValueError("该签到活动已结束或不再可用")
                return client.sign(live, supplied, value["name"])
            message = use_client(value, do_sign)
            store.mark_signed(session["owner"], account_id, activity_id)
            store.event(session["owner"], account_id, "sign_success", selected["title"] + "：签到成功")
            return jsonify(message=message)

    @app.post("/api/accounts/<account_id>/study")
    def study(account_id):
        value = account(account_id)
        if not value["config"]["course_keys"]:
            raise ValueError("请先勾选课程并保存目标")
        courses_list = use_client(value, lambda client: client.courses())
        wanted = set(value["config"]["course_keys"])
        selected = [c for c in courses_list if c["key"] in wanted]
        if wanted - {c["key"] for c in selected}:
            raise ValueError("部分目标课程已不在当前账户中，请刷新课程并重新选择")
        if any(not c["cpi"] for c in selected):
            raise ValueError("课程缺少 cpi 参数，请刷新课程或更新接口适配器")
        api = store.settings(session["owner"]).get("api", API_DEFAULTS) if value["config"]["inherit_api"] else value["config"]["api"]
        # Refresh cookie snapshot after the server-side session check.
        value = account(account_id)
        return jsonify(job=tasks.start(session["owner"], value, api, selected)), 202

    @app.get("/api/jobs")
    def jobs():
        return jsonify(jobs=tasks.jobs(session["owner"]), events=store.events(session["owner"]),
                       accounts=[public_account(a) for a in store.accounts(session["owner"])])

    @app.get("/api/jobs/<job_id>/logs")
    def logs(job_id):
        return jsonify(logs=tasks.logs(session["owner"], job_id, int(request.args.get("after", 0))))

    @app.post("/api/jobs/<job_id>/stop")
    def stop(job_id):
        tasks.stop(session["owner"], job_id)
        return jsonify(ok=True)

    @app.post("/api/jobs/<job_id>/input")
    def answer(job_id):
        value = body().get("answer")
        if not isinstance(value, str) or len(value) > 10000:
            raise ValueError("请输入有效内容")
        tasks.answer(session["owner"], job_id, value)
        return jsonify(ok=True)

    return app
