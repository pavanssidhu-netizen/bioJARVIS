# Log agent A/B: raw events vs + deterministic aggregates (real Gemini)

Raw `eval/results/benchmark_query_20261108T123019Z.json` · 6 questions × 3 runs per condition · fixed fixture clock. Traps: relative time windows, a researcher-REJECTED duplicate window (5 presses), a discarded note.

| Condition | Accuracy |
|---|---|
| A_baseline | 1.0 |
| B_aggregates | 1.0 |

**Result: no measurable difference on this set** — the baseline already handled these windows and the rejected-window trap. Aggregates are kept because they make counts deterministic and auditable (code, not the LLM, does the arithmetic), but we do not claim an accuracy gain from them.

Process notes (why evals matter): the first run showed a large 'regression' that was a fixture bug (clock drift between conditions) and two grader bugs (reading '30' from '30 seconds', '0' from '(0 to 30 s ago)'); all fixed and re-graded from the saved answers.
