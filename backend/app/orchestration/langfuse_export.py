"""Export content-free telemetry spans (and eval scores) to a Langfuse server via its public ingestion API.

Why an exporter instead of the SDK in the request path: the deployed backend (Vercel) cannot reach a Langfuse
bound to a developer box's loopback, and request latency should not depend on observability. Spans are written
to the app DB; this exporter runs where Langfuse is reachable (scripts/langfuse_sync.py, or a Modal cron later).

Mapping:  trace_id -> Langfuse trace (sessionId = client_session)
          span kind=generation -> generation (model, usage, version=prompt_ref)
          other kinds -> span (metadata.kind = tool|guardrail|chain|span)
          status=error -> level ERROR + statusMessage=error_code
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

import httpx


class LangfuseConfig:
    def __init__(self) -> None:
        self.host = os.getenv("LANGFUSE_HOST", "http://127.0.0.1:3000").rstrip("/")
        self.public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        self.secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
        self.environment = os.getenv("LANGFUSE_ENVIRONMENT", "dev")

    @property
    def configured(self) -> bool:
        return bool(self.public_key and self.secret_key)


def _iso_end(start: str, ms: float) -> str:
    return (datetime.fromisoformat(start) + timedelta(milliseconds=ms)).isoformat(timespec="milliseconds")


def _ev(kind: str, body: dict, ts: str) -> dict:
    return {"id": uuid.uuid4().hex, "timestamp": ts, "type": kind, "body": body}


def spans_to_events(rows: Iterable[dict], environment: str = "dev") -> list[dict]:
    rows = list(rows)
    events: list[dict] = []
    seen_traces: set[str] = set()
    by_trace: dict[str, list[dict]] = {}
    for r in rows:
        by_trace.setdefault(r["trace_id"], []).append(r)
    for tid, spans in by_trace.items():
        root = next((s for s in spans if not s.get("parent_id")), spans[0])
        if tid not in seen_traces:
            seen_traces.add(tid)
            events.append(_ev("trace-create", {
                "id": tid, "name": root["name"], "sessionId": root.get("client_session") or None,
                "timestamp": root["start_time"], "environment": environment,
                "tags": sorted({s["name"].split(".")[0] for s in spans}),
                "metadata": {"spans": len(spans)}}, root["start_time"]))
        for s in spans:
            meta = json.loads(s.get("metadata_json") or "{}")
            meta["kind"] = s["kind"]
            body: dict[str, Any] = {
                "id": s["id"], "traceId": tid, "parentObservationId": s.get("parent_id") or None,
                "name": s["name"], "startTime": s["start_time"], "endTime": _iso_end(s["start_time"], s["latency_ms"]),
                "metadata": meta, "level": "ERROR" if s["status"] != "ok" else "DEFAULT",
                "statusMessage": s.get("error_code"), "environment": environment,
            }
            if s["kind"] == "generation":
                body.update({"model": s.get("model"), "version": s.get("prompt_ref"),
                             "usageDetails": {k: v for k, v in (("input", s.get("input_tokens")),
                                                                ("output", s.get("output_tokens"))) if v is not None}})
                events.append(_ev("generation-create", body, s["start_time"]))
            else:
                if s.get("model"):
                    meta["model"] = s["model"]
                if s.get("prompt_ref"):
                    body["version"] = s["prompt_ref"]
                events.append(_ev("span-create", body, s["start_time"]))
    return events


def score_event(name: str, value: float | str, *, trace_id: Optional[str] = None, session_id: Optional[str] = None,
                comment: Optional[str] = None, data_type: str = "NUMERIC", metadata: Optional[dict] = None,
                environment: str = "dev") -> dict:
    ts = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
    body = {"id": uuid.uuid4().hex, "name": name, "value": value, "dataType": data_type, "traceId": trace_id,
            "sessionId": session_id, "comment": comment, "metadata": metadata or {}, "environment": environment}
    return _ev("score-create", {k: v for k, v in body.items() if v is not None}, ts)


def send(events: list[dict], cfg: Optional[LangfuseConfig] = None, client: Optional[httpx.Client] = None,
         batch_size: int = 100) -> dict[str, int]:
    cfg = cfg or LangfuseConfig()
    if not cfg.configured:
        raise RuntimeError("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set")
    c = client or httpx.Client(timeout=20)
    ok = err = 0
    for i in range(0, len(events), batch_size):
        r = c.post(f"{cfg.host}/api/public/ingestion", auth=(cfg.public_key, cfg.secret_key),
                   json={"batch": events[i:i + batch_size]})
        if r.status_code not in (200, 207):
            raise RuntimeError(f"Langfuse ingestion failed: HTTP {r.status_code} {r.text[:200]}")
        data = r.json()
        ok += len(data.get("successes", []))
        err += len(data.get("errors", []))
    return {"sent": ok, "errors": err}
