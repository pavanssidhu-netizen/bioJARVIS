"""ONE authenticated call to the deployed Modal specialist (CPU; fraction of a cent) using a Person 3 test image.

    .venv/bin/python scripts/modal_check.py [image]
"""
import os
import sys
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
img = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "evals/vision_test/images/case_05_two_microbubbles.png"
fn = modal.Function.from_name(os.getenv("MODAL_VISION_APP", "labmate-vision"), "detect")
t0 = time.perf_counter()
res = fn.remote(img.read_bytes(), "modal_check", experiment_id="exp_001", step_id="step_05", include_overlay=False)
ms = (time.perf_counter() - t0) * 1000
print(f"{img.name}: count={res.get('count')} abstained={res.get('abstained')} model={res.get('model')} "
      f"backend={res.get('detector_backend')} ({ms:.0f} ms incl. cold start)")
