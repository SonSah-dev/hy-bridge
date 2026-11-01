"""Fix-ups applied to the Armenian ASR text before translation (DECISIONS.md D-016).

Step 4 showed two ASR -> MT failure patterns (D-015):
  - English terms that the ASR writes in Armenian letters are mistranslated
    (`փրադաքշ` -> "drill"). A user-editable glossary maps such spellings back to the term;
    an Armenian case ending is kept after a hyphen, as in written Armenian (`Python-ը`).
  - Spelled-out years and counts are misread (`երկու հազար քսաներկու` -> "1922").
    Number words worth 10 or more become digits, which NLLB translates correctly.
Single small numbers (`մեկ`, `չորս`) are left alone: `մեկ` also means "one/someone", and
NLLB already handles them.

Names (D-021): NLLB mistranslates many Armenian-letter names (`Սաթենիկ` -> "Satan",
`Լուսինեն` -> "Lune") but keeps Latin ones. A user-editable names list (same format and
matching as the glossary) turns them into Latin letters, and the endearment `ջան` after a
name is dropped, because NLLB read "Satenik ջան" as "Mr. Satenik".
"""
from __future__ import annotations

import re
from pathlib import Path

from .scoring import _ONES, _TEENS, _TENS, edit_distance

ARM = "Ա-Ֆա-և"                # letters only; ՝ ՛ ՞ ՜ sit between the two ranges
SUFFIXES = ("ներում", "ներից", "ների", "ները", "ներ", "ում", "ից", "ով", "ին", "ի", "ը", "ն")
_TOKEN = re.compile(rf"[{ARM}]+|[^{ARM}]+")


def load_glossary(path: str | Path) -> list[tuple[str, str]]:
    """TSV: `<Armenian-letter spelling>\\t<term>`; '#' starts a comment. Longest spellings first."""
    entries = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        src, sep, dst = line.partition("\t")
        if not sep or not src.strip() or not dst.strip():
            raise ValueError(f"{path} line {n}: expected '<spelling><TAB><term>'")
        entries.append((src.strip().lower(), dst.strip()))
    return sorted(entries, key=lambda e: -len(e[0]))


def apply_glossary(text: str, entries: list[tuple[str, str]], fuzzy: bool = True,
                   fuzzy_needs_capital: bool = False) -> str:
    suffix = "|".join(SUFFIXES)
    for src, dst in entries:
        stem = r"\s+".join(map(re.escape, src.split()))
        pat = re.compile(rf"(?<![{ARM}A-Za-z]){stem}({suffix})?(?![{ARM}])", re.IGNORECASE)
        text = pat.sub(lambda m: dst + (f"-{m.group(1)}" if m.group(1) else ""), text)
    return _fuzzy_glossary(text, entries, fuzzy_needs_capital) if fuzzy else text


# The ASR spells a term differently almost every time (live runs, D-018): version control came
# out as `վերժեն քընթրոլ`, `վերժան քընթրոլ`, `վեժին քընթրոլ`, `Վժըն քընթռոլ`. So glossary
# words of FUZZY_GLOSSARY_MIN letters or more also match misspellings: one letter off for a
# single-word entry; up to len/3 letters per word (same first letter) for multi-word entries,
# where all words matching together is distinctive. Shorter words (`գիթ`) stay exact, so
# `գիծ` ("line") never becomes Git, and `Ամառն` ("summer") is not Amazon.
FUZZY_GLOSSARY_MIN = 6        # 5-letter `այթին` (Python) matched the unrelated `Այնին`


def _glossary_word(entry: str, word: str, loose: bool) -> tuple[int, str] | None:
    """(distance, case ending) if `word` is `entry` (possibly misspelt) plus an optional ending."""
    w, e = word.lower(), entry
    le = _letters(e)
    best = None
    for suf in ("", *SUFFIXES):
        if suf and not w.endswith(suf):
            continue
        stem = w[: len(w) - len(suf)] if suf else w
        if not stem:
            continue
        d = edit_distance(le, _letters(stem))
        limit = len(le) // 3 if loose else 1
        # misspellings keep the first letter: FLEURS had `Լայթեն` (Layton) ~ `փայթեն` (Python) (D-024)
        ok = d == 0 or (len(le) >= FUZZY_GLOSSARY_MIN and d <= limit and stem[0] == e[0])
        if ok and (best is None or d < best[0]):
            best = (d, suf)
    return best


def _fuzzy_glossary(text: str, entries: list[tuple[str, str]], needs_capital: bool = False) -> str:
    tokens = _TOKEN.findall(text)
    alpha = [i for i, t in enumerate(tokens) if t[0] in _ALPHA]
    out, pos, n = [], 0, 0
    while n < len(alpha):
        done = False
        for src, dst in entries:
            ws = src.split()
            span = alpha[n:n + len(ws)]
            if len(span) < len(ws) or any(not all(tokens[k].isspace() for k in range(a + 1, b))
                                          for a, b in zip(span, span[1:])):
                continue
            if needs_capital and not tokens[span[0]][0].isupper():
                continue
            matches = [_glossary_word(e, tokens[i], loose=len(ws) > 1) for e, i in zip(ws, span)]
            # every word must match; only the last may carry an ending
            if all(m is not None for m in matches) and all(m[1] == "" for m in matches[:-1])                     and sum(m[0] for m in matches) > 0:
                suf = matches[-1][1]
                out.extend(tokens[pos:span[0]])
                out.append(dst + (f"-{suf}" if suf else ""))
                pos, n, done = span[-1] + 1, n + len(ws), True
                break
        if not done:
            n += 1
    out.extend(tokens[pos:])
    return "".join(out)


# ----------------------------------------------------------------- numbers
#
# Live runs (D-017) showed ASR number words that are slightly off (`քառասոուն`, `ութսանութ`,
# `ին` for `ինը`) and stutters (`հինինգ`). Converting what parses and leaving the rest gave
# confidently wrong digits ("1000 ին 188", 570000 -> 170000). So: accept one-letter variants
# of long number words, and convert nothing when a garbled number word is next to the phrase.

_VALUES = {w: i for i, w in enumerate(_ONES) if w}
_VALUES.update({w: 10 + i for i, w in enumerate(_TEENS)})
_VALUES["տաս"] = 10
for t, tw in enumerate(_TENS):
    if tw:
        _VALUES[tw] = 10 * t
        for o, ow in enumerate(_ONES):
            if ow:
                _VALUES[tw + ow] = 10 * t + o
                _VALUES[tw + "ու" + ow] = 10 * t + o      # քսանուերեք (spoken "twenty and three")
_SCALES = {"հարյուր": 100, "հազար": 1000}
FUZZY_MIN_LEN = 6      # one-letter variants accepted only for words this long (not համար ~ հազար)
NEAR_MIN_LEN = 6       # words this long within 2 letters of a number word block conversion


def _letters(w: str) -> str:
    return w.replace("ու", "ü")  # the vowel ու is one letter written with two characters


_VOCAB = {_letters(v): v for v in (*_VALUES, *_SCALES)}


def canonical(word: str) -> str | None:
    """Number word for `word`, allowing one wrong letter in long words; None if not a number."""
    w = word.lower()
    if w in _VALUES or w in _SCALES:
        return w
    lw = _letters(w)
    if len(lw) >= FUZZY_MIN_LEN:
        close = [v for k, v in _VOCAB.items() if abs(len(k) - len(lw)) <= 1 and edit_distance(k, lw) == 1]
        if len(close) == 1:
            return close[0]
    return None


def near_number(word: str) -> bool:
    """A garbled number word (e.g. the stutter `հինինգ`) that we cannot read safely."""
    w = word.lower()
    lw = _letters(w)
    if canonical(w) is not None or len(lw) < NEAR_MIN_LEN:
        return False
    return any(abs(len(k) - len(lw)) <= 2 and edit_distance(k, lw) <= 2 for k in _VOCAB if len(k) >= 4)


def _unsafe_neighbour(word: str) -> bool:
    return canonical(word) is not None or near_number(word) or word.lower() == "ին"


def _split_glued(word: str) -> list[str]:
    """'երկուհազար' / 'երկուազար' (h dropped in speech) -> ['երկու', 'հազար']."""
    for tail in ("հազար", "ազար", "հարյուր"):
        head = word[: -len(tail)]
        if word.endswith(tail) and head in _VALUES:
            return [head, "հազար" if tail.endswith("ազար") else tail]
    return [word]


def _parse(words: list[str]) -> tuple[int, int] | None:
    """Longest prefix of canonical number words that reads as one number -> (value, words used)."""
    total = current = used = 0
    for i, w in enumerate(words):
        if w in _SCALES:
            if w == "հազար":
                total += (current or 1) * 1000
                current = 0
            else:
                if current % 100:
                    current = current - current % 100 + (current % 100) * 100
                else:
                    current += 100
        elif w in _VALUES:
            v = _VALUES[w]
            if current % 100 and (v >= 10 or current % 10):
                break  # "two three" is two numbers, not five
            current += v
        else:
            break
        used = i + 1
    return (total + current, used) if used else None


def numbers_to_digits(text: str, minimum: int = 10) -> str:
    tokens = []
    for tok in _TOKEN.findall(text):
        tokens.extend(_split_glued(tok) if tok[0] in _ALPHA else [tok])
    alpha = [i for i, tok in enumerate(tokens) if tok[0] in _ALPHA]

    def joined(a: int, b: int) -> bool:  # only whitespace between tokens a and b
        return all(tokens[k].isspace() for k in range(a + 1, b))

    out, pos, n = [], 0, 0
    while n < len(alpha):
        i = alpha[n]
        # the run of words joined by whitespace starting here
        run = [i]
        while n + len(run) < len(alpha) and joined(run[-1], alpha[n + len(run)]):
            run.append(alpha[n + len(run)])
        canon, exact = [], False
        for k, idx in enumerate(run):
            c = canonical(tokens[idx])
            if c is None and tokens[idx].lower() == "ին" and k + 1 < len(run)                     and canonical(tokens[run[k + 1]]) in _SCALES:
                c = "ինը"                                  # ASR drops the final ը before a scale
            if c is None:
                break
            exact = exact or tokens[idx].lower() == c
            canon.append(c)
        parsed = _parse(canon) if canon else None
        if parsed and parsed[0] >= minimum and exact:   # variants only next to a correctly spelled one
            value, used = parsed
            # a number word we could not read, right before or after: leave all the words alone
            prev_bad = n > 0 and joined(alpha[n - 1], i) and _unsafe_neighbour(tokens[alpha[n - 1]])
            nxt = run[used] if used < len(run) else None
            next_bad = nxt is not None and _unsafe_neighbour(tokens[nxt])
            if not prev_bad and not next_bad:
                out.extend(tokens[pos:i])
                out.append(str(value))
                pos = run[used - 1] + 1
                n += used
                continue
        n += 1
    out.extend(tokens[pos:])
    return "".join(out)


# ----------------------------------------------------------------- clock times (D-025)
#
# NLLB reads spoken times badly (`ութն անց կես` -> "after eight and a half") but digits well
# (`Ժամը 8:30 է` -> "It's 8:30."). `<hour> անց <minutes>` becomes H:MM. The hour takes the
# connective ն/ը (ութն, ինն, տասն); minutes are կես (30), քառորդ (15) or number words; an ending
# -ին ("at") on the minutes is kept as in written Armenian (8:30-ին). Garbled hours are left alone.

_HOURS = {w: v for w, v in _VALUES.items() if 1 <= v <= 12 and "ու" not in w[1:]}
_HOURS.update({"երկուս": 2, "տասներկուս": 12, "ինն": 9, "տասն": 10})
# the ASR often glues the hour onto անց (`ութնանց`, `ութանց`): the space is optional (D-026)
_TIME = re.compile(rf"(?<![{ARM}])([{ARM}]+?)\s*անց\s+((?:[{ARM}]+\s+)?[{ARM}]+)(?![{ARM}])", re.IGNORECASE)


def _hour(word: str) -> int | None:
    w = word.lower()
    for cand in (w, w[:-1] if w[-1:] in "նը" else None, w[:-1] + "ը" if w.endswith("ն") else None):
        if cand and cand in _HOURS:
            return _HOURS[cand]
    return None


def _minutes(words: str) -> tuple[int, str] | None:
    ws = words.lower().split()
    ending = ""
    for suf in ("ին", "ը"):
        if ws[-1].endswith(suf) and len(ws[-1]) > len(suf) + 1:
            base = ws[-1][: -len(suf)]
            if base in ("կես", "քառորդ") or canonical(base) or canonical(base + "ը"):
                ws[-1], ending = base, suf
                break
    if ws == ["կես"]:
        return 30, ending
    if ws == ["քառորդ"]:
        return 15, ending
    canon = [canonical(w) or canonical(w + "ը") for w in ws]
    if None in canon:
        return None
    parsed = _parse(canon)
    if parsed and parsed[1] == len(canon) and 1 <= parsed[0] <= 59:
        return parsed[0], ending
    return None


def times_to_digits(text: str) -> str:
    def repl(m: re.Match) -> str:
        h = _hour(m.group(1))
        words, rest = m.group(2), ""
        mins = _minutes(words)
        if mins is None and " " in words.strip():          # "կես է": only the first word is minutes
            first, sep, rest = words.partition(" ")
            words, rest = first, sep + rest
            mins = _minutes(words)
        if h is None or mins is None:
            return m.group(0)
        value, ending = mins
        return f"{h}:{value:02d}" + ("-ին" if ending == "ին" else "") + rest
    return _TIME.sub(repl, text)


# The ASR writes the spoken abbreviation "կգ" as `կոգ` (two mic tests, D-026); only after a number.
_UNIT_AFTER_NUMBER = re.compile(rf"(\d)\s+կոգ(?![{ARM}])", re.IGNORECASE)


# NLLB translates the Armenian currency դրամ as "drachma(s)" ("Coffee costs 500 drachmas") but keeps
# "AMD" ("costs 500 AMD"). Only directly after a number: on its own դրամ also means "money" (D-029).
_DRAM_AFTER_NUMBER = re.compile(rf"(\d)\s+դրամ({'|'.join(SUFFIXES)})?(?![{ARM}])", re.IGNORECASE)


def units_after_numbers(text: str) -> str:
    text = _UNIT_AFTER_NUMBER.sub(r"\1 կգ", text)
    return _DRAM_AFTER_NUMBER.sub(lambda m: f"{m.group(1)} AMD" + (f"-{m.group(2)}" if m.group(2) else ""), text)


# The mic's noise gate (Intel Smart Sound) cuts the quiet voiced start of a phrase, so `Բարեւ ձեզ`
# is heard as `Հարեւ`, `Պարեւ`, `Տարեւ`, `Այարեւ`, `Այեւ`, `Հեւ`, `Հեք`, `Հովհեւ` ... `ձեզ`/`ծեզ`
# (D-032). Only the first word of a segment, directly before ձեզ; apart from Արեւ (sun) none is a
# word. `Նաեւ ձեզ` (to you too) and `Ձեզ եւս` are real phrases and stay.
_GREETING = re.compile(rf"^(\W*)(?:(?:[ՀՊՏՎ]ա|Այա|Հարա|Ա)?(?:րեւ|յեւ)|Հե[ւքց]|Հովհեւ)\s+[ձծ]եզ(?![{ARM}])",
                       re.IGNORECASE)


def fix_greeting(text: str) -> str:
    return _GREETING.sub(r"\1Բարեւ ձեզ", text)


# A short non-speech sound that the recognizer writes as `Հովհ` (with the call silent, and as call
# echo, D-030), shown as invented English ("How can we do this?", "John: What is it?"). As a whole
# segment it is noise and is not shown (D-032).
_NOISE = re.compile(r"\W*Հովհ(?:\s+[էծ])?\W*", re.IGNORECASE)


def is_noise(text: str) -> bool:
    return _NOISE.fullmatch(text) is not None


_ALPHA = set(re.findall(rf"[{ARM}]", "".join(map(chr, range(0x0531, 0x0588)))))


ENDEARMENT = "ջան"
_LATIN_THEN_JAN = re.compile(rf"([A-Za-z][A-Za-z{ARM}-]*)\s+{ENDEARMENT}(?![{ARM}])", re.IGNORECASE)


def apply_names(text: str, entries: list[tuple[str, str]]) -> str:
    """Armenian-letter names -> Latin (endings kept, as the glossary); drop ջան after a name."""
    spellings = {src for src, _ in entries}
    def unglue(m: re.Match) -> str:                      # Սոնաջան -> Սոնա (ASR glues it on)
        return m.group(1) if m.group(1).lower() in spellings else m.group(0)
    text = re.sub(rf"(?<![{ARM}])([{ARM}]+?){ENDEARMENT}(?![{ARM}])", unglue, text, flags=re.IGNORECASE)
    # a misspelt name must be capitalised: FLEURS had `լուսինն` ("the moon") ~ Լուսինե (D-024)
    text = apply_glossary(text, entries, fuzzy_needs_capital=True)
    return _LATIN_THEN_JAN.sub(r"\1", text)


# ----------------------------------------------------------------- gazetteer (D-026)
#
# Places in Armenia, notable people and given names with their English spellings, from Wikidata
# (CC0; built by eval/build_gazetteer.py). NLLB mistranslates names it does not know (`Դսեղ` ->
# "Dusseh", `Հովհաննես Թումանյան` -> "John Tumanyan"). Unlike names.tsv this list is large and
# not curated, so matching is strict: exact words only, the first word capitalised, an ending
# allowed on the last word, and a single word must not start the sentence (ordinary words are
# capitalised there) and must have at least GAZETTEER_MIN_LETTERS letters.
GAZETTEER_MIN_LETTERS = 4
_SENTENCE_END = set("։.?!:")


def _gkey(word: str) -> str:
    return word.lower().replace("և", "եւ")


class Gazetteer:
    def __init__(self, path: str | Path | None):
        self.entries: dict[tuple[str, ...], str] = {}
        if path:
            for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip() or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    raise ValueError(f"{path} line {n}: expected '<Armenian><TAB><English>[<TAB>kind]'")
                key = tuple(_gkey(w) for w in parts[0].split())
                self.entries.setdefault(key, parts[1].strip())
        self.max_words = max((len(k) for k in self.entries), default=0)

    def __call__(self, text: str) -> str:
        if not self.entries:
            return text
        tokens = _TOKEN.findall(text)
        alpha = [i for i, t in enumerate(tokens) if t[0] in _ALPHA]
        out, pos, n = [], 0, 0
        while n < len(alpha):
            hit = self._match(tokens, alpha, n)
            if hit is None:
                n += 1
                continue
            used, english, suffix = hit
            out.extend(tokens[pos:alpha[n]])
            out.append(english + (f"-{suffix}" if suffix else ""))
            pos, n = alpha[n + used - 1] + 1, n + used
        out.extend(tokens[pos:])
        return "".join(out)

    def _match(self, tokens: list[str], alpha: list[int], n: int) -> tuple[int, str, str] | None:
        first = tokens[alpha[n]]
        if not first[0].isupper():
            return None
        before = "".join(tokens[:alpha[n]]).rstrip()
        sentence_start = not before or before[-1] in _SENTENCE_END
        for size in range(min(self.max_words, len(alpha) - n), 0, -1):
            span = alpha[n:n + size]
            if any(not all(tokens[k].isspace() for k in range(a + 1, b)) for a, b in zip(span, span[1:])):
                continue
            words = [_gkey(tokens[i]) for i in span]
            if size == 1 and (sentence_start or len(_letters(words[0])) < GAZETTEER_MIN_LETTERS):
                continue
            for suf in ("", *SUFFIXES):
                last = words[-1]
                if suf and not (last.endswith(suf) and len(last) > len(suf) + 1):
                    continue
                key = tuple(words[:-1]) + (last[: len(last) - len(suf)] if suf else last,)
                if key in self.entries:
                    return size, self.entries[key], suf
        return None


class TextFixer:
    def __init__(self, glossary: str | Path | None, numbers: bool = True, names: str | Path | None = None,
                 gazetteer: str | Path | None = None):
        self.entries = load_glossary(glossary) if glossary else []
        self.names = load_glossary(names) if names else []
        self.gazetteer = Gazetteer(gazetteer)
        self.numbers = numbers

    def __call__(self, text: str) -> str:
        text = fix_greeting(text)
        if self.entries:
            text = apply_glossary(text, self.entries)
        if self.names:
            text = apply_names(text, self.names)
        text = self.gazetteer(text)                     # after the user's own names list
        if self.numbers:
            text = units_after_numbers(numbers_to_digits(times_to_digits(text)))
        return text
