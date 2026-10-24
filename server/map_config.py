"""Optional AMap JS API credentials; security code stays on the server."""
import re
import threading
import time
from collections import deque

import requests

from .config import MASK

DEFAULT_MAP = {'provider':'osm', 'key':'', 'security_code':''}


def validate_map_settings(data, current):
    if not isinstance(data,dict) or set(data)-set(DEFAULT_MAP):
        raise ValueError('地图设置格式错误')
    value={**DEFAULT_MAP, **current}
    for name, raw in data.items():
        if not isinstance(raw,str):
            raise ValueError('地图设置需要为文本')
        raw=raw.strip()
        if name in {'key','security_code'}:
            if raw == MASK:
                continue
            if raw and not re.fullmatch(r'[A-Za-z0-9_-]{16,128}',raw):
                raise ValueError('高德 Key / 安全密钥格式无效，请复制完整内容')
        value[name]=raw
    if value['provider'] not in {'osm','amap'}:
        raise ValueError('请选择免费地图或高德地图')
    if bool(value['key']) != bool(value['security_code']):
        raise ValueError('高德 Key 和 securityJsCode 需要配套填写，或同时清空')
    if value['provider']=='amap' and not value['key']:
        raise ValueError('请先填写高德 Web 端（JS API）Key 和安全密钥，再设为默认地图')
    return value


def public_map_settings(value):
    return {'provider':value.get('provider','osm'), 'key':MASK if value.get('key') else '',
            'security_code':MASK if value.get('security_code') else '',
            'configured':bool(value.get('key') and value.get('security_code'))}


class AMapProxy:
    PATHS={'v3/place/text':'https://restapi.amap.com/v3/place/text',
           'v5/place/text':'https://restapi.amap.com/v5/place/text',
           'v3/config/district':'https://restapi.amap.com/v3/config/district',
           'v4/map/styles':'https://webapi.amap.com/v4/map/styles'}

    def __init__(self):
        self.lock=threading.Lock()
        self.calls=deque()

    def fetch(self, path, query, settings, referer=''):
        if path not in self.PATHS:
            raise KeyError('map path')
        if not settings.get('key') or not settings.get('security_code'):
            raise ValueError('请到“设置 → 地图服务”配置高德 Key 和安全密钥')
        if len(query)>30 or any(len(k)>100 or len(v)>2048 for k,v in query.items()):
            raise ValueError('地图请求参数过长')
        callback=query.get('callback')
        if callback and not re.fullmatch(r'[A-Za-z_$][\w$.]{0,120}',callback):
            raise ValueError('地图回调参数无效')
        with self.lock:
            stamp=time.monotonic()
            while self.calls and stamp-self.calls[0]>60:
                self.calls.popleft()
            if len(self.calls)>=60:
                raise ValueError('地图请求过于频繁，请稍后重试')
            self.calls.append(stamp)
        params={k:v for k,v in query.items() if k not in {'key','jscode'}}
        params.update(key=settings['key'],jscode=settings['security_code'])
        try:
            response=requests.get(self.PATHS[path],params=params,timeout=(4,12),allow_redirects=False,
                                  headers={'User-Agent':'AutoChaoxingTool/0.2.3','Accept':'application/json, application/javascript', 'Referer':referer})
            if response.status_code != 200 or len(response.content)>2*1024*1024:
                raise ValueError('upstream response')
            mime='application/javascript' if callback else 'application/json'
            return response.content.replace(settings['security_code'].encode(),b'[redacted]'),mime
        except (requests.RequestException,ValueError):
            raise ValueError('高德地图服务暂不可用，请检查密钥、配额或网络；可切换免费地图') from None
