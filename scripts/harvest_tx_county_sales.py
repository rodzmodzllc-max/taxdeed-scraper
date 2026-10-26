#!/usr/bin/env python3
"""
Harvest Texas COUNTY-RUN tax-sale and struck-off resale lists - the lists a
county office publishes itself, outside the multi-county vendor feeds
(LGBS / RealAuction in harvesters/texas_harvester.py, untouched here; PBFCM /
MVBA / GovEase / CTSA are hard-blocked and never requested).

Added 2026-10-26 (owner decision: "find every property and every source,
then we'll work on the legal shit"). Every source below carries interim
INTERNAL_RISK_ACCEPTANCE records in data/source_permissions.csv (fetch /
parse / store, expiring 2027-04-12); the read stops before any request
without them. No login, no CAPTCHA, no paywall; an honest User-Agent; one
request per document, at most once a day. Accepting a page's own public
"I agree" disclaimer is not a login and needs no request (Harris serves the
list with the clickwrap overlay already in the HTML).

SOURCES (each a county unit in out/harvest_tx_county_status.json)
-------
tx_hctax / Harris - Harris County Tax Assessor-Collector, "Harris County
  Delinquent Tax Sale Property Listing" (hctax.net/Property/listings/
  taxsalelisting): one HTML page holding every listing of the next monthly
  constable sale, read live 2026-10-26: "Sale Date: November 03, 2026", 182
  listings (150 For Sale, 32 Cancelled). Per listing: Account# (HCAD account,
  13 digits), Cause#, address / city / zip, precinct, Type (SALE / RESALE /
  EOS / EXE ...), status (For Sale / Cancelled), Adjudged Value, Minimum Bid,
  Judgment date, tax years, legal description. AUCTIONS ledger. A Cancelled
  listing is kept out of the active rows (counted). "Sold with Account#"
  listings carry no minimum bid of their own - no bid is invented.
tx_bexar_resale / Bexar - Bexar County "Resale Properties Distribution List"
  PDF (bexar.org DocumentCenter 41852): properties struck off to the taxing
  units after a failed sheriff's sale, offered for resale. Read live
  2026-10-26: "List Updated October 9, 2026", columns Property Address,
  Suit No., Account No., "Struck off amt w/o interim tax / fees". Text layer
  only (the document is an OCR'd scan): a line is a row only when it ends in
  a Bexar CAD account (NNNNN-NNN-NNNN) and a dollar amount; any other line
  that carries a suit number is counted as rejected and makes the read
  INCOMPLETE, never COMPLETE. AVAILABLE ledger (struck-off resale
  inventory); the amount is the list's own struck-off amount
  (STRUCK_OFF_AMOUNT_WITHOUT_INTERIM_TAX_FEES) - never called a price.
tx_jefferson_sheriff_sale / Jefferson - Jefferson County Tax Office "Notice of
  Sale" PDF for the next Sheriff's sale, found on the office's own
  delinquent-tax-sale page (jeffcotax.com/property-tax/delinquent-tax-sale/,
  the newest linked "Notice of Sale" PDF - never a composed URL). Read live
  2026-10-26: December 1, 2026 sale, 19 pages, a ruled table with Sale #,
  Cause # / Judgment Date, Acct #, Style of Case, Legal Description (with
  situs), Adjudged Value / Add'l Delinquent Taxes, Estimated Minimum Bid.
  AUCTIONS ledger.

Output, one set per ledger (no file is shared between two ledgers):
  out/harvest_tx_county_auctions.json / _available.json - one dict per row,
    the field names of texas_harvester.TexasSaleRow plus a few list-specific
    extras (what scripts/texas_closeout.py reads: account_number, source,
    county, harvester_source);
  out/harvest_tx_county_auctions_status.json / _available_status.json - the
    per-(source, county) laft_status vocabulary;
  out/tx_county_auctions_properties_rows.json / _available_properties_rows.json
    - the same rows as `properties` rows (harvesters/otc/model.py
    OtcRecord.to_properties_row(), see to_properties_rows()), which
    scripts/sync_state_inventory.py upserts in the texas job.

Published by the owner's 2026-10-26 decision ("post their shit";
docs/publish-all-sources.md): registry rows PRODUCTION_VERIFIED / APPROVED with
the "Owner approved customer publication 2026-10-26; legal review pending"
restriction, INTERIM display / link records. Rows leave the list only through
scripts/texas_closeout.py, per source, after a COMPLETE / EMPTY read.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import laft_status as _LS  # noqa: E402
from laft_status import CategorizedError, StatusRecorder, describe_exception  # noqa: E402

OUT_DIR = HERE / "../out"
# One harvest file and one status file PER LEDGER (harvesters/ledgers/domains.py:
# no status or harvest file is shared between two ledgers).
LEDGER_FILES = {
    "AUCTIONS": ("harvest_tx_county_auctions.json", "harvest_tx_county_auctions_status.json"),
    "AVAILABLE": ("harvest_tx_county_available.json", "harvest_tx_county_available_status.json"),
}
# The same rows as `properties` rows, for scripts/sync_state_inventory.py.
PROPERTIES_ROWS_FILES = {
    "AUCTIONS": "tx_county_auctions_properties_rows.json",
    "AVAILABLE": "tx_county_available_properties_rows.json",
}
UA = "taxdeed-scraper/1.0 (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
HARVESTER = "tx_county_sales"
RETRY_DELAY_S = 5

AUCTION_DATASET = "sale_calendar"
AVAILABLE_DATASET = "lands_available"

HARRIS_URL = "https://www.hctax.net/Property/listings/taxsalelisting"
BEXAR_URL = "https://www.bexar.org/DocumentCenter/View/41852/Bexar-County-Resale-Properties-Distribution-List"
JEFFERSON_PAGE = "https://jeffcotax.com/property-tax/delinquent-tax-sale/"


def _clean(s) -> str:
    return re.sub(r"\s+", " ", "" if s is None else str(s)).strip()


def _money(s) -> float | None:
    m = re.search(r"\$?\s*([\d,]+\.\d{2})", s or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _date_long(s: str) -> str | None:
    s = _clean(s)
    for fmt in ("%B %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _row(**kw) -> dict:
    base = {"state": "TX", "account_number": None, "county": None, "auction_date": None, "min_bid": None,
            "cad_market_value": None, "legal_description": None, "address": None, "cause_number": None,
            "source": "", "harvester_source": "", "sale_list_url": None, "sale_status": None}
    base.update({k: v for k, v in kw.items()})
    return base


# ---------------------------------------------------------------- Harris (tx_hctax)


def parse_harris(html: str, url: str = HARRIS_URL) -> tuple[list[dict], dict]:
    from bs4 import BeautifulSoup  # noqa: PLC0415
    soup = BeautifulSoup(html, "html.parser")
    text = _clean(soup.get_text(" "))
    m = re.search(r"Sale Date:\s*([A-Z][a-z]+ \d{1,2},? \d{4})", text)
    if not m or "Delinquent Tax Sale Property Listing" not in text:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "listing page no longer names its sale date / title")
    sale_date = _date_long(m.group(1).replace(",", ", ").replace(",  ", ", "))
    listings = soup.select("li.listing")
    rows: list[dict] = []
    meta = {"listings": len(listings), "for_sale": 0, "cancelled": 0, "other_status": 0, "rejected": 0,
            "sale_date": sale_date, "types": {}}
    for li in listings:
        acct_el = li.select_one(".account strong")
        acct = _clean(acct_el.get_text()) if acct_el else ""
        if not re.fullmatch(r"\d{13}", acct):
            meta["rejected"] += 1
            continue
        status_el = li.select_one("div[class$='-small'] strong")
        status = _clean(status_el.get_text()) if status_el else ""
        if status == "Cancelled":
            meta["cancelled"] += 1
            continue
        if status != "For Sale":
            meta["other_status"] += 1
            continue
        meta["for_sale"] += 1
        cause_el = li.select_one(".SuitNumber strong")
        addr = " ".join(_clean(li.select_one(f".{c}").get_text()) for c in ("address", "city", "state", "zip")
                        if li.select_one(f".{c}"))
        h4 = li.find("h4")
        typ = ""
        if h4:
            tm = re.search(r"Type:\s*([A-Za-z]+)", _clean(h4.get_text()))
            typ = tm.group(1).upper() if tm else ""
        meta["types"][typ or "?"] = meta["types"].get(typ or "?", 0) + 1
        min_el = li.select_one(".minBid strong")
        adj_el = li.select_one(".adjudgedValue strong")
        modal = soup.find(id=f"listing-{acct}")
        legal = None
        judgment = None
        if modal:
            for p in modal.find_all("p"):
                if _clean(p.get_text()) == "Description":
                    nxt = p.find_next_sibling("p")
                    legal = _clean(nxt.get_text()) if nxt else None
                    break
            for td in modal.find_all("td", class_="modalCell"):
                if _clean(td.get_text()).startswith("Judgment"):
                    val = td.find_next_sibling("td")
                    judgment = _clean(val.get_text()) if val else None
        rows.append(_row(
            account_number=acct, county="Harris", auction_date=sale_date,
            min_bid=_money("$" + _clean(min_el.get_text())) if min_el else None,
            adjudged_value=_money("$" + _clean(adj_el.get_text())) if adj_el else None,
            legal_description=legal or None, address=addr or None,
            cause_number=_clean(cause_el.get_text()) if cause_el else None,
            source="auction", harvester_source="tx_hctax", sale_list_url=url,
            sale_status=status, sale_type=typ or None, judgment_date=judgment,
            precinct=_clean(li.select_one(".precinct").get_text()) if li.select_one(".precinct") else None,
            auction_url=url, auction_url_kind="sale"))
    return rows, meta


def harvest_harris(session) -> tuple[list[dict], dict, str]:
    r = session.get(HARRIS_URL, timeout=90)
    r.raise_for_status()
    rows, meta = parse_harris(r.text, HARRIS_URL)
    return rows, meta, HARRIS_URL


# ---------------------------------------------------------------- Bexar (tx_bexar_resale)

_SUIT = r"\d{1,4}-?TA[A-Za-z0-9]-[0-9OolI]{4,6}"
_ACCT = r"[\dlIO]{5}-\d{2,3}-\d{4}"
BEXAR_ROW = re.compile(
    rf"^(?P<addr>.*?)\s*(?P<suit>{_SUIT})\s+(?P<acct>{_ACCT})\s+\$\s?(?P<amt>[\d,]+\.\d{{2}})\s*$")
# The "MULTIPLE ACCOUNTS" page: one property (one suit, one amount) spread
# over several account lines between ruled separators.
BEXAR_SUIT_LIKE = re.compile(r"\d{1,4}-?TA[A-Za-z0-9]-")


def _ocr_digits(s: str) -> str:
    return s.replace("O", "0").replace("o", "0").replace("l", "1").replace("I", "1")


def parse_bexar_text(text: str, url: str = BEXAR_URL) -> tuple[list[dict], dict]:
    flat = _clean(text)
    if "RESALEPROPERTIES" not in flat.upper().replace(" ", ""):
        raise CategorizedError("PARSE_FORMAT_CHANGE", "document no longer titled 'Resale Properties'")
    um = re.search(r"List\s*Updated\s*([A-Z][a-z]+)\s*(\d{1,2}),?\s*(\d{4})", text)
    as_of = None
    if um:
        try:
            as_of = datetime.strptime(f"{um.group(1)} {um.group(2)} {um.group(3)}", "%B %d %Y").strftime("%Y-%m-%d")
        except ValueError:
            as_of = None
    rows, rejected, groups = [], 0, 0

    def emit(acct: str, suit: str, addr: str | None, amt: str, extra: list[str] | None = None) -> None:
        rows.append(_row(
            account_number=_ocr_digits(acct), county="Bexar", cause_number=_ocr_digits(suit),
            address=(_clean(addr or "").rstrip(",") or None),
            struck_off_amount=float(amt.replace(",", "")),
            amount_kind="STRUCK_OFF_AMOUNT_WITHOUT_INTERIM_TAX_FEES",
            source="laft", harvester_source="tx_bexar_resale", sale_list_url=url, list_as_of=as_of,
            sale_status="RESALE", **({"additional_accounts": [_ocr_digits(a) for a in extra]} if extra else {})))

    in_multi = False
    block: list[str] = []

    def close_block() -> None:
        nonlocal rejected, groups, block
        lines = [b for b in block if b]
        block = []
        if not lines:
            return
        accts, suit, amt, addr = [], None, None, None
        for b in lines:
            accts += re.findall(_ACCT, b)
            sm = re.search(rf"({_SUIT})", b)
            am = re.search(r"\$\s?([\d,]+\.\d{2})", b)
            if sm:
                suit = suit or sm.group(1)
            if am:
                amt = amt or am.group(1)
            lead = _clean(re.split(rf"{_SUIT}|{_ACCT}", b)[0])
            if lead and not addr:
                addr = lead
        if accts and suit and amt:
            emit(accts[0], suit, addr, amt, accts[1:])
            groups += 1
        else:
            rejected += 1

    for raw in text.splitlines():
        line = raw.strip()
        if re.match(r"^page\s*\d+$", line, re.I):
            close_block()
            in_multi = False
            continue
        if "MULTIPLE ACCOUNTS" in line.upper():
            in_multi = True
            continue
        if in_multi:
            if re.match(r"^_{5,}", line) or line.upper().startswith("THE DOLLAR AMOUNTS"):
                close_block()
            elif re.search(_ACCT, line) or re.search(_SUIT, line):
                block.append(line)
            continue
        m = BEXAR_ROW.match(line)
        if m:
            emit(m.group("acct"), m.group("suit"), m.group("addr"), m.group("amt"))
        elif BEXAR_SUIT_LIKE.search(line):
            rejected += 1
    close_block()
    return rows, {"rows": len(rows), "rejected": rejected, "multi_account_groups": groups, "list_as_of": as_of}


def _pdf_text(data: bytes) -> str:
    import pdfplumber  # noqa: PLC0415
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def harvest_bexar(session) -> tuple[list[dict], dict, str]:
    r = session.get(BEXAR_URL, timeout=60)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise CategorizedError("PARSE_FORMAT_CHANGE", "resale list link no longer returns a PDF")
    rows, meta = parse_bexar_text(_pdf_text(r.content), BEXAR_URL)
    return rows, meta, BEXAR_URL


# ---------------------------------------------------------------- Jefferson (tx_jefferson_sheriff_sale)

NOTICE_LINK = re.compile(r'href="([^"]+Notice-of-Sale[^"]*\.pdf)"', re.I)
JEFF_ACCT = re.compile(r"\d{6}-\d{3}-\d{6}-\d{5}")


def jefferson_notice_url(page_html: str, base: str = JEFFERSON_PAGE) -> str:
    links = []
    for href in NOTICE_LINK.findall(page_html):
        u = urljoin(base, href)
        if u not in links:
            links.append(u)
    if not links:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "delinquent-tax-sale page links no Notice of Sale PDF")
    return links[0]


def parse_jefferson_tables(tables: list[list[list]], url: str, sale_date: str | None) -> tuple[list[dict], dict]:
    rows, rejected, header_seen = [], 0, 0
    for table in tables:
        for r in table:
            cells = [(c or "").strip() for c in r]
            if len(cells) < 7:
                continue
            if cells[0].startswith("Sale"):
                header_seen += 1
                continue
            if not re.fullmatch(r"\d{1,4}", cells[0]):
                continue
            cause_lines = cells[1].split("\n")
            acct_lines = cells[2].split("\n")
            acct = "".join(acct_lines[:2]).replace(" ", "")
            if not JEFF_ACCT.fullmatch(acct):
                rejected += 1
                continue
            legal_lines = cells[4].split("\n")
            situs_idx = next((i for i, ln in enumerate(legal_lines) if re.match(r"^\d+\s+\S", ln) and i > 0), None)
            legal = _clean(" ".join(legal_lines[:situs_idx] if situs_idx else legal_lines))
            situs = _clean(" ".join(legal_lines[situs_idx:])) if situs_idx else None
            adjudged = _money(cells[5].split("\n")[0])
            rows.append(_row(
                account_number=acct, county="Jefferson", auction_date=sale_date,
                min_bid=_money(cells[6]), adjudged_value=adjudged,
                cause_number=_clean(cause_lines[0]) or None,
                judgment_date=_clean(cause_lines[1]) if len(cause_lines) > 1 else None,
                legal_description=legal or None, address=situs,
                sale_number=cells[0], source="auction", harvester_source="tx_jefferson_sheriff_sale",
                sale_list_url=url, sale_status="SCHEDULED",
                min_bid_note=("adjudged value + deed" if "adjudged" in cells[5].lower() else None)))
    return rows, {"rows": len(rows), "rejected": rejected, "header_rows": header_seen}


def _jefferson_sale_date(text: str) -> str | None:
    m = re.search(r"first Tuesday in ([A-Z][a-z]+),?\s*(\d{4}),?\s*the same being the (\d{1,2})", text)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(3)} {m.group(2)}", "%B %d %Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def harvest_jefferson(session) -> tuple[list[dict], dict, str]:
    page = session.get(JEFFERSON_PAGE, timeout=30)
    if "sucuri" in page.text.lower() and "Notice-of-Sale" not in page.text:
        # The site's bot challenge (a JavaScript cookie puzzle). It is never
        # solved or worked around here: the read fails closed and says why.
        raise CategorizedError("ACCESS_DENIED", "bot challenge (Sucuri cloudproxy) served instead of the page - not bypassed")
    page.raise_for_status()
    url = jefferson_notice_url(page.text)
    r = session.get(url, timeout=60)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise CategorizedError("PARSE_FORMAT_CHANGE", "Notice of Sale link no longer returns a PDF")
    import pdfplumber  # noqa: PLC0415
    with pdfplumber.open(io.BytesIO(r.content)) as pdf:
        first = pdf.pages[0].extract_text() or ""
        tables = [t for p in pdf.pages for t in p.extract_tables()]
    rows, meta = parse_jefferson_tables(tables, url, _jefferson_sale_date(first))
    meta["sale_date"] = rows[0]["auction_date"] if rows else _jefferson_sale_date(first)
    return rows, meta, url


# ---------------------------------------------------------------- shared helpers for linked documents


def find_doc_link(page_html: str, base: str, text_re: str, href_re: str = r"\.pdf") -> list[str]:
    """Every document link on the page whose visible text matches text_re and
    whose href matches href_re - read from the page, never composed."""
    out = []
    for m in re.finditer(r'<a\b[^>]*?href=\s*["\']([^"\']+)["\'][^>]*>(.*?)</a>', page_html, re.S | re.I):
        href, txt = m.group(1).replace("&amp;", "&"), _clean(re.sub(r"<[^>]+>", " ", m.group(2)))
        if re.search(text_re, txt, re.I) and re.search(href_re, href, re.I):
            u = urljoin(base, href)
            if u not in out:
                out.append(u)
    return out


def _get_pdf(session, url: str) -> bytes:
    r = session.get(url, timeout=60)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise CategorizedError("PARSE_FORMAT_CHANGE", "linked list no longer returns a PDF")
    return r.content


def _pdf_tables(data: bytes) -> list[list[list]]:
    import pdfplumber  # noqa: PLC0415
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [t for p in pdf.pages for t in p.extract_tables()]


def _mdy(s: str | None) -> str | None:
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m.%d.%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------- Montgomery (tx_montgomery_tax_trust)
# Montgomery County Tax Office "Tax Trust Properties" page: the "PDF Format"
# link of the current Tax Trust Listing (read live 2026-10-26: 5 pages, a ruled
# table "Account # | Strike-Off Unit | Legal Description | Cause No. |
# Appraisal Value | Base Tax Due | School District", ~236 rows). Property held
# in trust by a taxing unit after a failed tax sale, sold by bid -> AVAILABLE.
# The list publishes no price: no amount is stored (appraisal value is a
# value, base tax due is a tax - neither is a purchase figure).

MONTGOMERY_PAGE = "https://www.mctx.org/departments/departments_q_-_z/tax_office/tax_trust_property.php"
MONT_HEADER = ["Account #", "Strike-Off Unit", "Legal Description", "Cause No.", "Appraisal Value", "Base Tax Due",
               "School District"]


def parse_montgomery_tables(tables, url: str) -> tuple[list[dict], dict]:
    rows, rejected, headers = [], 0, 0
    for t in tables:
        for r in t:
            cells = [_clean(c) for c in r]
            if cells[:2] == MONT_HEADER[:2]:
                headers += 1
                continue
            if len(cells) != len(MONT_HEADER):
                rejected += 1
                continue
            if not re.fullmatch(r"\d{13}", cells[0]):
                rejected += 1
                continue
            rows.append(_row(account_number=cells[0], county="Montgomery", legal_description=cells[2] or None,
                             cause_number=cells[3] or None, cad_market_value=_money(cells[4] + ".00") if cells[4] else None,
                             trustee=cells[1] or None, base_tax_due=_money(cells[5]),
                             source="laft", harvester_source="tx_montgomery_tax_trust", sale_list_url=url,
                             sale_status="TAX_TRUST", amount_kind="NOT_PUBLISHED"))
    if not headers:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "trust listing table header not found")
    return rows, {"rows": len(rows), "rejected": rejected}


def harvest_montgomery(session):
    page = session.get(MONTGOMERY_PAGE, timeout=30)
    page.raise_for_status()
    links = find_doc_link(page.text, MONTGOMERY_PAGE, r"PDF Format", r"Tax\s*Trust.*\.pdf")
    if not links:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "Tax Trust page links no PDF listing")
    rows, meta = parse_montgomery_tables(_pdf_tables(_get_pdf(session, links[0])), links[0])
    return rows, meta, links[0]


# ---------------------------------------------------------------- Orange TX (tx_orange_trust_property)
# Orange County (TX) Tax Assessor-Collector "Property Tax Sales" page: the
# "Trust Property Tax Sales" PDF ("ORANGE COUNTY TRUST PROPERTY ... trust
# properties in Orange County available for purchase", "Date as of", read
# live 2026-10-26: 2 pages, ~19 properties). Each property is two table rows:
# No. / approximate location / legal description / suit / "Minimum* Bid
# Amount" / notes, then the account number. The list says only bids at the
# original tax-sale minimum are accepted -> amount kind MINIMUM_BID_ACCEPTED.

ORANGE_TX_PAGE = "https://www.co.orange.tx.us/departments/TaxAssessor-Collector/PropertyTaxSales"
ORANGE_ACCT = re.compile(r"\b\d{6}-\d{5,6}\b")


def parse_orange_tables(tables, url: str, as_of: str | None = None) -> tuple[list[dict], dict]:
    rows, rejected, cur = [], 0, None

    def flush():
        nonlocal cur, rejected
        if cur is None:
            return
        if cur.get("account_number"):
            rows.append(cur)
        else:
            rejected += 1
        cur = None

    for t in tables:
        for r in t:
            cells = [(c or "").strip() for c in r]
            if len(cells) < 6:
                continue
            if re.fullmatch(r"\d{1,3}", cells[0]):
                flush()
                legal = cells[2].split("\n")
                legal = _clean(" ".join(ln for ln in legal if not ln.lower().startswith("account nu")))
                acct = ORANGE_ACCT.search(" ".join(cells))
                cur = _row(account_number=acct.group(0) if acct else None, county="Orange",
                           address=_clean(cells[1].replace("\n", ", ")) or None, legal_description=legal or None,
                           cause_number=_clean(cells[4]) or None, min_bid=_money(cells[5]),
                           amount_kind="MINIMUM_BID_ACCEPTED", notes=_clean(cells[6]) if len(cells) > 6 else None,
                           source="laft", harvester_source="tx_orange_trust_property", sale_list_url=url,
                           list_as_of=as_of, sale_status="TRUST_PROPERTY")
            elif cur is not None and not cur.get("account_number"):
                acct = ORANGE_ACCT.search(" ".join(cells))
                if acct:
                    cur["account_number"] = acct.group(0)
    flush()
    return rows, {"rows": len(rows), "rejected": rejected, "list_as_of": as_of}


def harvest_orange_tx(session):
    page = session.get(ORANGE_TX_PAGE, timeout=30)
    page.raise_for_status()
    links = find_doc_link(page.text, ORANGE_TX_PAGE, r"Trust Property Tax Sales", r"\.pdf")
    if not links:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "page links no Trust Property PDF")
    data = _get_pdf(session, links[0])
    m = re.search(r"Date as of:\s*([A-Z][a-z]+ \d{1,2},? \d{4})", _pdf_text(data))
    rows, meta = parse_orange_tables(_pdf_tables(data), links[0], _date_long(m.group(1)) if m else None)
    return rows, meta, links[0]


# ---------------------------------------------------------------- Trinity CAD (tx_trinity_cad_resale)
# Trinity Central Appraisal District "Resale Property Information" page: two
# dated PDFs ("Trinity CAD Resale Property List - excluding Westwood Shores",
# "Westwood Shores Resale Property List"), read live 2026-10-26 (dated
# 9/22/2026): a ruled table "PID | file_as_name | legal_desc | state_cd",
# file_as_name being the trustee taxing unit. No price is published (bids on
# the district's bid form) -> no amount.

TRINITY_PAGE = "https://trinitycad.net/resale-property-information/"


def parse_trinity_tables(tables, url: str, as_of: str | None) -> tuple[list[dict], dict]:
    rows, rejected, headers = [], 0, 0
    for t in tables:
        for r in t:
            cells = [_clean(c) for c in r]
            if cells[:1] == ["PID"]:
                headers += 1
                continue
            if len(cells) < 3 or not re.fullmatch(r"\d{1,8}", cells[0]):
                rejected += 1
                continue
            rows.append(_row(account_number=cells[0], county="Trinity", legal_description=cells[2] or None,
                             trustee=cells[1] or None, state_code=(cells[3] if len(cells) > 3 else None) or None,
                             source="laft", harvester_source="tx_trinity_cad_resale", sale_list_url=url,
                             list_as_of=as_of, sale_status="RESALE", amount_kind="NOT_PUBLISHED"))
    if not headers:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "resale list header (PID) not found")
    return rows, {"rows": len(rows), "rejected": rejected}


def harvest_trinity(session):
    page = session.get(TRINITY_PAGE, timeout=30)
    page.raise_for_status()
    links = find_doc_link(page.text, TRINITY_PAGE, r"Resale Property List", r"\.pdf")
    if not links:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "page links no Resale Property List PDF")
    rows, meta = [], {"rows": 0, "rejected": 0, "documents": len(links)}
    seen = set()
    for link in links:
        data = _get_pdf(session, link)
        m = re.search(r"RESALE LIST[^\n]*?(\d{1,2}/\d{1,2}/\d{4})", _pdf_text(data))
        part, pm = parse_trinity_tables(_pdf_tables(data), link, _mdy(m.group(1)) if m else None)
        for r in part:
            if r["account_number"] not in seen:
                seen.add(r["account_number"])
                rows.append(r)
        meta["rejected"] += pm["rejected"]
    meta["rows"] = len(rows)
    return rows, meta, TRINITY_PAGE


# ---------------------------------------------------------------- Randall (tx_randall_trustee_property)
# Randall County Tax Office "Sheriff Sale" page: "Properties Listing (PDF)"
# (DocumentCenter 286) - "RANDALL COUNTY TRUSTEE PROPERTY LISTING", page 2
# "STRUCK OFF PROPERTY: Account Number | Description | Minimum Bid at Sale",
# "Updated <date>", then a bid form. Read live 2026-10-26: 3 properties,
# updated 10/02/2025. Numbered text entries "N. <account> <description>
# $<amount>". The amount is the minimum bid at the ORIGINAL sale ->
# ORIGINAL_OPENING_BID; bids are submitted on the form.

RANDALL_PAGE = "https://www.randallcounty.gov/293/Sheriff-Sale"
RANDALL_ENTRY = re.compile(r"^(?P<n>\d{1,3})\.\s+(?P<acct>\d[\d ]{4,9}\d)\s+(?P<desc>.*?)\s*\$(?P<amt>[\d,]+(?:\.\d{2})?)\s*(?P<rest>.*)$")


def parse_randall_text(text: str, url: str) -> tuple[list[dict], dict]:
    if "STRUCK OFF PROPERTY" not in text.upper():
        raise CategorizedError("PARSE_FORMAT_CHANGE", "listing no longer carries a 'Struck Off Property' section")
    um = re.search(r"Updated\s+(\d{1,2}/\d{1,2}/\d{4})", text)
    as_of = _mdy(um.group(1)) if um else None
    rows, rejected, cur = [], 0, None
    body = text.split("Bid at Sale", 1)[-1].split("BID SUBMISSION", 1)[0]
    for line in body.splitlines():
        line = line.strip()
        m = RANDALL_ENTRY.match(line)
        if m:
            cur = _row(account_number=m.group("acct").replace(" ", ""), county="Randall",
                       legal_description=_clean(m.group("desc") + " " + m.group("rest")),
                       min_bid=float(m.group("amt").replace(",", "")), amount_kind="ORIGINAL_OPENING_BID",
                       source="laft", harvester_source="tx_randall_trustee_property", sale_list_url=url,
                       list_as_of=as_of, sale_status="STRUCK_OFF")
            rows.append(cur)
        elif re.match(r"^\d{1,3}\.\s", line):
            rejected += 1
            cur = None
        elif cur is not None and line and not line.lower().startswith("updated"):
            if line.lower().startswith("deed filed"):
                cur["deed_filed"] = _mdy(line.split(":", 1)[-1].strip()) if ":" in line else _mdy(line.split()[-1])
            elif re.search(r",\s*TX\b", line):
                cur["address"] = line
            else:
                cur["legal_description"] = _clean((cur["legal_description"] or "") + " " + line)
    return rows, {"rows": len(rows), "rejected": rejected, "list_as_of": as_of}


def harvest_randall(session):
    page = session.get(RANDALL_PAGE, timeout=30)
    page.raise_for_status()
    links = find_doc_link(page.text, RANDALL_PAGE, r"Propert(y|ies) Listing", r"DocumentCenter|\.pdf")
    if not links:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "page links no Properties Listing")
    rows, meta = parse_randall_text(_pdf_text(_get_pdf(session, links[0])), links[0])
    return rows, meta, links[0]


# ---------------------------------------------------------------- Hood CAD (tx_hood_cad_struck_off)
# Hood Central Appraisal District "'Struck off' Property List" page: an HTML
# block "Current Properties on the struck off property list" with the columns
# Account Number | Legal Description | Address and a bid submission form.
# Read live 2026-10-26: the column headings and no property under them ->
# EMPTY only when that heading block is present with no account-shaped value
# after it; anything else unrecognised is INCOMPLETE.

HOOD_PAGE = "https://hoodcad.net/struck-off-property-list/"


def parse_hood(html: str, url: str = HOOD_PAGE) -> tuple[list[dict], dict]:
    from bs4 import BeautifulSoup  # noqa: PLC0415
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer"]):
        t.decompose()
    text = _clean(soup.get_text(" "))
    m = re.search(r"Current Properties on the struck off property list\s+Account Number\s+Legal Description\s+Address(.*?)"
                  r"(Bidder submission form|Contact Information)", text, re.I)
    if not m:
        raise CategorizedError("PARSE_FORMAT_CHANGE", "struck-off list heading block not found")
    between = _clean(m.group(1))
    rows = []
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        hdr = [_clean(c.get_text()) for c in trs[0].find_all(["th", "td"])] if trs else []
        if hdr[:1] == ["Account Number"]:
            for tr in trs[1:]:
                cells = [_clean(c.get_text()) for c in tr.find_all(["td", "th"])]
                if cells and re.search(r"\d", cells[0]):
                    rows.append(_row(account_number=cells[0], county="Hood",
                                     legal_description=(cells[1] if len(cells) > 1 else None) or None,
                                     address=(cells[2] if len(cells) > 2 else None) or None,
                                     source="laft", harvester_source="tx_hood_cad_struck_off", sale_list_url=url,
                                     sale_status="STRUCK_OFF", amount_kind="NOT_PUBLISHED"))
    meta = {"rows": len(rows), "rejected": 0, "empty_list": (not rows and not re.search(r"\d", between))}
    if not rows and re.search(r"\d", between):
        meta["rejected"] = 1  # something under the headings this parser cannot read
    return rows, meta


def harvest_hood(session):
    r = session.get(HOOD_PAGE, timeout=30)
    r.raise_for_status()
    rows, meta = parse_hood(r.text, HOOD_PAGE)
    return rows, meta, HOOD_PAGE


# ---------------------------------------------------------------- properties rows


# The page a list is published on (the row's list_url); the PDF the row was
# read from is its document_url. Bexar links its list straight from the county
# site, so the document is also the list.
LIST_PAGES = {
    "tx_hctax": HARRIS_URL,
    "tx_bexar_resale": BEXAR_URL,
    "tx_jefferson_sheriff_sale": JEFFERSON_PAGE,
    "tx_montgomery_tax_trust": MONTGOMERY_PAGE,
    "tx_orange_trust_property": ORANGE_TX_PAGE,
    "tx_trinity_cad_resale": TRINITY_PAGE,
    "tx_randall_trustee_property": RANDALL_PAGE,
    "tx_hood_cad_struck_off": HOOD_PAGE,
}

# The harvester's own amount wording -> the stored vocabulary
# (harvesters/otc/model.py AmountKind). An auction figure is a minimum bid
# only when the list calls it one; Jefferson's "Estimated Minimum Bid" and
# Bexar's "Struck off amt w/o interim tax / fees" are figures of unstated kind.
AMOUNT_KIND_FOR = {
    "tx_hctax": "MINIMUM_PURCHASE_AMOUNT",            # 'Minimum Bid'
    "tx_jefferson_sheriff_sale": "PUBLISHED_AMOUNT_KIND_UNSPECIFIED",  # 'Estimated Minimum Bid'
    "tx_bexar_resale": "PUBLISHED_AMOUNT_KIND_UNSPECIFIED",            # struck-off amount w/o interim tax / fees
    "tx_orange_trust_property": "MINIMUM_PURCHASE_AMOUNT",            # 'Minimum* Bid Amount' (original sale minimum)
    "tx_randall_trustee_property": "ORIGINAL_OPENING_BID",           # 'Minimum Bid at Sale' (the original sale)
}
# Source wording carried verbatim as the row's status text (tx_sale_status /
# inventory_status_raw); a status this harvester assigned itself is not.
SOURCE_STATUS_WORDING = {"tx_hctax"}
# Extras kept in otc_provenance (never a column of their own).
PROVENANCE_EXTRAS = ("cause_number", "adjudged_value", "struck_off_amount", "judgment_date", "precinct", "sale_type",
                     "sale_number", "trustee", "base_tax_due", "state_code", "additional_accounts", "deed_filed", "notes",
                     "min_bid_note")


def _iso_date(s):
    from datetime import date  # noqa: PLC0415
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def to_properties_row(row: dict, retrieved_at: datetime) -> dict:
    """One harvested row as a `properties` row, through the OTC record
    contract (OtcRecord.validate() refuses anything it cannot store).
    Identity: case_no = the CAD account (as Texas rows always store it), and
    parcel = the same account - the cause / suit number is a lawsuit, never a
    parcel, and rides in otc_provenance.cause_number."""
    import sys as _sys  # noqa: PLC0415
    _sys.path.insert(0, str(HERE.parent))
    from harvesters.otc.model import AmountKind, InventoryType, OtcRecord, SourceAuthority  # noqa: PLC0415
    sid = row["harvester_source"]
    auction = row["source"] == "auction"
    kind = AMOUNT_KIND_FOR.get(sid, "NOT_PUBLISHED")
    amount = row.get("min_bid") if row.get("min_bid") is not None else row.get("struck_off_amount")
    if amount is None or kind == "NOT_PUBLISHED":
        amount, kind = None, "NOT_PUBLISHED"
    list_url = LIST_PAGES[sid]
    doc = row.get("sale_list_url")
    as_of = _iso_date(row.get("list_as_of"))
    prov = {k: row[k] for k in PROVENANCE_EXTRAS if row.get(k) not in (None, "", [])}
    prov.update({"adapter": "tx_county_sales", "harvester": "scripts/harvest_tx_county_sales.py"})
    if as_of is not None:
        prov["list_as_of"] = "the list's own date line"
    rec = OtcRecord(
        state="TX", county=row["county"], case_no=row["account_number"], source_id=sid,
        source_authority=SourceAuthority.GOVERNMENT_DIRECT,
        inventory_type=None if auction else InventoryType.STRUCK_OFF_HELD_IN_TRUST,
        retrieved_at=retrieved_at, parcel=row["account_number"], address=row.get("address") or None,
        legal_desc=row.get("legal_description") or None, market=row.get("cad_market_value"),
        amount=amount, amount_kind=AmountKind(kind), list_url=list_url,
        document_url=doc if doc and doc != list_url else None, list_as_of=as_of,
        source_status_text=row.get("sale_status") if sid in SOURCE_STATUS_WORDING else None,
        provenance=prov, record_source="auction" if auction else "laft",
        sale_date=_iso_date(row.get("auction_date")) if auction else None)
    out = rec.to_properties_row()
    if auction and (row.get("auction_url") or "").startswith("https://"):
        # The sale's own listing page (the county's sale list, not a purchase page).
        out["url_auction"] = row["auction_url"]
        out["url_auction_kind"] = row.get("auction_url_kind") or "sale"
    return out


def to_properties_rows(rows: list[dict], retrieved_at: datetime) -> tuple[list[dict], int]:
    """(properties rows, refused count). A row the record contract refuses is
    counted, never written; a duplicate identity (one account listed twice)
    keeps the first."""
    out, refused, seen = [], 0, set()
    for r in rows:
        try:
            pr = to_properties_row(r, retrieved_at)
        except (ValueError, KeyError):
            refused += 1
            continue
        key = (pr["source"], pr["county"], pr["case_no"])
        if key in seen:
            continue
        seen.add(key)
        out.append(pr)
    return out, refused


# ---------------------------------------------------------------- driver

SOURCES = (
    # (county, source_id, dataset, harvest fn, ledger)
    ("Harris", "tx_hctax", AUCTION_DATASET, harvest_harris, "AUCTIONS"),
    ("Bexar", "tx_bexar_resale", AVAILABLE_DATASET, harvest_bexar, "AVAILABLE"),
    ("Jefferson", "tx_jefferson_sheriff_sale", AUCTION_DATASET, harvest_jefferson, "AUCTIONS"),
    ("Montgomery", "tx_montgomery_tax_trust", AVAILABLE_DATASET, harvest_montgomery, "AVAILABLE"),
    ("Orange", "tx_orange_trust_property", AVAILABLE_DATASET, harvest_orange_tx, "AVAILABLE"),
    ("Trinity", "tx_trinity_cad_resale", AVAILABLE_DATASET, harvest_trinity, "AVAILABLE"),
    ("Randall", "tx_randall_trustee_property", AVAILABLE_DATASET, harvest_randall, "AVAILABLE"),
    ("Hood", "tx_hood_cad_struck_off", AVAILABLE_DATASET, harvest_hood, "AVAILABLE"),
)

SOURCE_IDS = tuple(s[1] for s in SOURCES)


def classify(rows: list[dict], meta: dict) -> tuple[str, str | None]:
    if meta.get("rejected"):
        return "INCOMPLETE", "PARSE_FORMAT_CHANGE"
    if rows:
        return "COMPLETE", None
    if meta.get("empty_list"):
        return "EMPTY", None
    return "INCOMPLETE", "UNCONFIRMED_EMPTY"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--only", action="append", help="limit to these source ids")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = UA
    all_rows: list[dict] = []
    rows_by_ledger: dict[str, list[dict]] = {k: [] for k in LEDGER_FILES}
    recorders: dict[str, StatusRecorder] = {}
    for county, source_id, dataset, fn, ledger in SOURCES:
        if args.only and source_id not in args.only:
            continue
        rec = recorders.setdefault(source_id, StatusRecorder(HARVESTER + ":" + source_id, source_id=source_id,
                                                            source_class="GOVERNMENT_DIRECT", state="TX",
                                                            path=out_dir / LEDGER_FILES[ledger][1]))
        print(f"{county} ({source_id}, {ledger})", flush=True)
        denied = [op for op in ("fetch", "parse")
                  if not _LS.permission(source_id, op, state="TX", county=county, dataset=dataset).allowed]
        if denied:
            print(f"    ::error title={source_id}::{'/'.join(denied)} not permitted - 0 requests", flush=True)
            rec.failed(county, "PERMISSION_DENIED", f"{'/'.join(denied)} not permitted")
            continue
        try:
            try:
                rows, meta, url = fn(session)
            except (requests.ConnectionError, requests.Timeout):
                time.sleep(RETRY_DELAY_S)  # one polite retry of a dropped connection, nothing more
                rows, meta, url = fn(session)
        except Exception as exc:  # noqa: BLE001 - categorised, never a silent zero
            category, _ = describe_exception(exc)
            print(f"    ERROR ({category}): {type(exc).__name__}: {str(exc)[:160]}", flush=True)
            rec.failed(county, exc)
            continue
        status, category = classify(rows, meta)
        shown = {k: v for k, v in meta.items() if k not in ("list_as_of",)}
        print(f"    {len(rows)} rows; {json.dumps(shown, sort_keys=True)} -> {status}", flush=True)
        if status == "COMPLETE":
            rec.complete(county, len(rows), source_url=url)
        elif status == "EMPTY":
            rec.empty(county, "empty_list", source_url=url)
        else:
            rec.incomplete(county, category, f"{meta.get('rejected', 0)} line(s) not parsed", row_count=len(rows),
                           source_url=url)
        all_rows.extend(rows)
        rows_by_ledger[ledger].extend(rows)
    for rec in recorders.values():
        rec.write()
        print(rec.summary_line(), flush=True)
    retrieved_at = datetime.now(timezone.utc)
    for ledger, (harvest_name, _status) in LEDGER_FILES.items():
        (out_dir / harvest_name).write_text(json.dumps(rows_by_ledger[ledger], indent=2), encoding="utf-8")
        prows, refused = to_properties_rows(rows_by_ledger[ledger], retrieved_at)
        (out_dir / PROPERTIES_ROWS_FILES[ledger]).write_text(json.dumps(prows, indent=2), encoding="utf-8")
        print(f"{ledger}: {len(prows)} properties row(s) for the sync; {refused} refused by the record contract", flush=True)
    by = {}
    for r in all_rows:
        by[(r["harvester_source"], r["county"], r["source"])] = by.get((r["harvester_source"], r["county"], r["source"]), 0) + 1
    for (sid, county, ledger), n in sorted(by.items()):
        print(f"ROWS {sid} {county} {ledger}: {n}", flush=True)
    print(f"Harvested {len(all_rows)} Texas county-list rows -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
