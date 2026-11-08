#!/usr/bin/env bash
# One-time setup: Python 3.12 venv (via uv), backend deps, Playwright Chromium, Flutter packages.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || python3 -m pip install --user --index-url https://pypi.org/simple uv
UV=$(command -v uv || echo "$HOME/.local/bin/uv")
[[ -d .venv ]] || "$UV" venv --python 3.12 .venv
"$UV" pip install --python .venv/bin/python --index-url https://pypi.org/simple -r requirements-dev.txt
.venv/bin/playwright install chromium
[[ -f .env ]] || cp .env.example .env
export PATH="${FLUTTER_ROOT:-$HOME/flutter}/bin:$PATH"
command -v flutter >/dev/null || git clone --depth 1 -b stable https://github.com/flutter/flutter.git "$HOME/flutter"
(cd app && flutter pub get)
echo "Setup done. Put GEMINI_API_KEY in .env, then scripts/start.sh"
