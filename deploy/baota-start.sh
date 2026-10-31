#!/bin/sh
# Use as a Baota Python project's custom command, running as autochaoxing.
set -eu
set -a
. /etc/auto-chaoxing-tool/environment
set +a
cd /opt/auto-chaoxing-tool
exec /opt/auto-chaoxing-tool/.venv/bin/python -u run.py --host 127.0.0.1 --port 8765
