#!/usr/bin/env python3
"""
Harvest "Lands Available for Taxes" (LAFT) lists that Florida clerks publish
behind their own tax-deed PORTALS - the platforms none of the other LAFT
harvesters (PDF, static HTML, RealTDM, Pioneer, Orange TDSM, St. Lucie,
Osceola, Hillsborough, Leon) handle. CSV-driven
(data/laft_portal_sources.csv: County, Platform, BaseUrl, Notes), one parser
per platform, so a county found on a platform already handled is a CSV row.

Added 2026-10-26 (owner decision: find every property and every source,
legal review afterwards; interim INTERNAL_RISK_ACCEPTANCE permission records
for `fl_laft_portals` in data/source_permissions.csv). No login, no CAPTCHA,
no paywall; an honest User-Agent; one county at a time.

PLATFORMS
---------
kendo_taxdeed - an ASP.NET MVC "Tax Deed Services" site whose Lands Available
  page (/TaxDeed/Lands) draws a Kendo grid from
  POST /TaxDeed/GetTaxDeedViewByLandsAvailable with the page's own
  anti-forgery token (__RequestVerificationToken) - exactly the request the
  page's own script makes. Response: {"Data": [...], "Total": N, "Errors":
  null}. Fields (read live 2026-10-26, Charlotte): CaseId, CaseNumber,
  CertificateNumber, ParcelId, SaleDate (ISO), Status ('LANDS AVAILABLE'),
  BaseBid, HighBid, Surplus, Applicant, Owners.
    * Rows whose Status is not 'LANDS AVAILABLE' are not Available inventory
      and are dropped (counted).
    * BaseBid is the grid's own "Base Bid" column -> bid_kind OPENING_BID
      (laft_status.AMOUNT_KIND_BY_HEADER['base bid']). HighBid / Surplus are
      the failed auction's leftovers, never a price.
    * Total != rows read (after paging) is PARSE_COUNT_MISMATCH -> INCOMPLETE,
      never COMPLETE: nothing is closed on a partial read.
    * Total 0 with an empty Data list and no Errors is the portal's own
      statement that nothing is listed -> EMPTY.

Output: out/harvest_laft_portals.json / .csv, merged by
sync-laft-to-supabase.ps1 like every other harvest_laft_*.json.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

import laft_status as _LS  # noqa: E402 - permission gate
from laft_status import CategorizedError, StatusRecorder, describe_exception

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_laft_portals.json"
OUT_CSV = OUT_DIR / "harvest_laft_portals.csv"
SOURCES_CSV = HERE / "../data/laft_portal_sources.csv"

SOURCE_ID = "fl_laft_portals"
UA = "taxdeed-scraper/1.0 (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
PAGE_SIZE = 500
MAX_PAGES = 40
POLITE_DELAY_S = 1.0

KENDO_AVAILABLE_STATUS = "LANDS AVAILABLE"
KENDO_BID_KIND = "OPENING_BID"  # the grid's own column title: "Base Bid"
TOKEN_RE = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def _iso_to_mdy(value) -> str | None:
    s = _clean(value)
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "")[:19]).strftime("%m/%d/%Y")
    except ValueError:
        return None


def _money(value) -> str | None:
    if value is None or value == "":
        return None
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- kendo_taxdeed


def kendo_rows(payload, county: str, page_url: str) -> tuple[list[dict], dict]:
    """Rows from one or more merged grid responses. Raises CategorizedError on
    a shape the parser does not recognise (never a silent zero)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("Data"), list) or "Total" not in payload:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "grid response no longer carries {Data: [...], Total: N}")
    if payload.get("Errors"):
        raise CategorizedError("PARSE_FORMAT_CHANGE", "grid response reports Errors")
    out: list[dict] = []
    other_status = 0
    rejected = 0
    for entry in payload["Data"]:
        if not isinstance(entry, dict):
            raise CategorizedError("PARSE_FORMAT_CHANGE", "grid row is not an object")
        if _clean(entry.get("Status")).upper() != KENDO_AVAILABLE_STATUS:
            other_status += 1
            continue
        record: dict = {"county": county, "source": "laft", "url_auction": page_url}
        case_no = _clean(entry.get("CaseNumber"))
        parcel = _clean(entry.get("ParcelId"))
        if case_no:
            record["case_no"] = case_no
        if parcel:
            record["parcel"] = parcel
        cert = _clean(entry.get("CertificateNumber"))
        if cert:
            record["certificate_no"] = cert
        owners = _clean(entry.get("Owners"))
        if owners:
            record["owner_name"] = owners
        sale = _iso_to_mdy(entry.get("SaleDate"))
        if sale:
            record["sale_date"] = sale
        bid = _money(entry.get("BaseBid"))
        if bid is not None and float(bid) > 0:
            record["bid"] = bid
            record["bid_kind"] = KENDO_BID_KIND
        if not _LS.record_identifiers_plausible(record):
            rejected += 1
            continue
        if record.get("case_no") or record.get("parcel"):
            out.append(record)
        else:
            rejected += 1
    meta = {"total": payload.get("Total"), "rows": len(out), "other_status": other_status, "rejected": rejected}
    return out, meta


def harvest_kendo(session: requests.Session, county: str, base_url: str) -> tuple[list[dict], dict, str]:
    base = base_url.rstrip("/")
    page_url = f"{base}/TaxDeed/Lands"
    resp = session.get(page_url, timeout=30)
    resp.raise_for_status()
    m = TOKEN_RE.search(resp.text)
    if not m:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "Lands Available page carries no anti-forgery token")
    token = m.group(1)
    merged: list = []
    total = None
    for page in range(1, MAX_PAGES + 1):
        r = session.post(f"{base}/TaxDeed/GetTaxDeedViewByLandsAvailable",
                         data={"sort": "", "page": page, "pageSize": PAGE_SIZE, "group": "", "filter": "",
                               "__RequestVerificationToken": token},
                         headers={"X-Requested-With": "XMLHttpRequest", "Referer": page_url}, timeout=60)
        r.raise_for_status()
        try:
            payload = r.json()
        except ValueError as exc:
            raise CategorizedError("PARSE_FORMAT_CHANGE", "grid response is not JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("Data"), list):
            raise CategorizedError("PARSE_FORMAT_CHANGE", "grid response no longer carries {Data: [...]}")
        total = payload.get("Total")
        merged.extend(payload["Data"])
        if not payload["Data"] or not isinstance(total, int) or len(merged) >= total:
            break
        time.sleep(POLITE_DELAY_S)
    rows, meta = kendo_rows({"Data": merged, "Total": total, "Errors": None}, county, page_url)
    meta["read"] = len(merged)
    return rows, meta, page_url


PLATFORMS = {"kendo_taxdeed": harvest_kendo}


def classify(meta: dict) -> tuple[str, str | None]:
    """COMPLETE / EMPTY / INCOMPLETE for one county's read."""
    total, read = meta.get("total"), meta.get("read")
    if not isinstance(total, int):
        return "INCOMPLETE", "PARSE_FORMAT_CHANGE"
    if read != total:
        return "INCOMPLETE", "PARSE_COUNT_MISMATCH"
    if total == 0:
        return "EMPTY", None
    if meta.get("rows", 0) == 0 and meta.get("rejected", 0) > 0:
        return "INCOMPLETE", "PARSE_FORMAT_CHANGE"
    return ("COMPLETE", None) if meta.get("rows", 0) > 0 else ("EMPTY", None)


def main() -> int:
    # Source permission (2026-10-26, owner decision): no recorded fetch/parse
    # permission for fl_laft_portals -> 0 requests, exit 3.
    _denied = _LS.permission_gate(SOURCE_ID)
    if _denied:
        return _denied
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(SOURCES_CSV, newline="", encoding="utf-8") as f:
        sources = list(csv.DictReader(f))
    recorder = StatusRecorder(SOURCE_ID, source_class="GOVERNMENT_PLATFORM")
    session = requests.Session()
    session.headers["User-Agent"] = UA
    all_rows: list[dict] = []
    for i, src in enumerate(sources, 1):
        county, platform, base = src["County"], src["Platform"], src["BaseUrl"]
        print(f"[{i}/{len(sources)}] {county} ({platform})", flush=True)
        fn = PLATFORMS.get(platform)
        if fn is None:
            recorder.failed(county, "PARSE_FORMAT_CHANGE", f"unknown platform {platform!r}", source_url=base)
            continue
        try:
            rows, meta, page_url = fn(session, county, base)
        except Exception as exc:  # noqa: BLE001 - categorised, never a silent zero
            category, _detail = describe_exception(exc)
            print(f"    ERROR ({category}): {exc}", flush=True)
            recorder.failed(county, exc, source_url=base)
            continue
        status, category = classify(meta)
        print(f"    platform total {meta.get('total')}, read {meta.get('read')}, available rows {meta.get('rows')}, "
              f"other status {meta.get('other_status')}, rejected {meta.get('rejected')} -> {status}", flush=True)
        if status == "COMPLETE":
            recorder.complete(county, len(rows), source_url=page_url)
            all_rows.extend(rows)
        elif status == "EMPTY":
            recorder.empty(county, "empty_list", source_url=page_url)
        else:
            recorder.incomplete(county, category, f"read {meta.get('read')} of {meta.get('total')}",
                                row_count=len(rows), source_url=page_url)
            all_rows.extend(rows)
        time.sleep(POLITE_DELAY_S)
    recorder.write()
    print(recorder.summary_line(), flush=True)

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
    print(f"Harvested {len(all_rows)} LAFT properties from {len(sources)} portal county(ies)")
    print(f"Saved: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
