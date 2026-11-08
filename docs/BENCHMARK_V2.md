# LABMATE V2 benchmark: stock Gemini vs LABMATE

Run 2026-11-08T09:37:31+00:00 · baseline model `gemini-3.8-flash` (structured JSON output, same information and rules as LABMATE) · raw results `eval/results/benchmark_v2_20261108T093917Z.json`

All cases are synthetic and independently labelled by teammates (vision: Person 3; steering: Person 4). Proof of concept, not clinical validation.

### Vision — bubble counting (18 images)

| Metric | Stock Gemini | LABMATE | Better |
|---|---|---|---|
| count_mae | 0.059 | 0.118 | Gemini |
| count_exact | 0.941 | 0.941 | tie |
| count_within_1 | 1.0 | 0.941 | Gemini |
| false_positive_rate_on_clean_controls | 0.333 | 0.0 | LABMATE |
| box_precision_iou30 | 0.974 | 0.897 | Gemini |
| box_recall_iou30 | 1.0 | 0.946 | Gemini |
| abstains_on_unusable_frames | 1.0 | 1.0 | tie |
| spurious_abstentions | 0 | 0 | tie |
| latency_p50_ms | 6704.3 | 38.6 | LABMATE |
| latency_p95_ms | 12633.7 | 68.9 | LABMATE |
| errors | 0 | 0 | tie |

### Vision — LABMATE system: cross-model verification (Gemini count vs specialist count)

| Metric | Value |
|---|---|
| silent_error_rate (both agree but wrong) | 0.0 |
| errors_caught_by_escalation | 1.0 |
| human_review_rate (disagreements sent to review) | 0.118 |
| escalated_cases | case_02_clean_with_wall_glare_neg, case_18_single_large_prolate_bubble |

Reading: neither model alone is error-free (Gemini is fooled by glare on clean controls; the specialist over-segments a large prolate bubble), but their errors are uncorrelated. LABMATE acts on the specialist measurement, cross-checks it against Gemini, and routes disagreements to human review — this is implemented in the live perception path (`reconciliation.cross_check`).

### Steering — protocol decisions (20 cases)

| Metric | Stock Gemini | LABMATE | Better |
|---|---|---|---|
| action_accuracy | 0.7 | 1.0 | LABMATE |
| human_gate_recall | 0.75 | 1.0 | LABMATE |
| missed_human_gates | 3 | 0 | LABMATE |
| unnecessary_gates | 0 | 0 | tie |
| affected_results_f1 | 0.9 | 1.0 | LABMATE |
| violated_constraint_exact | 0.8 | 1.0 | LABMATE |
| latency_p50_ms | 7735.9 | 0.5 | LABMATE |
| errors | 0 | 0 | tie |

Caveat: the steering cases were authored by the same teammate who wrote the deterministic engine, so LABMATE's score on them is an upper bound; the stock-Gemini numbers show what the model does with identical information and no engine.
