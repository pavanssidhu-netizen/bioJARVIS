# Larvis voice-command accuracy (real Gemini Live audio)

Run 20261108T112102Z · model `gemini-3.8-live` · 15 spoken commands, each in a fresh Live session with the production token config · raw `eval/results/benchmark_voice_20261108T112102Z.json`

Speech is synthesised (single voice, quiet room) — real-world noise/accents will be harder. One run.

| Metric | Value |
|---|---|
| cases | 15 |
| tool_accuracy | 1.0 |
| first_tool_accuracy | 1.0 |
| tool_and_args_accuracy | 1.0 |
| wrong_but_valid_args | 0 |
| no_tool_called | 0 |
| transcript_contains_key_words | 0.933 |

| Command | Expected | Got | OK |
|---|---|---|---|
| I'm on step seven, channel eight. | `set_active_step` {"step_id": "step_07", "channel_id": "CH08"} | `set_active_step` {"step_id": "step_07", "channel_id": "CH08"} | ✅ |
| Track the pipette tip. | `track_object` {"label": "contains:pipette"} | `track_object` {"label": "pipette tip"} | ✅ |
| Stop tracking the pipette tip. | `stop_tracking` {"label": "contains:pipette"} | `stop_tracking` {"label": "pipette tip"} | ✅ |
| Note that there is one bubble in channel one. | `propose_observation` {"channel_id": "CH01", "measurement_type": "bubble_count", "measurement_value": 1} | `propose_observation` {"channel_id": "CH01", "measurement_type": "bubble_count", "measurement_value": 1, "summary": "One bubble in channel 1", "value": "1 bubble", "observation_type": "general_note"} | ✅ |
| The detection antibody incubated for nine minutes. | `propose_observation` {"measurement_type": "incubation_duration_min", "measurement_value": 9} | `propose_observation` {"measurement_value": 9, "protocol_step": "step_07", "measurement_type": "incubation_duration_min", "value": "9 minutes", "observation_type": "timing_note", "summary": "The detection antibody incubated for 9 minutes.", "measurement_unit": "min"} | ✅ |
| Room temperature is twenty four degrees. | `propose_observation` {"measurement_type": "temperature_c", "measurement_value": 24} | `propose_observation` {"measurement_unit": "\u00b0C", "measurement_type": "temperature_c", "measurement_value": 24, "observation_type": "temperature_note", "value": "24\u00b0C", "summary": "Room temperature recorded as 24\u00b0C."} | ✅ |
| Channel five did not fill completely. | `propose_observation` {"channel_id": "CH05", "measurement_type": "channel_fill_complete", "measurement_value": 0} | `propose_observation` {"summary": "Channel 5 did not fill completely.", "channel_id": "CH05", "measurement_value": 0, "measurement_type": "channel_fill_complete", "observation_type": "deviation", "value": "did not fill completely"} | ✅ |
| I washed channel two for three minutes. | `propose_observation` {"channel_id": "CH02", "measurement_type": "wash_duration_min", "measurement_value": 3} | `propose_observation` {"observation_type": "protocol_step_done", "value": "3 minutes", "channel_id": "CH02", "measurement_type": "wash_duration_min", "summary": "Washed channel CH02 for 3 minutes.", "measurement_value": 3, "measurement_unit": "minutes"} | ✅ |
| Two bubbles in channel eleven. | `propose_observation` {"channel_id": "CH11", "measurement_type": "bubble_count", "measurement_value": 2} | `propose_observation` {"observation_type": "visual_description", "measurement_type": "bubble_count", "summary": "Two bubbles in Channel 11.", "value": "2 bubbles", "channel_id": "CH11", "measurement_value": 2} | ✅ |
| Scratch that, discard the last note. | `discard_observation` {"event_id": "last"} | `discard_observation` {"reason": "User requested to discard the last note.", "event_id": "last"} | ✅ |
| What would a bubble in channel three affect? | `get_impact` {"channel_id": "CH03"} | `get_impact` {"channel_id": "CH03"} | ✅ |
| How many bubbles have I noted so far? | `query_lab_log` {} | `query_lab_log` {"question": "How many bubbles have I noted so far?"} | ✅ |
| Are we recording right now? | `describe_current_recording_state` {} | `describe_current_recording_state` {} | ✅ |
| Why might the replicate variance be high in the standard channels? | `investigate_discrepancy` {} | `investigate_discrepancy` {"question": "Why might the replicate variance be high in the standard channels?"} | ✅ |
| Show me the experiment log. | `request_ui_action` {"action": "show_tab", "argument": "log"} | `request_ui_action` {"argument": "log", "action": "show_tab"} | ✅ |
