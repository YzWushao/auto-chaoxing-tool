"""Decode QQ-uploaded QR pictures locally. Never fetch decoded QR URLs."""
import base64
import io
import re
import warnings
from urllib.parse import urlsplit, urlunsplit, parse_qs, urljoin

import requests
from PIL import Image, ImageOps
import zxingcpp

MAX_IMAGE = 8 * 1024 * 1024


class ImageReadError(ValueError):
    """User-facing image failure; keep the selected QR activity for retry."""


def base64_picture(encoded):
    if not isinstance(encoded, str):
        raise ImageReadError('图片内容无效，请重新发送原图')
    if encoded.startswith('base64://'):
        encoded = encoded[9:]
    elif encoded.startswith('data:'):
        header, separator, encoded = encoded.partition(',')
        if not separator or not header.startswith('data:image/') or not header.endswith(';base64'):
            raise ImageReadError('图片内容无效，请重新发送原图')
    if len(encoded) > (MAX_IMAGE * 4 // 3 + 16):
        raise ImageReadError('二维码图片不能超过 8 MB')
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        raise ImageReadError('图片内容无效，请重新发送原图') from None
    if not data or len(data) > MAX_IMAGE:
        raise ImageReadError('二维码图片需在 8 MB 以内')
    return data


class ImageStream:
    """Bounded, ordered reader for NapCat's official download_file_stream."""
    def __init__(self):
        self.content = bytearray()
        self.expected_size = None
        self.index = 0
        self.complete = False

    def feed(self, packet):
        if not isinstance(packet, dict) or self.complete:
            raise ImageReadError('图片传输未完成，请重新发送原图')
        kind = packet.get('data_type')
        if kind == 'file_info' and self.expected_size is None:
            size = packet.get('file_size')
            if type(size) is not int or not 0 < size <= MAX_IMAGE:
                raise ImageReadError('二维码图片需在 8 MB 以内')
            self.expected_size = size
        elif kind == 'file_chunk' and self.expected_size is not None:
            encoded = packet.get('data')
            if packet.get('index') != self.index or not isinstance(encoded, str) or len(encoded) > 90000:
                raise ImageReadError('图片传输未完成，请重新发送原图')
            chunk = base64_picture(encoded)
            if packet.get('size') != len(chunk) or len(self.content)+len(chunk) > self.expected_size:
                raise ImageReadError('图片传输未完成，请重新发送原图')
            self.content.extend(chunk)
            self.index += 1
        elif kind == 'file_complete' and self.expected_size is not None:
            if packet.get('total_chunks') != self.index or packet.get('total_bytes') != len(self.content) or len(self.content) != self.expected_size:
                raise ImageReadError('图片传输未完成，请重新发送原图')
            self.complete = True
        else:
            raise ImageReadError('图片传输未完成，请重新发送原图')
        return self.complete


def image_url(raw):
    if not isinstance(raw, str) or len(raw) > 8192:
        raise ValueError('QQ 未返回可用的图片下载地址，请重新发送原图')
    url = urlsplit(raw)
    host = (url.hostname or '').lower()
    if (url.scheme not in {'http', 'https'} or url.username or url.password or url.port not in {None, 80, 443}
            or not (host.endswith('.qpic.cn') or host == 'qpic.cn' or host in {'multimedia.nt.qq.com', 'multimedia.nt.qq.com.cn'})):
        raise ImageReadError('图片读取暂时失败，请重新发送原图')
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


def transcode_picture(data):
    """Decode uploaded bytes, honor orientation, flatten alpha, normalize to PNG."""
    if not isinstance(data, bytes) or not data or len(data) > MAX_IMAGE:
        raise ValueError('二维码图片需在 8 MB 以内')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in {'PNG', 'JPEG', 'WEBP', 'GIF'} or image.width * image.height > 24000000:
                    raise ValueError('图片格式或尺寸不支持，请裁剪二维码后重发')
                image.load()
                pixels = ImageOps.exif_transpose(image)
                pixels.thumbnail((2048, 2048))
                rgba = pixels.convert('RGBA')
                background = Image.new('RGBA', rgba.size, 'white')
                background.alpha_composite(rgba)
                output = io.BytesIO()
                background.convert('RGB').save(output, format='PNG')
                return output.getvalue()
    except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('图片无法读取，请发送清晰的二维码原图') from None


def decode_picture(data):
    normalized = transcode_picture(data)
    with Image.open(io.BytesIO(normalized)) as pixels:
        texts = list(dict.fromkeys(result.text for result in zxingcpp.read_barcodes(pixels, formats=zxingcpp.BarcodeFormat.QRCode) if result.text))
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


def qq_picture(rpc, segment, stream_loader=None):
    value = segment.get('data') or {}
    file = value.get('file') or value.get('file_id')
    if not isinstance(file, str) or not file or len(file) > 2048:
        raise ImageReadError('图片标识无效，请重新发送原图')
    if file.startswith(('/', '\\')) or '://' in file or re.match(r'^[A-Za-z]:', file):
        raise ImageReadError('图片标识无效，请直接发送图片')
    details = {}
    try:
        details = rpc('get_image', {'file': file})
    except ValueError:
        pass
    data = None
    if isinstance(details.get('base64'), str) and details['base64']:
        data = base64_picture(details['base64'])
    if data is None and stream_loader is not None:
        try:
            # File ID comes from the received image, never from a chat text/path.
            data = stream_loader(file)
        except ValueError:
            pass
    if data is None:
        try:
            fallback = rpc('get_file', {'file_id': file})
            if isinstance(fallback.get('base64'), str) and fallback['base64']:
                data = base64_picture(fallback['base64'])
            details = {**details, **{k: v for k, v in fallback.items() if v}}
        except ValueError:
            pass
    if data is None:
        # Older NapCat versions can still provide a refreshed QQ CDN URL.
        for url in (details.get('url'), value.get('url')):
            if not url:
                continue
            try:
                data = download_picture(url)
                break
            except ValueError:
                continue
    if data is None:
        raise ImageReadError('图片读取暂时失败，请重新发送原图')
    try:
        return decode_picture(data)
    except ValueError as error:
        raise ImageReadError(str(error)) from None
