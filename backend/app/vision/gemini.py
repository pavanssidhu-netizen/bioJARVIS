"""Native Gemini image interpretation with JSON response schemas. Prompts come from the versioned registry."""
from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types

from ..config import get_settings
from ..orchestration.models import model_for
from ..orchestration.prompts import PERCEPTION_WINDOW, VISION_SNAPSHOT
from .base import ImageInput, VisionAnalysis, VisionNotConfigured, VisionTask

_CERT = {"type": "string", "enum": ["certain", "likely", "uncertain"]}

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "Natural-language answer to the researcher's question."},
        "observation_type": {"type": "string", "enum": ["visual_description", "equipment_identification",
                                                        "text_reading", "object_count", "other"]},
        "description": {"type": "string", "description": "One-sentence factual description of the scene."},
        "objects": {"type": "array", "items": {"type": "object", "properties": {
            "label": {"type": "string"},
            "count": {"type": "integer", "description": "Only if objects are clearly separable; else omit."},
            "certainty": _CERT}, "required": ["label", "certainty"]}},
        "visible_text": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"},
                        "description": "What cannot be determined reliably from this image."},
    },
    "required": ["answer", "observation_type", "description", "objects", "limitations"],
}

PERCEPTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scene_summary": {"type": "string", "description": "One sentence: what is happening across the window."},
        "objects": {"type": "array", "items": {"type": "object", "properties": {
            "label": {"type": "string"}, "count": {"type": "integer"}, "certainty": _CERT,
            "box_2d": {"type": "array", "items": {"type": "integer"},
                       "description": "[ymin, xmin, ymax, xmax] normalised 0-1000 in the LAST frame"}},
            "required": ["label", "certainty"]}},
        "actions": {"type": "array", "items": {"type": "object", "properties": {
            "action": {"type": "string", "description": "short verb phrase, e.g. 'dispense drop', 'pipette liquid'"},
            "object": {"type": "string"},
            "count": {"type": "integer", "description": "number of distinct occurrences in this window"},
            "certainty": _CERT,
            "first_frame": {"type": "integer"},
            "protocol_step": {"type": "string", "description": "matching protocol step id, if any"}},
            "required": ["action", "count", "certainty"]}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["scene_summary", "objects", "actions", "limitations"],
}


def _usage(resp: Any) -> dict[str, int]:
    u = getattr(resp, "usage_metadata", None)
    out = {}
    for src, dst in (("prompt_token_count", "input"), ("candidates_token_count", "output")):
        v = getattr(u, src, None) if u is not None else None
        if isinstance(v, int):
            out[dst] = v
    return out


async def _generate(client: genai.Client, **kw: Any) -> Any:
    """Hold the client for the whole call, then close it. (With aiohttp installed, google-genai's async session
    is closed if the Client is garbage-collected mid-request - an inline `genai.Client(...).aio...` breaks.)"""
    try:
        return await client.aio.models.generate_content(**kw)
    finally:
        await client.aio.aclose()


class GeminiVisionProvider:
    name = "gemini"

    def __init__(self) -> None:
        self.settings = get_settings()

    def status(self) -> dict[str, Any]:
        return {"provider": self.name, "configured": bool(self.settings.gemini_api_key),
                "model": model_for("vision"), "perception_model": model_for("perception")}

    def _client(self) -> genai.Client:
        if not self.settings.gemini_api_key:
            raise VisionNotConfigured("GEMINI_API_KEY is not set")
        return genai.Client(api_key=self.settings.gemini_api_key)

    async def analyse_image(self, image: ImageInput, task: VisionTask) -> VisionAnalysis:
        model = model_for("vision")
        resp = await _generate(self._client(), model=model,
            contents=[types.Part.from_bytes(data=image.data, mime_type=image.mime_type),
                      VISION_SNAPSHOT.render(question=task.question, protocol_hint=task.protocol_hint)],
            config=types.GenerateContentConfig(response_mime_type="application/json",
                                               response_json_schema=RESPONSE_SCHEMA))
        structured = json.loads(resp.text or "{}")
        return VisionAnalysis(provider=self.name, model=model,
                              description=structured.get("answer") or structured.get("description", ""),
                              structured=structured, usage=_usage(resp), prompt_ref=VISION_SNAPSHOT.ref)

    async def analyse_frames(self, frames: list[ImageInput], interval_s: float, hint: str | None,
                             protocol_hint: str = "") -> VisionAnalysis:
        model = model_for("perception")
        contents: list[Any] = []
        for i, f in enumerate(frames):
            contents.append(f"Frame {i} (t={i * interval_s:.1f}s):")
            contents.append(types.Part.from_bytes(data=f.data, mime_type=f.mime_type))
        contents.append(PERCEPTION_WINDOW.render(n=len(frames), span=(len(frames) - 1) * interval_s,
                                                 hint=hint or "none", protocol_hint=protocol_hint))
        resp = await _generate(self._client(), model=model, contents=contents,
            config=types.GenerateContentConfig(response_mime_type="application/json",
                                               response_json_schema=PERCEPTION_SCHEMA))
        structured = json.loads(resp.text or "{}")
        for k in ("objects", "actions", "limitations"):
            structured.setdefault(k, [])
        return VisionAnalysis(provider=self.name, model=model, description=structured.get("scene_summary", ""),
                              structured=structured, usage=_usage(resp), prompt_ref=PERCEPTION_WINDOW.ref)
