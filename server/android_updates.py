"""Public, credential-free Android release metadata and fixed APK download."""
import hashlib
import json
import os
import re
from pathlib import Path

from flask import jsonify, send_file


def install_android_updates(app):
    directory = Path(app.config.get('ANDROID_RELEASE_DIR') or os.getenv('AUTO_CHAOXING_ANDROID_RELEASE_DIR') or Path(app.root_path).parent/'releases').resolve()
    cached = {}

    def release():
        try:
            manifest = directory/'release.json'
            if manifest.stat().st_size > 16384:
                raise ValueError()
            data = json.loads(manifest.read_text(encoding='utf-8'))
            if not isinstance(data,dict) or not isinstance(data.get('version_name'),str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}(?:-[a-zA-Z0-9.-]+)?',data['version_name']):
                raise ValueError()
            filename = data['filename']
            if not isinstance(filename,str) or Path(filename).name != filename or not filename.endswith('.apk'):
                raise ValueError()
            path = (directory/filename).resolve()
            if path.parent != directory or not path.is_file():
                raise ValueError()
            stat = path.stat()
            if not 0 < stat.st_size <= 100*1024*1024 or type(data['version_code']) is not int or not 0 < data['version_code'] < 2100000000:
                raise ValueError()
            identity = (str(path),stat.st_mtime_ns,stat.st_size)
            if cached.get('identity') != identity:
                with path.open('rb') as file:
                    hasher=hashlib.sha256()
                    for chunk in iter(lambda:file.read(65536),b''):
                        hasher.update(chunk)
                    digest=hasher.hexdigest()
                cached.update(identity=identity,sha256=digest)
            if data['sha256'] != cached['sha256']:
                raise ValueError()
            return path,dict(available=True,version_code=data['version_code'],version_name=str(data['version_name'])[:64],
                             sha256=cached['sha256'],size=stat.st_size,notes=str(data.get('notes',''))[:2000])
        except (OSError,ValueError,TypeError,KeyError):
            return None,{'available':False}

    @app.get('/android/update.json')
    def android_update_metadata():
        _,data = release()
        response = jsonify(data)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/android/latest.apk')
    def android_update_apk():
        path,data = release()
        if path is None:
            return jsonify(error='暂无可用安卓更新'),404
        response = send_file(path,mimetype='application/vnd.android.package-archive',as_attachment=True,
                             download_name='auto-chaoxing-tool-'+data['version_name']+'.apk',conditional=True)
        response.headers['Cache-Control'] = 'no-store'
        return response
