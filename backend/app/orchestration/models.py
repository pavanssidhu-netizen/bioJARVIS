"""Model router: every model call names a ROLE; the role -> model mapping lives here (env-overridable).

Roles
  live        Gemini Live voice session (browser <-> Gemini, token minted by us)
  vision      single-snapshot interpretation
  perception  multi-frame live-feed analysis (objects / actions / counts)
  query       read-only log analyst behind the query_lab_log skill
  specialist  teammate sub-model (local PyTorch or Modal) - optional, chained after perception/vision

Changing a model for a role is an env change, not a code change, and every telemetry span records the
resolved model so evaluations stay attributable.
"""
from __future__ import annotations

import os
from typing import Literal

from ..config import get_settings

Role = Literal["live", "vision", "perception", "query", "specialist"]


def model_for(role: Role) -> str:
    s = get_settings()
    return {
        "live": s.live_model,
        "vision": s.vision_model,
        "perception": os.getenv("GEMINI_PERCEPTION_MODEL") or s.vision_model,
        "query": os.getenv("GEMINI_QUERY_MODEL") or s.vision_model,
        "specialist": os.getenv("SPECIALIST_MODEL_NAME", "specialist-vision-v1"),
    }[role]


def specialist_provider() -> str:
    """Which specialist sub-model (if any) is chained after Gemini: none | local | modal."""
    v = os.getenv("SPECIALIST_PROVIDER", "none").lower()
    return v if v in ("none", "local", "modal") else "none"


def routing_table() -> dict[str, str]:
    return {r: model_for(r) for r in ("live", "vision", "perception", "query", "specialist")} | {
        "specialist_provider": specialist_provider()}
