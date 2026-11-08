"""Modal app serving the teammate specialist sub-model.

Cost controls (credits are limited):
  - CPU by default; set MODAL_GPU=T4 (cheapest) only when the real model needs it
  - min_containers=0 (scale to zero), max_containers=1, scaledown_window=60 s, timeout=60 s
  - no schedules, no web endpoints (called only via the authenticated Modal SDK from our backend)

Deploy:  .venv/bin/modal deploy modal_app/specialist_app.py
Test:    .venv/bin/python scripts/modal_check.py      (one call; costs a fraction of a cent on CPU)
"""
from __future__ import annotations

import os
from pathlib import Path

import modal

APP_NAME = os.getenv("MODAL_VISION_APP", "labmate-vision")
HERE = Path(__file__).resolve().parent
GPU = os.getenv("MODAL_GPU") or None  # e.g. "T4"; None = CPU only

image = modal.Image.debian_slim(python_version="3.12")
_reqs = [ln.strip() for ln in (HERE / "specialist" / "requirements.txt").read_text().splitlines()
         if ln.strip() and not ln.startswith("#")]
if _reqs:
    image = image.pip_install(*_reqs)
image = image.add_local_dir(HERE / "specialist", remote_path="/root/specialist")

app = modal.App(APP_NAME)

_common = dict(image=image, gpu=GPU, cpu=1.0, memory=1024, min_containers=0, max_containers=1,
               scaledown_window=60, timeout=60)


@app.function(**_common)
def detect(image_bytes: bytes, question: str = "") -> dict:
    from specialist import model  # type: ignore
    return model.predict(image_bytes, question)


@app.function(**_common)
def detect_frames(frames: list[bytes], interval_s: float = 1.0) -> dict:
    from specialist import model  # type: ignore
    return model.predict_frames(frames, interval_s)


@app.local_entrypoint()
def main() -> None:
    """`modal run modal_app/specialist_app.py` - one smoke call with a tiny JPEG header."""
    print(detect.remote(b"\xff\xd8\xff\xe0" + b"\0" * 32, "smoke"))
