"""Native input shares the existing server queue and never grants broader authority."""
import json
import time

import pytest

from tests.conftest import Browser, FakeClient
from tests.test_scan_links import grant,claim,QR
from tests.test_server_camera import wait_for
from tests.test_camera_sign import run_node


def test_native_one_use_grant_signs_on_server_and_returns_private_results(grant):
    client,headers,_=claim(grant)
    start=client.post('/scan-api/start',json={'input':'native'},headers=headers)
    assert start.status_code==200 and start.json['input']=='native'
    response=client.post('/scan-api/qr',json={'qr':QR},headers=headers)
    assert response.status_code==202
    result=wait_for(lambda:client.get('/scan-api/status',headers=headers),lambda r:r.json.get('terminal'))
    assert result.json['state']=='completed' and FakeClient.sign_calls==1
    assert QR not in json.dumps(result.json) and grant['accounts'][0]['id'] not in json.dumps(result.json)
    assert client.post('/scan-api/qr',json={'qr':QR},headers=headers).status_code==410
    assert client.get('/api/bootstrap').status_code==401


def test_native_grant_rejects_scope_origin_csrf_and_wrong_mode(grant):
    client,headers,_=claim(grant)
    assert client.post('/scan-api/start',json={'input':[]},headers=headers).status_code==400
    client.post('/scan-api/start',json={'input':'native'},headers=headers)
    assert client.post('/scan-api/qr',json={'qr':QR.replace('902','999')},headers=headers).status_code==400
    assert client.post('/scan-api/qr',json={'qr':QR,'account_id':'foreign'},headers=headers).status_code==400
    assert client.post('/scan-api/qr',json={'qr':QR},headers={**headers,'Origin':'https://evil.invalid'}).status_code==403
    assert client.post('/scan-api/qr',json={'qr':QR},headers={**headers,'X-Scan-CSRF':'bad'}).status_code==410
    assert client.post('/scan-api/frame',data=b'jpeg',content_type='image/jpeg',headers=headers).status_code==400
    assert FakeClient.sign_calls==0


def test_native_admin_queue_auth_ownership_and_cancel(browser,app,monkeypatch):
    account=browser.login()
    assert browser.send('/camera-stream',{'account_ids':[account['id']],'input':{}}).status_code==400
    start=browser.send('/camera-stream',{'account_ids':[account['id']],'input':'native'})
    path='/camera-stream/'+start.json['id']+'/qr'
    outsider=Browser(app);outsider.admin_login()
    assert outsider.send(path,{'qr':QR}).status_code==404
    assert browser.send(path,{'qr':''}).status_code==202
    assert browser.send(path,{'qr':''}).status_code==429
    assert browser.send(path,{'qr':'x'*4097}).status_code==400
    assert browser.send('/camera-stream/'+start.json['id']+'/stop').status_code==200
    assert browser.send(path,{'qr':QR}).json['state']=='stopped'
    assert FakeClient.sign_calls==0


def test_native_input_never_reuses_code_after_no_detection_or_stale_capture(browser,app):
    account=browser.login()
    run=app.extensions['camera_streams'].start(('offline','native'),[
        dict(id=account['id'],owner=app.extensions['napcat'].owner,name='offline')],input_mode='native')
    run.finish('stopped','test');run.thread.join(timeout=2);run.state='running'
    run.native({'qr':QR});assert run.qr[0]==QR
    run.native_at-=1;run.native({'qr':''});assert run.qr is None
    run.native_at-=1;run.native({'qr':QR});run.qr=(QR,time.monotonic()-2)
    run.dispatch();assert run.inflight==0 and FakeClient.sign_calls==0
    run.finish('stopped','test done')


def test_jpeg_session_rejects_native_injection(browser):
    account=browser.login()
    start=browser.send('/camera-stream',{'account_ids':[account['id']]})
    assert browser.send('/camera-stream/'+start.json['id']+'/qr',{'qr':QR}).status_code==400
    assert FakeClient.sign_calls==0


def test_android_phone_bridge_contract():
    run_node("require('./tests/android_camera_controller.cjs')")
    run_node("require('./tests/android_bridge.cjs')")
