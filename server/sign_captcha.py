"""Independent slide-challenge adapter. Tokens and images remain transient.

The HTTP field names follow Chaoxing's observed slide protocol. No Android
implementation or prediction model is bundled. Pillow supplies image masks.
"""
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
    """Find an isolated muted gap with the piece's size; abstain if ambiguous."""
    from collections import deque
    with Image.open(io.BytesIO(value['background'])) as original, Image.open(io.BytesIO(value['piece'])) as cutout:
        scale = min(1, 320/original.width)
        bg = original.convert('RGB').resize((round(original.width*scale), round(original.height*scale)))
        piece = cutout.convert('RGBA').resize((round(cutout.width*scale), round(cutout.height*scale)))
        alpha = piece.getchannel('A').point(lambda a: 255 if a > 180 else 0)
        box = alpha.getbbox()
        if not box:
            return None
        pw, ph = box[2]-box[0], box[3]-box[1]
        area = alpha.histogram()[255]
        if pw < 12 or ph < 12 or area < 100:
            return None
        pixels = bg.load()
        eligible = set()
        for y in range(bg.height):
            for x in range(bg.width):
                color = pixels[x, y]
                if max(color)-min(color) < 32 and 35 < sum(color)/3 < 165:
                    eligible.add((x, y))
        proposals = []
        while eligible:
            seed = eligible.pop()
            pending, points = deque([seed]), [seed]
            while pending:
                x, y = pending.popleft()
                for adjacent in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                    if adjacent in eligible:
                        eligible.remove(adjacent)
                        pending.append(adjacent)
                        points.append(adjacent)
            if len(points) < area*0.3:
                continue
            xs, ys = zip(*points)
            left, top, right, bottom = min(xs), min(ys), max(xs)+1, max(ys)+1
            width, height = right-left, bottom-top
            if not (pw*0.65 <= width <= pw*1.3 and ph*0.3 <= height <= ph*1.3):
                continue
            offset = round((left-box[0])/scale)
            if 0 <= offset <= value['width']-value['piece_width']:
                proposals.append((len(points), offset))
        proposals.sort(reverse=True)
        if not proposals or (len(proposals)>1 and proposals[0][0] < proposals[1][0]*1.6):
            return None
        return proposals[0][1]

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
