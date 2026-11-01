"""Capability boundary tests: fake accounts and platform only, no QQ messages."""
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import pytest

from server.chaoxing import PlatformError, SessionExpired, CaptchaRequired
from server.napcat import SignConversation, validate_settings, DEFAULT
from server.scan_links import ScanLinkExpired
from tests.conftest import FakeClient
from tests.test_napcat import QQ, BOT, TOKEN
from tests.test_sign_verification import challenge
from tests.test_camera_sign import run_node

QR = 'https://mobilelearn.chaoxing.com/widget/sign/e?id=902&enc=OFFLINE_SCAN_TOKEN_123'
HEADERS = {'X-Scan-Request': '1', 'Origin': 'http://localhost'}


def test_limited_scanner_releases_camera_and_handles_expiry_and_late_results():
    run_node("require('./tests/scan_link_controller.cjs')")


@pytest.fixture
def grant(app, browser, monkeypatch):
    first = browser.login()
    second = browser.login('13800000002')
    original = FakeClient.activities
    monkeypatch.setattr(FakeClient, 'activities', lambda self, courses: [
        *original(self, courses), {**original(self, courses)[0], 'id': '902', 'kind': 'qr'},
        {**original(self, courses)[0], 'id': '903', 'kind': 'qr'}])
    store, links, signing = (app.extensions[name] for name in ('store', 'scan_links', 'signing'))
    owner = app.extensions['napcat'].owner
    store.set_napcat_settings(owner, {**DEFAULT, 'enabled': True, 'ws_url': 'ws://localhost:12345',
                                     'token': TOKEN, 'allowed_qqs': [QQ], 'scan_base_url': 'https://scan.example.invalid'})
    activities = signing.refresh(owner, first['id'])
    def issue(items=None):
        return urlsplit(links.issue(QQ, owner, first['id'], activities if items is None else items)).fragment
    return dict(app=app, store=store, links=links, owner=owner, accounts=[first, second], issue=issue, activities=activities)


def claim(grant, token=None):
    client = grant['app'].test_client()
    result = client.post('/scan-api/claim', json={'token': token or grant['issue']()}, headers=HEADERS)
    assert result.status_code == 200, result.json
    return client, {**HEADERS, 'X-Scan-CSRF': result.json['csrf']}, result


def test_claim_is_atomic_one_use_and_never_authenticates_console(grant):
    token = grant['issue']()
    client, headers, result = claim(grant, token)
    assert set(result.json) == {'csrf', 'remaining_seconds', 'scan_interval'}
    assert 0 < result.json['remaining_seconds'] <= 300
    cookie = result.headers['Set-Cookie']
    assert 'HttpOnly' in cookie and 'Path=/scan-api' in cookie and 'SameSite=Strict' in cookie
    assert token not in cookie
    assert grant['app'].test_client().post('/scan-api/claim', json={'token': token}, headers=HEADERS).status_code == 410
    assert client.get('/api/session').json['authenticated'] is False
    for path in ('/api/bootstrap', '/api/accounts', '/api/napcat/settings', '/api/location-presets'):
        assert client.get(path).status_code == 401
    assert client.get('/scan-api/session', headers=headers).status_code == 200
    assert client.get('/scan-api/session').status_code == 403
    assert client.get('/scan-api/session', headers={'X-Scan-Request': '1'}).status_code == 410


def test_parallel_claim_has_exactly_one_winner(grant):
    token = grant['issue']()
    def enter(_):
        return grant['app'].test_client().post('/scan-api/claim', json={'token': token}, headers=HEADERS).status_code
    with ThreadPoolExecutor(max_workers=5) as executor:
        assert sorted(executor.map(enter, range(5))) == [200, 410, 410, 410, 410]


def test_link_scope_cannot_be_changed_and_completion_revokes_every_request(grant, monkeypatch):
    calls = []
    monkeypatch.setattr(FakeClient, 'sign', lambda client, activity, supplied, name:
                        calls.append((client.jar[0]['value'], activity['id'])) or 'sensitive upstream name')
    client, headers, _ = claim(grant)
    for payload in ({'qr': QR, 'account_id': grant['accounts'][1]['id']}, {'qr': QR, 'face_id': 'foreign'},
                    {'qr': QR, 'verification_id': 'foreign'}, {'qr': QR, 'location': {}},
                    {'qr': QR.replace('id=902', 'id=901')}, {'qr': QR.replace('id=902', 'id=904')}):
        assert client.post('/scan-api/submit', json=payload, headers=headers).status_code == 400
    assert not calls
    response = client.post('/scan-api/submit', json={'qr': QR}, headers=headers)
    assert response.json == {'completed': True, 'message': '本次签到已完成，入口已失效。'}
    assert calls == [('13800000001', '902')]
    assert client.get('/scan-api/session', headers=headers).status_code == 410
    assert client.post('/scan-api/submit', json={'qr': QR}, headers=headers).status_code == 410


@pytest.mark.parametrize('claimed', [False, True])
def test_expiry_is_absolute_and_cannot_be_extended(grant, claimed):
    token = grant['issue']()
    if claimed:
        client, headers, _ = claim(grant, token)
        record = next(iter(grant['links'].sessions.values()))
        before = record['expires']
        assert client.get('/scan-api/session', headers=headers).status_code == 200
        assert record['expires'] == before
        record['expires'] -= 301
        assert client.post('/scan-api/submit', json={'qr': QR}, headers=headers).status_code == 410
    else:
        next(iter(grant['links'].tickets.values()))['expires'] -= 301
        assert grant['app'].test_client().post('/scan-api/claim', json={'token': token}, headers=HEADERS).status_code == 410
    assert FakeClient.sign_calls == 0


@pytest.mark.parametrize('revoke', ['new_link', 'cancel', 'disable', 'remove_qq', 'remove_account', 'signed_elsewhere', 'close'])
def test_revocation_covers_existing_browser(grant, revoke):
    client, headers, _ = claim(grant)
    links, store, owner = grant['links'], grant['store'], grant['owner']
    if revoke == 'new_link':
        grant['issue']()
    elif revoke == 'cancel':
        links.revoke(QQ)
    elif revoke in {'disable', 'remove_qq'}:
        config = store.napcat_settings(owner)
        config.update({'enabled': False} if revoke == 'disable' else {'allowed_qqs': []})
        store.set_napcat_settings(owner, config)
    elif revoke == 'remove_account':
        with store.connect() as db:
            db.execute('DELETE FROM accounts WHERE id=?', (grant['accounts'][0]['id'],))
    elif revoke == 'signed_elsewhere':
        store.mark_signed(owner, grant['accounts'][0]['id'], '902')
    else:
        assert client.post('/scan-api/close', json={}, headers=headers).status_code == 200
    assert client.get('/scan-api/session', headers=headers).status_code == 410


def test_failed_scan_binds_one_activity_and_does_not_disclose_platform_data(grant, monkeypatch):
    client, headers, _ = claim(grant)
    def reject(*args):
        raise PlatformError('private-session-fixture phone13800000001 ' + TOKEN)
    monkeypatch.setattr(FakeClient, 'sign', reject)
    response = client.post('/scan-api/submit', json={'qr': QR}, headers=headers)
    assert response.status_code == 502
    assert 'private' not in response.text and TOKEN not in response.text and '13800000001' not in response.text
    assert client.post('/scan-api/submit', json={'qr': QR.replace('id=902', 'id=903')}, headers=headers).status_code == 400
    assert client.post('/scan-api/submit', json={'qr': QR}, headers=headers).status_code == 429
    assert client.get('/scan-api/session', headers=headers).status_code == 200


@pytest.mark.parametrize('error', [SessionExpired('secret name'), CaptchaRequired(challenge(), 'private-enc')])
def test_platform_verification_is_not_bypassed_or_exposed(grant, monkeypatch, error):
    def reject(*args):
        raise error
    monkeypatch.setattr(FakeClient, 'sign', reject)
    client, headers, _ = claim(grant)
    response = client.post('/scan-api/submit', json={'qr': QR}, headers=headers)
    assert response.status_code == 422 and response.json['code'] == 'stop'
    assert set(response.json) == {'error', 'code'}
    assert 'private' not in response.text and 'secret' not in response.text


def test_origin_json_csrf_and_no_store_boundaries(grant):
    client = grant['app'].test_client()
    token = grant['issue']()
    for headers in ({}, {'X-Scan-Request': '1'}, {**HEADERS, 'Origin': 'https://evil.invalid'}):
        assert client.post('/scan-api/claim', json={'token': token}, headers=headers).status_code == 403
    assert client.post('/scan-api/claim', data='token='+token, headers=HEADERS).status_code == 400
    client, headers, _ = claim(grant, token)
    assert client.post('/scan-api/submit', json={'qr': QR}, headers={**headers, 'X-Scan-CSRF': 'bad'}).status_code == 410
    page = client.get('/scan')
    assert page.status_code == 200 and page.headers['Cache-Control'] == 'no-store'
    assert page.headers['Referrer-Policy'] == 'no-referrer'
    assert page.headers['X-Robots-Tag'].startswith('noindex')
    assert '/static/app.js' not in page.text and 'name="password"' not in page.text
    assert client.post('/scan-api/submit', json={'qr': 'x'*9000}, headers=headers).status_code == 400


def test_https_origin_works_behind_http_reverse_proxy_and_keeps_secure_cookie(grant):
    app = grant['app']
    app.config['SESSION_COOKIE_SECURE'] = True
    client = app.test_client()
    # Exactly the production topology: browser HTTPS, proxy-to-Waitress HTTP.
    headers = {'X-Scan-Request': '1', 'Origin': 'https://localhost'}
    response = client.post('/scan-api/claim', json={'token': grant['issue']()}, headers=headers)
    assert response.status_code == 200
    assert 'Secure;' in response.headers['Set-Cookie']
    assert client.post('/scan-api/close', json={}, headers={**headers, 'X-Scan-CSRF': response.json['csrf']}).status_code == 200
    assert client.post('/scan-api/claim', json={'token': grant['issue']()}, headers=HEADERS).status_code == 403


@pytest.mark.parametrize('value', ['http://example.invalid', 'https://u:p@example.invalid', 'https://example.invalid/path',
                                 'https://example.invalid/?token=x', 'javascript:alert(1)', 'https://example.invalid:99999'])
def test_public_origin_configuration_rejects_unsafe_or_ambiguous_urls(value):
    with pytest.raises(ValueError):
        validate_settings({'scan_base_url': value}, DEFAULT)


def test_qq_refresh_sends_scoped_link_and_selection_replaces_it(grant):
    sent = []
    store, owner, links = grant['store'], grant['owner'], grant['links']
    chat = SignConversation(store, grant['app'].extensions['signing'], owner,
                            lambda action, params: sent.append(params['message'][0]['data']['text']),
                            lambda: store.napcat_settings(owner), scan_links=links)
    import time
    def say(text, index):
        chat.handle({'user_id': QQ, 'self_id': BOT, 'post_type': 'message', 'message_type': 'private',
                     'time': time.time(), 'message_id': index, 'message': [{'type': 'text', 'data': {'text': text}}]})
    say('签到', 1); say('1', 2)
    assert '/scan#' in sent[-1] and '免控制台登录' in sent[-1]
    old = sent[-1].split('/scan#')[1].split()[0]
    say('2', 3)
    assert '上传' in sent[-1] and '/scan#' in sent[-1]
    with pytest.raises(ScanLinkExpired):
        links.claim(old)
    record = next(iter(links.tickets.values()))
    assert record['allowed'] == {'902'} and record['account_id'] == grant['accounts'][0]['id']
    say('取消', 4)
    assert not links.tickets and not links.sessions
