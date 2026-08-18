#!/usr/bin/env python3
"""
Harvest "Lands Available for Taxes" (LAFT) lists published as real, static
HTML tables directly on the county Clerk's own site - no PDF download, no
login, no search form required.

Companion to harvest_laft_pdfs.py, which covers the PDF-published counties.
This one covers the counties a fresh 2026-08 research pass confirmed publish
a real table embedded in the page HTML. See ../data/laft_html_sources.csv
for the confirmed-live list (one row per county, URL + notes) - adding a
county here is a CSV edit, not a code change, same convention as the PDF
harvester.

That research pass checked 26 of Florida's larger/higher-volume counties.
(harvest_laft_pdfs.py's docstring cites an earlier "~20 counties confirmed
HTML table" estimate from an audit spreadsheet - that file no longer exists
anywhere in this project, so its findings couldn't be verified or reused.
This is a from-scratch replacement pass, and it came back far more
conservative: of the 26 counties actually fetched and read, only 4 turned
out to be real static HTML tables. Most large counties gate the list behind
a search portal instead - RealTDM/Realauction case search, Landmark Web, a
custom ASP.NET disclaimer-postback (clerk.org's app02 "Accept" gate, used by
both Volusia and Charlotte), or a JS "report" app (Miami-Dade's GovHub).
Those need portal/form automation, not a simple GET+parse, and are
deliberately NOT handled by this script - see the commit this shipped in
for the full county-by-county writeup.)

Like the PDF harvester: never fabricate a value. If a county's table
doesn't publish a field, leave it null rather than guess. Indian River's
page explicitly warns the listed price is stale and buyers must call the
Tax Collector for the real current price - that disclaimer is preserved
verbatim (see NOTES_BY_COUNTY below) rather than silently dropped.

Uses the same "find the header row by content, not position" approach the
PDF harvester already uses for Hendry's buried header, adapted to HTML:
scans every <table> on the page (not just the first) and scores each row by
how many cells match a known column name, since several of these sites bury
the real data table inside old nested-table page layouts (confirmed live on
Escambia - 6+ decorative tables before the real one) or serve it from an
embedded iframe on a completely different subdomain than the page a person
would actually load (confirmed on Leon - leonclerk.com is just a wrapper;
the real table lives at lforms.leonclerk.com and is what's in the CSV).

Output: harvest_laft_html.json / .csv - kept separate from
harvest_laft.json (the PDF harvester's own output) so this never has to
touch that script. sync-laft-to-supabase.ps1 reads both.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
SOURCES_CSV = HERE / "../data/laft_html_sources.csv"
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_laft_html.json"
OUT_CSV = OUT_DIR / "harvest_laft_html.csv"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Confirmed live 2026-08 (see laft_html_sources.csv Notes column for detail
# per county) - preserved verbatim on every row from that county rather than
# silently dropped, since it changes whether the published `bid` can be
# trusted at all.
NOTES_BY_COUNTY = {
    "Indian River": "Amounts listed are no longer the real opening bid per the county's own page - contact the Tax Collector (772-226-1338) for the current purchase price before relying on `bid` here.",
}

# Column-header aliases -> normalized field name. Matched case-insensitively
# after stripping whitespace/punctuation (see normalize_header). Deliberately
# generous with aliases so a new county added to the CSV later has a decent
# chance of working without a code change - add new aliases here, don't
# special-case a county by name in the parsing logic itself.
HEADER_MAP = {
    "case number": "case_no", "case #": "case_no", "case no": "case_no",
    "case number date": "case_no",  # Manatee: "Case Number / Date" (slash stripped)
    "sale #": "case_no", "sale number": "case_no",
    "file no.": "case_no", "file no": "case_no", "file number": "case_no",
    "clerks filenumber": "case_no",  # Escambia: "Clerk's FileNumber" (apostrophe stripped)
    "tax deed #": "case_no", "tax deed number": "case_no",
    "certificate #": "certificate_no", "certificate number": "certificate_no",
    "cert. no": "certificate_no", "cert no": "certificate_no", "cert. no.": "certificate_no",
    "certificate": "certificate_no", "tax certificate #": "certificate_no",
    "certification number": "certificate_no",  # Leon
    "parcel id": "parcel", "parcel #": "parcel", "parcel number": "parcel",
    "parcel identification number": "parcel",
    "owner": "owner_name", "owners": "owner_name", "owner(s)": "owner_name",
    "name in which assessed": "owner_name",
    "auction date": "sale_date", "sale date": "sale_date", "sales date": "sale_date",
    "original sale date": "sale_date", "tax deed sale date": "sale_date",
    "date of tax deed sale": "sale_date",
    "escheatment date": "escheatment_date", "expiration date": "escheatment_date",
    "amount to purchase": "bid", "opening bid": "bid", "minimum bid": "bid",
    "original opening bid": "bid", "purchase price": "bid", "price": "bid",
    "initial bid": "bid", "opening bid amount": "bid",
    "assessed value": "assessed", "property address": "address", "address": "address",
    "taxes address": "address", "legal address": "address",
    "legal description": "legal_desc", "description": "legal_desc",
    "description of property": "legal_desc",
    "homestead": "homestead",
    # If this column has a value, the property has already been sold and is
    # no longer available - same convention as the PDF harvester's Hendry fix.
    "sold to": "sold_to", "sold": "sold_to", "purchaser": "sold_to",
}

EMPTY_MARKERS = (
    "no available lands", "no properties at this time", "no properties available",
    "no parcels available", "there are no properties", "nothing available",
    "no lands available",
)


def normalize_header(h: str) -> str | None:
    if not h:
        return None
    key = re.sub(r"[^a-z0-9()#. ]", "", h.strip().lower())
    key = re.sub(r"\s+", " ", key).strip()
    return HEADER_MAP.get(key)


def normalize_parcel(p: str) -> str:
    return re.sub(r"\s+", "", p.strip()).upper()


def canonical_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def finalize_record(record: dict) -> dict:
    if record.get("parcel"):
        record["parcel"] = normalize_parcel(record["parcel"])
    if not record.get("case_no") and record.get("parcel"):
        record["case_no"] = canonical_key(record["parcel"])
    return record


def looks_empty(text: str) -> bool:
    low = re.sub(r"\s+", " ", text.lower())
    return any(marker in low for marker in EMPTY_MARKERS)


def _find_header_row(rows: list[list[str]]) -> tuple[int, list] | None:
    """Same discipline as the PDF harvester's _find_header_row: can't assume
    the header is row 0, and require at least 2 real field matches so a
    coincidental single match (a stray "Description" in body text) doesn't
    get mistaken for a real header."""
    best_idx, best_fields, best_score = None, None, 1
    for idx, row in enumerate(rows):
        fields = [normalize_header(c) for c in row]
        score = sum(1 for f in fields if f)
        if score > best_score:
            best_idx, best_fields, best_score = idx, fields, score
    if best_idx is None:
        return None
    return best_idx, best_fields


def _table_to_rows(table) -> list[list[str]]:
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        if cells:
            rows.append([c.get_text(strip=True) for c in cells])
    return rows


def extract_rows(html: bytes, county: str, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text(" ", strip=True)
    if looks_empty(page_text):
        return []

    best: tuple[int, list, list[list[str]]] | None = None
    best_score = 1
    for table in soup.find_all("table"):
        rows = _table_to_rows(table)
        if len(rows) < 2:
            continue
        found = _find_header_row(rows)
        if not found:
            continue
        header_idx, field_names = found
        score = sum(1 for f in field_names if f)
        if score > best_score:
            best_score = score
            best = (header_idx, field_names, rows)

    if not best:
        return []
    header_idx, field_names, rows = best
    body = rows[header_idx + 1:]

    note = NOTES_BY_COUNTY.get(county)
    out: list[dict] = []
    for raw in body:
        cell_texts = [c.strip() for c in raw if c and c.strip()]
        if not cell_texts:
            continue
        if all(looks_empty(c) for c in cell_texts):
            continue

        record: dict = {"county": county, "source": "laft", "url_auction": source_url}
        if note:
            record["notes"] = note
        for i, field in enumerate(field_names):
            if not field or i >= len(raw):
                continue
            val = raw[i].strip()
            if val:
                record[field] = val
        if record.get("sold_to"):
            continue
        if record.get("case_no") or record.get("parcel"):
            out.append(finalize_record(record))
    return out


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
