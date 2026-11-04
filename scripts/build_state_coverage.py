#!/usr/bin/env python3
"""Generate data/current_state/state-coverage.json and docs/state-coverage.md
from the repository's records (harvesters/governance/state_coverage.py).
`--check` fails when either file is not what the current inputs produce.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harvesters.governance import state_coverage as SC  # noqa: E402

JSON_OUT = REPO / "data" / "current_state" / "state-coverage.json"
MD_OUT = REPO / "docs" / "state-coverage.md"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    doc = SC.build()
    text = json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    md = SC.render_markdown(doc)
    if args.check:
        stale = [p.relative_to(REPO) for p, want in ((JSON_OUT, text), (MD_OUT, md)) if not p.is_file() or p.read_text(encoding="utf-8") != want]
        if stale:
            print("stale: " + ", ".join(map(str, stale)) + " - run scripts/build_state_coverage.py")
            return 1
        print("state coverage is current")
        return 0
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(text, encoding="utf-8")
    MD_OUT.write_text(md, encoding="utf-8")
    print(f"wrote {JSON_OUT.relative_to(REPO)} and {MD_OUT.relative_to(REPO)}; summary {doc['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
