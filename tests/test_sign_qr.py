import json
import shutil
import subprocess

import pytest
import qrcode

from server.chaoxing import ChaoxingClient, PlatformError
from server.config import ROOT
from tests.conftest import FakeClient
from tests.test_platform import response


NODE = shutil.which('node')


def run_javascript(payload):
    if not NODE:
        pytest.skip('Node.js is only required for offline JavaScript regression tests')
    program = r'''
const fs=require('node:fs'), path=require('node:path');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const helper=require(path.join(process.cwd(),'web/sign-qr.js'));
if(input.matrix){
  const jsQR=require(path.join(process.cwd(),'web/vendor/jsqr-1.4.0.js'));
  const n=input.matrix.length, scale=4, width=n*scale;
  const pixels=new Uint8ClampedArray(width*width*4);
  for(let y=0;y<width;y++) for(let x=0;x<width;x++){
    let value=input.matrix[Math.floor(y/scale)][Math.floor(x/scale)]?0:255;
    if(input.inverted) value=255-value;
    const i=(y*width+x)*4; pixels[i]=pixels[i+1]=pixels[i+2]=value; pixels[i+3]=255;
  }
  const result=jsQR(pixels,width,width,{inversionAttempts:'attemptBoth'});
  process.stdout.write(JSON.stringify(result?helper.parameters(result.data):null));
}else process.stdout.write(JSON.stringify(helper.parameters(input.text)));
'''
    result = subprocess.run([NODE, '-e', program], cwd=ROOT, input=json.dumps(payload),
                            text=True, capture_output=True, timeout=15, check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize('text,value,activity', [
    ('https://mobilelearn.chaoxing.com/widget/sign/e?id=902&enc=OFFLINE_TOKEN_123', 'OFFLINE_TOKEN_123', '902'),
    ('https://mobilelearn.chaoxing.com/widget/sign/e?id=999&enc=OTHER_ACTIVITY_TOKEN', 'OTHER_ACTIVITY_TOKEN', '999'),
    ('http://mobilelearn.chaoxing.com/widget/sign/e?activeId=902&enc=OLD_TOKEN_123&time=1', 'OLD_TOKEN_123', '902'),
    ('https://example.invalid/?enc=short', 'short', ''),
    ('plain-enc-input', 'plain-enc-input', ''),
    ('not a valid sign QR', 'not a valid sign QR', ''),
])
def test_parameters_are_filled_without_matching_or_expiry_interception(text, value, activity):
    result = run_javascript({'text': text})
    assert result['value'] == value
    assert result['activityId'] == activity
    assert result['raw'] == text


@pytest.mark.parametrize('inverted', [False, True])
def test_actual_qr_decoder_reads_generated_image_pixels(inverted):
    text = 'https://mobilelearn.chaoxing.com/widget/sign/e?id=902&enc=OFFLINE_QR_TOKEN_123456789'
    code = qrcode.QRCode(border=4)
    code.add_data(text)
    code.make(fit=True)
    result = run_javascript({'matrix': code.get_matrix(), 'inverted': inverted})
    assert result['value'] == 'OFFLINE_QR_TOKEN_123456789'
    assert result['activityId'] == '902'


def test_decoder_reports_no_qr_for_blank_pixels():
    assert run_javascript({'matrix': [[False]*32 for _ in range(32)]}) is None


def test_platform_qr_error_is_reported_instead_of_success(monkeypatch):
    client = ChaoxingClient()
    calls = []

    def request(method, url, **kwargs):
        calls.append(url)
        return response('二维码已过期' if url.endswith('/stuSignajax') else 'ready')

    monkeypatch.setattr(client, 'request', request)
    with pytest.raises(PlatformError, match='二维码已过期'):
        client.sign({'id': '902', 'kind': 'qr', 'course': {'courseId': '1', 'clazzId': '2'}},
                    {'kind': 'qr', 'qr': 'EXPIRED_TEST_TOKEN_12345'}, '测试')
    assert len(calls) == 2


def test_rejected_qr_does_not_create_success_record(browser, monkeypatch):
    account = browser.login()
    path = f"/accounts/{account['id']}"
    original = FakeClient.activities
    monkeypatch.setattr(FakeClient, 'activities', lambda self, courses: [
        {**original(self, courses)[0], 'id': '902', 'kind': 'qr'}])
    assert browser.get(path + '/activities').status_code == 200

    def rejected(*args):
        raise PlatformError('签到未成功：二维码已过期')

    monkeypatch.setattr(FakeClient, 'sign', rejected)
    reply = browser.send(path + '/sign', {'activity_id': '902', 'kind': 'qr', 'qr': 'EXPIRED_TEST_TOKEN_12345'})
    assert reply.status_code == 502
    assert '二维码已过期' in reply.json['error']
    assert browser.get(path + '/activities').json['activities'][0]['signed'] is False
    assert not any(e['kind'] == 'sign_success' for e in browser.get('/bootstrap').json['events'])
