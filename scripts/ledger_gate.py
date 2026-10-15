#!/usr/bin/env python3
"""The three-ledger contract for the Florida PowerShell syncs (2026-10-14).

scripts/sync-harvest-to-supabase.ps1 (AUCTIONS), sync-certificates-to-
supabase.ps1 (LIENS_CERTIFICATES) and sync-laft-to-supabase.ps1 (AVAILABLE)
build their rows in PowerShell. This CLI lets them apply the SAME contract the
Python syncs apply - harvesters/ledgers/records.py for rows and
harvesters/ledgers/health.py for status files - instead of a second copy of
the rules in PowerShell that could drift.

  rows       --ledger L --in rows.json
             prints {"refused": [index, ...], "accepted": n, "reasons": {...}}
             A row is refused when it does not belong to ledger L or breaks
             L's record contract (records.problems). Exit 2 when the input
             cannot be read: the caller then writes nothing (fail closed).

  closeable  --ledger L --status status.json [--source-id S]
             prints a JSON list of the counties whose read, as the ledger
             health reader sees it, may close absent rows of ledger L
             (COMPLETE, or EMPTY with a valid empty signal). A missing or
             unreadable status file prints [] (fail closed). Entries naming a
             source that does not feed L are ignored; without --source-id only
             entries that name no source count (one source's read never
             stands in for a sibling's).

Prints counts and county names only, never a row value. Standard library +
the repository's harvesters package; no network.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from harvesters.ledgers import Ledger, ledger_for_row  # noqa: E402
from harvesters.ledgers import health as LH  # noqa: E402
from harvesters.ledgers import records as LR  # noqa: E402


def _ledger(name: str) -> Ledger:
    try:
        return Ledger[name.upper()]
    except KeyError:
        raise SystemExit(f"ledger_gate: unknown ledger {name!r} (one of {', '.join(l.name for l in Ledger)})") from None


def _read_list(path: Path) -> list:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    # PowerShell's ConvertTo-Json writes a one-element array as a bare object.
    return data if isinstance(data, list) else [data]


def check_rows(ledger: Ledger, rows: list) -> dict:
    refused, reasons = [], Counter()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            refused.append(i)
            reasons["not_a_record"] += 1
            continue
        if ledger_for_row(row) is not ledger:
            refused.append(i)
            reasons["wrong_ledger"] += 1
            continue
        if LR.problems(row):
            refused.append(i)
            reasons["ledger_contract"] += 1
    return {"refused": refused, "accepted": len(rows) - len(refused), "reasons": dict(reasons)}


def closeable_counties(ledger: Ledger, entries: list, source_id: str | None = None) -> list[str]:
    units = LH.ledger_units([e for e in entries if isinstance(e, dict)], ledger)
    counties = {str(e.get("county") or "") for e in entries if isinstance(e, dict) and e.get("county")}
    out = []
    for county in sorted(counties):
        status = units.get((source_id, county)) if source_id else units.get(county)
        if source_id and status is None:
            status = units.get(county)
        if LH.closeable(ledger, status):
            out.append(county)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rows")
    r.add_argument("--ledger", required=True)
    r.add_argument("--in", dest="inp", required=True)
    c = sub.add_parser("closeable")
    c.add_argument("--ledger", required=True)
    c.add_argument("--status", required=True)
    c.add_argument("--source-id")
    args = ap.parse_args(argv)
    ledger = _ledger(args.ledger)
    if args.cmd == "rows":
        try:
            rows = _read_list(Path(args.inp))
        except (OSError, ValueError) as exc:
            print(f"ledger_gate: rows unreadable ({type(exc).__name__}) - nothing may be written", file=sys.stderr)
            return 2
        out = check_rows(ledger, rows)
        print(json.dumps(out, sort_keys=True))
        if out["refused"]:
            print(f"ledger_gate: {ledger.value}: refused {len(out['refused'])} of {len(rows)} row(s) {out['reasons']}",
                  file=sys.stderr)
        return 0
    try:
        entries = _read_list(Path(args.status))
    except (OSError, ValueError) as exc:
        print(f"ledger_gate: status file unreadable ({type(exc).__name__}) - no county may close (fail closed)", file=sys.stderr)
        print("[]")
        return 0
    print(json.dumps(closeable_counties(ledger, entries, args.source_id)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
