"""Fill the LOCAL database with realistic Larvis demo data for UI work (no API keys needed).

    python scripts/seed_demo.py            # adds 2 finished sessions to exp_001 in data/labmate.db

Creates real records through the real backend code: dictated notes, perception windows with object tags
(box_2d), specialist bubble detections, and deterministic reconciliation flags from the steering engine
(pending reviews). Payload shapes are exactly what the live app receives. Refuses to run against Turso.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["TURSO_DATABASE_URL"] = ""  # never seed the shared/deployed DB

from backend.app.contracts import EventIn, ReviewIn  # noqa: E402
from backend.app.db import get_db  # noqa: E402
from backend.app.science.service import reconcile_and_record  # noqa: E402
from backend.app.services.store import Store  # noqa: E402

EXP = "exp_001"


def perception(st, rec, t, *, summary, objects, actions=(), bubbles=None, channel=None, step=None):
    spec = None
    if bubbles is not None:
        spec = {"provider": "specialist", "model": "labmate-perception-agent-v1", "count": len(bubbles),
                "counts_by_label": {"bubble": len(bubbles)}, "abstained": False, "review_required": bool(bubbles),
                "coordinate_system": "pixels", "image_width": 640, "image_height": 360,
                "detections": [{"label": "bubble", "bbox": b, "confidence": 0.9, "obstruction_risk": r,
                                "channel_obstruction_ratio": o} for b, r, o in bubbles],
                "description": f"{len(bubbles)} bubble(s) retained after sceptic audit",
                "sceptic_critique": "Border-clipped candidate and wall glare excluded."}
    payload = {"window_start": (t - timedelta(seconds=4)).isoformat(), "window_end": t.isoformat(), "frame_count": 5,
               "scene_summary": summary, "objects": objects, "actions": list(actions), "limitations": [
                   "Frames ~1 s apart; fast actions may be missed."], "provider": "gemini", "model": "gemini-3.8-flash",
               "specialist": spec, "tracking": ["bubbles"], "active_step_id": step, "active_channel_id": channel,
               "frame_ids": []}
    ev, _ = st.ingest(EventIn(session_id=rec.id, experiment_id=EXP, source_modality="video", event_type="perception",
                              payload={k: v for k, v in payload.items() if v is not None}, model_name="gemini-3.8-flash",
                              idempotency_key=f"seed-{uuid.uuid4().hex}"))
    if spec:
        rc = reconcile_and_record(st, ev, {"source_type": "camera", "content": spec["description"], "channel_id": channel,
                                           "measurement_type": "bubble_count", "measurement_value": len(bubbles),
                                           "measurement_unit": "count", "confidence": 0.9}, step)
        return ev, rc
    return ev, None


def note(st, rec, summary, **m):
    ev, _ = st.ingest(EventIn(session_id=rec.id, experiment_id=EXP, source_modality="speech",
                              event_type="observation_proposal", model_name="gemini-3.8-live",
                              idempotency_key=f"seed-{uuid.uuid4().hex}",
                              payload={"observation_type": m.pop("observation_type", "general_note"), "summary": summary,
                                       "proposed_by": "gemini_live", **m}))
    if m.get("measurement_type"):
        reconcile_and_record(st, ev, {"source_type": "voice", "content": summary, **m}, m.get("protocol_step"))
    return ev


def main() -> None:
    st = Store(get_db())
    print("seeding", get_db().label)
    now = datetime.now(timezone.utc)
    chip = {"label": "microfluidic chip", "certainty": "certain", "box_2d": [180, 40, 820, 960]}
    pip = {"label": "micropipette", "certainty": "certain", "box_2d": [40, 600, 520, 760]}
    inlet = {"label": "channel inlet CH01", "certainty": "likely", "box_2d": [430, 80, 520, 160]}
    bub = {"label": "bubble", "certainty": "likely", "box_2d": [440, 300, 500, 350], "tracked": True}

    # Session 1: earlier trial, one flagged bubble in a standard channel (affects the whole standard curve)
    r1 = st.start_recording(EXP)
    st.update_session_state(r1.id, active_step_id="step_05", active_channel_id="CH01")
    st.track(r1.id, "bubbles", by="voice")
    note(st, r1, "Loaded standards and samples into all twelve channels", observation_type="protocol_step_done",
         protocol_step="step_05")
    perception(st, r1, now - timedelta(minutes=50), summary="Pipette dispensing into channel 1 inlet",
               objects=[chip, pip, inlet], actions=[{"action": "pipette liquid", "object": "CH01 inlet", "count": 1,
                                                     "certainty": "likely", "protocol_step": "step_05"}])
    perception(st, r1, now - timedelta(minutes=49), summary="Small bubble visible near the CH01 capture spot",
               objects=[chip, bub], bubbles=[([300, 160, 334, 192], "low", 0.14)], channel="CH01", step="step_05")
    note(st, r1, "Incubated samples for 15 minutes", measurement_type="incubation_duration_min",
         measurement_value=15, measurement_unit="min", protocol_step="step_05")
    st.stop_recording(r1.id, "user_stopped")

    # Session 2: today, sample-channel obstruction + short detection incubation + a discarded note
    r2 = st.start_recording(EXP)
    st.update_session_state(r2.id, active_step_id="step_07", active_channel_id="CH08")
    perception(st, r2, now - timedelta(minutes=12), summary="Gas slug partially blocking channel 8",
               objects=[chip, {**bub, "box_2d": [430, 420, 520, 560]}],
               bubbles=[([410, 150, 470, 205], "high_obstruction_candidate", 0.62),
                        ([500, 160, 520, 180], "low", 0.08)], channel="CH08", step="step_07")
    note(st, r2, "Detection antibody incubation was 8 minutes", measurement_type="incubation_duration_min",
         measurement_value=8, measurement_unit="min", protocol_step="step_07")
    bad = note(st, r2, "Tube B turned blue")  # wrong experiment remark -> discarded by voice
    st.review(bad.id, ReviewIn(action="reject", reviewer="researcher (voice)", correction={"reason": "misspoke"}))
    note(st, r2, "Room temperature 24 degrees", measurement_type="temperature_c", measurement_value=24,
         measurement_unit="C", protocol_step="step_07")
    st.stop_recording(r2.id, "user_stopped")

    from backend.app.science.service import pending_reviews
    print(f"sessions: {r1.id}, {r2.id} | events: {st.last_sequence(EXP)} | pending reviews: "
          f"{len(pending_reviews(st, EXP))}")


if __name__ == "__main__":
    main()
