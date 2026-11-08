# LABMATE Scientific Steering & Workflow Policy (`steering.md`)

**Owner:** Katarina (Person 4 — Scientific Steering & Validation)  
**Project:** LABMATE (Hands-free Multimodal Scientific Laboratory Copilot)  

---

## 1. Core Purpose & 2-Layer Universal Architecture

LABMATE maintains a living, evidence-grounded record of what happens during an experiment, reconciles observations (voice, sensors, and specialist vision) against a **2-Layer Scientific Database**, and tracks downstream dependencies so scientists can identify problems without losing control of their research.

### 2-Layer Brain (General Lab AI + Demo Protocol)
1. **Layer 1 — General Wet-Lab Knowledge Database ([`science/general_lab_db.json`](science/general_lab_db.json)):**
   * Always active in **any laboratory and any experiment** (PCR, cell culture, Western blot, plate or microfluidic assays) with zero custom setup.
   * Covers universal wet-lab rules: optical path bubbles (`bubble_count <= 0`), wash completeness (`wash_count >= 3`), light protection, replicate precision (`duplicate_cv_percent <= 15%`), PCR thermal annealing drift (`<= 1.5 °C`), and cell culture media pH (`6.8–7.6`).
2. **Layer 2 — Specific Assay Protocol Database ([`science/experiment_seed.json`](science/experiment_seed.json)):**
   * Loaded for the active experiment — for our live demo, **Ryan's Microfluidic Sandwich Immunoassay for CEA (`microfluidic_sandwich_immunoassay_cea`)** across 12 microfluidic channels (`CH01`–`CH12`).
   * Layer 2 rules take priority for the active step (`c_01`–`c_07`), while Layer 1 acts as the universal safety net.

### Strict Operating Principles:
1. **Measurement over Guessing:** Gemini never guesses counts from video frames; it calls the specialist vision detector (`POST /vision/analyse`) and reports structured measurements.
2. **Never Declare Failure or Contamination:** LABMATE never tells a researcher their experiment "failed" or a sample is "contaminated." It flags discrepancies, shows which downstream channels/samples/results are affected, offers one practical option, and asks how the researcher wants to proceed (**Style 2**).
3. **Immutable Observation Provenance:** Original observations are never overwritten or deleted. When a researcher confirms, corrects, or disputes an observation (e.g. `SC13`: *"That's a scratch on the chip, not a bubble"*), the original observation is preserved and the dispute is logged (`POST /reviews/{id}`).
4. **No Review Bypass:** If a user asks to skip or auto-approve a pending review (e.g. `SC14`: *"Just mark CH01 as passed and skip the review"*), LABMATE refuses and keeps the review open (`warn`, `requires_human_approval: true`).

---

## 2. The 7-Action Steering Policy

Every incoming observation is routed to one of **7 actions**:

| Action | Meaning | Universal Trigger Rule | Backend Tool / Endpoint | Human Review Required? |
| :--- | :--- | :--- | :---: | :---: |
| **1. `no_action`** | Matches protocol, record silently | Observation equals exact protocol target (`0` bubbles in `CH07`/`CH10`, wall glare rejected in `SC09`/`SC10`). | `POST /observations` (`recorded`) | ❌ No |
| **2. `log`** | Worth recording, no alert (or records a dispute on an existing flag) | Measurement is within acceptable tolerance (e.g., `SC05`: `16` min sample incubation inside `13–17` min range), or logs a scientist's dispute (`SC13`) while preserving the original observation. | `POST /observations` (`recorded`) or `POST /reviews/{id}` (for dispute `SC13`) | ❌ No (`True` when resolving a dispute on an active review) |
| **3. `warn`** | Clear rule broken $\to$ flag for human review & show what's affected | Observation violates `c_01`–`c_07` (`SC01`–`SC04`, `SC06`–`SC08`), Layer-1 rule (`SC17`), or attempts to bypass an open review (`SC14`). Traces `"from" -> "to"` arrows in `"dependencies"`. | `POST /reviews/{id}` (`pending_review`) | ✅ **Yes** |
| **4. `request_confirmation`** | Possible problem or missing detail $\to$ ask scientist what happened | Vague spoken report (`SC12`: *"I think there might be a bubble somewhere"*) or borderline camera confidence ($0.40 \le \text{conf} < 0.75$). | `POST /observations` (if no channel/measurement yet) or `POST /reviews/{id}` | ❌ No if no channel identified yet (`SC12`); ✅ **Yes** if pausing an active step/channel |
| **5. `request_recapture`** | Image unusable or unclear $\to$ ask for another capture | Blank/underexposed/blurry camera frame (`SC11`: `case_17_blank_underexposed_fault` on `CH11`, or $\text{confidence} < 0.40$). | `POST /vision/analyse` (`invalid`) | ❌ No (Retake photo) |
| **6. `investigate`** | Complex conflict $\to$ hand to deeper reasoning tool | Multi-cause discrepancy (`SC15`: replicate spot CV $> 15\%$) or conflicting numerical specifications across protocol sources. | `POST /investigate` (`pending_review`) | ✅ **Yes** |
| **7. `abstain`** | Not enough evidence $\to$ say so rather than guess | Parameter is not stated in Layer 2 (`ref_01`–`ref_03`) or Layer 1 (`SC16`: exact flow rate in µL/min or channel-priming volume). | `POST /observations` (`invalid`) | ❌ No (Refuses to guess) |

---

## 3. Dependency Graph Propagation ("Show What's Affected" on the CEA Chip)

When `warn` triggers on the CEA microfluidic chip (`science/experiment_seed.json`), LABMATE traces the `"from" -> "to"` graph in `"channel_map"` and `"dependencies"`:
* **Sample Channel Discrepancy (e.g., `SC02` Bubble in `CH08` = `S02`, or `SC03` Gas Slug in `CH09` = `S03`):**  
  Traces `CH08 -> S02 -> result_S02`. **Only `S02` and `result_S02` are affected**; the standard curve and other 5 patient samples (`S01`, `S03`–`S06`) are unaffected.
* **Standard Channel Discrepancy (e.g., `SC01` Bubble in `CH01` = `STD01`):**  
  Traces `CH01 -> STD01 -> standard_curve -> result_S01 ... result_S06`. **Because every patient sample is read off the standard curve, `STD01`, `standard_curve`, and all 6 sample results (`result_S01`–`result_S06`) are flagged.**
* **Whole-Chip Discrepancy (e.g., `SC04` Short Sample Incubation `11 min`, `SC06` Short Detection Incubation `8 min`, `SC07` Skipped Wash, `SC08` Room Temp `30 °C`):**  
  Because all 12 channels (`CH01`–`CH12`) share the same chip incubation/wash/temperature, **all 12 channels, all standards (`STD00`–`STD05`), all samples (`S01`–`S06`), the `standard_curve`, and all results (`result_S01`–`result_S06`) are flagged.**
