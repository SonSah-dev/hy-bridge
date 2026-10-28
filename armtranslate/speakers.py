"""Remote speaker labels: WeSpeaker embeddings + online clustering (DECISIONS.md D-004, D-020).

Microphone segments are always `Me`. Each system-audio segment gets a voice embedding
(WeSpeaker ResNet34-LM, ONNX, 256 dims) and is compared with the running centroid of every
remote speaker seen so far:
  - a segment of at least `min_segment_s` joins the most similar speaker if the cosine
    similarity reaches `similarity_threshold`, and updates that speaker's centroid; otherwise
    it starts a new speaker, up to `max_remote_speakers` (after that, the most similar one);
  - a shorter segment only *borrows* a label: the most similar existing speaker if the
    similarity reaches `short_threshold`, else `Speaker ?`. It never creates or moves a
    speaker, because short segments give unreliable embeddings (D-010).

Features are Kaldi-compatible 80-bin log-mel fbanks, computed here in numpy so that neither
torch nor torchaudio is needed; `fbank` matches `torchaudio.compliance.kaldi.fbank` with the
settings WeSpeaker uses at inference (25/10 ms, Hamming, no dither), followed by mean
normalisation over time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

RATE = 16_000
MODEL_REPO = "Wespeaker/wespeaker-voxceleb-resnet34-LM"
MODEL_FILE = "voxceleb_resnet34_LM.onnx"
DEFAULT_MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "wespeaker-resnet34-LM"
UNKNOWN = "Speaker ?"

_FRAME, _SHIFT, _NFFT, _MELS = 400, 160, 512, 80
_EPS = float(np.finfo(np.float32).eps)


def download(model_dir: str | Path = DEFAULT_MODEL_DIR) -> Path:
    from huggingface_hub import hf_hub_download
    return Path(hf_hub_download(MODEL_REPO, MODEL_FILE, local_dir=str(model_dir)))


def _mel(f):
    return 1127.0 * np.log(1.0 + np.asarray(f, dtype=np.float64) / 700.0)


def _mel_banks() -> np.ndarray:
    """Kaldi's triangular mel filters, (80, 257), low 20 Hz, high = Nyquist."""
    lo, hi = _mel(20.0), _mel(RATE / 2)
    delta = (hi - lo) / (_MELS + 1)
    bins = _mel(np.arange(_NFFT // 2) * RATE / _NFFT)          # Kaldi leaves out the Nyquist bin
    left = lo + np.arange(_MELS)[:, None] * delta
    center, right = left + delta, left + 2 * delta
    up = (bins - left) / (center - left)
    down = (right - bins) / (right - center)
    w = np.maximum(0.0, np.minimum(up, down))
    return np.pad(w, ((0, 0), (0, 1))).astype(np.float32)


_BANKS = _mel_banks()
_WINDOW = (0.54 - 0.46 * np.cos(2 * np.pi * np.arange(_FRAME) / (_FRAME - 1))).astype(np.float32)


def fbank(samples: np.ndarray) -> np.ndarray:
    """16 kHz float32 in [-1, 1] -> (frames, 80) log-mel features, mean-normalised over time."""
    x = np.asarray(samples, dtype=np.float32) * 32768.0          # WeSpeaker scales to int16 range
    n = 1 + (len(x) - _FRAME) // _SHIFT
    if n < 1:
        return np.zeros((0, _MELS), np.float32)
    idx = np.arange(_FRAME)[None, :] + _SHIFT * np.arange(n)[:, None]
    frames = x[idx].astype(np.float64)
    frames -= frames.mean(axis=1, keepdims=True)                 # remove DC offset
    frames[:, 1:] -= 0.97 * frames[:, :-1].copy()                 # pre-emphasis (Kaldi style:
    frames[:, 0] *= 1 - 0.97                                      #  first sample against itself)
    frames *= _WINDOW
    power = np.abs(np.fft.rfft(frames, n=_NFFT)) ** 2
    feats = np.log(np.maximum(power @ _BANKS.T.astype(np.float64), _EPS)).astype(np.float32)
    return feats - feats.mean(axis=0, keepdims=True)


class Embedder:
    """WeSpeaker ResNet34-LM on onnxruntime (CPU). Licence: CC-BY-4.0 (D-005)."""

    def __init__(self, model_dir: str | Path = DEFAULT_MODEL_DIR, threads: int = 2):
        import onnxruntime as ort
        path = Path(model_dir) / MODEL_FILE
        if not path.exists():
            raise FileNotFoundError(f"no speaker model at {path}; run: python eval/bench_speakers.py --download")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        self._s = ort.InferenceSession(str(path), sess_options=opts, providers=["CPUExecutionProvider"])

    def __call__(self, samples: np.ndarray) -> np.ndarray:
        """Unit-length 256-dim embedding of one segment."""
        feats = fbank(samples)
        if len(feats) < 10:                                       # < 0.1 s: pad, the model needs frames
            feats = np.pad(feats, ((0, 10 - len(feats)), (0, 0)))
        e = self._s.run(None, {"feats": feats[None]})[0][0]
        return e / (np.linalg.norm(e) + 1e-9)


@dataclass
class SpeakerTracker:
    """Online clustering of remote voices into `Speaker 1`, `Speaker 2`, …"""

    similarity_threshold: float
    min_segment_s: float = 1.0
    max_speakers: int = 4
    short_threshold: float | None = None   # for short segments; None = same as similarity_threshold
    _sums: list[np.ndarray] = field(default_factory=list)
    counts: list[int] = field(default_factory=list)

    def centroids(self) -> np.ndarray:
        if not self._sums:
            return np.zeros((0, 0), np.float32)
        c = np.stack(self._sums)
        return c / np.linalg.norm(c, axis=1, keepdims=True)

    def assign(self, emb: np.ndarray, duration_s: float) -> tuple[str, dict]:
        """Label for one segment, plus details for the log (similarities, decision)."""
        emb = emb / (np.linalg.norm(emb) + 1e-9)
        sims = self.centroids() @ emb if self._sums else np.zeros(0)
        best = int(np.argmax(sims)) if len(sims) else -1
        top = float(sims[best]) if best >= 0 else None
        info = {"sims": [round(float(s), 3) for s in sims]}
        if duration_s < self.min_segment_s:
            thr = self.similarity_threshold if self.short_threshold is None else self.short_threshold
            if top is not None and top >= thr:
                return self._name(best), {**info, "decision": "short-match"}
            return UNKNOWN, {**info, "decision": "short-unknown"}
        if top is not None and top >= self.similarity_threshold:
            decision = "match"
        elif len(self._sums) < self.max_speakers:
            self._sums.append(np.zeros_like(emb))
            self.counts.append(0)
            best, decision = len(self._sums) - 1, "new"
        else:
            decision = "cap"                                      # nearest, though below threshold
        self._sums[best] = self._sums[best] + emb
        self.counts[best] += 1
        return self._name(best), {**info, "decision": decision}

    @staticmethod
    def _name(i: int) -> str:
        return f"Speaker {i + 1}"


class SpeakerLabeler:
    """Segment -> (label, log details) for system audio: embed, then `SpeakerTracker.assign`."""

    def __init__(self, embed, tracker: SpeakerTracker):
        self.embed, self.tracker = embed, tracker

    def __call__(self, samples: np.ndarray) -> tuple[str, dict]:
        return self.tracker.assign(self.embed(samples), len(samples) / RATE)
