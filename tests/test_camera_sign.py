import json
import shutil
import subprocess

import pytest

from server.camera_sign import qr_parameters
from server.chaoxing import PlatformError
from server.config import ROOT
from tests.conftest import FakeClient, Browser


QR = 'https://mobilelearn.chaoxing.com/widget/sign/e?id=902&enc=OFFLINE_CAMERA_TOKEN_123'


@pytest.fixture
def qr_activity(monkeypatch):
    original = FakeClient.activities
    monkeypatch.setattr(FakeClient, 'activities', lambda self, courses: [
        {**original(self, courses)[0], 'id': '902', 'kind': 'qr'}])


@pytest.mark.parametrize('raw', [QR, QR.replace('?id=', '?aid='), QR.replace('?id=', '?activeId='),
                                'SIGNIN:aid=902&source=15&code=123456&enc=OFFLINE_TOKEN_123-extra'])
def test_both_camera_wire_formats(raw):
    activity, enc = qr_parameters(raw)
    assert activity == '902' and enc.startswith('OFFLINE_')


@pytest.mark.parametrize('raw', [None, 123, 'OFFLINE_TOKEN_123', 'https://example.invalid/?id=1&enc=short',
                                QR.replace('id=902', 'id=0'), 'x'*4097])
def test_invalid_scan_cannot_start_a_sign_request(raw):
    with pytest.raises(ValueError):
        qr_parameters(raw)


def test_camera_endpoint_requires_admin_csrf_and_managed_account(browser, app):
    assert browser.send('/accounts/not-owned/camera-sign', {'qr': QR}).status_code == 401
    account = browser.login()
    url = f"/accounts/{account['id']}/camera-sign"
    outsider = Browser(app)
    assert outsider.send(url, {'qr': QR}).status_code == 401
    assert browser.client.post('/api'+url, json={'qr': QR}).status_code == 403
    assert browser.send('/accounts/not-owned/camera-sign', {'qr': QR}).status_code == 404
    assert browser.send(url, {'qr': QR, 'pixels': 'not-accepted'}).status_code == 400
    headers = browser.client.get('/').headers
    assert headers['Permissions-Policy'] == 'camera=(self), microphone=()'
    assert "media-src 'self' blob:" in headers['Content-Security-Policy']


def test_camera_auto_resolves_owned_activity_and_keeps_real_identity(browser, qr_activity, monkeypatch):
    first = browser.login()
    second = browser.login('13800000002')
    browser.send('/preferences', {'account_label': 'surname_tail'}, 'PUT')
    calls = []
    def signed(client, activity, supplied, name):
        calls.append((client.jar[0]['value'], activity['id'], supplied['qr'], name))
        return '签到成功（离线）'
    monkeypatch.setattr(FakeClient, 'sign', signed)
    for account in (first, second):
        result = browser.send(f"/accounts/{account['id']}/camera-sign", {'qr': QR})
        assert result.status_code == 200 and result.json['activity_id'] == '902'
    assert calls == [('13800000001', '902', 'OFFLINE_CAMERA_TOKEN_123', '测试用户0001'),
                     ('13800000002', '902', 'OFFLINE_CAMERA_TOKEN_123', '测试用户0002')]
    assert browser.send(f"/accounts/{first['id']}/camera-sign", {'qr': QR}).json['duplicate'] is True
    assert len(calls) == 2


def test_failures_are_not_success_and_retry_is_bounded(browser, qr_activity, monkeypatch):
    account = browser.login()
    def rejected(*args):
        raise PlatformError('二维码已过期（离线）')
    monkeypatch.setattr(FakeClient, 'sign', rejected)
    url = f"/accounts/{account['id']}/camera-sign"
    result = browser.send(url, {'qr': QR})
    assert result.status_code == 502 and '过期' in result.json['error']
    assert browser.send(url, {'qr': QR}).status_code == 429
    assert not any(e['kind'] == 'sign_success' for e in browser.get('/bootstrap').json['events'])


def test_scanned_id_cannot_bypass_membership_or_sign_mode(browser, monkeypatch):
    account = browser.login()
    result = browser.send(f"/accounts/{account['id']}/camera-sign", {'qr': QR})
    assert result.status_code == 400 and '没有此' in result.json['error']
    other = browser.login('13800000002')
    result = browser.send(f"/accounts/{other['id']}/camera-sign", {'qr': QR.replace('id=902', 'id=901')})
    assert result.status_code == 400 and '不是单独的二维码' in result.json['error']
    assert FakeClient.sign_calls == 0


def test_camera_can_resolve_opted_in_group_activity(browser, monkeypatch):
    from tests.test_group_sign import group_activity
    account = browser.login()
    group = {**group_activity(), 'id': '902', 'kind': 'qr'}
    browser.send('/preferences', {'include_group_sign': True}, 'PUT')
    monkeypatch.setattr(FakeClient, 'group_activities', lambda c: [group], raising=False)
    monkeypatch.setattr(FakeClient, 'group_activity', lambda c, selected: group, raising=False)
    assert browser.send(f"/accounts/{account['id']}/camera-sign", {'qr': QR}).status_code == 200


def run_node(program):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for offline camera queue tests')
    return subprocess.run([node, '-e', program], cwd=ROOT, text=True, encoding='utf-8', capture_output=True, timeout=15, check=True)


def test_queue_handoff_occurs_on_eleventh_failure_without_losing_users():
    run_node(r'''
const assert=require('node:assert/strict'),{Queue,parameters}=require('./web/camera-queue.js');
const q=new Queue([{id:'a',name:'甲'},{id:'b',name:'乙'},{id:'a',name:'甲'}]);
assert.equal(q.entries.length,2);assert.equal(q.bind('902'),true);assert.equal(q.bind('903'),false);
for(let i=1;i<=10;i++){q.begin();const r=q.finish(false,'过期');assert.equal(r.moved,false);assert.equal(q.current.id,'a');}
q.begin();const last=q.finish(false,'过期');assert.equal(last.moved,true);
assert.deepEqual(q.order,['b','a']);assert.equal(q.entries[0].failures,11);assert.equal(q.entries[0].passFailures,0);
q.begin();q.finish(true,'成功');assert.deepEqual(q.order,['a']);
q.begin();q.defer('限流');assert.equal(q.entries[0].failures,11);assert.equal(q.entries[0].attempts,11);
q.begin();q.finish(true,'成功');assert.equal(q.done,true);assert.equal(q.begin(),null);
assert.equal(parameters('not-a-sign-qr'),null);
assert.equal(parameters('SIGNIN:aid=902&enc=OFFLINE_TOKEN_123-extra').activityId,'902');
assert.equal(parameters('https://example.invalid/?aid=902&enc=OFFLINE_TOKEN_123').activityId,'902');
''')


def test_camera_controller_uses_fresh_qr_and_releases_tracks():
    run_node("require('./tests/camera_controller.cjs')")


def test_camera_parallel_batches_keep_account_results_and_verifications_separate():
    run_node("require('./tests/camera_concurrency.cjs')")


def test_five_camera_requests_overlap_without_mixing_cookies(browser, app, qr_activity, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    accounts = [browser.login(f'1380000000{i}') for i in range(1, 6)]
    clients = [Browser(app) for _ in accounts]
    for client in clients:
        assert client.admin_login().status_code == 200
    barrier = threading.Barrier(5)
    calls = []
    def sign(client, activity, supplied, name):
        barrier.wait(timeout=10)
        calls.append((client.jar[0]['value'], name))
        return '离线并发成功'
    monkeypatch.setattr(FakeClient, 'sign', sign)
    with ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(lambda pair: pair[0].send(
            f"/accounts/{pair[1]['id']}/camera-sign", {'qr': QR}), zip(clients, accounts)))
    assert [r.status_code for r in results] == [200] * 5
    assert sorted(calls) == [(f'1380000000{i}', f'测试用户000{i}') for i in range(1, 6)]
