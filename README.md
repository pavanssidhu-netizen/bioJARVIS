# LABMATE (`bioJARVIS`) — Hands-Free Multimodal Scientific Copilot & Specialist Perception Agent

**UCL Agentverse 2026 · Biotech Track · Team bioJARVIS**

> *"LABMATE doesn't simply interpret experiments through a foundation model. It combines live multimodal interaction, specialised scientific perception, persistent experimental state and verifiable reasoning to support reproducible laboratory work."*

---

## 1. The Biomedical Problem & Named User (Biotech Track Slide 11 & 14)

- **Named User**: Wet-lab scientist / assay technician running microfluidic immunoassays or multi-well diagnostic protocols with gloved hands.
- **Specific Bottleneck**: Microbubbles and incomplete channel filling in microfluidic chips and diagnostic wells obstruct flow or distort optical/fluorescent readouts ([Analytical Chemistry 2022](https://pubmed.ncbi.nlm.nih.gov/35438971/); [Microbubble Immunoassay Quantification 2026](https://pubmed.ncbi.nlm.nih.gov/)). Meanwhile, general-purpose Vision-Language Models (VLMs) struggle to count translucent overlapping bubbles, hallucinate spatial coordinates, or get fooled by channel-wall meniscus glare and camera-border clipping.
- **Why LABMATE Is Not an LLM Wrapper**:
  1. **Multi-Step Autonomous Perception & Sceptic Agent (`backend/vision/`)**: Instead of asking Gemini to "guess" bubble counts from a raw photo, our agent executes a 6-step tool chain (`Frame Quality & Calibration Gate` → `Adaptive CLAHE + Specular Glare Inpainting` → `Hybrid PyTorch YOLOv8-seg + Marker-Controlled Watershed` → `Autonomous 2x Super-Sampled ROI Cluster Zoom` → `Perception Sceptic Physics + PyTorch Patch CNN Audit` → `PyTorch Biochemical Yield Forecast + Gaussian Process Bayesian Active Correction`).
  2. **3D Biophysical Spheroid Geometry (`backend/vision/geometry.py`)**: Fits Mikaelian split-ellipses ($a, b_1, b_2$) to every segmented mask and computes **Prolate vs. Oblate 3D Gas Volume intervals** $[V_{\text{prolate}}, V_{\text{oblate}}]$, **Sauter Mean Diameter ($d_{32}$)**, and **Optical Path / Channel Obstruction Ratio ($\Phi_{\text{obs}} = d_{\text{eq}} / W_{\text{channel}}$)**.
  3. **In-House Trained PyTorch Models + Gaussian Process Bayesian Optimizer (`backend/vision/patch_classifier.py`, `backend/vision/predictive_models.py`)**:
     - **`BubblePatchCNN`**: 3-stage PyTorch CNN (`Conv2d(1->16->32->64)`) trained on disjoint phase-contrast patches (`100.0%` held-out validation accuracy, `F1 = 1.000`, `evals/patch_cnn_metrics.json`).
     - **`BiochemicalYieldMLP`**: Dual-head PyTorch MLP trained on 840 assay logs and evaluated on 360 held-out runs (**Held-Out $R^2 = 0.9792$**, **`MAE = 1.804%`**, **`Failure Accuracy = 94.44%`**, `evals/yield_model_metrics.json`).
     - **`GaussianProcessBayesianOptimizer`**: Exact GP surrogate + analytic **Expected Improvement (EI)** acquisition that recommends compensatory reagent top-up ($\pm\mu\text{L}$), incubation extension ($+s$), and flow/centrifugation actions before irreversible steps occur.
  4. **Person 2 (Ryan) R&D Systems Human CRP Sandwich ELISA (`DY1707`) & 64-Edge Dependency Graph (`backend/experiment_seed.json`)**: Automatically checks constraint `c_01` (`no bubbles before 450 nm read`, `ref_04`, `ref_05`) and propagates bubble impact across Ryan's 64 dependency edges (`STD01 -> standard_curve -> result_S01..result_S16`).
  5. **Immutable Observation Store & Mandatory Human-in-the-Loop Sign-Off (`POST /reviews/{id}`)**: Every observation is committed as `status: "pending_review"` (or `"abstained_low_quality"` on corrupted/blank frames). The agent **never** modifies approved protocol state or declares an experiment failed without explicit scientist sign-off.

---

## 2. Repository Structure

```text
bioJARVIS/
├── .agents/skills/                     # Agentverse skills (review-and-push, finance-*)
├── backend/
│   ├── main.py                         # FastAPI Gateway (all frozen endpoints + /predictive/optimise) + Live Cockpit
│   ├── contracts.py                    # Shared Pydantic schemas (Observation & Experiment Context contracts)
│   ├── experiment_seed.json            # Person 2 (Ryan): R&D Systems DY1707 Human CRP ELISA (8 steps, 96-well map, 64 deps)
│   └── vision/                         # Person 3 (Yeeyee): Specialist Perception, Sceptic & Bayesian Agent Brain
│       ├── geometry.py                 # Mikaelian split-ellipse + 3D Prolate/Oblate spheroid volume & d32 solver
│       ├── inference.py                # Hybrid PyTorch YOLO-seg + Phase-Boundary Watershed + Overlay renderer
│       ├── patch_classifier.py         # Custom-trained PyTorch BubblePatchCNN verifier (Val F1 = 1.000)
│       ├── predictive_models.py        # PyTorch BiochemicalYieldMLP (R^2 = 0.9792) + GP Bayesian Expected Improvement
│       ├── agent.py                    # 6-step Autonomous Perception + Sceptic + Bayesian Agent
│       └── adapter.py                  # FastAPI/Live-Camera adapter (`analyse_image`, `analyse_live_camera_frame`)
├── evals/
│   ├── vision_test/                    # 18 held-out annotated test cases, ground-truth labels, and overlays
│   ├── evaluate.py                     # 3-Way Scientific Benchmark runner (Baseline A vs. B vs. Agent C)
│   ├── results.json                    # Machine-readable vision benchmark output
│   ├── patch_cnn_metrics.json          # Held-out validation metrics for PyTorch BubblePatchCNN
│   ├── yield_model_metrics.json        # Held-out test metrics (R^2 = 0.9792) for PyTorch BiochemicalYieldMLP
│   └── REPORT.md                       # Complete evaluation report & dataset licence table
├── tests/
│   └── test_vision_agent.py            # 5 automated unit & integration tests (geometry, Sceptic, Bayesian, ELISA graph)
├── .env.example                        # Safe environment variable template (NEVER commit real .env)
├── .gitignore                          # Blocks secrets, .env, .venv, and large .pt model weights
└── requirements.txt
```

---

## 3. Quick Start & Live Judge Demo Commands

### Prerequisites
- Python 3.9+

### Installation
```powershell
py -3 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

*(Optional)* Copy `.env.example` to `.env` and set `GEMINI_API_KEY` to enable live Gemini (`gemini-3.8-flash`) scientific synthesis alongside the specialist perception agent.

### 1. Run the 3-Way Scientific Benchmark (`evals/evaluate.py`)
Generates the 18 held-out test cases (`evals/vision_test/`), runs **(A) Single-Shot Baseline**, **(B) Specialist CV Single-Pass**, and **(C) LABMATE Multi-Step Perception + Sceptic Agent**, saves annotated visual overlays to `evals/vision_test/overlays/`, and writes [`evals/REPORT.md`](evals/REPORT.md):
```powershell
.\.venv\Scripts\python.exe evals/evaluate.py
```

### 2. Inspect Any Single Image via CLI (`backend/vision/adapter.py`)
```powershell
.\.venv\Scripts\python.exe -m backend.vision.adapter evals/vision_test/images/case_09_channel_obstruction_slug.png
```

### 3. Launch the Live Interactive Judge Test Cockpit & FastAPI Server (`backend/main.py`)
```powershell
.\.venv\Scripts\uvicorn.exe backend.main:app --host 127.0.0.1 --port 8000
```
Then open **`http://127.0.0.1:8000`** in your browser to test any held-out case or upload a brand-new image live during the 2-minute judge test!

### 4. Run Automated Tests
```powershell
.\.venv\Scripts\pytest.exe -q
```

---

## 4. Datasets, References & Licences (Biotech Track Slide 12 Compliance)

| Resource | Purpose in LABMATE | Licence & Attribution |
| :--- | :--- | :--- |
| **kLarity** ([`maxsiska/kLarity`](https://github.com/maxsiska/kLarity), Zenodo `10.5281/zenodo.19582132`) | Mikaelian split-ellipse (`a`, `b1`, `b2`), 3D Prolate/Oblate spheroid volume & surface area equations, and border-contact filtering rule (`border_contact_px / d_eq > 1.0`). | **AGPL-3.0 / CC-BY 4.0** (Willer, Siska et al., DTU, 2026) |
| **BubbleID** ([`cldunlap73/BubbleID`](https://github.com/cldunlap73/BubbleID), OSF `3nwyx`) | Bubble interface dynamics & tracking benchmark reference. | **MIT License** (Dunlap et al., NED³ Lab, J. Appl. Phys.) |
| **LABMATE Held-Out Optical Benchmark Suite (`evals/vision_test/`)** | 18 controlled microfluidic channel test images with exact pixel-level ground truth (clean negatives, wall-glare artifacts, border-clipped menisci, touching clusters, channel-obstructing slugs, and blank camera faults). | **Explicitly Labelled Synthetic Benchmark Data** per Agentverse Slide 12. Zero patient data used. |

---

## 5. Safeguards & Responsible Design (Biotech Track Slide 14)

| Named Risk | Mitigation Enforced in Code |
| :--- | :--- |
| **1. Uncalibrated detector confidence treated as certainty** | Agent computes explicit **Count Tolerance Bands** `[min, max]` and **3D Prolate/Oblate Volume Intervals** `[V_min, V_max]` rather than a single black-box number. |
| **2. Border-clipped meniscus or wall glare causing false alarms** | **Perception Sceptic Subagent (`run_sceptic_physics_audit`)** deterministically rejects detections with `border_contact_ratio > 1.0` or non-spherical wall glare before escalating. |
| **3. Blurry, occluded, or blank camera frames** | **Quality & Calibration Gate (`check_frame_quality_and_calibration`)** refuses to guess and returns `status: "abstained_low_quality"`, instructing the scientist to re-capture. |
| **4. Autonomous agent overwriting experimental records** | Original observations are immutable; all observations enter `status: "pending_review"` and require explicit **Scientist Sign-Off (`POST /reviews/{id}`)** to confirm or dispute. |
