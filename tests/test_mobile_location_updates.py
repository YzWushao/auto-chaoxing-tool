import hashlib
import json
import time
from unittest.mock import Mock

import pytest

from server.chaoxing import ChaoxingClient, SignRequirement
from server.device_location import device_location
from tests.test_platform import response, sign_response
from tests.test_scan_links import grant, QR
from tests.test_qq_scan_picker import picker
from tests.conftest import FakeClient
from tests.test_server_camera import wait_for


def fix(**changes):
    return dict(latitude=31.2,longitude=121.4,accuracy=12,captured_at=time.time(),**changes)


@pytest.mark.parametrize('provided,requires,expected',[(True,True,'location_rejected'),(False,True,'location_required'),(False,False,'location_required')])
def test_location_rejection_only_means_uploaded_location_was_rejected(monkeypatch,provided,requires,expected):
    client=ChaoxingClient();calls=[]
    def request(method,url,**kwargs):
        calls.append(url)
        if url.endswith('/getPPTActiveInfo'):return response(payload={'data':{'ifopenAddress':int(requires)}})
        return sign_response(url,'errorLocation_private_detail')
    monkeypatch.setattr(client,'request',request)
    supplied={'qr':'OFFLINE_ENC_123'}
    if provided:supplied.update(latitude=31.2,longitude=121.4,address='actual device position')
    with pytest.raises(SignRequirement) as error:
        client.sign({'id':'902','kind':'qr','course':{'courseId':'1','clazzId':'2'}},supplied,'offline')
    assert error.value.code==expected
    assert 'private_detail' not in str(error.value)
    assert any(url.endswith('/stuSignajax') for url in calls)==(provided or not requires)


@pytest.mark.parametrize('code,expected',[('location_rejected','pending'),('location_required','waiting')])
def test_rejected_location_stays_in_retry_queue_and_then_succeeds(browser,app,monkeypatch,code,expected):
    account=browser.login();streams=app.extensions['camera_streams']
    run=streams.start(('offline','location-retry'),[dict(id=account['id'],owner=app.extensions['napcat'].owner,name='offline')],retry_interval=.25)
    run.finish('stopped','setup');run.thread.join(timeout=2);run.state='running';run.activity_id='902'
    monkeypatch.setattr(streams.camera,'submit',Mock(side_effect=SignRequirement(code,'PRIVATE_RESPONSE')))
    streams.sign_slots.acquire();run.inflight=1
    before=time.monotonic();run.sign(account['id'],QR)
    item=run.entries[account['id']]
    assert item['state']==expected and item['next_retry']>=before+.25
    assert (account['id'] in run.order)==(expected=='pending')
    assert 'PRIVATE_RESPONSE' not in json.dumps(run.snapshot())
    if expected=='pending':
        assert item['retry_code']=='location_rejected' and item['failures']==1
        assert '上报失败' in item['message']
        submit=Mock(return_value={});monkeypatch.setattr(streams.camera,'submit',submit)
        executor=Mock();executor.submit.side_effect=lambda fn,*args:fn(*args)
        monkeypatch.setattr(streams,'executor',executor)
        run.qr=(QR,time.monotonic());run.dispatch();assert not submit.called
        item['next_retry']=0;run.dispatch()
        assert item['state']=='succeeded' and item['retry_code']=='' and submit.call_count==1
        monkeypatch.undo()
    run.finish('stopped','done')


@pytest.mark.parametrize('field,value',[('latitude',91),('longitude',181),('accuracy',0),('accuracy',True),('captured_at',0),('captured_at',float('nan')),('latitude',10**500)])
def test_invalid_or_stale_device_fixes_are_rejected(field,value):
    value_dict=fix();value_dict[field]=value
    with pytest.raises(ValueError):device_location(value_dict,input_mode='native')


def test_device_position_is_native_only_exclusive_and_converted(browser,app):
    account=browser.login();data=fix()
    for extras in ({},{'input':'jpeg'},{'input':'native','location':{'school':'missing','name':'missing'}}):
        assert browser.send('/camera-stream',{'account_ids':[account['id']],'device_location':data,**extras}).status_code==400
    start=browser.send('/camera-stream',{'input':'native','account_ids':[account['id']],'device_location':data})
    assert start.status_code==200
    internal=app.extensions['camera_streams'].runs[start.json['id']].location
    assert set(internal['device'])=={'latitude','longitude','address'}
    assert internal['device']['latitude']!='31.200000'
    assert 'latitude' not in json.dumps(start.json)
    browser.send('/camera-stream/'+start.json['id']+'/stop')


def test_device_fix_reaches_only_selected_account_signing(grant,monkeypatch):
    client,headers,status=picker(grant);alias=status.json['accounts'][0]['id'];seen=[]
    def sign(client,activity,supplied,name):
        seen.append((client.jar[0]['value'],supplied))
        return 'offline success'
    monkeypatch.setattr(FakeClient,'sign',sign)
    assert client.post('/scan-api/start',json={'input':'native','account_ids':[alias],'device_location':fix()},headers=headers).status_code==200
    client.post('/scan-api/qr',json={'qr':QR},headers=headers)
    result=wait_for(lambda:client.get('/scan-api/status',headers=headers).json,lambda value:value.get('terminal'))
    assert result['state']=='completed' and len(seen)==1
    assert seen[0][0]=='13800000001'
    assert set(seen[0][1]) >= {'latitude','longitude','address'}
    assert seen[0][1]['latitude']!='31.200000'
    assert '设备当前位置' in seen[0][1]['address']
    assert 'captured_at' not in json.dumps(result)


def test_qq_picker_accepts_device_fix_without_expanding_its_account_scope(grant):
    client,headers,status=picker(grant);alias=status.json['accounts'][0]['id']
    data={'input':'native','account_ids':[alias],'device_location':fix()}
    start=client.post('/scan-api/start',json=data,headers=headers)
    assert start.status_code==200
    assert start.json['accounts'][0]['id']==alias and len(start.json['accounts'])==1
    assert 'latitude' not in json.dumps(start.json)
    assert client.post('/scan-api/start',json={**data,'device_location':{**data['device_location'],'latitude':1}},headers=headers).status_code==400
    client.post('/scan-api/close',json={},headers=headers)


def test_public_update_feed_is_bounded_and_does_not_authenticate(browser,app,tmp_path):
    from flask import Flask
    from server.android_updates import install_android_updates
    test=Flask('update-test');test.config['ANDROID_RELEASE_DIR']=str(tmp_path)
    install_android_updates(test);client=test.test_client()
    assert client.get('/android/update.json').json=={'available':False}
    assert client.get('/android/latest.apk').status_code==404
    apk=b'not an installable APK; offline HTTP fixture';(tmp_path/'release.apk').write_bytes(apk)
    meta=dict(filename='release.apk',version_code=13,version_name='0.12.0',sha256=hashlib.sha256(apk).hexdigest(),notes='offline')
    (tmp_path/'release.json').write_text(json.dumps(meta))
    result=client.get('/android/update.json');assert result.json['size']==len(apk) and result.headers['Cache-Control']=='no-store'
    assert 'filename' not in result.json
    assert client.get('/android/latest.apk').data==apk
    for changes in ({'sha256':'0'*64},{'filename':'../secret.apk'},{'version_code':True},{'version_name':'bad\r\nheader'}):
        (tmp_path/'release.json').write_text(json.dumps({**meta,**changes}))
        assert client.get('/android/update.json').json=={'available':False}
        assert client.get('/android/latest.apk').status_code==404
