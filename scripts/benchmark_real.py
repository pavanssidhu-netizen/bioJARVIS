"""Real-clip benchmark: stock Gemini (native video) vs Larvis pipeline, on team-recorded, hand-labelled clips.

Put clips (mp4/mov/webm or jpg/png stills) in eval/real_clips/ and labels in eval/real_clips/labels.csv:
    file,bubbles,drops,notes
    straw_2bubbles.mov,2,0,
    dropper_3.mov,0,3,
    clean_straw.mov,0,0,clean control
    blurry.mov,-1,0,unusable   (bubbles=-1 marks an unusable clip that should be abstained on)

    .venv/bin/python scripts/benchmark_real.py --runs 3

  A  Stock Gemini  : whole clip (native video, full frame rate) -> count bubbles at the end + drops dispensed
  B  Larvis        : 1 fps windows of 5 frames -> Gemini perception (actions, objects)  +  specialist council on the
                     last frame (bubbles)  -> numbers Larvis would act on
  C  Larvis system : B with cross-model verification (Gemini vs specialist bubble count); disagreement -> human review

Household mock-ups of a microfluidic channel (water-filled straw/tubing); proof of concept, NOT lab validation.
Writes eval/results/benchmark_real_<ts>.json and docs/BENCHMARK_REAL.md; pushes scores to Langfuse if configured.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.mkdtemp(prefix='larvis-real-')) / 'b.db'}"
os.environ["TURSO_DATABASE_URL"] = ""

import cv2  # noqa: E402
from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

from backend.app.config import get_settings  # noqa: E402
from backend.app.orchestration.models import model_for  # noqa: E402

CLIPS = ROOT / "eval" / "real_clips"
WORK = Path(tempfile.mkdtemp(prefix="larvis-norm-"))
VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v", ".avi", ".3gp"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}
SEM: asyncio.Semaphore | None = None


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def normalise(src: Path) -> Path:
    """Any phone video (incl. HEVC .MOV) -> 640 px H.264 mp4, max 20 s, no audio."""
    out = WORK / (src.stem + ".mp4")
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-i", str(src), "-t", "20", "-an", "-vf", "scale=640:-2",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out


def frames_1fps(video: Path) -> list[bytes]:
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    step, i, out = max(1, int(round(fps))), 0, []
    while True:
        ok, img = cap.read()
        if not ok:
            break
        if i % step == 0:
            out.append(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])[1].tobytes())
        i += 1
    cap.release()
    return out


async def gemini_json(contents, schema):
    global SEM
    if SEM is None or getattr(SEM, "_loop", None) not in (None, asyncio.get_running_loop()):
        SEM = asyncio.Semaphore(5)
    async with SEM:
        client = genai.Client(api_key=get_settings().gemini_api_key)
        t0 = time.perf_counter()
        try:
            r = await client.aio.models.generate_content(
                model=model_for("vision"), contents=contents,
                config=types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=schema))
            return json.loads(r.text or "{}"), (time.perf_counter() - t0) * 1000
        except Exception as e:  # noqa: BLE001
            return {"_error": f"{type(e).__name__}: {str(e)[:160]}"}, (time.perf_counter() - t0) * 1000
        finally:
            await client.aio.aclose()


STOCK_PROMPT = (
    "This is a short phone video of a lab bench mock-up: a clear straw/tube filled with liquid acts as a "
    "microfluidic channel, and a straw or dropper may dispense drops. Answer from the video:\n"
    "1. bubbles: number of distinct air bubbles / air pockets inside the liquid-filled channel in the FINAL frames "
    "(do not count reflections, glare, the open ends, or the liquid surface).\n"
    "2. drops: number of distinct drops dispensed during the whole video.\n"
    "If the video is too blurry/dark/obstructed to judge, set unusable=true.")
STOCK_SCHEMA = {"type": "object", "properties": {"bubbles": {"type": "integer"}, "drops": {"type": "integer"},
                                                 "unusable": {"type": "boolean"}},
                "required": ["bubbles", "drops", "unusable"]}


async def run_stock(video: Path | None, image: bytes | None):
    part = (types.Part.from_bytes(data=video.read_bytes(), mime_type="video/mp4") if video else
            types.Part.from_bytes(data=image, mime_type="image/jpeg"))
    g, ms = await gemini_json([part, STOCK_PROMPT], STOCK_SCHEMA)
    return {"bubbles": None if g.get("unusable") else g.get("bubbles"), "drops": g.get("drops"),
            "abstained": bool(g.get("unusable")), "ms": round(ms), "error": g.get("_error")}


async def run_larvis(frames: list[bytes]):
    """Exactly the live pipeline's components: Gemini perception on 5-frame windows + specialist on last frame."""
    from backend.app.vision import decode_image
    from backend.app.vision.gemini import GeminiVisionProvider
    from modal_app.specialist import model as specialist
    import base64
    imgs = [decode_image(base64.b64encode(f).decode(), 4_000_000) for f in frames]
    gem = GeminiVisionProvider()
    t0 = time.perf_counter()
    windows = [imgs[i:i + 5] for i in range(0, len(imgs), 5)] or [imgs]
    results = await asyncio.gather(*(gem.analyse_frames(w, 1.0, "count drops dispensed; track bubbles", "")
                                     for w in windows), return_exceptions=True)
    drops, g_bubbles, err = 0, 0, None
    for r in results:
        if isinstance(r, Exception):
            err = f"{type(r).__name__}: {str(r)[:120]}"
            continue
        drops += sum(int(a.get("count", 0) or 0) for a in r.structured.get("actions", [])
                     if "drop" in str(a.get("action", "")).lower())
    last = results[-1] if not isinstance(results[-1], Exception) else None
    if last is not None:
        bo = [o for o in last.structured.get("objects", []) if "bubble" in str(o.get("label", "")).lower()]
        g_bubbles = len(bo) if len(bo) > 1 else ((bo[0].get("count") or 1) if bo else 0)
    gms = (time.perf_counter() - t0) * 1000
    t1 = time.perf_counter()
    s = await asyncio.to_thread(specialist.predict, frames[-1], "", experiment_id="exp_001", step_id="step_05",
                                include_overlay=False)
    sms = (time.perf_counter() - t1) * 1000
    return {"drops": drops, "gemini_bubbles": g_bubbles, "specialist_bubbles": s.get("count"),
            "specialist_abstained": bool(s.get("abstained")), "gemini_ms": round(gms), "specialist_ms": round(sms),
            "windows": len(windows), "error": err}


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0, c - h), 3), round(min(1, c + h), 3)]


def count_metrics(pairs: list[tuple[int, int | None]]):
    """pairs = (truth, prediction or None if abstained)."""
    n = len(pairs)
    answered = [(t, p) for t, p in pairs if p is not None]
    errs = [abs(t - p) for t, p in answered]
    exact = sum(e == 0 for e in errs)
    return {"n": n, "answered": len(answered), "exact": round(exact / n, 3) if n else None, "exact_ci95": wilson(exact, n),
            "within_1": round(sum(e <= 1 for e in errs) / n, 3) if n else None,
            "mae": round(statistics.fmean(errs), 3) if errs else None,
            "bias": round(statistics.fmean(p - t for t, p in answered), 3) if answered else None}


def summarise(rows):
    usable = [r for r in rows if r["truth_bubbles"] >= 0]
    unusable = [r for r in rows if r["truth_bubbles"] < 0]
    clean = [r for r in usable if r["truth_bubbles"] == 0]
    out = {}
    for name, key in (("A_stock_gemini_video", lambda r: r["A"]["bubbles"]),
                      ("B_larvis_specialist", lambda r: None if r["B"]["specialist_abstained"] else r["B"]["specialist_bubbles"]),
                      ("B_larvis_gemini_1fps", lambda r: r["B"]["gemini_bubbles"])):
        m = count_metrics([(r["truth_bubbles"], key(r)) for r in usable])
        m["false_alarm_on_clean"] = round(sum((key(r) or 0) > 0 for r in clean) / len(clean), 3) if clean else None
        out[f"bubbles.{name}"] = m
    # C: cross-check
    agree = [r for r in usable if r["B"]["gemini_bubbles"] == r["B"]["specialist_bubbles"] and not r["B"]["specialist_abstained"]]
    esc = [r for r in usable if r not in agree]
    silent = [r for r in agree if r["B"]["specialist_bubbles"] != r["truth_bubbles"]]
    wrong_spec = [r for r in usable if r["B"]["specialist_bubbles"] != r["truth_bubbles"]]
    out["bubbles.C_larvis_crosscheck"] = {
        "n": len(usable), "silent_error_rate": round(len(silent) / len(usable), 3) if usable else None,
        "silent_error_ci95": wilson(len(silent), len(usable)),
        "auto_accepted_accuracy": round(1 - len(silent) / len(agree), 3) if agree else None,
        "human_review_rate": round(len(esc) / len(usable), 3) if usable else None,
        "specialist_errors_caught": round(sum(r in esc for r in wrong_spec) / len(wrong_spec), 3) if wrong_spec else 1.0}
    out["unusable.abstain_rate"] = {
        "A_stock_gemini_video": round(sum(r["A"]["abstained"] for r in unusable) / len(unusable), 3) if unusable else None,
        "B_larvis_specialist": round(sum(r["B"]["specialist_abstained"] for r in unusable) / len(unusable), 3) if unusable else None}
    drows = [r for r in rows if r["truth_drops"] >= 0]
    out["drops.A_stock_gemini_video"] = count_metrics([(r["truth_drops"], r["A"]["drops"]) for r in drows])
    out["drops.B_larvis_1fps_windows"] = count_metrics([(r["truth_drops"], r["B"]["drops"]) for r in drows])
    out["latency_ms_p50"] = {"A_stock_gemini_video": statistics.median([r["A"]["ms"] for r in rows]),
                             "B_gemini_perception": statistics.median([r["B"]["gemini_ms"] for r in rows]),
                             "B_specialist": statistics.median([r["B"]["specialist_ms"] for r in rows])}
    return out


async def run_all(entries, runs: int):
    prepared = []
    for e in entries:
        src = CLIPS / e["file"]
        if src.suffix.lower() in VIDEO_EXT:
            v = normalise(src)
            fr = frames_1fps(v)
            prepared.append((e, v, None, fr))
        else:
            img = cv2.imread(str(src))
            jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])[1].tobytes()
            prepared.append((e, None, jpg, [jpg]))
    all_runs = []
    for k in range(runs):
        async def one(item):
            e, v, img, fr = item
            a, b = await asyncio.gather(run_stock(v, img), run_larvis(fr))
            return {"file": e["file"], "truth_bubbles": e["bubbles"], "truth_drops": e["drops"], "notes": e["notes"],
                    "frames": len(fr), "A": a, "B": b}
        rows = await asyncio.gather(*(one(p) for p in prepared))
        for r in rows:
            print(f"  run{k + 1} {r['file']:<34} truth b={r['truth_bubbles']:>2} d={r['truth_drops']:>2} | "
                  f"A b={r['A']['bubbles']!s:>4} d={r['A']['drops']!s:>3} | B spec b={r['B']['specialist_bubbles']!s:>4} "
                  f"gem b={r['B']['gemini_bubbles']} d={r['B']['drops']}")
        all_runs.append({"run": k + 1, "rows": rows, "metrics": summarise(rows)})
    return all_runs


def aggregate(all_runs):
    """mean and range across runs for every scalar metric."""
    agg: dict = {}
    for name in all_runs[0]["metrics"]:
        agg[name] = {}
        for k, v in all_runs[0]["metrics"][name].items():
            vals = [r["metrics"][name][k] for r in all_runs]
            if all(isinstance(x, (int, float)) for x in vals):
                agg[name][k] = {"mean": round(statistics.fmean(vals), 3), "min": min(vals), "max": max(vals)}
            else:
                agg[name][k] = vals[0]
    return agg


def report(out: dict, path: Path) -> str:
    a = out["aggregate"]
    f = lambda d: (f"{d['mean']}" + (f" ({d['min']}–{d['max']})" if d["min"] != d["max"] else "")) if isinstance(d, dict) else str(d)  # noqa: E731
    lines = ["# Larvis real-clip benchmark (household microfluidic mock-ups)", "",
             f"Run {out['run_at']} · {out['clips']} clips × {out['runs']} runs · model `{out['model']}` · raw `{path.relative_to(ROOT)}`",
             "", "Clips recorded and labelled by the team with household items (water-filled straw/tubing as the channel, "
             "straw pipette as dropper). Proof of concept on real camera footage, **not** validation on lab hardware. "
             "Values: mean across runs (min–max); 95% Wilson CI from run 1.", "",
             "## Bubble counting", "", "| System | exact | 95% CI | within ±1 | MAE | bias | false alarm on clean |", "|---|---|---|---|---|---|---|"]
    for k, label in (("bubbles.A_stock_gemini_video", "A. Stock Gemini (native video)"),
                     ("bubbles.B_larvis_specialist", "B. Larvis specialist (acts on this)"),
                     ("bubbles.B_larvis_gemini_1fps", "B'. Gemini perception @1 fps")):
        m = a[k]
        lines.append(f"| {label} | {f(m['exact'])} | {m['exact_ci95']} | {f(m['within_1'])} | {f(m['mae'])} | {f(m['bias'])} | {f(m['false_alarm_on_clean'])} |")
    c = a["bubbles.C_larvis_crosscheck"]
    lines += ["", "**C. Larvis system (cross-check, disagreement → human review):** "
              f"silent error rate {f(c['silent_error_rate'])} (CI {c['silent_error_ci95']}), accuracy of auto-accepted counts "
              f"{f(c['auto_accepted_accuracy'])}, human review rate {f(c['human_review_rate'])}, specialist errors caught "
              f"{f(c['specialist_errors_caught'])}.", "",
              f"Abstention on unusable clips: stock Gemini {f(a['unusable.abstain_rate']['A_stock_gemini_video'])}, "
              f"Larvis {f(a['unusable.abstain_rate']['B_larvis_specialist'])}.", "",
              "## Drop counting", "", "| System | exact | 95% CI | within ±1 | MAE | bias |", "|---|---|---|---|---|---|"]
    for k, label in (("drops.A_stock_gemini_video", "A. Stock Gemini (native video, full fps)"),
                     ("drops.B_larvis_1fps_windows", "B. Larvis live windows (1 fps)")):
        m = a[k]
        lines.append(f"| {label} | {f(m['exact'])} | {m['exact_ci95']} | {f(m['within_1'])} | {f(m['mae'])} | {f(m['bias'])} |")
    lat = a["latency_ms_p50"]
    lines += ["", f"Median latency per clip: stock Gemini video {f(lat['A_stock_gemini_video'])} ms · "
              f"Larvis Gemini perception {f(lat['B_gemini_perception'])} ms · specialist {f(lat['B_specialist'])} ms.", "",
              "Interpretation guide: the specialist was built on synthetic microfluidic images, so real household footage "
              "is out of its domain; C shows whether the cross-check converts its failures into human review rather "
              "than silent errors. 1 fps windows under-count fast drops by design (live latency/cost trade-off)."]
    return "\n".join(lines) + "\n"


def push_langfuse(out):
    try:
        from backend.app.orchestration.langfuse_export import LangfuseConfig, score_event, send
    except Exception:  # noqa: BLE001
        return
    cfg = LangfuseConfig()
    if not cfg.configured:
        print("[langfuse] not configured; skipping")
        return
    ev = []
    for name, m in out["aggregate"].items():
        for k, v in m.items():
            if isinstance(v, dict) and "mean" in v:
                ev.append(score_event(f"real.{name}.{k}", float(v["mean"]), session_id=f"bench-real-{out['run_id']}",
                                      environment=cfg.environment, metadata={"min": v["min"], "max": v["max"]}))
    print("[langfuse]", send(ev, cfg))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    a = ap.parse_args()
    labels = CLIPS / "labels.csv"
    if not labels.exists():
        sys.exit(f"Put clips + labels.csv in {CLIPS} (see docstring)")
    entries = []
    for row in csv.DictReader(labels.open()):
        if not row.get("file") or not (CLIPS / row["file"].strip()).exists():
            print("skip (missing file):", row.get("file"))
            continue
        entries.append({"file": row["file"].strip(), "bubbles": int(row.get("bubbles") or 0),
                        "drops": int(row.get("drops") or 0), "notes": (row.get("notes") or "").strip()})
    print(f"{len(entries)} clips, {a.runs} runs")
    runs = asyncio.run(run_all(entries, a.runs))
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = {"run_id": ts, "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": model_for("vision"),
           "clips": len(entries), "runs": a.runs, "aggregate": aggregate(runs), "per_run": runs}
    path = ROOT / "eval" / "results" / f"benchmark_real_{ts}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, default=str))
    md = report(out, path)
    (ROOT / "docs" / "BENCHMARK_REAL.md").write_text(md)
    print("\n" + md)
    push_langfuse(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
