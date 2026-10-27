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
- **Still to verify:** Silero VAD's licence at its source (Step 5).
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
| End-of-phrase pause | 600 ms | trades latency against sentence completeness; tuned in Step 8 |
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
