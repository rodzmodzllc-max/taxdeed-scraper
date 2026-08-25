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
custom ASP.NET disclaimer-postback, or a JS "report" app (Miami-Dade's
GovHub). Those need portal/form automation, not a simple GET+parse, and are
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

Send a full, browser-realistic header set (not just User-Agent) on every
request - confirmed live 2026-08: 3 of these 18 counties (Escambia,
Columbia, Union) returned a 403 with only a User-Agent header set, despite
the exact same page loading fine in an ordinary browser and currently
having real (or legitimately empty) content - i.e. not a dead link, a
request-shape block. See BROWSER_HEADERS below.

CONFIRMED LIVE 2026-08-25 (workflow run #46): the fuller header set did
NOT fix Escambia/Columbia/Union - all three still 403 with it. Since the
same pages load fine from an ordinary (non-datacenter) IP, this points to
an IP-range block on GitHub Actions' runner IPs rather than anything
request-shape related, which no header change can fix. Left in place
anyway (harmless, and it may still help other counties or future WAF
configs) but do not assume this closes the gap for those three without
checking the next run's log.

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

# A bare User-Agent header is enough for 15 of these 18 counties, but 3
# (Escambia, Columbia, Union - confirmed live 2026-08) return a 403 with
# just that, from what looks like basic WAF/bot-detection gating on a
# thin, non-browser-realistic header set rather than blocking the UA
# string itself (both sites load fine, with real/legitimately-empty
# content, when opened in an actual browser). Sending the same header set
# a real browser sends is the standard fix for this class of block and is
# harmless for every county that was already working with UA alone.
# CONFIRMED LIVE 2026-08-25: it did NOT actually fix those three (still
# 403 - see the module docstring) but is left in place as a harmless,
# still-plausibly-correct improvement.
#
# Accept-Encoding deliberately omits "br" (Brotli) - confirmed live
# 2026-08-25: advertising it caused several counties (Sumter, Dixie,
# Franklin, Gulf, Holmes, Lafayette) to come back with "Some characters
# could not be decoded, and were replaced with REPLACEMENT CHARACTER."
# The `requests` library only auto-decompresses Brotli if the optional
# `brotli`/`brotlicffi` package is installed, which it isn't here - so a
# server that takes the hint and actually sends Brotli-encoded content
# gets silently mangled into garbage bytes on this end. Every one of those
# six counties happened to still resolve to "no properties currently
# listed" this run because looks_empty() apparently still matched through
# the corruption, but that's luck, not a guarantee for a real, non-empty
# row - so this stays gzip/deflate only, which `requests` decodes
# natively and no county has ever failed on.
BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

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

# Putnam publishes real, current LAFT data (confirmed live 2026-08, 38
# properties) but not as a column-oriented table at all - it's a layout
# table where each property spans two rows: a 2-cell row ("T.D. <case>" /
# owner name) followed by a 3-cell row cramming links, legal description +
# parcel, and the three dates/price together into single cells. The
# header-row-by-content scan above finds nothing here (there's no row where
# multiple cells match a known column name - every cell is a paragraph of
# mixed text), so without this fallback Putnam would silently report 0
# properties despite having real, valuable data. Written as a structural
# pattern match (any table with "T.D. <case>" 2-cell rows), not a
# county-name check, so it applies automatically if another county turns
# out to share the same template.
_TD_CASE_RE = re.compile(r"^T\.D\.\s*(\S+)")
_PARCEL_SPLIT_RE = re.compile(r"Parcel Number\s*([\w.\-]+)", re.IGNORECASE)
_AUCTION_DATE_RE = re.compile(r"Auction date:\s*([\d/]+)", re.IGNORECASE)
_AVAILABLE_DATE_RE = re.compile(r"Available for Purchase:\s*([\d/]+)", re.IGNORECASE)
_PRICE_RE = re.compile(r"Estimated Purchase Price:\s*\$?([\d,]+\.\d{2})", re.IGNORECASE)

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

def _rows_from_card_table(rows: list[list[str]], county: str, source_url: str) -> list[dict]:
    """See the _TD_CASE_RE comment above - fallback for Putnam-style "two
    rows per property, no header" tables. Scans for a 2-cell row starting
    with "T.D. <case>" followed by a 3-cell detail row, and pulls fields out
    of the crammed-together cell text with the same labeled-field regexes
    the PDF harvester's extract_label_value_rows() uses for Marion."""
    out: list[dict] = []
    i = 0
    while i < len(rows):
        row = rows[i]
        if len(row) == 2:
            m = _TD_CASE_RE.match(row[0].strip())
            if m and i + 1 < len(rows) and len(rows[i + 1]) == 3:
                case_no = m.group(1)
                owner_name = row[1].strip()
                detail = rows[i + 1]
                legal_and_parcel = detail[1]
                parcel_m = _PARCEL_SPLIT_RE.search(legal_and_parcel)
                legal_desc = (legal_and_parcel[:parcel_m.start()] if parcel_m else legal_and_parcel).strip()
                dates_price = detail[2]
                auction_m = _AUCTION_DATE_RE.search(dates_price)
                avail_m = _AVAILABLE_DATE_RE.search(dates_price)
                price_m = _PRICE_RE.search(dates_price)

                record: dict = {
                    "county": county, "source": "laft", "url_auction": source_url,
                    "case_no": case_no,
                }
                if owner_name:
                    record["owner_name"] = owner_name
                if legal_desc:
                    record["legal_desc"] = legal_desc
                if parcel_m:
                    record["parcel"] = parcel_m.group(1)
                if auction_m:
                    record["sale_date"] = auction_m.group(1)
                if avail_m:
                    # Not one of the standard fields sync-laft-to-supabase.ps1
                    # reads - kept in the JSON/CSV artifact for visibility
                    # (when the property actually becomes purchasable) even
                    # though it isn't synced to Supabase today.
                    record["available_date"] = avail_m.group(1)
                if price_m:
                    record["bid"] = price_m.group(1)
                out.append(finalize_record(record))
                i += 2
                continue
        i += 1
    return out

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
        # No table had a real header row - try the card-style fallback
        # (Putnam) before giving up entirely.
        for table in soup.find_all("table"):
            rows = _table_to_rows(table)
            card_rows = _rows_from_card_table(rows, county, source_url)
            if card_rows:
                return [r for r in card_rows if not r.get("sold_to")]
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
            resp = requests.get(url, headers=BROWSER_HEADERS, timeout=30)
            resp.raise_for_status()
            rows = extract_rows(resp.content, county, url)
            if rows:
                print(f"  {len(rows)} properties", flush=True)
                all_rows.extend(rows)
            else:
                print("  no properties currently listed", flush=True)
        except Exception as exc:  # noqa: BLE001 - one bad county must not kill the whole run
            print(f"  ERROR: {exc}", flush=True)

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
