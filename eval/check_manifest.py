"""Step 2 exit check: validate the evaluation set (DECISIONS.md D-012).

    python eval/check_manifest.py            # strict: every clip needs hy and en text
    python eval/check_manifest.py --draft    # while recording: missing text is a warning

Exit code 0 when there are no errors. Warnings (length targets, clipping) do not fail.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from armtranslate.evalset import check  # noqa: E402

HERE = Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(HERE / "manifest.jsonl"))
    ap.add_argument("--draft", action="store_true", help="treat missing reference text as warnings")
    args = ap.parse_args()
    sys.stdout.reconfigure(errors="replace")

    r = check(args.manifest, draft=args.draft)
    for k, v in r.summary.items():
        print(f"{k:>14}: {v}")
    for w in r.warnings:
        print(f"WARN   {w}")
    for e in r.errors:
        print(f"ERROR  {e}")
    print(f"\n{'PASS' if r.ok else 'FAIL'}: {len(r.errors)} error(s), {len(r.warnings)} warning(s)"
          + (" [draft mode]" if args.draft else ""))
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
