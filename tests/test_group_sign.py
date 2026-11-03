import base64
import json
import time
from types import SimpleNamespace

import pytest
from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
from cryptography.hazmat.primitives.ciphers import Cipher, modes
from cryptography.hazmat.primitives import padding

from server.group_sign import GroupSignClient, sign_attachments
from server.chaoxing import PlatformError
from tests.conftest import FakeClient


def attachment(aid='999', atype=74):
    return {'attachmentType':15,'att_chat_course':{'aid':aid,'atype':atype,'title':'离线群聊签到','courseInfo':{'courseid':'101','classid':'201'}}}


def encoded_message(value):
    return base64.b64encode(b'\x01\x08attachment\x12'+json.dumps(value,ensure_ascii=False).encode()+b'\x00').decode()


def test_extracts_only_structured_sign_attachments():
    assert sign_attachments(encoded_message(attachment()))[0]['aid']=='999'
    assert sign_attachments(encoded_message(attachment(atype=2)))[0]['atype']==2
    assert sign_attachments(encoded_message(attachment(atype=1)))==[]
    assert sign_attachments(encoded_message({'attachmentType':1,'att_chat_course':{'aid':'999','atype':74}}))==[]
    assert sign_attachments('not base64')==[]
    assert sign_attachments('A'*1100000)==[]


def test_im_login_uses_own_profile_and_separate_session_without_platform_cookies(monkeypatch):
    padder=padding.PKCS7(64).padder();data=padder.update(b'offline-im-password')+padder.finalize()
    encryptor=Cipher(TripleDES(b'SL2(M/eD'*3),modes.ECB()).encryptor()
    encrypted=(encryptor.update(data)+encryptor.finalize()).hex()
    class Platform:
        def request(self,method,url,**kwargs):
            assert url=='https://sso.chaoxing.com/apis/login/userLogin4Uname.do'
            return {'msg':{'uid':'12345','accountInfo':{'imAccount':{'password':encrypted}}}}
        def json(self,response):return response
    def request(session,method,url,**kwargs):
        assert not list(session.cookies) and 'Cookie' not in session.headers
        assert kwargs['allow_redirects'] is False
        assert kwargs['json']=={'grant_type':'password','username':'12345','password':'offline-im-password'}
        return SimpleNamespace(status_code=200,content=b'{}',json=lambda:{'access_token':'offline-im-access','user':{'username':'12345'}})
    monkeypatch.setattr('requests.Session.request',request)
    client=GroupSignClient(Platform())
    try:
        client.login()
        assert client.username=='12345' and client.http.headers['Authorization']=='Bearer offline-im-access'
    finally:client.http.close()


def test_group_history_paginates_and_extracts_signs():
    client=GroupSignClient(None);client.username='12345';calls=[]
    def request(method,url,**kwargs):
        calls.append(kwargs['json'])
        i=len(calls)
        return {'data':{'msgs':[{'msg':encoded_message(attachment(str(998+i)))}],'is_last':i==2,'next_key':'next-page'}}
    client.request=request
    try:
        assert [v['aid'] for v in client.history({'id':'777'})]==['999','1000']
        assert calls[1]['start']=='next-page' and calls[0]['queue']=='777@conference.easemob.com'
    finally:client.http.close()


def test_group_detail_filters_ended_and_retains_source():
    info={'otherId':2,'endtime':int((time.time()+3600)*1000),'courseId':'101','clazzid':'201'}
    platform=SimpleNamespace(request=lambda *args,**kwargs:{'data':info},json=lambda x:x,check_login_page=lambda x:None)
    client=GroupSignClient(platform)
    try:
        value=client.activity({'id':'777','name':'离线群聊'},attachment()['att_chat_course'])
        assert value['kind']=='qr' and value['source']=='group' and value['course']['clazzId']=='201'
        info['endtime']=int((time.time()-10)*1000)
        assert client.activity({'id':'777','name':'离线群聊'},attachment()['att_chat_course']) is None
    finally:client.http.close()


def group_activity():
    return {'id':'999','title':'群聊签到（离线）','kind':'normal','photo':False,'source':'group','group_id':'777','group_name':'离线群聊',
            'course':{'key':'group:777','courseId':'101','clazzId':'201','cpi':'','title':'离线群聊'},'_group_item':{'aid':'999','courseInfo':{}}}


def test_group_scope_is_retired_and_cannot_be_enabled(browser,monkeypatch):
    account=browser.login()
    monkeypatch.setattr(FakeClient,'group_activities',lambda c:pytest.fail('Retired group fetch must not run'),raising=False)
    assert browser.send('/preferences',{'include_group_sign':True},'PUT').status_code==400
    assert browser.get(f"/accounts/{account['id']}/activities?source=group").status_code==400
    result=browser.get(f"/accounts/{account['id']}/activities?source=all")
    assert result.status_code==200 and all(a['source']=='course' for a in result.json['activities'])


def test_stale_group_cache_cannot_be_submitted(app,browser,monkeypatch):
    account=browser.login();owner=app.extensions['napcat'].owner
    app.extensions['store'].set_preferences(owner,{'account_label':'phone_tail','include_group_sign':True})
    app.extensions['signing'].cache[(owner,account['id'],'group')]=(time.monotonic(),[group_activity()])
    monkeypatch.setattr(FakeClient,'group_activity',lambda *a:pytest.fail('Stale group submission must not run'),raising=False)
    result=browser.send(f"/accounts/{account['id']}/sign",{'activity_id':'999','source':'group'})
    assert result.status_code==400 and FakeClient.sign_calls==0
    assert browser.get('/bootstrap').json['preferences']['include_group_sign'] is False


def test_old_enabled_setting_still_reads_courses_only(app,browser,monkeypatch):
    account=browser.login();owner=app.extensions['napcat'].owner
    app.extensions['store'].set_preferences(owner,{'account_label':'full_name','include_group_sign':True})
    monkeypatch.setattr(FakeClient,'group_activities',lambda c:pytest.fail('Must not contact IM'),raising=False)
    result=browser.get(f"/accounts/{account['id']}/activities?source=all")
    assert result.status_code==200 and result.json['warnings']==[]
    assert all(a['source']=='course' for a in result.json['activities'])
    assert browser.get('/bootstrap').json['preferences']['account_label']=='full_name'


def test_groups_are_not_fetched_for_course_scope_or_disabled_default(browser,monkeypatch):
    account=browser.login()
    monkeypatch.setattr(FakeClient,'group_activities',lambda c:pytest.fail('must not contact IM'),raising=False)
    assert browser.get(f"/accounts/{account['id']}/activities?source=all").status_code==200
    assert browser.get(f"/accounts/{account['id']}/activities?source=course").status_code==200


def test_group_requirements_and_bad_source_are_rejected(browser):
    account=browser.login()
    assert browser.get(f"/accounts/{account['id']}/activities?source=group").status_code==400
    assert browser.send(f"/accounts/{account['id']}/sign",{'activity_id':'999','source':'group'}).status_code==400
    assert browser.send(f"/accounts/{account['id']}/sign",{'activity_id':'999','source':[]}).status_code==400
    assert FakeClient.sign_calls==0
