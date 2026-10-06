#!/usr/bin/env python3
"""Operational quality report for every active AVAILABLE record (counts only).

One row per (state, source) covering identity, financials, acquisition,
imagery, provenance and freshness. Its imagery columns come from
``harvesters.imagery.coverage``. This is an operations report: it carries no
score, no ranking and no property value, and it prints no identifier.

    python scripts/available_quality_report.py --rows rows.json      # offline
    SUPABASE_URL=... SUPABASE_SERVICE_KEY=... python scripts/available_quality_report.py

Output: ``out/public/available-quality.json`` and a table on stdout. It reads
only. Online, it pages by id at 1,000 rows (PostgREST max-rows; see CLAUDE.md
"Every whole-population REST read pages by id").
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from harvesters import imagery  # noqa: E402

CLOSED = ("closed", "sold", "gone", "expired", "redeemed", "cancelled", "canceled", "withdrawn")
COLUMNS = ("id,state,county,source,source_id,harvester_source,status,publication_status,parcel,address,"
           "latitude,longitude,field_provenance,photo_url,photo_source,photo_checked_at,purchase_path_type,"
           "purchase_amount,purchase_amount_kind,bid,assessed,market,taxable_value,acreage,land_use,legal_desc,"
           "last_seen_at,list_as_of,source_published_at,inventory_status,otc_provenance")
OUT = REPO / "out" / "public" / "available-quality.json"


def active_available(rows):
    for r in rows:
        if r.get("source") not in (None, "laft"):
            continue
        if str(r.get("status") or "active").lower() in CLOSED:
            continue
        yield r


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def report(rows, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    rows = list(active_available(rows))
    acc = defaultdict(lambda: defaultdict(int))
    for r in rows:
        key = (r.get("state") or "", r.get("source_id") or r.get("harvester_source") or "")
        c = acc[key]
        c["available"] += 1
        c["parcel"] += 0 if _blank(r.get("parcel")) else 1
        addr = str(r.get("address") or "")
        c["address"] += 1 if addr.strip() and not addr.lower().startswith("parcel") else 0
        kind = r.get("purchase_amount_kind")
        has_amount = (kind != "NOT_PUBLISHED") and any((isinstance(r.get(k), (int, float)) and r.get(k) > 0) for k in ("purchase_amount", "bid"))
        c["amount_published"] += 1 if has_amount else 0
        stmt = ((r.get("otc_provenance") or {}).get("purchase_statement") if isinstance(r.get("otc_provenance"), dict) else None)
        c["official_statement"] += 1 if stmt else 0
        path = r.get("purchase_path_type")
        c["acquisition_verified"] += 1 if path and path != "none_published" else 0
        c["values"] += 1 if any(r.get(k) is not None for k in ("assessed", "market", "taxable_value")) else 0
        c["acreage"] += 0 if r.get("acreage") is None else 1
        c["land_use"] += 0 if _blank(r.get("land_use")) else 1
        c["legal_desc"] += 0 if _blank(r.get("legal_desc")) else 1
        fp = r.get("field_provenance")
        c["field_provenance"] += 1 if isinstance(fp, dict) and fp else 0
        c["list_or_document_date"] += 0 if _blank(r.get("list_as_of")) and _blank(r.get("source_published_at")) else 1
        seen = r.get("last_seen_at")
        try:
            t = datetime.fromisoformat(str(seen).replace("Z", "+00:00")) if seen else None
        except ValueError:
            t = None
        c["read_7d"] += 1 if t and now - t <= timedelta(days=7) else 0
        c["never_read"] += 0 if t else 1
        c["lifecycle_status"] += 0 if _blank(r.get("inventory_status")) else 1
    img = {(x["state"], x["source_id"]): x for x in imagery.coverage(rows)}
    out = []
    for key in sorted(acc):
        c = dict(acc[key])
        i = img.get(key, {})
        out.append({"state": key[0], "source_id": key[1], **{k: c.get(k, 0) for k in (
            "available", "parcel", "address", "amount_published", "official_statement", "acquisition_verified",
            "values", "acreage", "land_use", "legal_desc", "field_provenance", "list_or_document_date",
            "read_7d", "never_read", "lifecycle_status")},
            "imagery": {k: i.get(k) for k in ("coordinate_coverage", "deterministic_match", "stored_images", "live_images",
                                               "displayed", "checked_no_image", "missing", "image_sources", "terms_status",
                                               "match_methods")}})
    return out


def fetch_rows(url: str, key: str):  # pragma: no cover - network
    import requests
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    rows, offset = [], 0
    while True:
        resp = requests.get(f"{url}/rest/v1/properties", headers=headers, timeout=60, params={
            "select": COLUMNS, "source": "eq.laft", "order": "id.asc", "limit": 1000, "offset": offset})
        resp.raise_for_status()
        page = resp.json()
        rows.extend(page)
        if len(page) < 1000:
            return rows
        offset += 1000


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rows", help="read rows from a JSON file instead of the database")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    if args.rows:
        rows = json.loads(Path(args.rows).read_text())
    else:
        url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
        if not (url and key):
            print("available_quality_report: SUPABASE_URL / SUPABASE_SERVICE_KEY not set - nothing read.")
            return 0
        rows = fetch_rows(url, key)
    out = report(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "sources": out}, indent=1))
    print(f"{'state':5} {'source':34} {'avail':>6} {'path':>6} {'amount':>6} {'coords':>6} {'images':>6} {'missing':>7}")
    for r in out:
        i = r["imagery"]
        print(f"{r['state']:5} {r['source_id'][:34]:34} {r['available']:>6} {r['acquisition_verified']:>6} "
              f"{r['amount_published']:>6} {i['coordinate_coverage']:>6} {i['displayed']:>6} {i['missing']:>7}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
