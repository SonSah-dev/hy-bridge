"""Step 1 spike: record microphone + WASAPI loopback (system audio) at the same time.

Windows only. Throwaway experiment, not application code.

    python audio_capture_spike.py --list
    python audio_capture_spike.py --seconds 30 [--mic INDEX] [--loop INDEX] [--out DIR]

Writes, per run, into DIR/run-YYYYmmdd-HHMMSS/:
    mic_native.wav, loop_native.wav   raw capture at each device's native format
    mic_16k.wav,    loop_16k.wav      resampled to 16 kHz mono (pipeline format)
    report.json,    report.txt        measurements + automatic checks
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import threading
import time
import wave
from datetime import datetime
from math import gcd
from pathlib import Path

import numpy as np

try:
    import pyaudiowpatch as pyaudio
except ImportError:  # allows importing the analysis helpers on non-Windows machines
    pyaudio = None

TARGET_RATE = 16_000
DURATION_TOLERANCE_S = 0.2
CLIP_LEVEL = 32767


# ----------------------------------------------------------------- analysis (pure, testable)

def bytes_to_array(raw: bytes, channels: int) -> np.ndarray:
    """int16 interleaved bytes -> array of shape (frames, channels)."""
    a = np.frombuffer(raw, dtype=np.int16)
    usable = len(a) - (len(a) % channels)
    return a[:usable].reshape(-1, channels)


def to_mono_16k(x: np.ndarray, rate: int) -> np.ndarray:
    """(frames, channels) int16 -> mono float32 at 16 kHz in [-1, 1]."""
    from scipy.signal import resample_poly

    mono = x.astype(np.float32).mean(axis=1) / 32768.0
    if rate == TARGET_RATE:
        return mono
    g = gcd(rate, TARGET_RATE)
    return resample_poly(mono, TARGET_RATE // g, rate // g).astype(np.float32)


def dbfs(v: float) -> float:
    return float(20 * np.log10(v)) if v > 0 else float("-inf")


def analyse(x: np.ndarray, rate: int, callback_times: list[float], requested_s: float) -> dict:
    frames = int(x.shape[0])
    duration = frames / rate if rate else 0.0
    flat = x.astype(np.float32).ravel()
    peak = float(np.abs(flat).max()) / 32768.0 if flat.size else 0.0
    rms = float(np.sqrt(np.mean((flat / 32768.0) ** 2))) if flat.size else 0.0
    clipped = int(np.count_nonzero(np.abs(x.astype(np.int32)) >= CLIP_LEVEL))
    gaps = np.diff(callback_times) if len(callback_times) > 1 else np.array([0.0])
    return {
        "frames": frames,
        "duration_s": round(duration, 3),
        "duration_error_s": round(duration - requested_s, 3),
        "peak_dbfs": round(dbfs(peak), 1),
        "rms_dbfs": round(dbfs(rms), 1),
        "clipped_samples": clipped,
        "clipped_fraction": round(clipped / max(flat.size, 1), 6),
        "callbacks": len(callback_times),
        "max_callback_gap_ms": round(float(gaps.max()) * 1000, 1),
    }


def checks(stats: dict, overflows: int, resampled_len_s: float) -> dict:
    """Automatic parts of the agreed success criterion. Listening checks stay manual."""
    return {
        "duration_within_0.2s": abs(stats["duration_error_s"]) <= DURATION_TOLERANCE_S,
        "resampled_16k_ok": abs(resampled_len_s - stats["duration_s"]) <= 0.05,
        "zero_overflows": overflows == 0,
        "signal_present(rms>-50dBFS)": stats["rms_dbfs"] > -50,
        "no_clipping(<0.1%)": stats["clipped_fraction"] < 0.001,
    }


def write_wav(path: Path, data: np.ndarray, rate: int, channels: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.astype(np.int16).tobytes())


# ----------------------------------------------------------------- capture (Windows)

class Recorder:
    def __init__(self, p, dev: dict, label: str):
        self.dev, self.label = dev, label
        self.channels = int(dev["maxInputChannels"])
        self.rate = int(dev["defaultSampleRate"])
        self.chunks: list[bytes] = []
        self.callback_times: list[float] = []
        self.overflows = 0
        self.last_rms = 0.0
        self.lock = threading.Lock()
        self.stream = p.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.rate,
            input=True,
            input_device_index=int(dev["index"]),
            frames_per_buffer=int(self.rate * 0.02),
            stream_callback=self._callback,
            start=False,
        )

    def _callback(self, in_data, frame_count, time_info, status):
        if status & pyaudio.paInputOverflow:
            self.overflows += 1
        a = np.frombuffer(in_data, dtype=np.int16)
        with self.lock:
            self.chunks.append(in_data)
            self.callback_times.append(time.perf_counter())
            self.last_rms = float(np.sqrt(np.mean((a / 32768.0) ** 2))) if a.size else 0.0
        return (None, pyaudio.paContinue)

    def close(self) -> None:
        self.stream.stop_stream()
        self.stream.close()

    def data(self) -> np.ndarray:
        with self.lock:
            return bytes_to_array(b"".join(self.chunks), self.channels)


def host_api_name(p, dev: dict) -> str:
    return p.get_host_api_info_by_index(dev["hostApi"])["name"]


def list_devices(p) -> None:
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    try:
        default_loop = p.get_default_wasapi_loopback()["index"]
    except Exception:
        default_loop = None
    print(f"{'idx':>4}  {'host API':<22} {'in':>3} {'out':>3} {'rate':>7}  flags  name")
    for d in p.get_device_info_generator():
        if d["maxInputChannels"] < 1:
            continue  # only capture-capable devices (loopbacks appear as inputs)
        flags = ""
        if d.get("isLoopbackDevice"):
            flags += "L"
        if d["index"] == wasapi["defaultInputDevice"]:
            flags += "M*"
        if d["index"] == default_loop:
            flags += "L*"
        print(f"{d['index']:>4}  {host_api_name(p, d):<22} {d['maxInputChannels']:>3} "
              f"{d['maxOutputChannels']:>3} {int(d['defaultSampleRate']):>7}  {flags:<5}  {d['name']}")
    print("\nL = WASAPI loopback (system audio)   M* = default WASAPI mic   L* = default loopback")
    print("Prefer WASAPI devices for both --mic and --loop.")


def pick_devices(p, mic_idx: int | None, loop_idx: int | None) -> tuple[dict, dict]:
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    mic = p.get_device_info_by_index(mic_idx if mic_idx is not None else wasapi["defaultInputDevice"])
    if loop_idx is not None:
        loop = p.get_device_info_by_index(loop_idx)
    else:
        loop = p.get_default_wasapi_loopback()
    if not loop.get("isLoopbackDevice"):
        sys.exit(f"Device {loop['index']} is not a WASAPI loopback device. Run --list.")
    if mic.get("isLoopbackDevice"):
        sys.exit(f"Device {mic['index']} is a loopback device, not a microphone. Run --list.")
    return mic, loop


def record(args) -> int:
    out = Path(args.out) / datetime.now().strftime("run-%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=False)
    p = pyaudio.PyAudio()
    try:
        mic_dev, loop_dev = pick_devices(p, args.mic, args.loop)
        recs = [Recorder(p, mic_dev, "mic"), Recorder(p, loop_dev, "loop")]
        print(f"mic : [{mic_dev['index']}] {mic_dev['name']} ({host_api_name(p, mic_dev)}, "
              f"{recs[0].rate} Hz, {recs[0].channels} ch)")
        print(f"loop: [{loop_dev['index']}] {loop_dev['name']} ({recs[1].rate} Hz, {recs[1].channels} ch)")
        print(f"Recording {args.seconds:.0f} s. Keep audio PLAYING and SPEAK into the mic.\n")
        for r in recs:
            r.stream.start_stream()
        t0 = time.perf_counter()
        while (elapsed := time.perf_counter() - t0) < args.seconds:
            levels = "  ".join(f"{r.label} {dbfs(r.last_rms):6.1f} dBFS" for r in recs)
            print(f"\r  {elapsed:5.1f}s  {levels}   ", end="", flush=True)
            time.sleep(0.25)
        wall = time.perf_counter() - t0
        for r in recs:
            r.close()
        print("\n")

        report = {
            "created": datetime.now().isoformat(timespec="seconds"),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "pyaudiowpatch": getattr(pyaudio, "__version__", "unknown"),
            "portaudio": pyaudio.get_portaudio_version_text(),
            "requested_s": args.seconds,
            "wall_clock_s": round(wall, 3),
            "streams": {},
        }
        all_ok = True
        for r in recs:
            x = r.data()
            stats = analyse(x, r.rate, r.callback_times, args.seconds)
            y16 = to_mono_16k(x, r.rate)
            write_wav(out / f"{r.label}_native.wav", x, r.rate, r.channels)
            write_wav(out / f"{r.label}_16k.wav", (np.clip(y16, -1, 1) * 32767).reshape(-1, 1),
                      TARGET_RATE, 1)
            c = checks(stats, r.overflows, len(y16) / TARGET_RATE)
            all_ok &= all(c.values())
            report["streams"][r.label] = {
                "device_index": int(r.dev["index"]),
                "device_name": r.dev["name"],
                "host_api": host_api_name(p, r.dev),
                "native_rate": r.rate,
                "native_channels": r.channels,
                "overflows": r.overflows,
                **stats,
                "checks": c,
            }
        report["automatic_checks_passed"] = all_ok
    finally:
        p.terminate()

    (out / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [f"Run folder: {out.resolve()}",
             f"Python {report['python']} | {report['platform']} | PyAudioWPatch {report['pyaudiowpatch']}",
             f"Requested {args.seconds} s, wall clock {report['wall_clock_s']} s", ""]
    for label, s in report["streams"].items():
        lines.append(f"[{label}] {s['device_name']} ({s['host_api']}, {s['native_rate']} Hz, "
                     f"{s['native_channels']} ch)")
        lines.append(f"   duration {s['duration_s']} s (err {s['duration_error_s']:+}), overflows {s['overflows']}, "
                     f"rms {s['rms_dbfs']} dBFS, peak {s['peak_dbfs']} dBFS, clipped {s['clipped_fraction']:.4%}, "
                     f"max callback gap {s['max_callback_gap_ms']} ms")
        for name, ok in s["checks"].items():
            lines.append(f"   {'PASS' if ok else 'FAIL'}  {name}")
    lines += ["", f"AUTOMATIC CHECKS: {'ALL PASS' if report['automatic_checks_passed'] else 'SOME FAILED'}",
              "MANUAL CHECKS: listen to mic_16k.wav (your voice) and loop_16k.wav (played audio);",
              "               confirm you heard the played audio normally during recording."]
    text = "\n".join(lines)
    (out / "report.txt").write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["automatic_checks_passed"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="list capture devices and exit")
    ap.add_argument("--mic", type=int, help="microphone device index (default: WASAPI default input)")
    ap.add_argument("--loop", type=int, help="loopback device index (default: loopback of default speakers)")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--out", default="spike_runs")
    args = ap.parse_args()
    if pyaudio is None:
        sys.exit("PyAudioWPatch is not installed (Windows only): pip install -r requirements-spike.txt")
    if args.list:
        p = pyaudio.PyAudio()
        try:
            list_devices(p)
        finally:
            p.terminate()
        return 0
    return record(args)


if __name__ == "__main__":
    sys.exit(main())
