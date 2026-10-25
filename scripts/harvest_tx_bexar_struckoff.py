#!/usr/bin/env python3
"""
Harvest Bexar County's struck-off (tax-foreclosure resale) property list,
published by Bexar County Public Works on bexar.org.

Added 2026-10-25 (Texas sources batch - docs/sources-batch-2026-10-25-texas.md).
GATED: source id `tx_bexar_struckoff`, wired into NO workflow and read by NO
sync. Its registry row is MANUAL_REVIEW_REQUIRED / UNREVIEWED (never
runnable by harvesters/otc/gate.py); the permission records
(data/source_permissions.csv) are an internal risk acceptance for fetch /
parse / store only, excluded from the paid tier - not the County's
permission. There is no display record.

WHAT THE SOURCE IS (read live 2026-10-25, structure and counts only):
Bexar County Public Works' "About Us" page (https://www.bexar.org/1670/About-Us)
says, under Property Tax Foreclosures: "to obtain a current Struck-Off List
please click the link below", and links "Current Struck-Off Property List"
to a DocumentCenter PDF. The reader finds that link on the page by its own
link text and never constructs the URL. The County's general information
sheet (DocumentCenter 41851) says properties not sold at the monthly
Sheriff's sale "are Struck Off and deeded in trust to Bexar County", are
"available for Private Sale", and are "sold at a minimum amount of the court
judgment against the property or for the adjudged value of the property,
whichever is less", with interim taxes, code-compliance liens and the deed
recording fee added.

The PDF is a scanned document (producer: a Lexmark scanner) with an OCR
text layer and no table structure. On 2026-10-25 it held two pages:
  page 1  "BEXAR COUNTY RESALE PROPERTIES", "List Updated <Month> <d>, <yyyy>",
          columns Property Address / Suit No. / Account No. / "Struck off amt
          w/o interim tax / fees", one property per line;
  page 2  "MULTIPLE ACCOUNTS": a suit covering several accounts with one
          amount, laid out across several lines.
and the footer "THE DOLLAR AMOUNTS LISTED ARE NOT GUARANTEED TO BE ACCURATE".

MAPPED (one-account lines only): Account No. -> case_no (the Bexar Appraisal
District account, shape 99999-999-9999 - the CAD account is case_no for
every Texas source), Suit No. -> parcel (the tax-suit cause number, exactly
as tx_lgbs / tx_realauction carry it), Property Address -> address (the
situs as listed; the County says street addresses are not guaranteed),
"Struck off amt w/o interim tax / fees" -> purchase_amount with
purchase_amount_kind PUBLISHED_AMOUNT_KIND_UNSPECIFIED (the list does not
call it a price or a minimum bid; the information sheet describes it as the
struck-off amount, with additions). "List Updated" -> list_as_of.
NOT MAPPED / NEVER STORED: the multiple-account section (its OCR layout
does not tie each account to its suit and amount reliably, so it is counted
and left unread), owner names (the list publishes none), bidder or purchaser
identities (none published).

STATUS (scripts/laft_status.py vocabulary; own status file
out/harvest_tx_struckoff_status.json, state TX):
  COMPLETE    every data line parsed and no unread section
  INCOMPLETE  rows kept, but some line failed the shape checks
              (PARSE_FORMAT_CHANGE - typically OCR noise), or the
              multiple-account section was present and not read; or the
              list was recognised with no row (UNCONFIRMED_EMPTY - the list
              has never been seen to state that it is empty, so a zero is
              never EMPTY)
  FAILED      transport, the link is missing from the page, not a PDF, no
              text layer, or the heading is not recognised
There is no EMPTY outcome: the source publishes no empty-list statement.

Logs carry counts, statuses and error categories only - never an account,
suit number, address or amount.

Run:
  python3 scripts/harvest_tx_bexar_struckoff.py                    # live (gated)
  python3 scripts/harvest_tx_bexar_struckoff.py --fixture F.pdf     # no network
Output: out/harvest_tx_bexar_struckoff.json.
"""
from __future__ import annotations

import argparse
import html as _html
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import laft_status as _LS  # noqa: E402 - permission gate
from laft_status import CategorizedError, StatusRecorder, describe_exception, record_identifiers_plausible

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_tx_bexar_struckoff.json"
STATUS_PATH = OUT_DIR / "harvest_tx_struckoff_status.json"

SOURCE_ID = "tx_bexar_struckoff"
STATE = "TX"
COUNTY = "Bexar"
DATASET = "struck_off_properties"
PAGE_URL = "https://www.bexar.org/1670/About-Us"
LINK_TEXT = "Current Struck-Off Property List"
MAX_PDF_BYTES = 20 * 1024 * 1024

INVENTORY_TYPE = "STRUCK_OFF_HELD_IN_TRUST"
AMOUNT_KIND = "PUBLISHED_AMOUNT_KIND_UNSPECIFIED"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Shapes, from the live list (2026-10-25). The account is the Bexar
# Appraisal District account; the suit number is the tax suit's cause
# number (e.g. a two-digit year, a court code, a serial).
ACCOUNT_RE = re.compile(r"^\d{5}-\d{3}-\d{4}$")
SUIT_RE = re.compile(r"^\d{1,4}-[A-Z]{2}[A-Z0-9]-\d{4,5}$")
AMOUNT_RE = re.compile(r"^\$\s?(\d{1,3}(?:,\d{3})*|\d+)\.\d{2}$")
# A one-account line: address, suit, account, amount (the last three are
# single tokens; everything before them is the address).
ROW_RE = re.compile(r"^(?P<address>.+?)\s+(?P<suit>\S+)\s+(?P<account>\S+)\s+(?P<amount>\$\s?[\d,]+\.\d{2})\s*$")
# Anything carrying an account-like or dollar token is a data line; one that
# does not parse is counted, never silently dropped.
DATA_LIKE_RE = re.compile(r"\d{4,5}-\d{2,3}-\d{3,4}|\$\s?[\d,]+\.\d{2}")
ACCOUNT_TOKEN_RE = re.compile(r"\b\d{5}-\d{3}-\d{4}\b")
LIST_UPDATED_RE = re.compile(r"List\s*Updated\s*([A-Za-z]+)\s*(\d{1,2})\s*,\s*(\d{4})", re.I)
HEADING = "BEXARCOUNTYRESALEPROPERTIES"
MULTI_MARKER = "MULTIPLEACCOUNTS"

_LINK_RE = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "").upper()


def discover_pdf_url(page_html: str, base: str = PAGE_URL) -> str:
    """The href of the page's own 'Current Struck-Off Property List' link."""
    want = _squash(LINK_TEXT)
    for href, inner in _LINK_RE.findall(page_html or ""):
        text = _html.unescape(re.sub(r"<[^>]+>", " ", inner))
        if _squash(text) == want:
            url = urljoin(base, _html.unescape(href))
            if not url.startswith("https://www.bexar.org/"):
                raise CategorizedError("PARSE_FORMAT_CHANGE", "the struck-off list link no longer points at bexar.org")
            return url
    raise CategorizedError("PARSE_FORMAT_CHANGE", "the page no longer carries the 'Current Struck-Off Property List' link")


def pdf_lines(pdf_bytes: bytes) -> list[list[str]]:
    """Text lines per page from the PDF's own text layer (no OCR here)."""
    if not pdf_bytes or not pdf_bytes.startswith(b"%PDF"):
        raise CategorizedError("PARSE_FORMAT_CHANGE", "the list document is not a PDF")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "the list document is larger than expected")
    import pdfplumber  # noqa: PLC0415 - only needed for a real read

    pages: list[list[str]] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            pages.append([ln.strip() for ln in (page.extract_text() or "").splitlines() if ln.strip()])
    if not any(pages):
        raise CategorizedError("PARSE_NO_TABLE", "the list document has no text layer")
    return pages


def list_as_of(pages: list[list[str]]) -> str | None:
    for lines in pages:
        for ln in lines:
            m = LIST_UPDATED_RE.search(ln)
            if m:
                try:
                    return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date().isoformat()
                except ValueError:
                    return None
    return None


def _amount(text: str) -> float | None:
    m = AMOUNT_RE.match(text.replace(" ", ""))
    if not m:
        return None
    return float(text.replace("$", "").replace(",", "").replace(" ", ""))


def parse_pages(pages: list[list[str]]) -> tuple[list[dict], dict]:
    """(records, outcome). Raises a format change when the heading is gone."""
    if HEADING not in _squash(" ".join(" ".join(p) for p in pages)):
        raise CategorizedError("PARSE_FORMAT_CHANGE", "the 'BEXAR COUNTY RESALE PROPERTIES' heading is not in the document")
    as_of = list_as_of(pages)
    outcome = {"data_lines": 0, "kept": 0, "unparsed": 0, "duplicate": 0,
               "multi_account_section": False, "multi_account_accounts": 0, "list_as_of": as_of}
    out: list[dict] = []
    seen: set[str] = set()
    in_multi = False
    for lines in pages:
        for ln in lines:
            if _squash(ln) == MULTI_MARKER:
                in_multi = True
                outcome["multi_account_section"] = True
                continue
            if in_multi:
                outcome["multi_account_accounts"] += len(ACCOUNT_TOKEN_RE.findall(ln))
                continue
            if not DATA_LIKE_RE.search(ln):
                continue
            outcome["data_lines"] += 1
            m = ROW_RE.match(ln)
            if not m:
                outcome["unparsed"] += 1
                continue
            suit, account = m.group("suit").upper(), m.group("account")
            amount = _amount(m.group("amount"))
            address = re.sub(r"\s+", " ", m.group("address")).strip()
            if not (SUIT_RE.match(suit) and ACCOUNT_RE.match(account)) or amount is None or not address:
                outcome["unparsed"] += 1
                continue
            if account in seen:
                outcome["duplicate"] += 1
                continue
            record = {
                "state": STATE, "county": COUNTY, "source": "laft", "harvester_source": SOURCE_ID,
                "inventory_type": INVENTORY_TYPE,
                "case_no": account,          # Bexar Appraisal District account (the CAD account)
                "parcel": suit,              # tax-suit cause number, as tx_lgbs / tx_realauction carry it
                "address": address,
                "purchase_amount": amount,
                "purchase_amount_kind": AMOUNT_KIND,
                "url_auction": PAGE_URL,
            }
            if as_of:
                record["list_as_of"] = as_of
            if not record_identifiers_plausible(record):
                outcome["unparsed"] += 1
                continue
            seen.add(account)
            out.append(record)
    outcome["kept"] = len(out)
    return out, outcome


def classify(records: list[dict], outcome: dict) -> tuple[str, str | None, str | None]:
    """(status, error_category, reason). There is no EMPTY: the list has
    never been seen to state that it is empty."""
    if not records:
        if outcome["unparsed"]:
            return "INCOMPLETE", "PARSE_FORMAT_CHANGE", "every data line failed the shape checks"
        return "INCOMPLETE", "UNCONFIRMED_EMPTY", "the list was recognised but no row was found; the source states no empty list"
    gaps = []
    if outcome["unparsed"]:
        gaps.append(f"{outcome['unparsed']} data line(s) failed the shape checks")
    if outcome["multi_account_section"]:
        gaps.append(f"multiple-account section not read ({outcome['multi_account_accounts']} account(s))")
    if gaps:
        return "INCOMPLETE", "PARSE_FORMAT_CHANGE", "; ".join(gaps)
    return "COMPLETE", None, None


def fetch_pdf() -> tuple[bytes, str]:
    import requests  # noqa: PLC0415 - a fixture read imports nothing networked

    s = requests.Session()
    page = s.get(PAGE_URL, headers=HEADERS, timeout=30)
    page.raise_for_status()
    pdf_url = discover_pdf_url(page.text)
    resp = s.get(pdf_url, headers={**HEADERS, "Accept": "application/pdf,*/*", "Referer": PAGE_URL}, timeout=60)
    resp.raise_for_status()
    return resp.content, pdf_url


def run(pdf_bytes: bytes | None = None, *, recorder: StatusRecorder | None = None) -> list[dict]:
    recorder = recorder or StatusRecorder(SOURCE_ID, source_class="GOVERNMENT_DIRECT", source_id=SOURCE_ID,
                                          path=STATUS_PATH, state=STATE)
    kw: dict = dict(source_url=PAGE_URL)
    try:
        if pdf_bytes is None:
            pdf_bytes, kw["document_url"] = fetch_pdf()
        records, outcome = parse_pages(pdf_lines(pdf_bytes))
        kw["list_as_of"] = outcome["list_as_of"]
        status, category, reason = classify(records, outcome)
        if status == "COMPLETE":
            recorder.complete(COUNTY, len(records), **kw)
        else:
            recorder.incomplete(COUNTY, category, reason, row_count=len(records), **kw)
        print(f"    {status}: {outcome['kept']} of {outcome['data_lines']} data line(s) kept "
              f"(unparsed {outcome['unparsed']}, duplicate {outcome['duplicate']}); "
              f"multiple-account section {'present' if outcome['multi_account_section'] else 'absent'} "
              f"({outcome['multi_account_accounts']} account(s) not read); "
              f"list as of {outcome['list_as_of'] or 'not stated'}", flush=True)
        return records
    except Exception as exc:  # noqa: BLE001 - recorded, never a silent zero
        category, _ = describe_exception(exc)
        print(f"    FAILED ({category})", flush=True)
        recorder.failed(COUNTY, exc, **kw)
        return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bexar County struck-off property list (gated)")
    ap.add_argument("--fixture", help="a local copy of the list PDF (no network)")
    args = ap.parse_args(argv)
    # Source permission: fetch / parse / store must each be recorded, or 0
    # requests and nothing written (exit 3). A fixture read makes no request.
    ops = ("parse", "store") if args.fixture else ("fetch", "parse", "store")
    denied = _LS.permission_gate(SOURCE_ID, operations=ops, state=STATE, dataset=DATASET)
    if denied:
        return denied
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    recorder = StatusRecorder(SOURCE_ID, source_class="GOVERNMENT_DIRECT", source_id=SOURCE_ID,
                              path=STATUS_PATH, state=STATE)
    print(f"[1/1] {COUNTY}, {STATE}", flush=True)
    records = run(Path(args.fixture).read_bytes() if args.fixture else None, recorder=recorder)
    recorder.write()
    print(recorder.summary_line(), flush=True)
    OUT_JSON.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Saved {len(records)} row(s) to {OUT_JSON.name}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
