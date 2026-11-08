# LABMATE V2 API — for the UI build

Base: same origin, `/api/...` (local: `http://127.0.0.1:8000`, interactive docs at `/api/docs`).
Send header `x-labmate-session: <per-page-load id>` on every call (already done by `LabmateApi`).
Default experiment: **`exp_001`** — Microfluidic sandwich immunoassay for CEA (Person 2 seed, 12 channels).
All writes during a session need an **active recording** (`POST /recordings/start`); the backend enforces it.

State lives in `app/lib/state/app_state.dart` (`AppController`). UI work = `app/lib/pages/*`, `app/lib/ui/*`.

---

## Screen 1 — Live Lab (camera cockpit)

### Layout rule (from product owner)
Text is **never overlaid on the camera**. Put scene summary / status ABOVE the camera window; draw only small
object **tags** (label chips + thin box) on the video. Bubble detections from the specialist get their own colour.

### Data
| What | Source |
|---|---|
| Recording on/off, session id | `POST /recordings/start`, `POST /recordings/{id}/stop`, `GET /events/{exp}?after_seq=N` → `.recording` |
| Active step / channel / tracking list | `GET /recordings/{id}/state` → `{active_step_id, active_channel_id, tracking:[{label, channel_id, added_by}]}` |
| Set step/channel from UI | `PUT /recordings/{id}/state {active_step_id, active_channel_id}` |
| Track / untrack from UI | `POST /recordings/{id}/tracking {label, channel_id?}`, `DELETE /recordings/{id}/tracking/{label}` |
| Live perception (every ~5 s) | `POST /perception/window` response (see below) — the app already calls it in the live-feed loop |
| Flags needing sign-off | `GET /reviews/pending?experiment_id=exp_001` |

### `POST /perception/window` response (what to render)
```json
{
  "saved": true,
  "perception": {
    "scene_summary": "Microfluidic chip channel in view",          // show ABOVE the camera
    "objects": [                                                       // tags ON the camera
      {"label": "micropipette", "certainty": "certain", "box_2d": [490, 642, 882, 972], "tracked": true}
    ],                                                                 // box_2d = [ymin,xmin,ymax,xmax] 0..1000 of the LAST frame
    "actions": [{"action": "dispense drop", "count": 2, "certainty": "likely", "protocol_step": "step_05"}],
    "specialist": {                                                    // Person 3 bubble council (may be null/error)
      "count": 2, "abstained": false, "review_required": true,
      "detections": [{"label": "bubble", "bbox": [114,130,146,160], "confidence": 0.91,
                      "obstruction_risk": "low", "channel_obstruction_ratio": 0.12}],   // bbox in PIXELS
      "image_width": 640, "image_height": 360,
      "sceptic_critique": "...", "description": "2 bubble(s) retained after sceptic audit"
    },
    "tracking": ["bubbles"], "active_step_id": "step_05", "active_channel_id": "CH08",
    "frame_ids": ["frm-...", "frm-..."], "limitations": ["..."]
  },
  "reconciliation": {                                                  // deterministic protocol check (or null)
    "action": "warn",               // no_action | log | warn | request_confirmation | request_recapture | investigate | abstain
    "scientific_status": "pending_review",   // recorded | warning | pending_review | invalid
    "requires_human_approval": true,
    "violated_constraints": ["c_01"],
    "affected_structured": {"channels": ["CH08"], "samples": ["S02"], "derived_values": ["result_S02"]},
    "spoken_response": "...", "citations": ["ref_02"], "event_id": "evt-..."
  }
}
```
Tag drawing: Gemini `box_2d` → `left = xmin/1000*W, top = ymin/1000*H`. Specialist `bbox` is pixels of
`image_width x image_height` → scale to the preview size. `tracked:true` → highlight. `certainty:uncertain` → dashed.

### Voice (already wired; UI just reflects state changes via polling)
"I'm on step five, channel eight" → `set_active_step` · "track the bubbles" / "stop tracking bubbles" →
`track_object` / `stop_tracking` · "scratch that" → `discard_observation(last)` (marks rejected, never deletes) ·
"one bubble in channel one" → `propose_observation` + reconciliation (Gemini speaks `spoken_response`) ·
"why did that happen?" → `investigate_discrepancy` · "what does that affect?" → `get_impact` ·
"how many drops did I add 30 s ago?" → `query_lab_log`.

### Session video (retained until the session ends)
`GET /recordings/{id}/frames?start=&end=` → `[{id, captured_at, bytes}]`;
`GET /recordings/{id}/frames/{frame_id}` → image bytes (use as `<img src>`; same-origin auth cookie applies);
`POST /recordings/{id}/reanalyse {start?, end?, frame_ids?, question?}` → fresh perception on stored frames
(not persisted). Frames are **purged automatically** on stop/expiry — tell the user in the UI.

---

## Screen 2 — Experiment / history (past experiments & trials)
| What | Endpoint |
|---|---|
| Experiments | `GET /experiments` |
| Protocol (steps for a stepper) | `GET /experiments/{id}/protocol` → `content.steps[{id, action, description, quantity, unit, tolerance}]` |
| Full scientific context | `GET /experiments/{id}/context` → steps, reagents, samples, `channel_map`, constraints, dependencies, related_evidence |
| Dependency graph | `GET /experiments/{id}/graph?focus=CH01` → `{nodes:[{id,type,label}], edges:[{from,to,type,reason}], affected:{structured}}` |
| Past sessions (trials) | `GET /experiments/{id}/sessions` → `[{id, started_at, stopped_at, status, event_count, flagged_count}]` |
| One session | `GET /recordings/{id}/summary` → `{recording, event_counts, flags[], notes[]}` |
| Full event log | `GET /observations?experiment_id=...` (each has `review_status`, `reviews[]`) |
| Export | client-side (already in Log page) |

Node types: `step`, `channel`, `standard`, `zero_standard`, `sample`, `derived_value`. Highlight `affected` nodes red;
label the graph "may need review" (impact ≠ proven causation).

## Screen 3 — Review
`GET /reviews/pending` → each item: `observation_id`, `action`, `violated_constraints`, `affected_structured`,
`spoken_response`, `rationale`, `citations`. Buttons → `POST /observations/{observation_id}/review
{action: accept|dispute|correct|reject, correction?, reviewer}`. Original + reconciliation stay in the log.
Optional "Investigate" button → `POST /investigate {experiment_id, question, step_id, observation_id}`.

## Other
`GET /capabilities` (models, routing, specialist status, steering docs), `GET /skills`, `GET /telemetry/summary`,
`POST /vision/analyse` (snapshot: Gemini + specialist), `POST /vision/specialist` (specialist only, returns
`overlay_base64`), `POST /predictive/optimise` (Person 3 GP optimiser), `POST /query` (log agent).
