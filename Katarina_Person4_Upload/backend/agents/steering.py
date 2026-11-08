"""
LABMATE Scientific Steering & Reconciliation Policy Engine (Person 4 — Katarina).

Two-Layer Universal Architecture:
  - Layer 1 (`science/general_lab_db.json`): Built-in General Wet-Lab Knowledge & Rules DB.
    Works in ANY laboratory on ANY experiment (PCR, cell culture, Western blot, optical assays).
  - Layer 2 (`science/experiment_seed.json`): Specific Assay Protocol DB (e.g., Ryan's Microfluidic
    CEA Immunoassay or 96-well CRP ELISA). Supports both `channel_map` (`CH01`..`CH12`) and
    `plate_map` (`A1`..`H12`), overriding or extending Layer 1 with assay-specific rules.

Implements the 7-action scientific steering taxonomy:
  1. no_action            — Matches protocol; record silently
  2. log                  — Worth recording (within tolerance or dispute logged); no new alert
  3. warn                 — Clear rule broken or review-bypass attempt; flag for human review
  4. request_confirmation — Possible problem or missing detail; ask scientist what happened
  5. request_recapture    — Image/signal unclear; ask for another photo
  6. investigate          — Complex conflict across sources or multi-cause discrepancy; hand to deeper reasoning tool
  7. abstain              — Not enough evidence in Layer 2 or Layer 1; say so rather than guess
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class SteeringAction(str, Enum):
    NO_ACTION = "no_action"
    LOG = "log"
    WARN = "warn"
    REQUEST_CONFIRMATION = "request_confirmation"
    REQUEST_RECAPTURE = "request_recapture"
    INVESTIGATE = "investigate"
    ABSTAIN = "abstain"


class ScientificStatus(str, Enum):
    RECORDED = "recorded"
    WARNING = "warning"
    PENDING_REVIEW = "pending_review"
    INVALID = "invalid"


# Load Layer 1: General Wet-Lab Knowledge Database
_GENERAL_DB_PATH = Path(__file__).resolve().parents[2] / "science" / "general_lab_db.json"
try:
    with open(_GENERAL_DB_PATH, "r", encoding="utf-8") as _f:
        GENERAL_LAB_DB: Dict[str, Any] = json.load(_f)
except Exception:
    GENERAL_LAB_DB = {"constraints": [], "related_evidence": [], "uncertainty_cues": [], "correction_cues": []}


@dataclass
class Observation:
    id: str
    step_id: str
    source_type: str  # "voice" | "camera" | "note"
    content: str
    well_id: Optional[str] = None
    channel_id: Optional[str] = None
    media_ref: Optional[str] = None
    confidence: float = 1.0
    measurement_type: Optional[str] = None
    measurement_value: Any = None
    measurement_unit: Optional[str] = None
    supersedes_observation_id: Optional[str] = None

    @property
    def location_id(self) -> Optional[str]:
        """Returns channel_id (e.g. 'CH01') or well_id (e.g. 'A1') uniformly."""
        return self.channel_id or self.well_id

    @classmethod
    def from_case_observation(
        cls,
        case_id: str,
        active_step_id: str,
        obs_dict: Dict[str, Any],
    ) -> "Observation":
        """Adapter for Ryan's `scientific_cases.json` observation format."""
        meas = obs_dict.get("measurement") or {}
        m_type = meas.get("type") if isinstance(meas, dict) else obs_dict.get("measurement_type")
        m_val = meas.get("value") if isinstance(meas, dict) else obs_dict.get("measurement_value")
        m_unit = meas.get("unit") if isinstance(meas, dict) else obs_dict.get("measurement_unit")
        utterance = obs_dict.get("utterance")
        media_ref = obs_dict.get("media_ref")
        content = utterance or media_ref or obs_dict.get("content") or ""
        return cls(
            id=f"obs_{case_id}",
            step_id=active_step_id,
            source_type=obs_dict.get("source_type", "voice"),
            content=content,
            well_id=obs_dict.get("well_id"),
            channel_id=obs_dict.get("channel_id"),
            media_ref=media_ref,
            confidence=float(obs_dict.get("confidence", 1.0)),
            measurement_type=m_type,
            measurement_value=m_val,
            measurement_unit=m_unit,
            supersedes_observation_id=obs_dict.get("supersedes_observation_id"),
        )

    @classmethod
    def from_vision_output(
        cls,
        obs_id: str,
        step_id: str,
        vision_result: Dict[str, Any],
        well_id: Optional[str] = None,
        channel_id: Optional[str] = None,
    ) -> "Observation":
        """Adapter for Person 3 (Yeeyee)'s `analyse_image()` vision output."""
        quality = str(vision_result.get("image_quality", "ok")).lower()
        raw_conf = float(vision_result.get("confidence", 0.90))
        media_ref = vision_result.get("media_ref")
        if quality in ("unusable", "dark", "blurry", "glare_obscured", "blank", "underexposed"):
            conf = min(raw_conf, 0.25)
        elif quality in ("borderline", "partial_glare", "uncertain"):
            conf = min(max(raw_conf, 0.45), 0.65)
        else:
            conf = raw_conf

        bubble_count = int(vision_result.get("bubble_count", 0))
        loc = channel_id or well_id or vision_result.get("channel_id") or vision_result.get("well_id")
        summary = vision_result.get("summary") or f"Vision analysis on {loc or 'plate/chip'}: bubble_count={bubble_count}"
        return cls(
            id=obs_id,
            step_id=step_id,
            source_type="camera",
            content=summary,
            well_id=well_id or vision_result.get("well_id"),
            channel_id=channel_id or vision_result.get("channel_id"),
            media_ref=media_ref,
            confidence=conf,
            measurement_type="bubble_count",
            measurement_value=bubble_count,
            measurement_unit="count",
        )


@dataclass
class SteeringDecision:
    action: SteeringAction
    scientific_status: ScientificStatus
    endpoint: str
    requires_human_approval: bool
    violated_constraints: List[str] = field(default_factory=list)
    affected_entities: List[str] = field(default_factory=list)
    affected_structured: Dict[str, List[str]] = field(
        default_factory=lambda: {"channels": [], "wells": [], "samples": [], "derived_values": []}
    )
    citations: List[str] = field(default_factory=list)
    spoken_response: str = ""
    rationale: str = ""
    preserves_original_observation: bool = True


def _get_location_map(experiment_context: Dict[str, Any]) -> Tuple[str, Dict[str, str]]:
    """Returns ('channels' | 'wells', mapping_dict) from experiment_context."""
    if "channel_map" in experiment_context and experiment_context["channel_map"]:
        return "channels", experiment_context["channel_map"]
    if "plate_map" in experiment_context and experiment_context["plate_map"]:
        return "wells", experiment_context["plate_map"]
    return "channels", {}


def trace_affected_dependencies(
    experiment_context: Dict[str, Any],
    location_id: Optional[str] = None,
    step_id: Optional[str] = None,
    global_violation: bool = False,
) -> Tuple[List[str], Dict[str, List[str]]]:
    """
    Dynamically walks `channel_map`/`plate_map` and `dependencies` in `experiment_context`.
    Returns:
      - flat list of affected entities (`affected_entities`)
      - structured dict (`{"channels": [...], "wells": [...], "samples": [...], "derived_values": [...]}`)
    """
    loc_key, loc_map = _get_location_map(experiment_context)
    dependencies: List[Dict[str, Any]] = experiment_context.get("dependencies", [])
    samples_list = {s.get("sample_id") for s in experiment_context.get("samples", []) if s.get("sample_id")}
    derived_list = {d.get("id") for d in experiment_context.get("derived_values", []) if d.get("id")}

    adj: Dict[str, List[str]] = {}
    for dep in dependencies:
        src = dep.get("from")
        dst = dep.get("to")
        if src and dst:
            adj.setdefault(src, []).append(dst)

    visited: List[str] = []
    queue: List[str] = []

    if location_id:
        visited.append(location_id)
        sample_id = loc_map.get(location_id)
        if sample_id:
            visited.append(sample_id)
            queue.append(sample_id)

    if global_violation:
        for ch_or_well, samp in loc_map.items():
            if ch_or_well not in visited:
                visited.append(ch_or_well)
            if samp not in visited:
                visited.append(samp)
                queue.append(samp)

    if step_id and not location_id and not global_violation:
        queue.append(step_id)

    while queue:
        curr = queue.pop(0)
        for nxt in adj.get(curr, []):
            if nxt not in visited:
                visited.append(nxt)
                queue.append(nxt)

    channels_out = [x for x in visited if x in loc_map and loc_key == "channels"]
    wells_out = [x for x in visited if x in loc_map and loc_key == "wells"]
    samples_out = [x for x in visited if x in samples_list]
    derived_out = [x for x in visited if x in derived_list]

    structured = {
        "channels": channels_out,
        "wells": wells_out,
        "samples": samples_out,
        "derived_values": derived_out,
    }
    return visited, structured


def _normalize_sources(src: Any) -> List[str]:
    if not src:
        return []
    if isinstance(src, list):
        return [str(s) for s in src]
    return [str(src)]


def _merged_constraints(experiment_context: Dict[str, Any], step_id: str) -> List[Dict[str, Any]]:
    """
    Merges Layer 2 (`experiment_seed.json`) constraints with Layer 1 (`general_lab_db.json`) constraints.
    Layer 2 rules for the active step take priority; Layer 1 provides universal fallback rules.
    """
    layer2 = experiment_context.get("constraints", [])
    layer1 = GENERAL_LAB_DB.get("constraints", [])

    active_layer2: List[Dict[str, Any]] = []
    other_layer2: List[Dict[str, Any]] = []
    covered_types_in_step = set()

    for c in layer2:
        applies = c.get("applies_to_step_ids", [c.get("step_id")])
        mtype = c.get("measurement_type")
        if step_id in applies or applies == ["*"]:
            active_layer2.append(c)
            if mtype:
                covered_types_in_step.add(mtype)
        else:
            other_layer2.append(c)

    fallback_layer1: List[Dict[str, Any]] = []
    for gc in layer1:
        if gc.get("measurement_type") not in covered_types_in_step:
            fallback_layer1.append(gc)

    return active_layer2 + other_layer2 + fallback_layer1


def _find_constraint(
    experiment_context: Dict[str, Any],
    step_id: str,
    measurement_type: Optional[str],
) -> Optional[Dict[str, Any]]:
    if not measurement_type:
        return None
    for c in _merged_constraints(experiment_context, step_id):
        if c.get("measurement_type") == measurement_type:
            applies = c.get("applies_to_step_ids", [c.get("step_id")])
            if step_id in applies or applies == ["*"]:
                return c
    for c in _merged_constraints(experiment_context, step_id):
        if c.get("measurement_type") == measurement_type:
            return c
    return None


def _step_has_conflicting_sources(step: Dict[str, Any]) -> bool:
    note = (step.get("note") or "").lower()
    has_multiple_options = bool(step.get("volume_options") and len(step.get("volume_options", [])) > 1)
    conflict_words = ("disagree", "conflict", "contradict", "versus", "vs.")
    return has_multiple_options and any(w in note for w in conflict_words)


def _format_style2_response(
    observation_and_limit: str,
    practical_option: str,
    question: str,
) -> str:
    """Enforces Katarina's Style 2 response template."""
    return f"{observation_and_limit} {practical_option} {question}"


def handle_intentional_correction(
    obs: Observation,
    experiment_context: Dict[str, Any],
    target_observation_status: str = "recorded",
) -> SteeringDecision:
    """
    Choice 2 Policy for Intentional Corrections / Disputes:
      - Preserves the original observation as immutable.
      - If disputing an active warning/detection (e.g. SC13 'That's a scratch on the chip, not a bubble'),
        records the dispute (`log`) and requires human review (`requires_human_approval=True`) via `POST /reviews/{id}`.
      - If correcting a normal spoken slip (`target_observation_status == "recorded"`), logs immediately (`requires_human_approval=False`).
    """
    loc = obs.location_id
    is_dispute_on_warning = (
        target_observation_status in ("warning", "pending_review")
        or any(w in (obs.content or "").lower() for w in ("not a bubble", "scratch", "glare", "dispute", "false positive"))
    )

    if is_dispute_on_warning:
        return SteeringDecision(
            action=SteeringAction.LOG,
            scientific_status=ScientificStatus.PENDING_REVIEW,
            endpoint=f"POST /reviews/{obs.supersedes_observation_id or obs.id}",
            requires_human_approval=True,
            violated_constraints=[],
            affected_entities=[],
            citations=[],
            spoken_response=_format_style2_response(
                f"Your dispute is recorded against the {loc or 'previous'} observation, and the original detection is preserved.",
                "You can resolve the flag through the review step.",
                "Would you like to confirm this review decision now?",
            ),
            rationale="Original observations are immutable; corrections are added on top and changes require human review.",
            preserves_original_observation=True,
        )

    return SteeringDecision(
        action=SteeringAction.LOG,
        scientific_status=ScientificStatus.RECORDED,
        endpoint="POST /observations",
        requires_human_approval=False,
        violated_constraints=[],
        affected_entities=[],
        citations=[],
        spoken_response=(
            f"Logged your correction ({obs.content}). The original observation is preserved in the audit history."
        ),
        rationale="Spoken slip corrected; original observation preserved in immutable audit log.",
        preserves_original_observation=True,
    )


def reconcile_observation(
    obs: Observation,
    experiment_context: Dict[str, Any],
    prior_observation_status: str = "recorded",
) -> SteeringDecision:
    """
    Evaluates an incoming Observation against Layer 2 (`experiment_seed.json`) and Layer 1 (`general_lab_db.json`)
    and returns one of the 7 official actions.
    """
    steps = {s["step_id"]: s for s in experiment_context.get("steps", []) if "step_id" in s}
    active_step = steps.get(obs.step_id, {})
    text_lower = (obs.content or "").lower()
    media_lower = (obs.media_ref or "").lower()
    loc = obs.location_id

    # 0. Safety / Governance Rule: Refusing to skip or bypass human review (e.g. SC14)
    if any(phrase in text_lower for phrase in ("skip the review", "mark ch", "as passed and skip", "bypass review", "skip review")):
        affected_flat, affected_struct = trace_affected_dependencies(
            experiment_context, location_id=loc, step_id=obs.step_id
        )
        return SteeringDecision(
            action=SteeringAction.WARN,
            scientific_status=ScientificStatus.PENDING_REVIEW,
            endpoint=f"POST /reviews/{obs.id}",
            requires_human_approval=True,
            violated_constraints=[],
            affected_entities=affected_flat,
            affected_structured=affected_struct,
            citations=[],
            spoken_response=_format_style2_response(
                f"I cannot bypass the human review step; the pending review on {loc or 'this step'} stays open.",
                f"Please complete the {loc or 'pending'} review through the review step.",
                "Would you like to confirm or dispute the flag in the review panel?",
            ),
            rationale="All proposed scientific changes require explicit human review.",
        )

    # 1. Check for intentional correction or dispute of a previous observation (e.g. SC13)
    correction_cues = GENERAL_LAB_DB.get(
        "correction_cues",
        ["actually i meant", "correction:", "wait, i meant", "not a bubble", "scratch on the"],
    )
    if obs.supersedes_observation_id or any(cue in text_lower for cue in correction_cues):
        return handle_intentional_correction(obs, experiment_context, prior_observation_status)

    # 2. Check for unusable/unclear camera frame (e.g. SC11 `case_17_blank_underexposed_fault` or confidence < 0.40)
    unusable_media_cues = ("blank", "underexposed", "blurry", "dark", "unusable", "fault")
    if obs.source_type == "camera" and (
        obs.confidence < 0.40
        or (obs.measurement_value is None and any(cue in media_lower for cue in unusable_media_cues))
    ):
        return SteeringDecision(
            action=SteeringAction.REQUEST_RECAPTURE,
            scientific_status=ScientificStatus.INVALID,
            endpoint="POST /vision/analyse",
            requires_human_approval=False,
            violated_constraints=[],
            affected_entities=[],
            citations=["ref_03"],
            spoken_response=_format_style2_response(
                f"The camera image of {loc or 'the channel/well'} is too dark or unclear to assess reliably.",
                f"Please recapture {loc or 'the image'} with adequate lighting before readout.",
                "Could you take another photo now?",
            ),
            rationale="An unusable image is evidence of neither a bubble nor a clean channel.",
        )

    # 3. Check for borderline camera confidence (0.40 <= confidence < 0.75) -> request_confirmation
    if obs.source_type == "camera" and 0.40 <= obs.confidence < 0.75:
        affected_flat, affected_struct = trace_affected_dependencies(
            experiment_context, location_id=loc, step_id=obs.step_id
        )
        return SteeringDecision(
            action=SteeringAction.REQUEST_CONFIRMATION,
            scientific_status=ScientificStatus.PENDING_REVIEW,
            endpoint=f"POST /reviews/{obs.id}",
            requires_human_approval=True,
            violated_constraints=[],
            affected_entities=affected_flat,
            affected_structured=affected_struct,
            citations=["ref_02", "ref_03"],
            spoken_response=_format_style2_response(
                f"Vision detected a possible anomaly in {loc or 'the image'} at borderline confidence ({obs.confidence:.2f}).",
                "You can inspect the channel/well directly or recapture the image.",
                f"Can you confirm whether {loc or 'the channel/well'} has an air bubble or surface glare?",
            ),
            rationale="Borderline vision confidence requires human confirmation before recording a violation.",
        )

    # 4. Check for uncertain spoken/note observation -> request_confirmation
    uncertainty_cues = GENERAL_LAB_DB.get(
        "uncertainty_cues",
        ["not sure", "i think", "maybe", "might have", "might be", "lost count", "did i", "roughly"],
    )
    if obs.source_type in ("voice", "note") and any(cue in text_lower for cue in uncertainty_cues):
        affected_flat, affected_struct = trace_affected_dependencies(
            experiment_context, location_id=loc, step_id=obs.step_id
        )
        # Note: per Ryan's SC12, if no channel_id or measurement is identified yet, requires_human_approval is False
        # (it asks the scientist to identify the channel and capture an image before recording anything).
        # If a specific measurement/step violation is already implicated, require human approval to proceed.
        has_specific_target = bool(loc or obs.measurement_type)
        return SteeringDecision(
            action=SteeringAction.REQUEST_CONFIRMATION,
            scientific_status=ScientificStatus.PENDING_REVIEW,
            endpoint=f"POST /reviews/{obs.id}" if has_specific_target else "POST /observations",
            requires_human_approval=has_specific_target,
            violated_constraints=[],
            affected_entities=affected_flat if has_specific_target else [],
            affected_structured=affected_struct if has_specific_target else {"channels": [], "wells": [], "samples": [], "derived_values": []},
            citations=_normalize_sources(active_step.get("source")) or ["ref_02"],
            spoken_response=_format_style2_response(
                f"Your report ('{obs.content}') is uncertain and does not confirm a specific channel or measurement.",
                "Please identify which channel or step you mean and show it to the camera so we can check before recording anything.",
                "Which channel or value can you confirm?",
            ),
            rationale="Uncertain verbal report requires clarification before recording a violation.",
        )

    # 5. Spoken skipped wash detection when measurement is null (e.g. SC07: 'I skipped the wash...')
    if obs.measurement_type is None and ("skipped the wash" in text_lower or "skip the wash" in text_lower or "no wash" in text_lower):
        wash_c = _find_constraint(experiment_context, obs.step_id, "wash_duration_min") or _find_constraint(
            experiment_context, obs.step_id, "wash_count"
        )
        if wash_c:
            cid = wash_c["constraint_id"]
            cites = _normalize_sources(wash_c.get("source"))
            affected_flat, affected_struct = trace_affected_dependencies(
                experiment_context, step_id=obs.step_id, global_violation=True
            )
            return SteeringDecision(
                action=SteeringAction.WARN,
                scientific_status=ScientificStatus.PENDING_REVIEW,
                endpoint=f"POST /reviews/{obs.id}",
                requires_human_approval=True,
                violated_constraints=[cid],
                affected_entities=affected_flat,
                affected_structured=affected_struct,
                citations=cites,
                spoken_response=_format_style2_response(
                    f"The required wash step ({wash_c.get('rule')}) was skipped, which affects all channels/samples.",
                    "You can decide how to proceed and record this deviation against the run.",
                    "How would you like to proceed in the review panel?",
                ),
                rationale=wash_c.get("rationale", "Protocol requires washing between binding steps."),
            )

    # 6. Check for complex source conflicts -> investigate
    if (
        obs.measurement_type == "reagent_volume_ul"
        or "methanesulfonic" in text_lower
        or "sulfuric" in text_lower
        or "conflict" in text_lower
    ) and _step_has_conflicting_sources(active_step):
        affected_flat, affected_struct = trace_affected_dependencies(
            experiment_context, step_id=obs.step_id, global_violation=True
        )
        return SteeringDecision(
            action=SteeringAction.INVESTIGATE,
            scientific_status=ScientificStatus.PENDING_REVIEW,
            endpoint="POST /investigate",
            requires_human_approval=True,
            violated_constraints=[],
            affected_entities=affected_flat,
            affected_structured=affected_struct,
            citations=["ref_01", "ref_02"],
            spoken_response=_format_style2_response(
                f"Protocol sources for {obs.step_id} ({active_step.get('name', 'this step')}) contain conflicting specifications ({active_step.get('note')}).",
                "I am handing this conflict to the deeper investigation tool to compare the cited references.",
                "Which source specification would you like to approve for this run?",
            ),
            rationale="Conflicting numerical specifications across cited sources require deeper investigation.",
        )

    # 7. Evaluate measurement against Layer 2 (`experiment_seed.json`) + Layer 1 (`general_lab_db.json`)
    constraint = _find_constraint(experiment_context, obs.step_id, obs.measurement_type)

    if constraint is not None and obs.measurement_value is not None:
        cid = constraint["constraint_id"]
        cites = _normalize_sources(constraint.get("source"))
        mtype = obs.measurement_type
        val = obs.measurement_value

        # 7a. Bubble count
        if mtype == "bubble_count":
            max_allowed = constraint.get("max_allowed", 0)
            if val > max_allowed:
                affected_flat, affected_struct = trace_affected_dependencies(
                    experiment_context, location_id=loc, step_id=obs.step_id
                )
                return SteeringDecision(
                    action=SteeringAction.WARN,
                    scientific_status=ScientificStatus.PENDING_REVIEW,
                    endpoint=f"POST /reviews/{obs.id}",
                    requires_human_approval=True,
                    violated_constraints=[cid],
                    affected_entities=affected_flat,
                    affected_structured=affected_struct,
                    citations=cites,
                    spoken_response=_format_style2_response(
                        f"Detected {val} bubble(s) in {loc or 'the channel/well'}, which violates {cid} ({constraint.get('rule')}) and affects {', '.join(affected_flat[:5])}.",
                        f"You can remove the bubble or re-fill {loc or 'the channel/well'} before continuing.",
                        "How would you like to proceed?",
                    ),
                    rationale=constraint.get("rationale", ""),
                )
            return SteeringDecision(
                action=SteeringAction.NO_ACTION,
                scientific_status=ScientificStatus.RECORDED,
                endpoint="POST /observations",
                requires_human_approval=False,
                violated_constraints=[],
                affected_entities=[],
                citations=cites,
                spoken_response=f"{loc or 'Channel/well'} is clear; no bubbles detected.",
                rationale="No constraint is violated.",
            )

        # 7b. Channel fill complete (e.g. SC03 gas slug / incomplete filling)
        if mtype == "channel_fill_complete":
            expected_bool = constraint.get("expected_value", True)
            if bool(val) != bool(expected_bool):
                affected_flat, affected_struct = trace_affected_dependencies(
                    experiment_context, location_id=loc, step_id=obs.step_id
                )
                violated = [cid]
                # If media_ref indicates obstruction slug with bubbles (SC03), include c_01 as well
                if "slug" in media_lower or "bubble" in text_lower:
                    bubble_c = _find_constraint(experiment_context, obs.step_id, "bubble_count")
                    if bubble_c and bubble_c["constraint_id"] not in violated:
                        violated.append(bubble_c["constraint_id"])
                return SteeringDecision(
                    action=SteeringAction.WARN,
                    scientific_status=ScientificStatus.PENDING_REVIEW,
                    endpoint=f"POST /reviews/{obs.id}",
                    requires_human_approval=True,
                    violated_constraints=violated,
                    affected_entities=affected_flat,
                    affected_structured=affected_struct,
                    citations=cites,
                    spoken_response=_format_style2_response(
                        f"Incomplete channel filling detected in {loc or 'channel'} ({constraint.get('rule')}), affecting {', '.join(affected_flat[:4])}.",
                        f"You can clear and re-fill {loc or 'the channel'} before continuing.",
                        "Would you like to clear and re-fill the channel now?",
                    ),
                    rationale=constraint.get("rationale", ""),
                )
            return SteeringDecision(
                action=SteeringAction.NO_ACTION,
                scientific_status=ScientificStatus.RECORDED,
                endpoint="POST /observations",
                requires_human_approval=False,
                citations=cites,
                spoken_response=f"{loc or 'Channel'} is completely filled.",
                rationale="Channel fill matches protocol.",
            )

        # 7c. Incubation duration (min) — supports `acceptable_range_min`, `tolerance_min`, or `duration_is_minimum`
        if mtype == "incubation_duration_min":
            expected = float(constraint.get("expected_value") or active_step.get("duration_min") or 0)
            acc_range = constraint.get("acceptable_range_min")
            tol = constraint.get("tolerance_min")
            is_min = bool(active_step.get("duration_is_minimum", False))

            if acc_range and len(acc_range) == 2:
                low, high = float(acc_range[0]), float(acc_range[1])
            elif tol is not None:
                low, high = expected - float(tol), expected + float(tol)
            else:
                low, high = expected * 0.90, expected * 1.10

            if float(val) == expected:
                return SteeringDecision(
                    action=SteeringAction.NO_ACTION,
                    scientific_status=ScientificStatus.RECORDED,
                    endpoint="POST /observations",
                    requires_human_approval=False,
                    citations=cites,
                    spoken_response=f"Incubation duration ({val} min) matches the protocol target ({expected:g} min).",
                    rationale="Exact protocol target match.",
                )
            if (is_min and float(val) >= expected) or (low <= float(val) <= high):
                return SteeringDecision(
                    action=SteeringAction.LOG,
                    scientific_status=ScientificStatus.RECORDED,
                    endpoint="POST /observations",
                    requires_human_approval=False,
                    citations=cites,
                    spoken_response=f"Incubation was {val} minutes, within the accepted {low:g}–{high:g} min range. Recorded; no action needed.",
                    rationale=f"{val} min is inside the acceptable range ({low:g}–{high:g} min) for {cid}.",
                )
            affected_flat, affected_struct = trace_affected_dependencies(
                experiment_context, step_id=obs.step_id, global_violation=True
            )
            return SteeringDecision(
                action=SteeringAction.WARN,
                scientific_status=ScientificStatus.PENDING_REVIEW,
                endpoint=f"POST /reviews/{obs.id}",
                requires_human_approval=True,
                violated_constraints=[cid],
                affected_entities=affected_flat,
                affected_structured=affected_struct,
                citations=cites,
                spoken_response=_format_style2_response(
                    f"Incubation duration was {val} minutes, outside the protocol requirement of {expected:g} min (acceptable {low:g}–{high:g} min), affecting all channels/samples.",
                    "You can decide whether to continue and annotate the deviation or repeat the run.",
                    "How would you like to proceed?",
                ),
                rationale=constraint.get("rationale", ""),
            )

        # 7d. Temperature (°C) — supports `acceptable_range_c` and `tolerance_c` (e.g. SC08)
        if mtype == "temperature_c":
            expected = float(constraint.get("expected_value") or active_step.get("temperature_c") or 25)
            acc_range = constraint.get("acceptable_range_c")
            tol = constraint.get("tolerance_c", 2)
            if acc_range and len(acc_range) == 2:
                low, high = float(acc_range[0]), float(acc_range[1])
            else:
                low, high = expected - float(tol), expected + float(tol)

            if float(val) == expected:
                return SteeringDecision(
                    action=SteeringAction.NO_ACTION,
                    scientific_status=ScientificStatus.RECORDED,
                    endpoint="POST /observations",
                    requires_human_approval=False,
                    citations=cites,
                    spoken_response=f"Temperature ({val} °C) matches the protocol specification ({expected:g} °C).",
                    rationale="Temperature matches protocol.",
                )
            if low <= float(val) <= high:
                return SteeringDecision(
                    action=SteeringAction.LOG,
                    scientific_status=ScientificStatus.RECORDED,
                    endpoint="POST /observations",
                    requires_human_approval=False,
                    citations=cites,
                    spoken_response=f"Temperature ({val} °C) is within the acceptable range ({low:g}–{high:g} °C). Logged.",
                    rationale="Temperature within acceptable tolerance.",
                )
            affected_flat, affected_struct = trace_affected_dependencies(
                experiment_context, step_id=obs.step_id, global_violation=True
            )
            return SteeringDecision(
                action=SteeringAction.WARN,
                scientific_status=ScientificStatus.PENDING_REVIEW,
                endpoint=f"POST /reviews/{obs.id}",
                requires_human_approval=True,
                violated_constraints=[cid],
                affected_entities=affected_flat,
                affected_structured=affected_struct,
                citations=cites,
                spoken_response=_format_style2_response(
                    f"Temperature reported as {val} °C; the protocol specifies {expected:g} °C (acceptable {low:g}–{high:g} °C), so all channels are affected.",
                    "Please confirm the temperature and decide whether to annotate the run or adjust conditions.",
                    "How would you like to proceed?",
                ),
                rationale=constraint.get("rationale", ""),
            )

        # 7e. Wash duration (min) or wash count
        if mtype in ("wash_duration_min", "wash_count"):
            expected = float(constraint.get("expected_value", 3))
            if float(val) < expected:
                affected_flat, affected_struct = trace_affected_dependencies(
                    experiment_context, step_id=obs.step_id, global_violation=True
                )
                return SteeringDecision(
                    action=SteeringAction.WARN,
                    scientific_status=ScientificStatus.PENDING_REVIEW,
                    endpoint=f"POST /reviews/{obs.id}",
                    requires_human_approval=True,
                    violated_constraints=[cid],
                    affected_entities=affected_flat,
                    affected_structured=affected_struct,
                    citations=cites,
                    spoken_response=_format_style2_response(
                        f"Wash {mtype} was {val}, below the required {expected:g} ({constraint.get('rule')}), affecting all channels/samples.",
                        "You can complete the remaining wash or annotate the deviation.",
                        "How would you like to proceed?",
                    ),
                    rationale=constraint.get("rationale", ""),
                )
            return SteeringDecision(
                action=SteeringAction.NO_ACTION if float(val) == expected else SteeringAction.LOG,
                scientific_status=ScientificStatus.RECORDED,
                endpoint="POST /observations",
                requires_human_approval=False,
                citations=cites,
                spoken_response=f"Wash ({val}) recorded.",
                rationale="Meets wash requirement.",
            )

        # 7f. Light protection (boolean)
        if mtype == "light_protection":
            expected_bool = constraint.get("expected_value", True)
            if bool(val) != bool(expected_bool):
                affected_flat, affected_struct = trace_affected_dependencies(
                    experiment_context, step_id=obs.step_id, global_violation=True
                )
                return SteeringDecision(
                    action=SteeringAction.WARN,
                    scientific_status=ScientificStatus.PENDING_REVIEW,
                    endpoint=f"POST /reviews/{obs.id}",
                    requires_human_approval=True,
                    violated_constraints=[cid],
                    affected_entities=affected_flat,
                    affected_structured=affected_struct,
                    citations=cites,
                    spoken_response=_format_style2_response(
                        f"Light-sensitive step {obs.step_id} was exposed to direct light, violating {cid}.",
                        "Cover the assay immediately and review whether to re-incubate or annotate.",
                        "Would you like to flag this step for review?",
                    ),
                    rationale=constraint.get("rationale", ""),
                )

        # 7g. Duplicate CV% (>15% triggers multi-cause investigation)
        if mtype == "duplicate_cv_percent":
            max_cv = float(constraint.get("max_allowed", 15))
            if float(val) > max_cv:
                affected_flat, affected_struct = trace_affected_dependencies(
                    experiment_context, location_id=loc, step_id=obs.step_id
                )
                return SteeringDecision(
                    action=SteeringAction.INVESTIGATE,
                    scientific_status=ScientificStatus.PENDING_REVIEW,
                    endpoint="POST /investigate",
                    requires_human_approval=True,
                    violated_constraints=[cid],
                    affected_entities=affected_flat,
                    affected_structured=affected_struct,
                    citations=cites,
                    spoken_response=_format_style2_response(
                        f"Duplicate CV is {val}%, exceeding the {max_cv:g}% limit in {cid}.",
                        "I am triggering a deeper investigation to check prior bubble and wash logs.",
                        "Would you like to review the multi-cause investigation report?",
                    ),
                    rationale=constraint.get("rationale", ""),
                )
            return SteeringDecision(
                action=SteeringAction.NO_ACTION,
                scientific_status=ScientificStatus.RECORDED,
                endpoint="POST /observations",
                requires_human_approval=False,
                citations=cites,
                spoken_response=f"Duplicate CV ({val}%) is within the {max_cv:g}% limit.",
                rationale="Replicate precision acceptable.",
            )

        # 7g.1 Pipette volume tracking (`pipette_volume_ul` — exact -> no_action, within ±5% -> log, outside -> warn)
        if mtype == "pipette_volume_ul":
            expected_vol = float(active_step.get("volume_ul") or constraint.get("expected_value") or 100.0)
            tol_pct = float(constraint.get("tolerance_pct", 5.0))
            low = expected_vol * (1.0 - tol_pct / 100.0)
            high = expected_vol * (1.0 + tol_pct / 100.0)
            if float(val) == expected_vol:
                return SteeringDecision(
                    action=SteeringAction.NO_ACTION,
                    scientific_status=ScientificStatus.RECORDED,
                    endpoint="POST /observations",
                    requires_human_approval=False,
                    citations=cites,
                    spoken_response=f"Pipette volume ({val} µL) matches target ({expected_vol:g} µL). Recorded.",
                    rationale="Exact pipette volume match.",
                )
            if low <= float(val) <= high:
                return SteeringDecision(
                    action=SteeringAction.LOG,
                    scientific_status=ScientificStatus.RECORDED,
                    endpoint="POST /observations",
                    requires_human_approval=False,
                    citations=cites,
                    spoken_response=f"Pipette reading ({val} µL) is within the ±{tol_pct:g}% tolerance ({low:g}–{high:g} µL). Logged.",
                    rationale="Pipette reading within ISO 8655 tolerance.",
                )
            affected_flat, affected_struct = trace_affected_dependencies(
                experiment_context, location_id=loc, step_id=obs.step_id, global_violation=(loc is None)
            )
            return SteeringDecision(
                action=SteeringAction.WARN,
                scientific_status=ScientificStatus.PENDING_REVIEW,
                endpoint=f"POST /reviews/{obs.id}",
                requires_human_approval=True,
                violated_constraints=[cid],
                affected_entities=affected_flat,
                affected_structured=affected_struct,
                citations=cites,
                spoken_response=_format_style2_response(
                    f"Pipetted volume in {loc or obs.step_id} was {val} µL, outside the {expected_vol:g} µL ±{tol_pct:g}% limit ({low:g}–{high:g} µL).",
                    f"You can top up/re-pipette {loc or 'the channel/well'} or annotate the volume deviation.",
                    "How would you like to proceed?",
                ),
                rationale=constraint.get("rationale", ""),
            )

        # 7h. Generic numeric range / max_allowed check (covers Layer-1 PCR temp, cell culture pH, stop-to-read delay)
        max_allowed = constraint.get("max_allowed")
        min_allowed = constraint.get("min_allowed")
        if max_allowed is not None and float(val) > float(max_allowed):
            affected_flat, affected_struct = trace_affected_dependencies(
                experiment_context, location_id=loc, step_id=obs.step_id, global_violation=(loc is None)
            )
            return SteeringDecision(
                action=SteeringAction.WARN,
                scientific_status=ScientificStatus.PENDING_REVIEW,
                endpoint=f"POST /reviews/{obs.id}",
                requires_human_approval=True,
                violated_constraints=[cid],
                affected_entities=affected_flat,
                affected_structured=affected_struct,
                citations=cites,
                spoken_response=_format_style2_response(
                    f"Measured {mtype}={val} {obs.measurement_unit or ''} exceeds limit ({max_allowed}) for rule {cid} ({constraint.get('rule')}).",
                    "You can adjust conditions or annotate the deviation.",
                    "How would you like to proceed?",
                ),
                rationale=constraint.get("rationale", ""),
            )
        if min_allowed is not None and float(val) < float(min_allowed):
            affected_flat, affected_struct = trace_affected_dependencies(
                experiment_context, location_id=loc, step_id=obs.step_id, global_violation=(loc is None)
            )
            return SteeringDecision(
                action=SteeringAction.WARN,
                scientific_status=ScientificStatus.PENDING_REVIEW,
                endpoint=f"POST /reviews/{obs.id}",
                requires_human_approval=True,
                violated_constraints=[cid],
                affected_entities=affected_flat,
                affected_structured=affected_struct,
                citations=cites,
                spoken_response=_format_style2_response(
                    f"Measured {mtype}={val} {obs.measurement_unit or ''} is below minimum ({min_allowed}) for rule {cid} ({constraint.get('rule')}).",
                    "You can adjust conditions or annotate the deviation.",
                    "How would you like to proceed?",
                ),
                rationale=constraint.get("rationale", ""),
            )

        return SteeringDecision(
            action=SteeringAction.NO_ACTION,
            scientific_status=ScientificStatus.RECORDED,
            endpoint="POST /observations",
            requires_human_approval=False,
            citations=cites,
            spoken_response=f"Recorded {mtype}={val} (within limits for {cid}).",
            rationale="Within constraint limits.",
        )

    # 8. Check if question/observation asks about something missing from both Layer 2 and Layer 1 -> abstain
    unverified_cues = (
        "certificate of analysis",
        "lot-specific",
        "lot number",
        "shelf life",
        "expiry",
        "molecular weight",
        "flow rate",
        "channel-priming",
        "priming volume",
        "curve-fitting method",
        "how many spots",
    )
    if obs.measurement_type == "unverified_parameter" or any(cue in text_lower for cue in unverified_cues):
        return SteeringDecision(
            action=SteeringAction.ABSTAIN,
            scientific_status=ScientificStatus.INVALID,
            endpoint="POST /observations",
            requires_human_approval=False,
            violated_constraints=[],
            affected_entities=[],
            citations=["ref_01"],
            spoken_response=(
                "I must abstain from giving a number: that parameter (such as flow rate, volume, or spot count) "
                "is not stated in the cited protocol source (ref_01) or general lab database. Please check your lab's bench sheet."
            ),
            rationale="Requested parameter is not stated in Layer 2 protocol or Layer 1 general lab database; abstaining prevents hallucination.",
        )

    # 9. Default fallback for benign notes -> log
    return SteeringDecision(
        action=SteeringAction.LOG,
        scientific_status=ScientificStatus.RECORDED,
        endpoint="POST /observations",
        requires_human_approval=False,
        violated_constraints=[],
        affected_entities=[],
        citations=_normalize_sources(active_step.get("source")),
        spoken_response=f"Logged note for {obs.step_id}: {obs.content}",
        rationale="General experimental note logged without constraint violation.",
    )
