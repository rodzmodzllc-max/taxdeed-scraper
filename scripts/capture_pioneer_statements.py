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
