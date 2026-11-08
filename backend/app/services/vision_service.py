"""Model-to-model vision orchestration: primary provider (Gemini) -> optional specialist sub-model.

Every model call is a telemetry generation span (model, prompt ref, steering hash, tokens, latency, outcome).
A specialist failure never fails the request: the primary result is returned with `specialist.error`.
"""
from __future__ import annotations

from typing import Any, Optional

from ..config import get_settings
from ..orchestration import telemetry
from ..orchestration.steering import compose
from ..vision import (ImageInput, VisionAnalysis, VisionNotConfigured, VisionTask, decode_image,
                      get_specialist_provider, get_vision_provider)
from .store import Store


def protocol_hint(store: Store, experiment_id: Optional[str], max_steps: int = 12) -> str:
    """Compact protocol context for vision prompts (step ids + actions + quantities)."""
    if not experiment_id:
        return ""
    try:
        p = store.get_protocol(experiment_id)
    except Exception:  # noqa: BLE001
        return ""
    if not p:
        return ""
    steps = "; ".join(f"{s.id}={s.action}" + (f" {s.quantity:g} {s.unit}" if s.quantity is not None and s.unit else "")
                      for s in p.content.steps[:max_steps])
    return f"Approved protocol '{p.content.title}' steps: {steps}.\n"


async def _primary_image(store: Store, img: ImageInput, task: VisionTask) -> VisionAnalysis:
    provider = get_vision_provider()
    _, steer = compose("vision")
    with telemetry.span("model.vision.snapshot", "generation", db=store.db, provider=provider.name,
                        image_bytes=len(img.data)) as sp:
        r = await provider.analyse_image(img, task)
        sp.model, sp.prompt = r.model, f"{r.prompt_ref}+steer:{steer}"
        sp.usage.update(r.usage)
        sp.set(objects=len(r.structured.get("objects", []) or []))
        return r


async def run_specialist(store: Store, kind: str, *, image: ImageInput | None = None,
                         frames: list[ImageInput] | None = None, interval_s: float = 1.0,
                         question: str = "", experiment_id: Optional[str] = None,
                         step_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    sp_provider = get_specialist_provider()
    if sp_provider is None:
        return None
    kw: dict[str, Any] = {}
    if experiment_id:
        from ..science.service import get_context
        try:
            kw = {"experiment_id": experiment_id, "step_id": step_id or "step_05",
                  "experiment_context": get_context(store, experiment_id)}
        except Exception:  # noqa: BLE001
            kw = {}
    with telemetry.span(f"model.specialist.{kind}", "generation", db=store.db, provider=sp_provider.name) as sp:
        try:
            r = (await sp_provider.analyse_image(image, VisionTask(question=question), **kw) if kind == "image"
                 else await sp_provider.analyse_frames(frames or [], interval_s, None, **kw))
            sp.model = r.model
            sp.set(count=r.structured.get("count"), detections=len(r.structured.get("detections", []) or []),
                   abstained=bool(r.structured.get("abstained")))
            return {"provider": r.provider, **r.structured}
        except VisionNotConfigured as e:
            sp.fail("not_configured")
            return {"provider": sp_provider.name, "error": "not_configured", "message": str(e)[:200]}
        except Exception as e:  # noqa: BLE001
            sp.fail(type(e).__name__)
            return {"provider": sp_provider.name, "error": type(e).__name__, "message": str(e)[:200]}


async def analyse_snapshot(store: Store, image_base64: str, question: str,
                           experiment_id: Optional[str] = None) -> VisionAnalysis:
    img = decode_image(image_base64, get_settings().max_image_bytes)
    r = await _primary_image(store, img, VisionTask(question=question, protocol_hint=protocol_hint(store, experiment_id)))
    spec = await run_specialist(store, "image", image=img, question=question, experiment_id=experiment_id)
    if spec is not None:
        r.structured = {**r.structured, "specialist": spec}
    return r
