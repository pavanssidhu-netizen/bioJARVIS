# LABMATE Scientific Steering Benchmark Report

* **Owner:** Person 4 (Katarina — Scientific Steering & Validation)
* **Architecture:** Layer 1 ([`science/general_lab_db.json`](../science/general_lab_db.json)) + Layer 2 ([`science/experiment_seed.json`](../science/experiment_seed.json))
* **Demo Protocol Verified:** `microfluidic_sandwich_immunoassay_cea` (Microfluidic sandwich immunoassay for CEA (demo))
* **Ryan's Official Answer Key (`science/scientific_cases.json` SC01–SC14):** **14/14 PASS (100.0%)**
* **Full 7-Action + Cross-Assay Suite (`evals/eval_cases.json` SC01–SC17):** **20/20 PASS (100.0%)**

## Expected-Outcome Verification Table

| Case ID | Scenario | Step | Expected Action | Actual Action | Status Tag | Endpoint | Approval Required | Affected Downstream | Result |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `SC01` | Bubble in standard channel CH01 after sample loading | `step_05` | `warn` | `warn` | `pending_review` | `POST /reviews/{id}` | `True` | 1 ch, 1 samples, 7 results | **PASS** |
| `SC02` | Bubble in sample channel CH08 after sample loading | `step_05` | `warn` | `warn` | `pending_review` | `POST /reviews/{id}` | `True` | 1 ch, 1 samples, 1 results | **PASS** |
| `SC03` | Channel-obstructing gas slug in CH09 after sample loading | `step_05` | `warn` | `warn` | `pending_review` | `POST /reviews/{id}` | `True` | 1 ch, 1 samples, 1 results | **PASS** |
| `SC04` | Sample incubation too short (11 min) | `step_05` | `warn` | `warn` | `pending_review` | `POST /reviews/{id}` | `True` | 12 ch, 12 samples, 7 results | **PASS** |
| `SC05` | Sample incubation within tolerance (16 min) | `step_05` | `log` | `log` | `recorded` | `POST /observations` | `False` | None | **PASS** |
| `SC06` | Detection antibody incubation too short (8 min) | `step_07` | `warn` | `warn` | `pending_review` | `POST /reviews/{id}` | `True` | 12 ch, 12 samples, 7 results | **PASS** |
| `SC07` | Wash after sample loading skipped | `step_06` | `warn` | `warn` | `pending_review` | `POST /reviews/{id}` | `True` | 12 ch, 12 samples, 7 results | **PASS** |
| `SC08` | Temperature outside range (30 °C) | `step_05` | `warn` | `warn` | `pending_review` | `POST /reviews/{id}` | `True` | 12 ch, 12 samples, 7 results | **PASS** |
| `SC09` | Clean channel CH07 after sample loading | `step_05` | `no_action` | `no_action` | `recorded` | `POST /observations` | `False` | None | **PASS** |
| `SC10` | Wall glare but no bubbles, CH10 | `step_05` | `no_action` | `no_action` | `recorded` | `POST /observations` | `False` | None | **PASS** |
| `SC11` | Blank / underexposed frame, CH11 | `step_09` | `request_recapture` | `request_recapture` | `invalid` | `POST /vision/analyse` | `False` | None | **PASS** |
| `SC12` | Vague spoken report of a possible bubble | `step_05` | `request_confirmation` | `request_confirmation` | `pending_review` | `POST /observations` | `False` | None | **PASS** |
| `SC13` | Scientist disputes the CH01 bubble detection | `step_05` | `log` | `log` | `pending_review` | `POST /reviews/{id}` | `True` | None | **PASS** |
| `SC14` | Request to skip review on CH01 | `step_05` | `warn` | `warn` | `pending_review` | `POST /reviews/{id}` | `True` | 1 ch, 1 samples, 7 results | **PASS** |
| `SC15` | High replicate CV (22.4%) between spots in CH07 triggers multi-cause investigation | `step_09` | `investigate` | `investigate` | `pending_review` | `POST /investigate` | `True` | 1 ch, 1 samples, 1 results | **PASS** |
| `SC16` | Scientist asks for exact channel flow rate (µL/min) not stated in ref_01 | `step_01` | `abstain` | `abstain` | `invalid` | `POST /observations` | `False` | None | **PASS** |
| `SC17` | Cross-assay General Lab DB test: PCR annealing temperature drift (+2.8 °C) | `step_01` | `warn` | `warn` | `pending_review` | `POST /reviews/{id}` | `True` | 12 ch, 12 samples, 7 results | **PASS** |
| `SC18` | Hands-free pipette reading within tolerance (98 µL for 100 µL target) | `step_05` | `log` | `log` | `recorded` | `POST /observations` | `False` | None | **PASS** |
| `SC19` | Pipette under-dispense error in CH08 (75 µL vs 100 µL target) | `step_05` | `warn` | `warn` | `pending_review` | `POST /reviews/{id}` | `True` | 1 ch, 1 samples, 1 results | **PASS** |
| `SC20` | Hands-free operational lab note (serum sample appearance) | `step_05` | `log` | `log` | `recorded` | `POST /observations` | `False` | None | **PASS** |
