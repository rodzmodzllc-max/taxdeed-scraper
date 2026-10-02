#!/usr/bin/env python3
"""Auction sale-process capture (cross-state enrichment sprint, 2026-10-02).

Reads each official county page in data/auction_candidate_pages.csv (and,
one hop away, the tax-deed / sale-rules / FAQ / bidder documents those pages
themselves link to) and prints, per county, ONLY the sentences that describe
how the county's tax sale runs: registration, deposit, payment method and
deadline, bidder requirements, identification, the sale's platform, location
and time, and the office contact the page publishes.

It is a capture, not a writer: nothing here touches the database. A person
reads the digest in the job log and records only what a page states in
data/auction_process_evidence.csv (review_state=verified). A sentence is
kept only when it carries sale-process vocabulary AND tax-sale context (the
sentence itself, or a page whose title / URL / headings are about a tax deed
/ tax sale / sheriff sale / auction) - so a clerk site's family-law or fee
pages do not drown the digest. Sentences with a 7+ digit run (a parcel /
account number) are dropped; candidates are leads, never evidence.

    python3 scripts/capture_auction_process.py [--state FL] [--county Lee] [--out out/public/auction-process-capture.json]
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import capture_purchase_evidence as C  # noqa: E402

CANDIDATES = REPO / "data" / "auction_candidate_pages.csv"
OUT_PATH = REPO / "out" / "public" / "auction-process-capture.json"

# What a sale-process sentence talks about.
PROCESS = re.compile(
    r"deposit|bidder|\bbid(?:s|ding)?\b|regist|wire|cashier|certified (?:funds|check)|money order|\bACH\b|credit card|"
    r"balance|non-?refundable|realtaxdeed|realforeclose|realauction|bid4assets|govease|online auction|in person|"
    r"auction (?:begins|starts|will|is|are)|sale(?:s)? (?:begin|start|are|is|will)|\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)|"
    r"\b(?:noon|eastern|central)\b|identification|photo id|driver'?s license|documentary stamp|recording fee|"
    r"overbid|surplus|title (?:is|will|search)|as[- ]is|tax deed|tax sale|sheriff'?s? sale|minimum bid|opening bid|"
    r"redeem|redemption|courthouse|location|held at|held on|held online|contact|phone|e-?mail", re.I)
# Tax-sale context: the sentence or the page must be about the tax sale.
CONTEXT = re.compile(r"tax[\s-]?deed|tax[\s-]?sale|sheriff'?s?[\s-]?sale|tax[\s-]?foreclos|auction|bidder|struck[\s-]?off|"
                     r"tax[\s-]?lien|delinquent", re.I)
FOLLOW = re.compile(r"tax[\s_-]?deed|tax[\s_-]?sale|sale[\s_-]?rules|rules|faq|frequently|bidder|registration|procedure|"
                    r"terms|deposit|auction|sheriff[\s_-]?sale|instructions", re.I)
NOISE = re.compile(r"dissolution of marriage|parenting plan|passport|marriage license|small claims|traffic|jury duty|"
                   r"child support|probate|eviction|guardianship|domestic violence", re.I)
MAX_SENTENCES = 40
MAX_CHARS = 320
MAX_FOLLOW = 6
PDF_PAGES = 10


def candidate_rows(path: Path = CANDIDATES) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if (r.get("url") or "").startswith("https://")]


def page_is_tax_sale(title: str, url: str, headings: list[str]) -> bool:
    return bool(CONTEXT.search(title or "") or CONTEXT.search(url or "") or any(CONTEXT.search(h or "") for h in headings))


def keep_sentences(text: str, *, page_context: bool) -> list[str]:
    out, seen = [], set()
    for s in C.sentences(text):
        if len(s) < 20 or C.LONG_DIGITS.search(s) or NOISE.search(s):
            continue
        if not PROCESS.search(s):
            continue
        if not (page_context or CONTEXT.search(s)):
            continue
        key = s.lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        out.append(s[:MAX_CHARS])
        if len(out) >= MAX_SENTENCES:
            break
    return out


def read_html(html: str, url: str) -> dict:
    soup = C.BeautifulSoup(html, "html.parser")
    title = C.clean(soup.title.get_text(" ")) if soup.title else ""
    headings = [C.clean(h.get_text(" ")) for h in soup.find_all(["h1", "h2", "h3"])][:20]
    links = []
    for a in soup.find_all("a", href=True):
        href, text = a["href"].strip(), C.clean(a.get_text(" "))
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(url, href)
        if C.LONG_DIGITS.search(absolute) or NOISE.search(text):
            continue
        if FOLLOW.search(text) or FOLLOW.search(absolute):
            links.append({"text": text[:120], "href": absolute, "document": bool(C.DOC_EXT.search(absolute)),
                          "same_site": C.same_site(absolute, url)})
    for tag in soup.find_all(["script", "style", "nav", "noscript", "header", "footer"]):
        tag.decompose()
    text = soup.get_text("\n")
    ctx = page_is_tax_sale(title, url, headings)
    return {"title": title, "headings": headings[:10], "tax_sale_page": ctx, "links": links[:40],
            "sentences": keep_sentences(text, page_context=ctx),
            "phones": sorted(set(m.group(0) for m in C.PHONE.finditer(text)))[:12],
            "emails": sorted(set(m.group(0) for m in C.EMAIL.finditer(text)))[:12]}


def read_pdf(data: bytes, url: str) -> dict:
    try:
        import pdfplumber
    except ImportError:
        return {"error": "pdfplumber not installed"}
    parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:PDF_PAGES]:
            parts.append(page.extract_text() or "")
    text = "\n".join(parts)
    return {"pages_read": len(parts), "tax_sale_page": page_is_tax_sale("", url, []) or bool(CONTEXT.search(text[:3000])),
            "sentences": keep_sentences(text, page_context=bool(CONTEXT.search(text[:3000]))),
            "phones": sorted(set(m.group(0) for m in C.PHONE.finditer(text)))[:12],
            "emails": sorted(set(m.group(0) for m in C.EMAIL.finditer(text)))[:12]}


def capture(session, url: str, kind: str) -> dict:
    out = {"url": url, "kind": kind, "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    resp, err = C.fetch(session, url)
    if err:
        out["error"] = err
        return out
    out.update(status=resp.status_code, final_url=resp.url, last_modified=resp.headers.get("Last-Modified"),
               content_type=resp.headers.get("Content-Type", ""))
    if resp.status_code != 200:
        return out
    if "pdf" in out["content_type"].lower() or url.lower().endswith(".pdf"):
        out.update(read_pdf(resp.content, url))
    else:
        out.update(read_html(resp.text, resp.url))
    return out


def follow_links(pages: list[dict], seen: set) -> list[str]:
    ranked = []
    for pg in pages:
        for l in pg.get("links") or []:
            href = l["href"]
            host = (urlsplit(href).hostname or "").lower()
            if href in seen or not href.startswith("https://") or C.NEVER_FOLLOW.search(host + "."):
                continue
            if not (l["same_site"] or l["document"]):
                continue
            seen.add(href)
            ranked.append(((0 if l["document"] else 1), href))
    ranked.sort()
    return [h for _, h in ranked[:MAX_FOLLOW]]


def run(states: set[str] | None, counties: set[str] | None) -> dict:
    import requests
    session = requests.Session()
    result: dict = {}
    for r in candidate_rows():
        if states and r["state"] not in states:
            continue
        if counties and r["county"] not in counties:
            continue
        key = f"{r['state']}/{r['county']}"
        unit = result.setdefault(key, {"pages": [], "notes": []})
        unit["notes"].append(r.get("note", ""))
        seen = {p["url"] for p in unit["pages"]}
        if r["url"] in seen:
            continue
        unit["pages"].append(capture(session, r["url"], "candidate_page"))
    for key, unit in result.items():
        seen = {p["url"] for p in unit["pages"]}
        for href in follow_links(unit["pages"], seen):
            unit["pages"].append(capture(session, href, "followed_link"))
    return result


def digest(result: dict) -> str:
    lines = []
    for key in sorted(result):
        lines.append(f"@@ {key}")
        for pg in result[key]["pages"]:
            head = f"  ## {pg['kind']} {pg['url']} -> {pg.get('status', pg.get('error'))} lm={pg.get('last_modified')}"
            lines.append(head)
            if pg.get("title"):
                lines.append(f"  title: {pg['title']} | tax_sale_page={pg.get('tax_sale_page')}")
            for s in pg.get("sentences") or []:
                lines.append(f"  > {s}")
            if pg.get("phones"):
                lines.append(f"  phones: {', '.join(pg['phones'])}")
            if pg.get("emails"):
                lines.append(f"  emails: {', '.join(pg['emails'])}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", action="append")
    ap.add_argument("--county", action="append")
    ap.add_argument("--out", default=str(OUT_PATH))
    a = ap.parse_args(argv)
    result = run(set(a.state) if a.state else None, set(a.county) if a.county else None)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(digest(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
