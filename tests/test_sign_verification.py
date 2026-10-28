"""Offline protocol/challenge tests; no real verification or sign is submitted."""
import io
import json

import pytest
from PIL import Image, ImageDraw

from server.chaoxing import ChaoxingClient, PlatformError, CaptchaRequired, SignRequirement
from server.sign_captcha import jsonp, predict_offset, captcha_image, check_challenge
from tests.conftest import FakeClient
from tests.test_platform import response, sign_response


def challenge(ambiguous=False):
    background = Image.new('RGB', (320, 160), (30, 170, 90))
    draw = ImageDraw.Draw(background)
    draw.rectangle((70, 40, 110, 80), fill=(100, 100, 100))
    if ambiguous:
        draw.rectangle((180, 40, 220, 80), fill=(100, 100, 100))
    piece = Image.new('RGBA', (48, 160))
    ImageDraw.Draw(piece).rectangle((4, 40, 44, 80), fill=(120, 170, 70, 255))
    def png(image):
        output = io.BytesIO();image.save(output, format='PNG');return output.getvalue()
    return {'background': png(background), 'piece': png(piece), 'width': 320, 'height': 160, 'piece_width': 48,
            'token': 'private-offline-challenge-token', 'iv': 'private-offline-iv',
            'referer': 'https://mobilelearn.chaoxing.com/newsign/preSign?activePrimaryId=901'}


def test_gap_prediction_uses_original_model_adapter(monkeypatch):
    seen = []
    monkeypatch.setattr('server.captcha_model.model.predict', lambda value: seen.append(value) or 66)
    value = challenge()
    assert predict_offset(value) == 66
    assert seen == [value]
    monkeypatch.setattr('server.captcha_model.model.predict', lambda value: None)
    assert predict_offset(value) is None


@pytest.mark.parametrize('url', ['http://captcha-b.chaoxing.com/a.png', 'https://example.invalid/a.png',
                                 'https://127.0.0.1/a.png', 'https://captcha-b.chaoxing.com@evil.invalid/a.png'])
def test_challenge_images_cannot_target_arbitrary_hosts(url, monkeypatch):
    monkeypatch.setattr('requests.Session.get', lambda *a, **k: pytest.fail('must not download'))
    with pytest.raises(PlatformError):
        captcha_image(url)


def test_jsonp_is_data_only_and_proof_requires_platform_success():
    assert jsonp(response('cx_captcha_function({"result":true});')) == {'result': True}
    with pytest.raises(PlatformError):
        jsonp(response('cx_captcha_function(alert(1))'))
    client = ChaoxingClient()
    client.request = lambda *a, **k: response(json.dumps({'result': False, 'extraData': json.dumps({'validate': 'must-not-accept'})}))
    assert check_challenge(client, challenge(), 66) is None
    client.request = lambda *a, **k: response(json.dumps({'result': True, 'extraData': json.dumps({'validate': 'offline-proof'})}))
    assert check_challenge(client, challenge(), 66) == 'offline-proof'
    for value in (True, -1, 500, '66'):
        with pytest.raises(ValueError):
            check_challenge(client, challenge(), value)


def test_auto_verification_retries_with_enc2_only_after_real_ack(monkeypatch):
    client = ChaoxingClient();calls=[];finals=[]
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith('/stuSignajax'):
            finals.append(kwargs['params'])
            return response('validate_offline-enc2' if len(finals)==1 else 'success')
        return sign_response(url)
    monkeypatch.setattr(client, 'request', request)
    monkeypatch.setattr('server.sign_captcha.resolve_challenge', lambda *a: ('offline-proof', None))
    result=client.sign({'id':'901','kind':'normal','course':{'courseId':'101','clazzId':'201'}}, {}, '真实姓名')
    assert result == '签到成功'
    assert [url.rsplit('/',1)[-1] for _,url,_ in calls] == ['getPPTActiveInfo','preSign','analysis','analysis2','stuSignajax','stuSignajax']
    assert calls[1][0] == 'POST'
    assert 'validate' not in finals[0]
    assert finals[1]['enc2']=='offline-enc2' and finals[1]['validate']=='offline-proof'
    assert finals[1]['name']=='真实姓名' and finals[1]['courseId']=='101'


def test_known_captcha_flag_gets_proof_before_final_submission(monkeypatch):
    client=ChaoxingClient();seen=[]
    def request(method,url,**kwargs):
        if url.endswith('/getPPTActiveInfo'):return response(payload={'data':{'ifNeedVCode':1}})
        if url.endswith('/stuSignajax'):seen.append(kwargs['params'])
        return sign_response(url)
    monkeypatch.setattr(client,'request',request)
    monkeypatch.setattr('server.sign_captcha.resolve_challenge',lambda *a:('offline-proof',None))
    client.sign({'id':'901','kind':'normal','course':{'courseId':'101','clazzId':'201'}},{},'姓名')
    assert len(seen)==1 and seen[0]['validate']=='offline-proof'


def test_pre_sign_positive_status_does_not_submit_again(monkeypatch):
    client=ChaoxingClient();urls=[]
    def request(method,url,**kwargs):
        urls.append(url)
        return response('var signstatus=1;') if url.endswith('/preSign') else response(payload={'data':{'openCheckFaceFlag':1}})
    monkeypatch.setattr(client,'request',request)
    assert '已签到' in client.sign({'id':'901','kind':'normal','course':{'courseId':'101','clazzId':'201'}},{},'姓名')
    assert not any('/stuSignajax' in url for url in urls)


def test_preparation_failure_never_looks_like_success(monkeypatch):
    client=ChaoxingClient();urls=[]
    def request(method,url,**kwargs):
        urls.append(url)
        return response('no acknowledgement') if url.endswith('/analysis') else sign_response(url)
    monkeypatch.setattr(client,'request',request)
    with pytest.raises(PlatformError,match='code'):
        client.sign({'id':'901','kind':'normal','course':{'courseId':'101','clazzId':'201'}},{},'姓名')
    assert not any('/stuSignajax' in url for url in urls)


def test_manual_challenge_is_account_bound_and_does_not_leak_proof(browser,app,monkeypatch):
    account=browser.login();other=browser.login('13800000002')
    base=f"/accounts/{account['id']}";browser.get(base+'/activities')
    observed=[]
    def sign(client,activity,supplied,name):
        observed.append(supplied)
        if supplied.get('_verification',{}).get('validate')=='private-offline-proof':return '签到成功（离线）'
        raise CaptchaRequired(challenge(),'private-offline-enc2')
    monkeypatch.setattr(FakeClient,'sign',sign)
    result=browser.send(base+'/sign',{'activity_id':'901'})
    assert result.status_code==409 and result.json['code']=='verification_required'
    public=result.json['verification'];nonce=public['id']
    serialized=json.dumps(result.json)
    assert 'private-offline' not in serialized
    assert browser.send(base+'/sign',{'activity_id':'901','verification_id':'forged-proof'}).status_code==400
    assert browser.send(f"/accounts/{other['id']}/verification/{nonce}",{'action':'check','x':66}).status_code==400
    assert not any(e['kind']=='sign_success' for e in browser.get('/bootstrap').json['events'])
    monkeypatch.setattr('server.sign_captcha.check_challenge',lambda *a:'private-offline-proof')
    verified=browser.send(base+'/verification/'+nonce,{'action':'check','x':66})
    assert verified.status_code==200 and 'private-offline' not in json.dumps(verified.json)
    result=browser.send(base+'/sign',{'activity_id':'901','verification_id':nonce})
    assert result.status_code==200
    assert observed[-1]['_verification']=={'validate':'private-offline-proof','enc2':'private-offline-enc2'}
    assert nonce not in app.extensions['signing'].challenges


def test_challenge_expiry_and_cancel_revoke_verification(browser,app,monkeypatch):
    account=browser.login();base=f"/accounts/{account['id']}";browser.get(base+'/activities')
    monkeypatch.setattr(FakeClient,'sign',lambda *a:(_ for _ in ()).throw(CaptchaRequired(challenge())))
    nonce=browser.send(base+'/sign',{'activity_id':'901'}).json['verification']['id']
    assert browser.send(base+'/verification/'+nonce,{'action':'cancel'}).status_code==200
    assert browser.send(base+'/verification/'+nonce,{'action':'check','x':66}).status_code==400
    nonce=browser.send(base+'/sign',{'activity_id':'901'}).json['verification']['id']
    app.extensions['signing'].challenges[nonce]['expires']=-1
    assert browser.send(base+'/sign',{'activity_id':'901','verification_id':nonce}).status_code==400


def test_camera_forwards_only_saved_location(browser,monkeypatch):
    from tests.test_location_presets import SCHOOL
    from tests.test_camera_sign import QR
    account=browser.login();browser.send('/location-presets',{'config':SCHOOL})
    original=FakeClient.activities
    monkeypatch.setattr(FakeClient,'activities',lambda c,courses:[{**original(c,courses)[0],'id':'902','kind':'qr'}])
    seen=[]
    monkeypatch.setattr(FakeClient,'sign',lambda c,a,p,n:seen.append(p) or '成功')
    result=browser.send(f"/accounts/{account['id']}/camera-sign",{'qr':QR,'location':{'school':'测试学校','name':'A教学楼'}})
    assert result.status_code==200 and 'latitude' in seen[0] and seen[0]['address']=='测试学校 · A教学楼'


def test_parallel_users_keep_separate_challenges(browser,app,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from tests.conftest import Browser
    first=browser.login();second=browser.login('13800000002')
    other=Browser(app);other.admin_login()
    browser.get(f"/accounts/{first['id']}/activities");other.get(f"/accounts/{second['id']}/activities")
    monkeypatch.setattr(FakeClient,'sign',lambda *a:(_ for _ in ()).throw(CaptchaRequired(challenge())))
    with ThreadPoolExecutor(max_workers=2) as pool:
        one=pool.submit(browser.send,f"/accounts/{first['id']}/sign",{'activity_id':'901'})
        two=pool.submit(other.send,f"/accounts/{second['id']}/sign",{'activity_id':'901'})
        results=[one.result(),two.result()]
    assert all(r.status_code==409 for r in results)
    ids=[r.json['verification']['id'] for r in results]
    assert ids[0]!=ids[1] and all(key in app.extensions['signing'].challenges for key in ids)
