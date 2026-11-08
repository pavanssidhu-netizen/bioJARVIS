"""Headless-Chromium end-to-end test of the built app against the local server.

    .venv/bin/python scripts/e2e_browser.py            # offline: media layer + UI + DB (no key needed)
    .venv/bin/python scripts/e2e_browser.py --live     # + real Gemini: press Start live feed, speak a note and a
                                                       #   question via a synthesised WAV fed as the fake mic

Chromium's fake devices stand in for the phone camera/mic; this does NOT replace testing on a real phone.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PORT = 8765
TMP = Path(tempfile.mkdtemp(prefix="labmate-e2e-"))
DB = TMP / "e2e.db"
os.environ["DATABASE_URL"] = f"sqlite:///{DB}"
os.environ["TURSO_DATABASE_URL"] = ""

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{' - ' + detail if detail else ''}", flush=True)
    return bool(ok)


def start_server() -> None:
    import uvicorn
    from fastapi.staticfiles import StaticFiles
    from backend.app.main import app
    app.mount("/", StaticFiles(directory=ROOT / "app/build/web", html=True), name="web")
    cfg = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")
    threading.Thread(target=uvicorn.Server(cfg).run, daemon=True).start()
    import httpx
    for _ in range(50):
        try:
            if httpx.get(f"http://127.0.0.1:{PORT}/api/health").status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.1)
    raise RuntimeError("server did not start")


INIT_SCRIPT = """
window.__gum = [];
const orig = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
navigator.mediaDevices.getUserMedia = (c) => { window.__gum.push(JSON.stringify(c)); return orig(c); };
"""


def db_rows(sql: str) -> list[tuple]:
    con = sqlite3.connect(DB)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def wait_text(page, text: str, timeout: int = 20000) -> None:
    """Flutter merges text into semantics nodes, so match on the semantics tree's text content."""
    page.wait_for_function(
        """t => { const h = document.querySelector('flt-semantics-host'); if (!h) return false;
                  const labels = [...h.querySelectorAll('[aria-label]')].map(e => e.getAttribute('aria-label')).join(' ');
                  return (h.textContent + ' ' + labels).includes(t); }""", arg=text, timeout=timeout)


def enable_semantics(page) -> None:
    # Flutter web renders to canvas; enabling its semantics tree exposes buttons to the accessibility API.
    page.wait_for_selector("flt-semantics-placeholder", state="attached", timeout=30000)
    page.evaluate("document.querySelector('flt-semantics-placeholder').click()")
    page.wait_for_timeout(500)


def offline_checks(page) -> None:
    print("\n== Offline: load + default state ==")
    page.goto(f"http://127.0.0.1:{PORT}/")
    enable_semantics(page)
    page.get_by_role("button", name="Start live feed").wait_for(timeout=30000)
    check("landing page renders with Start live feed", True)
    check("no getUserMedia on page load", page.evaluate("window.__gum.length") == 0,
          f"calls={page.evaluate('window.__gum')}")

    print("\n== Offline: browser media layer (fake devices) ==")
    r = page.evaluate("""async () => {
        const M = window.LabmateMedia; const v = document.createElement('video'); v.muted = true;
        document.body.appendChild(v); M.attachVideo(v);
        await M.cameraOpen('environment'); await new Promise(r => setTimeout(r, 800));
        const active = M.cameraActive(); const frame = M.captureFrame(512, 0.6);
        M.cameraClose();
        return {active, frameLen: frame ? frame.length : 0, jpeg: frame ? atob(frame).charCodeAt(0) === 0xff : false,
                after: M.cameraActive(), tracks: M.cameraTrackStates(), src: v.srcObject === null};
    }""")
    check("camera opens on explicit call", r["active"])
    check("snapshot is a JPEG", r["jpeg"] and r["frameLen"] > 1000, f"{r['frameLen']} b64 chars")
    check("Close Camera stops all tracks", not r["after"] and r["tracks"] == "ended" and r["src"], r["tracks"])

    r = page.evaluate("""async () => {
        const M = window.LabmateMedia; M.unlockAudio(); let n = 0, bytes = 0;
        await M.micStart((b64) => { n++; bytes = atob(b64).length; }, () => {});
        await new Promise(r => setTimeout(r, 1200));
        const active = M.micActive(); M.micStop(); const c = n;
        await new Promise(r => setTimeout(r, 400));
        return {active, chunks: c, bytes, after: M.micActive(), late: n - c};
    }""")
    check("mic streams 16 kHz PCM16 chunks", r["active"] and r["chunks"] >= 5 and r["bytes"] == 3200,
          f"{r['chunks']} chunks of {r['bytes']} bytes in 1.2 s")
    check("mic stop ends capture", not r["after"] and r["late"] <= 1, f"chunks after stop={r['late']}")

    r = page.evaluate("""() => { const M = window.LabmateMedia; M.unlockAudio();
        const pcm = new Int16Array(2400); for (let i=0;i<pcm.length;i++) pcm[i]=Math.sin(i/5)*8000;
        let s=''; const b=new Uint8Array(pcm.buffer); for (const x of b) s+=String.fromCharCode(x);
        M.playPcm(btoa(s), 24000); const p = M.isPlaying(); M.stopPlayback(); return {p, after: M.isPlaying()}; }""")
    check("24 kHz playback queues and barge-in clears", r["p"] and not r["after"])

    print("\n== Offline: UI <-> backend ==")
    page.get_by_role("tab", name="Diagnostics").click()
    wait_text(page, "STATE (EACH FLAG INDEPENDENT)")
    wait_text(page, "CAPABILITIES")
    check("diagnostics page shows state + backend", True)
    page.get_by_role("tab", name="Live Lab").click()


def live_checks(page, audio_ok: bool) -> None:
    print("\n== Live: Start live feed (real Gemini) ==")
    page.get_by_role("button", name="Start live feed").click()
    t0 = time.time()
    rec = []
    while time.time() - t0 < 20 and not rec:
        rec = db_rows("SELECT id FROM recording_sessions WHERE status='active'")
        time.sleep(0.5)
    check("recording session active in SQLite", bool(rec))
    page.get_by_role("button", name="Stop live feed").wait_for(timeout=20000)
    check("live view shown", True)

    # Perception: fake camera shows a moving test pattern; we only require a real model round trip + valid contract.
    t0, got = time.time(), []
    while time.time() - t0 < 45 and not got:
        got = db_rows("SELECT payload_json, model_name FROM observation_events WHERE event_type='perception'")
        time.sleep(1)
    if check("perception window persisted (real vision model)", bool(got), got[0][1] if got else "none in 45 s"):
        p = json.loads(got[0][0])
        check("perception contract fields", all(k in p for k in ("objects", "actions", "scene_summary", "window_start")),
              f"objects={[o['label'] for o in p['objects']][:4]} actions={p['actions'][:2]}")

    # Gemini Live connected?
    try:
        wait_text(page, "Voice on", timeout=20000)  # pill semantics: Gemini connected AND mic streaming
        check("Gemini Live session established in browser", True)
    except Exception as e:  # noqa: BLE001
        check("Gemini Live session established in browser", False, str(e)[:120])

    if audio_ok:
        print("  (fake mic is playing the synthesised note + question; waiting for transcript/tool writes)")
        t0, notes, segs = time.time(), [], []
        while time.time() - t0 < 60 and not (notes and segs):
            notes = db_rows("SELECT payload_json FROM observation_events WHERE event_type='observation_proposal'")
            segs = db_rows("SELECT payload_json FROM observation_events WHERE event_type='transcript_segment'")
            time.sleep(1)
        check("spoken audio transcribed + persisted", bool(segs), json.loads(segs[0][0])["text"][:80] if segs else "")
        check("spoken note -> propose_observation -> SQLite", bool(notes),
              json.loads(notes[0][0]).get("summary", "")[:80] if notes else "")

    page.get_by_role("button", name="Stop live feed").click()
    time.sleep(2)
    check("Stop ends recording server-side", not db_rows("SELECT id FROM recording_sessions WHERE status='active'"))
    n = db_rows("SELECT COUNT(*) FROM observation_events")[0][0]
    time.sleep(6)
    check("nothing persisted after stop", db_rows("SELECT COUNT(*) FROM observation_events")[0][0] == n)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--audio", help="WAV fed as the fake microphone (16-bit PCM)")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()
    if not (ROOT / "app/build/web/index.html").exists():
        print("Build the app first: scripts/build_web.sh")
        return 2
    start_server()
    from playwright.sync_api import sync_playwright
    args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", "--autoplay-policy=no-user-gesture-required"]
    if a.audio:
        args.append(f"--use-file-for-fake-audio-capture={Path(a.audio).resolve()}")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=not a.headed, args=args)
        ctx = b.new_context(permissions=["camera", "microphone"], viewport={"width": 412, "height": 915})
        ctx.add_init_script(INIT_SCRIPT)
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            offline_checks(page)
            if a.live:
                page.reload()
                enable_semantics(page)
                page.get_by_role("button", name="Start live feed").wait_for(timeout=30000)
                live_checks(page, bool(a.audio))
        except Exception as e:  # noqa: BLE001
            check("e2e run", False, f"{type(e).__name__}: {str(e)[:300]}")
            page.screenshot(path=str(TMP / "failure.png"))
            print(f"  screenshot: {TMP / 'failure.png'}")
        page.screenshot(path=str(TMP / "final.png"), full_page=True)
        check("no uncaught JS errors", not errors, "; ".join(errors)[:300])
        b.close()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed. DB: {DB}  screenshots: {TMP}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
