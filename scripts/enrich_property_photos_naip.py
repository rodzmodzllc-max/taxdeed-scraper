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

import json
import os
import random
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
    offset = 0
    if outstanding and outstanding > limit:
        offset = random.randrange(0, outstanding - limit + 1)
    params = {"select": "id,county,state,latitude,longitude", "order": "id.asc", "offset": str(offset), "limit": str(limit)}
    params.update(tier_params(tier_filter if tier_filter is not None else IMAGERY_TIERS[0][1]))
    params.update(EU.unit_params(unit))
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


def main():
    used = storage_used_bytes()
    budget = int(STORAGE_BUDGET_MB * 1024 * 1024)
    report = {"budget_mb": STORAGE_BUDGET_MB, "used_mb": None if used is None else round(used / 1048576, 1),
              "excluded_ledgers": list(EXCLUDED_SOURCES), "tiers": {}, "uploads_allowed": False}
    report.update({"collected_tiers": list(COLLECTED_TIERS), "compressed": 0, "deduplicated": 0, "bytes_saved": 0, "bytes_stored": 0})
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
                patch_property(row["id"], build_update_fields(stored_url, checked_at=checked_at))
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
          f"bytes stored {report.get('bytes_stored', 0)}, estimated bytes saved {report.get('bytes_saved', 0)}")
    for name, t in report["tiers"].items():
        print(f"  {name}: outstanding {t['outstanding']}, attempted {t['attempted']}, stored {t['stored']}, "
              f"no coverage {t['no_coverage']}, failed {t['failed']}, deferred {t['deferred']}")


if __name__ == "__main__":
    sys.exit(main())
