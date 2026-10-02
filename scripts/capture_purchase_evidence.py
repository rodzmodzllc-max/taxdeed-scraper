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
# Acquisition-path sprint (2026-10-01): official pages a person found by
# reading search results for the counties whose source page publishes no
# process. Each row names the page exactly as it was published; the capture
# reads it (and one hop of tax-deed links on it) so the process can be
# verified from the page itself before any evidence row is written.
CANDIDATES = REPO / "data" / "acquisition_candidate_pages.csv"
OUT_PATH = REPO / "out" / "public" / "purchase-evidence-capture.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip, deflate"}
LINK_VOCAB = re.compile(r"purchas|buy|apply|application|instruction|how to|procedure|process|form|lands available|"
                        r"land available|list of lands|tax deed|197\.502|fee|contact", re.I)
SNIPPET_VOCAB = re.compile(r"purchas|apply|application|contact|phone|e-?mail|mail|in person|office|submit|form|fee|"
                           r"197\.502|lands available|cashier|certified|payment|bid|struck|resale|re-sale|"
                           r"trust propert|held in trust|sheriff|tax sale|foreclos", re.I)
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
# Tax-deed context is REQUIRED (a first capture followed generic "Forms" /
# "Application Process" navigation into passport and marriage-licence pages).
FOLLOW_VOCAB = re.compile(r"tax[\s_-]?deed|lands?[\s_-]?available|list[\s_-]?of[\s_-]?lands|197\.502|\blaft\b|"
                          r"purchas\w* (property|land)|lands? for taxes|struck[\s_-]?off|re-?sale|sheriff[\s_-]?sale|"
                          r"tax[\s_-]?sale|trust[\s_-]?propert", re.I)
DOC_EXT = re.compile(r"\.(pdf|docx?|rtf)(\?|#|$)", re.I)
NEVER_FOLLOW = re.compile(r"(^|\.)(google|bing|yahoo|duckduckgo|facebook|twitter|x|instagram|linkedin|youtube|"
                          r"govease|bid4assets|lgbs|pbfcm|mvbalaw|mvba|ctsa|zillow|realtor)\.", re.I)
MAX_FOLLOW_PER_COUNTY = 6
# AVAILABLE discovery mode (--discovery, evidence_scope=available_discovery):
# post-sale program pages name their lists differently from Florida's Lands
# Available ("FLC Properties Available for Assignment", "Over the Counter",
# "Land - For Sale", land-bank inventories). In this mode those words also
# select and follow links, every snippet has its digits masked (an
# identifier, amount or acreage never reaches the log), and each table /
# PDF reports only its SHAPE: header words with digits masked, the row count
# and the share of rows carrying a digit run (identifier-shaped). Never a value.
DISCOVERY = False
DISCOVERY_VOCAB = re.compile(r"forfeit|\bflc\b|assignment|over[\s-]the[\s-]counter|\botc\b|for sale|land sale|land ?bank|"
                             r"available|surplus|struck|resale|propert(y|ies) list|inventory|no propert|none available", re.I)
IDENT_RUN = re.compile(r"\d[\d\-./]{2,}")
MAX_TABLES = 8


def mask_digits(text: str) -> str:
    return re.sub(r"\d", "#", text)


def table_shapes(soup) -> list[dict]:
    """Value-free shape of each table: header words (digits masked), row
    count, rows carrying an identifier-shaped digit run."""
    out = []
    for t in soup.find_all("table")[:MAX_TABLES]:
        rows = t.find_all("tr")
        if not rows:
            continue
        head_cells = rows[0].find_all(["th", "td"])
        header = [mask_digits(clean(c.get_text(" ")))[:40] for c in head_cells][:12]
        body = rows[1:]
        with_ident = sum(1 for r in body if IDENT_RUN.search(r.get_text(" ")))
        out.append({"header": header, "rows": len(body), "rows_with_identifier_shape": with_ident})
    return out
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


def extract_html(html: str, url: str, *, keep_tables: bool = False) -> dict:
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
        # A link carrying a parcel / account number (a 7+ digit run) is a
        # per-property link from the inventory list: never captured, so the
        # capture stays value-free (Putnam's list links every row to the Tax
        # Collector by account number).
        if LONG_DIGITS.search(absolute) or LONG_DIGITS.search(text):
            continue
        is_doc = bool(DOC_EXT.search(absolute))
        disc = DISCOVERY and bool(DISCOVERY_VOCAB.search(text) or DISCOVERY_VOCAB.search(absolute))
        if LINK_VOCAB.search(text) or LINK_VOCAB.search(absolute) or is_doc or disc:
            follow = bool(FOLLOW_VOCAB.search(text) or FOLLOW_VOCAB.search(absolute)) or (disc and same_site(absolute, url))
            links.append({"text": (mask_digits(text) if DISCOVERY else text)[:120], "href": absolute,
                          "host": (urlsplit(absolute).hostname or "").lower(),
                          "same_site": same_site(absolute, url), "document": is_doc, "follow": follow})
        if len(links) >= MAX_LINKS:
            break
    # Process text lives outside the inventory table: drop tables, scripts,
    # navigation before reading sentences, so no row value is captured.
    # A followed PROCESS page (FAQ, instructions) may lay its text out in a
    # table; the source's inventory list is never read with tables kept.
    shapes = table_shapes(soup) if DISCOVERY else None
    for tag in soup.find_all((["table"] if (not keep_tables or DISCOVERY) else []) + ["script", "style", "nav", "noscript"]):
        tag.decompose()
    body_text = soup.get_text("\n")
    snippets = []
    for s in sentences(body_text):
        if (SNIPPET_VOCAB.search(s) or (DISCOVERY and DISCOVERY_VOCAB.search(s))) and not LONG_DIGITS.search(s) and len(s) > 25:
            snippets.append((mask_digits(s) if DISCOVERY else s)[:MAX_SNIPPET_CHARS])
        if len(snippets) >= MAX_SNIPPETS:
            break
    phones = sorted(set(m.group(0) for m in PHONE.finditer(body_text)))[:10]
    emails = sorted(set(m.group(0) for m in EMAIL.finditer(body_text)))[:10]
    out = {"title": title, "headings": headings, "links": links, "snippets": snippets, "phones": phones, "emails": emails}
    if shapes is not None:
        out["table_shapes"] = shapes
    return out


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
    if DISCOVERY:
        lines = [clean(l) for l in text.splitlines() if clean(l)]
        snippets = [mask_digits(s)[:MAX_SNIPPET_CHARS] for s in sentences(text)
                    if (SNIPPET_VOCAB.search(s) or DISCOVERY_VOCAB.search(s)) and len(s) > 25][:MAX_SNIPPETS]
        return {"pages_read": min(4, len(text_parts)), "snippets": snippets,
                "pdf_shape": {"lines": len(lines), "lines_with_identifier_shape": sum(1 for l in lines if IDENT_RUN.search(l)),
                              "first_lines": [mask_digits(l)[:100] for l in lines[:6]]},
                "phones": sorted(set(m.group(0) for m in PHONE.finditer(text)))[:10]}
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


def capture_url(session: requests.Session, url: str, *, kind: str, keep_tables: bool | None = None) -> dict:
    keep_tables = (kind == "followed_link") if keep_tables is None else keep_tables
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
        out.update(extract_html(resp.text, resp.url, keep_tables=keep_tables))
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


def candidate_rows(path: Path = CANDIDATES) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if (r.get("url") or "").startswith("https://")]


def capture_candidates(session: requests.Session, states: set[str] | None, counties: set[str] | None, *,
                       follow: bool = False, path: Path = CANDIDATES) -> dict:
    """Read each candidate official page named in data/acquisition_candidate_pages.csv
    (https only), plus up to MAX_FOLLOW_PER_COUNTY tax-deed / struck-off links
    PRESENT on those pages. Keyed "<STATE>/<County>". Followed process pages
    keep their table text (a process FAQ may be laid out in a table); the
    candidate page itself never does. Value-free like every other capture."""
    result: dict = {}
    list_urls = set()
    with open(REGISTRY, newline="", encoding="utf-8") as fh:
        for reg in csv.DictReader(fh):
            list_urls.update(u.strip() for u in (reg.get("canonical_url"), reg.get("document_url")) if u and u.strip())
    for r in candidate_rows(path):
        if (states and r["state"] not in states) or (counties and r["county"] not in counties):
            continue
        key = f"{r['state']}/{r['county']}"
        entry = result.setdefault(key, {"source_id": "candidate", "access_method": r.get("found_via", ""),
                                        "machine_format": "", "pages": [], "_seen": []})
        if r["url"] in entry["_seen"]:
            continue
        entry["_seen"].append(r["url"])
        # A candidate process page (an FAQ) may lay its answers out in a table;
        # a page that is any registry source's inventory list never keeps one.
        entry["pages"].append(capture_url(session, r["url"], kind="candidate_page", keep_tables=r["url"] not in list_urls))
        time.sleep(0.6)
    for key, entry in result.items():
        seen = set(entry.pop("_seen"))
        if follow:
            for link in follow_candidates(entry["pages"], seen):
                page = capture_url(session, link["href"], kind="followed_link")
                page["followed_from"] = link["from"]
                page["link_text"] = link["text"]
                entry["pages"].append(page)
                time.sleep(0.6)
        print(f"  {key:<22} " + ", ".join(f"{p.get('kind')}={p.get('status', p.get('error', '?'))}" for p in entry["pages"]), flush=True)
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


def capture_realauction_results(dates: list[str], counties: set[str] | None) -> dict:
    """The CLOSED / CANCELED area (AREA=C) of each RealAuction host for past
    sale dates, through the harvester's own anonymous AJAX sequence
    (scripts/realauction_results.py). Value-free: label names, status-line
    shapes with every digit masked, class tokens and counts - never a case
    number, parcel, amount or name."""
    import realauction_results as RR  # noqa: E402 - sibling module
    out: dict = {}
    with open(REALAUCTION_HOSTS, newline="", encoding="utf-8") as fh:
        hosts = [r for r in csv.DictReader(fh)]
    for h in hosts:
        if counties and h["County"] not in counties:
            continue
        for d in dates:
            res = RR.fetch_area(requests.Session(), h["Host"], d)
            rec = RR.value_free_summary(res)
            if res.items and not out.get("_page_script"):
                out["_page_script"] = RR.page_script_snippets(requests.Session(), h["Host"], res.url)
            out.setdefault(h["County"], []).append(rec)
            print(f"  RealAuction results {h['County']:<14} {d}: ok={rec['ok']} login={rec['login_page']} "
                  f"items={rec['items']} err={rec['error']}", flush=True)
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
            for t in pg.get("table_shapes") or []:
                out.append(f"  table: rows={t['rows']} id-shaped={t['rows_with_identifier_shape']} header={' | '.join(t['header'])}")
            if pg.get("pdf_shape"):
                ps = pg["pdf_shape"]
                out.append(f"  pdf: lines={ps['lines']} id-shaped={ps['lines_with_identifier_shape']} first: {' / '.join(ps['first_lines'])}")
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
    rr = data.get("realauction_results") or {}
    if rr:
        out.append("@@ REALAUCTION closed/canceled area (AREA=C), value-free")
        ps = rr.get("_page_script") or {}
        if ps:
            out.append("  page scripts: " + ", ".join(ps.get("scripts") or []) + (f" err={ps.get('error')}" if ps.get("error") else ""))
            for sn in ps.get("snippets") or []:
                out.append("    js: " + sn[:420])
        for county, recs in sorted(rr.items()):
            if county.startswith("_"):
                continue
            for r in recs:
                out.append(f"  {county} {r.get('date')}: ok={r.get('ok')} login_page={r.get('login_page')} pages={r.get('pages')} "
                           f"items={r.get('items')} with_case={r.get('with_case')} with_parcel={r.get('with_parcel')} err={r.get('error')}")
                if r.get("labels"):
                    out.append("    labels: " + ", ".join(f"{k}({v})" for k, v in r["labels"].items()))
                for k, v in list((r.get("status_pairs") or {}).items())[:12]:
                    out.append(f"    status: {k} x{v}")
                if r.get("classes"):
                    out.append("    classes: " + ", ".join(f"{k}({v})" for k, v in r["classes"].items()))
                st = r.get("structure") or {}
                if st.get("json_keys"):
                    out.append("    json_keys: " + ", ".join(st["json_keys"]))
                for k, v in (st.get("other_keys") or {}).items():
                    out.append(f"    key {k}: {str(v)[:300]}")
                for k, v in (r.get("status_tally") or {}).items():
                    out.append(f"    result: {k} x{v}")
                if r.get("update") is not None or r.get("update_error"):
                    out.append(f"    update (aids={r.get('aids')} err={r.get('update_error')}): " + json.dumps(r.get("update"))[:2500])
                if st.get("first_item_skeleton"):
                    out.append("    skeleton: " + st["first_item_skeleton"].replace("\n", " ")[:2200])
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--digest", default=None, help="print a compact digest of an existing capture file and exit")
    ap.add_argument("--state", default="FL")
    ap.add_argument("--county", action="append", default=[], help="limit to these counties (repeatable)")
    ap.add_argument("--realauction-date", action="append", default=[], help="MM/DD/YYYY past sale date(s) for result-label discovery")
    ap.add_argument("--skip-available", action="store_true")
    ap.add_argument("--realauction-results", action="store_true",
                    help="also read the CLOSED / CANCELED area (AREA=C) of each --realauction-date, value-free")
    ap.add_argument("--follow", action="store_true", help="fetch up to %d acquisition links present on each source page (one hop)" % MAX_FOLLOW_PER_COUNTY)
    ap.add_argument("--candidates", action="store_true",
                    help="read only the official candidate pages in data/acquisition_candidate_pages.csv (all states unless --state-filter)")
    ap.add_argument("--state-filter", action="append", default=[], help="with --candidates: limit to these states (repeatable)")
    ap.add_argument("--discovery", action="store_true",
                    help="AVAILABLE discovery mode: also select / follow FLC, assignment, over-the-counter, for-sale and "
                         "land-bank links; mask every digit; report table / PDF shapes only")
    ap.add_argument("--candidates-file", default=str(CANDIDATES),
                    help="with --candidates: the candidate list to read (default data/acquisition_candidate_pages.csv; "
                         "data/available_discovery_pages.csv holds the AVAILABLE discovery candidates)")
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args(argv)
    global DISCOVERY
    DISCOVERY = bool(getattr(args, "discovery", False))
    if args.digest:
        print(digest(Path(args.digest)))
        return 0
    counties = set(args.county) or None
    session = requests.Session()
    report = {"generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(), "state": args.state,
              "note": "county-level process text, links, phones and e-mails from the approved sources' own pages; "
                      "tables removed before reading; no row value, no parcel, no case number, no amount, no name"}
    if args.candidates:
        print("capturing official acquisition candidate pages", flush=True)
        report["state"] = ",".join(args.state_filter) or "all"
        report["candidates_file"] = Path(args.candidates_file).name
        report["available_sources"] = capture_candidates(session, set(args.state_filter) or None, counties, follow=args.follow,
                                                         path=Path(args.candidates_file))
    elif not args.skip_available:
        print(f"capturing AVAILABLE source pages ({args.state})", flush=True)
        report["available_sources"] = capture_available(session, args.state, counties, follow=args.follow)
    if args.realauction_date:
        print("RealAuction result-label discovery", flush=True)
        report["realauction_result_labels"] = capture_realauction(session, args.realauction_date, counties)
        if args.realauction_results:
            print("RealAuction closed/canceled area (AREA=C)", flush=True)
            report["realauction_results"] = capture_realauction_results(args.realauction_date, counties)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
