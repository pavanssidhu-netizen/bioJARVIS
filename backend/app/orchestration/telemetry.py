"""Content-free telemetry spans.

Every model call, skill execution and API stage records a span into the `telemetry_spans` table in the SAME
database the app uses (local SQLite or Turso). The deployed Vercel backend cannot reach a Langfuse running on
a developer's loopback, so `scripts/langfuse_sync.py` later exports these rows to Langfuse.

Privacy: spans hold timings, sizes, counts, model / prompt / steering versions and outcome codes ONLY - never
transcripts, prompts, images or answers. That's enforced here by allowing only scalar metadata values.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

log = logging.getLogger("labmate.telemetry")

# Per-request trace id and client session id (set by the API middleware).
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
session_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("client_session", default="")
parent_var: contextvars.ContextVar[str] = contextvars.ContextVar("parent_span", default="")

_MAX_META = 40


def enabled() -> bool:
    return os.getenv("TELEMETRY_ENABLED", "true").lower() != "false"


def new_trace_id() -> str:
    return uuid.uuid4().hex  # 32 hex chars: valid W3C / Langfuse trace id


def _scrub(meta: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in list(meta.items())[:_MAX_META]:
        if v is None or isinstance(v, (bool, int, float)):
            out[k] = v
        elif isinstance(v, str):
            out[k] = v[:120]  # codes / ids / names only; callers never pass free text
        elif isinstance(v, (list, tuple)) and all(isinstance(x, (str, int, float, bool)) for x in v):
            out[k] = [x[:60] if isinstance(x, str) else x for x in v][:20]
    return out


class Span:
    def __init__(self, name: str, kind: str, model: Optional[str], prompt: Optional[str], meta: dict[str, Any]):
        self.id = uuid.uuid4().hex[:16]
        self.name, self.kind, self.model, self.prompt = name, kind, model, prompt
        self.meta = dict(meta)
        self.status = "ok"
        self.error: Optional[str] = None
        self.usage: dict[str, int] = {}

    def set(self, **kw: Any) -> None:
        self.meta.update(kw)

    def fail(self, code: str) -> None:
        self.status, self.error = "error", code[:120]

    def record_usage(self, resp: Any) -> None:
        """Pull token counts off a google-genai response if present."""
        u = getattr(resp, "usage_metadata", None)
        if u is None:
            return
        for src, dst in (("prompt_token_count", "input"), ("candidates_token_count", "output"),
                         ("total_token_count", "total")):
            v = getattr(u, src, None)
            if isinstance(v, int):
                self.usage[dst] = v


@contextmanager
def span(name: str, kind: str = "span", *, model: Optional[str] = None, prompt: Optional[str] = None,
         db: Any = None, **meta: Any) -> Iterator[Span]:
    """kind: span | generation | tool | chain | retriever | evaluator | guardrail (Langfuse observation types)."""
    s = Span(name, kind, model, prompt, meta)
    token = parent_var.set(s.id)
    t0 = time.perf_counter()
    start = datetime.now(timezone.utc)
    try:
        yield s
    except Exception as e:  # noqa: BLE001
        if s.status == "ok":
            s.fail(type(e).__name__)
        raise
    finally:
        parent_var.reset(token)
        if enabled():
            _write(db, s, start, (time.perf_counter() - t0) * 1000)


def _write(db: Any, s: Span, start: datetime, ms: float) -> None:
    try:
        if db is None:
            from ..db import get_db
            db = get_db()
        db.execute(
            "INSERT INTO telemetry_spans (id, trace_id, parent_id, client_session, name, kind, model, prompt_ref, "
            "status, error_code, start_time, latency_ms, input_tokens, output_tokens, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (s.id, trace_id_var.get() or new_trace_id(), parent_var.get() or None, session_id_var.get() or None,
             s.name, s.kind, s.model, s.prompt, s.status, s.error, start.isoformat(timespec="milliseconds"),
             round(ms, 1), s.usage.get("input"), s.usage.get("output"),
             json.dumps(_scrub(s.meta), separators=(",", ":"))),
        )
    except Exception:  # noqa: BLE001 - telemetry must never break the request path
        log.debug("telemetry write failed", exc_info=True)
