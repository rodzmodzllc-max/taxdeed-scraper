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
  * It is dated, and honestly so: `photo_captured_year` records the year
    the imagery was flown (the catalog's `acquisition_date`, see
    NAIP_CATALOG_QUERY_ENDPOINT), because a 2023 image of a lot that burned
    in 2025 must not be presented as current. `--backfill-capture-year`
    (or NAIP_YEAR_BACKFILL_LIMIT) fills it on images stored before it was
    recorded, only where the stored image is provably today's export.

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

import json
import os
import re
import sys
import time
from collections import Counter

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import enrichment_units as EU  # noqa: E402 - (state, county) units
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from harvesters import imagery as IMG  # noqa: E402 - coverage priority
import image_storage as IS  # noqa: E402 - optimize + content-addressed paths

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

BATCH_LIMIT = int(os.environ.get("NAIP_BATCH_LIMIT", "300"))
PER_COUNTY_LIMIT = int(os.environ.get("NAIP_PER_COUNTY_LIMIT", "30"))
COUNTY_MISS_STREAK = int(os.environ.get("NAIP_COUNTY_MISS_STREAK", "10"))
REQUEST_DELAY_SECONDS = float(os.environ.get("NAIP_REQUEST_DELAY_SECONDS", "0.35"))
REQUEST_TIMEOUT = int(os.environ.get("NAIP_REQUEST_TIMEOUT", "30"))
# 2026-10-29 (audit B28): the deeds job's 12-minute step timeout killed this
# step on every run with no output at all. A time budget (0 = none) stops it
# cleanly first, so the summary is printed and the report written.
TIME_BUDGET_SECONDS = float(os.environ.get("NAIP_TIME_BUDGET_SECONDS", "0") or 0)

NAIP_ENDPOINT = (
    "https://imagery.nationalmap.gov/arcgis/rest/services/"
    "USGSNAIPImagery/ImageServer/exportImage"
)
# The same ImageServer's catalog (2026-11-14). Read from the service's own
# metadata (`ImageServer?f=pjson`): the mosaic catalog carries, per raster
# item, `acquisition_date` (esriFieldTypeDate, epoch milliseconds UTC - the
# day the tile was flown, matching the date suffix of the item's `Name`, e.g.
# m_2908222_se_17_030_20230126 -> 1674691200000 = 2023-01-26) and `Year`
# (the NAIP program year, e.g. 2022 for that same Florida tile flown in
# January 2023). `photo_captured_year` is the CAPTURE year, so it comes from
# `acquisition_date`, never from `Year`. Only `Category = 1` (primary)
# items carry it; overviews have NULL dates.
NAIP_CATALOG_QUERY_ENDPOINT = (
    "https://imagery.nationalmap.gov/arcgis/rest/services/"
    "USGSNAIPImagery/ImageServer/query"
)
# Year backfill for stored usda_naip images whose photo_captured_year is NULL
# (0 = off). Runs BEFORE the new-image pass, inside the same time budget, so
# a run that spends its whole budget on new images still backfills a slice.
YEAR_BACKFILL_LIMIT = int(os.environ.get("NAIP_YEAR_BACKFILL_LIMIT", "0") or 0)

# Roughly a 150m box around the parcel centroid - wide enough to show the
# whole lot and its frontage, tight enough that the parcel is the subject
# rather than a dot in a neighbourhood. Degrees, so it is latitude-dependent;
# at Florida/Texas latitudes this is close enough for a thumbnail and does
# not warrant a projection round-trip.
BOX_DEGREES = float(os.environ.get("NAIP_BOX_DEGREES", "0.0012"))
IMAGE_SIZE = os.environ.get("NAIP_IMAGE_SIZE", "600,450")

STORAGE_BUCKET = os.environ.get("NAIP_STORAGE_BUCKET", "property-photos")
# Storage budget (MB) for the bucket as a whole. The project is on a plan
# with a fixed storage quota; an upload past it fails for every pipeline
# that stores into this bucket. The run totals the bucket first and stops
# uploading once the total reaches the budget - rows stay unchecked (NULL)
# and are retried when space exists. A failed total is treated as "over
# budget": nothing is uploaded on a guess.
STORAGE_BUDGET_MB = float(os.environ.get("NAIP_STORAGE_BUDGET_MB", "950"))

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


def capture_year_from_catalog(payload, *, max_year: int | None = None):
    """The capture year of the imagery in a catalog query answer, or None.

    `payload` is the parsed JSON of NAIP_CATALOG_QUERY_ENDPOINT for the
    image's own box, `where=Category = 1`. A year is returned only when every
    primary item the box touches has an `acquisition_date` and they all fall
    in ONE calendar year (UTC). No item, a missing date, items from different
    years, a truncated answer or an implausible year -> None: the image is
    then stored without a year rather than with a guessed one.
    """
    from datetime import datetime, timezone  # noqa: PLC0415
    if not isinstance(payload, dict) or payload.get("exceededTransferLimit"):
        return None
    feats = payload.get("features")
    if not isinstance(feats, list) or not feats:
        return None
    years = set()
    for f in feats:
        a = (f or {}).get("attributes") or {}
        if a.get("Category") not in (None, 1):
            continue
        ms = a.get("acquisition_date")
        if not isinstance(ms, (int, float)) or isinstance(ms, bool):
            return None
        try:
            years.add(datetime.fromtimestamp(ms / 1000.0, timezone.utc).year)
        except (OverflowError, OSError, ValueError):
            return None
    if len(years) != 1:
        return None
    year = years.pop()
    top = max_year if max_year is not None else datetime.now(timezone.utc).year + 1
    # migration 011's properties_photo_year_sane: 1990 .. next year.
    return year if 1990 <= year <= top else None


def fetch_capture_year(latitude, longitude):
    """(year_or_None, ok) for the image exported at these coordinates.

    Asks the ImageServer catalog which primary items intersect the exact box
    the image was exported for. ok=False = the request failed (HTTP error,
    ArcGIS error body, unparseable answer): nothing is learned.
    """
    params = {
        "geometry": bbox_for(latitude, longitude),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "where": "Category = 1",
        "outFields": "OBJECTID,Name,Category,Year,acquisition_date",
        "returnGeometry": "false",
        "f": "json",
    }
    try:
        resp = requests.get(NAIP_CATALOG_QUERY_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return None, False
    if not isinstance(payload, dict) or "error" in payload or not isinstance(payload.get("features"), list):
        return None, False
    return capture_year_from_catalog(payload), True


def public_url(path: str) -> str:
    return f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/{path}"


def object_exists(path: str) -> bool:
    """True only when the object is confirmed present (a failed check is
    'not known to exist', so the caller uploads rather than pointing a row at
    a missing object)."""
    try:
        resp = requests.head(public_url(path), timeout=REQUEST_TIMEOUT)
    except requests.RequestException:
        return False
    return resp.status_code == 200


def put_object(path: str, data: bytes, content_type: str) -> bool:
    url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}/{path}"
    headers = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": content_type,
        "cache-control": "31536000",
        # Content-addressed: the same path always holds the same bytes, so an
        # existing object is never overwritten.
        "x-upsert": "false",
    }
    try:
        resp = requests.post(url, headers=headers, data=data, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        print(f"  upload failed for {path}: {exc}", file=sys.stderr)
        return False
    if resp.status_code in (200, 201):
        return True
    # 409 / "Duplicate": the object appeared between the existence check and
    # the upload - same path means same content, so it is usable.
    if resp.status_code in (400, 409) and "uplicate" in (resp.text or ""):
        return True
    print(f"  upload failed for {path}: HTTP {resp.status_code}", file=sys.stderr)
    return False


def prepare_image(png: bytes):
    """(optimized, path): same-size WebP when strictly smaller and decodable,
    else the source bytes - at a content-addressed path either way."""
    opt = IS.optimize_image(png)
    path = IS.optimized_path(opt.source_sha256) if opt.optimized else f"{IS.OPTIMIZED_PREFIX}{opt.source_sha256}.{opt.extension}"
    return opt, path


def storage_used_bytes(prefix: str = "", depth: int = 0) -> int | None:
    """Total size of every object in the bucket (Storage list API, recursive
    over folders). None when the total cannot be established."""
    url = f"{SUPABASE_URL}/storage/v1/object/list/{STORAGE_BUCKET}"
    headers = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}", "Content-Type": "application/json"}
    total, offset = 0, 0
    while True:
        try:
            resp = requests.post(url, headers=headers, timeout=REQUEST_TIMEOUT,
                                 json={"prefix": prefix, "limit": 1000, "offset": offset, "sortBy": {"column": "name", "order": "asc"}})
            resp.raise_for_status()
            items = resp.json()
        except (requests.RequestException, ValueError):
            return None
        if not isinstance(items, list):
            return None
        for it in items:
            if it.get("id") is None:          # a folder
                if depth >= 3:
                    return None
                sub = storage_used_bytes(f"{prefix}{it.get('name')}/", depth + 1)
                if sub is None:
                    return None
                total += sub
            else:
                total += int((it.get("metadata") or {}).get("size") or 0)
        if len(items) < 1000:
            return total
        offset += 1000


def build_update_fields(photo_url, *, checked_at, captured_year=None):
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
        # The capture year comes from the same service (photo_source records
        # whose it is); written only when the catalog established it.
        if captured_year is not None:
            fields["photo_captured_year"] = int(captured_year)
    return fields


# --- capture-year backfill for images already stored ------------------------
#
# A stored row's year cannot simply be read from today's catalog: NAIP
# replaces an area's imagery when a newer flight is published, and the row's
# image may predate that. The year is written only when the image the service
# returns TODAY for the row's own box is byte-identical to the stored one -
# established from the content address in the stored path
# (naip/v2/<sha256 of the source bytes>.<ext>, image_storage) or, for an
# object stored untouched at an older path, from the stored bytes themselves.
# The export is deterministic (the same box returns the same bytes - checked
# 2026-11-14, three identical exports). Anything else is left NULL.

_V2_SHA = re.compile(r"(?:^|/)" + re.escape(IS.OPTIMIZED_PREFIX) + r"([0-9a-f]{64})\.[a-z0-9]+$")


def stored_source_sha(photo_url):
    """The source-image sha256 a content-addressed stored path names, or None."""
    path = IS.object_path_of(photo_url, STORAGE_BUCKET) or ""
    m = _V2_SHA.search(path)
    return m.group(1) if m else None


def fetch_stored_object(photo_url):
    """The stored object's bytes, or None (any failure)."""
    try:
        resp = requests.get(photo_url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException:
        return None
    return resp.content if resp.status_code == 200 and resp.content else None


def stored_image_matches_today(row, today_png: bytes):
    """True only when the stored image is provably today's export."""
    today = IS.sha256(today_png)
    named = stored_source_sha(row.get("photo_url"))
    if named is not None:
        return named == today
    stored = fetch_stored_object(row.get("photo_url"))
    return stored is not None and IS.sha256(stored) == today


def fetch_year_backfill_rows(limit):
    params = {
        "select": "id,latitude,longitude,photo_url",
        "photo_source": "eq.usda_naip",
        "photo_captured_year": "is.null",
        "photo_url": "not.is.null",
        "latitude": "not.is.null",
        "longitude": "not.is.null",
    }
    params.update(EU.state_param(EU.state_filter()))
    # A random window (keyset from a random id, wrapping), pages of <= 1000:
    # rows whose year cannot be established stay NULL and must not hold the
    # front of the queue on every run.
    return EU.get_window(_get_json, f"{SUPABASE_URL}/rest/v1/properties", params, limit)


def patch_capture_year(property_id, year):
    """One PATCH, one column, only while the column is still NULL."""
    url = f"{SUPABASE_URL}/rest/v1/properties"
    patch_headers = dict(HEADERS)
    patch_headers["Prefer"] = "return=minimal"
    resp = requests.patch(url, headers=patch_headers, timeout=20,
                          params={"id": f"eq.{property_id}", "photo_captured_year": "is.null"},
                          json={"photo_captured_year": int(year)})
    resp.raise_for_status()


def backfill_capture_years(limit, deadline=None):
    """Fill photo_captured_year on up to `limit` stored usda_naip rows."""
    out = {"limit": limit, "examined": 0, "written": 0, "image_changed": 0, "no_year": 0, "failed": 0,
           "time_budget_reached": False}
    if limit <= 0:
        return out
    if "photo_captured_year" not in available_optional_columns():
        out["skipped"] = "photo_captured_year column not available"
        return out
    try:
        rows = fetch_year_backfill_rows(limit)
    except (requests.RequestException, ValueError) as exc:
        print(f"Year backfill: could not read rows ({exc.__class__.__name__}) - skipped this run.", file=sys.stderr)
        out["failed"] += 1
        return out
    for row in rows[:limit]:
        if deadline is not None and time.monotonic() >= deadline:
            out["time_budget_reached"] = True
            break
        if not IMG.has_coordinates(row) or not row.get("photo_url"):
            continue
        out["examined"] += 1
        png, ok = fetch_naip_image(row["latitude"], row["longitude"])
        time.sleep(REQUEST_DELAY_SECONDS)
        if not ok or png is None:
            out["failed"] += 1
            continue
        if not stored_image_matches_today(row, png):
            out["image_changed"] += 1
            continue
        year, ok = fetch_capture_year(row["latitude"], row["longitude"])
        time.sleep(REQUEST_DELAY_SECONDS)
        if not ok:
            out["failed"] += 1
            continue
        if year is None:
            out["no_year"] += 1
            continue
        try:
            patch_capture_year(row["id"], year)
        except requests.RequestException:
            out["failed"] += 1
            continue
        out["written"] += 1
    print(f"Year backfill: examined {out['examined']}, written {out['written']}, image changed since stored "
          f"{out['image_changed']}, no single capture year {out['no_year']}, failed {out['failed']}.")
    return out


# Imagery priority (Customer-value sprint, 2026-10-01). Storage is the binding
# constraint, so imagery is spent where it serves customers most, in this
# order, and NEVER on liens & certificates (a lien instrument is not a parcel
# a customer acquires; certificate rows get no new property imagery - their
# existing images are left in place, not deleted):
#   1. available        - AVAILABLE / OTC / LAFT (source = laft), active
#   2. auction_active   - active / upcoming auctions
#   3. auction_closed   - closed / dropped-off auctions
# A tier is only reached once every higher tier has no outstanding row this run
# (or the per-run budget is spent). Deferred rows stay NULL ("not checked") -
# never marked complete.
GONE_STATUSES = ("closed", "expired", "gone", "sold", "redeemed", "cancelled", "canceled")
_GONE = "(" + ",".join(GONE_STATUSES) + ")"
IMAGERY_TIERS = (
    ("available", {"source": "eq.laft", "status": f"not.in.{_GONE}"}),
    ("auction_active", {"source": "eq.auction", "status": f"not.in.{_GONE}"}),
    ("auction_closed", {"source": "eq.auction", "status": f"in.{_GONE}"}),
)
EXCLUDED_SOURCES = ("certificate",)
# Storage-optimization sprint (2026-10-01): closed / dropped auctions get no
# NEW imagery either - no product requirement needs a fresh aerial of a sale
# that is over. Their outstanding rows are counted and reported as deferred
# by policy; their existing images are kept. Certificates are not even
# counted against storage: no request is made for them.
COLLECTED_TIERS = ("available", "auction_active")


def tier_params(tier_filter: dict) -> dict:
    params = {"photo_url": "is.null", "latitude": "not.is.null", "longitude": "not.is.null"}
    params.update(tier_filter)
    assert params.get("source") not in tuple(f"eq.{x}" for x in EXCLUDED_SOURCES)
    return params


def fetch_counties_needing_photos(tier_filter: dict | None = None):
    params = {"select": "state,county", "limit": "10000"}
    params.update(tier_params(tier_filter if tier_filter is not None else IMAGERY_TIERS[0][1]))
    params.update(EU.state_param(EU.state_filter()))
    return EU.outstanding_units(EU.get_paged(_get_json, f"{SUPABASE_URL}/rest/v1/properties", params, 100000))


def fetch_county_batch(unit, limit, outstanding=None, tier_filter: dict | None = None):
    # A random window into the backlog (keyset from a random id, wrapping) -
    # never a deep offset, which timed out on Detroit's 30,549 rows (2026-10-26).
    params = {"select": "id,county,state,latitude,longitude"}
    params.update(tier_params(tier_filter if tier_filter is not None else IMAGERY_TIERS[0][1]))
    params.update(EU.unit_params(unit))
    if outstanding and outstanding > limit:
        return EU.get_window(_get_json, f"{SUPABASE_URL}/rest/v1/properties", params, limit)
    return EU.get_paged(_get_json, f"{SUPABASE_URL}/rest/v1/properties", params, limit)


def write_priority_report(report: dict) -> None:
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out", "public", "imagery-priority.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)


def _get_json(url, params):
    resp = requests.get(url, headers=HEADERS, params=params, timeout=60)
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


def parse_args(argv):
    import argparse  # noqa: PLC0415
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backfill-capture-year", action="store_true",
                    help="only fill photo_captured_year on stored usda_naip rows (no new images)")
    ap.add_argument("--limit", type=int, default=None,
                    help="rows for --backfill-capture-year (default NAIP_YEAR_BACKFILL_LIMIT, else 300)")
    return ap.parse_args(argv)


def main(argv=None):
    args = parse_args([] if argv is None else argv)
    # Source permission (2026-10-12): recorded fetch/store permission for
    # usda_naip (data/source_permissions.csv), checked before any request.
    import permission_gate as _PG  # noqa: PLC0415
    if not _PG.allowed("usda_naip", ('fetch', 'store'), state="US", label="enrich_property_photos_naip"):
        sys.exit(_PG.DENIED_EXIT)
    deadline = time.monotonic() + TIME_BUDGET_SECONDS if TIME_BUDGET_SECONDS > 0 else None
    if args.backfill_capture_year:
        limit = args.limit if args.limit is not None else (YEAR_BACKFILL_LIMIT or 300)
        backfill_capture_years(limit, deadline)
        return 0
    year_backfill = backfill_capture_years(YEAR_BACKFILL_LIMIT, deadline) if YEAR_BACKFILL_LIMIT > 0 else None
    used = storage_used_bytes()
    budget = int(STORAGE_BUDGET_MB * 1024 * 1024)
    report = {"budget_mb": STORAGE_BUDGET_MB, "used_mb": None if used is None else round(used / 1048576, 1),
              "excluded_ledgers": list(EXCLUDED_SOURCES), "tiers": {}, "uploads_allowed": False}
    report.update({"collected_tiers": list(COLLECTED_TIERS), "compressed": 0, "deduplicated": 0, "bytes_saved": 0, "bytes_stored": 0,
                   "captured_year_written": 0})
    if year_backfill is not None:
        report["capture_year_backfill"] = year_backfill
    tiers = []
    for name, flt in IMAGERY_TIERS:
        units = fetch_counties_needing_photos(flt)
        if name == "available":
            # Coverage priority (harvesters/imagery.imagery_priority): counties
            # holding customer-visible Available rows are worked first. An
            # operational order only - never a judgement about a property.
            units = IMG.order_units(units, fetch_counties_needing_photos({**flt, **IMG.CUSTOMER_FILTER}))
        tiers.append((name, flt, units))
        report["tiers"][name] = {"outstanding": sum(n for _, n in units), "attempted": 0, "stored": 0, "no_coverage": 0, "failed": 0,
                                 "collected": name in COLLECTED_TIERS}
    if used is None:
        print("Storage usage could not be established - no image uploaded this run (budget guard fails closed).")
        _finish(report)
        return 0
    print(f"Bucket {STORAGE_BUCKET}: {used / 1048576:.0f} MB used of a {STORAGE_BUDGET_MB:.0f} MB budget.")
    if used >= budget:
        print("Storage budget reached - no image uploaded; rows stay unchecked and are retried when space exists.")
        _finish(report)
        return 0
    report["uploads_allowed"] = True
    attempted = 0
    stop = False
    report["time_budget_reached"] = False
    for name, flt, counties in tiers:
        t = report["tiers"][name]
        if name not in COLLECTED_TIERS:
            print(f"Tier {name}: {t['outstanding']} row(s) outstanding - deferred by policy (no new imagery collected).")
            continue
        if stop or attempted >= BATCH_LIMIT:
            break
        print(f"Tier {name}: {len(counties)} unit(s), {t['outstanding']} row(s) with coordinates and no image.")
        for unit, outstanding in counties:
            county = EU.label(unit)
            if attempted >= BATCH_LIMIT or stop:
                break
            rows = fetch_county_batch(unit, min(PER_COUNTY_LIMIT, BATCH_LIMIT - attempted), outstanding, flt)
            miss_streak = 0
            for row in rows:
                if deadline is not None and time.monotonic() >= deadline:
                    print(f"Time budget of {TIME_BUDGET_SECONDS:.0f} s reached - stopped cleanly; remaining rows stay unchecked.")
                    report["time_budget_reached"] = True
                    stop = True
                    break
                if miss_streak >= COUNTY_MISS_STREAK:
                    print(f"  [{county}] {miss_streak} consecutive failures - skipping the rest of this county's slice this run.")
                    break
                attempted += 1
                t["attempted"] += 1
                png, ok = fetch_naip_image(row["latitude"], row["longitude"])
                time.sleep(REQUEST_DELAY_SECONDS)
                if not ok:
                    t["failed"] += 1
                    miss_streak += 1
                    continue
                miss_streak = 0
                checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                if png is None:
                    patch_property(row["id"], build_update_fields("", checked_at=checked_at))
                    t["no_coverage"] += 1
                    continue
                # Optimized + content-addressed (image_storage): the budget is
                # checked against the bytes that would actually be added, and
                # an identical image already stored costs nothing.
                opt, path = prepare_image(png)
                exists = object_exists(path)
                need = 0 if exists else len(opt.data)
                if used + need > budget:
                    print("Storage budget reached mid-run - stopping uploads; remaining rows stay unchecked.")
                    stop = True
                    break
                if exists:
                    report["deduplicated"] += 1
                    report["bytes_saved"] += opt.source_bytes
                    stored_url = public_url(path)
                elif put_object(path, opt.data, opt.content_type):
                    stored_url = public_url(path)
                    report["bytes_stored"] += len(opt.data)
                    if opt.optimized:
                        report["compressed"] += 1
                        report["bytes_saved"] += opt.saved_bytes
                else:
                    stored_url = None
                if stored_url is None:
                    # The image exists but could not be stored: nothing is
                    # stamped, so the row is retried - never marked complete.
                    t["failed"] += 1
                    continue
                # The capture year of the image just exported, from the same
                # service's catalog for the same box. A failed or ambiguous
                # lookup stores the image without a year (backfilled later).
                year, _ok = fetch_capture_year(row["latitude"], row["longitude"])
                time.sleep(REQUEST_DELAY_SECONDS)
                if year is not None:
                    report["captured_year_written"] += 1
                patch_property(row["id"], build_update_fields(stored_url, checked_at=checked_at, captured_year=year))
                t["stored"] += 1
                used += need
    report["used_mb"] = round(used / 1048576, 1)
    _finish(report)
    return 0


def _finish(report: dict) -> None:
    for t in report["tiers"].values():
        t["deferred"] = max(0, t["outstanding"] - t["stored"] - t["no_coverage"])
    write_priority_report(report)
    print("Imagery priority (available > active auctions; closed auctions deferred by policy; certificates excluded):")
    print(f"  storage: compressed {report.get('compressed', 0)}, deduplicated {report.get('deduplicated', 0)}, "
          f"bytes stored {report.get('bytes_stored', 0)}, estimated bytes saved {report.get('bytes_saved', 0)}, "
          f"capture year recorded on {report.get('captured_year_written', 0)} new image(s)")
    for name, t in report["tiers"].items():
        print(f"  {name}: outstanding {t['outstanding']}, attempted {t['attempted']}, stored {t['stored']}, "
              f"no coverage {t['no_coverage']}, failed {t['failed']}, deferred {t['deferred']}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
