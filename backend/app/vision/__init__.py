from __future__ import annotations

import base64
import binascii
import hashlib

from ..config import get_settings
from .base import ImageInput, VisionAnalysis, VisionNotConfigured, VisionProvider, VisionTask
from .gemini import GeminiVisionProvider
from .specialist import ModalVisionProvider, SpecialistVisionProvider

_PROVIDERS = {"gemini": GeminiVisionProvider, "specialist": SpecialistVisionProvider, "modal": ModalVisionProvider}


def get_vision_provider(name: str | None = None) -> VisionProvider:
    key = (name or get_settings().vision_provider).lower()
    return _PROVIDERS.get(key, GeminiVisionProvider)()


def get_specialist_provider() -> VisionProvider | None:
    """Specialist sub-model chained AFTER the primary provider (SPECIALIST_PROVIDER=none|local|modal)."""
    from ..orchestration.models import specialist_provider
    p = specialist_provider()
    return None if p == "none" else (SpecialistVisionProvider() if p == "local" else ModalVisionProvider())


def decode_image(image_base64: str, max_bytes: int) -> ImageInput:
    """Validate an uploaded image by size and magic bytes (never trust a client-declared MIME type)."""
    if "," in image_base64[:100] and image_base64.startswith("data:"):
        image_base64 = image_base64.split(",", 1)[1]
    if len(image_base64) > max_bytes * 4 // 3 + 16:
        raise ValueError("image_too_large")
    try:
        data = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError("invalid_base64") from e
    if len(data) > max_bytes:
        raise ValueError("image_too_large")
    if data[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise ValueError("unsupported_image_type")
    return ImageInput(data=data, mime_type=mime, sha256=hashlib.sha256(data).hexdigest())


__all__ = ["ImageInput", "VisionAnalysis", "VisionNotConfigured", "VisionProvider", "VisionTask",
           "get_vision_provider", "get_specialist_provider", "decode_image"]
