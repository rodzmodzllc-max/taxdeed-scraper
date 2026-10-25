#!/usr/bin/env python3
"""Command-line form of harvesters/governance/permissions.authorize(), for
entry points that cannot import the Python package - the Florida PowerShell
harvesters and syncs call it as their first statement and stop unless it
exits 0.

    python3 scripts/source_permission_check.py --source fl_realauction --operation fetch --operation parse --state FL --dataset sale_calendar
    python3 scripts/source_permission_check.py --source fl_laft_pdfs --source fl_laft_html --operation store --state FL
    python3 scripts/source_permission_check.py --due 30          # records whose allowance ends within 30 days
    python3 scripts/source_permission_check.py --source fl_realauction --operation fetch --operation parse --state FL --dataset sale_calendar --list-denied-counties data/realauction_counties.csv

--list-denied-counties CSV prints, one per line, every county in the CSV's
`County` column for which any requested check is denied (e.g. a county-level
RESTRICTED or link-only record); it prints nothing else. The statewide check
still decides the exit code, so a harvester skips only those counties.

Exit codes: 0 every requested check allowed; 3 any check denied or the
permission file is invalid / unreadable (fail closed); 2 usage error.
Prints one JSON decision per check (machine-readable, no data values).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

DENIED = 3


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", action="append", default=[], help="source_id (repeatable; every one must be allowed)")
    ap.add_argument("--operation", action="append", default=[],
                    help="discover / fetch / fetch_via_proxy / parse / store / enrich / display / redistribute / link (repeatable)")
    ap.add_argument("--state", help="two-letter state, or US")
    ap.add_argument("--county", default=None)
    ap.add_argument("--dataset", default=None)
    ap.add_argument("--permissions", default=None, help="alternate permission file (tests)")
    ap.add_argument("--due", type=int, default=None, help="list allowances ending within N days and exit 0")
    ap.add_argument("--list-denied-counties", default=None, metavar="CSV",
                    help="print the counties (CSV 'County' column) for which any requested check is denied")
    args = ap.parse_args(argv)
    try:
        from harvesters.governance import permissions as P
    except Exception as exc:  # noqa: BLE001 - no governance package means no permission
        print(json.dumps({"allowed": False, "reason_code": "GOVERNANCE_UNAVAILABLE", "reason": f"{type(exc).__name__}: {exc}"}))
        return DENIED
    perms = P.Permissions.from_file(Path(args.permissions) if args.permissions else None)
    if args.due is not None:
        if perms.error:
            print(json.dumps({"allowed": False, "reason_code": "CONFIG_INVALID", "reason": perms.error}))
            return DENIED
        for r in perms.due_for_review(args.due):
            print(json.dumps({"source_id": r.source_id, "dataset": r.dataset, "jurisdiction": r.jurisdiction,
                              "operation": r.operation, "basis": r.evidence_type, "expires_on": r.expires_on}))
        return 0
    if not args.source or not args.operation or not args.state:
        ap.error("--source, --operation and --state are required")
    if args.list_denied_counties:
        import csv  # noqa: PLC0415
        try:
            with open(args.list_denied_counties, newline="", encoding="utf-8") as f:
                counties = [(r.get("County") or "").strip() for r in csv.DictReader(f)]
        except OSError as exc:
            print(json.dumps({"allowed": False, "reason_code": "COUNTY_LIST_UNREADABLE", "reason": str(exc)}), file=sys.stderr)
            return DENIED
        if perms.error:
            print(json.dumps({"allowed": False, "reason_code": "CONFIG_INVALID", "reason": perms.error}), file=sys.stderr)
            return DENIED
        for county in [c for c in counties if c]:
            if any(not perms.authorize(sid, op, state=args.state, county=county, dataset=args.dataset).allowed
                   for sid in args.source for op in args.operation):
                print(county)
        return 0
    worst = 0
    for sid in args.source:
        for op in args.operation:
            d = perms.authorize(sid, op, state=args.state, county=args.county, dataset=args.dataset)
            print(json.dumps(d.as_dict(), sort_keys=True))
            if not d.allowed:
                worst = DENIED
    return worst


if __name__ == "__main__":
    sys.exit(main())
