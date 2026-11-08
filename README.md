# Larvis (`bioJARVIS`) — a hands-free, state-aware lab copilot built on Gemini

**UCL Agentverse 2026 · Biotech track · Gemini track**

> Every experiment has a plan and a reality. Larvis connects them: it is a universal, protocol-agnostic wet-lab copilot (supporting microfluidics, ELISA, RT-qPCR, cell culture, and chromatography). It listens and (when permitted) sees, turns what happens at the bench into an auditable record, checks it against protocol rules, shows which downstream results are affected, and brings in specialist models and a human reviewer when it matters.

Bottleneck & Real-World Need: In wet-lab immunoassays, bubbles, pipetting drift, and thermal excursions distort optical read-outs (Bhuiyan et al., Anal. Chem. 2022
), while sterile-gloved hands prevent manual note-taking. An unnoticed bubble in one standard channel silently corrupts the entire standard curve and every dependent patient sample. Preclinical irreproducibility costs ~$28B annually (Freedman et al., 2015
). Larvis targets that execution gap. Next step to real use: validation on live wet-chip video with a UCL partner lab.

## What Larvis does (demo experiment: CEA microfluidic sandwich immunoassay, 12-channel chip)
- **Voice, hands-free (Gemini Live).** "I'm on step seven, channel eight" · "detection antibody incubated nine minutes" ·
  "what does that affect?" · "scratch that" · "how many bubbles have I noted?" — Gemini picks a typed tool; the
  backend validates and executes it; Gemini speaks the verified result.
- **Camera (opt-in).** Every ~5 s: Gemini 3.8 Flash describes the scene, tags objects (boxes) and actions; a
  **specialist bubble model** (on Modal) measures bubbles; the two counts are **cross-checked**.
- **Deterministic protocol engine.** Each observation is reconciled against the versioned protocol (constraints c_01–c_07)
  → log / warn / request confirmation / recapture / investigate / abstain, with violated constraints and the
  **dependency-graph impact** (e.g. bubble in standard CH01 → standard curve → all six results; sample CH08 → result_S02 only).
- **Human authority.** Flags enter a review queue; originals are immutable; corrections and discards are new linked records.
  Nothing is persisted unless the researcher pressed Record (enforced server-side).

## How decisions are split (the "not a wrapper" core)
| Concern | Who decides | Why |
|---|---|---|
| Conversation, intent → tool + arguments, scene understanding, object tags | **Gemini** (Live / 3.8 Flash) | open-vocabulary, multimodal, hands-free |
| Bubble count / obstruction | **Specialist model** (OpenCV watershed + PyTorch patch CNN + geometric audit) | measurement, not a guess |
| Protocol compliance, affected results | **Deterministic engine** on versioned protocol + dependency graph | reproducible, auditable, can't be argued out of a rule |
| Whether anything is saved / approved | **Server-enforced gates** + human review | the model can propose, never approve |
| "What happened 30 s ago?" | **Read-only log agent** (Gemini) over DB events, must cite event ids; invented ids are dropped | grounded answers |

```
phone mic ──► Gemini Live ──toolCall──► /api/tools/call ─► skills registry (policy) ─► engine / DB / log agent ─┐
phone cam ──► Gemini Flash (scene, tags) ─┐                                                                  │
          └─► specialist @ Modal (bubbles)┴─ cross-check ─► protocol engine ─► DB (if recording) ─► review ◄─┘
every step ─► content-free telemetry spans (model, prompt version, tokens, latency, outcome) ─► eval loop / Langfuse
```

## Measured results (all on labelled synthetic or scripted cases — see "What's real" below)
| Benchmark | Stock Gemini | Larvis | Source |
|---|---|---|---|
| Protocol decisions, 20 CEA cases (same protocol info given to both) | 70% correct, **3/12 human sign-offs missed** | 100%, 0 missed (upper bound: cases written by engine author) | `docs/BENCHMARK_V2.md` |
| Bubble counting, 18 labelled images | 94% exact, **33% false alarms on clean channels** (glare) | 94% exact, 0% false alarms | `docs/BENCHMARK_V2.md` |
| Cross-checking both models (17 usable images) | — | **0 silent errors**, both real errors escalated, 12% sent to review | `docs/BENCHMARK_V2.md` |
| Voice → correct tool + correct arguments, 15 spoken commands, real Live sessions | — | **15/15** (95% CI ≈ 80–100%) | `docs/BENCHMARK_VOICE.md` |
| Log-agent answers (synthetic log, 5 questions incl. relative time + rejected duplicate) | — | 5/5, 0 invented citations | `scripts/eval.py --qa` |

## What's real vs simulated
- **Real:** Gemini Live voice + tool calling; Gemini Flash perception; the specialist model and engine running live
  (Modal / Vercel); persistence, review, telemetry; every benchmark number above is a real run.
- **Synthetic / limited:** vision images are generated microfluidic test cases with known ground truth (Person 3), the
  specialist was developed on that generator (in-distribution); steering cases were authored by the engine's author;
  voice tests use synthesised speech in a quiet room; samples are small (n=15–20), single runs. **No physical lab or
  chip was available; nothing has been validated on real lab footage.** The live demo uses household objects as stand-ins.
- `BiochemicalYieldMLP` / GP optimiser (Person 3): trained and scored on a **mechanistic simulator**
  (`_mechanistic_biochemical_ground_truth`); its R² measures fit to that simulator, not assay data — an illustrative
  extension, not evidence.
- Investigation "PubMed / UniProt / PubChem" context (Person 4) is a **curated local snapshot**
  (`science/biotech_external_db.json`), not live database queries.
- The perception "council" stages are **deterministic Python modules** (no LLM in the loop by default); YOLO-seg is
  optional and **not** used in the benchmarked path (OpenCV watershed is). Geometry "volumes" are pixel-unit intervals
  under shape assumptions, not µL.

## Team & ownership
- **Pavan** — architecture, Gemini Live + tool orchestration, backend/API, state engine integration, Modal/Vercel/Turso,
  telemetry + eval loop, Flutter app core.
- **Ryan (Person 2)** — CEA protocol seed, constraints, channel map, dependency graph (`science/experiment_seed.json`).
- **Yeeyee (Person 3)** — specialist bubble perception, geometry, patch CNN, predictive models, vision benchmark
  (`backend/vision/`, `evals/vision_test/`).
- **Katarina (Person 4)** — steering engine, 7-action taxonomy, investigation, steering cases
  (`backend/agents/`, `science/`, `evals/steering/`).
- **UI** — Flutter UI (`app/lib/pages`, `app/lib/ui`).

## Run it
```bash
scripts/setup.sh                        # venv, deps, Flutter
scripts/start.sh                        # http://127.0.0.1:8000 (needs GEMINI_API_KEY in .env for voice/vision)
scripts/test.sh                         # backend + Flutter + headless-browser tests
.venv/bin/python scripts/benchmark_v2.py      # stock Gemini vs Larvis (vision + steering)
.venv/bin/python scripts/benchmark_voice.py   # spoken command accuracy (real Live)
scripts/deploy_vercel.sh                # protected preview deploy (maintainer)
```
UI development without keys: `docs/UI_DEV.md`. API for every screen: `docs/API_V2.md`. Architecture: `docs/ARCHITECTURE.md`.

## Datasets, references & licences
| Resource | Use | Licence |
|---|---|---|
| Zheng et al., Lab Chip 2012 ([10.1039/c2lc40145b](https://doi.org/10.1039/c2lc40145b)) | CEA protocol steps, timings, reagents | citation (protocol source) |
| Bhuiyan et al., Anal. Chem. 2022 ([10.1021/acs.analchem.1c04827](https://doi.org/10.1021/acs.analchem.1c04827)) | bubbles / incomplete filling as assay errors (c_01, c_02) | citation |
| Doganay et al., Lab Chip 2024 ([10.1039/d4lc00671b](https://doi.org/10.1039/d4lc00671b)) | context: AI bubble classification in microfluidics | citation |
| kLarity ([maxsiska/kLarity](https://github.com/maxsiska/kLarity)) | split-ellipse / spheroid geometry equations, border rule | AGPL-3.0 / CC-BY 4.0 |
| BubbleID ([cldunlap73/BubbleID](https://github.com/cldunlap73/BubbleID)) | reference only (not used for training) | MIT |
| `evals/vision_test/` | 18 synthetic labelled microfluidic images (generated) | team-generated, synthetic, no patient data |

## Safeguards
Mic/camera off by default; recording only on explicit press (server-enforced, heartbeat expiry); session frames purged at
session end; no raw audio/video stored; Gemini key never reaches the browser (short-lived config-locked tokens);
deployment behind Vercel Authentication; content-free telemetry; the model cannot approve, delete or overwrite records.
