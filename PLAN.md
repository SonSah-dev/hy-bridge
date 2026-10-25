# Plan (about 20 h, deadline Sun 2026-11-01 23:59 Yerevan time)

The challenge brief is the source of truth. Each step ends with a check that must pass before the next step starts.

| # | Step | h | Exit check | Status |
|---|---|---|---|---|
| 0 | Verify the chat-history export; set up the repo and its docs | 1.5 | Export format documented (D-006) | done |
| 1 | Windows audio-capture spike (mic + WASAPI loopback) | 2.0 | Criteria in TESTS.md §Step 1 | in progress |
| 2 | Evaluation set: ~15 own clips + a recorded call with 2 voices | 1.5 | Manifest with reference text | — |
| 3 | ASR: FastConformer CER + real-time factor on CPU; BuzzASR/OpenVINO capped at 1.5 h | 2.5 | Results in DECISIONS.md | — |
| 4 | Translation: NLLB-600M quality + speed; check whether opus-mt hy→en exists | 1.0 | Choice recorded | — |
| 5 | Walking skeleton: mic → VAD → ASR → MT → terminal, latency logged | 2.5 | Live lines appear; latency logged per segment | — |
| 6 | Add the loopback stream, the `Me` label, and a single inference worker | 1.5 | Both sources print | — |
| 7 | Speaker clustering on call audio | 3.0 | Speaker target met or explained | — |
| 8 | Latency hardening during a real call | 1.5 | p95 within target | — |
| 9 | Full rehearsal with 2+ remote speakers | 1.0 | TESTS.md checklist passes | — |
| 10 | README, limitations, final chat export into `chats/` | 2.0 | Deliverables complete | — |

**Buffer:** Sunday, Nov 1.
**Working rules:** small verified commits; change one thing at a time; stop and rethink after 3 failed attempts; no silent fallbacks.
