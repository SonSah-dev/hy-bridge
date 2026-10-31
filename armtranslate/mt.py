"""Armenian -> English translation with CTranslate2 on the CPU (DECISIONS.md D-003, D-015).

Two model families, both converted from the official Hugging Face repos with
`ct2-transformers-converter` into `models/` (git-ignored); see eval/bench_mt.py:
  - "opus": Helsinki-NLP/opus-mt-hy-en (Marian, Apache-2.0)
  - "nllb": facebook/nllb-200-distilled-600M (CC-BY-NC-4.0, non-commercial)
"""
from __future__ import annotations

import re
import time
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
SOURCES = {"opus": "Helsinki-NLP/opus-mt-hy-en", "nllb": "facebook/nllb-200-distilled-600M"}
DIRS = {"opus": "opus-mt-hy-en-ct2-{q}", "nllb": "nllb-{size}-ct2-{q}"}   # size: "600m" or "1.3b" (D-028)
NLLB_SRC, NLLB_TGT = "hye_Armn", "eng_Latn"
# Output length cap: 2 x input tokens + 10. Real translations stayed within 2 x (134 logged texts);
# a garbled segment made NLLB loop ("well, well, ...") to 242 tokens and 13.8 s (D-020).
MAX_OUT_RATIO, MAX_OUT_EXTRA = 2, 10
# Speed model for the deadline fallback (D-031): seconds ~ k x (input tokens + 4), k a moving average
# of recent translations. On two replays the actual time was within 1.3 x of this at p90.
SPEED_EXTRA, SPEED_ALPHA, SPEED_SAFETY = 4, 0.3, 1.3
_WORD = re.compile(r"[^\W_]+")


def repeat_run(text: str, max_n: int = 4) -> int:
    """Longest run of one word n-gram (n <= max_n) repeated back to back, case and punctuation
    ignored: "Well, well, well" -> 3; "what have you done, what have you done" -> 2."""
    w = [x.lower() for x in _WORD.findall(text)]
    best = 1
    for n in range(1, max_n + 1):
        for i in range(len(w) - 2 * n + 1):
            k = 1
            while w[i + k * n:i + (k + 1) * n] == w[i:i + n]:
                k += 1
            best = max(best, k)
    return best


def is_degenerate(source: str, output: str, min_run: int = 3, margin: int = 2) -> bool:
    """MT looped (D-023): a phrase repeats at least `min_run` times in a row in the output, and
    at least `margin` times more than anything repeats in the source. So "այո, այո, այո" ->
    "yes, yes, yes" passes, and so does "Շնորհակալություն, շնորհակալություն, շատ
    շնորհակալություն" -> "Thank you, thank you, thank you very much" (source x2, output x3)."""
    run = repeat_run(output)
    return run >= min_run and run >= repeat_run(source) + margin


def model_dir(family: str, compute: str, size: str = "600m") -> Path:
    return MODELS_DIR / DIRS[family].format(q=compute, size=size)


class Translator:
    """`family` is "opus" or "nllb"; `compute` is "int8" or "float32" (the converted weights)."""

    def __init__(self, family: str, compute: str = "int8", threads: int = 2, beam_size: int = 4,
                 path: str | Path | None = None, no_repeat_ngram: int = 0, size: str = "600m"):
        import ctranslate2
        import sentencepiece as spm

        if family not in SOURCES:
            raise ValueError(f"family must be one of {sorted(SOURCES)}, got {family!r}")
        path = Path(path) if path else model_dir(family, compute, size)
        if not (path / "model.bin").exists():
            raise FileNotFoundError(f"no CTranslate2 model in {path}; see eval/bench_mt.py --help")
        self.family, self.compute, self.threads, self.beam_size = family, compute, threads, beam_size
        self.no_repeat_ngram = no_repeat_ngram   # 0 = off; stops loops while decoding (D-028)
        self.s_per_piece: float | None = None    # k of the speed model, from default-beam calls
        self._tr = ctranslate2.Translator(str(path), device="cpu", compute_type=compute,
                                          intra_threads=threads, inter_threads=1)
        if family == "nllb":
            self._src = self._tgt = spm.SentencePieceProcessor(model_file=str(path / "sentencepiece.bpe.model"))
        else:
            self._src = spm.SentencePieceProcessor(model_file=str(path / "source.spm"))
            self._tgt = spm.SentencePieceProcessor(model_file=str(path / "target.spm"))

    def translate(self, text: str, beam_size: int | None = None) -> str:
        text = text.strip()
        if not text:
            return ""
        beam = beam_size or self.beam_size
        pieces = self._src.encode(text, out_type=str)
        t = time.perf_counter()
        out = self._decode(pieces, beam)
        if beam == self.beam_size:
            k = (time.perf_counter() - t) / (len(pieces) + SPEED_EXTRA)
            self.s_per_piece = k if self.s_per_piece is None else (1 - SPEED_ALPHA) * self.s_per_piece + SPEED_ALPHA * k
        return out

    def calibrate(self, text: str) -> None:
        """Seed the speed model from one translation (after a warm-up call, which is slower)."""
        self.s_per_piece = None
        self.translate(text)

    def predict_s(self, text: str) -> float | None:
        """Expected seconds for `text` at the default beam, with a safety margin; None = not measured."""
        if self.s_per_piece is None:
            return None
        n = len(self._src.encode(text.strip(), out_type=str))
        return SPEED_SAFETY * self.s_per_piece * (n + SPEED_EXTRA)

    def _decode(self, pieces: list[str], beam: int) -> str:
        limit = min(256, MAX_OUT_RATIO * len(pieces) + MAX_OUT_EXTRA)
        if self.family == "nllb":
            out = self._tr.translate_batch([[NLLB_SRC] + pieces + ["</s>"]], target_prefix=[[NLLB_TGT]],
                                           beam_size=beam, max_decoding_length=limit,
                                           no_repeat_ngram_size=self.no_repeat_ngram)
            tokens = [t for t in out[0].hypotheses[0] if t != NLLB_TGT]
        else:
            out = self._tr.translate_batch([pieces + ["</s>"]], beam_size=beam, max_decoding_length=limit,
                                           no_repeat_ngram_size=self.no_repeat_ngram)
            tokens = out[0].hypotheses[0]
        return self._tgt.decode(tokens).strip()


# NLLB invented vulgarities from garbled ASR ("Those are the bastards, you know.", "Be the son of a
# bitch.", D-019/D-026). In an interview a wrong obscenity is the worst error the screen can show,
# so English output with one of these words is shown as "[unclear]". Real swearing is hidden too.
_PROFANE = re.compile(r"\b(fuck\w*|motherfuck\w*|shit(?:s|ty|head)?|bullshit\w*|bitch(?:es|y)?|bastards?|assholes?|cunts?|whores?|sluts?)\b",
                      re.IGNORECASE)


def is_profane(output: str) -> bool:
    return _PROFANE.search(output) is not None


# A sentence ends at ։ . ? ! (or the colon FLEURS uses) followed by a space and a capital letter, so
# "8:30" and abbreviations followed by lower case stay whole. FLEURS: on references with 2+
# sentences NLLB often translated only the first; splitting raised their chrF 57.6 -> 60.6 (D-027).
_SENTENCES = re.compile(r"(?<=[։:.?!])\s+(?=[Ա-ՖA-Z])")


def _latin_punctuation(text: str) -> str:
    """Armenian punctuation -> English for text shown as is: `Amazon՞։` -> "Amazon?"."""
    question = "՞" in text
    out = text.replace("՞", "").replace("՛", "").replace("՜", "").replace("՝", ",").strip()
    out = out.rstrip("։.:")
    return out + ("?" if question else ".")


class SegmentTranslator:
    """MT for one pipeline segment, with special handling for short replies (D-017).

    1-3 word segments: phrasebook first; otherwise NLLB with a wider beam and `։` -> `.`,
    which hallucinated less on short inputs. Longer segments go to NLLB unchanged (the `.`
    replacement lowered chrF on full sentences, 65.2 -> 62.5).

    Deadline (D-031): with a `fallback` translator and a `budget_s`, a longer input goes to the
    fallback (NLLB-600M) when the main model's predicted time would not fit in the budget left.
    `used_fallback` tells whether the last call did so.
    """

    def __init__(self, translator: Translator, phrasebook=None, short_beam: int = 4,
                 fallback: Translator | None = None):
        from .phrasebook import MAX_WORDS, words
        self.translator, self.phrasebook, self.short_beam = translator, phrasebook, short_beam
        self.fallback, self.used_fallback = fallback, False
        self._words, self._max_words = words, MAX_WORDS

    def __call__(self, text: str, budget_s: float | None = None) -> str:
        self.used_fallback = False
        end = None if budget_s is None else time.perf_counter() + budget_s
        parts = _SENTENCES.split(text.strip())
        if len(parts) > 1:              # NLLB translates sentence by sentence and drops the rest (D-027)
            return " ".join(t for t in (self._one(p, end, parts[i + 1:]) for i, p in enumerate(parts)) if t)
        return self._one(text, end)

    def _pick(self, text: str, end: float | None, rest: list[str]) -> Translator:
        """The main model, unless it is predicted to miss `end` on this text plus the sentences after it."""
        if self.fallback is None or end is None:
            return self.translator
        need = self.translator.predict_s(" ".join([text, *rest]))
        if need is None or time.perf_counter() + need <= end:
            return self.translator
        self.used_fallback = True
        return self.fallback

    def _one(self, text: str, end: float | None = None, rest: list[str] = ()) -> str:
        if not self._words(text) and any(ch.isdigit() for ch in text):
            return text.replace("։", ".").strip()     # a bare number: NLLB invents a sentence around it
        ws = self._words(text)
        if ws and all(w.isascii() for w in ws):        # only names/terms already in Latin (D-025):
            return _latin_punctuation(text)           # NLLB turned "Satenik։" into "What is it?"
        if self.phrasebook is not None:
            hit = self.phrasebook.lookup(text)
            if hit is not None:
                return hit
        if len(self._words(text)) <= self._max_words:
            return self.translator.translate(text.replace("։", "."), beam_size=self.short_beam)
        return self._pick(text, end, rest).translate(text)
