"""Utterance-router accuracy (real Gemini, text in): category + tool + key args, incl. noise and ambiguity.

    .venv/bin/python scripts/benchmark_router.py      # ~22 small Gemini calls
Writes eval/results/benchmark_router_<ts>.json and docs/BENCHMARK_ROUTER.md.
"""
from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.mkdtemp(prefix='larvis-router-')) / 'r.db'}"
os.environ["TURSO_DATABASE_URL"] = ""
os.environ["SPECIALIST_PROVIDER"] = "none"

from backend.app.db import get_db  # noqa: E402
from backend.app.orchestration.router import route_utterance  # noqa: E402
from backend.app.services.store import Store  # noqa: E402
from benchmark_voice import CASES, arg_ok  # noqa: E402  (same 15 commands as the voice benchmark)

EXTRA = [  # (utterance, expected tool, expected args, expected category or None, expect ambiguous)
    ("I pressed the Shift key", "none", {}, "non_scientific", False),
    ("can you hear me", "none", {}, "non_scientific", False),
    ("hmm okay", "none", {}, "non_scientific", False),
    ("Sorry, I was talking to Ryan about lunch.", "none", {}, "non_scientific", False),
    ("Channel four looks a bit cloudy.", "propose_observation", {"channel_id": "CH04"}, "observation", None),
    ("Finished the wash.", "propose_observation", {}, None, None),
    ("I think something is off with the standards.", "investigate_discrepancy|propose_observation", {}, None, None),
]


async def main_async():
    st = Store(get_db())
    rec = st.start_recording("exp_001")
    st.update_session_state(rec.id, active_step_id="step_05")
    st.ingest(__import__("backend.app.contracts", fromlist=["EventIn"]).EventIn(
        session_id=rec.id, experiment_id="exp_001", source_modality="speech", event_type="observation_proposal",
        payload={"summary": "seed"}, idempotency_key="router-seed-001"))
    cases = [(u, t, a, None, None) for u, t, a in CASES] + EXTRA
    rows = []
    for i, (u, tool, args, cat, amb) in enumerate(cases):
        t0 = time.perf_counter()
        r = await route_utterance(st, "exp_001", rec.id, u, "voice", call_id=f"rt-{i}")
        ms = (time.perf_counter() - t0) * 1000
        ok_tool = r["tool"] in tool.split("|")
        ok_args = ok_tool and all(arg_ok(v, r["args"].get(k)) for k, v in args.items())
        ok_cat = cat is None or r["category"] == cat
        ok_amb = amb is None or r["ambiguous"] == amb
        rows.append({"utterance": u, "expected_tool": tool, "expected_args": args, "got_tool": r["tool"],
                     "got_args": {k: v for k, v in r["args"].items() if k != "classification"},
                     "category": r["category"], "ambiguous": r["ambiguous"], "stored": r["stored"],
                     "spoken": r.get("spoken"), "ok": ok_tool and ok_args and ok_cat and ok_amb, "ms": round(ms)})
        print(f"  [{'PASS' if rows[-1]['ok'] else 'FAIL'}] {u:<62} -> {r['category']:<14} {r['tool']:<26} "
              f"amb={r['ambiguous']!s:<5} | {str(r.get('spoken'))[:70]}")
    return rows


def main():
    rows = asyncio.run(main_async())
    n = len(rows)
    noise = [r for r in rows if r["expected_tool"] == "none"]
    m = {"cases": n, "routing_accuracy": round(sum(r["ok"] for r in rows) / n, 3),
         "noise_correctly_ignored": f"{sum(r['got_tool'] == 'none' and not r['stored'] for r in noise)}/{len(noise)}",
         "commands_correct": f"{sum(r['ok'] for r in rows[:15])}/15",
         "latency_p50_ms": statistics.median(r["ms"] for r in rows)}
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    p = ROOT / "eval" / "results" / f"benchmark_router_{ts}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"metrics": m, "rows": rows}, indent=2))
    md = ["# Larvis utterance router (real Gemini, text in)", "",
          f"Run {ts} · router model from `GEMINI_ROUTER_MODEL` · raw `{p.relative_to(ROOT)}`", "",
          "| Metric | Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in m.items()] + [
          "", "| Utterance | Expected | Routed | Ambiguous | OK |", "|---|---|---|---|---|"] + [
          f"| {r['utterance']} | `{r['expected_tool']}` | `{r['got_tool']}` ({r['category']}) {json.dumps(r['got_args'])[:90]} | "
          f"{r['ambiguous']} | {'✅' if r['ok'] else '❌'} |" for r in rows]
    (ROOT / "docs" / "BENCHMARK_ROUTER.md").write_text("\n".join(md) + "\n")
    print("\n" + "\n".join(md[:10]))


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "scripts"))
    main()
