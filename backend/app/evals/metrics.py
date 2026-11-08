"""System metrics for the eval loop. Pure functions over the app DB + telemetry (no model calls).

Each metric answers a question a judge (or an on-call engineer) would ask; see docs/METRICS.md.

  integrity.gate_violations          events persisted outside an active recording window   (target 0)
  integrity.unsessioned_writes       non-correction events with no recording session        (target 0)
  notes.save_success_rate            propose_observation calls that reached a committed write
  notes.attempts_while_inactive      model tried to save while not recording (refused, by design)
  grounding.hallucinated_id_rate     cited event ids that did not exist in the provided log   (lower = better)
  grounding.answers_with_evidence    log answers citing >=1 real event
  perception.persist_rate            windows saved / windows analysed (rest: no_change / inactive)
  perception.actions_per_window      mean actions detected per analysed window
  latency.<stage>.p50/p95_ms         perception, query, token mint, tool relay, end-to-end API
  reliability.<stage>.error_rate     failures per stage
  cost.tokens_per_live_minute        model tokens per minute of recording (cost proxy)
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

STAGES = {
    "perception": "model.perception.window",
    "query": "model.query.answer",
    "snapshot": "model.vision.snapshot",
    "token_mint": "live.token.mint",
    "tool_propose": "skill.propose_observation",
    "tool_query": "skill.query_lab_log",
}


def _pct(xs: list[float], p: float) -> Optional[float]:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))], 1)


def _ratio(a: float, b: float) -> Optional[float]:
    return round(a / b, 4) if b else None


def compute(db: Any, since: str = "", experiment_id: Optional[str] = None) -> dict[str, Any]:
    m: dict[str, Any] = {}
    exp_sql, exp_p = (" AND e.experiment_id = ?", [experiment_id]) if experiment_id else ("", [])

    # ---- integrity: every persisted event must sit inside its session's active window ----
    rows = db.execute(
        "SELECT e.id, e.event_type, e.timestamp, s.started_at, s.stopped_at, s.id AS sid "
        "FROM observation_events e LEFT JOIN recording_sessions s ON s.id = e.session_id "
        f"WHERE e.timestamp >= ?{exp_sql}", [since, *exp_p])
    violations = unsessioned = 0
    for r in rows:
        if r["event_type"] == "correction":
            continue  # corrections are explicit reviewer actions, allowed after a session ends
        if r["sid"] is None:
            unsessioned += 1
        elif r["timestamp"] < r["started_at"] or (r["stopped_at"] and r["timestamp"] > r["stopped_at"]):
            violations += 1
    m["integrity.events_checked"] = len(rows)
    m["integrity.gate_violations"] = violations
    m["integrity.unsessioned_writes"] = unsessioned

    spans = db.execute("SELECT name, status, latency_ms, input_tokens, output_tokens, metadata_json, start_time "
                       "FROM telemetry_spans WHERE start_time >= ?", (since,))
    for s in spans:
        s["meta"] = json.loads(s.get("metadata_json") or "{}")

    def named(n: str) -> list[dict]:
        return [s for s in spans if s["name"] == n]

    # ---- notes ----
    props = named("skill.propose_observation")
    inactive = [s for s in props if s["meta"].get("outcome") == "recording_inactive"]
    attempts = [s for s in props if s not in inactive]
    m["notes.attempts"] = len(attempts)
    m["notes.save_success_rate"] = _ratio(sum(1 for s in attempts if s["meta"].get("saved")), len(attempts))
    m["notes.attempts_while_inactive"] = len(inactive)

    # ---- grounding of the log agent ----
    qs = named("model.query.answer")
    cited = sum(s["meta"].get("cited", 0) or 0 for s in qs)
    m["grounding.queries"] = len(qs)
    m["grounding.hallucinated_id_rate"] = _ratio(sum(s["meta"].get("cited_hallucinated", 0) or 0 for s in qs), cited)
    m["grounding.answers_with_evidence"] = _ratio(sum(1 for s in qs if (s["meta"].get("cited_valid") or 0) > 0), len(qs))

    # ---- perception ----
    win = named("model.perception.window")
    persist = named("perception.persist")
    m["perception.windows"] = len(win)
    m["perception.persist_rate"] = _ratio(sum(1 for s in persist if s["meta"].get("outcome") == "saved"), len(persist))
    m["perception.actions_per_window"] = (round(sum(s["meta"].get("actions", 0) or 0 for s in persist) / len(persist), 3)
                                          if persist else None)

    # ---- latency + reliability per stage ----
    for key, name in STAGES.items():
        ss = named(name)
        m[f"latency.{key}.n"] = len(ss)
        m[f"latency.{key}.p50_ms"] = _pct([s["latency_ms"] for s in ss], 0.5)
        m[f"latency.{key}.p95_ms"] = _pct([s["latency_ms"] for s in ss], 0.95)
        m[f"reliability.{key}.error_rate"] = _ratio(sum(1 for s in ss if s["status"] != "ok"), len(ss))
    api = [s for s in spans if s["name"].startswith("api.")]
    m["reliability.api.5xx_rate"] = _ratio(sum(1 for s in api if (s["meta"].get("status_code") or 0) >= 500), len(api))

    # ---- cost proxy ----
    recs = db.execute("SELECT started_at, stopped_at, last_heartbeat_at FROM recording_sessions WHERE started_at >= ?",
                      (since,))
    minutes = 0.0
    for r in recs:
        end = r["stopped_at"] or r["last_heartbeat_at"]
        minutes += max(0.0, (datetime.fromisoformat(end) - datetime.fromisoformat(r["started_at"])).total_seconds() / 60)
    toks = sum((s["input_tokens"] or 0) + (s["output_tokens"] or 0) for s in spans if s["name"].startswith("model."))
    m["cost.recorded_minutes"] = round(minutes, 2)
    m["cost.model_tokens"] = toks
    m["cost.tokens_per_live_minute"] = round(toks / minutes, 1) if minutes > 0.05 else None
    return m


def count_accuracy(results: list[dict]) -> dict[str, Any]:
    """results: [{"expected": int, "predicted": int|None}] for a labelled action (e.g. 'dispense drop')."""
    pairs = [(r["expected"], r["predicted"]) for r in results if r.get("predicted") is not None]
    if not results:
        return {}
    errs = [abs(e - p) for e, p in pairs]
    return {
        "counting.clips": len(results),
        "counting.answered_rate": _ratio(len(pairs), len(results)),
        "counting.mae": round(sum(errs) / len(errs), 3) if errs else None,
        "counting.exact_match": _ratio(sum(1 for x in errs if x == 0), len(results)),
        "counting.within_1": _ratio(sum(1 for x in errs if x <= 1), len(results)),
        "counting.signed_bias": round(sum(p - e for e, p in pairs) / len(pairs), 3) if pairs else None,
    }
