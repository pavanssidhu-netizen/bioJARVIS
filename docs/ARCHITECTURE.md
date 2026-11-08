# Architecture

## Data flow
1. **Start live feed** (one tap; nothing is acquired before it):
   unlock audio → open camera → `POST /recordings/start` → perception loop → mint Live token → open Live WS →
   enable mic → share frames with Live (1 per 2 s).
2. **Perception loop**: 1 frame/s (512 px JPEG) buffered; every 5 frames → `POST /perception/window` →
   `gemini-3.8-flash` with a JSON schema → `PerceptionPayload` → persisted as `observation_events`
   (`event_type=perception`, `source_modality=video`) **only if** the backend recording session is active.
   Windows with no actions and the same object set as the previous one are skipped (`no_change`).
3. **Voice** goes browser → Gemini Live directly using a 1-use, 30-minute ephemeral token whose model, system
   prompt, tools and transcription settings are locked server-side.
4. **Tool calls** from Live arrive in the browser, which relays them to `POST /tools/call`. The backend
   re-verifies the recording session, validates args, writes, and only then returns `saved=true`; the browser
   sends that result back as `toolResponse`. The model never has DB access.
5. **Voice queries**: `query_lab_log(question)` → `services/query_agent.py` loads the last 30 min of events
   (compact JSON with `ago_s`, review status) → `gemini-3.8-flash` answers ONLY from that log, returning
   `answer/confidence/evidence_event_ids/caveats`; hallucinated ids are dropped. Read-only.
6. **Feed**: the app polls `GET /events/{exp}?after_seq=N` every 1.5 s (missed-update recovery built in) and
   takes recording state from the response — the backend is authoritative.

## State (all independent, `AppController`)
`app_connected, gemini_connected, microphone_enabled, camera_open, camera_streaming_to_gemini,
recording_active, snapshot_analysis_in_progress, database_connected`. "Live feed" composes them; it never
infers one from another. `recording_active` is only set from backend responses.

## Safety rails
- Recording sessions need a heartbeat (15 s); after 45 s without one the server marks them `expired` and
  rejects writes. `pagehide` also stops media and sends a `sendBeacon` stop.
- Gemini disconnect stops recording. Stop live feed stops everything and the perception timer.
- No raw audio/video/images are stored; analysed images keep only a SHA-256 in `media_assets`.
- Corrections create a new linked `correction` event; originals are never modified.
- Idempotency keys on every write; sequence numbers allocated atomically in a single INSERT…SELECT.
- `VERCEL_ENV=production` → API returns 403 (the Hobby production domain is not covered by deployment
  protection). Use the protected preview URL.

## Why Vercel + Turso (not a laptop SQLite) for V1
Vercel functions have no persistent disk and can't hold WebSockets, so: storage is Turso (hosted SQLite,
same schema/SQL as the local file), voice is direct-to-Gemini via ephemeral tokens, and the feed polls.
Locally the identical code uses `data/labmate.db`.
