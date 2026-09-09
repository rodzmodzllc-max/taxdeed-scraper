#!/usr/bin/env python3
"""Pushes harvesters/texas_harvester.py's output (out/harvest_texas.json) into
the same `properties` table the FL sync scripts write to, with state='TX'.

Mirrors sync-certificates-to-supabase.ps1 / sync-harvest-to-supabase.ps1's
safe-merge design, in Python rather than PowerShell (matching this repo's
existing Python-for-TX / PowerShell-for-FL split - see
enrich_property_details_tx.py, tx_use_codes.py, tx_yield_calc.py): only ever
sends the columns the harvester actually knows, so re-syncing never clobbers
hand research. Deliberately OMITTED from every payload, same as the FL
scripts: owner_name, status, lien_level, lien_note, prop_type, homestead,
url_streetview, url_zillow, url_taxcoll, url_title, tx_category,
redemption_period_months, redemption_expiration_date,
max_statutory_return_usd - those are enrichment-time or hand-research
fields, not harvest-time fields (see texas_harvester.py's module docstring).

Conflict target is `on_conflict=state,source,county,case_no` from day one -
NOT the older FL-only `on_conflict=source,county,case_no` target the three
FL sync scripts still fall back to. No fallback needed here: unlike the FL
scripts (which have to keep working against a Supabase project that might
predate 004_widen_unique_constraint_for_state.sql), Texas rows only ever
start existing once Texas harvesting itself starts, which is after that
migration has been run - see the `texas` job's own comment in
.github/workflows/harvest-and-sync.yml. If this still hits a 42P10 error,
that means the migration genuinely hasn't been run yet against whatever
Supabase project this points at - the fix is to run it (see that
migration's own header comment on why it can't be typed into the Supabase
SQL Editor via browser automation), not to fall back to the narrower
conflict target, which would silently reopen the exact FL/TX same-named-
county collision that migration exists to prevent.

`case_no` is LGBS's (or any future TX vendor's) own CAD parcel/account
number, not a legal case/cause number - see texas_harvester.py's module
docstring ("harvest_lgbs() shipped" note) for why a per-parcel-unique id was
required for this table's (state, source, county, case_no) uniqueness
constraint, and why the legal cause number goes into `parcel` instead.

`bid` (used by every card/spread/value-ratio calculation in public/app.js)
and `min_bid` (the Texas-specific "TX Min Bid" export column) are both set
from the same harvested minimum-bid figure - that number plays both roles
honestly: it is both "the amount you'd need to bid" (bid's cross-state
meaning) and Texas's own court-ordered statutory minimum (min_bid's
TX-specific meaning), not two different figures.

Run harvesters/texas_harvester.py first, then this.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
JSON_PATH = HERE / "../out/harvest_texas.json"

BATCH_SIZE = 40  # matches the FL sync scripts' batch size

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _num(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso_date_or_none(value):
    if not value or not isinstance(value, str) or not _ISO_DATE_RE.match(value):
        return None
    return value


def main() -> None:
    supabase_url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY")  # never log, never commit - see CLAUDE.md
    if not supabase_url or not service_key:
        print(
            "SUPABASE_URL / SUPABASE_SERVICE_KEY environment variables are not "
            "set - check the workflow's secrets.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not JSON_PATH.exists():
        print(f"No {JSON_PATH} - harvester found nothing this run. Nothing to sync.", file=sys.stderr)
        return

    harvest = json.loads(JSON_PATH.read_text())
    if not harvest:
        print("harvest_texas.json is empty - nothing to sync.", file=sys.stderr)
        return

    # De-duplicate on (county, case_no) - the same conflict-target key the
    # upsert below uses. Postgres's ON CONFLICT DO UPDATE rejects a batch
    # that would update the same conflict-target row twice in one statement
    # ("ON CONFLICT DO UPDATE command cannot affect row a second time"),
    # which failed sync-certificates-to-supabase.ps1's ENTIRE run the one
    # time LienHub published a duplicate row (see that script's own
    # comment) - not just the duplicated rows. Keep the last-seen row per
    # key, same as that fix.
    deduped: dict[tuple[str, str], dict] = {}
    skipped = 0
    for p in harvest:
        case_no = p.get("account_number")
        county = p.get("county")
        source = p.get("source")
        if not case_no or not county or not source:
            skipped += 1
            continue

        address = (p.get("address") or "").strip() or f"Account {case_no}"
        min_bid = _num(p.get("min_bid"))
        bid = min_bid if min_bid is not None else 0

        row = {
            "state": "TX",
            "source": source,
            "harvester_source": p.get("harvester_source") or None,
            "county": county,
            "case_no": case_no,
            "parcel": p.get("cause_number") or None,
            "address": address,
            "bid": bid,
            "min_bid": min_bid,
            "assessed": _num(p.get("cad_market_value")),
            "sale_date": _iso_date_or_none(p.get("auction_date")),
            "legal_desc": p.get("legal_description") or None,
        }
        # latitude/longitude get the safe-merge treatment PER ROW, not just
        # script-wide: scripts/geocode_properties.py only ever fills these
        # in when they are still NULL, so sending an explicit null here for
        # a row LGBS didn't publish coordinates for would silently erase a
        # value that script already backfilled on an earlier run. Omit the
        # keys entirely when we don't have real coordinates, rather than
        # sending null.
        lat, lon = _num(p.get("latitude")), _num(p.get("longitude"))
        if lat is not None and lon is not None:
            row["latitude"] = lat
            row["longitude"] = lon

        deduped[(county, case_no)] = row

    dupe_count = len(harvest) - skipped - len(deduped)
    if dupe_count > 0:
        print(
            f"De-duplicated {dupe_count} row(s) sharing a (county, case_no) key with another row in this harvest.",
            file=sys.stderr,
        )

    rows = list(deduped.values())
    if not rows:
        print(f"Every harvested row was missing case_no/county/source ({skipped} skipped) - nothing to sync.", file=sys.stderr)
        return
    print(f"Prepared {len(rows)} properties ({skipped} skipped for missing case_no/county/source).", file=sys.stderr)

    endpoint = f"{supabase_url}/rest/v1/properties?on_conflict=state,source,county,case_no"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }

    sent = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        body = json.dumps(batch).encode("utf-8")
        req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if "42P10" in detail or "no unique or exclusion constraint" in detail:
                print(
                    "SYNC FAILED: Postgres reports no unique constraint matches "
                    "on_conflict=state,source,county,case_no - "
                    "004_widen_unique_constraint_for_state.sql has not been run "
                    "against this Supabase project yet. Run it (see that "
                    "migration's header comment), then re-run this sync.",
                    file=sys.stderr,
                )
            else:
                print(f"SYNC FAILED on batch starting at row {i}: {exc.code} {detail}", file=sys.stderr)
            sys.exit(1)
        sent += len(batch)
        print(f"  synced {sent} / {len(rows)}", file=sys.stderr)

    counties = len({r["county"] for r in rows})
    print(f"Done. {sent} Texas properties upserted to Supabase (existing hand research untouched).", file=sys.stderr)
    print(f"Counties covered: {counties}", file=sys.stderr)


if __name__ == "__main__":
    main()
