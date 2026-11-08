"""Voice-command accuracy: spoken commands -> real Gemini Live session -> which tool + which arguments.

Each case is synthesised to speech (Gemini Live voice), streamed as 16 kHz PCM into a FRESH Live session opened
with the same config-locked token the phone uses (Larvis prompt + steering + CEA protocol + skills). Tool calls are
executed against a throwaway DB with an active recording, so Gemini sees real results, exactly as in the app.

    .venv/bin/python scripts/benchmark_voice.py            # ~30 Gemini calls, ~3 min
Writes eval/results/benchmark_voice_<ts>.json and docs/BENCHMARK_VOICE.md.
"""
from __future__ import annotations

import asyncio
import base64
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import smoke_live as sl  # noqa: E402  (sets a throwaway DATABASE_URL; provides tts() + pcm_resample())
import websockets  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402

EXP = "exp_001"

# (utterance, expected tool, expected args (subset; str values compared case-insensitively, 'contains:' = substring))
CASES = [
    ("I'm on step seven, channel eight.", "set_active_step", {"step_id": "step_07", "channel_id": "CH08"}),
    ("Track the pipette tip.", "track_object", {"label": "contains:pipette"}),
    ("Stop tracking the pipette tip.", "stop_tracking", {"label": "contains:pipette"}),
    ("Note that there is one bubble in channel one.", "propose_observation",
     {"channel_id": "CH01", "measurement_type": "bubble_count", "measurement_value": 1}),
    ("The detection antibody incubated for nine minutes.", "propose_observation",
     {"measurement_type": "incubation_duration_min", "measurement_value": 9}),
    ("Room temperature is twenty four degrees.", "propose_observation",
     {"measurement_type": "temperature_c", "measurement_value": 24}),
    ("Channel five did not fill completely.", "propose_observation",
     {"channel_id": "CH05", "measurement_type": "channel_fill_complete", "measurement_value": 0}),
    ("I washed channel two for three minutes.", "propose_observation",
     {"channel_id": "CH02", "measurement_type": "wash_duration_min", "measurement_value": 3}),
    ("Two bubbles in channel eleven.", "propose_observation",
     {"channel_id": "CH11", "measurement_type": "bubble_count", "measurement_value": 2}),
    ("Scratch that, discard the last note.", "discard_observation", {"event_id": "last"}),
    ("What would a bubble in channel three affect?", "get_impact", {"channel_id": "CH03"}),
    ("How many bubbles have I noted so far?", "query_lab_log", {}),
    ("Are we recording right now?", "describe_current_recording_state", {}),
    ("Why might the replicate variance be high in the standard channels?", "investigate_discrepancy", {}),
    ("Show me the experiment log.", "request_ui_action", {"action": "show_tab", "argument": "log"}),
]


def arg_ok(exp, got) -> bool:
    if isinstance(exp, str) and exp.startswith("contains:"):
        return exp[9:].lower() in str(got or "").lower()
    if isinstance(exp, str):
        return str(got or "").strip().lower() == exp.lower()
    if isinstance(exp, (int, float)):
        try:
            return float(got) == float(exp)
        except (TypeError, ValueError):
            return False
    return got == exp


async def run_case(c: TestClient, utt: str, audio: bytes, sem: asyncio.Semaphore) -> dict:
    async with sem:
        rec = await asyncio.to_thread(lambda: c.post("/api/recordings/start", json={"experiment_id": EXP}).json())
        # Seed one prior note so "scratch that" has a target.
        await asyncio.to_thread(lambda: c.post("/api/tools/call", json={
            "name": "propose_observation", "experiment_id": EXP, "session_id": rec["id"], "call_id": f"seed-{rec['id']}",
            "args": {"observation_type": "general_note", "summary": "seed note"}}))
        tok = await asyncio.to_thread(lambda: c.post("/api/live/token", params={"experiment_id": EXP}).json())
        calls, transcript, said = [], "", ""
        t0 = time.perf_counter()
        first_tool_ms = None
        async with websockets.connect(f"{tok['websocket_url']}?access_token={tok['token']}", max_size=None) as ws:
            await ws.send(json.dumps({"setup": {"model": f"models/{tok['model']}"}}))
            await asyncio.wait_for(ws.recv(), 20)
            pcm = sl.pcm_resample(audio, 24000, 16000) + b"\0" * 32000 * 2  # + ~2 s silence
            t_audio_end = None

            async def sender():
                nonlocal t_audio_end
                for i in range(0, len(pcm), 3200):
                    await ws.send(json.dumps({"realtimeInput": {"audio": {
                        "data": base64.b64encode(pcm[i:i + 3200]).decode(), "mimeType": "audio/pcm;rate=16000"}}}))
                    await asyncio.sleep(0.05)
                t_audio_end = time.perf_counter()

            send_task = asyncio.create_task(sender())
            deadline = time.perf_counter() + 40
            while time.perf_counter() < deadline:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), max(0.1, deadline - time.perf_counter())))
                except (asyncio.TimeoutError, websockets.ConnectionClosed):
                    break
                sc = m.get("serverContent", {})
                transcript += sc.get("inputTranscription", {}).get("text", "")
                said += sc.get("outputTranscription", {}).get("text", "")
                if "toolCall" in m:
                    if first_tool_ms is None and t_audio_end:
                        first_tool_ms = (time.perf_counter() - t_audio_end) * 1000
                    resps = []
                    for fc in m["toolCall"]["functionCalls"]:
                        calls.append({"name": fc["name"], "args": fc.get("args", {})})
                        res = await asyncio.to_thread(lambda fc=fc: c.post("/api/tools/call", json={
                            "name": fc["name"], "args": fc.get("args", {}), "experiment_id": EXP,
                            "session_id": rec["id"], "call_id": fc.get("id")}).json())
                        resps.append({"id": fc.get("id"), "name": fc["name"], "response": res})
                    await ws.send(json.dumps({"toolResponse": {"functionResponses": resps}}))
                if sc.get("turnComplete") and send_task.done() and (calls or said):
                    break
            send_task.cancel()
        await asyncio.to_thread(lambda: c.post(f"/api/recordings/{rec['id']}/stop"))
        return {"utterance": utt, "transcript": transcript.strip(), "calls": calls, "spoken": said.strip()[:300],
                "first_tool_ms_after_speech": round(first_tool_ms) if first_tool_ms else None,
                "total_ms": round((time.perf_counter() - t0) * 1000)}


def score(case, res) -> dict:
    utt, tool, exp_args = case
    names = [x["name"] for x in res["calls"]]
    hit = next((x for x in res["calls"] if x["name"] == tool), None)
    args_ok = hit is not None and all(arg_ok(v, hit["args"].get(k)) for k, v in exp_args.items())
    wrong_valid = hit is not None and not args_ok and all(k in hit["args"] for k in exp_args)
    return {**res, "expected_tool": tool, "expected_args": exp_args, "tool_ok": hit is not None,
            "first_tool_ok": bool(names) and names[0] == tool, "args_ok": args_ok, "wrong_but_valid_args": wrong_valid,
            "no_tool_called": not names}


async def main_async() -> list[dict]:
    c = TestClient(app)
    print("synthesising speech for", len(CASES), "commands...")
    audios = await asyncio.gather(*(asyncio.to_thread(sl.tts, None, u) for u, _, _ in CASES))
    sem = asyncio.Semaphore(4)
    results = await asyncio.gather(*(run_case(c, u, a, sem) for (u, _, _), a in zip(CASES, audios)))
    rows = [score(cs, r) for cs, r in zip(CASES, results)]
    for r in rows:
        print(f"  [{'PASS' if r['args_ok'] else 'TOOL' if r['tool_ok'] else 'FAIL'}] {r['utterance']:<62} -> "
              f"{[x['name'] for x in r['calls']]} {r['calls'][0]['args'] if r['calls'] else ''}")
    return rows


def main() -> int:
    rows = asyncio.run(main_async())
    n = len(rows)
    lat = [r["first_tool_ms_after_speech"] for r in rows if r["first_tool_ms_after_speech"]]
    m = {"cases": n, "tool_accuracy": round(sum(r["tool_ok"] for r in rows) / n, 3),
         "first_tool_accuracy": round(sum(r["first_tool_ok"] for r in rows) / n, 3),
         "tool_and_args_accuracy": round(sum(r["args_ok"] for r in rows) / n, 3),
         "wrong_but_valid_args": sum(r["wrong_but_valid_args"] for r in rows),
         "no_tool_called": sum(r["no_tool_called"] for r in rows),
         "transcript_contains_key_words": round(sum(any(w in r["transcript"].lower() for w in r["utterance"].lower().split()[-2:])
                                                    for r in rows) / n, 3),
         }  # latency not reported: silence padding makes the end-of-speech timestamp unreliable
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ROOT / "eval" / "results" / f"benchmark_voice_{ts}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"run_at": ts, "model": sl.S.live_model, "metrics": m, "rows": rows}, indent=2))
    md = ["# Larvis voice-command accuracy (real Gemini Live audio)", "",
          f"Run {ts} · model `{sl.S.live_model}` · {n} spoken commands, each in a fresh Live session with the production "
          f"token config · raw `{path.relative_to(ROOT)}`", "",
          "Speech is synthesised (single voice, quiet room) — real-world noise/accents will be harder. One run.", "",
          "| Metric | Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in m.items()] + [
          "", "| Command | Expected | Got | OK |", "|---|---|---|---|"] + [
          f"| {r['utterance']} | `{r['expected_tool']}` {json.dumps(r['expected_args'])} | "
          f"{', '.join('`' + x['name'] + '` ' + json.dumps(x['args']) for x in r['calls']) or '—'} | "
          f"{'✅' if r['args_ok'] else '🟡 tool only' if r['tool_ok'] else '❌'} |" for r in rows]
    (ROOT / "docs" / "BENCHMARK_VOICE.md").write_text("\n".join(md) + "\n")
    print("\n" + "\n".join(md[:14 + len(m)]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
