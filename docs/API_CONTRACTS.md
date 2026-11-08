# API contracts

All routes are under `/api`. Interactive OpenAPI: `/api/docs`. Types: `backend/app/contracts.py`.
Errors: `{"error": "<code>", "message": "...", "detail": {...}}` with 4xx/5xx status.

| Method | Path | Purpose |
|---|---|---|
| GET | /health | DB check, DB label, last write |
| GET | /capabilities | models, providers, tools, flags (no secrets) |
| GET/POST | /experiments | list / create `{name}` |
| GET | /experiments/{id} | |
| POST | /recordings/start | `{experiment_id}` → session (idempotent: one active per experiment) |
| POST | /recordings/{id}/stop | `{reason}` or empty body (sendBeacon) |
| POST | /recordings/{id}/heartbeat | keep-alive; 409 `recording_inactive` if expired |
| GET | /recordings/{id} · /recordings?experiment_id= | session / active session |
| GET | /observations?experiment_id&after_seq&event_type&modality | stored events + reviews |
| POST | /observations/propose | ingest one event (gated, idempotent) |
| POST | /observations/{id}/review | `accept|dispute|correct|reject` (+`correction`) |
| GET | /events/{exp}?after_seq=N | poll feed + current recording |
| GET | /events/{exp}/stream | SSE (bounded, resumable via Last-Event-ID) |
| POST | /vision/analyse | snapshot → description + structured; `save=true` needs active session |
| POST | /perception/window | frames → perception contract; persisted if session active |
| POST | /query | `{experiment_id, question}` → log agent answer |
| POST | /live/token | ephemeral Live token + WS URL |
| POST | /tools/call | relay target for Gemini function calls |

`WS /ws/live` from the original spec is replaced by `/live/token` + a direct browser→Gemini WebSocket
(a backend relay can be added on Modal later without changing the tool contract).

## Perception contract (`event_type=perception`)
```json
{
  "window_start": "2026-11-08T01:00:00.000Z", "window_end": "2026-11-08T01:00:04.000Z", "frame_count": 5,
  "scene_summary": "A gloved hand dispenses drops from a dropper into a test tube.",
  "objects": [{"label": "test tube", "count": 3, "certainty": "certain"},
              {"label": "dropper bottle", "certainty": "likely"}],
  "actions": [{"action": "dispense drop", "object": "test tube", "count": 2, "certainty": "likely", "first_frame": 1}],
  "limitations": ["Frames ~1 s apart; fast drops may be missed."],
  "provider": "gemini", "model": "gemini-3.8-flash"
}
```

## Ingest an event
```http
POST /api/observations/propose
{"session_id":"rec-1a2b","experiment_id":"exp-demo","source_modality":"speech",
 "event_type":"observation_proposal","payload":{"summary":"Tube A turned blue"},
 "idempotency_key":"seg-abc12345"}
→ 200 {"ok":true,"saved":true,"duplicate":false,"event":{"id":"evt-…","sequence_number":7,…}}
→ 409 {"ok":false,"saved":false,"error":"recording_inactive","message":"Recording is not active; nothing was saved"}
```

## Query the log
```http
POST /api/query {"experiment_id":"exp-demo","question":"How many drops did I add 30 seconds ago?"}
→ {"answer":"About 3 drops, in two perception windows 25-35 s ago.","confidence":"medium",
   "evidence_event_ids":["evt-…","evt-…"],"caveats":["Counts are model estimates at 1 fps."],
   "events_considered":42,"model":"gemini-3.8-flash","asked_at":"…"}
```

## Model tools (Gemini Live)
`get_experiment_context`, `propose_observation{observation_type, summary, subject?, value?, is_inference?}`,
`get_recent_observations{limit}`, `describe_current_recording_state`, `request_visual_analysis{image_id, question}`,
`query_lab_log{question, lookback_seconds?}`. Every result is `{"ok": bool, "saved"?: bool, "error"?: code, ...}`.
