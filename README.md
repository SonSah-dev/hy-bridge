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
| audio | `use_mic`, `use_system` | `true`, `true` | which sources to capture (`--no-mic`, `--no-system`) |
| audio | `mic_device`, `system_device` | `default` | index, name substring or `default` |
| audio | `fill_gaps`, `gap_threshold_ms` | `true`, 200 | loopback sends no data while nothing plays; gaps longer than this are filled with silence |
| segmentation | `end_pause_ms`, `max_segment_s` | 1000, 8.0 | end-of-phrase pause; forced cut (placed at the quietest point of the last 1.5 s) |
| segmentation | `vad_threshold`, `pre_roll_ms`, `min_speech_ms` | 0.5, 200, 250 | Silero speech probability; audio kept before onset; shorter bursts dropped |
| asr | `threads` | 2 | FastConformer threads (D-013) |
| mt | `family`, `compute`, `size`, `no_repeat_ngram`, `beam_size`, `threads` | nllb, int8, 1.3b, 4, 2, 4 | translation model and speed (D-015, D-028) |
| text | `glossary`, `numbers_to_digits` | glossary.tsv, true | fixes applied to the Armenian text before translation (D-016) |
| text | `phrasebook`, `min_letters` | phrasebook.tsv, 2 | short replies translated directly; shorter noise segments hidden (D-017) |
| mt | `short_beam_size` | 4 | beam for 1–3 word segments not in the phrasebook (D-017) |
| speakers | `enabled`, `min_segment_s`, `new_speaker_min_s`, `similarity_threshold`, `short_threshold`, `max_remote_speakers`, `threads` | true, 1.0, 2.0, 0.35, unset (= `similarity_threshold`), 4, 2 | remote speaker labels (D-020) |
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

Armenian → English uses NLLB-200 distilled **1.3B** (**CC-BY-NC-4.0, non-commercial**) through CTranslate2 int8 on the CPU, beam 2, 4 threads, never repeating a 4-word sequence (DECISIONS.md D-015, D-028). On FLEURS it scores chrF 64.6 against 60.8 for the 600M, at about 0.3 s more end-to-end latency. Download the ready-made int8 model once, then copy the 600M's tokenizer next to it (same vocabulary):

```powershell
python -c "from huggingface_hub import snapshot_download; snapshot_download('OpenNMT/nllb-200-distilled-1.3B-ct2-int8', local_dir='models/nllb-1.3b-ct2-int8')"
copy models\nllb-600m-ct2-int8\sentencepiece.bpe.model models\nllb-1.3b-ct2-int8\
```

`--set mt.size=600m` goes back to the 600M model. The permissive alternative `Helsinki-NLP/opus-mt-hy-en` (Apache-2.0) was measured and is clearly weaker. Models are converted once from the official repos into `models/`. Conversion needs `torch` and `transformers`; running the models does not. The commands are in [eval/bench_mt.py](eval/bench_mt.py).

```powershell
python eval/bench_mt.py --family nllb --compute int8 --beam 2 --threads 4
```

On the eval set, translating the ASR output: chrF 60.8 against our references; 0.73 s median per segment. Known weak spots: years and clock times, rare names, and English terms that the ASR wrote in Armenian letters.

## Licences

> **Non-commercial use only, as configured.** The translation model, NLLB-200 distilled 1.3B (or 600M), is licensed **CC-BY-NC-4.0**, which forbids commercial use. This was a deliberate choice: it is clearly more accurate than the only permissively licensed alternative we measured (DECISIONS.md D-005, D-015). For commercial use, swap it for `Helsinki-NLP/opus-mt-hy-en` (Apache-2.0, `family="opus"` in `armtranslate/mt.py`), at lower translation quality.

No model weights are included in this repository. Each model is downloaded from its original source, and by downloading it you accept its licence.

| Component | Used for | Licence |
|---|---|---|
| [facebook/nllb-200-distilled-1.3B](https://huggingface.co/facebook/nllb-200-distilled-1.3B), int8 conversion by [OpenNMT](https://huggingface.co/OpenNMT/nllb-200-distilled-1.3B-ct2-int8) | translation (default) | CC-BY-NC-4.0 (**non-commercial**) |
| [facebook/nllb-200-distilled-600M](https://huggingface.co/facebook/nllb-200-distilled-600M) | translation (`mt.size=600m`) | CC-BY-NC-4.0 (**non-commercial**) |
| [nvidia/stt_hy_fastconformer_hybrid_large_pc](https://huggingface.co/nvidia/stt_hy_fastconformer_hybrid_large_pc), via the ONNX export [OpenVoiceOS/stt_hy_fastconformer_hybrid_large_pc_onnx](https://huggingface.co/OpenVoiceOS/stt_hy_fastconformer_hybrid_large_pc_onnx) | speech recognition | CC-BY-4.0 (attribution below) |
| [Helsinki-NLP/opus-mt-hy-en](https://huggingface.co/Helsinki-NLP/opus-mt-hy-en) | measured alternative, not the default | Apache-2.0 |
| onnx-asr, onnxruntime, CTranslate2, PyAudioWPatch | runtime | MIT |
| sentencepiece | tokenisation | Apache-2.0 |
| [Silero VAD](https://github.com/snakers4/silero-vad) | voice activity detection | MIT |

**Attribution:** Armenian speech recognition uses *stt_hy_fastconformer_hybrid_large_pc* by NVIDIA, licensed CC-BY-4.0, converted to ONNX by OpenVoiceOS. Only the runtime format was changed, not the weights. Speaker labels use the *wespeaker-voxceleb-resnet34-LM* model by WeSpeaker, licensed CC-BY-4.0 (Hugging Face `Wespeaker/wespeaker-voxceleb-resnet34-LM`), unchanged. Voice activity detection uses Silero VAD (MIT). This is not legal advice.

## Running it (microphone + system audio)

```powershell
python translate.py --list                         # capture devices
python translate.py                                # default mic + loopback of the default output; Ctrl+C to stop
python translate.py --mic "Intel" --system "Headset" --set segmentation.end_pause_ms=800
python translate.py --no-system                    # microphone only (--no-mic: call only)
python translate.py --wav eval/audio/mic-01.wav    # play a recording through the same path as the mic
python translate.py --wav a.wav --wav-system b.wav # ... and another as the call
python translate.py --record                       # also save the live audio, to replay it later
python translate.py --no-speakers                  # label all call audio "Remote"
```

Each phrase prints as `[time] Me: Armenian  →  English` for the microphone and `[time] Speaker 1: …`, `Speaker 2`, … for system audio. Remote voices are told apart by a voice embedding compared with each speaker heard so far (D-020). Phrases under `speakers.new_speaker_min_s` (2 s) never start a new speaker; if they don't clearly match a known one they show as `Speaker ?`, which is common for each person's very first short reply. Turns need a pause of about `segmentation.end_pause_ms` (1 s) between people: if the next person starts sooner, both land in one phrase under one label. Both sources share one inference worker, so phrases are translated one at a time in the order they end. **Use headphones:** with speakers the microphone also hears the call, and remote speech prints twice. The Armenian shown is the text after the glossary and number fixes, i.e. what was translated. Every run writes `runs/<timestamp>/segments.jsonl` (texts and timings per segment) and `summary.json` (latency p50/p95/max). `runs/` is git-ignored because it contains transcripts.

Needed in `models/` (see Steps 3–4 for the ASR and MT models): `silero-vad/silero_vad.onnx` from [snakers4/silero-vad](https://github.com/snakers4/silero-vad) (MIT), and the speaker model, fetched with `python eval/bench_speakers.py --download` into `models/wespeaker-resnet34-LM/`.

**Glossary:** add the names and English terms you expect in the interview to [glossary.tsv](glossary.tsv), written the way the ASR spells them in Armenian letters (check the Armenian part of the printed lines). This is the main fix for terms that would otherwise be mistranslated.

**Unclear speech:** when the speech recogniser is unsure (low mean token probability, or many unsure tokens), the line shows the Armenian with `[unclear]` instead of a translation, because the translation model turns garbled text into fluent but invented English. Settings `asr.unclear_mean_logprob` (−0.3) and `asr.unclear_low_share` (0.15); set either to `none` to switch it off. It catches the worst cases, not all of them (D-022). A translation in which a phrase repeats 3+ times in a row, at least 2 more times than in the Armenian (the model looping "well, well, well, …"), is also shown as `[unclear]`; real repetition such as `այո, այո, այո` → "yes, yes, yes" is kept. Setting `mt.repeat_min_run` (3, `none` = off) (D-023).

**Names:** add the names of everyone in the interview, and places you expect, to [names.tsv](names.tsv) with their Latin spelling (`Սաթենիկ` → `Satenik`). The translation model keeps Latin names but turns many Armenian-letter names into words ("Satan", "Lune"). Endings are kept (`Satenik-ի`), and `ջան` after a name is dropped. Names of 6+ letters also match one-letter misspellings; for shorter ones, add the variants the ASR produces as extra lines (D-021).

**Profanity:** a translation containing a strong vulgar word is shown as `[unclear]`, because the model invented obscenities from garbled speech (`mt.block_profanity`, D-026).

**Gazetteer (off by default):** `gazetteer.tsv`, built from Wikidata with `python eval/build_gazetteer.py`, gives the English spelling of places in Armenia, Armenian people and given names, matched strictly after `names.tsv` (D-026). With the 1.3B model it brought no measurable gain on FLEURS, so it is off; `--set text.gazetteer=gazetteer.tsv` turns it on (D-028).

**Echo (shadow mode, logs only):** with speakers instead of headphones the microphone hears the call, and the echo prints as `Me` lines of invented text. Each `Me` segment is compared with the call audio: how much it overlaps the call's speech, how loud it is relative to the call, how closely its spectrogram matches the call at a delay of up to 800 ms, and how much mic speech falls while the call is silent. Segments that look like echo get `"echo_suspect": true` in `segments.jsonl`, with the measurements under `echo`; `summary.json` → `echo_suspect` counts them. **Nothing is hidden:** every line still prints. Settings in `[echo]` (`echo.enabled=false` turns the measuring off) (D-030). Known limit: a soft interruption by you while the call is talking loudly can look like echo, so this stays log-only until checked on more calls. Headphones remain the fix.

**Currency:** `դրամ` right after a number is written as `AMD` before translation, because the model renders the Armenian dram as "drachmas" (D-029).

**Times and bare names:** spoken clock times (`ութն անց կես`) are turned into digits (8:30) before translation, and a line that is only names (`Satenik`) or a unit (`կգ`) is shown as is, because the model invents a question around them (D-025).

**Phrasebook:** short replies (1–3 words) are looked up in [phrasebook.tsv](phrasebook.tsv) before translation, because the translation model often invents sentences for very short inputs. A greeting followed by a name keeps the name in Latin letters (`Ողջույն Սոնա ջան` → "Hello, Sona."). Add the short replies you expect.

**Power:** keep the laptop plugged in, and turn off sleep and Modern Standby for the session: one translation took 49 s instead of about 1 s while Windows entered standby (D-024). On battery, speech recognition and translation ran about twice as slowly (D-017).
