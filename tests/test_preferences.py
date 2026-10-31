import pytest
from server.preferences import account_label, validate_preferences, DEFAULT_PREFERENCES


@pytest.mark.parametrize('mode,expected', [('phone_tail','手机尾号 1234'),('surname_mask','张**'),('full_name','张三丰'),('masked_surname','*三丰'),('surname_tail','张 1234')])
def test_five_display_modes(mode,expected):
    assert account_label({'name':'张三丰','phone':'13800001234','uid':'56789'},mode)==expected


def test_compound_surname_and_missing_phone():
    value={'name':'欧阳娜娜','phone':'13800001234','uid':'56789'}
    assert account_label(value,'surname_mask')=='欧阳**'
    assert account_label(value,'masked_surname')=='**娜娜'
    assert account_label(value,'surname_tail')=='欧阳 1234'
    value['phone']=''
    assert account_label(value)=='UID 尾号 6789'
    assert account_label(value,'surname_tail')=='欧阳 · UID 尾号 6789'


def test_preferences_auth_csrf_and_preserve_platform_real_name(browser,app):
    assert browser.send('/preferences',{},'PUT').status_code==401
    account=browser.login()
    assert account['name']=='手机尾号 0001'
    assert browser.client.put('/api/preferences',json={}).status_code==403
    result=browser.send('/preferences',{'account_label':'full_name'},'PUT')
    assert result.status_code==200 and result.json['accounts'][0]['name']=='测试用户0001'
    owner=app.extensions['napcat'].owner
    assert app.extensions['store'].account(owner,account['id'])['name']=='测试用户0001'
    assert browser.get('/bootstrap').json['preferences']['account_label']=='full_name'


@pytest.mark.parametrize('data',[{'account_label':'unknown'},{'account_label':[]},{'include_group_sign':'yes'},{'token':'not-allowed'}])
def test_bad_preferences(data):
    with pytest.raises(ValueError):
        validate_preferences(data,DEFAULT_PREFERENCES)


@pytest.mark.parametrize('data', [
    {'camera_concurrency': 0}, {'camera_concurrency': 6}, {'camera_concurrency': 1.5},
    {'camera_concurrency': True}, {'camera_concurrency': '5'},
    {'camera_scan_interval': 0}, {'camera_scan_interval': 10.1},
    {'camera_scan_interval': True}, {'camera_scan_interval': '0.1'},
    {'camera_scan_interval': float('nan')}, {'camera_scan_interval': float('inf')},
])
def test_invalid_camera_preferences(data):
    with pytest.raises(ValueError):
        validate_preferences(data, DEFAULT_PREFERENCES)


def test_camera_preferences_default_save_and_restart(browser, app):
    from server.store import Store
    browser.admin_login()
    preferences = browser.get('/bootstrap').json['preferences']
    assert preferences['camera_concurrency'] == 1
    assert preferences['camera_scan_interval'] == 0.1
    saved = browser.send('/preferences', {'camera_concurrency': 5, 'camera_scan_interval': 0.25}, 'PUT')
    assert saved.status_code == 200
    browser.send('/preferences', {'account_label': 'full_name'}, 'PUT')
    store = Store(app.extensions['store'].directory)
    owner = store.administrator()['owner']
    preferences = store.preferences(owner)
    assert preferences['camera_concurrency'] == 5
    assert preferences['camera_scan_interval'] == 0.25
    assert preferences['account_label'] == 'full_name'
    # An existing installation's older saved preferences receive both defaults.
    store.set_preferences(owner, {'account_label': 'full_name', 'include_group_sign': True})
    defaults = browser.get('/bootstrap').json['preferences']
    assert defaults['camera_concurrency'] == 1 and defaults['camera_scan_interval'] == 0.1
