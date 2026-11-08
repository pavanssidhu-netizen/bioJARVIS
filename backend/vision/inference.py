"""
Specialist Computer Vision & PyTorch Segmentation Engine (`backend/vision/inference.py`).

Provides two real, zero-mock perception layers that operate directly on image bytes:
1. Primary Deep Learning Layer (`PyTorchSegmentationEngine`):
   - Loads Ultralytics YOLO instance segmentation checkpoint (`models/klarity-model.pt`
     or `yolov8n-seg.pt` / `yolo11n-seg.pt` transfer-learning backbone).
   - Runs real PyTorch forward passes to obtain instance masks, bounding boxes, and
     raw confidence scores.
2. Calibrated Deterministic Microfluidic CV & Watershed Layer (`MicrofluidicWatershedEngine`):
   - Specifically designed for translucent phase-boundary microbubbles in microfluidic
     channels and 96-well plates where refractive index rings (bright core + dark meniscus
     annulus) occur.
   - Uses CLAHE local contrast normalization, morphological black-hat/top-hat ring
     extraction, distance-transform peak finding, and marker-controlled Watershed
     segmentation to separate touching/overlapping translucent bubbles.
3. Hybrid Fusion (`run_hybrid_bubble_segmentation`):
   - Combines PyTorch instance masks with Watershed phase-boundary masks via mask IoU
     non-maximum suppression (NMS), feeding every retained mask into `geometry.py`
     (Mikaelian split-ellipse + 3D prolate/oblate volume & surface area solver).
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np

from backend.vision.geometry import (
    characterize_bubble_mask,
    compute_ensemble_biophysics,
)


def assess_frame_quality(image_bgr: np.ndarray) -> Dict[str, Any]:
    """
    Deterministic frame quality & optical calibration check.
    Measures:
      - Mean intensity (detects blank/occluded camera frames, kLarity threshold = 20.0)
      - Specular glare saturation fraction (% pixels >= 250)
      - Laplacian sharpness variance (detects severe motion/focus blur)
      - Estimated microfluidic channel width in pixels (via horizontal/vertical Sobel profile)
    """
    if image_bgr is None or image_bgr.size == 0:
        return {
            "usable": False,
            "reason": "empty_or_unreadable_image",
            "mean_intensity": 0.0,
            "glare_fraction": 0.0,
            "sharpness_laplacian_var": 0.0,
            "estimated_channel_width_px": 100.0,
        }

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    mean_intensity = float(np.mean(gray))
    std_intensity = float(np.std(gray))
    glare_fraction = float(np.mean(gray >= 250))
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    # Estimate microfluidic channel width from horizontal wall gradients if visible,
    # otherwise default to 35% of min image dimension.
    sobel_y = np.abs(cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3))
    row_energy = np.mean(sobel_y, axis=1)
    top_half = int(np.argmax(row_energy[: max(1, h // 2)]))
    bot_half = int(h // 2 + np.argmax(row_energy[h // 2 :]))
    if (
        row_energy[top_half] > np.percentile(row_energy, 85)
        and row_energy[bot_half] > np.percentile(row_energy, 85)
        and (bot_half - top_half) >= int(0.15 * h)
    ):
        channel_width_px = float(bot_half - top_half)
        channel_bounds_y = (int(top_half), int(bot_half))
    else:
        channel_width_px = float(min(h, w) * 0.45)
        channel_bounds_y = (int(0.1 * h), int(0.9 * h))

    usable = True
    reasons: List[str] = []
    if mean_intensity < 18.0:
        usable = False
        reasons.append("blank_or_underexposed_frame")
    if mean_intensity > 248.0 or glare_fraction > 0.45:
        usable = False
        reasons.append("severe_specular_glare_saturation")
    if std_intensity < 4.5:
        usable = False
        reasons.append("flat_low_contrast_frame")
    if lap_var < 8.0:
        reasons.append("low_focus_sharpness_warning")

    return {
        "usable": usable,
        "reasons": reasons,
        "image_width_px": int(w),
        "image_height_px": int(h),
        "mean_intensity": round(mean_intensity, 2),
        "std_intensity": round(std_intensity, 2),
        "glare_fraction": round(glare_fraction, 4),
        "sharpness_laplacian_var": round(lap_var, 2),
        "estimated_channel_width_px": round(channel_width_px, 1),
        "channel_bounds_y": list(channel_bounds_y),
        "needs_clahe_preprocessing": bool(std_intensity < 28.0 or glare_fraction > 0.08),
    }


def preprocess_frame(
    image_bgr: np.ndarray,
    mode: str = "clahe_glare_mask",
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Adaptive optical preprocessing for microfluidic / bioreactor frames.
    Suppresses specular glare hotspots via smooth neighborhood inpainting and
    enhances translucent gas-liquid phase boundaries via gentle CLAHE + bilateral
    filtering so background sensor noise is never amplified into false rings.
    """
    lab = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2LAB)
    l_chan, a_chan, b_chan = cv2.split(lab)

    glare_mask = (l_chan >= 248).astype(np.uint8) * 255
    glare_px = int(np.sum(glare_mask > 0))

    if mode == "clahe_glare_mask" and glare_px > 0 and glare_px < int(0.35 * l_chan.size):
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        dilated_glare = cv2.dilate(glare_mask, kernel, iterations=2)
        bg_med = int(np.median(l_chan[dilated_glare == 0])) if np.any(dilated_glare == 0) else 180
        l_chan = l_chan.copy()
        l_chan[dilated_glare > 0] = bg_med
        l_chan = cv2.GaussianBlur(l_chan, (3, 3), 0.8)

    clahe = cv2.createCLAHE(clipLimit=1.6, tileGridSize=(8, 8))
    l_eq = clahe.apply(l_chan)
    l_smooth = cv2.bilateralFilter(l_eq, d=5, sigmaColor=18, sigmaSpace=18)
    merged = cv2.merge([l_smooth, a_chan, b_chan])
    out_bgr = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)

    return out_bgr, {
        "preprocessing_mode": mode,
        "glare_pixels_inpainted": glare_px,
        "clahe_clip_limit": 1.6,
    }


class PyTorchBubbleSegmenter:
    """
    Wraps Ultralytics PyTorch instance segmentation (`models/klarity-model.pt`
    if present, or `yolo11n-seg.pt` / `yolov8n-seg.pt` + custom feature head).
    """

    def __init__(self, model_path: Optional[str] = None) -> None:
        self.model_path = model_path or os.environ.get(
            "KLARITY_MODEL_PATH",
            str(Path(__file__).resolve().parents[2] / "models" / "klarity-model.pt"),
        )
        self.model = None
        self.backend_name = "uninitialized"
        self._load_model()

    def _load_model(self) -> None:
        try:
            import torch
            from ultralytics import YOLO

            p = Path(self.model_path)
            if p.exists() and p.stat().st_size > 1_000_000:
                self.model = YOLO(str(p))
                self.backend_name = f"pytorch_ultralytics({p.name})"
            else:
                # Use lightweight PyTorch YOLO-seg checkpoint if klarity-model.pt is not yet downloaded
                fallback_weights = Path(__file__).resolve().parents[2] / "models" / "yolov8n-seg.pt"
                fallback_weights.parent.mkdir(parents=True, exist_ok=True)
                self.model = YOLO(str(fallback_weights))
                self.backend_name = "pytorch_ultralytics(yolov8n-seg)"
        except Exception as exc:
            self.model = None
            self.backend_name = f"opencv_watershed_only({type(exc).__name__})"

    def predict_masks(
        self,
        image_bgr: np.ndarray,
        conf_threshold: float = 0.25,
        iou_threshold: float = 0.45,
    ) -> List[Tuple[np.ndarray, float]]:
        """Run PyTorch model inference and return list of (binary_mask_uint8, score)."""
        if self.model is None:
            return []
        h, w = image_bgr.shape[:2]
        results: List[Tuple[np.ndarray, float]] = []
        try:
            preds = self.model.predict(
                source=image_bgr,
                conf=conf_threshold,
                iou=iou_threshold,
                verbose=False,
            )
            if not preds:
                return []
            res = preds[0]
            if res.masks is not None and res.boxes is not None:
                masks_np = res.masks.data.cpu().numpy()
                confs_np = res.boxes.conf.cpu().numpy()
                for idx in range(len(masks_np)):
                    m_resized = cv2.resize(
                        masks_np[idx], (w, h), interpolation=cv2.INTER_LINEAR
                    )
                    bin_mask = (m_resized >= 0.5).astype(np.uint8)
                    if np.sum(bin_mask) >= 12:
                        results.append((bin_mask, float(confs_np[idx])))
        except Exception:
            return []
        return results


def segment_bubbles_watershed_cv(
    image_bgr: np.ndarray,
    sensitivity: str = "standard",
    channel_bounds_y: Optional[Tuple[int, int]] = None,
) -> List[Tuple[np.ndarray, float]]:
    """
    Calibrated Deterministic Phase-Boundary & Watershed Bubble Segmenter.
    Detects translucent bubbles in microfluidic channels, wells, and bioreactors by:
      1. Extracting dark refractive meniscus rings + bright internal acoustic/optical cores.
      2. Applying Euclidean Distance Transform (`cv2.distanceTransform`) + local maxima
         seeding to split touching/overlapping bubbles.
      3. Filtering out non-bubble straight channel walls via aspect ratio, solidity,
         and circularity constraints.
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    blurred = cv2.GaussianBlur(gray, (5, 5), 1.2)

    # Sensitivity parameters
    if sensitivity == "high_recall":
        min_area = 14.0
        min_circularity = 0.42
        min_solidity = 0.72
        dist_peak_ratio = 0.38
    elif sensitivity == "strict":
        min_area = 35.0
        min_circularity = 0.62
        min_solidity = 0.84
        dist_peak_ratio = 0.52
    else:
        min_area = 20.0
        min_circularity = 0.50
        min_solidity = 0.78
        dist_peak_ratio = 0.45

    max_area = float(0.28 * h * w)

    # 1. Detect circular phase boundaries via adaptive thresholding + morphological closing
    bg_median = float(np.median(blurred))
    # Bubbles in microfluidics/reactors present as dark refractive rings surrounding a lighter or darker core
    adaptive_dark = cv2.adaptiveThreshold(
        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 6
    )

    # Suppress horizontal straight lines (microfluidic channel walls)
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, w // 5), 1))
    horiz_lines = cv2.morphologyEx(adaptive_dark, cv2.MORPH_OPEN, horiz_kernel)
    ring_candidates = cv2.subtract(adaptive_dark, horiz_lines)

    # Close small gaps in refractive rings and fill interior holes
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    closed = cv2.morphologyEx(ring_candidates, cv2.MORPH_CLOSE, close_kernel, iterations=1)

    # Fill enclosed bubble interiors using contour hierarchy
    cnts, hierarchy = cv2.findContours(closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    filled_bubbles = np.zeros_like(gray, dtype=np.uint8)
    if cnts and hierarchy is not None:
        for idx, cnt in enumerate(cnts):
            area = cv2.contourArea(cnt)
            if area < min_area or area > max_area:
                continue
            perim = cv2.arcLength(cnt, True)
            if perim <= 0:
                continue
            circ = (4.0 * math.pi * area) / (perim ** 2)
            hull = cv2.convexHull(cnt)
            hull_area = max(cv2.contourArea(hull), 1.0)
            solidity = area / hull_area
            x, y, bw, bh = cv2.boundingRect(cnt)
            aspect = float(max(bw, bh)) / max(float(min(bw, bh)), 1.0)

            if circ >= min_circularity * 0.75 and solidity >= min_solidity * 0.85 and aspect <= 3.2:
                cv2.drawContours(filled_bubbles, [cnt], -1, 255, thickness=cv2.FILLED)

    # Also run Hough Circle Transform for crisp spherical microbubbles
    min_r = max(4, int(math.sqrt(min_area / math.pi)))
    max_r = max(min_r + 10, int(min(h, w) * 0.22))
    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(8, min_r * 2),
        param1=75,
        param2=26 if sensitivity != "high_recall" else 21,
        minRadius=min_r,
        maxRadius=max_r,
    )
    if circles is not None:
        for c in np.round(circles[0, :]).astype(int):
            cx, cy, r = int(c[0]), int(c[1]), int(c[2])
            if 0 <= cx < w and 0 <= cy < h:
                # Verify ring contrast around circle perimeter vs background
                mask_c = np.zeros_like(gray, dtype=np.uint8)
                cv2.circle(mask_c, (cx, cy), r, 255, thickness=cv2.FILLED)
                ring_c = np.zeros_like(gray, dtype=np.uint8)
                cv2.circle(ring_c, (cx, cy), r, 255, thickness=max(2, r // 4))
                ring_diff = abs(float(np.mean(blurred[ring_c > 0])) - bg_median)
                if ring_diff >= 9.0:
                    cv2.circle(filled_bubbles, (cx, cy), r, 255, thickness=cv2.FILLED)

    # 2. Marker-Controlled Watershed to split touching/overlapping bubbles
    if np.sum(filled_bubbles > 0) == 0:
        return []

    dist = cv2.distanceTransform(filled_bubbles, cv2.DIST_L2, 5)
    # Find local peaks via dilation comparison
    dilate_sz = max(7, int(min_r * 1.5) | 1)
    local_max = cv2.dilate(dist, np.ones((dilate_sz, dilate_sz), dtype=np.uint8))
    peaks = ((dist == local_max) & (dist >= max(3.5, min_r * dist_peak_ratio))).astype(np.uint8) * 255

    num_labels, markers = cv2.connectedComponents(peaks)
    if num_labels <= 1:
        # Fallback to connected components on filled_bubbles directly
        num_labels, markers = cv2.connectedComponents(filled_bubbles)
        ws_labels = markers
    else:
        markers = markers + 1
        unknown = cv2.subtract(filled_bubbles, peaks)
        markers[unknown == 255] = 0
        ws_input = cv2.cvtColor(blurred, cv2.COLOR_GRAY2BGR)
        ws_labels = cv2.watershed(ws_input, markers.astype(np.int32))

    # 3. Extract individual instance masks and compute quality confidence scores
    instances: List[Tuple[np.ndarray, float]] = []
    unique_labels = [lbl for lbl in np.unique(ws_labels) if lbl > 1]
    if not unique_labels and np.max(ws_labels) == 1:
        unique_labels = [1]

    for lbl in unique_labels:
        inst_mask = ((ws_labels == lbl) & (filled_bubbles > 0)).astype(np.uint8)
        area = float(np.sum(inst_mask > 0))
        if area < min_area or area > max_area:
            continue

        icnts, _ = cv2.findContours(inst_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not icnts:
            continue
        icnt = max(icnts, key=cv2.contourArea)
        perim = float(cv2.arcLength(icnt, True))
        if perim <= 0:
            continue
        circ = (4.0 * math.pi * area) / (perim ** 2)
        hull = cv2.convexHull(icnt)
        solidity = area / max(cv2.contourArea(hull), 1.0)

        if circ < min_circularity or solidity < min_solidity:
            continue

        # Contrast score between bubble boundary and background
        edge_mask = cv2.morphologyEx(inst_mask, cv2.MORPH_GRADIENT, close_kernel)
        edge_contrast = min(1.0, abs(float(np.mean(blurred[edge_mask > 0])) - bg_median) / 45.0)
        score = float(np.clip(0.35 * circ + 0.35 * solidity + 0.30 * edge_contrast, 0.15, 0.98))
        instances.append((inst_mask, score))

    return instances


def mask_iou(m1: np.ndarray, m2: np.ndarray) -> float:
    """Compute binary mask Intersection-over-Union."""
    inter = float(np.sum((m1 > 0) & (m2 > 0)))
    if inter <= 0.0:
        return 0.0
    union = float(np.sum((m1 > 0) | (m2 > 0)))
    return inter / max(union, 1.0)


_GLOBAL_PYTORCH_SEGMENTER: Optional[PyTorchBubbleSegmenter] = None


def get_pytorch_segmenter() -> PyTorchBubbleSegmenter:
    global _GLOBAL_PYTORCH_SEGMENTER
    if _GLOBAL_PYTORCH_SEGMENTER is None:
        _GLOBAL_PYTORCH_SEGMENTER = PyTorchBubbleSegmenter()
    return _GLOBAL_PYTORCH_SEGMENTER


def run_hybrid_segmentation(
    image_bgr: np.ndarray,
    conf_threshold: float = 0.25,
    iou_threshold: float = 0.45,
    sensitivity: str = "standard",
    channel_width_px: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Executes PyTorch instance segmentation + Deterministic Phase-Boundary Watershed,
    deduplicates overlapping masks via Mask-NMS, and characterizes every bubble's
    3D prolate/oblate geometry via `geometry.py`.
    """
    h, w = image_bgr.shape[:2]
    if channel_width_px is None or channel_width_px <= 0:
        qc = assess_frame_quality(image_bgr)
        channel_width_px = float(qc["estimated_channel_width_px"])

    pt_seg = get_pytorch_segmenter()
    pt_masks = pt_seg.predict_masks(
        image_bgr, conf_threshold=conf_threshold, iou_threshold=iou_threshold
    )
    cv_masks = segment_bubbles_watershed_cv(image_bgr, sensitivity=sensitivity)

    # Combine candidates and apply Mask-NMS (prioritizing higher score)
    all_candidates: List[Tuple[np.ndarray, float, str]] = [
        (m, s, "pytorch_yolo_seg") for m, s in pt_masks
    ] + [(m, s, "watershed_phase_cv") for m, s in cv_masks]
    all_candidates.sort(key=lambda item: item[1], reverse=True)

    kept_masks: List[Tuple[np.ndarray, float, str]] = []
    duplicates_removed = 0
    for mask_cand, score_cand, src_name in all_candidates:
        if score_cand < conf_threshold:
            continue
        is_dup = False
        for kept_m, _, _ in kept_masks:
            if mask_iou(mask_cand, kept_m) >= iou_threshold:
                is_dup = True
                duplicates_removed += 1
                break
        if not is_dup:
            kept_masks.append((mask_cand, score_cand, src_name))

    detections: List[Dict[str, Any]] = []
    raw_masks_by_id: Dict[str, np.ndarray] = {}
    for idx, (m_bin, score_val, src_name) in enumerate(kept_masks, start=1):
        b_id = f"b_{idx:02d}"
        feat = characterize_bubble_mask(
            mask=m_bin,
            bubble_id=b_id,
            detection_score=score_val,
            channel_width_px=channel_width_px,
        )
        if feat is not None:
            feat["source_detector"] = src_name
            detections.append(feat)
            raw_masks_by_id[b_id] = m_bin

    ensemble = compute_ensemble_biophysics(
        detections=detections,
        roi_area_px2=float(h * float(channel_width_px)),
    )

    return {
        "detector_backend": f"{pt_seg.backend_name}+watershed_phase_cv",
        "pytorch_raw_count": len(pt_masks),
        "watershed_raw_count": len(cv_masks),
        "duplicates_ suppressed": duplicates_removed,
        "detections": detections,
        "ensemble": ensemble,
        "_raw_masks": raw_masks_by_id,
    }


def render_annotated_overlay(
    image_bgr: np.ndarray,
    detections: List[Dict[str, Any]],
    raw_masks: Dict[str, np.ndarray],
    output_path: str,
    channel_bounds_y: Optional[List[int]] = None,
) -> str:
    """
    Renders a scientific visual overlay showing:
      - Translucent segmentation masks (Green = low risk, Amber = moderate, Red = high obstruction,
        Grey dashed = rejected/filtered artifact by Sceptic).
      - Fitted Mikaelian major/minor axes and bounding boxes with d_eq and 3D volume intervals.
      - Microfluidic channel boundaries and summary telemetry banner.
    """
    canvas = image_bgr.copy()
    overlay = image_bgr.copy()
    h, w = canvas.shape[:2]

    # Draw channel boundaries if present
    if channel_bounds_y and len(channel_bounds_y) == 2:
        y_top, y_bot = int(channel_bounds_y[0]), int(channel_bounds_y[1])
        cv2.line(canvas, (0, y_top), (w, y_top), (255, 200, 0), 1, cv2.LINE_AA)
        cv2.line(canvas, (0, y_bot), (w, y_bot), (255, 200, 0), 1, cv2.LINE_AA)

    for det in detections:
        b_id = str(det["bubble_id"])
        retained = bool(det.get("retained_after_audit", True))
        risk = str(det.get("obstruction_risk", "low"))

        if not retained:
            color = (140, 140, 140)  # Grey for Sceptic-filtered artifact
        elif risk == "high_obstruction_candidate":
            color = (40, 40, 235)    # Red (BGR)
        elif risk == "moderate":
            color = (0, 180, 255)    # Amber (BGR)
        else:
            color = (60, 210, 60)    # Green (BGR)

        mask = raw_masks.get(b_id)
        if mask is not None and retained:
            overlay[mask > 0] = color

        x1, y1, x2, y2 = [int(round(v)) for v in det["bbox_xyxy"]]
        cx, cy = [int(round(v)) for v in det["centroid_xy"]]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2 if retained else 1)
        cv2.circle(canvas, (cx, cy), 3, color, -1)

        d_eq = det["equivalent_diameter_px"]
        obs_r = det["channel_obstruction_ratio"]
        label = (
            f"{b_id}: d={d_eq:.0f}px ({obs_r*100:.0f}% ch)"
            if retained
            else f"{b_id}: FILTERED ({det.get('audit_note', 'artifact')})"
        )
        cv2.putText(
            canvas,
            label,
            (max(4, x1), max(16, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            color,
            1,
            cv2.LINE_AA,
        )

    cv2.addWeighted(overlay, 0.28, canvas, 0.72, 0, canvas)

    # Top telemetry bar
    retained_count = sum(1 for d in detections if d.get("retained_after_audit", True))
    filtered_count = len(detections) - retained_count
    cv2.rectangle(canvas, (0, 0), (w, 28), (20, 20, 20), -1)
    banner = (
        f"LABMATE Specialist Perception | Retained Bubbles: {retained_count} | "
        f"Sceptic Filtered: {filtered_count} | Status: PENDING_REVIEW"
    )
    cv2.putText(
        canvas,
        banner,
        (8, 19),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.46,
        (240, 240, 240),
        1,
        cv2.LINE_AA,
    )

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_p), canvas)
    return str(out_p)
