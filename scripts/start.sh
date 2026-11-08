#!/usr/bin/env bash
# Build the web app and serve app + API on http://127.0.0.1:8000 (loopback only). Ctrl+C to stop.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ "${1:-}" == "--no-build" ]] || scripts/build_web.sh >/dev/null
echo "LABMATE: http://127.0.0.1:8000   API docs: http://127.0.0.1:8000/api/docs"
exec .venv/bin/python scripts/dev_server.py
