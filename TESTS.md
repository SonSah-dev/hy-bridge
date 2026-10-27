# Tests and success criteria

## Mandatory (from the brief)
- [x] Microphone and system audio are captured at the same time; the user chooses the devices *(Step 1, 2026-10-26)*
- [ ] Armenian speech is recognised and printed as Armenian text
- [ ] Each segment is translated into understandable English
- [ ] Microphone speech is always labelled `Me`; remote speakers get stable `Speaker 1`, `Speaker 2`, … labels for the whole session
- [ ] Each terminal line shows time, speaker, Armenian and English
- [ ] **≤ 5 s from the end of a spoken phrase to the English line.** Measured from the last voiced audio frame to the print timestamp, logged for every segment.
- [ ] Everything runs locally; no cloud speech or translation APIs

## Provisional internal targets (to be revised after the baseline measurements)
| Area | Target |
|---|---|
| Latency | p95 ≤ 4.0 s, max ≤ 5 s, measured during a live call |
| ASR | CER ≤ 20% on our own conversational clips |
| Speakers | ≥ 85% of segments ≥ 1.5 s labelled correctly with 2 remote speakers; ≤ 1 spurious extra label per 10 min |
| Translation | ≥ 70% of segments rated "understandable" manually |
| Stability | 15-minute session with no crash and no growing delay |

## Step 1 — audio-capture spike
Run `spikes/audio_capture_spike.py` with audio **playing** (any app) while you speak. All of the following must hold:
1. Both 16 kHz pipeline streams are 30 s ± 0.2 s, and native + filled audio adds up to that length *(checked automatically)*
2. The mic file contains your voice; the loopback file contains the played audio; no clipping or dropouts *(clipping, and signal in ≥ 30% of 1 s windows, checked automatically; the rest by listening)*
3. Zero buffer overflows, zero dropped chunks, no gaps filled on the mic *(checked automatically)*
4. The played audio stays audible to you throughout, with no virtual cable *(manual)*
5. Works from a fresh virtual environment using only `pip install`, 3 runs in a row *(manual)*
6. Selecting devices by name works: `--system "<part of name>"` and `--mic "<part of name>"` *(manual)*
7. Pause the played audio for ~10 s mid-run: `system` stays 30 s long; if the loopback stops sending data, the pause is reported as one filled gap *(manual, read report.txt)*
8. Note `max callback gap` on the mic. If it is near 200 ms, raise `audio.gap_threshold_ms` *(manual)*

**Result: PASSED 2026-10-26** on the developer laptop (Intel Smart Sound mic array, Realtek speakers loopback, both 48 kHz stereo).
| # | Evidence |
|---|---|
| 1, 3 | Runs `item5-a/b/c`: pipeline 29.97–30.00 s, 0 overflows, 0 dropped chunks, 0 mic gaps |
| 2 | Signal in 40–76% (mic) and 97–100% (system) of seconds; developer listened: voice and played audio clear, no dropouts |
| 4 | Developer confirmed playback stayed audible; no virtual cable |
| 5 | Fresh `spikes\.venv`, Python 3.12.10, `pip install -r requirements-spike.txt` only; 3 runs in a row all pass; 34 unit tests pass on 3.12 |
| 6 | `--mic Intel --system Realtek` selected the same devices as the defaults (works on the Russian device name) |
| 7 | Stopped playback → one filled gap of 18.1 s, stream 29.85 s (run 1); paused player kept sending near-silence → no gap needed (pause run) |
| 8 | Max callback gap 22–41 ms across all runs; 200 ms threshold kept |
| — | Mic/system start skew 0.5–1.9 ms |

Optional, saves time in Step 7: during a test call with the two remote speakers taking turns (S1), run `--seconds 120 --tag s1-turns` and keep `system_16k.wav` as an offline fixture for speaker clustering.

## Step 2 — evaluation set (D-012)
Record with `python eval/record_clip.py --prompt pNN` (prompts in `eval/prompts.md`), then fill `hy` and `en` in `eval/manifest.jsonl`.
1. `python eval/check_manifest.py` prints **PASS**: every clip has a 16 kHz mono WAV whose length matches the manifest, an Armenian `hy` and an English `en` reference, valid ids and sources *(automatic)*
2. Length targets met (≥ 15 clips, ≥ 2 under 1.5 s, ≥ 2 of 9 s or more): no length warnings *(automatic)*
3. Each `hy` is exactly what was said, including hesitations you want the ASR to output; each `en` is a natural translation *(manual)*
4. The manifest contains no private details; `eval/audio/` stays out of git *(manual; `git status` shows no .wav)*

## Speakers (Step 7) — default scenario from D-010
Two remote Armenian speakers on separate devices, plus the developer on the mic.
- [ ] **S1 turn-taking:** A and B alternate for ≥ 10 turns of 3–10 s each. Each person keeps one label (`Speaker 1` or `Speaker 2`) for the whole session.
- [ ] **S2 return after silence:** A speaks, B speaks, 60 s of silence, then A speaks again. A keeps the original label.
- [ ] **S3 short turns:** replies under 1.5 s. Record the labelling accuracy separately; this is a known weak case.
- [ ] **S4 mic isolation:** everything from the microphone is labelled `Me`, and `Me` never appears on system audio.
- [ ] **S5 no label explosion:** no more than one spurious extra speaker label in 10 minutes.

## Configuration
- [ ] Every D-010 setting can be overridden from the command line or a config file, and the README documents each one.
- [ ] Devices can be selected by index and by name substring.
