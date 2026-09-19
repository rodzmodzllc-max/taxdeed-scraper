#!/usr/bin/env python3
"""Audit enrichment coverage across the properties table.

Produces a comprehensive report of which enrichment fields are populated,
by source (auction/laft/certificate), state, and county. Helps identify
gaps and prioritize enrichment work.

Output: JSON to out/enrichment_audit.json and human-readable markdown
summary to out/enrichment-audit.md.

Read-only: no writes to any table.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
from datetime import datetime, timezone

import requests

OUT_DIR = pathlib.Path("out")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# The headline number: fdor_enriched_at coverage across the two ledgers the
# property-level enrichment targets. Certificates are a lien instrument, not a
# parcel, so they are reported but kept out of this figure.
HEADLINE_SOURCES = ("auction", "laft")

# Field groups, in display order. Every field here exists on `properties`
# (verified against information_schema.columns 2026-09-18).
ENRICHMENT_FIELDS = {
    "Property Type": ["prop_type", "dor_use_code"],
    "Valuation": ["market", "assessed", "land_value"],
    "Assessment": ["value_year"],
    "Owner": ["owner_name"],
    "Coordinates": ["latitude", "longitude"],
    "Structure": ["year_built", "living_area"],
    "Site": ["lot_sqft"],
    "Legal": ["legal_desc"],
    "Sale History": ["last_sale_price", "last_sale_year"],
    "Hazard": ["flood_zone"],
    "Photos": ["photo_url"],
}
ALL_FIELDS = [f for fields in ENRICHMENT_FIELDS.values() for f in fields]


def _get(url: str, **kw):
    """HTTP GET wrapper."""
    return requests.get(url, timeout=60, **kw)


def fetch_all_properties():
    """Fetch all properties from the database (in batches if needed)."""
    if not SUPABASE_URL or not SERVICE_KEY:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_KEY not set", file=sys.stderr)
        sys.exit(1)

    headers = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
    }

    all_rows = []
    offset = 0
    batch_size = 1000

    while True:
        params = {
            "select": "source,state,county,prop_type,dor_use_code,market,value_year,assessed,"
            "owner_name,latitude,longitude,year_built,living_area,lot_sqft,land_value,"
            "legal_desc,last_sale_price,last_sale_year,fdor_enriched_at,flood_zone,photo_url",
            "limit": str(batch_size),
            "offset": str(offset),
        }
        resp = _get(f"{SUPABASE_URL}/rest/v1/properties", headers=headers, params=params)
        resp.raise_for_status()

        rows = resp.json()
        if not rows:
            break

        all_rows.extend(rows)
        offset += batch_size
        print(f"[audit] Fetched {len(all_rows)} properties so far...", file=sys.stderr)

    return all_rows


def is_populated(value) -> bool:
    """True when a field carries a real value: not NULL, not '' / whitespace.

    '' matters: photo_url uses '' as a "checked, no coverage" sentinel (see
    CLAUDE.md, Property photos) and must not count as a photo.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def compute_coverage(rows: list[dict]) -> dict:
    """Compute enrichment coverage statistics."""
    coverage = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_rows": len(rows),
        "headline": {"sources": list(HEADLINE_SOURCES), "total": 0, "enriched": 0},
        "by_source": {},
        "by_state": {},
        "by_county": {},
        "field_coverage": {field: {"populated": 0, "total": 0} for field in ALL_FIELDS},
    }

    for row in rows:
        source = row.get("source") or "unknown"
        state = row.get("state") or "unknown"
        county = row.get("county") or "unknown"
        is_enriched = is_populated(row.get("fdor_enriched_at"))

        src = coverage["by_source"].setdefault(
            source,
            {"total": 0, "enriched": 0, "fields": {f: {"populated": 0, "total": 0} for f in ALL_FIELDS}},
        )
        st = coverage["by_state"].setdefault(state, {"total": 0, "enriched": 0})
        # Counties are keyed per state and source: "Polk" is one FL auction
        # county but "Harris" TX auction and "Harris" TX laft are two
        # different populations, and folding them together hides which
        # ledger actually needs work.
        cty = coverage["by_county"].setdefault(
            f"{state}/{source}/{county}",
            {"total": 0, "enriched": 0, "source": source, "state": state, "county": county},
        )

        src["total"] += 1
        st["total"] += 1
        cty["total"] += 1
        if source in HEADLINE_SOURCES:
            coverage["headline"]["total"] += 1

        if is_enriched:
            src["enriched"] += 1
            st["enriched"] += 1
            cty["enriched"] += 1
            if source in HEADLINE_SOURCES:
                coverage["headline"]["enriched"] += 1

        for field in ALL_FIELDS:
            coverage["field_coverage"][field]["total"] += 1
            src["fields"][field]["total"] += 1
            if is_populated(row.get(field)):
                coverage["field_coverage"][field]["populated"] += 1
                src["fields"][field]["populated"] += 1

    coverage["headline"]["pct_enriched"] = _pct(
        coverage["headline"]["enriched"], coverage["headline"]["total"]
    )
    for bucket in ("by_source", "by_state", "by_county"):
        for stats in coverage[bucket].values():
            stats["pct_enriched"] = _pct(stats["enriched"], stats["total"])
    for stats in coverage["field_coverage"].values():
        stats["pct_populated"] = _pct(stats["populated"], stats["total"])
    for src in coverage["by_source"].values():
        for stats in src["fields"].values():
            stats["pct_populated"] = _pct(stats["populated"], stats["total"])

    return coverage


def write_json_report(coverage: dict, path: pathlib.Path):
    """Write JSON report."""
    with open(path, "w") as f:
        json.dump(coverage, f, indent=2)
    print(f"[audit] JSON report: {path}")


def write_markdown_report(coverage: dict, path: pathlib.Path):
    """Write human-readable markdown report."""
    with open(path, "w") as f:
        f.write("# Enrichment Coverage Audit\n\n")
        f.write(f"Generated: {coverage['timestamp']}\n\n")

        head = coverage["headline"]
        f.write("## Summary\n\n")
        f.write(f"- **Total rows**: {coverage['total_rows']:,}\n")
        f.write(
            f"- **Headline ({' + '.join(head['sources'])})**: "
            f"{head['enriched']:,} / {head['total']:,} enriched "
            f"({head['pct_enriched']}%)\n\n"
        )

        f.write("## By Source\n\n")
        for source in sorted(coverage["by_source"]):
            stats = coverage["by_source"][source]
            f.write(
                f"### {source.capitalize()}\n\n"
                f"- Rows: {stats['total']:,}\n"
                f"- Enriched: {stats['enriched']:,} ({stats['pct_enriched']}%)\n"
                f"- Unenriched: {stats['total'] - stats['enriched']:,}\n\n"
            )
            for field in sorted(stats["fields"], key=lambda x: stats["fields"][x]["pct_populated"], reverse=True):
                fs = stats["fields"][field]
                f.write(f"  - {field}: {fs['pct_populated']}% ({fs['populated']:,}/{fs['total']:,})\n")
            f.write("\n")

        f.write("## By State\n\n")
        for state in sorted(coverage["by_state"]):
            stats = coverage["by_state"][state]
            f.write(
                f"- **{state}**: {stats['total']:,} rows, "
                f"{stats['enriched']:,} enriched ({stats['pct_enriched']}%), "
                f"{stats['total'] - stats['enriched']:,} unenriched\n"
            )
        f.write("\n")

        f.write("## Top Unenriched Counties (by count)\n\n")
        counties_by_unenriched = sorted(
            coverage["by_county"].items(),
            key=lambda x: x[1]["total"] - x[1]["enriched"],
            reverse=True,
        )
        for _key, stats in counties_by_unenriched[:20]:
            unenriched = stats["total"] - stats["enriched"]
            if unenriched > 0:
                f.write(
                    f"- **{stats['county']}** ({stats['state']}/{stats['source']}): "
                    f"{unenriched:,} of {stats['total']:,} unenriched "
                    f"({round(100 - stats['pct_enriched'], 1)}%)\n"
                )
        f.write("\n")

        f.write("## Field Coverage\n\n")
        for field in sorted(coverage["field_coverage"], key=lambda x: coverage["field_coverage"][x]["pct_populated"], reverse=True):
            stats = coverage["field_coverage"][field]
            pct = stats["pct_populated"]
            bar_len = int(pct / 5)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            f.write(
                f"- {field:25s} {bar} {pct:5.1f}% ({stats['populated']:,}/{stats['total']:,})\n"
            )
        f.write("\n")

    print(f"[audit] Markdown report: {path}")


def main():
    OUT_DIR.mkdir(exist_ok=True)
    print("[audit] Fetching properties...", file=sys.stderr)
    rows = fetch_all_properties()

    print(f"[audit] Analyzing {len(rows)} rows...", file=sys.stderr)
    coverage = compute_coverage(rows)

    write_json_report(coverage, OUT_DIR / "enrichment_audit.json")
    write_markdown_report(coverage, OUT_DIR / "enrichment-audit.md")

    print("[audit] Complete", file=sys.stderr)


if __name__ == "__main__":
    main()
