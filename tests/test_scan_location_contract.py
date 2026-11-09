import pytest

from tests.test_scan_links import grant, QR
from tests.test_qq_scan_picker import picker
from tests.test_mobile_location_updates import fix
from tests.test_school_location import SCHOOL
from tests.test_server_camera import wait_for, jpeg, post_frame
from tests.conftest import FakeClient
from tests.test_camera_sign import run_node


def test_browser_position_intent_is_not_lost_during_capability_refresh():
    run_node("require('./tests/scan_location_contract.cjs')")


@pytest.mark.parametrize('native',[False,True])
def test_admin_cannot_silently_start_without_requested_position(browser,app,native):
    account=browser.login()
    for flag in (True,1,'true'):
        result=browser.send('/camera-stream',dict(account_ids=[account['id']],report_location=flag,input='native' if native else 'jpeg'))
        assert result.status_code==400
        assert not app.extensions['camera_streams'].runs


@pytest.mark.parametrize('input_mode',['native','jpeg'])
@pytest.mark.parametrize('source',['device','preset'])
def test_position_intent_reaches_selected_signer_and_is_confirmed(grant,monkeypatch,input_mode,source):
    client,headers,status=picker(grant)
    application=grant['app']
    store=application.extensions['store']
    if source=='preset':
        # Issue a fresh picker after creating the preset so the location alias is scoped.
        owner=application.extensions['napcat'].owner
        store.import_location_presets(owner,[SCHOOL])
        client,headers,status=picker(grant)
    alias=status.json['accounts'][0]['id'];seen=[]
    monkeypatch.setattr(FakeClient,'sign',lambda self,activity,params,name:seen.append(params) or 'offline success')
    data=dict(input=input_mode,account_ids=[alias],report_location=True)
    if source=='device':data['device_location']=fix()
    else:data['location']=status.json['locations'][0]['id']
    start=client.post('/scan-api/start',json=data,headers=headers)
    assert start.status_code==200 and start.json['location_mode']==source
    assert 'latitude' not in str(start.json)
    if input_mode=='native':client.post('/scan-api/qr',json={'qr':QR},headers=headers)
    else:post_frame(client,'/scan-api/frame',jpeg(),headers)
    result=wait_for(lambda:client.get('/scan-api/status',headers=headers).json,lambda x:x.get('terminal'))
    assert result['state']=='completed' and len(seen)==1
    assert set(seen[0]) >= {'latitude','longitude','address'}


def test_qq_picker_refuses_location_intent_without_position(grant):
    client,headers,status=picker(grant)
    response=client.post('/scan-api/start',json=dict(account_ids=[status.json['accounts'][0]['id']],report_location=True),headers=headers)
    assert response.status_code==400
