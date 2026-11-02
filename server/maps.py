"""Explicit public-place search, isolated from all platform sessions.

Nominatim policy: https://operations.osmfoundation.org/policies/nominatim/
Single-deployment global rate limit, cached results, no autocomplete/bulk use.
"""
import math
import os
import threading
import time
from urllib.parse import urlsplit

import requests


class MapSearch:
    def __init__(self):
        self.url = os.getenv('AUTO_CHAOXING_GEOCODER_URL', 'https://nominatim.openstreetmap.org/search')
        self.reverse_url = os.getenv('AUTO_CHAOXING_REVERSE_GEOCODER_URL', 'https://nominatim.openstreetmap.org/reverse')
        self.lock = threading.Lock()
        self.last_request = -math.inf
        self.cache = {}

    def search(self, query):
        if not isinstance(query, str) or not 2 <= len(query.strip()) <= 120:
            raise ValueError('请输入 2～120 个字符的公开学校或地点名称')
        query = query.strip()
        if not self.url:
            raise ValueError('管理员已关闭在线地点搜索，请拖动地图选点')
        if urlsplit(self.url).scheme != 'https':
            raise ValueError('搜索服务地址必须使用 HTTPS')
        with self.lock:
            stamp = time.monotonic()
            cached = self.cache.get(query)
            if cached and stamp - cached[0] < 86400:
                return cached[1]
            if stamp - self.last_request < 1.1:
                raise ValueError('搜索过于频繁，请稍后重试（全局至少间隔 1 秒）')
            self.last_request = stamp
            # Serialize external requests; never share a Chaoxing cookie jar.
            try:
                response = requests.get(self.url, params={'q':query,'format':'jsonv2','limit':5,'accept-language':'zh-CN,zh,en'},
                                        headers={'User-Agent':'AutoChaoxingTool/0.2.2 (+https://github.com/YzWushao/auto-chaoxing-tool)', 'Accept':'application/json'},
                                        timeout=(4,10), allow_redirects=False)
                response.raise_for_status()
                raw = response.json()
                if not isinstance(raw,list):
                    raise ValueError('invalid response')
                result = []
                for item in raw[:5]:
                    if not isinstance(item,dict):
                        continue
                    try:
                        lon, lat = float(item['lon']), float(item['lat'])
                    except (KeyError,TypeError,ValueError,OverflowError):
                        continue
                    if not math.isfinite(lon) or not math.isfinite(lat) or abs(lon)>180 or abs(lat)>85.05112878:
                        continue
                    result.append({'name':str(item.get('display_name') or item.get('name') or query)[:400], 'longitude':lon, 'latitude':lat})
            except (requests.RequestException,ValueError):
                raise ValueError('地点搜索暂不可用，请检查网络或继续拖动地图选点') from None
            if len(self.cache) >= 1000:
                self.cache.pop(next(iter(self.cache)))
            self.cache[query] = (stamp,result)
            return result

    def reverse(self, longitude, latitude):
        if (type(longitude) not in {int,float} or type(latitude) not in {int,float}
                or not math.isfinite(longitude) or not math.isfinite(latitude)
                or abs(longitude)>180 or abs(latitude)>85.05112878):
            raise ValueError('请提供有效的 WGS84 选点坐标')
        if not self.reverse_url:
            raise ValueError('管理员已关闭在线地址查询，请手动填写位置说明')
        if urlsplit(self.reverse_url).scheme != 'https':
            raise ValueError('地址查询服务必须使用 HTTPS')
        key = ('reverse',f'{longitude:.6f}',f'{latitude:.6f}')
        with self.lock:
            stamp = time.monotonic()
            cached = self.cache.get(key)
            if cached and stamp-cached[0]<86400:
                return cached[1]
            if stamp-self.last_request<1.1:
                raise ValueError('地址查询过于频繁，请稍后点击“获取位置说明”重试')
            self.last_request = stamp
            try:
                response = requests.get(self.reverse_url,
                    params={'lon':key[1],'lat':key[2],'format':'jsonv2','zoom':18,'addressdetails':1,'accept-language':'zh-CN,zh,en'},
                    headers={'User-Agent':'AutoChaoxingTool/0.13.0 (+https://github.com/YzWushao/auto-chaoxing-tool)', 'Accept':'application/json'},
                    timeout=(4,10),allow_redirects=False)
                response.raise_for_status()
                raw = response.json()
                address = raw.get('display_name') if isinstance(raw,dict) else None
                if not isinstance(address,str) or not address.strip():
                    raise ValueError()
                result = {'address':address.strip()[:200], 'attribution':'© OpenStreetMap contributors'}
            except (requests.RequestException,ValueError):
                raise ValueError('未能获取此点的地址，请手动填写位置说明或稍后重试') from None
            if len(self.cache)>=1000:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = (stamp,result)
            return result
