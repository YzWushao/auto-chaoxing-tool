import copy
import json

import pytest

from server import qq_intent
from server.config import MASK
from server.napcat import DEFAULT, validate_settings
from tests.test_napcat import chat, QQ

CONFIG = {'intent_enabled': True, 'intent_api_url': 'https://model.invalid/v1',
          'intent_api_key': 'offline-model-key', 'intent_model': 'offline-model'}
CTX = {'stage': 'account', 'allowed_actions': ['select', 'all', 'unknown'],
       'choices': [{'index': 1, 'label': '用户1'}, {'index': 3, 'label': '用户3'}], 'total': 3}


def result(action='select', indices=None, confidence=.99):
    return json.dumps(dict(action=action, indices=[1, 3] if indices is None else indices, confidence=confidence))


@pytest.mark.parametrize('url,expected', [
    ('https://model.invalid', 'https://model.invalid/v1/chat/completions'),
    ('https://model.invalid/v1/', 'https://model.invalid/v1/chat/completions'),
    ('http://127.0.0.1:1234/api/chat/completions', 'http://127.0.0.1:1234/api/chat/completions'),
    ('https://model.invalid/custom', 'https://model.invalid/custom/chat/completions')])
def test_endpoint_normalization(url, expected):
    assert qq_intent.endpoint(url) == expected


@pytest.mark.parametrize('patch', [
    {'intent_enabled': 1}, {'intent_api_url': 'file:///secret'}, {'intent_api_url': 'https://user:pass@model.invalid'},
    {'intent_api_url': 'https://model.invalid?key=secret'}, {'intent_api_url': 'https://model.invalid:99999'},
    {'intent_api_key': 'key\nsecret'}, {'intent_model': None}, {'intent_enabled': True},
    {'intent_api_url': 0}, {'intent_api_key': []}, {'intent_model': 'a'*161}])
def test_settings_reject_invalid(patch):
    with pytest.raises(ValueError):
        validate_settings(patch, DEFAULT)


@pytest.mark.parametrize('content', [
    result(indices=[2]), result(indices=[True]), result(indices=[0]), result(indices=[1, 1]),
    result(action='shell', indices=[]), result(action='all', indices=[1]),
    result(confidence=True), result(confidence=float('nan')), result(confidence=2),
    '{}', '```json\n'+result()+'\n```', result()[:-1]+',"url":"https://evil.invalid"}'])
def test_model_output_is_strictly_stage_and_index_bound(content):
    with pytest.raises(ValueError):
        qq_intent.decode(content, CTX)


def test_unknown_and_low_confidence_never_select():
    assert qq_intent.decode(result(confidence=.89), CTX) is None
    assert qq_intent.decode(result(action='unknown', indices=[]), CTX) is None
    assert qq_intent.decode(result(), CTX) == '1,3'
    point = {**CTX, 'stage': 'point', 'allowed_actions': ['select', 'unknown']}
    with pytest.raises(ValueError):
        qq_intent.decode(result(), point)
    with pytest.raises(ValueError):
        qq_intent.decode(result(action='all', indices=[]), point)


def test_context_only_contains_display_labels_of_current_page():
    state = {'phase': 'account', 'page': 1, 'choices': [
        {'id': 'PRIVATE-ID', 'owner': 'PRIVATE-OWNER', 'cookies': 'PRIVATE-COOKIE',
         'phone': '13800000001', 'name': f'用户{i} 13800000001'} for i in range(30)]}
    ctx = qq_intent.context(state, CONFIG)
    assert [i['index'] for i in ctx['choices']] == list(range(13, 25))
    assert ctx['total'] == 30
    encoded = json.dumps(ctx, ensure_ascii=False)
    assert 'PRIVATE' not in encoded and '13800000001' not in encoded and '尾号0001' in encoded
    assert qq_intent.clean_text('offline-model-key https://qr.invalid/?enc=SECRET 13800000001', CONFIG) == '[凭据已隐藏] [链接或图片已隐藏] 尾号0001'


def test_disabled_and_canonical_commands_and_images_never_call_model(chat, monkeypatch):
    def fail(*args):
        pytest.fail('Unexpected model request')
    monkeypatch.setattr(qq_intent, 'interpret', fail)
    say = chat['message']
    say('帮我签到')
    assert not chat['sent']
    chat['config'].update(CONFIG)
    say('签到'); say('1'); say('2'); say(image=True)
    assert len(chat['calls']) == 1
    say('签到'); say('全选'); say('取消')
    assert QQ not in chat['conversation'].sessions


def test_natural_start_select_and_cancel_use_existing_flow(chat, monkeypatch):
    chat['config'].update(CONFIG)
    seen = []
    commands = iter(['签到', '2', '1', '取消'])
    def classify(config, text, ctx):
        seen.append(ctx)
        return next(commands)
    monkeypatch.setattr(qq_intent, 'interpret', classify)
    say = chat['message']
    say('帮我签到'); event = say('选第二位'); say('选第一个活动')
    assert len(chat['calls']) == 1 and chat['calls'][0][2][0]['value'] == '13800000002'
    chat['conversation'].handle(event)
    assert len(seen) == 3 and len(chat['calls']) == 1
    say('先别签了')
    assert QQ not in chat['conversation'].sessions
    assert [ctx['stage'] for ctx in seen] == ['idle', 'account', 'activity', 'idle']


def test_inferred_all_requires_confirmation_and_does_not_cross_stages(chat, monkeypatch):
    chat['config'].update(CONFIG)
    monkeypatch.setattr(qq_intent, 'interpret', lambda *args: '全选')
    say = chat['message']
    say('签到'); say('所有用户')
    assert '确认全选' in chat['sent'][-1][1]
    assert chat['conversation'].sessions[QQ]['phase'] == 'account' and not chat['calls']
    say('确认全选')
    assert chat['conversation'].sessions[QQ]['phase'] == 'activity' and not chat['calls']
    say('确认全选')
    assert '没有待确认' in chat['sent'][-1][1] and not chat['calls']
    say('所有活动'); say('取消'); say('确认全选')
    assert not chat['calls']


@pytest.mark.parametrize('failure', [False, True])
def test_unknown_or_api_failure_retains_session_and_permits_direct_selection(chat, monkeypatch, failure):
    chat['config'].update(CONFIG)
    def classify(*args):
        if failure:
            raise ValueError('模型接口暂不可用；请使用序号')
        return None
    monkeypatch.setattr(qq_intent, 'interpret', classify)
    say = chat['message']
    say('签到'); before = chat['conversation'].sessions[QQ]
    say('随便吧')
    assert before is chat['conversation'].sessions[QQ] and not chat['calls']
    say('1'); say('1')
    assert len(chat['calls']) == 1


def test_revoked_authorization_during_model_request_cannot_execute(chat, monkeypatch):
    chat['config'].update(CONFIG)
    def classify(*args):
        chat['config']['allowed_qqs'] = []
        return '1'
    monkeypatch.setattr(qq_intent, 'interpret', classify)
    say = chat['message']
    say('签到'); say('1'); say('第一个活动')
    assert not chat['calls']


def test_qr_text_and_untrusted_qq_never_reach_model(chat, monkeypatch):
    chat['config'].update(CONFIG)
    def fail(*args):
        pytest.fail('Image/link or unauthorized message reached model')
    monkeypatch.setattr(qq_intent, 'interpret', fail)
    say = chat['message']
    say('帮我签到', qq='30000001')
    say('https://qr.invalid/?enc=SECRET')
    say('SIGNIN:SECRET')
    assert not chat['calls']


def test_natural_multiselect_uses_only_selected_accounts(chat, monkeypatch):
    chat['config'].update(CONFIG)
    outputs = iter(['1,2', '1'])
    monkeypatch.setattr(qq_intent, 'interpret', lambda *args: next(outputs))
    say = chat['message']
    say('签到'); say('第一位和第二位'); say('第一个活动')
    assert len(chat['calls']) == 2
    assert {call[2][0]['value'] for call in chat['calls']} == {'13800000001', '13800000002'}


def test_settings_form_toggle_payload_and_test_are_wired_offline():
    from tests.test_camera_sign import run_node
    run_node(r'''
const fs=require('fs'),vm=require('vm'),assert=require('node:assert/strict');
const listeners={},fields={disabled:true};
const ctx={document:{addEventListener:(type,fn)=>listeners[type]=fn},state:{napcat_settings:{allowed_qqs:[],ws_url:'',token:''}},esc:String,$:()=>fields};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('web/napcat-settings.js','utf8'),ctx);
const html=ctx.napcatPanel();
for(const name of ['intent_enabled','intent_api_url','intent_api_key','intent_model'])assert(html.includes('name="'+name+'"'));
assert(html.includes('id="napcat-intent-fields" disabled'));assert(!html.includes('style='));
listeners.change({target:{id:'napcat-intent-enabled',checked:true}});assert.equal(fields.disabled,false);
const elements={};for(const n of ['ws_url','token','scan_base_url','intent_api_url','intent_api_key','intent_model'])elements[n]={value:' value '};
elements.allowed_qqs={value:'10000001\n10000002'};elements.enabled={checked:true};elements.intent_enabled={checked:true};
const payload=ctx.readNapCat({elements});assert.equal(payload.intent_enabled,true);assert.equal(payload.intent_api_key,' value ');
assert.equal(payload.intent_api_url,'value');assert.equal(payload.allowed_qqs.length,2);
''')


def test_model_settings_api_mask_encrypt_preserve_and_clear(browser, app, monkeypatch):
    assert browser.send('/napcat/intent/test', CONFIG).status_code == 401
    browser.admin_login()
    assert browser.client.post('/api/napcat/intent/test', json=CONFIG).status_code == 403
    response = browser.send('/napcat/settings', CONFIG, 'PUT')
    assert response.status_code == 200 and response.json['napcat_settings']['intent_api_key'] == MASK
    store = app.extensions['store']
    assert CONFIG['intent_api_key'].encode() not in store.path.read_bytes()
    assert CONFIG['intent_api_key'] not in json.dumps(browser.get('/bootstrap').json)
    assert browser.send('/napcat/settings', {'intent_api_key': MASK}, 'PUT').status_code == 200
    assert app.extensions['napcat'].settings()['intent_api_key'] == CONFIG['intent_api_key']
    seen = []
    def test(config):
        seen.append(copy.deepcopy(config))
        return {'ok': True, 'message': '离线成功'}
    monkeypatch.setattr('server.app.test_intent_connection', test)
    assert browser.send('/napcat/intent/test', {'intent_api_key': MASK}).json['ok']
    assert seen[0]['intent_api_key'] == CONFIG['intent_api_key']
    assert browser.send('/napcat/settings', {'intent_enabled': False, 'intent_api_key': ''}, 'PUT').status_code == 200
    assert app.extensions['napcat'].settings()['intent_api_key'] == ''


def transport(monkeypatch, *, status=200, body=None, chunks=None):
    seen = {}
    class Response:
        status_code = status
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, size):
            yield from chunks if chunks is not None else [json.dumps(body).encode()]
    class Session:
        trust_env = True
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, **kwargs):
            seen.update(url=url, trust_env=self.trust_env, **kwargs)
            return Response()
    monkeypatch.setattr(qq_intent.requests, 'Session', Session)
    return seen


def test_http_request_is_bounded_and_does_not_forward_credentials_in_prompt(monkeypatch):
    seen = transport(monkeypatch, body={'choices': [{'finish_reason': 'stop', 'message': {'content': result()}}]})
    assert qq_intent.interpret(CONFIG, '第一个和第三个 offline-model-key', CTX) == '1,3'
    assert not seen['trust_env'] and not seen['allow_redirects'] and seen['stream']
    assert seen['timeout'] == (3, 8) and seen['headers']['Authorization'] == 'Bearer offline-model-key'
    assert CONFIG['intent_api_key'] not in json.dumps(seen['json'])
    assert seen['json']['response_format'] == {'type': 'json_object'} and not seen['json'].get('tools')


@pytest.mark.parametrize('status,body,chunks', [
    (302, {}, None), (401, {'error': 'offline-model-key'}, None), (200, {}, None),
    (200, {'choices': [{'finish_reason': 'length', 'message': {'content': result()}}]}, None),
    (200, {}, [b'x'*4096]*17)])
def test_bad_http_responses_are_sanitized(monkeypatch, status, body, chunks):
    transport(monkeypatch, status=status, body=body, chunks=chunks)
    with pytest.raises(ValueError, match='模型接口暂不可用') as error:
        qq_intent.interpret(CONFIG, '第一个', CTX)
    assert CONFIG['intent_api_key'] not in str(error.value)


def test_synthetic_connection_probe_never_invokes_signing(monkeypatch):
    transport(monkeypatch, body={'choices': [{'finish_reason': 'stop', 'message': {'content': result()}}]})
    assert qq_intent.test_connection(CONFIG)['ok']
