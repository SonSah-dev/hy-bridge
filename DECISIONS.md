# Decision log

Each entry records what was decided, why, the evidence behind it, and its status.
**Status values:** `proposed` (a candidate, not yet tested) · `verified` (checked by inspection or measurement in this project) · `rejected` · `open` (needs a decision).
Published model claims are labelled *reported* until they have been reproduced here.

---

## D-001 Target hardware: CPU first, Intel acceleration optional
- **Date:** 2026-10-25 · **Status:** verified (hardware confirmed by the developer)
- **Context:** Windows laptop with an Intel Core Ultra 5 125H, 24 GB RAM and integrated Intel graphics. There is no CUDA and no dedicated GPU memory.
- **Decision:** every component must meet the 5 s latency requirement on the **CPU**. OpenVINO on the integrated GPU or NPU is only a time-boxed experiment.
- **Consequence:** Whisper-large-class models are not expected to keep up with real time on this CPU. Published CPU benchmarks report a real-time factor above 1 (*reported*, measured on other hardware).
- **Update 2026-10-27 (D-014):** measured. A Whisper-large-v3 fine-tune ran at RTF 2.64 on this CPU (torch fp32), and at 0.43 on the integrated GPU (OpenVINO fp16).

## D-002 ASR candidates (not validated)
- **Date:** 2026-10-25 · **Status:** proposed
- **Primary:** NVIDIA `stt_hy_fastconformer_hybrid_large_pc`, run through its ONNX export (`OpenVoiceOS/stt_hy_fastconformer_hybrid_large_pc_onnx`) with `onnx-asr` on CPU. The authors' paper reports 9.9% WER for Armenian (*reported*, on read speech).
- **Time-boxed experiment (≤ 1.5 h):** `BuzzASR/armenian` (a Whisper-large-v3 fine-tune) via OpenVINO on the integrated GPU. Its model card reports 3.72% CER / 11.89% WER on FLEURS (*reported*, self-published, very new). Converting it to OpenVINO and its speed on this laptop are **untested**.
- **Rejected for now:**
  - Whisper large/turbo zero-shot: slow on CPU, weaker on Armenian.
  - SeamlessM4T v2: 2.3B parameters, non-commercial licence.
  - Omnilingual ASR: Windows support unverified.
- **To verify:** CER and real-time factor on our own conversational clips (step 3).
- **Update 2026-10-25 (D-009):** the BuzzASR experiment is deferred; only run if FastConformer fails Step 3.
- **Update 2026-10-27 (D-013):** FastConformer passed Step 3 (8.2% CER, RTF 0.04 on CPU); it is the ASR. BuzzASR is not needed.
- **Update 2026-10-27 (D-014):** BuzzASR measured on our clips: 12.3% CER, RTF 2.64 on CPU and 0.43 on the integrated GPU. Rejected. Size corrected to ≈ 1.55B parameters.

## D-003 Translation candidate (not validated)
- **Date:** 2026-10-25 · **Status:** proposed
- **Initial candidate:** NLLB-200 distilled 600M (`hye_Armn` → `eng_Latn`) via CTranslate2 int8 on CPU. Memory use of about 3 GB is *reported* by a converter's notes.
- **Fallback:** NLLB 1.3B (about 5.5 GB, *reported*), only if quality is insufficient and latency allows.
- **To verify:** whether a Helsinki `opus-mt` hy→en model exists (only en→hy has been confirmed); speed and quality on our clips (step 4).
- **Update 2026-10-27 (D-015):** `Helsinki-NLP/opus-mt-hy-en` exists (Apache-2.0) but scores about 20 chrF points below NLLB-600M. NLLB-600M int8 is chosen.

## D-004 Speaker identification approach (not validated)
- **Date:** 2026-10-25 · **Status:** proposed
- **Decision:** microphone segments are always labelled `Me`. System-audio segments are labelled by **online clustering** of WeSpeaker ResNet34 embeddings (ONNX, 26.5 MB) against running cluster centroids.
- **Why not pyannote pipelines:** they are gated (accepting terms or a token is required), and their documentation describes no streaming inference.
- **To verify:** label stability on codec-compressed call audio and short segments (step 7).

## D-005 Licensing
- **Date:** 2026-10-25 · **Status:** decided 2026-10-27 (NLLB accepted with disclosure); remaining items as noted
- **The brief:** says nothing about licences. It requires local models, Python, and no model weights in the repo.
- **Known licences:**
  - NLLB-200: CC-BY-NC-4.0 (**non-commercial**)
  - SeamlessM4T: CC-BY-NC-4.0
  - FastConformer Armenian: CC-BY-4.0 (attribution required)
  - BuzzASR: MIT
  - PyAudioWPatch: MIT
- **Conflicting information:** WeSpeaker ResNet34 is tagged Apache-2.0 on Hugging Face, but WeSpeaker's documentation says VoxCeleb-trained models follow CC BY 4.0. It is treated conservatively as CC BY 4.0.
- **Verified 2026-10-27 (Step 5):** Silero VAD is MIT (official LICENSE file in snakers4/silero-vad).
- **Verified 2026-10-27:** the OpenVoiceOS ONNX export repo is CC-BY-4.0 (Hugging Face metadata). Package metadata: `onnx-asr` MIT, onnxruntime MIT, CTranslate2 MIT, sentencepiece Apache-2.0, `Helsinki-NLP/opus-mt-hy-en` Apache-2.0.
- **Pending decision (developer):** accept NLLB's non-commercial licence with disclosure in the README, or require permissively licensed models only.
- **Update 2026-10-27 (D-015):** the only permissive MT measured (opus-mt-hy-en, Apache-2.0) is about 20 chrF points worse than NLLB.
- **Decision 2026-10-27 (developer):** accept NLLB-200's CC-BY-NC-4.0 licence and disclose it clearly in the README (section *Licences*). Consequences:
  - The tool as configured is for **non-commercial use only** (e.g. this challenge, evaluation, personal use).
  - Commercial use would require replacing the translation model. `opus-mt-hy-en` (Apache-2.0) is the measured permissive fallback and already works with `armtranslate/mt.py` (`family="opus"`), at lower quality (D-015).
  - No model weights are committed (brief). Users download them from the original repos and accept each licence themselves.
  - CC-BY-4.0 models (FastConformer; WeSpeaker, treated conservatively) need attribution, which the README gives.
- Not legal advice.

## D-006 Chat-history preservation — Step 0 findings
- **Date:** 2026-10-25 · **Status:** verified (export from 2026-10-25 10:21 UTC inspected read-only)
- **Export format:** a manifest plus 4 ZIPs: `light_metadata`, `projects`, `memories`, `conversations`. `conversations-000.zip` contains a single `conversations.json` (a list of conversations). Download links expire after 24 h and may only work once.
- **Preserved:**
  - all user and assistant message text in full
  - timestamps, and the link from each message to the one it replies to
  - **every tool call** (name, exact input, ID, timestamp): 20 of 20
  - **tool results** with full content, including error results
  - citations (character positions + URL)
  - hidden context blocks (date notes, tool listings, memory snapshot)
  - Project docs, as text, in `projects-000.zip`
- **Gaps:**
  1. Reasoning ("thinking") is exported only as one-line summaries; the full text is hidden.
  2. Conversations have **no structured Project field**, so sessions must be tracked by conversation ID.
  3. Each message's built-in `text` field replaces tool steps with placeholders, so a converter must render the detailed `content` blocks instead.
- **Still uncertain:**
  - how workspace tools (Bash/Read/Write/Glob) and file uploads appear
  - whether every session stays a single conversation entry
  - These will be checked with a second trial export.
- **Open decisions:**
  - whether to include hidden context blocks verbatim in `chats/` (recommended: yes, clearly labelled; reviewed for privacy, but not edited)
  - when to build the converter and its completeness check (deferred by the developer)

## D-007 Repository location and remote
- **Date:** 2026-10-25 · **Status:** decided
- **Local:** `C:\Users\<user>\armenian-live-translate` (outside folders synced by OneDrive).
- **Remote:** a private GitHub repository, created now; the developer pushes after each verified step.
- **Line endings:** `.gitattributes` enforces LF in the repo so edits from Windows and from the Linux tooling stay consistent.

## D-008 Language variety
- **Date:** 2026-10-25 · **Status:** proposed (assumption)
- **Assumption:** Eastern Armenian is the target variety, because the brief does not specify one. To be revisited if the interview conditions indicate Western Armenian or code-switching.

## D-009 Deadline compressed to 3 days
- **Date:** 2026-10-25 · **Status:** decided by the developer (exact cut-off time to be confirmed)
- **Context:** the brief, dated 2026-10-21, allows "one week from receiving this brief". The developer set 3 days remaining as of 2026-10-25, giving a deadline of Wed 2026-10-28.
- **Decision:** compressed plan (PLAN.md), targeting submission by 28 Oct 18:00.
  - BuzzASR/OpenVINO is deferred and only tried if FastConformer fails in Step 3.
  - NLLB 1.3B is only tried if 600M fails.
  - The converter is built no later than Step 10.
- **Unchanged:** the ≤ 5 s latency requirement and the brief's deliverables.

## D-010 Test and interview assumptions are configurable
- **Date:** 2026-10-25 · **Status:** decided (these are assumptions, not requirements; the brief stays the source of truth)
- **Brief:** at least two people on the call side; the call app and audio setup are not specified.
- **Default test scenario:** two remote participants on **separate devices**, including stretches where they take turns talking (A, B, A, B …).
- **Not yet decided:** the call app and headphones vs speakers. No code may depend on either.
- **Configurable, not hard-coded:**

| Setting | Provisional default | Why it is provisional |
|---|---|---|
| Microphone device | Windows default WASAPI input | user may pick by index or name |
| System-audio device | loopback of the Windows default output | user may pick by index or name |
| End-of-phrase pause | 600 ms → **1000 ms** (D-016) | trades latency against sentence completeness; 600 ms split spontaneous sentences; revisit in Step 8 |
| Forced segment cut | 8 s | keeps long monologues within 5 s latency |
| Minimum segment length for speaker assignment | 1.0 s | short segments give unreliable voice embeddings; tuned in Step 7 |
| Speaker similarity threshold | to be measured (Step 7) | depends on call audio quality |
| Maximum remote speakers | 4 | safety cap against label explosion; brief requires at least 2 |

- Every default is documented in the README with how to override it.

## D-011 Audio capture is independent of the conferencing app
- **Date:** 2026-10-25 · **Status:** proposed (design; capture still has to pass the Step 1 spike)
- **Decision:**
  - Capture uses only standard Windows audio: a microphone input device, plus the **WASAPI loopback of an output device** (whatever plays through it, from any app).
  - There is no app-specific code, no virtual cable and no app plugin.
- **Interface:**
  - Each source (`mic`, `system`) produces timestamped 16 kHz mono float32 frames.
  - Everything downstream (VAD, ASR, MT, speakers) sees only that interface.
  - Devices are selected by index or by name substring; a `--list-devices` command prints them.
- **Timestamps:** taken from the wall clock at capture, not from frame counts. That way, if loopback delivers no data during silence, timing stays correct (to confirm in Step 1).
- **User responsibility (README):** the call app must play through the output device being captured. If a headset is used, select that headset's loopback.
- **Known limits:**
  - apps using WASAPI exclusive mode are not captured
  - echo from speakers into the mic is out of scope (brief)

### D-011 update 2026-10-25: capture layer implemented (`armtranslate/audio.py`)
- **Status:** implemented; unit-tested; one real 5 s capture on the developer laptop (mic passes, system stream silent because nothing was playing). Full Step 1 still pending.
- **Interface:** `AudioSource.read() -> AudioFrame(source, t_start, samples, rate)`; sources are `mic` and `system`. Selection by index, name substring (WASAPI devices only, case-insensitive; ambiguous names are an error) or Windows default.
- **Resampling:** `soxr.ResampleStream` (streaming, no edge artefacts between chunks), replacing per-file `scipy.resample_poly`. Timestamps take the resampler's delay into account.
- **Timing (confirmed on this laptop):** WASAPI loopback delivered **zero callbacks** while nothing was playing. Each source therefore keeps a sample clock anchored when the stream starts. When the wall clock runs ahead of it by more than `gap_threshold_ms` (200 ms), the gap is filled with silence, so the system stream stays continuous and in sync with the mic (start skew measured at 1–2 ms). Leading silence and later gaps are counted separately in the stats. A device clock running fast is resynchronised.
- **Trade-off:** silence on a loopback that has gone quiet reaches downstream up to `gap_threshold_ms` late. Call apps usually keep rendering during a call, so this should be rare. To be checked in Step 6/8.
- **Device names** come back in the Windows display language (here Russian, as Unicode). They are matched as Unicode; console output uses `errors="replace"`.
- **Step 1 runs 2026-10-26 (laptop speakers, Realtek loopback):** both loopback behaviours were seen. (a) When playback stopped, the loopback sent no callbacks; this was filled as one gap (18.1 s) and the stream stayed 29.85 s. (b) In the pause test the player kept its stream open: callbacks continued, with near-silent audio (about −80 dBFS) for about 10 s, so there was no gap and nothing needed filling. Both keep the system stream continuous. The mic noise suppressor (Intel Smart Sound) brings non-speech down to about −97 dBFS.

## D-012 Evaluation set for Steps 3–4 (Step 2)
- **Date:** 2026-10-26 · **Status:** decided by the developer (format and targets are provisional)
- **Sources:** about 15 **mic** clips of the developer now. **Call** clips (system audio, the two remote speakers) are added during Step 7 as `call-NN`.
- **Consequence:** the first Step 3 error rate reflects laptop-mic audio only. Call-compressed speech is measured in Step 7.
- **Content:** natural, interview-style Eastern Armenian (D-008): questions, answers, opinions, with some names, numbers and dates. It is spoken freely in answer to prompts (`eval/prompts.md`), not read aloud.
- **References per clip:**
  - Armenian transcript in Armenian script, exactly as spoken, typed by the developer.
  - A short, natural English translation, so Step 4 ratings are consistent.
- **Length targets:** about 10 clips of 2–8 s, 2–3 of about 9–12 s, 2–3 with under 1.5 s of **speech** (short replies; also Step 7's S3 case). Speech length excludes the trimming padding, so a 1.1 s reply in a 1.7 s file counts as short.
- **Format:**
  - Clips are recorded through the capture layer (D-011), trimmed of leading/trailing silence, and saved as 16 kHz mono 16-bit WAV in `eval/audio/` (git-ignored).
  - `eval/manifest.jsonl` has one JSON object per clip. It is text only and **committed**; content is kept free of private details.
- **Tools:**
  - `eval/record_clip.py` records one clip and adds its manifest row.
  - `eval/check_manifest.py` validates the set; it is Step 2's exit check.

## D-013 ASR: FastConformer ONNX, fp32, 2 threads (Step 3)
- **Date:** 2026-10-27 · **Status:** verified on the 15 mic clips (D-012); call audio still to measure (Step 7)
- **Setup:** `OpenVoiceOS/stt_hy_fastconformer_hybrid_large_pc_onnx` (CTC head of the hybrid model; licence CC-BY-4.0, attribution in the README) with `onnx-asr` 0.12.0 (MIT) and onnxruntime 1.31.1 (MIT), CPU only, Python 3.14. Script: `eval/bench_asr.py`; per-clip results in `eval/results/asr-*.jsonl`.
- **Scoring (`armtranslate/scoring.py`):** both texts lower-cased, `և` → `եւ`, punctuation removed (Armenian ՞ ՛ ՜ deleted inside words), digits expanded to Eastern Armenian number words. CER counts spaces. Timing is the median of 3 runs after a warm-up; RTF = compute / audio length.
- **Results (whole clips, Intel Core Ultra 5 125H):**

| Variant | CER | WER | CER, 10 clips without English terms | RTF | Slowest clip |
|---|---|---|---|---|---|
| **fp32, 2 threads** | **8.2%** | 18.9% | **2.9%** | **0.042** | 0.71 s (mic-07, 18.5 s) |
| fp32, onnxruntime default threads | 8.2% | 18.9% | 2.9% | 0.057 | 0.83 s (mic-08, 12.8 s) |
| int8 (`model.int8.onnx`) | 8.6% | 20.9% | 3.7% | 0.067 | 1.38 s (mic-07) |

- **Decision:** fp32 with 2 intra-op threads. int8 is less accurate *and* slower here, so it is dropped. Two threads beat the default (all cores), probably because the default spreads work over the slower E-cores; it also leaves cores free for translation. The thread count is a setting, to be re-checked in Step 8.
- **Internal target met:** CER ≤ 20% (TESTS.md). Speed leaves wide margin: an 8 s forced segment (D-010) costs ≈ 0.35 s of ASR.
- **Error types seen:**
  - English terms are written phonetically in Armenian letters (`Amazon-ում` → `ամազոնում`, `Python` → `փայթեն`, `AI/ML` → `էյայի էմել`). These account for most of the CER (5 clips, up to 37.5%). The text stays readable; Step 4 checks whether MT recovers the terms.
  - Short endings dropped or changed: the article `ը` (`հարցը` → `հարց`), `ք` (`կկրկնեք` → `կկրկնե`), `եմ` → `է`, `ժամը իննին` → `ժամ ին`.
  - The model card says there is no int8 variant, but the repo now ships `model.int8.onnx`; it runs on CPU.
- **Not yet known:** accuracy on call-compressed audio and on VAD-cut segments rather than hand-trimmed clips (Steps 5 and 7). BuzzASR stays deferred (D-009): FastConformer passed.

## D-014 BuzzASR measured: rejected (Step 3 follow-up)
- **Date:** 2026-10-27 · **Status:** verified on the 15 mic clips (D-012). Replaces the deferral in D-002/D-009 with a measurement.
- **Why measured:** D-002 and D-009 deferred BuzzASR because of time, not evidence. Its card reports 11.89% WER on FLEURS against 13.23% for FastConformer's CTC head (NVIDIA card), so it might have been the more accurate model.
- **Setup:** `BuzzASR/armenian` (full fine-tune of Whisper-large-v3, MIT). Generation as on the card: greedy, `no_repeat_ngram_size=3`, `repetition_penalty=1.2`. Same clips, scoring and output format as D-013, via `eval/bench_buzzasr.py`. It needs torch/transformers/optimum-intel, so it ran in a separate Python 3.12 venv (torch 2.14.1+cpu, transformers 4.57.6, OpenVINO 2026.4.1, optimum-intel 1.27.0); these are not project dependencies. One timed run per clip after a warm-up. Results are in `eval/results/asr-buzzasr-*.jsonl`.
- **Results (whole clips, Intel Core Ultra 5 125H):**

| Model / device | CER | WER | CER, 10 clips without English terms | RTF | Per clip |
|---|---|---|---|---|---|
| **FastConformer ONNX, CPU, 2 threads (D-013)** | **8.2%** | **18.9%** | **2.9%** | **0.042** | **0.03–0.71 s** |
| BuzzASR, torch fp32, CPU (14 threads) | 12.3% | 25.2% | 8.3% | 2.64 | 14.3–30.1 s |
| BuzzASR, OpenVINO fp16, integrated GPU | 12.9% | 24.8% | 9.4% | 0.43 | 2.2–4.4 s (first clip 9.9 s) |

- **Decision: rejected.** On our audio, BuzzASR is less accurate than FastConformer on every measure. It is also too slow:
  - **CPU:** 14–30 s per clip, against a 5 s budget for the whole pipeline.
  - **Integrated GPU:** 2.2–4.4 s per clip, even for a 1.5 s reply, because Whisper always pads input to 30 s. ASR alone would use most of the 5 s budget (target p95 ≤ 4 s) before the 600 ms end-of-phrase pause, translation and speaker labelling. The GPU number covers only the 15 clips, with no live load.
- **Error types (different from FastConformer's):** BuzzASR substitutes real but wrong words, which change the meaning. FastConformer mostly drops or changes word endings. Examples:
  - mic-10: `հասցրել … պրոյեկտ` ("completed … projects") → `թաքցրել … պատկեր` ("hid … pictures")
  - mic-07: `վերանայում` ("review") → `վայելում` ("enjoy")
  - mic-01: `Անահիտ Ադամյան … Վանաձոր … կավագործությամբ` → `անհատ Բադամյան … Վանոցոր … բալագործությամբ`
  
  English terms are written in Armenian letters, as with FastConformer (`AI/ML` → `էյ այ էմ էլ`).
- **Why the FLEURS ranking reversed:** BuzzASR was fine-tuned only on FLEURS and Common Voice. Both are read speech, and their test splits are what its card reports. Our clips are spontaneous laptop-mic speech. FastConformer's training also includes about 235 h of other corpora (NVIDIA card). This is a plausible explanation, not a tested one.
- **Caveats:**
  - The GPU result is fp16, and on mic-01 it differs from the CPU fp32 output (CER 23.5% vs 11.1%).
  - The first GPU clip took 9.9 s after its warm-up. This is unexplained, probably kernel compilation for new shapes.
  - The OpenVINO export takes about 4 minutes and 5.8 GB of disk.
  - The NPU was not tried.
- **Corrections to earlier statements (2026-10-27):**
  - **BuzzASR size:** a summary of its model card gave about 2B parameters. Its `model.safetensors` is 3.09 GB in float16, so it has **≈ 1.55B** parameters (the Whisper-large-v3 size), about 13 times FastConformer's 115M.
  - **"Whisper-large-class models are not expected to keep up with real time on this CPU" (D-001):** this rested on third-party benchmarks from other hardware. It is now **measured** for a Whisper-large-v3 model in torch fp32: RTF 2.64. faster-whisper/CTranslate2 int8 was not tried.
  - **"Whisper zero-shot is weaker on Armenian" (D-002):** this is backed by the BuzzASR card, which reports Whisper-large-v3 at 13.79% CER on FLEURS (BuzzASR 3.72%). It was not measured here.
  - **Omnilingual ASR (D-002):** fairseq2, which it is built on, states it has no native Windows support and lists Python 3.10–3.12 (fairseq2 README). The rejection now has a primary source, not just "unverified".
  - **D-013 limitation:** our ONNX export contains FastConformer's CTC head. NVIDIA's Transducer head is reported 0.9 WER points better on FLEURS (12.32% vs 13.23%). This accuracy is available only if a Transducer export is made; not pursued.

## D-015 Translation: NLLB-200 distilled 600M, CTranslate2 int8, beam 2, 4 threads (Step 4)
- **Date:** 2026-10-27 · **Status:** verified on the 15 mic clips (D-012); manual rating confirmed by the developer; licence accepted (D-005).
- **Candidates:** both were converted from the official repos with `ct2-transformers-converter` (CTranslate2 4.8.4, MIT) and tokenised with sentencepiece:
  - `facebook/nllb-200-distilled-600M` (`hye_Armn` → `eng_Latn`), CC-BY-NC-4.0
  - `Helsinki-NLP/opus-mt-hy-en` (Marian), Apache-2.0. **This settles D-003's open question:** an Armenian→English opus-mt model does exist.
- **Method (`eval/bench_mt.py`):** each clip is translated from the `hy` reference and from FastConformer's actual output (`asr-fp32-t2`, D-013); the latter is what the pipeline will see. chrF and BLEU (sacrebleu) are computed against the single short `en` reference, so they are relative, not absolute. Time is the median of 3 runs after a warm-up, translating the ASR text. Results are in `eval/results/mt-*.jsonl`.
- **Results:**

| Model | Weights | Beam | Threads | chrF from ASR | chrF from reference | BLEU from ASR | Median | Max (mic-07, 18.5 s of speech) |
|---|---|---|---|---|---|---|---|---|
| opus-mt-hy-en | int8 | 4 | 2 | 40.4 | 43.0 | 15.0 | 0.16 s | 0.50 s |
| opus-mt-hy-en | fp32 | 4 | 2 | 39.3 | 42.1 | 13.8 | 0.43 s | 1.24 s |
| NLLB-600M | fp32 | 4 | 2 | 60.1 | 63.0 | 32.3 | 4.10 s | 9.44 s |
| NLLB-600M | int8 | 4 | 2 | 60.6 | 63.5 | 32.0 | 1.10 s | 2.42 s |
| NLLB-600M | int8 | 1 | 2 | 57.7 | 62.2 | 30.2 | 0.76 s | 2.07 s |
| NLLB-600M | int8 | 4 | 4 | 60.6 | 63.5 | 32.0 | 0.87 s | 2.50 s |
| **NLLB-600M** | **int8** | **2** | **4** | **60.8** | 60.8 | **33.8** | **0.73 s** | **1.72 s** |

- **Decision:** NLLB-600M, int8, beam 2, 4 threads.
  - opus-mt is about 20 chrF points worse and often loses the meaning (mic-10: "we've finished about seven-year-olds"; mic-15: "develop plastic models").
  - int8 matches fp32 and is about 4× faster.
  - Beam sizes 1, 2 and 4 are within noise on 15 clips (one timed run per setting), so the fastest setting was chosen.
  - Beam and threads are settings, to be re-tuned in Step 8 when ASR and MT share one worker.
- **Latency estimate (not yet measured live):** for an 8 s forced segment (D-010): 600 ms end-of-phrase pause + ≈ 0.35 s ASR + ≈ 1 s MT ≈ 2 s, inside the p95 ≤ 4 s target. Step 5 measures it.
- **Manual rating:** **11 of 15 understandable (73%)**, against a target of ≥ 70% (TESTS.md). Claude rated first; the developer's ratings matched (`eval/results/mt-review-nllb-int8-b2-t4.csv`).
- **Failure patterns:**
  - **Numbers and times:** 2022 → "1922" (mic-06). `ժամ ին` (ASR's version of `ժամը իննին`) → "1:00" (mic-07).
  - **Rare words and place names:** Վանաձոր → "Vanassar", կավագործ (potter) → "cowboy"/"cattle industry" (mic-01). These fail even from the correct reference, so the cause is NLLB, not ASR.
  - **English terms written in Armenian letters by the ASR:** `փրադաքշ` (production) → "drill"/"PR"; `վերժեն քընթրոլ` (version control) → "neutral genes". From the Latin-letter reference they translate correctly, so this is an ASR→MT interaction.
  - **ASR ending errors change the person:** `շարունակել է` (ASR, for `եմ`) → "He continued" (mic-06).
  - **Minor:** "Thank you. Thank you." repeated (mic-04); Anna → "Hannah".
- **Open:**
  - **D-005 (decided 2026-10-27):** NLLB accepted with a README disclosure; opus-mt stays the permissive fallback. NLLB 1.3B (also CC-BY-NC) stays deferred: 600M meets the target.
  - **Call audio:** not measured yet (Step 7).

## D-016 Walking skeleton, mic path: Silero VAD, segmentation, text fixes (Step 5)
- **Date:** 2026-10-27 · **Status:** verified by playing the 15 eval clips through the full pipeline in real time. **The live microphone run by the developer is still pending** (TESTS.md §Step 5).
- **Pipeline (`translate.py`, `armtranslate/pipeline.py`):** capture (D-011) → Silero VAD → `Segmenter` → FastConformer (D-013) → text fixes → NLLB-600M (D-015) → one terminal line `[time] Me: Armenian  →  English`.
  - A single worker thread runs ASR and MT in order (D-010).
  - Each segment is logged to `runs/<timestamp>/segments.jsonl`, with latency p50/p95/max in `summary.json`. `runs/` is git-ignored because it holds transcripts of real speech.
  - `--wav` plays recordings through the same path in real time, so runs can be repeated without a microphone.
- **VAD:** Silero VAD v5 ONNX (MIT; official LICENSE file checked), 32 ms windows, run on onnxruntime with one thread.
- **Segmenter (`armtranslate/vad.py`):**
  - Speech starts at probability ≥ `vad_threshold` (0.5) and ends after `end_pause_ms` below 0.35 (hysteresis).
  - 200 ms of pre-roll is kept before the onset. Voiced bursts under 250 ms are dropped.
  - **Forced cut at `max_segment_s` (8 s):** placed at the lowest VAD probability in the last 1.5 s (`FORCED_LOOKBACK_S`), so it falls between words. A 3 s lookback was tried first and rejected: the cut point is that far in the past when the segment closes, which would add up to 3 s of latency.
  - Latency is measured from the end of the segment's last voiced chunk to the printed line.
- **Text fixes before MT (`armtranslate/textfix.py`, `glossary.tsv`):**
  - **Glossary:** user-editable TSV mapping Armenian-letter spellings to terms (`փայթեն` → Python). Armenian case endings are kept after a hyphen (`Python-ը`).
  - **Numbers:** spelled-out numbers ≥ 10 become digits (`երկու հազար քսաներկու` → 2022), including the spoken `երկուազար`. Smaller numbers are left alone, because `մեկ` also means "one/someone".
  - The printed Armenian is the fixed text, i.e. what was actually translated.
  - Bug found and fixed: Armenian punctuation (՝ ՛ ՞) lies inside the Unicode range `Ա-և`, so word boundaries now use letters only (`Ա-Ֆա-և`).
- **Effect of the fixes on the Step 4 benchmark** (NLLB int8, beam 2, translating the whole-clip ASR output): chrF **60.8 → 65.2**.
  - Fixed: mic-06 "1922" → "2022"; mic-09 "drill" → "production"; mic-13 "PR" → "production"; mic-15 "neutral genes" → "version control".
  - **Flattered:** the glossary entries were taken from these same 15 clips; there is no held-out set.
  - **Brittle:** in the live runs, new ASR spellings slipped through (`Հայայիթենը` → "Hyacinth"; with the 600 ms setting `վերժան քընթրոլ` → "cheapest nitrogenous"; `գուգում` → "Cheating").
- **End-to-end runs** (15 clips, 129 s of speech, 1.5 s silence between clips, real time, Core Ultra 5 125H):

| `end_pause_ms` | Forced cut | Segments | Latency p50 | p95 | max | Over 5 s |
|---|---|---|---|---|---|---|
| 600 | at 8 s exactly | 26 | 1.12 s | 1.53 s | 1.61 s | 0 |
| 1000 | at 8 s exactly | 22 | 1.52 s | 1.86 s | 1.87 s | 0 |
| **1000** | **quietest point of last 1.5 s** | **22** | **1.60 s** | **2.15 s** | **2.35 s** | **0** |

- **Decision: `end_pause_ms` 600 → 1000** (D-010 default changed). With 600 ms, natural pauses in spontaneous speech split sentences into fragments that translate into nonsense ("Ես աշխատել եմ" | "Ամազոնում…"; mic-08 split inside the word `իրական|ացրել`). 1000 ms costs about 0.4 s of latency, and p95 stays at about half the 4 s target. To be revisited in Step 8 with live conversation.
- **Known weaknesses:**
  - Sentence fragments (e.g. a lone "Հությունը" → "The story") still occur at long hesitations.
  - ASR on a forced-cut continuation is worse than on the whole clip (mic-07's middle part).
  - The 1.5 s lookback may find no real pause in very fast speech.
  - All runs used trimmed, single-speaker playback through `--wav`: there was no microphone noise and no competing CPU load from the system-audio source (Step 6).

## D-017 Live microphone findings: short replies, numbers, noise (Step 5)
- **Date:** 2026-10-27 · **Status:** live runs by the developer; fixes verified by replaying the logged ASR text and on the eval set.
- **Live runs:** 4 runs (`runs/20261027-201453`, `-210043`, `-210320`, `-210444`), 33 segments, laptop microphone (Intel Smart Sound).
  - **Latency passed:** p95 1.51–2.06 s per run, max 2.29 s, nothing over 5 s.
  - **Accuracy problems reported by the developer and confirmed in `segments.jsonl`:**
    1. **Numbers.** The ASR wrote number words slightly off: `քառասոուն` (for `քառասուն`), `ութսանութ` (for `ութսունութ`), `ին` (for `ինը`), and the stutter `հինինգ`. The D-016 converter turned whatever parsed into digits and left the rest, giving **confidently wrong numbers**:
       - `Տասներեք հազար ութ հարյուր քառասոուն` → "13800 քառասոուն" → "13800 square feet"
       - `հազար ին հարյուր ութսունութ` → "1000 ին 188" → "born in 1881"
       - `հինինգ հարյուր յոթանասուն հազար` (570 000) → "170000"
    2. **Short replies hallucinated by NLLB,** although the ASR text was correct: `Հաջողություն։` → "What is the meaning of life?"; `Ողջույն Սոնա ջան։` → "I'm going to tell you something."; `Մամ ջան։` → "I'm going to be a mother."
    3. **Noise segments** (`«.`, `Ե։`) were "translated" into invented sentences.
    4. **Terms and names misrecognised by the ASR:** `Այթինը` (Python) → "Aitin"; `Սանաան` (Sona).
- **Short-input tests** (9 phrases, NLLB-600M and opus-mt, beams 2 and 4, with `։`, `.`, `!` or no punctuation): no setting was reliable on 1–3 words.
  - Beam 4 with `.` hallucinated least (`Հաջողություն` → "Successful.").
  - Replacing `։` with `.` *lowered* chrF on the full eval sentences (65.2 → 62.5), so it is applied to short segments only.
  - Beam 4 for everything was slower with no gain overall (chrF 64.6, max 3.4 s).
- **Fixes:**
  - **Phrasebook (`armtranslate/phrasebook.py`, `phrasebook.tsv`, user-editable):**
    - Segments of 1–3 words are looked up first: greetings, thanks, yes/no, good luck, forms of address.
    - The endearment `ջան` is ignored when other words remain.
    - A phrase followed by capitalised words is treated as phrase + names, and the names are transliterated (Armenian → Latin): `Ողջույն Սոնա ջան` → "Hello, Sona."
    - Short segments not in the phrasebook go to NLLB with beam 4 and `։` → `.` (`mt.short_beam_size`).
    - A segment that is only a number is shown as is: NLLB invented "13840. What is it?".
  - **Numbers (`armtranslate/textfix.py`):**
    - A one-letter variant of a number word of 6+ letters is accepted. The vowel `ու` counts as one letter.
    - `ին` before հարյուր/հազար reads as `ինը`, and `քսանուերեք` reads as 23.
    - Variants are only accepted next to a correctly spelled number word.
    - **If an unreadable number-like word is next to the phrase, nothing is converted** (the words go to MT unchanged). A wrong digit is worse than words.
    - The replay caught a false variant, `համար` ("for") ~ `հազար` (thousand), which led to the 6-letter minimum.
  - **Noise filter:** segments with fewer than 2 Armenian letters are not shown (`text.min_letters`); the count is in `summary.json`.
- **Verification:**
  - **Replaying the 33 logged live segments** through the new path (same ASR text, so speech-recognition errors remain):
    - Every reported number case is now correct: "born in 1988" ×2, "1998", "23 years old", "13840".
    - "Good luck.", "Hello, Sona.", "Hello, Sanaan.", "No.", "Dear.", "Mom." are correct.
    - Both noise segments are hidden.
    - The stutter case is no longer converted, but NLLB still reads `հինինգ հարյուր յոթանասուն հազար` as 170,000.
  - **Eval set:** chrF unchanged at 65.2, so long sentences did not regress. 136 unit tests pass, including every live case above.
  - **Full pipeline on the eval clips:** 22 segments, nothing over 5 s, but p95 2.97 s and max 3.2 s (it was 2.15/2.35 s). **The laptop was on battery** (Balanced plan, 76%): ASR on an 8 s segment took 0.5–0.77 s against 0.35 s plugged in (D-013). The slowest segments are all forced cuts, where the 1.5 s lookback adds to the wait. **Run the interview on mains power.**
- **Still weak:**
  - ASR misrecognition of English terms and non-Armenian names (`Այթինը`, `Հայայիթենը` for Python). The glossary only catches spellings already seen, so add likely terms and names before the interview.
  - Number words that the ASR garbles badly are left as words, and NLLB may still misread them.
  - Short phrases outside the phrasebook can still hallucinate.
  - The phrasebook covers common replies only.

## D-018 Fuzzy glossary matching (Step 5, second live check)
- **Date:** 2026-10-27 · **Status:** verified on the developer's live run `runs/20261027-214510` (12 segments) and by replaying all 96 logged texts.
- **Live run with the D-017 fixes:** p95 1.64 s, max 1.67 s.
  - Correct: all numbers (1987, 7321, 688 including the variant `ութսանութ`, 2004), "Good luck.", Python, JavaScript, Google, Amazon.
  - Misses reported by the developer: `Վժըն քընթռոլ` → "I'm going to take a shower."; also `վեժին քընթրոլ` → "low-carbohydrate diets", `Ողջույն Սոնաջան` → "Hello, Sonajan.", `Ամազո՞` → "What is it?".
- **Finding:** the ASR spells the same term differently almost every time. Version control has come out as `վերժեն`/`վերժան`/`վեժին`/`Վժըն` + `քընթրոլ`/`քընթռոլ`. Adding exact spellings cannot keep up.
- **Change (`armtranslate/textfix.py`):** after exact matching, glossary words of **6+ letters** (`ու` counts as one letter) also match misspellings:
  - single-word entries: **1 letter** off;
  - multi-word entries: up to **len/3 letters per word**, with the same first letter, because all words matching together is distinctive;
  - shorter entries stay exact, so `գիծ` ("line") never becomes Git.
- **Phrasebook:** a name with the endearment glued on (`Սոնաջան`) is read as `Սոնա`.
- **Glossary:** added the observed variants `վժըն քընթռոլ`, `հայայիթեն`, `այթին`, `ջավասքրիպտ`/`ջավասքրփթ`.
- **False positives found by replaying all 96 logged texts (fuzzy on vs off) and fixed:**
  - With a 2-letter allowance on single words, `Ամառն` ("summer") → Amazon. Fixed by allowing only 1 letter for single-word entries.
  - With a 5-letter minimum, `Այնին` → Python (via `այթին`). Fixed by raising the minimum to 6.
  - After the fixes only 3 texts change, all correctly (`Ամազո՞` → Amazon, `վերժան`/`վեժին քընթրոլ` → version control). Unit tests cover both false positives.
- **Result on the live run:** 11 of 12 lines now right. Changed: "Hello, Sona.", "Git is used for version control.", "version control.", "What about Amazon?". Eval chrF unchanged at 65.2. 145 unit tests pass.
- **Still weak:** fragments the ASR garbles (`Աեից։` → "I'm going to tell you.") are too long for the noise filter and still get invented translations. Terms the ASR mangles beyond these limits still need explicit glossary entries.

## D-019 Second source: system audio (loopback) in the same pipeline (Step 6)
- **Date:** 2026-10-27 · **Status:** verified by a two-source playback run, a live loopback run and a live call by the developer (2026-10-28, `runs/20261028-225057`).
- **Change:** `translate.py` captures the microphone (`Me`) and the loopback of an output device (`Remote`) together, by default.
  - Each source has its own Silero VAD and `Segmenter` (the VAD is stateful), and both feed the **one inference worker** (D-010). Segments are processed in the order they close, so the CPU never runs two inferences at once.
  - `Remote` is a placeholder label. Step 7 splits it into `Speaker 1`, `Speaker 2`, … .
  - **Settings:** `audio.use_mic` and `audio.use_system` (both `true`) in the config. On the command line: `--system DEVICE`, `--no-mic`, `--no-system`. `--wav-system` plays files as the call, next to `--wav` for the mic. `--seconds N` stops a run by itself, for scripted tests.
  - `summary.json` adds latency per source (`by_source`).
- **Reader loop fix:** the Step 5 loop read one frame per source and waited up to 20 ms on each. With two sources, a quiet source would hold up a busy one, and since each source produces a 20 ms frame every 20 ms, a backlog could build. The loop now takes every frame each source has ready without waiting, and sleeps 5 ms only when no source had anything. Playback sources return `None` when their next frame is not due yet, instead of sleeping.
- **Two-source playback run** (8 eval clips as the mic and 7 as the call, played at the same time in real time, so they overlap; **laptop on battery**, 45%):
  - 22 segments, 13 `Me` and 9 `Remote`, all with the right label.
  - Latency p50 1.62 s, p95 2.20 s, max 2.84 s, nothing over 5 s. The single-source run on battery had p95 2.97 s (D-017).
  - The longest wait for the worker was 0.70 s, once, when both sources closed a segment at almost the same time. Otherwise it was under 25 ms.
  - Translations matched the single-source runs. The one garbled line (mic-07's continuation after a forced cut) was garbled the same way in Step 5 (D-016), so it is not caused by the second source.
- **Live loopback run:** 5 eval clips played through the laptop speakers (Realtek) and captured from their loopback with `--no-mic`. All 7 phrases printed as `Remote` lines. Latency p50 1.49 s, p95 1.88 s, max 1.89 s.
- **Live call** (developer, 2026-10-28; laptop mic + loopback of `Speaker (Realtek)`, one remote person, taking turns):
  - 24 segments, 14 `Me` and 10 `Remote`, every label right and no phrase printed twice.
  - Latency p50 1.55 s, p95 1.84 s, max 2.39 s, nothing over 5 s. Per source, p95 was 2.04 s for `Me` and 1.69 s for `Remote`. The longest wait for the worker was 0.21 s.
  - **Accuracy problems (for later steps):**
    - **Names:** `Սաթենիկ ջան` → "Satanic, what are you doing?" and "Mr. Sattenik"; `Սանաջան` → "Sana". The phrasebook only transliterates names after a greeting it knows (D-017).
    - **Garbled ASR on unclear speech**, which NLLB turns into fluent but invented English (`Աես բարառերն են…` → "Those are the bastards, you know."; `Հորսկացադր ներ։` → "What is the meaning of this verse?").
    - Short phrases mistranslated: `Լավ, դուք ինչ բացեք` → "All right, you guys open up."
- **Not tested yet:**
  - The mic and system audio live at the same time with **speakers**, the mic also hears the call, so remote speech would print twice (once as `Me`). Echo is out of scope (brief, D-011). **Use headphones**, or turn the speaker volume low.
  - Sustained overlapping speech: the worker's queue would grow by one segment's ASR + MT time (≈ 1 s) per overlap. To be watched in Step 8.

## D-020 Remote speaker labels: WeSpeaker ResNet34-LM + online clustering (Step 7)
- **Date:** 2026-10-28 · **Status:** implemented and checked offline; **the live test call (TESTS.md §Speakers, S1–S5) is still pending.** The threshold is an offline estimate until then.
- **Model:** `Wespeaker/wespeaker-voxceleb-resnet34-LM` (`voxceleb_resnet34_LM.onnx`, 26.5 MB, 256-dim embeddings). Licence CC-BY-4.0 on its Hugging Face card, which settles D-005's conflicting information for this variant. Run with onnxruntime, 2 threads.
- **Features without torch:** Kaldi 80-bin log-mel fbank (25/10 ms, Hamming, no dither, input scaled to the int16 range, mean-normalised over time) written in numpy (`armtranslate/speakers.py`). Checked against `kaldi-native-fbank` 1.22.4 on mic-01: max difference 0.0006 (mean |value| 4.7). `kaldi-native-fbank` is not a dependency.
- **Clustering (`SpeakerTracker`):** microphone segments stay `Me` (D-004). Each system-audio segment that passes the noise filter (D-017) is embedded and compared by cosine with each remote speaker's centroid (running sum of embeddings).
  - ≥ `min_segment_s` (1.0 s): joins the best speaker if similarity ≥ `similarity_threshold`, and updates its centroid; else becomes a new `Speaker N`; at `max_remote_speakers` (4) the nearest speaker is used (`cap`, logged).
  - Shorter: borrows the best speaker's label if similarity ≥ `short_threshold` (default: the same as `similarity_threshold`), else `Speaker ?`. It never creates or moves a speaker.
  - Centroids never expire, so a speaker keeps their label after any silence (S2).
  - Each segment's similarities and decision are logged in `segments.jsonl` (`speaker`); `summary.json` adds a `speakers` block. `--no-speakers` / `speakers.enabled=false` returns to `Remote`.
- **Offline data (`eval/bench_speakers.py`):** the developer's 15 mic clips (Armenian) and pyannote's MIT-licensed two-speaker sample (`tutorials/assets/sample.wav` + `.rttm`, English, 30 s; overlapped parts removed; saved git-ignored in `eval/audio/external/`). No Armenian call audio with two remote speakers exists yet. "Narrowband" resamples to 8 kHz and back, a rough stand-in for a poor codec.

| | same speaker, ≥ 1.5 s: p5 / median | different speakers, ≥ 1.5 s: median / max | best pairwise split |
|---|---|---|---|
| wideband | 0.34 / 0.63 | 0.05 / 0.42 | 0.34 (6% error) |
| narrowband 8 kHz | 0.27 / 0.64 | 0.22 / 0.46 | 0.36 (9% error) |

  - Online clustering, segments ≥ 1 s: at threshold **0.3–0.4 every segment is labelled right** (two voices in real turn order 6/6; three voices interleaved 21/21), wideband and narrowband. 0.5–0.6 makes one spurious label; 0.7 makes 4.
  - **Decision: `similarity_threshold` = 0.4**, the high end of the clean range: centroid matching beats pairwise similarity, and an extra label is a smaller error than merging two people.
  - Short segments (< 1 s): 0 of 3 right; two came before any speaker existed, and one was nearer the wrong speaker (0.26). Short replies are shown as `Speaker ?` rather than lowering their threshold on 3 samples. **Known weak case (S3).**
  - Embedding time: median 0.21 s, up to 0.45 s for an 8 s segment (0.62 s for an 18 s clip). It runs in the single worker (D-010) and adds to system-audio latency only.
- **Caveats:** tiny data (3 voices, 24 segments); the developer's clips and the pyannote sample come from different microphones, which makes them easier to tell apart than two people on one call app. The live call decides.
- **Found in the two-source playback run** (`runs/20261028-230813`, pyannote sample as the call):
  - **Turns without a pause are merged.** In the sample the speakers answer with no gap, so VAD segments (forced 8 s cuts) contain both voices, and all 8 segments became `Speaker 1`. Labels can only be as fine as segments: the next speaker must leave about `end_pause_ms` (1 s). Splitting a segment at a speaker change is not implemented (PLAN.md backlog).
  - **MT loop: 13.8 s for one segment.** Garbled ASR text (English speech) made NLLB repeat "well, well, …" up to its 256-token limit; with the segments queued behind it, 2 segments went over 5 s. **Fix:** output capped at 2 × input tokens + 10 (`armtranslate/mt.py`). Over all 134 logged and eval texts, real translations used at most 2.0× (only 1–3 piece inputs reach it); the loop used 7.3×. The capped loop still takes ≈ 3.7 s and stays garbage. A repetition guard is left for Step 8 (PLAN.md backlog).
- **Recording:** `--record` saves the live audio (`input-mic.wav`, `input-system.wav`) in the run folder, so the test call can be replayed with `--wav-system` to re-tune the threshold. Recordings stay in the git-ignored `runs/`.
- **Live test call, 2026-10-29** (`runs/20261029-202643`, `--record`; laptop mic + `Speaker (Realtek)` loopback; two remote people on separate devices, about 3.5 min; developer confirmed who said what):
  - Latency p50 1.63 s, p95 2.48 s, max 2.73 s, nothing over 5 s (76 lines). Speaker step at most 0.22 s. S4 passed: all mic lines `Me`, nothing printed twice.
  - **Labels with threshold 0.4: 4 for 2 people.** Person B's first three replies (1.4 s, 2.4 s, 2.8 s) each started a new speaker (`Speaker 2`, `3`, `4`; best similarities 0.19, 0.25, 0.38). After that, both people kept one label to the end.
  - **Call audio scores lower than the offline data:** same-person median 0.47 (A) and **0.36** (B); different people median 0.18, **max 0.40**. 0.4 sat on the overlap.
  - **Change:** `similarity_threshold` 0.4 → **0.35**, and a new setting **`new_speaker_min_s` = 2.0**: segments between `min_segment_s` and 2 s may join a known speaker (and update it) but never start one; unmatched they show `Speaker ?` (decision `unknown`).
  - **Replaying the recorded call** (same VAD segments, 28 of 28 matched to the live log) with the new defaults: **2 labels, 26/28 right**; the 2 others are `Speaker ?`, each person's first reply before anyone was known. Sweep: thresholds 0.3–0.35 with a 2 s minimum gave 26/28; 0.4 with 2 s gave 3 labels; a 3 s minimum labelled many lines `Speaker ?`.
  - **Caveat:** tuned and checked on the same 28 segments, so not held out. S2 (60 s silence), S3 (short replies) and a 10-minute S5 were not run. A second call is needed.
  - The offline numbers above were measured before `new_speaker_min_s` existed.

## D-021 Names list: Armenian-letter names -> Latin before translation (Step 8, quality)
- **Date:** 2026-10-29 · **Status:** verified by replaying all 211 logged and eval texts; not yet on a live call.
- **Problem (D-019, test call D-020):** NLLB turns Armenian-letter names into words or other names: `Սաթենիկ` → "Satan"/"Satanic"/"sadist", `Լուսինեն` → "Lune", `Գոհա` → "Gohan", `Վանաձոր` → "Vanassar", `Սոնաան` → "Sonja". The phrasebook handles names only after a greeting it knows (D-017).
- **Check first:** NLLB keeps **Latin** names inside Armenian sentences: `Լավ Gohar, դուք մեզ լսո՞ւմ եք։` → "All right, Gohar, can you hear us?"; `քո եւ Satenik-ի զրույցը` → "your conversation with Satenik". But `Satenik ջան` → "Mr. Satenik".
- **Change:**
  - `names.tsv` (user-editable, same format as the glossary): Armenian spelling → Latin. Applied in `TextFixer` after the glossary, with the glossary's matching: endings kept after a hyphen (`Satenik-ի`), and one-letter misspellings for names of 6+ letters (`Սաթթենիկ`, `սաթեմիկի`). Shorter names match exactly, so ASR variants are listed (`Սոնաան`, `Գոհա`).
  - `ջան` right after a name is dropped, including when glued on (`Սոնաջան` → Sona).
  - Phrasebook: a Latin capitalised word counts as a name too, so `Առայժմ Satenik` → "Bye for now, Satenik." (new entry `առայժմ`).
  - Setting `text.names` (`""` = off).
  - **Not done:** transliterating unknown capitalised words. Of the mid-sentence capitalised words in the logs, many were ASR garbage, and `Հայաստանի` is already translated as "Armenia", which transliteration would break.
- **Replay** (same ASR text, so recognition errors remain): 21 of 211 texts change.
  - **Better (16):** "Hi, Satenik.", "Bye for now, Satenik.", "My name is Lusine.", "All right, Gohar, …", "your conversation with Satenik", "I'm Anahit Adamyan from Vanadzor", "Very well, Sona.", "Hello, Sona." (was "Sanaan").
  - **Same:** "Hello, Sona." twice (the phrasebook already did it).
  - **Not better:** `Սաթեն՞ք` (garbled) "What is Satan?" → "Do you eat?".
  - **Worse (1):** a garbled post-call segment (`Աքատամ շատ լավ Սոն ա ջան գրիլա Սոնա Ան…`) went from "Sonja, sonja, …" to a crude English sentence. Garbage in either case; the `[unclear]` check (PLAN.md backlog) is meant for such text.
- **Flattered:** `Անահիտ`, `Ադամյան`, `Վանաձոր` come from eval clip mic-01, and the others from the logged calls, as with the glossary (D-016). The real test is the interview's names, which the user adds beforehand.
- 170 unit tests pass.

## D-022 `[unclear]` instead of invented English for garbled recognition (Step 8, quality)
- **Date:** 2026-10-29 · **Status:** verified offline on 131 recorded segments; not yet on a live call.
- **Problem (D-017, D-019, D-020):** unclear speech gives non-words, and NLLB turns them into fluent but invented English (`Տ գրված ծ ին բալ ծրագիր…` → "It's written in a blueprint."; `Աես բարառերն են…` → "Those are the bastards, you know.").
- **Signal:** the FastConformer CTC head gives a log-probability per output token through onnx-asr's `with_timestamps()` adapter, in the same pass: **no extra cost** (8 s segment: 0.069 s plain, 0.068 s scored). Per segment: the **mean token log-probability** and the **share of tokens with probability < 0.5**. Both are logged in `segments.jsonl` (`asr_conf`).
- **Data:** every recorded run re-segmented with the live VAD settings: the test call (`20261029-202643`, mic and system: clear call speech plus garbled after-call chat), the English sample played as the call (`20261028-230813`, all garbled), and eval-clip playback (`20261027-191427`, `-221739`, clean). 114 unique texts.
  - Clear sentences: mean −0.00 to −0.10, low share 0. Clearly garbled: mean −0.3 to −0.94 and/or low share ≥ 0.15. Between −0.3 and −0.15, garbled chat and correct short words (`Ցտեսություն։` −0.20, `Շնորհակալություն։` −0.21) overlap.
- **Rule:** `[unclear]` if mean < **−0.3** or low share ≥ **0.15**, unless the fixed text is an exact phrasebook phrase (D-017; a known phrase is trusted). The line shows the Armenian and `[unclear]`; MT is skipped. Settings `asr.unclear_mean_logprob`, `asr.unclear_low_share` (`none` = off). `summary.json` counts `unclear`.
- **Replay result:** 12 of 114 flagged.
  - **10 clearly garbled:** two forced-cut fragments of eval clip mic-07 (−0.94, −0.87), `Ապրումեք սածան`, `Տ գրված ծ ին բալ…`, three English-sample lines, `Քեզ հետ լվում`, `Լա`, `Աասա, Լուսինեն էլ ավտոմատ տառաս…`.
  - **2 borderline (after-call chat):** `Ձայնս հաճաճելի ա, հաո, իրոք էնքան հաճելի…` was mostly understandable and NLLB had translated it reasonably: a **false positive**. `Ս տեսամեցնում, Շան, …` is half garbled.
  - **No correct eval or call sentence was flagged.**
  - **Missed:** garbled lines with confident-looking tokens: `Պարոն Նջելինը` (English sample, −0.18), `Սաթեն՞ք`, and most of the after-call chat, including the line that became a crude sentence in D-021 (−0.18). So this removes the worst invented translations, not all.
- **Caveat:** thresholds chosen on these same segments, without a held-out set; the challenge-specific eval set (PLAN.md backlog) would give one.
- 173 unit tests pass.

## D-023 MT repetition guard: looping translations shown as `[unclear]` (Step 8, quality)
- **Date:** 2026-10-29 · **Status:** verified on tuning data, on held-out eval results and on two sets of new phrases; not yet on a live call.
- **Where the repetition comes from:** all 201 unique (Armenian, English) pairs in the logged runs were scanned for the longest back-to-back repeat of a word n-gram (n ≤ 4). 8 translations repeat; in **every one the Armenian source has no repetition (×1)**, so the loop is made by NLLB. All but one source are garbled ASR (`Ի ջան, հը լավ գո…` → "yeah" ×8; `…Սոն ա ջան գրիլա Սոնա…` → "sonja" ×5; `Լավան, ինչպես ես…` → "what have you done" ×3; the English sample → "well" ×121, "oh" ×3). The exception is `Շնորհակալություն։` → "Thank you. Thank you." (×2), which the phrasebook now answers.
- **Choice: a detector, not a decoding change.** `no_repeat_ngram_size`/`repetition_penalty` would change every translation and need a full chrF re-run; a check on the output touches only the looping ones. The length cap (D-020) still bounds the time a loop takes (≈ 3.7 s).
- **Rule (`armtranslate/mt.py`, `is_degenerate`):** the output is degenerate if some word n-gram (n ≤ 4, case and punctuation ignored) repeats **≥ 3 times in a row** and **≥ 2 times more than any repeat in the Armenian source**. A degenerate output is replaced by `[unclear]` (`unclear_reason` `"mt-repeat"`; ASR-based ones are `"asr"`, D-022, unchanged). Setting `mt.repeat_min_run` (3; `none` = off). Cost: 2.4 ms on the worst case (121 words).
- **Results, kept apart by how the data was used:**
  - **Tuning (logged runs, used to design the rule):** 5 of 201 flagged, all loops above (×121, ×8, ×5, ×3, ×3). Not flagged: the ×2 repeats ("Thank you. Thank you.", "you're wrong, you're wrong").
  - **Held-out 1, eval results** (`eval/results/mt-*.jsonl`: 15 clips × 8 MT configurations × from-reference and from-ASR = 240 outputs; not inspected for repetition before the rule was fixed): **0 flagged** with both versions of the rule. Only ×2 repeats occur.
  - **Held-out 2, 12 new Armenian phrases with real repetition**, translated with the live settings: the first version (`output > source`) flagged **1 of 12**: `Շնորհակալություն, շնորհակալություն, շատ շնորհակալություն։` → "Thank you, thank you, thank you very much." (source ×2 because `շատ` breaks the run, output ×3) — a false positive. **The margin of 2 was added because of it, so this set then became tuning data.**
  - **Held-out 3, 10 more new phrases written after that change:** **0 of 10 flagged**, including `Հա, հա, հա` → "Oh, oh, oh, oh" (×3 → ×4) and "Wait, wait, wait, …".
- **End-to-end:** a 2-clip playback run works (latency max 1.12 s); `summary.json` counts `unclear`.
- **Limits:** a loop that repeats only twice, or a non-repeating invented sentence, is not caught (that is D-022's job, which also misses some). The garbled source is still shown in Armenian. Real repetition 2+ times longer in English than in Armenian would be wrongly flagged; none seen in 262 held-out outputs.
- 192 unit tests pass (regression tests: the 5 real loops; 10 valid repetitions, including both margin cases).

## D-024 Held-out check on FLEURS Armenian (test split)
- **Date:** 2026-10-30 · **Status:** measured. Data: Google FLEURS `hy_am` test split (CC-BY-4.0; 932 clips, 350 sentences, 3.0 h, read Wikipedia sentences), English references from the matching `en_us` rows. Audio is git-ignored under `eval/audio/fleurs/`; per-clip results are git-ignored (`eval/results/fleurs-*.jsonl`); `eval/results/fleurs-summary.json` holds the numbers and the changed sentences (FLEURS text, CC-BY-4.0, Google). Script: `eval/bench_fleurs.py`.
- **Why it counts as held out:** nothing in the glossary, names list, phrasebook, `[unclear]` thresholds or repetition guard was tuned on it, and FastConformer was trained on FLEURS *train*, not test. Whole clips (up to 33 s) were recognised, without the live VAD cuts. **Limit:** read speech, not conversation; few of the terms and names the lists target.
- **ASR:** CER **2.8%**, WER 10.5% (D-013 mic clips: 8.2% / 18.9%), RTF 0.029, slowest clip 1.15 s for 33 s. Worst clip CER 28%, mostly spoken digits (`802.11n` → "ութ հարյուր երկու կետ տասնմեկ").
- **`[unclear]` (D-022): 0 of 932 flagged.** Least confident clip mean −0.144 (1st percentile; the cut-off is −0.3); largest unsure-token share 0.114 (cut-off 0.15). Confidence correlates with CER (r = −0.41). **No false alarms on clean speech; recall on garbled speech cannot be measured here** (no clip above 28% CER).
- **Repetition guard (D-023): 0 flagged** among 823 distinct translations.
- **Glossary and names lists:** they fire on **4 distinct sentences** of 350 (before the fix below):
  - `ամազոնից` → Amazon (the river): correct; chrF 52.9 → 65.1 and 55.4 → 63.2.
  - `Սուրբ Մարիամի` → "Saint Mariam" instead of "Mary": chrF 49.9 → 41.8.
  - **False match, glossary:** `Լայթեն` (the name Layton) → **Python**, a one-letter fuzzy match against `փայթեն` with a different first letter.
  - **False match, names:** `լուսինն` ("the moon") → **Lusine**, a fuzzy match of a lowercase noun.
  - Corpus chrF: none 57.59, glossary 57.62, names 57.58, both 57.61, i.e. **no measurable effect** on general text. They neither help nor hurt on average; the risk is the individual false match.
- **Fix (`armtranslate/textfix.py`):** a fuzzy glossary match must keep the first letter (multi-word entries already had this rule), and a fuzzy *name* match must be capitalised. Exact matches are unchanged. Both FLEURS false matches are now regression tests, **so these sentences are now tuning data.** Replaying the 211 logged live texts: the tightening loses one earlier correct fix, the lowercase misspelling `սաթեմիկի` (Satenik). After the fix, 4 → 3 FLEURS sentences change (both false matches gone).
- **MT time:** median 0.99 s, p95 1.82 s, p99 2.76 s; whole 30 s clips (124 tokens) took 4.7 s, which the live 8 s forced cut avoids. **One outlier: 49.1 s** for a 42-token sentence that re-runs in 0.9–1.4 s with identical output. Windows logged Modern Standby entries/exits (Kernel-Power 506/507) during the run, so standby is the likely cause (not proven to the second). **For the interview: mains power, and sleep/standby off.**
- **Conclusion:** the general mechanisms (numbers, phrasebook, `[unclear]`, repetition guard) show no harm on held-out data. The glossary and names lists have no measurable average effect on general text and produced 2 false matches in 350 sentences; their benefit for interview vocabulary is still unmeasured. Treat them as preparation aids, kept exact or close to it.
- 193 unit tests pass.

## D-025 Bare names and units shown as is; spoken clock times as digits
- **Date:** 2026-10-30 · **Status:** verified by replaying the developer's mic test (`runs/20261030-214321`), all logged texts and the FLEURS ASR output; not yet on a live call.
- **Mic test (2.5 min, mic only, no call audio):** latency p50 1.45 s, p95 1.66 s, max 1.68 s. Names, places and full sentences were right ("Hello, Satenik.", "Vanadzor is quite far away.", "Sona is late for the meeting.", "The capital of Armenia is Yerevan."). Problems:
  1. A segment that is only a name: `Սաթենիկ ջան։` → (names list) `Satenik։` → NLLB **"What is it?"**. Probe: `Satenik, Sona։` → "Satenik, Sona. What are you doing?"; `Python։` → "This is Python."
  2. A unit alone: `Կգ։` → **"What are you doing here?"**; probe: `կմ։` → "What is this?", `Տոկոս։` → "What is it?".
  3. Clock times: NLLB misreads spoken forms (`Ժամը ութն անց կես է։` → "It's after eight and a half.") but reads digits (`Ժամը 8:30 է։` → "It's 8:30."; `ժամը 8:30-ին կհանդիպենք` → "I'll see you at 8:30.").
  4. The ASR garbled "eight" in every time phrase of the test (`Ուութթն է`, `Ուսնանց երեսոուն`, `Ուութթանց կես`). Two of these were confident enough to pass `[unclear]` and became "I'm going to teach you something." and "Halfway through Watson.". **Not fixed**: this is recognition, which a text rule cannot repair.
- **Changes:**
  - `SegmentTranslator`: a segment whose words are all Latin (names or terms already replaced) is shown as is, not translated; Armenian punctuation becomes English (`Amazon՞։` → "Amazon?").
  - `phrasebook.tsv`: common units on their own (կգ, կմ, սմ, մմ, կիլոգրամ, կիլոմետր, մետր, գրամ, տոկոս, դրամ, դոլար, եվրո).
  - `textfix.times_to_digits` (with `text.numbers_to_digits`): `<hour 1–12, with the connective ն/ը> անց <կես | քառորդ | minutes in words>` → `H:MM`; an `-ին` ending on the minutes is kept (`9:15-ին`). Garbled hours and other uses of `անց` ("three days later") are left alone.
- **Replay:**
  - Mic test: `Սաթենիկ ջան։` → "Satenik."; `Կգ։` → "kg.". The garbled times stay wrong (item 4).
  - All 211 logged and eval texts: the time rule changes 1 (eval clip mic-07, `Ինն անց կես` → 9:30, correct); the Latin pass-through changes 2 (`Ամազո՞։` → "Amazon?", previously "What about Amazon?" from MT; `Վժըն քընթռոլ։` → "version control."); units 0.
  - FLEURS ASR (822 texts, held out): the time rule changes 1, correctly (`տասնմեկ անց երեսունհինգ րոպե` → 11:35; translation "…by 11:35", reference "by 11:35 pm"); pass-through and units 0.
- **Open:** `Մոտակա է։` ("it's nearby") was shown as `[unclear]` (mean −0.265, unsure share 0.167). If that is what was said, it is a false alarm, the first one seen on clear speech; the developer is asked to confirm before any threshold change.
- 211 unit tests pass.

## D-026 Glued times, `կոգ` after numbers, profanity guard, gazetteer matcher
- **Date:** 2026-10-30 · **Status:** implemented and unit-tested; the gazetteer *data* is still being built (Wikidata outage) and is checked for false matches before use.
- **From the developer's mic tests** (`runs/20261030-215355`, `-221858`, mic only):
  - **Glued times:** the ASR wrote `ութն անց` as one word (`ութնանց`, `ութանց`), so the D-025 rule did not fire ("approach halfway through the eight"). The space before `անց` is now optional; non-hour words (`կանանց`, "of women") are still left alone.
  - **`կոգ` → `կգ` after a number:** the ASR wrote the spoken abbreviation as `կոգ` in two tests ("980 coug"); `980 կգ` translates as "980 kg.". Only directly after a digit.
  - **Profanity guard:** NLLB invented vulgarities from garbled ASR ("Those are the bastards, you know.", D-019; "Be the son of a bitch.", from `Եղ որդի խճյուղին`) and from correct Armenian (FLEURS: "rumors" → "bullshit", D-027). English output matching a short list of strong vulgar words (`fuck…`, `shit/shits/shitty`, `bullshit…`, `bitch…`, `bastard(s)`, `asshole(s)`, `cunt(s)`, `whore(s)`, `slut(s)`) is shown as `[unclear]` (`unclear_reason` "mt-profanity"). Setting `mt.block_profanity` (true). Checked: it catches the 3 real cases and 0 of 826 FLEURS ASR translations and 0 of 240 eval-result translations; the surname "Shitov" was matched by a first version and the word forms were narrowed. Cost: real swearing is hidden too.
- **Gazetteer matcher (`textfix.Gazetteer`):** for a large, uncurated Wikidata list (places in Armenia, Armenian people, given names), applied after the user's `names.tsv`. Strict: exact words only; the first word capitalised; an ending allowed on the last word (`Tumanyan-ը`); a single word must not start a sentence (ordinary words are capitalised there) and must have ≥ 4 letters. Setting `text.gazetteer` (`gazetteer.tsv`; a missing file prints a warning and the run continues). Built by `eval/build_gazetteer.py` via the Wikidata Action API, because the SPARQL service was rate-limited (1 request/min, outage) and the QLever mirror returned 502.
  - **Rejected filter:** the MIT HySpell dictionary (`hy-r.dic`, 162k entries) was meant to drop names that are also ordinary words, but it lists proper nouns in lower case too (`վանաձոր`, `թումանյան`, `սաթենիկ`), so it cannot tell them apart.
- 240 unit tests pass (with D-027).

## D-027 MT ceiling on FLEURS; sentences translated separately
- **Date:** 2026-10-30 · **Status:** measured on FLEURS `hy_am` test (D-024).
- **Ceiling:** the same MT path on the **reference** Armenian (no recognition errors) scores chrF **60.8** / BLEU 35.5, against **57.6** / 30.4 from the ASR text. Recognition costs about 3 chrF points (median 1.6 per clip; 91 of 932 clips lose more than 15). **Most of the remaining quality loss is the translation model**, consistent with D-015 (own clips: 60.8 from reference vs 60.8 from ASR).
- **NLLB-600M errors on correct Armenian** (worst sentences): wrong word choices ("deface" → "distort", "maria" → "eruptions", "label" → "trademark", "rumors" → "bullshit"), invented details ("p.m.", D-025), and **dropped sentences**: with 2+ sentences in one input it often translated only the first.
- **Change:** `SegmentTranslator` splits its input at sentence ends (`։ . ? !` or the FLEURS colon, followed by a space and a capital letter) and translates each sentence through the same path (phrasebook, short-input handling, pass-through). `8:30` and "Python-ը գիտեմ. իսկ" stay whole.
- **Effect:** FLEURS references with 2+ sentences (57 of 350): chrF 57.6 → 60.6 (found on this data). FLEURS ASR output with 2+ sentences (48 of 932 clips): 58.2 → 61.8. **Own eval clips: 0 of 15** reach MT with 2+ sentences (the ASR joins them with commas), so no independent check was possible; **logged live texts: 0 of 235**. In live use the change will rarely fire: it is kept because it is cheap and only acts on multi-sentence input. Slowest split translation 1.61 s.
- **Ready-made larger model:** `OpenNMT/nllb-200-distilled-1.3B-ct2-int8` (1.38 GB, CTranslate2 maintainers; CC-BY-NC-4.0 like the 600M; same SentencePiece model as the 600M). Not downloaded yet; the next measurement is its chrF on FLEURS and its latency on this CPU.

## D-028 Translation: NLLB-200 distilled 1.3B, int8, no repeated 4-grams; gazetteer off
- **Date:** 2026-10-31 · **Status:** decided on FLEURS (held out) and a replay of the recorded test call; not yet in a live session.
- **Model:** `OpenNMT/nllb-200-distilled-1.3B-ct2-int8` (1.38 GB, ready-made CTranslate2 int8 by the CTranslate2 maintainers; CC-BY-NC-4.0 like the 600M, D-005). Its vocabulary is identical to the 600M's (256,206 tokens), so the 600M's `sentencepiece.bpe.model` is reused. Settings `mt.size` (`1.3b`/`600m`) and `mt.no_repeat_ngram`.
- **FLEURS `hy_am` test** (932 clips, D-024), same settings (int8, beam 2, 4 threads, all text fixes):

| Model | chrF / BLEU from ASR | chrF / BLEU from reference | MT time median / p95 / max (reference) |
|---|---|---|---|
| NLLB-600M | 57.6 / 30.4 | 60.8 / 35.5 | 1.09 / 2.00 / 3.45 s |
| NLLB-1.3B | 60.3 / 33.4 | 64.4 / 39.8 | 1.58 / 2.66 / **12.70 s** |
| **NLLB-1.3B, `no_repeat_ngram_size` 4** | — | **64.6 / 40.2** | 1.53 / 2.54 / 4.64 s |

  - Per sentence (from ASR): the 1.3B is better by > 5 chrF on 126 of 350, worse on 49. Gains are meaning fixes ("mosaic" → mosasaur; "16-gun ammunition" → "M16 rifle"; dropped sentences recovered); losses are mostly paraphrases ("hot climate", "home"). From the mic tests: "10:20 p.m. local time" → "10:20 in Yerevan time"; "bullshit" → "nonsense"; "My name is Lune" → "Lusine".
  - **Loops:** the 1.3B repeated "it rains so hard" 26 times on a 100-token input (12.7 s). With `no_repeat_ngram_size` 4 the same input gives a correct translation in 4.3 s; across FLEURS only 16 of 350 translations change, none by more than 5 chrF worse, and the longest repeat falls from 26 to 2. `repetition_penalty` 1.2 was faster but changed "km/h" into "miles an hour", so it was rejected.
- **Latency, replay of the recorded test call** (`runs/20261029-202643` → `runs/20261031-001255`; both sources, speaker labels, all fixes, real time): 70 segments, latency **p50 1.84 s, p95 2.76 s, max 3.31 s**, none over 5 s; MT p95 1.92 s, max 2.28 s. The same call live with the 600M: p50 1.63, p95 2.48, max 2.73 s. **6 further segments were caught by Windows standby** (one translation "took" 4,373 s; it reruns in 1.72 s; a wake event was logged): sleep/standby must be off (D-024).
- **Gazetteer (D-026) off by default:** with the 1.3B it lowers chrF on the 13 FLEURS sentences it changes (56.0 → 54.7; e.g. Cristina → "Kristina"), because the larger model already writes names well. On the logged mic tests it gave small gains ("Deseg" → "Dsegh", "Hovhannis" → "Hovhannes") and one loss ("Mashtots" → "Mashtosh"). The data and matcher stay; `text.gazetteer = "gazetteer.tsv"` turns it on.
- **Speaker labels, same replay:** 3 labels for the 2 remote people. Person B's 2.4 s `Այո, ո։` started a speaker, and her next line scored 0.33 against it (threshold 0.35). The D-020 tuning on this call had 2 labels only because the live segment boundaries differed slightly. **Labelling for B's voice sits on the threshold; the planned second test call is needed to retune with new data** (TESTS.md §Speakers).

## D-029 `<number> դրամ` → `AMD` before translation
- **Date:** 2026-10-31 · **Status:** implemented; checked on the logged texts and FLEURS.
- **Mic tests** (`runs/20261031-143816`, NLLB-1.3B): `Սուրճը կշում է 500 դրամ` → "Coffee **costs** 500 **drachmas**"; `Մեկ դրամը արժե 30 դրամ` → "One drachma is worth 30 drachmas". Probe with the 1.3B: `500 դրամ` → "drachmas", `500 dram` → "drams", `500 AMD` → "**500 AMD**"; `390 դրամ` after "dollar" → "drams".
- **Change (`textfix.units_after_numbers`):** `դրամ` directly after a digit becomes `AMD`, keeping an ending (`2000 դրամով` → `2000 AMD-ով` → "for 2,000 AMD"). On its own `դրամ` also means "money" (`Դրամ չունեմ`), so it is left alone; number words under 10 stay words (D-016), so `Մեկ դրամը` is not changed.
- **Check:** FLEURS ASR 0 of 822 texts change (its 9 sentences with `դրամ` have no digit before it); logged texts 4 change, all from the developer's currency tests.
- **Not fixed:** in three of those four the developer said **գրամ** (grams) and the ASR heard **դրամ**, so the result ("weighs 300 AMD") is still wrong. That is a recognition error (third time seen); `Սուրճը կշռում է 500 գրամ` itself translates correctly ("Coffee weighs 500 grams"). Also seen in these tests and not fixable by text rules: NLLB adds "in the morning"/"in the afternoon" to clock times and drops "Yerevan time"; rare compounds are translated literally (`Հակաչեզոքացուցիչ` → "the opposite of neutral").
- 245 unit tests pass.

## D-030 Echo detection in shadow mode (logs only)
- **Date:** 2026-10-31 · **Status:** implemented in shadow mode on branch `step8/echo-shadow`. It measures and logs; it hides nothing. Suppression needs the developer's approval after a new test call.
- **Problem:** in the 2026-10-31 test call (`runs/20261031-160647`, call played through laptop speakers), 4 of 17 `Me` lines were the call's audio picked up by the mic, and 2 of them were translated as confident invented English (`Հովհ է.` → "It's John."). The 2026-10-29 call had at most 1 such line (175.5 s, unresolved). All 4 echo segments started while a remote person was talking.
- **Study:**
  - A waveform match (GCC-PHAT) is too weak. The mic DSP (Intel Smart Sound) gates the signal to digital zero and processes it non-linearly, and a linear echo model gave a delay that jumped between 0 and 350 ms.
  - The patterns that survive this processing are three:
    - **Loudness:** mic level minus call level is −17 to +4 dB for echo, against +10 to +16 dB for the developer talking over the call.
    - **Spectrogram correlation:** 16 bands, best delay of 0 to 800 ms. Echo scores 0.30–0.51 and own speech 0.03–0.29. With the call silent the score is meaningless (about 0.3–0.47 by chance), so it only counts during call speech.
    - **Mic-only time:** mic speech while the call is silent.
- **Rule (`armtranslate/echo.py`, `[echo]` settings):** a mic segment is `echo_suspect` only if **all** of these hold:
  - at least 0.3 s of its voiced time overlaps call speech, and that is at least 50% of its voiced time;
  - mic level is no more than +5 dB above the call;
  - correlation is at least 0.3;
  - less than 0.3 s of mic speech falls while the call is silent.
  - `segments.jsonl` gets `echo_suspect` and `echo` (overlap, share, level, similarity, delay, mic-only time, wait). `summary.json` gets `echo_suspect` (count and times).
- **Pipeline:** the reader loop keeps the last 20 s of system audio. A mic segment waits until the system audio covering it has been read; live it is already there, because a segment closes 1 s after the last voiced chunk. Segments that close meanwhile queue behind it, so the order of lines is unchanged. If system audio stalls, the wait is at most 0.5 s. A failed measurement logs an error and never costs a line. The check takes 8–30 ms (1–8 s segments) on the reader thread, not the inference worker.
- **Replays in real time** (full pipeline):
  - **31 Oct call** (`runs/20261031-173855`): **3 flagged, all echo** (23.7 s `Հովհ.`, 61.0 s `Ինչ։`, 69.6 s `«ովհ է։`).
    - **2 echoes missed:** 20.3 s (`Հովհ է.` → "It's John.", only 0.08 s of overlap at the chosen delay) and 45.7 s (`Հովհ.` → "How can we do this?", correlation 0.22).
    - **Own speech flagged: none** of 13, including the overlap `Իսկ ժամ...` (+22 dB).
  - **29 Oct call** (`runs/20261031-174055`): **0 of 47 flagged**. That includes the own phrases spoken while the call talked: `Ինչո՞վ է զբաղվում` +16 dB, `Ես նույնպես այդպես եմ կարծում` +13 dB. 175.5 s `Տտեսությություն` is not flagged (no overlap); whether it was echo is unresolved.
  - **Offline replays** (Silero segmentation, not real time) flag 8.6, 23.8, 61.1 and 69.5 s in the 31 Oct call, and nothing in the 29 Oct call. These are unit tests that skip when the private recordings are absent.
- **Latency:** no segment over 5 s in either replay; queue wait unchanged (mean 0.02 s); echo wait at most 0.001 s. 29 Oct replay, back to back on the same machine:

| Replay | p50 | p95 | max | over 5 s |
|---|---|---|---|---|
| Echo on (`runs/20261031-174055`) | 2.38 s | 4.00 s | 4.50 s | 0 |
| Echo off, control (`runs/20261031-174847`) | 2.51 s | 4.99 s | 6.07 s | **4** |

  The difference comes from the machine, not the detector: translation time rose in the control run. **The control run's 4 segments over 5 s** are all forced 8 s cuts of the developer's monologue *after* the call (268–388 s), with NLLB-1.3B taking 3.4–5.1 s on long, garbled text. This problem was already there before the echo change, and it puts the 5 s requirement at risk on long monologues whenever the laptop runs slow. It should be followed up separately (for example a shorter `max_segment_s`, or a cap on the translation time). In the call itself, the 31 Oct replay had p95 2.79 s and max 3.09 s.
- **Known limits:**
  - **Quiet speech during simultaneous talking:** a soft interruption by the developer under loud call audio can look like echo. With own phrases mixed 10 dB below normal over 5 echo segments, 2 stayed under +5 dB; a unit test keeps this limit visible. **This is the reason the rule must stay log-only until a call with deliberate quiet interruptions has been checked.**
  - Short echoes and echoes with a weak spectral match are missed (2 of 5 in the 31 Oct replay). The rule leans toward missing echo rather than flagging real speech.
  - The thresholds come from 8 labelled examples on one laptop (Intel Smart Sound mic, Realtek speakers). Another mic or speaker setup may need retuning.
  - Short non-speech that the recognizer writes as `Հովհ` also appears with the call silent (0.0 s, both calls). That isn't echo and isn't caught.
  - Headphones remain the fix: with them, the rule never fires.
- **Next:** a test call with speakers on, including loud and quiet interruptions, and the same call with headphones as a control. Pass if no own phrase is flagged and at least 80% of echoes are flagged; only then consider hiding flagged lines.
