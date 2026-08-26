#!/usr/bin/env python3
"""
Harvest "Lands Available for Taxes" (LAFT) listings for Osceola County from
its NewVision Systems tax-deed portal - officialrecords.osceolaclerk.org.

=============================================================================
2026-08-26 REWRITE - this harvester returned 0 in production for a county
that has 10 real properties. Read this before changing it back.
=============================================================================

Osceola has never once produced a row in production. Both previous versions
drove the page with Playwright and both silently returned 0 - no exception,
just the "no grid rendered = genuine zero" branch, which is indistinguishable
from a real empty list. Root-caused 2026-08-26 by checking the live site by
hand: **there are 10 real LANDA-status properties**, so every production run
so far has been wrong.

THE BUG: the page contains **FIVE identical
`button[ng-click="runSearch(true)"]` elements** - one per search panel (Name,
Tax Number, Lands Available, Parcel, Sale Date). Only the active panel's
button is visible; the app defaults to the Name panel. After clicking "Lands
Available" the visible button is index 2, and index 0 becomes hidden. A
selector matching that attribute therefore either matches 5 elements
(strict-mode error) or resolves to the now-HIDDEN Name-tab button, whose
actionability check times out - so the search never runs, no rows ever
render, and the harvester reports a confident zero.

That is the second distinct trap on this page. The first, fixed earlier, was
that the prominent "Run Lands Available Search" text is a plain <span> with
no click handler at all - a decoy. Matching the button by visible text hit
the decoy; matching it by ng-click hit a hidden duplicate. Both produced the
same silent zero.

THE FIX: stop driving the page entirely and call the JSON API directly.
Confirmed live 2026-08-26 that `POST /browserviewtd/api/search` is **fully
stateless** - verified with credentials omitted AND referrer suppressed, it
returns HTTP 200 with all 10 records. No cookie, no session, no CSRF token,
no Referer, no anti-bot header. Only Content-Type is actually required.

This removes the Playwright dependency for this county and eliminates both
trap classes at once - the same fix that resolved an identical silent-zero
bug on the Pioneer/TaxSmartWeb platform the same day (see
harvest_laft_pioneer.py, whose results also turned out to arrive in a
separate request the browser automation was racing).

On the project's standing "don't trust an HTTP-level reproduction of an
unfamiliar site's search" rule: satisfied rather than ignored. This endpoint
was verified against a county KNOWN to have live data, returning exactly the
10 records visible in the rendered grid with matching tax numbers, parcels
and bid amounts - not merely against a county that happened to return zero.

THREE FOOTGUNS, all confirmed live, all guarded below:

1. **The response is a JSON OBJECT keyed "0","1",..., NOT a list.** Calling
   .json() and iterating it as a list yields nothing - a second, independent
   way to produce exactly the 0-row symptom this rewrite exists to fix.

2. **Never send an empty body `{}`.** It triggers an unbounded query that
   hangs (>20s, no response). The `LandAvailable` key must always be present.
   Curiously the VALUE is ignored - the key's presence alone selects
   Lands-Available mode - but it is sent as "LANDA" to match what the app
   itself sends rather than relying on that quirk.

3. **The leading spaces in `" 100"` / `" 0"` are deliberate** - that is
   exactly what the app transmits. Left as-is rather than "cleaned up",
   since this endpoint's parameter handling is clearly loose and there is no
   upside to differing from the known-good request.

Not needed, but worth recording: the app RSA-encrypts these parameters with
JSEncrypt using a hardcoded public key served in Scripts/app/services.js.
The server accepts plaintext, so no crypto is required here. If a future
endpoint ever enforces encryption, that key is public and the scheme is
PKCS#1 v1.5.

Output: harvest_laft_osceola.json / .csv - kept separate from the other
harvesters' outputs. sync-laft-to-supabase.ps1 merges all of them.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_laft_osceola.json"
OUT_CSV = OUT_DIR / "harvest_laft_osceola.csv"

COUNTY = "Osceola"
BASE_URL = "https://officialrecords.osceolaclerk.org/browserviewtd/"
API_URL = "https://officialrecords.osceolaclerk.org/browserviewtd/api/search"

# Exactly what the app itself sends. See footgun #2 and #3 in the module
# docstring - do NOT send an empty body, and do NOT strip the leading spaces.
SEARCH_PAYLOAD = {
    "LandAvailable": "LANDA",
    "AvailDate": "19000101",
    "MaxRows": " 100",
    "RowsPerPage": " 0",
    "StartRow": " 0",
}

# Confirmed live field names in the JSON response. Anything not listed is
# either pagination metadata (rowid, _start_row, _end_row, _total_rows) or
# the `_headers` block the API repeats in every single record.
FIELD_MAP = {
    "tax_number": "case_no",
    "strap_num": "parcel",
    "trans_amt": "bid",        # "Base Bid" - the opening bid
    "bid_amt": "high_bid",
    "deed_status": "status",
    "last_name": "owners",
    "ref_1": "tax_deed_id",
    "type_code": "type",
}

# Dates come back as full ISO timestamps ("2025-04-22T00:00:00").
# sync-laft-to-supabase.ps1's ConvertTo-IsoDate only tries MM/dd/yyyy,
# M/d/yyyy and yyyy-MM-dd, so an untouched timestamp would silently land as
# NULL - the exact gap already observed on St. Lucie. Normalised here at
# harvest time instead, so every harvester keeps writing the same shape.
DATE_FIELDS = {"sale_date": "sale_date"}


def _normalise_date(value) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%m/%d/%Y")
        except ValueError:
            continue
    return text  # pass through rather than drop the data


def _clean(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _parse_response(payload) -> tuple[list[dict], int | None]:
    """The API returns an OBJECT keyed "0","1",... not a list - see footgun
    #1. Returns (records, reported_total) where reported_total comes from
    the API's own `_total_rows`, cross-checked by the caller."""
    if isinstance(payload, list):
        # Not the observed shape, but handle it rather than silently
        # returning nothing if the vendor ever switches to a plain array.
        entries = payload
    elif isinstance(payload, dict):
        entries = [payload[k] for k in sorted(payload, key=lambda k: int(k))
                   if str(k).lstrip("-").isdigit() and isinstance(payload[k], dict)]
    else:
        return [], None

    reported = None
    out: list[dict] = []
    for entry in entries:
        if reported is None and entry.get("_total_rows") is not None:
            try:
                reported = int(entry["_total_rows"])
            except (TypeError, ValueError):
                pass
        record: dict = {"county": COUNTY, "source": "laft", "url_auction": BASE_URL}
        for api_field, out_field in FIELD_MAP.items():
            value = _clean(entry.get(api_field))
            if value:
                record[out_field] = value
        for api_field, out_field in DATE_FIELDS.items():
            d = _normalise_date(entry.get(api_field))
            if d:
                record[out_field] = d
        if record.get("case_no") or record.get("parcel"):
            out.append(record)
    return out, reported


def harvest() -> list[dict]:
    resp = requests.post(
        API_URL,
        headers={
            "Content-Type": "application/json;charset=utf-8",
            "Accept": "application/json, text/plain, */*",
        },
        json=SEARCH_PAYLOAD,
        timeout=60,
    )
    resp.raise_for_status()
    try:
        payload = resp.json()
    except ValueError as exc:
        raise RuntimeError(
            f"search API did not return JSON (got {resp.headers.get('Content-Type')!r}) - "
            f"the vendor may have changed the endpoint: {exc}"
        ) from exc

    rows, reported = _parse_response(payload)

    # Loud, non-fatal cross-check against the API's own total. A genuine zero
    # is possible and must stay quiet; a MISMATCH is what hid this bug for
    # weeks, so it gets shouted about.
    if reported is not None and reported != len(rows):
        print(
            f"    WARNING: API reports {reported} total rows but {len(rows)} were parsed - "
            f"investigate before trusting this count",
            flush=True,
        )
    return rows


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"[1/1] {COUNTY}", flush=True)
    try:
        rows = harvest()
    except Exception as exc:  # noqa: BLE001 - report cleanly, don't crash the job
        print(f"    ERROR: {exc}", flush=True)
        rows = []

    if rows:
        priced = sum(1 for r in rows if r.get("bid"))
        print(f"    {len(rows)} properties ({priced} with a base bid)", flush=True)
    else:
        # Osceola has had live properties every time it has been checked by
        # hand. A zero here is more likely a regression than a real empty
        # list - say so rather than reporting it as routine.
        print(
            "    no properties currently listed - NOTE: Osceola has had live LAFT "
            "properties on every manual check to date, so verify this by hand before "
            "accepting it as a genuine zero",
            flush=True,
        )

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)

    if rows:
        fieldnames = sorted({k for row in rows for k in row.keys()})
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
            import csv

            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    else:
        OUT_CSV.write_text("", encoding="utf-8")

    print("")
    print("=" * 50)
    print(f"Harvested {len(rows)} LAFT properties total (Osceola County)")
    print("=" * 50)
    print(f"Saved: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
