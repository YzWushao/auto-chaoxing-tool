"""Bot API auth, scope, queue identity and retry contracts. Fake platform only."""
import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from server.api_access import SCOPES
from server.app import create_app
from server.config import account_defaults
from tests.conftest import FakeClient
from tests.test_server_camera import jpeg, wait_for
from tests.test_scan_links import QR
from tests.test_camera_sign import run_node


def mint(app,browser,scopes=None,enabled=True,**fields):
    if not browser.get('/session').json['authenticated']:browser.admin_login()
    result=browser.send('/access/keys',{'name':'offline plugin','scopes':list(SCOPES) if scopes is None else scopes,**fields})
    assert result.status_code==201,result.json
    browser.send('/access',{'enabled':enabled},'PUT')
    return {'Authorization':'Bearer '+result.json['token']},result.json


def call(app,headers,path,method='GET',body=None,**kwargs):
    return app.test_client().open('/api/v1'+path,method=method,headers=headers,
        **({'json':{} if body is None else body} if method!='GET' else {}),**kwargs)


def test_keys_default_off_only_hash_persisted_and_bearer_never_sets_console_cookie(app,browser):
    headers,created=mint(app,browser,enabled=False)
    assert call(app,headers,'/me').status_code==401
    browser.send('/access',{'enabled':True},'PUT')
    result=call(app,headers,'/me');assert result.status_code==200
    assert result.json['key']['scopes']==list(SCOPES) and 'Set-Cookie' not in result.headers
    visible=browser.get('/access').json
    assert created['token'] not in json.dumps(visible)
    with app.extensions['store'].connect() as db:
        rows=[tuple(row) for row in db.execute('SELECT * FROM api_tokens')]
    assert created['token'] not in repr(rows)
    assert hashlib.sha256(created['token'].encode()).hexdigest() in repr(rows)


def test_no_cookie_query_or_csrf_fallback_for_external_api(app,browser):
    headers,_=mint(app,browser)
    assert browser.client.get('/api/v1/me').status_code==401
    verified=browser.client.get('/api/v1/me',headers=headers)
    assert verified.status_code==200 and 'Set-Cookie' not in verified.headers and 'Cookie' not in verified.headers.get('Vary','')
    assert browser.get('/session').json['authenticated'] is True
    assert call(app,{},'/me?api_key='+headers['Authorization'][7:]).status_code==401
    assert call(app,{'Authorization':'Basic invalid'},'/me').status_code==401
    assert browser.send('/preferences',{'camera_concurrency':2},'PUT').status_code==200
    assert browser.client.put('/api/preferences',json={'camera_concurrency':3},headers=headers).status_code==403
    assert call(app,headers,'/preferences','PUT',{'camera_concurrency':4}).status_code==200
    assert app.extensions['store'].preferences(app.extensions['store'].administrator()['owner'])['camera_concurrency']==4


@pytest.mark.parametrize('path,method,body,scope',[
    ('/preferences','PUT',{'camera_concurrency':2},'settings:write'),
    ('/auth/password','POST',{'phone':'13800000002','password':'test'},'accounts:write'),
    ('/accounts/foreign/study','POST',{},'study:write'),
    ('/accounts/foreign/sign','POST',{'activity_id':'901'},'sign:write'),
    ('/admin/credentials','PUT',{'username':'other','current_password':'admin'},'admin:write')])
def test_read_key_cannot_write_even_with_admin_cookie(app,browser,path,method,body,scope):
    headers,_=mint(app,browser,['read'])
    result=browser.client.open('/api/v1'+path,method=method,json=body,headers=headers)
    assert result.status_code==403 and result.json['required_scope']==scope
    assert FakeClient.sign_calls==0


@pytest.mark.parametrize('fields',[
    {'name':''},{'name':'x'*65},{'name':'x\ny'},{'scopes':[]},{'scopes':['unknown']},{'scopes':['read','read']},
    {'scopes':[{}]},{'expires_days':True},{'expires_days':0},{'expires_days':366},{'rate_limit':9},{'rate_limit':6001}])
def test_key_validation(app,browser,fields):
    browser.admin_login()
    response=browser.send('/access/keys',{'name':'plugin',**fields})
    assert response.status_code==400


def test_api_revocation_expiry_master_switch_and_persistence(app,browser):
    headers,created=mint(app,browser,['read'])
    assert call(app,headers,'/accounts').status_code==200
    other=create_app({'TESTING':True,'DATA_DIR':app.config['DATA_DIR']},FakeClient)
    try:assert call(other,headers,'/me').status_code==200
    finally:other.extensions['camera_streams'].shutdown();other.extensions['tasks'].shutdown()
    browser.send('/access',{'enabled':False},'PUT');assert call(app,headers,'/me').status_code==401
    browser.send('/access',{'enabled':True},'PUT');assert call(app,headers,'/me').status_code==200
    assert browser.send('/access/keys/'+created['key']['id'],{},'DELETE').status_code==200
    assert call(app,headers,'/me').status_code==401
    headers,_=mint(app,browser,['read'])
    with app.extensions['store'].connect() as db:db.execute('UPDATE api_tokens SET expires_at=?',(time.time()-1,))
    assert call(app,headers,'/accounts').status_code==401


def test_all_ui_handlers_have_classified_versioned_aliases_and_filtered_tools(app,browser):
    headers,_=mint(app,browser,['read'])
    access=app.extensions['api_access']
    rules=list(app.url_map.iter_rules())
    for rule in rules:
        if not rule.rule.startswith('/api/') or rule.rule.startswith(('/api/access','/api/v1/')) or rule.endpoint in {'current_session','admin_login','logout'}:continue
        for method in rule.methods-{'HEAD','OPTIONS'}:
            assert (rule.endpoint,method) in access.operations
            assert any(alias.rule=='/api/v1'+rule.rule[4:] and method in alias.methods and
                       app.view_functions[alias.endpoint] is app.view_functions[rule.endpoint] for alias in rules)
    spec=call(app,headers,'/openapi.json').json;tools=call(app,headers,'/tools').json['tools']
    assert spec['openapi']=='3.1.0' and spec['servers']==[{'url':'/api/v1'}]
    assert '/accounts/{account_id}/sign' not in spec['paths']
    assert {'accounts_list','activities','courses','jobs'}<={t['function']['name'] for t in tools}
    assert 'sign' not in {t['function']['name'] for t in tools}
    all_spec=browser.get('/access/openapi.json').json
    assert '/accounts/{account_id}/sign' in all_spec['paths']
    assert '/access/keys' not in all_spec['paths'] and '/admin/login' not in all_spec['paths']
    assert call(app,headers,'/access/keys','POST',{}).status_code==404
    assert app.test_client().get('/api/access',headers=headers).status_code==401


def test_account_names_and_credentials_are_masked_and_workspace_cannot_be_escaped(app,browser):
    account=browser.login()
    store=app.extensions['store']
    foreign=store.save_account('outside',{'uid':'foreign-uid','phone':'13800000009','name':'Hidden'},[],account_defaults())
    headers,_=mint(app,browser,['read'])
    result=call(app,headers,'/accounts');assert result.status_code==200
    assert len(result.json['accounts'])==1 and result.json['accounts'][0]['id']==account['id']
    serialized=json.dumps(result.json)
    assert 'private-session-fixture' not in serialized and 'cookies' not in serialized
    assert result.json['accounts'][0]['phone']=='138****0001'
    assert call(app,headers,'/accounts/'+foreign['id']).status_code==404
    assert call(app,headers,'/accounts/'+foreign['id']+'/activities').status_code==404


def test_password_and_qr_login_work_without_browser_sessions_and_qr_is_key_scoped(app,browser,monkeypatch):
    headers,_=mint(app,browser,['read','accounts:write'])
    account=call(app,headers,'/auth/password','POST',{'phone':'13800000002','password':'fake'})
    assert account.status_code==200 and 'csrf' not in account.json and 'Set-Cookie' not in account.headers
    qr=app.extensions['qr'];identities={}
    def create(identity):identities['owner']=identity;return {'id':'offline-qr','image':'data:image/png;base64,','expires_in':180}
    def poll(identity,token):
        if identity!=identities['owner']:raise ValueError('not this key')
        client=FakeClient();profile=client.login_password('13800000003','fake')
        return {'profile':profile},client
    monkeypatch.setattr(qr,'create',create);monkeypatch.setattr(qr,'poll',poll)
    assert call(app,headers,'/auth/qr','POST').status_code==200
    foreign,_=mint(app,browser,['accounts:write'])
    assert call(app,foreign,'/auth/qr/offline-qr/poll','POST').status_code==400
    assert call(app,headers,'/auth/qr/offline-qr/poll','POST').json['state']=='confirmed'
    assert identities['owner'].startswith('api:') and len(call(app,headers,'/accounts').json['accounts'])==2


def test_admin_change_requires_password_and_revokes_all_keys(app,browser):
    headers,_=mint(app,browser,['admin:write'])
    assert call(app,headers,'/admin/credentials','PUT',{'username':'other','current_password':'wrong'}).status_code==400
    result=call(app,headers,'/admin/credentials','PUT',{'username':'other','current_password':'admin','new_password':'offline-password-123'})
    assert result.status_code==200 and call(app,headers,'/me').status_code==401
    assert not browser.get('/session').json['authenticated']


def test_rate_limit_and_audit_never_store_request_bodies_or_keys(app,browser):
    headers,created=mint(app,browser,['settings:write'],rate_limit=10)
    for _ in range(10):assert call(app,headers,'/preferences','PUT',{'camera_concurrency':2}).status_code==200
    limited=call(app,headers,'/me');assert limited.status_code==429 and limited.headers['Retry-After']=='60'
    rows=browser.get('/access').json['audit'];assert len(rows)==11
    serialized=json.dumps(rows)
    assert created['token'] not in serialized and 'camera_concurrency' not in serialized
    assert all(re.fullmatch(r'[0-9a-f]{32}',row['request_id']) for row in rows)


def test_idempotency_replays_success_rejects_conflicts_and_encrypts_responses(app,browser,monkeypatch):
    account=browser.login();headers,created=mint(app,browser)
    called=[]
    monkeypatch.setattr(app.extensions['tasks'],'start',lambda *a:called.append(a) or {'id':'fake-task','state':'running'})
    assert call(app,headers,'/accounts/'+account['id']+'/config','PUT',{'course_keys':['101:201']}).status_code==200
    once={**headers,'Idempotency-Key':'QQ-event-123-tool-1'}
    first=call(app,once,'/accounts/'+account['id']+'/study','POST');second=call(app,once,'/accounts/'+account['id']+'/study','POST')
    assert first.status_code==second.status_code==202 and first.json==second.json and len(called)==1
    assert second.headers['Idempotency-Replayed']=='true'
    assert call(app,once,'/accounts/'+account['id']+'/study','POST',{'other':True}).status_code==409
    with app.extensions['store'].connect() as db:
        stored=[dict(row) for row in db.execute('SELECT * FROM api_requests')]
    assert len(stored)==1 and 'fake-task' not in repr(stored) and 'QQ-event-123-tool-1' not in repr(stored)


def test_concurrent_idempotent_writes_run_once(app,browser,monkeypatch):
    headers,_=mint(app,browser,['settings:write']);started=threading.Event();release=threading.Event();calls=[]
    original=app.extensions['store'].set_preferences
    def save(*args):calls.append(1);started.set();release.wait(5);return original(*args)
    monkeypatch.setattr(app.extensions['store'],'set_preferences',save)
    once={**headers,'Idempotency-Key':'same-event'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(call,app,once,'/preferences','PUT',{'camera_concurrency':3});assert started.wait(3)
        second=call(app,once,'/preferences','PUT',{'camera_concurrency':3});assert second.status_code==409
        release.set();assert first.result().status_code==200
    replay=call(app,once,'/preferences','PUT',{'camera_concurrency':3})
    assert replay.status_code==200 and replay.headers['Idempotency-Replayed']=='true' and calls==[1]


def test_api_camera_jpeg_and_native_are_key_scoped_and_revoke_stops_queue(app,browser,monkeypatch):
    account=browser.login();headers,created=mint(app,browser,['read','sign:write'])
    selected=account['id'];calls=[]
    monkeypatch.setattr(app.extensions['signing'],'refresh',lambda *args:[{'id':'902','kind':'qr','photo':False,'signed':False,'source':'course','title':'QR'}])
    monkeypatch.setattr(app.extensions['signing'],'submit',lambda *args:calls.append(args) or {'message':'offline success'})
    start=call(app,headers,'/camera-stream','POST',{'account_ids':[selected]});assert start.status_code==200
    run_id=start.json['id']
    foreign,_=mint(app,browser,['sign:write'])
    assert call(app,foreign,'/camera-stream/'+run_id).status_code==404
    response=app.test_client().post('/api/v1/camera-stream/'+run_id+'/frame',data=jpeg(),content_type='image/jpeg',headers=headers)
    assert response.status_code==202
    result=wait_for(lambda:call(app,headers,'/camera-stream/'+run_id),lambda r:r.status_code==200 and r.json['terminal'])
    assert result.json['state']=='completed' and len(calls)==1
    start=call(app,headers,'/camera-stream','POST',{'account_ids':[selected],'input':'native'})
    run=app.extensions['camera_streams'].runs[start.json['id']]
    assert call(app,headers,'/camera-stream/'+run.id+'/qr','POST',{'qr':''}).status_code==202
    browser.send('/access/keys/'+created['key']['id'],{},'DELETE')
    wait_for(run.snapshot,lambda r:r['terminal'])
    assert run.state=='expired' and FakeClient.sign_calls==0


def test_api_sign_preset_uses_school_address_and_server_coordinate_conversion(app,browser,monkeypatch):
    account=browser.login();headers,_=mint(app,browser,['settings:write','sign:write'])
    assert call(app,headers,'/location-presets/school','PUT',{'name':'Offline School','address':'School official position'}).status_code==200
    point={'name':'Building','longitude':116.2,'latitude':40.1,'coordinate_system':'gcj02'}
    assert call(app,headers,'/location-presets/point','PUT',{'school':'Offline School','point':point}).status_code==200
    called=[];monkeypatch.setattr(app.extensions['signing'],'submit',lambda *args:called.append(args) or {'message':'fake'})
    response=call(app,headers,'/accounts/'+account['id']+'/sign','POST',{'activity_id':'901','location_preset':{'school':'Offline School','name':'Building'},'address':'ignored'})
    assert response.status_code==200
    data=called[0][2];assert data['address']=='School official position' and float(data['longitude'])!=116.2


def test_plugin_adapter_discovers_and_executes_only_allowed_routes(app,browser,monkeypatch):
    from examples.qq_api_client import ChaoxingAPI,PluginAPIError
    headers,created=mint(app,browser,['read','settings:write'])
    sdk=ChaoxingAPI('http://localhost',created['token']);http=app.test_client()
    class Reply:
        def __init__(self,response):self.response=response;self.status_code=response.status_code;self.ok=response.status_code<400;self.headers=response.headers
        def json(self):return self.response.get_json()
    def request(method,url,**kwargs):
        from urllib.parse import urlsplit
        request_headers={**sdk.session.headers,**kwargs.get('headers',{})}
        return Reply(http.open(urlsplit(url).path,method=method,json=kwargs.get('json'),headers=request_headers,query_string=kwargs.get('params')))
    monkeypatch.setattr(sdk.session,'request',request)
    tools=sdk.discover();assert 'preferences_save' in {row['function']['name'] for row in tools}
    assert sdk.call('preferences_save',{'body':{'camera_concurrency':5}},request_id='offline-event')['preferences']['camera_concurrency']==5
    with pytest.raises(ValueError):sdk.call('study',{'path':{'account_id':'foreign'},'body':{}},request_id='bad')
    with pytest.raises(ValueError):sdk.call('preferences_save',{'body':{} })
    with pytest.raises(ValueError):sdk.call('account_detail',{'path':{'account_id':'../access'}})
    sdk.close()


def test_settings_key_creation_copy_and_hide_do_not_retain_plaintext_in_state():
    run_node("require('./tests/api_access_controller.cjs')")


def test_idempotency_survives_restart_and_caches_validation_errors(app,browser):
    headers,_=mint(app,browser,['settings:write']);once={**headers,'Idempotency-Key':'bad-preference'}
    error=call(app,once,'/preferences','PUT',{'camera_concurrency':99});assert error.status_code==400
    restarted=create_app({'TESTING':True,'DATA_DIR':app.config['DATA_DIR']},FakeClient)
    try:
        replay=call(restarted,once,'/preferences','PUT',{'camera_concurrency':99})
        assert replay.status_code==400 and replay.json==error.json and replay.headers['Idempotency-Replayed']=='true'
        malformed=call(restarted,{**headers,'Idempotency-Key':'with space'},'/preferences','PUT',{})
        assert malformed.status_code==400
    finally:restarted.extensions['camera_streams'].shutdown();restarted.extensions['tasks'].shutdown()
