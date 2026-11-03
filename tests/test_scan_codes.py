import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from server.scan_links import ScanLinkExpired, digest
from tests.test_scan_links import grant, HEADERS, QQ
from tests.conftest import FakeClient


def verify(grant,code,**extra):
    client=grant['app'].test_client()
    result=client.post('/scan-api/verify',json={'code':code},headers=HEADERS,**extra)
    return client,result


def test_fixed_address_uses_eight_digits_and_only_hmac_is_kept(grant):
    access=grant['links'].issue_picker_code(QQ)
    assert access['url']=='https://scan.example.invalid/scan' and '#' not in access['url'] and '?' not in access['url']
    assert len(access['code'])==8 and all(c in '0123456789' for c in access['code'])
    assert not grant['links'].tickets and len(grant['links'].codes)==1
    assert digest(access['code']) not in grant['links'].codes
    assert access['code'] not in json.dumps(list(grant['links'].codes.values()),default=str)


def test_page_is_public_but_shows_no_account_information_before_verification(grant):
    access=grant['links'].issue_picker_code(QQ);client=grant['app'].test_client()
    for _ in range(2):
        page=client.get('/scan');assert page.status_code==200
        assert 'id="scan-code-form"' in page.text and 'inputmode="numeric"' in page.text
        assert '手机尾号 0001' not in page.text and access['code'] not in page.text
    assert len(grant['links'].codes)==1
    assert client.get('/api/bootstrap').status_code==401
    assert client.get('/scan-api/session',headers=HEADERS).status_code==410
    assert not FakeClient.sign_calls


def test_numeric_code_preserves_leading_zero_and_binds_only_scanner_scope(grant,monkeypatch):
    monkeypatch.setattr('server.scan_links.secrets.randbelow',lambda maximum:7)
    access=grant['links'].issue_picker_code(QQ);assert access['code']=='00000007'
    client,result=verify(grant,access['code'])
    assert result.status_code==200 and result.json['select_users']
    assert 'HttpOnly' in result.headers['Set-Cookie'] and access['code'] not in result.headers['Set-Cookie']
    headers={**HEADERS,'X-Scan-CSRF':result.json['csrf']}
    assert client.get('/scan-api/session',headers=headers).status_code==200
    assert client.get('/api/bootstrap').status_code==401
    assert verify(grant,access['code'])[1].status_code==410
    assert client.post('/scan-api/start',json={'account_ids':['foreign']},headers=headers).status_code==400


def test_code_has_exactly_one_winner_under_concurrent_verification(grant):
    code=grant['links'].issue_picker_code(QQ)['code']
    with ThreadPoolExecutor(max_workers=5) as pool:
        results=list(pool.map(lambda _:verify(grant,code)[1].status_code,range(5)))
    assert sorted(results)==[200,410,410,410,410]


def test_reissue_revocation_and_absolute_expiry(grant):
    links=grant['links'];first=links.issue_picker_code(QQ);second=links.issue_picker_code(QQ)
    assert first['url']==second['url'] and len(links.codes)==1
    with pytest.raises(ScanLinkExpired):links.verify_code(first['code'],'offline')
    next(iter(links.codes.values()))['expires']-=301
    assert verify(grant,second['code'])[1].status_code==410
    third=links.issue_picker_code(QQ);links.revoke(QQ)
    assert verify(grant,third['code'])[1].status_code==410


@pytest.mark.parametrize('code',[None,12345678,'1234567','123456789','abcdefgh','１２３４５６７８',' 12345678'])
def test_bad_codes_never_create_sessions(grant,code):
    _,result=verify(grant,code)
    assert result.status_code==410 and not grant['links'].sessions and not FakeClient.sign_calls


def test_attempt_limit_ignores_spoofed_forwarding_headers_and_does_not_consume_valid_code(grant):
    access=grant['links'].issue_picker_code(QQ)
    client=grant['app'].test_client()
    wrong='00000000' if access['code']!='00000000' else '11111111'
    for i in range(10):
        response=client.post('/scan-api/verify',json={'code':wrong},headers={**HEADERS,'X-Forwarded-For':f'192.0.2.{i}'})
        assert response.status_code==410
    response=client.post('/scan-api/verify',json={'code':access['code']},headers=HEADERS)
    assert response.status_code==429 and response.headers['Retry-After']=='60'
    assert len(grant['links'].codes)==1
    assert verify(grant,access['code'],environ_overrides={'REMOTE_ADDR':'192.0.2.99'})[1].status_code==200


def test_origin_guard_and_csrf_are_still_required(grant):
    access=grant['links'].issue_picker_code(QQ);client=grant['app'].test_client()
    assert client.post('/scan-api/verify',json={'code':access['code']}).status_code==403
    assert client.post('/scan-api/verify',json={'code':access['code']},headers={**HEADERS,'Origin':'https://foreign.invalid'}).status_code==403
    result=client.post('/scan-api/verify',json={'code':access['code']},headers=HEADERS);assert result.status_code==200
    assert client.get('/scan-api/session',headers=HEADERS).status_code==410


def test_recent_code_is_not_reused_when_rng_repeats(grant,monkeypatch):
    values=iter([7,7,8])
    monkeypatch.setattr('server.scan_links.secrets.randbelow',lambda maximum:next(values))
    first=grant['links'].issue_picker_code(QQ);second=grant['links'].issue_picker_code(QQ)
    assert first['code']=='00000007' and second['code']=='00000008'
    assert verify(grant,first['code'])[1].status_code==410
    assert verify(grant,second['code'])[1].status_code==200


def test_global_attempt_limit_and_expired_window(grant,monkeypatch):
    access=grant['links'].issue_picker_code(QQ)
    wrong='00000000' if access['code']!='00000000' else '11111111'
    for i in range(60):
        assert verify(grant,wrong,environ_overrides={'REMOTE_ADDR':f'192.0.2.{i}'})[1].status_code==410
    blocked=verify(grant,access['code'],environ_overrides={'REMOTE_ADDR':'192.0.2.200'})[1]
    assert blocked.status_code==429 and len(grant['links'].codes)==1
    from server.scan_links import time
    later=time.monotonic()+61
    monkeypatch.setattr(time,'monotonic',lambda:later)
    assert verify(grant,access['code'])[1].status_code==200
