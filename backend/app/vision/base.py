"""Vision provider interface. Swap implementations via VISION_PROVIDER=gemini|specialist|modal, or chain a
specialist AFTER Gemini with SPECIALIST_PROVIDER=local|modal.

The frontend only ever sees VisionAnalysis (description + structured dict), so a teammate can plug in a
PyTorch/YOLO/OpenCV detector by implementing `analyse_image` / `analyse_frames` - no frontend changes needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ImageInput:
    data: bytes
    mime_type: str
    sha256: str


@dataclass
class VisionTask:
    question: str = "Describe what is visible."
    kind: str = "describe"  # describe | detect | count | read_text
    protocol_hint: str = ""  # compact protocol context composed by the orchestration layer


@dataclass
class VisionAnalysis:
    provider: str
    model: str
    description: str
    structured: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=dict)  # token counts if the provider reports them
    prompt_ref: str = ""


class VisionNotConfigured(Exception):
    """Raised by providers that are wired up as extension points but have no real model yet."""


class VisionProvider(Protocol):
    name: str

    async def analyse_image(self, image: ImageInput, task: VisionTask) -> VisionAnalysis: ...

    async def analyse_frames(self, frames: list[ImageInput], interval_s: float, hint: str | None,
                             protocol_hint: str = "") -> VisionAnalysis:
        """Temporal analysis of consecutive frames -> structured dict matching contracts.PerceptionPayload
        (scene_summary, objects[], actions[], limitations[])."""
        ...

    def status(self) -> dict[str, Any]: ...
