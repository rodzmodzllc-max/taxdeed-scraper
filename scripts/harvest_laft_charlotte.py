#!/usr/bin/env python3
"""
Harvest "Lands Available for Taxes" (LAFT) for Charlotte County from the
Clerk's own tax-deed site, https://taxdeeds.charlotteclerk.com/TaxDeed/Lands.

Added 2026-10-25 (Florida sources batch - docs/sources-batch-2026-10-25-florida.md).
GATED: source id `fl_laft_charlotte`, wired into NO workflow and NOT read by
sync-laft-to-supabase.ps1. Its registry row is MANUAL_REVIEW_REQUIRED /
UNREVIEWED (never runnable by harvesters/otc/gate.py); the permission records
(data/source_permissions.csv) are an internal risk acceptance for fetch /
parse / store only, excluded from the paid tier - not the Clerk's permission.

WHAT THE PAGE IS (read live 2026-10-25, structure and counts only): the page
HTML has no data rows. It is an ASP.NET MVC page whose Kendo UI grid
(`#gridTaxCase`) loads its rows by POSTing to
`/TaxDeed/GetTaxDeedViewByLandsAvailable` (the grid's own `transport.read`,
type `aspnetmvc-ajax`) with the page's anti-forgery token
(`__RequestVerificationToken`, a hidden input on the page). The response is
`{"Data": [...], "Total": N, "AggregateResults": ..., "Errors": ...}`;
each row carries Applicant, CaseNumber, CertificateNumber, ParcelId,
SaleDate (ISO datetime), Status, BaseBid, HighBid, Surplus, Owners, CaseId.
On 2026-10-25 the endpoint reported Total 4 and returned 4 rows, every one
with Status "LANDS AVAILABLE". Same category of fix as Leon's
listoflands.txt: read the data source the page's own script reads.

MAPPED: CaseNumber -> case_no, CertificateNumber -> certificate_no,
ParcelId -> parcel (whitespace removed), SaleDate -> sale_date (MM/DD/YYYY,
the date part as written), BaseBid -> bid (> 0 only; bid_kind OPENING_BID,
laft_status.AMOUNT_KIND_BY_HEADER["base bid"] - statutory additions apply,
data/available_financial_terms.csv). NEVER MAPPED: Owners (owner names),
Applicant (the certificate holder who applied), HighBid / Surplus (a
property-sale result is never inferred from a lands-available case), CaseId
(an internal grid key).

STATUS (scripts/laft_status.py rules):
  COMPLETE    at least one LANDS AVAILABLE row parsed and len(Data) == Total
  EMPTY       the endpoint itself reported Total 0 with an empty Data list
              and no Errors (empty_signal "reported_count_zero")
  INCOMPLETE  Total != rows collected (PARSE_COUNT_MISMATCH), every row
              rejected by the identifier gate, or a non-LANDS AVAILABLE
              status only (rows parsed are still emitted)
  FAILED      transport error, missing token, non-JSON / unrecognised shape

Logs carry counts, statuses and error categories only - never a case,
parcel, owner, applicant or amount.

Run:
  python3 scripts/harvest_laft_charlotte.py                 # live (gated)
  python3 scripts/harvest_laft_charlotte.py --fixture F.json # no network
Output: out/harvest_laft_charlotte.json; status entry merged into
out/harvest_laft_status.json (harvester fl_laft_charlotte).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests

import laft_status as _LS  # noqa: E402 - permission gate
from laft_status import CategorizedError, StatusRecorder, describe_exception, record_identifiers_plausible

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_laft_charlotte.json"

SOURCE_ID = "fl_laft_charlotte"
COUNTY = "Charlotte"
BASE = "https://taxdeeds.charlotteclerk.com"
PAGE_URL = BASE + "/TaxDeed/Lands"
DATA_URL = BASE + "/TaxDeed/GetTaxDeedViewByLandsAvailable"
PAGE_SIZE = 500
MAX_PAGES = 20

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}

OFFERED_STATUS = "LANDS AVAILABLE"
REQUIRED_FIELDS = ("CaseNumber", "ParcelId", "Status")
BID_KIND = "OPENING_BID"  # the grid's own column title: "Base Bid"

_TOKEN_RE = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')
_TOKEN_RE_ALT = re.compile(r'value="([^"]+)"[^>]*name="__RequestVerificationToken"')


def _clean(value) -> str:
    return "" if value is None else str(value).strip()


def find_token(html: str) -> str:
    m = _TOKEN_RE.search(html) or _TOKEN_RE_ALT.search(html)
    if not m:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "the Lands page no longer carries an anti-forgery token")
    return m.group(1)


def _sale_date(value) -> str | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%m/%d/%Y")
    except ValueError:
        return None


def check_envelope(payload) -> tuple[list, int]:
    """(Data, Total) from the Kendo envelope; anything else is a format change."""
    if not isinstance(payload, dict) or not isinstance(payload.get("Data"), list) or not isinstance(payload.get("Total"), int):
        raise CategorizedError("PARSE_FORMAT_CHANGE", "response is not a Kendo {Data: [...], Total: n} envelope")
    if payload.get("Errors"):
        raise CategorizedError("PARSE_FORMAT_CHANGE", "the endpoint reported Errors")
    return payload["Data"], payload["Total"]


def parse_rows(data: list) -> tuple[list[dict], dict]:
    """(records, outcome) from the endpoint's Data list."""
    outcome = {"rejected": 0, "other_status": 0, "missing_fields": 0}
    out: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict) or any(f not in entry for f in REQUIRED_FIELDS):
            outcome["missing_fields"] += 1
            continue
        if _clean(entry.get("Status")).upper() != OFFERED_STATUS:
            outcome["other_status"] += 1
            continue
        record: dict = {"county": COUNTY, "source": "laft", "url_auction": PAGE_URL}
        case_no = _clean(entry.get("CaseNumber"))
        parcel = re.sub(r"\s+", "", _clean(entry.get("ParcelId"))).upper()
        cert = _clean(entry.get("CertificateNumber"))
        if case_no:
            record["case_no"] = case_no
        if parcel:
            record["parcel"] = parcel
        if cert:
            record["certificate_no"] = cert
        sale = _sale_date(entry.get("SaleDate"))
        if sale:
            record["sale_date"] = sale
        bid = entry.get("BaseBid")
        if isinstance(bid, (int, float)) and not isinstance(bid, bool) and bid > 0:
            record["bid"] = f"{bid:.2f}"
            record["bid_kind"] = BID_KIND
        if not (record.get("case_no") or record.get("parcel")) or not record_identifiers_plausible(record):
            outcome["rejected"] += 1
            continue
        out.append(record)
    return out, outcome


def classify(records: list[dict], outcome: dict, total: int, collected: int) -> tuple[str, str | None, str | None]:
    """(status, signal_or_category, reason)."""
    if collected != total:
        return "INCOMPLETE", "PARSE_COUNT_MISMATCH", f"endpoint reported {total}, {collected} returned"
    if total == 0:
        return "EMPTY", "reported_count_zero", None
    if outcome.get("missing_fields"):
        return "INCOMPLETE", "PARSE_FORMAT_CHANGE", f"{outcome['missing_fields']} row(s) missing a required field"
    if not records:
        if outcome.get("rejected"):
            return "INCOMPLETE", "PARSE_FORMAT_CHANGE", "every row failed the identifier plausibility gate"
        return "INCOMPLETE", "UNCONFIRMED_EMPTY", "no row carries the LANDS AVAILABLE status"
    return "COMPLETE", None, None


def fetch_all(session: requests.Session) -> tuple[list, int]:
    page = session.get(PAGE_URL, headers=HEADERS, timeout=30)
    page.raise_for_status()
    token = find_token(page.text)
    data: list = []
    total = None
    for n in range(1, MAX_PAGES + 1):
        resp = session.post(DATA_URL, timeout=30,
                            data={"sort": "", "page": str(n), "pageSize": str(PAGE_SIZE), "group": "", "filter": "",
                                  "__RequestVerificationToken": token},
                            headers={**HEADERS, "Accept": "application/json, text/javascript, */*; q=0.01",
                                     "X-Requested-With": "XMLHttpRequest", "Referer": PAGE_URL})
        resp.raise_for_status()
        try:
            payload = resp.json()
        except ValueError as exc:
            raise CategorizedError("PARSE_FORMAT_CHANGE", "endpoint did not return JSON") from exc
        rows, page_total = check_envelope(payload)
        total = page_total if total is None else total
        data.extend(rows)
        if not rows or len(data) >= total:
            break
    return data, int(total or 0)


def run(payload_pages: list | None = None, *, recorder: StatusRecorder | None = None) -> list[dict]:
    """Read (live, or from fixture payloads), record the county status and
    return the records. A fixture is a list of Kendo envelopes (pages)."""
    recorder = recorder or StatusRecorder(SOURCE_ID, source_class="GOVERNMENT_DIRECT", source_id=SOURCE_ID)
    kw = dict(source_url=PAGE_URL, document_url=DATA_URL)
    try:
        if payload_pages is None:
            data, total = fetch_all(requests.Session())
        else:
            data, total = [], None
            for p in payload_pages:
                rows, t = check_envelope(p)
                total = t if total is None else total
                data.extend(rows)
            total = int(total or 0)
        records, outcome = parse_rows(data)
        status, sig, reason = classify(records, outcome, total, len(data))
        if status == "COMPLETE":
            recorder.complete(COUNTY, len(records), **kw)
        elif status == "EMPTY":
            recorder.empty(COUNTY, sig, **kw)
        else:
            recorder.incomplete(COUNTY, sig, reason, row_count=len(records), **kw)
        print(f"    {status}: {len(records)} row(s) kept; reported {total}; "
              f"other status {outcome['other_status']}, rejected {outcome['rejected']}, "
              f"missing fields {outcome['missing_fields']}", flush=True)
        return records
    except Exception as exc:  # noqa: BLE001 - recorded, never a silent zero
        category, _ = describe_exception(exc)
        print(f"    FAILED ({category})", flush=True)
        recorder.failed(COUNTY, exc, **kw)
        return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--fixture", help="a JSON file: one Kendo envelope or a list of them (no network)")
    args = ap.parse_args(argv)
    pages = None
    if args.fixture:
        loaded = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        pages = loaded if isinstance(loaded, list) else [loaded]
    else:
        # Source permission: no recorded fetch/parse permission -> 0 requests, exit 3.
        denied = _LS.permission_gate(SOURCE_ID)
        if denied:
            return denied
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    recorder = StatusRecorder(SOURCE_ID, source_class="GOVERNMENT_DIRECT", source_id=SOURCE_ID)
    print(f"[1/1] {COUNTY}", flush=True)
    records = run(pages, recorder=recorder)
    recorder.write()
    print(recorder.summary_line(), flush=True)
    OUT_JSON.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Saved {len(records)} row(s) to {OUT_JSON.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
