import json
import threading
import time

import pytest

from server.chaoxing import SignRequirement
from tests.conftest import Browser,FakeClient
from tests.test_server_camera import wait_for
from tests.test_external_api import mint,call
from tests.test_camera_sign import run_node


def activity(kind='normal',phase='in',**changes):
    return dict(id='901',kind=kind,phase=phase,title='offline activity',course=FakeClient().courses()[0],photo=False,**changes)


def start(browser,users,**changes):
    return browser.send('/batch-sign',{'account_ids':[a['id'] for a in users],'activity_id':'901','kind':'normal',**changes})


def final(browser,run_id):
    return wait_for(lambda:browser.get('/batch-sign/'+run_id).json,lambda result:result['terminal'])


@pytest.mark.parametrize('kind',['normal','gesture','code','location'])
def test_one_batch_submits_all_eligible_users_with_own_cookies(browser,app,monkeypatch,kind):
    users=[browser.login(),browser.login('13800000002'),browser.login('13800000003')]
    monkeypatch.setattr(FakeClient,'activities',lambda *a:[activity(kind)])
    seen=[]
    monkeypatch.setattr(FakeClient,'sign',lambda c,a,p,n:seen.append((c.jar[0]['value'],p,n)) or 'offline success')
    params={}
    if kind in {'gesture','code'}:params['code']='00123'
    if kind=='location':
        browser.send('/location-presets',{'config':{'school':'school','address':'school position','coordinate_system':'bd09','points':[{'name':'building','longitude':116.2,'latitude':40.2}]}})
        params['location']={'school':'school','name':'building'}
    result=start(browser,users,kind=kind,**params);assert result.status_code==200,result.json
    result=final(browser,result.json['id']);assert result['state']=='completed'
    assert len(seen)==3 and len({row[0] for row in seen})==3
    assert all(a['state']=='succeeded' for a in result['accounts'])
    if kind in {'gesture','code'}:assert all(row[1]['code']=='00123' for row in seen)
    if kind=='location':assert all(row[1]['address']=='school position' and row[1]['latitude']=='40.200000' for row in seen)
    assert not any(key in json.dumps(result) for key in ('00123','latitude','longitude','13800000001','private-session'))
    assert browser.get('/batch-sign/current').json['run']['id']==result['id']


@pytest.mark.parametrize('changes',[{'kind':'qr'},{'kind':[]},{'phase':[]},{'phase':'bad'},{'activity_id':True},
                                   {'kind':'gesture','code':True},{'kind':'gesture','code':'ABC'},
                                   {'kind':'location'},{'location':{}},{'extra':1},{'source':'group'}])
def test_invalid_batches_cannot_submit(browser,changes):
    user=browser.login()
    assert start(browser,[user],**changes).status_code==400
    assert FakeClient.sign_calls==0


def test_ineligible_users_skip_and_method_change_does_not_submit(browser,monkeypatch):
    users=[browser.login(),browser.login('13800000002')]
    monkeypatch.setattr(FakeClient,'activities',lambda c,courses:[activity()] if c.jar[0]['value'].endswith('1') else [])
    result=start(browser,users);result=final(browser,result.json['id'])
    assert [r['state'] for r in result['accounts']]==['succeeded','skipped'] and FakeClient.sign_calls==1
    another=browser.login('13800000003');calls=iter([[activity()],[activity('qr')]])
    monkeypatch.setattr(FakeClient,'activities',lambda *a:next(calls))
    result=final(browser,start(browser,[another]).json['id'])
    assert result['accounts'][0]['state']=='attention' and FakeClient.sign_calls==1


def test_need_attention_and_rejected_location_remain_per_user(browser,monkeypatch):
    users=[browser.login(),browser.login('13800000002')]
    def rejected(client,*args):
        raise SignRequirement('location_rejected' if client.jar[0]['value'].endswith('1') else 'face_required','PRIVATE_RESPONSE')
    monkeypatch.setattr(FakeClient,'sign',rejected)
    result=final(browser,start(browser,users).json['id'])
    assert [r['state'] for r in result['accounts']]==['failed','attention']
    assert result['accounts'][0]['code']=='location_rejected'
    assert 'PRIVATE_RESPONSE' not in json.dumps(result)


def test_bounded_concurrency_stop_and_owner_isolation(browser,app,monkeypatch):
    users=[browser.login('1380000000'+str(i)) for i in range(1,8)]
    browser.send('/preferences',{'camera_concurrency':3},'PUT')
    release=threading.Event();entered=threading.Event();seen=[];lock=threading.Lock()
    def sign(client,*args):
        with lock:
            seen.append(client.jar[0]['value'])
            if len(seen)==3:entered.set()
        assert release.wait(5);return 'offline'
    monkeypatch.setattr(FakeClient,'sign',sign)
    result=start(browser,users);run_id=result.json['id']
    try:
        assert entered.wait(3) and len(seen)==3
        assert start(browser,users).status_code==400
        outsider=Browser(app);outsider.admin_login()
        assert outsider.get('/batch-sign/'+run_id).status_code==404
        assert outsider.send('/batch-sign/'+run_id+'/stop').status_code==404
        assert outsider.get('/batch-sign/current').json['run'] is None
        assert browser.send('/batch-sign/'+run_id+'/stop').status_code==200
    finally:release.set()
    result=final(browser,run_id)
    assert result['state']=='stopped' and len(seen)==3
    assert len([r for r in result['accounts'] if r['state']=='cancelled'])==4


def test_sign_api_scope_and_revocation_cancel_pending_work(app,browser,monkeypatch):
    user=browser.login()
    read,_=mint(app,browser,scopes=['read'])
    assert call(app,read,'/batch-sign/current').status_code==403
    assert call(app,read,'/batch-sign','POST',{'account_ids':[user['id']],'activity_id':'901','kind':'normal'}).status_code==403
    headers,key=mint(app,browser,scopes=['sign:write']);release=threading.Event();entered=threading.Event()
    def activities(*args):entered.set();assert release.wait(5);return [activity()]
    monkeypatch.setattr(FakeClient,'activities',activities)
    result=call(app,headers,'/batch-sign','POST',{'account_ids':[user['id']],'activity_id':'901','kind':'normal'})
    assert result.status_code==200 and 'Set-Cookie' not in result.headers
    try:
        assert entered.wait(3)
        assert browser.send('/access/keys/'+key['key']['id'],{},'DELETE').status_code==200
    finally:release.set()
    wait_for(lambda:next(iter(app.extensions['batch_signs'].runs.values())).snapshot(),lambda r:r['terminal'])
    assert FakeClient.sign_calls==0


def test_frontend_all_modes_and_filtered_explicit_payload():
    run_node("require('./tests/batch_sign_controller.cjs')")
    run_node("require('./tests/device_position.cjs')")


def test_browser_fix_can_be_used_for_location_batch(browser,monkeypatch):
    user=browser.login();seen=[]
    monkeypatch.setattr(FakeClient,'activities',lambda *a:[activity('location')])
    monkeypatch.setattr(FakeClient,'sign',lambda c,a,p,n:seen.append(p) or 'offline')
    result=start(browser,[user],kind='location',device_location=dict(latitude=31.2,longitude=121.4,accuracy=15,captured_at=time.time()))
    assert result.status_code==200
    assert final(browser,result.json['id'])['state']=='completed'
    assert seen[0]['latitude']!='31.200000' and '设备当前位置' in seen[0]['address']
