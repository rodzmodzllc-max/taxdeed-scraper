#!/usr/bin/env python3
"""Capture what each approved AVAILABLE source PUBLISHES about how to buy
or apply - county-level process text, value-free (Customer Value /
Evidence Acquisition sprint, 2026-09-30).

The purchase-path engine (scripts/purchase_path_engine.py) only ever
establishes a customer action path from evidence a person has verified and
recorded in data/purchase_path_evidence.csv. That table stayed empty
because no county page could be read from the assistant's sandbox. This
script closes the loop the repository-native way: it runs where the
harvesters run (GitHub Actions, manual dispatch only), fetches the SAME
canonical list page / document each production registry row already names,
and writes a value-free capture of the process wording it finds:

  - page title and headings
  - links whose text or target looks like a purchase / application /
    instructions page (text, resolved URL, host, same-site flag)
  - sentences that mention purchasing, applying, contacting the office,
    fees, forms, F.S. 197.502 - outside any table, capped in length, never
    a sentence carrying a long digit run (a parcel / case number)
  - phone numbers and e-mail addresses the page publishes for that process

Nothing here is a purchase path. The capture is the raw material a person
reads to write an evidence row (URL, type, quoted wording, observed date);
the engine then applies that row deterministically on the next laft run.

RealAuction result-label discovery (--realauction-date): for the FL deed
auction hosts, fetch the sale-day page of a PAST date and record which
LABELS the page publishes for each item (e.g. "Auction Status", "Sold To",
"Amount") with counts, plus the distinct VALUES of status-like labels only
(status vocabulary, never an amount, a name or an identifier). This tells
us whether the approved source publishes explicit results at all; it never
records a result.

Standard library + requests + beautifulsoup4 (+ pdfplumber for PDF
documents). No credentials. Output: out/public/purchase-evidence-capture.json.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - the workflow installs it
    BeautifulSoup = None

REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "data" / "county_source_registry.csv"
REALAUCTION_HOSTS = REPO / "data" / "realauction_counties.csv"
OUT_PATH = REPO / "out" / "public" / "purchase-evidence-capture.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip, deflate"}
LINK_VOCAB = re.compile(r"purchas|buy|apply|application|instruction|how to|procedure|process|form|lands available|"
                        r"land available|list of lands|tax deed|197\.502|fee|contact", re.I)
SNIPPET_VOCAB = re.compile(r"purchas|apply|application|contact|phone|e-?mail|mail|in person|office|submit|form|fee|"
                           r"197\.502|lands available|cashier|certified|payment|bid", re.I)
LONG_DIGITS = re.compile(r"\d{7,}")
PHONE = re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MAX_SNIPPETS, MAX_SNIPPET_CHARS, MAX_LINKS = 40, 320, 60
# Acquisition sprint 2 (2026-09-30): one-hop follow. Only a link that is
# PRESENT on an approved source page, whose own text or URL names the
# acquisition process (strong vocabulary - not "contact", not "fee"), and
# whose host is not a search engine, social site or blocked vendor, is
# fetched. Capped per county. Never a crawl, never a search, never a guessed
# URL; the operator still reads the capture and records evidence by hand.
FOLLOW_VOCAB = re.compile(r"purchas|how to (buy|purchase|apply)|instruction|application|apply|procedure|"
                          r"lands? available|list of lands|197\.502|tax deed (info|faq|process|general|sales? info)|"
                          r"faq|frequently asked|general information|requirements|forms?\b", re.I)
DOC_EXT = re.compile(r"\.(pdf|docx?|rtf)(\?|#|$)", re.I)
NEVER_FOLLOW = re.compile(r"(^|\.)(google|bing|yahoo|duckduckgo|facebook|twitter|x|instagram|linkedin|youtube|"
                          r"govease|bid4assets|lgbs|zillow|realtor)\.", re.I)
MAX_FOLLOW_PER_COUNTY = 6
STATUS_LABEL = re.compile(r"status", re.I)


def registry_rows(state: str) -> list[dict]:
    with open(REGISTRY, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh)
                if r["state"] == state and r["verification_status"] == "PRODUCTION_VERIFIED" and "AVAILABLE" in (r.get("ledgers") or "")]


def same_site(url: str, base: str) -> bool:
    a, b = (urlsplit(url).hostname or "").lower(), (urlsplit(base).hostname or "").lower()
    if not a or not b:
        return False
    return a == b or a.endswith("." + b) or b.endswith("." + a) or ".".join(a.split(".")[-2:]) == ".".join(b.split(".")[-2:])


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def sentences(text: str):
    for s in re.split(r"(?<=[.!?])\s+|\n{2,}", text):
        s = clean(s)
        if s:
            yield s


def extract_html(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = clean(soup.title.get_text(" ")) if soup.title else ""
    headings = [clean(h.get_text(" ")) for h in soup.find_all(["h1", "h2", "h3"])][:15]
    links = []
    for a in soup.find_all("a", href=True):
        text = clean(a.get_text(" "))
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(url, href)
        is_doc = bool(DOC_EXT.search(absolute))
        if LINK_VOCAB.search(text) or LINK_VOCAB.search(absolute) or is_doc:
            links.append({"text": text[:120], "href": absolute, "host": (urlsplit(absolute).hostname or "").lower(),
                          "same_site": same_site(absolute, url), "document": is_doc,
                          "follow": bool(FOLLOW_VOCAB.search(text) or FOLLOW_VOCAB.search(absolute))})
        if len(links) >= MAX_LINKS:
            break
    # Process text lives outside the inventory table: drop tables, scripts,
    # navigation before reading sentences, so no row value is captured.
    for tag in soup.find_all(["table", "script", "style", "nav", "noscript"]):
        tag.decompose()
    body_text = soup.get_text("\n")
    snippets = []
    for s in sentences(body_text):
        if SNIPPET_VOCAB.search(s) and not LONG_DIGITS.search(s) and len(s) > 25:
            snippets.append(s[:MAX_SNIPPET_CHARS])
        if len(snippets) >= MAX_SNIPPETS:
            break
    phones = sorted(set(m.group(0) for m in PHONE.finditer(body_text)))[:10]
    emails = sorted(set(m.group(0) for m in EMAIL.finditer(body_text)))[:10]
    return {"title": title, "headings": headings, "links": links, "snippets": snippets, "phones": phones, "emails": emails}


def extract_pdf(data: bytes) -> dict:
    try:
        import pdfplumber
    except ImportError:
        return {"error": "pdfplumber not installed"}
    text_parts = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:4]:
            text_parts.append(page.extract_text() or "")
    text = "\n".join(text_parts)
    snippets = [s[:MAX_SNIPPET_CHARS] for s in sentences(text) if SNIPPET_VOCAB.search(s) and not LONG_DIGITS.search(s) and len(s) > 25][:MAX_SNIPPETS]
    return {"pages_read": min(4, len(text_parts)), "snippets": snippets,
            "phones": sorted(set(m.group(0) for m in PHONE.finditer(text)))[:10],
            "emails": sorted(set(m.group(0) for m in EMAIL.finditer(text)))[:10]}


def fetch(session: requests.Session, url: str) -> tuple[requests.Response | None, str | None]:
    try:
        resp = session.get(url, headers=HEADERS, timeout=40, allow_redirects=True)
        return resp, None
    except requests.RequestException as exc:
        return None, f"{type(exc).__name__}: {str(exc)[:160]}"


def capture_url(session: requests.Session, url: str, *, kind: str) -> dict:
    out = {"url": url, "kind": kind, "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    resp, err = fetch(session, url)
    if err:
        out["error"] = err
        return out
    out["status"] = resp.status_code
    out["final_url"] = resp.url
    out["content_type"] = resp.headers.get("Content-Type", "")
    out["last_modified"] = resp.headers.get("Last-Modified")
    if resp.status_code != 200:
        return out
    ctype = out["content_type"].lower()
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        out.update(extract_pdf(resp.content))
    elif BeautifulSoup is not None:
        out.update(extract_html(resp.text, resp.url))
    else:
        out["error"] = "beautifulsoup4 not installed"
    return out


def follow_candidates(pages: list[dict], seen: set) -> list[dict]:
    """The links to fetch one hop from the source's own pages: present on
    the page, acquisition vocabulary, not a search engine / social / vendor
    host, not already captured; documents first, then same-site pages."""
    out, keys = [], set(seen)
    for pg in pages:
        for l in pg.get("links") or []:
            href = l.get("href") or ""
            host = (urlsplit(href).hostname or "").lower()
            if not l.get("follow") or href in keys or not href.startswith(("https://", "http://")) or NEVER_FOLLOW.search(host + "."):
                continue
            keys.add(href)
            out.append({"href": href, "text": l.get("text", ""), "from": pg.get("url"), "rank": (0 if l.get("document") else 1, 0 if l.get("same_site") else 1)})
    out.sort(key=lambda x: x["rank"])
    return out[:MAX_FOLLOW_PER_COUNTY]


def capture_available(session: requests.Session, state: str, counties: set[str] | None, *, follow: bool = False) -> dict:
    result: dict = {}
    for r in registry_rows(state):
        if counties and r["county"] not in counties:
            continue
        entry = {"source_id": r["source_id"], "access_method": r["access_method"], "machine_format": r["machine_format"], "pages": []}
        seen = set()
        for kind, url in (("canonical_url", r["canonical_url"]), ("document_url", r["document_url"]), ("purchase_url", r["purchase_url"])):
            url = (url or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            entry["pages"].append(capture_url(session, url, kind=kind))
            time.sleep(0.6)
        if follow:
            for link in follow_candidates(entry["pages"], seen):
                page = capture_url(session, link["href"], kind="followed_link")
                page["followed_from"] = link["from"]
                page["link_text"] = link["text"]
                entry["pages"].append(page)
                seen.add(link["href"])
                time.sleep(0.6)
        result[r["county"]] = entry
        print(f"  {r['county']:<14} {r['source_id']:<22} " + ", ".join(f"{p.get('kind')}={p.get('status', p.get('error', '?'))}" for p in entry["pages"]), flush=True)
    return result


def capture_realauction(session: requests.Session, dates: list[str], counties: set[str] | None) -> dict:
    """Which labels a RealAuction sale-day page publishes per item, and the
    distinct values of status-like labels. Value-free by construction."""
    out: dict = {}
    with open(REALAUCTION_HOSTS, newline="", encoding="utf-8") as fh:
        hosts = [r for r in csv.DictReader(fh)]
    for h in hosts:
        if counties and h["County"] not in counties:
            continue
        for d in dates:
            url = f"https://{h['Host']}/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate={d}"
            resp, err = fetch(session, url)
            rec: dict = {"url": url, "date": d}
            if err or resp is None:
                rec["error"] = err
            else:
                rec["status"] = resp.status_code
                if resp.status_code == 200 and BeautifulSoup is not None:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    labels: dict[str, int] = {}
                    status_values: dict[str, dict[str, int]] = {}
                    for th in soup.find_all(["th", "td", "div", "span"], class_=re.compile(r"AD_LBL|label|lbl", re.I)):
                        label = clean(th.get_text(" ")).rstrip(":")
                        if not label or len(label) > 40 or LONG_DIGITS.search(label):
                            continue
                        labels[label] = labels.get(label, 0) + 1
                        if STATUS_LABEL.search(label):
                            sib = th.find_next_sibling()
                            val = clean(sib.get_text(" ")) if sib else ""
                            if val and len(val) <= 40 and not re.search(r"\d", val):
                                status_values.setdefault(label, {})[val] = status_values.setdefault(label, {}).get(val, 0) + 1
                    # A page-level status banner (e.g. "Auction Status: Sold") - words only.
                    banner = [clean(m.group(0))[:60] for m in re.finditer(r"Auction Status[^<\n]{0,60}", resp.text)][:5]
                    rec.update({"labels": dict(sorted(labels.items())), "status_values": status_values,
                                "banner_samples": [b for b in banner if not re.search(r"\d", b)],
                                "item_count_hint": len(soup.find_all(class_=re.compile(r"AUCTION_ITEM|auction-item", re.I)))})
            out.setdefault(h["County"], []).append(rec)
            print(f"  RealAuction {h['County']:<14} {d}: {rec.get('status', rec.get('error'))}", flush=True)
            time.sleep(0.6)
    return out


def digest(path: Path, *, max_links: int = 25, max_snippets: int = 25, snippet_chars: int = 240) -> str:
    """A compact, line-oriented digest of a capture file for the job log
    (the full JSON is in the artifact). Same value-free content, fewer
    bytes: one block per county, RealAuction label sets de-duplicated."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = [f"# purchase-evidence digest {data.get('generated_at')} state={data.get('state')}"]
    for county, e in sorted((data.get("available_sources") or {}).items()):
        out.append(f"@@ {county} | {e.get('source_id')} | {e.get('access_method')} | {e.get('machine_format')}")
        for pg in e.get("pages") or []:
            via = f" (from {pg.get('followed_from')} link {pg.get('link_text', '')[:50]!r})" if pg.get("followed_from") else ""
            out.append(f"  ## {pg.get('kind')} {pg.get('url')} -> {pg.get('status', pg.get('error'))} ct={str(pg.get('content_type', ''))[:30]} lm={pg.get('last_modified')}{via}")
            if pg.get("title"):
                out.append(f"  title: {pg['title'][:140]}")
            if pg.get("headings"):
                out.append("  headings: " + " || ".join(h[:80] for h in pg["headings"][:8]))
            for l in (pg.get("links") or [])[:max_links]:
                out.append(f"  link: {l['text'][:70]!r} -> {l['href']} [{'same' if l.get('same_site') else 'OTHER'}{' DOC' if l.get('document') else ''}{' follow' if l.get('follow') else ''}]")
            for sn in (pg.get("snippets") or [])[:max_snippets]:
                out.append(f"  s: {sn[:snippet_chars]}")
            if pg.get("phones"):
                out.append("  phones: " + ", ".join(pg["phones"]))
            if pg.get("emails"):
                out.append("  emails: " + ", ".join(pg["emails"]))
    ra = data.get("realauction_result_labels") or {}
    if ra:
        out.append("@@ REALAUCTION result-label discovery")
        seen: dict[str, list[str]] = {}
        for county, recs in sorted(ra.items()):
            for r in recs:
                key = json.dumps({"labels": r.get("labels"), "status_values": r.get("status_values"), "banner": r.get("banner_samples"),
                                  "items": r.get("item_count_hint"), "status": r.get("status", r.get("error"))}, sort_keys=True)
                seen.setdefault(key, []).append(f"{county} {r.get('date')}")
        for key, where in seen.items():
            out.append(f"  set ({len(where)} page(s): {', '.join(where[:6])}{' ...' if len(where) > 6 else ''}): {key}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--digest", default=None, help="print a compact digest of an existing capture file and exit")
    ap.add_argument("--state", default="FL")
    ap.add_argument("--county", action="append", default=[], help="limit to these counties (repeatable)")
    ap.add_argument("--realauction-date", action="append", default=[], help="MM/DD/YYYY past sale date(s) for result-label discovery")
    ap.add_argument("--skip-available", action="store_true")
    ap.add_argument("--follow", action="store_true", help="fetch up to %d acquisition links present on each source page (one hop)" % MAX_FOLLOW_PER_COUNTY)
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args(argv)
    if args.digest:
        print(digest(Path(args.digest)))
        return 0
    counties = set(args.county) or None
    session = requests.Session()
    report = {"generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "state": args.state,
              "note": "county-level process text, links, phones and e-mails from the approved sources' own pages; "
                      "tables removed before reading; no row value, no parcel, no case number, no amount, no name"}
    if not args.skip_available:
        print(f"capturing AVAILABLE source pages ({args.state})", flush=True)
        report["available_sources"] = capture_available(session, args.state, counties, follow=args.follow)
    if args.realauction_date:
        print("RealAuction result-label discovery", flush=True)
        report["realauction_result_labels"] = capture_realauction(session, args.realauction_date, counties)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
