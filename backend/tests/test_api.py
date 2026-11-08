"""Offline API + DB tests (no model key needed)."""
import asyncio
import base64
import sqlite3
import uuid

from backend.app.contracts import ToolCallIn

EXP = "exp-demo"


def _start(client, exp=EXP):
    r = client.post("/api/recordings/start", json={"experiment_id": exp})
    assert r.status_code == 201, r.text
    return r.json()


def _event(session_id, exp=EXP, key=None, **kw):
    body = {"session_id": session_id, "experiment_id": exp, "source_modality": "speech",
            "event_type": "observation_proposal", "payload": {"summary": "Tube A turned blue"},
            "idempotency_key": key or f"k-{uuid.uuid4().hex}"}
    body.update(kw)
    return body


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["database_ok"] is True


def test_seed_and_create_experiment(client):
    assert any(e["id"] == EXP for e in client.get("/api/experiments").json())
    r = client.post("/api/experiments", json={"name": "Enzyme kinetics"})
    assert r.status_code == 201
    exp_id = r.json()["id"]
    assert client.get(f"/api/experiments/{exp_id}").json()["name"] == "Enzyme kinetics"
    assert client.get("/api/experiments/nope").status_code == 404


def test_recording_lifecycle_and_persist(client):
    rec = _start(client)
    assert rec["status"] == "active"
    r = client.post("/api/observations/propose", json=_event(rec["id"]))
    assert r.status_code == 200 and r.json()["saved"] is True
    assert r.json()["event"]["sequence_number"] == 1
    stopped = client.post(f"/api/recordings/{rec['id']}/stop", json={"reason": "user_stopped"}).json()
    assert stopped["status"] == "stopped" and stopped["event_count"] == 1


def test_reject_when_recording_inactive(client, db_path):
    rec = _start(client)
    client.post(f"/api/recordings/{rec['id']}/stop")  # empty body (sendBeacon path)
    r = client.post("/api/observations/propose", json=_event(rec["id"]))
    assert r.status_code == 409
    assert r.json()["error"] == "recording_inactive" and r.json()["saved"] is False
    n = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM observation_events").fetchone()[0]
    assert n == 0


def test_unknown_session_rejected(client):
    assert client.post("/api/observations/propose", json=_event("rec-doesnotexist")).status_code == 404


def test_duplicate_idempotency_key(client, db_path):
    rec = _start(client)
    body = _event(rec["id"], key="same-key-123")
    a = client.post("/api/observations/propose", json=body).json()
    b = client.post("/api/observations/propose", json=body).json()
    assert a["event"]["id"] == b["event"]["id"] and b["duplicate"] is True
    n = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM observation_events").fetchone()[0]
    assert n == 1


def test_fetch_and_recover_from_sequence(client):
    rec = _start(client)
    for _ in range(5):
        client.post("/api/observations/propose", json=_event(rec["id"]))
    page = client.get(f"/api/events/{EXP}", params={"after_seq": 3}).json()
    assert [e["sequence_number"] for e in page["events"]] == [4, 5]
    assert page["last_sequence"] == 5 and page["recording"]["id"] == rec["id"]
    assert len(client.get("/api/observations", params={"experiment_id": EXP}).json()) == 5


def test_review_and_correction_never_overwrites(client):
    rec = _start(client)
    ev = client.post("/api/observations/propose", json=_event(rec["id"])).json()["event"]
    assert client.post(f"/api/observations/{ev['id']}/review", json={"action": "dispute"}).status_code == 200
    r = client.post(f"/api/observations/{ev['id']}/review",
                    json={"action": "correct", "correction": {"summary": "Tube B turned blue"}, "reviewer": "pav"})
    assert r.status_code == 200
    corr = r.json()["correction_event"]
    assert corr["event_type"] == "correction" and corr["source_event_id"] == ev["id"]
    original = client.get(f"/api/observations/{ev['id']}").json()
    assert original["payload"]["summary"] == "Tube A turned blue"  # untouched
    assert original["review_status"] == "corrected" and len(original["reviews"]) == 2
    assert client.post(f"/api/observations/{ev['id']}/review", json={"action": "correct"}).status_code == 422


def test_heartbeat_timeout_expires_recording(client, monkeypatch):
    monkeypatch.setenv("RECORDING_HEARTBEAT_TIMEOUT_S", "0")
    rec = _start(client)
    import time; time.sleep(0.01)
    assert client.get(f"/api/recordings/{rec['id']}").json()["status"] == "expired"
    assert client.post("/api/observations/propose", json=_event(rec["id"])).status_code == 409


def test_database_survives_restart(client, db_path):
    rec = _start(client)
    client.post("/api/observations/propose", json=_event(rec["id"], key="persist-me-1"))
    from backend.app.db import get_db
    get_db().close(); get_db.cache_clear()  # simulate process restart
    from fastapi.testclient import TestClient
    from backend.app.main import app
    events = TestClient(app).get("/api/observations", params={"experiment_id": EXP}).json()
    assert [e["idempotency_key"] for e in events] == ["persist-me-1"]


def test_wal_mode(client, db_path):
    client.get("/api/health")
    assert sqlite3.connect(db_path).execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_tool_propose_observation_requires_recording(client):
    from backend.app.db import get_db
    from backend.app.live.tools import execute_tool
    from backend.app.services.store import Store
    st = Store(get_db())
    args = {"observation_type": "colour_change", "summary": "Tube A turned blue at 2 min"}
    r = asyncio.run(execute_tool(st, ToolCallIn(name="propose_observation", args=args, experiment_id=EXP)))
    assert r["saved"] is False and r["error"] == "recording_inactive"
    rec = _start(client)
    r = asyncio.run(execute_tool(st, ToolCallIn(name="propose_observation", args=args, experiment_id=EXP,
                                                session_id=rec["id"], call_id="fc-1")))
    assert r["saved"] is True and r["event_id"].startswith("evt-")
    state = asyncio.run(execute_tool(st, ToolCallIn(name="describe_current_recording_state", experiment_id=EXP)))
    assert state["recording_active"] is True and state["event_count"] == 1
    recent = asyncio.run(execute_tool(st, ToolCallIn(name="get_recent_observations", experiment_id=EXP)))
    assert recent["observations"][0]["payload"]["summary"].startswith("Tube A")


def test_tool_endpoint_unknown_tool(client):
    r = client.post("/api/tools/call", json={"name": "drop_tables", "experiment_id": EXP})
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["error"] == "unknown_tool"


def test_vision_rejects_non_image_and_save_without_recording(client):
    bad = base64.b64encode(b"not an image at all").decode()
    assert client.post("/api/vision/analyse", json={"image_base64": bad}).status_code == 422
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 32).decode()
    r = client.post("/api/vision/analyse", json={"image_base64": png, "save": True, "experiment_id": EXP})
    assert r.status_code == 409 and r.json()["error"] == "recording_inactive"


def test_specialist_provider_reports_not_configured(client):
    caps = client.get("/api/capabilities").json()
    assert "configured" in caps["specialist_vision"] and caps["raw_media_storage"] is False


def test_production_guard(client, monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "production")
    assert client.get("/api/health").status_code == 403
