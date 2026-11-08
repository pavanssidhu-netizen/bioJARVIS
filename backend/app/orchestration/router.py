"""Utterance router: every researcher utterance (voice transcript or typed) -> ONE action, no conversation.

  text ─► small Gemini call (structured JSON, steering 'router') ─► {category, tool, args, ambiguous, confidence}
       ─► deterministic dispatch through the skills registry (same policy gates as everything else)
       ─► short confirmation text for the voice to speak

Ambiguous lab-relevant input is still logged (tagged `classification.ambiguous=true`) and can be re-classified
at review via a correction; non-scientific chatter is dropped without storage.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from google import genai
from google.genai import types

from ..config import get_settings
from ..services.store import Store
from . import skills, telemetry
from .models import model_for
from .prompts import ROUTER
from .steering import compose

CATEGORIES = ["observation", "protocol_step", "command", "question", "non_scientific"]
ROUTABLE = ["propose_observation", "set_active_step", "track_object", "stop_tracking", "discard_observation",
            "query_lab_log", "get_impact", "investigate_discrepancy", "describe_current_recording_state",
            "get_protocol", "request_ui_action", "none"]

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": CATEGORIES},
        "tool": {"type": "string", "enum": ROUTABLE},
        "args": {"type": "object", "properties": {
            "observation_type": {"type": "string", "enum": skills.OBS_TYPES},
            "summary": {"type": "string"}, "subject": {"type": "string"}, "value": {"type": "string"},
            "channel_id": {"type": "string"}, "step_id": {"type": "string"}, "protocol_step": {"type": "string"},
            "measurement_type": {"type": "string", "enum": ["bubble_count", "channel_fill_complete",
                                                            "incubation_duration_min", "wash_duration_min",
                                                            "temperature_c", "volume_ul", "flow_rate_ul_min", "note"]},
            "measurement_value": {"type": "number"}, "measurement_unit": {"type": "string"},
            "label": {"type": "string"}, "event_id": {"type": "string"}, "reason": {"type": "string"},
            "question": {"type": "string"}, "action": {"type": "string"}, "argument": {"type": "string"},
            "is_inference": {"type": "boolean"}}},
        "ambiguous": {"type": "boolean"},
        "ambiguity_reason": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": ["category", "tool", "args", "ambiguous", "confidence"],
}


def _tool_catalogue() -> str:
    lines = []
    for name in ROUTABLE[:-1]:
        sk = skills.get(name)
        if sk:
            props = ", ".join(sk.parameters.get("properties", {}).keys())
            lines.append(f"- {name}: {sk.description[:160]} | {props}")
    return "\n".join(lines)


_NUM = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve".split())}


def _spoken_number(tok: str) -> Optional[int]:
    tok = tok.lower()
    return int(tok) if tok.isdigit() else _NUM.get(tok)


def _extract_ids(text: str) -> dict[str, str]:
    """Deterministic fallback for ids the classifier may drop: 'channel eight' -> CH08, 'step seven' -> step_07."""
    import re
    out: dict[str, str] = {}
    t = text.lower()
    m = re.search(r"\b(?:channel|ch)\s*(\d{1,2}|" + "|".join(_NUM) + r")\b", t)
    if m and (n := _spoken_number(m.group(1))) and 1 <= n <= 12:
        out["channel_id"] = f"CH{n:02d}"
    m = re.search(r"\bstep\s*(\d{1,2}|" + "|".join(_NUM) + r")\b", t)
    if m and (n := _spoken_number(m.group(1))) and 1 <= n <= 9:
        out["step_id"] = f"step_{n:02d}"
    return out


def _confirmation(category: str, tool: str, res: dict, ambiguous: bool, args: Optional[dict] = None) -> Optional[str]:
    args = args or {}
    if tool == "none":
        return None
    if not res.get("ok"):
        if res.get("error") == "recording_inactive":
            return "Not saved: recording is off. Press Start Recording to log it."
        return f"Couldn't do that: {res.get('message') or res.get('error')}"
    if tool == "propose_observation":
        rc = res.get("reconciliation") or {}
        what = args.get("summary", "")
        base = f"Logged: {what}".rstrip(". ") + "." + (" Marked ambiguous for review." if ambiguous else "")
        return f"{base} {rc['spoken_response']}" if rc.get("requires_human_approval") and rc.get("spoken_response") else base
    if tool == "set_active_step":
        st = res.get("session_state", {})
        return f"Now on {st.get('active_step_id')}" + (f", {st['active_channel_id']}." if st.get("active_channel_id") else ".")
    if tool == "track_object":
        return "Tracking " + ", ".join(t["label"] for t in res.get("session_state", {}).get("tracking", [])[-1:]) + "."
    if tool == "stop_tracking":
        return "Stopped tracking."
    if tool == "discard_observation":
        return "Discarded the last observation. It stays in the audit log as rejected."
    if tool == "query_lab_log":
        return res.get("answer")
    if tool == "get_impact":
        dv = (res.get("affected") or {}).get("structured", {}).get("derived_values", [])
        return ("That may affect " + ", ".join(dv[:4]) + ("" if len(dv) <= 4 else f" and {len(dv) - 4} more") + ".") if dv \
            else "No downstream results depend on that."
    if tool == "describe_current_recording_state":
        return "Recording is on." if res.get("recording_active") else "Recording is off."
    if tool == "investigate_discrepancy":
        inv = res.get("investigation") or {}
        return str(inv.get("spoken_response") or inv.get("summary") or "Investigation added to the log.")[:300]
    if tool == "get_protocol":
        return f"Protocol version {res.get('version')} is loaded."
    return "Done."


async def route_utterance(store: Store, experiment_id: str, session_id: Optional[str], text: str,
                          source: str = "voice", call_id: Optional[str] = None) -> dict[str, Any]:
    text = (text or "").strip()
    if len(text) < 2:
        return {"category": "non_scientific", "tool": "none", "stored": False, "spoken": None}
    s = get_settings()
    from ..science.service import get_context
    ctx = get_context(store, experiment_id)
    sess = store.session_state(session_id) if session_id else {"active_step_id": None, "active_channel_id": None}
    rec = store.active_recording(experiment_id)
    steering, steer_hash = compose("router")
    prompt = ROUTER.render(steering=steering,
                           steps=", ".join(f"{x['step_id']}={x['name']}" for x in ctx.get("steps", [])) or "(none)",
                           recording=bool(rec and rec.id == session_id), active_step=sess.get("active_step_id"),
                           active_channel=sess.get("active_channel_id"), tools=_tool_catalogue(), source=source,
                           text=text.replace('"', "'")[:600])
    model = model_for("router")
    with telemetry.span("model.router.classify", "generation", db=store.db, model=model,
                        prompt=f"{ROUTER.ref}+steer:{steer_hash}", source=source, chars=len(text)) as sp:
        client = genai.Client(api_key=s.gemini_api_key)
        try:
            resp = await client.aio.models.generate_content(
                model=model, contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=SCHEMA))
        finally:
            await client.aio.aclose()
        sp.record_usage(resp)
        d = json.loads(resp.text or "{}")
        cat = d.get("category") if d.get("category") in CATEGORIES else "non_scientific"
        tool = d.get("tool") if d.get("tool") in ROUTABLE else "none"
        args = {k: v for k, v in (d.get("args") or {}).items() if v not in (None, "")}
        amb = bool(d.get("ambiguous"))
        # Deterministic fix-ups (never trust the classifier blindly)
        if cat == "non_scientific":
            tool = "none"
        ids = _extract_ids(text)
        if tool in ("propose_observation", "set_active_step", "get_impact") and ids.get("channel_id") \
                and not args.get("channel_id"):
            args["channel_id"] = ids["channel_id"]
        if tool == "set_active_step" and ids.get("step_id") and not args.get("step_id"):
            args["step_id"] = ids["step_id"]
        if tool == "propose_observation":
            args.setdefault("observation_type", "protocol_step_done" if cat == "protocol_step" else "general_note")
            args.setdefault("summary", text[:300])
            if args.get("channel_id"):
                args["channel_id"] = str(args["channel_id"]).upper().replace("CHANNEL", "CH").replace(" ", "")
        if tool == "query_lab_log":
            args.setdefault("question", text)
        if tool == "investigate_discrepancy":
            args.setdefault("question", text)
        # Deterministic rule: an utterance starting with "note" is a direct instruction to log it verbatim as a note.
        import re as _re
        is_note = bool(_re.match(r"^\s*(please\s+)?(take\s+a\s+)?notes?\b[\s,:-]*", text, _re.I))
        if is_note:
            cat, tool, amb = "observation", "propose_observation", False
            args = {k: v for k, v in args.items() if k in ("channel_id", "measurement_type", "measurement_value",
                                                         "measurement_unit", "protocol_step", "subject", "value")}
            args.update({"observation_type": "note", "summary": text[:600]})
            if ids.get("channel_id") and not args.get("channel_id"):
                args["channel_id"] = ids["channel_id"]
        if tool == "set_active_step" and not args.get("step_id"):
            tool, args = "propose_observation", {"observation_type": "protocol_step_done", "summary": text[:300]}
            amb = True
        sp.set(category=cat, tool=tool, ambiguous=amb, confidence=str(d.get("confidence")), note_rule=is_note)
    out: dict[str, Any] = {"text": text, "source": source, "category": cat, "tool": tool, "args": args, "ambiguous": amb,
                           "ambiguity_reason": d.get("ambiguity_reason"), "confidence": d.get("confidence"),
                           "router_model": model, "stored": False}
    if tool == "none":
        out["spoken"] = None
        return out
    sctx = skills.SkillContext(store=store, experiment_id=experiment_id, session_id=session_id, call_id=call_id,
                               caller=f"router:{source}")
    if tool == "propose_observation":
        # Tag the classification on the record so it can be reviewed / re-classified later.
        args["classification"] = {"category": cat, "ambiguous": amb, "reason": d.get("ambiguity_reason"),
                                  "confidence": d.get("confidence"), "router": f"{model}:{ROUTER.ref}"}
    res = await skills.execute(tool, sctx, args)
    out["result"] = res
    out["stored"] = bool(res.get("saved"))
    out["spoken"] = _confirmation(cat, tool, res, amb, args)
    return out
