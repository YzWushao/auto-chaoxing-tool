"""Slide-challenge protocol adapter; original-model inference is local and transient."""
import base64
import hashlib
import io
import json
import re
import secrets
import time
from urllib.parse import urlsplit

import requests
from PIL import Image

from .chaoxing import PlatformError

ROOT = 'https://captcha.chaoxing.com/captcha'
CAPTCHA_ID = 'Qt9FIw9o4pwRjOyqM6yizZBh682qN2TU'
CALLBACK = 'cx_captcha_function'


def jsonp(response):
    text = response.text.strip()
    if len(text) > 1024*1024:
        raise PlatformError('验证服务响应过大')
    if text.startswith(CALLBACK+'('):
        text = text[len(CALLBACK)+1:]
        text = re.sub(r'\);?\s*$', '', text)
    try:
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise PlatformError('验证服务格式已变化，请稍后重试') from None


def captcha_image(url):
    parsed = urlsplit(url) if isinstance(url, str) else None
    if (not parsed or parsed.scheme != 'https' or parsed.username or parsed.password
            or parsed.port not in (None, 443) or not re.fullmatch(r'captcha(?:-[a-z])?\.chaoxing\.com', parsed.hostname or '')):
        raise PlatformError('验证图片来源暂不支持')
    try:
        # No account cookies, proxy credentials, or redirects on image downloads.
        with requests.Session() as http:
            http.trust_env = False
            http.headers.update({'User-Agent': 'Mozilla/5.0', 'Referer': 'https://mobilelearn.chaoxing.com/'})
            with http.get(url, timeout=(5, 12), stream=True, allow_redirects=False) as response:
                if response.status_code != 200:
                    raise ValueError()
                data = bytearray()
                for chunk in response.iter_content(65536):
                    data.extend(chunk)
                    if len(data) > 2*1024*1024:
                        raise ValueError()
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {'PNG', 'JPEG', 'WEBP'} or not 0 < image.width*image.height <= 1024*1024:
                raise ValueError()
            output = io.BytesIO()
            image.convert('RGBA').save(output, format='PNG')
            return output.getvalue(), image.width, image.height
    except (requests.RequestException, ValueError, OSError, Image.DecompressionBombError):
        raise PlatformError('无法读取验证图片，请刷新验证后重试') from None


def create_challenge(client, referer):
    headers = {'Referer': referer}
    conf = jsonp(client.request('GET', ROOT+'/get/conf', headers=headers,
                               params={'callback': CALLBACK, 'captchaId': CAPTCHA_ID, '_': int(time.time()*1000)}))
    try:
        stamp = int(conf['t'])
    except (KeyError, TypeError, ValueError):
        raise PlatformError('验证服务未提供时间参数') from None
    key, iv = secrets.token_hex(16), secrets.token_hex(16)
    # Legacy wire format, not a password hash or a local security primitive.
    digest = hashlib.md5((str(stamp)+CAPTCHA_ID+'slide'+key).encode(), usedforsecurity=False).hexdigest()
    query = {'callback': CALLBACK, 'captchaId': CAPTCHA_ID, 'type': 'slide', 'version': '1.1.20',
             'captchaKey': key, 'token': digest+':'+str(stamp+300000), 'referer': referer, 'iv': iv, '_': int(time.time()*1000)}
    value = jsonp(client.request('GET', ROOT+'/get/verification/image', headers=headers, params=query))
    images = value.get('imageVerificationVo')
    if not isinstance(images, dict) or images.get('type') not in (None, 'slide') or not isinstance(value.get('token'), str):
        raise PlatformError('当前验证类型暂不支持，请到官方客户端处理')
    background, width, height = captcha_image(images.get('shadeImage'))
    piece, piece_width, piece_height = captcha_image(images.get('cutoutImage'))
    if not 8 < piece_width < width <= 1024 or not 8 < height <= 1024 or piece_height != height:
        raise PlatformError('验证图片尺寸已变化，请刷新验证')
    return {'token': value['token'], 'iv': iv, 'referer': referer, 'background': background, 'piece': piece,
            'width': width, 'height': height, 'piece_width': piece_width}


def public_challenge(value, nonce):
    return {'id': nonce, 'background': 'data:image/png;base64,'+base64.b64encode(value['background']).decode(),
            'piece': 'data:image/png;base64,'+base64.b64encode(value['piece']).decode(),
            'width': value['width'], 'height': value['height'], 'piece_width': value['piece_width'], 'expires_in': 180}


def predict_offset(value):
    from .captcha_model import model
    return model.predict(value)

def check_challenge(client, value, x):
    if type(x) is not int or not 0 <= x <= value['width']-value['piece_width']:
        raise ValueError('请将滑块移动到图片中的缺口位置')
    query = {'callback': CALLBACK, 'captchaId': CAPTCHA_ID, 'type': 'slide', 'token': value['token'],
             'textClickArr': json.dumps([{'x': x}], separators=(',', ':')), 'coordinate': '[]', 'runEnv': '10',
             'version': '1.1.20', 't': 'a', 'iv': value['iv'], '_': int(time.time()*1000)}
    result = jsonp(client.request('GET', ROOT+'/check/verification/result', headers={'Referer': value['referer']}, params=query))
    if result.get('result') is not True or result.get('error') in (1, '1'):
        return None
    extra = result.get('extraData')
    try:
        if isinstance(extra, str):
            extra = json.loads(extra)
        proof = extra.get('validate') if isinstance(extra, dict) else None
    except ValueError:
        proof = None
    if not isinstance(proof, str) or not 1 <= len(proof) <= 4096 or any(ord(c) < 32 for c in proof):
        raise PlatformError('验证服务未提供有效结果，请刷新验证')
    return proof


def resolve_challenge(client, referer):
    challenge = create_challenge(client, referer)
    for attempt in range(2):
        x = predict_offset(challenge)
        if x is None:
            break
        proof = check_challenge(client, challenge, x)
        if proof:
            return proof, None
        challenge = create_challenge(client, referer)
    return None, challenge
