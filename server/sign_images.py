"""Decode QQ-uploaded QR pictures locally. Never fetch decoded QR URLs."""
import base64
import io
import warnings
from urllib.parse import urlsplit, urlunsplit, parse_qs, urljoin

import requests
from PIL import Image
import zxingcpp

MAX_IMAGE = 8 * 1024 * 1024


def image_url(raw):
    if not isinstance(raw, str) or len(raw) > 8192:
        raise ValueError('QQ 未返回可用的图片下载地址，请重新发送原图')
    url = urlsplit(raw)
    host = (url.hostname or '').lower()
    if (url.scheme not in {'http', 'https'} or url.username or url.password or url.port not in {None, 80, 443}
            or not (host.endswith('.qpic.cn') or host == 'qpic.cn' or host == 'multimedia.nt.qq.com')):
        raise ValueError('只接收 QQ 图片 CDN 地址，不下载任意网址或本地文件')
    return urlunsplit(('https', host, url.path, url.query, ''))


def download_picture(raw):
    url = image_url(raw)
    with requests.Session() as session:
        session.trust_env = False
        session.headers['User-Agent'] = 'AutoChaoxingTool/QQ-QR'
        for _ in range(4):
            try:
                with session.get(url, timeout=(5, 12), allow_redirects=False, stream=True) as response:
                    if response.is_redirect:
                        url = image_url(urljoin(url, response.headers.get('Location', '')))
                        continue
                    if response.status_code != 200:
                        raise ValueError('QQ 图片下载失败，请重新发送原图')
                    data = bytearray()
                    for chunk in response.iter_content(65536):
                        data.extend(chunk)
                        if len(data) > MAX_IMAGE:
                            raise ValueError('二维码图片不能超过 8 MB')
                    return bytes(data)
            except requests.RequestException:
                raise ValueError('QQ 图片暂时无法下载，请重新发送原图') from None
    raise ValueError('QQ 图片重定向次数过多，请重新发送原图')


def decode_picture(data):
    if not isinstance(data, bytes) or not data or len(data) > MAX_IMAGE:
        raise ValueError('二维码图片需在 8 MB 以内')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {'PNG', 'JPEG', 'WEBP', 'GIF'} or image.width * image.height > 24000000:
                    raise ValueError('图片格式或尺寸不支持，请裁剪二维码后重发')
                image.load()
                pixels = image.convert('RGB')
                pixels.thumbnail((2048, 2048))
                texts = list(dict.fromkeys(result.text for result in zxingcpp.read_barcodes(pixels, formats=zxingcpp.BarcodeFormat.QRCode) if result.text))
    except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('图片无法读取，请发送清晰的二维码原图') from None
    if not texts:
        raise ValueError('没有识别到二维码，请裁剪二维码后重新上传')
    if len(texts) != 1:
        raise ValueError('图片包含多个不同二维码，请只保留目标二维码')
    raw = texts[0].strip()
    # Same passthrough semantics as the web decoder: no activity/expiry rejection.
    try:
        return parse_qs(urlsplit(raw).query).get('enc', [raw])[0]
    except ValueError:
        return raw


def qq_picture(rpc, segment):
    value = segment.get('data') or {}
    file = value.get('file')
    if not isinstance(file, str) or not file or len(file) > 2048:
        raise ValueError('QQ 图片标识无效，请重新发送图片')
    details = rpc('get_image', {'file': file})
    # Some compatible implementations return the bytes directly; do not open a
    # remote server's `file` path on this machine or request arbitrary file APIs.
    if isinstance(details.get('base64'), str):
        encoded = details['base64']
        if len(encoded) > (MAX_IMAGE * 4 // 3 + 16):
            raise ValueError('二维码图片不能超过 8 MB')
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise ValueError('QQ 返回的图片内容无效，请重新发送原图') from None
        return decode_picture(data)
    return decode_picture(download_picture(details.get('url') or value.get('url')))
