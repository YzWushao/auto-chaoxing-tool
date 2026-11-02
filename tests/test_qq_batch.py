"""Batch consent, per-account isolation and mixed QQ workflows with fake platform calls."""
import json
import time
from urllib.parse import urlsplit

import pytest

from server.chaoxing import PlatformError, SessionExpired
from server.qq_batch import selection
from server.napcat import SignConversation
from tests.conftest import FakeClient
from tests.test_napcat import chat, QQ, BOT
from tests.test_scan_links import grant, claim, QR, HEADERS
from tests.test_server_camera import wait_for, jpeg, post_frame


@pytest.mark.parametrize('text,expected',[
    ('1,3,5',[0,2,4]),('1，3、5',[0,2,4]),('1 3 5',[0,2,4]),('2,1,2',[1,0]),
    ('1-3,5',[0,1,2,4]),('2至4',[1,2,3]),('全选',list(range(15))),('一键全选',list(range(15))),
])
def test_selection_formats_and_global_select_all(text,expected):
    assert selection(text,15)==expected


@pytest.mark.parametrize('text',['0','1,99','3-1','1,x','1,,2','-1','1-99999999',''])
def test_bad_selection_is_rejected_atomically(text):
    with pytest.raises(ValueError):selection(text,5)


def test_multiple_users_share_merged_activity_and_keep_own_cookies(chat):
    say=chat['message'];say('签到');say('1,2')
    state=chat['conversation'].sessions[QQ]
    assert len(state['choices'])==4 and len(state['choices'][0]['targets'])==2
    assert '全选' in chat['sent'][-1][1]
    say('1')
    assert len(chat['calls'])==2 and {call[2][0]['value'] for call in chat['calls']}=={'13800000001','13800000002'}
    assert QQ not in chat['conversation'].sessions and '成功 2' in chat['sent'][-1][1]


def test_select_all_users_and_all_activities_handles_qr_then_skips_unavailable_tasks(chat):
    say=chat['message'];say('签到');say('一键全选');say('全选')
    assert len(chat['calls'])==2 and chat['conversation'].sessions[QQ]['phase']=='qr'
    say(image=True)
    assert len(chat['calls'])==4 and {c[0]['kind'] for c in chat['calls']}=={'normal','qr'}
    assert QQ not in chat['conversation'].sessions
    assert '成功 4' in chat['sent'][-1][1] and '跳过 4' in chat['sent'][-1][1]


def test_mixed_selection_uses_explicit_saved_point_for_each_chosen_user(browser,chat):
    browser.send('/location-presets',{'config':{'school':'离线学校','coordinate_system':'bd09',
        'points':[{'name':'教学楼','longitude':116.2,'latitude':40.3}]}})
    say=chat['message'];say('签到');say('1-2');say('1,3')
    assert len(chat['calls'])==2 and chat['conversation'].sessions[QQ]['phase']=='point'
    say('全选');assert len(chat['calls'])==2
    say('1');assert len(chat['calls'])==4
    location=[c for c in chat['calls'] if c[0]['kind']=='location']
    assert len(location)==2 and all(c[1]['longitude']=='116.200000' for c in location)


def test_single_user_can_multi_select_activities_without_changing_legacy_single_choice(chat):
    say=chat['message'];say('签到');say('1');say('1、2')
    assert len(chat['calls'])==1 and chat['conversation'].sessions[QQ]['phase']=='qr'
    say(image=True);assert len(chat['calls'])==2 and all(c[2][0]['value']=='13800000001' for c in chat['calls'])


def test_qr_partial_failure_retries_only_failed_accounts(chat,monkeypatch):
    original=FakeClient.sign;attempts={}
    def sign(client,activity,supplied,name):
        uid=client.cookies()[0]['value'];attempts[uid]=attempts.get(uid,0)+1
        if uid=='13800000002' and attempts[uid]==1:raise PlatformError('二维码已过期（离线）')
        return original(client,activity,supplied,name)
    monkeypatch.setattr(FakeClient,'sign',sign)
    say=chat['message'];say('签到');say('全选');say('2');say(image=True)
    assert len(chat['calls'])==1 and len(chat['conversation'].sessions[QQ]['batch_current']['targets'])==1
    assert '未完成' in chat['sent'][-1][1]
    say(image=True)
    assert attempts=={'13800000001':1,'13800000002':2} and len(chat['calls'])==2


def test_one_failed_user_does_not_stop_other_users(chat,monkeypatch):
    original=FakeClient.sign
    def sign(client,*args):
        if client.cookies()[0]['value']=='13800000001':raise SessionExpired('expired')
        return original(client,*args)
    monkeypatch.setattr(FakeClient,'sign',sign)
    say=chat['message'];say('签到');say('全选');say('1')
    assert len(chat['calls'])==1 and chat['calls'][0][2][0]['value']=='13800000002'
    assert '成功 1' in chat['sent'][-1][1] and '失败/待处理 1' in chat['sent'][-1][1]


def test_invalid_multiselect_does_not_partially_submit(chat):
    say=chat['message'];say('签到');say('1,999');assert not chat['calls']
    assert chat['conversation'].sessions[QQ]['phase']=='account'
    say('1,2');say('1,999');assert not chat['calls']
    assert chat['conversation'].sessions[QQ]['phase']=='activity'


def test_batch_qr_cancel_and_skip_never_replay_completed_normal_tasks(chat):
    say=chat['message'];say('签到');say('全选');say('1,2')
    assert len(chat['calls'])==2
    say('跳过');assert len(chat['calls'])==2 and QQ not in chat['conversation'].sessions
    say('签到');say('全选');say('2');say('取消');say(image=True)
    assert len(chat['calls'])==2 and QQ not in chat['conversation'].sessions
    say('全选');assert '没有有效' in chat['sent'][-1][1]


def test_merged_activities_only_submit_users_who_actually_have_the_activity(chat,monkeypatch):
    original=FakeClient.activities
    def activities(client,courses):
        result=original(client,courses)
        return result if client.cookies()[0]['value']=='13800000001' else [*result,{**result[0],'id':'905','title':'另一门课活动'}]
    monkeypatch.setattr(FakeClient,'activities',activities)
    say=chat['message'];say('签到');say('全选');say('5')
    assert len(chat['calls'])==1 and chat['calls'][0][0]['id']=='905' and chat['calls'][0][2][0]['value']=='13800000002'


def test_select_all_from_later_page_still_selects_every_user(chat,monkeypatch):
    conversation=chat['conversation'];owner=conversation.owner
    users=[dict(id=str(i),owner=owner,name='离线用户'+str(i),status='active') for i in range(13)]
    read=[];base=conversation.signing.refresh(owner,chat['accounts'][0]['id'])[0]
    monkeypatch.setattr(conversation,'accounts',lambda:users)
    monkeypatch.setattr(conversation.signing,'refresh',lambda owner,account:(read.append(account) or [base]))
    say=chat['message'];say('签到');say('下一页');assert '13.' in chat['sent'][-1][1]
    say('全选')
    assert read==[str(i) for i in range(13)] and len(conversation.sessions[QQ]['choices'][0]['targets'])==13
    assert not chat['calls']


def batch_token(grant, activities=None):
    signing=grant['app'].extensions['signing'];targets=[]
    for account in grant['accounts']:
        items=signing.refresh(grant['owner'],account['id'])
        targets.append(dict(owner=grant['owner'],account_id=account['id'],activities=[a for a in items if a['id']=='902']))
    return urlsplit(grant['links'].issue_many(QQ,targets)).fragment


@pytest.mark.parametrize('mode',['jpeg','native'])
def test_batch_camera_grant_is_scoped_to_selected_accounts_and_completes_all(grant,browser,mode):
    outsider=browser.login('13800000003')
    client,headers,_=claim(grant,batch_token(grant))
    start=client.post('/scan-api/start',json={'input':mode},headers=headers)
    assert start.status_code==200 and len(start.json['accounts'])==2
    if mode=='native':response=client.post('/scan-api/qr',json={'qr':QR},headers=headers)
    else:response=post_frame(client,'/scan-api/frame',jpeg(),headers)
    assert response.status_code==202
    result=wait_for(lambda:client.get('/scan-api/status',headers=headers),lambda r:r.status_code==200 and r.json.get('terminal'))
    assert result.json['state']=='completed' and FakeClient.sign_calls==2
    assert grant['store'].signed(grant['owner'],grant['accounts'][0]['id'],'902')
    assert grant['store'].signed(grant['owner'],grant['accounts'][1]['id'],'902')
    assert not grant['store'].signed(grant['owner'],outsider['id'],'902')
    serialized=json.dumps(result.json)
    assert QR not in serialized and all(a['id'] not in serialized for a in grant['accounts'])
    assert client.get('/api/bootstrap').status_code==401
    assert client.post('/scan-api/qr',json={'qr':QR},headers=headers).status_code==410


def test_batch_grant_checks_origin_scope_cancel_and_cannot_accept_account_ids(grant):
    client,headers,_=claim(grant,batch_token(grant))
    assert client.post('/scan-api/start',json={'input':'native','account_ids':['foreign']},headers=headers).status_code==400
    client.post('/scan-api/start',json={'input':'native'},headers=headers)
    assert client.post('/scan-api/qr',json={'qr':QR},headers={**headers,'Origin':'https://evil.invalid'}).status_code==403
    assert client.post('/scan-api/qr',json={'qr':QR.replace('902','903')},headers=headers).status_code==400
    assert client.post('/scan-api/submit',json={'qr':QR},headers=headers).status_code==400
    assert FakeClient.sign_calls==0
    grant['links'].revoke(QQ)
    assert client.post('/scan-api/qr',json={'qr':QR},headers=headers).status_code==410


def test_batch_grant_requires_common_activity_and_does_not_expire_when_only_one_user_signed(grant):
    token=batch_token(grant)
    grant['store'].mark_signed(grant['owner'],grant['accounts'][0]['id'],'902')
    client,headers,_=claim(grant,token)
    assert client.get('/scan-api/session',headers=headers).status_code==200
    grant['store'].mark_signed(grant['owner'],grant['accounts'][1]['id'],'902')
    assert client.get('/scan-api/session',headers=headers).status_code==410
    targets=[dict(owner=grant['owner'],account_id=a['id'],activities=[{'id':str(i),'kind':'qr','signed':False}]) for i,a in enumerate(grant['accounts'])]
    assert grant['links'].issue_many(QQ,targets) is None


def test_qq_batch_link_to_browser_completion_and_qq_continue(grant):
    sent=[];store=grant['store'];owner=grant['owner']
    conversation=SignConversation(store,grant['app'].extensions['signing'],owner,
        lambda action,params:sent.append(params['message'][0]['data']['text']),lambda:store.napcat_settings(owner),scan_links=grant['links'])
    counter=0
    def say(text):
        nonlocal counter
        counter+=1
        conversation.handle(dict(user_id=QQ,self_id=BOT,post_type='message',message_type='private',time=time.time(),message_id=counter,
                                 message=[{'type':'text','data':{'text':text}}]))
    # Legacy activity-scoped batch remains usable by existing callers; QQ now
    # opens the picker immediately when capability integration is installed.
    conversation.scan_links=None
    say('签到');say('全选')
    conversation.scan_links=grant['links']
    say('2')
    assert '一次性摄像头' in sent[-1]
    token=sent[-1].split('/scan#')[1].split()[0]
    client,headers,_=claim(grant,token)
    assert client.post('/scan-api/start',json={'input':'native'},headers=headers).status_code==200
    client.post('/scan-api/qr',json={'qr':QR},headers=headers)
    wait_for(lambda:client.get('/scan-api/status',headers=headers),lambda r:r.status_code==200 and r.json.get('terminal'))
    say('继续')
    assert QQ not in conversation.sessions and FakeClient.sign_calls==2 and '已完成 2' in sent[-1]


def test_batch_camera_does_not_repeat_account_completed_before_scanning(grant):
    token=batch_token(grant)
    grant['store'].mark_signed(grant['owner'],grant['accounts'][0]['id'],'902')
    client,headers,_=claim(grant,token)
    client.post('/scan-api/start',json={'input':'native'},headers=headers)
    client.post('/scan-api/qr',json={'qr':QR},headers=headers)
    result=wait_for(lambda:client.get('/scan-api/status',headers=headers),lambda r:r.status_code==200 and r.json.get('terminal'))
    assert result.json['state']=='completed' and FakeClient.sign_calls==1
