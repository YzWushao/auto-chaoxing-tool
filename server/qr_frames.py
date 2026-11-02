"""Bounded, memory-only camera frame recognition. Never fetch decoded URLs."""
import io
import re
import threading
import time
import warnings
from urllib.parse import parse_qs, urlsplit

from PIL import Image, ImageOps
import zxingcpp


MAX_FRAME_BYTES = 768 * 1024


class FrameBusy(ValueError):
    pass


def activity(text):
    try:
        fields = parse_qs(text[7:].partition('-')[0] if text.startswith('SIGNIN:') else urlsplit(text).query)
        return next((fields[k][0] for k in ('id', 'aid', 'activeId', 'activePrimaryId') if fields.get(k)), '') if fields.get('enc') else ''
    except ValueError:
        return ''


class FrameDetector:
    def __init__(self):
        self.slots = threading.BoundedSemaphore(2)
        self.lock = threading.Lock()
        self.last = {}

    def detect(self, content, key, target=''):
        if not isinstance(content, bytes) or not 0 < len(content) <= MAX_FRAME_BYTES:
            raise ValueError('视频帧大小无效，最大 768 KB')
        if not isinstance(target, str) or target and not re.fullmatch(r'[1-9][0-9]{0,24}', target):
            raise ValueError('扫码活动参数无效')
        now = time.monotonic()
        with self.lock:
            self.last = {k:v for k,v in self.last.items() if now-v < 30}
            if now-self.last.get(key, -100) < .18 or key not in self.last and len(self.last) >= 256:
                raise FrameBusy('视频帧发送过快，请等待下一帧')
            self.last[key] = now
        if not self.slots.acquire(blocking=False):
            raise FrameBusy('识别服务繁忙，请等待下一帧')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                try:
                    with Image.open(io.BytesIO(content)) as original:
                        if original.format != 'JPEG' or min(original.size) < 16 or original.width*original.height > 4200000:
                            raise ValueError('请发送 420 万像素以内的 JPEG 视频帧')
                        pixels = ImageOps.exif_transpose(original).convert('RGB')
                except (OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                    raise ValueError('无法读取视频帧，请检查摄像头画面') from None
            with pixels:
                results = zxingcpp.read_barcodes(pixels, formats=zxingcpp.BarcodeFormat.QRCode,
                    try_rotate=True, try_invert=True, try_downscale=True, return_errors=True,
                    text_mode=zxingcpp.TextMode.Plain)
                choices = []
                for index, result in enumerate(results):
                    text = result.text if result.valid else ''
                    p = result.position
                    corners = [{'x':point.x,'y':point.y} for point in (p.top_left,p.top_right,p.bottom_right,p.bottom_left)]
                    valid_box = all(0 <= v['x'] <= pixels.width and 0 <= v['y'] <= pixels.height for v in corners)
                    if not valid_box:
                        corners = None
                    aid = activity(text)
                    rank = (100 if text else 0)+(20 if aid else 0)+(50 if target and aid == target else 0)
                    choices.append((rank,-index,{'text':text,'corners':corners}))
                selected = max(choices,key=lambda v:v[:2])[2] if choices else {'text':'','corners':None}
                return {**selected,'width':pixels.width,'height':pixels.height,'engine':'server',
                        'decode_ms':round((time.monotonic()-now)*1000,1)}
        finally:
            self.slots.release()
