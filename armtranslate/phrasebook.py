"""Short replies: phrasebook lookup and name transliteration (DECISIONS.md D-017).

NLLB-600M hallucinates on 1-3 word inputs, whatever the beam or punctuation (live Step 5
runs: `Հաջողություն։` -> "What is the meaning of life?"). Short segments are first looked
up in a user-editable phrasebook. A greeting followed by capitalised words is treated as
greeting + name(s), and the names are transliterated: `Ողջույն Սոնա ջան` -> "Hello, Sona."
The endearment `ջան` ("dear") is dropped when other words remain.
"""
from __future__ import annotations

import re
from pathlib import Path

from .textfix import ARM

MAX_WORDS = 3
ENDEARMENT = "ջան"
_WORD = re.compile(rf"[{ARM}A-Za-z]+(?:-[{ARM}A-Za-z]+)?")
_UPPER = re.compile(r"[Ա-ՖA-Z]")            # Latin: a name already fixed by names.tsv (D-021)

_TRANSLIT = {
    "ա": "a", "բ": "b", "գ": "g", "դ": "d", "ե": "e", "զ": "z", "է": "e", "ը": "y", "թ": "t",
    "ժ": "zh", "ի": "i", "լ": "l", "խ": "kh", "ծ": "ts", "կ": "k", "հ": "h", "ձ": "dz", "ղ": "gh",
    "ճ": "ch", "մ": "m", "յ": "y", "ն": "n", "շ": "sh", "ո": "o", "չ": "ch", "պ": "p", "ջ": "j",
    "ռ": "r", "ս": "s", "վ": "v", "տ": "t", "ր": "r", "ց": "ts", "ւ": "v", "փ": "p", "ք": "k",
    "օ": "o", "ֆ": "f", "և": "ev",
}


def transliterate(word: str) -> str:
    """Armenian name -> Latin letters, e.g. Սոնա -> Sona, Երևան -> Yerevan."""
    w = word.lower().replace("ու", "u")
    out = []
    for i, ch in enumerate(w):
        if i == 0 and ch == "ե":
            out.append("ye")
        elif i == 0 and ch == "ո":
            out.append("vo")
        else:
            out.append(_TRANSLIT.get(ch, ch))
    return "".join(out).capitalize()


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def _key(ws: list[str]) -> str:
    return " ".join(w.lower().replace("և", "եւ") for w in ws)


class Phrasebook:
    def __init__(self, path: str | Path | None):
        self.entries: dict[str, str] = {}
        if path:
            for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
                line = line.split("#", 1)[0].rstrip()
                if not line.strip():
                    continue
                hy, sep, en = line.partition("\t")
                if not sep or not hy.strip() or not en.strip():
                    raise ValueError(f"{path} line {n}: expected '<Armenian><TAB><English>'")
                self.entries[_key(words(hy))] = en.strip()

    def lookup(self, text: str) -> str | None:
        """English for a short reply, or None to fall back to MT."""
        ws = words(text)
        if not ws or len(ws) > MAX_WORDS + 1:
            return None
        if len(ws) > 1:
            ws = [w for w in ws if w.lower() != ENDEARMENT] or ws
        if len(ws) > MAX_WORDS:
            return None
        whole = self.entries.get(_key(ws))
        if whole is not None:
            return whole
        # phrase + capitalised name(s): "Ողջույն Սոնա" -> "Hello, Sona."
        for n in range(len(ws) - 1, 0, -1):
            head = self.entries.get(_key(ws[:n]))
            names = ws[n:]
            if head is not None and all(_UPPER.match(w) for w in names):
                # the ASR sometimes glues the endearment on: Սոնաջան -> Սոնա
                names = [w[: -len(ENDEARMENT)] if w.lower().endswith(ENDEARMENT) and len(w) > len(ENDEARMENT) + 1
                         else w for w in names]
                return f"{head.rstrip('.!?')}, {' '.join(transliterate(w) for w in names)}."
        return None
