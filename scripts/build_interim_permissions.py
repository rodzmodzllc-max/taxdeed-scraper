#!/usr/bin/env python3
"""Write data/current_state/interim-permissions.json + docs/interim-permissions.md
(harvesters/governance/interim_permissions.py). --check compares both to disk.

Lists every interim allowance with its scope, evidence, dates, conditions and
the code that enforces it. Allows, renews or changes nothing."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harvesters.governance import interim_permissions as IP  # noqa: E402

OUT_JSON = REPO / "data" / "current_state" / "interim-permissions.json"
OUT_MD = REPO / "docs" / "interim-permissions.md"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    doc = IP.build()
    text = json.dumps(doc, indent=1, sort_keys=True) + "\n"
    md = IP.render_markdown(doc)
    if a.check:
        ok = OUT_JSON.is_file() and OUT_JSON.read_text(encoding="utf-8") == text and OUT_MD.is_file() and OUT_MD.read_text(encoding="utf-8") == md
        print("interim permissions are current" if ok else "interim permissions are STALE - run scripts/build_interim_permissions.py")
        return 0 if ok else 1
    OUT_JSON.write_text(text, encoding="utf-8")
    OUT_MD.write_text(md, encoding="utf-8")
    s = doc["summary"]
    print(f"wrote {OUT_JSON.relative_to(REPO)} and {OUT_MD.relative_to(REPO)}: {s['records']} interim records, "
          f"expiry {s['by_expiry']}, findings {s['by_finding']}")
    return 0 if doc["config_error"] is None else 1


if __name__ == "__main__":
    sys.exit(main())
