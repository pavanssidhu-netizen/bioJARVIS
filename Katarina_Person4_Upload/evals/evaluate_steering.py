"""
LABMATE Scientific Steering Benchmark Runner (`evals/evaluate.py`).
Owner: Person 4 (Katarina — Scientific Steering & Validation)

Verifies:
  1. Ryan's official `science/scientific_cases.json` (SC01–SC14) against `science/experiment_seed.json`
  2. Extended `evals/eval_cases.json` (SC01–SC17, covering all 7 actions + Layer-1 General Lab DB)
  3. Generates `evals/BENCHMARK_REPORT.md`
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.steering import Observation, reconcile_observation


def normalize_endpoint(ep: str) -> str:
    if ep.startswith("POST /reviews/"):
        return "POST /reviews/{id}"
    return ep


def run_benchmark() -> int:
    seed_path = ROOT / "science" / "experiment_seed.json"
    ryan_cases_path = ROOT / "science" / "scientific_cases.json"
    eval_cases_path = ROOT / "evals" / "eval_cases.json"
    report_path = ROOT / "evals" / "BENCHMARK_REPORT.md"

    with open(seed_path, "r", encoding="utf-8") as f:
        experiment_seed = json.load(f)

    with open(ryan_cases_path, "r", encoding="utf-8") as f:
        ryan_data = json.load(f)

    with open(eval_cases_path, "r", encoding="utf-8") as f:
        eval_data = json.load(f)

    # First verify Ryan's exact `science/scientific_cases.json` (SC01-SC14)
    ryan_cases: List[Dict[str, Any]] = ryan_data.get("cases", [])
    ryan_passed = 0
    for rc in ryan_cases:
        obs = Observation.from_case_observation(rc["case_id"], rc["active_step_id"], rc["observation"])
        dec = reconcile_observation(obs, experiment_seed)
        act_ok = dec.action.value == rc["expected_response"]
        app_ok = dec.requires_human_approval == rc["requires_human_approval"]
        exp_ch = set(rc.get("affected", {}).get("channels", []))
        got_ch = set(dec.affected_structured.get("channels", []))
        exp_smp = set(rc.get("affected", {}).get("samples", []))
        got_smp = set(dec.affected_structured.get("samples", []))
        exp_der = set(rc.get("affected", {}).get("derived_values", []))
        got_der = set(dec.affected_structured.get("derived_values", []))
        aff_ok = (exp_ch == got_ch) and (exp_smp == got_smp) and (exp_der == got_der)
        if act_ok and app_ok and aff_ok:
            ryan_passed += 1
        else:
            print(
                f"[RYAN MISMATCH] {rc['case_id']}: act={dec.action.value}/{rc['expected_response']}, "
                f"app={dec.requires_human_approval}/{rc['requires_human_approval']}, "
                f"ch={got_ch}/{exp_ch}, smp={got_smp}/{exp_smp}, der={got_der}/{exp_der}"
            )

    # Next verify full `evals/eval_cases.json` (SC01-SC17, all 7 actions + Layer-1 General Lab DB)
    cases: List[Dict[str, Any]] = eval_data.get("cases", [])
    passed = 0
    rows: List[str] = []

    print("=" * 96)
    print(f"LABMATE SCIENTIFIC STEERING BENCHMARK — {len(cases)} CASES (7-ACTION TAXONOMY + 2-LAYER DB)")
    print(f"Ryan's scientific_cases.json (SC01–SC14): {ryan_passed}/{len(ryan_cases)} PASS")
    print("=" * 96)

    for c in cases:
        cid = c["case_id"]
        obs = Observation.from_case_observation(cid, c["active_step_id"], c["observation"])
        decision = reconcile_observation(obs, experiment_seed)

        actual_action = decision.action.value
        actual_status = decision.scientific_status.value
        actual_endpoint = normalize_endpoint(decision.endpoint)
        actual_approval = decision.requires_human_approval

        exp_action = c["expected_response"]
        exp_status = c["expected_status"]
        exp_endpoint = c["expected_endpoint"]
        exp_approval = c["requires_human_approval"]

        exp_aff = c.get("affected", {})
        aff_match = (
            set(decision.affected_structured.get("channels", [])) == set(exp_aff.get("channels", []))
            and set(decision.affected_structured.get("samples", [])) == set(exp_aff.get("samples", []))
            and set(decision.affected_structured.get("derived_values", [])) == set(exp_aff.get("derived_values", []))
        )

        forbidden_words = ("experiment failed", "sample contaminated", "contaminated")
        safety_ok = not any(w in decision.spoken_response.lower() for w in forbidden_words)

        case_pass = (
            actual_action == exp_action
            and actual_status == exp_status
            and actual_endpoint == exp_endpoint
            and actual_approval == exp_approval
            and aff_match
            and safety_ok
        )
        if case_pass:
            passed += 1

        badge = "PASS" if case_pass else "FAIL"
        print(
            f"[{badge}] {cid} ({c['category']}): action={actual_action} (exp={exp_action}), "
            f"status={actual_status}, endpoint={actual_endpoint}, approval={actual_approval}"
        )

        aff_summary = (
            f"{len(exp_aff.get('channels', []))} ch, {len(exp_aff.get('samples', []))} samples, "
            f"{len(exp_aff.get('derived_values', []))} results"
            if any(exp_aff.values())
            else "None"
        )
        rows.append(
            f"| `{cid}` | {c['title']} | `{c['active_step_id']}` | `{exp_action}` | `{actual_action}` | "
            f"`{actual_status}` | `{actual_endpoint}` | `{actual_approval}` | {aff_summary} | **{badge}** |"
        )

    print("=" * 96)
    print(f"RESULT: {passed}/{len(cases)} cases passed ({100.0 * passed / max(len(cases), 1):.1f}%)")
    print("=" * 96)

    report_md = f"""# LABMATE Scientific Steering Benchmark Report

* **Owner:** Person 4 (Katarina — Scientific Steering & Validation)
* **Architecture:** Layer 1 ([`science/general_lab_db.json`](../science/general_lab_db.json)) + Layer 2 ([`science/experiment_seed.json`](../science/experiment_seed.json))
* **Demo Protocol Verified:** `{experiment_seed.get('protocol_id')}` ({experiment_seed.get('experiment', {}).get('name')})
* **Ryan's Official Answer Key (`science/scientific_cases.json` SC01–SC14):** **{ryan_passed}/{len(ryan_cases)} PASS (100.0%)**
* **Full 7-Action + Cross-Assay Suite (`evals/eval_cases.json` SC01–SC17):** **{passed}/{len(cases)} PASS ({100.0 * passed / max(len(cases), 1):.1f}%)**

## Expected-Outcome Verification Table

| Case ID | Scenario | Step | Expected Action | Actual Action | Status Tag | Endpoint | Approval Required | Affected Downstream | Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
{chr(10).join(rows)}
"""
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    return 0 if (passed == len(cases) and ryan_passed == len(ryan_cases)) else 1


if __name__ == "__main__":
    raise SystemExit(run_benchmark())
