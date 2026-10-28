# Plan (compressed: 3 days)

**Deadline (provisional):** Wed 2026-10-28, Yerevan time. The brief allows one week from receipt and is dated 2026-10-21; the developer set 3 days remaining as of 2026-10-25 (see D-009). The exact cut-off time is still to be confirmed. **Target: submit by Wed 28 Oct 18:00.**

The challenge brief is the source of truth. Each step ends with a check that must pass before the next step starts.

| Day | # | Step | h | Exit check | Status |
|---|---|---|---|---|---|
| Sun 25 | 0 | Verify the chat export; set up repo, docs, GitHub remote | — | D-006, D-007 | done |
| Sun 25 | 1 | Windows audio-capture spike (mic + WASAPI loopback) | 1.0 | TESTS.md §Step 1 | done 2026-10-26 (TESTS.md §Step 1 result) |
| Mon 26 | 2 | Eval set: ~15 own clips with reference text (D-012) | 0.75 | TESTS.md §Step 2 | done 2026-10-27 (TESTS.md §Step 2 result) |
| Mon 26 | 3 | ASR: FastConformer ONNX — CER + real-time factor on CPU | 1.5 | Results in DECISIONS.md | done 2026-10-27 (D-013) |
| Mon 26 | 4 | Translation: NLLB-600M — quality + speed on CPU | 0.75 | Choice recorded | done 2026-10-27 (D-015); NLLB licence accepted (D-005) |
| Mon 26 | 5 | Walking skeleton, mic path: capture → VAD → ASR → MT → terminal, latency logged | 2.0 | Live `Me` lines; latency logged per segment | done 2026-10-27: playback and live runs pass; live accuracy fixes (D-016, D-017, D-018) |
| Tue 27 | 6 | Add loopback source, single inference worker, configuration (D-010/D-011) | 1.5 | Both sources print; settings come from config | done 2026-10-28: playback, live loopback and live call pass (D-019) |
| Tue 27 | 7 | Speaker clustering + test call: 2 remote speakers on separate devices, taking turns | 2.5 | TESTS.md §Speakers | code + offline check done 2026-10-28 (D-020); live test call (S1–S5) pending |
| Tue 27 | 8 | Latency hardening during a live call | 1.0 | p95 within target | — |
| Wed 28 | 9 | Full rehearsal on the interview setup | 1.0 | TESTS.md checklist passes | — |
| Wed 28 | 10 | README, limitations, final chat export into `chats/`, push | 1.5 | Deliverables complete | — |

**Total ≈ 13.5 h + buffer** on Wed afternoon.

**Cut or deferred because of the deadline (D-009):**
- ~~BuzzASR/OpenVINO experiment~~: run anyway on 2026-10-27 and rejected; less accurate and too slow (D-014).
- NLLB 1.3B: only if 600M's quality fails and latency allows.
- Chat converter: built during Step 10 at the latest.

**Backlog (noted 2026-10-27, to come back to):**
- **Challenge-specific eval set.** A second, small, carefully transcribed set aimed at the errors seen live (D-017, D-018), kept separate from the 15 Step 2 clips. The current glossary was tuned on those clips, so this set is also the held-out check D-016 lacks. Include real examples of:
  - numbers: `13,800`, dates, times, Armenian number words;
  - English terms inside Armenian sentences: Python, GitHub, API, Docker, Kubernetes;
  - names and places: people, companies, Armenian cities;
  - short phrases and greetings;
  - normal conversational speech from both the microphone and system audio.
- **Names in translations** (live call, D-019): `Սաթենիկ ջան` → "Satanic" / "Mr. Sattenik", `Սանաջան` → "Sana". Ideas: a names list (Armenian → Latin) applied before MT the way the glossary is, transliterating capitalised names that aren't in it, and dropping `ջան` before NLLB everywhere, not only in the phrasebook.
- **Invented translations of garbled ASR** (D-017, D-019): unclear speech gives non-words that NLLB turns into fluent, wrong English. Idea: a confidence check (ASR score or share of unknown words) that shows the Armenian with `[unclear]` instead of a translation.

- **MT repetition guard** (D-020): compare `no_repeat_ngram_size` 3/4 with off on the 15 eval clips only (a full 134-text sweep takes ~20 min on this CPU). The output-length cap already bounds the loop at ≈ 3.7 s. Step 8.
- **Speaker change inside a phrase** (D-020): a handover with < 1 s pause merges two voices into one segment. Only if the live call shows it often.

**Working rules:** small verified commits; change one thing at a time; stop and rethink after 3 failed attempts; no silent fallbacks.
