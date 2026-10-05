#!/usr/bin/env python3
"""Write public/available-terms.json from data/available_financial_terms.csv
(harvesters/sources/available_terms.py). --check fails if it is stale or the
table has a problem."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harvesters.sources import available_terms as T  # noqa: E402

OUT = REPO / "public" / "available-terms.json"


def main(argv: list[str]) -> int:
    bad = T.problems()
    if bad:
        print("\n".join(bad))
        return 1
    text = T.render()
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("public/available-terms.json is stale - run scripts/build_available_terms.py")
            return 1
        print("public/available-terms.json is current")
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({len(T.load())} terms)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
