# Plan (compressed: 3 days)

**Deadline (provisional):** Wed 2026-10-28, Yerevan time. The brief allows one week from receipt and is dated 2026-10-21; the developer set 3 days remaining as of 2026-10-25 (see D-009). The exact cut-off time is still to be confirmed. **Target: submit by Wed 28 Oct 18:00.**

The challenge brief is the source of truth. Each step ends with a check that must pass before the next step starts.

| Day | # | Step | h | Exit check | Status |
|---|---|---|---|---|---|
| Sun 25 | 0 | Verify the chat export; set up repo, docs, GitHub remote | — | D-006, D-007 | done |
| Sun 25 | 1 | Windows audio-capture spike (mic + WASAPI loopback) | 1.0 | TESTS.md §Step 1 | done 2026-10-26 (TESTS.md §Step 1 result) |
| Mon 26 | 2 | Eval set: ~15 own clips with reference text (D-012) | 0.75 | TESTS.md §Step 2 | done 2026-10-27 (TESTS.md §Step 2 result) |
| Mon 26 | 3 | ASR: FastConformer ONNX — CER + real-time factor on CPU | 1.5 | Results in DECISIONS.md | — |
| Mon 26 | 4 | Translation: NLLB-600M — quality + speed on CPU | 0.75 | Choice recorded | — |
| Mon 26 | 5 | Walking skeleton, mic path: capture → VAD → ASR → MT → terminal, latency logged | 2.0 | Live `Me` lines; latency logged per segment | — |
| Tue 27 | 6 | Add loopback source, single inference worker, configuration (D-010/D-011) | 1.5 | Both sources print; settings come from config | — |
| Tue 27 | 7 | Speaker clustering + test call: 2 remote speakers on separate devices, taking turns | 2.5 | TESTS.md §Speakers | — |
| Tue 27 | 8 | Latency hardening during a live call | 1.0 | p95 within target | — |
| Wed 28 | 9 | Full rehearsal on the interview setup | 1.0 | TESTS.md checklist passes | — |
| Wed 28 | 10 | README, limitations, final chat export into `chats/`, push | 1.5 | Deliverables complete | — |

**Total ≈ 13.5 h + buffer** on Wed afternoon.

**Cut or deferred because of the deadline (D-009):**
- BuzzASR/OpenVINO experiment: only if Step 3 shows FastConformer is unusable.
- NLLB 1.3B: only if 600M's quality fails and latency allows.
- Chat converter: built during Step 10 at the latest.

**Working rules:** small verified commits; change one thing at a time; stop and rethink after 3 failed attempts; no silent fallbacks.
