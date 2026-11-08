"""Real-API smoke test (needs GEMINI_API_KEY in .env). Uses a throwaway SQLite DB.

    .venv/bin/python scripts/smoke_live.py

Steps: key + model discovery -> vision snapshot -> perception window -> token mint -> Live WS via the token
(same setup message the browser sends) -> spoken note (TTS audio) -> tool call -> real SQLite row ->
spoken question -> query_lab_log -> spoken answer. Also writes data/e2e_voice.wav for the browser E2E.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import sqlite3
import struct
import sys
import tempfile
import time
import uuid
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DB = Path(tempfile.mkdtemp(prefix="labmate-smoke-")) / "smoke.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["TURSO_DATABASE_URL"] = ""

from fastapi.testclient import TestClient  # noqa: E402
from google import genai  # noqa: E402
from google.genai import types  # noqa: E402
import websockets  # noqa: E402

from backend.app.config import get_settings  # noqa: E402
from backend.app.main import app  # noqa: E402

S = get_settings()
EXP = "exp-demo"
ok_all = True


def check(name, ok, detail=""):
    global ok_all
    ok_all &= bool(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{' - ' + str(detail) if detail else ''}", flush=True)
    return ok


def pcm_resample(pcm: bytes, src: int, dst: int) -> bytes:
    n = len(pcm) // 2
    samples = struct.unpack(f"<{n}h", pcm[: n * 2])
    m = int(n * dst / src)
    out = [samples[min(n - 1, int(i * src / dst))] for i in range(m)]
    return struct.pack(f"<{m}h", *out)


def tts(client, text: str) -> bytes:
    """24 kHz PCM16 speech. TTS models aren't on every key, so ask Gemini Live itself to read the line."""
    async def run() -> bytes:
        url = ("wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta."
               f"GenerativeService.BidiGenerateContent?key={S.gemini_api_key}")
        audio = b""
        async with websockets.connect(url, max_size=None) as ws:
            await ws.send(json.dumps({"setup": {"model": f"models/{S.live_model}",
                                                "generationConfig": {"responseModalities": ["AUDIO"]},
                                                "systemInstruction": {"parts": [{"text":
                                                    "You are a text-to-speech engine. Read the user's text aloud "
                                                    "verbatim, in a natural voice, and say nothing else."}]}}}))
            await asyncio.wait_for(ws.recv(), 20)
            await ws.send(json.dumps({"realtimeInput": {"text": text}}))
            while True:
                m = json.loads(await asyncio.wait_for(ws.recv(), 30))
                for p in m.get("serverContent", {}).get("modelTurn", {}).get("parts", []):
                    if "inlineData" in p:
                        audio += base64.b64decode(p["inlineData"]["data"])
                if m.get("serverContent", {}).get("turnComplete"):
                    return audio
    return asyncio.run(run())


async def live_model_ok(model: str) -> str:
    url = ("wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta."
           f"GenerativeService.BidiGenerateContent?key={S.gemini_api_key}")
    try:
        async with websockets.connect(url, max_size=None) as ws:
            await ws.send(json.dumps({"setup": {"model": f"models/{model}",
                                                "generationConfig": {"responseModalities": ["AUDIO"]}}}))
            return "ok" if "setupComplete" in json.loads(await asyncio.wait_for(ws.recv(), 15)) else "no setupComplete"
    except websockets.ConnectionClosed as e:
        return f"closed: {e.rcvd.reason if e.rcvd else e}"


def bench_image(client) -> bytes:
    """A realistic lab-bench image via image generation (so vision has something real to describe)."""
    cache = ROOT / "data" / "test_bench.png"
    if cache.exists():
        return cache.read_bytes()
    r = client.models.generate_content(
        model="gemini-3.1-flash-image",
        contents="Photo of a lab bench: a plastic dropper bottle, three test tubes in a rack, one with blue liquid, "
                 "a micropipette and a beaker. Realistic, phone camera, top-down at 45 degrees.")
    for p in r.candidates[0].content.parts:
        if p.inline_data and p.inline_data.mime_type.startswith("image/"):
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(p.inline_data.data)
            return p.inline_data.data
    raise RuntimeError("no image returned")


async def live_session(api: TestClient, rec_id: str, utterances: list[bytes]) -> dict:
    tok = api.post("/api/live/token").json()
    url = f"{tok['websocket_url']}?access_token={tok['token']}"
    out = {"setup": False, "input": "", "output": "", "audio_bytes": 0, "tools": [], "tool_results": []}
    async with websockets.connect(url, max_size=None) as ws:
        await ws.send(json.dumps({"setup": {"model": f"models/{tok['model']}"}}))  # identical to the browser
        msg = json.loads(await asyncio.wait_for(ws.recv(), 20))
        out["setup"] = "setupComplete" in msg
        if not out["setup"]:
            out["error"] = msg
            return out

        async def reader(stop_after_tool: str, deadline: float):
            while time.time() < deadline:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), deadline - time.time()))
                except (asyncio.TimeoutError, websockets.ConnectionClosed):
                    return
                sc = m.get("serverContent", {})
                out["input"] += sc.get("inputTranscription", {}).get("text", "")
                out["output"] += sc.get("outputTranscription", {}).get("text", "")
                for p in sc.get("modelTurn", {}).get("parts", []):
                    if "inlineData" in p:
                        out["audio_bytes"] += len(base64.b64decode(p["inlineData"]["data"]))
                if "toolCall" in m:
                    resps = []
                    for fc in m["toolCall"]["functionCalls"]:
                        out["tools"].append(fc["name"])
                        res = api.post("/api/tools/call", json={"name": fc["name"], "args": fc.get("args", {}),
                                                                "experiment_id": EXP, "session_id": rec_id,
                                                                "call_id": fc.get("id")}).json()
                        out["tool_results"].append(res)
                        resps.append({"id": fc.get("id"), "name": fc["name"], "response": res})
                    await ws.send(json.dumps({"toolResponse": {"functionResponses": resps}}))
                if sc.get("turnComplete") and stop_after_tool in out["tools"]:
                    return

        for audio, want_tool in utterances:
            pcm16 = pcm_resample(audio, 24000, 16000)
            for i in range(0, len(pcm16), 3200):  # 100 ms chunks, 2x real time
                await ws.send(json.dumps({"realtimeInput": {"audio": {
                    "data": base64.b64encode(pcm16[i:i + 3200]).decode(), "mimeType": "audio/pcm;rate=16000"}}}))
                await asyncio.sleep(0.05)
            silence = b"\0" * 3200
            for _ in range(15):  # 1.5 s of silence so VAD ends the turn
                await ws.send(json.dumps({"realtimeInput": {"audio": {
                    "data": base64.b64encode(silence).decode(), "mimeType": "audio/pcm;rate=16000"}}}))
                await asyncio.sleep(0.05)
            await reader(want_tool, time.time() + 45)
    return out


def main() -> int:
    if not S.gemini_api_key:
        print("GEMINI_API_KEY is not set. Put it in .env (see .env.example).")
        return 2
    client = genai.Client(api_key=S.gemini_api_key)
    api = TestClient(app)

    print("== 1. Key + model discovery ==")
    try:
        names = {m.name.removeprefix("models/") for m in client.models.list()}
        check("API key accepted", True, f"{len(names)} models visible")
        check(f"live model '{S.live_model}' opens a session", (r := asyncio.run(live_model_ok(S.live_model))) == "ok", r)
        check(f"vision model '{S.vision_model}' available", S.vision_model in names)
    except Exception as e:  # noqa: BLE001
        check("API key accepted", False, f"{type(e).__name__}: {str(e)[:200]}")
        return 1

    print("== 2. Snapshot vision ==")
    img = bench_image(client)
    r = api.post("/api/vision/analyse", json={"image_base64": base64.b64encode(img).decode(),
                                              "question": "What lab equipment can you see?"})
    if check("vision endpoint", r.status_code == 200, r.status_code):
        j = r.json()
        check("structured objects returned", len(j["structured"].get("objects", [])) > 0,
              [o["label"] for o in j["structured"]["objects"]][:6])
        print("     ", j["description"][:160])

    print("== 3. Perception window -> SQLite ==")
    rec = api.post("/api/recordings/start", json={"experiment_id": EXP}).json()
    frames = [base64.b64encode(img).decode()] * 3
    r = api.post("/api/perception/window", json={
        "frames_base64": frames, "frame_interval_s": 1.0, "window_start": "2026-01-01T00:00:00Z",
        "window_end": "2026-01-01T00:00:02Z", "experiment_id": EXP, "session_id": rec["id"],
        "idempotency_key": f"smoke-{uuid.uuid4().hex}"})
    if check("perception endpoint", r.status_code == 200, r.status_code if r.status_code == 200 else r.text[:200]):
        j = r.json()
        check("perception persisted", j["saved"], j.get("skipped_reason") or j["event"]["id"])
        print("      objects:", [o["label"] for o in j["perception"]["objects"]][:6], "actions:", j["perception"]["actions"])

    print("== 4. Ephemeral token ==")
    r = api.post("/api/live/token")
    check("token minted", r.status_code == 200 and r.json()["token"].startswith("auth_tokens/"),
          r.json().get("token", "")[:18] + "…" if r.status_code == 200 else r.text[:300])
    if r.status_code != 200:
        return 1

    print("== 5. Gemini Live: spoken note + spoken question ==")
    note = tts(client, "Note that tube A turned blue after adding three drops of indicator.")
    question = tts(client, "How many drops of indicator did I add?")
    with wave.open(str(ROOT / "data" / "e2e_voice.wav"), "wb") as w:  # for scripts/e2e_browser.py --audio
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
        w.writeframes(b"\0" * 48000 * 2 + note + b"\0" * 24000 * 6 + question + b"\0" * 24000 * 20)
    out = asyncio.run(live_session(api, rec["id"], [(note, "propose_observation"), (question, "query_lab_log")]))
    check("Live session via ephemeral token", out["setup"], out.get("error", ""))
    check("input transcription", "blue" in out["input"].lower(), out["input"][:120])
    check("spoken audio response", out["audio_bytes"] > 10000, f"{out['audio_bytes']} PCM bytes")
    check("output transcription", bool(out["output"]), out["output"][:160])
    check("tool: propose_observation called", "propose_observation" in out["tools"], out["tools"])
    saved = [t for t in out["tool_results"] if t.get("saved")]
    check("tool result saved=true", bool(saved), saved[0]["event_id"] if saved else out["tool_results"][:1])
    q = [t for t in out["tool_results"] if "answer" in t]
    check("tool: query_lab_log answered from DB", bool(q), q[0]["answer"][:160] if q else out["tools"])

    rows = sqlite3.connect(DB).execute(
        "SELECT event_type, payload_json FROM observation_events WHERE event_type='observation_proposal'").fetchall()
    check("observation row in SQLite", bool(rows), json.loads(rows[0][1])["summary"][:100] if rows else "")
    api.post(f"/api/recordings/{rec['id']}/stop")
    print(f"\n{'ALL PASSED' if ok_all else 'SOME CHECKS FAILED'}  (db: {DB})")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
