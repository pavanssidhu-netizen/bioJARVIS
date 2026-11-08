"""Skill registry - the single place where model-facing capabilities are declared.

A Skill = name + description + parameter schema + handler + POLICY:
  effect             read | write | model | ui    (what it touches)
  requires_recording  writes refused unless the backend session is active (enforced here, not by the model)
  expose_to_live      included in the Gemini Live tool list (token-locked at mint time)

Everything else derives from this registry: Live tool declarations, the /api/tools/call relay, /api/skills
listing and docs. Adding a capability (e.g. a teammate's sub-model) = register one Skill.
Every execution is a telemetry span (kind=tool) with outcome code, never arguments or results.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Optional

from ..config import get_settings
from ..contracts import MODEL_UI_ACTIONS, EventIn
from ..services.store import ApiError, Store
from . import telemetry
from .models import model_for

Effect = Literal["read", "write", "model", "ui"]


@dataclass
class SkillContext:
    store: Store
    experiment_id: str
    session_id: Optional[str] = None      # recording session as known to the client - re-verified for writes
    call_id: Optional[str] = None         # Gemini functionCall id (idempotency)
    image_base64: Optional[str] = None    # client-held snapshot for vision skills
    caller: str = "gemini_live"


Handler = Callable[[SkillContext, dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]


@dataclass
class Skill:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    effect: Effect = "read"
    requires_recording: bool = False
    expose_to_live: bool = True
    behavior: str = "BLOCKING"
    tags: list[str] = field(default_factory=list)

    def declaration(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters,
                "behavior": self.behavior}

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "effect": self.effect, "requires_recording": self.requires_recording,
                "expose_to_live": self.expose_to_live, "tags": self.tags, "description": self.description,
                "parameters": self.parameters}


_REGISTRY: dict[str, Skill] = {}


def register(skill: Skill) -> Skill:
    _REGISTRY[skill.name] = skill
    return skill


def skill(name: str, description: str, parameters: Optional[dict] = None, **policy: Any):
    """Decorator form: @skill("name", "desc", {...schema...}, effect="write", requires_recording=True)."""
    def wrap(fn: Handler) -> Handler:
        register(Skill(name=name, description=description,
                       parameters=parameters or {"type": "OBJECT", "properties": {}}, handler=fn, **policy))
        return fn
    return wrap


def get(name: str) -> Optional[Skill]:
    return _REGISTRY.get(name)


def all_skills() -> list[Skill]:
    return list(_REGISTRY.values())


def live_declarations() -> list[dict[str, Any]]:
    return [s.declaration() for s in _REGISTRY.values() if s.expose_to_live]


def fail(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "saved": False, "error": code, "message": message, **extra}


async def execute(name: str, ctx: SkillContext, args: dict[str, Any]) -> dict[str, Any]:
    """Policy-enforced execution. Always returns a structured result; never raises to the caller."""
    sk = _REGISTRY.get(name)
    with telemetry.span(f"skill.{name}", "tool", db=ctx.store.db, effect=sk.effect if sk else "unknown",
                        caller=ctx.caller) as sp:
        if sk is None:
            sp.fail("unknown_skill")
            return fail("unknown_tool", f"Unknown tool {name}")
        try:
            ctx.store.get_experiment(ctx.experiment_id)
            if sk.requires_recording:
                rec = ctx.store.get_recording(ctx.session_id) if ctx.session_id else None
                if rec is None or rec.status != "active" or rec.experiment_id != ctx.experiment_id:
                    sp.set(outcome="recording_inactive")
                    return fail("recording_inactive", "No recording session is active; nothing was saved.")
            out = sk.handler(ctx, args)
            if inspect.isawaitable(out):
                out = await out
            sp.set(outcome="ok" if out.get("ok") else str(out.get("error", "not_ok")), saved=bool(out.get("saved")))
            if not out.get("ok"):
                sp.fail(str(out.get("error", "not_ok")))
            return out
        except ApiError as e:
            sp.fail(e.code)
            return fail(e.code, e.message)
        except ValueError as e:
            sp.fail("invalid_input")
            return fail("invalid_input", str(e)[:200])
        except Exception as e:  # noqa: BLE001
            sp.fail(type(e).__name__)
            return fail("tool_backend_error", f"{type(e).__name__}: {str(e)[:200]}")


# =====================================================================================================
# Built-in skills
# =====================================================================================================
OBS_TYPES = ["note", "colour_change", "precipitate", "temperature_note", "timing_note", "volume_note", "equipment_note",
             "sample_label", "visual_description", "protocol_step_done", "deviation", "general_note"]


@skill("get_experiment_context", "Get the current experiment's name, status, protocol and observation count.")
def _ctx(ctx: SkillContext, args: dict) -> dict:
    return {"ok": True, **ctx.store.experiment_context(ctx.experiment_id)}


@skill("get_protocol", "Get the approved protocol steps (ids, quantities, units, tolerances, expected observations).",
       tags=["protocol"])
def _protocol(ctx: SkillContext, args: dict) -> dict:
    p = ctx.store.get_protocol(ctx.experiment_id)
    if p is None:
        return {"ok": True, "protocol": None, "note": "No protocol is loaded for this experiment."}
    return {"ok": True, "version": p.version, "protocol": p.content.model_dump()}


@skill("describe_current_recording_state",
       "Authoritative backend answer to 'are we recording?' plus session id and event count.")
def _rec_state(ctx: SkillContext, args: dict) -> dict:
    rec = ctx.store.active_recording(ctx.experiment_id)
    return {"ok": True, "recording_active": rec is not None, "session_id": rec.id if rec else None,
            "started_at": rec.started_at if rec else None, "event_count": rec.event_count if rec else 0,
            "note": "Only the researcher can start/stop recording via the app buttons."}


@skill("get_recent_observations", "Fetch the most recent saved notes/observations for this experiment.",
       {"type": "OBJECT", "properties": {"limit": {"type": "INTEGER", "description": "1-20, default 5"}}})
def _recent(ctx: SkillContext, args: dict) -> dict:
    limit = max(1, min(int(args.get("limit", 5) or 5), 20))
    last = ctx.store.last_sequence(ctx.experiment_id)
    events = ctx.store.list_events(ctx.experiment_id, after_seq=max(0, last - 80), limit=200)
    events = [e for e in events if e.event_type not in ("transcript_segment", "perception")][-limit:]
    return {"ok": True, "observations": [{"id": e.id, "timestamp": e.timestamp, "type": e.event_type,
                                          "payload": e.payload, "review_status": e.review_status} for e in events]}


@skill("propose_observation",
       ("Persist a structured experimental note the researcher just dictated. Only works while the backend "
        "recording session is active. Returns saved=true only after a committed DB write, plus a deterministic "
        "protocol reconciliation (action, violated constraints, affected channels/results, spoken_response). "
        "ALWAYS speak the reconciliation.spoken_response when present. Fill channel_id (e.g. CH01), "
        "measurement_type and measurement_value whenever the researcher states a quantity or channel."),
       {"type": "OBJECT", "properties": {
           "observation_type": {"type": "STRING", "enum": OBS_TYPES},
           "summary": {"type": "STRING", "description": "One-sentence observation in the researcher's own terms."},
           "subject": {"type": "STRING", "description": "Sample/tube/plate/equipment, if stated."},
           "value": {"type": "STRING", "description": "A stated value WITH units, exactly as said."},
           "channel_id": {"type": "STRING", "description": "Microfluidic channel id if stated, e.g. CH01..CH12"},
           "measurement_type": {"type": "STRING", "enum": ["bubble_count", "channel_fill_complete",
                                                           "incubation_duration_min", "wash_duration_min",
                                                           "temperature_c", "volume_ul", "flow_rate_ul_min", "note"]},
           "measurement_value": {"type": "NUMBER", "description": "Numeric value (booleans: 1=true, 0=false)."},
           "measurement_unit": {"type": "STRING"},
           "protocol_step": {"type": "STRING", "description": "Protocol step id this note relates to, if clear."},
           "is_inference": {"type": "BOOLEAN", "description": "True if an interpretation, not a direct observation."},
           "source_event_id": {"type": "STRING"}},
        "required": ["observation_type", "summary"]},
       effect="write", requires_recording=True)
def _propose(ctx: SkillContext, args: dict) -> dict:
    if args.get("observation_type") not in OBS_TYPES:
        return fail("invalid_observation_type", f"observation_type must be one of {OBS_TYPES}")
    summary = str(args.get("summary", "")).strip()
    if not summary or len(summary) > 2000:
        return fail("invalid_summary", "summary is required (max 2000 chars)")
    payload = {k: args[k] for k in ("observation_type", "summary", "subject", "value", "protocol_step", "is_inference",
                                    "channel_id", "measurement_type", "measurement_value", "measurement_unit",
                                    "classification")
               if k in args}
    payload["proposed_by"] = ctx.caller
    src = args.get("source_event_id") or None
    if src:
        try:
            ctx.store.get_event(src)
        except ApiError:
            src = None  # hallucinated id: drop the link rather than fail the write
    import hashlib
    # Gemini call ids can be short and are only unique within a Live session: hash with the recording session.
    basis = f"call:{ctx.call_id}" if ctx.call_id else f"text:{summary}"
    idem = "tool-" + hashlib.sha256(f"{basis}|{ctx.session_id}".encode()).hexdigest()[:32]
    event, dup = ctx.store.ingest(EventIn(
        session_id=ctx.session_id, experiment_id=ctx.experiment_id, source_modality="speech",
        event_type="observation_proposal", payload=payload, model_name=model_for("live"),
        idempotency_key=idem, source_event_id=src))
    out = {"ok": True, "saved": True, "duplicate": dup, "event_id": event.id,
           "sequence_number": event.sequence_number, "review_status": "pending"}
    # Deterministic reconciliation against the scientific context (seeded experiments only).
    from ..science.service import get_context, reconcile_and_record
    sess = ctx.store.session_state(ctx.session_id)
    if get_context(ctx.store, ctx.experiment_id).get("steps") and not dup:
        mv = args.get("measurement_value")
        if args.get("measurement_type") == "channel_fill_complete" and isinstance(mv, (int, float)):
            mv = bool(mv)
        out["reconciliation"] = reconcile_and_record(ctx.store, event, {
            "source_type": "voice", "content": summary, "channel_id": args.get("channel_id") or sess["active_channel_id"],
            "measurement_type": args.get("measurement_type"), "measurement_value": mv,
            "measurement_unit": args.get("measurement_unit")}, args.get("protocol_step") or sess["active_step_id"])
    return out


@skill("query_lab_log",
       ("Answer a question about what has happened in this experiment from the database log (automatic camera "
        "perception events with objects/actions/counts, dictated notes, transcript, protocol). Use for ANY "
        "question about past events, counts, timing, protocol progress or deviations, e.g. 'how many drops did "
        "I add 30 seconds ago?'. Pass the researcher's question verbatim."),
       {"type": "OBJECT", "properties": {
           "question": {"type": "STRING"},
           "lookback_seconds": {"type": "INTEGER", "description": "How far back to search; default 1800."}},
        "required": ["question"]},
       effect="model", tags=["model-to-model"])
async def _query(ctx: SkillContext, args: dict) -> dict:
    from ..contracts import LogQueryIn
    from ..services.query_agent import answer_question
    q = LogQueryIn(experiment_id=ctx.experiment_id, question=str(args.get("question", "")).strip() or "?",
                   lookback_seconds=int(args.get("lookback_seconds") or 1800))
    return {"ok": True, **(await answer_question(ctx.store, q)).model_dump()}


@skill("request_visual_analysis",
       "Run the high-detail vision model (and specialist sub-model if configured) on the latest captured snapshot.",
       {"type": "OBJECT", "properties": {"image_id": {"type": "STRING"}, "question": {"type": "STRING"}},
        "required": ["question"]},
       effect="model", tags=["model-to-model"])
async def _visual(ctx: SkillContext, args: dict) -> dict:
    from ..services.vision_service import analyse_snapshot
    if not ctx.image_base64:
        return fail("no_image", "No snapshot is available. Use request_ui_action capture_snapshot first, or ask the "
                                "researcher to press Capture Snapshot.")
    r = await analyse_snapshot(ctx.store, ctx.image_base64, str(args.get("question", "")), ctx.experiment_id)
    return {"ok": True, "provider": r.provider, "model": r.model, "description": r.description,
            "structured": r.structured, "persisted": False,
            "note": "Not saved. The researcher can save it from the app while recording."}


@skill("request_ui_action",
       ("Ask the app to perform a SAFE UI action: capture_snapshot (from the open camera), show_tab "
        "(argument: lab|feed|log|diagnostics), show_protocol_step (argument: step id), flip_camera. Cannot start "
        "or stop recording, camera, or microphone."),
       {"type": "OBJECT", "properties": {
           "action": {"type": "STRING", "enum": list(MODEL_UI_ACTIONS)},
           "argument": {"type": "STRING"}}, "required": ["action"]},
       effect="ui")
def _ui(ctx: SkillContext, args: dict) -> dict:
    action = args.get("action")
    if action not in MODEL_UI_ACTIONS:
        return fail("ui_action_not_allowed", f"Allowed: {list(MODEL_UI_ACTIONS)}")
    arg = str(args.get("argument", ""))[:40]
    if action == "show_tab" and arg not in ("lab", "feed", "log", "diagnostics"):
        return fail("invalid_argument", "show_tab argument must be lab|feed|log|diagnostics")
    if action == "show_protocol_step":
        p = ctx.store.get_protocol(ctx.experiment_id)
        if not p or arg not in {s.id for s in p.content.steps}:
            return fail("invalid_argument", "Unknown protocol step id")
    # Approved; the client executes it and reports the actual outcome back to the model.
    return {"ok": True, "approved": True, "ui_action": {"action": action, "argument": arg}, "executed_by": "client"}


def tool_names() -> list[str]:
    return [s.name for s in all_skills() if s.expose_to_live]


# ----------------------------------------------------------------------------- V2 session / science skills
@skill("set_active_step", "Set which protocol step (e.g. step_05) and optionally which channel (e.g. CH03) the "
       "researcher is working on now. Used to check observations against the right constraints.",
       {"type": "OBJECT", "properties": {"step_id": {"type": "STRING"}, "channel_id": {"type": "STRING"}},
        "required": ["step_id"]}, effect="write", requires_recording=True)
def _set_step(ctx: SkillContext, args: dict) -> dict:
    from ..science.service import get_context
    steps = {s["step_id"] for s in get_context(ctx.store, ctx.experiment_id).get("steps", [])}
    sid = str(args.get("step_id", ""))
    if steps and sid not in steps:
        return fail("invalid_step", f"Unknown step. Valid: {sorted(steps)}")
    st = ctx.store.update_session_state(ctx.session_id, active_step_id=sid,
                                        active_channel_id=(str(args["channel_id"]).upper() if args.get("channel_id") else None))
    return {"ok": True, "session_state": st}


@skill("track_object", "Start tracking an object/region in the camera view for this session (e.g. 'bubbles', "
       "'channel CH03', 'pipette tip'). Tracked items are tagged in the live view and prioritised by perception.",
       {"type": "OBJECT", "properties": {"label": {"type": "STRING"}, "channel_id": {"type": "STRING"}},
        "required": ["label"]}, effect="write", requires_recording=True)
def _track(ctx: SkillContext, args: dict) -> dict:
    return {"ok": True, "session_state": ctx.store.track(ctx.session_id, str(args.get("label", "")),
                                                         args.get("channel_id"), by="voice")}


@skill("stop_tracking", "Stop tracking an object (label) or everything (label='all') in this session.",
       {"type": "OBJECT", "properties": {"label": {"type": "STRING"}}, "required": ["label"]},
       effect="write", requires_recording=True)
def _untrack(ctx: SkillContext, args: dict) -> dict:
    return {"ok": True, "session_state": ctx.store.untrack(ctx.session_id, str(args.get("label", "")))}


@skill("discard_observation", "The researcher asks to discard an observation (event_id, or 'last' for the most recent "
       "note/perception). Never deletes: records a 'reject' review by the researcher; the original stays in the audit log.",
       {"type": "OBJECT", "properties": {"event_id": {"type": "STRING"}, "reason": {"type": "STRING"}},
        "required": ["event_id"]}, effect="write", requires_recording=True)
def _discard(ctx: SkillContext, args: dict) -> dict:
    from ..contracts import ReviewIn
    eid = str(args.get("event_id", ""))
    if eid in ("last", "latest", ""):
        rows = ctx.store.db.execute(
            "SELECT id FROM observation_events WHERE session_id=? AND event_type IN "
            "('observation_proposal','perception','visual_observation') ORDER BY sequence_number DESC LIMIT 1",
            (ctx.session_id,))
        if not rows:
            return fail("nothing_to_discard", "No observation in this session yet.")
        eid = rows[0]["id"]
    ev = ctx.store.get_event(eid)
    if ev.experiment_id != ctx.experiment_id:
        return fail("wrong_experiment", "That observation belongs to another experiment.")
    rev, _ = ctx.store.review(eid, ReviewIn(action="reject", reviewer="researcher (voice)",
                                            correction={"reason": str(args.get("reason", ""))[:200]} if args.get("reason") else None))
    return {"ok": True, "discarded_event_id": eid, "review_id": rev.id,
            "note": "Marked rejected; the original record is preserved for audit."}


@skill("investigate_discrepancy", "Deep scientific investigation of a flagged discrepancy or the researcher's 'why' "
       "question: combines protocol constraints, references (PubMed/UniProt/PubChem), and prior session observations.",
       {"type": "OBJECT", "properties": {
           "question": {"type": "STRING"}, "step_id": {"type": "STRING"}, "measurement_type": {"type": "STRING"},
           "measurement_value": {"type": "NUMBER"}, "observation_id": {"type": "STRING"}}, "required": ["question"]},
       effect="model", tags=["model-to-model", "science"])
def _investigate(ctx: SkillContext, args: dict) -> dict:
    from ..science.service import investigate
    return {"ok": True, "investigation": investigate(
        ctx.store, ctx.experiment_id, str(args.get("question", "")), args.get("step_id"),
        args.get("measurement_type"), args.get("measurement_value"), args.get("observation_id"))}


@skill("get_impact", "Which channels, samples and downstream results (standard curve, sample results) may need review "
       "if a given channel or step is compromised. Deterministic dependency-graph traversal.",
       {"type": "OBJECT", "properties": {"channel_id": {"type": "STRING"}, "step_id": {"type": "STRING"}}},
       tags=["science"])
def _impact(ctx: SkillContext, args: dict) -> dict:
    from ..science.service import dependency_graph
    g = dependency_graph(ctx.store, ctx.experiment_id, args.get("channel_id"), args.get("step_id"))
    return {"ok": True, "affected": g["affected"], "note": g["note"]}


def specialist_enabled() -> bool:
    from .models import specialist_provider
    return specialist_provider() != "none"


__all__ = ["Skill", "SkillContext", "register", "skill", "get", "all_skills", "live_declarations", "execute",
           "tool_names", "fail", "get_settings"]
