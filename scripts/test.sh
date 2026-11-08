#!/usr/bin/env bash
# Offline tests (no key): backend pytest, Flutter unit tests, headless-browser E2E.
# Add --live to also run the real-Gemini smoke test and the live browser E2E.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="${FLUTTER_ROOT:-$HOME/flutter}/bin:$PATH"
echo "== backend =="; GEMINI_API_KEY= .venv/bin/python -W ignore -m pytest backend/tests -q
echo "== flutter =="; (cd app && flutter test)
echo "== web build =="; scripts/build_web.sh >/dev/null
echo "== browser e2e (offline) =="; .venv/bin/python -W ignore scripts/e2e_browser.py
if [[ "${1:-}" == "--live" ]]; then
  echo "== real Gemini smoke =="; .venv/bin/python -W ignore scripts/smoke_live.py
  echo "== browser e2e (live, synthesised voice) =="
  .venv/bin/python -W ignore scripts/e2e_browser.py --live --audio data/e2e_voice.wav
fi
