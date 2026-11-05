import json
from unittest.mock import MagicMock

import pytest
import requests

from server.config import API_DEFAULTS, ENGINE, MASK


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.syspath_prepend(str(ENGINE))
    from api.answer import Tiku
    value = Tiku.get_tiku_from_config({**API_DEFAULTS, 'provider':'TikuHai',
                                     'tikuhai_card':'offline-secret', 'tikuhai_min_interval':'0'})
    value.init_tiku()
    return value


def result(kind='single', values=None, **fields):
    return {'success':True, 'meta':{'hit':True,'billing_result':'charged'}, 'data':{
        'asset_type':'standalone','answer_status':'complete',
        'items':[{'answer':{'kind':kind,'values':['选项二'] if values is None else values}}], **fields}}


def transport(monkeypatch, payload):
    session = MagicMock()
    response = session.post.return_value.__enter__.return_value
    response.status_code = 200
    response.iter_content.return_value = [json.dumps(payload).encode()]
    monkeypatch.setattr('api.tikuhai.requests.Session', lambda:session)
    session.__enter__.return_value = session
    return session


def test_query_keeps_original_text_full_image_url_and_isolated_headers(provider, monkeypatch):
    session = transport(monkeypatch, result())
    question = {'title':'123（2.0分） IMG<img src="https://example.invalid/a?token=x#p">',
                'type':'single', 'options':'A. 选项一\nB、选项二'}
    assert provider.query(question)=='选项二'
    args = session.post.call_args
    assert args.args[0]==provider.ENDPOINT
    assert args.kwargs['json']=={'stem':question['title'],'options':['选项一','选项二'],'type':'single_choice'}
    assert args.kwargs['headers']['X-Consumer-Token']=='offline-secret'
    assert 'X-Channel-Key' not in args.kwargs['headers']
    assert args.kwargs['allow_redirects'] is False and session.trust_env is False
    assert provider.query(question)=='选项二' and session.post.call_count==1


@pytest.mark.parametrize('kind,values,expected',[
    ('single',['选项二'],'选项二'),('multiple',['甲','乙'],'甲\n乙'),
    ('judgement',[False],'错误'),('judgement',[True],'正确'),
    ('completion',['第一空','第二空'],'第一空\n第二空')])
def test_all_supported_answer_kinds(provider,monkeypatch,kind,values,expected):
    transport(monkeypatch,result(provider.KINDS[kind],values))
    assert provider.query_all([{'title':'原题','type':kind,'options':''}])==[expected]


@pytest.mark.parametrize('payload',[
    {'success':False,'error':{'message':'untrusted'}},
    {'success':True,'data':None,'meta':{'hit':False}},
    {'success':True,'data':{'answer_status':'missing'},'meta':{}},
    {'success':True,'data':{'answer_status':'complete'},'meta':{'billing_result':'exhausted'}},
    result(asset_type='composite'), result(kind='multi'), result(values=[]), result(values=[True]),
    {'success':True,'meta':{},'data':{'answer_status':'complete','answer':'top-level answer'}}])
def test_misses_exhaustion_and_bad_shapes_do_not_become_answers(provider,monkeypatch,payload):
    transport(monkeypatch,payload)
    assert provider.query({'title':'测试题','type':'single','options':''}) is None


def test_failed_request_is_not_retried_or_logged_with_secret(provider,monkeypatch):
    session=transport(monkeypatch,result())
    session.post.side_effect=requests.ConnectionError('offline-secret')
    messages=[]
    monkeypatch.setattr('api.tikuhai.logger.warning', lambda text:messages.append(text))
    assert provider.query({'title':'测试题','type':'single'}) is None
    assert session.post.call_count==1 and 'offline-secret' not in repr(messages)


def test_multi_provider_fallback_preserves_original_question(provider,monkeypatch):
    from api.answer import Tiku, TikuFallback
    class Miss(Tiku):
        def _query(self,question):return None
        def _query_all(self,questions,query_delay=0):
            for question in questions:question['title']='modified'
            return [None]*len(questions)
    missing=Miss();missing.name='offline miss';missing.config_set(dict(API_DEFAULTS))
    combined=TikuFallback([missing,provider]);combined.config_set(dict(API_DEFAULTS));combined.init_tiku()
    session=transport(monkeypatch,result())
    assert combined.query_all([{'title':'123 原题（2.0分）','type':'single','options':'A. 一\nB. 选项二'}])==['选项二']
    assert session.post.call_args.kwargs['json']['stem']=='123 原题（2.0分）'


def test_new_fields_mask_and_survive_global_and_account_config(browser):
    account=browser.login()
    payload={'provider':'TikuHai','tikuhai_card':'offline-consumer-secret','tikuhai_channel_key':'offline-channel-secret'}
    saved=browser.send('/settings',{'api':payload},'PUT')
    assert saved.status_code==200 and saved.json['api']['tikuhai_card']==MASK
    saved=browser.send('/accounts/'+account['id']+'/config',{'inherit_api':False,'api':payload},'PUT')
    assert saved.status_code==200 and saved.json['config']['api']['tikuhai_channel_key']==MASK
    assert 'TikuHai' in browser.get('/bootstrap').json['schema']['providers']


def test_api_mode_uses_only_api_credential(provider,monkeypatch):
    provider.config_set({**API_DEFAULTS,'tikuhai_auth_mode':'api','tikuhai_card':'inactive-card',
                         'tikuhai_api_key':'selected-api-key','tikuhai_channel_key':'channel', 'tikuhai_min_interval':'0'})
    provider.init_tiku()
    session=transport(monkeypatch,result())
    assert provider.query({'title':'测试题','type':'single'})=='选项二'
    headers=session.post.call_args.kwargs['headers']
    assert headers['X-Consumer-Token']=='selected-api-key' and headers['X-Channel-Key']=='channel'
    assert 'inactive-card' not in repr(session.post.call_args)


def test_missing_selected_credential_does_not_use_other_mode(provider):
    provider.config_set({**API_DEFAULTS,'tikuhai_auth_mode':'api','tikuhai_card':'card-only'})
    provider.init_tiku()
    assert provider.DISABLE


def test_ui_shows_mode_selector_and_only_selected_credential():
    from tests.test_camera_sign import run_node
    run_node("""
        const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
        const source = fs.readFileSync('web/app.js','utf8');
        const context = vm.createContext({
            state:{schema:{api:{provider:'',tikuhai_auth_mode:'card',tikuhai_card:'',tikuhai_api_key:''},providers:['TikuHai']}},
            labels:{}, secrets:new Set(['tikuhai_card','tikuhai_api_key']), esc:value=>String(value)
        });
        vm.runInContext(source.slice(source.indexOf('function apiFields('),source.indexOf('function timingFields(')),context);
        const card = vm.runInContext('apiFields({tikuhai_auth_mode:"card"})',context);
        assert(card.includes('name="api.tikuhai_auth_mode"'));
        assert(card.includes('data-tikuhai-credential="tikuhai_api_key" hidden'));
        const api = vm.runInContext('apiFields({tikuhai_auth_mode:"api"})',context);
        assert(api.includes('data-tikuhai-credential="tikuhai_card" hidden'));
        assert(!api.includes('data-tikuhai-credential="tikuhai_api_key" hidden'));
    """)
