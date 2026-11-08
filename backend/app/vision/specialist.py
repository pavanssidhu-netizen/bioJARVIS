"""Specialist sub-model adapters (teammates' PyTorch / YOLO / OpenCV models).

Both adapters call the SAME teammate entrypoint contract, so a model can move between local and Modal
without code changes:

    # modal_app/specialist/model.py
    def predict(image_bytes: bytes, question: str = "") -> dict          # single image
    def predict_frames(frames: list[bytes], interval_s: float) -> dict   # optional, temporal

returning SPECIALIST_SCHEMA below. Until a real model is installed they report not-configured honestly.
"""
from __future__ import annotations

import asyncio
import importlib
import os
from typing import Any

from ..config import get_settings
from .base import ImageInput, VisionAnalysis, VisionNotConfigured, VisionTask

EXAMPLE_SPECIALIST_SCHEMA: dict[str, Any] = {
    "model": "specialist-vision-v1",
    "detections": [],          # [{"label": "drop", "confidence": 0.91, "bbox": [x0, y0, x1, y1], "frame": 0}]
    "count": 0,                # total of the target class
    "counts_by_label": {},     # {"drop": 3, "pipette_tip": 1}
    "coordinate_system": "pixels",
    "image_width": 1280,
    "image_height": 720,
    "review_required": False,  # True when confidence is low / model is a placeholder
}


def _to_analysis(provider: str, result: dict[str, Any]) -> VisionAnalysis:
    if not isinstance(result, dict) or "detections" not in result:
        raise ValueError("specialist result does not match SPECIALIST_SCHEMA (missing 'detections')")
    if result.get("not_configured"):
        raise VisionNotConfigured(result.get("reason", "specialist model not installed"))
    desc = result.get("description") or ", ".join(f"{k} x{v}" for k, v in (result.get("counts_by_label") or {}).items()) \
        or f"{result.get('count', 0)} detections"
    return VisionAnalysis(provider=provider, model=str(result.get("model", "specialist")), description=desc,
                          structured=result)


class SpecialistVisionProvider:
    """Runs the teammate model IN-PROCESS (CPU). Module path via SPECIALIST_MODULE (default modal_app.specialist.model)."""
    name = "specialist"

    def __init__(self) -> None:
        self.module_name = os.getenv("SPECIALIST_MODULE", "modal_app.specialist.model")

    def _module(self):
        try:
            return importlib.import_module(self.module_name)
        except ImportError as e:
            raise VisionNotConfigured(f"specialist module {self.module_name} not importable: {e}") from e

    def status(self) -> dict[str, Any]:
        try:
            m = self._module()
            configured = bool(getattr(m, "IS_REAL_MODEL", False))
            return {"provider": self.name, "configured": configured, "module": self.module_name,
                    "model": getattr(m, "MODEL_NAME", "unknown"),
                    "reason": None if configured else "placeholder model (IS_REAL_MODEL=False)",
                    "example_schema": EXAMPLE_SPECIALIST_SCHEMA}
        except VisionNotConfigured as e:
            return {"provider": self.name, "configured": False, "reason": str(e), "example_schema": EXAMPLE_SPECIALIST_SCHEMA}

    @staticmethod
    def _kw(fn, kw: dict) -> dict:
        import inspect
        params = inspect.signature(fn).parameters
        if any(p.kind == p.VAR_KEYWORD for p in params.values()):
            return kw
        return {k: v for k, v in kw.items() if k in params}

    async def analyse_image(self, image: ImageInput, task: VisionTask, **kw: Any) -> VisionAnalysis:
        m = self._module()
        return _to_analysis(self.name, await asyncio.to_thread(m.predict, image.data, task.question,
                                                               **self._kw(m.predict, kw)))

    async def analyse_frames(self, frames: list[ImageInput], interval_s: float, hint: str | None,
                             protocol_hint: str = "", **kw: Any) -> VisionAnalysis:
        m = self._module()
        fn = getattr(m, "predict_frames", None)
        if fn is None:
            raise VisionNotConfigured("specialist model has no predict_frames()")
        return _to_analysis(self.name, await asyncio.to_thread(fn, [f.data for f in frames], interval_s,
                                                               **self._kw(fn, kw)))


class ModalVisionProvider:
    """Calls the deployed Modal app (modal_app/specialist_app.py). Never deploys anything itself.
    Auth: MODAL_TOKEN_ID / MODAL_TOKEN_SECRET env (Vercel) or ~/.modal.toml (local)."""
    name = "modal"

    def __init__(self) -> None:
        self.settings = get_settings()

    def status(self) -> dict[str, Any]:
        return {"provider": self.name, "configured": self.settings.modal_enabled,
                "app": self.settings.modal_app, "function": self.settings.modal_function}

    def _fn(self, name: str):
        if not self.settings.modal_enabled:
            raise VisionNotConfigured("MODAL_ENABLED=false")
        # Empty MODAL_TOKEN_* (e.g. blank lines in .env) would override ~/.modal.toml and break auth.
        for k in ("MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"):
            if os.environ.get(k) == "":
                os.environ.pop(k)
        try:
            import modal  # optional dependency
        except ImportError as e:
            raise VisionNotConfigured("modal package not installed") from e
        return modal.Function.from_name(self.settings.modal_app, name)

    async def analyse_image(self, image: ImageInput, task: VisionTask, **kw: Any) -> VisionAnalysis:
        result = await self._fn(self.settings.modal_function).remote.aio(image.data, task.question, **kw)
        return _to_analysis(self.name, result)

    async def analyse_frames(self, frames: list[ImageInput], interval_s: float, hint: str | None,
                             protocol_hint: str = "", **kw: Any) -> VisionAnalysis:
        result = await self._fn(self.settings.modal_function + "_frames").remote.aio(
            [f.data for f in frames], interval_s, **kw)
        return _to_analysis(self.name, result)
