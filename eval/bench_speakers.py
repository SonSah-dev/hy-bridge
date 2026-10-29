"""Step 7: speaker-embedding similarities and online clustering, offline (DECISIONS.md D-020).

    python eval/bench_speakers.py --download                  # fetch WeSpeaker ResNet34-LM into models/
    python eval/bench_speakers.py                             # default data, wideband and narrowband
    python eval/bench_speakers.py --rttm-pair a.wav a.rttm    # add any recording with an RTTM annotation

Data: the developer's mic clips (speaker `me`, eval/manifest.jsonl) and every `--rttm-pair`
(default: pyannote's two-speaker sample in eval/audio/external/, if present). Turns that overlap
another speaker are left out. Reports:
  1. cosine similarity of same-speaker and different-speaker pairs, split by segment length;
  2. online clustering (`SpeakerTracker`) over a range of thresholds, on the RTTM recordings in
     their real turn order, and on a three-voice sequence interleaving them with the mic clips:
     how many labels were made and how many segments got their speaker's label;
  3. embedding time per segment.
"narrowband" resamples to 8 kHz and back first: a rough stand-in for a poor call codec.
"""
from __future__ import annotations

import argparse
import itertools
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from armtranslate.evalset import load_manifest, read_wav  # noqa: E402
from armtranslate.speakers import DEFAULT_MODEL_DIR, Embedder, SpeakerTracker, download  # noqa: E402

HERE = Path(__file__).resolve().parent
PYANNOTE = (HERE / "audio" / "external" / "sample.wav", HERE / "audio" / "external" / "sample.rttm")
SHORT_S = 1.5   # TESTS.md S3: replies under 1.5 s


def rttm_turns(wav: Path, rttm: Path, tag: str) -> list[tuple[str, np.ndarray]]:
    y, rate, _ = read_wav(wav)
    turns = []
    for line in rttm.read_text().splitlines():
        p = line.split()
        if p and p[0] == "SPEAKER":
            turns.append((float(p[3]), float(p[3]) + float(p[4]), f"{tag}:{p[7]}"))
    out = []
    for s, e, spk in sorted(turns):
        keep = np.zeros(len(y), bool)
        keep[int(s * rate):int(e * rate)] = True
        for o_s, o_e, o_spk in turns:
            if o_spk != spk:                                # overlapped speech has no single truth
                keep[int(o_s * rate):int(o_e * rate)] = False
        if keep.sum() >= 0.3 * rate:
            out.append((spk, y[keep]))
    return out


def narrowband(y: np.ndarray) -> np.ndarray:
    import soxr
    return soxr.resample(soxr.resample(y, 16_000, 8_000), 8_000, 16_000).astype(np.float32)


def similarity_report(items, embs) -> None:
    durs = np.array([len(y) / 16_000 for _, y in items])
    spk = [s for s, _ in items]
    same, diff = {"long": [], "short": []}, {"long": [], "short": []}
    for i, j in itertools.combinations(range(len(items)), 2):
        kind = "short" if min(durs[i], durs[j]) < SHORT_S else "long"
        (same if spk[i] == spk[j] else diff)[kind].append(float(embs[i] @ embs[j]))
    for kind in ("long", "short"):
        s, d = np.array(same[kind]), np.array(diff[kind])
        if not len(s) or not len(d):
            continue
        cand = np.linspace(0, 1, 101)
        errs = [max((s < t).mean(), (d >= t).mean()) for t in cand]
        t_best = cand[int(np.argmin(errs))]
        print(f"  {kind:5} pairs  same n={len(s):3} min {s.min():.2f} p5 {np.percentile(s, 5):.2f} "
              f"median {np.median(s):.2f} | different n={len(d):3} median {np.median(d):.2f} "
              f"p95 {np.percentile(d, 95):.2f} max {d.max():.2f} | best split {t_best:.2f} "
              f"(error {min(errs):.0%})")


def cluster_report(name: str, seq, embs, thresholds, min_s: float) -> None:
    print(f"  {name}: {len(seq)} segments, {len(set(s for s, _ in seq))} voices")
    for thr in thresholds:
        tr = SpeakerTracker(thr, min_s, max_speakers=4)
        labels = [tr.assign(e, len(y) / 16_000)[0] for (_, y), e in zip(seq, embs)]
        truth = [s for s, _ in seq]
        long_ = [i for i, (_, y) in enumerate(seq) if len(y) / 16_000 >= min_s]
        # each label stands for the voice it was given most often; a segment is right if its
        # label stands for its own voice and no other label already stands for that voice
        owner = {}
        for lab in set(labels):
            owner[lab] = Counter(t for t, l in zip(truth, labels) if l == lab).most_common(1)[0][0]
        first = {}
        for lab in sorted(set(labels) - {"Speaker ?"}, key=lambda l: labels.index(l)):
            first.setdefault(owner[lab], lab)
        ok = [labels[i] == first.get(truth[i]) for i in range(len(seq))]
        short = [i for i in range(len(seq)) if i not in long_]
        acc = lambda idx: f"{sum(ok[i] for i in idx)}/{len(idx)}" if idx else "-"  # noqa: E731
        print(f"    threshold {thr:.2f}: {len(tr.counts)} labels, right: segments >= {min_s:g} s "
              f"{acc(long_)}, shorter {acc(short)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--rttm-pair", nargs=2, action="append", metavar=("WAV", "RTTM"))
    ap.add_argument("--threads", type=int, default=2)
    ap.add_argument("--min-segment-s", type=float, default=1.0)
    ap.add_argument("--thresholds", type=float, nargs="+", default=[0.3, 0.4, 0.5, 0.6, 0.7])
    args = ap.parse_args()
    if args.download:
        print(download(DEFAULT_MODEL_DIR))
        return 0

    mine = [("me", read_wav(HERE / c.audio)[0]) for c in load_manifest(HERE / "manifest.jsonl")]
    pairs = args.rttm_pair or ([PYANNOTE] if PYANNOTE[0].exists() else [])
    calls = [t for k, (w, r) in enumerate(pairs) for t in rttm_turns(Path(w), Path(r), f"rec{k + 1}")]
    if not calls:
        print("no recording with an RTTM annotation; pass --rttm-pair", file=sys.stderr)
        return 1
    emb = Embedder(threads=args.threads)
    emb(np.zeros(16_000, np.float32))

    for variant, f in (("wideband", lambda y: y), ("narrowband 8 kHz", narrowband)):
        items = [(s, f(y)) for s, y in mine + calls]
        times, embs = [], []
        for _, y in items:
            t = time.perf_counter()
            embs.append(emb(y))
            times.append((time.perf_counter() - t, len(y) / 16_000))
        embs = np.stack(embs)
        print(f"\n== {variant}: {len(items)} segments "
              f"({Counter(s for s, _ in items).most_common()})")
        similarity_report(items, embs)
        n_mine = len(mine)
        cluster_report("recordings in turn order", items[n_mine:], embs[n_mine:], args.thresholds,
                       args.min_segment_s)
        order = [i for pair in itertools.zip_longest(range(n_mine, len(items)), range(n_mine))
                 for i in pair if i is not None]
        cluster_report("three voices interleaved", [items[i] for i in order], embs[order],
                       args.thresholds, args.min_segment_s)
        slow = max(times)
        print(f"  embedding time: median {np.median([t for t, _ in times]) * 1000:.0f} ms, "
              f"max {slow[0] * 1000:.0f} ms ({slow[1]:.1f} s of audio)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
