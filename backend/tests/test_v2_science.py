"""V2: CEA microfluidic scenario end-to-end (offline; Gemini faked, REAL team engines):
Person 2 seed + Person 4 steering engine + Person 3 specialist council, through the LABMATE API."""
import base64
import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from backend.app.vision.base import VisionAnalysis

ROOT = Path(__file__).resolve().parents[2]
EXP = "exp_001"
IMAGES = ROOT / "evals" / "vision_test" / "images"


def _call(client, name, args=None, session_id=None, **kw):
    return client.post("/api/tools/call", json={"name": name, "args": args or {}, "experiment_id": EXP,
                                                "session_id": session_id, **kw}).json()


@pytest.fixture()
def rec(client):
    return client.post("/api/recordings/start", json={"experiment_id": EXP}).json()


def test_seed_loaded_as_experiment_context(client):
    ctx = client.get(f"/api/experiments/{EXP}/context").json()
    assert ctx["protocol_id"] == "microfluidic_sandwich_immunoassay_cea" and len(ctx["steps"]) == 9
    assert ctx["channel_map"]["CH01"] == "STD01" and len(ctx["dependencies"]) == 33
    prot = client.get(f"/api/experiments/{EXP}/protocol").json()
    assert [s["id"] for s in prot["content"]["steps"]][:2] == ["step_01", "step_02"]


def test_graph_impact_standard_vs_sample_channel(client):
    std = client.get(f"/api/experiments/{EXP}/graph", params={"focus": "CH01"}).json()["affected"]["structured"]
    assert "standard_curve" in std["derived_values"] and "result_S06" in std["derived_values"]
    smp = client.get(f"/api/experiments/{EXP}/graph", params={"focus": "CH08"}).json()["affected"]["structured"]
    assert smp["derived_values"] == ["result_S02"]  # a sample channel only affects its own result


def test_spoken_bubble_note_reconciled_and_flagged(client, rec):
    assert _call(client, "set_active_step", {"step_id": "step_05", "channel_id": "ch01"}, rec["id"])["ok"]
    r = _call(client, "propose_observation", {
        "observation_type": "general_note", "summary": "one bubble in channel 1 after loading",
        "measurement_type": "bubble_count", "measurement_value": 1}, rec["id"], call_id="v2-1")
    assert r["saved"] is True
    rc = r["reconciliation"]
    assert rc["action"] == "warn" and rc["requires_human_approval"] is True and "c_01" in rc["violated_constraints"]
    assert "standard_curve" in rc["affected_structured"]["derived_values"] and rc["spoken_response"]
    pend = client.get("/api/reviews/pending", params={"experiment_id": EXP}).json()
    assert pend and pend[0]["observation_id"] == r["event_id"]
    # Human review clears it from the pending queue; original + reconciliation stay immutable.
    client.post(f"/api/observations/{r['event_id']}/review", json={"action": "accept", "reviewer": "scientist"})
    assert client.get("/api/reviews/pending", params={"experiment_id": EXP}).json() == []


def test_in_tolerance_incubation_logged_without_flag(client, rec):
    _call(client, "set_active_step", {"step_id": "step_05"}, rec["id"])
    r = _call(client, "propose_observation", {"observation_type": "timing_note", "summary": "incubated 15 minutes",
                                              "measurement_type": "incubation_duration_min", "measurement_value": 15},
              rec["id"], call_id="v2-2")
    assert r["reconciliation"]["action"] in ("log", "no_action") and not r["reconciliation"]["requires_human_approval"]
    r = _call(client, "propose_observation", {"observation_type": "timing_note", "summary": "incubated 9 minutes",
                                              "measurement_type": "incubation_duration_min", "measurement_value": 9},
              rec["id"], call_id="v2-3")
    assert r["reconciliation"]["requires_human_approval"] is True


def test_reconcile_preview_matches_katarina_cases(client):
    cases = json.loads((ROOT / "evals" / "steering" / "eval_cases.json").read_text())["cases"]
    hits = 0
    for c in cases:
        o = c["observation"]
        m = o.get("measurement") or {}
        d = client.post(f"/api/experiments/{EXP}/reconcile", json={
            "step_id": c["active_step_id"], "channel_id": o.get("channel_id"), "well_id": o.get("well_id"),
            "content": o.get("utterance") or o.get("media_ref") or "", "source_type": o.get("source_type", "voice"),
            "media_ref": o.get("media_ref"), "confidence": o.get("confidence", 1.0),
            "measurement_type": m.get("type"), "measurement_value": m.get("value"), "measurement_unit": m.get("unit"),
            "supersedes_observation_id": o.get("supersedes_observation_id")}).json()
        hits += d["action"] == c["expected_response"]
    assert hits / len(cases) >= 0.85  # API path preserves Person 4's engine behaviour


def test_voice_tracking_and_discard(client, rec, db_path):
    st = _call(client, "track_object", {"label": "Bubbles", "channel_id": "CH03"}, rec["id"])["session_state"]
    assert st["tracking"][0]["label"] == "bubbles" and st["tracking"][0]["added_by"] == "voice"
    _call(client, "track_object", {"label": "pipette tip"}, rec["id"])
    assert len(_call(client, "stop_tracking", {"label": "bubbles"}, rec["id"])["session_state"]["tracking"]) == 1
    assert _call(client, "stop_tracking", {"label": "nonexistent"}, rec["id"])["error"] == "not_tracked"
    n = _call(client, "propose_observation", {"observation_type": "general_note", "summary": "oops wrong tube"},
              rec["id"], call_id="v2-4")
    d = _call(client, "discard_observation", {"event_id": "last", "reason": "misspoke"}, rec["id"])
    assert d["discarded_event_id"] == n["event_id"]
    ev = client.get(f"/api/observations/{n['event_id']}").json()
    assert ev["review_status"] == "rejected" and ev["payload"]["summary"] == "oops wrong tube"  # preserved
    client.post(f"/api/recordings/{rec['id']}/stop")
    assert _call(client, "track_object", {"label": "x"}, rec["id"])["error"] == "recording_inactive"


class _FakeGemini:
    name = "gemini"

    async def analyse_frames(self, frames, interval_s, hint, protocol_hint=""):
        assert "TRACK: bubbles" in (hint or "")
        return VisionAnalysis("gemini", "fake-flash", "chip", {
            "scene_summary": "Microfluidic chip channel in view",
            "objects": [{"label": "bubbles", "certainty": "likely", "box_2d": [100, 200, 300, 400]},
                        {"label": "microfluidic chip", "certainty": "certain", "box_2d": [0, 0, 1200, 900]}],
            "actions": [], "limitations": []})


@pytest.mark.skipif(not (IMAGES / "case_05_two_microbubbles.png").exists(), reason="run evals.evaluate image builder")
def test_perception_real_specialist_counts_reconciled_frames_retained_and_purged(client, rec, monkeypatch, db_path):
    import backend.app.services.perception as perc
    monkeypatch.setattr(perc, "get_vision_provider", lambda: _FakeGemini())
    monkeypatch.setenv("SPECIALIST_PROVIDER", "local")
    _call(client, "set_active_step", {"step_id": "step_05", "channel_id": "CH08"}, rec["id"])
    _call(client, "track_object", {"label": "bubbles"}, rec["id"])
    img = base64.b64encode((IMAGES / "case_05_two_microbubbles.png").read_bytes()).decode()
    r = client.post("/api/perception/window", json={
        "frames_base64": [img, img], "frame_interval_s": 1.0, "window_start": "2026-11-08T10:00:00Z",
        "window_end": "2026-11-08T10:00:01Z", "experiment_id": EXP, "session_id": rec["id"],
        "idempotency_key": f"pw-{uuid.uuid4().hex}"})
    assert r.status_code == 200, r.text
    r = r.json()
    p = r["perception"]
    assert p["specialist"]["count"] == 2 and p["specialist"]["provider"] == "specialist"  # Person 3 ground truth = 2
    assert [o["tracked"] for o in p["objects"]] == [True, False]
    assert p["objects"][1]["box_2d"] is None  # out-of-range model coordinates rejected
    assert len(p["frame_ids"]) == 2 and p["active_channel_id"] == "CH08"
    rc = r["reconciliation"]
    assert rc["action"] in ("warn", "request_confirmation") and rc["requires_human_approval"]
    assert rc["affected_structured"]["derived_values"] == ["result_S02"]
    # Frames retrievable during the session...
    frames = client.get(f"/api/recordings/{rec['id']}/frames").json()["frames"]
    assert len(frames) == 2
    jpg = client.get(f"/api/recordings/{rec['id']}/frames/{frames[0]['id']}")
    assert jpg.status_code == 200 and jpg.content[:4] == b"\x89PNG"
    # ...and purged when the session ends.
    client.post(f"/api/recordings/{rec['id']}/stop")
    assert sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM session_frames").fetchone()[0] == 0
    hist = client.get(f"/api/experiments/{EXP}/sessions").json()
    assert hist[0]["id"] == rec["id"] and hist[0]["flagged_count"] >= 1
    summ = client.get(f"/api/recordings/{rec['id']}/summary").json()
    assert summ["event_counts"]["perception"] == 1 and summ["event_counts"]["reconciliation"] >= 1


def test_investigate_endpoint(client):
    r = client.post("/api/investigate", json={"experiment_id": EXP, "question": "Why is replicate CV high?",
                                              "step_id": "step_05", "measurement_type": "duplicate_cv_percent",
                                              "measurement_value": 22.4})
    assert r.status_code == 200 and isinstance(r.json(), dict) and r.json()
