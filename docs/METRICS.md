# Metrics (eval loop) and why each one

Computed by `scripts/eval.py` from the app DB + content-free telemetry; pushed to Langfuse with `--push`.
Spans reach Langfuse via `scripts/langfuse_sync.py` (traces grouped by app session).

| Metric | Definition | Why it matters | Target |
|---|---|---|---|
| `integrity.gate_violations` | persisted events whose timestamp is outside their recording session's [start, stop] | Consent: nothing is recorded unless the researcher pressed Start. Verified from data, not assumed from code. | 0 |
| `integrity.unsessioned_writes` | non-correction events with no session | Same guarantee, other failure mode | 0 |
| `notes.save_success_rate` | dictated notes (`propose_observation` while recording) that reached a committed write | A notebook that drops notes is worse than paper | ≥ 0.98 |
| `notes.attempts_while_inactive` | model tried to save while not recording (refused) | Shows the gate working; high values = prompt/steering issue | informational |
| `grounding.hallucinated_id_rate` | cited event ids not present in the log given to the agent | Direct, model-agnostic hallucination signal for voice answers | ≈ 0 |
| `grounding.answers_with_evidence` | log answers citing ≥ 1 real event | Answers should be traceable to records | ≥ 0.9 |
| `qa.accuracy` | exact numeric answers on a deterministic synthetic log (includes relative-time and a rejected-duplicate trap) | End-to-end correctness of "how many drops 30 s ago?" independent of camera noise | ≥ 0.8 |
| `gemini.counting.mae` / `exact_match` / `within_1` / `signed_bias` | per labelled clip: predicted vs. true action count | The scientific task. Bias shows systematic over/under-counting (1 fps sampling under-counts) | MAE ≤ 1 |
| `specialist.counting.*` | same, from the teammate sub-model | Justifies the specialist: compare against Gemini on identical clips | beats Gemini |
| `perception.persist_rate` | windows saved / analysed (rest: no-change or not recording) | Log signal-to-noise and DB growth | informational |
| `latency.<stage>.p50/p95_ms` | perception window, log query, snapshot, token mint, tool relay | Hands-free use needs spoken answers in a few seconds; p95 catches tail stalls | query p95 < 6 s |
| `reliability.<stage>.error_rate`, `reliability.api.5xx_rate` | failures per stage | Where to spend debugging time | < 2 % |
| `cost.tokens_per_live_minute` | model tokens / recorded minute | Cost proxy for running a real lab session | informational |

Each span also carries `model`, `prompt_ref` (e.g. `query.log@v2+steer:ab12cd34ef`) and token counts, so any
metric can be split by model, prompt version or steering version in Langfuse.

Not measured on purpose: transcript/answer text quality via LLM-as-judge on real sessions (would require
storing content; Phase 1 keeps telemetry content-free). Use the synthetic QA set instead.
