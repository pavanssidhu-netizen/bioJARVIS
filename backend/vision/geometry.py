"""
Biophysical 3D Geometry & Split-Ellipse Reconstruction Engine.

Adapted and extended from:
  - Mikaelian et al. (2015), "A new experimental method to analyze the dynamics
    and the morphology of bubbles in liquids"
  - Willer, Siska et al. (2026), "Machine Learning Driven Quantification of Local
    Bubble Dynamics across a Pilot Scale Stirred Bioreactor" (kLarity, AGPL-3.0)

Given any 2D binary bubble segmentation mask (from PyTorch YOLO-seg or Watershed):
1. Computes moments, centroid, area, equivalent circular diameter (d_eq),
   perimeter, circularity, and image-border contact length.
2. Fits a two-half-ellipse sharing the major axis `a` with independent front/rear
   semi-minor axes `b1` and `b2` via linear least squares in the principal-axis frame.
3. Reconstructs 3D volume (V) and interfacial surface area (S) under two physical
   depth-axis bounds:
     - Prolate spheroid (revolution about major axis):
       V_prolate = (pi * a / 3) * (b1^2 + b2^2)
     - Oblate spheroid (revolution about minor axis):
       V_oblate  = (pi * a^2 / 6) * (b1 + b2)
4. Computes ensemble Sauter Mean Diameter (d32 = 6 * sum(V) / sum(S)) and
   Microfluidic Channel Obstruction Ratio (Phi_obs = d_eq / W_channel).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple
import cv2
import numpy as np

_SPHERE_REL_TOL = 1e-6


def principal_axis(points_centered: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
    """Compute principal major/minor unit vectors and orientation angle (degrees)."""
    cov = np.cov(points_centered.T)
    evals, evecs = np.linalg.eigh(cov)
    u = evecs[:, int(np.argmax(evals))]
    u = u / (np.linalg.norm(u) + 1e-12)
    v = np.array([-u[1], u[0]])
    angle_deg = float(np.degrees(np.arctan2(u[1], u[0])))
    return u, v, angle_deg


def fit_two_half_ellipse_lsq(
    mask: np.ndarray,
) -> Optional[Tuple[float, float, float, float, float, float]]:
    """
    Mikaelian two-half-ellipse least-squares fit on a binary mask.

    Returns (cx, cy, angle_deg, a_full_px, b1_px, b2_px) where `a_full_px` is the
    FULL major axis length (2 * A_semi) and `b1_px`, `b2_px` are the two semi-minor
    axes, or falls back to equivalent circle axes if contour is too small.
    """
    m = (mask > 0).astype(np.uint8)
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None
    cnt = max(cnts, key=cv2.contourArea)
    area = float(cv2.contourArea(cnt))
    if area <= 1.0:
        return None

    mom = cv2.moments(cnt)
    if mom["m00"] == 0:
        x, y, w, h = cv2.boundingRect(cnt)
        cx, cy = x + w / 2.0, y + h / 2.0
    else:
        cx, cy = mom["m10"] / mom["m00"], mom["m01"] / mom["m00"]

    pts = cnt[:, 0, :].astype(float)
    d_eq = math.sqrt(4.0 * area / math.pi)

    if pts.shape[0] < 8:
        r = max(d_eq / 2.0, 1.0)
        return float(cx), float(cy), 0.0, float(2.0 * r), float(r), float(r)

    centered = pts - np.array([cx, cy])
    u, v, angle_deg = principal_axis(centered)
    u_coord = centered @ u
    v_coord = centered @ v

    pos_mask = v_coord >= 0
    neg_mask = v_coord < 0
    if np.sum(pos_mask) < 3 or np.sum(neg_mask) < 3:
        r = max(d_eq / 2.0, 1.0)
        return float(cx), float(cy), angle_deg, float(2.0 * r), float(r), float(r)

    # Build linear system: u^2 * (1/A^2) + v_+^2 * (1/b1^2) + v_-^2 * (1/b2^2) = 1
    X = np.column_stack([
        u_coord ** 2,
        np.where(pos_mask, v_coord ** 2, 0.0),
        np.where(neg_mask, v_coord ** 2, 0.0),
    ])
    y = np.ones(pts.shape[0], dtype=float)
    try:
        theta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError:
        theta = np.array([-1.0, -1.0, -1.0])

    # Fallback to quantile extents if least-squares produces non-positive curvature
    A_semi = float(1.0 / math.sqrt(theta[0])) if theta[0] > 1e-9 else float(np.percentile(np.abs(u_coord), 95))
    b1 = float(1.0 / math.sqrt(theta[1])) if theta[1] > 1e-9 else float(np.percentile(v_coord[pos_mask], 95))
    b2 = float(1.0 / math.sqrt(theta[2])) if theta[2] > 1e-9 else float(np.percentile(np.abs(v_coord[neg_mask]), 95))

    r_eq = max(d_eq / 2.0, 1.0)
    A_semi = float(np.clip(A_semi, 0.4 * r_eq, 3.0 * r_eq))
    b1 = float(np.clip(b1, 0.25 * r_eq, 2.5 * r_eq))
    b2 = float(np.clip(b2, 0.25 * r_eq, 2.5 * r_eq))

    # Ensure major axis `a = 2 * A_semi` is at least the mean minor diameter
    a_full = max(2.0 * A_semi, b1 + b2)
    return float(cx), float(cy), float(angle_deg), float(a_full), float(b1), float(b2)


def half_spheroid_surface(c_eq: float, p_pol: float) -> float:
    """Curved surface area of HALF a spheroid of revolution with equatorial radius c_eq and polar semi-axis p_pol."""
    if c_eq <= 0.0 or p_pol <= 0.0:
        return 0.0
    scale = max(c_eq, p_pol, 1e-12)
    rel = abs(p_pol - c_eq) / scale
    if rel < _SPHERE_REL_TOL:
        return float(2.0 * math.pi * (c_eq ** 2))
    if p_pol < c_eq:
        # Oblate half-spheroid
        e_ob = math.sqrt(max(0.0, 1.0 - (p_pol / c_eq) ** 2))
        e_safe = min(max(e_ob, 1e-12), 1.0 - 1e-12)
        return float(math.pi * (c_eq ** 2) + (math.pi * (p_pol ** 2) / e_safe) * math.atanh(e_safe))
    else:
        # Prolate half-spheroid
        e_pr = math.sqrt(max(0.0, 1.0 - (c_eq / p_pol) ** 2))
        e_safe = min(max(e_pr, 1e-12), 1.0)
        return float(math.pi * (c_eq ** 2) + math.pi * (c_eq * p_pol / e_safe) * math.asin(e_safe))


def volume_surface_prolate_oblate(
    a_full: float, b1: float, b2: float
) -> Dict[str, float]:
    """
    Compute 3D Volume and Surface Area under both Prolate and Oblate depth assumptions.
    - Prolate: V = (pi * a / 3) * (b1^2 + b2^2)
    - Oblate:  V = (pi * a^2 / 6) * (b1 + b2)
    """
    if a_full <= 0 or b1 <= 0 or b2 <= 0:
        return {
            "volume_prolate_px3": 0.0,
            "volume_oblate_px3": 0.0,
            "surface_prolate_px2": 0.0,
            "surface_oblate_px2": 0.0,
        }

    A_semi = 0.5 * a_full
    # Prolate
    v_prolate = (math.pi * a_full / 3.0) * (b1 ** 2 + b2 ** 2)
    b_eq = math.sqrt(0.5 * (b1 ** 2 + b2 ** 2))
    s_prolate = 2.0 * half_spheroid_surface(b_eq, A_semi)

    # Oblate
    v_oblate = (math.pi * (a_full ** 2) / 6.0) * (b1 + b2)
    s_oblate = half_spheroid_surface(A_semi, b1) + half_spheroid_surface(A_semi, b2)

    return {
        "volume_prolate_px3": float(v_prolate),
        "volume_oblate_px3": float(v_oblate),
        "surface_prolate_px2": float(s_prolate),
        "surface_oblate_px2": float(s_oblate),
    }


def compute_border_contact_px(mask: np.ndarray, margin: int = 4) -> float:
    """Count number of mask boundary pixels touching or within `margin` px of the image border."""
    h, w = mask.shape[:2]
    m = (mask > 0).astype(np.uint8)
    top = int(np.max(np.sum(m[:margin, :] > 0, axis=0)) if np.any(m[:margin, :] > 0) else 0)
    top_len = int(np.sum(np.any(m[:margin, :] > 0, axis=0)))
    bot_len = int(np.sum(np.any(m[max(0, h - margin):, :] > 0, axis=0)))
    left_len = int(np.sum(np.any(m[:, :margin] > 0, axis=1)))
    right_len = int(np.sum(np.any(m[:, max(0, w - margin):] > 0, axis=1)))
    return float(top_len + bot_len + left_len + right_len)


def characterize_bubble_mask(
    mask: np.ndarray,
    bubble_id: str,
    detection_score: float,
    channel_width_px: float,
) -> Optional[Dict[str, object]]:
    """
    Full biophysical characterization of a single bubble binary mask.
    Returns dictionary matching `BubbleDetection` schema fields.
    """
    m = (mask > 0).astype(np.uint8)
    area_px2 = float(np.sum(m > 0))
    if area_px2 < 9.0:
        return None

    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None
    cnt = max(cnts, key=cv2.contourArea)
    perim = float(cv2.arcLength(cnt, True))
    circularity = float(min(1.0, (4.0 * math.pi * area_px2) / (perim ** 2 + 1e-9)))
    d_eq = float(math.sqrt(4.0 * area_px2 / math.pi))

    ys, xs = np.where(m > 0)
    x1, y1, x2, y2 = float(np.min(xs)), float(np.min(ys)), float(np.max(xs)), float(np.max(ys))

    fit = fit_two_half_ellipse_lsq(m)
    if fit is None:
        return None
    cx, cy, angle_deg, a_full, b1, b2 = fit

    vol_surf = volume_surface_prolate_oblate(a_full, b1, b2)
    border_px = compute_border_contact_px(m, margin=4)
    border_ratio = float(border_px / max(d_eq, 1.0))

    obs_ratio = float(d_eq / max(channel_width_px, 1.0))
    if obs_ratio >= 0.45:
        obs_risk = "high_obstruction_candidate"
    elif obs_ratio >= 0.22:
        obs_risk = "moderate"
    else:
        obs_risk = "low"

    return {
        "bubble_id": bubble_id,
        "bbox_xyxy": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
        "centroid_xy": [round(cx, 2), round(cy, 2)],
        "detection_score": round(float(detection_score), 4),
        "area_px2": round(area_px2, 2),
        "equivalent_diameter_px": round(d_eq, 2),
        "circularity": round(circularity, 4),
        "semi_axes_px": {
            "a": round(a_full, 2),
            "b1": round(b1, 2),
            "b2": round(b2, 2),
            "angle_deg": round(angle_deg, 2),
        },
        "volume_prolate_px3": round(vol_surf["volume_prolate_px3"], 2),
        "volume_oblate_px3": round(vol_surf["volume_oblate_px3"], 2),
        "surface_prolate_px2": round(vol_surf["surface_prolate_px2"], 2),
        "surface_oblate_px2": round(vol_surf["surface_oblate_px2"], 2),
        "border_contact_ratio": round(border_ratio, 4),
        "channel_obstruction_ratio": round(obs_ratio, 4),
        "obstruction_risk": obs_risk,
        "retained_after_audit": True,
        "audit_note": None,
    }


def compute_ensemble_biophysics(
    detections: List[Dict[str, object]],
    roi_area_px2: float,
) -> Dict[str, object]:
    """
    Aggregate individual bubble biophysical metrics into ensemble measurements:
      - Sauter Mean Diameter d32 = 6 * sum(V_mid) / sum(S_mid)
      - Ordered Total Volume Interval [sum(min(V_pr, V_ob)), sum(max(V_pr, V_ob))]
      - Ordered Total Surface Area Interval [sum(min(S_pr, S_ob)), sum(max(S_pr, S_ob))]
      - Max channel obstruction ratio & gas holdup fraction
    """
    retained = [d for d in detections if d.get("retained_after_audit", True)]
    if not retained:
        return {
            "count": 0,
            "sauter_mean_diameter_px": 0.0,
            "total_gas_volume_px3_interval": [0.0, 0.0],
            "total_interfacial_area_px2_interval": [0.0, 0.0],
            "max_channel_obstruction_ratio": 0.0,
            "gas_holdup_area_fraction": 0.0,
        }

    v_min_sum = 0.0
    v_max_sum = 0.0
    v_mid_sum = 0.0
    s_min_sum = 0.0
    s_max_sum = 0.0
    s_mid_sum = 0.0
    area_sum = 0.0
    max_obs = 0.0

    for d in retained:
        vp = float(d["volume_prolate_px3"])
        vo = float(d["volume_oblate_px3"])
        sp = float(d["surface_prolate_px2"])
        so = float(d["surface_oblate_px2"])
        v_min_sum += min(vp, vo)
        v_max_sum += max(vp, vo)
        v_mid_sum += 0.5 * (vp + vo)
        s_min_sum += min(sp, so)
        s_max_sum += max(sp, so)
        s_mid_sum += 0.5 * (sp + so)
        area_sum += float(d["area_px2"])
        max_obs = max(max_obs, float(d["channel_obstruction_ratio"]))

    d32 = float(6.0 * v_mid_sum / max(s_mid_sum, 1e-9))
    holdup = float(min(1.0, area_sum / max(roi_area_px2, 1.0)))

    return {
        "count": len(retained),
        "sauter_mean_diameter_px": round(d32, 2),
        "total_gas_volume_px3_interval": [round(v_min_sum, 2), round(v_max_sum, 2)],
        "total_interfacial_area_px2_interval": [round(s_min_sum, 2), round(s_max_sum, 2)],
        "max_channel_obstruction_ratio": round(max_obs, 4),
        "gas_holdup_area_fraction": round(holdup, 4),
    }
