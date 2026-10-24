import copy
import json

import pytest

from server.location_presets import validate_import
from server.store import Store


SCHOOL = {'version':1, 'school':'测试学校', 'coordinate_system':'gcj02',
          'points':[{'name':'A教学楼','longitude':116.410244,'latitude':39.916404,'address':'测试学校 · A教学楼'}]}


def test_authentication_and_csrf_are_required(browser):
    assert browser.get('/location-presets').status_code == 401
    assert browser.get('/location-presets/export').status_code == 401
    assert browser.send('/location-presets', {'config':SCHOOL}).status_code == 401
    browser.admin_login()
    assert browser.client.post('/api/location-presets',json={'config':SCHOOL}).status_code == 403


def test_import_persistence_export_round_trip_and_settings_unchanged(browser, app):
    browser.login()
    before=browser.get('/bootstrap').json
    response=browser.send('/location-presets',{'config':SCHOOL})
    assert response.status_code == 200
    values=response.json['location_presets']
    assert values[0]['points'][0]['coordinate_system'] == 'gcj02'
    assert browser.get('/bootstrap').json['location_presets'] == values
    after=browser.get('/bootstrap').json
    assert before['settings'] == after['settings']
    assert before['accounts'] == after['accounts']
    exported=browser.get('/location-presets/export')
    assert exported.headers['Content-Disposition'].endswith('"auto-chaoxing-locations.json"')
    assert set(exported.json) == {'version','schools'}
    assert exported.json['schools'] == values
    assert browser.send('/location-presets',{'config':exported.json}).status_code == 400
    assert browser.send('/location-presets',{'config':exported.json,'replace':True}).status_code == 200
    store=app.extensions['store']
    with store.connect() as db:
        owner=db.execute('SELECT owner FROM administrators WHERE id=1').fetchone()['owner']
    reopened=Store(store.directory)
    assert reopened.location_presets(owner) == values
    assert reopened.location_presets('another-owner') == []
    assert SCHOOL['points'][0]['address'].encode() not in store.path.read_bytes()


def test_add_edit_move_delete_points(browser):
    browser.admin_login()
    point={**SCHOOL['points'][0],'coordinate_system':'gcj02'}
    data={'school':'学校甲','point':point}
    assert browser.send('/location-presets/point',data,'PUT').status_code == 400
    for name in ['学校甲','学校乙']:
        assert browser.send('/location-presets/school',{'name':name},'PUT').status_code == 200
    assert browser.send('/location-presets/point',data,'PUT').status_code == 200
    assert browser.send('/location-presets/point',data,'PUT').status_code == 400
    edited={**point,'name':'B教学楼','longitude':116.42,'coordinate_system':'bd09'}
    response=browser.send('/location-presets/point',{'school':'学校乙','point':edited,'original':{'school':'学校甲','name':'A教学楼'}},'PUT')
    assert response.status_code == 200
    assert len(response.json['location_presets']) == 2
    assert next(s for s in response.json['location_presets'] if s['school']=='学校乙')['points'][0]['longitude'] == 116.42
    assert browser.send('/location-presets/point',{'school':'学校乙','name':'B教学楼'},'DELETE').status_code == 200
    assert all(not s['points'] for s in browser.get('/location-presets').json['location_presets'])
    assert browser.send('/location-presets/point',{'school':'学校乙','name':'B教学楼'},'DELETE').status_code == 404


def test_no_saved_point_count_limit_and_large_imports(browser):
    browser.admin_login()
    config=copy.deepcopy(SCHOOL)
    config['points']=[{**SCHOOL['points'][0],'name':f'教学楼{i}'} for i in range(1200)]
    response=browser.send('/location-presets',{'config':config})
    assert response.status_code == 200
    assert len(response.json['location_presets'][0]['points']) == 1200


def test_multi_school_import_is_atomic_on_conflict(browser):
    browser.admin_login()
    browser.send('/location-presets',{'config':SCHOOL})
    other={**SCHOOL,'school':'新学校'}
    assert browser.send('/location-presets',{'config':{'version':1,'schools':[other,SCHOOL]}}).status_code == 400
    assert len(browser.get('/location-presets').json['location_presets']) == 1
    assert browser.send('/location-presets',{'config':{'version':1,'schools':[other,SCHOOL]},'replace':True}).status_code == 200
    assert len(browser.get('/location-presets').json['location_presets']) == 2


@pytest.mark.parametrize('changes', [
    {'school':''}, {'school':'x'*101}, {'coordinate_system':'invalid'}, {'points':None},
    {'points':[{'name':'楼','longitude':'NaN','latitude':30}]},
    {'points':[{'name':'楼','longitude':True,'latitude':30}]},
    {'points':[{'name':'楼','longitude':181,'latitude':30}]},
    {'points':[{'name':'楼','longitude':120,'latitude':91}]},
    {'points':[{'name':'楼','longitude':120,'latitude':30,'coordinate_system':'invalid'}]},
    {'points':[SCHOOL['points'][0],SCHOOL['points'][0]]}, {'cookies':'must-not-import'},
])
def test_invalid_configuration_is_rejected(changes):
    with pytest.raises(ValueError):
        validate_import({**SCHOOL,**changes})


def test_mixed_coordinate_systems_and_duplicate_school_rejection():
    school=copy.deepcopy(SCHOOL)
    school['points'].append({'name':'B教学楼','longitude':116.4,'latitude':39.9,'coordinate_system':'wgs84'})
    assert validate_import(school)[0]['points'][1]['coordinate_system'] == 'wgs84'
    with pytest.raises(ValueError):
        validate_import({'version':1,'schools':[school,school]})


def test_sample_is_importable_and_does_not_contain_accounts(browser):
    browser.admin_login()
    example=browser.client.get('/static/examples/location-presets.example.json').json
    assert validate_import(example)[0]['school'].startswith('示例学校')
    assert browser.send('/location-presets',{'config':example}).status_code == 200


def test_explicit_school_parent_lifecycle(browser):
    browser.admin_login()
    assert browser.send('/location-presets/school',{'name':'空学校'},'PUT').status_code == 200
    assert browser.get('/location-presets').json['location_presets'][0]['points'] == []
    assert browser.send('/location-presets/school',{'name':'空学校'},'PUT').status_code == 400
    assert browser.send('/location-presets/school',{'name':'已更名学校','original':'空学校'},'PUT').status_code == 200
    assert browser.get('/location-presets').json['location_presets'][0]['school'] == '已更名学校'
    exported=browser.get('/location-presets/export').json
    assert browser.send('/location-presets',{'config':exported,'replace':True}).status_code == 200
    assert browser.send('/location-presets/school',{'name':'已更名学校'},'DELETE').status_code == 200
    assert browser.get('/location-presets').json['location_presets'] == []
