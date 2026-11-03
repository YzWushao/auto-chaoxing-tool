import copy

import pytest

from server.napcat import DEFAULT
from server.preferences import account_label
from server.chaoxing import SessionExpired
from tests.conftest import FakeClient
from tests.test_napcat import chat, QQ


def integrated(app,chat):
    chat['config']['scan_base_url']='https://scan.example.invalid'
    app.extensions['store'].set_napcat_settings(app.extensions['napcat'].owner,{**DEFAULT,**chat['config']})
    chat['conversation'].scan_links=app.extensions['scan_links']
    return chat['message']


@pytest.mark.parametrize('mode',['phone_tail','surname_mask','full_name','masked_surname','surname_tail'])
def test_sign_checks_all_users_sorts_by_count_and_appends_global_nicknames(app,browser,chat,monkeypatch,mode):
    browser.login('13800000003');browser.send('/preferences',{'account_label':mode},'PUT')
    checked=[]
    def activities(client,courses):
        uid=client.cookies()[0]['value'];checked.append(uid)
        ids={'13800000001':['910','920','930'],'13800000002':['920','930'],'13800000003':['920']}[uid]
        return [dict(id=aid,title={'910':'单人活动','920':'三人活动','930':'两人活动'}[aid],kind='normal',course=courses[0],photo=False) for aid in ids]
    monkeypatch.setattr(FakeClient,'activities',activities)
    say=integrated(app,chat);say('签到')
    state=chat['conversation'].sessions[QQ]
    assert state['phase']=='activity' and state['all_accounts'] and state['batch']
    assert set(checked)=={'13800000001','13800000002','13800000003'} and len(checked)==3
    assert [a['id'] for a in state['choices']]==['920','930','910']
    expected={account_label(a,mode) for a in chat['conversation'].accounts()}
    assert {a['name'] for a in state['choices'][0]['targets']}==expected
    text=chat['sent'][-1][1]
    assert text.index('三人活动')<text.index('两人活动')<text.index('单人活动')
    assert '涉及 3 人（' in text and all(name in text for name in expected)
    assert not chat['calls'] and not app.extensions['scan_links'].tickets


def test_scan_sign_is_direct_link_and_never_fetches_activities(app,chat,monkeypatch):
    def fail(*args):pytest.fail('Camera link command must not query activities or call model')
    monkeypatch.setattr(FakeClient,'activities',fail)
    monkeypatch.setattr('server.qq_intent.interpret',fail)
    chat['config']['intent_enabled']=True
    say=integrated(app,chat);say('扫码签到')
    assert '/scan#' in chat['sent'][-1][1] and '摄像头' in chat['sent'][-1][1]
    assert QQ not in chat['conversation'].sessions and not chat['calls']


def test_one_failed_user_does_not_hide_other_user_information(app,chat,monkeypatch):
    original=FakeClient.activities;checked=[]
    def activities(client,courses):
        uid=client.cookies()[0]['value'];checked.append(uid)
        if uid.endswith('0001'):raise SessionExpired('离线失效')
        return original(client,courses)
    monkeypatch.setattr(FakeClient,'activities',activities)
    say=integrated(app,chat);say('签到')
    assert len(checked)==2 and any('登录已失效' in text for _,text in chat['sent'])
    assert chat['conversation'].sessions[QQ]['phase']=='activity' and not chat['calls']


def test_long_nickname_annotations_are_split_without_being_lost(app,chat):
    say=integrated(app,chat);say('签到')
    state=chat['conversation'].sessions[QQ]
    item=copy.deepcopy(state['choices'][0]);names=[f'测试昵称用户{i:03d}' for i in range(200)]
    item['targets']=[dict(name=name) for name in names];state['choices']=[item]
    chat['sent'].clear();chat['conversation'].show(QQ,state)
    combined=''.join(text for _,text in chat['sent'])
    assert all(name in combined for name in names)
    assert all(len(text)<=1800 for _,text in chat['sent']) and not chat['calls']


def test_all_user_information_is_not_truncated_by_old_200_user_selection_limit(app,chat,monkeypatch):
    say=integrated(app,chat);owner=app.extensions['napcat'].owner;checked=[]
    users=[dict(owner=owner,id=f'offline-{i}',name=f'测试用户{i}',phone='',uid=str(1000+i),status='active') for i in range(205)]
    monkeypatch.setattr(chat['conversation'],'accounts',lambda:users)
    monkeypatch.setattr(app.extensions['signing'],'refresh',lambda o,a:checked.append(a) or [])
    say('签到')
    assert len(checked)==205 and not chat['calls']
