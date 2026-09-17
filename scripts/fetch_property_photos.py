#!/usr/bin/env python3
"""Backfill `properties.photo_url` with a real Google Street View Static
image, cached in Supabase Storage (`property-photos` bucket, public read).

Why server-side, not a live client-side fetch: a Street View Static API
call is billed per request and requires an API key. Calling it from the
browser would mean shipping that key to every visitor (same class of
mistake `public/config.js`'s comments warn about for the Supabase
service_role key) and re-paying for the same photo on every single page
view. Fetching it once here, storing the bytes in our own Storage bucket,
and having the frontend read `photo_url` like any other column means the
key never leaves this script and each address is paid for exactly once.

Requires GOOGLE_MAPS_API_KEY (Street View Static API enabled, billing
account attached - Google's free monthly credit comfortably covers this
app's traffic) as a GitHub Actions secret. Until that secret exists, this
script prints one line saying so and exits 0 - same "ship the pipeline
ahead of the credential" pattern texas_harvester.py's still-stubbed
harvest_pbfcm()/harvest_govease() already use in this repo, so a missing
key never fails the job, it just means no photos land yet.

Requires schema-v9-property-photos.sql to have been run against Supabase
first (adds `properties.photo_url` and creates the storage bucket) - same
intentional-failure pattern as geocode_properties.py without
schema-v8-geocoding.sql.

Two-call pattern per property: the Street View Static **metadata**
endpoint is free and tells us whether real imagery exists at that address
BEFORE spending a paid image call - a real concern here, since a lot of
tax-deed inventory is vacant land or rural parcels Street View's coverage
car never reached. Only a metadata "OK" triggers the billed image call.

Sentinel distinction, on purpose, unlike geocode_properties.py's own
`latitude IS NULL` gate (which the priority-fix note in that script admits
re-attempts the same known-unmatchable junk-address rows every run): a
confirmed "no coverage here" result is stored as `photo_url = ''` (empty
string), NOT left NULL - so fetch_unphotographed()'s `photo_url IS NULL`
filter permanently excludes it from future batches instead of re-spending
a metadata call on it forever. NULL means "not yet checked"; '' means
"checked, nothing there"; a real value means "cached photo ready."
"""
import os
import sys
import time
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
BATCH_LIMIT = int(os.environ.get("PHOTO_BATCH_LIMIT", "50"))
REQUEST_DELAY_SECONDS = 0.3
BUCKET = "property-photos"
IMAGE_SIZE = "640x400"

STREETVIEW_METADATA = "https://maps.googleapis.com/maps/api/streetview/metadata"
STREETVIEW_IMAGE = "https://maps.googleapis.com/maps/api/streetview"

if not SUPABASE_URL or not SERVICE_KEY:
    print("SUPABASE_URL / SUPABASE_SERVICE_KEY environment variables are not set - check the workflow's secrets.", file=sys.stderr)
    sys.exit(1)

if not GOOGLE_MAPS_API_KEY:
    print(
        "GOOGLE_MAPS_API_KEY is not set - skipping photo backfill for this run "
        "(not a failure: this pipeline is shipped ahead of the credential, same "
        "as texas_harvester.py's still-stubbed vendors. Add a Street View Static "
        "API key as a GOOGLE_MAPS_API_KEY GitHub Actions secret to activate it - "
        "see CLAUDE.md's Property photos section.)"
    )
    sys.exit(0)

HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
}


def fetch_unphotographed(limit):
    """Rows with a real address or coordinates but no photo attempt yet.
    See the module docstring for why `photo_url IS NULL` (not `= ''`) is
    the correct "not yet checked" filter here."""
    params = {
        "photo_url": "is.null",
        "select": "id,address,latitude,longitude",
        "limit": str(limit),
        "or": "(address.not.is.null,latitude.not.is.null)",
    }
    resp = requests.get(f"{SUPABASE_URL}/rest/v1/properties", headers=HEADERS, params=params, timeout=30)
    if resp.status_code == 400 and "photo_url" in resp.text.lower():
        print(
            "PHOTO BACKFILL FAILED - most likely schema-v9-property-photos.sql "
            "hasn't been run against this Supabase project yet.\n"
            f"Error: {resp.status_code} {resp.text[:300]}",
            file=sys.stderr,
        )
        sys.exit(1)
    resp.raise_for_status()
    return resp.json()


def location_param(row):
    if row.get("latitude") is not None and row.get("longitude") is not None:
        return f"{row['latitude']},{row['longitude']}"
    return row.get("address")


def has_coverage(location):
    resp = requests.get(
        STREETVIEW_METADATA,
        params={"location": location, "key": GOOGLE_MAPS_API_KEY},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("status") == "OK"


def fetch_image_bytes(location):
    resp = requests.get(
        STREETVIEW_IMAGE,
        params={"location": location, "size": IMAGE_SIZE, "key": GOOGLE_MAPS_API_KEY},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.content


def upload_photo(property_id, image_bytes):
    """Uploads to Supabase Storage and returns the public URL. `upsert:true`
    (via the x-upsert header) makes this safe to re-run for a row whose
    photo_url patch failed after a successful upload on a prior attempt."""
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{property_id}.jpg"
    upload_headers = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "image/jpeg",
        "x-upsert": "true",
    }
    resp = requests.post(url, headers=upload_headers, data=image_bytes, timeout=30)
    resp.raise_for_status()
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{property_id}.jpg"


def patch_property(property_id, photo_url):
    url = f"{SUPABASE_URL}/rest/v1/properties?id=eq.{property_id}"
    patch_headers = dict(HEADERS)
    patch_headers["Prefer"] = "return=minimal"
    resp = requests.patch(url, headers=patch_headers, json={"photo_url": photo_url}, timeout=15)
    resp.raise_for_status()


def main():
    rows = fetch_unphotographed(BATCH_LIMIT)
    print(f"Found {len(rows)} propert{'y' if len(rows) == 1 else 'ies'} without a photo attempt yet (limit {BATCH_LIMIT} per run).")
    if not rows:
        print("Nothing to fetch.")
        return

    cached = 0
    no_coverage = 0
    skipped = 0
    errors = 0
    for i, row in enumerate(rows, 1):
        location = location_param(row)
        if not location:
            skipped += 1
            continue
        try:
            if not has_coverage(location):
                no_coverage += 1
                patch_property(row["id"], "")  # sentinel: checked, nothing there
                time.sleep(REQUEST_DELAY_SECONDS)
                continue
            image_bytes = fetch_image_bytes(location)
            photo_url = upload_photo(row["id"], image_bytes)
            patch_property(row["id"], photo_url)
            cached += 1
            if i % 10 == 0 or i == len(rows):
                print(f"  [{i}/{len(rows)}] cached {cached} so far...")
        except requests.RequestException as e:
            errors += 1
            print(f"  [{i}/{len(rows)}] ERROR fetching photo for {row.get('address') or row['id']}: {e}", file=sys.stderr)
        time.sleep(REQUEST_DELAY_SECONDS)

    print(
        f"Done. Cached {cached}, no Street View coverage {no_coverage}, "
        f"skipped (no address/coords) {skipped}, errors {errors} "
        f"(of {len(rows)} attempted)."
    )


if __name__ == "__main__":
    main()
