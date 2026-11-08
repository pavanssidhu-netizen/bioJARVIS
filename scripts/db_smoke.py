"""Round-trip the configured database (Turso if TURSO_DATABASE_URL is set) through the real API code.

    .venv/bin/python scripts/db_smoke.py
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.config import get_settings  # noqa: E402
from backend.app.main import app  # noqa: E402

c = TestClient(app)
print("database:", get_settings().database_label)
assert c.get("/api/health").json()["database_ok"], "health failed"
exp = c.post("/api/experiments", json={"name": "db-smoke"}).json()["id"]
rec = c.post("/api/recordings/start", json={"experiment_id": exp}).json()
body = {"session_id": rec["id"], "experiment_id": exp, "source_modality": "text", "event_type": "observation_proposal",
        "payload": {"summary": "db smoke"}, "idempotency_key": f"smoke-{uuid.uuid4().hex}"}
a = c.post("/api/observations/propose", json=body).json()
b = c.post("/api/observations/propose", json=body).json()
assert a["saved"] and b["duplicate"] and a["event"]["id"] == b["event"]["id"], (a, b)
c.post(f"/api/recordings/{rec['id']}/stop")
assert c.post("/api/observations/propose", json={**body, "idempotency_key": "x" * 12}).status_code == 409
print("OK: schema, write, idempotency, recording gate all verified on", get_settings().database_label)
