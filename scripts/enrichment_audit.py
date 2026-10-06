#!/usr/bin/env python3
"""Enrichment coverage audit: counts per state x county x ledger.

For every active record (status active / available) it counts the fields an
investor uses - coordinates and their provenance, identifiers, legal
description, values, acreage, land use, owner / assessed name, FDOR
enrichment, acquisition evidence, purchase / application and auction URLs,
imagery - and the records missing source truth or provenance, both for all
records and for the customer-visible ones, with each record's enrichment
priority rule (harvesters/enrichment/priority.py).

Counts only: no identifier, address, value or name is ever written to the
log or to out/public/enrichment-audit.json. Read-only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from harvesters.enrichment import priority as PR  # noqa: E402
from harvesters.sources import coordinates as C  # noqa: E402

READ_COLUMNS = ("id,state,county,ledger_type,source,status,publication_status,parcel,case_no,legal_desc,assessed,"
                "market,taxable_value,acreage,lot_sqft,land_use,dor_use_code,owner_name,fdor_enriched_at,"
                "purchase_path_type,otc_provenance,purchase_url,url_auction,photo_url,latitude,longitude,"
                "field_provenance,source_id,harvester_source")

METRICS = ("records", "coordinates", "authoritative_coordinates", "parcel", "legal_description", "assessed_value",
           "taxable_value", "acreage", "land_use", "owner_name", "fdor_enriched", "acquisition_evidence",
           "purchase_url", "auction_url", "imagery_capable", "stored_imagery", "missing_source_truth",
           "incomplete_provenance")


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def facts(row: dict) -> dict:
    """The per-record presence tests (booleans). One record, one source of truth."""
    coords = C.has_coordinates(row)
    otc = row.get("otc_provenance") if isinstance(row.get("otc_provenance"), dict) else {}
    fp = row.get("field_provenance") if isinstance(row.get("field_provenance"), dict) else {}
    return {
        "records": True,
        "coordinates": coords,
        "authoritative_coordinates": coords and C.coordinate_provenance(row)["authoritative"],
        "parcel": not _blank(row.get("parcel")),
        "legal_description": not _blank(row.get("legal_desc")),
        "assessed_value": row.get("assessed") is not None or row.get("market") is not None,
        "taxable_value": row.get("taxable_value") is not None,
        "acreage": row.get("acreage") is not None or row.get("lot_sqft") is not None,
        "land_use": not _blank(row.get("land_use")) or not _blank(row.get("dor_use_code")),
        "owner_name": not _blank(row.get("owner_name")),
        "fdor_enriched": row.get("fdor_enriched_at") is not None,
        "acquisition_evidence": not _blank(row.get("purchase_path_type")) or bool(otc.get("acquisition")),
        "purchase_url": not _blank(row.get("purchase_url")),
        "auction_url": not _blank(row.get("url_auction")),
        # Live USDA NAIP needs only coordinates (and no '' "checked, no image" sentinel).
        "imagery_capable": coords and row.get("photo_url") != "",
        "stored_imagery": not _blank(row.get("photo_url")),
        "missing_source_truth": _blank(row.get("source_id")) and _blank(row.get("harvester_source")),
        "incomplete_provenance": not fp,
    }


def audit(rows, ctx: PR.Context | None = None) -> dict:
    """{"units": [...], "totals": {...}} - one unit per (state, county, ledger)."""
    ctx = ctx or PR.Context()
    units: dict[tuple, dict] = {}
    for r in rows:
        if not PR.is_active(r):
            continue
        key = (str(r.get("state") or ""), str(r.get("county") or ""), PR.ledger_of(r) or "UNKNOWN")
        u = units.setdefault(key, {"state": key[0], "county": key[1], "ledger": key[2],
                                   "all": dict.fromkeys(METRICS, 0), "visible": dict.fromkeys(METRICS, 0),
                                   "rules": dict.fromkeys(PR.RULE_IDS, 0), "coordinate_methods": {}})
        f = facts(r)
        vis = PR.customer_visible(r)
        for m in METRICS:
            if f[m]:
                u["all"][m] += 1
                if vis:
                    u["visible"][m] += 1
        u["rules"][PR.rule_of(r, ctx)] += 1
        meth = C.coordinate_provenance(r)["method"]
        u["coordinate_methods"][meth] = u["coordinate_methods"].get(meth, 0) + 1
    out = sorted(units.values(), key=lambda u: (u["state"], u["ledger"], u["county"]))
    totals = dict.fromkeys(METRICS, 0)
    for u in out:
        for m in METRICS:
            totals[m] += u["all"][m]
    return {"units": out, "totals": totals}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rows", help="read rows from this JSON file instead of the database")
    ap.add_argument("--out", default=str(REPO / "out" / "public" / "enrichment-audit.json"))
    a = ap.parse_args(argv)
    if a.rows:
        rows = json.loads(Path(a.rows).read_text(encoding="utf-8"))
    else:
        base, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not (base and key):
            print("skip: SUPABASE_URL / SUPABASE_SERVICE_KEY not set and no --rows file")
            return 0
        from harvesters.governance import states as S
        rows = []
        for st in sorted(S.PRODUCTION_STATES):
            rows += read(base, key, st)
    report = audit(rows, PR.Context.from_repo())
    p = Path(a.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"units": len(report["units"]), "totals": report["totals"]}, sort_keys=True))
    return 0


def read(base: str, key: str, state: str) -> list[dict]:
    import urllib.parse
    from scripts import geocode_authoritative as GA
    hdr = {"apikey": key, "Authorization": f"Bearer {key}"}
    rows, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"select": READ_COLUMNS, "state": f"eq.{state}", "status": "in.(active,available)",
                                    "order": "id.asc", "limit": GA.PAGE, "offset": offset})
        page = GA.http_json(f"{base}/rest/v1/properties?{q}", headers=hdr) or []
        rows += page
        if len(page) < GA.PAGE:
            return rows
        offset += len(page)


if __name__ == "__main__":
    raise SystemExit(main())
