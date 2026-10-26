#!/usr/bin/env python3
"""Sarasota County Tax Collector: county-held tax certificates (2026-10-26).

WHY

LienHub (Grant Street Group) has answered every GitHub runner with HTTP 403
since 2026-10-01, so the certificate job reads no Florida county. That block
is never worked around. Sarasota is one of the 32 LienHub counties, and its
Tax Collector ALSO publishes the county-held certificate list on its own site:

    https://www.sarasotataxcollector.gov/services/tax-services/property-tax/tax-cert-sale
      "County-Held Certificates for Purchase" -> /files/docs/CountyHeldCertificates.pdf

(read 2026-10-26: a five-page table headed "<year> CERTIFICATES" with
ACCOUNT / CERT YEAR / CERT# / ASSESSED VALUE / FACE AMOUNT / INTEREST /
TAX YEAR / a 4.50% column / a fee column / PURCHASE PRICE). This reader takes
that list - the same scope as LienHub's county-held list - from the county's
own page. Survey of the other LienHub counties:
docs/review/fl-certificate-sources-2026-10-26.md.

PERMISSION

fetch / parse / store records for `fl_sarasota_tc_certificates` in
data/source_permissions.csv are the owner's interim risk acceptance
(decision 2026-10-26, expiring 2027-04-12, `excluded_from_paid_tier`), never
the Tax Collector's permission. No display record exists. Checked before any
request; a denial exits 3 with zero requests.

WHAT IS MAPPED (to the row shape sync-certificates-to-supabase.ps1 reads)

  ACCOUNT        -> case_no and parcel (LienHub's Sarasota rows carry the same
                    10-digit account as case_no, so a row lands on the same
                    stored identity)
  CERT#          -> certificate_no
  TAX YEAR       -> tax_year
  ASSESSED VALUE -> assessed
  INTEREST       -> interest_rate
  PURCHASE PRICE -> bid (the price the Tax Collector publishes for buying the
                    county-held certificate)
  CERT YEAR, FACE AMOUNT and the two charge columns are not mapped. No owner,
  address or issue date is published, so none is stored.

STATUS (out/harvest_sarasota_certificates_status.json, the LienHub status-file
shape plus source_id)

  COMPLETE    the page linked the PDF, its header was recognised and every
              data row passed the identifier gate
  INCOMPLETE  rows were read but at least one failed the gate, or no row at
              all was read (a zero is never EMPTY: the PDF states no empty
              marker)
  FAILED      transport, a missing link, or an unrecognised header

Prints counts and statuses only - never a row value.

    harvest_sarasota_certificates.py                 # live read
    harvest_sarasota_certificates.py --fixture F.pdf # no network
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import laft_status as LS  # noqa: E402

SOURCE_ID = "fl_sarasota_tc_certificates"
DATASET = "county_held_certificates"
COUNTY = "Sarasota"
PAGE_URL = "https://www.sarasotataxcollector.gov/services/tax-services/property-tax/tax-cert-sale"
LINK_TEXT = re.compile(r"county[-\s]held\s+certificates\s+for\s+purchase", re.I)
LINK_HREF = re.compile(r"CountyHeldCertificates[^\"'/]*\.pdf$", re.I)
UA = "taxdeed-scraper/1.0 (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
OUT = REPO / "out" / "harvest_certificates_sarasota.json"
STATUS = REPO / "out" / "harvest_sarasota_certificates_status.json"

# Header cell (normalised: upper case, spaces collapsed) -> output role. The
# PDF's text layer interleaves two header cells ("ASSESSED VAFLAUCEE AMOUNT"),
# so the table reader's cells are matched by prefix, never by position.
HEADERS = {
    "account": ("ACCOUNT",),
    "cert_year": ("CERT YEAR",),
    "cert_no": ("CERT#", "CERT #", "CERT NO"),
    "assessed": ("ASSESSED",),
    "interest": ("INTEREST",),
    "tax_year": ("TAX YEAR",),
    "price": ("PURCHASE PRICE",),
}
REQUIRED = ("account", "cert_no", "tax_year", "price")
ACCOUNT_RE = re.compile(r"^\d{10}$")
CERT_RE = re.compile(r"^\d{1,8}$")
YEAR_RE = re.compile(r"^(19|20)\d\d$")


def _norm(cell) -> str:
    return re.sub(r"\s+", " ", str(cell or "")).strip().upper()


def _money(cell) -> float | None:
    s = re.sub(r"[$,\s]", "", str(cell or ""))
    return float(s) if re.fullmatch(r"\d+(\.\d+)?", s) else None


def header_map(row) -> dict[str, int] | None:
    """role -> column index, or None when this row is not the header."""
    cells = [_norm(c) for c in row]
    out: dict[str, int] = {}
    for role, prefixes in HEADERS.items():
        for i, c in enumerate(cells):
            if any(c.startswith(p) for p in prefixes) and i not in out.values():
                out[role] = i
                break
    return out if all(r in out for r in REQUIRED) else None


def parse_tables(tables: list[list[list]]) -> tuple[list[dict], dict]:
    """Rows of every page's table -> (records, counts). The header is found on
    each page (the PDF repeats it, or not); a page with no header reuses the
    last one seen."""
    records: list[dict] = []
    counts = {"rows": 0, "rejected": 0, "header_pages": 0}
    hm = None
    for table in tables:
        for row in table or []:
            h = header_map(row)
            if h:
                hm = h
                counts["header_pages"] += 1
                continue
            if hm is None or not any(_norm(c) for c in row):
                continue
            get = lambda role: (row[hm[role]] if role in hm and hm[role] < len(row) else None)  # noqa: E731
            # Page furniture (the "<year> CERTIFICATES" title the table reader
            # folds into a row): no digit in any identifier or price cell.
            if not any(re.search(r"\d", _norm(get(r))) for r in ("account", "cert_no", "price")):
                counts["furniture"] = counts.get("furniture", 0) + 1
                continue
            counts["rows"] += 1
            account = _norm(get("account"))
            cert = _norm(get("cert_no"))
            year = _norm(get("tax_year"))
            price = _money(get("price"))
            if not (ACCOUNT_RE.match(account) and CERT_RE.match(cert) and YEAR_RE.match(year) and price is not None):
                counts["rejected"] += 1
                continue
            rate = _money(get("interest"))
            records.append({
                "county": COUNTY,
                "case_no": account,
                "parcel": account,
                "certificate_no": cert,
                "tax_year": year,
                "issued_date": None,
                "expiration_date": None,
                "bid": price,
                "assessed": _money(get("assessed")),
                "interest_rate": rate,
                "owner_name": None,
                "address": None,
                "url_auction": PAGE_URL,
                "source_id": SOURCE_ID,
            })
    return records, counts


def read_pdf_tables(data: bytes) -> tuple[list[list[list]], str]:
    import io
    import pdfplumber
    tables, text = [], ""
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for i, page in enumerate(pdf.pages):
            if i == 0:
                text = page.extract_text() or ""
            for t in page.extract_tables() or []:
                tables.append(t)
    return tables, text


def list_year(first_page_text: str) -> str | None:
    m = re.search(r"\b((?:19|20)\d\d)\s+CERTIFICATES\b", first_page_text or "", re.I)
    return m.group(1) if m else None


def find_pdf_link(html: str, base: str) -> str | None:
    """The PDF the page itself links as the county-held list; never built."""
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
        href, text = m.group(1), re.sub(r"<[^>]+>|\s+", " ", m.group(2)).strip()
        if LINK_TEXT.search(text) or LINK_HREF.search(href):
            url = urljoin(base, href)
            if url.startswith("https://"):
                return url
    return None


def status_entry(status: str, rows: int, reason: str, **extra) -> dict:
    e = {"county": COUNTY, "status": status, "rowCount": rows, "source_id": SOURCE_ID, "reason": reason,
         "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    e.update({k: v for k, v in extra.items() if v is not None})
    return e


def evaluate(records: list[dict], counts: dict) -> dict:
    if counts["header_pages"] == 0:
        return status_entry("FAILED", 0, "the county-held list's header was not recognised", error_category="PARSE_FORMAT_CHANGE")
    if counts["rows"] == 0:
        return status_entry("INCOMPLETE", 0, "header recognised, no data row - the PDF states no empty marker",
                            error_category="UNCONFIRMED_EMPTY")
    if counts["rejected"]:
        return status_entry("INCOMPLETE", len(records), f"{counts['rejected']} of {counts['rows']} rows failed the identifier gate",
                            error_category="PARSE_FORMAT_CHANGE")
    return status_entry("COMPLETE", len(records), "every data row of the county-held list read")


def write_outputs(records: list[dict], entry: dict) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(records, indent=1), encoding="utf-8")
    STATUS.write_text(json.dumps([entry], indent=1), encoding="utf-8")


def report(records: list[dict], counts: dict, entry: dict, year: str | None) -> None:
    years = sorted({r["tax_year"] for r in records})
    print(f"{SOURCE_ID}: {entry['status']} - {len(records)} certificate(s) kept, {counts['rejected']} rejected, "
          f"{counts['rows']} data row(s), header on {counts['header_pages']} page(s); list year {year or 'not stated'}; "
          f"tax years {', '.join(years) or 'none'}; distinct accounts {len({r['case_no'] for r in records})}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixture", help="read this PDF instead of the network")
    a = ap.parse_args(argv)
    for op in ("fetch", "parse", "store"):
        # Source "fl_sarasota_tc_certificates" (named here for the interim-permission call-site inventory).
        d = LS.permission(SOURCE_ID, op, state="FL", county=COUNTY, dataset=DATASET)
        if not d.allowed:
            print(f"::error title={SOURCE_ID}::{op} denied [{d.reason_code}] - 0 requests made, nothing written", flush=True)
            return LS.PERMISSION_DENIED_EXIT
    if a.fixture:
        data = Path(a.fixture).read_bytes()
    else:
        import requests
        try:
            page = requests.get(PAGE_URL, headers={"User-Agent": UA}, timeout=30)
            page.raise_for_status()
            link = find_pdf_link(page.text, page.url)
            if not link:
                entry = status_entry("FAILED", 0, "the page no longer links the county-held list", error_category="SOURCE_LINK_MISSING")
                write_outputs([], entry)
                print(f"{SOURCE_ID}: FAILED - the county page links no county-held PDF")
                return 0
            pdf = requests.get(link, headers={"User-Agent": UA, "Referer": page.url}, timeout=60)
            pdf.raise_for_status()
            data = pdf.content
        except Exception as exc:  # noqa: BLE001 - transport: recorded, never retried into another path
            cat, detail = LS.describe_exception(exc)
            write_outputs([], status_entry("FAILED", 0, detail, error_category=cat))
            print(f"{SOURCE_ID}: FAILED - {detail}")
            return 0
    try:
        tables, text = read_pdf_tables(data)
    except Exception as exc:  # noqa: BLE001
        write_outputs([], status_entry("FAILED", 0, type(exc).__name__, error_category="PARSE_UNREADABLE_DOCUMENT"))
        print(f"{SOURCE_ID}: FAILED - the document could not be read ({type(exc).__name__})")
        return 0
    records, counts = parse_tables(tables)
    year = list_year(text)
    entry = evaluate(records, counts)
    if year:
        entry["list_as_of_year"] = year
    write_outputs(records, entry)
    report(records, counts, entry, year)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
