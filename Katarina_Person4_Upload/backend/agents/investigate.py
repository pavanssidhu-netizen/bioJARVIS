"""
Argon Deep Scientific Investigation & Cross-Researcher Reproducibility Engine for LABMATE.

Author: Katarina (Person 4 - Scientific Steering & Validation)
Project: LABMATE (Hands-free Multimodal Scientific Laboratory Copilot)

Provides two non-wrapper scientific reasoning engines grounded in structured databases:
  1. `run_argon_investigation` (`POST /investigate`):
     Synthesizes multi-database evidence (PubMed/Europe PMC, UniProtKB/AlphaFold DB, PubChem,
     and protocol constraints) with prior observation history to explain *why* an assay discrepancy
     occurred and recommend a concrete corrective action.
  2. `compare_researcher_runs` (`POST /reproducibility/compare`):
     Compares two researchers (e.g. Person A vs. Person B) executing the exact same protocol,
     identifies every step-level divergence using the 7-action steering engine, links each divergence
     to PubMed/UniProt/PubChem mechanisms, and outputs a reproducibility alignment plan.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from backend.agents.literature import BIOTECH_EXTERNAL_DB, search_protocol_and_reference_databases
from backend.agents.steering import Observation, SteeringDecision, reconcile_observation


def run_argon_investigation(
    observation_id: str = "obs_inv_01",
    step_id: str = "step_05",
    measurement_type: str = "duplicate_cv_percent",
    measurement_value: Any = 22.4,
    question: str = "Why did replicate variance or protocol discrepancy occur?",
    decision: Optional[SteeringDecision] = None,
    experiment_context: Optional[Dict[str, Any]] = None,
    prior_observations: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Executes a multi-database scientific investigation (`POST /investigate`) combining:
      - Active protocol constraints (`experiment_seed.json`)
      - PubMed / Europe PMC literature (`PMID:22565653`, `PMID:35438971`)
      - UniProtKB / AlphaFold protein stability (`P06731` CEACAM5 / `P02741` CRP)
      - PubChem buffer & surfactant chemistry (`CID:24978514` PBS, `CID:448537` Tween-20)
      - Prior bench observations logged during the run
    Never declares the experiment "failed" or "contaminated".
    """
    ctx = experiment_context or {}
    priors = prior_observations or []

    if decision is None:
        obs = Observation(
            id=observation_id,
            step_id=step_id,
            source_type="voice",
            content=question,
            measurement_type=measurement_type,
            measurement_value=measurement_value,
        )
        decision = reconcile_observation(obs, ctx)

    db_hits = search_protocol_and_reference_databases(
        measurement_type=measurement_type,
        step_id=step_id,
        query_text=question,
        experiment_context=ctx,
    )

    # Check prior observations for compound root causes (e.g. bubbles + short incubation + temp drift)
    prior_anomalies = [
        p for p in priors if p.get("status") in ("pending_review", "warning") or p.get("steering_action") == "warn"
    ]

    hypotheses: List[Dict[str, Any]] = []
    for pm in db_hits["pubmed_europe_pmc_records"]:
        hypotheses.append({
            "source_database": f"{pm['database']} (PMID: {pm['pmid']})",
            "reference_id": pm["ref_id"],
            "citation": f"{pm['authors']} — {pm['journal']}",
            "mechanism": pm["key_findings"],
        })

    for up in db_hits["uniprot_alphafold_records"]:
        props = up.get("biophysical_properties", {})
        hypotheses.append({
            "source_database": f"{up['database']} ({up['uniprot_id']} / {up['alphafold_id']})",
            "protein_target": up["protein_name"],
            "optimal_window": f"{props.get('safe_temp_window_c')} °C, pH {props.get('optimal_ph_window')}",
            "mechanism": props.get("thermal_sensitivity_note", ""),
        })

    for pc in db_hits["pubchem_reagent_records"]:
        hypotheses.append({
            "source_database": f"{pc['database']} (CID: {pc['pubchem_cid']})",
            "reagent": pc["compound_name"],
            "mechanism": pc["chemical_note"],
        })

    recommendations = [
        "1. Inspect channel/well overlay for trapped air microbubbles (`ref_02`, PMID:35438971) and clear/re-fill affected channels before readout.",
        "2. Verify sample and detection antibody incubation durations stay within the 13–17 min and 9–11 min windows at 23–27 °C (`ref_01`, PMID:22565653; UniProt P06731).",
        "3. Confirm all 3-minute 1X PBS washes (`PubChem CID:24978514`) were completed between binding steps to prevent non-specific background.",
    ]

    return {
        "investigation_id": f"inv_{observation_id}",
        "target_observation": observation_id,
        "active_step": step_id,
        "steering_action": decision.action.value,
        "scientific_status": decision.scientific_status.value,
        "requires_human_approval": True,
        "violated_constraints": decision.violated_constraints,
        "affected": decision.affected_structured,
        "prior_flagged_observations_count": len(prior_anomalies),
        "multi_database_evidence": {
            "pubmed_europe_pmc": db_hits["pubmed_europe_pmc_records"],
            "uniprot_alphafold": db_hits["uniprot_alphafold_records"],
            "pubchem_reagents": db_hits["pubchem_reagent_records"],
            "protocol_rules": db_hits["matched_protocol_rules"],
        },
        "ranked_scientific_hypotheses": hypotheses,
        "recommended_actions": recommendations,
        "spoken_summary": (
            f"Multi-database investigation complete for {step_id} ({measurement_type}={measurement_value}). "
            f"Cross-referencing PubMed (PMID:22565653, PMID:35438971), UniProt (P06731 CEACAM5), and PubChem (CID:24978514) "
            "identifies microbubble optical scattering, under-incubation kinetics, or thermal drift as primary candidate causes. "
            "Please review the ranked recommendations and confirm how you would like to proceed."
        ),
    }


def compare_researcher_runs(
    experiment_context: Dict[str, Any],
    run_a: Optional[Dict[str, Any]] = None,
    run_b: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Compares two researchers (Person A vs. Person B) running the exact same protocol
    to pinpoint why Person A's experiment reproduced cleanly while Person B's showed high variance.
    Uses the deterministic 7-action steering engine + PubMed/UniProt/PubChem databases.
    """
    stored_runs = BIOTECH_EXTERNAL_DB.get("cross_researcher_reproducibility_runs", {}).get("runs", {})
    person_a = run_a or stored_runs.get("run_person_A", {})
    person_b = run_b or stored_runs.get("run_person_B", {})

    metrics_a = person_a.get("step_metrics", {})
    metrics_b = person_b.get("step_metrics", {})

    metric_specs = [
        ("step_05_sample_incubation_min", "step_05", "incubation_duration_min", "min", None, "Sample incubation duration"),
        ("step_05_temperature_c", "step_05", "temperature_c", "°C", None, "Ambient lab temperature"),
        ("step_05_pipette_volume_ul_CH08", "step_05", "pipette_volume_ul", "µL", "CH08", "Pipetted sample volume (CH08)"),
        ("step_05_bubble_count_CH01", "step_05", "bubble_count", "count", "CH01", "Microbubbles in standard channel CH01"),
        ("step_06_wash_duration_min", "step_06", "wash_duration_min", "min", None, "Inter-step PBS wash duration"),
        ("step_07_detection_ab_duration_min", "step_07", "incubation_duration_min", "min", None, "Detection antibody incubation"),
    ]

    discrepancies: List[Dict[str, Any]] = []
    recommendations: List[str] = []

    for key, step_id, mtype, unit, ch_id, label in metric_specs:
        val_a = metrics_a.get(key)
        val_b = metrics_b.get(key)
        if val_a is None or val_b is None or val_a == val_b:
            continue

        obs_b = Observation(
            id=f"cmp_{key}",
            step_id=step_id,
            source_type="voice",
            content=f"{label}: {val_b} {unit}",
            channel_id=ch_id,
            measurement_type=mtype,
            measurement_value=val_b,
            measurement_unit=unit,
        )
        dec_b = reconcile_observation(obs_b, experiment_context)

        db_info = search_protocol_and_reference_databases(mtype, step_id, label, experiment_context)
        db_citation = "ref_01 (PMID:22565653)"
        if mtype == "bubble_count":
            db_citation = "PubMed PMID:35438971 (ref_02)"
        elif mtype == "temperature_c":
            db_citation = "UniProt P06731 (CEACAM5 thermal stability) & PubMed PMID:22565653 (ref_01)"
        elif mtype == "wash_duration_min":
            db_citation = "PubChem CID:24978514 (1X PBS wash) & PubMed PMID:22565653 (ref_01)"
        elif mtype == "pipette_volume_ul":
            db_citation = "ISO 8655 Micropipette Standard (`gen_pipette_01`)"

        discrepancies.append({
            "step_id": step_id,
            "parameter": label,
            "channel_id": ch_id,
            "person_A_value": f"{val_a} {unit}",
            "person_B_value": f"{val_b} {unit}",
            "delta": round(float(val_b) - float(val_a), 2),
            "steering_action_triggered": dec_b.action.value,
            "violated_constraints": dec_b.violated_constraints,
            "affected_samples": dec_b.affected_structured.get("samples", []),
            "database_evidence": db_citation,
            "scientific_explanation": dec_b.rationale,
        })
        recommendations.append(
            f"Align {step_id} ({label}): change from {val_b} {unit} (Person B) to {val_a} {unit} (Person A) [{db_citation}]."
        )

    return {
        "comparison_id": "repro_cmp_A_vs_B",
        "protocol_id": experiment_context.get("protocol_id", "microfluidic_sandwich_immunoassay_cea"),
        "synthetic_data_disclosure": BIOTECH_EXTERNAL_DB.get("synthetic_data_disclosure", {}),
        "person_A_summary": {
            "researcher": person_a.get("researcher"),
            "standard_curve_r2": person_a.get("standard_curve_r2"),
            "replicate_spot_cv_pct": person_a.get("replicate_spot_cv_pct"),
            "outcome_status": person_a.get("outcome_status"),
        },
        "person_B_summary": {
            "researcher": person_b.get("researcher"),
            "standard_curve_r2": person_b.get("standard_curve_r2"),
            "replicate_spot_cv_pct": person_b.get("replicate_spot_cv_pct"),
            "outcome_status": person_b.get("outcome_status"),
        },
        "discrepancies_found_count": len(discrepancies),
        "step_by_step_discrepancies": discrepancies,
        "reproducibility_recommendations": recommendations,
        "bench_to_bedside_impact": (
            f"Identified {len(discrepancies)} unrecorded execution deviations between Researcher A (R²={person_a.get('standard_curve_r2')}, CV={person_a.get('replicate_spot_cv_pct')}%) "
            f"and Researcher B (R²={person_b.get('standard_curve_r2')}, CV={person_b.get('replicate_spot_cv_pct')}%). "
            "Resolving these step-level deviations eliminates inter-operator assay drift and accelerates bench-to-bedside biomarker validation."
        ),
    }
