"""Build gazetteer.tsv from Wikidata (CC0): Armenian name -> English spelling (D-026).

    python eval/build_gazetteer.py            # about 700 API calls, a few minutes
    python eval/build_gazetteer.py --reclean  # re-apply the label cleaning to gazetteer.tsv only

Uses the Wikidata Action API (search with `haswbstatement`, then `wbgetentities` for labels),
because the SPARQL service was rate-limited during the build. Sets:
  - place:  items located in Armenia (P17=Q399) with coordinates;
  - person: humans with Armenian citizenship (P27=Q399) or Armenian ethnicity (P172=Q79797);
            the full name, plus the surname alone when it is a -յան/-yan pair;
  - given:  male and female given names with an Armenian label.
Labels are cleaned (no parentheses, no text after a comma, Armenian letters only on the left,
plain Latin on the right, 1-3 words); an Armenian key that maps to several English spellings
keeps the most frequent one. The text pipeline matches entries strictly (armtranslate/textfix.py).
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "gazetteer.tsv"
API = "https://www.wikidata.org/w/api.php"
UA = {"User-Agent": "armenian-live-translate/0.1 (offline gazetteer build; github.com/SonSah-dev)"}
SETS = {
    "place": ["haswbstatement:P17=Q399 haswbstatement:P625"],
    "person": ["haswbstatement:P31=Q5 haswbstatement:P27=Q399", "haswbstatement:P31=Q5 haswbstatement:P172=Q79797"],
    "given": ["haswbstatement:P31=Q12308941 haslabel:hy", "haswbstatement:P31=Q11879590 haslabel:hy"],
}
_HY = re.compile(r"^[Ա-Ֆա-և]+(?:[ -][Ա-Ֆա-և]+){0,2}$")
_EN = re.compile(r"^[A-Za-z][A-Za-z'\-]*(?: [A-Za-z][A-Za-z'\-]*){0,3}$")


def api(params: dict) -> dict:
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    for attempt in range(5):
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60))
        except Exception as e:  # noqa: BLE001 - transient network errors: back off and retry
            print(f"  retry {attempt + 1}: {type(e).__name__}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Wikidata API failed: {params}")


def search_ids(query: str) -> list[str]:
    ids, offset = [], 0
    while offset is not None and offset < 10_000:            # CirrusSearch stops at 10,000
        r = api({"action": "query", "list": "search", "srsearch": query, "srnamespace": 0,
                 "srlimit": 500, "sroffset": offset, "srprop": ""})
        if "query" not in r:                                   # e.g. the search window is exhausted
            print(f"  stopped at offset {offset}: {r.get('error', r)}", file=sys.stderr)
            break
        ids += [h["title"] for h in r["query"]["search"]]
        offset = r.get("continue", {}).get("sroffset")
        time.sleep(0.3)
    return ids


def labels(ids: list[str]) -> dict[str, tuple[str, str]]:
    out = {}
    for i in range(0, len(ids), 50):
        r = api({"action": "wbgetentities", "ids": "|".join(ids[i:i + 50]), "props": "labels",
                 "languages": "hy|en"})
        for qid, e in r.get("entities", {}).items():
            lab = e.get("labels", {})
            if "hy" in lab and "en" in lab:
                out[qid] = (lab["hy"]["value"], lab["en"]["value"])
        time.sleep(0.3)
    return out


_ADMIN_HY = re.compile(r"(մարզ|համայնք|շրջան)")
_ADMIN_EN = re.compile(r"\s+(Municipality|Province|Community|District|Rural Community)$", re.IGNORECASE)


def clean(hy: str, en: str) -> tuple[str, str] | None:
    hy = re.sub(r"\s*\(.*?\)", "", hy).split(",")[0].strip()
    en = re.sub(r"\s*\(.*?\)", "", en).split(",")[0].strip()
    if not _ADMIN_HY.search(hy):          # `Գյումրի` is the town: not "Gyumri Municipality"
        en = _ADMIN_EN.sub("", en)
    if not _HY.match(hy) or not _EN.match(en):
        return None
    return hy, en


def reclean() -> int:
    lines, changed = [], 0
    for line in OUT.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            lines.append(line)
            continue
        hy, en, kind = line.split("\t")
        c = clean(hy, en)
        if c is None:
            changed += 1
            continue
        changed += c[1] != en
        lines.append(f"{c[0]}\t{c[1]}\t{kind}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"recleaned {OUT.name}: {changed} entries changed or dropped")
    return 0


def main() -> int:
    if "--reclean" in sys.argv[1:]:
        return reclean()
    pairs: dict[str, dict[str, Counter]] = {k: defaultdict(Counter) for k in (*SETS, "surname")}
    for kind, queries in SETS.items():
        ids = sorted({i for q in queries for i in search_ids(q)})
        print(f"{kind}: {len(ids)} items", flush=True)
        for hy, en in labels(ids).values():
            c = clean(hy, en)
            if c is None:
                continue
            pairs[kind][c[0]][c[1]] += 1
            if kind == "person" and " " in c[0] and " " in c[1]:
                sh, se = c[0].split()[-1], c[1].split()[-1]
                if sh.endswith("յան") and se.lower().endswith(("yan", "ian")):
                    pairs["surname"][sh][se] += 1
        print(f"  {len(pairs[kind])} usable", flush=True)
    seen, lines = set(), []
    for kind in ("person", "place", "surname", "given"):     # earlier kinds win a shared key
        for hy, ens in sorted(pairs.get(kind, {}).items()):
            key = hy.lower().replace("և", "եւ")
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"{hy}\t{ens.most_common(1)[0][0]}\t{kind}")
    header = ("# Armenian name<TAB>English spelling<TAB>kind. Generated by eval/build_gazetteer.py from\n"
              "# Wikidata (CC0) on " + time.strftime("%Y-%m-%d") + "; do not edit by hand (use names.tsv). D-026.\n")
    OUT.write_text(header + "\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT.name}: {len(lines)} entries "
          f"({', '.join(f'{k} {sum(1 for l in lines if l.endswith(chr(9) + k))}' for k in ('person', 'place', 'surname', 'given'))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
