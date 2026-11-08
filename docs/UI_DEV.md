# Previewing UI changes locally (hot reload, no API keys)

You run the backend + app on your own laptop. Edit a widget, save, see it in Chrome within a second.
Your laptop webcam works in the camera view (localhost counts as a secure origin). Gemini voice/vision
needs a key and stays off locally; everything else (protocol, graph, history, reviews, sessions, tags) works.

## One-time setup
Needs: Git, Python 3.12, Flutter (stable), Chrome.

```powershell
git clone https://github.com/pavanssidhu-netizen/bioJARVIS.git
cd bioJARVIS
python -m venv .venv
# Windows:
.\.venv\Scripts\pip install -r requirements.txt uvicorn
# Mac/Linux:
# .venv/bin/pip install -r requirements.txt uvicorn
cd app; flutter pub get; cd ..
```

## Every time (two terminals)

**Terminal 1 — backend with demo data** (local SQLite at `data/labmate.db`, no keys):
```powershell
# Windows PowerShell
.\.venv\Scripts\python scripts\seed_demo.py          # once (re-run to add more demo sessions)
$env:LARVIS_DEV_CORS="1"; .\.venv\Scripts\python scripts\dev_server.py
# Mac/Linux
# .venv/bin/python scripts/seed_demo.py
# LARVIS_DEV_CORS=1 .venv/bin/python scripts/dev_server.py
```
Backend: http://127.0.0.1:8000 (API docs: http://127.0.0.1:8000/api/docs)

**Terminal 2 — app with hot reload:**
```powershell
cd app
flutter run -d chrome --dart-define=API_BASE=http://127.0.0.1:8000
```
Press `r` in this terminal to hot-reload after saving (or `R` for full restart).

## What you'll see
- Experiment log / history: 2 seeded sessions on `exp_001` (CEA microfluidic assay) with notes, perception
  events with object tags (`box_2d`), specialist bubble detections, and 3 pending review flags.
- Live Lab: press **Start live feed** → your webcam + a real recording session. Without a Gemini key the voice
  part shows "did not connect" and camera analysis returns an error item — expected locally. To design the
  camera overlay use the seeded perception payloads (Data feed tab → tap an item → JSON).

## Rules
- Edit only `app/lib/pages/*` and `app/lib/ui/*`. Don't change `lib/state`, `lib/services` or backend files.
- Before pushing: `cd app; flutter analyze; flutter test` must pass.
- Push to a branch (e.g. `ui/cockpit`), never delete others' files; Pavan merges + deploys
  (`scripts/deploy_vercel.sh`) and shares the protected preview URL.
- API reference for every screen: `docs/API_V2.md`.
