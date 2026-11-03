"""Real JPEG recognition + server-owned signing against fake accounts only."""
import io
import json
import threading
import time

import pytest
import qrcode
from PIL import Image, ImageFilter, ImageOps

from server.qr_frames import FrameDetector, FrameBusy
from tests.conftest import Browser, FakeClient
from tests.test_camera_sign import run_node
from tests.test_scan_links import grant, claim, QR, HEADERS


def jpeg(text=QR, variation='plain'):
    image=qrcode.make(text,box_size=7).get_image().convert('RGB')
    if variation=='rotate':image=image.rotate(19,expand=True,fillcolor='white')
    if variation=='invert':image=ImageOps.invert(image)
    if variation=='blur':image=image.filter(ImageFilter.GaussianBlur(.6))
    if variation=='offcenter':
        frame=Image.new('RGB',(1600,900),'#a3a4b8');frame.paste(image,(1060,280));image=frame
    output=io.BytesIO();image.save(output,format='JPEG',quality=70)
    return output.getvalue()


def wait_for(action, predicate, timeout=5):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        result=action()
        if predicate(result):return result
        time.sleep(.02)
    pytest.fail('Server camera result was not ready')


def post_frame(client,path,frame,headers):
    return client.post(path,data=frame,content_type='image/jpeg',headers=headers)


@pytest.mark.parametrize('variation',['plain','rotate','invert','blur','offcenter'])
def test_native_decoder_returns_real_corners_for_difficult_jpeg(variation):
    result=FrameDetector().detect(jpeg(variation=variation),'offline')
    assert result['text']==QR and len(result['corners'])==4
    assert all(0<=p['x']<=result['width'] and 0<=p['y']<=result['height'] for p in result['corners'])


def test_empty_invalid_large_frames_and_rate_are_bounded():
    detector=FrameDetector()
    for index,content in enumerate((b'',b'not jpeg',b'x'*(768*1024+1))):
        with pytest.raises(ValueError):detector.detect(content,str(index))
    image=io.BytesIO();Image.new('RGB',(2400,2400),'white').save(image,format='JPEG')
    with pytest.raises(ValueError):detector.detect(image.getvalue(),'oversize-pixels')
    detector.detect(jpeg(),'rate')
    with pytest.raises(FrameBusy):detector.detect(jpeg(),'rate')
    detector.slots.acquire();detector.slots.acquire()
    try:
        with pytest.raises(FrameBusy):detector.detect(jpeg(),'busy')
    finally:detector.slots.release();detector.slots.release()


def test_grant_phone_sends_jpeg_only_server_signs_and_returns_no_qr_data(grant):
    client,headers,_=claim(grant)
    start=client.post('/scan-api/start',json={},headers=headers)
    assert start.status_code==200 and start.json['state']=='running'
    response=post_frame(client,'/scan-api/frame',jpeg(),headers)
    assert response.status_code==202
    result=wait_for(lambda:client.get('/scan-api/status',headers=headers),lambda r:r.status_code==200 and r.json.get('terminal'))
    assert result.json['state']=='completed'
    assert result.json['accounts'][0]['state']=='succeeded' and FakeClient.sign_calls==1
    for data in (start.json,response.json,result.json):
        serialized=json.dumps(data)
        assert QR not in serialized and 'OFFLINE_SCAN_TOKEN' not in serialized
        assert grant['accounts'][0]['id'] not in serialized
        assert 'activity_id' not in serialized and 'enc' not in data and 'text' not in data
    assert post_frame(client,'/scan-api/frame',jpeg(),headers).status_code==410
    assert client.post('/scan-api/start',json={},headers=headers).status_code==410
    assert client.get('/api/bootstrap').status_code==401
    assert client.get('/api/devices').status_code==401


def test_grant_rejects_other_activity_and_cancel_revokes_background_worker(grant):
    client,headers,_=claim(grant)
    client.post('/scan-api/start',json={},headers=headers)
    run_id=next(iter(grant['app'].extensions['camera_streams'].runs))
    run=grant['app'].extensions['camera_streams'].runs[run_id]
    post_frame(client,'/scan-api/frame',jpeg(QR.replace('id=902','id=999')),headers)
    wait_for(lambda:run.snapshot(),lambda r:'所选活动' in r['message'])
    assert FakeClient.sign_calls==0
    grant['links'].revoke('10000001')
    wait_for(lambda:run.snapshot(),lambda r:r['terminal'])
    assert client.get('/scan-api/status',headers=headers).status_code==410
    assert FakeClient.sign_calls==0


def test_grant_checks_origin_csrf_and_frame_type(grant):
    client,headers,_=claim(grant)
    assert client.post('/scan-api/start',json={'account_ids':['foreign']},headers=headers).status_code==400
    client.post('/scan-api/start',json={},headers=headers)
    assert post_frame(client,'/scan-api/frame',jpeg(),{**headers,'Origin':'https://evil.invalid'}).status_code==403
    assert post_frame(client,'/scan-api/frame',jpeg(),{**headers,'X-Scan-CSRF':'bad'}).status_code==410
    assert client.post('/scan-api/frame',json={},headers=headers).status_code==400
    assert post_frame(client,'/scan-api/frame',b'x'*(768*1024+1),headers).status_code==400
    assert FakeClient.sign_calls==0


def test_stop_drops_queued_frames_and_results_remain_readonly(grant):
    client,headers,_=claim(grant)
    start=client.post('/scan-api/start',json={},headers=headers)
    run=grant['app'].extensions['camera_streams'].runs[start.json['id']]
    assert client.post('/scan-api/close',json={},headers=headers).status_code==200
    assert run.pending is None and run.qr is None
    assert client.get('/scan-api/status',headers=headers).json['state']=='stopped'
    assert post_frame(client,'/scan-api/frame',jpeg(),headers).status_code==410


def test_idle_and_absolute_deadline_stop_without_platform_requests(grant):
    client,headers,_=claim(grant)
    start=client.post('/scan-api/start',json={},headers=headers)
    run=grant['app'].extensions['camera_streams'].runs[start.json['id']]
    run.frame_at-=11;run.wake.set()
    wait_for(lambda:run.snapshot(),lambda r:r['terminal'])
    assert run.state=='stopped' and FakeClient.sign_calls==0
    assert client.get('/scan-api/status',headers=headers).json['state']=='stopped'


def test_server_queue_five_accounts_overlap_and_use_their_own_cookies(browser,app,monkeypatch):
    accounts=[browser.login(f'1380000000{i}') for i in range(1,6)]
    browser.send('/preferences',{'camera_concurrency':5},'PUT')
    original=FakeClient.activities
    monkeypatch.setattr(FakeClient,'activities',lambda c,courses:[{**original(c,courses)[0],'kind':'qr','id':'902'}])
    barrier=threading.Barrier(5);seen=[]
    def sign(client,*args):
        barrier.wait(timeout=4);seen.append(client.jar[0]['value']);return 'offline success'
    monkeypatch.setattr(FakeClient,'sign',sign)
    result=browser.send('/camera-stream',{'account_ids':[a['id'] for a in accounts]})
    assert result.status_code==200
    run_id=result.json['id'];headers={'Origin':'http://localhost','X-CSRF-Token':browser.csrf}
    response=post_frame(browser.client,f'/api/camera-stream/{run_id}/frame',jpeg(),headers)
    assert response.status_code==202
    result=wait_for(lambda:browser.get('/camera-stream/'+run_id).json,lambda r:r['terminal'])
    assert result['state']=='completed' and len(seen)==5 and len(set(seen))==5
    outsider=Browser(app);outsider.admin_login()
    assert outsider.get('/camera-stream/'+run_id).status_code==404


def test_admin_stream_requires_auth_csrf_owned_ids_and_binary_frames(browser,app):
    assert browser.send('/camera-stream',{'account_ids':['missing']}).status_code==401
    account=browser.login()
    assert browser.send('/camera-stream',{'account_ids':['missing']}).status_code==404
    assert browser.send('/camera-stream',{'account_ids':[]}).status_code==400
    start=browser.send('/camera-stream',{'account_ids':[account['id']]})
    path='/api/camera-stream/'+start.json['id']+'/frame'
    assert post_frame(browser.client,path,jpeg(),{}).status_code==403
    assert browser.client.post(path,json={},headers={'X-CSRF-Token':browser.csrf}).status_code==400
    assert browser.send('/camera-stream/'+start.json['id']+'/stop').status_code==200


def test_server_keeps_only_latest_frame_and_eleventh_failure_rotates(browser,app,monkeypatch):
    accounts=[browser.login(),browser.login('13800000002')]
    run=app.extensions['camera_streams'].start(('offline','rotation'),[
        dict(id=a['id'],owner=app.extensions['napcat'].owner,name=a['name']) for a in accounts])
    # Exercise queue logic without creating any outgoing platform request.
    run.finish('stopped','offline setup');run.thread.join(timeout=2)
    run.state='running';run.activity_id='902';run.qr=(QR,time.monotonic())
    run.upload(b'first');run.upload(b'last');assert run.pending[0]==b'last'
    monkeypatch.setattr(app.extensions['camera_streams'].camera,'submit',lambda *a,**k:(_ for _ in ()).throw(ValueError('offline')))
    for _ in range(11):
        run.manager.sign_slots.acquire();run.inflight+=1
        run.entries[accounts[0]['id']]['state']='submitting';run.entries[accounts[0]['id']]['attempts']+=1
        run.sign(accounts[0]['id'],QR)
    assert run.order==[accounts[1]['id'],accounts[0]['id']]
    assert run.entries[accounts[0]['id']]['failures']==11
    run.finish('stopped','done')


def test_push_only_browser_contract():
    run_node("require('./tests/server_camera_controller.cjs')")


def test_scoped_queue_records_safe_reason_after_activity_ends(grant, monkeypatch):
    from server.chaoxing import SignRequirement

    def ended(*args, **kwargs):
        raise SignRequirement('activity_ended', 'PRIVATE_PLATFORM_RESPONSE')

    app = grant['app']
    monkeypatch.setattr(app.extensions['camera_streams'].camera, 'submit', ended)
    client, headers, _ = claim(grant)
    assert client.post('/scan-api/start', json={'input':'native'}, headers=headers).status_code == 200
    assert client.post('/scan-api/qr', json={'qr':QR}, headers=headers).status_code == 202
    result = wait_for(lambda: client.get('/scan-api/status', headers=headers).json, lambda value: value.get('terminal'))
    assert result['state'] == 'attention'
    assert '已截止' in result['accounts'][0]['message']
    events = wait_for(lambda: grant['store'].events(grant['owner']), lambda rows: any(row['kind']=='sign_attention' for row in rows))
    assert '已截止' in next(row['message'] for row in events if row['kind']=='sign_attention')
    assert 'PRIVATE_PLATFORM_RESPONSE' not in repr((result, events))


def test_live_zoom_slider_changes_preview_and_encoded_frame_together():
    run_node("require('./tests/camera_zoom_controller.cjs')")
