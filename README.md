# Armenian live transcription and translation

Python command-line tool that captures microphone and system audio on Windows, transcribes Armenian speech, translates it into English, and labels speakers (`Me`, `Speaker 1`, `Speaker 2`, …). All models run locally.

**Status:** in development. See PLAN.md, DECISIONS.md and TESTS.md.

Setup, model rationale, architecture and limitations will be documented here as each part is verified.

## Audio capture and configuration

Capture uses only standard Windows audio (DECISIONS.md D-011): a WASAPI **microphone** (labelled `Me`) and the WASAPI **loopback of an output device** (`system`: whatever any app plays there). Nothing depends on a particular call app, headset or virtual cable.

```powershell
python spikesudio_capture_spike.py --list                         # devices, with indices
python spikesudio_capture_spike.py --mic 9 --system "Headset"     # index or part of the name
python spikesudio_capture_spike.py --config config.toml --set speakers.min_segment_s=1.5
```

**Make sure the call app plays through the device you capture.** Many call apps use the Windows *communications* device (often a headset), not the default output. If so, select that device's loopback by name. Devices are resolved once at start; changing the Windows default mid-session is not followed.

All settings and test assumptions are listed, with their defaults, in [config.example.toml](config.example.toml) (D-010). They are provisional, not requirements; the challenge brief is the source of truth. Order of precedence: built-in defaults < `--config FILE` < `--set section.key=value` < `--mic` / `--system`. Unknown keys are rejected.

| Section | Key | Default | Meaning |
|---|---|---|---|
| audio | `mic_device`, `system_device` | `default` | index, name substring or `default` |
| audio | `fill_gaps`, `gap_threshold_ms` | `true`, 200 | loopback sends no data while nothing plays; gaps longer than this are filled with silence |
| segmentation | `end_pause_ms`, `max_segment_s` | 600, 8.0 | end-of-phrase pause; forced cut |
| speakers | `min_segment_s`, `similarity_threshold`, `max_remote_speakers` | 1.0, unset, 4 | speaker assignment |
| scenario | `remote_participants`, `separate_devices`, `turn_taking`, `call_app`, `output_setup` | 2, true, true, unspecified, unspecified | describes the test; recorded in reports only |

Unit tests (no audio hardware needed): `pip install -r requirements-dev.txt; python -m pytest tests`.

## Evaluation set

About 15 interview-style Armenian clips with Armenian and English references (DECISIONS.md D-012). Audio stays local in `eval/audio/`; the text-only manifest `eval/manifest.jsonl` is committed.

```powershell
python eval/record_clip.py --prompt p04    # Enter to start, Enter to stop; silence trimmed
python eval/check_manifest.py --draft      # progress while texts are missing
python eval/check_manifest.py              # Step 2 exit check
```
