"""Read-only question answering over the experiment event log (model-to-model: Live -> this agent).

Gemini Live calls `query_lab_log(question)`; this agent gets the question, steering, the approved protocol and
a compact time-stamped window of DB events, and must answer ONLY from them, citing event ids. No write path.
Telemetry records grounding signals (cited vs. valid vs. hallucinated ids) for the eval loop.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from google import genai
from google.genai import types

from ..config import get_settings
from ..contracts import LogQueryIn, LogQueryResult
from ..orchestration import telemetry
from ..orchestration.models import model_for
from ..orchestration.prompts import QUERY_LOG
from ..orchestration.steering import compose
from ..vision.gemini import _generate
from .store import ApiError, Store

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "Direct, short answer suitable to be spoken aloud."},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "evidence_event_ids": {"type": "array", "items": {"type": "string"}},
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["answer", "confidence", "evidence_event_ids", "caveats"],
}

REVIEW = {"reject": "rejected", "accept": "accepted", "dispute": "disputed", "correct": "corrected"}


def _compact(e: dict, now: datetime) -> dict:
    p = json.loads(e["payload_json"])
    if e["event_type"] == "perception":
        p = {k: p.get(k) for k in ("scene_summary", "objects", "actions", "specialist", "window_start", "window_end")
             if p.get(k) is not None}
    ts = datetime.fromisoformat(e["timestamp"])
    if e["event_type"] == "perception" and p.get("window_end"):
        try:  # what happened is when the frames were captured, not when the model finished
            ts = datetime.fromisoformat(str(p["window_end"]).replace("Z", "+00:00"))
        except ValueError:
            pass
    return {"id": e["id"], "ago_s": int((now - ts).total_seconds()), "type": e["event_type"],
            "modality": e["source_modality"], "review_status": e.get("review_status", "pending"), "data": p}


def load_log(store: Store, experiment_id: str, lookback_seconds: int, now: datetime) -> list[dict]:
    since = (now - timedelta(seconds=lookback_seconds)).isoformat(timespec="milliseconds")
    rows = store.db.execute(
        "SELECT e.*, (SELECT action FROM observation_reviews r WHERE r.observation_id = e.id "
        " ORDER BY r.timestamp DESC, r.rowid DESC LIMIT 1) AS last_review "
        "FROM observation_events e WHERE e.experiment_id = ? AND e.timestamp >= ? "
        "ORDER BY e.sequence_number DESC LIMIT 400", (experiment_id, since))
    rows.reverse()
    for r in rows:
        r["review_status"] = REVIEW.get(r.pop("last_review") or "", "pending")
    return [_compact(r, now) for r in rows]


WINDOWS_S = (30, 60, 120, 300, 1800)


def aggregates(events: list[dict]) -> dict:
    """Deterministic counts the LLM should not compute itself: action totals per time window (rejected excluded),
    notes by type, bubble measurements by channel."""
    acts: dict[str, dict[str, int]] = {}
    notes: dict[str, int] = {}
    bubbles: dict[str, int] = {}
    for e in events:
        if e.get("review_status") == "rejected":
            continue
        d = e["data"]
        if e["type"] == "perception":
            for a in d.get("actions") or []:
                label = str(a.get("action", "")).lower().strip()
                if not label:
                    continue
                row = acts.setdefault(label, {f"last_{w}s": 0 for w in WINDOWS_S})
                for w in WINDOWS_S:
                    if e["ago_s"] <= w:
                        row[f"last_{w}s"] += int(a.get("count") or 0)
            sp = d.get("specialist") or {}
            if isinstance(sp.get("count"), int):
                bubbles["specialist_latest"] = sp["count"]
        elif e["type"] == "observation_proposal":
            t = str(d.get("observation_type") or "note")
            notes[t] = notes.get(t, 0) + 1
            if d.get("measurement_type") == "bubble_count" and d.get("channel_id"):
                ch = str(d["channel_id"])
                bubbles[ch] = bubbles.get(ch, 0) + int(float(d.get("measurement_value") or 0))
    return {"action_counts_by_window": acts, "notes_by_type": notes, "notes_total": sum(notes.values()),
            "bubbles_noted_by_channel": bubbles,
            "note": "computed by code from non-rejected events; windows are measured from now using frame time"}


async def answer_question(store: Store, q: LogQueryIn, now: datetime | None = None) -> LogQueryResult:
    """`now` is overridable only for reproducible evals (fixed fixture clock)."""
    s = get_settings()
    if not s.gemini_api_key:
        raise ApiError(503, "gemini_not_configured", "GEMINI_API_KEY is not set")
    store.get_experiment(q.experiment_id)
    now = now or datetime.now(timezone.utc)
    events = load_log(store, q.experiment_id, q.lookback_seconds, now)
    proto = store.get_protocol(q.experiment_id)
    steering, steer_hash = compose("query")
    model = model_for("query")
    import os
    use_agg = os.getenv("LARVIS_QUERY_AGGREGATES", "1") != "0"
    agg_txt = ("Deterministic aggregates (computed by code - use these for any count; cite the events they came from):\n"
               + json.dumps(aggregates(events), separators=(",", ":")) + "\n\n") if use_agg else ""
    prompt = QUERY_LOG.render(
        aggregates=agg_txt,
        now=now.isoformat(timespec="seconds"), question=q.question, n=len(events), lookback=q.lookback_seconds,
        steering=steering or "(none)",
        protocol=proto.content.model_dump_json(exclude_none=True) if proto else "(no protocol loaded)",
        events=json.dumps(events, separators=(",", ":")))
    with telemetry.span("model.query.answer", "generation", db=store.db, model=model,
                        prompt=f"{QUERY_LOG.ref}+steer:{steer_hash}", events_considered=len(events),
                        prompt_chars=len(prompt), protocol_version=proto.version if proto else None,
                        aggregates=use_agg) as sp:
        resp = await _generate(genai.Client(api_key=s.gemini_api_key), model=model, contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=SCHEMA))
        sp.record_usage(resp)
        out = json.loads(resp.text or "{}")
        valid_ids = {e["id"] for e in events}
        cited = [str(i) for i in out.get("evidence_event_ids", [])]
        kept = [i for i in cited if i in valid_ids]  # drop hallucinated ids
        conf = out.get("confidence") if out.get("confidence") in ("high", "medium", "low") else "low"
        sp.set(cited=len(cited), cited_valid=len(kept), cited_hallucinated=len(cited) - len(kept), confidence=conf)
    return LogQueryResult(
        answer=str(out.get("answer", "I could not determine that from the log.")), confidence=conf,
        evidence_event_ids=kept, caveats=[str(c) for c in out.get("caveats", [])][:5],
        events_considered=len(events), model=model, asked_at=now.isoformat(timespec="seconds"),
    )
