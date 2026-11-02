from types import SimpleNamespace

import pytest
import requests

from server.maps import MapSearch
from tests.test_camera_sign import run_node


def test_reverse_requires_admin_csrf_and_operator_opt_in(browser, app, monkeypatch):
    calls=[]
    monkeypatch.setattr('server.maps.requests.get',lambda url,**kw:calls.append((url,kw)) or SimpleNamespace(
        raise_for_status=lambda:None,json=lambda:{'display_name':'测试省测试市测试大学教学区'}))
    point={'longitude':116.4,'latitude':39.9}
    assert browser.send('/map/reverse',point).status_code==401
    browser.admin_login()
    assert browser.send('/map/reverse',point).status_code==400 and not calls
    assert browser.client.post('/api/map/reverse',json=point).status_code==403
    assert browser.send('/map/settings',{'free_reverse_enabled':True},'PUT').status_code==200
    response=browser.send('/map/reverse',point)
    assert response.status_code==200 and response.json['address']=='测试省测试市测试大学教学区'
    assert calls[0][0]=='https://nominatim.openstreetmap.org/reverse'
    assert calls[0][1]['params']['lon']=='116.400000' and calls[0][1]['params']['lat']=='39.900000'
    assert 'AutoChaoxingTool/' in calls[0][1]['headers']['User-Agent']
    assert not {'cookies','auth'}&calls[0][1].keys() and calls[0][1]['allow_redirects'] is False
    assert browser.send('/map/reverse',point).status_code==200 and len(calls)==1
    assert browser.send('/map/search',{'query':'测试学校'}).status_code==400
    assert browser.send('/map/settings',{'free_reverse_enabled':False},'PUT').status_code==200
    assert browser.send('/map/reverse',point).status_code==400 and len(calls)==1


@pytest.mark.parametrize('lon,lat',[(True,30),(116,None),(181,30),(116,86),(float('nan'),30),('116',30)])
def test_reverse_rejects_invalid_coordinates_without_network(lon,lat):
    with pytest.raises(ValueError):MapSearch().reverse(lon,lat)


def test_reverse_endpoint_can_change_or_be_disabled(monkeypatch):
    monkeypatch.setenv('AUTO_CHAOXING_REVERSE_GEOCODER_URL','')
    with pytest.raises(ValueError,match='关闭'):MapSearch().reverse(116,30)
    monkeypatch.setenv('AUTO_CHAOXING_REVERSE_GEOCODER_URL','http://test.invalid/reverse')
    with pytest.raises(ValueError,match='HTTPS'):MapSearch().reverse(116,30)


def test_reverse_failure_does_not_make_up_an_address(monkeypatch):
    def fail(*a,**k):raise requests.Timeout('private diagnostic')
    monkeypatch.setattr('server.maps.requests.get',fail)
    with pytest.raises(ValueError,match='手动填写') as error:MapSearch().reverse(116,30)
    assert 'private diagnostic' not in str(error.value)
    monkeypatch.setattr('server.maps.requests.get',lambda *a,**kw:SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'error':'no results'}))
    with pytest.raises(ValueError,match='手动填写'):MapSearch().reverse(116,30)


def test_async_address_lookup_tracks_latest_point_and_preserves_manual_text():
    run_node("require('./tests/map_address_controller.cjs')")
