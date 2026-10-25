"""Audio-capture layer (DECISIONS.md D-011).

Uses only standard Windows audio: a WASAPI microphone input and the WASAPI loopback of an
output device, so it captures whatever any app plays there. Nothing here knows about the
conferencing app.

Everything downstream sees only `AudioSource.read()` -> `AudioFrame`: 16 kHz mono float32
samples from one source ("mic" or "system") with wall-clock timestamps.

Timing: each source keeps a sample clock anchored to the wall clock at the first callback.
WASAPI loopback delivers no data while nothing is playing; when the wall clock runs ahead of
the sample clock by more than `gap_threshold_ms`, the gap is filled with silence (counted in
the stats) so timestamps and segment boundaries stay correct.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol

import numpy as np
import soxr

from .config import AudioConfig, DeviceSpec

try:
    import pyaudiowpatch as pyaudio
except ImportError:  # the pure parts below stay importable (and testable) without it
    pyaudio = None

SOURCES = ("mic", "system")

# perf_counter is monotonic; this offset turns it into Unix time for display and logs.
_EPOCH_OFFSET = time.time() - time.perf_counter()


def wall_time(perf_t: float) -> float:
    return _EPOCH_OFFSET + perf_t


@dataclass(frozen=True)
class AudioFrame:
    source: str           # "mic" or "system"
    t_start: float        # Unix time of the first sample
    samples: np.ndarray   # float32, mono
    rate: int = 16_000

    @property
    def t_end(self) -> float:
        return self.t_start + len(self.samples) / self.rate


class AudioSource(Protocol):
    name: str

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def read(self, timeout: float | None = None) -> AudioFrame | None: ...
    def stats(self) -> dict: ...


# ----------------------------------------------------------------- device selection (pure)

class DeviceError(ValueError):
    pass


def _describe(devices: Iterable[dict]) -> str:
    return "\n".join(f"  [{d['index']}] {d['name']}" for d in devices) or "  (none)"


def resolve_device(devices: list[dict], spec: DeviceSpec, kind: str,
                   default_index: int | None, wasapi_host: int) -> dict:
    """Pick a capture device for `kind` ("mic" or "system") by index, name substring or default.

    Name matching only considers WASAPI devices of the right kind (loopbacks for "system").
    An ambiguous substring is an error unless one device name matches exactly.
    """
    if kind not in SOURCES:
        raise DeviceError(f"unknown source kind {kind!r}")
    want_loop = kind == "system"

    def fits(d: dict) -> bool:
        return d["maxInputChannels"] > 0 and bool(d.get("isLoopbackDevice")) == want_loop

    candidates = [d for d in devices if fits(d) and d["hostApi"] == wasapi_host]
    what = "a WASAPI loopback (system audio) device" if want_loop else "a microphone"

    if spec is None or isinstance(spec, int):
        idx = default_index if spec is None else spec
        if idx is None:
            raise DeviceError(f"no default {kind} device; choose one by index or name:\n"
                              f"{_describe(candidates)}")
        by_idx = {d["index"]: d for d in devices}
        if idx not in by_idx:
            raise DeviceError(f"no device with index {idx}")
        d = by_idx[idx]
        if not fits(d):
            raise DeviceError(f"device [{idx}] {d['name']} is not {what}. Candidates:\n"
                              f"{_describe(candidates)}")
        return d

    needle = spec.casefold()
    matches = [d for d in candidates if needle in d["name"].casefold()]
    exact = [d for d in matches if d["name"].casefold() == needle]
    if len(exact) == 1:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise DeviceError(f"no {kind} device name contains {spec!r}. Candidates:\n"
                          f"{_describe(candidates)}")
    raise DeviceError(f"{spec!r} matches several {kind} devices; be more specific:\n"
                      f"{_describe(matches)}")


# ----------------------------------------------------------------- stream conditioning (pure)

class FrameAssembler:
    """Turns raw int16 callback chunks into timestamped 16 kHz mono float32 frames."""

    def __init__(self, source: str, native_rate: int, channels: int, cfg: AudioConfig):
        self.source = source
        self.native_rate = native_rate
        self.channels = channels
        self.out_rate = cfg.sample_rate
        self.fill_gaps = cfg.fill_gaps
        self.threshold = cfg.gap_threshold_ms / 1000
        self._resampler = soxr.ResampleStream(native_rate, cfg.sample_rate, 1, dtype="float32")
        self._clock: float | None = None   # perf_counter time just after the last sample
        self._in_s = 0.0                    # audio fed to the resampler (incl. filled gaps)
        self._out_s = 0.0                   # audio emitted by it
        self._in_gap = False
        self.gaps_filled = 0                # silent stretches after real audio had arrived
        self.gap_filled_s = 0.0             # all inserted silence, including leading_fill_s
        self.leading_fill_s = 0.0           # silence before the first real audio
        self.resyncs = 0
        self.native_frames = 0

    def _emit(self, mono: np.ndarray) -> AudioFrame | None:
        out = self._resampler.resample_chunk(mono, last=False)
        self._in_s += len(mono) / self.native_rate
        if out.size == 0:
            return None
        self._out_s += out.size / self.out_rate
        held_back = self._in_s - self._out_s   # resampler delay: output trails the input
        t_end = wall_time(self._clock) - held_back
        return AudioFrame(self.source, t_end - out.size / self.out_rate,
                          np.ascontiguousarray(out, dtype=np.float32), self.out_rate)

    def _gap(self, now: float, pending_s: float) -> np.ndarray | None:
        """Silence for the time the sample clock lags behind `now` (minus audio still to come)."""
        lag = now - pending_s - self._clock
        # Before the first real audio, data arriving now marks the true start: fill exactly.
        threshold = 0.0 if self.native_frames == 0 and pending_s > 0 else self.threshold
        if not self.fill_gaps or lag <= threshold:
            return None
        n = int(round(lag * self.native_rate))
        if self.native_frames == 0:          # stream start-up / nothing played yet
            self.leading_fill_s += n / self.native_rate
        elif not self._in_gap:               # one silent stretch counts as one gap
            self.gaps_filled += 1
        self._in_gap = True
        self.gap_filled_s += n / self.native_rate
        self._clock += n / self.native_rate
        return np.zeros(n, dtype=np.float32)

    def anchor(self, t: float) -> None:
        """Start the sample clock at stream start, so silence before the first callback counts."""
        if self._clock is None:
            self._clock = t

    def push(self, raw: bytes, t_callback: float) -> AudioFrame | None:
        a = np.frombuffer(raw, dtype=np.int16)
        a = a[: len(a) - len(a) % self.channels].reshape(-1, self.channels)
        mono = a.astype(np.float32).mean(axis=1) / 32768.0
        dur = len(mono) / self.native_rate
        if self._clock is None:
            self._clock = t_callback - dur
        pieces = []
        silence = self._gap(t_callback, dur)
        if silence is not None:
            pieces.append(silence)
        self.native_frames += len(mono)
        pieces.append(mono)
        self._in_gap = False
        self._clock += dur
        if self._clock - t_callback > self.threshold:   # device clock running ahead: resync
            self._clock = t_callback
            self.resyncs += 1
        return self._emit(np.concatenate(pieces) if len(pieces) > 1 else mono)

    def idle(self, now: float) -> AudioFrame | None:
        """No data arrived: emit silence up to `now` if the gap exceeds the threshold."""
        if self._clock is None:
            return None
        silence = self._gap(now, 0.0)
        return None if silence is None else self._emit(silence)


# ----------------------------------------------------------------- WASAPI capture (Windows)

def _require_pyaudio() -> None:
    if pyaudio is None:
        raise RuntimeError("PyAudioWPatch is not installed (Windows only): pip install PyAudioWPatch")


def capture_devices(p) -> tuple[list[dict], int, int | None, int | None]:
    """(all devices, WASAPI host index, default mic index, default loopback index)."""
    _require_pyaudio()
    wasapi = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    try:
        default_loop = p.get_default_wasapi_loopback()["index"]
    except Exception:
        default_loop = None
    mic = wasapi["defaultInputDevice"]
    return (list(p.get_device_info_generator()), wasapi["index"],
            mic if mic is not None and mic >= 0 else None, default_loop)


def select_devices(p, cfg: AudioConfig) -> dict[str, dict]:
    devices, host, default_mic, default_loop = capture_devices(p)
    return {
        "mic": resolve_device(devices, cfg.mic_device, "mic", default_mic, host),
        "system": resolve_device(devices, cfg.system_device, "system", default_loop, host),
    }


def device_table(p) -> str:
    devices, host, default_mic, default_loop = capture_devices(p)
    names = {i: p.get_host_api_info_by_index(i)["name"] for i in {d["hostApi"] for d in devices}}
    rows = [f"{'idx':>4}  {'host API':<22} {'in':>3} {'rate':>7}  {'use as':<9} name"]
    for d in devices:
        if d["maxInputChannels"] < 1:
            continue
        use = ("system" if d.get("isLoopbackDevice") else "mic") if d["hostApi"] == host else "-"
        if d["index"] in (default_mic, default_loop):
            use += " *"
        rows.append(f"{d['index']:>4}  {names[d['hostApi']]:<22} {d['maxInputChannels']:>3} "
                    f"{int(d['defaultSampleRate']):>7}  {use:<9} {d['name']}")
    rows += ["", "* = Windows default. Select with an index or part of the name, e.g.",
             '    --mic 3   --system "Headset"   (system = WASAPI loopback of an output device)',
             "Only WASAPI devices can be selected by name."]
    return "\n".join(rows)


class WasapiSource:
    """One capture stream (mic or system loopback) feeding a bounded queue."""

    def __init__(self, p, device: dict, name: str, cfg: AudioConfig,
                 raw_sink: Callable[[bytes], None] | None = None):
        _require_pyaudio()
        self.name, self.device, self.cfg = name, device, cfg
        self.native_rate = int(device["defaultSampleRate"])
        self.channels = int(device["maxInputChannels"])
        self._assembler = FrameAssembler(name, self.native_rate, self.channels, cfg)
        self._raw_sink = raw_sink
        self._queue: queue.Queue[tuple[bytes, float]] = queue.Queue(
            maxsize=max(1, int(cfg.queue_seconds * 1000 / cfg.block_ms)))
        self._lock = threading.Lock()
        self._s = {"callbacks": 0, "overflows": 0, "dropped_chunks": 0,
                   "max_callback_gap_ms": 0.0, "last_rms": 0.0}
        self._last_cb: float | None = None
        self._stream = p.open(
            format=pyaudio.paInt16, channels=self.channels, rate=self.native_rate, input=True,
            input_device_index=int(device["index"]),
            frames_per_buffer=int(self.native_rate * cfg.block_ms / 1000),
            stream_callback=self._callback, start=False)

    def _callback(self, in_data, frame_count, time_info, status):
        now = time.perf_counter()
        a = np.frombuffer(in_data, dtype=np.int16)
        with self._lock:
            s = self._s
            s["callbacks"] += 1
            if status & pyaudio.paInputOverflow:
                s["overflows"] += 1
            if self._last_cb is not None:
                s["max_callback_gap_ms"] = max(s["max_callback_gap_ms"], (now - self._last_cb) * 1000)
            self._last_cb = now
            s["last_rms"] = float(np.sqrt(np.mean((a / 32768.0) ** 2))) if a.size else 0.0
        if self._raw_sink is not None:
            self._raw_sink(in_data)
        try:
            self._queue.put_nowait((in_data, now))
        except queue.Full:
            with self._lock:
                self._s["dropped_chunks"] += 1
        return (None, pyaudio.paContinue)

    def start(self) -> None:
        self._stream.start_stream()
        self._assembler.anchor(time.perf_counter())

    def stop(self) -> None:
        if self._stream.is_active():
            self._stream.stop_stream()
        self._stream.close()

    def read(self, timeout: float | None = None) -> AudioFrame | None:
        """Next frame, or None if nothing is available within `timeout` (None = block)."""
        while True:
            try:
                raw, t = self._queue.get(timeout=timeout) if timeout else self._queue.get_nowait()
            except queue.Empty:
                return self._assembler.idle(time.perf_counter())
            frame = self._assembler.push(raw, t)
            if frame is not None:
                return frame

    def stats(self) -> dict:
        with self._lock:
            s = dict(self._s)
        a = self._assembler
        s.update(native_rate=self.native_rate, native_channels=self.channels,
                 native_s=round(a.native_frames / self.native_rate, 3),
                 gaps_filled=a.gaps_filled, gap_filled_s=round(a.gap_filled_s, 3),
                 leading_fill_s=round(a.leading_fill_s, 3),
                 clock_resyncs=a.resyncs, max_callback_gap_ms=round(s["max_callback_gap_ms"], 1))
        return s


def open_sources(p, cfg: AudioConfig, raw_sinks: dict[str, Callable[[bytes], None]] | None = None
                 ) -> dict[str, WasapiSource]:
    devices = select_devices(p, cfg)
    sinks = raw_sinks or {}
    return {name: WasapiSource(p, dev, name, cfg, sinks.get(name)) for name, dev in devices.items()}
