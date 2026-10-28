"""Model/runtime contracts; never submit an answer to a live verification service."""
import hashlib
import io

import numpy as np
from PIL import Image
import pytest

from server.captcha_model import CaptchaModel, DIRECTORY, HASHES, decode, model, preprocess
from server.sign_captcha import resolve_challenge
from tests.test_sign_verification import challenge


def test_preprocess_matches_upstream_padding_channels_and_normalization():
    image = Image.new('RGB', (32, 16), (255, 128, 0))
    buffer = io.BytesIO();image.save(buffer, 'PNG')
    tensor, side = preprocess(buffer.getvalue())
    assert side == 32 and tensor.shape == (1, 3, 640, 640)
    assert tensor.dtype == np.float32 and tensor.flags.c_contiguous
    assert tensor[0, :, 50, 50].tolist() == pytest.approx([1, 128/255, 0])
    assert tensor[0, :, 500, 50].tolist() == [0, 0, 0]


def output(*boxes):
    return np.array(boxes, dtype=np.float32).T[None]


def test_decode_uses_top_left_scaling_nms_and_original_edge_offset():
    result = output((300, 150, 100, 100, .9), (302, 150, 100, 100, .8), (100, 150, 80, 90, .5))
    assert decode(result, 320, 320, 56) == 121
    assert decode(result, 640, 640, 56) == 246


@pytest.mark.parametrize('box', [(300,150,100,100,.24), (300,150,100,100,float('nan')),
                                (float('inf'),150,100,100,.9), (300,150,-100,100,.9),
                                (0,150,100,100,.9), (640,150,50,100,.9)])
def test_decode_rejects_low_scores_nonfinite_values_and_invalid_coordinates(box):
    assert decode(output(box), 320, 320, 56) is None


def test_decode_rejects_unexpected_output_shape():
    assert decode(np.zeros((1, 8400, 5)), 320, 320, 56) is None
    assert decode(np.zeros((1, 5, 0)), 320, 320, 56) is None


def test_bundled_original_and_compatible_model_hashes_and_real_inference():
    for name, digest in HASHES.items():
        assert hashlib.sha256((DIRECTORY/name).read_bytes()).hexdigest() == digest
    status = model.status()
    assert status['available'] and status['format'] in {'ort', 'onnx-fp32'}
    pixels, _ = preprocess(challenge()['background'])
    result = model.initialize().run(None, {'images': pixels})[0]
    assert result.shape == (1, 5, 8400) and np.isfinite(result).all()
    offset = model.predict(challenge())
    assert offset is None or type(offset) is int and 0 <= offset <= 272


def test_corrupt_model_is_disabled_and_cannot_produce_a_guess(tmp_path):
    (tmp_path/'captcha.ort').write_bytes(b'corrupt-model')
    predictor = CaptchaModel(tmp_path)
    assert predictor.status() == {'name':'ChaoxingSignFaker captcha.ort','available':False,
                                  'format':None,'reason':'model_hash_mismatch'}
    assert predictor.predict(challenge()) is None


def test_missing_model_falls_back_to_manual_without_startup_failure(tmp_path):
    predictor = CaptchaModel(tmp_path)
    assert not predictor.status()['available']
    assert predictor.predict(challenge()) is None


def test_auto_check_is_bounded_and_only_platform_proof_counts(monkeypatch):
    images, checked = [], []
    def create(*args):
        value = challenge();images.append(value);return value
    monkeypatch.setattr('server.sign_captcha.create_challenge', create)
    monkeypatch.setattr('server.sign_captcha.predict_offset', lambda value: 66)
    monkeypatch.setattr('server.sign_captcha.check_challenge', lambda client,value,x: checked.append(x))
    proof, manual = resolve_challenge(object(), 'offline')
    assert proof is None and manual is images[-1] and len(checked) == 2 and len(images) == 3
    monkeypatch.setattr('server.sign_captcha.check_challenge', lambda *args: 'platform-proof')
    assert resolve_challenge(object(), 'offline') == ('platform-proof', None)


def test_low_confidence_does_not_submit_verification_answer(monkeypatch):
    value = challenge()
    monkeypatch.setattr('server.sign_captcha.create_challenge', lambda *args: value)
    monkeypatch.setattr('server.sign_captcha.predict_offset', lambda value: None)
    monkeypatch.setattr('server.sign_captcha.check_challenge', lambda *args: pytest.fail('must not check'))
    assert resolve_challenge(object(), 'offline') == (None, value)
