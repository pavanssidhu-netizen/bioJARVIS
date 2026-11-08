# Larvis utterance router (real Gemini, text in)

Run 20261108T114526Z · router model from `GEMINI_ROUTER_MODEL` · raw `eval/results/benchmark_router_20261108T114526Z.json`

| Metric | Value |
|---|---|
| cases | 22 |
| routing_accuracy | 1.0 |
| noise_correctly_ignored | 4/4 |
| commands_correct | 15/15 |
| latency_p50_ms | 855.0 |

| Utterance | Expected | Routed | Ambiguous | OK |
|---|---|---|---|---|
| I'm on step seven, channel eight. | `set_active_step` | `set_active_step` (protocol_step) {"step_id": "step_07", "protocol_step": "Detection antibody", "measurement_type": "note",  | False | ✅ |
| Track the pipette tip. | `track_object` | `track_object` (command) {"label": "pipette tip"} | False | ✅ |
| Stop tracking the pipette tip. | `stop_tracking` | `stop_tracking` (command) {"label": "pipette tip"} | False | ✅ |
| Note that there is one bubble in channel one. | `propose_observation` | `propose_observation` (observation) {"observation_type": "general_note", "summary": "one bubble in channel one", "channel_id": | False | ✅ |
| The detection antibody incubated for nine minutes. | `propose_observation` | `propose_observation` (observation) {"observation_type": "timing_note", "summary": "The detection antibody incubated for nine  | False | ✅ |
| Room temperature is twenty four degrees. | `propose_observation` | `propose_observation` (observation) {"observation_type": "temperature_note", "summary": "Room temperature is twenty four degre | False | ✅ |
| Channel five did not fill completely. | `propose_observation` | `propose_observation` (observation) {"observation_type": "protocol_step_done", "summary": "Channel five did not fill completel | False | ✅ |
| I washed channel two for three minutes. | `propose_observation` | `propose_observation` (observation) {"observation_type": "timing_note", "summary": "Washed channel two for three minutes", "ch | False | ✅ |
| Two bubbles in channel eleven. | `propose_observation` | `propose_observation` (observation) {"observation_type": "volume_note", "summary": "Two bubbles in channel eleven", "channel_i | False | ✅ |
| Scratch that, discard the last note. | `discard_observation` | `discard_observation` (command) {"event_id": "last"} | False | ✅ |
| What would a bubble in channel three affect? | `get_impact` | `get_impact` (question) {"channel_id": "CH03", "question": "What would a bubble in channel three affect?"} | False | ✅ |
| How many bubbles have I noted so far? | `query_lab_log` | `query_lab_log` (question) {"question": "How many bubbles have I noted so far?"} | False | ✅ |
| Are we recording right now? | `describe_current_recording_state` | `describe_current_recording_state` (question) {} | False | ✅ |
| Why might the replicate variance be high in the standard channels? | `investigate_discrepancy` | `investigate_discrepancy` (question) {"question": "Why might the replicate variance be high in the standard channels?"} | False | ✅ |
| Show me the experiment log. | `request_ui_action` | `request_ui_action` (command) {"action": "show_tab", "argument": "log"} | False | ✅ |
| I pressed the Shift key | `none` | `none` (non_scientific) {} | False | ✅ |
| can you hear me | `none` | `none` (non_scientific) {} | False | ✅ |
| hmm okay | `none` | `none` (non_scientific) {} | False | ✅ |
| Sorry, I was talking to Ryan about lunch. | `none` | `none` (non_scientific) {} | False | ✅ |
| Channel four looks a bit cloudy. | `propose_observation` | `propose_observation` (observation) {"observation_type": "visual_description", "summary": "Channel four looks a bit cloudy.",  | False | ✅ |
| Finished the wash. | `propose_observation` | `propose_observation` (protocol_step) {"observation_type": "protocol_step_done", "summary": "Finished the wash", "protocol_step" | False | ✅ |
| I think something is off with the standards. | `investigate_discrepancy|propose_observation` | `propose_observation` (observation) {"observation_type": "deviation", "summary": "I think something is off with the standards. | True | ✅ |
