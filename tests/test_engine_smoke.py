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
