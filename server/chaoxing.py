"""Platform adapters. HTTPS only; sessions are passed in per account, never global.

Sign-in flows reference Yink-Design/chaoxing-sign-cli (MIT), commit
4084545e2f00e5297693776ac5c8fccc809c07ca. Python adaptation: 2026-10-23.
Original copyright (c) 2021 miaochenxi; see licenses/chaoxing-sign-cli-MIT.txt.
"""
from __future__ import annotations

import base64
import re
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit

import pyaes
import requests
from bs4 import BeautifulSoup


class PlatformError(Exception):
    pass


class SessionExpired(PlatformError):
    pass


def encrypt_login(value):
    key = b"u2oh6Vu^HWe4_AES"
    data = value.encode("utf-8")
    padding = 16 - len(data) % 16
    data += bytes([padding]) * padding
    cipher = pyaes.AESModeOfOperationCBC(key, iv=key)
    return base64.b64encode(b"".join(cipher.encrypt(data[i:i + 16]) for i in range(0, len(data), 16))).decode()


def serialize_cookies(jar):
    return [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path,
             "secure": c.secure, "expires": c.expires} for c in jar]


def parse_courses(html):
    soup = BeautifulSoup(html, "html.parser")
    result = []
    for item in soup.select("div.course"):
        if item.select_one(".not-open-tip"):
            continue
        def input_value(css):
            tag = item.select_one(css)
            return tag.get("value", "") if tag else ""
        course_id, clazz_id = input_value("input.courseId"), input_value("input.clazzId")
        if not course_id or not clazz_id:
            continue
        link = item.select_one("a[href*='cpi=']") or item.select_one("a[href]")
        query = parse_qs(urlsplit(link.get("href", "") if link else "").query)
        title = item.select_one(".course-name")
        teacher = item.select_one("p.color3")
        result.append({"key": f"{course_id}:{clazz_id}", "courseId": course_id,
                       "clazzId": clazz_id, "cpi": query.get("cpi", [""])[0],
                       "title": (title.get("title") or title.get_text(strip=True)) if title else course_id,
                       "teacher": (teacher.get("title") or teacher.get_text(strip=True)) if teacher else ""})
    return result


class ChaoxingClient:
    COURSE_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
    INTERACTION = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction"
    SIGN_BASE = "https://mobilelearn.chaoxing.com"

    def __init__(self, cookies=None):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Referer": self.INTERACTION,
        })
        for cookie in cookies or []:
            domain = cookie.get("domain", ".chaoxing.com")
            if domain.lstrip(".") == "chaoxing.com" or domain.endswith(".chaoxing.com"):
                self.session.cookies.set_cookie(requests.cookies.create_cookie(**cookie))

    def cookies(self):
        return serialize_cookies(self.session.cookies)

    def cookie(self, name, default=""):
        # Different platform subdomains may legitimately set the same cookie name.
        values = [c.value for c in self.session.cookies if c.name == name]
        return values[-1] if values else default

    def request(self, method, url, **kwargs):
        if urlsplit(url).scheme != "https":
            raise PlatformError("平台接口必须使用 HTTPS")
        try:
            response = self.session.request(method, url, timeout=(8, 25), **kwargs)
            if response.status_code == 401:
                raise SessionExpired("超星登录已失效，请重新登录")
            if response.status_code == 403:
                raise PlatformError("平台要求额外验证，请先在官方客户端完成验证后重试")
            response.raise_for_status()
            return response
        except requests.RequestException:
            # Exception strings often contain request URLs with session credentials.
            raise PlatformError("无法连接超星平台，请检查网络或稍后重试") from None

    @staticmethod
    def json(response):
        try:
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except ValueError:
            raise PlatformError("平台返回了非预期格式，可能需要重新登录或适配接口") from None

    @staticmethod
    def check_login_page(response):
        if ("passport2.chaoxing.com" in response.url and "accountManage" not in response.url
                or re.search(r'<title[^>]*>[^<]*(登录|login)', response.text, re.I)
                or 'id="loginForm"' in response.text):
            raise SessionExpired("超星登录已失效，请重新登录")

    def login_password(self, phone, password):
        data = self.json(self.request("POST", "https://passport2.chaoxing.com/fanyalogin", data={
            "fid": "-1", "uname": encrypt_login(phone), "password": encrypt_login(password),
            "refer": "https%3A%2F%2Fi.chaoxing.com", "t": "true", "forbidotherlogin": "0",
            "validate": "", "doubleFactorLogin": "0", "independentId": "0",
        }))
        if data.get("status") is not True:
            raise PlatformError(str(data.get("msg2") or data.get("mes") or "登录失败，请核对账号密码或完成平台验证")[:200])
        return self.profile(phone)

    def profile(self, phone=""):
        uid = self.cookie("_uid") or self.cookie("UID")
        if not uid:
            raise SessionExpired("未取得有效登录凭据，请重新登录")
        # Validate actual server response, not merely the existence of cookies.
        self.course_page()
        name = phone[-4:] if phone else "超星用户"
        response = self.request("GET", "https://passport2.chaoxing.com/mooc/accountManage")
        self.check_login_page(response)
        tag = BeautifulSoup(response.text, "html.parser").select_one("#messageName")
        if tag:
            name = tag.get("value") or tag.get_text(strip=True) or name
        return {"uid": uid, "name": name, "phone": phone}

    def course_page(self, folder="0"):
        response = self.request("POST", self.COURSE_URL, data={
            "courseType": "1", "courseFolderId": folder, "query": "", "superstarClass": "0"})
        self.check_login_page(response)
        return response

    def courses(self):
        result = parse_courses(self.course_page().text)
        response = self.request("GET", self.INTERACTION)
        self.check_login_page(response)
        soup = BeautifulSoup(response.text, "html.parser")
        folders = list(dict.fromkeys(t.get("fileid") for t in soup.select("ul.file-list > li[fileid]")))
        for folder in folders[:100]:
            if folder:
                result.extend(parse_courses(self.course_page(folder).text))
        return list({c["key"]: c for c in result}.values())

    def activities(self, courses):
        activities = []
        for course in courses:
            response = self.request("GET", self.SIGN_BASE + "/v2/apis/active/student/activelist", params={
                "fid": "0", "courseId": course["courseId"], "classId": course["clazzId"],
                "_": str(int(time.time() * 1000)),
            })
            self.check_login_page(response)
            data = self.json(response)
            body = data.get("data")
            if not isinstance(body, dict) or not isinstance(body.get("activeList"), list):
                raise PlatformError("签到活动列表格式已变化，请重新登录或更新适配器")
            for item in body["activeList"]:
                if str(item.get("status")) != "1" or str(item.get("otherId")) not in {"0", "2", "3", "4", "5"}:
                    continue
                # type=2 is sign-in; non-sign activities can also have otherId=0.
                if item.get("type") is not None and str(item["type"]) != "2":
                    continue
                if not item.get("id"):
                    continue
                activities.append({"id": str(item["id"]), "title": item.get("nameOne", "签到活动"),
                                   "kind": {"0": "normal", "2": "qr", "3": "gesture", "4": "location", "5": "code"}[str(item["otherId"])],
                                   "course": course, "start_time": item.get("startTime"),
                                   "photo": str(item.get("ifphoto", "0")) == "1"})
        return list({a["id"]: a for a in activities}.values())

    def sign(self, activity, supplied, name):
        kind = supplied.get("kind") or ("photo" if activity.get("photo") else activity["kind"])
        if kind not in {"normal", "photo", "qr", "gesture", "location", "code"}:
            raise ValueError("暂不支持此签到方式")
        uid = self.cookie("_uid") or self.cookie("UID")
        course = activity["course"]
        params = {"name": name, "activeId": activity["id"], "uid": uid, "fid": self.cookie("fid", "0"),
                  "appType": "15", "clientip": "", "useragent": "", "latitude": "-1", "longitude": "-1"}
        if kind == "qr":
            raw = str(supplied.get("qr", "")).strip()
            enc = parse_qs(urlsplit(raw).query).get("enc", [raw])[0]
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,256}", enc):
                raise ValueError("请输入当前签到二维码链接或有效 enc 参数")
            params["enc"] = enc
        elif kind == "location":
            try:
                lat, lon = float(supplied["latitude"]), float(supplied["longitude"])
            except (KeyError, ValueError, TypeError):
                raise ValueError("请填写有效的经纬度") from None
            if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                raise ValueError("经纬度超出有效范围")
            address = str(supplied.get("address", "")).strip()
            if not address:
                raise ValueError("请填写位置说明")
            params.update(latitude=str(lat), longitude=str(lon), address=address[:200], ifTiJiao="1")
        elif kind == "photo":
            object_id = str(supplied.get("object_id", "")).strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", object_id):
                raise ValueError("请提供已上传到超星云盘的图片 objectId")
            params["objectId"] = object_id
        elif kind in {"gesture", "code"}:
            code = str(supplied.get("code", "")).strip()
            if not re.fullmatch(r"[0-9]{1,20}", code):
                raise ValueError("请填写当前活动的手势数字或签到码")
            params["signCode"] = code
        pre = self.request("GET", self.SIGN_BASE + "/newsign/preSign", params={
            "courseId": course["courseId"], "classId": course["clazzId"], "activePrimaryId": activity["id"],
            "general": "1", "sys": "1", "ls": "1", "appType": "15", "uid": uid,
        })
        self.check_login_page(pre)
        response = self.request("GET", self.SIGN_BASE + "/pptSign/stuSignajax", params=params)
        self.check_login_page(response)
        result = response.text.strip()
        if result != "success":
            if result.lower() in {"please login", "login", "notlogin"} or "请先登录" in result:
                raise SessionExpired("超星登录已失效，请重新登录")
            plain = BeautifulSoup(result, "html.parser").get_text(" ", strip=True)[:200]
            raise PlatformError("签到未成功：" + (plain or "平台未确认成功"))
        return "签到成功"


class QRLogin:
    def __init__(self, client_factory=ChaoxingClient):
        self.factory = client_factory
        self.entries = {}
        self.lock = threading.RLock()

    def cancel(self, browser_id, token):
        with self.lock:
            entry = self.entries.get(token)
            if entry and entry["browser"] == browser_id:
                self.entries.pop(token, None)

    def cancel_browser(self, browser_id):
        with self.lock:
            self.entries = {k: v for k, v in self.entries.items() if v["browser"] != browser_id}

    def create(self, browser_id):
        with self.lock:
            self.entries = {k: v for k, v in self.entries.items() if v["expires"] > time.time() and v["browser"] != browser_id}
            if len(self.entries) >= 50:
                raise PlatformError("二维码请求过多，请稍后重试")
        client = self.factory()
        page = client.request("GET", "https://passport2.chaoxing.com/cloudscanlogin", params={
            "mobiletip": "电脑端登录确认", "pcrefer": "https://i.chaoxing.com"})
        soup = BeautifulSoup(page.text, "html.parser")
        uuid_tag, enc_tag = soup.select_one("#uuid"), soup.select_one("#enc")
        if not uuid_tag or not enc_tag:
            raise PlatformError("无法获取登录二维码，请改用手机号登录或稍后重试")
        uuid_value, enc = uuid_tag.get("value"), enc_tag.get("value")
        if not uuid_value or not enc:
            raise PlatformError("平台未返回有效二维码参数")
        image = client.request("GET", "https://passport2.chaoxing.com/createqr", params={
            "uuid": uuid_value, "xxtrefer": "", "type": "1", "mobiletip": "电脑端登录确认"})
        mime = image.headers.get("Content-Type", "").split(";")[0]
        if mime not in {"image/png", "image/jpeg", "image/gif"}:
            raise PlatformError("平台返回的二维码图片无效")
        token = secrets.token_urlsafe(24)
        with self.lock:
            self.entries[token] = {"browser": browser_id, "client": client, "uuid": uuid_value,
                                   "enc": enc, "expires": time.time() + 180, "last_poll": 0, "polling": False}
        return {"id": token, "image": f"data:{mime};base64," + base64.b64encode(image.content).decode(), "expires_in": 180}

    def poll(self, browser_id, token):
        with self.lock:
            entry = self.entries.get(token)
            if not entry or entry["browser"] != browser_id:
                raise ValueError("二维码不存在，请刷新")
            if entry["expires"] < time.time():
                self.entries.pop(token, None)
                return {"state": "expired"}, None
            if entry["polling"] or time.time() - entry["last_poll"] < 1.5:
                return {"state": "waiting"}, None
            entry["last_poll"], entry["polling"] = time.time(), True
        client = entry["client"]
        try:
            response = client.json(client.request("POST", "https://passport2.chaoxing.com/getauthstatus", data={"uuid": entry["uuid"], "enc": entry["enc"]}))
            with self.lock:
                if self.entries.get(token) is not entry:
                    return {"state": "cancelled"}, None
            if response.get("status") is True:
                profile = client.profile()
                with self.lock:
                    if self.entries.get(token) is not entry:
                        return {"state": "cancelled"}, None
                    self.entries.pop(token, None)
                return {"state": "confirmed", "profile": profile}, client
            state = {"2": "expired", "4": "scanned", "6": "cancelled"}.get(str(response.get("type")), "waiting")
            return {"state": state}, None
        finally:
            with self.lock:
                entry["polling"] = False
