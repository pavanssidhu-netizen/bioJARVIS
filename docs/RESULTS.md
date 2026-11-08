# Larvis — results sheet for slides (measured numbers only)

1. **Protocol decisions (20 CEA cases, identical protocol info to both):** stock Gemini 70% correct and missed **3 of 12**
   required human sign-offs; Larvis 100% / 0 missed. *Caveat: cases written by the engine's author → upper bound.
   2 of Gemini's 6 misses are labelling convention (log vs no_action); 4 are substantive.*
2. **Bubble counting (18 labelled synthetic images):** both 94% exact; stock Gemini raised a false bubble on **1 in 3 clean
   channels** (glare); Larvis specialist 0 false alarms; specialist 39 ms vs Gemini 6.7 s median.
3. **Cross-model verification:** when Gemini and the specialist agree (15/17) every count was right — **0 silent errors**;
   both real errors were escalated to review (12% review rate). Neither model alone was error-free; their errors didn't overlap.
4. **Voice commands → tool + arguments (real Gemini Live, 15 spoken commands):** **15/15**, incl. "channel eleven"→CH11,
   "did not fill completely"→fill=false, "scratch that"→discard last. *Synthetic voice, quiet room, n=15 (95% CI ≈ 80–100%).*
5. **Log agent (5 questions on a synthetic log):** 5/5 correct, 0 invented event citations, ignores a researcher-rejected record.
6. **Integrity checks (engineered, tested):** 0 writes outside recording, idempotent tool calls, immutable originals,
   AI cannot approve — enforced server-side, verified by automated tests.

Limitations to say out loud: no physical lab — synthetic images, household-object live demo; small n; single runs;
yield model trained on a simulator; literature context is a curated local snapshot.
