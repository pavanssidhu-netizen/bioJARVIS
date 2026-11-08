"""Mint short-lived, config-locked Gemini Live tokens. The long-lived API key never leaves the server.

The token is locked to our model, composed system instruction (core prompt + steering + protocol), tools and
transcription settings, so a client holding it cannot repurpose it for a different model or prompt.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from google import genai

from ..config import get_settings
from ..contracts import LiveTokenResponse
from ..orchestration import skills, telemetry
from ..orchestration.models import model_for
from ..orchestration.prompts import LIVE_CORE
from ..orchestration.steering import compose
from ..services.store import Store

WS_URL = ("wss://generativelanguage.googleapis.com/ws/"
          "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained")


def system_instruction(store: Optional[Store] = None, experiment_id: Optional[str] = None) -> tuple[str, str]:
    steering, steer_hash = compose("live")
    parts = [LIVE_CORE.text, "# Operating rules and steering\n" + steering]
    if store and experiment_id:
        try:
            p = store.get_protocol(experiment_id)
            if p:
                steps = "\n".join(f"- {s.id}: {s.description}" for s in p.content.steps)
                parts.append(f"# Approved protocol v{p.version}: {p.content.title}\n{steps}\n"
                             "Use get_protocol for full details (quantities, tolerances).")
        except Exception:  # noqa: BLE001
            pass
    return "\n\n".join(parts), f"{LIVE_CORE.ref}+steer:{steer_hash}"


def live_config(store: Optional[Store] = None, experiment_id: Optional[str] = None) -> tuple[dict, str]:
    text, ref = system_instruction(store, experiment_id)
    return {
        "response_modalities": ["AUDIO"],
        "system_instruction": text,
        "tools": [{"function_declarations": skills.live_declarations()}],
        "input_audio_transcription": {},
        "output_audio_transcription": {},
        "session_resumption": {},
    }, ref


def mint_live_token(store: Optional[Store] = None, experiment_id: Optional[str] = None) -> LiveTokenResponse:
    s = get_settings()
    model = model_for("live")
    cfg, ref = live_config(store, experiment_id)
    with telemetry.span("live.token.mint", "span", db=store.db if store else None, model=model, prompt=ref,
                        tools=len(cfg["tools"][0]["function_declarations"])):
        client = genai.Client(api_key=s.gemini_api_key, http_options={"api_version": "v1beta"})
        now = datetime.now(timezone.utc)
        expire, new_session = now + timedelta(minutes=30), now + timedelta(minutes=1)
        token = client.auth_tokens.create(config={
            "uses": 1,
            "expire_time": expire,
            "new_session_expire_time": new_session,
            "live_connect_constraints": {"model": model, "config": cfg},
            "http_options": {"api_version": "v1beta"},
        })
    return LiveTokenResponse(token=token.name, model=model, websocket_url=WS_URL,
                             expires_at=expire.isoformat(), new_session_expires_at=new_session.isoformat())
