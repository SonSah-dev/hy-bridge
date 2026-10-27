"""Step 3: ASR error rate and speed on the evaluation set (DECISIONS.md D-013).

    python eval/bench_asr.py --download              # fetch the model into models/ once
    python eval/bench_asr.py                         # fp32 and int8, default threads
    python eval/bench_asr.py --quant int8 --threads 4

For each clip: transcript, CER/WER against `hy`, and compute time (median of --repeats
runs after one warm-up). The real-time factor (RTF) is compute time / audio length.
Results go to eval/results/asr-<tag>.jsonl plus a summary on stdout.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from armtranslate.asr import DEFAULT_MODEL_DIR, Recognizer, download  # noqa: E402
from armtranslate.evalset import load_manifest, read_wav  # noqa: E402
from armtranslate.scoring import LATIN, char_errors, normalize, word_errors  # noqa: E402

HERE = Path(__file__).resolve().parent


def bench(rec: Recognizer, clips, root: Path, repeats: int) -> list[dict]:
    rows = []
    for c in clips:
        y, _, _ = read_wav(root / c.audio)
        rec.transcribe(y)  # warm-up
        times = []
        for _ in range(repeats):
            t = time.perf_counter()
            hyp = rec.transcribe(y)
            times.append(time.perf_counter() - t)
        ce, cn = char_errors(c.hy, hyp)
        we, wn = word_errors(c.hy, hyp)
        dur = len(y) / 16_000
        sec = statistics.median(times)
        rows.append({"id": c.id, "duration_s": round(dur, 2), "compute_s": round(sec, 3),
                     "rtf": round(sec / dur, 3), "char_err": ce, "chars": cn, "word_err": we,
                     "words": wn, "cer": round(ce / cn, 3), "latin_terms": bool(LATIN.search(c.hy)),
                     "ref": c.hy, "hyp": hyp, "ref_norm": normalize(c.hy), "hyp_norm": normalize(hyp)})
    return rows


def summarize(rows: list[dict]) -> dict:
    def rate(sub, e, n):
        return round(sum(r[e] for r in sub) / max(1, sum(r[n] for r in sub)), 3)
    plain = [r for r in rows if not r["latin_terms"]]
    return {
        "clips": len(rows),
        "cer": rate(rows, "char_err", "chars"),
        "wer": rate(rows, "word_err", "words"),
        "cer_no_latin": rate(plain, "char_err", "chars"),
        "clips_no_latin": len(plain),
        "rtf_total": round(sum(r["compute_s"] for r in rows) / sum(r["duration_s"] for r in rows), 3),
        "max_compute_s": max(r["compute_s"] for r in rows),
        "max_compute_clip": max(rows, key=lambda r: r["compute_s"])["id"],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(HERE / "manifest.jsonl"))
    ap.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    ap.add_argument("--quant", choices=["fp32", "int8", "both"], default="both")
    ap.add_argument("--threads", type=int, default=0, help="onnxruntime intra-op threads; 0 = default")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--download", action="store_true", help="download the model and exit")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.download:
        print(download(args.model_dir))
        return 0

    manifest = Path(args.manifest)
    clips = [c for c in load_manifest(manifest) if c.hy.strip()]
    if not clips:
        print(f"no clips with an hy reference in {manifest}")
        return 1
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    quants = ["fp32", "int8"] if args.quant == "both" else [args.quant]
    for q in quants:
        t = time.perf_counter()
        rec = Recognizer(args.model_dir, quantization=None if q == "fp32" else q, threads=args.threads)
        load_s = time.perf_counter() - t
        rows = bench(rec, clips, manifest.parent, args.repeats)
        s = {"model": q, "threads": args.threads, "load_s": round(load_s, 2), **summarize(rows)}
        tag = f"{q}-t{args.threads}"
        with open(out_dir / f"asr-{tag}.jsonl", "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"summary": s}, ensure_ascii=False) + "\n")
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n== {tag} ==")
        for r in rows:
            print(f"{r['id']:>7} {r['duration_s']:5.1f}s  rtf {r['rtf']:.3f}  cer {r['cer']:.3f}"
                  f"{'  [latin]' if r['latin_terms'] else ''}")
        print(json.dumps(s, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
