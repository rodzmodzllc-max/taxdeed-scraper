#!/usr/bin/env python3
"""
Harvest "Lands Available for Taxes" (LAFT) PDFs.

LAFT is Florida's fixed-price leftover-inventory program: a property that got
zero bids at a county's tax deed auction goes on this list, purchasable
directly from the Clerk at a set price for a statutory period. It is NOT the
same product as tax certificates (a separate lien-investment program, already
covered by harvest_lienhub_certificates.ps1) - do not merge the two.

As of 2026-08, none of the 67 counties had ANY automated LAFT coverage - a
67-county research pass (see LAFT_coverage_audit.xlsx delivered separately)
found the list is published as a real, scrapable HTML table in ~20 counties,
behind a search portal in ~27, and as a PDF in a handful. This script covers
the PDF ones specifically - the confirmed-URL list lives in
../data/laft_pdf_sources.csv, one row per county, so adding a county is a CSV
edit, not a code change. Every row was individually confirmed live (fetched
and read, not just found in a search result) before being added - see the
CSV's Notes column for what was confirmed and when. Sumter was checked and
found to publish its list as plain HTML on the clerk site rather than a PDF -
deliberately excluded here, would need a separate HTML scraper.

Deliberately conservative about what's actually confirmed: a county that
*might* publish LAFT as a PDF (e.g. a dead/stale link, or a page seen only in
search results but never actually fetched and read) does NOT belong in the
CSV. Every row here was fetched and its real column layout read before being
added - see the Notes column in the CSV for what was confirmed and when.

Every county's PDF has a different column layout (confirmed different even
across the 3 in this first batch), so this uses a tolerant header-name
normalizer rather than assuming one fixed schema - see HEADER_MAP below.
"Amount to Purchase" / opening bid is often just not published at all (e.g.
Marion) - never fabricate one; leave it null rather than guess.

Output: harvest_laft.json / harvest_laft.csv (source='laft', kept separate
from harvest_all.json/harvest_certificates.json - synced by
sync-laft-to-supabase.ps1, not the other two sync scripts).
"""
from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path

import pdfplumber
import requests

from harvest_cache import PARSER_VERSION, conditional_get, load_cache, record_cache_stats, save_cache
from laft_status import StatusRecorder, amount_kind_for_header, describe_exception, extract_list_as_of, record_identifiers_plausible

HERE = Path(__file__).resolve().parent
SOURCES_CSV = HERE / "../data/laft_pdf_sources.csv"
OUT_DIR = HERE / "../out"
OUT_JSON = OUT_DIR / "harvest_laft.json"
OUT_CSV = OUT_DIR / "harvest_laft.csv"

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Column-header aliases -> normalized field name. Matched case-insensitively
# after stripping whitespace/punctuation. Add new aliases here as new
# counties' PDFs get confirmed and added to the CSV - do NOT special-case a
# county by name in the parsing logic itself.
HEADER_MAP = {
    "case number": "case_no", "case #": "case_no", "case no": "case_no",
    "sale #": "case_no", "sale number": "case_no",
    "file no.": "case_no", "file no": "case_no", "file number": "case_no",
    # "Tax Deed #" (Pasco) and bare "certificate" / "certificate:" (Glades,
    # F.S. 197.502(7) statutory template - the colon is already stripped by
    # normalize_header before this dict is consulted).
    "tax deed #": "case_no", "tax deed number": "case_no",
    "certificate #": "certificate_no", "certificate number": "certificate_no",
    "cert. no": "certificate_no", "cert no": "certificate_no", "cert. no.": "certificate_no",
    "certificate": "certificate_no", "tax certificate #": "certificate_no",
    "parcel id": "parcel", "parcel #": "parcel", "parcel number": "parcel",
    "parcel identification number": "parcel",
    # Added 2026-09-07 after confirming on Volusia's LAFT PDF (see
    # laft_pdf_sources.csv): pdfplumber's text-based table strategy can
    # cluster this column's "Short Parcel ID Number" header into a cell
    # that never includes "ID NUMBER", so the exact-string aliases above
    # never fire and the whole table - real, currently-purchasable
    # properties included - was being silently discarded as unrecognized.
    "short parcel": "parcel", "short parcel id": "parcel",
    "short parcel id number": "parcel",
    "owner": "owner_name", "owners": "owner_name", "owner(s)": "owner_name",
    "name in which assessed": "owner_name",
    "auction date": "sale_date", "sale date": "sale_date",
    "original sale date": "sale_date", "tax deed sale date": "sale_date",
    "date of tax deed sale": "sale_date",
    "escheatment date": "escheatment_date", "expiration date": "escheatment_date",
    "amount to purchase": "bid", "opening bid": "bid", "minimum bid": "bid",
    "original opening bid": "bid", "purchase price": "bid", "price": "bid",
    "initial bid": "bid",
    "assessed value": "assessed", "property address": "address", "address": "address",
    "taxes address": "address",
    "legal description": "legal_desc", "description": "legal_desc",
    "description of property": "legal_desc",
    # If this column has a value, the property has already been sold and is
    # no longer available - confirmed on Hendry's PDF ("SOLD TO"). Rows with
    # a non-blank sold_to are filtered out in _rows_from_table below rather
    # than surfaced as a currently-purchasable property.
    "sold to": "sold_to", "sold": "sold_to", "purchaser": "sold_to",
}

# Phrases seen in an otherwise-empty PDF that mean "no properties right now"
# rather than "the parser failed to find a table" - must not be treated as an
# error, and must not produce a fake row.
EMPTY_MARKERS = (
    "no available lands", "no properties at this time", "no properties available",
    "no parcels available", "there are no properties", "nothing available",
)


def normalize_header_key(h: str) -> str:
    """The normalised header text HEADER_MAP is keyed by (also what
    laft_status.amount_kind_for_header() reads the amount kind from)."""
    key = re.sub(r"[^a-z0-9()#. ]", "", (h or "").strip().lower())
    return re.sub(r"\s+", " ", key).strip()


def normalize_header(h: str) -> str | None:
    if not h:
        return None
    return HEADER_MAP.get(normalize_header_key(h))


# Municode-hosted PDFs (Hendry, Glades) live behind a per-document download
# id that changes when the clerk uploads a new version - the registered
# Hendry URL returned HTTP 404 on 2026-09-29. The clerk's own Municode node
# page (the CSV's SourcePage) embeds the CURRENT download link, so on a 404
# the harvester reads that page and follows the first munidocDownload link
# it finds. Best effort, and honestly limited: the node page is largely
# JavaScript-rendered, so the link may not be present in the static HTML;
# when it is not, the county is recorded FAILED / TRANSPORT_HTTP_404 with
# the reason, never as an empty list. Not verified against the live site
# from this sandbox (egress blocked) - see docs/otc-inventory-model.md.
MUNICODE_HOST = "mcclibraryfunctions.azurewebsites.us"
_MUNIDOC_LINK_RE = re.compile(r"https?://mcclibraryfunctions\.azurewebsites\.us/api/munidocDownload/\d+/[0-9a-f]+/pdf", re.I)
_MUNIDOC_RELATIVE_RE = re.compile(r"/api/munidocDownload/\d+/[0-9a-f]+/pdf", re.I)


def discover_successor_pdf(source_page_html: str, current_url: str) -> str | None:
    """First munidocDownload PDF link on the clerk's Municode node page that
    is NOT the (dead) URL we already tried, or None."""
    if not source_page_html:
        return None
    candidates = list(_MUNIDOC_LINK_RE.findall(source_page_html))
    candidates += [f"https://{MUNICODE_HOST}{m}" for m in _MUNIDOC_RELATIVE_RE.findall(source_page_html)]
    for cand in candidates:
        if cand.rstrip("/") != current_url.rstrip("/"):
            return cand
    return None


def source_class_for_url(url: str) -> str:
    """Government-hosted document -> GOVERNMENT_DIRECT; a clerk document
    published through a third-party document platform (Municode) ->
    GOVERNMENT_PLATFORM. The clerk is the source of record either way."""
    return "GOVERNMENT_PLATFORM" if MUNICODE_HOST in (url or "") else "GOVERNMENT_DIRECT"


def normalize_parcel(p: str) -> str:
    """Light, non-destructive cleanup of a parcel/folio number as extracted
    from PDF cell text: trims stray whitespace PDF extraction leaves around
    tokens and collapses internal whitespace, then uppercases. Never touches
    digits, dashes, or leading zeros - those are part of the county's real
    parcel format and altering them would make the displayed number wrong."""
    return re.sub(r"\s+", "", p.strip()).upper()


def canonical_key(value: str) -> str:
    """Strip every non-alphanumeric character and uppercase, producing a
    format-independent matching key. Two parcel numbers that print
    differently only because of dash/space placement (e.g.
    "10-27-25-C1-00001.0100" vs "102725C100001.0100") collapse to the same
    key here."""
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def finalize_record(record: dict) -> dict:
    """Applied to every extracted row right before it's kept. Normalizes the
    displayed parcel value and - when the source PDF doesn't publish a real
    case/file number - derives a stable, format-independent case_no from the
    parcel so sync-laft-to-supabase.ps1's on_conflict(source,county,case_no)
    upsert always recognizes the same physical property across harvest runs,
    even if the PDF's parcel formatting drifts slightly between runs (this
    is what was causing Hendry's duplicate-card bug: two harvests of the
    same property extracted its parcel with different punctuation, so each
    run's case_no fallback - previously just the raw parcel string - never
    matched the other run's row, and both stuck around as separate rows)."""
    if record.get("parcel"):
        record["parcel"] = normalize_parcel(record["parcel"])
    if not record.get("case_no") and record.get("parcel"):
        record["case_no"] = canonical_key(record["parcel"])
    return record


def looks_empty(text: str) -> bool:
    # Collapse all whitespace (including the mid-phrase line breaks PDF text
    # extraction leaves behind, e.g. DeSoto's placeholder wraps as "NO
    # PROPERTIES\nAT THIS TIME") so EMPTY_MARKERS matches regardless of how
    # the source PDF wrapped the line.
    low = re.sub(r"\s+", " ", text.lower())
    return any(marker in low for marker in EMPTY_MARKERS)


def _find_header_row(table: list) -> tuple[int, list] | None:
    """Return (row_index, field_names) for whichever row looks most like a
    real header, or None if no row is a plausible match.

    Can't just assume row 0 - confirmed on Hendry, whose PDF renders the
    title, the multi-line disclaimer paragraph, AND the actual data all
    inside one pdfplumber-detected table (one bordered box with internal
    divider lines), so the real "File No. / Cert. No / ..." header sits
    several rows down, with the title text ("LIST OF LANDS AVAILABLE FOR
    TAXES") misidentified as row 0 instead. Score every row by how many
    cells normalize to a known field and take the best one, requiring at
    least 2 matches so a stray coincidental match (e.g. a "Description"
    sentence in the preamble) can't be mistaken for a real header.
    """
    best_idx, best_fields, best_score = None, None, 1
    for idx, row in enumerate(table):
        fields = [normalize_header(c) for c in row]
        score = sum(1 for f in fields if f)
        if score > best_score:
            best_idx, best_fields, best_score = idx, fields, score
    if best_idx is None:
        return None
    return best_idx, best_fields


# Rows the county's own list marks sold ('Sold To' / 'Purchaser' column
# with a value - Hendry keeps them on the list). They are never inventory,
# but they ARE a source-published result: their IDENTITY (county + case /
# parcel, never the purchaser) is written to out/harvest_laft_sold_pdfs.json
# for scripts/inventory_status_writer.py. Reset per run in main().
SOLD_ROWS: list[dict] = []
OUT_SOLD_JSON = OUT_DIR / "harvest_laft_sold_pdfs.json"


def record_sold_identity(record: dict) -> None:
    ident = finalize_record({k: record.get(k) for k in ("county", "case_no", "parcel") if record.get(k)})
    if ident.get("county") and (ident.get("case_no") or ident.get("parcel")) and record_identifiers_plausible(ident):
        SOLD_ROWS.append({"county": ident["county"], "case_no": ident.get("case_no"), "parcel": ident.get("parcel"), "source": "laft"})


def _rows_from_table(table: list, county: str, source_url: str, rejected: list | None = None) -> list[dict]:
    """`rejected` (optional list) collects the count of rows dropped by the
    identifier plausibility gate (laft_status.record_identifiers_plausible)
    so extract_rows_with_outcome() can report them; the values themselves
    are never logged."""
    rows: list[dict] = []
    if not table or len(table) < 2:
        return rows
    found_header = _find_header_row(table)
    if not found_header:
        return rows  # not a recognizable data table - e.g. a stray formatting grid
    header_idx, field_names = found_header
    header_keys = [normalize_header_key(str(c)) if c else "" for c in table[header_idx]]
    body = table[header_idx + 1:]
    for raw in body:
        # Defense in depth: a "no properties" notice can render as a
        # 1-column/1-row table rather than page-level text (this is what
        # actually happened for DeSoto - looks_empty() missed it because of
        # a mid-phrase line break, and every cell in the row was the same
        # placeholder sentence). Skip a row outright if every non-empty cell
        # is itself an empty marker - it is never real property data.
        cell_texts = [str(c).strip() for c in raw if c and str(c).strip()]
        if cell_texts and all(looks_empty(c) for c in cell_texts):
            continue

        record: dict = {"county": county, "source": "laft", "url_auction": source_url}
        for i, field in enumerate(field_names):
            if not field or i >= len(raw) or raw[i] is None:
                continue
            val = str(raw[i]).strip()
            if val:
                record[field] = val
                if field == "bid":
                    # What the county's own column label says this amount
                    # IS - carried through to purchase_amount_kind.
                    record["bid_kind"] = amount_kind_for_header(header_keys[i] if i < len(header_keys) else None)
        # A "SOLD TO" (or similar) column with a value means this property
        # has already been purchased and is no longer available - confirmed
        # on Hendry's PDF, which keeps sold rows on the same list rather
        # than removing them. Never surface those as a currently-available
        # property.
        if record.get("sold_to"):
            record_sold_identity(record)
            continue
        # A row needs at least a case/parcel identifier to be worth keeping -
        # matches the same "skip if no case/address" discipline
        # sync-harvest-to-supabase.ps1 already applies to the auction ledger.
        if record.get("case_no") or record.get("parcel"):
            # Identifier plausibility gate: a wrapped column heading or a
            # paragraph that landed in the parcel/case cell is not a
            # property (Volusia "IDNUMBER", Pasco's whole-page run - see
            # laft_status.plausible_identifier). Dropped whole, counted.
            if not record_identifiers_plausible(record):
                if rejected is not None:
                    rejected.append(1)
                continue
            rows.append(finalize_record(record))
    return rows


# Every HEADER_MAP key, longest-first so e.g. "sale date" matches before the
# more generic "sale #" would ever get a chance to swallow it. Used by
# extract_label_value_rows() below - the last-resort parser for counties
# that publish LAFT as plain "Label: value" text rather than any kind of
# grid pdfplumber can detect as a table (confirmed on Marion: two properties,
# each just "Sale #: ... Sale Date: ... Parcel #: ... Description: ...", no
# ruling lines and no whitespace-aligned columns either).
_LABEL_PATTERN = re.compile(
    r"(?i)(" + "|".join(re.escape(k) for k in sorted(HEADER_MAP, key=len, reverse=True)) + r")\s*:?\s+"
)


def extract_label_value_rows(full_text: str, county: str, source_url: str, rejected: list | None = None) -> list[dict]:
    matches = list(_LABEL_PATTERN.finditer(full_text))
    if not matches:
        return []
    # The field of the very first label seen is treated as the per-property
    # anchor: seeing it again means a new property block has started. This
    # works regardless of which field a given county happens to lead with.
    anchor_field = HEADER_MAP[matches[0].group(1).lower()]

    records: list[dict] = []
    current: dict | None = None
    for i, m in enumerate(matches):
        field = HEADER_MAP[m.group(1).lower()]
        value_end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        value = re.sub(r"\s+", " ", full_text[m.end():value_end]).strip(" .,;:-")
        if not value or looks_empty(value):
            continue
        if field == anchor_field or current is None:
            _keep_label_record(current, records, rejected)
            current = {"county": county, "source": "laft", "url_auction": source_url}
        current[field] = value
        if field == "bid":
            current["bid_kind"] = amount_kind_for_header(m.group(1).lower())
    _keep_label_record(current, records, rejected)
    return records


def _keep_label_record(current: dict | None, records: list[dict], rejected: list | None) -> None:
    if not current or not (current.get("case_no") or current.get("parcel")):
        return
    if current.get("sold_to"):
        record_sold_identity(current)
        return
    # Same identifier gate as _rows_from_table: a "Parcel ID" label whose
    # value ran on to the end of the page (Pasco, 2026-09) is not a parcel.
    if not record_identifiers_plausible(current):
        if rejected is not None:
            rejected.append(1)
        return
    records.append(finalize_record(current))


def extract_rows(pdf_bytes: bytes, county: str, source_url: str) -> list[dict]:
    return extract_rows_with_outcome(pdf_bytes, county, source_url)[0]


def extract_rows_with_outcome(pdf_bytes: bytes, county: str, source_url: str) -> tuple[list[dict], dict]:
    """(rows, outcome). `outcome` says what the parser actually SAW, so a
    zero-row result can be classified honestly instead of reported as an
    empty list:

        empty_marker  - the document itself says nothing is listed (EMPTY)
        table_seen    - pdfplumber found at least one table-like grid
        rows          - number of usable property rows extracted

    Zero rows with no empty marker (Brevard's procedural-text LOLA.pdf, or
    any layout neither table strategy nor the label scanner recognises) is
    an INCOMPLETE observation - the list may well be empty, but this parser
    did not confirm it."""
    outcome = {"empty_marker": False, "table_seen": False, "rows": 0, "rejected": 0, "list_as_of": None}
    rejected: list = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        full_text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        # The list's own as-of date, when the document states one (see
        # laft_status.extract_list_as_of); the filename fallback is applied
        # by main(), which knows the URL.
        outcome["list_as_of"] = extract_list_as_of(full_text)
        if looks_empty(full_text):
            outcome["empty_marker"] = True
            return [], outcome

        rows: list[dict] = []
        text_strategy_settings = {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "snap_tolerance": 3,
            "join_tolerance": 3,
        }
        for page in pdf.pages:
            page_tables = page.extract_tables()
            # Always also try the text-alignment strategy, even when the
            # default (line-based) detector found something - a table can be
            # "found" with the wrong column boundaries (e.g. a merged
            # header/data cell) and silently yield zero valid rows, which
            # looks identical to "no table at all" unless both strategies
            # get a chance. Whichever strategy produces usable rows wins;
            # if both do, results are deduped by (case_no, parcel) below.
            if not page_tables:
                page_tables = page.extract_tables(table_settings=text_strategy_settings)
                strategy_used = ["text"] * len(page_tables)
            else:
                strategy_used = ["lines"] * len(page_tables)
                extra = page.extract_tables(table_settings=text_strategy_settings)
                page_tables = page_tables + extra
                strategy_used = strategy_used + ["text"] * len(extra)

            for table, strat in zip(page_tables, strategy_used):
                if table:
                    outcome["table_seen"] = True
                found = _rows_from_table(table, county, source_url, rejected)
                if not found and table:
                    # Diagnostic only, never fatal - lets a CI run reveal
                    # exactly why a real, non-empty PDF still produced 0
                    # rows (e.g. Hendry: visually a real bordered table, but
                    # worth confirming pdfplumber sees the same header row)
                    # instead of guessing blind from outside the sandbox.
                    header_preview = table[0][:8] if table else []
                    print(f"      [debug] {strat} strategy found a "
                          f"{len(table)}-row table but 0 usable rows - "
                          f"header: {header_preview}", flush=True)
                rows.extend(found)

        if not rows:
            # Neither table strategy found anything grid-like at all (e.g. a
            # "Sale #: ... Sale Date: ... Parcel #: ..." label block per
            # property, with no column alignment to detect as a table
            # either). Fall back to scanning the raw text for known field
            # labels.
            rows = extract_label_value_rows(full_text, county, source_url, rejected)
            if not rows:
                snippet = re.sub(r"\s+", " ", full_text).strip()[:300]
                print(f"      [debug] no table detected by either strategy "
                      f"and no labels matched - text starts: {snippet!r}",
                      flush=True)

        # Dedupe in case both strategies independently found the same row.
        seen = set()
        deduped = []
        for r in rows:
            key = (r.get("case_no"), r.get("parcel"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)
        rows = deduped
    outcome["rows"] = len(rows)
    outcome["rejected"] = len(rejected)
    return rows, outcome


def _fetch_with_successor(url: str, source_page: str | None, entry: dict | None):
    """conditional_get(), plus the Municode successor-link discovery on a
    404 (see discover_successor_pdf). Returns (status, content, validators,
    url_used, discovered_from)."""
    try:
        status, content, validators = conditional_get(requests, url, entry, headers={"User-Agent": UA}, timeout=30)
        return status, content, validators, url, None
    except requests.exceptions.HTTPError as exc:
        code = getattr(getattr(exc, "response", None), "status_code", None)
        if code != 404 or not source_page:
            raise
        print("      registered PDF link returned 404 - looking for the current link on the clerk's source page", flush=True)
        page = requests.get(source_page, headers={"User-Agent": UA}, timeout=30)
        page.raise_for_status()
        successor = discover_successor_pdf(page.text, url)
        if not successor:
            raise
        print(f"      trying discovered successor: {successor}", flush=True)
        status, content, validators = conditional_get(requests, successor, None, headers={"User-Agent": UA}, timeout=30)
        return status, content, validators, successor, source_page


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(SOURCES_CSV, newline="", encoding="utf-8") as f:
        sources = list(csv.DictReader(f))

    recorder = StatusRecorder("fl_laft_pdfs", source_class="GOVERNMENT_DIRECT", parser_version=str(PARSER_VERSION))

    # Change detection - see scripts/harvest_cache.py for the full rationale.
    # A county whose PDF is byte-identical to the one we already parsed costs
    # nothing beyond (at most) the download, instead of a full pdfplumber
    # parse. Any cache problem falls straight through to the original
    # fetch-and-parse path, so the worst case is simply the old behaviour.
    cache = load_cache("laft_pdf")
    new_cache: dict = {}
    reused = 0

    all_rows: list[dict] = []
    SOLD_ROWS.clear()
    for i, src in enumerate(sources, 1):
        county, url = src["County"], src["Url"]
        source_page = (src.get("SourcePage") or "").strip() or None
        print(f"[{i}/{len(sources)}] {county}", flush=True)
        entry = cache.get(url)
        status_kw = dict(source_url=source_page or url, document_url=url, source_class=source_class_for_url(url))
        try:
            status, content, validators, url_used, _discovered = _fetch_with_successor(url, source_page, entry)
            status_kw["document_url"] = url_used
            doc_kw = dict(document_sha256=validators.get("sha256"), document_etag=validators.get("etag"),
                          document_last_modified=validators.get("last_modified"))

            if status in ("not_modified", "unchanged") and entry and "rows" in entry:
                rows = entry["rows"]
                reused += 1
                why = "server says unchanged" if status == "not_modified" else "identical content"
                print(f"      unchanged ({why}) - reusing {len(rows)} cached rows, parse skipped", flush=True)
                doc_kw["list_as_of"] = entry.get("list_as_of") or extract_list_as_of(None, url_used)
                recorder.complete(county, len(rows), from_cache=True, **status_kw, **doc_kw)
            else:
                if content is None:
                    # 304 but we have no cached rows to reuse (cache was
                    # cleared, or this entry predates row caching). Refetch
                    # unconditionally rather than reporting zero rows.
                    resp = requests.get(url_used, headers={"User-Agent": UA}, timeout=30)
                    resp.raise_for_status()
                    content = resp.content
                rows, outcome = extract_rows_with_outcome(content, county, url_used)
                doc_kw["list_as_of"] = outcome.get("list_as_of") or extract_list_as_of(None, url_used)
                if outcome.get("rejected"):
                    print(f"      {outcome['rejected']} row(s) rejected by the identifier gate (not a parcel/case number)", flush=True)
                if rows:
                    print(f"      {len(rows)} properties", flush=True)
                    recorder.complete(county, len(rows), **status_kw, **doc_kw)
                elif outcome["empty_marker"]:
                    print("      no properties currently listed (document says so)", flush=True)
                    recorder.empty(county, "empty_marker", **status_kw, **doc_kw)
                elif outcome.get("rejected"):
                    # Every candidate row failed the identifier gate: the
                    # parser found something but none of it was a property.
                    # A layout change, not an empty list - never close-out.
                    print("      0 usable rows - INCOMPLETE (every parsed row failed the identifier gate)", flush=True)
                    recorder.incomplete(county, "PARSE_FORMAT_CHANGE",
                                        "every parsed row failed the identifier plausibility gate",
                                        **status_kw, **doc_kw)
                else:
                    # Zero rows but the document never said it was empty:
                    # Brevard's procedural-only PDF, or a layout this parser
                    # does not recognise. Not an authoritative empty list.
                    print("      0 rows and no empty marker - INCOMPLETE (unconfirmed empty, parser saw "
                          f"{'a table' if outcome['table_seen'] else 'no table'})", flush=True)
                    recorder.incomplete(county, "PARSE_NO_TABLE" if not outcome["table_seen"] else "UNCONFIRMED_EMPTY",
                                        "no recognisable data table and no empty-list marker in the PDF",
                                        **status_kw, **doc_kw)

            all_rows.extend(rows)
            # Only cache rows we actually believe in. Caching a zero-row parse
            # would let one bad parse suppress a county until the PDF changed.
            if rows:
                validators["rows"] = rows
                validators["list_as_of"] = doc_kw.get("list_as_of")
                new_cache[url_used] = validators
        except Exception as exc:  # noqa: BLE001 - one bad county must not kill the whole run
            category, detail = describe_exception(exc)
            print(f"      ERROR ({category}): {exc}", flush=True)
            recorder.failed(county, exc, **status_kw)
            # Keep the previous good entry so a transient failure doesn't also
            # throw away a usable cache for the next run.
            if entry:
                new_cache[url] = entry

    save_cache("laft_pdf", new_cache)
    recorder.write()
    print(recorder.summary_line(), flush=True)
    record_cache_stats("laft_pdf", reused, len(sources))
    if reused:
        print(f"\n{reused} of {len(sources)} sources were unchanged - parse skipped for those.", flush=True)

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, indent=2)
    with open(OUT_SOLD_JSON, "w", encoding="utf-8") as f:
        json.dump(SOLD_ROWS, f, indent=2)
    if SOLD_ROWS:
        print(f"{len(SOLD_ROWS)} row(s) the lists themselves mark sold - identities written to {OUT_SOLD_JSON.name} (not inventory)")

    if all_rows:
        fieldnames = sorted({k for row in all_rows for k in row.keys()})
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_rows)
    else:
        OUT_CSV.write_text("", encoding="utf-8")

    print("")
    print("=" * 50)
    print(f"Harvested {len(all_rows)} LAFT properties total")
    print(f"Counties with matches: {len({r['county'] for r in all_rows})} of {len(sources)} checked")
    print("=" * 50)
    print(f"Saved: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
