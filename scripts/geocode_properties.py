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

State + verification fix (2026-09-22, Phase 68). Three defects, all found by
reading production run logs and the rows they produced, not by reading code:

  1. The query was built as "<address>, <county> County, FL" for EVERY row.
     The literal ", FL" mislabelled every Texas row (69 TX auction rows
     without coordinates were being asked for as Florida addresses -
     "14107 HORSESHOE TRL, Dallas County, FL"), and "<county> County" was
     being handed to the Census parser in the CITY slot, which is not a
     place the parser can resolve. The Census geocoder does not take a
     county as an input at all.
  2. Nothing checked the answer. The Census one-line parser returns its
     best nationwide street match when the city/ZIP tokens don't resolve,
     and the old code wrote whatever came back. Measured live 2026-09-22:
     of 48 Florida auction rows geocoded by this script (no FDOR centroid),
     2 sat more than 90 km from their own county's centroid - a Lee County
     row written at 40.84,-115.79 (Elko, Nevada) and a Leon County row
     written in Osceola County. Those coordinates then fed the FEMA flood
     lookup and the aerial-imagery step for the wrong place.
  3. Run after run the whole 250-row budget went to rows that can never
     match (the latest production run: 0 geocoded, 249 no-match, 1 error),
     because "has a comma" was the only signal for "has a usable address" -
     rows carrying a ZIP but no comma ("321 GARFIELD DR 32505", or a
     newline-separated "TAMPA    33647" city line) sat in the junk tier.

  What changed:
  - build_query() uses the row's own `state` column - never a hard-coded
    "FL" - and never appends the county. A row with no `state` is skipped
    outright rather than assumed to be Florida; nothing here ever writes a
    `state` or `county` value, only latitude/longitude.
  - City/ZIP context already present in the address is preserved (a
    newline-separated city line becomes a comma-separated one); nothing is
    ever invented for rows that lack it - those are queried as
    "<street>, <STATE>" and can only be written if the answer verifies.
  - verify_match() accepts a Census match ONLY when the returned state
    equals the row's state AND the returned county (from the geographies
    endpoint, vintage Current_Current) equals the row's county. Anything
    else - state mismatch, county mismatch, or a response that carries no
    county at all - is rejected and left NULL for a later run. A stored
    coordinate is now a county-verified fact, not the parser's best guess.
  - The priority tier is "comma OR 5-digit ZIP anywhere in the address",
    with the second tier its exact complement, so ZIP-bearing rows are
    tried before bare street lines.
  - GEOCODE_DRY_RUN=1 runs the whole pass, logs every decision, and
    writes nothing - used by .github/workflows/geocode-dry-run.yml to
    measure the real success rate on production rows before this ships.
"""
import os
import re
import sys
import time
import urllib.parse
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
BATCH_LIMIT = int(os.environ.get("GEOCODE_BATCH_LIMIT", "250"))
DRY_RUN = os.environ.get("GEOCODE_DRY_RUN", "").strip().lower() in ("1", "true", "yes")
REQUEST_DELAY_SECONDS = 0.4  # polite pacing against a free public API
# The `geographies` flavour of the one-line endpoint returns the same
# coordinates as `locations` PLUS the county the point falls in (under a
# vintage), which is what lets verify_match() check the answer against the
# row's own county instead of trusting the parser.
CENSUS_ENDPOINT = "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress"
CENSUS_BENCHMARK = "Public_AR_Current"
CENSUS_VINTAGE = "Current_Current"

# "Has usable address context" = a comma (city/state already spelled out by
# the harvester) OR a 5-digit ZIP anywhere in the text. The PostgREST
# `match` operator is Postgres `~`; the second tier below is the exact
# complement of this expression so the two fetches can never overlap.
ADDRESS_CONTEXT_FILTER = 'or(address.like."*,*",address.match."[0-9]{5}")'
ADDRESS_NO_CONTEXT_FILTER = 'address.not.like."*,*",address.not.match."[0-9]{5}"'

if not SUPABASE_URL or not SERVICE_KEY:
    print("SUPABASE_URL / SUPABASE_SERVICE_KEY environment variables are not set - check the workflow's secrets.", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
}


def _fetch(limit, address_conditions):
    """address_conditions is a comma-joined list of extra PostgREST
    conditions on the `address` column (already in `and=(...)` syntax), or
    None for no extra condition beyond `address IS NOT NULL`.

    Deliberately NO state filter here: this script serves Florida and Texas
    rows alike (see test_provenance_integration.py's static check). The
    row's `state` is SELECTED, so build_query() can use it, never assumed."""
    params = {
        "latitude": "is.null",
        "select": "id,address,county,state",
        "limit": str(limit),
    }
    if address_conditions is None:
        params["address"] = "not.is.null"
    else:
        # Can't repeat the `address` query-string key for two conditions,
        # so combine both into one PostgREST `and=(...)` expression.
        params["and"] = f"(address.not.is.null,{address_conditions})"
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
    """Rows with address context (comma or ZIP) first, bare-street/junk rows
    only with whatever budget is left over - see the priority-fix notes in
    the module docstring for why this ordering matters. The two filters are
    exact complements, so the two fetches can never overlap.

    The LIKE pattern is double-quoted (`"*,*"` not `*,*`) because these
    filters ride inside a PostgREST `and=(...)` combinator, whose own
    top-level parser splits on unquoted commas - an unquoted literal comma
    in the pattern gets read as a condition separator instead of pattern
    text, which PostgREST then rejects outright (400 Bad Request), not a
    silent misparse. Caught live 2026-09-01. The regex pattern is quoted
    for the same reason (its braces are harmless, its brackets are not
    special to the combinator, but quoting keeps both tiers uniform)."""
    real = _fetch(limit, ADDRESS_CONTEXT_FILTER)
    if len(real) >= limit:
        return real
    junk = _fetch(limit - len(real), ADDRESS_NO_CONTEXT_FILTER)
    return real + junk


def _norm(text):
    """Comparison key for place names: 'St. Lucie' / 'ST LUCIE' / 'st lucie'
    all become 'stlucie'; 'Miami-Dade' becomes 'miamidade'."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def build_query(address, state):
    """The one-line address handed to the Census geocoder.

    - Newlines (the LienHub/RealAuction "street\\nCITY    ZIP" shape) become
      comma separators so the city line is read as a city, not as more
      street text; runs of whitespace collapse.
    - The row's own state is appended unless the address already carries it
      as a separate token ("..., Holiday FL 34690", "..., Live Oak, FL",
      "LAKE WALES, FL- 33898" all already do).
    - The county is never appended: the Census parser has no county input,
      and putting "<county> County" in the city slot is exactly what made
      every bare-street row fail before.
    - No city or ZIP is ever invented. A bare street line goes out as
      "<street>, <STATE>" and is only kept if verify_match() agrees."""
    text = re.sub(r"\s*[\r\n]+\s*", ", ", (address or "").strip())
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*,\s*", ", ", text).strip(" ,")
    state = (state or "").strip().upper()
    if not state:
        raise ValueError("build_query needs the row's state - never assume one")
    if not re.search(rf"(?:^|[\s,]){re.escape(state)}(?:$|[\s,.\-])", text, re.IGNORECASE):
        text = f"{text}, {state}"
    return text


def verify_match(match, state, county):
    """Returns (ok, reason). A match is only usable when the Census answer
    agrees with the row on BOTH state and county. 'unverifiable-county'
    means the response carried no county geography at all - treated as a
    rejection, never as a pass."""
    components = match.get("addressComponents") or {}
    if _norm(components.get("state")) != _norm(state):
        return False, "state-mismatch"
    geographies = match.get("geographies") or {}
    counties = geographies.get("Counties") or []
    if not counties:
        return False, "unverifiable-county"
    names = set()
    for entry in counties:
        base = entry.get("BASENAME") or re.sub(r"\s+county$", "", entry.get("NAME") or "", flags=re.IGNORECASE)
        names.add(_norm(base))
    if _norm(county) not in names:
        return False, "county-mismatch"
    return True, "verified"


def geocode_one(address, county, state):
    """Returns (result, reason). result is {"latitude", "longitude",
    "matched_address"} for a county-verified match, else None. reason is
    'verified', 'no-match', or the rejection reason from verify_match() for
    the last candidate examined (every candidate is tried in order; the
    first one that verifies wins)."""
    query = build_query(address, state)
    params = {
        "address": query,
        "benchmark": CENSUS_BENCHMARK,
        "vintage": CENSUS_VINTAGE,
        "format": "json",
    }
    url = f"{CENSUS_ENDPOINT}?{urllib.parse.urlencode(params)}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    matches = data.get("result", {}).get("addressMatches", [])
    if not matches:
        return None, "no-match"
    reason = "no-match"
    for match in matches:
        ok, reason = verify_match(match, state, county)
        if not ok:
            continue
        coords = match["coordinates"]
        # Census returns x=longitude, y=latitude - easy to transpose, so name
        # these explicitly rather than unpacking positionally.
        return {
            "latitude": coords["y"],
            "longitude": coords["x"],
            "matched_address": match.get("matchedAddress", ""),
        }, "verified"
    return None, reason


def patch_property(property_id, latitude, longitude):
    """Writes ONLY latitude/longitude. State, county and every other column
    stay exactly as the harvester left them - this step supplements a
    missing coordinate, it never rewrites identity."""
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
    mode = " [DRY RUN - nothing will be written]" if DRY_RUN else ""
    print(f"Found {len(rows)} propert{'y' if len(rows) == 1 else 'ies'} without coordinates (limit {BATCH_LIMIT} per run).{mode}")
    if not rows:
        print("Nothing to geocode.")
        return

    counts = {
        "verified": 0, "no-match": 0, "state-mismatch": 0, "county-mismatch": 0,
        "unverifiable-county": 0, "skipped-no-address": 0, "skipped-no-state": 0,
        "errors": 0,
    }
    per_state = {}  # state -> [verified, attempted]
    for i, row in enumerate(rows, 1):
        address = row.get("address")
        county = row.get("county")
        state = (row.get("state") or "").strip().upper()
        if not address or not county:
            counts["skipped-no-address"] += 1
            continue
        if not state:
            # Never guess a state for a row that has none - a Florida
            # default here is exactly the defect this rewrite removes.
            counts["skipped-no-state"] += 1
            print(f"  [{i}/{len(rows)}] skipped (row has no state): {address!r} / {county}")
            continue
        query = build_query(address, state)
        tally = per_state.setdefault(state, [0, 0])
        tally[1] += 1
        try:
            result, reason = geocode_one(address, county, state)
        except requests.RequestException as e:
            counts["errors"] += 1
            print(f"  [{i}/{len(rows)}] ERROR geocoding {query!r}: {e}", file=sys.stderr)
            time.sleep(REQUEST_DELAY_SECONDS)
            continue

        if result is None:
            counts[reason] = counts.get(reason, 0) + 1
            if reason == "no-match":
                print(f"  [{i}/{len(rows)}] no match: {query}")
            else:
                print(f"  [{i}/{len(rows)}] rejected ({reason}, row county {county}): {query}")
        else:
            counts["verified"] += 1
            tally[0] += 1
            print(f"  [{i}/{len(rows)}] verified ({county} County, {state}): {query} -> {result['matched_address']}")
            if not DRY_RUN:
                try:
                    patch_property(row["id"], result["latitude"], result["longitude"])
                except requests.RequestException as e:
                    counts["errors"] += 1
                    print(f"  [{i}/{len(rows)}] ERROR saving coordinates for {row['id']}: {e}", file=sys.stderr)

        time.sleep(REQUEST_DELAY_SECONDS)

    attempted = sum(v for v in counts.values()) - counts["skipped-no-address"] - counts["skipped-no-state"]
    print(
        f"Done. Verified {counts['verified']}, no match {counts['no-match']}, "
        f"rejected state-mismatch {counts['state-mismatch']}, county-mismatch {counts['county-mismatch']}, "
        f"unverifiable-county {counts['unverifiable-county']}, errors {counts['errors']} "
        f"(of {attempted} attempted; skipped {counts['skipped-no-address']} without address/county, "
        f"{counts['skipped-no-state']} without state).{mode}"
    )
    print("Per-state verified/attempted this run:")
    for state in sorted(per_state):
        verified, tried = per_state[state]
        print(f"  {state}: {verified}/{tried}")
    # Non-fatal: a batch of no-matches/errors is expected (PO boxes, typos in
    # scraped addresses, a Census outage) and shouldn't fail the whole
    # workflow the way the sanity check does - this step is additive
    # enrichment, not a correctness gate on the harvest itself.

    # Phase 12 (Production Provenance & Data Lineage Integration): this is
    # the one real, currently-running ENRICHED-stage step in this
    # codebase's actual production pipeline (confirmed: this script has no
    # state FILTER anywhere in _fetch()/fetch_ungeocoded() above - it runs
    # against TX and FL rows alike; the row's state is read, never used to
    # exclude rows). Logged here, plain-language, rather than as a
    # harvesters/governance/provenance.py Provenance object: a
    # `Provenance.source_id` is meant to identify a SOURCE_REGISTRY entry
    # (a governed, restriction-bearing commercial source) - the free US
    # Census Bureau Geocoder this script calls is neither commercial nor
    # gated, so representing it as a fabricated registry-shaped source_id
    # would be inventing structure this enrichment doesn't actually have,
    # not integrating real provenance (Phase 12 Step 23 - do not
    # over-engineer). What matters for the provenance record is the
    # distinction this line documents: SOURCE VALUES (a row's
    # originally-harvested `latitude`/`longitude`, if any) are NEVER touched
    # here - only rows already NULL are ever selected (see
    # fetch_ungeocoded()'s `latitude: "is.null"` filter above), so an
    # ENRICHED value here always supplements, never overwrites, whatever a
    # SOURCE value would have been. See
    # docs/provenance-production-integration.md's "Enrichment lineage"
    # section for the full accounting.
    if counts["verified"] and not DRY_RUN:
        print(
            f"Provenance (Phase 12, audit-only, not persisted): ENRICHED {counts['verified']} propert"
            f"{'y' if counts['verified'] == 1 else 'ies'}' latitude/longitude via the free US Census Bureau "
            "Geocoder (classification=DERIVED, is_source_provided=False - a project-computed "
            "enrichment, not from any SOURCE_REGISTRY entry; supplements NULL values only, never "
            "overwrites a source-provided value; each value county-verified against the row's own "
            "state/county before being written) - see docs/provenance-production-integration.md",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
