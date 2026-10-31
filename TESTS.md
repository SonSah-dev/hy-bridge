# Tests and success criteria

## Mandatory (from the brief)
- [x] Microphone and system audio are captured at the same time; the user chooses the devices *(Step 1, 2026-10-26)*
- [x] Armenian speech is recognised and printed as Armenian text *(Step 3: CER 8.2% on own clips; FLEURS D-024; every live run since Step 5)*
- [ ] Each segment is translated into understandable English *(mic clips with the 600M: 11/15 understandable, Step 4. NLLB-1.3B is now the default: FLEURS chrF 64.6 vs 60.8, D-028. Garbled speech shows `[unclear]`, D-022. Not yet rated on a live call: Step 9)*
- [ ] Microphone speech is always labelled `Me`; remote speakers get stable `Speaker 1`, `Speaker 2`, … labels for the whole session *(`Me` part met: S4 passed on the 29 Oct call. Stable remote labels shown only on a replay of the call they were tuned on, D-020; S1–S3 and S5 need a second call. With speakers instead of headphones, call audio can print as `Me`, D-030)*
- [x] Each terminal line shows time, speaker, Armenian and English *(`[time] Label: Armenian  →  English`, every run since Step 5; unit test `test_worker_logs_and_prints`)*
- [x] **≤ 5 s from the end of a spoken phrase to the English line.** Measured from the last voiced audio frame to the print timestamp, logged for every segment. *(Live: 29 Oct call p95 2.48 s, max 2.73 s; 31 Oct call p95 2.06 s, max 2.10 s; none over 5 s. Replays on a slow-CPU day went over 5 s on 8 s monologue cuts. With the 6 s cut and the 600M fallback: max 3.93 s, D-031. Not yet live with D-031)*
- [x] Everything runs locally; no cloud speech or translation APIs *(all inference on the CPU: Silero VAD, FastConformer, NLLB via CTranslate2, WeSpeaker. Network use is only the one-time model download from Hugging Face/GitHub)*

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
2. Length targets met (≥ 15 clips, ≥ 2 with under 1.5 s of speech, ≥ 2 of 9 s or more): no length warnings *(automatic)*
3. Each `hy` is exactly what was said, including hesitations you want the ASR to output; each `en` is a natural translation *(manual)*
4. The manifest contains no private details; `eval/audio/` stays out of git *(manual; `git status` shows no .wav)*

**Result: PASSED 2026-10-27.** 15 mic clips, 129 s in total; 2 with under 1.5 s of speech, 6 of 9 s or more. `check_manifest.py` passes with one accepted warning: mic-07 is 18.5 s and ends mid-sentence.
- **Conventions in `hy`:** numbers and years as digits; clock times in words; English names and terms (Amazon, AI/ML, production, Python, Git, version control) in Latin letters. Step 3 scoring should normalise case, and may need to treat digits and spelled-out numbers as equal.
- **Manual checks:** the developer confirmed the texts match the recordings, and that names and details are invented or fine to commit.

## Step 3 — ASR baseline (D-013)
Run `python eval/bench_asr.py` on the Step 2 set. Exit check: CER and real-time factor recorded in DECISIONS.md; CER ≤ 20% and RTF well under 1 on the CPU.

**Result: PASSED 2026-10-27.** FastConformer ONNX, fp32, 2 threads: **CER 8.2%** (2.9% on the 10 clips without English terms), WER 18.9%, **RTF 0.042**; slowest clip 0.71 s for 18.5 s of audio. int8 was worse on both counts. Main error source: English terms written in Armenian letters. Mic clips only; call audio is measured in Step 7.

## Step 4 — translation (D-015)
Run `python eval/bench_mt.py` on the Step 2 set, translating both the `hy` reference and the Step 3 ASR output. Exit check: choice recorded in DECISIONS.md; ≥ 70% of segments rated "understandable" (from ASR output); time per segment leaves room in the 5 s budget.

**Result: PASSED 2026-10-27.** NLLB-200 distilled 600M, CTranslate2 int8, beam 2, 4 threads: chrF 60.8 from ASR output (opus-mt-hy-en: 40.4); median 0.73 s, max 1.72 s per segment. Manual rating: **11 of 15 understandable (73%)**; the developer's ratings matched Claude's provisional ones (`eval/results/mt-review-nllb-int8-b2-t4.csv`). Licence: NLLB accepted with README disclosure (D-005, 2026-10-27).

## Step 5 — walking skeleton, mic path (D-016)
Exit check: live `Me` lines from the microphone, and latency logged for every segment.
1. **Playback run** *(automatic, done)*: `python translate.py --wav eval/audio/mic-*.wav` plays the 15 clips in real time through VAD → ASR → fixes → MT. Result 2026-10-27: 22 segments, latency p50 1.60 s, p95 2.15 s, max 2.35 s, none over 5 s.
2. **Live run** *(manual)*: `python translate.py` (or `--mic "<name>"`). Speak interview-style Armenian for about 2 minutes, then press Ctrl+C. Pass if:
   - every phrase prints as one `[time] Me: Armenian  →  English` line;
   - `summary.json` in the run folder shows no segment over 5 s;
   - no errors appear and Ctrl+C exits cleanly, printing the summary.

   Note anything that reads wrong (split sentences, missed terms) for Step 8, and add new term spellings to `glossary.tsv`.

**Result: PASSED 2026-10-27 (timing and lines); accuracy issues found and fixed (D-017).** 4 live runs, 33 segments, latency max 2.29 s, nothing over 5 s, clean exit. The developer reported wrong numbers, hallucinated short replies, noise lines and misrecognised terms. Numbers, short replies and noise are fixed and checked by replaying the logged segments. Misrecognised terms and names remain a known weakness, and the glossary must be prepared for the interview. **Run on mains power:** on battery the same playback run had p95 2.97 s. Second live run after the fixes (21:45): p95 1.64 s; numbers, short replies and most terms correct; version-control misspellings are now caught by fuzzy glossary matching (D-018).

## Speakers (Step 7) — default scenario from D-010
Two remote Armenian speakers on separate devices, plus the developer on the mic.

**How to run** *(manual)*: wear headphones, join the call, run `python translate.py --record` and go through S1–S5 (about 10 minutes in all), then Ctrl+C. Ask A and B to leave a short pause (about 1 s) before answering. Check the printed labels; `summary.json` → `speakers` shows how many labels were made. `--record` keeps `input-system.wav`, so the threshold can be re-tuned offline with `python translate.py --wav-system runs/<run>/input-system.wav --set speakers.similarity_threshold=…`.

**Live test call 2026-10-29** (`runs/20261029-202643`, two remote people, 3.5 min, D-020): latency p95 2.48 s, none over 5 s. **S4 passed.** S1/S5 **failed** with threshold 0.4: one person got 3 labels from her first short replies. Fixed (threshold 0.35, `new_speaker_min_s` 2.0): replaying the recorded call gives 2 labels, 26/28 right, 2 `Speaker ?` (each person's first reply). S2, S3 and the 10-minute S5 were not run; **a second call is needed** to check the fix on new audio.

**Offline check done 2026-10-28** (D-020, `eval/bench_speakers.py`): three voices (developer's 15 clips + pyannote's two-speaker sample), segments ≥ 1 s all labelled right at threshold 0.3–0.4, wideband and 8 kHz narrowband. Short segments: 0 of 3 right (shown as `Speaker ?`). Unit tests cover S1, S2, S4 and the cap (S5) with synthetic voices.
- [ ] **S1 turn-taking:** A and B alternate for ≥ 10 turns of 3–10 s each. Each person keeps one label (`Speaker 1` or `Speaker 2`) for the whole session.
- [ ] **S2 return after silence:** A speaks, B speaks, 60 s of silence, then A speaks again. A keeps the original label.
- [ ] **S3 short turns:** replies under 1.5 s. Record the labelling accuracy separately; this is a known weak case.
- [ ] **S4 mic isolation:** everything from the microphone is labelled `Me`, and `Me` never appears on system audio.
- [ ] **S5 no label explosion:** no more than one spurious extra speaker label in 10 minutes.

## Configuration
- [x] Every D-010 setting can be overridden from the command line or a config file, and the README documents each one. *(`--config`/`--set` for every key, unknown keys rejected, unit tests in `tests/test_config.py`; README table covers every key, checked 2026-10-31)*
- [x] Devices can be selected by index and by name substring. *(name: Step 1 #6; index and name: unit tests `test_parse_device` and `tests/test_audio.py`)*

## Step 6 — system audio added (D-019)
Exit check: both sources print; settings come from config.
1. **Two-source playback** *(automatic, done)*: `python translate.py --wav eval/audio/mic-{01,03,...}.wav --wav-system eval/audio/mic-{02,04,...}.wav --gap-s 2`. Result 2026-10-27 (on battery): 22 segments, every `Me`/`Remote` label right, latency p95 2.20 s, max 2.84 s, none over 5 s.
2. **Live loopback** *(automatic, done)*: `python translate.py --no-mic --seconds 60` while eval clips play through the default output. Result 2026-10-27: 7 of 7 phrases printed as `Remote`; p95 1.88 s.
3. **Settings from config** *(unit tests, done)*: `audio.use_mic` / `audio.use_system` load from TOML and `--set`; unknown keys are rejected.
4. **Live call** *(manual)*: wear headphones and join a call (any app) with one other person. Run `python translate.py` (add `--system "<headset name>"` if the call plays through the headset; see `--list`). Take turns for about 2 minutes, then press Ctrl+C. Pass if:
   - your speech prints as `Me` and theirs as `Remote`, with no line printed twice;
   - `summary.json` shows no segment over 5 s, for either source (`by_source`);
   - no errors appear and Ctrl+C exits cleanly.

**Result: PASSED 2026-10-28** (`runs/20261028-225057`). 24 segments, 14 `Me` and 10 `Remote`, labels right, nothing printed twice; latency p95 1.84 s, max 2.39 s, none over 5 s. Names were mistranslated (`Սաթենիկ` → "Satanic"/"Sattenik"), and garbled ASR on unclear speech became invented English; both are left for later steps (D-019, PLAN.md backlog).

## Echo detection, shadow mode (D-030)
Logs `echo_suspect` per mic segment; never hides a line.
1. **Unit tests** *(automatic, done)*, `tests/test_echo.py`:
   - echo of the call at 0, 300 and 750 ms delay is flagged;
   - own speech with the call silent, own speech over the call at normal level, a call overlap under 0.3 s, and own speech after the call stops are not flagged;
   - the quiet-interruption limit is kept visible in a test;
   - frame placement and buffer expiry;
   - shadow mode prints the same lines, in the same order, as with the detector off;
   - a measurement error never costs a line.
2. **Replays of the recorded calls** *(automatic; skipped without the private recordings)*: 31 Oct flags exactly 8.6, 23.8, 61.1 and 69.5 s and none of the 12 own phrases; 29 Oct flags nothing.
3. **Real-time replays** *(done 2026-10-31)*: see D-030. No own speech was flagged; 3 of 5 echoes were flagged; no segment was over 5 s.
4. **Next live call** *(manual, pending)*: run `python translate.py --record` with laptop speakers. Include loud and quiet interruptions while a remote person talks, then repeat with headphones. Check `echo_suspect` in `segments.jsonl` against what was actually said. Pass if no own phrase is flagged and at least 80% of echo lines are flagged. Suppression stays off until this passes and is approved.
