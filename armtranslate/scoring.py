"""Text normalisation and error rates for the ASR benchmark (Step 3, DECISIONS.md D-013).

References follow the D-012 conventions (numbers as digits, English terms in Latin
letters); the ASR writes numbers as words. Both sides are normalised the same way:
lower case, `և` spelled `եւ`, punctuation removed, and digits expanded to Eastern
Armenian number words, so `4` and `չորս` count as equal.
"""
from __future__ import annotations

import re
import unicodedata

_ONES = ["", "մեկ", "երկու", "երեք", "չորս", "հինգ", "վեց", "յոթ", "ութ", "ինը"]
_TEENS = ["տասը", "տասնմեկ", "տասներկու", "տասներեք", "տասնչորս", "տասնհինգ",
          "տասնվեց", "տասնյոթ", "տասնութ", "տասնինը"]
_TENS = ["", "", "քսան", "երեսուն", "քառասուն", "հիսուն", "վաթսուն", "յոթանասուն",
         "ութսուն", "իննսուն"]
LATIN = re.compile(r"[A-Za-z]")


def number_to_hy(n: int) -> str:
    """Eastern Armenian words for 0 <= n < 1 000 000 (e.g. 2022 -> 'երկու հազար քսաներկու')."""
    if not 0 <= n < 1_000_000:
        raise ValueError(f"{n} is out of range")
    if n == 0:
        return "զրո"
    parts = []
    thousands, rest = divmod(n, 1000)
    if thousands:
        parts.append("հազար" if thousands == 1 else f"{number_to_hy(thousands)} հազար")
    hundreds, rest = divmod(rest, 100)
    if hundreds:
        parts.append("հարյուր" if hundreds == 1 else f"{_ONES[hundreds]} հարյուր")
    if rest >= 20:
        parts.append(_TENS[rest // 10] + _ONES[rest % 10])  # written as one word: քսանմեկ
    elif rest >= 10:
        parts.append(_TEENS[rest - 10])
    elif rest:
        parts.append(_ONES[rest])
    return " ".join(parts)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    text = text.replace("և", "եւ")
    text = re.sub(r"[՛՜՞]", "", text)  # Armenian emphasis/exclamation/question marks sit inside words
    text = re.sub(r"\d+", lambda m: f" {number_to_hy(int(m.group()))} ", text)
    # Keep letters (any script) and spaces; other punctuation (։ ՝ , - / …) separates words.
    text = "".join(ch if ch.isalpha() or ch.isspace() else " " for ch in text)
    return " ".join(text.split())


def edit_distance(ref: list | str, hyp: list | str) -> int:
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1]


def char_errors(ref: str, hyp: str) -> tuple[int, int]:
    """-> (character edits, reference length) on normalised text, spaces included."""
    r, h = normalize(ref), normalize(hyp)
    return edit_distance(r, h), len(r)


def word_errors(ref: str, hyp: str) -> tuple[int, int]:
    r, h = normalize(ref).split(), normalize(hyp).split()
    return edit_distance(r, h), len(r)
