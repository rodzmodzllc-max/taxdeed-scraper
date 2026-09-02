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

Incremental by design, same as geocode_properties.py: a row is stamped with
`fdor_enriched_at` on a successful match and never re-fetched afterwards, so
this is cheap to run every harvest cycle. Rows that did NOT match are left
unstamped and retried later on purpose, so a county whose parcel format gets
cracked in a future revision picks up its whole backlog automatically.

What it fills (expanded 2026-09-02 from just prop_type/address, after finding
the layer exposes 121 fields rather than the 4 originally used):
  * prop_type, address     - as before (address only over a junk placeholder)
  * market                 - JV, the county appraiser's own statutory "just
                             value"; `value_year` carries the assessment year
                             alongside it so the UI can attribute the number
                             honestly instead of implying a live estimate
  * assessed, owner_name   - fill-blank only, never over a scraped value
  * latitude/longitude     - the parcel polygon's centroid, which needs no
                             street address and so lifts map/Street View
                             coverage off the ~3.6% address-geocoding ceiling
  * year_built, living_area, lot_sqft, num_buildings, land_value, legal_desc,
    last_sale_price, last_sale_year - columns only this script populates
"""
import os
import random
import sys
import time
from datetime import datetime, timezone

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
# Raised 2026-09-02 from 300/10. Measured live at that point: 2,041 of 3,232
# rows sat in counties this script has ALREADY matched successfully at least
# once - i.e. they were merely queued behind the old per-run cap, not blocked
# by anything. At 300/run that backlog needed ~7 runs (3+ days) to clear,
# which is what kept mappable coordinates at a few hundred rows. These
# limits clear it in 2-3 runs instead. Steady state stays cheap regardless:
# `fdor_enriched_at` means only genuinely new rows are ever fetched again.
BATCH_LIMIT = int(os.environ.get("ENRICH_BATCH_LIMIT", "1000"))
PER_COUNTY_LIMIT = int(os.environ.get("ENRICH_PER_COUNTY_LIMIT", "40"))
# A county whose parcel format this script can't match burns one request per
# normalize_candidates() variant on every row - 8 wasted lookups per row now
# that the trailing-"R" variants exist. Rather than let an unmatchable county
# spend its whole enlarged slice proving the same thing 40 times, give up on
# it after this many CONSECUTIVE misses within a single run and hand the
# leftover budget to counties that are actually producing.
#
# This does not weaken the anti-starvation design: the county is still tried
# from scratch on the very next run (misses are never stamped), so a format
# fixed later still picks up its whole backlog - exactly what happened for
# Duval. It only stops one run from wasting minutes on a known-bad format.
COUNTY_MISS_STREAK = int(os.environ.get("ENRICH_COUNTY_MISS_STREAK", "6"))
REQUEST_DELAY_SECONDS = 0.3  # polite pacing against a free public API
FDOR_ENDPOINT = (
    "https://services9.arcgis.com/Gh9awoU677aKree0/arcgis/rest/services/"
    "Florida_Statewide_Cadastral/FeatureServer/0/query"
)

# The layer exposes 121 fields; this is the subset that maps onto something a
# bidder actually wants to see on a property card. Confirmed live 2026-09-02
# against a real matched parcel (Duval 0037090000R -> 6422 BLUEBIRD RD,
# JACKSONVILLE: JV 68017, ACT_YR_BLT 1958, TOT_LVG_AR 1840, LND_SQFOOT 16456,
# OWN_NAME "OAK CLIFF BIBLE CHURCH INCORPO", ASMNT_YR 2025).
#
# JV ("just value") is the single most valuable field here: it is the county
# property appraiser's own statutory estimate of market value, which is
# exactly the honest, attributable number this project needs (the app's
# `market` column was only ~3.6% populated before this). It is NOT a Zestimate
# and must never be labelled as a live/AVM estimate - the companion
# `value_year` column carries ASMNT_YR so the UI can say whose number it is
# and for which tax year.
FDOR_OUT_FIELDS = ",".join([
    "PARCEL_ID", "ASMNT_YR",
    "PHY_ADDR1", "PHY_CITY", "PHY_ZIPCD",
    "DOR_UC",
    "JV", "AV_NSD", "LND_VAL", "JV_HMSTD",
    "ACT_YR_BLT", "TOT_LVG_AR", "NO_BULDNG", "LND_SQFOOT",
    "OWN_NAME", "S_LEGAL",
    "SALE_PRC1", "SALE_YR1",
])


def _num(value):
    """FDOR uses 0 as the 'no data' sentinel for every numeric field (a real
    $0 just value / year built / square footage doesn't occur), so 0 and
    blanks both become None rather than being written as a misleading 0."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None


def _int(value):
    num = _num(value)
    return int(num) if num is not None else None


def _text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None

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
#
# The trailing-"R" variants were added 2026-09-02 after discovering (via
# fast PARCEL_ID-prefix LIKE queries against the FDOR layer, which stay
# indexed/fast even though bare CO_NO or PHY_ADDR1 queries time out - see
# the roadmap doc for the full investigation) that Duval's FDOR PARCEL_ID
# is exactly its dash-stripped RE# plus a literal trailing "R"
# (e.g. our stored "003709-0000" -> FDOR "0037090000R"), confirmed exact
# across an 11/11 sample. Kept generic rather than Duval-only since it's a
# cheap extra equality try that can only produce a false positive if some
# other county's real PARCEL_ID happens to exactly equal
# <our value>+"R", which is not realistic.
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
    for value in list(candidates):
        with_r = value + "R"
        if with_r not in seen:
            seen.add(with_r)
            candidates.append(with_r)
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
    """All distinct counties that still have at least one row with a parcel
    number that this script hasn't successfully enriched yet - the fairness
    unit for PER_COUNTY_LIMIT.

    The "already done" marker is `fdor_enriched_at`, not `prop_type IS NULL`.
    That changed 2026-09-02 when this script grew from filling one field
    (prop_type) to filling a dozen: keying off prop_type would have
    permanently locked out every row enriched by an earlier, narrower version
    of this script, so the ~300 rows already typed would never receive the
    just value, owner name, coordinates, year built or living area now
    available to them. A dedicated timestamp column is set only on a
    successful FDOR match, so each row is enriched exactly once and is never
    re-fetched afterwards.

    Rows that do NOT match stay unmarked and are retried on later runs - that
    is deliberate, so that a county whose parcel format gets cracked later
    (as Duval's was) picks up its backlog automatically. The per-county quota
    below is what keeps those retries from starving anyone.

    `parcel=not.is.null` alone still matches empty-string parcels (a real
    row shape confirmed live 2026-09-02: some Citrus rows carry `parcel=''`
    rather than NULL, presumably because the source listing genuinely had
    no parcel number and a harvester wrote '' instead of leaving it NULL).
    Those rows can never match anything here - excluding them keeps a
    parcel-less county from consuming its PER_COUNTY_LIMIT slice on rows
    this script can never fix, without changing the fairness design."""
    params = {
        "select": "county",
        "and": "(parcel.not.is.null,parcel.neq.\"\")",
        "fdor_enriched_at": "is.null",
        "limit": "5000",
    }
    resp = requests.get(f"{SUPABASE_URL}/rest/v1/properties", headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    counties = sorted({row["county"] for row in resp.json() if row.get("county")})
    random.shuffle(counties)
    return counties


def fetch_county_batch(county, limit):
    # Same empty-string-parcel exclusion as fetch_needing_enrichment_counties()
    # above, and for the same reason (confirmed live for Citrus 2026-09-02):
    # `parcel=not.is.null` alone still matches `parcel=''` rows, which can
    # never resolve through lookup_fdor() and would otherwise burn part of
    # this county's PER_COUNTY_LIMIT slice every run on unfixable rows.
    # Existing values come back too, because this script only ever FILLS
    # BLANKS on columns a harvester also writes (market/assessed/owner_name/
    # coordinates/prop_type) - a scraped value from the source listing always
    # wins over the tax roll's copy of it.
    params = {
        "select": "id,parcel,address,county,prop_type,market,assessed,owner_name,latitude,longitude",
        "county": f"eq.{county}",
        "and": "(parcel.not.is.null,parcel.neq.\"\")",
        "fdor_enriched_at": "is.null",
        "limit": str(limit),
    }
    resp = requests.get(f"{SUPABASE_URL}/rest/v1/properties", headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def lookup_fdor(county, parcel):
    """Returns (attributes, centroid, matched_candidate) or (None, None, None).

    `returnCentroid=true` + `outSR=4326` asks the layer for each matched
    parcel polygon's centroid in plain WGS84 lat/lon, with returnGeometry
    off so the full ring coordinates don't come back too. This is the single
    biggest win available here: geocoding coverage was stuck at ~3.6% because
    the US Census geocoder can only match a real street address and ~94% of
    these rows carry a junk placeholder instead (see the geocoding
    starvation writeup in the roadmap doc). A parcel centroid needs no
    address at all - every parcel that matches by number gets exact
    coordinates, which is what makes the map pin, the Street View link and
    the coordinate-based Zillow link work for those rows.
    """
    co_no = COUNTY_CODES.get(COUNTY_ALIASES.get(county, county))
    if co_no is None:
        return None, None, None  # unmapped county name - skip rather than guess
    for candidate in normalize_candidates(parcel):
        # Escape single quotes defensively - parcel numbers are normally
        # digits/letters/dashes only, but never trust scraped input in a
        # hand-built filter string.
        safe = candidate.replace("'", "''")
        params = {
            "where": f"PARCEL_ID='{safe}' AND CO_NO={co_no}",
            "outFields": FDOR_OUT_FIELDS,
            "returnGeometry": "false",
            "returnCentroid": "true",
            "outSR": "4326",
            "f": "json",
        }
        resp = requests.get(FDOR_ENDPOINT, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        features = data.get("features", [])
        if features:
            feature = features[0]
            return feature.get("attributes", {}), feature.get("centroid"), candidate
    return None, None, None


def patch_property(property_id, fields):
    url = f"{SUPABASE_URL}/rest/v1/properties?id=eq.{property_id}"
    patch_headers = dict(HEADERS)
    patch_headers["Prefer"] = "return=minimal"
    resp = requests.patch(url, headers=patch_headers, json=fields, timeout=15)
    resp.raise_for_status()


def build_update_fields(row, attrs, centroid):
    """Map one matched FDOR record onto `properties` columns.

    Two deliberately different rules apply, by column:

    1. Columns a harvester ALSO writes (prop_type, market, assessed,
       owner_name, latitude/longitude, address) are only ever used to FILL A
       BLANK. A value scraped from the source auction listing is the more
       authoritative one for that auction and is never overwritten by the tax
       roll's copy of it. `address` keeps its existing extra guard: it is only
       replaced when ours is a known junk placeholder AND the tax roll's is a
       real street address.
    2. Columns only this script populates (year_built, living_area, lot_sqft,
       num_buildings, land_value, legal_desc, last_sale_*, value_year) are
       written straight from the tax roll, since nothing else supplies them.

    `homestead` is a special case: only positive evidence is written. A
    homestead exemption on file (JV_HMSTD > 0) sets it True, but the absence
    of one never writes False, because that column already carries a
    non-null value on every row and a blanket overwrite would destroy
    whatever a harvester legitimately recorded there.
    """
    fields = {}

    prop_type = dor_use_to_prop_type(attrs.get("DOR_UC"))
    if prop_type and not _text(row.get("prop_type")):
        fields["prop_type"] = prop_type

    just_value = _num(attrs.get("JV"))
    if just_value is not None and _num(row.get("market")) is None:
        fields["market"] = just_value

    assessed = _num(attrs.get("AV_NSD"))
    if assessed is not None and _num(row.get("assessed")) is None:
        fields["assessed"] = assessed

    owner = _text(attrs.get("OWN_NAME"))
    if owner and not _text(row.get("owner_name")):
        fields["owner_name"] = owner

    # Parcel centroid -> coordinates, but only for rows that have none. A real
    # geocode of a real street address is more precise than a polygon centroid
    # on a large/irregular parcel, so an existing fix is never replaced.
    if centroid and row.get("latitude") is None and row.get("longitude") is None:
        lat, lon = centroid.get("y"), centroid.get("x")
        if (
            isinstance(lat, (int, float)) and isinstance(lon, (int, float))
            # Sanity-bound to Florida rather than merely to valid lat/lon, so a
            # bad projection or a swapped x/y can never silently drop a pin in
            # the ocean or another state.
            and 24.0 <= lat <= 31.5 and -88.0 <= lon <= -79.5
        ):
            fields["latitude"] = lat
            fields["longitude"] = lon

    if is_junk_address(row.get("address")) and not is_junk_fdor_address(
        attrs.get("PHY_ADDR1"), attrs.get("PHY_CITY")
    ):
        zip_part = f" {_text(attrs.get('PHY_ZIPCD')) or ''}".rstrip()
        fields["address"] = f"{attrs['PHY_ADDR1']}, {attrs['PHY_CITY']}, FL{zip_part}"

    if _num(attrs.get("JV_HMSTD")) is not None:
        fields["homestead"] = True

    for column, value in (
        ("year_built", _int(attrs.get("ACT_YR_BLT"))),
        ("living_area", _int(attrs.get("TOT_LVG_AR"))),
        ("lot_sqft", _int(attrs.get("LND_SQFOOT"))),
        ("num_buildings", _int(attrs.get("NO_BULDNG"))),
        ("land_value", _num(attrs.get("LND_VAL"))),
        ("legal_desc", _text(attrs.get("S_LEGAL"))),
        ("last_sale_price", _num(attrs.get("SALE_PRC1"))),
        ("last_sale_year", _int(attrs.get("SALE_YR1"))),
        ("value_year", _int(attrs.get("ASMNT_YR"))),
    ):
        if value is not None:
            fields[column] = value

    return fields


def main():
    counties = fetch_needing_enrichment_counties()
    print(f"{len(counties)} counties have rows needing enrichment (parcel set, not yet FDOR-enriched).")
    if not counties:
        print("Nothing to enrich.")
        return

    total_attempted = 0
    total_matched = 0
    total_unmapped_county = 0
    per_county_matches = {}
    # Per-column fill counts, so a run's log says exactly which card fields got
    # populated rather than just "N rows matched".
    filled_counts = {}

    for county in counties:
        if total_attempted >= BATCH_LIMIT:
            break
        rows = fetch_county_batch(county, min(PER_COUNTY_LIMIT, BATCH_LIMIT - total_attempted))
        if not rows:
            continue
        county_matched = 0
        miss_streak = 0
        for row in rows:
            if miss_streak >= COUNTY_MISS_STREAK:
                # Give up on this county for THIS run only - see the
                # COUNTY_MISS_STREAK note above. Retried in full next run.
                print(f"  [{county}] {miss_streak} consecutive misses - skipping the rest of this county's slice this run.")
                break
            total_attempted += 1
            parcel = row.get("parcel")
            if not parcel:
                continue
            if COUNTY_ALIASES.get(county, county) not in COUNTY_CODES:
                total_unmapped_county += 1
                time.sleep(REQUEST_DELAY_SECONDS)
                continue
            try:
                attrs, centroid, matched_candidate = lookup_fdor(county, parcel)
            except requests.RequestException as e:
                print(f"  [{county}] ERROR looking up parcel {parcel!r}: {e}", file=sys.stderr)
                time.sleep(REQUEST_DELAY_SECONDS)
                continue

            if attrs is None:
                # Left unmarked on purpose - retried on a later run, so a
                # county whose format gets cracked later picks up its backlog.
                miss_streak += 1
                time.sleep(REQUEST_DELAY_SECONDS)
                continue

            total_matched += 1
            county_matched += 1
            miss_streak = 0  # a hit proves the format works; keep going

            fields = build_update_fields(row, attrs, centroid)
            # Stamped only on a successful match, and in the same PATCH as the
            # data, so a row is never marked enriched unless its values landed.
            fields["fdor_enriched_at"] = datetime.now(timezone.utc).isoformat()

            try:
                patch_property(row["id"], fields)
                for column in fields:
                    if column != "fdor_enriched_at":
                        filled_counts[column] = filled_counts.get(column, 0) + 1
            except requests.RequestException as e:
                print(f"  [{county}] ERROR saving parcel {parcel!r} (matched via {matched_candidate!r}): {e}", file=sys.stderr)

            time.sleep(REQUEST_DELAY_SECONDS)

        if rows:
            per_county_matches[county] = (county_matched, len(rows))

    print(
        f"Done. Attempted {total_attempted}, FDOR matches {total_matched}, "
        f"unmapped-county rows skipped {total_unmapped_county}."
    )
    print("Fields populated this run (column: rows filled):")
    for column, count in sorted(filled_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"  {column}: {count}")
    print("Per-county match rate this run (matched/attempted) - a persistent 0 for a county across runs is the signal its parcel-number format needs a new normalize_candidates() rule:")
    for county, (matched, attempted) in sorted(per_county_matches.items()):
        print(f"  {county}: {matched}/{attempted}")
    # Non-fatal by design, same reasoning as geocode_properties.py: this is
    # additive enrichment, not a correctness gate on the harvest itself.


if __name__ == "__main__":
    main()
