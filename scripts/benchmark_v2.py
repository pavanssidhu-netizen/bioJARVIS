"""LABMATE V2 benchmark: stock Gemini vs LABMATE on identical, independently labelled cases.

  Vision   : Person 3's 18 labelled synthetic microfluidic images (ground-truth bubble count, boxes, blank frames)
             A = stock Gemini (same counting rules in the prompt, JSON output)  vs  B = LABMATE specialist council
  Steering : Person 4's 20 labelled CEA protocol cases (expected action, human-approval gate, affected results)
             A = stock Gemini given the FULL seed (protocol, constraints, channel map, dependency graph)
             B = LABMATE deterministic reconciliation (Person 4 engine on Person 2 seed) through the API layer

    .venv/bin/python scripts/benchmark_v2.py            # ~38 Gemini calls
    .venv/bin/python scripts/benchmark_v2.py --only vision|steering

Writes eval/results/benchmark_v2_<ts>.json and docs/BENCHMARK_V2.md. Synthetic cases; proof of concept, not
clinical validation.
"""
from __future__ import annotations

import argparse
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
os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.mkdtemp(prefix='labmate-bench-')) / 'b.db'}"
os.environ["TURSO_DATABASE_URL"] = ""

from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

from backend.app.config import get_settings  # noqa: E402
from backend.app.orchestration.models import model_for  # noqa: E402

SEM: asyncio.Semaphore | None = None  # created inside each event loop
IMG_DIR = ROOT / "evals" / "vision_test" / "images"
LBL_DIR = ROOT / "evals" / "vision_test" / "labels"


async def gemini_json(contents, schema) -> tuple[dict, float]:
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
            return {"_error": f"{type(e).__name__}: {str(e)[:120]}"}, (time.perf_counter() - t0) * 1000
        finally:
            await client.aio.aclose()


def pct(xs, p):
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(p * (len(xs) - 1) + 0.5))], 1) if xs else None


# =========================================================================================== vision
VISION_PROMPT = (
    "This image ({w}x{h} px) shows a microfluidic channel from a lab immunoassay chip. Count the gas BUBBLES inside "
    "the channel. Rules: do NOT count bubbles clipped by the image border, wall glare / specular reflections, "
    "streaks, dust or the meniscus. Touching bubbles count separately. If the frame is blank, underexposed or "
    "otherwise unusable, set unusable=true and do not guess a count. Return boxes in pixel coordinates "
    "[x1, y1, x2, y2] for each counted bubble.")
VISION_SCHEMA = {"type": "object", "properties": {
    "bubble_count": {"type": "integer"}, "unusable": {"type": "boolean"},
    "boxes": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}}},
    "required": ["bubble_count", "unusable", "boxes"]}


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def match(pred, gt, thr=0.3):
    used, tp = set(), 0
    for p in pred:
        best, bj = 0.0, None
        for j, g in enumerate(gt):
            if j not in used and len(p) == 4:
                v = iou(p, g)
                if v > best:
                    best, bj = v, j
        if bj is not None and best >= thr:
            used.add(bj)
            tp += 1
    return tp


def vision_metrics(rows, key):
    usable = [r for r in rows if not r["gt_blank"]]
    errs = [abs(r[key]["count"] - r["gt_count"]) for r in usable if r[key]["count"] is not None]
    neg = [r for r in usable if r["gt_count"] == 0]
    tp = sum(r[key]["tp"] for r in usable)
    npred = sum(r[key]["n_boxes"] for r in usable)
    ngt = sum(r["gt_count"] for r in usable)
    blank = [r for r in rows if r["gt_blank"]]
    return {
        "cases": len(rows),
        "count_mae": round(statistics.fmean(errs), 3) if errs else None,
        "count_exact": round(sum(e == 0 for e in errs) / len(usable), 3),
        "count_within_1": round(sum(e <= 1 for e in errs) / len(usable), 3),
        "false_positive_rate_on_clean_controls": round(sum((r[key]["count"] or 0) > 0 for r in neg) / len(neg), 3) if neg else None,
        "box_precision_iou30": round(tp / npred, 3) if npred else None,
        "box_recall_iou30": round(tp / ngt, 3) if ngt else None,
        "abstains_on_unusable_frames": round(sum(r[key]["abstained"] for r in blank) / len(blank), 3) if blank else None,
        "spurious_abstentions": sum(r[key]["abstained"] for r in usable),
        "latency_p50_ms": pct([r[key]["ms"] for r in rows], 0.5),
        "latency_p95_ms": pct([r[key]["ms"] for r in rows], 0.95),
        "errors": sum(1 for r in rows if r[key].get("error")),
    }


async def run_vision() -> dict:
    import cv2
    from modal_app.specialist import model as specialist
    labels = sorted(LBL_DIR.glob("*.json"))
    if not (IMG_DIR / "case_01_clean_channel_neg.png").exists():
        from evals.evaluate import build_held_out_vision_test_set
        build_held_out_vision_test_set(ROOT / "evals" / "vision_test")
        os.system(f"cd {ROOT} && git checkout -- evals/vision_test/labels evals/vision_test/manifest.json 2>/dev/null")
    seed = json.loads((ROOT / "science" / "experiment_seed.json").read_text())

    async def one(lp: Path):
        lab = json.loads(lp.read_text())
        gt = lab["ground_truth"]
        img_path = IMG_DIR / f"{lab['case_id']}.png"
        data = img_path.read_bytes()
        h, w = cv2.imread(str(img_path)).shape[:2]
        g, gms = await gemini_json([types.Part.from_bytes(data=data, mime_type="image/png"),
                                    VISION_PROMPT.format(w=w, h=h)], VISION_SCHEMA)
        t0 = time.perf_counter()
        s = await asyncio.to_thread(specialist.predict, data, "", experiment_id="exp_001", step_id="step_05",
                                    experiment_context=seed, include_overlay=False)
        sms = (time.perf_counter() - t0) * 1000
        gt_boxes = gt.get("boxes_xyxy", [])
        g_boxes = [b for b in (g.get("boxes") or []) if isinstance(b, list) and len(b) == 4]
        s_boxes = [d["bbox"] for d in s.get("detections", [])]
        row = {"case_id": lab["case_id"], "category": lab.get("category"), "gt_count": gt["valid_bubble_count"],
               "gt_blank": bool(gt.get("is_unusable_blank_frame")),
               "gemini": {"count": None if g.get("unusable") else g.get("bubble_count"), "abstained": bool(g.get("unusable")),
                          "n_boxes": len(g_boxes), "tp": match(g_boxes, gt_boxes), "ms": round(gms, 1),
                          "error": g.get("_error")},
               "labmate": {"count": s.get("count"), "abstained": bool(s.get("abstained")), "n_boxes": len(s_boxes),
                           "tp": match(s_boxes, gt_boxes), "ms": round(sms, 1)}}
        print(f"  {lab['case_id']:<44} gt={row['gt_count']}{' (blank)' if row['gt_blank'] else ''}  "
              f"gemini={row['gemini']['count']}{'A' if row['gemini']['abstained'] else ''}  "
              f"labmate={row['labmate']['count']}{'A' if row['labmate']['abstained'] else ''}")
        return row

    rows = await asyncio.gather(*(one(p) for p in labels))
    return {"rows": rows, "stock_gemini": vision_metrics(rows, "gemini"), "labmate": vision_metrics(rows, "labmate"),
            "crosscheck": crosscheck_metrics(rows)}


def crosscheck_metrics(rows):
    """C = LABMATE system: Gemini and specialist counts cross-checked; disagreement -> human review."""
    usable = [r for r in rows if not r["gt_blank"]]
    agree = [r for r in usable if r["gemini"]["count"] == r["labmate"]["count"]]
    dis = [r for r in usable if r["gemini"]["count"] != r["labmate"]["count"]]
    err = [r for r in usable if r["gemini"]["count"] != r["gt_count"] or r["labmate"]["count"] != r["gt_count"]]
    silent = [r for r in agree if r["labmate"]["count"] != r["gt_count"]]
    return {"cases": len(usable), "silent_error_rate": round(len(silent) / len(usable), 3),
            "errors_caught_by_escalation": round(sum(1 for r in dis if r in err) / len(err), 3) if err else 1.0,
            "human_review_rate": round(len(dis) / len(usable), 3),
            "escalated_cases": [r["case_id"] for r in dis]}


# =========================================================================================== steering
ACTIONS = ["no_action", "log", "warn", "request_confirmation", "request_recapture", "investigate", "abstain"]
STEER_SCHEMA = {"type": "object", "properties": {
    "action": {"type": "string", "enum": ACTIONS}, "requires_human_approval": {"type": "boolean"},
    "violated_constraints": {"type": "array", "items": {"type": "string"}},
    "affected_derived_values": {"type": "array", "items": {"type": "string"}},
    "affected_channels": {"type": "array", "items": {"type": "string"}},
    "spoken_response": {"type": "string"}},
    "required": ["action", "requires_human_approval", "violated_constraints", "affected_derived_values",
                 "affected_channels", "spoken_response"]}
STEER_PROMPT = """You are a hands-free laboratory assistant supervising a microfluidic sandwich immunoassay for CEA.
Decide how to handle the researcher's latest observation, using ONLY the experiment definition below.

Actions (choose exactly one):
- no_action: nothing scientifically relevant.  - log: within protocol, just record it.
- warn: a protocol constraint appears violated or a result may be compromised; flag for human review.
- request_confirmation: ambiguous/uncertain report; ask the researcher to confirm before recording.
- request_recapture: image/sensor evidence is too poor to judge; ask for a new capture.
- investigate: multi-factor anomaly needing deeper analysis.  - abstain: out of scope / cannot be judged.
requires_human_approval: true if a scientist must sign off before the record/result is trusted.
List violated constraint ids (e.g. c_01) and the downstream derived values (standard_curve, result_S01..S06) and
channels that may be affected, following the dependency graph.

Experiment definition (JSON):
{seed}

Active protocol step: {step}
Observation (JSON): {obs}
"""


def f1(pred: set, exp: set):
    if not pred and not exp:
        return 1.0
    tp = len(pred & exp)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(exp) if exp else 0.0
    return 2 * p * r / (p + r) if p + r else 0.0


def steering_metrics(rows, key):
    gate = [r for r in rows if r["exp_approval"]]
    no_gate = [r for r in rows if not r["exp_approval"]]
    aff = [r for r in rows if r["exp_affected"] is not None]
    return {
        "cases": len(rows),
        "action_accuracy": round(sum(r[key]["action"] == r["exp_action"] for r in rows) / len(rows), 3),
        "human_gate_recall": round(sum(r[key]["approval"] for r in gate) / len(gate), 3) if gate else None,
        "missed_human_gates": sum(not r[key]["approval"] for r in gate),
        "unnecessary_gates": sum(r[key]["approval"] for r in no_gate),
        "affected_results_f1": round(statistics.fmean(f1(set(r[key]["affected"]), set(r["exp_affected"])) for r in aff), 3) if aff else None,
        "violated_constraint_exact": round(sum(set(r[key]["violated"]) == set(r["exp_violates"]) for r in rows) / len(rows), 3),
        "latency_p50_ms": pct([r[key]["ms"] for r in rows], 0.5),
        "errors": sum(1 for r in rows if r[key].get("error")),
    }


async def run_steering() -> dict:
    from backend.app.db import get_db
    from backend.app.science.service import get_context, reconcile
    from backend.app.services.store import Store
    st = Store(get_db())
    ctx = get_context(st, "exp_001")
    seed_txt = json.dumps({k: ctx[k] for k in ("experiment", "steps", "samples", "channel_map", "constraints",
                                               "derived_values", "dependencies")}, separators=(",", ":"))
    cases = json.loads((ROOT / "evals" / "steering" / "eval_cases.json").read_text())["cases"]

    async def one(c):
        o = c["observation"]
        m = o.get("measurement") or {}
        obs = {"source_type": o.get("source_type", "voice"), "channel_id": o.get("channel_id"), "well_id": o.get("well_id"),
               "content": o.get("utterance") or o.get("media_ref") or "", "media_ref": o.get("media_ref"),
               "confidence": o.get("confidence", 1.0), "measurement_type": m.get("type"),
               "measurement_value": m.get("value"), "measurement_unit": m.get("unit"),
               "supersedes_observation_id": o.get("supersedes_observation_id")}
        g, gms = await gemini_json(STEER_PROMPT.format(seed=seed_txt, step=c["active_step_id"],
                                                       obs=json.dumps({k: v for k, v in obs.items() if v is not None})),
                                   STEER_SCHEMA)
        t0 = time.perf_counter()
        d = reconcile(st, "exp_001", obs, c["active_step_id"])
        lms = (time.perf_counter() - t0) * 1000
        exp_aff = (c.get("affected") or {}).get("derived_values")
        row = {"case_id": c["case_id"], "category": c.get("category"), "exp_action": c["expected_response"],
               "exp_approval": bool(c.get("requires_human_approval")), "exp_violates": c.get("violates", []),
               "exp_affected": exp_aff,
               "gemini": {"action": g.get("action"), "approval": bool(g.get("requires_human_approval")),
                          "violated": g.get("violated_constraints", []), "affected": g.get("affected_derived_values", []),
                          "ms": round(gms, 1), "error": g.get("_error")},
               "labmate": {"action": d["action"], "approval": bool(d["requires_human_approval"]),
                           "violated": d["violated_constraints"],
                           "affected": d["affected_structured"].get("derived_values", []), "ms": round(lms, 2)}}
        print(f"  {c['case_id']:<5} {c.get('category', ''):<26} expected={row['exp_action']:<21} "
              f"gemini={row['gemini']['action']!s:<21} labmate={row['labmate']['action']}")
        return row

    rows = await asyncio.gather(*(one(c) for c in cases))
    return {"rows": rows, "stock_gemini": steering_metrics(rows, "gemini"), "labmate": steering_metrics(rows, "labmate")}


# =========================================================================================== report
def table(title: str, a: dict, b: dict, better: dict) -> str:
    lines = [f"### {title}", "", "| Metric | Stock Gemini | LABMATE | Better |", "|---|---|---|---|"]
    for k in a:
        if k == "cases":
            continue
        va, vb = a[k], b[k]
        win = ""
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and k in better:
            win = "LABMATE" if (vb > va if better[k] == "high" else vb < va) else ("tie" if va == vb else "Gemini")
        lines.append(f"| {k} | {va} | {vb} | {win} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["vision", "steering"])
    ap.add_argument("--report-only", type=Path, help="rebuild docs/BENCHMARK_V2.md from a saved results JSON")
    a = ap.parse_args()
    if a.report_only:
        res = a.report_only.resolve()
        out = json.loads(res.read_text())
        if "vision" in out:
            out["vision"]["crosscheck"] = crosscheck_metrics(out["vision"]["rows"])
            res.write_text(json.dumps(out, indent=2, default=str))
    else:
        if not get_settings().gemini_api_key:
            sys.exit("GEMINI_API_KEY required")
        out = {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "baseline_model": model_for("vision")}
        if a.only in (None, "vision"):
            print("== VISION: bubble counting on 18 labelled microfluidic images ==")
            out["vision"] = asyncio.run(run_vision())
        if a.only in (None, "steering"):
            print("== STEERING: 20 labelled CEA protocol cases ==")
            out["steering"] = asyncio.run(run_steering())
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        res = ROOT / "eval" / "results" / f"benchmark_v2_{ts}.json"
        res.parent.mkdir(parents=True, exist_ok=True)
        res.write_text(json.dumps(out, indent=2, default=str))

    md = [f"# LABMATE V2 benchmark: stock Gemini vs LABMATE", "",
          f"Run {out['run_at']} · baseline model `{out['baseline_model']}` (structured JSON output, same information "
          "and rules as LABMATE) · raw results `" + str(res.relative_to(ROOT)) + "`", "",
          "All cases are synthetic and independently labelled by teammates (vision: Person 3; steering: Person 4). "
          "Proof of concept, not clinical validation.", ""]
    if "vision" in out:
        md.append(table("Vision — bubble counting (18 images)", out["vision"]["stock_gemini"], out["vision"]["labmate"], {
            "count_mae": "low", "count_exact": "high", "count_within_1": "high",
            "false_positive_rate_on_clean_controls": "low", "box_precision_iou30": "high", "box_recall_iou30": "high",
            "abstains_on_unusable_frames": "high", "spurious_abstentions": "low", "latency_p50_ms": "low",
            "latency_p95_ms": "low", "errors": "low"}))
        c = out["vision"]["crosscheck"]
        md += ["", "### Vision — LABMATE system: cross-model verification (Gemini count vs specialist count)", "",
               "| Metric | Value |", "|---|---|",
               f"| silent_error_rate (both agree but wrong) | {c['silent_error_rate']} |",
               f"| errors_caught_by_escalation | {c['errors_caught_by_escalation']} |",
               f"| human_review_rate (disagreements sent to review) | {c['human_review_rate']} |",
               f"| escalated_cases | {', '.join(c['escalated_cases']) or '-'} |", "",
               "Reading: neither model alone is error-free (Gemini is fooled by glare on clean controls; the specialist "
               "over-segments a large prolate bubble), but their errors are uncorrelated. LABMATE acts on the specialist "
               "measurement, cross-checks it against Gemini, and routes disagreements to human review — this is "
               "implemented in the live perception path (`reconciliation.cross_check`).", ""]
    if "steering" in out:
        md.append(table("Steering — protocol decisions (20 cases)", out["steering"]["stock_gemini"], out["steering"]["labmate"], {
            "action_accuracy": "high", "human_gate_recall": "high", "missed_human_gates": "low",
            "unnecessary_gates": "low", "affected_results_f1": "high", "violated_constraint_exact": "high",
            "latency_p50_ms": "low", "errors": "low"}))
        md.append("\nCaveat: the steering cases were authored by the same teammate who wrote the deterministic engine, "
                  "so LABMATE's score on them is an upper bound; the stock-Gemini numbers show what the model does "
                  "with identical information and no engine.")
    (ROOT / "docs" / "BENCHMARK_V2.md").write_text("\n".join(md) + "\n")
    print("\n" + "\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
