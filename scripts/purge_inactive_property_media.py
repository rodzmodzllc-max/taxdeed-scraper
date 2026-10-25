#!/usr/bin/env python3
"""Release stored property media for records that are no longer active.

Policy (owner, 2026-10-25): stored photos and parcel outlines are kept only
while a property is being presented. When a record drops off its list
(closed, dropped, not found, or delisted) the stored picture and outline are
released. A record that returns is enriched again by the normal pipeline,
because its photo_url is NULL once released and its outline is refreshed for
active rows only.

What is released for an INACTIVE row (not an active status, or delisted_at
set):
  * properties.photo_url / photo_source are set to NULL (never '' - '' means
    "checked, no image" and must not be written for a row that was never
    checked);
  * its parcel_boundaries row is deleted;
  * its storage object is deleted, but only when no ACTIVE row still points
    at it. Photos are content-addressed and can be shared by two rows.

Order matters: the database pointers are cleared first, and an object is
removed only after every pointer to it has been cleared. A failed database
step deletes nothing from storage.

Dry run by default. Writes need --confirm-apply. Output is counts only, never
a row, an address or a parcel number.

Environment: SUPABASE_URL, SUPABASE_SERVICE_KEY (service role, read only in
main()). Bucket: NAIP_STORAGE_BUCKET (default property-photos).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harvesters.enrichment.priority import is_active  # noqa: E402
import rest_pages  # noqa: E402

PATCH_CHUNK = 200
DELETE_CHUNK = 500
REQUEST_TIMEOUT = 60


def is_inactive(row: dict) -> bool:
    """Same rule as enrichment priority, plus a delisting date."""
    return (not is_active(row)) or row.get("delisted_at") is not None


def storage_path(photo_url: str, bucket: str) -> str | None:
    """The object path inside the bucket, or None for a URL that is not ours."""
    marker = f"/{bucket}/"
    if not photo_url or marker not in photo_url:
        return None
    return photo_url.split(marker, 1)[1].split("?", 1)[0] or None


def plan(property_rows: list[dict], boundary_ids: set, bucket: str) -> dict:
    """Pure: what would be released. property_rows carries id, status,
    delisted_at, photo_url; boundary_ids is the set of property ids that have
    an outline stored."""
    inactive_photo_ids, inactive_boundary_ids = [], []
    live_paths: set[str] = set()
    candidate_paths: set[str] = set()

    for row in property_rows:
        pid = row["id"]
        path = storage_path(row.get("photo_url") or "", bucket)
        if is_inactive(row):
            if row.get("photo_url"):
                inactive_photo_ids.append(pid)
                if path:
                    candidate_paths.add(path)
            if pid in boundary_ids:
                inactive_boundary_ids.append(pid)
        elif path:
            live_paths.add(path)

    delete_paths = sorted(candidate_paths - live_paths)
    kept_shared = len(candidate_paths & live_paths)
    return {
        "clear_photo_ids": inactive_photo_ids,
        "delete_boundary_ids": inactive_boundary_ids,
        "delete_storage_paths": delete_paths,
        "kept_shared_objects": kept_shared,
    }


def chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def apply_plan(base: str, key: str, bucket: str, result: dict) -> dict:
    headers = {**_headers(key), "Prefer": "return=minimal"}
    rest = f"{base.rstrip('/')}/rest/v1"
    done = {"photo_rows_cleared": 0, "boundaries_deleted": 0, "storage_objects_deleted": 0, "failures": 0}

    for ids in chunks(result["clear_photo_ids"], PATCH_CHUNK):
        resp = requests.patch(f"{rest}/properties", headers=headers, timeout=REQUEST_TIMEOUT,
                              params={"id": f"in.({','.join(map(str, ids))})"},
                              json={"photo_url": None, "photo_source": None})
        if resp.status_code >= 300:
            print(f"  clearing photo pointers failed: HTTP {resp.status_code}; storage left untouched", file=sys.stderr)
            done["failures"] += 1
            return done
        done["photo_rows_cleared"] += len(ids)

    for ids in chunks(result["delete_boundary_ids"], PATCH_CHUNK):
        resp = requests.delete(f"{rest}/parcel_boundaries", headers=headers, timeout=REQUEST_TIMEOUT,
                               params={"property_id": f"in.({','.join(ids)})"})
        if resp.status_code >= 300:
            print(f"  deleting outlines failed: HTTP {resp.status_code}", file=sys.stderr)
            done["failures"] += 1
        else:
            done["boundaries_deleted"] += len(ids)

    # Every pointer to these objects was cleared above, so removing them
    # cannot leave a row with a dead URL.
    for paths in chunks(result["delete_storage_paths"], DELETE_CHUNK):
        resp = requests.delete(f"{base.rstrip('/')}/storage/v1/object/{bucket}", headers=_headers(key),
                               timeout=REQUEST_TIMEOUT, json={"prefixes": paths})
        if resp.status_code >= 300:
            print(f"  deleting stored objects failed: HTTP {resp.status_code}", file=sys.stderr)
            done["failures"] += 1
        else:
            done["storage_objects_deleted"] += len(paths)
    return done


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--confirm-apply", action="store_true", help="write; without it this is a dry run")
    args = parser.parse_args(argv)

    base = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    bucket = os.environ.get("NAIP_STORAGE_BUCKET", "property-photos")
    if not base or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY are not set; nothing read, nothing written.", file=sys.stderr)
        return 2

    rows = rest_pages.read_all(base, "properties", _headers(key),
                               {"select": "id,status,delisted_at,photo_url", "order": "id.asc"})
    boundary_rows = rest_pages.read_all(base, "parcel_boundaries", _headers(key),
                                        {"select": "property_id", "order": "property_id.asc"})
    boundary_ids = {r["property_id"] for r in boundary_rows}
    result = plan(rows, boundary_ids, bucket)

    print(f"read: {len(rows)} properties, {len(boundary_ids)} stored outlines")
    print(f"would clear photo pointers on {len(result['clear_photo_ids'])} inactive rows")
    print(f"would delete {len(result['delete_boundary_ids'])} outlines of inactive rows")
    print(f"would delete {len(result['delete_storage_paths'])} stored objects "
          f"({result['kept_shared_objects']} shared with active rows, kept)")

    if not args.confirm_apply:
        print("dry run: nothing written (pass --confirm-apply to release)")
        return 0
    done = apply_plan(base, key, bucket, result)
    print(f"applied: {done}")
    return 1 if done["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
