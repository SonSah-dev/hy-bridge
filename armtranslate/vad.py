"""Voice activity detection and segmentation (DECISIONS.md D-010, D-016).

`Segmenter` turns a stream of `AudioFrame`s from one source into speech segments:
  - speech starts when the VAD probability reaches `vad_threshold`;
  - it ends after `end_pause_ms` below `vad_threshold - 0.15` (hysteresis);
  - a segment is cut at `max_segment_s` even mid-speech, so monologues keep within 5 s;
    the cut is placed at the quietest moment (lowest VAD probability) of the last
    `FORCED_LOOKBACK_S`, so it falls between words rather than inside one;
  - `pre_roll_ms` of audio before the onset is kept; bursts shorter than `min_speech_ms`
    are dropped.
Each segment records `t_last_voice`, the end of its last voiced chunk: latency is measured
from there to the printed line (TESTS.md).

The VAD itself is any callable taking 512 samples (32 ms at 16 kHz) and returning a speech
probability, so the segmenter is testable without a model. `SileroVad` is the real one.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .audio import AudioFrame
from .config import SegmentationConfig

RATE = 16_000
CHUNK = 512                       # Silero's window at 16 kHz
CHUNK_S = CHUNK / RATE
HYSTERESIS = 0.15
FORCED_LOOKBACK_S = 1.5        # the cut point is this far in the past at most: adds to latency
SILERO_URL = "https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx"
DEFAULT_VAD_PATH = Path(__file__).resolve().parent.parent / "models" / "silero-vad" / "silero_vad.onnx"


@dataclass(frozen=True)
class Segment:
    source: str
    t_start: float            # Unix time of the first sample (including pre-roll)
    t_last_voice: float       # end of the last voiced chunk
    t_emit: float             # Unix (stream) time at which the segmenter closed the segment
    samples: np.ndarray
    forced: bool = False      # cut at max_segment_s rather than at a pause

    @property
    def duration_s(self) -> float:
        return len(self.samples) / RATE


class SileroVad:
    """Silero VAD v5 ONNX (MIT). State is kept between calls; one instance per source."""

    CONTEXT = 64

    def __init__(self, path: str | Path = DEFAULT_VAD_PATH):
        import onnxruntime as ort
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"no VAD model at {path}; download it from {SILERO_URL}")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 1
        opts.inter_op_num_threads = 1
        self._s = ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])
        self._sr = np.array(RATE, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.CONTEXT), dtype=np.float32)

    def __call__(self, chunk: np.ndarray) -> float:
        x = np.concatenate([self._context, chunk.reshape(1, -1).astype(np.float32)], axis=1)
        out, self._state = self._s.run(None, {"input": x, "state": self._state, "sr": self._sr})
        self._context = x[:, -self.CONTEXT:]
        return float(out[0, 0])


class Segmenter:
    def __init__(self, source: str, vad: Callable[[np.ndarray], float], cfg: SegmentationConfig):
        self.source, self.vad, self.cfg = source, vad, cfg
        self._pending = np.zeros(0, dtype=np.float32)
        self._t_pending: float | None = None      # stream time of _pending[0]
        self._pre = deque(maxlen=max(1, round(cfg.pre_roll_ms / 1000 / CHUNK_S)))
        self._buf: list[np.ndarray] = []
        self._probs: list[float] = []
        self._t_start = 0.0
        self._t_last_voice = 0.0
        self._voiced_s = 0.0
        self._silence_s = 0.0
        self.in_speech = False
        self.dropped_short = 0

    def push(self, frame: AudioFrame) -> list[Segment]:
        if self._t_pending is None:
            self._t_pending = frame.t_start
        self._pending = np.concatenate([self._pending, frame.samples])
        out = []
        while len(self._pending) >= CHUNK:
            chunk, self._pending = self._pending[:CHUNK], self._pending[CHUNK:]
            t0 = self._t_pending
            self._t_pending += CHUNK_S
            seg = self._step(chunk, t0, self.vad(chunk))
            if seg is not None:
                out.append(seg)
        return out

    def flush(self) -> list[Segment]:
        """Close any open segment (end of input)."""
        seg = self._close(self._t_pending or 0.0, forced=False)
        return [seg] if seg is not None else []

    def _step(self, chunk: np.ndarray, t0: float, p: float) -> Segment | None:
        cfg = self.cfg
        t1 = t0 + CHUNK_S
        if not self.in_speech:
            if p >= cfg.vad_threshold:
                self.in_speech = True
                self._buf = list(self._pre) + [chunk]
                self._probs = [0.0] * len(self._pre) + [p]
                self._t_start = t0 - len(self._pre) * CHUNK_S
                self._t_last_voice = t1
                self._voiced_s, self._silence_s = CHUNK_S, 0.0
                self._pre.clear()
            else:
                self._pre.append(chunk)
            return None

        self._buf.append(chunk)
        self._probs.append(p)
        if p >= cfg.vad_threshold - HYSTERESIS:
            self._t_last_voice = t1
            self._voiced_s += CHUNK_S
            self._silence_s = 0.0
        else:
            self._silence_s += CHUNK_S
        if self._silence_s * 1000 >= cfg.end_pause_ms:
            return self._close(t1, forced=False)
        if len(self._buf) * CHUNK_S >= cfg.max_segment_s:
            return self._forced_cut(t1)
        return None

    def _forced_cut(self, t_emit: float) -> Segment | None:
        n = len(self._buf)
        look = min(n - 1, max(1, round(FORCED_LOOKBACK_S / CHUNK_S)))
        probs = np.array(self._probs[n - look:])
        smooth = np.convolve(probs, np.ones(3) / 3, mode="same")   # a dip, not one stray chunk
        cut = n - look + int(np.argmin(smooth)) + 1                 # keep chunks [0, cut)
        rest_buf, rest_probs = self._buf[cut:], self._probs[cut:]
        self._buf, self._probs = self._buf[:cut], self._probs[:cut]
        t_cut = self._t_start + cut * CHUNK_S
        voiced_rest = sum(CHUNK_S for q in rest_probs if q >= self.cfg.vad_threshold - HYSTERESIS)
        self._voiced_s -= voiced_rest
        self._t_last_voice = min(self._t_last_voice, t_cut)
        seg = self._close(t_emit, forced=True)
        self.in_speech = True                # speech continues into the next segment
        self._buf, self._probs, self._t_start = rest_buf, rest_probs, t_cut
        self._voiced_s, self._silence_s = voiced_rest, 0.0
        self._t_last_voice = t_emit
        return seg

    def _close(self, t_emit: float, forced: bool) -> Segment | None:
        if not self.in_speech:
            return None
        self.in_speech = False
        buf, self._buf, self._probs = self._buf, [], []
        if not buf:
            return None
        if self._voiced_s * 1000 < self.cfg.min_speech_ms:
            self.dropped_short += 1
            return None
        samples = np.concatenate(buf)
        if not forced:  # trim the trailing pause, keeping a little padding
            keep = int(round((self._t_last_voice - self._t_start + 0.15) * RATE))
            samples = samples[:max(CHUNK, keep)]
        return Segment(self.source, self._t_start, self._t_last_voice, t_emit, samples, forced)
