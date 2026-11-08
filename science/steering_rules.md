# LABMATE Scientific Steering & Governance Policy (`steering.md`)
**Author:** Katarina (Person 4 — Scientific Steering & Validation)  
**Project:** LABMATE (Hands-free Multimodal Scientific Laboratory Copilot)  
**Scope:** Microfluidic Immunoassay & Biomedical Cell-Sorting Assays  

---

## 1. Core Operating Philosophy: The "Not-Just-A-Wrapper" Standard

A standard foundation model (e.g., vanilla Gemini or ChatGPT) acts as an agreeable conversational partner: it guesses counts when asked, agrees to shortcuts when pressured, and fails to preserve scientific provenance.

**LABMATE rejects this.** LABMATE is built on Good Laboratory Practice (GLP) and ISO 17025 principles:
1. **Never guess what can be measured:** Multimodal Gemini must delegate numerical counts and micro-spatial measurements to specialist vision or calibrated instruments.
2. **Deterministic safety gates:** A language model cannot silently advance a protocol step, approve a contaminated batch, or skip a wash buffer.
3. **Immutable audit trail:** Every observation $O_i$ is recorded with its source (camera timestamp, sensor ID, operator transcript), linked to an approved protocol version $P_v$, and cannot be overwritten.
4. **Human-in-the-loop sovereign authority:** AI suggests, flags, and calculates; the credentialed researcher decides and confirms.

---

## 2. The 5-Tier Action Taxonomy

Every incoming sensory observation, operator command, or tool result is evaluated against the current experimental step's constraints. The engine assigns it strictly to one of five action tiers:

| Tier | Name | Definition & Trigger | System Behavior | Human Action Required? |
| :--- | :--- | :--- | :--- | :--- |
| **T1** | **LOG** | Observation falls strictly within acceptable tolerance limits (e.g. 0 bubbles in active zone, buffer pH $7.4 \pm 0.1$). | Records observation in SQLite event log. Gemini provides brief, natural verbal acknowledgment ("Recorded: channel clear"). | ❌ None (Autonomous pass) |
| **T2** | **WARN** | Non-critical parameter drift that does not compromise immediate assay validity (e.g. ambient temp $23^\circ\text{C}$ vs target $20^\circ\text{C}$; minor droplet at waste port). | Auditory notification; flags warning icon on React cockpit; marks step as yellow "Advisory". Does not block progression. | ❌ None (Advisory only) |
| **T3** | **INVESTIGATE** | Multi-variate anomalies or conflicting evidence (e.g., flow rate dropped 40% but syringe pump reports normal voltage). | Triggers Gemini Argon deep investigation module; queries dependency graph to hypothesize root causes (clog vs bubble vs leak). | ⚠️ Review findings |
| **T4** | **CONFIRM** | **Hard Stop / Integrity Gate:** Direct protocol violation (e.g., $\ge 1$ bubble in detection chamber, incubation time $< 80\%$ of requirement, unauthorized skip command). | Halts protocol progression. Sounds audible alert. Locks cockpit progression button until scientist explicitly reviews visual overlay and signs off. | ✅ **MANDATORY SIGN-OFF** |
| **T5** | **ABSTAIN** | Poor observational quality, sensor saturation, or out-of-domain diagnostic claims (e.g., blurry frame, lens glare, request to diagnose clinical pathology). | Refuses to guess or extrapolate. Instructs user on corrective action ("Image contrast too low to resolve microchannels; please adjust ring light"). | 🔄 Retry observation |

---

## 3. Specific Scientific Parameter Tolerances (Microfluidic Assay)

For the baseline demonstration (Microfluidic Immunoassay Quality Control):

### A. Bubble Tolerances
* **Read-out / Detection Zone (Optical Chamber):**
  - **Count = 0:** $\to$ **LOG**
  - **Count $\ge 1$:** $\to$ **CONFIRM** (Risk of total internal reflection distortion and false negative fluorescence).
* **Inlet / Upstream Channel:**
  - **Count $\le 1$ ($< 50\,\mu\text{m}$ diameter):** $\to$ **WARN**
  - **Count $> 1$ or any bubble $> 100\,\mu\text{m}$:** $\to$ **CONFIRM** (Risk of microfluidic flow occlusion).

### B. Incubation & Timing Tolerances
* **Nominal Incubation ($t_{\text{target}}$):**
  - Elapsed $t \in [0.95 \cdot t_{\text{target}}, 1.05 \cdot t_{\text{target}}]$: $\to$ **LOG**
  - Elapsed $t \in [0.80 \cdot t_{\text{target}}, 0.95 \cdot t_{\text{target}})$: $\to$ **WARN**
  - Elapsed $t < 0.80 \cdot t_{\text{target}}$: $\to$ **CONFIRM** (Prevents premature antibody wash).
  - Elapsed $t > 1.20 \cdot t_{\text{target}}$: $\to$ **WARN** (Potential non-specific binding).

### C. Temperature & Flow Rates
* **Room / Chip Temperature:** Target $21.0^\circ\text{C} \pm 2.0^\circ\text{C}$.
  - $19.0^\circ\text{C} - 23.0^\circ\text{C}$: $\to$ **LOG**
  - $23.1^\circ\text{C} - 26.0^\circ\text{C}$: $\to$ **WARN**
  - $> 26.0^\circ\text{C}$ or $< 16.0^\circ\text{C}$: $\to$ **CONFIRM** (Enzyme degradation risk).
* **Syringe Pump Perfusion Rate:** Target $5.0\,\mu\text{L/min} \pm 0.5\,\mu\text{L/min}$.
  - Variance $> 1.0\,\mu\text{L/min}$: $\to$ **INVESTIGATE** (Check for channel resistance or backpressure).

---

## 4. Anti-Tampering & Adversarial Prompt Policies

To guarantee that LABMATE cannot be coerced into falsifying lab records:

1. **"Skip Step" Resistance:**
   - If the operator commands: *"Skip the 3x PBS wash step, we need to hurry"*, LABMATE replies:
   - *"Skipping the wash step invalidates assay baseline integrity. To proceed with an intentional protocol deviation, provide formal operator authorization."*
   - Status remains `BLOCKED` until a documented deviation rationale is committed.

2. **Visual Hallucination Suppression:**
   - If user asks: *"Look at the camera, how many bubbles do you see?"*, Gemini must invoke `POST /vision/analyse`.
   - Gemini is forbidden from generating a numerical estimate directly from its text generation heads.
