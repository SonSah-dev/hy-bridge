"""Step 3 follow-up: BuzzASR (Whisper-large-v3 Armenian fine-tune) on the eval set (DECISIONS.md D-014).

Needs torch + transformers (and optimum-intel[openvino] for --backend ov-*), which the
project itself does not depend on; use a separate venv:

    python eval/bench_buzzasr.py --download
    python eval/bench_buzzasr.py --backend torch-cpu --threads 6
    python eval/bench_buzzasr.py --backend ov-gpu        # exports to OpenVINO once

Scoring, timing and output format are the same as eval/bench_asr.py; generation settings
follow the model card (greedy, no_repeat_ngram_size=3, repetition_penalty=1.2).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
from armtranslate.evalset import load_manifest  # noqa: E402
from bench_asr import bench, summarize  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = "BuzzASR/armenian"
MODEL_DIR = ROOT / "models" / "buzzasr-armenian"
OV_DIR = ROOT / "models" / "buzzasr-armenian-ov"
GEN = {"num_beams": 1, "no_repeat_ngram_size": 3, "repetition_penalty": 1.2, "max_new_tokens": 440}


class BuzzRecognizer:
    def __init__(self, backend: str, threads: int):
        from transformers import AutoProcessor
        self.processor = AutoProcessor.from_pretrained(MODEL_DIR)
        if backend == "torch-cpu":
            import torch
            from transformers import WhisperForConditionalGeneration
            if threads:
                torch.set_num_threads(threads)
            self.torch = torch
            self.model = WhisperForConditionalGeneration.from_pretrained(MODEL_DIR, torch_dtype=torch.float32).eval()
        else:
            from optimum.intel import OVModelForSpeechSeq2Seq
            device = "GPU" if backend == "ov-gpu" else "CPU"
            if (OV_DIR / "openvino_encoder_model.xml").exists():
                self.model = OVModelForSpeechSeq2Seq.from_pretrained(OV_DIR, device=device)
            else:
                # load_in_8bit=False: optimum otherwise compresses weights of >1B models to int8
                self.model = OVModelForSpeechSeq2Seq.from_pretrained(MODEL_DIR, export=True, device=device,
                                                                     load_in_8bit=False)
                self.model.save_pretrained(OV_DIR)
            self.torch = None

    def transcribe(self, samples) -> str:
        feats = self.processor(samples, sampling_rate=16_000, return_tensors="pt").input_features
        if self.torch is not None:
            with self.torch.inference_mode():
                ids = self.model.generate(feats, **GEN)
        else:
            ids = self.model.generate(feats, **GEN)
        return self.processor.batch_decode(ids, skip_special_tokens=True)[0].strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(HERE / "manifest.jsonl"))
    ap.add_argument("--backend", choices=["torch-cpu", "ov-cpu", "ov-gpu"], default="torch-cpu")
    ap.add_argument("--threads", type=int, default=0, help="torch threads; 0 = default")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--download", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.download:
        from huggingface_hub import snapshot_download
        print(snapshot_download(REPO, local_dir=str(MODEL_DIR)))
        return 0

    manifest = Path(args.manifest)
    clips = [c for c in load_manifest(manifest) if c.hy.strip()]
    t = time.perf_counter()
    rec = BuzzRecognizer(args.backend, args.threads)
    load_s = time.perf_counter() - t
    rows = bench(rec, clips, manifest.parent, args.repeats)
    tag = f"buzzasr-{args.backend}-t{args.threads}"
    s = {"model": tag, "load_s": round(load_s, 2), **summarize(rows)}
    out = HERE / "results" / f"asr-{tag}.jsonl"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"summary": s}, ensure_ascii=False) + "\n")
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n== {tag} ==")
    for r in rows:
        print(f"{r['id']:>7} {r['duration_s']:5.1f}s  {r['compute_s']:6.2f}s  rtf {r['rtf']:.3f}  cer {r['cer']:.3f}"
              f"{'  [latin]' if r['latin_terms'] else ''}")
    print(json.dumps(s, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
