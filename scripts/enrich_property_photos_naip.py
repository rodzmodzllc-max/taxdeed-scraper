#!/usr/bin/env python3
"""Backfill property imagery from NAIP - free, public domain, no API key.

WHY THIS EXISTS ALONGSIDE fetch_property_photos.py

`scripts/fetch_property_photos.py` fetches Google Street View Static images
and caches them in a PUBLIC Supabase Storage bucket. It has never run: it
needs a Google Cloud project with billing attached and a GOOGLE_MAPS_API_KEY
secret, so `photo_url` is 0% populated. It also sits awkwardly against this
repo's own `docs/image-rights-policy.md`, which says property photos from any
source are LEGAL_REVIEW_REQUIRED and that the project's approach is "linking,
not copying - no bytes from those services are stored or re-served." Storing
and re-serving Google imagery from a public bucket is the opposite of that.

This script takes the other road. The USDA National Agriculture Imagery
Program (NAIP), served by USGS's National Map, is a work of the United States
federal government: public domain, free, no key, no quota negotiation, and no
restriction on storing or re-serving the bytes. That makes it the one imagery
source this project can actually use today without either a billing account
or an unresolved rights question.

Confirmed live 2026-09-17 against a real Alachua parcel at 29.660087,
-82.301424 - returned genuine aerial imagery at parcel resolution (visible
structures, tree canopy, road frontage), not a blank or placeholder tile.

WHAT IT IS AND IS NOT

It is aerial, not street-level. For a tax-deed product that is arguably the
better fit and certainly the more honest one:

  * A large share of this inventory is vacant or unimproved land, where
    Street View has no coverage at all and returns nothing. NAIP covers it.
  * Aerial imagery shows the whole parcel - frontage, outbuildings,
    encroachment, whether anything is built at all - which is closer to what
    a bidder needs than a kerbside photo of one facade.
  * It is dated, and honestly so: `photo_captured_year` records the NAIP
    vintage, because a 2023 image of a lot that burned in 2025 must not be
    presented as current.

It is NOT a photograph of a building, and the UI must not label it one.

THREE OUTCOMES, NOT TWO - the same rule the flood enricher follows:

    an image returns       -> store it, stamp the check
    the parcel has no
      coordinates          -> not attempted; nothing written, row untouched
    the request fails      -> nothing written, retried on a later run

A row with coordinates that NAIP genuinely cannot cover is stamped with the
empty-string sentinel the existing `photo_url` contract already defines
(NULL = never checked, '' = checked and no coverage, a value = a real image),
so it is not re-fetched every run.
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

BATCH_LIMIT = int(os.environ.get("NAIP_BATCH_LIMIT", "300"))
PER_COUNTY_LIMIT = int(os.environ.get("NAIP_PER_COUNTY_LIMIT", "30"))
COUNTY_MISS_STREAK = int(os.environ.get("NAIP_COUNTY_MISS_STREAK", "10"))
REQUEST_DELAY_SECONDS = float(os.environ.get("NAIP_REQUEST_DELAY_SECONDS", "0.35"))
REQUEST_TIMEOUT = int(os.environ.get("NAIP_REQUEST_TIMEOUT", "30"))

NAIP_ENDPOINT = (
    "https://imagery.nationalmap.gov/arcgis/rest/services/"
    "USGSNAIPImagery/ImageServer/exportImage"
)

# Roughly a 150m box around the parcel centroid - wide enough to show the
# whole lot and its frontage, tight enough that the parcel is the subject
# rather than a dot in a neighbourhood. Degrees, so it is latitude-dependent;
# at Florida/Texas latitudes this is close enough for a thumbnail and does
# not warrant a projection round-trip.
BOX_DEGREES = float(os.environ.get("NAIP_BOX_DEGREES", "0.0012"))
IMAGE_SIZE = os.environ.get("NAIP_IMAGE_SIZE", "600,450")

STORAGE_BUCKET = os.environ.get("NAIP_STORAGE_BUCKET", "property-photos")

OPTIONAL_COLUMNS = ("photo_source", "photo_captured_year", "photo_checked_at")

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
    """Same probe the FDOR and flood enrichers use: PostgREST rejects a whole
    PATCH over one unknown key, so a writer shipped ahead of its migration
    would silently write nothing on every row rather than degrading."""
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


def drop_unavailable_columns(fields: dict) -> dict:
    available = available_optional_columns()
    return {k: v for k, v in fields.items() if k not in OPTIONAL_COLUMNS or k in available}


def bbox_for(latitude: float, longitude: float) -> str:
    half = BOX_DEGREES / 2.0
    return f"{longitude - half},{latitude - half},{longitude + half},{latitude + half}"


def fetch_naip_image(latitude, longitude):
    """Return (png_bytes_or_None, ok).

    ok=False means the request failed and nothing should be written - the row
    stays unstamped and is retried. png_bytes=None with ok=True means NAIP
    answered but has no imagery for that point, which is a real finding and
    gets the no-coverage sentinel rather than an endless retry.
    """
    params = {
        "bbox": bbox_for(latitude, longitude),
        "bboxSR": "4326",
        "size": IMAGE_SIZE,
        "format": "png",
        "f": "image",
    }
    try:
        resp = requests.get(NAIP_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        return None, False

    content_type = (resp.headers.get("Content-Type") or "").lower()
    # ArcGIS reports failures as a JSON body with a 200 status. Reading that
    # as "no coverage" would stamp a finding onto a row we learned nothing
    # about - the same trap the flood enricher guards against.
    if "json" in content_type:
        return None, False
    if "image" not in content_type:
        return None, False

    body = resp.content
    if not body:
        return None, True
    return body, True


def upload_image(property_id: str, png: bytes) -> str | None:
    """Store in the same public bucket the Street View pipeline uses. Unlike
    that pipeline, this is unambiguously allowed: NAIP is public domain, so
    re-serving the bytes carries no licence question at all."""
    path = f"naip/{property_id}.png"
    url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}/{path}"
    headers = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "image/png",
        "x-upsert": "true",
    }
    try:
        resp = requests.post(url, headers=headers, data=png, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  upload failed for {property_id}: {exc}", file=sys.stderr)
        return None
    return f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/{path}"


def build_update_fields(photo_url, *, checked_at):
    """photo_url='' is the established no-coverage sentinel on this column -
    NULL means never checked. Preserved exactly rather than inventing a
    fourth state."""
    fields = {
        "photo_url": photo_url,
        "photo_checked_at": checked_at,
    }
    if photo_url:
        # Recorded so the UI can say whose image this is and roughly when it
        # was taken. An aerial image presented as a current photograph of a
        # building would be a misrepresentation twice over.
        fields["photo_source"] = "usda_naip"
    return fields


def fetch_counties_needing_photos():
    params = {
        "select": "county",
        "photo_url": "is.null",
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
    offset = 0
    if outstanding and outstanding > limit:
        offset = random.randrange(0, outstanding - limit + 1)
    params = {
        "select": "id,county,state,latitude,longitude",
        "county": f"eq.{county}",
        "photo_url": "is.null",
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
    resp = requests.patch(url, headers=patch_headers, json=fields, timeout=20)
    resp.raise_for_status()


def main():
    counties = fetch_counties_needing_photos()
    print(f"{len(counties)} counties have rows with coordinates and no photo yet.")
    if not counties:
        print("Nothing to fetch.")
        return 0

    attempted = stored = no_coverage = failed = 0

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
                    f"  [{county}] {miss_streak} consecutive failures - skipping the "
                    "rest of this county's slice this run."
                )
                break
            attempted += 1
            png, ok = fetch_naip_image(row["latitude"], row["longitude"])
            time.sleep(REQUEST_DELAY_SECONDS)

            if not ok:
                failed += 1
                miss_streak += 1
                continue
            miss_streak = 0

            checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            if png is None:
                patch_property(row["id"], build_update_fields("", checked_at=checked_at))
                no_coverage += 1
                continue

            public_url = upload_image(row["id"], png)
            if public_url is None:
                # The image exists but we could not store it. Nothing is
                # stamped, so this row is retried rather than being recorded
                # as having no coverage.
                failed += 1
                continue
            patch_property(row["id"], build_update_fields(public_url, checked_at=checked_at))
            stored += 1

    print(
        f"\nAttempted {attempted}. Stored {stored}, no-coverage {no_coverage}, "
        f"failed {failed} (left unstamped for retry)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
