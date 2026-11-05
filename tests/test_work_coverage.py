import copy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from server.config import ENGINE


@pytest.fixture
def work(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(ENGINE))
    from api import base
    from api.work_answers import matched_answer
    return base, matched_answer


@pytest.mark.parametrize('kind,result,options,expected', [
    ('single', 'two', 'A. one\nB. two', 'B'),
    ('single', 'B', 'A. one\nB. two', 'B'),
    ('single', 'B. two', 'A. one\nB. two', 'B'),
    ('single', 'B. incorrect', 'A. one\nB. two', ''),
    ('single', 'almos', 'A. almost\nB. other', ''),
    ('single', 'same', 'A. same\nB. same', ''),
    ('single', None, 'A. one\nB. two', ''),
    ('single', 'Hello, world', 'A. Hello, world\nB. Goodbye', 'A'),
    ('multiple', 'one\ntwo', 'A. one\nB. two', 'AB'),
    ('multiple', 'AB', 'A. one\nB. two', 'AB'),
    ('multiple', ['one', 'missing'], 'A. one\nB. two', ''),
    ('multiple', 'one\nmissing', 'A. one\nB. two', ''),
    ('judgement', 'correct', '', 'true'),
    ('judgement', '错误', '', 'false'),
    ('judgement', 'maybe', '', ''),
    ('completion', None, '', ''),
    ('completion', ['first', ''], '', ''),
    ('completion', ['first', 'second'], '', 'firstsecond'),
])
def test_only_complete_unambiguous_answers_are_filled(work, kind, result, options, expected):
    _, match = work
    tiku = SimpleNamespace(true_list=['correct'], false_list=[])
    assert match({'type': kind, 'options': options}, result, tiku) == expected


@pytest.mark.parametrize('threshold,hits,submit,rollback,manual,flag', [
    (0.9, 1, True, 0, False, '1'),
    (0.9, 1, True, 2, False, '1'),
    (0.9, 1, True, 0, True, '1'),
    (0.5, 1, True, 0, False, ''),
    (1, 2, True, 0, False, ''),
    (0.5, 2, False, 0, False, '1'),
    (0, 0, True, 0, False, ''),
    (1, 1, True, 0, False, '1'),
])
def test_actual_work_payload_respects_threshold_and_never_guesses(
        work, monkeypatch, threshold, hits, submit, rollback, manual, flag):
    base, _ = work
    questions = {'questions': [dict(id=str(i), title='offline question', type='single',
                                   options='A. one\nB. two', answerField={f'answertype{i}': '0'}) for i in range(2)]}
    monkeypatch.setattr(base, 'decode_questions_info', lambda html: copy.deepcopy(questions))
    monkeypatch.setattr(base, 'random_answer', Mock(side_effect=AssertionError('Random answers forbidden')))
    http = Mock()
    http.get.return_value = SimpleNamespace(status_code=200, text='offline fixture')
    http.post.return_value = SimpleNamespace(status_code=200, json=lambda: {'status': True, 'msg': 'offline'})
    monkeypatch.setattr(base.SessionManager, 'get_session', lambda: http)
    tiku = SimpleNamespace(DISABLE=False, COVER_RATE=threshold, is_manual=manual,
                           true_list=[], false_list=[], get_submit_params=lambda: '' if submit else '1',
                           query_all=lambda *a, **k: ['two'] * hits + [None] * (2 - hits))
    client = base.Chaoxing(tiku=tiku)
    client.rollback_times = rollback
    client._check_work_result = Mock(return_value=None)
    result = client.study_work({'clazzId': '2', 'courseId': '1'},
                               {'jobid': 'work-3', 'enc': 'offline'},
                               {'knowledgeid': '4', 'ktoken': 'offline', 'cpi': '5'})
    assert result == base.StudyResult.SUCCESS
    payload = http.post.call_args.kwargs['data']
    assert payload['pyFlag'] == flag
    assert [payload[f'answer{i}'] for i in range(2)] == ['B'] * hits + [''] * (2 - hits)
    assert http.post.call_count == 1
    assert client._check_work_result.call_count == (0 if flag == '1' else 1)


def test_percent_input_and_storage_conversion():
    from tests.test_camera_sign import run_node
    run_node(r"""
      const assert=require('node:assert/strict'), fs=require('node:fs'),vm=require('node:vm');
      const source=fs.readFileSync('web/app.js','utf8');
      const context=vm.createContext({state:{schema:{api:{cover_rate:'0.9'},providers:[]}},labels:{},secrets:new Set(),esc:String});
      vm.runInContext(source.slice(source.indexOf('function apiFields('),source.indexOf('function timingFields(')),context);
      const html=vm.runInContext("apiFields({cover_rate:'0.875'})",context);
      assert(html.includes('min="0" max="100"'));
      assert(html.includes('value="87.5"'));
      assert(html.includes('不随机作答'));
      context.$$=()=>[{name:'api.cover_rate',value:'87.5'},{name:'api.submit',value:'true'}];
      vm.runInContext(source.slice(source.indexOf('function readApi('),source.indexOf('\n',source.indexOf('function readApi('))),context);
      assert.equal(vm.runInContext('readApi({}).cover_rate',context),'0.875');
      assert.equal(vm.runInContext('readApi({}).submit',context),'true');
    """)


def test_rate_is_preserved_for_global_and_individual_configs(browser, app, monkeypatch):
    account = browser.login()
    path = '/accounts/' + account['id']
    captured = []
    monkeypatch.setattr(app.extensions['tasks'], 'start', lambda owner, account, api, courses:
                        captured.append(api['cover_rate']) or {'id': 'offline'})
    assert browser.send('/settings', {'api': {'cover_rate': '0.875'}}, 'PUT').status_code == 200
    assert browser.send(path + '/config', {'course_keys': ['101:201'], 'api': {'cover_rate': '1'}}, 'PUT').status_code == 200
    assert browser.send(path + '/study').status_code == 202
    assert captured[-1] == '0.875'
    browser.send(path + '/config', {'inherit_api': False}, 'PUT')
    assert browser.send(path + '/study').status_code == 202
    assert captured[-1] == '1'
    assert browser.get('/bootstrap').json['settings']['api']['cover_rate'] == '0.875'


@pytest.mark.parametrize('value', ['-0.1', '1.01', 'NaN', 'inf'])
def test_invalid_minimum_rate_is_rejected(browser, value):
    browser.admin_login()
    assert browser.send('/settings', {'api': {'cover_rate': value}}, 'PUT').status_code == 400
