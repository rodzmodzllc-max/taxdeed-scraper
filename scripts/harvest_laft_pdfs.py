#!/usr/bin/env python3
"""
Harvest "Lands Available for Taxes" (LAFT) PDFs.

LAFT is Florida's fixed-price leftover-inventory program: a property that got
zero bids at a county's tax deed auction goes on this list, purchasable
directly from the Clerk at a set price for a statutory period. It is NOT the
same product as tax certificates (a separate lien-investment program, already
covered by harvest_lienhub_certificates.ps1) - do not merge the two.

As of 2026-08, none of the 67 counties had ANY automated LAFT coverage - a
67-county research pass (see LAFT_coverage_audit.xlsx delivered separately)
found the list is published as a real, scrapable HTML table in ~20 counties,
behind a search portal in ~27, and as a PDF in a handful, including the 3
below that were individually confirmed live (fetched and read) before being
added here. This script covers the PDF ones specifically - the confirmed-URL
list lives in ../data/laft_pdf_sources.csv, one row per county, so adding a
county is a CSV edit, not a code change.

Deliberately conservative about what's actually confirmed: a county that
*might* publish LAFT as a PDF (e.g. a dead/stale link, or a page seen only in
search results but never actually fetched and read) does NOT belong in the
CSV. Every row here was fetched and its real column layout read before being
added - see the Notes column in the CSV for what was confirmed and when.

Every county's PDF has a different column layout (confirmed different even
across the 3 in this first batch), so this uses a tolerant header-name
normalizer rather than assuming one fixed schema - see HEADER_MAP below.
"Amount to Purchase" / opening bid is often just not published at all (e.g.
Marion) - never fabricate one; leave it null rather than guess.

Output: harvest_laft.json / harvest_laft.csv (source='laft', kept separate
from harvest_all.json/harvest_certificates.json - synced by
sync-laft-to-supabase.ps1, not the other two sync scripts).
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path

import pdfplumber
import requests

HERE = Path(__file__).resolve().parent
SOURCES_CSV = HERE / "../data/laft_pdf_sources.csv"
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_laft.json"
OUT_CSV = OUT_DIR / "harvest_laft.csv"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Column-header aliases -> normalized field name. Matched case-insensitively
# after stripping whitespace/punctuation. Add new aliases here as new
# counties' PDFs get confirmed and added to the CSV - do NOT special-case a
# county by name in the parsing logic itself.
HEADER_MAP = {
    "case number": "case_no", "case #": "case_no", "case no": "case_no",
    "sale #": "case_no", "sale number": "case_no",
    "certificate #": "certificate_no", "certificate number": "certificate_no",
    "parcel id": "parcel", "parcel #": "parcel", "parcel number": "parcel",
    "owner": "owner_name", "owners": "owner_name", "owner(s)": "owner_name",
    "auction date": "sale_date", "sale date": "sale_date",
    "original sale date": "sale_date", "tax deed sale date": "sale_date",
    "escheatment date": "escheatment_date", "expiration date": "escheatment_date",
    "amount to purchase": "bid", "opening bid": "bid",
    "original opening bid": "bid", "purchase price": "bid", "price": "bid",
    "assessed value": "assessed", "property address": "address", "address": "address",
    "legal description": "legal_desc", "description": "legal_desc",
}

# Phrases seen in an otherwise-empty PDF that mean "no properties right now"
# rather than "the parser failed to find a table" - must not be treated as an
# error, and must not produce a fake row.
EMPTY_MARKERS = (
    "no available lands", "no properties at this time", "no properties available",
    "no parcels available", "there are no properties", "nothing available",
)


def normalize_header(h: str) -> str | None:
    if not h:
        return None
    key = re.sub(r"[^a-z0-9()#. ]", "", h.strip().lower())
    key = re.sub(r"\s+", " ", key).strip()
    return HEADER_MAP.get(key)


def looks_empty(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in EMPTY_MARKERS)


def extract_rows(pdf_bytes: bytes, county: str, source_url: str) -> list[dict]:
    rows: list[dict] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        if looks_empty(full_text):
            return []

        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue
                header_row, *body = table
                field_names = [normalize_header(h) for h in header_row]
                if not any(field_names):
                    continue  # not a recognizable data table - e.g. a stray formatting grid
                for raw in body:
                    record: dict = {"county": county, "source": "laft", "url_auction": source_url}
                    for i, field in enumerate(field_names):
                        if not field or i >= len(raw) or raw[i] is None:
                            continue
                        val = str(raw[i]).strip()
                        if val:
                            record[field] = val
                    # A row needs at least a case/parcel identifier to be worth keeping -
                    # matches the same "skip if no case/address" discipline
                    # sync-harvest-to-supabase.ps1 already applies to the auction ledger.
                    if record.get("case_no") or record.get("parcel"):
                        rows.append(record)
    return rows


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(SOURCES_CSV, newline="", encoding="utf-8") as f:
        sources = list(csv.DictReader(f))

    all_rows: list[dict] = []
    for i, src in enumerate(sources, 1):
        county, url = src["County"], src["Url"]
        print(f"[{i}/{len(sources)}] {county}", flush=True)
        try:
            resp = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            resp.raise_for_status()
            rows = extract_rows(resp.content, county, url)
            if rows:
                print(f"      {len(rows)} properties", flush=True)
                all_rows.extend(rows)
            else:
                print("      no properties currently listed", flush=True)
        except Exception as exc:  # noqa: BLE001 - one bad county must not kill the whole run
            print(f"      ERROR: {exc}", flush=True)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, indent=2)

    if all_rows:
        fieldnames = sorted({k for row in all_rows for k in row.keys()})
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_rows)
    else:
        OUT_CSV.write_text("", encoding="utf-8")

    print("")
    print("=" * 50)
    print(f"Harvested {len(all_rows)} LAFT properties total")
    print(f"Counties with matches: {len({r['county'] for r in all_rows})} of {len(sources)} checked")
    print("=" * 50)
    print(f"Saved: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
