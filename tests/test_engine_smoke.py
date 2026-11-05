import os
import subprocess
import sys

import pytest

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


@pytest.mark.parametrize('mode', ['card', 'api'])
@pytest.mark.parametrize('delay', ['0', '0.125'])
def test_web_string_delay_reaches_real_tikuhai_query_loop_as_number(tmp_path, mode, delay):
    code = """
import main
from pathlib import Path
import configparser
from unittest.mock import patch
parser = configparser.ConfigParser(interpolation=None)
parser.read(Path(main.__file__).parent / 'config_template.ini', encoding='utf-8')
config = dict(parser['tiku'], provider='TikuHai', tikuhai_auth_mode=__mode_literal__,
              tikuhai_card='offline-card', tikuhai_api_key='offline-key', delay=__delay_literal__)
client = main.init_chaoxing({'use_cookies': True}, config)
assert client.kwargs['query_delay'] == float(__delay_literal__)
questions = [{'title':'original question', 'type':'single', 'options':'A. one\\nB. two'}] * 2
with patch.object(client.tiku, '_query', return_value='two') as query, \\
     patch('api.answer.time.sleep') as sleep, \\
     patch('requests.sessions.Session.request', side_effect=AssertionError('No real requests')):
    answers = client.tiku.query_all(questions, query_delay=client.kwargs['query_delay'])
    assert answers == ['two', 'two'] and query.call_count == 2
    assert sleep.call_count == (2 if float(__delay_literal__) > 0 else 0)
    if sleep.call_count:
        assert all(call.args == (float(__delay_literal__),) for call in sleep.call_args_list)
print('QUERY_DELAY_OK')
""".replace('__mode_literal__', repr(mode)).replace('__delay_literal__', repr(delay))
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path,
                            env=dict(os.environ, PYTHONPATH=str(ENGINE), PYTHONIOENCODING='utf-8'),
                            text=True, encoding='utf-8', capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'QUERY_DELAY_OK' in result.stdout
