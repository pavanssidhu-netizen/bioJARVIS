"""Push server-side secrets from .env to the linked Vercel project's PREVIEW environment (encrypted).

Uses the Vercel CLI login token (no interactive prompts). Never prints values.
    .venv/bin/python scripts/vercel_env_sync.py
"""
import json
import pathlib
import re

import httpx

KEYS = ["GEMINI_API_KEY", "TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN", "GEMINI_LIVE_MODEL", "GEMINI_VISION_MODEL",
        "GEMINI_PERCEPTION_MODEL", "GEMINI_QUERY_MODEL", "SPECIALIST_PROVIDER", "MODAL_ENABLED", "MODAL_TOKEN_ID",
        "MODAL_TOKEN_SECRET", "TELEMETRY_ENABLED"]
tok = json.load(open(pathlib.Path.home() / ".local/share/com.vercel.cli/auth.json"))["token"]
proj = json.load(open(".vercel/project.json"))
env = dict(re.findall(r"^([A-Z_]+)=(.+)$", open(".env").read(), re.M))
url = f"https://api.vercel.com/v10/projects/{proj['projectId']}/env?teamId={proj['orgId']}&upsert=true"
for k in KEYS:
    if not env.get(k):
        print("skip", k, "(empty)")
        continue
    r = httpx.post(url, headers={"Authorization": f"Bearer {tok}"},
                   json={"key": k, "value": env[k], "type": "encrypted", "target": ["preview"]})
    print(k, "->", "ok" if r.is_success else f"{r.status_code} {r.text[:200]}")
