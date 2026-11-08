# Plugging in teammate work (morning checklist)

Everything below is a drop-in: no changes to the Live/voice code are needed.

## (a) Sub-models (specialist vision)
1. Replace the internals of `modal_app/specialist/model.py` (keep the names): `MODEL_NAME`, `IS_REAL_MODEL=True`,
   `load()`, `predict(image_bytes, question) -> dict`, optional `predict_frames(frames, interval_s) -> dict`.
   Return the schema documented at the top of that file (`detections`, `count`, `counts_by_label`, ...).
2. Deps -> `modal_app/specialist/requirements.txt` (pinned). Weights -> `modal_app/specialist/weights/` or a Modal Volume.
3. Test locally, no cloud cost:
   `SPECIALIST_PROVIDER=local .venv/bin/python -m pytest backend/tests/test_orchestration.py -k specialist -q`
   and `SPECIALIST_PROVIDER=local .venv/bin/python scripts/eval.py --clips eval/clips.json`
4. Run on Modal (CPU default; set `MODAL_GPU=T4` only if needed - credits are limited):
   `.venv/bin/modal deploy modal_app/specialist_app.py && .venv/bin/python scripts/modal_check.py`
5. Turn it on in the app: `.env` -> `SPECIALIST_PROVIDER=modal`, `MODAL_ENABLED=true`, plus
   `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET` (from `~/.modal.toml`), then `scripts/deploy_vercel.sh --sync-env` and
   `scripts/deploy_vercel.sh`.
   The specialist runs *after* Gemini on every perception window and snapshot; its output appears as
   `perception.specialist` / `structured.specialist`, the log agent prefers its counts, and a specialist failure
   never breaks the Gemini path.

## (b) UI formatting
- Only edit `app/lib/pages/*` and `app/lib/ui/*` (theme: `ui/theme.dart`). Read state from `AppController`
  (`lib/state/app_state.dart`); call its methods for actions. Do not touch `lib/state` or `lib/services`.
- Check: `cd app && flutter analyze && flutter test`, then `scripts/build_web.sh` and
  `.venv/bin/python scripts/e2e_browser.py` (buttons are found by their labels: keep "Start live feed",
  "Stop live feed" and the tab names, or update the e2e script).

## (c) Science docs / protocols
- **Protocol** (structured, versioned): author JSON in the shape of
  `backend/steering/protocols/demo-colour-assay.json` (`steps[]` with `id, action, description, quantity, unit,
  tolerance, expected_observation, perception_actions`). Load it:
  `curl -X PUT http://127.0.0.1:8000/api/experiments/exp-demo/protocol -H 'content-type: application/json' -d @protocol.json`
  (or via the deployed app's `/api/docs`). Each PUT creates a new version; old versions are kept.
  The protocol is injected into the Live system prompt (at token mint), perception prompts (step matching),
  snapshot prompts and the log agent (protocol-progress / deviation questions).
- **Steering** (policy text, no code): add/edit markdown in `backend/steering/*.md` with front matter
  `id`, `applies_to: [live, query, perception, vision]`, `priority`. Hash of composed steering is recorded in
  every telemetry span, so eval results are attributable to steering versions.
- **Labelled clips** for the accuracy metric: record 5-10 short clips (5-20 s) of the protocol actions with
  known counts, put them under `eval/clips/`, list them in `eval/clips.json` (see `eval/clips.example.json`).

## Orchestration map (for the write-up)
```
UI action (button / tab / step)  --POST /api/ui/actions-->  ui_actions table  (content-free)
voice --Gemini Live (token-locked: core prompt + steering + protocol + skills)--> functionCall
   --browser relay--> POST /api/tools/call --> skills registry (policy: effect, requires_recording)
        read   : get_experiment_context, get_protocol, get_recent_observations, describe_current_recording_state
        write  : propose_observation            (backend-verified recording session)
        model  : query_lab_log -> log agent (gemini, steering + protocol + DB window, cites event ids)
                 request_visual_analysis -> Gemini vision -> specialist sub-model (local | Modal)
        ui     : request_ui_action -> approved -> executed by the app -> real outcome back to the model
camera --perception windows--> Gemini perception (+protocol step matching) -> specialist -> DB (if recording)
every stage --> telemetry_spans --> scripts/langfuse_sync.py --> Langfuse (local)  <-- scripts/eval.py scores
```
List live: `GET /api/skills`, `GET /api/steering`, `GET /api/capabilities` (routing table), `GET /api/telemetry/summary`.
