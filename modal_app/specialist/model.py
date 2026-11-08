"""Specialist sub-model entrypoint = Person 3 (Yeeyee)'s 5-agent bubble perception council.

Runs `backend.vision.adapter.analyse_live_camera_frame` (OpticalTriage -> SpatialPerception (hybrid
segmentation + ROI zoom) -> AdversarialSceptic (BubblePatchCNN + spheroid/border audit) -> Bayesian strategist
(yield MLP + GP) -> Chair) and maps its VisionAnalyseResponse onto the LABMATE specialist schema.
Runs in-process (SPECIALIST_PROVIDER=local, needs torch/opencv/scipy) or on Modal (SPECIALIST_PROVIDER=modal).
"""
from __future__ import annotations

import os
from typing import Any, Optional

MODEL_NAME = "labmate-perception-council-v1 (Person 3)"
IS_REAL_MODEL = True


def load() -> None:
    from backend.vision.patch_classifier import get_patch_classifier
    get_patch_classifier()  # loads (or trains once) the BubblePatchCNN


def _map(r: dict, image_size: Optional[tuple[int, int]] = None) -> dict:
    meas = r.get("measurement") or {}
    dets = [d for d in r.get("detections", []) if d.get("retained_after_audit", True)]
    status = r.get("status", "pending_review")
    return {
        "model": (r.get("method") or {}).get("model_version", MODEL_NAME),
        "detector_backend": (r.get("method") or {}).get("detector_backend"),
        "detections": [{"label": "bubble", "bbox": d["bbox_xyxy"], "confidence": d.get("detection_score"),
                        "equivalent_diameter_px": d.get("equivalent_diameter_px"),
                        "channel_obstruction_ratio": d.get("channel_obstruction_ratio"),
                        "obstruction_risk": d.get("obstruction_risk")} for d in dets],
        "count": int(meas.get("value", len(dets))) if status != "abstained_low_quality" else None,
        "counts_by_label": {"bubble": int(meas.get("value", len(dets)))} if status != "abstained_low_quality" else {},
        "measurement": {k: meas.get(k) for k in ("type", "value", "unit", "tolerance_band", "max_channel_obstruction_ratio",
                                                 "gas_holdup_area_fraction", "qc_flags") if k in meas},
        "filtered_artifacts_count": r.get("filtered_artifacts_count", 0),
        "abstained": status == "abstained_low_quality",
        "status": status,
        "coordinate_system": "pixels",
        "image_width": image_size[0] if image_size else None,
        "image_height": image_size[1] if image_size else None,
        "review_required": status != "confirmed",
        "sceptic_critique": r.get("sceptic_critique", "")[:600],
        "scientific_interpretation": r.get("scientific_interpretation", "")[:600],
        "bayesian_predictive_assessment": r.get("bayesian_predictive_assessment"),
        "tool_trace": (r.get("method") or {}).get("tool_trace", [])[:20],
        "overlay_base64": r.get("overlay_base64"),
        "description": (f"{meas.get('value', len(dets))} bubble(s) retained after sceptic audit"
                        if status != "abstained_low_quality" else "abstained: frame quality too low"),
    }


def predict(image_bytes: bytes, question: str = "", *, experiment_id: str = "exp_001",
            step_id: str = "step_05", experiment_context: Optional[dict[str, Any]] = None,
            include_overlay: bool = True) -> dict:
    if not image_bytes:
        raise ValueError("empty image")
    from backend.vision.adapter import analyse_live_camera_frame
    r = analyse_live_camera_frame(image_bytes, experiment_id=experiment_id, protocol_step_id=step_id,
                                  use_gemini_orchestrator=os.getenv("SPECIALIST_GEMINI_CHAIR", "false") == "true",
                                  experiment_context=experiment_context)
    size = None
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        size = (int(img.shape[1]), int(img.shape[0])) if img is not None else None
    except Exception:  # noqa: BLE001
        pass
    out = _map(r, size)
    if not include_overlay:
        out.pop("overlay_base64", None)
    return out


def predict_frames(frames: list[bytes], interval_s: float, **kw: Any) -> dict:
    """Bubbles are a state, not an action: analyse the LAST (most recent, settled) frame of the window."""
    if not frames:
        raise ValueError("no frames")
    out = predict(frames[-1], **{**kw, "include_overlay": kw.get("include_overlay", False)})
    out["frames_considered"] = 1
    out["window_frames"] = len(frames)
    return out
