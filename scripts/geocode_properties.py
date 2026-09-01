#!/usr/bin/env python3
"""Backfill latitude/longitude on `properties` using the free US Census
Bureau Geocoder (no API key needed, generous rate limits for polite use).

Why this exists: fallbackStreetviewUrl()/fallbackZillowUrl() in app.js
currently build an *address search* URL, which can land on a nearby result
instead of the actual parcel. Once latitude/longitude are populated here,
the frontend switches to a direct-coordinate link instead (see the app.js
diff alongside this script).

Requires schema-v8-geocoding.sql to have been run against Supabase first -
until then the PATCH step below will fail loudly (same intentional-failure
pattern as sync-certificates-to-supabase.ps1 without schema-v4-certificates.sql),
so a missing migration doesn't get missed.

Incremental by design: only ever processes rows where latitude IS NULL, so
this is cheap to run every harvest cycle - most of the table gets geocoded
once and never touched again, and only genuinely new properties cost an API
call on the next run. BATCH_LIMIT caps how many rows one run will attempt,
to stay a polite, well-behaved caller of a free public API.

Priority fix (2026-09-01): only ~5.6% of rows ever carry a real street+city
address (measured directly - see claude/search-and-card-data-reality.md in
the project docs); the rest are junk placeholders like "NO STREET COUNTY"
that the Census geocoder will never match. The original single unordered
query fetched whatever Postgres's default scan order happened to return -
in practice a STABLE set dominated by junk rows, since a failed attempt
never changes latitude and therefore never leaves the `latitude IS NULL`
pool or its position in that order. With BATCH_LIMIT=250 and ~2,900 junk
rows ahead of most real ones in that stable order, the same ~250 junk rows
were being retried every single run - measured live 2026-09-01: 147 rows
with a genuine comma-containing address had been sitting at zero
coordinates for over a week of twice-daily runs. Fixed by fetching the
likely-real (comma-containing address) rows FIRST, in their own query, and
only spending any leftover budget on the rest - see fetch_ungeocoded().
"""
import os
import sys
import time
import urllib.parse
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
BATCH_LIMIT = int(os.environ.get("GEOCODE_BATCH_LIMIT", "250"))
REQUEST_DELAY_SECONDS = 0.4  # polite pacing against a free public API
CENSUS_ENDPOINT = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"

if not SUPABASE_URL or not SERVICE_KEY:
    print("SUPABASE_URL / SUPABASE_SERVICE_KEY environment variables are not set - check the workflow's secrets.", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
}


def _fetch(limit, address_filter):
    """address_filter is a PostgREST filter value for the `address` column
    (e.g. "like.*,*"), or None for no extra filter on it."""
    params = {
        "latitude": "is.null",
        "select": "id,address,county",
        "limit": str(limit),
    }
    if address_filter is None:
        params["address"] = "not.is.null"
    else:
        # Can't repeat the `address` query-string key for two conditions,
        # so combine both into one PostgREST `and=(...)` expression.
        params["and"] = f"(address.not.is.null,address.{address_filter})"
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/properties", headers=HEADERS, params=params, timeout=30
    )
    if resp.status_code == 400 and "latitude" in resp.text.lower():
        # Matches the certificates-sync failure pattern on purpose - a
        # missing column reads as "schema-v8-geocoding.sql hasn't been run
        # yet" far more clearly than a raw PostgREST error would.
        print(
            "GEOCODE FAILED - most likely schema-v8-geocoding.sql hasn't been "
            "run against this Supabase project yet.\n"
            f"Error: {resp.status_code} {resp.text[:300]}",
            file=sys.stderr,
        )
        sys.exit(1)
    resp.raise_for_status()
    return resp.json()


def fetch_ungeocoded(limit):
    """Likely-real (comma-containing) addresses first, junk-address rows
    only with whatever budget is left over - see the priority-fix note in
    the module docstring for why this ordering matters. The two filters
    (`like`/`not.like` on the same pattern) are exact complements, so the
    two fetches can never overlap.

    The pattern is double-quoted (`"*,*"` not `*,*`) because these filters
    ride inside a PostgREST `and=(...)` combinator, whose own top-level
    parser splits on unquoted commas - an unquoted literal comma in the
    LIKE pattern gets read as a condition separator instead of pattern
    text, which PostgREST then rejects outright (400 Bad Request), not a
    silent misparse. Caught live 2026-09-01: this exact bug shipped in the
    first version of this fix and broke every run's geocoding step until
    fixed here."""
    real = _fetch(limit, 'like."*,*"')
    if len(real) >= limit:
        return real
    junk = _fetch(limit - len(real), 'not.like."*,*"')
    return real + junk


def geocode_one(address, county):
    query = f"{address}, {county} County, FL"
    params = {
        "address": query,
        "benchmark": "Public_AR_Current",
        "format": "json",
    }
    url = f"{CENSUS_ENDPOINT}?{urllib.parse.urlencode(params)}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    matches = data.get("result", {}).get("addressMatches", [])
    if not matches:
        return None
    coords = matches[0]["coordinates"]
    # Census returns x=longitude, y=latitude - easy to transpose, so name
    # these explicitly rather than unpacking positionally.
    return {"latitude": coords["y"], "longitude": coords["x"]}


def patch_property(property_id, latitude, longitude):
    url = f"{SUPABASE_URL}/rest/v1/properties?id=eq.{property_id}"
    patch_headers = dict(HEADERS)
    patch_headers["Prefer"] = "return=minimal"
    resp = requests.patch(
        url,
        headers=patch_headers,
        json={"latitude": latitude, "longitude": longitude},
        timeout=15,
    )
    resp.raise_for_status()


def main():
    rows = fetch_ungeocoded(BATCH_LIMIT)
    print(f"Found {len(rows)} propert{'y' if len(rows) == 1 else 'ies'} without coordinates (limit {BATCH_LIMIT} per run).")
    if not rows:
        print("Nothing to geocode.")
        return

    geocoded = 0
    no_match = 0
    errors = 0
    for i, row in enumerate(rows, 1):
        address = row.get("address")
        county = row.get("county")
        if not address or not county:
            no_match += 1
            continue
        try:
            result = geocode_one(address, county)
        except requests.RequestException as e:
            errors += 1
            print(f"  [{i}/{len(rows)}] ERROR geocoding {address!r}: {e}", file=sys.stderr)
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        if result is None:
            no_match += 1
            print(f"  [{i}/{len(rows)}] no match: {address}, {county} County, FL")
        else:
            try:
                patch_property(row["id"], result["latitude"], result["longitude"])
                geocoded += 1
                if i % 25 == 0 or i == len(rows):
                    print(f"  [{i}/{len(rows)}] geocoded {geocoded} so far...")
            except requests.RequestException as e:
                errors += 1
                print(f"  [{i}/{len(rows)}] ERROR saving coordinates for {row['id']}: {e}", file=sys.stderr)

        time.sleep(REQUEST_DELAY_SECONDS)

    print(
        f"Done. Geocoded {geocoded}, no match {no_match}, errors {errors} "
        f"(of {len(rows)} attempted)."
    )
    # Non-fatal: a batch of no-matches/errors is expected (PO boxes, typos in
    # scraped addresses, a Census outage) and shouldn't fail the whole
    # workflow the way the sanity check does - this step is additive
    # enrichment, not a correctness gate on the harvest itself.


if __name__ == "__main__":
    main()
