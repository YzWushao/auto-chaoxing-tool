import hashlib
import json
import time

import pytest
from werkzeug.security import check_password_hash

from server.app import create_app
from server.config import account_defaults
from server.store import Store
from tests.conftest import Browser, FakeClient


def test_default_administrator_and_protected_platform_login(app, browser):
    assert browser.get('/session').json['auth_mode'] == 'admin'
    for path in ('/auth/password', '/auth/qr', '/auth/qr/token/poll', '/auth/qr/token/cancel'):
        assert browser.send(path).status_code == 401
    before = browser.csrf
    assert browser.admin_login(password='wrong').status_code == 401
    assert browser.admin_login().status_code == 200
    assert browser.csrf != before
    data = browser.get('/bootstrap').json
    assert data['admin'] == {'username': 'admin', 'default_password': True}
    assert data['accounts'] == []
    with app.extensions['store'].connect() as db:
        row = db.execute('SELECT * FROM administrators').fetchone()
        assert row['password_hash'] != 'admin'
        assert check_password_hash(row['password_hash'], 'admin')
    assert 'password_hash' not in json.dumps(data)


def test_legacy_signed_owner_cookie_is_not_admin(browser):
    with browser.client.session_transaction() as sess:
        sess['owner'] = 'old-platform-uid'
    assert browser.get('/session').json['authenticated'] is False
    assert browser.get('/bootstrap').status_code == 401


def test_sqlite_session_survives_restart_and_logout_revokes_copy(app, browser):
    browser.admin_login()
    cookie = browser.client.get_cookie('ac_console').value
    with browser.client.session_transaction() as sess:
        token = sess['admin_sid']
    with app.extensions['store'].connect() as db:
        row = db.execute('SELECT * FROM admin_sessions').fetchone()
        assert row['token_hash'] == hashlib.sha256(token.encode()).hexdigest()
        assert token not in str(tuple(row))
    restarted = create_app({'TESTING': True, 'DATA_DIR': app.config['DATA_DIR']}, FakeClient)
    other = Browser(restarted)
    other.client.set_cookie('ac_console', cookie)
    other.csrf = other.get('/session').json['csrf']
    assert other.get('/session').json['authenticated'] is True
    assert other.send('/auth/logout').status_code == 200
    assert browser.get('/session').json['authenticated'] is False
    assert browser.get('/bootstrap').status_code == 401


def test_expired_admin_session_requires_login(app, browser):
    browser.admin_login()
    with app.extensions['store'].connect() as db:
        db.execute('UPDATE admin_sessions SET expires_at=?', (time.time() - 1,))
    assert browser.get('/session').json['authenticated'] is False
    assert browser.get('/bootstrap').status_code == 401


def test_rename_and_password_change_revoke_all_sessions_without_deleting_accounts(app, browser):
    account = browser.login()
    other = Browser(app)
    other.admin_login()
    response = browser.send('/admin/credentials', {'username': '管理员', 'current_password': 'admin', 'new_password': 'new-admin-password'}, 'PUT')
    assert response.status_code == 200
    assert response.json['reauthenticate'] is True
    assert other.get('/bootstrap').status_code == 401
    browser.csrf = browser.get('/session').json['csrf']
    assert browser.admin_login().status_code == 401
    assert browser.admin_login('管理员', 'new-admin-password').status_code == 200
    data = browser.get('/bootstrap').json
    assert data['admin'] == {'username': '管理员', 'default_password': False}
    assert [a['id'] for a in data['accounts']] == [account['id']]
    assert browser.get(f"/accounts/{account['id']}/courses").status_code == 200
    restarted = create_app({'TESTING': True, 'DATA_DIR': app.config['DATA_DIR']}, FakeClient)
    fresh = Browser(restarted)
    assert fresh.admin_login().status_code == 401
    assert fresh.admin_login('管理员', 'new-admin-password').status_code == 200


@pytest.mark.parametrize('changes', [
    {'current_password': 'bad'}, {'username': ''}, {'username': 'white space'},
    {'new_password': 'short'}, {'new_password': ' ' * 10}, {'new_password': None},
    {'username': 'x' * 65}, {'unknown': 'field'},
])
def test_bad_admin_updates_do_not_change_credentials(browser, changes):
    browser.admin_login()
    response = browser.send('/admin/credentials', {'username': 'admin', 'current_password': 'admin', **changes}, 'PUT')
    assert response.status_code == 400
    assert browser.get('/session').json['authenticated'] is True


def test_rename_only_retains_password_and_warning(browser):
    browser.admin_login()
    assert browser.send('/admin/credentials', {'username': 'owner', 'current_password': 'admin'}, 'PUT').status_code == 200
    browser.csrf = browser.get('/session').json['csrf']
    assert browser.admin_login('owner', 'admin').status_code == 200
    assert browser.get('/bootstrap').json['admin']['default_password'] is True


def test_relogin_targets_original_identity_and_preserves_config(browser):
    account = browser.login()
    path = f"/accounts/{account['id']}/config"
    browser.send(path, {'course_keys': ['101:201']}, 'PUT')
    payload = {'phone': '13800000002', 'password': 'fixture-password', 'account_id': account['id']}
    assert browser.send('/auth/password', payload).status_code == 400
    payload['phone'] = '13800000001'
    response = browser.send('/auth/password', payload)
    assert response.status_code == 200
    assert response.json['account']['id'] == account['id']
    assert response.json['account']['config']['course_keys'] == ['101:201']
    assert len(browser.get('/bootstrap').json['accounts']) == 1


def test_legacy_workspaces_and_duplicate_uids_are_preserved(tmp_path):
    old = Store(tmp_path)
    primary = old.save_account('legacy-primary', {'uid': '1', 'name': '主账户'}, [], account_defaults())
    old.save_account('legacy-primary', {'uid': '2', 'name': '附加账户'}, [], account_defaults())
    duplicate = old.save_account('legacy-secondary', {'uid': '1', 'name': '另一配置'}, [], account_defaults())
    old.set_settings('legacy-primary', {'api': {'model': 'legacy-model'}})
    old.set_settings('legacy-secondary', {'api': {'model': 'other-model'}})
    old.mark_signed('legacy-secondary', duplicate['id'], 'activity')
    with old.connect() as db:
        db.execute("INSERT INTO jobs VALUES ('old-job','legacy-secondary',?,'succeeded','{}','now','now',NULL)", (duplicate['id'],))
        db.execute("INSERT INTO logs(job_id,level,message,created_at) VALUES ('old-job','info','legacy log','now')")
        db.execute('DELETE FROM administrators')
        db.execute('DELETE FROM admin_workspaces')
    migrated = create_app({'TESTING': True, 'DATA_DIR': tmp_path}, FakeClient)
    browser = Browser(migrated)
    browser.admin_login()
    data = browser.get('/bootstrap').json
    assert len(data['accounts']) == 3
    assert {primary['id'], duplicate['id']} <= {a['id'] for a in data['accounts']}
    assert data['settings']['api']['model'] == 'legacy-model'
    assert browser.get('/jobs/old-job/logs').json['logs'][0]['message'] == 'legacy log'
    assert migrated.extensions['store'].signed('legacy-secondary', duplicate['id'], 'activity')
    assert migrated.extensions['store'].settings('legacy-secondary')['api']['model'] == 'other-model'


def test_admin_updates_still_require_csrf_and_matching_origin(browser):
    browser.admin_login()
    assert browser.client.put('/api/admin/credentials', json={}).status_code == 403
    assert browser.client.put('/api/admin/credentials', json={}, headers={'X-CSRF-Token': browser.csrf, 'Origin': 'https://evil.example'}).status_code == 403


def test_platform_login_does_not_save_after_admin_revocation(app, browser, monkeypatch):
    browser.admin_login()
    original = FakeClient.login_password

    def revoke_during_login(client, phone, password):
        profile = original(client, phone, password)
        with app.extensions['store'].connect() as db:
            db.execute('DELETE FROM admin_sessions')
        return profile

    monkeypatch.setattr(FakeClient, 'login_password', revoke_during_login)
    assert browser.send('/auth/password', {'phone': '13800000001', 'password': 'fixture-password'}).status_code == 401
    with app.extensions['store'].connect() as db:
        assert db.execute('SELECT COUNT(*) FROM accounts').fetchone()[0] == 0


def test_admin_login_is_rate_limited(browser):
    for i in range(12):
        assert browser.admin_login(password='bad').status_code == 401
    assert browser.admin_login().status_code == 400


def test_unmanaged_workspace_cannot_be_accessed(app, browser):
    hidden = app.extensions['store'].save_account('unmanaged', {'uid': 'hidden', 'name': 'private'}, [], account_defaults())
    browser.admin_login()
    assert browser.get('/bootstrap').json['accounts'] == []
    assert browser.get(f"/accounts/{hidden['id']}/courses").status_code == 404
    assert browser.send('/auth/password', {'phone': '13800000001', 'password': 'fixture-password', 'account_id': hidden['id']}).status_code == 404


@pytest.mark.parametrize('action', ['logout', 'credentials'])
def test_admin_session_changes_do_not_stop_running_tasks(app, browser, action):
    from unittest.mock import Mock
    account = browser.login()
    manager = app.extensions['tasks']
    owner = app.extensions['store'].managed_owners(1)[0]
    process = Mock()
    manager.running['test-running'] = {'owner': owner, 'account': account['id'], 'process': process, 'stopped': False}
    try:
        if action == 'logout':
            response = browser.send('/auth/logout')
        else:
            response = browser.send('/admin/credentials', {'username': 'renamed', 'current_password': 'admin'}, 'PUT')
        assert response.status_code == 200
        process.terminate.assert_not_called()
        assert manager.running['test-running']['stopped'] is False
    finally:
        manager.running.clear()


def test_qr_login_is_bound_to_admin_and_can_be_cancelled(app, browser):
    from tests.test_platform import response

    class Client:
        def request(self, *args, **kwargs):
            return response('<input id="uuid" value="u"><input id="enc" value="e">', {'status': False})
    qr = app.extensions['qr']
    qr.factory = Client
    browser.admin_login()
    created = browser.send('/auth/qr').json
    outsider = Browser(app)
    outsider.admin_login()
    assert outsider.send(f"/auth/qr/{created['id']}/poll").status_code == 400
    assert outsider.send(f"/auth/qr/{created['id']}/cancel").status_code == 200
    assert created['id'] in qr.entries
    assert browser.send(f"/auth/qr/{created['id']}/cancel").status_code == 200
    assert created['id'] not in qr.entries
