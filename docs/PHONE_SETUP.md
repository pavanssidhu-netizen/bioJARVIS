# Phone setup

You need the **preview URL** printed by `scripts/deploy_vercel.sh` (looks like
`https://labmate-<hash>-<you>.vercel.app`). It is protected by Vercel Authentication: the first visit asks you
to sign in to Vercel (same account that deployed). Camera/mic need HTTPS, which Vercel provides.

## Android (Chrome)
1. Open the URL, sign in to Vercel.
2. Menu ⋮ → **Add to Home screen** → Install. Launch LABMATE from the icon.
3. Tap **Start live feed** → allow Camera, then Microphone.
4. Use headphones or a quiet bench; echo cancellation is on but speaker → mic feedback can cause barge-in.

## iPhone (Safari, iOS 16.4+)
1. Open the URL **in Safari**, sign in to Vercel.
2. Share → **Add to Home Screen**. (Home-screen apps may re-ask for camera/mic each launch — iOS behaviour.)
3. Tap **Start live feed**; allow Camera and Microphone. Audio only plays because the tap unlocks it;
   if you hear nothing, check the silent switch and media volume, then Stop and Start again.
4. If permissions were denied: Settings → Safari → Camera / Microphone → Ask.

## Test checklist (manual — cannot be automated from the dev box)
1. Landing page loads; pills show Backend green, Mic/Camera/Recording off.
2. Start live feed → camera preview, REC pill, "Voice" pill, perception overlay appears within ~10 s.
3. Do something visible (add drops from a dropper) → `perception` events with actions/counts in the stream.
4. Say "Note that tube A turned blue" → spoken confirmation + `observation_proposal` SAVED in the stream.
5. Say "How many drops did I add in the last 30 seconds?" → spoken answer from the log.
6. Stop live feed → camera light off, REC off; speaking or typing now shows EPHEMERAL / NOT SAVED.
7. Refresh → Experiment log tab still shows the saved records; Accept / Dispute / Correct work.
8. On the laptop: `.venv/bin/python scripts/watch_db.py` shows events arriving (or Turso dashboard).
