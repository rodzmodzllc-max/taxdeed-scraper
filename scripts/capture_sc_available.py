#!/usr/bin/env python3
"""Read-only STRUCTURAL capture of the two South Carolina Forfeited Land
Commission sources (2026-10-02, feat/sc-available-inventory):

  * Georgetown County - the FLC program page, its terms / disclaimer pages and
    the "2026 FLC LIST" PDF;
  * Spartanburg County - the FLC program page, its terms / disclaimer pages and
    the "Real-Estate Tax Sale List" PDF.

It runs only as the manual evidence job (`job=evidence`,
`evidence_scope=sc_available`). No database credential reaches it and it
writes nothing anywhere except out/public/sc-available-structure.json, which
the job prints and uploads. The PDFs and pages are held in memory only.

What may be printed (and nothing else):
  * terms / disclaimer wording and the program page's own availability /
    process wording - county-written sentences, read with every <table>
    removed, dropped whole if they carry a digit run, a dollar amount or an
    e-mail address;
  * source titles, URLs, HTTP status, read time, Last-Modified;
  * the PDF's heading and column-header lines - ONLY lines whose every word is
    in HEADING_WORDS (so a name, an address or a legal description can never
    pass), years kept, every other digit masked;
  * header-word x positions, row / table / line COUNTS, identifier SHAPES
    (every digit -> 9, every letter -> A), keyword counts, year counts;
  * the SC FLC parser's own counts (harvesters/otc/adapters/sc_flc.py) when it
    can run: rows, valid / invalid identifiers by category, sections - never a
    row, an identifier or a name.

Never printed: an owner name, an address, a TMS / MAP number, a raw row, raw
PDF text, a snippet of the document body. tests/python/test_sc_available.py
feeds this script a document full of names, addresses and identifiers and
proves none of them reaches its output.

    python3 scripts/capture_sc_available.py            # live (evidence job only)
    python3 scripts/capture_sc_available.py --digest out/public/sc-available-structure.json
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
OUT_PATH = REPO / "out" / "public" / "sc-available-structure.json"

PAGE_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9"}

# The two sources of this sprint. URLs are the ones the discovery read
# recorded (data/available_discovery_evidence.csv, data/available_discovery_pages.csv).
SOURCES = (
    {"source_id": "sc_georgetown_forfeited_land", "county": "Georgetown",
     "program_url": "https://www.gtcountysc.gov/415/Forfeited-Land-Commission",
     "document_url": "https://www.gtcountysc.gov/DocumentCenter/View/3019/2026-FLC-LIST---UPDATED-MAY-2026-PDF"},
    {"source_id": "sc_spartanburg_forfeited_land", "county": "Spartanburg",
     "program_url": "https://www.spartanburgcounty.org/388/Forfeited-Land-Commission",
     "document_url": "https://www.spartanburgcounty.gov/DocumentCenter/View/104130/Real-Estate-Tax-Sale-List"},
)

# ---- privacy filters ---------------------------------------------------------
YEAR = re.compile(r"\b(?:19|20)\d\d\b")
ROW_LIKE = re.compile(r"\d[\d\-./,]{2,}|\$\s*\d|@")


def row_like(text: str) -> bool:
    """A digit run (identifier, amount, phone, date), a dollar amount or an
    e-mail address anywhere in the text. A year alone is not row-like."""
    return bool(ROW_LIKE.search(YEAR.sub("", text or "")))


def mask(text: str) -> str:
    """Every digit -> 9 except a year."""
    years = {m.start(): m.group(0) for m in YEAR.finditer(text)}
    out, i = [], 0
    while i < len(text):
        if i in years:
            out.append(years[i])
            i += 4
            continue
        out.append("9" if text[i].isdigit() else text[i])
        i += 1
    return "".join(out)


def shape(token: str) -> str:
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", token))


# Every word a heading / column-header line may consist of. A line with any
# other word is never printed - that is what keeps names and addresses out.
HEADING_WORDS = frozenset("""
a account acreage acres address amount and as assessed assignment available best bid bids by claim commission
county current date deed defaulting description district due estate flc for forfeited from georgetown grantee group home
homes in included item known land list location map minimum mobile name needed no not number of on opening or owner page
parcel period personal prior properties property quit real redemption sale sales sealed serial south spartanburg spartanburgs
status tax taxes taxpayer the tms to total updated value vin year years carolina notes per sold redeemed withdrawn pending
january february march april may june july august september october november december
""".split())


def heading_line(line: str) -> bool:
    words = re.findall(r"[A-Za-z]+", line or "")
    if not words or len(words) > 16:
        return False
    if re.sub(r"[A-Za-z#()\-/:&.,'\s]", "", YEAR.sub("", line)):  # only letters, years and punctuation
        return False
    return all(w.lower() in HEADING_WORDS for w in words)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def sentences(text: str):
    for s in re.split(r"(?<=[.!?])\s+", clean(text)):
        if 25 <= len(s) <= 400:
            yield s


# Program-page wording that decides AVAILABLE semantics / the acquisition path.
AVAIL_VOCAB = re.compile(r"forfeited land|assign|redemption|redeem|quit[- ]?claim|sealed bid|bid form|application|purchase|"
                         r"available|offer|deed|certified|cash|first come|in person|mail|monthly|meeting|approve|vote", re.I)
# Terms / publication wording.
TERMS_VOCAB = re.compile(r"copyright|reproduc|republi|redistribut|commercial|permission|licen[cs]|terms|disclaim|warrant|"
                         r"accura|liab|public record|freedom of information|foia|attribut|restrict|prohibit|property of", re.I)
TERMS_LINK = re.compile(r"terms|disclaimer|policy|policies|copyright|legal|privacy|site info", re.I)
FORM_LINK = re.compile(r"application|form|bid|assignment|flc|forfeited|list|procedure|process|instructions", re.I)
PHONE = re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-.]\d{4}\b")
MAX_SENTENCES, MAX_TERMS_PAGES = 30, 4


def html_wording(html: str, url: str) -> dict:
    """County-written wording on a web page - never a table cell."""
    from bs4 import BeautifulSoup  # noqa: PLC0415
    soup = BeautifulSoup(html, "html.parser")
    title = clean(soup.title.get_text()) if soup.title else ""
    links = []
    for a in soup.find_all("a", href=True):
        text, href = clean(a.get_text(" ")), urljoin(url, a["href"].strip())
        if href.startswith("https://") and (FORM_LINK.search(text) or TERMS_LINK.search(text)) \
                and not re.search(r"\d{7,}", href) and not row_like(text):
            links.append({"text": text[:100], "href": href})
    for t in soup(["table", "script", "style", "noscript", "form", "select"]):
        t.decompose()
    body = soup.get_text(" ")
    avail = [s for s in sentences(body) if AVAIL_VOCAB.search(s) and not row_like(s)]
    terms = [s for s in sentences(body) if TERMS_VOCAB.search(s) and not row_like(s)]
    # A phone number is never printed (it may be a person's direct line); only
    # whether the page publishes one.
    phones = len({m.group(0) for m in PHONE.finditer(body)})
    return {"title": mask(title)[:160], "availability_wording": list(dict.fromkeys(avail))[:MAX_SENTENCES],
            "terms_wording": list(dict.fromkeys(terms))[:MAX_SENTENCES], "links": links[:40], "phone_numbers_on_page": phones}


# ---- PDF structure -----------------------------------------------------------
KEYWORDS = ("assignment", "redemption", "redeemed", "quit claim", "quitclaim", "sealed bid", "mobile home", "real estate",
            "sold", "withdrawn", "pending", "available", "opening bid", "bid amount", "forfeited land", "personal property")
# Identifier-shaped tokens: digit groups joined by - or . (TMS / map numbers),
# or a long digit run.
ID_TOKEN = re.compile(r"(?<![\w$.,])(?:\d{1,5}(?:[-.]\d{1,6}){2,7}|\d{9,})(?![\w])")
AMOUNT = re.compile(r"\$\s?\d[\d,]*(?:\.\d\d)?|\b\d{1,3}(?:,\d{3})+\.\d\d\b|\b\d+\.\d\d\b")


def pdf_structure(pdf) -> dict:
    """Structure of an opened pdfplumber document (or any object with the same
    page methods). Counts, shapes, headings and header-word positions only."""
    pages = list(pdf.pages)
    out = {"pages": len(pages), "lines": 0, "headings": Counter(), "header_words": [], "tables": [],
           "id_shapes": Counter(), "id_tokens": 0, "id_lines": 0, "amount_tokens": 0, "years": Counter(),
           "keywords": Counter(), "sections": []}
    section = None
    for pno, page in enumerate(pages, 1):
        text = page.extract_text() or ""
        lines = [clean(l) for l in text.splitlines() if clean(l)]
        out["lines"] += len(lines)
        low = text.lower()
        for k in KEYWORDS:
            out["keywords"][k] += low.count(k)
        out["years"].update(m.group(0) for m in YEAR.finditer(text))
        for line in lines:
            ids = ID_TOKEN.findall(line)
            if heading_line(line):
                h = mask(line)[:120]
                out["headings"][h] += 1
                section = {"heading": h, "page": pno, "id_lines": 0}
                out["sections"].append(section)
            if ids:
                out["id_lines"] += 1
                out["id_tokens"] += len(ids)
                out["id_shapes"].update(shape(t) for t in ids)
                if section is not None:
                    section["id_lines"] += 1
            out["amount_tokens"] += len(AMOUNT.findall(line))
        try:
            words = page.extract_words() or []
        except Exception:  # noqa: BLE001 - structure only; a page that cannot be split is counted, not read
            words = []
        if pno <= 3:
            for w in words:
                t = w.get("text", "")
                if t.lower().strip("#():") in HEADING_WORDS and len(out["header_words"]) < 120:
                    out["header_words"].append({"page": pno, "word": t[:24], "x0": round(float(w.get("x0", 0))),
                                                "top": round(float(w.get("top", 0)))})
        try:
            tables = page.extract_tables() or []
        except Exception:  # noqa: BLE001
            tables = []
        for ti, tbl in enumerate(tables):
            rows = [r for r in tbl if r and any((c or "").strip() for c in r)]
            header = next((r for r in rows if all(heading_line(clean(c or "")) or not clean(c or "") for c in r)
                           and any(clean(c or "") for c in r)), None)
            id_cols = Counter()
            for r in rows:
                for ci, c in enumerate(r):
                    if ID_TOKEN.fullmatch(clean(c or "")):
                        id_cols[ci] += 1
            out["tables"].append({"page": pno, "table": ti, "rows": len(rows), "columns": max((len(r) for r in rows), default=0),
                                  "header": [mask(clean(c or ""))[:40] for c in header] if header else None,
                                  "id_cells_by_column": dict(id_cols)})
    out["headings"] = dict(out["headings"].most_common(40))
    out["id_shapes"] = dict(out["id_shapes"].most_common(12))
    out["years"] = dict(sorted(out["years"].items()))
    out["keywords"] = {k: v for k, v in out["keywords"].items() if v}
    out["sections"] = out["sections"][:60]
    out["tables"] = out["tables"][:80]
    return out


def pdf_meta(pdf) -> dict:
    meta = getattr(pdf, "metadata", None) or {}
    title = clean(str(meta.get("Title") or ""))
    return {"title": mask(title)[:120] if heading_line(title) else ("(not printed)" if title else "")}


# ---- capture -----------------------------------------------------------------
def fetch(session, url: str):
    try:
        r = session.get(url, headers=PAGE_HEADERS, timeout=60)
        return r, None
    except Exception as exc:  # noqa: BLE001 - transport failure is reported, never read as empty
        return None, type(exc).__name__


def capture_source(session, src: dict, *, parser=None) -> dict:
    now = lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat()  # noqa: E731
    res = {"source_id": src["source_id"], "county": src["county"], "program": {}, "terms_pages": [], "document": {}}
    r, err = fetch(session, src["program_url"])
    res["program"] = {"url": src["program_url"], "read_at": now(), "http_status": r.status_code if r is not None else None,
                      "error": err}
    terms_links = []
    if r is not None and r.ok and "html" in r.headers.get("content-type", "").lower():
        w = html_wording(r.text, src["program_url"])
        res["program"].update(w)
        host = urlsplit(src["program_url"]).hostname
        terms_links = [l["href"] for l in w["links"] if TERMS_LINK.search(l["text"]) and urlsplit(l["href"]).hostname == host]
    for url in list(dict.fromkeys(terms_links))[:MAX_TERMS_PAGES]:
        tr, terr = fetch(session, url)
        page = {"url": url, "read_at": now(), "http_status": tr.status_code if tr is not None else None, "error": terr}
        if tr is not None and tr.ok and "html" in tr.headers.get("content-type", "").lower():
            w = html_wording(tr.text, url)
            page.update({"title": w["title"], "terms_wording": w["terms_wording"]})
        res["terms_pages"].append(page)
    d, derr = fetch(session, src["document_url"])
    doc = {"url": src["document_url"], "read_at": now(), "http_status": d.status_code if d is not None else None, "error": derr}
    if d is not None and d.ok:
        doc.update({"content_type": d.headers.get("content-type", ""), "bytes": len(d.content),
                    "last_modified": d.headers.get("last-modified")})
        doc.update(analyse_pdf(d.content, src, parser=parser))
    res["document"] = doc
    return res


def analyse_pdf(data: bytes, src: dict, *, parser=None, opener=None) -> dict:
    if not data.startswith(b"%PDF"):
        return {"pdf": False}
    try:
        import pdfplumber  # noqa: PLC0415
        opener = opener or (lambda b: pdfplumber.open(io.BytesIO(b)))
        with opener(data) as pdf:
            out = {"pdf": True, **pdf_meta(pdf), "structure": pdf_structure(pdf)}
    except Exception as exc:  # noqa: BLE001
        return {"pdf": True, "error": type(exc).__name__}
    if parser is not None:
        try:
            out["parser"] = parser(src["source_id"], data)
        except Exception as exc:  # noqa: BLE001 - a parser failure is a finding, never a row
            out["parser"] = {"error": type(exc).__name__}
    return out


def parser_summary(source_id: str, data: bytes) -> dict:
    """The adapter's own counts against the live document (never a row)."""
    from harvesters.otc.adapters import sc_flc  # noqa: PLC0415
    return sc_flc.summary(sc_flc.parse_document(source_id, data, retrieved_at=datetime.now(timezone.utc)))


def digest(path: Path) -> str:
    doc = json.loads(path.read_text(encoding="utf-8"))
    out = [f"SC FLC structural capture  generated={doc.get('generated_at')}"]
    for s in doc.get("sources", []):
        out.append(f"== {s['county']} ({s['source_id']})")
        p = s.get("program", {})
        out.append(f"  program {p.get('http_status')} {p.get('url')} read_at={p.get('read_at')} title={p.get('title')!r}")
        for x in p.get("availability_wording", []):
            out.append(f"    avail: {x}")
        for x in p.get("terms_wording", []):
            out.append(f"    terms: {x}")
        for l in p.get("links", []):
            out.append(f"    link: {l['text']!r} -> {l['href']}")
        if p.get("phone_numbers_on_page") is not None:
            out.append(f"    phone numbers on the page: {p['phone_numbers_on_page']} (not printed)")
        for t in s.get("terms_pages", []):
            out.append(f"  terms page {t.get('http_status')} {t.get('url')} title={t.get('title')!r}")
            for x in t.get("terms_wording", []):
                out.append(f"    terms: {x}")
        d = s.get("document", {})
        out.append(f"  document {d.get('http_status')} {d.get('url')} type={d.get('content_type')} bytes={d.get('bytes')} "
                   f"last_modified={d.get('last_modified')} read_at={d.get('read_at')} pdf_title={d.get('title')!r}")
        st = d.get("structure") or {}
        if st:
            out.append(f"    pages={st['pages']} lines={st['lines']} id_lines={st['id_lines']} id_tokens={st['id_tokens']} "
                       f"amount_tokens={st['amount_tokens']}")
            out.append(f"    id_shapes={st['id_shapes']}")
            out.append(f"    years={st['years']}")
            out.append(f"    keywords={st['keywords']}")
            for h, n in st["headings"].items():
                out.append(f"    heading x{n}: {h}")
            for sec in st["sections"]:
                out.append(f"    section p{sec['page']}: {sec['heading']} -> id_lines={sec['id_lines']}")
            for t in st["tables"]:
                out.append(f"    table p{t['page']}#{t['table']} rows={t['rows']} cols={t['columns']} header={t['header']} "
                           f"id_cells_by_column={t['id_cells_by_column']}")
            hw = " ".join(f"{w['word']}@p{w['page']}x{w['x0']}y{w['top']}" for w in st["header_words"])
            out.append(f"    header words: {hw}")
        if d.get("parser"):
            out.append(f"    parser: {json.dumps(d['parser'], sort_keys=True)}")
        if d.get("error"):
            out.append(f"    error: {d['error']}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--digest")
    ap.add_argument("--out", default=str(OUT_PATH))
    a = ap.parse_args(argv)
    if a.digest:
        print(digest(Path(a.digest)))
        return 0
    import requests  # noqa: PLC0415
    session = requests.Session()
    try:
        from harvesters.otc.adapters import sc_flc  # noqa: F401,PLC0415
        parser = parser_summary
    except ImportError:
        parser = None
    report = {"generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
              "note": "Structural capture only: counts, shapes, whitelisted headings, county-written wording. No row, "
                      "name, address or identifier.",
              "sources": [capture_source(session, s, parser=parser) for s in SOURCES]}
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(report['sources'])} sources)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
