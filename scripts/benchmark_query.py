"""Log-agent A/B: does adding deterministic aggregates make DB answers more reliable? (real Gemini)

Synthetic session: 8 perception windows at known times with 'press shift key' / 'pick up mug' counts, one window
REJECTED by the researcher (trap), 3 notes + 1 discarded note. Each question asked RUNS times per condition:
  A  baseline: LLM reads raw events and must filter/sum itself
  B  Larvis  : same + code-computed aggregates (per action, per time window, rejected excluded)

    .venv/bin/python scripts/benchmark_query.py [runs]
Writes eval/results/benchmark_query_<ts>.json and docs/BENCHMARK_QUERY.md (pushes to Langfuse if configured).
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.mkdtemp(prefix='larvis-query-')) / 'q.db'}"
os.environ["TURSO_DATABASE_URL"] = ""

from backend.app.contracts import EventIn, LogQueryIn, ReviewIn  # noqa: E402
from backend.app.db import get_db  # noqa: E402
from backend.app.services.query_agent import answer_question  # noqa: E402
from backend.app.services.store import Store  # noqa: E402
from eval import first_int  # noqa: E402

EXP = "exp_001"
# (ago_s, shift presses, mug pickups, rejected)
WINDOWS = [(12, 1, 0, False), (27, 2, 1, False), (44, 1, 0, False), (55, 5, 0, True),
           (75, 3, 0, False), (98, 1, 1, False), (150, 2, 0, False), (210, 2, 1, False)]
CASES = [  # question, expected, unit
    ("How many times did I press the shift key in the last minute?", 4, "time|press"),
    ("How many times did I press the shift key in the last two minutes?", 8, "time|press"),
    ("How many shift key presses are in the log in total?", 12, "press|time"),
    ("How many times did I pick up the mug?", 3, "time|pick"),
    ("How many notes have I taken?", 3, "note"),
    ("In the last 30 seconds, how many shift presses were there?", 3, "time|press"),
]


def grade(answer: str, units: str):
    import re
    answer = re.sub(r"\([^)]*\)", " ", answer)  # drop parentheticals like "(0 to 30 s ago)"
    answer = re.sub(r"\b(\d+|thirty|sixty|two|one)\s*(seconds?|secs?|minutes?|mins?|s)\b", " ", answer, flags=re.I)
    for u in units.split("|"):
        v = first_int(answer, u)
        if v is not None:
            return v
    return first_int(answer)


FIXED_NOW = datetime.now(timezone.utc)


def seed(st: Store):
    rec = st.start_recording(EXP)
    now = FIXED_NOW
    for i, (ago, shift, mug, rejected) in enumerate(WINDOWS):
        acts = ([{"action": "press shift key", "object": "shift key", "count": shift, "certainty": "likely"}] if shift else []) + \
               ([{"action": "pick up mug", "object": "mug", "count": mug, "certainty": "likely"}] if mug else [])
        end = now - timedelta(seconds=ago)
        ev, _ = st.ingest(EventIn(session_id=rec.id, experiment_id=EXP, source_modality="video", event_type="perception",
                                  model_name="fixture", idempotency_key=f"q-fixture-w{i}", payload={
            "window_start": (end - timedelta(seconds=3)).isoformat(), "window_end": end.isoformat(), "frame_count": 6,
            "scene_summary": "hand on keyboard", "objects": [{"label": "hand", "certainty": "certain"}],
            "actions": acts, "limitations": [], "provider": "fixture", "model": "fixture"}))
        if rejected:
            st.review(ev.id, ReviewIn(action="reject", reviewer="researcher", correction={"reason": "duplicate window"}))
    for i, t in enumerate(["note the chip looks clean", "note step five started", "note room is warm", "note wrong tube"]):
        ev, _ = st.ingest(EventIn(session_id=rec.id, experiment_id=EXP, source_modality="speech",
                                  event_type="observation_proposal", model_name="fixture",
                                  idempotency_key=f"q-fixture-n{i}", payload={"observation_type": "note", "summary": t}))
        if t.endswith("wrong tube"):
            st.review(ev.id, ReviewIn(action="reject", reviewer="researcher (voice)"))


async def run(runs: int):
    st = Store(get_db())
    seed(st)
    sem = asyncio.Semaphore(6)
    results = {"A_baseline": [], "B_aggregates": []}

    async def ask(cond, q, exp, units, k):
        async with sem:
            os.environ["LARVIS_QUERY_AGGREGATES"] = "0" if cond == "A_baseline" else "1"
            r = await answer_question(st, LogQueryIn(experiment_id=EXP, question=q, lookback_seconds=86400),
                                       now=FIXED_NOW + timedelta(seconds=1))
        got = grade(r.answer, units)
        return cond, {"question": q, "expected": exp, "got": got, "ok": got == exp, "answer": r.answer[:200],
                      "evidence": len(r.evidence_event_ids), "run": k}

    # conditions run sequentially (env flag is process-global); questions/runs in parallel within a condition
    for cond in results:
        out = await asyncio.gather(*(ask(cond, q, e, u, k) for k in range(runs) for q, e, u in CASES))
        results[cond] = [r for _, r in out]
    return results


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    res = asyncio.run(run(runs))
    n = len(CASES) * runs
    m = {}
    for cond, rows in res.items():
        acc = sum(r["ok"] for r in rows) / n
        per_run = [sum(r["ok"] for r in rows if r["run"] == k) / len(CASES) for k in range(runs)]
        m[cond] = {"accuracy": round(acc, 3), "per_run": [round(x, 3) for x in per_run],
                   "min": round(min(per_run), 3), "max": round(max(per_run), 3)}
        for q, e, _ in CASES:
            got = [r["got"] for r in rows if r["question"] == q]
            print(f"  {cond:<13} {q[:62]:<62} exp={e:<3} got={got}")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    p = ROOT / "eval" / "results" / f"benchmark_query_{ts}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"metrics": m, "rows": res}, indent=2))
    md = ["# Log agent A/B: raw events vs + deterministic aggregates (real Gemini)", "",
          f"Run {ts} · {len(CASES)} questions × {runs} runs per condition · same model/prompt otherwise · raw `{p.relative_to(ROOT)}`",
          "", "Traps: relative time windows, a researcher-REJECTED duplicate window (5 presses), a discarded note.", "",
          "| Condition | Accuracy | Per run |", "|---|---|---|"] + [
          f"| {c} | {v['accuracy']} | {v['per_run']} |" for c, v in m.items()] + ["", "| Question | Expected | A baseline (per run) | B aggregates (per run) |", "|---|---|---|---|"] + [
          f"| {q} | {e} | {[r['got'] for r in res['A_baseline'] if r['question'] == q]} | "
          f"{[r['got'] for r in res['B_aggregates'] if r['question'] == q]} |" for q, e, _ in CASES]
    (ROOT / "docs" / "BENCHMARK_QUERY.md").write_text("\n".join(md) + "\n")
    print("\n" + "\n".join(md[:9]))
    try:
        from backend.app.orchestration.langfuse_export import LangfuseConfig, score_event, send
        cfg = LangfuseConfig()
        if cfg.configured:
            print("[langfuse]", send([score_event(f"query.{c}.accuracy", v["accuracy"], session_id=f"bench-query-{ts}")
                                      for c, v in m.items()], cfg))
    except Exception as e:  # noqa: BLE001
        print("[langfuse] skipped:", e)


if __name__ == "__main__":
    main()
