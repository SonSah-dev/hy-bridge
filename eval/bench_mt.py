"""Step 4: Armenian -> English translation quality and speed (DECISIONS.md D-015).

Models are converted once from the official repos (needs torch + transformers, e.g. a
separate venv; the project itself only needs ctranslate2 + sentencepiece):

    ct2-transformers-converter --model Helsinki-NLP/opus-mt-hy-en --output_dir models/opus-mt-hy-en-ct2-int8 \
        --quantization int8 --copy_files source.spm target.spm
    ct2-transformers-converter --model facebook/nllb-200-distilled-600M --output_dir models/nllb-600m-ct2-int8 \
        --quantization int8 --copy_files sentencepiece.bpe.model tokenizer.json

    python eval/bench_mt.py                                  # every converted model, beam 4
    python eval/bench_mt.py --family nllb --compute int8 --beam 1

Each clip is translated twice: from the `hy` reference and from the ASR output in
--asr-results (what the live pipeline will see). chrF and BLEU are computed against the
single `en` reference, which is short and free; treat them as relative, not absolute.
Results go to eval/results/mt-<tag>.jsonl, plus eval/results/mt-review-<tag>.csv for
the manual "understandable" rating (TESTS.md).
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from armtranslate.evalset import load_manifest  # noqa: E402
from armtranslate.mt import SOURCES, Translator, model_dir  # noqa: E402
from armtranslate.textfix import TextFixer  # noqa: E402

HERE = Path(__file__).resolve().parent


def load_asr(path: Path) -> dict[str, str]:
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return {r["id"]: r["hyp"] for r in rows if "id" in r}


def bench(tr: Translator, clips, asr: dict[str, str], repeats: int) -> list[dict]:
    rows = []
    for c in clips:
        row = {"id": c.id, "hy": c.hy, "en_ref": c.en, "asr": asr.get(c.id, "")}
        for key, src in (("ref", c.hy), ("asr", row["asr"])):
            tr.translate(src)  # warm-up
            times = []
            for _ in range(repeats):
                t = time.perf_counter()
                out = tr.translate(src)
                times.append(time.perf_counter() - t)
            row[f"en_from_{key}"] = out
            row[f"ms_from_{key}"] = round(1000 * statistics.median(times), 1)
        rows.append(row)
    return rows


def scores(rows: list[dict], key: str) -> dict:
    import sacrebleu
    hyps = [r[f"en_from_{key}"] for r in rows]
    refs = [[r["en_ref"] for r in rows]]
    return {"chrf": round(sacrebleu.corpus_chrf(hyps, refs).score, 1),
            "bleu": round(sacrebleu.corpus_bleu(hyps, refs).score, 1)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(HERE / "manifest.jsonl"))
    ap.add_argument("--asr-results", default=str(HERE / "results" / "asr-fp32-t2.jsonl"))
    ap.add_argument("--family", choices=[*SOURCES, "all"], default="all")
    ap.add_argument("--compute", choices=["int8", "float32", "all"], default="all")
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--beam", type=int, default=4)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--fix", action="store_true",
                    help="apply glossary.tsv + numbers-to-digits to the ASR text first (D-016)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    clips = [c for c in load_manifest(args.manifest) if c.hy.strip() and c.en.strip()]
    asr = load_asr(Path(args.asr_results))
    if args.fix:
        fixer = TextFixer(ROOT / "glossary.tsv")
        asr = {k: fixer(v) for k, v in asr.items()}
    families = list(SOURCES) if args.family == "all" else [args.family]
    computes = ["int8", "float32"] if args.compute == "all" else [args.compute]
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    for fam in families:
        for q in computes:
            if not (model_dir(fam, q) / "model.bin").exists():
                print(f"skip {fam} {q}: {model_dir(fam, q)} not converted")
                continue
            t = time.perf_counter()
            tr = Translator(fam, q, threads=args.threads, beam_size=args.beam)
            load_s = time.perf_counter() - t
            rows = bench(tr, clips, asr, args.repeats)
            tag = f"{fam}-{q}-b{args.beam}-t{args.threads}" + ("-fix" if args.fix else "")
            ms = [r["ms_from_asr"] for r in rows]
            s = {"model": tag, "source": SOURCES[fam], "load_s": round(load_s, 2), "clips": len(rows),
                 "from_ref": scores(rows, "ref"), "from_asr": scores(rows, "asr"),
                 "ms_median": statistics.median(ms), "ms_max": max(ms),
                 "ms_max_clip": max(rows, key=lambda r: r["ms_from_asr"])["id"]}
            with open(out_dir / f"mt-{tag}.jsonl", "w", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps({"summary": s}, ensure_ascii=False) + "\n")
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            with open(out_dir / f"mt-review-{tag}.csv", "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["id", "asr_hy", "en_from_asr", "en_reference", "understandable (y/n)", "note"])
                for r in rows:
                    w.writerow([r["id"], r["asr"], r["en_from_asr"], r["en_ref"], "", ""])
            print(f"\n== {tag} ==")
            for r in rows:
                print(f"{r['id']:>7} {r['ms_from_asr']:7.1f} ms  {r['en_from_asr']}")
            print(json.dumps(s, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
