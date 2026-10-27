import base64
import copy
import io
import json
import queue
import threading
import time

import pytest
import qrcode
from websockets.sync.server import serve

from server.chaoxing import PlatformError
from server.config import MASK
from server.napcat import SignConversation, validate_settings, DEFAULT
from server.sign_images import decode_picture, image_url, qq_picture
from server.sign_coordinates import location_parameters
from tests.conftest import FakeClient

QQ = '10000001'
BOT = '20000001'
TOKEN = 'offline-token-not-a-real-credential'


def qr_bytes(text='https://mobilelearn.chaoxing.com/widget/sign/e?id=other&enc=EXPIRED_TEST_TOKEN_123&time=1'):
    stream = io.BytesIO()
    qrcode.make(text).save(stream, format='PNG')
    return stream.getvalue()


@pytest.fixture
def chat(app, browser, monkeypatch):
    first = browser.login('13800000001')
    second = browser.login('13800000002')
    calls = []
    def activities(client, courses):
        return [{'id': str(901+i), 'title': kind+'活动', 'kind': kind, 'course': courses[0], 'photo': False}
                for i, kind in enumerate(['normal', 'qr', 'location', 'code'])]
    def sign(client, activity, supplied, name):
        calls.append((copy.deepcopy(activity), copy.deepcopy(supplied), copy.deepcopy(client.cookies())))
        return '签到成功（离线）'
    monkeypatch.setattr(FakeClient, 'activities', activities)
    monkeypatch.setattr(FakeClient, 'sign', sign)
    manager = app.extensions['napcat']
    config = {'enabled': True, 'ws_url': 'ws://127.0.0.1:12345/', 'token': TOKEN, 'allowed_qqs': [QQ, '10000002']}
    sent = []
    def rpc(action, params):
        if action == 'get_image':
            return {'base64': base64.b64encode(qr_bytes()).decode()}
        assert action == 'send_private_msg'
        sent.append((str(params['user_id']), params['message'][0]['data']['text']))
        return {'message_id': 9}
    conversation = SignConversation(app.extensions['store'], app.extensions['signing'], manager.owner, rpc, lambda: config)
    counter = 0
    def message(text='', *, qq=QQ, image=False, **changes):
        nonlocal counter
        counter += 1
        event = {'self_id': int(BOT), 'post_type': 'message', 'message_type': 'private', 'user_id': int(qq), 'message_id': counter,
                 'time': time.time(), 'message': [{'type': 'image', 'data': {'file': 'fixture.png'}}] if image else [{'type': 'text', 'data': {'text': text}}]}
        event.update(changes)
        conversation.handle(event)
        return event
    return {'conversation': conversation, 'message': message, 'sent': sent, 'calls': calls, 'accounts': [first, second], 'config': config}


def test_asks_who_then_refreshes_selected_account_before_normal_sign(chat):
    say, calls, sent = chat['message'], chat['calls'], chat['sent']
    say('签到')
    assert '为谁签到' in sent[-1][1] and '0001' in sent[-1][1] and '0002' in sent[-1][1]
    assert not calls
    say('2')
    assert '签到列表' in sent[-1][1] and '二维码' in sent[-1][1]
    event = say('1')
    assert len(calls) == 1 and calls[0][2][0]['value'] == '13800000002'
    assert '成功' in sent[-1][1]
    chat['conversation'].handle(event)
    assert len(calls) == 1


def test_qr_waits_for_image_then_passes_enc_without_expiry_or_activity_filter(chat):
    say = chat['message']
    say('签到'); say('1'); say('2')
    assert not chat['calls'] and '上传' in chat['sent'][-1][1]
    say('不是图片')
    assert not chat['calls']
    say(image=True)
    assert chat['calls'][0][1]['qr'] == 'EXPIRED_TEST_TOKEN_123'
    assert chat['calls'][0][0]['id'] == '902'


def test_location_uses_saved_point_selected_by_number(app, browser, chat):
    browser.send('/location-presets', {'config': {'school': '离线学校', 'coordinate_system': 'bd09', 'points': [
        {'name': '教学楼甲', 'longitude': 116.1, 'latitude': 40.1, 'address': '离线地址甲'},
        {'name': '教学楼乙', 'longitude': 116.2, 'latitude': 40.2, 'address': '离线地址乙'}]}})
    say = chat['message']
    say('签到'); say('1'); say('3')
    assert '教学楼甲' in chat['sent'][-1][1] and '教学楼乙' in chat['sent'][-1][1]
    assert not chat['calls']
    say('2')
    supplied = chat['calls'][0][1]
    assert supplied['kind'] == 'location' and supplied['longitude'] == '116.200000' and supplied['address'] == '离线地址乙'
    assert app.extensions['store'].signed(app.extensions['napcat'].owner, chat['accounts'][0]['id'], '903')


def test_location_without_presets_and_unsupported_mode_do_not_submit(chat):
    say = chat['message']
    say('签到'); say('1'); say('3')
    assert '没有已保存' in chat['sent'][-1][1]
    say('4')
    assert '网页' in chat['sent'][-1][1]
    assert not chat['calls']


@pytest.mark.parametrize('changes', [
    {'user_id': 99999999}, {'message_type': 'group', 'group_id': 1}, {'post_type': 'message_sent'},
    {'user_id': int(BOT)}, {'time': 1}, {'message_id': 'bad'}, {'message': '[CQ:image,file=xxx]'}])
def test_unauthorized_group_self_stale_or_malformed_events_ignored(chat, changes):
    chat['message']('签到', **changes)
    assert not chat['sent'] and not chat['calls']


def test_cancel_timeout_invalid_selection_and_qq_session_isolation(chat):
    say = chat['message']
    say('签到'); say('0')
    assert '有效序号' in chat['sent'][-1][1]
    say('签到', qq='10000002'); say('2', qq='10000002')
    assert chat['conversation'].sessions[QQ]['phase'] == 'account'
    assert chat['conversation'].sessions['10000002']['phase'] == 'activity'
    say('取消')
    assert QQ not in chat['conversation'].sessions
    say('1')
    assert '没有有效' in chat['sent'][-1][1]
    chat['conversation'].sessions['10000002']['touched'] -= 301
    say('1', qq='10000002')
    assert '没有有效' in chat['sent'][-1][1]
    assert not chat['calls']


def test_live_activity_revalidated_and_web_and_qq_share_duplicate_guard(app, browser, chat):
    say = chat['message']
    say('签到'); say('1')
    account = chat['accounts'][0]['id']
    assert browser.send(f'/accounts/{account}/sign', {'activity_id': '901'}).status_code == 200
    say('1')
    assert len(chat['calls']) == 1 and '无需重复' in chat['sent'][-1][1]


def test_platform_errors_do_not_mark_success_and_can_retry(chat, monkeypatch):
    def fail(*args):
        raise PlatformError('二维码已过期（离线测试）')
    monkeypatch.setattr(FakeClient, 'sign', fail)
    say = chat['message']
    say('签到'); say('1'); say('2'); say(image=True)
    assert '过期' in chat['sent'][-1][1]
    assert chat['conversation'].sessions[QQ]['phase'] == 'qr'
    assert not chat['calls']


def test_web_refresh_mode_change_cannot_turn_qr_into_normal(app, browser, chat, monkeypatch):
    say = chat['message']
    say('签到'); say('1')
    def changed(client, courses):
        return [{'id': '901', 'title': 'changed', 'kind': 'qr', 'course': courses[0], 'photo': False}]
    monkeypatch.setattr(FakeClient, 'activities', changed)
    assert browser.get(f"/accounts/{chat['accounts'][0]['id']}/activities").status_code == 200
    say('1')
    assert not chat['calls'] and '方式已变化' in chat['sent'][-1][1]


def test_modified_point_is_not_silently_submitted(app, browser, chat):
    config = {'school': '离线学校', 'coordinate_system': 'bd09', 'points': [{'name': '教学楼', 'longitude': 116, 'latitude': 40}]}
    assert browser.send('/location-presets', {'config': config}).status_code == 200
    say = chat['message']
    say('签到'); say('1'); say('3')
    config['points'][0]['longitude'] = 117
    browser.send('/location-presets', {'config': config, 'replace': True})
    say('1')
    assert not chat['calls'] and '修改或删除' in chat['sent'][-1][1]


def test_photo_requirement_and_expired_login_never_auto_submit(app, chat, monkeypatch):
    def photo(client, courses):
        return [{'id': '901', 'title': 'photo', 'kind': 'normal', 'course': courses[0], 'photo': True}]
    monkeypatch.setattr(FakeClient, 'activities', photo)
    say = chat['message']
    say('签到'); say('1'); say('1')
    assert not chat['calls'] and '网页端' in chat['sent'][-1][1]
    FakeClient.expired = True
    try:
        say('签到'); say('1')
        assert '登录已失效' in chat['sent'][-1][1] and QQ not in chat['conversation'].sessions
    finally:
        FakeClient.expired = False


def test_many_points_paginate_without_losing_global_number(app, browser, chat):
    config = {'school': '离线学校', 'coordinate_system': 'bd09', 'points': [{'name': f'教学楼{i+1}', 'longitude': 116+i/1000, 'latitude': 40} for i in range(30)]}
    browser.send('/location-presets', {'config': config})
    say = chat['message']
    say('签到'); say('1'); say('3'); say('下一页')
    assert '13. 离线学校 · 教学楼13' in chat['sent'][-1][1] and '第 2/3 页' in chat['sent'][-1][1]
    say('下一页'); say('30')
    assert chat['calls'][0][1]['longitude'] == '116.029000'


def test_napcat_config_auth_csrf_masks_encryption_and_export(browser, app):
    assert browser.get('/napcat/settings').status_code == 401
    assert browser.send('/napcat/test').status_code == 401
    browser.admin_login()
    config = {'enabled': True, 'ws_url': 'ws://127.0.0.1:12345/', 'token': TOKEN, 'allowed_qqs': [QQ]}
    assert browser.client.put('/api/napcat/settings', json=config).status_code == 403
    response = browser.send('/napcat/settings', config, 'PUT')
    assert response.status_code == 200
    assert response.json['napcat_settings']['token'] == MASK
    assert TOKEN not in json.dumps(browser.get('/bootstrap').json)
    assert TOKEN not in json.dumps(browser.get('/location-presets/export').json)
    assert TOKEN.encode() not in app.extensions['store'].path.read_bytes()
    assert browser.send('/napcat/settings', {'token': MASK}, 'PUT').status_code == 200
    assert app.extensions['napcat'].settings()['token'] == TOKEN


@pytest.mark.parametrize('value', [
    {'enabled': True}, {'enabled': 'true'}, {'ws_url': 'http://example.com'}, {'ws_url': 'ws://user:pw@example.com'},
    {'ws_url': 'ws://example.com/?access_token=secret'}, {'ws_url': 'ws://example.com:99999'},
    {'allowed_qqs': ['0']}, {'allowed_qqs': [12345]}, {'token': 'hello\r\nInjected: x'}, {'unknown': True}])
def test_invalid_napcat_configuration(value):
    with pytest.raises(ValueError):
        validate_settings(value, DEFAULT)


def test_qr_decode_and_no_arbitrary_url_or_file_download():
    assert decode_picture(qr_bytes('PLAIN_ENC_123456')) == 'PLAIN_ENC_123456'
    assert decode_picture(qr_bytes()) == 'EXPIRED_TEST_TOKEN_123'
    with pytest.raises(ValueError):
        decode_picture(b'not an image')
    for value in ['file:///secret.key', 'http://127.0.0.1/a', 'https://qpic.cn.evil.invalid/a', 'https://user:pw@gchat.qpic.cn/a', 'https://gchat.qpic.cn:8765/a']:
        with pytest.raises(ValueError):
            image_url(value)
    assert image_url('http://gchat.qpic.cn/a?k=public-image') == 'https://gchat.qpic.cn/a?k=public-image'


def test_bad_qq_image_does_not_open_remote_local_path():
    with pytest.raises(ValueError):
        qq_picture(lambda *args: {'file': 'C:/secret.key', 'url': 'file:///secret.key'}, {'data': {'file': 'image-id'}})


def test_coordinates_match_known_web_projection():
    result = location_parameters({'longitude': 116.404, 'latitude': 39.915, 'coordinate_system': 'wgs84', 'address': 'offline'})
    assert abs(float(result['longitude']) - 116.416627) < 0.000001
    assert abs(float(result['latitude']) - 39.922700) < 0.000001
    bd = {'longitude': 116.1, 'latitude': 40.1, 'coordinate_system': 'bd09', 'address': 'offline'}
    assert location_parameters(bd)['longitude'] == '116.100000'


def test_real_websocket_transport_routes_echo_and_private_events(app, browser, monkeypatch):
    browser.login()
    replies = queue.Queue()
    connected = queue.Queue()
    def handler(socket):
        connected.put(socket)
        try:
            for raw in socket:
                value = json.loads(raw)
                data = {'user_id': BOT} if value['action'] == 'get_login_info' else {'message_id': 1}
                socket.send(json.dumps({'status': 'ok', 'retcode': 0, 'data': data, 'echo': value['echo']}))
                if value['action'] == 'send_private_msg':
                    replies.put(value['params']['message'][0]['data']['text'])
        except Exception:
            pass
    with serve(handler, '127.0.0.1', 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        manager = app.extensions['napcat']
        app.extensions['store'].set_napcat_settings(manager.owner, {'enabled': True, 'ws_url': f'ws://127.0.0.1:{server.socket.getsockname()[1]}/', 'token': TOKEN, 'allowed_qqs': [QQ]})
        manager.start()
        try:
            socket = connected.get(timeout=5)
            deadline = time.monotonic()+5
            while manager.status()['state'] != 'connected' and time.monotonic() < deadline:
                threading.Event().wait(.02)
            assert manager.status()['state'] == 'connected'
            socket.send(json.dumps({'post_type': 'message', 'message_type': 'private', 'self_id': BOT, 'user_id': QQ, 'message_id': 1, 'time': time.time(), 'message': [{'type': 'text', 'data': {'text': '签到'}}]}))
            assert '为谁签到' in replies.get(timeout=5)
        finally:
            manager.stop()
            server.shutdown()
            thread.join(timeout=5)
        assert manager.status()['state'] == 'disabled'
