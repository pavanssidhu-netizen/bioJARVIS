"""Offline tests: eval metrics, Langfuse export mapping (mock server), clip frame loading + counting."""
import asyncio
import json
import sqlite3
import sys
import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
EXP = "exp-demo"


def test_metrics_integrity_notes_and_latency(client, db_path):
    from backend.app.db import get_db
    from backend.app.evals.metrics import compute
    rec = client.post("/api/recordings/start", json={"experiment_id": EXP}).json()
    call = lambda sid, cid: client.post("/api/tools/call", json={  # noqa: E731
        "name": "propose_observation", "experiment_id": EXP, "session_id": sid, "call_id": cid,
        "args": {"observation_type": "general_note", "summary": f"note {cid}"}}).json()
    assert call(rec["id"], "a")["saved"] and call(rec["id"], "b")["saved"]
    client.post(f"/api/recordings/{rec['id']}/stop")
    assert call(rec["id"], "c")["error"] == "recording_inactive"
    m = compute(get_db())
    assert m["integrity.gate_violations"] == 0 and m["integrity.unsessioned_writes"] == 0
    assert m["notes.attempts"] == 2 and m["notes.save_success_rate"] == 1.0
    assert m["notes.attempts_while_inactive"] == 1
    assert m["latency.tool_propose.n"] == 3 and m["latency.tool_propose.p50_ms"] is not None

    # Simulate a gate violation (row written after the session stopped) -> metric must catch it.
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO observation_events (id, session_id, experiment_id, sequence_number, timestamp, "
                "source_modality, event_type, payload_json, status, idempotency_key) VALUES "
                "('evt-bad', ?, ?, 999, '2999-01-01T00:00:00+00:00', 'speech', 'transcript_segment', '{}', 'persisted', 'bad-key-1')",
                (rec["id"], EXP))
    con.commit()
    assert compute(get_db())["integrity.gate_violations"] == 1


def test_count_accuracy():
    from backend.app.evals.metrics import count_accuracy
    r = count_accuracy([{"expected": 4, "predicted": 4}, {"expected": 3, "predicted": 5},
                        {"expected": 0, "predicted": 0}, {"expected": 2, "predicted": None}])
    assert r["counting.mae"] == round(2 / 3, 3) and r["counting.exact_match"] == 0.5
    assert r["counting.within_1"] == 0.5 and r["counting.answered_rate"] == 0.75 and r["counting.signed_bias"] == round(2 / 3, 3)


def test_langfuse_mapping_and_send(client, db_path, monkeypatch):
    from backend.app.db import get_db
    from backend.app.orchestration.langfuse_export import LangfuseConfig, score_event, send, spans_to_events
    client.get("/api/health", headers={"x-labmate-session": "sess-lf-01"})
    client.post("/api/tools/call", json={"name": "get_protocol", "experiment_id": EXP})
    rows = get_db().execute("SELECT * FROM telemetry_spans ORDER BY start_time")
    events = spans_to_events(rows, "test")
    types = [e["type"] for e in events]
    assert types.count("trace-create") == len({r["trace_id"] for r in rows})
    tr = next(e for e in events if e["type"] == "trace-create" and e["body"]["sessionId"] == "sess-lf-01")
    assert tr["body"]["environment"] == "test"
    child = next(e for e in events if e["body"].get("name") == "skill.get_protocol")
    parent = next(e for e in events if e["type"] == "span-create"
                  and e["body"].get("name", "").startswith("api.POST /api/tools/call"))
    assert child["body"]["parentObservationId"] == parent["body"]["id"]
    assert child["body"]["endTime"] >= child["body"]["startTime"]

    got = []

    def handler(req: httpx.Request):
        assert req.url.path == "/api/public/ingestion" and req.headers["authorization"].startswith("Basic ")
        batch = json.loads(req.content)["batch"]
        got.extend(batch)
        return httpx.Response(207, json={"successes": [{"id": e["id"], "status": 201} for e in batch], "errors": []})

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    events.append(score_event("grounding.hallucinated_id_rate", 0.0, session_id="eval-x"))
    res = send(events, LangfuseConfig(), client=httpx.Client(transport=httpx.MockTransport(handler)), batch_size=3)
    assert res == {"sent": len(events), "errors": 0} and len(got) == len(events)
    assert got[-1]["type"] == "score-create" and got[-1]["body"]["value"] == 0.0


def test_langfuse_requires_keys(monkeypatch):
    from backend.app.orchestration.langfuse_export import LangfuseConfig, send
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    with pytest.raises(RuntimeError):
        send([], LangfuseConfig())


def test_clip_frames_and_counting_offline(tmp_path, monkeypatch, db_path):
    import cv2
    import numpy as np
    sys.path.insert(0, str(ROOT / "scripts"))
    import eval as ev  # scripts/eval.py
    d = tmp_path / "clip"
    d.mkdir()
    for i in range(7):
        cv2.imwrite(str(d / f"{i:03}.jpg"), np.full((720, 1280, 3), i * 30, np.uint8))
    frames = ev.load_frames({"path": "clip"}, tmp_path)
    assert len(frames) == 7 and frames[0][:3] == b"\xff\xd8\xff"
    assert cv2.imdecode(np.frombuffer(frames[0], np.uint8), 1).shape[1] == 512

    from backend.app.vision.base import VisionAnalysis

    class Fake:
        name = "gemini"

        async def analyse_frames(self, fr, i, h, protocol_hint=""):
            return VisionAnalysis("gemini", "fake", "", {"scene_summary": "", "objects": [], "limitations": [],
                                                         "actions": [{"action": "Dispense drop", "count": 2, "certainty": "likely"}]})

    import backend.app.services.perception as perc
    monkeypatch.setattr(perc, "get_vision_provider", lambda: Fake())
    (tmp_path / "m.json").write_text(json.dumps([{"id": "c1", "path": "clip", "expected_count": 4, "window_frames": 5}]))
    out = asyncio.run(ev.run_clips(tmp_path / "m.json"))
    assert out["clips"][0]["gemini"] == 4  # 2 windows (5 + 2 frames) x 2 drops
    assert out["gemini.counting.exact_match"] == 1.0


def test_first_int_parsing():
    sys.path.insert(0, str(ROOT / "scripts"))
    import eval as ev
    assert ev.first_int("You added three drops") == 3
    assert ev.first_int("About 7 drops in total") == 7
    assert ev.first_int("Step 2") == 2
    assert ev.first_int("not determinable") is None
    # Grader must read the number attached to the unit, not timestamps
    assert ev.first_int("About 38 seconds ago, camera perception estimated you added 3 drops", "drop") == 3
    assert ev.first_int("Roughly two minutes ago (135 seconds ago), you dispensed 4 drops", "drop") == 4
    assert ev.first_int("You noted one tube turning blue", "tube") == 1
    assert ev.first_int("Step 2", "step") == 2
    assert ev.first_int("7 drops of indicator in total", "drop") == 7
