#!/usr/bin/env python3
"""Sync one activated state's adapter records into public.properties
(state-expansion sprint, 2026-09-30).

    python3 scripts/sync_state_inventory.py --state LA                 # live (SUPABASE_URL + SUPABASE_SERVICE_KEY)
    python3 scripts/sync_state_inventory.py --state LA --dry-run       # plan only, no request

Reads the rows `scripts/harvest_state_inventory.py` wrote with
`OtcRecord.to_properties_row()` (out/<state>_properties_rows.json - private,
never uploaded unencrypted) and upserts them on the table's own identity
(state, source, county, case_no). It refuses, before any request, unless:

  * the state is ACTIVATED (harvesters/governance/states.py);
  * the source is a PRODUCTION_VERIFIED registry row of that state with a
    runnable governance status;
  * the harvester's status file says the unit was read COMPLETE or
    INCOMPLETE (a FAILED / EMPTY / missing read syncs nothing - absence is
    for scripts/laft_lifecycle.py to judge, never this script).

Each row is stamped with the registry's publication decision
(publication_status - the frontend withholds anything not APPROVED*), its
ledger (ledger_type 'buy' for the AVAILABLE ledger) and harvester_source =
the source id. Public log discipline: counts only, never a row value.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
from harvesters.governance import states  # noqa: E402
from harvesters.governance.county_source_registry import RUNNABLE_GOVERNANCE, load_registry  # noqa: E402
from harvesters.governance.publication import effective_publication  # noqa: E402

REGISTRY = REPO / "data" / "county_source_registry.csv"
OUT = REPO / "out"
USER_AGENT = "taxdeed-scraper state-inventory-sync (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
BATCH = 500
LEDGER_TYPE_FOR_SOURCE = {"laft": "buy", "auction": "auctions", "certificate": "lien"}
OBSERVED = frozenset({"COMPLETE", "INCOMPLETE"})


def rows_path(state: str) -> Path:
    return OUT / f"{state.lower()}_properties_rows.json"


def registry_rows(state: str, path: Path = REGISTRY) -> dict[str, object]:
    return {r.source_id: r for r in load_registry(path) if r.state == state}


def plan(state: str, rows: list[dict], registry: dict, status_units: dict[str, str]) -> tuple[list[dict], dict]:
    """(rows to upsert, counts). Pure - no I/O. Raises ValueError when the
    state or a row's source may not be synced at all."""
    if not states.is_activated(state):
        raise ValueError(f"state {state} is not activated: {', '.join(states.activation_blockers(state))}")
    counts = {"input": len(rows), "upsert": 0, "skipped_unit_not_read": 0, "wrong_state": 0}
    out: list[dict] = []
    keys: set[str] = set()
    for r in rows:
        if r.get("state") != state:
            counts["wrong_state"] += 1
            continue
        reg = registry.get(r.get("source_id") or "")
        if reg is None or not reg.is_production or reg.governance_status not in RUNNABLE_GOVERNANCE:
            raise ValueError(f"source {r.get('source_id')!r} is not a production, governance-approved {state} registry row")
        if status_units.get(r.get("county") or "") not in OBSERVED:
            counts["skipped_unit_not_read"] += 1
            continue
        row = dict(r)
        row["publication_status"] = effective_publication(reg)
        row["ledger_type"] = LEDGER_TYPE_FOR_SOURCE[row["source"]]
        row["harvester_source"] = reg.source_id
        keys.update(row)
        out.append(row)
    # PostgREST bulk upserts need one key set: a key absent on a row is sent
    # as NULL. Only this source writes these rows, so that is its own value.
    out = [{k: r.get(k) for k in sorted(keys)} for r in out]
    counts["upsert"] = len(out)
    return out, counts


def status_units(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("counties") if isinstance(data, dict) else data
    if isinstance(entries, dict):
        entries = [{"county": k, **v} for k, v in entries.items()]
    return {str(e.get("county")): str(e.get("status")) for e in entries or [] if isinstance(e, dict)}


def upsert(base: str, key: str, rows: list[dict]) -> int:
    requests = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        req = urllib.request.Request(
            f"{base.rstrip('/')}/rest/v1/properties?on_conflict=state,source,county,case_no",
            data=json.dumps(chunk).encode(), method="POST",
            headers={"apikey": key, "Authorization": f"Bearer {key}", "User-Agent": USER_AGENT, "Content-Type": "application/json",
                     "Prefer": "resolution=merge-duplicates,return=minimal"})
        with urllib.request.urlopen(req, timeout=120):
            requests += 1
    return requests


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", required=True)
    ap.add_argument("--rows", default=None)
    ap.add_argument("--status", required=True, help="the harvester's status file (per-unit COMPLETE / INCOMPLETE / ...)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    path = Path(args.rows) if args.rows else rows_path(args.state)
    if not path.exists():
        print(f"{args.state}: no rows file ({path.name}) - nothing to sync")
        return 0
    rows = json.loads(path.read_text(encoding="utf-8"))
    try:
        to_send, counts = plan(args.state, rows, registry_rows(args.state), status_units(Path(args.status)))
    except ValueError as exc:
        print(f"::error title=sync_{args.state.lower()}::{exc} - 0 requests made")
        return 2
    print(f"{args.state} sync plan: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    if args.dry_run or not to_send:
        return 0
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print(f"::error title=sync_{args.state.lower()}::SUPABASE_URL / SUPABASE_SERVICE_KEY not set - 0 requests made")
        return 2
    n = upsert(url, key, to_send)
    print(f"{args.state}: upserted {len(to_send)} row(s) in {n} request(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
