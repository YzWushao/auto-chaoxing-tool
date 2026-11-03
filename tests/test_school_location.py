import copy

import pytest

from server.location_presets import validate_school, resolve_point
from tests.conftest import FakeClient
from tests.test_napcat import chat, QQ

ADDRESS = '测试理工学院河北省测试市大学路 808 号'
SCHOOL = {'school':'离线学校','address':ADDRESS,'coordinate_system':'bd09','points':[
    {'name':'教学楼甲','longitude':116.1,'latitude':40.1,'address':'旧点位甲说明'},
    {'name':'教学楼乙','longitude':116.2,'latitude':40.2,'address':'旧点位乙说明'}]}


def test_import_exports_parent_description_and_discards_legacy_child_descriptions(browser):
    browser.admin_login()
    result=browser.send('/location-presets',{'config':SCHOOL})
    assert result.status_code==200
    saved=result.json['location_presets'][0]
    assert saved['address']==ADDRESS and all('address' not in p for p in saved['points'])
    assert [(p['longitude'],p['latitude']) for p in saved['points']]==[(116.1,40.1),(116.2,40.2)]
    assert browser.get('/location-presets/export').json['schools'][0]==saved
    assert browser.send('/location-presets',{'config':saved,'replace':True}).status_code==200


def test_legacy_read_is_non_destructive_and_never_uses_a_child_description(app,browser):
    browser.admin_login();store=app.extensions['store'];owner=app.extensions['napcat'].owner
    legacy=copy.deepcopy(SCHOOL);legacy.pop('address')
    store.import_location_presets(owner,[legacy])
    with store.connect() as db:before=db.execute('SELECT value FROM location_presets').fetchone()[0]
    value=store.location_presets(owner)[0]
    assert value['address']==value['school'] and all('address' not in p for p in value['points'])
    assert resolve_point(store,owner,{'school':value['school'],'name':'教学楼乙'})['address']==value['school']
    with store.connect() as db:assert db.execute('SELECT value FROM location_presets').fetchone()[0]==before


def test_editing_school_position_updates_all_children_without_changing_coordinates(browser):
    browser.admin_login();browser.send('/location-presets',{'config':SCHOOL})
    before=browser.get('/location-presets').json['location_presets'][0]['points']
    result=browser.send('/location-presets/school',{'name':SCHOOL['school'],'original':SCHOOL['school'],'address':'统一的新学校位置'},'PUT')
    assert result.status_code==200 and result.json['location_presets'][0]['address']=='统一的新学校位置'
    assert result.json['location_presets'][0]['points']==before
    for bad in ('',None,'a'*201):
        assert browser.send('/location-presets/school',{'name':SCHOOL['school'],'original':SCHOOL['school'],'address':bad},'PUT').status_code==400


@pytest.mark.parametrize('point_index',[0,1])
def test_web_server_overrides_point_description_with_latest_school_location(app,browser,monkeypatch,point_index):
    account=browser.login();browser.send('/location-presets',{'config':SCHOOL})
    signing=app.extensions['signing'];owner=app.extensions['napcat'].owner
    signing.refresh(owner,account['id'])
    seen=[]
    monkeypatch.setattr(FakeClient,'sign',lambda self,activity,params,name:seen.append(copy.deepcopy(params)) or '离线成功')
    point=SCHOOL['points'][point_index]
    result=browser.send('/accounts/'+account['id']+'/sign',dict(activity_id='901',kind='location',longitude=point['longitude'],latitude=point['latitude'],
        address='客户端残留的点位说明',location_preset={'school':SCHOOL['school'],'name':point['name']}))
    assert result.status_code==200 and seen[0]['address']==ADDRESS
    assert 'location_preset' not in seen[0] and float(seen[0]['longitude'])==point['longitude']


def test_camera_preset_uses_school_position(app,browser,monkeypatch):
    account=browser.login();browser.send('/location-presets',{'config':SCHOOL})
    original=FakeClient.activities
    monkeypatch.setattr(FakeClient,'activities',lambda c,courses:[{**original(c,courses)[0],'kind':'qr'}])
    seen=[]
    monkeypatch.setattr(FakeClient,'sign',lambda self,activity,params,name:seen.append(copy.deepcopy(params)) or '离线成功')
    camera=app.extensions['camera_sign'] if 'camera_sign' in app.extensions else app.extensions['camera_streams'].camera
    camera.submit(app.extensions['napcat'].owner,account['id'],'https://offline.invalid/?id=901&enc=OFFLINE_ENC_123',location={'school':SCHOOL['school'],'name':'教学楼乙'})
    assert seen[0]['address']==ADDRESS and seen[0]['longitude']=='116.200000'


def test_qq_batch_location_uses_same_school_description_for_every_selected_user(browser,chat):
    browser.send('/location-presets',{'config':SCHOOL})
    say=chat['message'];say('签到');say('全选');say('3');say('2')
    assert len(chat['calls'])==2
    assert all(call[1]['address']==ADDRESS and call[1]['longitude']=='116.200000' for call in chat['calls'])
