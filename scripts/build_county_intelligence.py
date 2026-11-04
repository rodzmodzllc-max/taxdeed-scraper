#!/usr/bin/env python3
"""Build public/county-intelligence.json (harvesters/sources/county_intel.py).

Value-free: source names, publishers, URLs, publication and verification
states, and whether a county's acquisition process and financial terms have
been verified - never a property row. Rebuild it after editing the registry,
either purchase-path evidence table, the Available financial terms or a
discovery-candidate file; ``--check`` fails when it is stale.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from harvesters.sources import county_intel as CI  # noqa: E402

OUT = REPO / "public" / "county-intelligence.json"


def render() -> str:
    doc = CI.build()
    bad = CI.problems(doc)
    if bad:
        raise SystemExit("county intelligence problems:\n" + "\n".join(bad))
    return json.dumps(doc, indent=None, separators=(",", ":"), sort_keys=True, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    text = render()
    if a.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("public/county-intelligence.json is stale - run scripts/build_county_intelligence.py")
            return 1
        print("public/county-intelligence.json is current")
        return 0
    OUT.write_text(text, encoding="utf-8")
    doc = json.loads(text)
    n = sum(len(s["counties"]) for s in doc["states"])
    print(f"wrote {OUT.relative_to(REPO)} ({len(doc['states'])} states, {n} counties)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
