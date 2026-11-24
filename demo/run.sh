#!/bin/bash
# Start the board web demo on the SDK.
#   demo/run.sh [--port 8765] [--models <package-root>]
# Env: A8_CLOCK_MS (160 | 80, default: the installed one), A8_LANG (en | zh, default en), A8_MODELS (default
#      <repo>/models), AUDIO8_ASR_LIB (optional explicit qualified library; default: installed SDK).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "Missing demo virtual environment: $ROOT/.venv" >&2
  echo "Create and activate .venv from the repository root to install the Demo." >&2
  echo "  python -m pip install -r requirements.txt" >&2
  echo "For SDK-only installation, see the SDK README (sdk/README.md)." >&2
  exit 1
fi
exec "$PYTHON" -u "$HERE/demo_server.py" "$@"
