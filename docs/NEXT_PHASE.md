# Next phase

All extensions plug into the backend; the Flutter app only consumes contracts in `backend/app/contracts.py`.

- **Backend on Modal (prod)**: wrap `backend.app.main:app` with `@modal.asgi_app()`; add a `/ws/live` relay there
  if you want server-side audio handling. Point the Flutter build at the Modal URL or keep Vercel as a proxy.
- **Specialist PyTorch vision**: implement `SpecialistVisionProvider.analyse_image/analyse_frames`
  (`backend/app/vision/specialist.py`) returning the documented schema (detections, count, bbox in pixels,
  `review_required`); set `VISION_PROVIDER=specialist`. Drop counting is the obvious first target: a small
  detector at 10–15 fps beats 1 fps LLM sampling.
- **Modal-hosted inference**: deploy a function `labmate-vision/detect(image_bytes, question) -> dict`, set
  `MODAL_ENABLED=true`, `VISION_PROVIDER=modal`. `ModalVisionProvider` already calls it (no deploys from here).
- **Protocol reconciliation**: store protocols in `protocol_documents` (versioned JSON); add a service that
  compares perception/observation events to protocol steps and emits `deviation` events for human review.
- **Experiment dependency graph**: populate `scientific_entities` / `scientific_relationships` from
  observations (samples, reagents, steps); keep the event log as the source of truth.
- **Human review / approval**: `observation_reviews` already records accept/dispute/correct/reject with
  history; add reviewer identity from real auth and approval gates before export.
- **Gemini Argon reasoning**: swap the query agent model (`services/query_agent.py`) to `gemini-4-argon` for
  multi-step analysis; keep it read-only.
- **Langfuse observability**: wrap model calls in `vision/gemini.py`, `query_agent.py`, `live/token.py`;
  log metadata (latency, tokens, tool names) — not transcripts — unless consent is recorded.
- **Bayesian next-experiment suggestions**: a separate service reading accepted observations only, proposing
  (never applying) parameter changes; surfaced in the UI as suggestions requiring approval.
- **Auth for teammates/real users**: replace Vercel deployment protection with a real identity provider
  before any non-team access; never ship invented shared-secret auth.
