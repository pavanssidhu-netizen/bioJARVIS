"""
Shared Typed Contracts for LABMATE (bioJARVIS).

Strictly adheres to Section 4 of the LABMATE 8-hour Execution Plan:
  - GET  /experiment/{id}
  - POST /observations
  - POST /vision/analyse
  - POST /investigate
  - POST /reviews/{id}
  - GET  /events/{id}/stream

Preserves all required fields from the frozen Shared Observation Contract
and Shared Experiment Context Contract while extending with optional
scientific perception fields (3D prolate/oblate spheroid volumes,
Mikaelian split-ellipse semi-axes, Sauter mean diameter d32, channel
obstruction ratio, and multi-step agent reasoning trace).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
import pydantic


class ObservationSource(pydantic.BaseModel):
    type: str = pydantic.Field(default="camera", description="e.g. 'camera', 'voice', 'microfluidics_rig'")
    media_id: str = pydantic.Field(..., description="Unique frame or media identifier, e.g. 'frame_018'")
    timestamp: str = pydantic.Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        description="ISO-8601 UTC timestamp of capture",
    )


class SemiAxesPx(pydantic.BaseModel):
    """Mikaelian et al. (2015) / kLarity split-ellipse semi-axes in pixels."""
    a: float = pydantic.Field(..., description="In-plane major axis length (px)")
    b1: float = pydantic.Field(..., description="Front semi-minor axis (px)")
    b2: float = pydantic.Field(..., description="Rear semi-minor axis (px)")
    angle_deg: float = pydantic.Field(default=0.0, description="Principal axis orientation (deg)")


class BubbleDetection(pydantic.BaseModel):
    """Single detected & biophysically characterized bubble instance."""
    bubble_id: str
    bbox_xyxy: List[float] = pydantic.Field(..., description="[x1, y1, x2, y2] in image pixel coordinates")
    centroid_xy: List[float] = pydantic.Field(..., description="[cx, cy] in image pixel coordinates")
    detection_score: float = pydantic.Field(..., description="Detector score [0, 1] (not calibrated certainty)")
    area_px2: float = pydantic.Field(..., description="Segmented mask area in square pixels")
    equivalent_diameter_px: float = pydantic.Field(..., description="d_eq = sqrt(4 * Area / pi) in pixels")
    circularity: float = pydantic.Field(..., description="4 * pi * Area / Perimeter^2")
    semi_axes_px: SemiAxesPx
    volume_prolate_px3: float = pydantic.Field(..., description="Prolate spheroid volume (pi * a / 3) * (b1^2 + b2^2)")
    volume_oblate_px3: float = pydantic.Field(..., description="Oblate spheroid volume (pi * a^2 / 6) * (b1 + b2)")
    surface_prolate_px2: float = pydantic.Field(..., description="Prolate spheroid surface area in px^2")
    surface_oblate_px2: float = pydantic.Field(..., description="Oblate spheroid surface area in px^2")
    border_contact_ratio: float = pydantic.Field(..., description="border_contact_px / equivalent_diameter_px")
    channel_obstruction_ratio: float = pydantic.Field(..., description="d_eq / channel_width_px")
    obstruction_risk: Literal["low", "moderate", "high_obstruction_candidate"]
    retained_after_audit: bool = True
    audit_note: Optional[str] = None


class MeasurementPayload(pydantic.BaseModel):
    """Core measurement block matching the frozen Shared Observation Contract."""
    type: str = pydantic.Field(default="bubble_count", description="Measurement type, e.g. 'bubble_count'")
    value: int = pydantic.Field(..., description="Verified count of retained bubbles")
    unit: str = pydantic.Field(default="count", description="Unit of measurement")
    # Extended biophysical & QC fields (backward-compatible optional extensions)
    tolerance_band: List[int] = pydantic.Field(
        default_factory=list,
        description="[min_count, max_count] accounting for borderline/overlapping candidates",
    )
    sauter_mean_diameter_px: Optional[float] = pydantic.Field(
        default=None,
        description="d32 = 6 * sum(V_mid) / sum(S_mid) volume-to-surface mean diameter (px)",
    )
    total_gas_volume_px3_interval: Optional[List[float]] = pydantic.Field(
        default=None,
        description="[V_min, V_max] total gas volume interval across prolate/oblate depth models",
    )
    total_interfacial_area_px2_interval: Optional[List[float]] = pydantic.Field(
        default=None,
        description="[S_min, S_max] total gas-liquid interfacial area interval (px^2)",
    )
    max_channel_obstruction_ratio: float = pydantic.Field(
        default=0.0,
        description="Maximum ratio of bubble diameter to microfluidic channel width",
    )
    gas_holdup_area_fraction: float = pydantic.Field(
        default=0.0,
        description="Fraction of channel/ROI area occupied by gas bubbles",
    )
    qc_flags: List[str] = pydantic.Field(default_factory=list)


class ObservationMethod(pydantic.BaseModel):
    """Method metadata matching the frozen Shared Observation Contract."""
    type: str = pydantic.Field(default="specialist_vision")
    model_version: str = pydantic.Field(default="labmate-perception-agent-v1")
    detector_backend: str = pydantic.Field(default="hybrid_yolov11seg_watershed")
    multi_step_agent_used: bool = True
    tool_trace: List[str] = pydantic.Field(
        default_factory=list,
        description="Ordered log of agent tools executed during inspection",
    )


class AgentStepTrace(pydantic.BaseModel):
    """Traceable step in the multi-agent scientific perception, sceptic & Bayesian council."""
    step_index: int
    agent_role: Literal[
        "perception_orchestrator",
        "specialist_tool",
        "perception_sceptic",
        "predictive_bayesian_agent",
        "optical_triage_agent",
        "spatial_perception_agent",
        "adversarial_sceptic_agent",
        "bayesian_strategist_agent",
        "chief_chair_orchestrator",
    ]
    action_or_tool: str
    input_summary: str
    finding_summary: str
    decision_rationale: str
    duration_ms: float


class VisionAnalyseResponse(pydantic.BaseModel):
    """
    Complete response for POST /vision/analyse and compatible with POST /observations.
    Includes every top-level field of the Shared Observation Contract plus
    detailed detections, agent reasoning trace, sceptic critique, and overlay path.
    """
    observation_id: str
    experiment_id: str
    source: ObservationSource
    measurement: MeasurementPayload
    method: ObservationMethod
    status: Literal["pending_review", "abstained_low_quality", "confirmed", "disputed"] = "pending_review"
    # Extended fields for UI & Scientific Investigator
    detections: List[BubbleDetection] = pydantic.Field(default_factory=list)
    filtered_artifacts_count: int = 0
    sceptic_critique: str = ""
    scientific_interpretation: str = ""
    bayesian_predictive_assessment: Optional[Dict[str, Any]] = None
    council_consensus: Optional[Dict[str, Any]] = None
    experiment_profile: Optional[Dict[str, Any]] = None
    human_review_prompt: str = ""
    annotated_overlay_path: Optional[str] = None
    agent_trace: List[AgentStepTrace] = pydantic.Field(default_factory=list)
    latency_ms: float = 0.0


class SharedExperimentContext(pydantic.BaseModel):
    """Matches Section 4 Shared Experiment Context Contract."""
    experiment_id: str = "exp_001"
    protocol_id: str = "protocol_001"
    protocol_version: int = 1
    active_step_id: str = "step_003"
    steps: List[Dict[str, Any]] = pydantic.Field(default_factory=list)
    samples: List[Dict[str, Any]] = pydantic.Field(default_factory=list)
    constraints: List[Dict[str, Any]] = pydantic.Field(default_factory=list)
    dependencies: List[Dict[str, Any]] = pydantic.Field(default_factory=list)
    related_evidence: List[Dict[str, Any]] = pydantic.Field(default_factory=list)
