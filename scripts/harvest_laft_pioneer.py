#!/usr/bin/env python3
"""
Harvest "Lands Available for Taxes" (LAFT) listings from counties on the
Pioneer Technology Group "TaxSmartWeb" platform (also branded Catalis /
Landmark in some counties) - one deployment per county rather than a
shared multi-tenant subdomain, so every county's base URL is confirmed
individually and stored in ../data/laft_pioneer_counties.csv.

=============================================================================
2026-08-26 REWRITE - this harvester was silently returning 0 for counties
that demonstrably had properties. Read this before changing it back.
=============================================================================

History, because this platform has now burned three separate approaches and
the failure mode was identical and silent every time:

  Attempt 1 - plain `requests` POST of the search form. Returned 0 for
  Citrus on a day Citrus had 5 real properties. Abandoned.

  Attempt 2 - Playwright, real browser, click the "Lands Available" tab
  then click `buttonSubmitLandsAvailable`. This fixed a genuine bug (the
  tab panel is display:none until its tab is clicked, so the button was
  not clickable), and the run went green... but still returned 0 for
  counties with live data.

  Attempt 3 (this one) - root-caused 2026-08-26 by checking five counties
  BY HAND against the scraper's output. Hernando had 6 live properties and
  Palm Beach had 2; the harvester reported 0 for both. Clay, St. Johns and
  Walton were confirmed genuinely empty in the same pass, which is why the
  bug hid for so long - most counties really are empty most of the time,
  so "0" always looked plausible.

THE ACTUAL MECHANISM: the search form POST does NOT return the results.
It re-renders the page with an EMPTY jqGrid skeleton (`<table id="TaxDeed">`).
The rows arrive in a SECOND request the page fires afterwards:

    GET {base}/Home/GridSearchData?SearchType=Lands+Available&_search=false
        &rows=100&page=1&sidx=&sord=asc

Proven directly: a raw form POST to Hernando returned 57KB of HTML
containing the grid skeleton but NOT case 2024-119TD and no record count;
the six rows only existed in the DOM after the AJAX call completed. So any
approach that POSTs and then parses the response HTML returns zero for
every county - which is exactly what both previous attempts did. The
Playwright version additionally raced this AJAX call: it read the grid
immediately after clicking search, usually before the rows had landed.

THE FIX: skip the form entirely and call `GridSearchData` directly. Confirmed
live on all five counties checked that this endpoint needs **no prior POST,
no session, no cookie, and no tab click** - a cold GET on a freshly-loaded
page returns correct results. That makes this harvester a plain `requests`
call again, with NO Playwright dependency, and removes both the tab-click
bug and the AJAX race in one move.

This is an HTTP-level reproduction of a vendor search, which this project
has an explicit standing lesson against trusting. That lesson is satisfied
here rather than ignored: this endpoint was verified against counties KNOWN
to have live data (Hernando returning exactly its 6, Palm Beach exactly its
2, with case numbers and bid amounts matching what the rendered page shows),
not merely against counties that happened to return zero.

Two traps this deliberately avoids, both confirmed live:
  - The page renders a DECOY header-only table before the real grid, so a
    naive "first table on the page" selector yields a header row and no
    data. Not an issue here since we never parse the HTML, but it is why
    the HTML-parsing approach looked like it was "working".
  - Counties with zero results omit the grid element ENTIRELY rather than
    rendering an empty one with a "no records found" message. There is no
    such message on this platform. `records` in the JSON is the only
    trustworthy empty/non-empty signal, which is why it is cross-checked
    below instead of inferring emptiness from a missing element.

Output: harvest_laft_pioneer.json / .csv - kept separate from the other
harvesters' outputs. sync-laft-to-supabase.ps1 merges all of them.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
SOURCES_CSV = HERE / "../data/laft_pioneer_counties.csv"
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_laft_pioneer.json"
OUT_CSV = OUT_DIR / "harvest_laft_pioneer.csv"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Every confirmed deployment serves the grid endpoint at this path relative
# to its own base URL, despite the base URLs themselves having no shared
# convention at all (/TaxDeed, /TaxSmart/, /taxsmartweb, /TaxSmartWeb,
# /TaxSmartWebLive/, and several at the bare host root - see the CSV).
GRID_PATH = "Home/GridSearchData"

SEARCH_TYPE = "Lands Available"

# Confirmed live cell order in the JSON payload. Matched positionally
# because this endpoint returns bare arrays with no field names - unlike
# every other harvester in this project, there is no header text to match
# against. The order was verified identical across all five counties
# checked; a mismatch is therefore worth failing loudly on rather than
# silently misaligning, which is what CELL_COUNT below guards.
CELL_FIELDS = [
    "applicant",
    "case_no",
    "certificate_no",
    "parcel",
    "sale_date",
    "status",
    "bid",          # "Base Bid" - the opening bid, which is what we want
    "high_bid",
    "surplus",
    "owners",
]
CELL_COUNT = len(CELL_FIELDS)

# 25 is the platform default; no county checked has come close to 100, but
# the count is cross-checked against `records` below so a county that ever
# exceeds this is caught loudly rather than silently truncated.
ROWS_PER_PAGE = 100


def _grid_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/{GRID_PATH}"


def _clean(value) -> str:
    return str(value).strip() if value is not None else ""


def _parse_rows(payload: dict, county: str, base_url: str) -> tuple[list[dict], int]:
    """Return (records, reported_total). `reported_total` is the platform's
    own `records` count, cross-checked by the caller - see module docstring
    for why that is the only trustworthy empty/non-empty signal here."""
    reported = int(payload.get("records") or 0)
    out: list[dict] = []
    for entry in payload.get("rows") or []:
        cells = entry.get("cell") if isinstance(entry, dict) else entry
        if not isinstance(cells, list):
            continue
        if len(cells) < CELL_COUNT:
            print(
                f"    WARNING: row has {len(cells)} cells, expected {CELL_COUNT} - "
                f"vendor may have changed the grid columns; skipping this row rather "
                f"than risk misaligning fields",
                flush=True,
            )
            continue
        record: dict = {"county": county, "source": "laft", "url_auction": base_url}
        for i, field in enumerate(CELL_FIELDS):
            value = _clean(cells[i])
            if value:
                record[field] = value
        if record.get("case_no") or record.get("parcel"):
            out.append(record)
    return out, reported


def harvest_county(session: requests.Session, county: str, base_url: str) -> list[dict]:
    resp = session.get(
        _grid_url(base_url),
        params={
            "SearchType": SEARCH_TYPE,
            "_search": "false",
            "rows": str(ROWS_PER_PAGE),
            "page": "1",
            "sidx": "",
            "sord": "asc",
        },
        headers={"User-Agent": UA, "X-Requested-With": "XMLHttpRequest"},
        timeout=30,
    )
    resp.raise_for_status()
    try:
        payload = resp.json()
    except ValueError as exc:
        raise RuntimeError(
            f"grid endpoint did not return JSON (got {resp.headers.get('Content-Type')!r}) - "
            f"base URL may be wrong or the vendor changed the endpoint: {exc}"
        ) from exc

    rows, reported = _parse_rows(payload, county, base_url)

    # Loud, non-fatal cross-check. A genuine zero is normal on this platform
    # and must stay quiet; a MISMATCH is the thing that hid the original bug
    # for weeks, so it gets shouted about.
    if reported != len(rows):
        print(
            f"    WARNING: endpoint reports {reported} records but {len(rows)} were parsed"
            + (f" - more than the {ROWS_PER_PAGE}-row page size, pagination now needed" if reported > ROWS_PER_PAGE else "")
            + " - investigate before trusting this county's count",
            flush=True,
        )
    return rows


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(SOURCES_CSV, newline="", encoding="utf-8") as f:
        sources = list(csv.DictReader(f))

    all_rows: list[dict] = []
    for i, src in enumerate(sources, 1):
        county, base_url = src["County"], src["BaseUrl"]
        print(f"[{i}/{len(sources)}] {county}", flush=True)
        try:
            session = requests.Session()
            rows = harvest_county(session, county, base_url)
            if rows:
                priced = sum(1 for r in rows if r.get("bid"))
                print(f"    {len(rows)} properties ({priced} with a base bid)", flush=True)
                all_rows.extend(rows)
            else:
                print("    no properties currently listed", flush=True)
        except Exception as exc:  # noqa: BLE001 - one bad county must not kill the whole run
            print(f"    ERROR: {exc}", flush=True)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, indent=2)

    if all_rows:
        fieldnames = sorted({k for row in all_rows for k in row.keys()})
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_rows)
    else:
        OUT_CSV.write_text("", encoding="utf-8")

    print("")
    print("=" * 50)
    print(f"Harvested {len(all_rows)} LAFT properties total")
    print(f"Counties with matches: {len({r['county'] for r in all_rows})} of {len(sources)} checked")
    print("=" * 50)
    print(f"Saved: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
