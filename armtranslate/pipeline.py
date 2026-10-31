"""Live pipeline: capture -> VAD segments -> ASR -> speaker -> text fixes -> MT -> terminal (Steps 5-7).

One reader loop per run drains frames from every source (mic, system) and cuts segments; a single worker
thread runs ASR, the speaker embedding (system audio only, D-020) and MT in order, so the CPU is
never shared by two inferences (D-010).
Every segment is logged as one JSON line with its timings; latency is measured from the
end of the last voiced chunk to the moment the line is printed (TESTS.md).
"""
from __future__ import annotations

import json
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, TextIO

import numpy as np

from .audio import AudioFrame, wall_time
from .evalset import read_wav
from .textfix import _ALPHA
from .vad import Segment

UNCLEAR = "[unclear]"
LABELS = {"mic": "Me", "system": "Remote"}   # "Remote" only when speaker labels are off (D-020)


class FileSource:
    """Plays a 16 kHz mono WAV as an `AudioSource`, paced in real time unless `realtime=False`.

    Silence is added before and after so the segmenter can close the last phrase.
    """

    def __init__(self, path: str | Path, name: str = "mic", realtime: bool = True,
                 frame_ms: int = 20, lead_s: float = 0.5, tail_s: float = 1.5):
        y, rate, ch = read_wav(Path(path))
        if rate != 16_000 or ch != 1:
            raise ValueError(f"{path}: expected 16 kHz mono, got {rate} Hz {ch} ch")
        pad = lambda s: np.zeros(int(s * rate), np.float32)  # noqa: E731
        self.samples = np.concatenate([pad(lead_s), y, pad(tail_s)])
        self.name, self.realtime = name, realtime
        self._n = int(rate * frame_ms / 1000)
        self._pos = 0
        self._t0 = 0.0
        self.finished = False

    def start(self) -> None:
        self._t0 = time.perf_counter()

    def stop(self) -> None:
        pass

    def read(self, timeout: float | None = None) -> AudioFrame | None:
        """Next frame once it is due; None if it is not due within `timeout` (0 = don't wait)."""
        if self._pos >= len(self.samples):
            self.finished = True
            return None
        t_frame = self._t0 + self._pos / 16_000
        if self.realtime:
            wait = t_frame + self._n / 16_000 - time.perf_counter()  # frame is "captured" at its end
            if wait > 0:
                if timeout is not None and wait > timeout:
                    if timeout > 0:
                        time.sleep(timeout)
                    return None
                time.sleep(wait)
        chunk = self.samples[self._pos:self._pos + self._n]
        self._pos += self._n
        return AudioFrame(self.name, wall_time(t_frame), chunk)

    def stats(self) -> dict:
        return {"file_s": round(len(self.samples) / 16_000, 2)}


class RecordingSource:
    """Wraps a source and saves everything it delivers to a WAV when stopped (`--record`).

    Live runs can then be replayed with `--wav` / `--wav-system` to tune settings offline.
    """

    def __init__(self, src, path: str | Path):
        self.src, self.path, self._parts = src, Path(path), []

    def __getattr__(self, name):
        return getattr(self.src, name)

    def start(self) -> None:
        self.src.start()

    def read(self, timeout: float | None = None) -> AudioFrame | None:
        frame = self.src.read(timeout=timeout)
        if frame is not None:
            self._parts.append(frame.samples)
        return frame

    def stop(self) -> None:
        self.src.stop()
        from .evalset import write_wav
        write_wav(self.path, np.concatenate(self._parts) if self._parts else np.zeros(0, np.float32))


@dataclass
class Result:
    source: str
    label: str
    t_start: float
    duration_s: float
    forced: bool
    hy: str
    hy_fixed: str
    en: str
    asr_s: float
    mt_s: float
    queue_s: float           # waiting for the worker after the segment closed
    latency_s: float         # last voiced audio -> printed line
    t_print: float
    spk_s: float = 0.0       # speaker embedding + assignment (system audio only)
    speaker: dict | None = None   # similarities to each remote speaker and the decision (D-020)
    asr_conf: dict | None = None  # mean token log-prob and share of unsure tokens (D-022)
    unclear: bool = False         # shown as "[unclear]" instead of a translation (D-022, D-023)
    unclear_reason: str | None = None   # "asr": unsure recognition; "mt-repeat": MT looped;
                                        # "mt-profanity": vulgar English (D-026)

    def line(self) -> str:
        clock = datetime.fromtimestamp(self.t_start).strftime("%H:%M:%S")
        return f"[{clock}] {self.label}: {self.hy_fixed}  →  {self.en}"


@dataclass
class Worker:
    transcribe: Callable[[np.ndarray], str | tuple[str, dict]]   # text, or (text, confidence)
    translate: Callable[[str], str]
    fix: Callable[[str], str] = lambda s: s
    out: TextIO = sys.stdout
    log: TextIO | None = None
    clock: Callable[[], float] = time.time
    min_letters: int = 2                    # fewer Armenian letters: noise, not shown (D-017)
    speakers: Callable[[np.ndarray], tuple[str, dict]] | None = None  # system audio labels (D-020)
    unclear: Callable[[str, dict], bool] | None = None   # (fixed text, confidence) -> garbled? (D-022)
    degenerate: Callable[[str, str], bool] | None = None  # (fixed text, English) -> MT looped? (D-023)
    profane: Callable[[str], bool] | None = None          # English -> invented vulgarity? (D-026)
    results: list[Result] = field(default_factory=list)
    skipped: int = 0

    def __post_init__(self):
        self.q: queue.Queue[Segment | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="inference", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def submit(self, seg: Segment) -> None:
        self.q.put(seg)

    def close(self) -> None:
        """Finish queued segments, then stop."""
        self.q.put(None)
        self._thread.join()

    def process(self, seg: Segment) -> Result | None:
        t_dequeue = self.clock()
        t = time.perf_counter()
        out = self.transcribe(seg.samples)
        hy, conf = (out if isinstance(out, tuple) else (out, None))
        hy = hy.strip()
        asr_s = time.perf_counter() - t
        if sum(ch in _ALPHA for ch in hy) < self.min_letters:
            self.skipped += 1
            return None
        label, speaker, spk_s = LABELS.get(seg.source, seg.source), None, 0.0
        if seg.source == "system" and self.speakers is not None:   # after the noise check: noise
            t = time.perf_counter()                                 # must not create a speaker
            label, speaker = self.speakers(seg.samples)
            spk_s = time.perf_counter() - t
        fixed = self.fix(hy)
        unclear = conf is not None and self.unclear is not None and self.unclear(fixed, conf)
        t = time.perf_counter()
        en = UNCLEAR if unclear else self.translate(fixed)
        mt_s = time.perf_counter() - t
        reason = "asr" if unclear else None
        if not unclear and self.degenerate is not None and self.degenerate(fixed, en):
            en, unclear, reason = UNCLEAR, True, "mt-repeat"
        if not unclear and self.profane is not None and self.profane(en):
            en, unclear, reason = UNCLEAR, True, "mt-profanity"
        t_print = self.clock()
        r = Result(seg.source, label, seg.t_start, round(seg.duration_s, 2),
                   seg.forced, hy, fixed, en, round(asr_s, 3), round(mt_s, 3),
                   round(max(0.0, t_dequeue - seg.t_emit), 3), round(t_print - seg.t_last_voice, 3), t_print,
                   round(spk_s, 3), speaker, conf, unclear, reason)
        print(r.line(), file=self.out, flush=True)
        if self.log is not None:
            self.log.write(json.dumps(r.__dict__, ensure_ascii=False) + "\n")
            self.log.flush()
        self.results.append(r)
        return r

    def _run(self) -> None:
        while True:
            seg = self.q.get()
            if seg is None:
                return
            try:
                self.process(seg)
            except Exception as e:  # one bad segment must not stop the session
                print(f"[error] segment at {seg.t_start:.2f}: {type(e).__name__}: {e}", file=sys.stderr)


def latency_summary(results: list[Result]) -> dict:
    if not results:
        return {"segments": 0}
    lat = np.array([r.latency_s for r in results])
    return {"segments": len(results), "latency_p50_s": round(float(np.percentile(lat, 50)), 2),
            "latency_p95_s": round(float(np.percentile(lat, 95)), 2), "latency_max_s": round(float(lat.max()), 2),
            "over_5s": int((lat > 5.0).sum()), "asr_max_s": max(r.asr_s for r in results),
            "mt_max_s": max(r.mt_s for r in results), "spk_max_s": max(r.spk_s for r in results),
            "queue_max_s": max(r.queue_s for r in results), "unclear": sum(r.unclear for r in results)}


def run(sources: dict, segmenters: dict, worker: Worker, stop: threading.Event | None = None,
        idle_s: float = 0.005) -> None:
    """Read all sources until `stop` is set (or every FileSource has finished).

    Each pass drains every frame a source has ready without waiting, so a quiet source never
    holds up a busy one; the loop sleeps `idle_s` only when no source had anything.
    """
    stop = stop or threading.Event()
    for s in sources.values():
        s.start()
    worker.start()
    try:
        while not stop.is_set():
            got = False
            for name, src in sources.items():
                while (frame := src.read(timeout=0)) is not None:
                    got = True
                    for seg in segmenters[name].push(frame):
                        worker.submit(seg)
            if not got:
                if all(getattr(s, "finished", False) for s in sources.values()):
                    break
                time.sleep(idle_s)
    except KeyboardInterrupt:
        pass
    finally:
        for name, src in sources.items():
            src.stop()
            for seg in segmenters[name].flush():
                worker.submit(seg)
        worker.close()
