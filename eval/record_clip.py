"""Step 2: record one evaluation clip and add it to eval/manifest.jsonl (DECISIONS.md D-012).

    python eval/record_clip.py --prompt p01          # next free id (mic-01, mic-02, ...)
    python eval/record_clip.py --id mic-04 --force   # re-record a clip, keeping its texts
    python eval/record_clip.py --source system --speaker remote-A   # Step 7 call clips

Press Enter to start, speak, press Enter to stop. Leading and trailing silence is trimmed
(0.25 s padding kept) and the clip is saved as 16 kHz mono WAV in eval/audio/. Afterwards,
type what you actually said into the row's "hy" field and an English translation into "en".
Devices and settings come from the same config as the capture layer (--config, --set, --mic).
"""
from __future__ import annotations

import argparse
import re
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from armtranslate import audio  # noqa: E402
from armtranslate.config import load_config, parse_device  # noqa: E402
from armtranslate.evalset import (RATE, Clip, load_manifest, next_id, save_manifest,  # noqa: E402
                                  speech_bounds, upsert, write_wav)

HERE = Path(__file__).resolve().parent


def load_prompts(path: Path) -> dict[str, str]:
    """Rows of the form `| p01 | ... | prompt text |` in eval/prompts.md -> {id: text}."""
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells and re.fullmatch(r"p\d{2}", cells[0]):
            out[cells[0]] = cells[-1]
    return out


def capture(src, max_s: float, fixed_s: float | None) -> list[np.ndarray]:
    chunks: list[np.ndarray] = []
    stop = threading.Event()

    def reader():
        t0 = time.perf_counter()
        while not stop.is_set():
            f = src.read(timeout=0.05)
            if f is not None:
                chunks.append(f.samples)
            if time.perf_counter() - t0 >= max_s:
                if not stop.is_set():
                    print(f"\n  reached --max-seconds {max_s:.0f}; press Enter", flush=True)
                stop.set()

    src.start()
    t = threading.Thread(target=reader, daemon=True)
    t.start()
    if fixed_s is not None:
        time.sleep(fixed_s)
    else:
        input("  recording... press Enter to stop ")
    stop.set()
    t.join()
    src.stop()
    return chunks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id", help="clip id, e.g. mic-03 (default: next free id)")
    ap.add_argument("--prompt", default="", help="prompt id from eval/prompts.md, e.g. p03")
    ap.add_argument("--source", choices=audio.SOURCES, default="mic")
    ap.add_argument("--speaker", help='speaker label (default "me" for the mic)')
    ap.add_argument("--notes", default="")
    ap.add_argument("--force", action="store_true", help="overwrite an existing clip's audio")
    ap.add_argument("--no-trim", action="store_true", help="keep leading/trailing silence")
    ap.add_argument("--max-seconds", type=float, default=20.0)
    ap.add_argument("--seconds", type=float, help="record a fixed time without key presses")
    ap.add_argument("--manifest", default=str(HERE / "manifest.jsonl"))
    ap.add_argument("--audio-dir", help="default: audio/ next to the manifest")
    ap.add_argument("--mic", help="microphone: index or name substring")
    ap.add_argument("--system", help="system audio: loopback index or name substring")
    ap.add_argument("--config", help="TOML settings file (see config.example.toml)")
    ap.add_argument("--set", action="append", default=[], metavar="SECTION.KEY=VALUE")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")

    if audio.pyaudio is None:
        sys.exit("PyAudioWPatch is not installed (Windows only): pip install -r requirements.txt")
    try:
        cfg = load_config(args.config, args.set)
    except (OSError, ValueError) as e:
        sys.exit(f"Configuration error: {e}")
    if args.mic is not None:
        cfg = replace(cfg, audio=replace(cfg.audio, mic_device=parse_device(args.mic)))
    if args.system is not None:
        cfg = replace(cfg, audio=replace(cfg.audio, system_device=parse_device(args.system)))

    manifest = Path(args.manifest).resolve()
    audio_dir = Path(args.audio_dir).resolve() if args.audio_dir else manifest.parent / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    clips = load_manifest(manifest)
    clip_id = args.id or next_id(clips, args.source)
    expected = "mic-" if args.source == "mic" else "call-"
    if not clip_id.startswith(expected):
        sys.exit(f"{args.source} clips use ids starting with {expected!r}, got {clip_id!r}")
    wav = audio_dir / f"{clip_id}.wav"
    if wav.exists() and not args.force:
        sys.exit(f"{wav} already exists. Use --force to re-record it (texts are kept).")
    speaker = args.speaker or ("me" if args.source == "mic" else "")
    if not speaker:
        sys.exit("--speaker is required for system-audio clips, e.g. --speaker remote-A")

    prompts = load_prompts(HERE / "prompts.md")
    if args.prompt and args.prompt not in prompts:
        sys.exit(f"unknown prompt {args.prompt!r}; see eval/prompts.md")

    p = audio.pyaudio.PyAudio()
    try:
        try:
            dev = audio.select_device(p, cfg.audio, args.source)
        except audio.DeviceError as e:
            sys.exit(f"Device selection failed: {e}")
        src = audio.WasapiSource(p, dev, args.source, cfg.audio)
        print(f"{clip_id} <- [{dev['index']}] {dev['name']}")
        if args.prompt:
            print(f"Prompt {args.prompt}: {prompts[args.prompt]}")
            print("Answer in Armenian, in your own words.")
        if args.seconds is None:
            input("Press Enter to start recording ")
        chunks = capture(src, args.max_seconds, args.seconds)
        stats = src.stats()
    finally:
        p.terminate()

    y = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
    raw_s = len(y) / RATE
    if stats["overflows"] or stats["dropped_chunks"]:
        print(f"WARNING: {stats['overflows']} overflows, {stats['dropped_chunks']} dropped chunks")
    if not args.no_trim:
        bounds = speech_bounds(y)
        if bounds is None:
            sys.exit(f"No speech detected in {raw_s:.1f} s of audio; nothing saved. Is the mic muted?")
        y = y[bounds[0]:bounds[1]]
    write_wav(wav, y)
    duration = round(len(y) / RATE, 3)
    peak = 20 * np.log10(np.abs(y).max() + 1e-12) if y.size else float("-inf")

    rel = wav.relative_to(manifest.parent).as_posix() if wav.is_relative_to(manifest.parent) else str(wav)
    clip = Clip(id=clip_id, audio=rel, source=args.source, speaker=speaker, duration_s=duration,
                prompt=args.prompt, notes=args.notes,
                recorded=datetime.now().isoformat(timespec="seconds"))
    save_manifest(manifest, upsert(clips, clip))
    row = next(c for c in load_manifest(manifest) if c.id == clip_id)
    print(f"Saved {wav.name}: {duration:.2f} s (recorded {raw_s:.2f} s), peak {peak:.1f} dBFS")
    if not row.hy or not row.en:
        print(f'Next: in {manifest.name}, fill "hy" (exactly what you said) and "en" for {clip_id}.')
    return 0


if __name__ == "__main__":
    sys.exit(main())
