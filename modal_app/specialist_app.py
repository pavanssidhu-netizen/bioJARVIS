"""Modal app serving the specialist sub-models (Person 3's bubble perception council + predictive models).

Why Modal: the council needs torch + OpenCV + SciPy, far beyond Vercel's function size; Modal runs it on CPU
and scales to zero. Called only from our backend via the authenticated Modal SDK (no public web endpoint).

Cost controls (credits are limited): CPU only (MODAL_GPU unset), min_containers=0, max_containers=1,
scaledown_window=120 s, timeout=120 s. Trained weights are baked into the image (no retraining on Modal).

Deploy:  .venv/bin/modal deploy modal_app/specialist_app.py
Check:   .venv/bin/python scripts/modal_check.py
"""
from __future__ import annotations

import os
from pathlib import Path

import modal

APP_NAME = os.getenv("MODAL_VISION_APP", "labmate-vision")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
GPU = os.getenv("MODAL_GPU") or None

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("torch==2.15.0", index_url="https://download.pytorch.org/whl/cpu")
    .pip_install("numpy==2.5.4", "scipy==1.18.1", "opencv-python-headless==5.0.0.93", "pydantic==2.14.3",
                 "pillow", "google-genai==3.0.0")
    .add_local_file(ROOT / "backend" / "__init__.py", "/root/backend/__init__.py")
    .add_local_file(ROOT / "backend" / "contracts.py", "/root/backend/contracts.py")
    .add_local_dir(ROOT / "backend" / "vision", "/root/backend/vision", ignore=["__pycache__"])
    .add_local_dir(ROOT / "models", "/root/models")
    .add_local_dir(HERE / "specialist", "/root/modal_app/specialist", ignore=["__pycache__"])
    .add_local_file(HERE / "__init__.py", "/root/modal_app/__init__.py")
)

app = modal.App(APP_NAME)
_common = dict(image=image, gpu=GPU, cpu=2.0, memory=2048, min_containers=0, max_containers=1,
               scaledown_window=120, timeout=120)


@app.function(**_common)
def detect(image_bytes: bytes, question: str = "", **kw) -> dict:
    import sys
    sys.path.insert(0, "/root")
    from modal_app.specialist import model
    return model.predict(image_bytes, question, **kw)


@app.function(**_common)
def detect_frames(frames: list[bytes], interval_s: float = 1.0, **kw) -> dict:
    import sys
    sys.path.insert(0, "/root")
    from modal_app.specialist import model
    return model.predict_frames(frames, interval_s, **kw)


@app.function(**_common)
def optimise(params: dict) -> dict:
    """Person 3 GP Bayesian optimiser (compensatory action)."""
    import inspect
    import json
    import sys
    sys.path.insert(0, "/root")
    from backend.vision.predictive_models import GaussianProcessBayesianOptimizer
    fn = GaussianProcessBayesianOptimizer().optimize_compensatory_action
    res = fn(**{k: v for k, v in params.items() if k in inspect.signature(fn).parameters})
    return json.loads(json.dumps(res, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
