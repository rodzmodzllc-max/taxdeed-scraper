#!/usr/bin/env python3
"""READ-ONLY structural capture: where do Pioneer TaxSmartWeb counties publish
the per-case Lands Available purchase statement ("List of Lands" / "Total Due
from Purchaser")?

2026-10-05, customer report: the Citrus clerk's statement for case
2024-0075TD reads "Total Due from Purchaser $27,689.42 ... IF RECEIVED BY
8/31/2026", while the app stores only the grid's "Base Bid" ($2,606.70). The
grid endpoint (scripts/harvest_laft_pioneer.py) carries no total. This script
finds - without guessing - the page or document chain from a grid row to that
statement, so a harvester can be written against the real structure.

What it does, per county in data/laft_pioneer_counties.csv that has Lands
Available rows (at most ONE row per county is followed):
  1. the grid JSON: row entry keys, cell count, id SHAPE (digits masked);
  2. the portal page: every app-relative URL referenced in its scripts and
     links, masked (digits -> 9), plus query parameter NAMES only;
  3. URLs that look like a per-row detail / document endpoint are requested
     with the row's id or case number: status, content type, size, and for
     HTML the document-like links on it (masked);
  4. one PDF reached that way: which statement LABELS appear ("Total Due from
     Purchaser", "IF RECEIVED BY", "Lands Available Total", ...) and the
     SHAPE of the figure next to each - never a value.

Prints only shapes, labels and status codes. Writes nothing; no database
credential exists in the job that runs it.
"""
from __future__ import annotations

import csv
import io
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qsl

import requests

HERE = Path(__file__).resolve().parent
SOURCES = HERE / "../data/laft_pioneer_counties.csv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
GRID = "Home/GridSearchData"
DOC_WORDS = re.compile(r"detail|document|doc|image|pdf|view|case|statement|lol|land|file|attach|report", re.I)
LABELS = [
    "Total Due from Purchaser", "IF RECEIVED BY", "Lands Available Total", "LOL Total", "Opening Bid",
    "Lands Available Interest", "Omitted Taxes", "Total Omitted Taxes", "Documentary Stamp Tax",
    "Deed Recording Fee", "TOTAL AMOUNT OF TAXES DUE", "List of Lands",
]


def mask(text: str) -> str:
    return re.sub(r"\d", "9", text)


def shape_after(text: str, label: str) -> str:
    m = re.search(re.escape(label) + r"[^\n$0-9]{0,40}(\$?\s?[\d,]+\.\d{2}|\d{1,2}/\d{1,2}/\d{4})", text, re.I)
    return mask(m.group(1)) if m else "-"


def app_urls(html: str) -> list[str]:
    found = set()
    for m in re.finditer(r"""["'](\.{0,2}/?[A-Za-z][A-Za-z0-9_]*/[A-Za-z][A-Za-z0-9_]*(?:\?[^"'\s<>]*)?)["']""", html):
        u = m.group(1)
        if u.lower().startswith(("http", "text/", "application/", "image/")) or u.count("/") > 3:
            continue
        found.add(u)
    for m in re.finditer(r"""(?:href|src|action)\s*=\s*["']([^"'#]+)["']""", html, re.I):
        u = m.group(1)
        if DOC_WORDS.search(u) and not u.lower().startswith(("http://", "https://", "mailto:", "javascript:")):
            found.add(u)
    return sorted(found)


def describe_url(u: str) -> str:
    p = urlparse(u)
    names = [k for k, _ in parse_qsl(p.query, keep_blank_values=True)]
    return mask(p.path) + (f" ?{','.join(names)}" if names else "")


def pdf_labels(blob: bytes) -> str:
    try:
        import pdfplumber
    except ImportError:
        return "pdfplumber not installed"
    try:
        with pdfplumber.open(io.BytesIO(blob)) as pdf:
            text = "\n".join((pg.extract_text() or "") for pg in pdf.pages[:6])
            pages = len(pdf.pages)
    except Exception as exc:  # noqa: BLE001
        return f"pdf unreadable ({type(exc).__name__})"
    if not text.strip():
        return f"{pages} page(s), no text layer (scanned)"
    hits = [f"{lab}={shape_after(text, lab)}" for lab in LABELS if lab.lower() in text.lower()]
    return f"{pages} page(s), text {len(text)} chars; labels: " + ("; ".join(hits) if hits else "none of the statement labels")


# Pass 2 (2026-10-05, after run 37247820926 showed Details?id=<row id> ->
# Home/Image/<doc id> links and a SCANNED first document): which docket
# entry is the statement, what the Details page itself labels, and whether
# OCR can read the statement. Docket descriptors are printed through a
# document-type vocabulary only - any other token (a name, an address) prints
# as "~" - so nothing personal can reach the public log.
DOC_VOCAB = set("""TAX DEED APPLICATION APPLICATIONS LIST OF LANDS LAND AVAILABLE FOR TAXES STATEMENT NOTICE NOTICES CERTIFICATE
CERTIFICATES CERTIFIED MAIL RETURN RECEIPT RECEIPTS PROOF PUBLICATION AFFIDAVIT SALE SALES TITLE SEARCH REPORT OWNERSHIP
ENCUMBRANCE O&E OE BID BIDS BIDDER RESULTS RESULT REDEMPTION REDEEMED PAYMENT PAYMENTS AMOUNT TOTAL DUE PURCHASER
OPENING INVOICE FEE FEES SHERIFF SERVICE SERVED NON-SERVICE NONSERVICE ADDRESS PROPERTY PROPERTIES INFORMATION
INFO LETTER LETTERS MAILING MAILINGS POSTED POSTING AD ADVERTISEMENT AD. LEGAL COPY COPIES ORDER RECEIPTED
TD TDA CANCEL CANCELLED CANCELED ESCHEAT ESCHEATED SURPLUS COUNTY CLERK TAXES OMITTED INTEREST DELINQUENT
NOTICE: WORKSHEET CALCULATION SUMMARY AND TO THE ON IN A AT BY FROM HOMESTEAD LOL DOCKET DOCUMENT DOC IMAGE
PAGE PAGES MISC MISCELLANEOUS UNSERVED RETURNED UNDELIVERABLE GREEN CARD CARDS ADS PUBLISH PUBLISHED""".split())
STATEMENT_WORDS = re.compile(r"LIST\s+OF\s+LANDS|LANDS\s+AVAILABLE|STATEMENT|TOTAL\s+DUE|INVOICE|WORKSHEET|CALCULATION", re.I)
MONEY_LABEL = re.compile(r"([A-Za-z][A-Za-z .#/&()-]{2,40}?)\s*:?\s*</t[dh]>\s*<td[^>]*>\s*\$?\s*-?[\d,]+\.\d{2}", re.I)
TERMS = re.compile(r"[^.<>]{0,160}\b(disclaimer|terms of use|copyright|commercial|not responsible|no warrant|reproduc|resale|redistribut|unofficial|official record)[^.<>]{0,160}", re.I)


def vocab_only(text: str) -> str:
    out = []
    for tok in re.sub(r"<[^>]+>", " ", text).split():
        t = tok.strip(",;:()[]").upper()
        if re.fullmatch(r"[\d/.-]+", t):
            out.append(mask(t))
        else:
            out.append(t if t in DOC_VOCAB else "~")
    return re.sub(r"(~ )+~", "~", " ".join(out))[:120]


def ocr_labels(blob: bytes, max_pages: int = 3) -> str:
    try:
        import pdfplumber
        import pytesseract
    except ImportError as exc:
        return f"OCR unavailable ({exc.name})"
    try:
        with pdfplumber.open(io.BytesIO(blob)) as pdf:
            texts = []
            for pg in pdf.pages[:max_pages]:
                img = pg.to_image(resolution=200).original
                texts.append(pytesseract.image_to_string(img))
            text = "\n".join(texts)
    except Exception as exc:  # noqa: BLE001
        return f"OCR failed ({type(exc).__name__})"
    hits = [f"{lab}={shape_after(text, lab)}" for lab in LABELS if lab.lower() in text.lower()]
    return f"OCR {min(max_pages, 99)} page(s), {len(text)} chars; labels: " + ("; ".join(hits) if hits else "none of the statement labels")


def details_pass(s: requests.Session, base: str, row_id: str) -> None:
    url = urljoin(base, f"Home/Details?id={row_id}")
    try:
        r = s.get(url, timeout=30)
    except Exception as exc:  # noqa: BLE001
        print(f"  details: {type(exc).__name__}")
        return
    html = r.text
    labels = sorted({mask(m.group(1).strip()) for m in MONEY_LABEL.finditer(html)})
    print(f"  details {r.status_code}: money labels on the page: {labels or 'none'}")
    heads = sorted({vocab_only(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", html, re.I | re.S) if h.strip()})
    print(f"  details table headers: {heads}")
    for m in TERMS.finditer(html):
        snippet = mask(re.sub(r"\s+", " ", m.group(0)).strip())[:300]
        print(f"  terms text: {snippet}")
    docs = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S):
        link = re.search(r"""href\s*=\s*["']([^"']*Image/\d+)["']""", tr, re.I)
        if link:
            docs.append((link.group(1), vocab_only(tr)))
    print(f"  docket documents: {len(docs)}")
    for href, desc in docs:
        print(f"    doc {describe_url(href)} :: {desc}")
    picked = [(h, d) for h, d in docs if STATEMENT_WORDS.search(d)]
    print(f"  statement-like documents: {len(picked)}")
    for href, desc in picked[:2]:
        try:
            d = s.get(urljoin(url, href), timeout=60)
        except Exception as exc:  # noqa: BLE001
            print(f"    fetch failed: {type(exc).__name__}")
            continue
        ctype = d.headers.get("Content-Type", "")
        print(f"    {desc}: {d.status_code} {ctype[:30]} {len(d.content)} bytes")
        if "pdf" in ctype.lower():
            info = pdf_labels(d.content)
            print(f"      text layer: {info}")
            if "no text layer" in info or "none of the statement labels" in info:
                print(f"      {ocr_labels(d.content)}")


def main() -> int:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    rows = list(csv.DictReader(open(SOURCES, newline="", encoding="utf-8")))
    for src in rows:
        county, base = src["County"], src["BaseUrl"].rstrip("/") + "/"
        print(f"\n=== {county} ({mask(urlparse(base).netloc)}{urlparse(base).path}) ===", flush=True)
        try:
            g = s.get(urljoin(base, GRID), params={"SearchType": "Lands Available", "_search": "false", "rows": "100", "page": "1", "sidx": "", "sord": "asc"},
                      headers={"X-Requested-With": "XMLHttpRequest"}, timeout=30)
            payload = g.json()
        except Exception as exc:  # noqa: BLE001
            print(f"  grid: {type(exc).__name__}")
            continue
        recs = payload.get("rows") or []
        print(f"  grid: records={payload.get('records')} rows={len(recs)} top-level keys={sorted(payload.keys())}")
        if not recs:
            continue
        first = recs[0]
        if isinstance(first, dict):
            print(f"  row keys={sorted(first.keys())} id shape={mask(str(first.get('id')))} cells={len(first.get('cell') or [])}")
        row_id = str(first.get("id")) if isinstance(first, dict) and first.get("id") is not None else ""
        cells = (first.get("cell") if isinstance(first, dict) else first) or []
        case_no = str(cells[1]).strip() if len(cells) > 1 else ""
        print(f"  case shape={mask(case_no)}")

        try:
            page = s.get(base, timeout=30)
            html = page.text
        except Exception as exc:  # noqa: BLE001
            print(f"  portal page: {type(exc).__name__}")
            continue
        urls = app_urls(html)
        print(f"  portal page {page.status_code}, {len(html)} bytes; app URLs referenced ({len(urls)}):")
        for u in urls:
            print(f"    {describe_url(u)}")
        handlers = sorted(set(re.findall(r"(onSelectRow|ondblClickRow|formatter\s*:\s*[A-Za-z_]+|window\.open|location\.href)", html)))
        print(f"  grid handlers/navigation present: {handlers}")
        for m in re.finditer(r"(window\.open|location\.href\s*=)\s*\(?\s*([^;]{0,160})", html):
            print(f"    nav expr: {mask(m.group(2)).strip()[:160]}")

        if row_id:
            details_pass(s, base, row_id)
            continue  # pass 1's generic probing already ran (run 37247820926)

        tried = 0
        for u in urls:
            if tried >= 6 or not DOC_WORDS.search(u) or GRID.lower() in u.lower():
                continue
            for val in [v for v in (row_id, case_no) if v]:
                if "=" in u and u.endswith("="):
                    target = urljoin(base, u + val)
                elif "?" not in u:
                    target = urljoin(base, u) + f"?id={val}"
                else:
                    target = urljoin(base, u)
                tried += 1
                try:
                    r = s.get(target, timeout=30)
                except Exception as exc:  # noqa: BLE001
                    print(f"    try {describe_url(u)} [{'id' if val == row_id else 'case'}]: {type(exc).__name__}")
                    continue
                ctype = r.headers.get("Content-Type", "")
                print(f"    try {describe_url(u)} [{'id' if val == row_id else 'case'}]: {r.status_code} {ctype[:40]} {len(r.content)} bytes")
                if "pdf" in ctype.lower():
                    print(f"      PDF: {pdf_labels(r.content)}")
                elif "html" in ctype.lower() and r.status_code == 200:
                    links = [l for l in re.findall(r"""(?:href|src)\s*=\s*["']([^"']+)["']""", r.text) if DOC_WORDS.search(l)]
                    for l in sorted(set(links))[:12]:
                        print(f"      link: {describe_url(l)}")
                    for l in sorted(set(links)):
                        if ".pdf" in l.lower() or "document" in l.lower() or "image" in l.lower():
                            try:
                                d = s.get(urljoin(target, l), timeout=40)
                                if "pdf" in d.headers.get("Content-Type", "").lower():
                                    print(f"      followed {describe_url(l)}: PDF {pdf_labels(d.content)}")
                                    break
                            except Exception as exc:  # noqa: BLE001
                                print(f"      follow failed: {type(exc).__name__}")
                break
    return 0


if __name__ == "__main__":
    sys.exit(main())
