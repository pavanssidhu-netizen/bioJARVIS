"""
Multi-Database Scientific Literature, Protein & Chemical Search Engine for LABMATE.

Author: Katarina (Person 4 - Scientific Steering & Validation)
Project: LABMATE (Hands-free Multimodal Scientific Laboratory Copilot)

Queries:
  1. Loaded Protocol Database (`science/experiment_seed.json`)
  2. Universal Wet-Lab Rules Database (`science/general_lab_db.json`)
  3. Agentverse Biotech External Databases (`science/biotech_external_db.json`):
     - Literature: PubMed & Europe PMC (`PMID:22565653`, `PMID:35438971`, `PMID:39360812`)
     - Proteins & Structures: UniProtKB & AlphaFold DB (`P06731` CEACAM5/CEA, `P02741` CRP)
     - Molecules & Buffers: PubChem (`CID:24978514` PBS, `CID:448537` Tween-20)
     - Cross-Researcher Reproducibility Run Logs (`run_person_A` vs `run_person_B`)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

_SCIENCE_DIR = Path(__file__).resolve().parents[2] / "science"
_BIOTECH_DB_PATH = _SCIENCE_DIR / "biotech_external_db.json"

try:
    with open(_BIOTECH_DB_PATH, "r", encoding="utf-8") as _f:
        BIOTECH_EXTERNAL_DB: Dict[str, Any] = json.load(_f)
except Exception:
    BIOTECH_EXTERNAL_DB = {
        "pubmed_europe_pmc_records": [],
        "uniprot_alphafold_records": [],
        "pubchem_reagent_records": [],
        "cross_researcher_reproducibility_runs": {"runs": {}},
    }


def search_protocol_and_reference_databases(
    measurement_type: str,
    step_id: str,
    query_text: str,
    experiment_context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Searches across the active protocol database (`experiment_seed.json`) AND the external
    biotech databases (`PubMed / Europe PMC`, `UniProtKB / AlphaFold DB`, `PubChem`).
    """
    matched_refs: List[Dict[str, Any]] = []
    matched_rules: List[Dict[str, Any]] = []
    ref_ids_needed = set()

    for c in experiment_context.get("constraints", []):
        c_type = c.get("measurement_type") or c.get("type") or ""
        applies = c.get("applies_to_step_ids", [])
        if c_type == measurement_type or step_id in applies or step_id == c.get("step_id"):
            matched_rules.append(c)
            src = c.get("source", [])
            if isinstance(src, str):
                ref_ids_needed.add(src)
            elif isinstance(src, list):
                ref_ids_needed.update(src)

    for s in experiment_context.get("steps", []):
        if s.get("step_id") == step_id:
            if s.get("source"):
                ref_ids_needed.add(s["source"])
            if s.get("note"):
                matched_rules.append({"step_id": step_id, "step_note": s["note"], "source": s.get("source")})

    keywords = set(query_text.lower().split()) | {measurement_type.lower()}
    for ev in experiment_context.get("related_evidence", []):
        ref_id = ev.get("ref_id")
        ev_text = f"{ev.get('citation', '')} {ev.get('used_for', '')}".lower()
        if ref_id in ref_ids_needed or any(k in ev_text for k in keywords if len(k) > 3):
            matched_refs.append(ev)

    # Search PubMed / Europe PMC records in biotech_external_db.json
    pubmed_hits: List[Dict[str, Any]] = []
    for pm in BIOTECH_EXTERNAL_DB.get("pubmed_europe_pmc_records", []):
        if (
            pm.get("ref_id") in ref_ids_needed
            or measurement_type in pm.get("relevant_measurements", [])
            or any(k in pm.get("key_findings", "").lower() for k in keywords if len(k) > 3)
        ):
            pubmed_hits.append(pm)

    # Search UniProt / AlphaFold DB records
    analyte_blob = str(experiment_context.get("experiment", {}).get("analyte", "")).lower()
    uniprot_hits: List[Dict[str, Any]] = []
    for up in BIOTECH_EXTERNAL_DB.get("uniprot_alphafold_records", []):
        pname = up.get("protein_name", "").lower()
        if "cea" in analyte_blob and "ceacam5" in pname:
            uniprot_hits.append(up)
        elif "crp" in analyte_blob and "c-reactive" in pname:
            uniprot_hits.append(up)
        elif not uniprot_hits:
            uniprot_hits.append(up)

    # Search PubChem reagent records
    pubchem_hits: List[Dict[str, Any]] = BIOTECH_EXTERNAL_DB.get("pubchem_reagent_records", [])

    return {
        "found": bool(matched_refs or matched_rules or pubmed_hits),
        "matched_protocol_rules": matched_rules,
        "matched_evidence_records": matched_refs,
        "pubmed_europe_pmc_records": pubmed_hits,
        "uniprot_alphafold_records": uniprot_hits,
        "pubchem_reagent_records": pubchem_hits,
        "synthetic_data_disclosure": BIOTECH_EXTERNAL_DB.get("synthetic_data_disclosure", {}),
    }
