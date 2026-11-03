import json
from urllib.parse import urlsplit

import pytest

from tests.conftest import FakeClient
from tests.test_scan_links import grant, claim, QR, HEADERS, QQ
from tests.test_server_camera import jpeg, post_frame, wait_for
from tests.test_camera_sign import run_node


def picker(grant):
    token = urlsplit(grant['links'].issue_picker(QQ)).fragment
    return claim(grant, token)


def test_picker_exposes_only_scoped_labels_and_opaque_user_aliases(grant, monkeypatch):
    monkeypatch.setattr(FakeClient, 'activities', lambda *a: pytest.fail('No discovery before scanning'))
    client, headers, result = picker(grant)
    value = result.json
    assert value['select_users'] and len(value['accounts']) == 2
    assert [a['name'] for a in value['accounts']] == ['手机尾号 0001', '手机尾号 0002']
    for a in value['accounts']:
        assert set(a) == {'id', 'name', 'status'} and len(a['id']) == 16
    encoded = json.dumps(value)
    for account in grant['accounts']:
        assert account['id'] not in encoded
    assert grant['owner'] not in encoded and '13800000001' not in encoded
    assert client.get('/api/accounts').status_code == 401
    assert client.get('/api/map/settings').status_code == 401
    assert FakeClient.sign_calls == 0


@pytest.mark.parametrize('selection', [None, [], ['foreign'], ['{real}'], [True], ['{first}', '{first}'], 'all'])
def test_selection_is_explicit_atomic_and_cannot_use_real_account_ids(grant, selection):
    client, headers, result = picker(grant)
    aliases = result.json['accounts']
    if isinstance(selection, list):
        selection = [grant['accounts'][0]['id'] if v == '{real}' else aliases[0]['id'] if v == '{first}' else v for v in selection]
    response = client.post('/scan-api/start', json={'input': 'native', 'account_ids': selection}, headers=headers)
    assert response.status_code == 400
    assert not grant['app'].extensions['camera_streams'].runs and not FakeClient.sign_calls
    assert client.post('/scan-api/submit', json={'qr': QR}, headers=headers).status_code == 400


@pytest.mark.parametrize('mode', ['jpeg', 'native'])
def test_only_manually_selected_user_signs_and_success_consumes_entry(grant, mode):
    client, headers, result = picker(grant)
    selected = [result.json['accounts'][1]['id']]
    start = client.post('/scan-api/start', json={'input': mode, 'account_ids': selected}, headers=headers)
    assert start.status_code == 200
    assert start.json['accounts'][0]['name'] == result.json['accounts'][1]['name']
    if mode == 'jpeg':
        assert post_frame(client, '/scan-api/frame', jpeg(), headers).status_code == 202
    else:
        assert client.post('/scan-api/qr', json={'qr': QR}, headers=headers).status_code == 202
    final = wait_for(lambda: client.get('/scan-api/status', headers=headers), lambda r: r.status_code == 200 and r.json.get('terminal'))
    assert final.json['state'] == 'completed' and FakeClient.sign_calls == 1
    assert not grant['store'].signed(grant['owner'], grant['accounts'][0]['id'], '902')
    assert grant['store'].signed(grant['owner'], grant['accounts'][1]['id'], '902')
    assert final.json['accounts'][0]['id'] == selected[0]
    assert client.post('/scan-api/start', json={'account_ids': selected}, headers=headers).status_code == 410
    assert client.get('/scan-api/session', headers=headers).status_code == 410


def test_selection_freezes_once_started_and_new_accounts_cannot_be_added(grant, browser):
    client, headers, result = picker(grant)
    aliases = [a['id'] for a in result.json['accounts']]
    later = browser.login('13800000003')
    assert client.post('/scan-api/start', json={'account_ids': [later['id']]}, headers=headers).status_code == 400
    start = client.post('/scan-api/start', json={'account_ids': aliases[:1], 'input': 'native'}, headers=headers)
    assert start.status_code == 200
    assert client.post('/scan-api/start', json={'account_ids': aliases, 'input': 'native'}, headers=headers).status_code == 400
    same = client.post('/scan-api/start', json={'account_ids': aliases[:1], 'input': 'native'}, headers=headers)
    assert same.status_code == 200 and same.json['id'] == start.json['id']
    assert not FakeClient.sign_calls


def test_picker_retains_first_qr_binding_and_supports_multi_user_selection(grant):
    client, headers, result = picker(grant)
    aliases = [a['id'] for a in result.json['accounts']]
    client.post('/scan-api/start', json={'account_ids': aliases, 'input': 'native'}, headers=headers)
    client.post('/scan-api/qr', json={'qr': QR}, headers=headers)
    wait_for(lambda: client.get('/scan-api/status', headers=headers), lambda r: r.status_code == 200 and r.json.get('terminal'))
    assert FakeClient.sign_calls == 2


def test_expired_user_is_displayed_but_cannot_be_selected(grant):
    client, headers, result = picker(grant)
    grant['store'].update_account(grant['owner'], grant['accounts'][0]['id'], status='expired')
    assert client.get('/scan-api/session', headers=headers).json['accounts'][0]['status'] == 'expired'
    assert client.post('/scan-api/start', json={'account_ids': [result.json['accounts'][0]['id']]}, headers=headers).status_code == 400


def test_picker_expiry_revoke_origin_and_exit_before_start(grant):
    client, headers, result = picker(grant)
    assert client.post('/scan-api/start', json={'account_ids': [result.json['accounts'][0]['id']]}, headers={**headers, 'Origin': 'https://foreign.invalid'}).status_code == 403
    assert client.post('/scan-api/close', json={}, headers=headers).status_code == 200
    assert client.get('/scan-api/session', headers=headers).status_code == 410
    client, headers, result = picker(grant)
    next(iter(grant['links'].sessions.values()))['expires'] -= 301
    assert client.get('/scan-api/session', headers=headers).status_code == 410
    assert not FakeClient.sign_calls


def test_new_picker_frontend_requires_selection_and_sends_only_aliases():
    run_node("require('./tests/scan_picker_controller.cjs')")


def test_picker_location_alias_uses_latest_school_position(grant,browser,monkeypatch):
    browser.send('/location-presets',{'config':{'school':'测试学校','address':'学校最初位置','coordinate_system':'bd09',
        'points':[{'name':'A楼','longitude':116.2,'latitude':40.2,'address':'不应上报的点位说明'}]}})
    client,headers,result=picker(grant)
    location=result.json['locations'][0]
    assert set(location)=={'id','school','name','address'} and location['address']=='学校最初位置'
    assert len(location['id'])==16
    aliases=[result.json['accounts'][0]['id']]
    assert client.post('/scan-api/start',json={'account_ids':aliases,'location':{'school':'测试学校','name':'A楼'}},headers=headers).status_code==400
    start=client.post('/scan-api/start',json={'account_ids':aliases,'input':'native','location':location['id']},headers=headers)
    assert start.status_code==200
    assert client.post('/scan-api/start',json={'account_ids':aliases,'input':'native'},headers=headers).status_code==400
    browser.send('/location-presets/school',{'name':'测试学校','original':'测试学校','address':'全校统一新位置'},'PUT')
    seen=[]
    monkeypatch.setattr(FakeClient,'sign',lambda self,activity,params,name:seen.append(params) or '离线成功')
    client.post('/scan-api/qr',json={'qr':QR},headers=headers)
    final=wait_for(lambda:client.get('/scan-api/status',headers=headers),lambda r:r.status_code==200 and r.json.get('terminal'))
    assert final.json['state']=='completed' and seen[0]['address']=='全校统一新位置'
    assert seen[0]['longitude']=='116.200000' and seen[0]['latitude']=='40.200000'


def test_picker_location_can_be_omitted_and_removed_points_cannot_be_used(grant,browser):
    browser.send('/location-presets',{'config':{'school':'测试学校','address':'学校位置','coordinate_system':'bd09',
        'points':[{'name':'A楼','longitude':116.2,'latitude':40.2}]}})
    client,headers,result=picker(grant);alias=result.json['accounts'][0]['id'];location=result.json['locations'][0]['id']
    browser.send('/location-presets/point',{'school':'测试学校','name':'A楼'},'DELETE')
    assert client.post('/scan-api/start',json={'account_ids':[alias],'location':location},headers=headers).status_code==400
    start=client.post('/scan-api/start',json={'account_ids':[alias]},headers=headers)
    assert start.status_code==200
    assert grant['app'].extensions['camera_streams'].runs[start.json['id']].location is None
