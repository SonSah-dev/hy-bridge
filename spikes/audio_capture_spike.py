"""Step 1 spike: record microphone + WASAPI loopback (system audio) at the same time.

Windows only. Exercises the real capture layer (armtranslate/audio.py) so Step 1 tests the
code the pipeline will use. Devices and assumptions come from armtranslate/config.py
defaults, an optional TOML file and command-line overrides (DECISIONS.md D-010, D-011).

    python audio_capture_spike.py --list
    python audio_capture_spike.py --seconds 30 [--mic IDX|NAME] [--system IDX|NAME]
                                  [--config FILE] [--set section.key=value ...] [--tag NAME]

Writes, per run, into OUT/run-YYYYmmdd-HHMMSS[-TAG]/:
    mic_native.wav, system_native.wav   raw callback data at each device's native format
    mic_16k.wav,    system_16k.wav      capture-layer output (16 kHz mono, gaps filled)
    report.json,    report.txt          settings, measurements and automatic checks
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import threading
import time
import wave
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from armtranslate import audio  # noqa: E402
from armtranslate.config import load_config, parse_device  # noqa: E402

DURATION_TOLERANCE_S = 0.2
CLIP_LEVEL = 32767


# ----------------------------------------------------------------- analysis (pure, testable)

def dbfs(v: float) -> float:
    return float(20 * np.log10(v)) if v > 0 else float("-inf")


def analyse_native(raw: bytes, channels: int) -> dict:
    a = np.frombuffer(raw, dtype=np.int16)
    flat = a.astype(np.float32) / 32768.0
    clipped = int(np.count_nonzero(np.abs(a.astype(np.int32)) >= CLIP_LEVEL))
    rms = float(np.sqrt(np.mean(flat ** 2))) if flat.size else 0.0
    peak = float(np.abs(flat).max()) if flat.size else 0.0
    return {
        "rms_dbfs": round(dbfs(rms), 1),
        "peak_dbfs": round(dbfs(peak), 1),
        "clipped_fraction": round(clipped / max(a.size, 1), 6),
    }


def checks(name: str, pipeline_s: float, requested_s: float, st: dict, lv: dict) -> dict:
    """Automatic parts of TESTS.md Step 1. Listening checks stay manual."""
    c = {
        "duration_within_0.2s": abs(pipeline_s - requested_s) <= DURATION_TOLERANCE_S,
        "16k_length_consistent": abs(pipeline_s - (st["native_s"] + st["gap_filled_s"])) <= 0.05,
        "zero_overflows": st["overflows"] == 0,
        "zero_dropped_chunks": st["dropped_chunks"] == 0,
        "signal_present(rms>-50dBFS)": lv["rms_dbfs"] > -50,
        "no_clipping(<0.1%)": lv["clipped_fraction"] < 0.001,
    }
    if name == "mic":  # a microphone streams continuously; gaps there mean lost audio
        c["mic_no_gaps_filled"] = st["gaps_filled"] == 0
    return c


def write_wav(path: Path, pcm16: bytes, rate: int, channels: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm16)


def float_to_pcm16(x: np.ndarray) -> bytes:
    return (np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()


# ----------------------------------------------------------------- run

def record(args, cfg) -> int:
    pyaudio = audio.pyaudio
    name = datetime.now().strftime("run-%Y%m%d-%H%M%S") + (f"-{args.tag}" if args.tag else "")
    out = Path(args.out) / name
    out.mkdir(parents=True, exist_ok=False)

    raw: dict[str, list[bytes]] = {s: [] for s in audio.SOURCES}
    raw_lock = threading.Lock()

    def sink(src):
        def put(b: bytes) -> None:
            with raw_lock:
                raw[src].append(b)
        return put

    p = pyaudio.PyAudio()
    try:
        try:
            sources = audio.open_sources(p, cfg.audio, {s: sink(s) for s in audio.SOURCES})
        except audio.DeviceError as e:
            sys.exit(f"Device selection failed: {e}\nRun with --list to see devices.")
        for s in sources.values():
            print(f"{s.name:<6}: [{s.device['index']}] {s.device['name']} "
                  f"({s.native_rate} Hz, {s.channels} ch)")
        print(f"Recording {args.seconds:.0f} s. Keep audio PLAYING and SPEAK into the mic.\n")

        frames: dict[str, list[audio.AudioFrame]] = {s: [] for s in sources}
        for s in sources.values():
            s.start()
        t0 = time.perf_counter()
        while (elapsed := time.perf_counter() - t0) < args.seconds:
            for s in sources.values():
                while (f := s.read(timeout=0)) is not None:
                    frames[s.name].append(f)
            levels = "  ".join(f"{s.name} {dbfs(s.stats()['last_rms']):6.1f} dBFS"
                               for s in sources.values())
            print(f"\r  {elapsed:5.1f}s  {levels}   ", end="", flush=True)
            time.sleep(0.05)
        for s in sources.values():
            while (f := s.read(timeout=0)) is not None:
                frames[s.name].append(f)
        wall = time.perf_counter() - t0
        for s in sources.values():
            s.stop()
        print("\n")

        report = {
            "created": datetime.now().isoformat(timespec="seconds"),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "pyaudiowpatch": getattr(pyaudio, "__version__", "unknown"),
            "portaudio": pyaudio.get_portaudio_version_text(),
            "config": cfg.to_dict(),
            "requested_s": args.seconds,
            "wall_clock_s": round(wall, 3),
            "streams": {},
        }
        starts = {}
        all_ok = True
        for nm, s in sources.items():
            st = s.stats()
            with raw_lock:
                native = b"".join(raw[nm])
            y = np.concatenate([f.samples for f in frames[nm]]) if frames[nm] else np.zeros(0, np.float32)
            pipeline_s = len(y) / cfg.audio.sample_rate
            lv = analyse_native(native, s.channels)
            write_wav(out / f"{nm}_native.wav", native, s.native_rate, s.channels)
            write_wav(out / f"{nm}_16k.wav", float_to_pcm16(y), cfg.audio.sample_rate, 1)
            c = checks(nm, pipeline_s, args.seconds, st, lv)
            all_ok &= all(c.values())
            starts[nm] = frames[nm][0].t_start if frames[nm] else None
            report["streams"][nm] = {
                "device_index": int(s.device["index"]),
                "device_name": s.device["name"],
                "pipeline_s": round(pipeline_s, 3),
                "frames": len(frames[nm]),
                **{k: v for k, v in st.items() if k != "last_rms"},
                **lv,
                "checks": c,
            }
        if all(v is not None for v in starts.values()):
            report["start_skew_ms(system-mic)"] = round((starts["system"] - starts["mic"]) * 1000, 1)
        report["automatic_checks_passed"] = all_ok
    finally:
        p.terminate()

    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    sc = cfg.scenario
    lines = [f"Run folder: {out.resolve()}",
             f"Python {report['python']} | {report['platform']} | PyAudioWPatch {report['pyaudiowpatch']}",
             f"Scenario: {sc.remote_participants} remote, separate_devices={sc.separate_devices}, "
             f"call_app={sc.call_app}, output={sc.output_setup}",
             f"Requested {args.seconds} s, wall clock {report['wall_clock_s']} s, "
             f"start skew system-mic {report.get('start_skew_ms(system-mic)', 'n/a')} ms", ""]
    for nm, s in report["streams"].items():
        lines.append(f"[{nm}] {s['device_name']} ({s['native_rate']} Hz, {s['native_channels']} ch)")
        lines.append(f"   pipeline {s['pipeline_s']} s = native {s['native_s']} s + filled gaps "
                     f"{s['gap_filled_s']} s (leading {s['leading_fill_s']} s + {s['gaps_filled']} gaps), "
                     f"resyncs {s['clock_resyncs']}")
        lines.append(f"   overflows {s['overflows']}, dropped {s['dropped_chunks']}, rms {s['rms_dbfs']} dBFS, "
                     f"peak {s['peak_dbfs']} dBFS, clipped {s['clipped_fraction']:.4%}, "
                     f"max callback gap {s['max_callback_gap_ms']} ms")
        for check, ok in s["checks"].items():
            lines.append(f"   {'PASS' if ok else 'FAIL'}  {check}")
    lines += ["", f"AUTOMATIC CHECKS: {'ALL PASS' if report['automatic_checks_passed'] else 'SOME FAILED'}",
              "MANUAL CHECKS: listen to mic_16k.wav (your voice) and system_16k.wav (played audio);",
              "               confirm you heard the played audio normally during recording."]
    text = "\n".join(lines)
    (out / "report.txt").write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["automatic_checks_passed"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", "--list-devices", action="store_true", help="list capture devices and exit")
    ap.add_argument("--mic", help="microphone: index or name substring (default: Windows default input)")
    ap.add_argument("--system", "--loop", dest="system",
                    help="system audio: loopback index or name substring (default: default output)")
    ap.add_argument("--config", help="TOML settings file (see config.example.toml)")
    ap.add_argument("--set", action="append", default=[], metavar="SECTION.KEY=VALUE",
                    help="override one setting; repeatable")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--tag", help="suffix for the run folder, e.g. s1-turns")
    ap.add_argument("--out", default="spike_runs")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")  # device names may not fit the console code page
    if audio.pyaudio is None:
        sys.exit("PyAudioWPatch is not installed (Windows only): pip install -r requirements-spike.txt")
    if args.list:
        p = audio.pyaudio.PyAudio()
        try:
            print(audio.device_table(p))
        finally:
            p.terminate()
        return 0
    try:
        cfg = load_config(args.config, args.set)
    except (OSError, ValueError) as e:
        sys.exit(f"Configuration error: {e}")
    if args.mic is not None:
        cfg = replace(cfg, audio=replace(cfg.audio, mic_device=parse_device(args.mic)))
    if args.system is not None:
        cfg = replace(cfg, audio=replace(cfg.audio, system_device=parse_device(args.system)))
    return record(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
