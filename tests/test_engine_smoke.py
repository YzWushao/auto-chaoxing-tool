import os
import subprocess
import sys

from server.config import ENGINE


def test_real_engine_initializes_from_isolated_directory(tmp_path):
    code = """
import main
import configparser
from pathlib import Path
from api.cxsecret_font import fonthash_dao
assert len(fonthash_dao.char_map) > 1000
parser = configparser.ConfigParser(interpolation=None)
parser.read(Path(main.__file__).parent / 'config_template.ini', encoding='utf-8')
config = dict(parser['tiku'], provider='TikuManual', manual_mode_default='single')
client = main.init_chaoxing({'use_cookies': True}, config)
assert type(client.tiku).__name__ == 'TikuManual'
assert client.account.password == ''
print('ENGINE_OK')
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                            env=dict(os.environ, PYTHONPATH=str(ENGINE), PYTHONIOENCODING="utf-8"),
                            text=True, encoding="utf-8", capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "ENGINE_OK" in result.stdout


def test_quiz_job_discovery_does_not_complete_empty_pages(tmp_path):
    code = """
from unittest.mock import Mock, patch
from api.base import Chaoxing
client = object.__new__(Chaoxing)
client.kwargs = {'quiz_only':True}
client.rate_limiter = Mock()
client.study_emptypage = Mock()
response = Mock(status_code=200, text='offline')
with patch('api.base.SessionManager.get_session') as session, patch('api.base.decode_course_card', return_value=([],{'knowledgeid':'1'})):
    session.return_value.get.return_value = response
    course = {'courseId':'1','clazzId':'2','cpi':'3'}
    client.get_job_list(course, {'id':'point'})
    client.study_emptypage.assert_not_called()
    client.kwargs = {}
    client.get_job_list(course, {'id':'point'})
    assert client.study_emptypage.call_count == 1
    client.kwargs = {'quiz_only':True}
    response.status_code = 503
    try:
        client.get_job_list(course, {'id':'point'})
        raise AssertionError('A failed card request must not be treated as an empty chapter')
    except RuntimeError:
        pass
print('QUIZ_EMPTY_OK')
"""
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path,
                            env=dict(os.environ, PYTHONPATH=str(ENGINE), PYTHONIOENCODING='utf-8'),
                            text=True, encoding='utf-8', capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'QUIZ_EMPTY_OK' in result.stdout
