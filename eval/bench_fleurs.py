"""Held-out check on FLEURS Armenian (test split): ASR, the text fixes, MT and [unclear] (D-024).

    python eval/bench_fleurs.py asr            # speech recognition with confidence, cached
    python eval/bench_fleurs.py mt             # translation for each fix variant, cached
    python eval/bench_fleurs.py mtref          # translation of the reference Armenian (MT ceiling)
    python eval/bench_fleurs.py report         # numbers for DECISIONS.md

Data (CC-BY-4.0, google/fleurs on Hugging Face), git-ignored under eval/audio/fleurs/:
raw/data/hy_am/test.tsv, raw/data/en_us/{test,dev}.tsv, audio/test/*.wav. The English
reference of a clip is the en_us row with the same FLEURS sentence id.

Why FLEURS: none of the glossary, names list, phrasebook or [unclear] thresholds were tuned on
it, and FastConformer was trained on FLEURS *train*, not test. Caveat: it is read Wikipedia
sentences, not conversation, and it has few of the terms and names the lists target.
Whole clips are recognised (as in D-013), without the live VAD cuts.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from armtranslate.evalset import read_wav  # noqa: E402
from armtranslate.scoring import char_errors, word_errors  # noqa: E402

DATA = ROOT / "eval" / "audio" / "fleurs"
OUT = ROOT / "eval" / "results"
ASR_CACHE = OUT / "fleurs-asr.jsonl"
MT_CACHE = OUT / "fleurs-mt.jsonl"
MTREF_CACHE = OUT / "fleurs-mtref.jsonl"     # same settings, input = reference text (no ASR errors)
# The live pipeline is "all"; the others switch one list off at a time (numbers stay on).
VARIANTS = {"none": (False, False), "glossary": (True, False), "names": (False, True), "all": (True, True)}


def load_clips() -> list[dict]:
    csv.field_size_limit(10_000_000)
    en = {}
    for split in ("test", "dev"):
        with open(DATA / f"raw/data/en_us/{split}.tsv", encoding="utf-8", newline="") as f:
            for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
                en.setdefault(row[0], row[2])
    clips = []
    with open(DATA / "raw/data/hy_am/test.tsv", encoding="utf-8", newline="") as f:
        for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            clips.append({"id": row[0], "file": row[1], "hy": row[2], "en": en.get(row[0]), "gender": row[6]})
    return clips


def find_audio(name: str) -> Path:
    hits = list((DATA / "audio").rglob(name))
    if len(hits) != 1:
        raise FileNotFoundError(f"{name}: {len(hits)} matches under {DATA / 'audio'}")
    return hits[0]


def read_audio(path: Path) -> tuple[np.ndarray, int, int]:
    """FLEURS WAVs are IEEE float (format 3), which `wave` cannot read; PCM goes to read_wav."""
    data = path.read_bytes()
    pos, fmt, rate, ch, bits, samples = 12, None, 0, 0, 0, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], int.from_bytes(data[pos + 4:pos + 8], "little")
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt, ch = int.from_bytes(body[0:2], "little"), int.from_bytes(body[2:4], "little")
            rate, bits = int.from_bytes(body[4:8], "little"), int.from_bytes(body[14:16], "little")
        elif cid == b"data":
            samples = body
        pos += 8 + size + (size & 1)
    if fmt == 1:
        return read_wav(path)
    if fmt != 3 or bits not in (32, 64) or samples is None:
        raise ValueError(f"{path}: unsupported WAV (format {fmt}, {bits} bit)")
    y = np.frombuffer(samples, dtype=np.float32 if bits == 32 else np.float64).astype(np.float32)
    return (y.reshape(-1, ch).mean(axis=1) if ch > 1 else y), rate, 1


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def stage_asr(limit: int | None) -> None:
    from armtranslate.asr import Recognizer
    done = {r["file"] for r in read_jsonl(ASR_CACHE)}
    rec = Recognizer(threads=2)
    rec.transcribe(np.zeros(16_000, np.float32))
    audio = {p.name: p for p in (DATA / "audio").rglob("*.wav")}
    todo = [c for c in load_clips() if c["file"] not in done][:limit]
    print(f"{len(done)} cached, {len(todo)} to do", flush=True)
    with open(ASR_CACHE, "a", encoding="utf-8", newline="\n") as f:
        for i, c in enumerate(todo, 1):
            y, rate, ch = read_audio(audio[c["file"]])
            if rate != 16_000 or ch != 1:
                raise SystemExit(f"{c['file']}: expected 16 kHz mono, got {rate} Hz {ch} ch")
            t = time.perf_counter()
            text, conf = rec.transcribe_scored(y)
            f.write(json.dumps({**c, "asr": text, "conf": conf, "audio_s": round(len(y) / rate, 2),
                                "asr_s": round(time.perf_counter() - t, 3)}, ensure_ascii=False) + "\n")
            if i % 50 == 0:
                f.flush()
                print(f"  {i}/{len(todo)}", flush=True)


def fixers() -> dict:
    from armtranslate.textfix import TextFixer
    g, n = ROOT / "glossary.tsv", ROOT / "names.tsv"
    return {k: TextFixer(g if use_g else None, True, n if use_n else None) for k, (use_g, use_n) in VARIANTS.items()}


def stage_mt(limit: int | None, reference: bool = False) -> None:
    from armtranslate.mt import SegmentTranslator, Translator
    from armtranslate.phrasebook import Phrasebook
    cache_path = MTREF_CACHE if reference else MT_CACHE
    cache = {r["src"]: r for r in read_jsonl(cache_path)}
    fx = fixers()
    rows = read_jsonl(ASR_CACHE)[:limit]
    if reference:      # the reference as the live pipeline would see perfect ASR: same fixes
        srcs = list(dict.fromkeys(fx["all"](r["hy"]) for r in rows))
    else:
        srcs = list(dict.fromkeys(fx[v](r["asr"]) for r in rows for v in VARIANTS))
    todo = [s for s in srcs if s not in cache]
    print(f"{len(srcs)} distinct texts, {len(todo)} to translate", flush=True)
    st = SegmentTranslator(Translator("nllb", "int8", threads=4, beam_size=2),
                           Phrasebook(ROOT / "phrasebook.tsv"), 4)
    with open(cache_path, "a", encoding="utf-8", newline="\n") as f:
        for i, s in enumerate(todo, 1):
            t = time.perf_counter()
            en = st(s)
            f.write(json.dumps({"src": s, "en": en, "mt_s": round(time.perf_counter() - t, 3)},
                               ensure_ascii=False) + "\n")
            if i % 50 == 0:
                f.flush()
                print(f"  {i}/{len(todo)}", flush=True)


def report(mean_below: float, low_from: float) -> dict:
    import sacrebleu
    from armtranslate.asr import is_unclear
    from armtranslate.mt import is_degenerate
    rows = read_jsonl(ASR_CACHE)
    mt = {r["src"]: r["en"] for r in read_jsonl(MT_CACHE)}
    fx = fixers()
    ce = cn = we = wn = 0
    for r in rows:
        e, n = char_errors(r["hy"], r["asr"]); ce += e; cn += n
        e, n = word_errors(r["hy"], r["asr"]); we += e; wn += n
        r["cer"] = char_errors(r["hy"], r["asr"])[0] / max(1, char_errors(r["hy"], r["asr"])[1])
    audio_s = sum(r["audio_s"] for r in rows)
    out = {"clips": len(rows), "audio_h": round(audio_s / 3600, 2), "cer": round(ce / cn, 4),
           "wer": round(we / wn, 4), "rtf": round(sum(r["asr_s"] for r in rows) / audio_s, 4),
           "asr_max_s": max(r["asr_s"] for r in rows)}

    # text fixes: how often each list fires, and the effect on chrF of the translations
    with_en = [r for r in rows if r["en"]]
    out["with_english_ref"] = len(with_en)
    variants = {}
    for v in VARIANTS:
        hyps = [mt.get(fx[v](r["asr"])) for r in with_en]
        if any(h is None for h in hyps):
            continue
        variants[v] = {"chrf": round(sacrebleu.corpus_chrf(hyps, [[r["en"] for r in with_en]]).score, 2),
                       "bleu": round(sacrebleu.corpus_bleu(hyps, [[r["en"] for r in with_en]]).score, 2),
                       "texts_changed_vs_none": sum(fx[v](r["asr"]) != fx["none"](r["asr"]) for r in rows)}
    out["variants"] = variants
    ref_mt = {r["src"]: r["en"] for r in read_jsonl(MTREF_CACHE)}
    hyps = [ref_mt.get(fx["all"](r["hy"])) for r in with_en]
    if all(h is not None for h in hyps):      # MT ceiling: same pipeline, no recognition errors
        out["mt_from_reference"] = {
            "chrf": round(sacrebleu.corpus_chrf(hyps, [[r["en"] for r in with_en]]).score, 2),
            "bleu": round(sacrebleu.corpus_bleu(hyps, [[r["en"] for r in with_en]]).score, 2)}
    changed = []
    for r in with_en:
        a, b = fx["none"](r["asr"]), fx["all"](r["asr"])
        if a != b and a in mt and b in mt:
            ca = sacrebleu.sentence_chrf(mt[a], [r["en"]]).score
            cb = sacrebleu.sentence_chrf(mt[b], [r["en"]]).score
            changed.append({"id": r["id"], "asr": r["asr"], "fixed": b, "ref": r["en"],
                            "en_none": mt[a], "en_all": mt[b], "chrf_none": round(ca, 1), "chrf_all": round(cb, 1)})
    out["changed_by_lists"] = changed

    # [unclear] (D-022): how often it fires on clean read speech, and on what
    flagged = [r for r in rows if is_unclear(r["conf"], mean_below, low_from)]
    def mean_cer(rs): return round(float(np.mean([r["cer"] for r in rs])), 4) if rs else None
    out["unclear"] = {"thresholds": [mean_below, low_from], "flagged": len(flagged),
                      "flagged_share": round(len(flagged) / len(rows), 4),
                      "mean_cer_flagged": mean_cer(flagged),
                      "mean_cer_kept": mean_cer([r for r in rows if r not in flagged]),
                      "by_cer": {f"cer>={lo}": [sum(1 for r in rows if r["cer"] >= lo),
                                                sum(1 for r in flagged if r["cer"] >= lo)]
                                 for lo in (0.0, 0.1, 0.2, 0.3, 0.5)},
                      "examples": [{"id": r["id"], "cer": round(r["cer"], 3), "conf": r["conf"],
                                    "hy": r["hy"][:120], "asr": r["asr"][:120]} for r in flagged]}
    # repetition guard (D-023) on the live variant
    out["mt_repeat_flagged"] = [{"src": fx["all"](r["asr"]), "en": mt[fx["all"](r["asr"])]}
                                for r in rows if fx["all"](r["asr"]) in mt
                                and is_degenerate(fx["all"](r["asr"]), mt[fx["all"](r["asr"])])]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["asr", "mt", "mtref", "report"])
    ap.add_argument("--limit", type=int, help="first N clips only")
    ap.add_argument("--unclear", type=float, nargs=2, default=[-0.3, 0.15], metavar=("MEAN", "LOW_SHARE"))
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.stage == "asr":
        stage_asr(args.limit)
    elif args.stage in ("mt", "mtref"):
        stage_mt(args.limit, reference=args.stage == "mtref")
    else:
        out = report(*args.unclear)
        (OUT / "fleurs-summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        brief = {k: v for k, v in out.items() if k not in ("changed_by_lists", "mt_repeat_flagged")}
        brief["unclear"] = {k: v for k, v in out["unclear"].items() if k != "examples"}
        print(json.dumps(brief, ensure_ascii=False, indent=1))
        print(f"changed by lists: {len(out['changed_by_lists'])}; repetition guard: {len(out['mt_repeat_flagged'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
