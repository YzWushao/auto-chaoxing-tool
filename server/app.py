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

from flask import Flask, g, jsonify, request, send_from_directory, session
from werkzeug.exceptions import HTTPException, Unauthorized

from .chaoxing import ChaoxingClient, PlatformError, QRLogin, SessionExpired
from .config import API_DEFAULTS, PROVIDERS, ROOT, VERSION, account_defaults, public_api, public_config, validate_api, validate_config
from .store import Store
from .location_presets import validate_school, validate_import
from .maps import MapSearch
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
    map_search = MapSearch()
    app.extensions['map_search'] = map_search
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
        g.admin = store.admin_session(session.get("admin_sid"))
        g.owners = store.managed_owners(g.admin["id"]) if g.admin else []
        public = {"/api/session", "/api/admin/login", "/api/health"}
        if request.path not in public and not g.admin:
            return jsonify(error="请先使用管理员账号登录控制台"), 401

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        # OSM's tile policy requires a Referer; only the origin crosses sites.
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://tile.openstreetmap.org; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
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
        if not isinstance(account_id, str) or not 1 <= len(account_id) <= 128:
            raise ValueError("超星账户 ID 无效")
        for owner in g.owners:
            result = store.account(owner, account_id)
            if result:
                return result
        raise KeyError(account_id)

    def accounts():
        return sorted([a for owner in g.owners for a in store.accounts(owner)], key=lambda a: a["created_at"])

    def visible_jobs():
        return sorted([j for owner in g.owners for j in tasks.jobs(owner)], key=lambda j: j["created_at"], reverse=True)[:50]

    def visible_events():
        return sorted([e for owner in g.owners for e in store.events(owner)], key=lambda e: e["id"], reverse=True)[:60]

    def owned_job(job_id):
        for owner in g.owners:
            result = tasks.job(owner, job_id)
            if result:
                return result
        raise KeyError(job_id)

    def public_admin():
        return {k: g.admin[k] for k in ("username", "default_password")}

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

    def finish_login(client, profile, target_id=None):
        if not store.admin_session(session.get("admin_sid")):
            raise Unauthorized("管理员会话已失效，请重新登录")
        target = account(target_id) if target_id else next((a for a in accounts() if a["uid"] == profile["uid"]), None)
        if target and target["uid"] != profile["uid"]:
            raise ValueError("登录的超星账号与所选用户不一致，请使用原账号重新登录")
        owner = target["owner"] if target else g.admin["owner"]
        value = store.save_account(owner, profile, client.cookies(), account_defaults())
        store.event(owner, value["id"], "login_success", f"{value['name']} 登录成功")
        return {"account": public_account(value), "csrf": session["csrf"]}

    @app.get("/")
    def index():
        return send_from_directory(ROOT / "web", "index.html")

    @app.get("/legal/<document>")
    def legal(document):
        documents = {"license": ROOT / "LICENSE", "notice": ROOT / "NOTICE.md",
                     "sources": ROOT / "THIRD_PARTY.md", "sign-mit": ROOT / "licenses" / "chaoxing-sign-cli-MIT.txt",
                     "jsqr": ROOT / "licenses" / "jsqr-Apache-2.0.txt",
                     "leaflet": ROOT / "licenses" / "leaflet-BSD-2-Clause.txt",
                     "coordtransform": ROOT / "licenses" / "coordtransform-MIT.txt"}
        path = documents.get(document)
        if path is None:
            raise KeyError(document)
        return send_from_directory(path.parent, path.name, mimetype="text/plain; charset=utf-8")

    @app.get("/api/health")
    def health():
        return jsonify(status="ok", version=VERSION)

    @app.get("/api/session")
    def current_session():
        return jsonify(authenticated=bool(g.admin), csrf=session["csrf"], auth_mode="admin",
                       admin=public_admin() if g.admin else None)

    @app.post("/api/admin/login")
    def admin_login():
        limit_login()
        data = body()
        username, password = data.get("username", ""), data.get("password", "")
        if not isinstance(username, str) or not 1 <= len(username) <= 64 or not isinstance(password, str) or not 1 <= len(password) <= 200:
            raise ValueError("请输入管理员账号和密码")
        result = store.authenticate_admin(username, password)
        if not result:
            return jsonify(error="管理员账号或密码不正确"), 401
        qr.cancel_browser(session["browser_id"])
        store.revoke_admin_session(session.get("admin_sid"))
        token, admin = result
        session.clear()
        session.permanent = True
        session.update(admin_sid=token, csrf=secrets.token_urlsafe(32), browser_id=secrets.token_urlsafe(24))
        return jsonify(csrf=session["csrf"], admin={k: admin[k] for k in ("username", "default_password")})

    @app.put("/api/admin/credentials")
    def admin_credentials():
        limit_login()
        data = body()
        if set(data) - {"username", "current_password", "new_password"}:
            raise ValueError("管理员配置含未知字段")
        store.update_admin(g.admin["id"], data.get("username", g.admin["username"]),
                           data.get("current_password", ""), data.get("new_password", ""))
        qr.cancel_browser(session["browser_id"])
        session.clear()
        return jsonify(ok=True, reauthenticate=True)

    @app.post("/api/auth/password")
    def login_password():
        limit_login()
        data = body()
        phone, password = str(data.get("phone", "")).strip(), data.get("password", "")
        if not re.fullmatch(r"\d{5,20}", phone) or not isinstance(password, str) or not 1 <= len(password) <= 200:
            raise ValueError("请填写有效手机号与密码")
        client = client_factory()
        if data.get("account_id"):
            account(data["account_id"])
        profile = client.login_password(phone, password)
        return jsonify(finish_login(client, profile, data.get("account_id")))

    @app.post("/api/auth/qr")
    def qr_create():
        limit_login()
        result = qr.create(session["browser_id"])
        if not store.admin_session(session.get("admin_sid")):
            qr.cancel(session["browser_id"], result["id"])
            raise Unauthorized("管理员会话已失效，请重新登录")
        return jsonify(result)

    @app.post("/api/auth/qr/<token>/poll")
    def qr_poll(token):
        data = body()
        if data.get("account_id"):
            account(data["account_id"])
        state, client = qr.poll(session["browser_id"], token)
        if client:
            return jsonify(state="confirmed", **finish_login(client, state["profile"], data.get("account_id")))
        return jsonify(state)

    @app.post("/api/auth/qr/<token>/cancel")
    def qr_cancel(token):
        qr.cancel(session["browser_id"], token)
        return jsonify(ok=True)

    @app.post("/api/auth/logout")
    def logout():
        qr.cancel_browser(session["browser_id"])
        store.revoke_admin_session(session.get("admin_sid"))
        session.clear()
        return jsonify(ok=True)

    @app.get("/api/bootstrap")
    def bootstrap():
        settings = {"api": copy.deepcopy(API_DEFAULTS), **store.settings(g.admin["owner"])}
        return jsonify(admin=public_admin(), accounts=[public_account(a) for a in accounts()],
                       location_presets=store.location_presets(g.admin['owner']),
                       settings={"api": public_api(settings["api"])},
                       schema={"api": public_api(API_DEFAULTS), "providers": PROVIDERS},
                       jobs=visible_jobs(), events=visible_events(),
                       system={"version": VERSION, "ocr": importlib.util.find_spec("ddddocr") is not None},
                       integrations=[{"name": "NapCat", "state": "planned", "description": "获取签到二维码、辅助登录和状态消息"},
                                     {"name": "第三方推送", "state": "planned", "description": "登录失效、刷课完成、签到结果通知"}])

    @app.post('/api/map/search')
    def search_map():
        data = body()
        if set(data) != {'query'}:
            raise ValueError('需要提供地点名称')
        return jsonify(results=map_search.search(data['query']))

    @app.get('/api/location-presets')
    def location_presets():
        return jsonify(location_presets=store.location_presets(g.admin['owner']))

    @app.post('/api/location-presets')
    def location_presets_import():
        request.max_content_length = 16 * 1024 * 1024
        data = body()
        if set(data) - {'config', 'replace'} or not isinstance(data.get('replace', False), bool):
            raise ValueError('导入格式错误')
        values = validate_import(data.get('config'))
        store.import_location_presets(g.admin['owner'], values, data.get('replace', False))
        return jsonify(location_presets=store.location_presets(g.admin['owner']), schools=[v['school'] for v in values])

    @app.put('/api/location-presets/school')
    def location_school_save():
        data=body()
        if set(data)-{'name','original'} or not isinstance(data.get('name'),str) or not 1 <= len(data['name'].strip()) <= 100:
            raise ValueError('学校名称需要 1～100 个字符')
        original=data.get('original')
        if original is not None and (not isinstance(original,str) or not 1 <= len(original) <= 100):
            raise ValueError('原学校名称无效')
        store.save_location_school(g.admin['owner'],data['name'].strip(),original)
        return jsonify(location_presets=store.location_presets(g.admin['owner']))

    @app.delete('/api/location-presets/school')
    def location_school_delete():
        data=body()
        if set(data) != {'name'} or not isinstance(data['name'],str) or not 1 <= len(data['name']) <= 100:
            raise ValueError('需要学校名称')
        store.delete_location_school(g.admin['owner'],data['name'])
        return jsonify(location_presets=store.location_presets(g.admin['owner']))

    @app.put('/api/location-presets/point')
    def location_point_save():
        data = body()
        if set(data) - {'school','point','original'} or not isinstance(data.get('point'), dict):
            raise ValueError('点位格式错误')
        original = data.get('original')
        if original is not None and (not isinstance(original,dict) or set(original) != {'school','name'} or not all(isinstance(v,str) and v.strip() and len(v)<=100 for v in original.values())):
            raise ValueError('原点位标识无效')
        value = validate_school({'school':data.get('school'),'coordinate_system':data['point'].get('coordinate_system'),'points':[data['point']]})
        store.save_location_point(g.admin['owner'],value['school'],value['points'][0],original)
        return jsonify(location_presets=store.location_presets(g.admin['owner']))

    @app.delete('/api/location-presets/point')
    def location_point_delete():
        data = body()
        if set(data) != {'school','name'} or not all(isinstance(v,str) and v.strip() and len(v)<=100 for v in data.values()):
            raise ValueError('需要提供学校和点位名称')
        store.delete_location_point(g.admin['owner'],data['school'],data['name'])
        return jsonify(location_presets=store.location_presets(g.admin['owner']))

    @app.get('/api/location-presets/export')
    def location_presets_export():
        response = jsonify(version=1, schools=store.location_presets(g.admin['owner']))
        response.headers['Content-Disposition'] = 'attachment; filename="auto-chaoxing-locations.json"'
        return response

    @app.put("/api/settings")
    def settings_save():
        current = store.settings(g.admin["owner"]).get("api", API_DEFAULTS)
        data = body()
        if set(data) != {"api"}:
            raise ValueError("需要提供 API 配置")
        value = validate_api(data["api"], current)
        store.set_settings(g.admin["owner"], {"api": value})
        return jsonify(api=public_api(value))

    @app.put("/api/accounts/<account_id>/config")
    def account_config(account_id):
        value = account(account_id)
        config_value = validate_config(body(), value["config"])
        store.update_account(value["owner"], account_id, config=config_value)
        return jsonify(config=public_config(config_value))

    @app.delete("/api/accounts/<account_id>")
    def account_remove(account_id):
        value = account(account_id)
        if any(j["account_id"] == account_id and j["state"] in ACTIVE for j in tasks.jobs(value["owner"])):
            raise ValueError("请先停止该用户的刷课任务")
        with store.connect() as db:
            db.execute("DELETE FROM accounts WHERE owner=? AND id=?", (value["owner"], account_id))
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
            activities_cache[(value["owner"], account_id)] = (time.time(), result)
            return jsonify(activities=[a | {"signed": store.signed(value["owner"], account_id, a["id"])} for a in result])

    @app.post("/api/accounts/<account_id>/sign")
    def sign(account_id):
        value, supplied = account(account_id), body()
        activity_id = str(supplied.get("activity_id", ""))
        with account_locks[account_id]:
            if store.signed(value["owner"], account_id, activity_id):
                return jsonify(message="该活动已签到，无需重复提交", duplicate=True)
            stamp, cached = activities_cache.get((value["owner"], account_id), (0, []))
            selected = next((a for a in cached if a["id"] == activity_id), None)
            if not selected or time.time() - stamp > 300:
                raise ValueError("活动列表已过期，请刷新后选择签到活动")
            def do_sign(client):
                live = next((a for a in client.activities([selected["course"]]) if a["id"] == activity_id), None)
                if not live:
                    raise ValueError("该签到活动已结束或不再可用")
                return client.sign(live, supplied, value["name"])
            message = use_client(value, do_sign)
            store.mark_signed(value["owner"], account_id, activity_id)
            store.event(value["owner"], account_id, "sign_success", selected["title"] + "：签到成功")
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
        api = store.settings(g.admin["owner"]).get("api", API_DEFAULTS) if value["config"]["inherit_api"] else value["config"]["api"]
        # Refresh cookie snapshot after the server-side session check.
        value = account(account_id)
        return jsonify(job=tasks.start(value["owner"], value, api, selected)), 202

    @app.get("/api/jobs")
    def jobs():
        return jsonify(jobs=visible_jobs(), events=visible_events(), accounts=[public_account(a) for a in accounts()])

    @app.get("/api/jobs/<job_id>/logs")
    def logs(job_id):
        return jsonify(logs=tasks.logs(owned_job(job_id)["owner"], job_id, int(request.args.get("after", 0))))

    @app.post("/api/jobs/<job_id>/stop")
    def stop(job_id):
        tasks.stop(owned_job(job_id)["owner"], job_id)
        return jsonify(ok=True)

    @app.post("/api/jobs/<job_id>/input")
    def answer(job_id):
        value = body().get("answer")
        if not isinstance(value, str) or len(value) > 10000:
            raise ValueError("请输入有效内容")
        tasks.answer(owned_job(job_id)["owner"], job_id, value)
        return jsonify(ok=True)

    return app
