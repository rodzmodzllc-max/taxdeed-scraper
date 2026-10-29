#!/usr/bin/env python3
"""Write public/buyers-guide.json (docs/buyers-guide-contract.md) from
data/buyers_guide_questions.csv, data/buyers_guide_answers.csv and
data/buyers_guide_captures.csv (harvesters/sources/buyers_guide.py).

  python3 scripts/build_buyers_guide.py           # write it (and the root copy)
  python3 scripts/build_buyers_guide.py --check   # fail on a rule problem or a stale file
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harvesters.sources import buyers_guide as G  # noqa: E402

OUT = REPO / "public" / "buyers-guide.json"
ROOT_COPY = REPO / "buyers-guide.json"


def main(argv: list[str]) -> int:
    bad = G.problems()
    if bad:
        print("\n".join(bad))
        return 1
    text = G.render()
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("public/buyers-guide.json is stale - run scripts/build_buyers_guide.py")
            return 1
        print("public/buyers-guide.json is current")
        return 0
    OUT.write_text(text, encoding="utf-8")
    ROOT_COPY.write_text(text, encoding="utf-8")
    c = G.build()["counts"]
    print(f"wrote {OUT.relative_to(REPO)}: " + ", ".join(f"{k} {v}" for k, v in c.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
