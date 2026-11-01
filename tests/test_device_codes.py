"""Persistent identity tests with synthetic codes and fake platform accounts."""
import base64
from concurrent.futures import ThreadPoolExecutor

import pytest

from server.chaoxing import ChaoxingClient
from server.config import account_defaults
from server.device_codes import random_device_code, validate_device_code
from server.store import Store
from tests.conftest import FakeClient
from tests.test_camera_sign import run_node
from tests.test_platform import sign_response


CODE = 'OFFLINE_DEVICE_BINDING_123456789'


def test_random_device_code_has_original_wire_shape_and_is_not_constant():
    first, second = random_device_code(), random_device_code()
    decoded = base64.b64decode(first, validate=True)
    assert len(decoded) == 64 and decoded[:32] == decoded[32:]
    assert first != second and validate_device_code(first) == first


@pytest.mark.parametrize('value', [None, [], 123, '', 'short', 'a'*513, 'x'*20+'\n'+'y'*20,
                                 'https://example.invalid/?dc=not-a-code', '<script>alert(1)</script>'])
def test_invalid_device_code_is_rejected(value):
    with pytest.raises(ValueError):
        validate_device_code(value)


def test_default_codes_are_unique_persistent_and_relogin_does_not_replace(browser, app):
    first, second = browser.login(), browser.login('13800000002')
    values = browser.get('/devices').json['device_bindings']
    assert len(values) == 2 and values[0]['code'] != values[1]['code']
    assert all(item['source'] == 'generated' for item in values)
    assert not any('device' in key for key in first)
    again = browser.login()
    assert again['id'] == first['id']
    assert browser.get('/devices').json['device_bindings'] == values
    reopened = Store(app.extensions['store'].directory)
    owner = reopened.administrator()['owner']
    assert reopened.device_binding(owner, first['id'])['code'] == values[0]['code']


def test_legacy_missing_binding_is_created_once_under_parallel_first_use(browser, app):
    account = browser.login()
    store = app.extensions['store'];owner = store.administrator()['owner']
    with store.connect() as db:
        db.execute('DELETE FROM account_devices')
    with ThreadPoolExecutor(max_workers=5) as executor:
        values = list(executor.map(lambda _:store.device_binding(owner,account['id'])['code'],range(5)))
    assert len(set(values)) == 1
    with store.connect() as db:
        db.execute('DELETE FROM account_devices')
    restarted = Store(store.directory)
    saved = restarted.device_binding(owner,account['id'])
    assert saved['source'] == 'generated'
    assert Store(store.directory).device_binding(owner,account['id']) == saved


def test_binding_requires_admin_csrf_and_account_ownership(browser, app):
    assert browser.get('/devices').status_code == 401
    assert browser.send('/devices/global',{'code':CODE,'apply_existing':True},'PUT').status_code == 401
    account = browser.login()
    assert browser.client.put('/api/accounts/'+account['id']+'/device',json={'action':'random'}).status_code == 403
    assert browser.send('/accounts/missing/device',{'action':'random'},'PUT').status_code == 404
    store = app.extensions['store']
    foreign = store.save_account('foreign-owner', {'uid':'foreign','name':'foreign'},[],account_defaults())
    assert browser.send('/accounts/'+foreign['id']+'/device',{'action':'random'},'PUT').status_code == 404
    assert foreign['id'] not in {a['id'] for a in browser.get('/devices').json['device_bindings']}


def test_manual_binding_is_encrypted_and_preserves_account_configuration(browser, app):
    account = browser.login()
    result = browser.send('/accounts/'+account['id']+'/device',{'action':'bind','code':CODE,'source':'imported'},'PUT')
    assert result.status_code == 200
    value = result.json['device_bindings'][0]
    assert value['source'] == 'imported' and value['code'] == CODE
    store = app.extensions['store'];owner = store.administrator()['owner']
    before = store.account(owner,account['id'])['config']
    browser.login()
    assert store.device_binding(owner,account['id']) == {k:v for k,v in value.items() if k not in {'id','name'}}
    assert store.account(owner,account['id'])['config'] == before
    with store.connect() as db:
        assert CODE not in db.execute('SELECT value FROM account_devices').fetchone()[0]
    assert CODE not in browser.get('/bootstrap').text


def test_global_defaults_bulk_apply_and_per_account_override(browser, app):
    first, second = browser.login(), browser.login('13800000002')
    old = browser.get('/devices').json['device_bindings']
    result = browser.send('/devices/global',{'code':CODE,'apply_existing':False},'PUT')
    assert result.json['device_bindings'] == old
    third = browser.login('13800000003')
    bindings = {a['id']:a for a in browser.get('/devices').json['device_bindings']}
    assert bindings[third['id']]['code'] == CODE and bindings[third['id']]['source'] == 'unified'
    result = browser.send('/devices/global',{'code':CODE,'apply_existing':True},'PUT')
    assert {a['code'] for a in result.json['device_bindings']} == {CODE}
    browser.send('/accounts/'+first['id']+'/device',{'action':'bind','code':CODE+'_OVERRIDE'},'PUT')
    browser.send('/accounts/'+second['id']+'/device',{'action':'random'},'PUT')
    saved = browser.get('/devices').json['device_bindings']
    assert len({a['code'] for a in saved}) == 3
    browser.send('/devices/global',{'code':'','apply_existing':False},'PUT')
    assert browser.get('/devices').json['device_bindings'] == saved
    fourth = browser.login('13800000004')
    assert next(a for a in browser.get('/devices').json['device_bindings'] if a['id']==fourth['id'])['source']=='generated'
    store = app.extensions['store']
    assert Store(store.directory).device_settings(store.administrator()['owner'])['code']==''


@pytest.mark.parametrize('body',[{'action':'bind','code':CODE,'source':[]},{'action':'random','code':CODE},
                                {'action':'bind','code':CODE,'source':'generated'},{'action':'bind'}, {'action':[]}])
def test_invalid_binding_actions(browser,body):
    account=browser.login()
    assert browser.send('/accounts/'+account['id']+'/device',body,'PUT').status_code==400


def test_invalid_global_update_is_atomic(browser):
    browser.login()
    old=browser.get('/devices').json
    for body in ({'code':'','apply_existing':True},{'code':CODE,'apply_existing':'yes'},{'code':CODE,'owner':'foreign','apply_existing':True}):
        assert browser.send('/devices/global',body,'PUT').status_code==400
        assert browser.get('/devices').json==old


def test_web_and_qq_use_bound_codes_without_replacing_other_accounts(browser,app,monkeypatch):
    import time
    from server.napcat import SignConversation
    first,second=browser.login(),browser.login('13800000002')
    browser.send('/accounts/'+first['id']+'/device',{'action':'bind','code':CODE},'PUT')
    second_code=next(a['code'] for a in browser.get('/devices').json['device_bindings'] if a['id']==second['id'])
    seen=[]
    monkeypatch.setattr(FakeClient,'sign',lambda client,*args:seen.append((client.jar[0]['value'],client.device_code)) or 'offline success')
    browser.get('/accounts/'+first['id']+'/activities')
    assert browser.send('/accounts/'+first['id']+'/sign',{'activity_id':'901','deviceCode':'attacker_override'}).status_code==200
    owner=app.extensions['napcat'].owner
    chat=SignConversation(app.extensions['store'],app.extensions['signing'],owner,lambda *a:None,
                          lambda:{'enabled':True,'allowed_qqs':['10000001']})
    for index,text in enumerate(('签到','2','1')):
        chat.handle({'user_id':'10000001','self_id':'20000001','post_type':'message','message_type':'private',
                     'time':time.time(),'message_id':index+1,'message':[{'type':'text','data':{'text':text}}]})
    assert seen==[('13800000001',CODE),('13800000002',second_code)]


def test_camera_and_one_use_capability_use_the_same_stored_device(browser,app,monkeypatch):
    from tests.test_scan_links import claim,QR,HEADERS
    from server.napcat import DEFAULT
    account=browser.login();store=app.extensions['store'];owner=store.administrator()['owner']
    browser.send('/accounts/'+account['id']+'/device',{'action':'bind','code':CODE},'PUT')
    original=FakeClient.activities
    monkeypatch.setattr(FakeClient,'activities',lambda client,courses:[{**original(client,courses)[0],'kind':'qr','id':'902'}])
    seen=[]
    monkeypatch.setattr(FakeClient,'sign',lambda client,*a:seen.append(client.device_code) or 'offline success')
    store.set_napcat_settings(owner,{**DEFAULT,'enabled':True,'allowed_qqs':['10000001'],'scan_base_url':'https://example.invalid'})
    activities=app.extensions['signing'].refresh(owner,account['id'])
    token=app.extensions['scan_links'].issue('10000001',owner,account['id'],activities).split('#')[1]
    client,headers,_=claim({'app':app},token)
    assert client.post('/scan-api/submit',json={'qr':QR},headers=headers).status_code==200
    assert seen==[CODE]
    assert client.get('/api/devices').status_code==401


@pytest.mark.parametrize('kind,supplied',[('normal',{}),('qr',{'qr':'OFFLINE_QR_ENC_123'}),('location',{'latitude':30,'longitude':120,'address':'offline'}),
                                          ('gesture',{'code':'123'}),('code',{'code':'123'}),('photo',{'object_id':'OFFLINE_IMAGE_123'})])
def test_device_code_reaches_final_platform_request_for_all_sign_modes(monkeypatch,kind,supplied):
    client=ChaoxingClient();client.device_code=CODE;calls=[]
    def request(method,url,**kwargs):
        calls.append(kwargs);return sign_response(url)
    monkeypatch.setattr(client,'request',request)
    client.sign({'id':'901','kind':kind,'course':{'courseId':'101','clazzId':'201'}},supplied,'offline')
    assert calls[-1]['params']['deviceCode']==CODE
    assert client.device_code==CODE


def test_removed_account_binding_is_deleted(browser,app):
    account=browser.login()
    assert browser.send('/accounts/'+account['id'],method='DELETE').status_code==200
    with app.extensions['store'].connect() as db:
        assert db.execute('SELECT count(*) FROM account_devices').fetchone()[0]==0


def test_browser_identity_is_persistent_and_qr_parser_returns_only_dc():
    run_node(r'''
const assert=require('node:assert/strict'),D=require('./web/device-code-utils.js');
const values=new Map(),storage={getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)};
let calls=0;const random=a=>{calls++;a.fill(42)},encode=s=>Buffer.from(s,'binary').toString('base64');
const first=D.localCode(storage,random,encode),second=D.localCode(storage,random,encode);
assert.equal(first,second);assert.equal(calls,1);
const raw='http://cdn.aquamarine5.fun/?phone=private-phone&pwd=private-password&name=private-name&dc='+encodeURIComponent(first);
assert.equal(D.fromShare(raw),first);assert.ok(!D.fromShare(raw).includes('private'));
assert.throws(()=>D.fromShare('https://example.invalid/?phone=private&pwd=private'));
assert.throws(()=>D.fromShare(raw+'&dc='+encodeURIComponent(first)));
assert.throws(()=>D.localCode({getItem:()=>null,setItem(){}},random,encode));
console.log('local device identity and private QR extraction verified');
''')
