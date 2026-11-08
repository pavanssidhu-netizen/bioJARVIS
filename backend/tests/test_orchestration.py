"""Offline tests for the orchestration layer: skills policy, steering, prompts, telemetry, protocol, UI actions,
specialist chaining and the composed Live config."""
import asyncio
import base64
import json
import sqlite3
import uuid

import pytest

from backend.app.vision.base import VisionAnalysis

EXP = "exp-demo"
JPEG = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\0" * 64).decode()


def _call(client, name, args=None, session_id=None, **kw):
    return client.post("/api/tools/call", json={"name": name, "args": args or {}, "experiment_id": EXP,
                                                "session_id": session_id, **kw}).json()


def test_skill_registry_lists_policy(client):
    skills = {s["name"]: s for s in client.get("/api/skills").json()}
    assert {"propose_observation", "query_lab_log", "request_ui_action", "get_protocol",
            "describe_current_recording_state"} <= set(skills)
    assert skills["propose_observation"]["requires_recording"] is True
    assert skills["propose_observation"]["effect"] == "write"
    assert skills["query_lab_log"]["effect"] == "model"
    assert all(not s["requires_recording"] for n, s in skills.items() if s["effect"] != "write")


def test_write_skill_gated_centrally_even_with_forged_session(client):
    # A client claiming a session id that was stopped must not get a write through.
    rec = client.post("/api/recordings/start", json={"experiment_id": EXP}).json()
    client.post(f"/api/recordings/{rec['id']}/stop")
    r = _call(client, "propose_observation", {"observation_type": "general_note", "summary": "x"}, rec["id"])
    assert r["saved"] is False and r["error"] == "recording_inactive"
    # Session from a different experiment is also refused.
    other = client.post("/api/experiments", json={"name": "other"}).json()["id"]
    rec2 = client.post("/api/recordings/start", json={"experiment_id": other}).json()
    r = _call(client, "propose_observation", {"observation_type": "general_note", "summary": "x"}, rec2["id"])
    assert r["error"] == "recording_inactive"


def test_propose_idempotent_by_call_id(client, db_path):
    rec = client.post("/api/recordings/start", json={"experiment_id": EXP}).json()
    args = {"observation_type": "colour_change", "summary": "Tube A blue", "protocol_step": "S2"}
    a = _call(client, "propose_observation", args, rec["id"], call_id="fc-42")
    b = _call(client, "propose_observation", args, rec["id"], call_id="fc-42")
    assert a["saved"] and b["duplicate"] and a["event_id"] == b["event_id"]
    payload = json.loads(sqlite3.connect(db_path).execute(
        "SELECT payload_json FROM observation_events WHERE id=?", (a["event_id"],)).fetchone()[0])
    assert payload["protocol_step"] == "S2"


def test_demo_protocol_seeded_and_versioned(client):
    p = client.get(f"/api/experiments/{EXP}/protocol").json()
    assert p["version"] == 1 and [s["id"] for s in p["content"]["steps"]] == ["S1", "S2", "S3", "S4"]
    new = dict(p["content"]); new["title"] = "Revised assay"
    r = client.put(f"/api/experiments/{EXP}/protocol", json=new)
    assert r.status_code == 201 and r.json()["version"] == 2
    assert client.get(f"/api/experiments/{EXP}/protocol").json()["content"]["title"] == "Revised assay"
    assert client.get(f"/api/experiments/{EXP}/protocol", params={"version": 1}).json()["content"]["title"].startswith("Demo")
    assert client.put(f"/api/experiments/{EXP}/protocol", json={"title": "bad", "steps": []}).status_code == 422
    tool = _call(client, "get_protocol")
    assert tool["ok"] and tool["version"] == 2


def test_ui_action_skill_allowlist(client):
    ok = _call(client, "request_ui_action", {"action": "show_protocol_step", "argument": "S2"})
    assert ok["ok"] and ok["ui_action"] == {"action": "show_protocol_step", "argument": "S2"}
    assert _call(client, "request_ui_action", {"action": "show_protocol_step", "argument": "S99"})["error"] == "invalid_argument"
    assert _call(client, "request_ui_action", {"action": "start_recording"})["error"] == "ui_action_not_allowed"
    assert _call(client, "request_ui_action", {"action": "show_tab", "argument": "settings"})["error"] == "invalid_argument"


def test_ui_actions_logged_without_content(client, db_path):
    r = client.post("/api/ui/actions", json={"experiment_id": EXP, "actions": [
        {"action": "live_feed_start"}, {"action": "tab_change", "detail": {"tab": "log", "free_text": "x" * 500}},
        {"action": "show_protocol_step", "source": "model", "detail": {"step": "S2"}}]})
    assert r.status_code == 202 and r.json()["accepted"] == 3
    rows = client.get("/api/ui/actions", params={"experiment_id": EXP}).json()
    assert [x["action"] for x in rows] == ["live_feed_start", "tab_change", "show_protocol_step"]
    assert rows[1]["detail"] == {"tab": "log"}  # oversized free text dropped
    assert client.post("/api/ui/actions", json={"experiment_id": EXP, "actions": [{"action": "rm_rf"}]}).status_code == 422


def test_telemetry_spans_recorded_and_content_free(client, db_path):
    rec = client.post("/api/recordings/start", json={"experiment_id": EXP}).json()
    secret_text = "PATIENT-NAME-SHOULD-NEVER-APPEAR"
    _call(client, "propose_observation", {"observation_type": "general_note", "summary": secret_text}, rec["id"],
          call_id="fc-t1")
    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT name, kind, status, metadata_json, trace_id, parent_id FROM telemetry_spans").fetchall()
    names = [r[0] for r in rows]
    assert "skill.propose_observation" in names and any(n.startswith("api.POST /api/tools/call") for n in names)
    assert all(secret_text not in (r[3] or "") for r in rows)
    skill_row = next(r for r in rows if r[0] == "skill.propose_observation")
    api_row = next(r for r in rows if r[0].startswith("api.POST /api/tools/call"))
    assert skill_row[1] == "tool" and json.loads(skill_row[3])["saved"] is True
    assert skill_row[4] == api_row[4]  # same trace
    summary = client.get("/api/telemetry/summary").json()
    assert summary["spans"] >= 2 and any(g["name"] == "skill.propose_observation" for g in summary["by_name"])


def test_session_header_groups_spans(client, db_path):
    client.get("/api/health", headers={"x-labmate-session": "sess-abc123"})
    client.get("/api/health", headers={"x-labmate-session": "bad header with spaces"})
    vals = [r[0] for r in sqlite3.connect(db_path).execute("SELECT client_session FROM telemetry_spans")]
    assert "sess-abc123" in vals and "bad header with spaces" not in vals


def test_router_mode_live_is_voice_only(client, monkeypatch):
    monkeypatch.setenv("LARVIS_LIVE_MODE", "router")
    from backend.app.live.token import live_config
    cfg, ref = live_config(None, None)
    assert "tools" not in cfg and ref.startswith("live.voice@v")
    assert "stay silent" in cfg["system_instruction"] and "[Larvis]" in cfg["system_instruction"]


def test_steering_and_live_config_composition(client, monkeypatch):
    monkeypatch.setenv("LARVIS_LIVE_MODE", "tools")
    from backend.app.db import get_db
    from backend.app.live.token import live_config
    from backend.app.services.store import Store
    cfg, ref = live_config(Store(get_db()), EXP)
    si = cfg["system_instruction"]
    assert si.startswith("You are Larvis")
    assert "query_lab_log" in si and "scientific-integrity" in si and "lab-safety" in si
    assert "Approved protocol v1" in si and "S2:" in si
    names = {d["name"] for d in cfg["tools"][0]["function_declarations"]}
    assert {"propose_observation", "query_lab_log", "request_ui_action", "get_protocol"} <= names
    assert ref.startswith("live.core@v") and "+steer:" in ref
    st = client.get("/api/steering").json()
    assert {d["id"] for d in st["docs"]} >= {"operating-rules", "scientific-integrity", "lab-safety"}
    caps = client.get("/api/capabilities").json()
    assert caps["routing"]["live"] == "gemini-3.8-live" and caps["routing"]["specialist_provider"] == "none"


class _FakeGemini:
    name = "gemini"

    async def analyse_frames(self, frames, interval_s, hint, protocol_hint=""):
        assert "S2=dispense drop 3 drops" in protocol_hint  # protocol context reaches the vision prompt
        return VisionAnalysis("gemini", "fake-flash", "drops", {
            "scene_summary": "drops", "objects": [{"label": "tube", "certainty": "certain"}],
            "actions": [{"action": "dispense drop", "count": 2, "certainty": "likely", "protocol_step": "S2"}],
            "limitations": []}, usage={"input": 1000, "output": 50}, prompt_ref="perception.window@v2")


def test_specialist_chained_after_gemini_and_failure_isolated(client, monkeypatch, db_path):
    import backend.app.services.perception as perc
    monkeypatch.setattr(perc, "get_vision_provider", lambda: _FakeGemini())
    monkeypatch.setenv("SPECIALIST_PROVIDER", "local")
    monkeypatch.setenv("SPECIALIST_MODULE", "broken_specialist_mod")  # import fails -> must not break Gemini path
    rec = client.post("/api/recordings/start", json={"experiment_id": EXP}).json()
    body = {"frames_base64": [JPEG] * 3, "window_start": "2026-01-01T00:00:00Z", "window_end": "2026-01-01T00:00:02Z",
            "experiment_id": EXP, "session_id": rec["id"], "idempotency_key": f"pw-{uuid.uuid4().hex}"}
    r = client.post("/api/perception/window", json=body).json()
    assert r["saved"] is True
    assert r["perception"]["actions"][0]["protocol_step"] == "S2"
    assert r["perception"]["specialist"]["error"] == "not_configured"  # import failure surfaced honestly
    spans = {row[0]: row for row in sqlite3.connect(db_path).execute(
        "SELECT name, model, prompt_ref, input_tokens, status FROM telemetry_spans")}
    gen = spans["model.perception.window"]
    assert gen[1] == "fake-flash" and gen[2].startswith("perception.window@v2+steer:") and gen[3] == 1000
    assert spans["model.specialist.frames"][4] == "error"


def test_specialist_real_model_contract(monkeypatch, client, tmp_path):
    """A teammate module that returns the schema flows through unchanged."""
    mod = tmp_path / "fake_specialist.py"
    mod.write_text("MODEL_NAME='drop-v1'\nIS_REAL_MODEL=True\n"
                   "def predict(b, q=''): return {'model':'drop-v1','detections':[{'label':'drop','confidence':0.9,"
                   "'bbox':[1,2,3,4]}],'count':1,'counts_by_label':{'drop':1},'review_required':False}\n"
                   "def predict_frames(f, i): return predict(f[0])\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("SPECIALIST_PROVIDER", "local")
    monkeypatch.setenv("SPECIALIST_MODULE", "fake_specialist")
    from backend.app.db import get_db
    from backend.app.services.store import Store
    from backend.app.services.vision_service import run_specialist
    from backend.app.vision import decode_image
    img = decode_image(JPEG, 10_000)
    out = asyncio.run(run_specialist(Store(get_db()), "image", image=img))
    assert out["count"] == 1 and out["counts_by_label"] == {"drop": 1} and out["provider"] == "specialist"
    caps = client.get("/api/capabilities").json()
    assert caps["specialist_vision"]["configured"] is True and caps["specialist_vision"]["model"] == "drop-v1"


def test_prompt_versions_unique():
    from backend.app.orchestration.prompts import ALL
    assert len({p.ref for p in ALL.values()}) == len(ALL)
