"""Armenian live transcription and translation (Step 6: microphone + system audio).

    python translate.py --list                          # capture devices
    python translate.py                                 # default mic + loopback of default output; Ctrl+C
    python translate.py --mic "Intel" --system "Headset" --config config.toml
    python translate.py --no-system                     # microphone only
    python translate.py --wav eval/audio/mic-01.wav     # recordings instead of live capture:
    python translate.py --wav a.wav --wav-system b.wav  #   --wav plays as the mic, --wav-system as the call

Prints one line per phrase: time, speaker (Me / Remote), Armenian, English. Each run writes
runs/<timestamp>/segments.jsonl (timings and texts per segment) and summary.json
(latency p50/p95/max). See README for models and settings.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from armtranslate import audio  # noqa: E402
from armtranslate.config import load_config, parse_device  # noqa: E402
from armtranslate.pipeline import LABELS, FileSource, Worker, latency_summary, run  # noqa: E402
from armtranslate.vad import Segmenter, SileroVad  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", "--list-devices", action="store_true", help="list capture devices and exit")
    ap.add_argument("--mic", help="microphone: index or name substring (default: Windows default input)")
    ap.add_argument("--system", help="system audio: index or name substring of a loopback/output device "
                    "(default: loopback of the Windows default output)")
    ap.add_argument("--no-mic", action="store_true", help="do not capture the microphone")
    ap.add_argument("--no-system", action="store_true", help="do not capture system audio")
    ap.add_argument("--config", help="TOML settings file (see config.example.toml)")
    ap.add_argument("--set", action="append", default=[], metavar="SECTION.KEY=VALUE")
    ap.add_argument("--wav", nargs="+", help="16 kHz mono WAV file(s) played as the microphone, in real time")
    ap.add_argument("--wav-system", nargs="+", help="16 kHz mono WAV file(s) played as system audio")
    ap.add_argument("--gap-s", type=float, default=1.5, help="silence after each WAV file")
    ap.add_argument("--runs", default=str(ROOT / "runs"), help="folder for run logs")
    ap.add_argument("--seconds", type=float, help="stop by itself after this many seconds (scripted tests)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.list:
        p = audio.pyaudio.PyAudio()
        try:
            print(audio.device_table(p))
        finally:
            p.terminate()
        return 0

    cfg = load_config(args.config, args.set)
    a = cfg.audio
    if args.mic is not None:
        a = replace(a, mic_device=parse_device(args.mic))
    if args.system is not None:
        a = replace(a, system_device=parse_device(args.system))
    if args.no_mic:
        a = replace(a, use_mic=False)
    if args.no_system:
        a = replace(a, use_system=False)
    cfg = replace(cfg, audio=a)
    if args.wav or args.wav_system:          # playback: only the given files, no live capture
        wavs = {k: v for k, v in (("mic", args.wav), ("system", args.wav_system)) if v}
    else:
        wavs = {}
        if not (a.use_mic or a.use_system):
            raise SystemExit("nothing to capture: both the microphone and system audio are switched off")

    from armtranslate.asr import Recognizer
    from armtranslate.mt import SegmentTranslator, Translator
    from armtranslate.phrasebook import Phrasebook
    from armtranslate.textfix import TextFixer

    print("loading models ...", file=sys.stderr)
    asr = Recognizer(threads=cfg.asr.threads)
    mt = Translator(cfg.mt.family, cfg.mt.compute, threads=cfg.mt.threads, beam_size=cfg.mt.beam_size)
    glossary = (ROOT / cfg.text.glossary) if cfg.text.glossary else None
    fixer = TextFixer(glossary, cfg.text.numbers_to_digits)
    phrasebook = Phrasebook(ROOT / cfg.text.phrasebook) if cfg.text.phrasebook else None
    translate = SegmentTranslator(mt, phrasebook, cfg.mt.short_beam_size)
    asr.transcribe(np.zeros(16_000, np.float32))      # warm-up, so the first phrase is not slower
    mt.translate("Բարեւ")

    run_dir = Path(args.runs) / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    log = open(run_dir / "segments.jsonl", "w", encoding="utf-8", newline="\n")
    worker = Worker(asr.transcribe, translate, fixer, log=log, min_letters=cfg.text.min_letters)

    p = None
    sources, inputs = {}, {}
    try:
        if wavs:
            for name, files in wavs.items():
                sources[name] = _concat_wavs(files, args.gap_s, run_dir, name)
                inputs[name] = [str(w) for w in files]
        else:
            p = audio.pyaudio.PyAudio()
            for name in [n for n, on in (("mic", a.use_mic), ("system", a.use_system)) if on]:
                dev = audio.select_device(p, cfg.audio, name)
                sources[name] = audio.WasapiSource(p, dev, name, cfg.audio)
                inputs[name] = dev["name"]
        segmenters = {name: Segmenter(name, SileroVad(), cfg.segmentation) for name in sources}
        for name, what in inputs.items():
            print(f"{LABELS[name]:>6} <- {name}: {what}", file=sys.stderr)
        print("listening  (Ctrl+C to stop)", file=sys.stderr)
        stop = threading.Event()
        if args.seconds:
            threading.Timer(args.seconds, stop.set).start()
        run(sources, segmenters, worker, stop)
    finally:
        log.close()
        if p is not None:
            p.terminate()

    summary = {"inputs": inputs, "config": cfg.to_dict(), **latency_summary(worker.results),
               "by_source": {n: latency_summary([r for r in worker.results if r.source == n]) for n in sources},
               "dropped_short": {n: s.dropped_short for n, s in segmenters.items()},
               "skipped_no_text": worker.skipped,
               "source_stats": {n: s.stats() for n, s in sources.items()}}
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    keys = ("segments", "latency_p50_s", "latency_p95_s", "latency_max_s", "over_5s")
    print("\n" + "  ".join(f"{k}={summary.get(k)}" for k in keys), file=sys.stderr)
    print(f"log: {run_dir}", file=sys.stderr)
    return 0


def _concat_wavs(paths: list[str], gap_s: float, run_dir: Path, name: str) -> FileSource:
    """Join several WAVs with silence between them into one real-time source."""
    from armtranslate.evalset import read_wav, write_wav
    parts = []
    for path in paths:
        y, rate, ch = read_wav(Path(path))
        if rate != 16_000 or ch != 1:
            raise SystemExit(f"{path}: expected 16 kHz mono")
        parts += [y, np.zeros(int(gap_s * 16_000), np.float32)]
    joined = run_dir / f"input-{name}.wav"
    write_wav(joined, np.concatenate(parts))
    return FileSource(joined, name)


if __name__ == "__main__":
    raise SystemExit(main())
