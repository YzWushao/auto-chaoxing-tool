"""ChaoxingSignFaker captcha model inference adapted for the Python backend.

Predictor reference: aquamarine5/ChaoxingSignFaker, commit 0346adf.
Copyright (c) 2026 aquamarine5 / Brainspark; Python adaptation (c) 2026 YzWushao.
SPDX-License-Identifier: AGPL-3.0-only
See models/chaoxing-captcha/README.md and licenses/ChaoxingSignFaker-AGPL-3.0.txt.
"""
import hashlib
import io
import math
from pathlib import Path
import threading

from PIL import Image

DIRECTORY = Path(__file__).resolve().parent.parent / 'models' / 'chaoxing-captcha'
HASHES = {'captcha.ort': 'ce9623e1f58b46bc5e7485dffc6449d36255af5e9e2d877bb4db94e8c8b21ee7',
          'captcha-cpu.onnx': 'e1c8930a83389e7f10d456944d37c007fb8d9fbfc26e8326a06f2ffc23e091a5'}
INPUT_SIZE, SCORE_THRESHOLD, NMS_IOU_THRESHOLD, EDGE_OFFSET = 640, 0.25, 0.45, 4


def preprocess(background):
    import numpy as np
    with Image.open(io.BytesIO(background)) as original:
        if not 8 < original.width <= 1024 or not 8 < original.height <= 1024:
            raise ValueError('Invalid challenge dimensions')
        side = max(original.size)
        padded = Image.new('RGB', (side, side), 'black')
        image = original.convert('RGBA')
        padded.paste(image, (0, 0), image.getchannel('A'))
        scaled = padded.resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.BILINEAR)
        pixels = np.asarray(scaled, dtype=np.float32) / np.float32(255)
        return np.ascontiguousarray(pixels.transpose(2, 0, 1)[None]), side


def intersection_over_union(a, b):
    width = max(0, min(a[0]+a[2], b[0]+b[2])-max(a[0], b[0]))
    height = max(0, min(a[1]+a[3], b[1]+b[3])-max(a[1], b[1]))
    intersection = width*height
    union = a[2]*a[3]+b[2]*b[3]-intersection
    return intersection/union if union > 0 else 0


def decode(output, padded_side, width, piece_width):
    import numpy as np
    output = np.asarray(output)
    if output.ndim != 3 or output.shape[:2] != (1, 5) or not 0 < output.shape[2] <= 20000:
        return None
    candidates = []
    for cx, cy, w, h, score in output[0].T:
        if not all(math.isfinite(float(v)) for v in (cx, cy, w, h, score)):
            continue
        if not SCORE_THRESHOLD <= score <= 1 or w <= 0 or h <= 0:
            continue
        candidates.append((float(cx-w/2), float(cy-h/2), float(w), float(h), float(score)))
    candidates.sort(key=lambda item: item[4], reverse=True)
    kept = []
    while candidates:
        best = candidates.pop(0)
        kept.append(best)
        candidates = [item for item in candidates if intersection_over_union(best, item) <= NMS_IOU_THRESHOLD]
    if not kept:
        return None
    # Same top-left inverse scaling and four-pixel correction as the Android predictor.
    offset = int(kept[0][0]*padded_side/INPUT_SIZE-EDGE_OFFSET+0.5)
    return offset if 0 <= offset <= width-piece_width else None


class CaptchaModel:
    def __init__(self, directory=DIRECTORY):
        self.directory = Path(directory)
        self.lock = threading.Lock()
        self.session = None
        self.initialized = False
        self.format = None
        self.reason = 'not_loaded'

    def initialize(self):
        with self.lock:
            if self.initialized:
                return self.session
            self.initialized = True
            try:
                import onnxruntime as ort
                options = ort.SessionOptions()
                options.intra_op_num_threads = 2
                options.inter_op_num_threads = 1
                options.log_severity_level = 3
                original = self.directory / 'captcha.ort'
                if hashlib.sha256(original.read_bytes()).hexdigest() != HASHES[original.name]:
                    self.reason = 'model_hash_mismatch'
                    return None
                try:
                    session = ort.InferenceSession(str(original), sess_options=options, providers=['CPUExecutionProvider'])
                    selected_format = 'ort'
                except Exception:
                    # Upstream's half-precision MatMul has no kernel on some desktop CPUs.
                    # The checked-in compatibility artifact widens the same weights to FP32.
                    compatible = self.directory / 'captcha-cpu.onnx'
                    if hashlib.sha256(compatible.read_bytes()).hexdigest() != HASHES[compatible.name]:
                        self.reason = 'model_hash_mismatch'
                        return None
                    session = ort.InferenceSession(str(compatible), sess_options=options, providers=['CPUExecutionProvider'])
                    selected_format = 'onnx-fp32'
                inputs, outputs = session.get_inputs(), session.get_outputs()
                if (len(inputs) != 1 or inputs[0].name != 'images' or inputs[0].type != 'tensor(float)'
                        or inputs[0].shape != [1, 3, INPUT_SIZE, INPUT_SIZE] or not outputs
                        or outputs[0].shape[:2] != [1, 5]):
                    self.reason = 'model_shape_mismatch'
                    return None
                self.session, self.format, self.reason = session, selected_format, None
            except ImportError:
                self.reason = 'runtime_missing'
            except OSError:
                self.reason = 'model_missing'
            except Exception:
                # Never log transient challenge contents or silently declare verification success.
                self.reason = 'model_load_failed'
            return self.session

    def status(self):
        self.initialize()
        return {'name': 'ChaoxingSignFaker captcha.ort', 'available': self.session is not None,
                'format': self.format, 'reason': self.reason}

    def predict(self, value):
        session = self.initialize()
        if session is None:
            return None
        try:
            pixels, side = preprocess(value['background'])
            output = session.run(None, {'images': pixels})[0]
            return decode(output, side, value['width'], value['piece_width'])
        except Exception:
            return None


model = CaptchaModel()
