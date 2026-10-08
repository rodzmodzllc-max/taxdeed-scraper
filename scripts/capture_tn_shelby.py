#!/usr/bin/env python3
"""Read-only STRUCTURAL capture of the Shelby County, Tennessee candidate
sources (2026-10-08, Tennessee onboarding):

  * Shelby County Land Bank (county-owned, tax-sale-leftover parcels for sale)
    - the site, its FAQ, the scripts behind its map, and any ArcGIS REST layer
    those scripts or pages name (layer metadata and a record COUNT only);
  * Shelby County Chancery Court Clerk & Master tax sales - the Tax Sale
    Information page and the numbered sale-book PDFs it links;
  * City of Memphis Real Estate - city-owned parcels for sale.

It runs only as the manual evidence job (`job=evidence`,
`evidence_scope=tn_shelby`). No database credential reaches it and it writes
nothing anywhere except out/public/tn-shelby-structure.json, which the job
prints and uploads. Documents are held in memory only.

What may be printed (and nothing else):
  * page titles, HTTP status, final URL, Last-Modified, content type;
  * link HREFs on official hosts, and link TEXT only when every word is in
    SAFE_WORDS (otherwise "[text withheld]");
  * headings / PDF lines only when every word is in SAFE_WORDS (so an owner
    name, a street or a legal description can never pass), every non-year
    digit masked to 9;
  * script src hosts, ArcGIS / API endpoint URLs found in page or script
    source, ArcGIS layer name, geometry type, field names and types,
    maxRecordCount and a returnCountOnly count;
  * PDF page / line counts, identifier SHAPES (digit -> 9, letter -> A),
    keyword counts.

Never printed: a row, an owner or purchaser name, an address, a parcel
number, an amount, raw PDF text. tests/python/test_capture_tn_shelby.py feeds
this module text full of names, addresses and parcel numbers and proves none
of them reaches its output.

    python3 scripts/capture_tn_shelby.py            # live (evidence job only)
    python3 scripts/capture_tn_shelby.py --digest out/public/tn-shelby-structure.json
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

REPO = Path(__file__).resolve().parents[1]
OUT_PATH = REPO / "out" / "public" / "tn-shelby-structure.json"
UA = "taxdeed-scraper/1.0 (+https://github.com/rodzmodzllc-max/taxdeed-scraper; read-only structure capture)"

PAGES = [
    ("landbank_home", "https://landbank.shelbycountytn.gov/"),
    ("landbank_faq", "https://landbank.shelbycountytn.gov/faqs"),
    ("county_tax_sale_info", "https://www.shelbycountytn.gov/330/Tax-Sale-Information"),
    ("county_cm_process", "https://www.shelbycountytn.gov/DocumentCenter/View/42037/CandM-Info-On-Tax-Sale-Process-v2024"),
    ("county_landbank_flash_sale", "https://www.shelbycountytn.gov/DocumentCenter/View/44679/SHELBY-COUNTY-LAND-BANK-ANNOUNCES-FLASH-SALE-ON-SELECT-PROPERTIES"),
    ("memphis_real_estate", "https://www.memphistn.gov/real-estate"),
]
SALE_BOOKS = [
    "https://www.shelbycountytn.gov/DocumentCenter/View/45087/TX-2024TS2202SaleBook",
    "https://www.shelbycountytn.gov/DocumentCenter/View/44156/TX-2024TS2201SaleBook",
]
OFFICIAL_HOSTS = ("shelbycountytn.gov", "memphistn.gov", "arcgis.com", "zeusauction.com")
MAX_SCRIPTS = 8
MAX_LAYERS = 12
MAX_EXTRA_BOOKS = 2

YEAR = re.compile(r"\b(19|20)\d\d\b")
ENDPOINT = re.compile(r"https?://[A-Za-z0-9.\-]+/[A-Za-z0-9_./\-]*(?:FeatureServer|MapServer)(?:/\d+)?|"
                      r"https?://[A-Za-z0-9.\-]+/[A-Za-z0-9_./\-]*/(?:api|odata|services)/[A-Za-z0-9_./\-]*|"
                      r"https?://[A-Za-z0-9.\-]*arcgis\.com/[A-Za-z0-9_./\-?=&]*", re.I)

# A heading / PDF line / link text is printed only when EVERY word is here.
SAFE_WORDS = frozenset("""
a about account acres day days acreage address all amount an and any application applications apply appraisal appraised april
as at auction august available back bank be bid bidder bidders bids book business buy buyer by can city clerk click
code confirmed confirmation contact cost costs county court current date deadline december deed default defaulted
delinquent deposit description details document documents due enforcement estate faq faqs february filter flash for
form forms frequently from high how in info information into is january july june land landbank lease list listing
listings lot lots map march master may memphis minimum more name no not notice november number october of offer offers
on online opening or order owned owner page parcel parcels payment period policy price prices privacy procedure
procedures process program properties property purchase purchaser purchasers questions real redeem redeemed redemption
register registration results sale sales search september shelby sold status street structure structures suit tax taxes
terms the to total trustee type use vacant view website when with year years zeus zip
""".split())

KEYWORDS = ("redemption", "high bid", "purchaser", "confirm", "parcel", "minimum", "opening", "defaulted", "trustee",
            "price", "appraisal", "offer", "sealed", "zeus")


def mask(text: str) -> str:
    years = [(m.start(), m.end()) for m in YEAR.finditer(text)]
    out = []
    for i, ch in enumerate(text):
        if ch.isdigit() and not any(a <= i < b for a, b in years):
            out.append("9")
        else:
            out.append(ch)
    return "".join(out)


def shape(token: str) -> str:
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", token))


def safe_line(line: str) -> bool:
    words = re.findall(r"[A-Za-z]+", line or "")
    if not words or len(words) > 16:
        return False
    if re.sub(r"[A-Za-z0-9#()\-/:&.,'%$\s]", "", line):
        return False
    return all(w.lower() in SAFE_WORDS for w in words)


def safe_text(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if not text:
        return ""
    return mask(text) if safe_line(text) else "[text withheld]"


def official(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in OFFICIAL_HOSTS)


def pdf_structure(lines: list[str]) -> dict:
    """Shape-only summary of a PDF's text lines (testable without a PDF)."""
    lines = [re.sub(r"\s+", " ", l).strip() for l in lines if l and l.strip()]
    first_shapes = collections.Counter(shape(l.split(" ")[0]) for l in lines if re.match(r"^\S*\d", l))
    low = "\n".join(lines).lower()
    return {
        "lines": len(lines),
        "safe_heading_lines": sorted({mask(l) for l in lines if safe_line(l)})[:40],
        "first_token_shapes": first_shapes.most_common(8),
        "lines_with_amount": sum(1 for l in lines if re.search(r"\$\s?\d", l)),
        "keyword_counts": {k: low.count(k) for k in KEYWORDS},
        "years_seen": sorted({m.group(0) for m in YEAR.finditer("\n".join(lines))})[:12],
    }


def html_structure(html: str, base: str) -> dict:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["table"]):
        t.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    heads = [safe_text(h.get_text(" ", strip=True)) for h in soup.find_all(["h1", "h2", "h3", "h4"])]
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base, a["href"])
        if href.startswith(("http://", "https://")) and official(href):
            links.append({"href": href, "text": safe_text(a.get_text(" ", strip=True))})
    scripts = [urljoin(base, s["src"]) for s in soup.find_all("script", src=True)]
    iframes = [urljoin(base, f["src"]) for f in soup.find_all("iframe", src=True)]
    return {
        "title": safe_text(title),
        "headings": [h for h in heads if h][:30],
        "links": links[:80],
        "script_srcs": scripts[:30],
        "iframes": iframes[:10],
        "endpoints": sorted(set(ENDPOINT.findall(html)))[:30],
    }


def fetch(session, url: str):
    try:
        r = session.get(url, timeout=40, headers={"User-Agent": UA})
        return r, None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}"


def page_entry(session, kind: str, url: str) -> dict:
    out = {"kind": kind, "url": url}
    r, err = fetch(session, url)
    if err:
        out["error"] = err
        return out
    out.update(status=r.status_code, final_url=r.url, content_type=r.headers.get("Content-Type", ""),
               last_modified=r.headers.get("Last-Modified"), bytes=len(r.content))
    if r.status_code != 200:
        return out
    ctype = out["content_type"].lower()
    if "pdf" in ctype or r.content[:4] == b"%PDF":
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(r.content)) as pdf:
                out["pdf_pages"] = len(pdf.pages)
                lines = []
                for p in pdf.pages[:6]:
                    lines.extend((p.extract_text() or "").splitlines())
                out["pdf"] = pdf_structure(lines)
        except Exception as e:  # noqa: BLE001
            out["pdf_error"] = type(e).__name__
    elif "html" in ctype:
        out["html"] = html_structure(r.text, r.url)
    return out


def layer_entry(session, url: str) -> dict:
    out = {"url": url}
    r, err = fetch(session, url.split("?")[0] + "?f=pjson")
    if err or r is None or r.status_code != 200:
        out["error"] = err or (r.status_code if r is not None else "none")
        return out
    try:
        meta = r.json()
    except ValueError:
        out["error"] = "not json"
        return out
    out["name"] = safe_text(meta.get("name", "")) or meta.get("name", "")[:60]
    out["type"] = meta.get("type")
    out["geometry_type"] = meta.get("geometryType")
    out["max_record_count"] = meta.get("maxRecordCount")
    out["fields"] = [(f.get("name"), f.get("type")) for f in (meta.get("fields") or [])][:80]
    out["sublayers"] = [(l.get("id"), safe_text(l.get("name", "")) or "?") for l in (meta.get("layers") or [])][:40]
    if re.search(r"/(FeatureServer|MapServer)/\d+$", url.split("?")[0]):
        c, err = fetch(session, url.split("?")[0] + "/query?where=1%3D1&returnCountOnly=true&f=json")
        if c is not None and c.status_code == 200:
            try:
                out["count"] = c.json().get("count")
            except ValueError:
                pass
    return out


def capture() -> dict:
    import requests
    session = requests.Session()
    report = {"generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "pages": [], "scripts": [],
              "layers": [], "sale_books": []}
    endpoints: set[str] = set()
    for kind, url in PAGES:
        e = page_entry(session, kind, url)
        report["pages"].append(e)
        endpoints.update((e.get("html") or {}).get("endpoints", []))
        print(f"  {kind:<28} {e.get('status', e.get('error'))}", flush=True)
        time.sleep(0.6)
    # The scripts behind the Land Bank map: endpoint URLs only.
    lb = [p for p in report["pages"] if p["kind"].startswith("landbank") and p.get("html")]
    srcs = [s for p in lb for s in p["html"]["script_srcs"]]
    for s in srcs[:MAX_SCRIPTS]:
        r, err = fetch(session, s)
        found = sorted(set(ENDPOINT.findall(r.text))) if r is not None and r.status_code == 200 else []
        report["scripts"].append({"src": s, "status": getattr(r, "status_code", err), "endpoints": found[:30]})
        endpoints.update(found)
        time.sleep(0.4)
    for ep in sorted(endpoints)[:MAX_LAYERS]:
        if re.search(r"(FeatureServer|MapServer)", ep):
            report["layers"].append(layer_entry(session, ep))
            time.sleep(0.4)
    books = list(SALE_BOOKS)
    for p in report["pages"]:
        for l in (p.get("html") or {}).get("links", []):
            if re.search(r"salebook|sale-book|sale_book", l["href"], re.I) and l["href"] not in books and len(books) < len(SALE_BOOKS) + MAX_EXTRA_BOOKS:
                books.append(l["href"])
    for b in books:
        e = page_entry(session, "sale_book", b)
        report["sale_books"].append(e)
        print(f"  sale_book {b.rsplit('/', 1)[-1]:<28} {e.get('status', e.get('error'))} pages={e.get('pdf_pages')}", flush=True)
        time.sleep(0.6)
    return report


def digest(report: dict) -> str:
    out = [f"Shelby County TN structure capture {report.get('generated_at')}"]
    for p in report.get("pages", []) + report.get("sale_books", []):
        out.append(f"\n[{p['kind']}] {p['url']} -> {p.get('status', p.get('error'))} {p.get('content_type', '')} lm={p.get('last_modified')}")
        h = p.get("html")
        if h:
            out.append(f"  title: {h['title']}")
            out += [f"  h: {x}" for x in h["headings"][:15]]
            out += [f"  link: {l['text']} -> {l['href']}" for l in h["links"][:40]]
            out += [f"  script: {s}" for s in h["script_srcs"][:15]]
            out += [f"  iframe: {s}" for s in h["iframes"]]
            out += [f"  endpoint: {s}" for s in h["endpoints"]]
        if p.get("pdf"):
            d = p["pdf"]
            out.append(f"  pdf pages={p.get('pdf_pages')} lines(first 6 pages)={d['lines']} amount-lines={d['lines_with_amount']}")
            out.append(f"  first-token shapes: {d['first_token_shapes']}")
            out.append(f"  keywords: {d['keyword_counts']}  years: {d['years_seen']}")
            out += [f"  heading: {x}" for x in d["safe_heading_lines"]]
    for s in report.get("scripts", []):
        out.append(f"\n[script] {s['src']} -> {s['status']}")
        out += [f"  endpoint: {e}" for e in s["endpoints"]]
    for l in report.get("layers", []):
        out.append(f"\n[layer] {l['url']} name={l.get('name')} type={l.get('type')} geom={l.get('geometry_type')} "
                   f"max={l.get('max_record_count')} count={l.get('count')} err={l.get('error')}")
        if l.get("fields"):
            out.append("  fields: " + ", ".join(f"{n}:{t}" for n, t in l["fields"]))
        if l.get("sublayers"):
            out.append("  sublayers: " + ", ".join(f"{i}:{n}" for i, n in l["sublayers"]))
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--digest")
    ap.add_argument("--out", default=str(OUT_PATH))
    a = ap.parse_args(argv)
    if a.digest:
        print(digest(json.loads(Path(a.digest).read_text(encoding="utf-8"))))
        return 0
    report = capture()
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(digest(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
