"""No real photos, uploads, liveness checks, or attendance requests."""
import base64
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from server.chaoxing import ChaoxingClient, SignRequirement, CaptchaRequired
from server.sign_faces import photo_bytes, upload_photo, face_context
from tests.conftest import FakeClient, Browser
from tests.test_platform import response
from tests.test_sign_verification import challenge


def image_data():
    image=Image.new('RGB',(160,200),(70,100,140));out=io.BytesIO();image.save(out,format='JPEG')
    return 'data:image/jpeg;base64,'+base64.b64encode(out.getvalue()).decode()


@pytest.fixture
def face_adapter(monkeypatch):
    original=FakeClient.sign_requirements
    monkeypatch.setattr(FakeClient,'sign_requirements',lambda c,a:{**original(c,a),'needs_face':True})
    calls=[]
    def upload(client,data):calls.append((client.jar[0]['value'],data));return 'private-photo-object'
    monkeypatch.setattr('server.sign_faces.upload_photo',upload)
    monkeypatch.setattr('server.sign_faces.face_context',lambda c,a,o:{'object_id':o,'enc':'private-face-context'})
    return calls


def test_current_activity_formats_and_sign_out_relation(monkeypatch):
    client=ChaoxingClient()
    rows=[{'id':901,'type':74,'status':1,'otherId':2},{'id':902,'type':74,'status':1,'otherId':0}]
    def request(method,url,**kwargs):
        if url.endswith('/activelist'):return response(payload={'data':{'activeList':rows,'ext':{'token':'private-ext'}}})
        return response(payload={'data':{'otherId':2,'signInId':900}} if kwargs['params']['activeId']=='901' else {'data':{'otherId':0}})
    monkeypatch.setattr(client,'request',request)
    result=client.activities([{'key':'101:201','courseId':'101','clazzId':'201'}])
    assert [(a['id'],a['phase']) for a in result]==[('901','out'),('902','in')]
    assert 'private-ext' in result[0]['_ext']


def test_sign_in_and_out_keep_separate_records_and_events(browser,app,monkeypatch):
    account=browser.login();owner=app.extensions['napcat'].owner
    original=FakeClient.activities
    monkeypatch.setattr(FakeClient,'activities',lambda c,courses:[original(c,courses)[0],{**original(c,courses)[0],'id':'902','phase':'out'}])
    app.extensions['store'].mark_signed(owner,account['id'],'901')
    browser.get(f"/accounts/{account['id']}/activities")
    result=browser.send(f"/accounts/{account['id']}/sign",{'activity_id':'902'})
    assert result.status_code==200 and result.json['phase']=='out' and FakeClient.sign_calls==1
    assert browser.send(f"/accounts/{account['id']}/sign",{'activity_id':'901'}).json['duplicate'] is True
    assert any(e['kind']=='sign_out_success' for e in browser.get('/bootstrap').json['events'])


def test_related_activity_requires_published_owned_active_target(browser,monkeypatch):
    account=browser.login();base=f"/accounts/{account['id']}";original=FakeClient.activities
    monkeypatch.setattr(FakeClient,'activities',lambda c,courses:[original(c,courses)[0],{**original(c,courses)[0],'id':'902','phase':'out'}])
    original_requirements=FakeClient.sign_requirements
    monkeypatch.setattr(FakeClient,'sign_requirements',lambda c,a:{**original_requirements(c,a),'sign_out_id':'902' if a['id']=='901' else None})
    browser.get(base+'/activities')
    assert browser.send(base+'/activities/901/related',{'relation':'out'}).json['activity']['id']=='902'
    assert browser.send(base+'/activities/902/related',{'relation':'out'}).status_code==400
    assert browser.send(base+'/activities/not-owned/related',{'relation':'out'}).status_code==400
    assert browser.get(base+'/activities/901/requirements?source=group').status_code==400
    assert FakeClient.sign_calls==0


def test_confirm_only_marks_an_explicit_platform_acknowledgement(browser,monkeypatch):
    account=browser.login();base=f"/accounts/{account['id']}";browser.get(base+'/activities')
    result=browser.send(base+'/activities/901/confirm')
    assert result.status_code==200 and result.json['signed'] is False
    monkeypatch.setattr(FakeClient,'sign_confirmed',lambda c,a:True)
    result=browser.send(base+'/activities/901/confirm')
    assert result.json['signed'] is True and FakeClient.sign_calls==0
    assert browser.send(base+'/sign',{'activity_id':'901'}).json['duplicate'] is True
    monkeypatch.setattr(FakeClient,'courses',lambda c:[])
    assert browser.send(base+'/activities/901/confirm').status_code==400


@pytest.mark.parametrize('value',['not-an-image','data:image/png;base64,AAAA','data:image/jpeg;base64,AAAA','data:image/jpeg;base64,'+'A'*900001],ids=['text','png','invalid-jpeg','too-large'])
def test_invalid_photo_never_becomes_a_face_context(value):
    with pytest.raises(ValueError):photo_bytes(value)


def test_photos_are_reencoded_without_exif():
    normalized=photo_bytes(image_data())
    with Image.open(io.BytesIO(normalized)) as picture:
        assert picture.format=='JPEG' and picture.size==(160,200) and not picture.getexif()


def test_upload_uses_the_selected_account_and_face_does_not_claim_liveness(monkeypatch):
    client=ChaoxingClient();client.session.cookies.set('_uid','111',domain='.chaoxing.com');calls=[]
    def request(method,url,**kwargs):
        calls.append((method,url,kwargs))
        if url.endswith('/uservalid'):return response(payload={'_token':'private-cloud-token'})
        if url.endswith('/upload'):return response(payload={'objectId':'photo-object-123'})
        return response(payload={'enc':'private-face-enc'})
    monkeypatch.setattr(client,'request',request)
    object_id=upload_photo(client,b'jpeg-test-content')
    context=face_context(client,'901',object_id)
    assert calls[1][2]['data']['puid']=='111' and calls[1][2]['files']['file'][1]==b'jpeg-test-content'
    fields=json.loads(calls[2][2]['params']['faceResult'])
    assert fields['LiveDetectionStatus']==0 and fields['collectStatus']==1 and 'signToken' not in fields
    assert context['object_id']=='photo-object-123'
    monkeypatch.setattr(client,'request',lambda *a,**k:response(payload={'result':False,'enc':'must-not-accept'}))
    with pytest.raises(SignRequirement) as rejected:face_context(client,'901',object_id)
    assert rejected.value.code=='official_face_required'


def test_face_upload_needs_consent_auth_csrf_and_activity(browser,app,face_adapter):
    assert browser.send('/accounts/unknown/face',{}).status_code==401
    account=browser.login();base=f"/accounts/{account['id']}";browser.get(base+'/activities')
    payload={'activity_id':'901','source':'course','image':image_data(),'consent':False}
    assert browser.send(base+'/face',payload).status_code==400
    assert browser.send(base+'/face',{**payload,'consent':True,'activity_id':'999'}).status_code==400
    assert browser.client.post('/api'+base+'/face',json={**payload,'consent':True}).status_code==403
    assert not face_adapter


def test_face_context_is_ephemeral_bound_and_consumed(browser,app,monkeypatch,face_adapter):
    account=browser.login();other=browser.login('13800000002');base=f"/accounts/{account['id']}"
    browser.get(base+'/activities');browser.get(f"/accounts/{other['id']}/activities")
    result=browser.send(base+'/face',{'activity_id':'901','source':'course','image':image_data(),'consent':True})
    assert result.status_code==200 and 'private-' not in json.dumps(result.json)
    nonce=result.json['face_id'];assert face_adapter[0][0]=='13800000001'
    assert browser.send(f"/accounts/{other['id']}/sign",{'activity_id':'901','face_id':nonce}).status_code==400
    seen=[]
    monkeypatch.setattr(FakeClient,'sign',lambda c,a,p,n:seen.append(p) or '签到成功')
    assert browser.send(base+'/sign',{'activity_id':'901','face_id':nonce}).status_code==200
    assert seen[0]['_face']['object_id']=='private-photo-object'
    assert nonce not in app.extensions['signing'].faces.records
    assert not list(Path(app.config['DATA_DIR']).glob('*.jpg'))


def test_face_and_slider_contexts_can_resume_together(browser,app,monkeypatch,face_adapter):
    account=browser.login();base=f"/accounts/{account['id']}";browser.get(base+'/activities')
    def sign(client,activity,payload,name):
        if not payload.get('_face'):raise SignRequirement('face_required','需要本人照片','private-face-enc2')
        if not payload.get('_verification'):raise CaptchaRequired(challenge(),'private-captcha-enc2')
        return '签到成功'
    monkeypatch.setattr(FakeClient,'sign',sign)
    assert browser.send(base+'/sign',{'activity_id':'901'}).json['code']=='face_required'
    nonce=browser.send(base+'/face',{'activity_id':'901','image':image_data(),'consent':True}).json['face_id']
    result=browser.send(base+'/sign',{'activity_id':'901','face_id':nonce})
    assert result.status_code==409
    verification=result.json['verification']['id']
    monkeypatch.setattr('server.sign_captcha.check_challenge',lambda *a:'private-proof')
    browser.send(base+'/verification/'+verification,{'action':'check','x':66})
    result=browser.send(base+'/sign',{'activity_id':'901','face_id':nonce,'verification_id':verification})
    assert result.status_code==200 and nonce not in app.extensions['signing'].faces.records


def test_expired_or_cancelled_photo_context_cannot_be_submitted(browser,app,face_adapter):
    account=browser.login();base=f"/accounts/{account['id']}";browser.get(base+'/activities')
    def new():return browser.send(base+'/face',{'activity_id':'901','image':image_data(),'consent':True}).json['face_id']
    nonce=new();app.extensions['signing'].faces.records[nonce]['expires']=0
    assert browser.send(base+'/sign',{'activity_id':'901','face_id':nonce}).status_code==400
    nonce=new();assert browser.send(base+'/face/'+nonce+'/cancel').status_code==200
    assert browser.send(base+'/sign',{'activity_id':'901','face_id':nonce}).status_code==400


def test_face_capture_browser_contract():
    from tests.test_camera_sign import run_node
    run_node("require('./tests/face_controller.cjs')")
