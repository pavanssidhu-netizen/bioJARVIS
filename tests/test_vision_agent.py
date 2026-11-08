"""
Unit & Integration Tests for Person 3 Specialist Perception & Sceptic Agent (`tests/test_vision_agent.py`).
Verifies:
  1. 3D Mikaelian Split-Ellipse & Prolate/Oblate Spheroid Physics (`geometry.py`)
  2. Multi-Step Autonomous Perception & Sceptic Agent (`agent.py` & `adapter.py`):
     - Rejects border-clipped artifacts (`border_contact_px / d_eq > 1.0`)
     - Abstains on blank/corrupted frames (`status == "abstained_low_quality"`)
     - Enforces Human-in-the-Loop sign-off (`status == "pending_review"`)
     - Matches the frozen Shared Observation Contract (`observation_id`, `experiment_id`, `source`, `measurement`, `method`, `status`)
"""

from __future__ import annotations

import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2
import numpy as np
import pytest

from backend.vision.geometry import (
    characterize_bubble_mask,
    compute_ensemble_biophysics,
    fit_two_half_ellipse_lsq,
    volume_surface_prolate_oblate,
)
from backend.vision.adapter import analyse_image
from backend.vision.patch_classifier import get_patch_classifier, score_bubble_patch_pytorch
from evals.evaluate import build_held_out_vision_test_set


def test_prolate_oblate_sphere_equivalence() -> None:
    """For a perfect sphere (a = 2R, b1 = R, b2 = R), prolate and oblate volumes must both equal (4/3)*pi*R^3."""
    R = 25.0
    a_full = 2.0 * R
    res = volume_surface_prolate_oblate(a_full, R, R)
    expected_v = (4.0 / 3.0) * math.pi * (R ** 3)
    expected_s = 4.0 * math.pi * (R ** 2)

    assert math.isclose(res["volume_prolate_px3"], expected_v, rel_tol=1e-4)
    assert math.isclose(res["volume_oblate_px3"], expected_v, rel_tol=1e-4)
    assert math.isclose(res["surface_prolate_px2"], expected_s, rel_tol=1e-4)
    assert math.isclose(res["surface_oblate_px2"], expected_s, rel_tol=1e-4)


def test_split_ellipse_and_characterization() -> None:
    mask = np.zeros((200, 200), dtype=np.uint8)
    cv2.circle(mask, (100, 100), 22, 255, thickness=-1)
    feat = characterize_bubble_mask(mask, bubble_id="b_test", detection_score=0.92, channel_width_px=100.0)
    assert feat is not None
    assert 42.0 <= feat["equivalent_diameter_px"] <= 46.0
    assert feat["border_contact_ratio"] == 0.0
    assert feat["obstruction_risk"] in ("moderate", "high_obstruction_candidate")


def test_autonomous_agent_contract_and_sceptic(tmp_path: Path) -> None:
    cases = build_held_out_vision_test_set(tmp_path)
    assert len(cases) == 18

    # 1. Test border-artifact filtering case (case_15: 1 valid central bubble + 2 border-clipped artifacts)
    case_15 = next(c for c in cases if c["case_id"] == "case_15_border_clip_both_sides")
    res_15 = analyse_image(case_15["image_path"], experiment_id="exp_001", use_gemini_orchestrator=False)

    # Verify frozen Shared Observation Contract keys
    for req_key in ("observation_id", "experiment_id", "source", "measurement", "method", "status"):
        assert req_key in res_15
    assert res_15["status"] == "pending_review"
    assert res_15["measurement"]["value"] == 1
    assert res_15["filtered_artifacts_count"] >= 1
    assert len(res_15["agent_trace"]) >= 3

    # 2. Test blank/underexposed camera fault abstention (case_17)
    case_17 = next(c for c in cases if c["case_id"] == "case_17_blank_underexposed_fault")
    res_17 = analyse_image(case_17["image_path"], experiment_id="exp_001", use_gemini_orchestrator=False)
    assert res_17["status"] == "abstained_low_quality"
    assert "abstained_unusable_frame" in res_17["measurement"]["qc_flags"]


def test_pytorch_yield_predictor_and_gp_bayesian_optimizer() -> None:
    """Verify Model 2 (PyTorch BiochemicalYieldMLP) & Model 3 (GP Bayesian Expected Improvement)."""
    from backend.vision.predictive_models import GaussianProcessBayesianOptimizer, get_yield_model

    _, metrics = get_yield_model()
    assert metrics["held_out_r2"] >= 0.85

    optimizer = GaussianProcessBayesianOptimizer()
    # Test severe bubble obstruction + pipetting slip (-2.0 uL, 12 min wait, Phi_obs=0.62)
    bo = optimizer.optimize_compensatory_action(
        volume_variance_ul=-2.0,
        concentration_ratio=1.0,
        wait_time_min=12.0,
        ambient_temp_c=23.5,
        max_channel_obstruction_ratio=0.62,
        sauter_mean_diameter_px=54.0,
        gas_holdup_volume_ul=0.14,
    )
    assert bo["bayesian_intervention_required"] is True
    assert bo["posterior_recovered_yield_pct"] > bo["uncompensated_Predicted_yield_pct"]
    assert bo["requires_human_confirmation"] is True


def test_multi_experiment_universal_generalization(tmp_path: Path) -> None:
    """Verify the 5-Agent Council dynamically adapts across all canonical and custom unseen experiments."""
    cases = build_held_out_vision_test_set(tmp_path)
    case_09 = next(c for c in cases if c["case_id"] == "case_09_channel_obstruction_slug")

    # 1. RT-qPCR experiment (exp_002)
    res_qpcr = analyse_image(
        case_09["image_path"],
        experiment_id="exp_002",
        protocol_step_id="step_04_plate_seal_and_load",
        use_gemini_orchestrator=False,
    )
    assert res_qpcr["experiment_profile"]["protocol_id"] == "rt_qpcr_taqman"
    assert "RT-qPCR" in res_qpcr["scientific_interpretation"]

    # 2. Organ-on-a-Chip perfusion (exp_003)
    res_ooc = analyse_image(
        case_09["image_path"],
        experiment_id="exp_003",
        protocol_step_id="step_03_lumen_perfusion",
        use_gemini_orchestrator=False,
    )
    assert res_ooc["experiment_profile"]["protocol_id"] == "organ_on_chip_perfusion"
    assert "Organ-on-a-Chip" in res_ooc["scientific_interpretation"]

    # 3. Completely unseen custom user experiment with custom constraints & references
    res_custom = analyse_image(
        case_09["image_path"],
        experiment_id="exp_999_custom",
        protocol_step_id="step_02_electrotransfer",
        use_gemini_orchestrator=False,
        experiment_context={
            "protocol_name": "Western Blot PVDF Membrane Electrotransfer",
            "assay_domain": "proteomics_electrotransfer",
            "constraints": [{"measurement_type": "bubble_count", "max_allowed": 0}],
            "references": ["Bio-Rad Mini-PROTEAN Trans-Blot Manual (ref_wb_01)"],
            "ambient_temp_c": 4.0,
        },
    )
    assert res_custom["experiment_profile"]["protocol_name"] == "Western Blot PVDF Membrane Electrotransfer"
    assert "Western Blot PVDF Membrane Electrotransfer" in res_custom["scientific_interpretation"]
    assert "ref_wb_01" in res_custom["scientific_interpretation"]
