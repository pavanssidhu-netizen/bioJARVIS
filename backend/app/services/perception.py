"""Live-feed perception: frame window -> Gemini (objects/actions/boxes) -> specialist council (bubbles) ->
deterministic protocol reconciliation -> DB (only while recording). Frames are retained for the session.

Division of labour (the "not a wrapper" core):
  Gemini        open-vocabulary scene understanding, actions, object tags/boxes, tracking-guided attention
  Specialist    quantitative bubble count/obstruction (Person 3 council) - Gemini never supplies counts we act on
  Steering      deterministic constraint check + dependency impact (Person 4 engine on Person 2 seed)
"""
from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from ..config import get_settings
from ..contracts import EventIn, PerceptionAction, PerceptionObject, PerceptionPayload, PerceptionResult, PerceptionWindowIn
from ..orchestration import telemetry
from ..orchestration.steering import compose
from ..vision import decode_image, get_vision_provider
from .store import ApiError, Store
from .vision_service import protocol_hint, run_specialist


def _clean(items: list[Any], model: type) -> list:
    out = []
    for it in items or []:
        try:
            out.append(model.model_validate(it))
        except ValidationError:
            continue  # drop malformed model output rather than fail the whole window
    return out


def _last_perception_labels(store: Store, experiment_id: str) -> set[str] | None:
    rows = store.db.execute(
        "SELECT payload_json FROM observation_events WHERE experiment_id=? AND event_type='perception' "
        "ORDER BY sequence_number DESC LIMIT 1", (experiment_id,))
    if not rows:
        return None
    return {o.get("label", "").lower() for o in json.loads(rows[0]["payload_json"]).get("objects", [])}


def _session_ctx(store: Store, session_id: str | None) -> dict:
    if not session_id:
        return {"tracking": [], "active_step_id": None, "active_channel_id": None}
    try:
        st = store.session_state(session_id)
        return {"tracking": [t["label"] for t in st["tracking"]], "active_step_id": st["active_step_id"],
                "active_channel_id": st["active_channel_id"]}
    except ApiError:
        return {"tracking": [], "active_step_id": None, "active_channel_id": None}


async def process_window(store: Store, body: PerceptionWindowIn) -> PerceptionResult:
    s = get_settings()
    store.get_experiment(body.experiment_id)
    try:
        frames = [decode_image(f, s.max_image_bytes) for f in body.frames_base64]
    except ValueError as e:
        raise ApiError(422, str(e), "Frame rejected") from e
    if sum(len(f.data) for f in frames) > s.max_image_bytes:
        raise ApiError(413, "window_too_large", "Total frame bytes exceed the request limit")

    sess = _session_ctx(store, body.session_id)
    hint = "; ".join(x for x in (body.hint, f"TRACK: {', '.join(sess['tracking'])}" if sess["tracking"] else "") if x) or None

    # Retain frames for in-session review/re-analysis (purged when the session ends).
    frame_ids: list[str] = []
    if body.session_id:
        try:
            from datetime import datetime, timedelta
            t0 = datetime.fromisoformat(body.window_start.replace("Z", "+00:00"))
            frame_ids = store.store_frames(body.session_id, body.experiment_id, [
                ((t0 + timedelta(seconds=i * body.frame_interval_s)).isoformat(timespec="milliseconds"),
                 f.data, f.mime_type, f.sha256) for i, f in enumerate(frames)])
        except (ApiError, ValueError):
            frame_ids = []

    provider = get_vision_provider()
    _, steer = compose("perception")
    with telemetry.span("model.perception.window", "generation", db=store.db, provider=provider.name,
                        frames=len(frames), frame_bytes=sum(len(f.data) for f in frames),
                        tracking=len(sess["tracking"])) as sp:
        analysis = await provider.analyse_frames(frames, body.frame_interval_s, hint,
                                                 protocol_hint(store, body.experiment_id))
        sp.model, sp.prompt = analysis.model, f"{analysis.prompt_ref}+steer:{steer}"
        sp.usage.update(analysis.usage)
    st = analysis.structured
    objects = _clean(st.get("objects", []), PerceptionObject)
    for o in objects:
        o.tracked = any(t in o.label.lower() or o.label.lower() in t for t in sess["tracking"])
        if o.box_2d is not None and (len(o.box_2d) != 4 or not all(0 <= v <= 1000 for v in o.box_2d)):
            o.box_2d = None  # deterministic validation of model coordinates
    specialist = await run_specialist(store, "frames", frames=frames, interval_s=body.frame_interval_s,
                                      experiment_id=body.experiment_id,
                                      step_id=sess["active_step_id"] or "step_05")
    payload = PerceptionPayload(
        window_start=body.window_start, window_end=body.window_end, frame_count=len(frames),
        scene_summary=str(st.get("scene_summary", ""))[:500], objects=objects,
        actions=[a for a in _clean(st.get("actions", []), PerceptionAction) if a.count > 0],
        limitations=[str(x)[:300] for x in st.get("limitations", [])][:10],
        provider=analysis.provider, model=analysis.model, specialist=specialist,
        tracking=sess["tracking"], active_step_id=sess["active_step_id"], active_channel_id=sess["active_channel_id"],
        frame_ids=frame_ids,
    )

    with telemetry.span("perception.persist", "guardrail", db=store.db, actions=len(payload.actions),
                        objects=len(payload.objects), action_count_total=sum(a.count for a in payload.actions)) as gp:
        if not body.session_id:
            gp.set(outcome="recording_inactive")
            return PerceptionResult(perception=payload, saved=False, skipped_reason="recording_inactive")
        labels = {o.label.lower() for o in payload.objects}
        measured = bool(specialist and specialist.get("count") is not None and "error" not in specialist)
        if not payload.actions and not measured and labels == _last_perception_labels(store, body.experiment_id):
            gp.set(outcome="no_change")
            return PerceptionResult(perception=payload, saved=False, skipped_reason="no_change")
        try:
            event, _ = store.ingest(EventIn(
                session_id=body.session_id, experiment_id=body.experiment_id, source_modality="video",
                event_type="perception", payload=payload.model_dump(exclude_none=True,
                                                                     exclude={"specialist": {"overlay_base64"}}),
                model_name=analysis.model, idempotency_key=body.idempotency_key,
            ))
        except ApiError as e:
            if e.code == "recording_inactive":
                gp.set(outcome="recording_inactive")
                return PerceptionResult(perception=payload, saved=False, skipped_reason="recording_inactive")
            raise
        gp.set(outcome="saved")

    recon = None
    cross = None
    if measured:
        # Cross-model verification: Gemini's open-vocabulary bubble count vs the specialist's measured count.
        # Benchmark (docs/BENCHMARK_V2.md): agreement had 0 silent errors; every disagreement was a real error.
        g_bubbles = [o for o in payload.objects if "bubble" in o.label.lower()]
        # Gemini may list one object per bubble (each repeating the total in `count`) or one object with a count.
        g_count = len(g_bubbles) if len(g_bubbles) > 1 else ((g_bubbles[0].count or 1) if g_bubbles else 0)
        cross = {"gemini_count": g_count, "specialist_count": specialist["count"],
                 "agree": g_count == specialist["count"]}
    if measured:  # only specialist measurements drive protocol decisions
        from ..science.service import reconcile_and_record
        recon = reconcile_and_record(store, event, {
            "source_type": "camera", "content": specialist.get("description", ""),
            "channel_id": sess["active_channel_id"], "measurement_type": "bubble_count",
            "measurement_value": specialist["count"], "measurement_unit": "count",
            # disagreement between models -> low confidence -> engine asks for confirmation/recapture
            "confidence": 0.3 if specialist.get("abstained") else (0.9 if cross["agree"] else 0.5),
            "media_ref": frame_ids[-1] if frame_ids else None,
        }, sess["active_step_id"])
        recon["cross_check"] = cross
    return PerceptionResult(perception=payload, saved=True, event=event, reconciliation=recon)
