"""Offline tests for the live-feed perception contract and the DB query agent (model calls faked)."""
import base64
import json
import uuid

import pytest

from backend.app.vision.base import VisionAnalysis

EXP = "exp-demo"
JPEG = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\0" * 64).decode()


class FakeProvider:
    name = "fake"

    def __init__(self, actions):
        self.actions = actions

    async def analyse_frames(self, frames, interval_s, hint, protocol_hint=""):
        return VisionAnalysis(provider="fake", model="fake-vision", description="bench", structured={
            "scene_summary": "A dropper over a test tube.",
            "objects": [{"label": "test tube", "count": 1, "certainty": "certain"},
                        {"label": "dropper", "certainty": "likely"}, {"bad": "row"}],
            "actions": self.actions, "limitations": ["1 fps sampling"]})


@pytest.fixture()
def fake_vision(monkeypatch):
    holder = {"actions": [{"action": "dispense drop", "object": "test tube", "count": 3, "certainty": "likely"}]}
    import backend.app.services.perception as perc
    monkeypatch.setattr(perc, "get_vision_provider", lambda: FakeProvider(holder["actions"]))
    return holder


def _window(session_id=None):
    return {"frames_base64": [JPEG] * 5, "frame_interval_s": 1.0, "window_start": "2026-01-01T00:00:00Z",
            "window_end": "2026-01-01T00:00:04Z", "experiment_id": EXP, "session_id": session_id,
            "idempotency_key": f"pw-{uuid.uuid4().hex}"}


def test_perception_saved_only_while_recording(client, fake_vision):
    r = client.post("/api/perception/window", json=_window()).json()
    assert r["saved"] is False and r["skipped_reason"] == "recording_inactive"
    assert r["perception"]["actions"][0]["count"] == 3
    assert len(r["perception"]["objects"]) == 2  # malformed object row dropped

    rec = client.post("/api/recordings/start", json={"experiment_id": EXP}).json()
    r = client.post("/api/perception/window", json=_window(rec["id"])).json()
    assert r["saved"] is True and r["event"]["event_type"] == "perception"
    assert r["event"]["source_modality"] == "video"
    assert r["event"]["payload"]["actions"][0]["action"] == "dispense drop"


def test_perception_no_change_is_not_spammed(client, fake_vision):
    rec = client.post("/api/recordings/start", json={"experiment_id": EXP}).json()
    fake_vision["actions"] = []
    assert client.post("/api/perception/window", json=_window(rec["id"])).json()["saved"] is True  # first scene
    r = client.post("/api/perception/window", json=_window(rec["id"])).json()
    assert r["saved"] is False and r["skipped_reason"] == "no_change"
    fake_vision["actions"] = [{"action": "shake tube", "count": 1, "certainty": "certain"}]
    assert client.post("/api/perception/window", json=_window(rec["id"])).json()["saved"] is True


def test_perception_rejects_bad_frames(client, fake_vision):
    w = _window()
    w["frames_base64"] = ["aGVsbG8="]
    assert client.post("/api/perception/window", json=w).status_code == 422


class _FakeResp:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    last_prompt = None

    async def generate_content(self, model, contents, config):
        _FakeModels.last_prompt = contents
        log = json.loads(contents.split("lookback 1800s):\n", 1)[1])
        perception = [e for e in log if e["type"] == "perception"]
        drops = sum(a["count"] for e in perception for a in e["data"]["actions"])
        return _FakeResp(json.dumps({"answer": f"About {drops} drops.", "confidence": "medium",
                                     "evidence_event_ids": [e["id"] for e in perception] + ["evt-made-up"],
                                     "caveats": ["exploratory"]}))


class _FakeAio:
    def __init__(self):
        self.models = _FakeModels()

    async def aclose(self):
        pass


class _FakeClient:
    def __init__(self, **_):
        self.aio = _FakeAio()


def test_query_agent_reads_db_and_drops_hallucinated_ids(client, fake_vision, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-not-real")
    import backend.app.services.query_agent as qa
    monkeypatch.setattr(qa.genai, "Client", _FakeClient)
    rec = client.post("/api/recordings/start", json={"experiment_id": EXP}).json()
    ev = client.post("/api/perception/window", json=_window(rec["id"])).json()["event"]
    # A rejected event must be marked so the agent ignores it.
    client.post(f"/api/observations/{ev['id']}/review", json={"action": "reject"})
    ev2 = client.post("/api/perception/window", json=_window(rec["id"])).json()["event"]

    r = client.post("/api/query", json={"experiment_id": EXP, "question": "How many drops 30 seconds ago?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["events_considered"] == 2
    assert "evt-made-up" not in body["evidence_event_ids"] and ev2["id"] in body["evidence_event_ids"]
    assert '"review_status":"rejected"' in _FakeModels.last_prompt
    assert "ago_s" in _FakeModels.last_prompt

    # Same agent via the Live tool relay.
    t = client.post("/api/tools/call", json={"name": "query_lab_log", "experiment_id": EXP,
                                             "args": {"question": "how many drops?"}}).json()
    assert t["ok"] is True and t["answer"].startswith("About")


def test_query_without_key_is_explicit(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    r = client.post("/api/query", json={"experiment_id": EXP, "question": "anything?"})
    assert r.status_code == 503 and r.json()["error"] == "gemini_not_configured"
