"""Local dev server: LABMATE API + built Flutter web app on ONE origin, bound to loopback only.

    .venv/bin/python scripts/dev_server.py            # http://127.0.0.1:8000
Phone access goes through the Vercel deployment, not this server.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from backend.app.main import app  # noqa: E402

web = ROOT / "app" / "build" / "web"
if web.is_dir():
    app.mount("/", StaticFiles(directory=web, html=True), name="web")
else:
    print(f"[labmate] {web} missing - run scripts/build_web.sh for the UI; API only.")

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
