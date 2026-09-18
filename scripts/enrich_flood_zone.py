#!/usr/bin/env python3
"""Backfill FEMA flood-hazard facts onto `properties` from the National Flood
Hazard Layer, using coordinates this project already has.

Why this one first, out of everything the Risk & Legal panel wants: it is the
only risk field available from a single, free, national, public API that needs
nothing we do not already store. Liens, judgments and code violations each
require per-county clerk or municipal integrations. Flood needs a latitude and
a longitude, and 1,889 Florida rows and 462 Texas rows already have both.

Source: hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer, layer 28
("Flood Hazard Zones"). Confirmed live 2026-09-17 against a real Alachua
parcel at 29.660087, -82.301424, which returned FLD_ZONE "X", ZONE_SUBTY
"AREA OF MINIMAL FLOOD HAZARD", SFHA_TF "F", DFIRM_ID "12001C".

=============================================================================
THE DISTINCTION THIS SCRIPT IS BUILT AROUND
=============================================================================
A point query against FEMA has THREE outcomes, and collapsing them is the way
this feature goes wrong:

    features returned   -> that is the flood zone
    zero features       -> FEMA HAS NO MAP covering this point
    request failed      -> we know nothing

"FEMA does not map this parcel" is not "FEMA mapped it and found minimal
hazard." Writing NULL for both would let the UI show an unmapped rural parcel
as low risk, which is exactly the confident-wrong-answer failure this project
has guarded against since the harvester lessons. So a zero-feature response
writes the explicit sentinel UNMAPPED, and leaves `flood_sfha` NULL because
the Special Flood Hazard Area question genuinely has no answer there.

A failed request writes nothing at all and leaves `flood_checked_at` NULL, so
the row is retried on a later run rather than being permanently stamped with
a check that never happened.

Incremental by design, same as the FDOR enricher: a row is stamped on a
successful lookup and never re-fetched. Per-county quotas and a randomized
county order keep one large county from starving the rest - the anti-
starvation lesson the geocoding backfill learned the hard way.
"""
from __future__ import annotations

import os
import random
import sys
import time
from collections import Counter

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

BATCH_LIMIT = int(os.environ.get("FLOOD_BATCH_LIMIT", "500"))
PER_COUNTY_LIMIT = int(os.environ.get("FLOOD_PER_COUNTY_LIMIT", "40"))
COUNTY_MISS_STREAK = int(os.environ.get("FLOOD_COUNTY_MISS_STREAK", "10"))
REQUEST_DELAY_SECONDS = float(os.environ.get("FLOOD_REQUEST_DELAY_SECONDS", "0.25"))
REQUEST_TIMEOUT = int(os.environ.get("FLOOD_REQUEST_TIMEOUT", "20"))

NFHL_ENDPOINT = (
    "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
)

# FEMA's own no-data sentinel for base flood elevation. A real BFE of -9999
# feet does not exist; storing it would put a nonsense number on a bid screen.
BFE_NO_DATA = -9999.0

UNMAPPED = "UNMAPPED"

OPTIONAL_COLUMNS = (
    "flood_zone",
    "flood_checked_at",
    "flood_zone_subtype",
    "flood_sfha",
    "flood_bfe",
    "flood_firm_id",
)

if not SUPABASE_URL or not SERVICE_KEY:
    print(
        "SUPABASE_URL / SUPABASE_SERVICE_KEY environment variables are not set "
        "- check the workflow's secrets.",
        file=sys.stderr,
    )
    sys.exit(1)

HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
}

_available_optional_columns = None


def _column_exists(column: str) -> bool:
    """`limit=0` projects the column and returns no rows: one round trip, no
    data transferred. 200 means the column is real."""
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/properties",
            headers=HEADERS,
            params={"select": column, "limit": "0"},
            timeout=15,
        )
    except requests.RequestException:
        return False
    return resp.status_code == 200


def available_optional_columns() -> frozenset:
    """Memoised. Same reasoning as the FDOR enricher's probe: PostgREST
    rejects an entire PATCH over one unknown key, so a writer deployed ahead
    of migration 010 would not degrade - it would silently write nothing on
    every row. Probing once per run makes the deploy order not matter."""
    global _available_optional_columns
    if _available_optional_columns is not None:
        return _available_optional_columns

    if _column_exists(",".join(OPTIONAL_COLUMNS)):
        _available_optional_columns = frozenset(OPTIONAL_COLUMNS)
    else:
        _available_optional_columns = frozenset(
            c for c in OPTIONAL_COLUMNS if _column_exists(c)
        )
    return _available_optional_columns


def schema_is_ready() -> bool:
    """`flood_zone` and `flood_checked_at` are the irreducible pair - a zone
    without its timestamp cannot be written honestly, and the database's own
    CHECK would reject it anyway."""
    have = available_optional_columns()
    return "flood_zone" in have and "flood_checked_at" in have


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def sfha_to_bool(raw):
    """FEMA's SFHA_TF is the string 'T' or 'F'. Anything else - blank, None, an
    unexpected code - becomes None rather than a guess, because False here is
    a positive claim that the parcel is NOT in a Special Flood Hazard Area."""
    text = _text(raw)
    if text is None:
        return None
    upper = text.upper()
    if upper in {"T", "TRUE", "Y", "YES"}:
        return True
    if upper in {"F", "FALSE", "N", "NO"}:
        return False
    return None


def bfe_value(raw):
    """-9999 is FEMA's no-data sentinel, not an elevation."""
    value = _num(raw)
    if value is None or value <= BFE_NO_DATA:
        return None
    return value


def lookup_flood_zone(latitude, longitude):
    """Return (attrs_or_None, ok).

    ok=False means the request itself failed and nothing should be written.
    attrs=None with ok=True means FEMA returned no polygon: the point is
    genuinely unmapped, which is a real finding and gets recorded as one.
    """
    params = {
        "geometry": f"{longitude},{latitude}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF,DFIRM_ID,STATIC_BFE",
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        resp = requests.get(NFHL_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None, False

    # ArcGIS reports failures in a 200 body. An error envelope is a failed
    # request, not an unmapped point - treating it as "unmapped" would stamp
    # a finding onto a row we learned nothing about.
    if isinstance(data, dict) and data.get("error"):
        return None, False

    features = data.get("features") or []
    if not features:
        return None, True
    return features[0].get("attributes") or {}, True


def build_update_fields(attrs, *, checked_at):
    """Map one FEMA response onto `properties` columns.

    `attrs=None` is the unmapped case and is deliberately recorded, not
    skipped: knowing FEMA does not map a parcel is itself worth storing, and
    it stops the row being retried forever.
    """
    fields = {"flood_checked_at": checked_at}

    if attrs is None:
        # Unmapped. No zone letter, and critically no SFHA answer - FEMA made
        # no determination here, so claiming one either way would be fiction.
        fields["flood_zone"] = UNMAPPED
        return fields

    zone = _text(attrs.get("FLD_ZONE"))
    # A mapped polygon with no zone string is malformed rather than unmapped;
    # treat it the same as unmapped rather than inventing a zone.
    fields["flood_zone"] = zone or UNMAPPED

    subtype = _text(attrs.get("ZONE_SUBTY"))
    if subtype:
        fields["flood_zone_subtype"] = subtype

    if fields["flood_zone"] != UNMAPPED:
        sfha = sfha_to_bool(attrs.get("SFHA_TF"))
        if sfha is not None:
            fields["flood_sfha"] = sfha

    bfe = bfe_value(attrs.get("STATIC_BFE"))
    if bfe is not None:
        fields["flood_bfe"] = bfe

    firm = _text(attrs.get("DFIRM_ID"))
    if firm:
        fields["flood_firm_id"] = firm

    return fields


def drop_unavailable_columns(fields):
    available = available_optional_columns()
    return {k: v for k, v in fields.items() if k not in OPTIONAL_COLUMNS or k in available}


def fetch_counties_needing_flood():
    """Counties with rows that have coordinates and no flood check yet.

    Randomized order, and each county gets its own capped slice per run, so a
    single large county can never consume the whole budget - the same
    anti-starvation shape the FDOR enricher and the geocoder both use.
    """
    params = {
        "select": "county",
        "flood_checked_at": "is.null",
        "latitude": "not.is.null",
        "longitude": "not.is.null",
        "limit": "10000",
    }
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/properties", headers=HEADERS, params=params, timeout=30
    )
    resp.raise_for_status()
    outstanding = Counter(r["county"] for r in resp.json() if r.get("county"))
    counties = sorted(outstanding)
    random.shuffle(counties)
    return [(c, outstanding[c]) for c in counties]


def fetch_county_batch(county, limit, outstanding=None):
    """A random window into the county's backlog, for the reason Phase 51
    established: without `order` PostgREST returns the same rows every run,
    and because a miss is never stamped, the same rows would lead the slice
    forever and the county would never advance past them."""
    offset = 0
    if outstanding and outstanding > limit:
        offset = random.randrange(0, outstanding - limit + 1)
    params = {
        "select": "id,county,state,latitude,longitude",
        "county": f"eq.{county}",
        "flood_checked_at": "is.null",
        "latitude": "not.is.null",
        "longitude": "not.is.null",
        "order": "id.asc",
        "offset": str(offset),
        "limit": str(limit),
    }
    resp = requests.get(
        f"{SUPABASE_URL}/rest/v1/properties", headers=HEADERS, params=params, timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def patch_property(property_id, fields):
    fields = drop_unavailable_columns(fields)
    if not fields:
        return
    url = f"{SUPABASE_URL}/rest/v1/properties?id=eq.{property_id}"
    patch_headers = dict(HEADERS)
    patch_headers["Prefer"] = "return=minimal"
    resp = requests.patch(url, headers=patch_headers, json=fields, timeout=15)
    resp.raise_for_status()


def main():
    if not schema_is_ready():
        print(
            "flood_zone / flood_checked_at are not in this database yet - apply "
            "scripts/migrations/010_flood_hazard.sql first. Nothing written.",
            file=sys.stderr,
        )
        return 0

    counties = fetch_counties_needing_flood()
    print(f"{len(counties)} counties have rows with coordinates and no flood check.")
    if not counties:
        print("Nothing to check.")
        return 0

    attempted = 0
    mapped = 0
    unmapped = 0
    failed = 0
    zones = Counter()

    for county, outstanding in counties:
        if attempted >= BATCH_LIMIT:
            break
        rows = fetch_county_batch(
            county, min(PER_COUNTY_LIMIT, BATCH_LIMIT - attempted), outstanding
        )
        if not rows:
            continue

        miss_streak = 0
        for row in rows:
            if miss_streak >= COUNTY_MISS_STREAK:
                print(
                    f"  [{county}] {miss_streak} consecutive request failures - "
                    "skipping the rest of this county's slice this run."
                )
                break
            attempted += 1
            attrs, ok = lookup_flood_zone(row["latitude"], row["longitude"])
            time.sleep(REQUEST_DELAY_SECONDS)

            if not ok:
                # Nothing written, nothing stamped: retried next run.
                failed += 1
                miss_streak += 1
                continue

            miss_streak = 0
            checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            fields = build_update_fields(attrs, checked_at=checked_at)
            try:
                patch_property(row["id"], fields)
            except requests.RequestException as exc:
                print(f"  [{county}] write failed for {row['id']}: {exc}", file=sys.stderr)
                failed += 1
                continue

            if fields.get("flood_zone") == UNMAPPED:
                unmapped += 1
            else:
                mapped += 1
                zones[fields["flood_zone"]] += 1

    print(
        f"\nAttempted {attempted}. Mapped {mapped}, unmapped {unmapped}, "
        f"failed {failed} (left unstamped for retry)."
    )
    if zones:
        print("Zones written: " + ", ".join(f"{z}={n}" for z, n in zones.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
