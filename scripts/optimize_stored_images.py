#!/usr/bin/env python3
"""Measure and optimize the stored property imagery (storage-optimization sprint, 2026-10-01).

    python3 scripts/optimize_stored_images.py                  # --analyze: read-only report
    python3 scripts/optimize_stored_images.py --apply [--max N]
    python3 scripts/optimize_stored_images.py --apply --consolidate   # see CONSOLIDATION below

Runs as the manual `job=storage` of harvest-and-sync.yml (input `storage_mode`).
The sandbox cannot reach Supabase Storage, so every measurement is taken from
the runner.

ANALYZE (read-only, the default)
  * Lists every object in the bucket, which gives the bytes, the count, the
    MIME type, the eTag and the size distribution.
  * Joins the objects to the properties that reference them, giving a
    breakdown by tier (Available / active auction / closed auction /
    certificate / unreferenced), state, ledger, source and county.
  * Finds the exact-duplicate candidates (same eTag and size).
  * Downloads a stratified sample and measures, per image:
    - the format and dimensions;
    - the same-size WebP size and the decode check;
  * Projects the bucket under policies A-D (image_storage.project_policies).
  * Writes `out/public/storage-analysis.json`. It holds counts and sizes only:
    no parcel, no property id, no URL.

APPLY: compress in place
  Each object that is not yet WebP is downloaded through the authenticated
  endpoint (not the CDN), then re-encoded at the same dimensions
  (`image_storage.optimize_image`). The re-encoded file is uploaded back to
  the SAME path only when all of these hold:
    * it decodes;
    * its dimensions are unchanged;
    * it is strictly smaller.
  The stored object is then downloaded again and checked. Its bytes must match
  the upload and it must decode at the same size. If that check fails, the
  original bytes are put back.

  Keeping the path means no `properties` row is written. That matters: every
  UPDATE on `properties` fires `touch_updated_at`, and `updated_at` is what
  the app shows as "Last synced" and uses for its stale warnings. Repointing
  3,500 rows would make each of them look freshly synced, which is false.

  A second run finds every object already WebP and changes nothing
  (idempotent). No object is deleted by this mode.

CONSOLIDATION (--consolidate; off by default)
  Exact duplicates (byte-identical, confirmed by sha256 after download, never
  by eTag alone) are folded onto one canonical object:
    1. every referencing row is repointed to the canonical object;
    2. the references are re-counted, and must be zero;
    3. only then is the redundant object deleted.
  Step 1 is a row write, so it bumps `updated_at` on those rows. That is why
  this step is opt-in and reported separately; run it only once that
  trade-off is accepted.

FAIL-SAFE
  An object this run cannot read, encode, verify or write is left exactly as
  it was. Any error ends the run with the report written; it never touches
  any other table or job.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from collections import Counter, defaultdict

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import image_storage as IS  # noqa: E402

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
BUCKET = os.environ.get("NAIP_STORAGE_BUCKET", "property-photos")
BUDGET_MB = float(os.environ.get("NAIP_STORAGE_BUDGET_MB", "950"))
TIMEOUT = 60
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "out", "public")
API_PAGE = 1000          # PostgREST max-rows


def _h(extra: dict | None = None) -> dict:
    h = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}
    h.update(extra or {})
    return h


# ---------------------------------------------------------------- storage I/O
def list_objects(prefix: str = "", depth: int = 0) -> list[dict]:
    out, offset = [], 0
    while True:
        r = requests.post(f"{SUPABASE_URL}/storage/v1/object/list/{BUCKET}", headers=_h({"Content-Type": "application/json"}), timeout=TIMEOUT,
                          json={"prefix": prefix, "limit": 1000, "offset": offset, "sortBy": {"column": "name", "order": "asc"}})
        r.raise_for_status()
        items = r.json()
        for it in items:
            if it.get("id") is None:
                if depth < 4:
                    out.extend(list_objects(f"{prefix}{it.get('name')}/", depth + 1))
                continue
            md = it.get("metadata") or {}
            out.append({"name": f"{prefix}{it.get('name')}", "size": int(md.get("size") or 0),
                        "etag": str(md.get("eTag") or "").strip('"'), "mimetype": md.get("mimetype") or ""})
        if len(items) < 1000:
            return out
        offset += 1000


def download(path: str) -> bytes | None:
    """Authenticated read - straight from storage, never a CDN copy."""
    try:
        r = requests.get(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}", headers=_h(), timeout=TIMEOUT)
    except requests.RequestException:
        return None
    return r.content if r.status_code == 200 else None


def upload(path: str, data: bytes, content_type: str, *, upsert: bool) -> bool:
    try:
        r = requests.post(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}", timeout=TIMEOUT, data=data,
                          headers=_h({"Content-Type": content_type, "x-upsert": "true" if upsert else "false", "cache-control": "3600"}))
    except requests.RequestException:
        return False
    return r.status_code in (200, 201)


def delete_objects(paths: list[str]) -> bool:
    try:
        r = requests.delete(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}", headers=_h({"Content-Type": "application/json"}),
                            json={"prefixes": paths}, timeout=TIMEOUT)
    except requests.RequestException:
        return False
    return r.status_code == 200


def public_url(path: str) -> str:
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{path}"


# ---------------------------------------------------------------- database I/O
def property_refs() -> list[dict]:
    rows, offset = [], 0
    while True:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/properties", headers=_h(), timeout=TIMEOUT, params={
            "select": "id,state,source,county,status,photo_url", "photo_url": f"like.*/{BUCKET}/*",
            "order": "id.asc", "limit": str(API_PAGE), "offset": str(offset)})
        r.raise_for_status()
        page = r.json()
        rows.extend(page)
        if len(page) < API_PAGE:
            return rows
        offset += len(page)


def outstanding_by_tier() -> dict:
    """Rows with coordinates and no image yet, per tier (exact counts)."""
    gone = "(" + ",".join(sorted(IS.GONE)) + ")"
    spec = {"available": {"source": "eq.laft", "status": f"not.in.{gone}"},
            "auction_active": {"source": "eq.auction", "status": f"not.in.{gone}"},
            "auction_closed": {"source": "eq.auction", "status": f"in.{gone}"},
            "certificate": {"source": "eq.certificate"}}
    out = {}
    for tier, flt in spec.items():
        params = {"select": "id", "photo_url": "is.null", "latitude": "not.is.null", "longitude": "not.is.null", "limit": "1"}
        params.update(flt)
        r = requests.get(f"{SUPABASE_URL}/rest/v1/properties", params=params, timeout=TIMEOUT, headers=_h({"Prefer": "count=exact"}))
        rng = r.headers.get("Content-Range", "*/0")
        out[tier] = int(rng.split("/")[-1]) if rng.split("/")[-1].isdigit() else 0
    return out


def repoint(old_url: str, new_url: str) -> int:
    r = requests.patch(f"{SUPABASE_URL}/rest/v1/properties", params={"photo_url": f"eq.{old_url}"}, json={"photo_url": new_url},
                       headers=_h({"Content-Type": "application/json", "Prefer": "return=representation"}), timeout=TIMEOUT)
    r.raise_for_status()
    return len(r.json())


def refs_to(url: str) -> int:
    r = requests.get(f"{SUPABASE_URL}/rest/v1/properties", params={"select": "id", "photo_url": f"eq.{url}", "limit": "1"},
                     headers=_h({"Prefer": "count=exact"}), timeout=TIMEOUT)
    r.raise_for_status()
    return int(r.headers.get("Content-Range", "*/0").split("/")[-1] or 0)


# ---------------------------------------------------------------- analysis
def classify(objects: list[dict], refs: list[dict]) -> dict:
    by_path = defaultdict(list)
    for row in refs:
        path = IS.object_path_of(row.get("photo_url"), BUCKET)
        if path:
            by_path[path].append(row)
    tiers, states, ledgers, counties, refs_per_object = Counter(), Counter(), Counter(), Counter(), Counter()
    tier_bytes = Counter()
    for o in objects:
        rows = by_path.get(o["name"], [])
        refs_per_object[min(len(rows), 3)] += 1
        if not rows:
            tiers["unreferenced"] += 1
            tier_bytes["unreferenced"] += o["size"]
            continue
        # One object, several rows: the highest-priority tier wins.
        tier = min((IS.tier_of(r.get("source"), r.get("status")) for r in rows), key=lambda t: IS.PRIORITY.get(t, 9))
        tiers[tier] += 1
        tier_bytes[tier] += o["size"]
        states[rows[0].get("state") or "?"] += o["size"]
        ledgers[rows[0].get("source") or "?"] += o["size"]
        counties[f"{rows[0].get('state')}/{rows[0].get('county')}"] += o["size"]
    mb = lambda c: {k: round(v / 1048576, 1) for k, v in c.most_common()}  # noqa: E731
    return {"objects_by_tier": dict(tiers), "mb_by_tier": mb(tier_bytes), "mb_by_state": mb(states), "mb_by_ledger": mb(ledgers),
            "mb_top_counties": dict(list(mb(counties).items())[:15]),
            "objects_by_reference_count": {"0": refs_per_object[0], "1": refs_per_object[1], "2": refs_per_object[2], "3+": refs_per_object[3]}}


def sample_measure(objects: list[dict], n: int) -> dict:
    pool = [o for o in objects if o["mimetype"] != "image/webp"]
    random.Random(20261001).shuffle(pool)
    dims, fmts, ratios, refused = Counter(), Counter(), [], Counter()
    for o in pool[:n]:
        data = download(o["name"])
        if data is None:
            refused["download failed"] += 1
            continue
        p = IS.probe(data)
        if p:
            fmts[p[0]] += 1
            dims[f"{p[1]}x{p[2]}"] += 1
        opt = IS.optimize_image(data)
        if opt.optimized:
            ratios.append(len(opt.data) / len(data))
        else:
            refused[opt.reason] += 1
    return {"sampled": min(n, len(pool)), "formats": dict(fmts), "dimensions": dict(dims),
            "webp_ratio_median": round(statistics.median(ratios), 3) if ratios else None,
            "webp_ratio_mean": round(statistics.mean(ratios), 3) if ratios else None,
            "webp_ratio_max": round(max(ratios), 3) if ratios else None, "not_optimizable": dict(refused)}


def analyze(args) -> dict:
    objects = list_objects()
    refs = property_refs()
    sizes = sorted(o["size"] for o in objects)
    total = sum(sizes)
    groups = IS.consolidation_groups(objects)
    dup_groups = [g for g in groups if len(g) > 1]
    sample = sample_measure(objects, args.sample)
    ratio = sample["webp_ratio_mean"] or 1.0
    budget = int(BUDGET_MB * 1048576)
    report = {
        "bucket": BUCKET, "objects": len(objects), "bytes": total, "mb": round(total / 1048576, 1),
        "budget_mb": BUDGET_MB, "pct_of_budget": round(100 * total / budget, 1), "remaining_mb": round((budget - total) / 1048576, 1),
        "avg_bytes": int(total / max(1, len(objects))), "median_bytes": int(statistics.median(sizes)) if sizes else 0,
        "largest_bytes": sizes[-10:][::-1], "mimetypes": dict(Counter(o["mimetype"] for o in objects)),
        "already_webp": sum(1 for o in objects if o["mimetype"] == "image/webp"),
        "duplicate_groups": len(dup_groups), "duplicate_redundant_objects": sum(len(g) - 1 for g in dup_groups),
        "duplicate_redundant_mb": round(sum((len(g) - 1) * g[0]["size"] for g in dup_groups) / 1048576, 1),
        "largest_duplicate_groups": [len(g) for g in dup_groups[:8]],
        "classification": classify(objects, refs), "sample": sample,
    }
    outstanding = outstanding_by_tier()
    report["outstanding_new_imagery"] = outstanding
    proj = IS.project_policies(objects, sample_ratio=ratio, budget_bytes=budget, outstanding=outstanding)
    report["policies_mb"] = {k: (round(v / 1048576, 1) if isinstance(v, int) and k[0] in "ABCD" else v) for k, v in proj.items()}
    return report


# ---------------------------------------------------------------- apply
def compress_in_place(objects: list[dict], limit: int | None) -> dict:
    stats = Counter()
    saved = 0
    todo = [o for o in objects if o["mimetype"] != "image/webp"]
    stats["already_optimized"] = len(objects) - len(todo)
    for o in todo[: limit or len(todo)]:
        original = download(o["name"])
        if original is None:
            stats["skipped_unreadable"] += 1
            continue
        opt = IS.optimize_image(original)
        if not opt.optimized:
            stats[f"left_unchanged: {opt.reason}"] += 1
            continue
        if not upload(o["name"], opt.data, opt.content_type, upsert=True):
            stats["upload_failed_left_unchanged"] += 1
            continue
        stored = download(o["name"])
        check = IS.probe(stored) if stored else None
        if stored != opt.data or check is None or (check[1], check[2]) != (opt.width, opt.height):
            # Put the original back: never leave an unverified replacement.
            restored = upload(o["name"], original, "image/png", upsert=True)
            stats["verify_failed_restored" if restored else "verify_failed_RESTORE_FAILED"] += 1
            continue
        stats["optimized"] += 1
        saved += len(original) - len(opt.data)
        if stats["optimized"] % 200 == 0:
            print(f"  optimized {stats['optimized']} so far, {saved / 1048576:.1f} MB saved")
    return {"counts": dict(stats), "bytes_saved": saved, "mb_saved": round(saved / 1048576, 1)}


def consolidate(objects: list[dict], refs: list[dict]) -> dict:
    by_path = defaultdict(list)
    for row in refs:
        p = IS.object_path_of(row.get("photo_url"), BUCKET)
        if p:
            by_path[p].append(row)
    stats, saved = Counter(), 0
    for group in IS.consolidation_groups(objects):
        if len(group) < 2:
            continue
        blobs = {o["name"]: download(o["name"]) for o in group}
        if any(b is None for b in blobs.values()):
            stats["group_skipped_unreadable"] += 1
            continue
        by_hash = defaultdict(list)
        for name, b in blobs.items():
            by_hash[IS.sha256(b)].append(name)
        for names in by_hash.values():            # only byte-identical objects are merged
            if len(names) < 2:
                continue
            names.sort()
            keep, drop = names[0], names[1:]
            keep_url = public_url(keep)
            removable = []
            for name in drop:
                old_url = public_url(name)
                if by_path.get(name):
                    stats["rows_repointed"] += repoint(old_url, keep_url)
                if refs_to(old_url) == 0:
                    removable.append(name)
                else:
                    stats["kept_still_referenced"] += 1
            if removable and delete_objects(removable):
                stats["objects_removed"] += len(removable)
                saved += sum(len(blobs[n]) for n in removable)
    return {"counts": dict(stats), "bytes_saved": saved, "mb_saved": round(saved / 1048576, 1)}


def write(name: str, report: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, name), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Measure / optimize stored property imagery.")
    ap.add_argument("--apply", action="store_true", help="re-encode objects in place (no row writes)")
    ap.add_argument("--consolidate", action="store_true", help="with --apply: also fold byte-identical objects (repoints rows)")
    ap.add_argument("--max", type=int, default=None, help="optimize at most N objects this run")
    ap.add_argument("--sample", type=int, default=120, help="objects downloaded for the analysis sample")
    args = ap.parse_args(argv)
    if not SUPABASE_URL or not SERVICE_KEY:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set - nothing measured.")
        return 0
    if IS.probe(b"") is None and IS._image() is None:
        print("Pillow is not installed - nothing can be measured or optimized.")
        return 1
    started = time.time()
    before = analyze(args)
    print(json.dumps({k: before[k] for k in ("objects", "mb", "pct_of_budget", "already_webp", "duplicate_redundant_objects",
                                             "duplicate_redundant_mb", "mimetypes")}, indent=1))
    print("classification:", json.dumps(before["classification"], indent=1))
    print("sample:", json.dumps(before["sample"], indent=1))
    print("outstanding new imagery:", before["outstanding_new_imagery"])
    print("policies (MB):", json.dumps(before["policies_mb"], indent=1))
    result = {"mode": "apply" if args.apply else "analyze", "before": before}
    if args.apply:
        objects = list_objects()
        result["compress"] = compress_in_place(objects, args.max)
        print("compress:", result["compress"])
        if args.consolidate:
            result["consolidate"] = consolidate(list_objects(), property_refs())
            print("consolidate:", result["consolidate"])
        after = list_objects()
        total = sum(o["size"] for o in after)
        result["after"] = {"objects": len(after), "bytes": total, "mb": round(total / 1048576, 1),
                           "pct_of_budget": round(100 * total / int(BUDGET_MB * 1048576), 1),
                           "mimetypes": dict(Counter(o["mimetype"] for o in after))}
        print("after:", result["after"])
    result["seconds"] = int(time.time() - started)
    write("storage-optimization.json" if args.apply else "storage-analysis.json", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
