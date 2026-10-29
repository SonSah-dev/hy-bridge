"""Armenian speech recognition: FastConformer CTC via onnx-asr on the CPU (DECISIONS.md D-002, D-013).

The model is downloaded once into `models/` (git-ignored); see the README.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

RATE = 16_000
MODEL_REPO = "OpenVoiceOS/stt_hy_fastconformer_hybrid_large_pc_onnx"
MODEL_TYPE = "nemo-conformer-ctc"
DEFAULT_MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "stt_hy_fastconformer_onnx"


def download(model_dir: str | Path = DEFAULT_MODEL_DIR) -> Path:
    from huggingface_hub import snapshot_download
    return Path(snapshot_download(MODEL_REPO, local_dir=str(model_dir)))


class Recognizer:
    """Wraps one onnx-asr model. `quantization` is None (fp32) or "int8"."""

    def __init__(self, model_dir: str | Path = DEFAULT_MODEL_DIR, quantization: str | None = None,
                 threads: int = 0):
        import onnx_asr
        import onnxruntime as ort

        model_dir = Path(model_dir)
        if not (model_dir / "config.json").exists():
            raise FileNotFoundError(f"no model in {model_dir}; run: python eval/bench_asr.py --download")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads  # 0 = onnxruntime default (all physical cores)
        self.quantization = quantization
        self.threads = threads
        self._scored = None
        self._model = onnx_asr.load_model(MODEL_TYPE, str(model_dir), quantization=quantization,
                                          providers=["CPUExecutionProvider"], sess_options=opts)

    def transcribe(self, samples: np.ndarray) -> str:
        """16 kHz mono float32 in [-1, 1] -> Armenian text."""
        return self._model.recognize(np.ascontiguousarray(samples, dtype=np.float32), sample_rate=RATE)

    def transcribe_scored(self, samples: np.ndarray) -> tuple[str, dict]:
        """Text plus confidence from the same pass (no extra cost, D-022): the mean token
        log-probability and the share of tokens with probability under 0.5."""
        if self._scored is None:
            self._scored = self._model.with_timestamps()
        r = self._scored.recognize(np.ascontiguousarray(samples, dtype=np.float32), sample_rate=RATE)
        lp = np.asarray(r.logprobs or [0.0], dtype=np.float64)
        return r.text, {"mean_logprob": round(float(lp.mean()), 3),
                        "low_share": round(float((lp < LOW_LOGPROB).mean()), 3)}


LOW_LOGPROB = float(np.log(0.5))


def is_unclear(conf: dict, mean_below: float | None, low_share_from: float | None) -> bool:
    """Garbled recognition (D-022): low mean token log-probability or many unsure tokens."""
    return ((mean_below is not None and conf["mean_logprob"] < mean_below)
            or (low_share_from is not None and conf["low_share"] >= low_share_from))
