# Tests and success criteria

## Mandatory (from the brief)
- [ ] Microphone and system audio are captured at the same time; the user chooses the devices
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
Run `spikes/audio_capture_spike.py`. All of the following must hold:
1. Both recordings are 30 s ± 0.2 s and can be resampled to 16 kHz mono *(checked automatically)*
2. The mic file contains your voice; the loopback file contains the played audio; no clipping or dropouts *(clipping checked automatically; the rest by listening)*
3. Zero buffer overflows *(checked automatically)*
4. The played audio stays audible to you throughout, with no virtual cable *(manual)*
5. Works from a fresh virtual environment using only `pip install`, 3 runs in a row *(manual)*
