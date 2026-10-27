"""Local web console. All mutable state lives in AUTO_CHAOXING_DATA_DIR."""
import argparse
import atexit
import os

from waitress import serve
from server.app import create_app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto Chaoxing Tool Web Console")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    app = create_app()
    atexit.register(app.extensions["tasks"].shutdown)
    atexit.register(app.extensions['napcat'].stop)
    app.extensions['napcat'].start()
    print(f"Auto Chaoxing Tool: http://{args.host}:{args.port}", flush=True)
    print("使用管理员账号登录；首次默认 admin / admin，请进入设置修改后再开放远程访问。", flush=True)
    serve(app, host=args.host, port=args.port, threads=12, max_request_body_size=1024 * 1024)
