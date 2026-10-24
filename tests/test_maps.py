from types import SimpleNamespace

import pytest
import requests

from server.maps import MapSearch


def test_search_auth_and_session_isolation(browser,app,monkeypatch):
    calls=[]
    def get(url,**kwargs):
        calls.append((url,kwargs))
        return SimpleNamespace(raise_for_status=lambda:None,json=lambda:[{'display_name':'公开测试地点','lon':'116.4','lat':'39.9'}])
    monkeypatch.setattr('server.maps.requests.get',get)
    assert browser.send('/map/search',{'query':'测试地点'}).status_code == 401
    browser.login()
    response=browser.send('/map/search',{'query':'测试地点'})
    assert response.status_code == 200
    assert response.json['results'][0]['longitude'] == 116.4
    assert calls[0][1]['params']['limit'] == 5
    assert 'AutoChaoxingTool/' in calls[0][1]['headers']['User-Agent']
    assert not {'cookies','auth'} & calls[0][1].keys()
    assert calls[0][1]['allow_redirects'] is False
    assert browser.send('/map/search',{'query':'测试地点'}).status_code == 200
    assert len(calls) == 1  # cached; no repeat traffic
    assert browser.send('/map/search',{'query':'另一个地方'}).status_code == 400


@pytest.mark.parametrize('query',[None,'','a','x'*121,{},True])
def test_invalid_search_terms(query):
    with pytest.raises(ValueError):
        MapSearch().search(query)


def test_service_failure_and_bad_data(monkeypatch):
    search=MapSearch()
    def failed(*a,**k):
        raise requests.Timeout()
    monkeypatch.setattr('server.maps.requests.get',failed)
    with pytest.raises(ValueError,match='暂不可用'):
        search.search('测试学校')
    search.last_request=-10000
    monkeypatch.setattr('server.maps.requests.get',lambda *a,**k:SimpleNamespace(raise_for_status=lambda:None,json=lambda:[{'lon':'NaN','lat':30},{'lon':181,'lat':30},{}]))
    assert search.search('测试学校') == []


def test_provider_can_be_changed_or_disabled_without_code(monkeypatch):
    monkeypatch.setenv('AUTO_CHAOXING_GEOCODER_URL','')
    with pytest.raises(ValueError,match='关闭'):
        MapSearch().search('测试学校')
    monkeypatch.setenv('AUTO_CHAOXING_GEOCODER_URL','http://example.invalid')
    with pytest.raises(ValueError,match='HTTPS'):
        MapSearch().search('测试学校')
