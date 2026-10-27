# Armenian live transcription and translation

Python command-line tool that captures microphone and system audio on Windows, transcribes Armenian speech, translates it into English, and labels speakers (`Me`, `Speaker 1`, `Speaker 2`, …). All models run locally.

**Status:** in development. See PLAN.md, DECISIONS.md and TESTS.md.

Setup, model rationale, architecture and limitations will be documented here as each part is verified.

## Audio capture and configuration

Capture uses only standard Windows audio (DECISIONS.md D-011): a WASAPI **microphone** (labelled `Me`) and the WASAPI **loopback of an output device** (`system`: whatever any app plays there). Nothing depends on a particular call app, headset or virtual cable.

```powershell
python spikes/audio_capture_spike.py --list                         # devices, with indices
python spikes/audio_capture_spike.py --mic 9 --system "Headset"     # index or part of the name
python spikes/audio_capture_spike.py --config config.toml --set speakers.min_segment_s=1.5
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

## Speech recognition (Step 3)

Armenian ASR uses NVIDIA's FastConformer (CC-BY-4.0) through its ONNX export [`OpenVoiceOS/stt_hy_fastconformer_hybrid_large_pc_onnx`](https://huggingface.co/OpenVoiceOS/stt_hy_fastconformer_hybrid_large_pc_onnx) and `onnx-asr` (MIT) on the CPU, fp32, 2 threads (DECISIONS.md D-013). The model (≈ 460 MB) is downloaded once into `models/`, which is git-ignored.

```powershell
pip install -r requirements.txt
python eval/bench_asr.py --download                    # fetch the model
python eval/bench_asr.py --quant fp32 --threads 2      # CER and speed on the eval set
```

On the eval set: 8.2% CER overall, 2.9% on clips without English terms; 0.04× real time (an 18.5 s clip in 0.7 s). English terms come out in Armenian letters (`Python` → `փայթեն`).

## Translation (Step 4)

Armenian → English uses NLLB-200 distilled 600M (**CC-BY-NC-4.0, non-commercial**) through CTranslate2 int8 on the CPU, beam 2, 4 threads (DECISIONS.md D-015). The permissive alternative `Helsinki-NLP/opus-mt-hy-en` (Apache-2.0) was measured and is clearly weaker. Models are converted once from the official repos into `models/`. Conversion needs `torch` and `transformers`; running the models does not. The commands are in [eval/bench_mt.py](eval/bench_mt.py).

```powershell
python eval/bench_mt.py --family nllb --compute int8 --beam 2 --threads 4
```

On the eval set, translating the ASR output: chrF 60.8 against our references; 0.73 s median per segment. Known weak spots: years and clock times, rare names, and English terms that the ASR wrote in Armenian letters.

## Licences

> **Non-commercial use only, as configured.** The translation model, NLLB-200 distilled 600M, is licensed **CC-BY-NC-4.0**, which forbids commercial use. This was a deliberate choice: it is clearly more accurate than the only permissively licensed alternative we measured (DECISIONS.md D-005, D-015). For commercial use, swap it for `Helsinki-NLP/opus-mt-hy-en` (Apache-2.0, `family="opus"` in `armtranslate/mt.py`), at lower translation quality.

No model weights are included in this repository. Each model is downloaded from its original source, and by downloading it you accept its licence.

| Component | Used for | Licence |
|---|---|---|
| [facebook/nllb-200-distilled-600M](https://huggingface.co/facebook/nllb-200-distilled-600M) | translation | CC-BY-NC-4.0 (**non-commercial**) |
| [nvidia/stt_hy_fastconformer_hybrid_large_pc](https://huggingface.co/nvidia/stt_hy_fastconformer_hybrid_large_pc), via the ONNX export [OpenVoiceOS/stt_hy_fastconformer_hybrid_large_pc_onnx](https://huggingface.co/OpenVoiceOS/stt_hy_fastconformer_hybrid_large_pc_onnx) | speech recognition | CC-BY-4.0 (attribution below) |
| [Helsinki-NLP/opus-mt-hy-en](https://huggingface.co/Helsinki-NLP/opus-mt-hy-en) | measured alternative, not the default | Apache-2.0 |
| onnx-asr, onnxruntime, CTranslate2, PyAudioWPatch | runtime | MIT |
| sentencepiece | tokenisation | Apache-2.0 |

**Attribution:** Armenian speech recognition uses *stt_hy_fastconformer_hybrid_large_pc* by NVIDIA, licensed CC-BY-4.0, converted to ONNX by OpenVoiceOS. Only the runtime format was changed, not the weights. Licences of components added in later steps (voice activity detection, speaker embeddings) are listed here as they are added. This is not legal advice.
