#!/usr/bin/env python3
"""RentCast value estimates for the MRV (Marc Research Value), 2026-11-25.

The MRV on a property card is the median of the values available for the
property: the county's own value (on the row) and outside estimates from
licensed APIs, stored one row per (property, source) in
public.property_value_estimates (migration 045). This script fills the
RentCast rows: GET https://api.rentcast.io/v1/avm/value?address=... with the
owner's key (X-Api-Key), keeping price, its low / high range and the number
of comparables.

Rules:
  * Nothing runs without RENTCAST_API_KEY (prints one line, exits 0) or
    without the permission records (authorize rentcast_avm fetch / store).
  * A hard monthly budget: RENTCAST_MONTHLY_LIMIT lookups (default 45, under
    the free plan's 50), counted from the estimates already stored this
    calendar month; RENTCAST_RUN_LIMIT caps one run (default: what is left).
  * Only properties a customer can act on: active Available rows first, then
    active auctions with a sale date ahead; certificates never (a lien is
    not the property). The lookup sends the street address when it carries
    a house number and a ZIP code, else the row's own coordinates (most
    lists publish no ZIP); a row with neither is skipped - a partial address
    could value the wrong house.
  * A stored estimate younger than RENTCAST_REFRESH_DAYS (default 90) is
    not looked up again.
  * When the row carries coordinates, the estimate is kept only if RentCast's
    own point lies within ~1.5 km of them (a different house is refused).
  * Logs are counts only - never an address, a value or a key.

    python3 scripts/fetch_rentcast_estimates.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(REPO))

import rest_pages  # noqa: E402
from harvesters.governance import permissions as PERM  # noqa: E402

SOURCE = "rentcast_avm"
API = "https://api.rentcast.io/v1/avm/value"
TABLE = "property_value_estimates"
GONE = ("closed", "dropped", "sold", "notfound")
ZIP_RX = re.compile(r"\b\d{5}(?:-\d{4})?\s*$")
STREET_RX = re.compile(r"^\s*\d+[A-Za-z]?\s+\S+")
MAX_KM = 1.5


def env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


def usable_address(addr) -> bool:
    """A street address with a house number and a ZIP code, nothing else."""
    a = str(addr or "").strip()
    return bool(a) and bool(STREET_RX.match(a)) and bool(ZIP_RX.search(a))


def is_candidate(row: dict, today: str) -> bool:
    if str(row.get("status") or "active").lower() in GONE:
        return False
    src = row.get("source")
    if src == "laft":
        pass
    elif src == "auction":
        if not row.get("sale_date") or str(row["sale_date"])[:10] < today:
            return False
    else:
        return False
    return lookup_params(row) is not None


def has_point(row: dict) -> bool:
    return all(isinstance(row.get(k), (int, float)) for k in ("latitude", "longitude"))


def lookup_params(row: dict) -> dict | None:
    """RentCast's query for this row: the full address, else its point."""
    if usable_address(row.get("address")):
        return {"address": str(row["address"]).strip()}
    if has_point(row) and STREET_RX.match(str(row.get("address") or "")):
        return {"latitude": f"{float(row['latitude']):.6f}", "longitude": f"{float(row['longitude']):.6f}"}
    return None


def priority(row: dict) -> tuple:
    return (0 if row.get("source") == "laft" else 1, str(row.get("state") or ""), str(row.get("county") or ""), str(row.get("id")))


def km_between(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def accept(row: dict, res: dict) -> tuple[bool, str]:
    """Keep an estimate only when it is a positive price and, where both points
    exist, RentCast valued a house near the row's own point."""
    price = res.get("price")
    if not isinstance(price, (int, float)) or price <= 0:
        return False, "NO_PRICE"
    lat, lng = row.get("latitude"), row.get("longitude")
    rlat, rlng = res.get("latitude"), res.get("longitude")
    if all(isinstance(v, (int, float)) for v in (lat, lng, rlat, rlng)):
        if km_between(float(lat), float(lng), float(rlat), float(rlng)) > MAX_KM:
            return False, "LOCATION_MISMATCH"
    return True, "OK"


def estimate_row(row: dict, res: dict, now: str) -> dict:
    lo, hi = res.get("priceRangeLow"), res.get("priceRangeHigh")
    return {
        "property_id": row["id"], "source": SOURCE, "value": round(float(res["price"]), 2),
        "value_low": round(float(lo), 2) if isinstance(lo, (int, float)) and lo > 0 else None,
        "value_high": round(float(hi), 2) if isinstance(hi, (int, float)) and hi > 0 else None,
        "observed_at": now,
        "provenance": {"api": "rentcast /v1/avm/value", "lookup": "address" if usable_address(row.get("address")) else "point",
                       "comparables": len(res.get("comparables") or [])},
    }


def plan(rows: list[dict], stored: dict, *, today: str, refresh_before: str, budget: int) -> list[dict]:
    """The rows to look up this run, in priority order, within the budget."""
    out = []
    if budget <= 0:
        return out
    for r in sorted((r for r in rows if is_candidate(r, today)), key=priority):
        seen = stored.get(str(r["id"]))
        if seen and seen >= refresh_before:
            continue
        out.append(r)
        if len(out) >= budget:
            break
    return out


def rentcast_get(params: dict, key: str, opener=urllib.request.urlopen) -> dict:
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-Api-Key": key, "Accept": "application/json",
                                               "User-Agent": "taxdeed-scraper/1.0 (MRV)"})
    with opener(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="plan only: no lookup, no write")
    args = ap.parse_args(argv)

    key = os.environ.get("RENTCAST_API_KEY", "").strip()
    if not key and not args.dry_run:
        print("RentCast: RENTCAST_API_KEY is not set - no lookups (MRV shows county values only).")
        return 0
    perms = PERM.Permissions.from_file()
    for op in ("fetch", "store"):
        d = perms.authorize(SOURCE, op, state="US")
        if not d.allowed:
            print(f"::error title=source_permission::RentCast {op} not permitted ({d.reason_code}) - no lookups")
            return 3
    base, svc = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not svc:
        print("RentCast: SUPABASE_URL / SUPABASE_SERVICE_KEY not set - nothing read.")
        return 0 if args.dry_run else 2
    headers = {"apikey": svc, "Authorization": f"Bearer {svc}"}

    now_dt = datetime.now(timezone.utc)
    now, today = now_dt.isoformat(), now_dt.date().isoformat()
    month_start = now_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    refresh_before = (now_dt - timedelta(days=env_int("RENTCAST_REFRESH_DAYS", 90))).isoformat()
    try:
        est = rest_pages.read_all(base, TABLE, headers, {"select": "property_id,observed_at", "source": f"eq.{SOURCE}"}, key="property_id")
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 400):
            print("RentCast: property_value_estimates is not on this database (migration 045) - nothing done.")
            return 0
        raise
    stored = {str(e["property_id"]): str(e["observed_at"]) for e in est}
    used = sum(1 for v in stored.values() if v >= month_start)
    budget = max(0, env_int("RENTCAST_MONTHLY_LIMIT", 45) - used)
    budget = min(budget, env_int("RENTCAST_RUN_LIMIT", budget))
    rows = rest_pages.read_all(base, "properties", headers,
                               {"select": "id,state,county,source,status,sale_date,address,latitude,longitude",
                                "source": "in.(laft,auction)", "address": "not.is.null"})
    todo = plan(rows, stored, today=today, refresh_before=refresh_before, budget=budget)
    print(f"RentCast: {len(rows)} rows read; {used} lookups already this month; budget this run {budget}; {len(todo)} to look up.")
    if args.dry_run or not todo:
        return 0

    counts = {"OK": 0, "NO_PRICE": 0, "LOCATION_MISMATCH": 0, "NOT_FOUND": 0, "ERROR": 0, "DENIED": 0}
    out = []
    for r in todo:
        if not perms.authorize(SOURCE, "fetch", state=r.get("state") or "US").allowed:
            counts["DENIED"] += 1
            continue
        try:
            res = rentcast_get(lookup_params(r), key)
        except urllib.error.HTTPError as exc:
            counts["NOT_FOUND" if exc.code == 404 else "ERROR"] += 1
            if exc.code in (401, 403, 429):
                print(f"RentCast: HTTP {exc.code} - stopping this run.")
                break
            continue
        except Exception:  # noqa: BLE001 - counted, never printed with the address
            counts["ERROR"] += 1
            continue
        ok, why = accept(r, res)
        counts[why] += 1
        if ok:
            out.append(estimate_row(r, res, now))
    if out:
        body = json.dumps(out).encode("utf-8")
        req = lambda: urllib.request.Request(  # noqa: E731
            f"{base}/rest/v1/{TABLE}?on_conflict=property_id,source", data=body, method="POST",
            headers=dict(headers, **{"Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"}))
        rest_pages.send_idempotent(req)
    print("RentCast: " + ", ".join(f"{k.lower()} {v}" for k, v in counts.items()) + f"; {len(out)} estimates stored.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
