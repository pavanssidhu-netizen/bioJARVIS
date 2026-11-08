"""LABMATE eval loop.

    .venv/bin/python scripts/eval.py                       # system metrics from the app DB (no model calls)
    .venv/bin/python scripts/eval.py --since 120m          # last 2 hours
    .venv/bin/python scripts/eval.py --qa                  # + log-agent QA on a synthetic log  (~8 Gemini calls)
    .venv/bin/python scripts/eval.py --clips eval/clips.json   # + counting accuracy on labelled clips (Gemini [+ specialist])
    .venv/bin/python scripts/eval.py --push                # also push scores to Langfuse

Model-calling evals run against a throwaway SQLite DB, never the live Turso DB. Report -> eval/results/<ts>.json
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                    "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}


def first_int(text: str, unit: str | None = None):
    """Number attached to `unit` ('3 drops', 'three tubes', 'step 2') if given, else the first number."""
    t = text.lower()
    num = r"(\d+|" + "|".join(WORDS) + r")"
    if unit:
        u = unit.rstrip("s")
        for pat in (rf"\b{num}\s+(?:\w+\s+){{0,2}}{u}s?\b", rf"\b{u}s?\s+{num}\b"):
            m = re.search(pat, t)
            if m:
                g = m.group(1)
                return int(g) if g.isdigit() else WORDS[g]
    for tok in re.findall(r"\d+|[a-z]+", t):
        if tok.isdigit():
            return int(tok)
        if tok in WORDS:
            return WORDS[tok]
    return None


def parse_since(s: str) -> str:
    if not s:
        return ""
    m = re.fullmatch(r"(\d+)([mhd])", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = timedelta(minutes=n) if unit == "m" else timedelta(hours=n) if unit == "h" else timedelta(days=n)
        return (datetime.now(timezone.utc) - delta).isoformat(timespec="milliseconds")
    return s


def use_temp_db() -> Path:
    from backend.app.db import get_db
    p = Path(tempfile.mkdtemp(prefix="labmate-eval-")) / "eval.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{p}"
    os.environ["TURSO_DATABASE_URL"] = ""
    get_db.cache_clear()
    return p


# ------------------------------------------------------------------------------------------- QA eval
QA_CASES = [  # (question, expected number, unit the number is attached to)
    ("How many drops of indicator did I add in total?", 7, "drop"),
    ("How many drops did I add about 30 seconds ago?", 3, "drop"),
    ("How many drops did I add roughly two minutes ago?", 4, "drop"),
    ("How many tubes did I note turned blue?", 1, "tube"),
    ("Which protocol step did the most recent drops correspond to? Answer with the step number only.", 2, "step"),
]


def seed_synthetic_log(store) -> None:
    """Deterministic log: 4 drops ~120 s ago, 3 drops ~30 s ago (one rejected duplicate window), notes."""
    from backend.app.contracts import EventIn, ReviewIn
    rec = store.start_recording("exp-demo")
    now = datetime.now(timezone.utc)

    def perception(ago: int, drops: int, key: str):
        end = (now - timedelta(seconds=ago)).isoformat(timespec="milliseconds")
        start = (now - timedelta(seconds=ago + 4)).isoformat(timespec="milliseconds")
        ev, _ = store.ingest(EventIn(session_id=rec.id, experiment_id="exp-demo", source_modality="video",
                                     event_type="perception", model_name="eval-fixture", idempotency_key=key, payload={
            "window_start": start, "window_end": end, "frame_count": 5, "scene_summary": "dropper over tube",
            "objects": [{"label": "dropper bottle", "certainty": "certain"}, {"label": "test tube", "certainty": "certain"}],
            "actions": [{"action": "dispense drop", "object": "test tube", "count": drops, "certainty": "likely",
                         "protocol_step": "S2"}], "limitations": [], "provider": "fixture", "model": "eval-fixture"}))
        return ev

    perception(120, 4, "qa-fixture-p1")
    perception(30, 3, "qa-fixture-p2")
    dup = perception(29, 3, "qa-fixture-p3")  # duplicate window the researcher rejected
    store.review(dup.id, ReviewIn(action="reject", reviewer="eval"))
    store.ingest(EventIn(session_id=rec.id, experiment_id="exp-demo", source_modality="speech",
                         event_type="observation_proposal", idempotency_key="qa-fixture-n1", model_name="eval-fixture",
                         payload={"observation_type": "colour_change", "summary": "Tube A turned blue",
                                  "subject": "tube A", "protocol_step": "S4"}))


async def run_qa() -> dict:
    use_temp_db()
    from backend.app.contracts import LogQueryIn
    from backend.app.db import get_db
    from backend.app.services.query_agent import answer_question
    from backend.app.services.store import Store
    st = Store(get_db())
    seed_synthetic_log(st)
    rows, correct, grounded = [], 0, 0
    for q, expected, unit in QA_CASES:
        r = await answer_question(st, LogQueryIn(experiment_id="exp-demo", question=q))
        got = first_int(r.answer, unit)
        ok = got == expected
        correct += ok
        grounded += bool(r.evidence_event_ids)
        rows.append({"question": q, "expected": expected, "got": got, "ok": ok, "answer": r.answer,
                     "confidence": r.confidence, "evidence": len(r.evidence_event_ids)})
        print(f"  [{'PASS' if ok else 'FAIL'}] {q}  expected={expected} got={got}  | {r.answer[:90]}")
    from backend.app.evals.metrics import compute
    sysm = compute(get_db())
    return {"qa.accuracy": round(correct / len(QA_CASES), 3), "qa.grounded_rate": round(grounded / len(QA_CASES), 3),
            "qa.hallucinated_id_rate": sysm["grounding.hallucinated_id_rate"],
            "qa.latency_p50_ms": sysm["latency.query.p50_ms"], "qa.cases": rows}


# ------------------------------------------------------------------------------------------- clip eval
def load_frames(entry: dict, base: Path) -> list[bytes]:
    import cv2
    p = (base / entry["path"]).resolve()
    interval = float(entry.get("frame_interval_s", 1.0))
    width = int(entry.get("width", 512))
    frames: list[bytes] = []

    def enc(img):
        h, w = img.shape[:2]
        if w > width:
            img = cv2.resize(img, (width, int(h * width / w)))
        return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()

    if p.is_dir():
        for f in sorted(x for x in p.iterdir() if x.suffix.lower() in (".jpg", ".jpeg", ".png")):
            frames.append(enc(cv2.imread(str(f))))
    else:
        cap = cv2.VideoCapture(str(p))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        step, i = max(1, int(round(fps * interval))), 0
        while True:
            ok, img = cap.read()
            if not ok:
                break
            if i % step == 0:
                frames.append(enc(img))
            i += 1
        cap.release()
    if not frames:
        raise ValueError(f"no frames from {p}")
    return frames


def matches(action: str, target: str) -> bool:
    a, t = action.lower(), target.lower()
    return t in a or all(w in a for w in t.split())


async def run_clips(manifest: Path) -> dict:
    use_temp_db()
    from backend.app.contracts import PerceptionWindowIn
    from backend.app.db import get_db
    from backend.app.evals.metrics import count_accuracy
    from backend.app.services.perception import process_window
    from backend.app.services.store import Store
    st = Store(get_db())
    entries = json.loads(manifest.read_text())
    gem, spec, rows = [], [], []
    for e in entries:
        frames = load_frames(e, manifest.parent)
        n = int(e.get("window_frames", 5))
        target = e.get("target_action", "dispense drop")
        g_total, s_total, s_any = 0, 0, False
        for i in range(0, len(frames), n):
            chunk = frames[i:i + n]
            r = await process_window(st, PerceptionWindowIn(
                frames_base64=[base64.b64encode(f).decode() for f in chunk], frame_interval_s=e.get("frame_interval_s", 1.0),
                window_start="1970-01-01T00:00:00Z", window_end="1970-01-01T00:00:05Z", experiment_id="exp-demo",
                idempotency_key=f"clip-{uuid.uuid4().hex}"))
            g_total += sum(a.count for a in r.perception.actions if matches(a.action, target))
            sp = r.perception.specialist
            if sp and "error" not in sp:
                s_any = True
                s_total += int((sp.get("counts_by_label") or {}).get(e.get("specialist_label", "drop"), sp.get("count", 0)))
        gem.append({"expected": e["expected_count"], "predicted": g_total})
        if s_any:
            spec.append({"expected": e["expected_count"], "predicted": s_total})
        rows.append({"id": e["id"], "expected": e["expected_count"], "gemini": g_total,
                     "specialist": s_total if s_any else None, "frames": len(frames)})
        print(f"  clip {e['id']}: expected {e['expected_count']}  gemini {g_total}  "
              f"specialist {s_total if s_any else '-'}  ({len(frames)} frames)")
    out = {f"gemini.{k}": v for k, v in count_accuracy(gem).items()}
    if spec:
        out |= {f"specialist.{k}": v for k, v in count_accuracy(spec).items()}
    out["clips"] = rows
    return out


# ------------------------------------------------------------------------------------------- main
def push_scores(report: dict) -> None:
    from backend.app.orchestration.langfuse_export import LangfuseConfig, score_event, send
    cfg = LangfuseConfig()
    if not cfg.configured:
        print("[langfuse] not configured; skipping push")
        return
    run_id = report["run_id"]
    events = [score_event(k, float(v), session_id=f"eval-{run_id}", comment="labmate eval", environment=cfg.environment,
                          metadata={"run_id": run_id, "git": report.get("git")})
              for k, v in report["metrics"].items() if isinstance(v, (int, float)) and not isinstance(v, bool)]
    res = send(events, cfg)
    print(f"[langfuse] pushed {res['sent']} scores ({res['errors']} errors) session=eval-{run_id}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="")
    ap.add_argument("--experiment", default=None)
    ap.add_argument("--qa", action="store_true")
    ap.add_argument("--clips", type=Path)
    ap.add_argument("--push", action="store_true")
    a = ap.parse_args()

    import subprocess
    git = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    report: dict = {"run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"), "git": git, "metrics": {}}

    from backend.app.db import get_db
    from backend.app.evals.metrics import compute
    print(f"== system metrics ({get_db().label}) ==")
    sysm = compute(get_db(), parse_since(a.since), a.experiment)
    for k, v in sysm.items():
        if v is not None and not k.endswith(".n"):
            print(f"  {k:<40} {v}")
    report["metrics"].update(sysm)

    if a.qa:
        print("== log-agent QA (synthetic log, live Gemini) ==")
        qa = asyncio.run(run_qa())
        report["qa_cases"] = qa.pop("qa.cases")
        report["metrics"].update(qa)
        print(f"  accuracy {qa['qa.accuracy']}  grounded {qa['qa.grounded_rate']}  "
              f"hallucinated-id rate {qa['qa.hallucinated_id_rate']}")
    if a.clips:
        print("== counting accuracy (labelled clips) ==")
        cl = asyncio.run(run_clips(a.clips))
        report["clips"] = cl.pop("clips")
        report["metrics"].update(cl)
        for k, v in cl.items():
            print(f"  {k:<40} {v}")

    out = ROOT / "eval" / "results" / f"{report['run_id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"report: {out}")
    if a.push:
        push_scores(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
