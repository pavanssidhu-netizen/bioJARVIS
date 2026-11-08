"""LABMATE API. Same ASGI app runs locally (uvicorn, 127.0.0.1), on Vercel (api/index.py) and on Modal
(modal_app/backend_app.py). Layers:

  api (this file)        HTTP contracts, auth boundary (deployment protection), request tracing
  orchestration/         skills registry + policy, steering docs, versioned prompts, model routing, telemetry
  services/              store (DB authority), perception, vision, query agent
  vision/                provider adapters (gemini | specialist local | modal)
"""
from __future__ import annotations

import asyncio
import os
import logging
import re
import statistics
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .config import get_settings
from .contracts import (Capabilities, ErrorBody, EventAck, EventIn, EventPage, Experiment, ExperimentCreate, Health,
                        LiveTokenResponse, LogQueryIn, LogQueryResult, ObservationEvent, PerceptionResult,
                        PerceptionWindowIn, ProtocolContent, ProtocolDocument, RecordingSession, RecordingStart,
                        RecordingStop, ReviewIn, ReviewResult, TelemetrySummary, ToolCallIn, UiActionBatch,
                        VisionRequest, VisionResult)
from .db import get_db
from .live.token import mint_live_token
from .live.tools import execute_tool
from .orchestration import skills, steering, telemetry
from .orchestration.models import routing_table
from .services.perception import process_window
from .services.query_agent import answer_question
from .services.store import ApiError, Store, now_iso
from .services.vision_service import analyse_snapshot
from .vision import VisionNotConfigured, decode_image, get_specialist_provider

log = logging.getLogger("labmate")  # never log payloads, transcripts or keys

app = FastAPI(title="Larvis API", version="0.2.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
api = APIRouter(prefix="/api")

# Local UI development ONLY (flutter run serves the app on another localhost port). Off unless LARVIS_DEV_CORS=1,
# restricted to loopback origins, and refused on any Vercel deployment.
if os.getenv("LARVIS_DEV_CORS") == "1" and not os.getenv("VERCEL_ENV"):
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware, allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
                       allow_methods=["*"], allow_headers=["*"], allow_credentials=False)

ERR = {409: {"model": ErrorBody}, 404: {"model": ErrorBody}, 422: {"model": ErrorBody}}
_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


def store() -> Store:
    return Store(get_db())


@app.middleware("http")
async def guard_and_trace(request: Request, call_next):
    # Vercel Hobby deployment protection covers preview URLs but NOT the production domain.
    # Fail closed: refuse to serve the API on an unprotected production deployment unless explicitly allowed.
    s = get_settings()
    if s.vercel_env == "production" and not s.allow_production:
        return JSONResponse(status_code=403, content={"error": "production_disabled",
                                                      "message": "Use the protected preview deployment URL."})
    if not request.url.path.startswith("/api"):
        return await call_next(request)
    sess = request.headers.get("x-labmate-session", "")
    t1 = telemetry.trace_id_var.set(telemetry.new_trace_id())
    t2 = telemetry.session_id_var.set(sess if _SESSION_RE.match(sess) else "")
    try:
        with telemetry.span("api.request", "span", method=request.method) as sp:
            response = await call_next(request)
            route = request.scope.get("route")
            sp.name = f"api.{request.method} {getattr(route, 'path', 'unmatched')}"
            sp.set(status_code=response.status_code)
            if response.status_code >= 500:
                sp.fail(f"http_{response.status_code}")
            # Don't trace the high-frequency poll/heartbeat endpoints individually beyond the span itself.
        return response
    finally:
        telemetry.trace_id_var.reset(t1)
        telemetry.session_id_var.reset(t2)


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, e: ApiError):
    return JSONResponse(status_code=e.status, content=ErrorBody(error=e.code, message=e.message, detail=e.detail).model_dump())


# ---------------- health / capabilities / orchestration introspection ----------------
@api.get("/health", response_model=Health)
def health() -> Health:
    s = get_settings()
    try:
        last, ok = store().last_write(), True
    except Exception:  # noqa: BLE001 - diagnostics endpoint must not crash
        log.exception("db health check failed")
        last, ok = None, False
    return Health(status="ok" if ok else "degraded", database_ok=ok, database=s.database_label,
                  last_db_write=last, time=now_iso())


@api.get("/capabilities", response_model=Capabilities)
def capabilities() -> Capabilities:
    s = get_settings()
    from .vision.specialist import SpecialistVisionProvider
    spec = get_specialist_provider()
    return Capabilities(gemini_configured=bool(s.gemini_api_key), live_model=s.live_model, vision_model=s.vision_model,
                        vision_provider=s.vision_provider,
                        specialist_vision=(spec or SpecialistVisionProvider()).status(),
                        modal_enabled=s.modal_enabled, database=s.database_label, raw_media_storage=False,
                        heartbeat_timeout_s=s.heartbeat_timeout_s, tools=skills.tool_names(),
                        routing=routing_table(), steering_docs=steering.list_docs(),
                        telemetry_enabled=telemetry.enabled())


@api.get("/skills")
def list_skills() -> list[dict]:
    """Every registered capability with its policy (effect, requires_recording, exposed to Live)."""
    return [s.describe() for s in skills.all_skills()]


@api.get("/steering")
def list_steering() -> dict:
    return {"docs": steering.list_docs(), "roles": {r: steering.compose(r)[1] for r in ("live", "query", "perception", "vision")}}


@api.get("/telemetry/summary", response_model=TelemetrySummary)
def telemetry_summary(minutes: int = Query(60, ge=1, le=10080), st: Store = Depends(store)):
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="milliseconds")
    rows = st.db.execute("SELECT name, status, latency_ms, input_tokens, output_tokens FROM telemetry_spans "
                         "WHERE start_time >= ?", (since,))
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["name"], []).append(r)

    def pct(xs: list[float], p: float) -> float:
        xs = sorted(xs)
        return round(xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))], 1) if xs else 0.0

    by = [{"name": k, "n": len(v), "errors": sum(1 for x in v if x["status"] != "ok"),
           "p50_ms": pct([x["latency_ms"] for x in v], 0.5), "p95_ms": pct([x["latency_ms"] for x in v], 0.95),
           "mean_ms": round(statistics.fmean(x["latency_ms"] for x in v), 1),
           "input_tokens": sum(x["input_tokens"] or 0 for x in v), "output_tokens": sum(x["output_tokens"] or 0 for x in v)}
          for k, v in sorted(groups.items())]
    return TelemetrySummary(window_minutes=minutes, spans=len(rows), by_name=by)


# ---------------- experiments + protocol ----------------
@api.get("/experiments", response_model=list[Experiment])
def list_experiments(st: Store = Depends(store)):
    return st.list_experiments()


@api.post("/experiments", response_model=Experiment, status_code=201)
def create_experiment(body: ExperimentCreate, st: Store = Depends(store)):
    return st.create_experiment(body.name)


@api.get("/experiments/{exp_id}", response_model=Experiment, responses=ERR)
def get_experiment(exp_id: str, st: Store = Depends(store)):
    return st.get_experiment(exp_id)


@api.get("/experiments/{exp_id}/protocol", response_model=Optional[ProtocolDocument], responses=ERR)
def get_protocol(exp_id: str, version: Optional[int] = None, st: Store = Depends(store)):
    st.get_experiment(exp_id)
    return st.get_protocol(exp_id, version)


@api.put("/experiments/{exp_id}/protocol", response_model=ProtocolDocument, status_code=201, responses=ERR)
def put_protocol(exp_id: str, body: ProtocolContent, st: Store = Depends(store)):
    """Creates a new protocol version (earlier versions are retained)."""
    return st.put_protocol(exp_id, body)


# ---------------- recordings ----------------
@api.post("/recordings/start", response_model=RecordingSession, status_code=201, responses=ERR)
def start_recording(body: RecordingStart, st: Store = Depends(store)):
    return st.start_recording(body.experiment_id)


@api.post("/recordings/{rec_id}/stop", response_model=RecordingSession, responses=ERR)
async def stop_recording(rec_id: str, request: Request, st: Store = Depends(store)):
    # Accepts an empty body too, so navigator.sendBeacon() can stop recording on page unload.
    reason = "user_stopped"
    raw = await request.body()
    if raw:
        try:
            reason = RecordingStop.model_validate_json(raw).reason
        except ValueError:
            pass
    return st.stop_recording(rec_id, reason)


@api.post("/recordings/{rec_id}/heartbeat", response_model=RecordingSession, responses=ERR)
def heartbeat(rec_id: str, st: Store = Depends(store)):
    return st.heartbeat(rec_id)


@api.get("/recordings/{rec_id}", response_model=RecordingSession, responses=ERR)
def get_recording(rec_id: str, st: Store = Depends(store)):
    return st.get_recording(rec_id)


@api.get("/recordings", response_model=Optional[RecordingSession])
def active_recording(experiment_id: str, st: Store = Depends(store)):
    return st.active_recording(experiment_id)


# ---------------- observations / events ----------------
@api.get("/observations", response_model=list[ObservationEvent])
def list_observations(experiment_id: Optional[str] = None, after_seq: int = 0, limit: int = Query(200, le=500),
                      event_type: Optional[str] = None, modality: Optional[str] = None, st: Store = Depends(store)):
    return st.list_events(experiment_id, after_seq, limit, event_type, modality)


@api.get("/observations/{obs_id}", response_model=ObservationEvent, responses=ERR)
def get_observation(obs_id: str, st: Store = Depends(store)):
    return st.get_event(obs_id)


@api.post("/observations/propose", response_model=EventAck,
          responses={409: {"model": EventAck}, 404: {"model": ErrorBody}})
def propose(body: EventIn, st: Store = Depends(store)):
    try:
        event, dup = st.ingest(body)
    except ApiError as e:
        if e.code == "recording_inactive":
            return JSONResponse(status_code=409, content=EventAck(ok=False, saved=False, error=e.code,
                                                                  message=e.message).model_dump())
        raise
    return EventAck(ok=True, saved=True, duplicate=dup, event=event)


@api.post("/observations/{obs_id}/review", response_model=ReviewResult, responses=ERR)
def review(obs_id: str, body: ReviewIn, st: Store = Depends(store)):
    rev, corr = st.review(obs_id, body)
    return ReviewResult(review=rev, correction_event=corr)


@api.get("/events/{experiment_id}", response_model=EventPage)
def poll_events(experiment_id: str, after_seq: int = 0, limit: int = Query(200, le=500), st: Store = Depends(store)):
    """Polling feed: clients pass the last sequence they hold and receive anything newer (missed-update recovery)."""
    st.get_experiment(experiment_id)
    events = st.list_events(experiment_id, after_seq, limit)
    return EventPage(experiment_id=experiment_id, events=events,
                     last_sequence=events[-1].sequence_number if events else max(after_seq, 0),
                     recording=st.active_recording(experiment_id))


@api.get("/events/{experiment_id}/stream")
async def stream_events(experiment_id: str, request: Request, after_seq: int = 0, max_seconds: int = Query(25, le=300)):
    """Server-Sent Events. Bounded duration (serverless-friendly); resume with Last-Event-ID or after_seq."""
    st = store()
    st.get_experiment(experiment_id)
    cursor = int(request.headers.get("last-event-id") or after_seq or 0)

    async def gen():
        nonlocal cursor
        loop = asyncio.get_event_loop()
        end = loop.time() + max_seconds
        yield "retry: 1000\n\n"
        while loop.time() < end and not await request.is_disconnected():
            for e in st.list_events(experiment_id, cursor, 200):
                cursor = e.sequence_number
                yield f"id: {cursor}\nevent: observation\ndata: {e.model_dump_json()}\n\n"
            await asyncio.sleep(1.0)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


# ---------------- UI actions ----------------
@api.post("/ui/actions", status_code=202)
def ui_actions(body: UiActionBatch, st: Store = Depends(store)) -> dict:
    """Content-free interaction log from the app (button presses, tab changes, executed model UI actions)."""
    return {"accepted": st.record_ui_actions(body)}


@api.get("/ui/actions")
def recent_ui_actions(experiment_id: str, limit: int = Query(50, le=500), st: Store = Depends(store)) -> list[dict]:
    return st.recent_ui_actions(experiment_id, limit)


# ---------------- vision ----------------
@api.post("/vision/analyse", response_model=VisionResult, responses=ERR)
async def vision_analyse(body: VisionRequest, st: Store = Depends(store)):
    s = get_settings()
    try:
        img = decode_image(body.image_base64, s.max_image_bytes)
    except ValueError as e:
        raise ApiError(413 if str(e) == "image_too_large" else 422, str(e), "Image rejected") from e
    if body.save:  # check BEFORE spending a model call; re-checked atomically at write time by ingest()
        if not (body.session_id and body.experiment_id):
            raise ApiError(409, "recording_inactive", "Saving requires an active recording session")
        if st.get_recording(body.session_id).status != "active":
            raise ApiError(409, "recording_inactive", "Recording is not active; nothing was saved")
    try:
        result = await analyse_snapshot(st, body.image_base64, body.question, body.experiment_id)
    except VisionNotConfigured as e:
        raise ApiError(503, "vision_not_configured", str(e)) from e
    except Exception as e:  # noqa: BLE001
        log.warning("vision provider error: %s", type(e).__name__)
        raise ApiError(502, "vision_provider_error", f"{type(e).__name__}: {str(e)[:300]}") from e
    out = VisionResult(provider=result.provider, model=result.model, description=result.description,
                       structured=result.structured, image_sha256=img.sha256)
    if body.save:
        try:
            event, _ = st.ingest(EventIn(
                session_id=body.session_id, experiment_id=body.experiment_id, source_modality="image",
                event_type="visual_observation",
                payload={"question": body.question, "description": result.description, "structured": result.structured,
                         "image_sha256": img.sha256, "raw_image_stored": False},
                model_name=result.model, idempotency_key=body.idempotency_key or f"vis-{uuid.uuid4().hex}",
            ))
            st.record_media_hash(body.experiment_id, img.sha256, img.mime_type, event.id)
            out.saved, out.event = True, event
        except ApiError as e:
            out.save_error = e.code
    return out


# ---------------- live feed perception + log queries ----------------
@api.post("/perception/window", response_model=PerceptionResult, responses=ERR)
async def perception_window(body: PerceptionWindowIn, st: Store = Depends(store)):
    """Analyse a window of consecutive frames into the objects/actions contract; persisted only while recording."""
    try:
        return await process_window(st, body)
    except VisionNotConfigured as e:
        raise ApiError(503, "vision_not_configured", str(e)) from e
    except ApiError:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("perception error: %s", type(e).__name__)
        raise ApiError(502, "vision_provider_error", f"{type(e).__name__}: {str(e)[:300]}") from e


@api.post("/query", response_model=LogQueryResult, responses=ERR)
async def query_log(body: LogQueryIn, st: Store = Depends(store)):
    """Read-only natural-language question over the experiment log (same agent the voice tool uses)."""
    try:
        return await answer_question(st, body)
    except ApiError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ApiError(502, "query_agent_error", f"{type(e).__name__}: {str(e)[:300]}") from e


# ---------------- V2: science (context, graph, reconciliation, reviews, investigation, predictive) ----------------
from .science import service as science  # noqa: E402


@api.get("/experiments/{exp_id}/context", responses=ERR)
def experiment_context(exp_id: str, st: Store = Depends(store)) -> dict:
    """Full scientific context (Person 2 seed shape): steps, reagents, samples, channel_map, constraints,
    dependencies, derived_values, related_evidence."""
    return science.get_context(st, exp_id)


@api.put("/experiments/{exp_id}/context", status_code=201, responses=ERR)
def put_experiment_context(exp_id: str, body: dict, st: Store = Depends(store)) -> dict:
    """Store a NEW context version (e.g. team scientist filled in tolerances); also refreshes the protocol view."""
    if not body.get("steps"):
        raise ApiError(422, "invalid_context", "context must include steps[]")
    return {"experiment_id": exp_id, "version": science.put_context(st, exp_id, body)}


@api.get("/experiments/{exp_id}/graph", responses=ERR)
def experiment_graph(exp_id: str, focus: Optional[str] = None, step_id: Optional[str] = None,
                     st: Store = Depends(store)) -> dict:
    """Dependency graph nodes/edges; with focus=CH01 or step_id=step_05 also returns affected entities."""
    return science.dependency_graph(st, exp_id, focus, step_id)


@api.post("/experiments/{exp_id}/reconcile", responses=ERR)
def reconcile_preview(exp_id: str, body: dict, st: Store = Depends(store)) -> dict:
    """Dry-run deterministic reconciliation (nothing persisted). Body: {step_id, channel_id, measurement_type,
    measurement_value, measurement_unit, content, source_type, confidence}."""
    science.require_context(st, exp_id)
    return science.reconcile(st, exp_id, body, body.get("step_id"))


@api.get("/reviews/pending")
def reviews_pending(experiment_id: str, st: Store = Depends(store)) -> list[dict]:
    """Flags awaiting human sign-off: reconciliation decisions with requires_human_approval and no review yet."""
    return science.pending_reviews(st, experiment_id)


@api.post("/investigate", responses=ERR)
def investigate(body: dict, st: Store = Depends(store)) -> dict:
    """Deep investigation (Person 4 Argon engine): {experiment_id, question, step_id?, measurement_type?,
    measurement_value?, observation_id?}."""
    exp = body.get("experiment_id") or science.DEFAULT_EXPERIMENT
    science.require_context(st, exp)
    return science.investigate(st, exp, str(body.get("question", "")), body.get("step_id"),
                               body.get("measurement_type"), body.get("measurement_value"), body.get("observation_id"))


@api.post("/predictive/optimise")
async def predictive_optimise(body: dict) -> dict:
    """Person 3 GP Bayesian optimiser (compensatory action under bubble obstruction). Needs torch (local/Modal)."""
    try:
        from backend.vision.predictive_models import GaussianProcessBayesianOptimizer
    except ImportError as e:
        if get_settings().modal_enabled:  # Vercel: no torch -> run Person 3's optimiser on Modal
            import modal
            for k in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"):
                if os.environ.get(k) == "":
                    os.environ.pop(k)
            with telemetry.span("model.predictive.optimise", "generation", model="gp-bayes-opt@modal"):
                return await modal.Function.from_name(get_settings().modal_app, "optimise").remote.aio(body)
        raise ApiError(503, "predictive_not_available", f"predictive models need torch or MODAL_ENABLED: {e}") from e
    import inspect
    opt = GaussianProcessBayesianOptimizer()
    fn = opt.optimize_compensatory_action
    allowed = set(inspect.signature(fn).parameters)
    with telemetry.span("model.predictive.optimise", "generation", model="gp-bayes-opt (Person 3)"):
        res = fn(**{k: v for k, v in body.items() if k in allowed})
    import json as _json
    return _json.loads(_json.dumps(res, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))


@api.post("/vision/specialist", responses=ERR)
async def vision_specialist(body: VisionRequest, step_id: str = "step_05", st: Store = Depends(store)) -> dict:
    """Run ONLY the specialist council (Person 3) on an image - bubble detections, count, overlay, sceptic critique."""
    from .services.vision_service import run_specialist
    try:
        img = decode_image(body.image_base64, get_settings().max_image_bytes)
    except ValueError as e:
        raise ApiError(422, str(e), "Image rejected") from e
    res = await run_specialist(st, "image", image=img, question=body.question,
                               experiment_id=body.experiment_id or science.DEFAULT_EXPERIMENT, step_id=step_id)
    if res is None:
        raise ApiError(503, "specialist_not_configured", "Set SPECIALIST_PROVIDER=local|modal")
    return res


# ---------------- V2: live session state, tracking, retained frames ----------------
@api.get("/recordings/{rec_id}/state", responses=ERR)
def session_state(rec_id: str, st: Store = Depends(store)) -> dict:
    return st.session_state(rec_id)


@api.put("/recordings/{rec_id}/state", responses=ERR)
def put_session_state(rec_id: str, body: dict, st: Store = Depends(store)) -> dict:
    """{active_step_id?, active_channel_id?} (active_channel_id=null clears)."""
    return st.update_session_state(rec_id, active_step_id=body.get("active_step_id"),
                                   active_channel_id=body.get("active_channel_id"),
                                   clear_channel="active_channel_id" in body and body["active_channel_id"] is None)


@api.post("/recordings/{rec_id}/tracking", responses=ERR)
def add_tracking(rec_id: str, body: dict, st: Store = Depends(store)) -> dict:
    return st.track(rec_id, str(body.get("label", "")), body.get("channel_id"), by=body.get("by", "user"))


@api.delete("/recordings/{rec_id}/tracking/{label}", responses=ERR)
def remove_tracking(rec_id: str, label: str, st: Store = Depends(store)) -> dict:
    return st.untrack(rec_id, label)


@api.get("/recordings/{rec_id}/frames", responses=ERR)
def list_frames(rec_id: str, start: Optional[str] = None, end: Optional[str] = None, st: Store = Depends(store)) -> dict:
    """Frames retained for this session (purged automatically when it stops/expires)."""
    st.get_recording(rec_id)
    return {"session_id": rec_id, "frames": st.list_frames(rec_id, start, end)}


@api.get("/recordings/{rec_id}/frames/{frame_id}", responses=ERR)
def get_frame(rec_id: str, frame_id: str, st: Store = Depends(store)):
    from fastapi.responses import Response
    f = st.get_frame(rec_id, frame_id)
    return Response(content=f["data"], media_type=f["mime_type"], headers={"Cache-Control": "private, max-age=600"})


@api.post("/recordings/{rec_id}/reanalyse", responses=ERR)
async def reanalyse(rec_id: str, body: dict, st: Store = Depends(store)) -> dict:
    """Re-run perception (+specialist) on retained frames: {start?, end?, frame_ids?, question?}. Not persisted."""
    import base64 as _b64
    rec = st.get_recording(rec_id)
    ids = body.get("frame_ids")
    metas = st.list_frames(rec_id, body.get("start"), body.get("end"))
    if ids:
        metas = [m for m in metas if m["id"] in set(ids)]
    metas = metas[-8:]
    if not metas:
        raise ApiError(404, "no_frames", "No retained frames in that range (frames are purged at session end)")
    frames = [st.get_frame(rec_id, m["id"]) for m in metas]
    res = await process_window(st, PerceptionWindowIn(
        frames_base64=[_b64.b64encode(f["data"]).decode() for f in frames], frame_interval_s=1.0,
        window_start=metas[0]["captured_at"], window_end=metas[-1]["captured_at"], experiment_id=rec.experiment_id,
        session_id=None, idempotency_key=f"reanalyse-{uuid.uuid4().hex}", hint=body.get("question")))
    return {"frames": [m["id"] for m in metas], "perception": res.perception.model_dump(), "persisted": False}


# ---------------- V2: history (past experiments / trials) ----------------
@api.get("/experiments/{exp_id}/sessions", responses=ERR)
def experiment_sessions(exp_id: str, st: Store = Depends(store)) -> list[dict]:
    return st.experiment_sessions(exp_id)


@api.get("/recordings/{rec_id}/summary", responses=ERR)
def recording_summary(rec_id: str, st: Store = Depends(store)) -> dict:
    rec = st.get_recording(rec_id)
    events = [e for e in st.list_events(rec.experiment_id, limit=500) if e.session_id == rec_id]
    by_type: dict[str, int] = {}
    for e in events:
        by_type[e.event_type] = by_type.get(e.event_type, 0) + 1
    flags = [e for e in events if e.event_type == "reconciliation" and e.payload.get("requires_human_approval")]
    return {"recording": rec.model_dump(), "event_counts": by_type, "flags": [f.model_dump() for f in flags],
            "notes": [e.model_dump() for e in events if e.event_type == "observation_proposal"],
            "state": st.session_state(rec_id) if rec.status == "active" else None}


# ---------------- live ----------------
@api.post("/live/token", response_model=LiveTokenResponse, responses={503: {"model": ErrorBody}})
def live_token(experiment_id: str = "exp_001", st: Store = Depends(store)):
    if not get_settings().gemini_api_key:
        raise ApiError(503, "gemini_not_configured", "GEMINI_API_KEY is not set on the server")
    st.get_experiment(experiment_id)
    try:
        return mint_live_token(st, experiment_id)
    except Exception as e:  # noqa: BLE001
        log.warning("token mint failed: %s", type(e).__name__)
        raise ApiError(502, "token_mint_failed", f"{type(e).__name__}: {str(e)[:300]}") from e


@api.post("/tools/call")
async def tools_call(body: ToolCallIn, st: Store = Depends(store)) -> dict:
    """Relay target for Gemini functionCalls. Result is always structured; never raises for tool-level failures."""
    return await execute_tool(st, body)


app.include_router(api)


@app.get("/api", include_in_schema=False)
def root():
    return {"service": "labmate", "docs": "/api/docs"}
