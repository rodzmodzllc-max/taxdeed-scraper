#!/usr/bin/env python3
"""Backfill `prop_type` (and, only where the scraped `address` is a known
junk placeholder, `address`) on `properties` using Florida's free, no-API-
key statewide parcel dataset: the FL Dept of Revenue / Florida Geographic
Information Office "Florida Statewide Cadastral" ArcGIS FeatureServer,
built from the same annual tax-roll submissions every one of the 67 county
property appraisers already sends the state.

Why this exists (2026-09-02 scoping, see claude/improvement-roadmap.md in
the project docs for the full research writeup): the original plan was to
build a property-appraiser CAMA scraper per county (Qpublic/Schneider for
some, bespoke portals for the big counties) - 40+ potential harvesters.
Before writing any of that, a live test against this project's own data
found something much cheaper: 99.2% of `properties` rows already carry a
`parcel` number (captured straight off the source listing, not inferred),
and that parcel number can be looked up directly against ONE free statewide
API instead of 60+ county-specific ones. Verified live: exact matches for
Alachua/Marion with zero changes, Miami-Dade after stripping dashes from
our stored format. Some counties' parcel-number formatting doesn't match
the statewide layer's PARCEL_ID as-is (Volusia, Nassau confirmed so far) -
NORMALIZE_CANDIDATES below tries a few cheap reformattings automatically
rather than requiring that every county's exact format be hand-researched
up front; a county whose format isn't cracked by any candidate just quietly
gets 0 matches and its rows are left alone; the county-level match-rate
line this script prints is what identifies which counties still need a
bespoke normalization rule added here.

Important nuance (confirmed live, see the roadmap doc): the statewide layer
is sourced from the SAME county tax-roll data that produces our own junk
address placeholders ("UNASSIGNED LOCATION RE", "NO STREET COUNTY", etc.)
for genuinely-vacant/unassigned parcels - so this will NOT invent a real
street address where the county itself doesn't have one on file. It DOES
still return DOR_UC (the property-type/use code) for those same parcels,
which is the main win here: property-type coverage can approach the ~99%
parcel-coverage ceiling even for rows whose address coverage is capped by
a real data limitation, not a scraper gap.

Fairness / anti-starvation design (the geocoding backfill's own hard-won
lesson, applied proactively here rather than waiting to get bitten by it
again - see the geocoding starvation-bug writeup in the roadmap doc): a
flat `LIMIT BATCH_LIMIT` with no ordering would let whichever counties
happen to sit first in Postgres's stable scan order consume the whole
budget every run, and a county whose parcel format never matches (e.g.
Volusia/Nassau today) would occupy that spot forever, permanently starving
every other county's rows behind it - the exact failure mode already found
and fixed in scripts/geocode_properties.py. Fixed here by construction
instead of by ordering: every county with outstanding rows gets its own
small, capped slice (PER_COUNTY_LIMIT) each run, in a randomized county
order, so a county that can never match still only ever spends its own
small quota and can never block another county's rows.

Incremental by design, same as geocode_properties.py: only ever touches
rows where prop_type IS NULL (for the type backfill) - once a row is
enriched it's never re-processed, so this is cheap to run every harvest
cycle.
"""
import os
import random
import sys
import time
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
BATCH_LIMIT = int(os.environ.get("ENRICH_BATCH_LIMIT", "300"))
PER_COUNTY_LIMIT = int(os.environ.get("ENRICH_PER_COUNTY_LIMIT", "10"))
REQUEST_DELAY_SECONDS = 0.3  # polite pacing against a free public API
FDOR_ENDPOINT = (
    "https://services9.arcgis.com/Gh9awoU677aKree0/arcgis/rest/services/"
    "Florida_Statewide_Cadastral/FeatureServer/0/query"
)

if not SUPABASE_URL or not SERVICE_KEY:
    print("SUPABASE_URL / SUPABASE_SERVICE_KEY environment variables are not set - check the workflow's secrets.", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
}

# Standard FL DOR county numbering: 67 counties, alphabetical, 11-77.
# Confirmed live against the FDOR layer this session for Alachua (11),
# Miami-Dade (23), Marion (52), Nassau (55), Volusia (74) - all matched
# the CO_NO the layer itself returned for known parcels in those counties.
COUNTY_CODES = {
    "Alachua": 11, "Baker": 12, "Bay": 13, "Bradford": 14, "Brevard": 15,
    "Broward": 16, "Calhoun": 17, "Charlotte": 18, "Citrus": 19, "Clay": 20,
    "Collier": 21, "Columbia": 22, "Miami-Dade": 23, "DeSoto": 24, "Dixie": 25,
    "Duval": 26, "Escambia": 27, "Flagler": 28, "Franklin": 29, "Gadsden": 30,
    "Gilchrist": 31, "Glades": 32, "Gulf": 33, "Hamilton": 34, "Hardee": 35,
    "Hendry": 36, "Hernando": 37, "Highlands": 38, "Hillsborough": 39,
    "Holmes": 40, "Indian River": 41, "Jackson": 42, "Jefferson": 43,
    "Lafayette": 44, "Lake": 45, "Lee": 46, "Leon": 47, "Levy": 48,
    "Liberty": 49, "Madison": 50, "Manatee": 51, "Marion": 52, "Martin": 53,
    "Monroe": 54, "Nassau": 55, "Okaloosa": 56, "Okeechobee": 57,
    "Orange": 58, "Osceola": 59, "Palm Beach": 60, "Pasco": 61,
    "Pinellas": 62, "Polk": 63, "Putnam": 64, "St. Johns": 65,
    "St. Lucie": 66, "Santa Rosa": 67, "Sarasota": 68, "Seminole": 69,
    "Sumter": 70, "Suwannee": 71, "Taylor": 72, "Union": 73, "Volusia": 74,
    "Wakulla": 75, "Walton": 76, "Washington": 77,
}
# A few counties get harvested/stored under a slightly different spelling
# than the canonical DOR name above - map those aliases here rather than
# silently failing to resolve a CO_NO for them.
COUNTY_ALIASES = {
    "Dade": "Miami-Dade",
    "St Johns": "St. Johns",
    "Saint Johns": "St. Johns",
    "St Lucie": "St. Lucie",
    "Saint Lucie": "St. Lucie",
    "DeSoto County": "DeSoto",
}

# Cheap, generic reformattings tried in order against a county's stored
# `parcel` value until one matches the FDOR layer's PARCEL_ID for that
# county. Confirmed live this session: identity works for Alachua/Marion,
# dash-stripped works for Miami-Dade. Kept intentionally generic (no
# per-county special-casing yet) - counties that need something smarter
# than these will show up with a 0%% match rate in this script's own
# per-county summary, which is the signal to add a rule here.
def normalize_candidates(parcel):
    parcel = parcel.strip()
    seen = set()
    candidates = []
    for value in (
        parcel,
        parcel.replace("-", ""),
        parcel.replace(" ", ""),
        "".join(ch for ch in parcel if ch.isalnum()),
    ):
        if value and value not in seen:
            seen.add(value)
            candidates.append(value)
    return candidates


# Standard statewide FL DOR use-code table (same 2-digit codes used by
# every county property appraiser's own published copy, e.g.
# https://www.leepa.org/Docs/Codes/DOR_Code_List.pdf - confirmed identical
# scheme against live DOR_UC values returned by the FDOR layer this
# session: 001->Single Family, 000->Vacant Residential, 002->Mobile Home,
# 010->Vacant Commercial, 041->Light Manufacturing, 052->Cropland Class II).
# Only used to backfill prop_type when it's currently NULL - never
# overwrites an existing scraped value (which often carries more specific
# info, like bed/bath counts or acreage, that a use code can't provide).
DOR_USE_LABELS = {
    0: "Vacant Residential", 1: "Single Family", 2: "Mobile Home",
    3: "Multi-Family", 4: "Condo", 5: "Cooperative", 6: "Retirement Home",
    7: "Residential", 8: "Multi-Family", 9: "Residential Common Area",
    10: "Vacant Commercial", 39: "Hotel/Motel",
    40: "Vacant Industrial", 70: "Vacant Institutional",
    80: "Vacant Governmental",
}
def dor_use_to_prop_type(dor_uc):
    try:
        code = int(str(dor_uc).strip())
    except (TypeError, ValueError):
        return None
    if code in DOR_USE_LABELS:
        return DOR_USE_LABELS[code]
    if 0 <= code <= 9:
        return "Residential"
    if 10 <= code <= 39:
        return "Commercial"
    if 40 <= code <= 49:
        return "Industrial"
    if 50 <= code <= 69:
        return "Agricultural"
    if 70 <= code <= 79:
        return "Institutional"
    if 80 <= code <= 89:
        return "Government"
    if 90 <= code <= 99:
        return "Miscellaneous"
    return None


_JUNK_MARKERS = ("UNASSIGNED", "UNKNOWN", "NO STREET", "NOT ASSIGNED", "N/A")
def is_junk_address(address):
    if not address:
        return True
    upper = address.strip().upper()
    if not upper:
        return True
    if any(marker in upper for marker in _JUNK_MARKERS):
        return True
    # A genuine situs address almost always starts with a house number -
    # deliberately conservative (only used to decide whether it's SAFE to
    # overwrite, never to decide whether to geocode/display), so treating
    # "no digit anywhere" as junk risks nothing beyond leaving well enough
    # alone on an address this heuristic can't confidently classify.
    return not any(ch.isdigit() for ch in upper)


def is_junk_fdor_address(phy_addr1, phy_city):
    if not phy_addr1 or is_junk_address(phy_addr1):
        return True
    if not phy_city or not phy_city.strip():
        return True
    return False


def fetch_needing_enrichment_counties():
    """All distinct counties that still have at least one row with a
    parcel number but no prop_type - the fairness unit for PER_COUNTY_LIMIT."""
    params = {
        "select": "county",
        "parcel": "not.is.null",
        "prop_type": "is.null",
        "limit": "5000",
    }
    resp = requests.get(f"{SUPABASE_URL}/rest/v1/properties", headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    counties = sorted({row["county"] for row in resp.json() if row.get("county")})
    random.shuffle(counties)
    return counties


def fetch_county_batch(county, limit):
    params = {
        "select": "id,parcel,address,county",
        "county": f"eq.{county}",
        "parcel": "not.is.null",
        "prop_type": "is.null",
        "limit": str(limit),
    }
    resp = requests.get(f"{SUPABASE_URL}/rest/v1/properties", headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def lookup_fdor(county, parcel):
    co_no = COUNTY_CODES.get(COUNTY_ALIASES.get(county, county))
    if co_no is None:
        return None, None  # unmapped county name - skip rather than guess
    for candidate in normalize_candidates(parcel):
        # Escape single quotes defensively - parcel numbers are normally
        # digits/letters/dashes only, but never trust scraped input in a
        # hand-built filter string.
        safe = candidate.replace("'", "''")
        params = {
            "where": f"PARCEL_ID='{safe}' AND CO_NO={co_no}",
            "outFields": "PHY_ADDR1,PHY_CITY,PHY_ZIPCD,DOR_UC",
            "f": "json",
        }
        resp = requests.get(FDOR_ENDPOINT, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features", [])
        if features:
            return features[0].get("attributes", {}), candidate
    return None, None


def patch_property(property_id, fields):
    url = f"{SUPABASE_URL}/rest/v1/properties?id=eq.{property_id}"
    patch_headers = dict(HEADERS)
    patch_headers["Prefer"] = "return=minimal"
    resp = requests.patch(url, headers=patch_headers, json=fields, timeout=15)
    resp.raise_for_status()


def main():
    counties = fetch_needing_enrichment_counties()
    print(f"{len(counties)} counties have rows needing enrichment (parcel set, prop_type NULL).")
    if not counties:
        print("Nothing to enrich.")
        return

    total_attempted = 0
    total_matched = 0
    total_type_set = 0
    total_address_fixed = 0
    total_unmapped_county = 0
    per_county_matches = {}

    for county in counties:
        if total_attempted >= BATCH_LIMIT:
            break
        rows = fetch_county_batch(county, min(PER_COUNTY_LIMIT, BATCH_LIMIT - total_attempted))
        if not rows:
            continue
        county_matched = 0
        for row in rows:
            total_attempted += 1
            parcel = row.get("parcel")
            if not parcel:
                continue
            if COUNTY_ALIASES.get(county, county) not in COUNTY_CODES:
                total_unmapped_county += 1
                time.sleep(REQUEST_DELAY_SECONDS)
                continue
            try:
                attrs, matched_candidate = lookup_fdor(county, parcel)
            except requests.RequestException as e:
                print(f"  [{county}] ERROR looking up parcel {parcel!r}: {e}", file=sys.stderr)
                time.sleep(REQUEST_DELAY_SECONDS)
                continue

            if attrs is None:
                time.sleep(REQUEST_DELAY_SECONDS)
                continue

            total_matched += 1
            county_matched += 1
            fields = {}

            prop_type = dor_use_to_prop_type(attrs.get("DOR_UC"))
            if prop_type:
                fields["prop_type"] = prop_type
                total_type_set += 1

            if is_junk_address(row.get("address")) and not is_junk_fdor_address(
                attrs.get("PHY_ADDR1"), attrs.get("PHY_CITY")
            ):
                zip_part = f" {attrs['PHY_ZIPCD']}" if attrs.get("PHY_ZIPCD") else ""
                fields["address"] = f"{attrs['PHY_ADDR1']}, {attrs['PHY_CITY']}, FL{zip_part}"
                total_address_fixed += 1

            if fields:
                try:
                    patch_property(row["id"], fields)
                except requests.RequestException as e:
                    print(f"  [{county}] ERROR saving parcel {parcel!r} (matched via {matched_candidate!r}): {e}", file=sys.stderr)

            time.sleep(REQUEST_DELAY_SECONDS)

        if rows:
            per_county_matches[county] = (county_matched, len(rows))

    print(
        f"Done. Attempted {total_attempted}, FDOR matches {total_matched} "
        f"(prop_type set {total_type_set}, address fixed {total_address_fixed}), "
        f"unmapped-county rows skipped {total_unmapped_county}."
    )
    print("Per-county match rate this run (matched/attempted) - a persistent 0 for a county across runs is the signal its parcel-number format needs a new normalize_candidates() rule:")
    for county, (matched, attempted) in sorted(per_county_matches.items()):
        print(f"  {county}: {matched}/{attempted}")
    # Non-fatal by design, same reasoning as geocode_properties.py: this is
    # additive enrichment, not a correctness gate on the harvest itself.


if __name__ == "__main__":
    main()
