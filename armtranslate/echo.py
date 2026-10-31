"""Echo detection, shadow mode only (D-030): is a mic segment the call's own audio picked up by the mic?

With speakers instead of headphones the laptop mic hears the remote people, and that echo became
`Me` lines ("Հովհ է." -> "It's John.") in the 2026-10-31 test call. The detector keeps the last
seconds of system audio and, for each mic segment, measures:
  - overlap_s / overlap_share: voiced mic frames during which the call is talking (at the best lag);
  - level_db: mic p90 band level minus system p90 band level; echo is quieter than the call,
    your own voice is louder (measured: echo -17..+4 dB, real speech over the call +10..+16 dB);
  - similarity: correlation of the 16-band log spectrogram with the system audio at the best
    lag of 0..max_lag_ms (echo 0.30-0.51, own speech 0.03-0.29);
  - mic_only_s: voiced mic time while the call is silent, i.e. you talking outside the call's turn.
A segment is `suspect` only if all conditions hold. Nothing is suppressed: the result is logged
in segments.jsonl so the rule can be checked on new calls before it is allowed to hide anything.

Known limit: a quiet interruption by you while the call talks loudly can look like echo
(simulated at -10 dB: 2 of 5 cases), so suppression must stay off until more data is checked.
The mic DSP (Intel Smart Sound) gates and processes the echo non-linearly, so a waveform
canceller was not used; spectral patterns survive that processing.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from .audio import AudioFrame
from .config import EchoConfig

RATE = 16_000
NFFT, HOP = 512, 256                    # 32 ms frames, 16 ms hop
FRAME_S = HOP / RATE
_EDGES = (np.geomspace(250, 4000, 17) * NFFT / RATE).astype(int)   # 16 bands, 250 Hz - 4 kHz
_WIN = np.hanning(NFFT).astype(np.float32)
_FLOOR = 1e-12
DILATE = 3                              # +-48 ms: delay jitter and room reverb
MIC_RANGE_DB = 30                       # mic frames within 30 dB of the segment's loudest are voiced


def band_power(y: np.ndarray) -> np.ndarray:
    """(frames, 16) band powers."""
    if len(y) < NFFT:
        y = np.pad(y, (0, NFFT - len(y)))
    fr = np.lib.stride_tricks.sliding_window_view(y, NFFT)[::HOP] * _WIN
    p = np.abs(np.fft.rfft(fr, axis=1)) ** 2
    return np.stack([p[:, a:b].sum(1) for a, b in zip(_EDGES[:-1], _EDGES[1:])], 1) + _FLOOR


def frame_dbfs(y: np.ndarray) -> np.ndarray:
    """RMS level of each analysis frame, dB full scale."""
    if len(y) < NFFT:
        y = np.pad(y, (0, NFFT - len(y)))
    fr = np.lib.stride_tricks.sliding_window_view(y, NFFT)[::HOP]
    return 10 * np.log10((fr ** 2).mean(1) + _FLOOR)


def measure(mic: np.ndarray, system: np.ndarray, cfg: EchoConfig) -> dict:
    """Echo measurements for one mic segment.

    `system` is the system audio from `cfg.max_lag_ms` before the segment to its end, so system
    sample `lag + i` lines up with mic sample `i` delayed by `lag`.
    """
    max_lag = int(round(cfg.max_lag_ms / 1000 / FRAME_S))
    M, S = band_power(mic), band_power(system)
    n = len(M)
    S = np.vstack([S, np.full((max(0, max_lag + n - len(S)), S.shape[1]), _FLOOR)])
    sys_on_all = frame_dbfs(system) > cfg.active_dbfs
    sys_on_all = np.concatenate([sys_on_all, np.zeros(max(0, max_lag + n - len(sys_on_all)), bool)])
    mic_db = 10 * np.log10(M.sum(1))
    voiced = (mic_db > mic_db.max() - MIC_RANGE_DB) & (frame_dbfs(mic)[:n] > cfg.active_dbfs - 20)
    out = {"suspect": False, "overlap_s": 0.0, "overlap_share": 0.0, "level_db": None,
           "similarity": None, "lag_ms": None, "mic_only_s": round(voiced.sum() * FRAME_S, 2)}
    if voiced.sum() < 2 or not sys_on_all.any():
        return out
    lm = np.log(M[voiced])
    lm -= lm.mean(0)
    best_c, best_lag = -1.0, 0
    for lag in range(max_lag + 1):             # system delayed by `lag` frames relative to the mic
        ls = np.log(S[max_lag - lag: max_lag - lag + n][voiced])
        ls -= ls.mean(0)
        den = np.sqrt((lm ** 2).sum() * (ls ** 2).sum())
        c = float((lm * ls).sum() / den) if den > 0 else 0.0
        if c > best_c:
            best_c, best_lag = c, lag
    on = sys_on_all[max_lag - best_lag: max_lag - best_lag + n]
    on = np.convolve(on.astype(float), np.ones(2 * DILATE + 1), mode="same") > 0
    overlap = voiced & on
    sys_db = 10 * np.log10(S[max_lag - best_lag: max_lag - best_lag + n].sum(1))
    level = float(np.percentile(mic_db, 90) - np.percentile(sys_db, 90))
    out.update(overlap_s=round(overlap.sum() * FRAME_S, 2), overlap_share=round(overlap.sum() / voiced.sum(), 2),
               level_db=round(level, 1), similarity=round(best_c, 2), lag_ms=round(best_lag * FRAME_S * 1000),
               mic_only_s=round((voiced & ~on).sum() * FRAME_S, 2))
    out["suspect"] = bool(out["overlap_s"] >= cfg.min_overlap_s and out["overlap_share"] >= cfg.min_overlap_share
                          and level <= cfg.max_level_db and best_c >= cfg.min_similarity
                          and out["mic_only_s"] < cfg.max_mic_only_s)
    return out


class EchoDetector:
    """Keeps recent system audio and measures mic segments against it (shadow mode: log only)."""

    def __init__(self, cfg: EchoConfig, keep_s: float = 20.0):
        self.cfg = cfg
        self._frames: deque[AudioFrame] = deque()
        self._keep_s = keep_s
        self.t_end = 0.0                       # end of the newest system audio received

    def feed(self, frame: AudioFrame) -> None:
        self._frames.append(frame)
        self.t_end = max(self.t_end, frame.t_end)
        while self._frames and self._frames[0].t_end < self.t_end - self._keep_s:
            self._frames.popleft()

    def covers(self, t: float) -> bool:
        return self.t_end >= t

    def system_audio(self, t0: float, t1: float) -> np.ndarray:
        """System samples from t0 to t1 (silence where nothing was received)."""
        out = np.zeros(max(0, int(round((t1 - t0) * RATE))), np.float32)
        for f in self._frames:
            if f.t_end <= t0 or f.t_start >= t1:
                continue
            a = int(round((f.t_start - t0) * RATE))
            lo, hi = max(0, a), min(len(out), a + len(f.samples))
            out[lo:hi] = f.samples[lo - a:hi - a]
        return out

    def check(self, samples: np.ndarray, t_start: float) -> dict:
        t1 = t_start + len(samples) / RATE
        sys_audio = self.system_audio(t_start - self.cfg.max_lag_ms / 1000, t1)
        return measure(samples, sys_audio, self.cfg)
