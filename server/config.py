import configparser
import copy
import math
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
ENGINE = ROOT / "vendor" / "chaoxing"
VERSION = "0.2.3"
MASK = "••••••••"
SECRET_FIELDS = {"tokens", "key", "siliconflow_key", "go_authorization"}
PROVIDERS = ["TikuYanxi", "TikuLike", "TikuAdapter", "AI", "SiliconFlow", "TikuGo", "TikuManual"]


def template():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(ENGINE / "config_template.ini", encoding="utf-8")
    return dict(parser["tiku"])


API_DEFAULTS = template()
API_DEFAULTS.update(provider="", check_llm_connection="false", submit="false")
STUDY_DEFAULTS = dict(speed=1.0, jobs=1, notopen_action="retry", retry_interval=3.0,
                      work_redo_enabled=False, work_max_retries=3, add_learning_count=False, target_count=100,
                      study_mode="duration", replay_completed=True)


def account_defaults():
    return {"course_keys": [], "inherit_api": True, "api": copy.deepcopy(API_DEFAULTS), "study": copy.deepcopy(STUDY_DEFAULTS)}


def public_api(value):
    return {key: MASK if key in SECRET_FIELDS and val else val for key, val in value.items()}


def public_config(value):
    result = copy.deepcopy(value)
    result["study"] = {**STUDY_DEFAULTS, **result["study"]}
    result["api"] = public_api(result["api"])
    return result


def validate_api(data, current):
    if not isinstance(data, dict) or set(data) - set(API_DEFAULTS):
        raise ValueError("API 配置含未知参数")
    value = {**API_DEFAULTS, **current}
    for key, val in data.items():
        if not isinstance(val, (str, int, float, bool)) or len(str(val)) > 8192:
            raise ValueError(f"无效参数：{key}")
        if key in SECRET_FIELDS and val == MASK:
            continue
        value[key] = str(val).lower() if isinstance(val, bool) else str(val).strip()
    if any(p.strip() not in PROVIDERS for p in value["provider"].split(",") if p.strip()):
        raise ValueError("不支持的题库类型")
    for key in ("delay", "cover_rate", "min_interval_seconds", "go_min_interval", "go_retry_backoff"):
        number = float(value[key])
        if not math.isfinite(number) or number < 0 or (key == "cover_rate" and number > 1):
            raise ValueError(f"{key} 数值超出范围")
    for key in ("go_retry_times", "likeapi_retry_times"):
        if not 0 <= int(value[key]) <= 20:
            raise ValueError(f"{key} 需要为 0–20 的整数")
    for key in ("endpoint", "siliconflow_endpoint", "url"):
        if value[key] and urlsplit(value[key]).scheme not in {"http", "https"}:
            raise ValueError(f"{key} 必须使用 HTTP 或 HTTPS 地址")
    for key, default in API_DEFAULTS.items():
        if default in ("true", "false") and value[key] not in ("true", "false"):
            raise ValueError(f"{key} 需要为 true 或 false")
    return value


def validate_config(data, current):
    if not isinstance(data, dict) or set(data) - {"study", "api", "course_keys", "inherit_api"}:
        raise ValueError("配置格式不正确")
    value = copy.deepcopy(current)
    value["study"] = {**STUDY_DEFAULTS, **value["study"]}
    if "inherit_api" in data:
        if not isinstance(data["inherit_api"], bool):
            raise ValueError("继承全局配置需要为布尔值")
        value["inherit_api"] = data["inherit_api"]
    if "course_keys" in data:
        keys = data["course_keys"]
        if not isinstance(keys, list) or len(keys) > 500 or any(not isinstance(k, str) or len(k) > 150 for k in keys):
            raise ValueError("课程目标格式不正确")
        value["course_keys"] = list(dict.fromkeys(keys))
    if "api" in data:
        value["api"] = validate_api(data["api"], value["api"])
    if "study" in data:
        study = data["study"]
        if not isinstance(study, dict) or set(study) - set(STUDY_DEFAULTS):
            raise ValueError("存在未知刷课参数")
        value["study"].update(study)
        for name, lower, upper in (("speed", 1, 2), ("jobs", 1, 8), ("retry_interval", 0.5, 600), ("work_max_retries", 0, 10), ("target_count", 1, 10000)):
            raw = value["study"][name]
            if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
                raise ValueError(f"{name} 需要为数字")
            number = float(raw)
            if not math.isfinite(number) or not lower <= number <= upper:
                raise ValueError(f"{name} 需要在 {lower}–{upper} 之间")
            if name in ("jobs", "work_max_retries", "target_count") and number != int(number):
                raise ValueError(f"{name} 需要为整数")
            value["study"][name] = int(number) if name in ("jobs", "work_max_retries", "target_count") else number
        for name in ("work_redo_enabled", "add_learning_count", "replay_completed"):
            if not isinstance(value["study"][name], bool):
                raise ValueError(f"{name} 需要为布尔值")
        if value["study"]["notopen_action"] not in ("retry", "continue", "ask"):
            raise ValueError("无效的关闭章节处理方式")
        if value["study"]["study_mode"] not in ("duration", "task"):
            raise ValueError("学习模式需要为 duration 或 task")
    return value
