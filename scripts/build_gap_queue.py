#!/usr/bin/env python3
"""Write data/current_state/gap-queue.json + docs/gap-queue.md
(harvesters/governance/gap_queue.py). --check compares both to disk."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harvesters.governance import gap_queue as GQ  # noqa: E402

OUT_JSON = REPO / "data" / "current_state" / "gap-queue.json"
OUT_MD = REPO / "docs" / "gap-queue.md"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    doc = GQ.build()
    text = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    md = GQ.render_markdown(doc)
    if a.check:
        ok = OUT_JSON.is_file() and OUT_JSON.read_text(encoding="utf-8") == text and OUT_MD.is_file() and OUT_MD.read_text(encoding="utf-8") == md
        print("gap queue is current" if ok else "gap queue is STALE - run scripts/build_gap_queue.py")
        return 0 if ok else 1
    OUT_JSON.write_text(text, encoding="utf-8")
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(REPO)} and {OUT_MD.relative_to(REPO)}: {len(doc['units'])} units, "
          f"by category {doc['summary']['by_category']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
