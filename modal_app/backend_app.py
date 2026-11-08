"""(Prepared, NOT deployed) - the LABMATE FastAPI backend as a Modal ASGI app for the prod setup.

requires_proxy_auth=True: Modal rejects requests without Modal-Key / Modal-Secret proxy-auth headers, so the
endpoint is never anonymously reachable. Browsers can't hold those secrets, so in prod either keep Vercel as
the (deployment-protected) front door that proxies to Modal server-side, or put a real identity provider in
front. Do not flip requires_proxy_auth off.

Deploy only when moving to prod:  .venv/bin/modal deploy modal_app/backend_app.py
Secrets: create a Modal secret "labmate-backend" with GEMINI_API_KEY, TURSO_DATABASE_URL, TURSO_AUTH_TOKEN.
"""
from __future__ import annotations

from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]

image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install_from_requirements(str(ROOT / "requirements.txt"))
         .add_local_dir(ROOT / "backend" / "app", remote_path="/root/backend/app")
         .add_local_dir(ROOT / "backend" / "steering", remote_path="/root/backend/steering")
         .add_local_dir(ROOT / "modal_app" / "specialist", remote_path="/root/modal_app/specialist"))

app = modal.App("labmate-backend")


@app.function(image=image, secrets=[modal.Secret.from_name("labmate-backend")], min_containers=0,
              max_containers=2, scaledown_window=120, timeout=120)
@modal.asgi_app(requires_proxy_auth=True)
def web():
    import sys
    sys.path.insert(0, "/root")
    open("/root/backend/__init__.py", "a").close()
    from backend.app.main import app as fastapi_app
    return fastapi_app
