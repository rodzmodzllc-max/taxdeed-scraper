#!/usr/bin/env python3
"""Close out FUTURE-dated Florida deed-auction rows that are no longer on a
COMPLETE county's current sale list (2026-10-25, OFF by default).

The deed sync (sync-harvest-to-supabase.ps1) closes only rows whose sale day
has PASSED and that left a COMPLETE county's Waiting feed. A row with a
future sale date that the county dropped (cancelled, redeemed, rescheduled -
the feed does not say which) stayed `active` and read as an upcoming sale;
the app only labels it (app.js offCurrentSaleList). CLAUDE.md "Auctions off
the county's current sale list" names closing such rows server-side as an
owner decision - so this step exists, but writes nothing unless BOTH
`--apply` is passed AND the environment sets AUCTION_OFFLIST_CLOSE=1 (the
workflow passes it only from the repository variable of the same name).

A row is closed only when ALL of these hold (the app's rule, plus the read):
  * state FL, source auction, status active, sale_date >= the Florida date
    (UTC-6, the sync's own convention); a row without a sale date is left
    alone
  * its county's read this run is COMPLETE or EMPTY
    (harvest_all_status.json through harvesters/ledgers/health.py - the same
    gate as the sync's own close-out)
  * its case number is NOT in this run's harvest for that county
  * its own last_seen_at is missing or more than 36 h older than the
    county's newest last_seen_at among its active auction rows, and that
    newest read is itself within 36 h of now (stamp_seen.py ran this run;
    otherwise the county is skipped - fail closed)

What it writes: `{"status": "closed"}` and nothing else - never a result, a
sale, a price or a purchaser; absence is never a sale. Output is counts only
(per county), never a case number or an address.

    python3 scripts/auction_offlist_closeout.py --status out/harvest_all_status.json --harvest out/harvest_all.json
    AUCTION_OFFLIST_CLOSE=1 python3 scripts/auction_offlist_closeout.py ... --apply
    python3 scripts/auction_offlist_closeout.py --rows rows.json --status s.json --harvest h.json --now 2026-10-25T12:00:00Z
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(REPO))

from harvesters.ledgers import Ledger  # noqa: E402
from harvesters.ledgers import health as LH  # noqa: E402

FLAG = "AUCTION_OFFLIST_CLOSE"
GRACE = timedelta(hours=36)          # app.js OFF_LIST_GRACE_MS
SALE_DAY_UTC_OFFSET = timedelta(hours=-6)
SELECT = "id,county,case_no,status,sale_date,last_seen_at"
BATCH = 100


def as_list(data) -> list:
    """PowerShell's ConvertTo-Json writes a one-element array as a bare object."""
    if isinstance(data, list):
        return data
    return [data] if isinstance(data, dict) else []


def complete_counties(status_entries) -> set[str]:
    entries = [e for e in as_list(status_entries) if isinstance(e, dict)]
    units = LH.ledger_units(entries, Ledger.AUCTIONS)
    out = set()
    for e in entries:
        county = str(e.get("county") or "")
        if county and LH.closeable(Ledger.AUCTIONS, LH.unit_status(units, e.get("source_id"), county)):
            out.add(county)
    return out


def harvested_cases(harvest_rows, case_key: str = "case") -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for r in as_list(harvest_rows):
        if not isinstance(r, dict):
            continue
        county, case = str(r.get("county") or "").strip(), str(r.get(case_key) or r.get("case_no") or "").strip()
        if county and case:
            out.setdefault(county, set()).add(case)
    return out


def florida_today(now: datetime) -> str:
    return (now.astimezone(timezone.utc) + SALE_DAY_UTC_OFFSET).date().isoformat()


def plan(rows: list[dict], *, complete: set[str], harvested: dict[str, set[str]], now: datetime) -> tuple[list[str], dict]:
    """(ids to close, counts). Pure; see the module docstring for the rule."""
    today = florida_today(now)
    active = [r for r in rows if str(r.get("status") or "").lower() == "active"]
    newest: dict[str, datetime] = {}
    for r in active:
        seen = LH.observed_at(r)
        c = str(r.get("county") or "")
        if seen and (c not in newest or seen > newest[c]):
            newest[c] = seen
    counts: Counter = Counter()
    by_county: Counter = Counter()
    ids: list[str] = []
    for r in active:
        county = str(r.get("county") or "")
        sale = str(r.get("sale_date") or "")[:10]
        if not sale or sale < today:
            counts["not_future_dated"] += 1
            continue
        if county not in complete:
            counts["county_not_complete"] += 1
            continue
        if str(r.get("case_no") or "").strip() in harvested.get(county, set()):
            counts["on_current_list"] += 1
            continue
        top = newest.get(county)
        if top is None or now - top > GRACE:
            counts["county_newest_read_not_this_run"] += 1
            continue
        seen = LH.observed_at(r)
        if seen is not None and top - seen <= GRACE:
            counts["seen_within_grace"] += 1
            continue
        counts["close"] += 1
        by_county[county] += 1
        ids.append(str(r["id"]))
    counts["active_rows"] = len(active)
    return ids, {"counts": dict(counts), "by_county": dict(sorted(by_county.items())), "florida_today": today}


def _read_json(path: str | None):
    if not path or not Path(path).exists():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except ValueError:
        return None


def fetch_rows(base: str, key: str) -> list[dict]:
    import rest_pages as RP  # noqa: PLC0415
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    return RP.read_all(base, "properties", headers,
                       {"select": SELECT, "state": "eq.FL", "source": "eq.auction", "status": "eq.active"})


def close(base: str, key: str, ids: list[str]) -> int:
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "Prefer": "return=minimal"}
    done = 0
    for i in range(0, len(ids), BATCH):
        chunk = ids[i:i + BATCH]
        url = (f"{base}/rest/v1/properties?state=eq.FL&source=eq.auction&status=eq.active"
               f"&id=in.({','.join(chunk)})")
        req = urllib.request.Request(url, data=json.dumps({"status": "closed"}).encode(), method="PATCH", headers=headers)
        with urllib.request.urlopen(req, timeout=120):
            pass
        done += len(chunk)
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", default="out/harvest_all_status.json")
    ap.add_argument("--harvest", default="out/harvest_all.json")
    ap.add_argument("--case-key", default="case")
    ap.add_argument("--rows", help="offline: a JSON list of properties rows (no network)")
    ap.add_argument("--now")
    ap.add_argument("--apply", action="store_true", help=f"write - also needs {FLAG}=1 in the environment")
    a = ap.parse_args(argv)
    now = LH.parse_ts(a.now) if a.now else datetime.now(timezone.utc)
    status = _read_json(a.status)
    if status is None:
        print(f"auction off-list close-out: no readable {a.status} - nothing eligible (fail closed)")
        return 0
    harvest = _read_json(a.harvest)
    if harvest is None:
        print(f"auction off-list close-out: no readable {a.harvest} - nothing eligible (fail closed)")
        return 0
    complete = complete_counties(status)
    harvested = harvested_cases(harvest, a.case_key)
    base, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if a.rows:
        rows = as_list(json.loads(Path(a.rows).read_text(encoding="utf-8")))
    else:
        if not base or not key:
            print("auction off-list close-out: SUPABASE_URL / SUPABASE_SERVICE_KEY not set - skipped")
            return 0
        rows = fetch_rows(base, key)
    ids, report = plan(rows, complete=complete, harvested=harvested, now=now)
    enabled = a.apply and os.environ.get(FLAG, "") == "1"
    mode = "apply" if enabled else ("plan-only (--apply given but " + FLAG + " is not 1)" if a.apply else "plan-only")
    print(f"auction off-list close-out (FL): mode {mode}; COMPLETE counties {len(complete)}; "
          f"would close {len(ids)} future-dated row(s) absent from their county's current sale list")
    print("  counts: " + json.dumps(report["counts"], sort_keys=True))
    if report["by_county"]:
        print("  by county: " + ", ".join(f"{c} {n}" for c, n in report["by_county"].items()))
    if enabled and ids and not a.rows:
        import stamp_seen  # noqa: PLC0415 - the same recorded `store` permission as the FL auction stamp
        if not stamp_seen.store_permitted("FL", "auction"):
            return stamp_seen.PERMISSION_DENIED_EXIT
        print(f"  closed {close(base, key, ids)} row(s) (status 'closed' only; no result)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
