"""Scientific state engine: experiment context, deterministic reconciliation, dependency impact, investigation.

The LLM never decides whether an observation violates the protocol: `backend.agents.steering.reconcile_observation`
(Person 4) does, against the versioned experiment context (Person 2's seed). Its decision is persisted as an
immutable `reconciliation` event linked to the source observation, and handed back to Gemini to speak.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from ..orchestration import telemetry
from ..services.store import ApiError, Store, now_iso

ROOT = Path(__file__).resolve().parents[3]
SEED_PATH = ROOT / "science" / "experiment_seed.json"
DEFAULT_EXPERIMENT = "exp_001"

# Field names the reconciliation engine understands (from the seed's constraints).
MEASUREMENT_TYPES = ["bubble_count", "channel_fill_complete", "incubation_duration_min", "wash_duration_min",
                     "temperature_c", "volume_ul", "flow_rate_ul_min", "duplicate_cv_percent", "note"]


# ------------------------------------------------------------------------------------------- context
def load_seed() -> Optional[dict]:
    try:
        return json.loads(SEED_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None


def seed_database(db: Any) -> None:
    """Idempotently register the seed experiment, its context v1, and a protocol view for the UI."""
    seed = load_seed()
    if not seed:
        return
    exp_id = seed.get("experiment_id", DEFAULT_EXPERIMENT)
    name = (seed.get("experiment") or {}).get("name", exp_id)
    db.execute("INSERT OR IGNORE INTO experiments (id, name, created_at, status) VALUES (?, ?, ?, 'active')",
               (exp_id, name, "2026-11-08T00:00:00+00:00"))
    db.execute("INSERT OR IGNORE INTO experiment_contexts (experiment_id, version, context_json, source, created_at) "
               "VALUES (?, 1, ?, 'science/experiment_seed.json', ?)", (exp_id, json.dumps(seed), now_iso()))
    db.execute(
        "INSERT INTO protocol_documents (id, experiment_id, version, content_json, created_at) "
        "SELECT ?, ?, 1, ?, ? WHERE NOT EXISTS (SELECT 1 FROM protocol_documents WHERE experiment_id=?)",
        (f"prot-{exp_id}-v1", exp_id, json.dumps(protocol_view(seed)), now_iso(), exp_id))


def protocol_view(seed: dict) -> dict:
    """Seed steps -> the generic ProtocolContent shape the app's protocol panel renders."""
    cons = seed.get("constraints", [])
    steps = []
    for s in sorted(seed.get("steps", []), key=lambda x: x.get("order", 0)):
        sid = s["step_id"]
        rules = [c for c in cons if sid in (c.get("applies_to_step_ids") or [c.get("step_id")])]
        tol = "; ".join(c["rule"] for c in rules)[:300] or None
        desc = s["name"] + (f" - {s['reagent']}" if s.get("reagent") else "") + \
            (f" ({s['reagent_concentration']})" if s.get("reagent_concentration") else "") + \
            (f", {s['duration_min']} min" if s.get("duration_min") else "") + \
            (f" @ {s['temperature_c']} °C" if s.get("temperature_c") is not None else "")
        steps.append({"id": sid, "action": s["name"], "description": desc, "reagent": s.get("reagent"),
                      "quantity": s.get("duration_min"), "unit": "min" if s.get("duration_min") else None,
                      "tolerance": tol, "expected_observation": s.get("note"),
                      "perception_actions": ["fill channel"] if s.get("is_fill_step") else []})
    exp = seed.get("experiment") or {}
    return {"title": exp.get("name", seed.get("protocol_id", "protocol")), "summary": exp.get("note"),
            "materials": [r.get("name", r.get("reagent_id")) for r in seed.get("reagents", [])],
            "safety": [], "steps": steps}


def get_context(store: Store, experiment_id: str) -> dict:
    rows = store.db.execute("SELECT context_json, version FROM experiment_contexts WHERE experiment_id=? "
                            "ORDER BY version DESC LIMIT 1", (experiment_id,))
    if not rows:
        store.get_experiment(experiment_id)
        return {"experiment_id": experiment_id, "steps": [], "constraints": [], "dependencies": [], "samples": [],
                "channel_map": {}, "context_version": 0}
    ctx = json.loads(rows[0]["context_json"])
    ctx["context_version"] = rows[0]["version"]
    return ctx


def put_context(store: Store, experiment_id: str, context: dict, source: str = "api") -> int:
    store.get_experiment(experiment_id)
    v = store.db.execute("SELECT COALESCE(MAX(version),0)+1 v FROM experiment_contexts WHERE experiment_id=?",
                         (experiment_id,))[0]["v"]
    store.db.execute("INSERT INTO experiment_contexts (experiment_id, version, context_json, source, created_at) "
                     "VALUES (?, ?, ?, ?, ?)", (experiment_id, v, json.dumps(context), source, now_iso()))
    store.put_protocol(experiment_id, __import__("backend.app.contracts", fromlist=["ProtocolContent"])
                       .ProtocolContent.model_validate(protocol_view(context)))
    return v


# ------------------------------------------------------------------------------------------- graph
def dependency_graph(store: Store, experiment_id: str, focus: Optional[str] = None,
                     step_id: Optional[str] = None) -> dict:
    ctx = get_context(store, experiment_id)
    nodes: dict[str, dict] = {}
    for s in ctx.get("steps", []):
        nodes[s["step_id"]] = {"id": s["step_id"], "type": "step", "label": s["name"]}
    for s in ctx.get("samples", []):
        nodes[s["sample_id"]] = {"id": s["sample_id"], "type": s.get("type", "sample"), "label": s["sample_id"],
                                 "channels": s.get("channels", [])}
    for ch, sample in (ctx.get("channel_map") or {}).items():
        nodes[ch] = {"id": ch, "type": "channel", "label": ch, "sample": sample}
    for d in ctx.get("derived_values", []):
        nodes[d["id"]] = {"id": d["id"], "type": "derived_value", "label": d["id"], "description": d.get("description")}
    edges = [{"id": d.get("dependency_id"), "from": d["from"], "to": d["to"], "type": d.get("dependency_type"),
              "reason": d.get("reason")} for d in ctx.get("dependencies", [])]
    edges += [{"id": f"map_{ch}", "from": ch, "to": s, "type": "channel_holds", "reason": "channel_map"}
              for ch, s in (ctx.get("channel_map") or {}).items()]
    affected: dict = {}
    if focus or step_id:
        from backend.agents.steering import trace_affected_dependencies
        flat, struct = trace_affected_dependencies(ctx, location_id=focus, step_id=step_id)
        affected = {"focus": focus, "step_id": step_id, "entities": flat, "structured": struct}
    return {"experiment_id": experiment_id, "nodes": list(nodes.values()), "edges": edges, "affected": affected,
            "note": "Impact-for-review graph: a path means 'may need review', not proven causation."}


# ------------------------------------------------------------------------------------------- reconciliation
def _decision_dict(d: Any) -> dict:
    out = asdict(d)
    for k in ("action", "scientific_status"):
        out[k] = getattr(getattr(d, k), "value", out[k])
    return out


def reconcile(store: Store, experiment_id: str, observation: dict, step_id: Optional[str] = None,
              prior_status: str = "recorded") -> dict:
    """Deterministic decision for one observation. observation keys: content, source_type, channel_id, well_id,
    measurement_type, measurement_value, measurement_unit, confidence, media_ref, supersedes_observation_id."""
    from backend.agents.steering import Observation, reconcile_observation
    ctx = get_context(store, experiment_id)
    sid = step_id or observation.get("step_id") or ctx.get("active_step_id") or "step_01"
    obs = Observation(
        id=str(observation.get("id") or "obs_preview"), step_id=sid,
        source_type=str(observation.get("source_type") or "voice"), content=str(observation.get("content") or ""),
        well_id=observation.get("well_id"), channel_id=observation.get("channel_id"),
        media_ref=observation.get("media_ref"), confidence=float(observation.get("confidence", 1.0) or 1.0),
        measurement_type=observation.get("measurement_type"), measurement_value=observation.get("measurement_value"),
        measurement_unit=observation.get("measurement_unit"),
        supersedes_observation_id=observation.get("supersedes_observation_id"))
    with telemetry.span("science.reconcile", "guardrail", db=store.db, step_id=sid,
                        measurement_type=obs.measurement_type, has_location=bool(obs.location_id)) as sp:
        d = _decision_dict(reconcile_observation(obs, ctx, prior_status))
        sp.set(action=d["action"], status=d["scientific_status"], violated=len(d["violated_constraints"]),
               affected=len(d["affected_entities"]), requires_human_approval=d["requires_human_approval"])
    d["step_id"] = sid
    d["context_version"] = ctx.get("context_version")
    return d


def reconcile_and_record(store: Store, event: Any, observation: dict, step_id: Optional[str]) -> dict:
    """Reconcile a persisted event and append the decision as a linked, immutable `reconciliation` event."""
    from ..contracts import EventIn
    d = reconcile(store, event.experiment_id, {**observation, "id": event.id}, step_id)
    rec_event, _ = store.ingest(EventIn(
        session_id=event.session_id, experiment_id=event.experiment_id, source_modality="system",
        event_type="reconciliation", payload=d, model_name="deterministic:backend.agents.steering",
        idempotency_key=f"recon-{event.id}", source_event_id=event.id))
    return {"event_id": rec_event.id, **{k: d[k] for k in ("action", "scientific_status", "requires_human_approval",
                                                         "violated_constraints", "affected_entities",
                                                         "affected_structured", "citations", "spoken_response",
                                                         "step_id")}}


def pending_reviews(store: Store, experiment_id: str) -> list[dict]:
    """Reconciliations requiring human approval whose source observation has no human review yet."""
    rows = store.db.execute(
        "SELECT r.id, r.source_event_id, r.payload_json, r.timestamp, r.sequence_number FROM observation_events r "
        "WHERE r.experiment_id=? AND r.event_type='reconciliation' AND NOT EXISTS "
        "(SELECT 1 FROM observation_reviews v WHERE v.observation_id = r.source_event_id) "
        "ORDER BY r.sequence_number DESC LIMIT 100", (experiment_id,))
    out = []
    for r in rows:
        p = json.loads(r["payload_json"])
        if p.get("requires_human_approval"):
            out.append({"reconciliation_event_id": r["id"], "observation_id": r["source_event_id"],
                        "timestamp": r["timestamp"], "sequence_number": r["sequence_number"], **p})
    return out


# ------------------------------------------------------------------------------------------- investigation
def investigate(store: Store, experiment_id: str, question: str, step_id: Optional[str] = None,
                measurement_type: Optional[str] = None, measurement_value: Any = None,
                observation_id: Optional[str] = None) -> dict:
    from backend.agents.investigate import run_argon_investigation
    ctx = get_context(store, experiment_id)
    priors = [{"id": e.id, "type": e.event_type, "payload": e.payload, "review_status": e.review_status}
              for e in store.list_events(experiment_id, after_seq=max(0, store.last_sequence(experiment_id) - 40))
              if e.event_type in ("observation_proposal", "reconciliation", "visual_observation")]
    with telemetry.span("science.investigate", "chain", db=store.db, step_id=step_id, priors=len(priors)) as sp:
        out = run_argon_investigation(
            observation_id=observation_id or "obs_inv", step_id=step_id or ctx.get("active_step_id") or "step_05",
            measurement_type=measurement_type or "note", measurement_value=measurement_value, question=question,
            experiment_context=ctx, prior_observations=priors)
        sp.set(keys=len(out))
    return json.loads(json.dumps(out, default=lambda o: getattr(o, "value", str(o))))


def require_context(store: Store, experiment_id: str) -> dict:
    ctx = get_context(store, experiment_id)
    if not ctx.get("steps"):
        raise ApiError(404, "no_scientific_context", f"No scientific context loaded for {experiment_id}")
    return ctx
