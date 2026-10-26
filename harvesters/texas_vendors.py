"""Texas tax-sale listings published by the delinquent-tax law firms and the
online auction platform the owner unblocked on 2026-10-26 (owner decision,
verbatim: "Do not block vendors. Post their shit and we'll figure out the
legal shit afterwards"; terms-of-service / robots.txt risk accepted, legal
review pending - data/source_permissions.csv records it as an interim,
expiring internal risk acceptance, never as permission).

  tx_pbfcm   Perdue Brandon Fielder Collins & Mott (www.pbfcm.com)
             taxsale.html   -> per-county sale lists (PDF)      -> AUCTIONS
             taxresale.html -> per-taxing-unit resale lists (PDF) -> AVAILABLE
  tx_mvba    McCreary Veselka Bragg & Allen (mvbalaw.com, mvbataxsales.com)
             /tax-sales/month-sales/           -> monthly sale lists (PDF)  -> AUCTIONS
             mvbataxsales.com /api/auctions + /api/getitems (JSON, the
               firm's own online auction site)                             -> AUCTIONS
             /tax-sales/trust-properties-for-sale/ -> trust lists (PDF)    -> AVAILABLE
  tx_govease GovEase (liveauctions.govease.com), Texas counties only
             /tx/<slug>/<id>/browse[/<page>] (server-rendered table) and
             each parcel's own page                                        -> AUCTIONS

Every structure here was read live on 2026-10-26 (docs/texas-vendor-sources.md).
Access is plain HTTPS GET/POST with an honest User-Agent, at most one request
per second per process (PoliteFetcher), no login, no CAPTCHA, no proxy. A
source that answers with a login wall or a refusal is recorded as FAILED for
that unit - never worked around.

Identity follows the repository's Texas convention (texas_harvester.py
"harvest_lgbs() shipped" note; CLAUDE.md data-quality sprint): the appraisal
district ACCOUNT is `account_number` (DB case_no); the tax-suit CAUSE number
is `cause_number` (DB parcel). A row with no account is never stored. A
figure is never invented: no published minimum -> min_bid None; no stated
sale date -> auction_date None.

Status per (source, county) - COMPLETE / EMPTY / INCOMPLETE / FAILED, worst
document wins, with per-ledger detail - is returned in `stats["units"]` and
written by texas_harvester.main() to out/harvest_texas_status.json.
"""
from __future__ import annotations

import csv
import html as htmllib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

try:  # both import contexts of texas_harvester.py
    from harvesters import tx_sale_tables as TABLES
except ImportError:  # pragma: no cover - run with harvesters/ on sys.path
    import tx_sale_tables as TABLES  # type: ignore

REPO = Path(__file__).resolve().parents[1]
USER_AGENT = "taxdeed-scraper/1.0"
# Never faster than one request per second, whatever the environment says.
MIN_INTERVAL_SECONDS = max(1.0, float(os.environ.get("TX_VENDOR_MIN_INTERVAL", "1.0") or 1.0))

COMPLETE, EMPTY, INCOMPLETE, FAILED = "COMPLETE", "EMPTY", "INCOMPLETE", "FAILED"
_SEVERITY = {EMPTY: 0, COMPLETE: 1, INCOMPLETE: 2, FAILED: 3}


# --- counties ---------------------------------------------------------------

def _load_counties() -> dict[str, str]:
    path = REPO / "data" / "tx_county_coverage_matrix.csv"
    with path.open(newline="", encoding="utf-8") as f:
        return {r["county"].strip().upper(): r["county"].strip() for r in csv.DictReader(f) if r.get("state") == "TX"}


_COUNTIES: dict[str, str] | None = None


def canonical_county(raw: str | None) -> str | None:
    """'FORT BEND COUNTY' / 'Ft Bend' / 'McLennan - MVBA' -> the repository's
    own county name (data/tx_county_coverage_matrix.csv, 254 counties), or
    None when the text names no Texas county (never guessed)."""
    global _COUNTIES
    if _COUNTIES is None:
        _COUNTIES = _load_counties()
    if not raw:
        return None
    name = htmllib.unescape(str(raw)).strip()
    name = re.split(r"\s+[-–]\s+|\(", name)[0]
    name = re.sub(r"\bCOUNTY\b.*$", "", name, flags=re.I).strip(" ,.-")
    name = re.sub(r"^FT\.?\s+", "FORT ", name, flags=re.I)
    return _COUNTIES.get(re.sub(r"\s+", " ", name).upper())


# --- polite HTTP ------------------------------------------------------------

class FetchError(Exception):
    def __init__(self, url: str, category: str, detail: str = ""):
        super().__init__(f"{category}: {detail}")
        self.url = url
        self.category = category


class PoliteFetcher:
    """HTTPS only; one request at a time, at least MIN_INTERVAL_SECONDS apart;
    a transient failure (connection, timeout, HTTP 5xx / 429) is retried with
    backoff; HTTP 401/403 is a refusal and is never retried or worked around."""

    def __init__(self, *, min_interval: float = MIN_INTERVAL_SECONDS, timeout: float = 60.0, attempts: int = 3,
                 opener: Callable | None = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.min_interval = max(1.0, float(min_interval))
        self.timeout = timeout
        self.attempts = max(1, attempts)
        self._opener = opener
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None
        self.requests = 0

    def _open(self, req):
        if self._opener is not None:
            return self._opener(req, timeout=self.timeout)
        try:
            from harvesters import tls_chain  # noqa: PLC0415
        except ImportError:  # pragma: no cover
            import tls_chain  # type: ignore  # noqa: PLC0415
        return tls_chain.urlopen(req, timeout=self.timeout)

    def _pace(self):
        if self._last is not None:
            wait = self.min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def request(self, url: str, data: dict | None = None, *, accept: str = "*/*") -> bytes:
        if not url.startswith("https://"):
            raise FetchError(url, "NOT_HTTPS", url)
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        headers = {"User-Agent": USER_AGENT, "Accept": accept}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        last_exc: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            self._pace()
            self.requests += 1
            req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
            try:
                with self._open(req) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403, 407):
                    raise FetchError(url, "ACCESS_REFUSED", f"HTTP {exc.code}") from exc
                if exc.code == 404:
                    raise FetchError(url, "NOT_FOUND", "HTTP 404") from exc
                if exc.code < 500 and exc.code != 429:
                    raise FetchError(url, "HTTP_ERROR", f"HTTP {exc.code}") from exc
                last_exc = exc
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
                last_exc = exc
            if attempt < self.attempts:
                self._sleep(2.0 * attempt)
        raise FetchError(url, "TRANSPORT", f"{type(last_exc).__name__}: {last_exc}")


# --- status book ------------------------------------------------------------

@dataclass
class UnitBook:
    """Per-(county) read outcomes for one source, from its documents."""
    units: dict[str, dict] = field(default_factory=dict)

    def record(self, county: str, ledger: str, status: str, *, url: str | None = None, rows: int = 0,
               signal: str = "") -> None:
        u = self.units.setdefault(county, {"status": EMPTY, "rows": 0, "ledgers": {}, "documents": []})
        u["rows"] += rows
        u["ledgers"][ledger] = max(u["ledgers"].get(ledger, EMPTY), status, key=_SEVERITY.get)
        u["status"] = max(u["status"], status, key=_SEVERITY.get)
        u["documents"].append({"url": url, "ledger": ledger, "status": status, "rows": rows, "signal": signal})

    def complete(self) -> bool:
        return all(u["status"] in (COMPLETE, EMPTY) for u in self.units.values())

    def stats(self) -> dict:
        return {k: self.units[k] for k in sorted(self.units)}

    def county_entries(self, source_id: str, *, index_errors: dict | None = None) -> list[dict]:
        """One entry per county in the status-file shape every reader uses
        (harvesters/ledgers/health.py reader_status): EMPTY carries the
        documents' own signal, a refused / unreachable read carries an
        ACCESS_ / TRANSPORT_ category (read as SOURCE_UNAVAILABLE).

        When an index page (a whole list of counties' documents) could not be
        read, no county of the source is vouched for: a COMPLETE / EMPTY
        county is reported INCOMPLETE, so a close-out never removes rows of
        the list that was not read."""
        out = []
        for county in sorted(self.units):
            u = self.units[county]
            signals = sorted({d["signal"] for d in u["documents"] if d.get("signal")})
            status = u["status"]
            if index_errors and status in (COMPLETE, EMPTY):
                status = INCOMPLETE
                signals.append("INDEX_UNREAD:" + ",".join(sorted(set(index_errors.values()))))
            e = {"source_id": source_id, "county": county, "status": status, "row_count": u["rows"],
                 "ledgers": dict(sorted(u["ledgers"].items())), "reason": ", ".join(signals)}
            if status == EMPTY:
                e["empty_signal"] = ", ".join(signals) or "no offered row in any listed document"
            if status == FAILED:
                failed = [d["signal"] for d in u["documents"] if d["status"] == FAILED]
                cat = failed[0] if failed else "TRANSPORT"
                e["error_category"] = cat if cat.startswith(("ACCESS_", "TRANSPORT")) else f"TRANSPORT_{cat}"
                e["transport_ok"] = False
            out.append(e)
        return out


def _row(*, source_id: str, ledger: str, county: str, account: str, cause: str | None = None,
         legal: str | None = None, address: str | None = None, min_bid: float | None = None,
         value: float | None = None, sale_date: str | None = None, auction_url: str | None = None,
         auction_url_kind: str | None = None, sale_list_url: str | None = None,
         latitude: float | None = None, longitude: float | None = None) -> dict:
    """A TexasSaleRow-shaped dict (texas_harvester.TexasSaleRow(**row))."""
    return {
        "account_number": account, "county": county, "state": "TX", "auction_date": sale_date,
        "min_bid": min_bid, "cad_market_value": value, "legal_description": legal, "address": address,
        "cause_number": cause, "latitude": latitude, "longitude": longitude, "source": ledger,
        "harvester_source": source_id, "auction_url": auction_url, "auction_url_kind": auction_url_kind,
        "sale_list_url": sale_list_url, "sale_status": None,
    }


def _clean_text(s: str | None, limit: int = 2000) -> str | None:
    if not s:
        return None
    s = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", s))).strip()
    return s[:limit] or None


_REDIRECT_NOTICE = re.compile(r"texascg|govease|for information on tax foreclosed|now being conducted exclusively", re.I)


def document_status(res: "TABLES.TableReadResult") -> tuple[str, str]:
    """What one parsed sale / resale document says, as a unit status.
    ROWS with no unreadable data row -> COMPLETE; a list whose rows were all
    marked pulled / sold / ... or a list table with no data row -> EMPTY; a
    notice that points elsewhere (another firm's site, GovEase) -> EMPTY; an
    image-only scan, an unrecognised layout or rows the reader could not
    identify -> INCOMPLETE (rows kept, nothing closed on it)."""
    if res.chars == 0:
        return INCOMPLETE, "IMAGE_ONLY"
    if res.rows:
        return (INCOMPLETE, "ROWS_WITH_UNREAD") if res.skipped_no_account else (COMPLETE, "ROWS")
    if res.skipped_no_account:
        return INCOMPLETE, "UNREAD_ROWS"
    if res.tables_used and not res.rows:
        return EMPTY, "LIST_WITHOUT_OFFERED_ROWS"
    if _REDIRECT_NOTICE.search(res.text or ""):
        return EMPTY, "REDIRECT_NOTICE"
    return INCOMPLETE, "UNRECOGNISED_LAYOUT"


def rows_from_document(res, *, source_id: str, ledger: str, county: str, url: str,
                       sale_date: str | None) -> list[dict]:
    out, seen = [], set()
    for r in res.rows:
        if r.account in seen:
            continue
        seen.add(r.account)
        out.append(_row(source_id=source_id, ledger=ledger, county=county, account=r.account, cause=r.cause,
                        legal=r.legal, address=r.address, min_bid=r.min_bid, value=r.value,
                        sale_date=sale_date if ledger == "auction" else None,
                        sale_list_url=url))
    return out


def _read_document(fetcher: PoliteFetcher, book: UnitBook, *, source_id: str, county: str, ledger: str,
                   url: str, read_pdf=None) -> list[dict]:
    read_pdf = read_pdf or TABLES.read_pdf
    try:
        data = fetcher.request(url, accept="application/pdf,*/*")
    except FetchError as exc:
        book.record(county, ledger, FAILED, url=url, signal=exc.category)
        return []
    if not data.startswith(b"%PDF"):
        book.record(county, ledger, INCOMPLETE, url=url, signal="NOT_A_PDF")
        return []
    try:
        res = read_pdf(data)
    except Exception as exc:  # noqa: BLE001 - a broken document is one unit's problem
        book.record(county, ledger, INCOMPLETE, url=url, signal=f"PARSE_ERROR:{type(exc).__name__}")
        return []
    status, signal = document_status(res)
    sale_date = TABLES.sale_date_from_text(res.text) if ledger == "auction" else None
    rows = rows_from_document(res, source_id=source_id, ledger=ledger, county=county, url=url, sale_date=sale_date)
    book.record(county, ledger, status, url=url, rows=len(rows), signal=signal)
    return rows


# --- PBFCM ------------------------------------------------------------------

PBFCM_BASE = "https://www.pbfcm.com/"
PBFCM_INDEXES = (("taxsale.html", "auction"), ("taxresale.html", "laft"))


@dataclass(frozen=True)
class Document:
    county: str
    label: str
    url: str
    ledger: str


def parse_pbfcm_index(page_html: str, ledger: str, base: str = PBFCM_BASE) -> tuple[list[Document], dict]:
    """The county entries of taxsale.html / taxresale.html. Commented-out
    entries (the page keeps inactive counties inside <!-- -->) are ignored;
    only the firm's own PDFs are documents - an external link (another
    firm's site, an appraisal district page) is counted, never followed."""
    text = re.sub(r"<!--.*?-->", "", page_html or "", flags=re.S)
    docs: list[Document] = []
    skipped = {"external_links": 0, "unknown_county": 0, "blank_links": 0}
    for entity in re.split(r'<li class="tax-list-entity"', text)[1:]:
        title = re.search(r'tax-list-entity-title">([^<]*)', entity)
        county = canonical_county(title.group(1) if title else None)
        for href, label in re.findall(r'<a href="([^"]*)"[^>]*>(.*?)</a>', entity, flags=re.S):
            href = htmllib.unescape(href).strip()
            if not href:
                skipped["blank_links"] += 1
                continue
            url = urllib.parse.urljoin(base, href)
            if urllib.parse.urlsplit(url).netloc.lower() not in ("www.pbfcm.com", "pbfcm.com") or not url.lower().endswith(".pdf"):
                skipped["external_links"] += 1
                continue
            if county is None:
                skipped["unknown_county"] += 1
                continue
            docs.append(Document(county, _clean_text(label) or "", url.replace("http://", "https://", 1), ledger))
    return docs, skipped


def harvest_pbfcm(fetcher: PoliteFetcher | None = None, stats: dict | None = None, limit: int | None = None,
                  read_pdf=None) -> list[dict]:
    fetcher = fetcher or PoliteFetcher()
    book, rows, index_errors, skipped_total = UnitBook(), [], {}, {}
    for page, ledger in PBFCM_INDEXES:
        try:
            page_html = fetcher.request(PBFCM_BASE + page, accept="text/html").decode("utf-8", "replace")
        except FetchError as exc:
            index_errors[page] = exc.category
            continue
        docs, skipped = parse_pbfcm_index(page_html, ledger)
        for k, v in skipped.items():
            skipped_total[k] = skipped_total.get(k, 0) + v
        if not docs:
            index_errors[page] = "NO_DOCUMENTS_LISTED"
        for doc in docs:
            rows.extend(_read_document(fetcher, book, source_id="tx_pbfcm", county=doc.county, ledger=ledger,
                                       url=doc.url, read_pdf=read_pdf))
            if limit is not None and len(rows) >= limit:
                break
    rows = _dedupe(rows)
    if stats is not None:
        stats.update({"complete": not index_errors and book.complete(), "index_errors": index_errors,
                      "skipped_links": skipped_total, "units": book.stats(), "requests": fetcher.requests,
                      "rows_kept": len(rows), "county_entries": book.county_entries("tx_pbfcm", index_errors=index_errors)})
    _log("harvest_pbfcm", rows, book, index_errors)
    return rows[:limit] if limit is not None else rows


# --- MVBA -------------------------------------------------------------------

MVBA_MONTH_URL = "https://mvbalaw.com/tax-sales/month-sales/"
MVBA_TRUST_URL = "https://mvbalaw.com/tax-sales/trust-properties-for-sale/"
MVBA_AUCTION_SITE = "https://www.mvbataxsales.com"
_MVBA_PDF = re.compile(r'<a[^>]+href="(https://mvbalaw\.com/wp-content/TaxUploads/[^"]+\.pdf)"[^>]*>(.*?)</a>', re.I | re.S)


def parse_mvba_page(page_html: str, ledger: str) -> tuple[list[Document], dict]:
    """The PDF links of the month-sales / trust page, county from the link
    text ('Bastrop County', 'Bandera County Sale Information'). A link whose
    text is information about a sale rather than a list ('Sale Information')
    is not a document of properties."""
    docs, skipped = [], {"unknown_county": 0, "information_only": 0}
    main = page_html or ""
    for url, label in _MVBA_PDF.findall(main):
        text = _clean_text(label) or ""
        if re.search(r"sale\s+information|info\b", text, re.I) or re.search(r"saleinfo", url, re.I):
            skipped["information_only"] += 1
            continue
        county = canonical_county(text)
        if county is None:
            skipped["unknown_county"] += 1
            continue
        docs.append(Document(county, text, url, ledger))
    return docs, skipped


def _mvba_county(item: dict, auction_title: str) -> str | None:
    desc = _clean_text(item.get("description")) or _clean_text(item.get("title")) or ""
    m = re.search(r"([A-Z][A-Za-z.' ]{1,30}?)\s+County,\s+Texas", desc)
    county = canonical_county(m.group(1)) if m else None
    if county is None:
        m = re.search(r"([A-Z][A-Za-z.' ]{1,30}?)\s+COUNTY\s+ONLINE", auction_title or "", re.I)
        county = canonical_county(m.group(1).split("-")[-1].strip()) if m else None
    return county


_MVBA_ACCOUNT = re.compile(r"Account\s+No\.?\s*([A-Z0-9][A-Z0-9\-./]{1,40})", re.I)
_MVBA_SUIT = re.compile(r"Suit\s+No\.?\s*([A-Z0-9][A-Z0-9\-./]{1,30})", re.I)
_MVBA_ADDRESS = re.compile(r"Approximate\s+Property\s+Address:\s*([^:]{4,160}?)\s*(?::::::|$)", re.I)


def mvba_item_row(item: dict, *, auction: dict) -> tuple[dict | None, str]:
    """One mvbataxsales.com /api/getitems item -> a row, or (None, why)."""
    desc = _clean_text(item.get("description")) or ""
    extra = _clean_text(item.get("extra_info")) or ""
    if re.search(r"WITHDRAWN|CANCEL+ED|PULLED|REDEEMED", f"{desc} {extra}", re.I):
        return None, "withdrawn"
    m = _MVBA_ACCOUNT.search(desc)
    if not m:
        return None, "no_account"
    account = m.group(1).rstrip(".,;:").split("/")[0]
    county = _mvba_county(item, auction.get("title") or "")
    if county is None:
        return None, "unknown_county"
    cause = _MVBA_SUIT.search(desc)
    addr = _MVBA_ADDRESS.search(desc)
    parts = [p.strip() for p in desc.split(":::::")]
    legal = re.sub(r"^Account\s+No\.?\s*\S+\s*,?\s*", "", parts[0], flags=re.I).strip(" ,") or None
    bid = TABLES.plain_number(str(item.get("minimum_bid") or item.get("starting_bid") or ""))
    starts = str(auction.get("starts") or "")
    sale_date = starts[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", starts) else None
    url = item.get("item_url") or ""
    url = url if url.startswith("https://www.mvbataxsales.com/") else None
    return _row(source_id="tx_mvba", ledger="auction", county=county, account=account,
                cause=cause.group(1).rstrip(".,;:") if cause else None, legal=legal,
                address=addr.group(1).strip(" ,") if addr else None, min_bid=bid, sale_date=sale_date,
                auction_url=url, auction_url_kind="property" if url else None), "row"


def harvest_mvba_online(fetcher: PoliteFetcher, book: UnitBook) -> tuple[list[dict], dict]:
    """The firm's own online sales (mvbataxsales.com, AuctionMethod JSON):
    /api/auctions lists the open auctions, /api/getitems with auction_id
    pages one auction's items (24 a page, `filters[page]`)."""
    info: dict = {"auctions": 0, "items": 0, "skipped": {}}
    try:
        listing = json.loads(fetcher.request(f"{MVBA_AUCTION_SITE}/api/auctions",
                                             {"filters[page]": "1", "past_sales": "false"}, accept="application/json"))
    except (FetchError, ValueError) as exc:
        info["error"] = getattr(exc, "category", "BAD_JSON")
        return [], info
    rows = []
    for auction in listing.get("data") or []:
        try:
            item_count = int(auction.get("item_count") or 0)
        except ValueError:
            item_count = 0
        if str(auction.get("completed")) == "1" or item_count <= 0:
            continue
        info["auctions"] += 1
        aid = str(auction.get("id"))
        county_hint = _mvba_county({}, auction.get("title") or "")
        auction_rows, page, pages, ok = [], 1, 1, True
        while page <= pages and page <= 50:
            try:
                payload = json.loads(fetcher.request(f"{MVBA_AUCTION_SITE}/api/getitems",
                                                     {"auction_id": aid, "filters[page]": str(page)},
                                                     accept="application/json"))
            except (FetchError, ValueError) as exc:
                ok = False
                info.setdefault("errors", []).append(getattr(exc, "category", "BAD_JSON"))
                break
            pages = int(payload.get("total_pages") or 1)
            for item in payload.get("items") or []:
                if str(item.get("auction_id")) != aid:
                    continue  # the endpoint ignores an unknown filter by listing everything; never mix auctions
                info["items"] += 1
                row, why = mvba_item_row(item, auction=auction)
                if row is None:
                    info["skipped"][why] = info["skipped"].get(why, 0) + 1
                    continue
                auction_rows.append(row)
            page += 1
        counties = {r["county"] for r in auction_rows} or ({county_hint} if county_hint else set())
        url = f"{MVBA_AUCTION_SITE}/auction/{auction.get('auction_id_slug') or aid}/bidgallery/"
        for county in counties:
            n = sum(1 for r in auction_rows if r["county"] == county)
            book.record(county, "auction", COMPLETE if ok and n else (EMPTY if ok else FAILED), url=url, rows=n,
                        signal="ONLINE_AUCTION")
        rows.extend(auction_rows)
    return rows, info


def harvest_mvba(fetcher: PoliteFetcher | None = None, stats: dict | None = None, limit: int | None = None,
                 read_pdf=None) -> list[dict]:
    fetcher = fetcher or PoliteFetcher()
    book, rows, index_errors, skipped_total = UnitBook(), [], {}, {}
    for page_url, ledger in ((MVBA_MONTH_URL, "auction"), (MVBA_TRUST_URL, "laft")):
        try:
            page_html = fetcher.request(page_url, accept="text/html").decode("utf-8", "replace")
        except FetchError as exc:
            index_errors[page_url] = exc.category
            continue
        docs, skipped = parse_mvba_page(page_html, ledger)
        for k, v in skipped.items():
            skipped_total[k] = skipped_total.get(k, 0) + v
        for doc in docs:
            rows.extend(_read_document(fetcher, book, source_id="tx_mvba", county=doc.county, ledger=ledger,
                                       url=doc.url, read_pdf=read_pdf))
    online_rows, online = harvest_mvba_online(fetcher, book)
    if online.get("error"):
        index_errors[MVBA_AUCTION_SITE] = online["error"]
    rows.extend(online_rows)
    rows = _dedupe(rows)
    if stats is not None:
        stats.update({"complete": not index_errors and book.complete(), "index_errors": index_errors,
                      "skipped_links": skipped_total, "online": online, "units": book.stats(),
                      "requests": fetcher.requests, "rows_kept": len(rows), "county_entries": book.county_entries("tx_mvba", index_errors=index_errors)})
    _log("harvest_mvba", rows, book, index_errors)
    return rows[:limit] if limit is not None else rows


# --- GovEase ----------------------------------------------------------------

GOVEASE_BASE = "https://liveauctions.govease.com"
# Any Texas county's browse page carries the whole county picker; this one
# was live on 2026-10-26. If it ever stops answering, the run is FAILED.
GOVEASE_SEED = f"{GOVEASE_BASE}/tx/txwichita/1429/browse"
GOVEASE_PAGE_LIMIT = 40


@dataclass(frozen=True)
class GovEaseCounty:
    county: str
    slug: str
    county_id: str
    label: str

    @property
    def browse_url(self) -> str:
        return f"{GOVEASE_BASE}/tx/{self.slug}/{self.county_id}/browse"


def parse_govease_counties(page_html: str) -> tuple[list[GovEaseCounty], list[str]]:
    """The Texas entries of the county picker: <option value="tx|<slug>|<id>">TX - <County>[ - note]</option>."""
    found, unknown, seen = [], [], set()
    for value, label in re.findall(r'<option value="(tx\|[a-z0-9]+\|\d+)"[^>]*>([^<]*)</option>', page_html or "", re.I):
        _, slug, cid = value.split("|")
        if (slug, cid) in seen:
            continue
        seen.add((slug, cid))
        name = re.sub(r"^\s*TX\s*-\s*", "", htmllib.unescape(label)).strip()
        county = canonical_county(name)
        if county is None:
            unknown.append(name)
            continue
        found.append(GovEaseCounty(county, slug.lower(), cid, name))
    return found, unknown


def _cells(row_html: str) -> list[str]:
    return [re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
            for c in re.findall(r"<td[^>]*>(.*?)</td>", row_html, flags=re.S)]


def parse_govease_browse(page_html: str) -> tuple[list[dict], bool]:
    """The browse table: header names -> cell values per row, plus each
    row's own parcel link. Returns (rows, table_present)."""
    table = re.search(r'<table id="dt-auctions".*?</table>', page_html or "", flags=re.S)
    if not table:
        return [], False
    head = re.search(r"<thead.*?</thead>", table.group(0), flags=re.S)
    names = [re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", c))).strip().rstrip(":").strip()
             for c in re.findall(r"<th[^>]*>(.*?)</th>", head.group(0) if head else "", flags=re.S)]
    out = []
    for row_html in re.findall(r'<tr role="row" class="(?:odd|even)[^"]*"[^>]*>(.*?)</tr>', table.group(0), flags=re.S):
        cells = _cells(row_html)
        link = re.search(r'href="(/tx/[^"]+/open(?:standard)?parcel/[^"]+)"', row_html)
        rec = {names[i]: cells[i] for i in range(min(len(names), len(cells))) if names[i]}
        rec["_link"] = GOVEASE_BASE + htmllib.unescape(link.group(1)) if link else None
        out.append(rec)
    return out, True


def parse_govease_parcel(page_html: str) -> dict:
    """A parcel page's labelled facts (Physical Address, Property
    Description, Legal Description, Minimum Bid / Starting Bid / Face Value)
    and the sale start the page states ('scheduled to begin MM/DD/YYYY')."""
    text = re.sub(r"<(script|style).*?</\1>", "", page_html or "", flags=re.S | re.I)
    lines = [l.strip() for l in htmllib.unescape(re.sub(r"<[^>]+>", "\n", text)).split("\n") if l.strip()]
    labels = {"Physical Address", "Property Description", "Legal Description", "Minimum Bid", "Starting Bid",
              "Face Value", "Tax Year", "Unique #", "Primary Owner", "Assessed Land", "Assessed Improvements",
              "Total True Value", "True Building Value", "True Land Value", "Address", "Information",
              "Current Bid"}
    facts: dict[str, str] = {}
    i = 0
    while i < len(lines):
        if lines[i] in labels:
            key, vals = lines[i], []
            i += 1
            while i < len(lines) and lines[i] not in labels and not lines[i].startswith("©"):
                vals.append(lines[i])
                i += 1
            facts.setdefault(key, "\n".join(vals))
            continue
        i += 1
    m = re.search(r"scheduled to begin\s+(\d{1,2})/(\d{1,2})/(20\d\d)", " ".join(lines), re.I)
    if m:
        facts["_sale_date"] = f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return facts


_GE_ACCOUNT = re.compile(r"\bAccount\s*(?:Number|No\.?|#)\s*:?\s*#?\s*([A-Z0-9][A-Z0-9\-./]{2,40})", re.I)
_GE_CAUSE = re.compile(r"\b(?:Cause|Suit)\s*(?:Number|No\.?|#)\s*:?\s*([A-Z0-9][A-Z0-9\-./,]{2,40})", re.I)
_GE_VALUE = re.compile(r"Adjudged\s+Value\s*:?\s*\$?\s*([0-9][0-9,]*(?:\.\d{1,2})?)", re.I)
_GE_NOT_TAX = re.compile(r"\bHOA\b|homeowners?'?\s+association|owners association", re.I)


def govease_row(county: str, rec: dict, facts: dict) -> tuple[dict | None, str]:
    """One browse-table row (+ its parcel page) -> a row, or (None, why).
    The browse table's 'Parcel #' is the CAD account in some counties
    (Wichita, Parker, Palo Pinto) and the suit number in others (Grayson,
    McLennan, Denton): a labelled 'Account' on the row or its page decides,
    and only then is 'Parcel #' read as the cause."""
    desc = "\n".join(x for x in (rec.get("Property Description"), facts.get("Property Description")) if x)
    if _GE_NOT_TAX.search(desc):
        return None, "not_a_tax_sale"
    parcel_no = (rec.get("Parcel #") or "").strip()
    acct = _GE_ACCOUNT.search(desc)
    cause = _GE_CAUSE.search(desc)
    if acct:
        account = acct.group(1).rstrip(".,;:").split("/")[0]
        cause_no = cause.group(1).rstrip(".,;:") if cause else (parcel_no if parcel_no and parcel_no != account else None)
    elif cause:
        account, cause_no = parcel_no, cause.group(1).rstrip(".,;:")
    else:
        # Neither labelled: 'Parcel #' is all the source gives. It is kept
        # as the account only when it is not the shape of a suit number.
        if not parcel_no or re.match(r"^(?:T-?)?\d{2,4}-\d", parcel_no, re.I):
            return None, "no_account"
        account, cause_no = parcel_no, None
    if not account or account == cause_no:
        cause_no = None if account == cause_no else cause_no
    if not account:
        return None, "no_account"
    bid = None
    for k in ("Minimum Bid", "Face Value", "Starting Bid"):
        bid = TABLES.money(rec.get(k)) or TABLES.money(facts.get(k))
        if bid:
            break
    vm = _GE_VALUE.search(desc)
    value = TABLES.plain_number(vm.group(1)) if vm else None
    address = _clean_text(rec.get("Parcel Address") or facts.get("Physical Address"), 160)
    legal = _clean_text(facts.get("Legal Description"))
    return _row(source_id="tx_govease", ledger="auction", county=county, account=account, cause=cause_no,
                legal=legal, address=address, min_bid=bid, value=value, sale_date=facts.get("_sale_date"),
                auction_url=rec.get("_link"), auction_url_kind="property" if rec.get("_link") else None), "row"


def harvest_govease(fetcher: PoliteFetcher | None = None, stats: dict | None = None, limit: int | None = None,
                    county_slugs: list[str] | None = None) -> list[dict]:
    fetcher = fetcher or PoliteFetcher()
    book, rows, index_errors, skipped = UnitBook(), [], {}, {}
    try:
        seed = fetcher.request(GOVEASE_SEED, accept="text/html").decode("utf-8", "replace")
        counties, unknown = parse_govease_counties(seed)
    except FetchError as exc:
        counties, unknown = [], []
        index_errors["county_picker"] = exc.category
    if not counties and not index_errors:
        index_errors["county_picker"] = "NO_TEXAS_COUNTIES_LISTED"
    if county_slugs:
        counties = [c for c in counties if c.slug in set(county_slugs)]
    for c in counties:
        county_rows, seen_links, ok = [], set(), True
        page_num, page_base = 1, c.browse_url
        while page_num <= GOVEASE_PAGE_LIMIT:
            url = c.browse_url if page_num == 1 else f"{page_base}/{page_num}"
            try:
                page_html = fetcher.request(url, accept="text/html").decode("utf-8", "replace")
                listing, present = parse_govease_browse(page_html)
                if page_num == 1:
                    # The page names its own listing path ('/browse' or '/browsestandard');
                    # later pages are '<that path>/<n>' (the site's own gotoPage()).
                    post = re.search(r'id="SearchCriteria_PostUrl"[^>]*value="(/tx/[a-z0-9]+/\d+/browse[a-z]*)"', page_html, re.I)
                    if post:
                        page_base = GOVEASE_BASE + post.group(1)
            except FetchError as exc:
                ok = False
                book.record(c.county, "auction", FAILED, url=url, signal=exc.category)
                break
            if not present:
                if page_num == 1:
                    ok = False
                    book.record(c.county, "auction", INCOMPLETE, url=url, signal="NO_LISTING_TABLE")
                break
            new = [r for r in listing if r.get("_link") and r["_link"] not in seen_links]
            if not new:
                break
            for rec in new:
                seen_links.add(rec["_link"])
                facts = {}
                try:
                    facts = parse_govease_parcel(fetcher.request(rec["_link"], accept="text/html").decode("utf-8", "replace"))
                except FetchError:
                    skipped["parcel_page_unreadable"] = skipped.get("parcel_page_unreadable", 0) + 1
                row, why = govease_row(c.county, rec, facts)
                if row is None:
                    skipped[why] = skipped.get(why, 0) + 1
                    continue
                county_rows.append(row)
            if len(listing) < 50:
                break
            page_num += 1
        if ok:
            book.record(c.county, "auction", COMPLETE if county_rows else EMPTY, url=c.browse_url,
                        rows=len(county_rows), signal="BROWSE_TABLE")
        rows.extend(county_rows)
        if limit is not None and len(rows) >= limit:
            break
    rows = _dedupe(rows)
    if stats is not None:
        stats.update({"complete": not index_errors and book.complete(), "index_errors": index_errors,
                      "unknown_counties": unknown if counties or unknown else [], "skipped_rows": skipped,
                      "units": book.stats(), "requests": fetcher.requests, "rows_kept": len(rows),
                      "county_entries": book.county_entries("tx_govease", index_errors=index_errors)})
    _log("harvest_govease", rows, book, index_errors)
    return rows[:limit] if limit is not None else rows


# --- shared -----------------------------------------------------------------

def _dedupe(rows: list[dict]) -> list[dict]:
    """One row per (ledger, county, account); the first read wins."""
    out, seen = [], set()
    for r in rows:
        key = (r["source"], r["county"], r["account_number"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _log(name: str, rows: list[dict], book: UnitBook, index_errors: dict) -> None:
    by_status: dict[str, int] = {}
    for u in book.units.values():
        by_status[u["status"]] = by_status.get(u["status"], 0) + 1
    print(f"{name}: kept {len(rows)} TX rows across {len({r['county'] for r in rows})} counties; "
          f"units {dict(sorted(by_status.items()))}; index errors {index_errors or 'none'}", file=sys.stderr)
