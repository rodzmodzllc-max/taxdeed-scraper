#!/usr/bin/env python3
"""Append owner-accepted INTERIM permission records (owner decision
2026-10-26) to data/source_permissions.csv for sources of the new-sources
sprint - idempotent: a (source_id, dataset, jurisdiction, operation) record
already present is left as it is, never rewritten.

    python3 scripts/add_owner_interim_permissions.py SOURCE_ID "Provider name" ST [--ops discover,fetch,parse,store]

The records say exactly what they are: an internal risk acceptance by the
product owner (INTERNAL_RISK_ACCEPTANCE under OWNER_PERMISSION_REQUIRED),
dated 2026-10-26 and expiring 2027-04-12 - never a grant, never display.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CSV_PATH = REPO / "data" / "source_permissions.csv"
DECISION = "2026-10-26"
EXPIRES = "2027-04-12"
REVIEWER = "product owner (decision 2026-10-26: collect every property from every source; legal review to follow)"
REASON = ("Owner decision 2026-10-26 ('find every property and every source, and then we'll work on the legal'): terms / "
          "licensing risk accepted for collection; collected for admin review only and labelled UNREVIEWED. No customer "
          "display is recorded, so display is denied until written permission and an admin review exist.")
DEFAULT_OPS = ("discover", "fetch", "parse", "store")


def add(source_id: str, provider: str, state: str, ops=DEFAULT_OPS, path: Path = CSV_PATH) -> int:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames
        rows = list(reader)
    have = {(r["source_id"], r["dataset"], r["jurisdiction"], r["operation"]) for r in rows}
    new = []
    for op in ops:
        if (source_id, "*", state, op) in have:
            continue
        new.append({
            "source_id": source_id, "provider": provider, "dataset": "*", "publisher": provider, "jurisdiction": state,
            "operation": op, "status": "OWNER_PERMISSION_REQUIRED", "evidence_type": "INTERNAL_RISK_ACCEPTANCE",
            "evidence_ref": f"data/county_source_registry.csv {source_id}; docs/new-sources-2026-10-26.md (owner decision {DECISION})",
            "evidence_date": DECISION, "reviewer": REVIEWER, "effective_on": DECISION, "expires_on": EXPIRES,
            "conditions": "", "attribution": "", "last_verified_on": DECISION, "reason": REASON,
        })
    if new:
        with path.open("a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
            for r in new:
                w.writerow(r)
    return len(new)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("source_id")
    ap.add_argument("provider")
    ap.add_argument("state")
    ap.add_argument("--ops", default=",".join(DEFAULT_OPS))
    a = ap.parse_args(argv)
    n = add(a.source_id, a.provider, a.state.upper(), tuple(o.strip() for o in a.ops.split(",") if o.strip()))
    print(f"{a.source_id}: {n} record(s) added")
    return 0


if __name__ == "__main__":
    sys.exit(main())
