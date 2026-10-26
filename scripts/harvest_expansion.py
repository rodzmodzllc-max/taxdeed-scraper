#!/usr/bin/env python3
"""Harvest one six-state-expansion state's live-verified sources (MI, WY,
SC, CO, WI - harvesters/otc/adapters/expansion.py) through the shared
adapters (arcgis.py / tabular.py). Six-state sprint, 2026-10-01.

    python3 scripts/harvest_expansion.py --state MI                        # live
    python3 scripts/harvest_expansion.py --state MI --fixture mi_eaton_treasurer_sale=<page.json>

Refuses before any request unless the state is ACTIVATED and every source
is a PRODUCTION_VERIFIED, governance-runnable registry row with verified
columns. Per county it records COMPLETE / EMPTY (the source's own empty
statement or an empty layer) / FAILED (transport, error payload, unknown
shape - nothing read is trusted) in out/harvest_<st>_status.json, and
writes out/<st>_properties_rows.json for scripts/sync_state_inventory.py.
A county served by two sources (WI: current + previous sales) is FAILED if
either failed, else COMPLETE if any rows were read, else EMPTY.

Public log discipline: counts, statuses, URLs and identifier SHAPES (every
digit -> 9, every letter -> A) - never a row value.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(REPO))
from laft_status import ERROR_CATEGORIES, StatusRecorder  # noqa: E402
from harvesters.governance import states  # noqa: E402
from harvesters.governance.county_source_registry import RUNNABLE_GOVERNANCE, load_registry  # noqa: E402
from harvesters.otc.adapters import arcgis as AG, expansion as EX  # noqa: E402
from harvesters.otc.adapters.tabular import TabularListAdapter  # noqa: E402

OUT = REPO / "out"
REGISTRY = REPO / "data" / "county_source_registry.csv"
EXPANSION_EVIDENCE = REPO / "data" / "purchase_path_evidence_expansion.csv"
USER_AGENT = "taxdeed-scraper/1.0 (+https://github.com/rodzmodzllc-max/taxdeed-scraper; GitHub Actions)"
# County web pages: the same browser headers the Florida HTML harvester and the
# evidence capture use (a county WAF can refuse a bot User-Agent outright - the
# Morgan CO page did on 2026-09-30 while the capture's browser headers read it).
PAGE_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
PARSER_VERSION = "1"
CATEGORY_MAP = {"TRANSPORT": "TRANSPORT_CONNECTION", "SOURCE_ERROR": "PARSE_FORMAT_CHANGE"}


def shape(v: str) -> str:
    return re.sub(r"[A-Za-z]", "A", re.sub(r"\d", "9", (v or "").strip()))


def dedupe(records):
    """-> (records with one entry per (county, record_source, case_no), dropped count)."""
    seen, out = set(), []
    for r in records:
        key = (r.county, r.record_source, r.case_no)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out, len(records) - len(out)


def attach_purchase_paths(state: str, rows: list[dict], *, harvest_date: str, registry_path: Path = REGISTRY,
                          evidence=None) -> tuple[list[dict], int]:
    """The shared acquisition engine (scripts/purchase_path_engine.py) on
    this state's rows: a path only from a verified evidence row or the
    registry, and only on a row the source still lists as active - a
    completed / closed sale has no acquisition path. -> (rows, rows given a path)."""
    import purchase_path_engine as PPE  # noqa: PLC0415
    reg = {r.source_id: r for r in load_registry(registry_path) if r.state == state}
    # The six-state evidence lives in its own table (data/purchase_path_evidence_expansion.csv):
    # same columns, same verification rules, never mixed into the Florida AVAILABLE table.
    evidence = PPE.load_evidence(EXPANSION_EVIDENCE) if evidence is None else evidence
    n = 0
    # Every row states its path explicitly - a verified one or NULL - so a listing
    # that has closed (or whose evidence was withdrawn) sheds a path it once had,
    # and the URL / path-type pairing constraints always see a consistent row.
    blank = {"purchase_path_type": None, "purchase_path_scope": None, "purchase_path_evidence": None,
             "purchase_path_observed_on": None}
    for row in rows:
        row.update(blank)
        if row.get("status") != "active":
            continue
        path, _ = PPE.resolve(row, state=state, source_id=row["source_id"], county=row["county"],
                              registry_row=reg.get(row["source_id"]), evidence=evidence,
                              list_url=row.get("list_url"), document_url=row.get("document_url"), harvest_date=harvest_date)
        if path is None:
            continue
        row.update(path.columns())
        row["otc_provenance"] = {**(row.get("otc_provenance") or {}), **path.provenance()}
        n += 1
    return rows, n


def gate(state: str, registry_path: Path = REGISTRY, reg: dict | None = None) -> list[str]:
    """Why this state's sources may not run (empty = allowed). A source
    that is registered, live-verified and governance-runnable but whose
    PUBLICATION decision is not APPROVED* is not a problem here - it is
    simply not run (runnable_sources()); a source with no registry row, no
    production verification or unverified columns is a configuration error."""
    problems = []
    if not states.is_activated(state):
        problems.append(f"state {state} is not activated: {', '.join(states.activation_blockers(state))}")
    reg = reg if reg is not None else {r.source_id: r for r in load_registry(registry_path) if r.state == state}
    for src in EX.SOURCES.get(state, ()):
        cfg = src.config
        row = reg.get(cfg.source_id)
        if row is None or not row.is_production or row.governance_status not in RUNNABLE_GOVERNANCE:
            problems.append(f"{cfg.source_id}: not a production, governance-runnable registry row")
        if not cfg.columns_verified:
            problems.append(f"{cfg.source_id}: columns not verified against the live source")
    if not EX.SOURCES.get(state):
        problems.append(f"no expansion sources configured for {state}")
    return problems


def runnable_sources(state: str, reg: dict) -> tuple[list, list[tuple[str, str]]]:
    """(sources to request, [(source_id, publication decision)] not requested).

    Collection is decided by source_publication.collectable(), not by the
    customer publication decision: an APPROVED* source is requested, and so is
    an AVAILABLE (laft) source awaiting review (UNREVIEWED / RESTRICTED) - its
    rows are synced with that publication_status and shown to admins / customer
    preview, never as approved. A BLOCKED source, and an auction / lien source
    that is not publishable, makes zero requests (auction and certificate logic
    unchanged). Since 2026-10-12 a source must also hold a recorded `fetch`
    permission (data/source_permissions.csv); without one it is reported as
    PERMISSION_<reason> and makes zero requests."""
    import source_publication as SP  # noqa: PLC0415
    run, gated = [], []
    for src in EX.SOURCES.get(state, ()):
        row = reg.get(src.config.source_id)
        if SP.collectable(row, src.config.record_source):
            run.append(src)
        elif (src.config.source_id, SP.decision(row, src.config.record_source)) not in gated:
            gated.append((src.config.source_id, SP.decision(row, src.config.record_source)))
    return run, gated


XLSX_MAGIC = b"PK"          # an XLSX workbook is a zip archive
PDF_MAGIC = b"%PDF-"


def document_rows(data: bytes, cfg) -> tuple[list[list[str]], str]:
    """(table rows, format) of a downloaded list file, by its own magic
    bytes - never by its URL or name: an XLSX workbook (only the config's
    `document_sheet`) or a text PDF. Anything else raises ValueError."""
    from harvesters.otc.adapters.tabular import pdf_table_rows, workbook_sheet_rows  # noqa: PLC0415
    if data[:2] == XLSX_MAGIC:
        return workbook_sheet_rows(data, cfg.document_sheet), "XLSX"
    if data[:5] == PDF_MAGIC:
        return pdf_table_rows(data), "PDF"
    raise ValueError("neither an XLSX workbook nor a PDF")


def run_latest_dated_document(src, fetch_text, fetch_bytes, *, retrieved_at, fixture: str | None = None):
    """A list page that links one dated file per update (Fayette PA's
    'Repository Update M-D-YYYY'): read the page, follow the link whose file
    name carries the NEWEST date (config list_as_of_pattern), read that file
    (XLSX sheet or PDF) - list_as_of = that name's date. Offline (`fixture`)
    the fixture IS the document and its file name is the dated name.

    FAILED, never EMPTY: a transport error (TRANSPORT_CONNECTION), a page with
    no dated link (PARSE_NO_TABLE), a file that is neither XLSX nor PDF, lacks
    the configured sheet, or yields no identifier row (PARSE_FORMAT_CHANGE).
    EMPTY only when every row read is a well-formed identifier carrying the
    source's own not-offered status (no malformed identifier at all). -> (status, records, category, detail, empty_signal)."""
    import dataclasses  # noqa: PLC0415
    cfg = src.config
    doc_url = None
    try:
        if fixture:
            data, name = Path(fixture).read_bytes(), Path(fixture).name
        else:
            from harvesters.otc.adapters.tabular import latest_dated_link  # noqa: PLC0415
            picked = latest_dated_link(fetch_text(src.url), src.url, cfg)
            if picked is None:
                return "FAILED", [], "PARSE_NO_TABLE", "no dated document linked on the list page", None
            doc_url = picked[0]
            data = fetch_bytes(doc_url)          # requests follows redirects
            name = doc_url.rstrip("/").rsplit("/", 1)[-1]
    except Exception as exc:  # noqa: BLE001 - transport failure is FAILED, never zero
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return "FAILED", [], "TRANSPORT_CONNECTION", f"{type(exc).__name__}" + (f" HTTP {status}" if status else ""), None
    run_cfg = dataclasses.replace(cfg, document_url=doc_url) if doc_url else cfg
    adapter = TabularListAdapter(run_cfg)
    try:
        rows, fmt = document_rows(data, cfg)
        recs = adapter.parse_rows(rows, retrieved_at=retrieved_at, document_name=name)
    except Exception as exc:  # noqa: BLE001 - an unreadable file is a format change, never "empty"
        return "FAILED", [], "PARSE_FORMAT_CHANGE", type(exc).__name__, None
    for r in recs:
        r.provenance["document"] = f"the list page's newest dated file ({fmt}" + (f", sheet {cfg.document_sheet!r})" if fmt == "XLSX" else ")")
    # Counts and the public file name only - never a row value.
    print(f"{cfg.source_id}: file={name} format={fmt} offered={len(recs)} excluded={adapter.excluded_status} "
          f"bad-id={adapter.rejected_ids}")
    if recs:
        return "COMPLETE", recs, None, None, None
    if adapter.excluded_status and not adapter.rejected_ids:
        # Every row a well-formed identifier carrying a not-offered status: the source's own statement.
        return "EMPTY", [], None, None, "no_offered_status"
    return "FAILED", [], "PARSE_FORMAT_CHANGE", f"no offered identifier row in {name} ({fmt})", None

def link_property_pages(cfg, recs, fetch_text, *, offline: bool) -> int:
    """The source's own per-property page on each record (tabular.attach_property_pages).
    When the config names the source's listed-on-page file, it is read first; a
    failed read links nothing and drops nothing (the rows keep their listing page
    as the acquisition path). Offline (fixture) runs make no request. Counts only."""
    from harvesters.otc.adapters.tabular import attach_property_pages, listed_ids  # noqa: PLC0415
    if getattr(cfg, "property_page", None) is None or not recs:
        return 0
    listed = None
    if cfg.property_page_listed_url:
        if offline or fetch_text is None:
            print(f"{cfg.source_id}: per-property pages not linked (offline run; the listed-on-page file is not read)")
            return 0
        try:
            listed = listed_ids(fetch_text(cfg.property_page_listed_url), cfg.property_page_listed_column)
        except Exception as exc:  # noqa: BLE001 - never fatal: the rows stay, unlinked
            print(f"{cfg.source_id}: per-property pages not linked ({type(exc).__name__} reading the listed-on-page file)")
            return 0
    n = attach_property_pages(recs, cfg, listed)
    print(f"{cfg.source_id}: per-property page linked on {n} of {len(recs)} row(s)"
          + (f" (listed-on-page file: {len(listed)} identifier(s))" if listed is not None else ""))
    return n


def run_source(src, fetch_json, fetch_text, *, retrieved_at, fixture: str | None = None, fetch_bytes=None):
    """-> (status, records, category, detail, empty_signal)."""
    cfg = src.config
    if getattr(cfg, "superseded", None) and not fixture:
        # The county's own pages say this list's sale is over and name the
        # next one (Albany WY: the 2026 sale; owner decision 2026-10-26 to
        # close its rows). No request is made; the read is EMPTY with its own
        # signal, so the sync's close-out closes the stored rows - closed, never
        # sold (no result is published).
        return "EMPTY", [], None, None, "superseded_list"
    if src.kind == "arcgis":
        if fixture:
            payload = json.loads(Path(fixture).read_text(encoding="utf-8"))
            fj = lambda url: payload  # noqa: E731 - one page fixture
            if getattr(cfg, "keyset", False):
                import dataclasses  # noqa: PLC0415 - a one-page fixture has no object-id batches to walk
                cfg = dataclasses.replace(cfg, keyset=False)
        else:
            fj = fetch_json
        res = AG.fetch_all(cfg, fj, retrieved_at=retrieved_at)
        if res.outcome == "FAILED":
            return "FAILED", [], CATEGORY_MAP.get(res.error_category, res.error_category), res.error_detail, None
        if res.duplicates_collapsed:
            print(f"  {cfg.source_id}: {res.duplicates_collapsed} identical repeat listing(s) on one page collapsed (count only)")
        if res.outcome == "EMPTY" and res.skipped_cycle:
            # Every row belongs to a sale cycle the county has published no date
            # for (e.g. last year's list): no current inventory - its own signal.
            return "EMPTY", [], None, None, "past_cycle"
        return res.outcome, res.records, None, None, ("empty_layer" if res.outcome == "EMPTY" else None)
    if src.kind == "epropertyplus":
        # Tennessee (2026-10-08): a land bank's ePropertyPlus portal, paged.
        from harvesters.otc.adapters import epropertyplus as EPP  # noqa: PLC0415
        if fixture:
            pages = json.loads(Path(fixture).read_text(encoding="utf-8"))
            pages = pages if isinstance(pages, list) else [pages]
            fj = lambda url: pages[min(int(re.search(r"page=(\d+)", url).group(1)), len(pages)) - 1]  # noqa: E731
        else:
            fj = fetch_json
        res = EPP.fetch_all(cfg, fj, retrieved_at=retrieved_at)
        if res.outcome == "FAILED":
            return "FAILED", [], res.error_category, res.error_detail, None
        print(f"{cfg.source_id}: portal size={res.size} read={res.rows_read} offered={len(res.records)} "
              f"not-offered={res.excluded_status} bad-id={res.rejected_ids} duplicate={res.duplicates}")
        if res.outcome == "INCOMPLETE":
            return "INCOMPLETE", res.records, res.error_category, res.error_detail, None
        return res.outcome, res.records, None, None, ("no_offered_status" if res.outcome == "EMPTY" else None)
    if src.kind == "tax_sale_info":
        # New-sources sprint (2026-10-26): Tax-Sale.info catalogs (Michigan).
        from harvesters.otc.adapters import tax_sale_info as TSI  # noqa: PLC0415
        if fixture:
            pages = json.loads(Path(fixture).read_text(encoding="utf-8"))   # {url: text}

            def ft(url):
                return pages[url]
        else:
            ft = fetch_text
        res = TSI.fetch_county(cfg, ft, retrieved_at=retrieved_at)
        if res.outcome == "FAILED":
            return "FAILED", [], res.error_category, res.error_detail, None
        if res.catalogs:
            print(f"{cfg.source_id} [{cfg.county}]: catalogs={res.catalogs} read={res.rows_read} kept={len(res.records)} "
                  f"no-parcel={res.rejected}")
        return res.outcome, res.records, None, None, ("no_catalog_listed" if res.outcome == "EMPTY" else None)
    if src.kind == "sc_flc_pdf":
        from harvesters.otc.adapters import sc_flc  # noqa: PLC0415
        try:
            data = Path(fixture).read_bytes() if fixture else fetch_bytes(src.url)
        except Exception as exc:  # noqa: BLE001
            status = getattr(getattr(exc, "response", None), "status_code", None)
            return "FAILED", [], "TRANSPORT_CONNECTION", f"{type(exc).__name__}" + (f" HTTP {status}" if status else ""), None
        res = sc_flc.parse_document(cfg.source_id, data, retrieved_at=retrieved_at)
        outcome = sc_flc.outcome(res)
        if outcome == "FAILED":
            return "FAILED", [], "PARSE_FORMAT_CHANGE", res.error or f"rejected={dict(res.rejected)}", None
        return outcome, res.records, None, None, ("no_qualifying_row" if outcome == "EMPTY" else None)
    if src.kind == "xlsx_flc_lists":
        from harvesters.otc.adapters import sc_flc  # noqa: PLC0415
        try:
            html = fetch_text(src.url)
            links = sc_flc.year_list_links(html, src.url)
            current = [(y, u) for y, u in links if sc_flc.list_year_past_redemption(y, retrieved_at.date())]
            recs, rejected = [], 0
            for year, url in current:
                adapter = TabularListAdapter(cfg)
                for r in adapter._records(sc_flc.xlsx_rows(fetch_bytes(url)), retrieved_at=retrieved_at, document_name=None):
                    r.provenance["tax_sale_year"] = f"the '{year} FLC List' workbook (past the redemption period)"
                    r.provenance["document"] = url
                    recs.append(r)
                rejected += adapter.rejected_ids
        except Exception as exc:  # noqa: BLE001
            status = getattr(getattr(exc, "response", None), "status_code", None)
            return "FAILED", [], "TRANSPORT_CONNECTION", f"{type(exc).__name__}" + (f" HTTP {status}" if status else ""), None
        if not links:
            return "FAILED", [], "PARSE_NO_TABLE", "no '<YEAR> FLC List' workbook linked", None
        if rejected:
            print(f"{cfg.source_id}: {rejected} non-identifier row(s) skipped (note lines / section words)")
        if current and not recs:
            # Lists past redemption exist but no row carried an identifier: a format change, never "empty".
            return "FAILED", [], "PARSE_FORMAT_CHANGE", f"no identifier row in {len(current)} list(s)", None
        return ("COMPLETE", recs, None, None, None) if recs else ("EMPTY", [], None, None, "no_list_past_redemption")
    if src.kind == "latest_dated_document":
        return run_latest_dated_document(src, fetch_text, fetch_bytes, retrieved_at=retrieved_at, fixture=fixture)
    if src.kind in ("csv", "pdf_table"):
        # AVAILABLE expansion (2026-10-04): a published CSV file (St. Louis LRA)
        # or a text PDF's tables (Fayette PA repository list).
        try:
            if src.kind == "csv":
                text = Path(fixture).read_text(encoding="utf-8-sig") if fixture else fetch_text(src.url)
            else:
                data = Path(fixture).read_bytes() if fixture else fetch_bytes(src.url)
        except Exception as exc:  # noqa: BLE001 - transport failure is FAILED, never zero
            status = getattr(getattr(exc, "response", None), "status_code", None)
            return "FAILED", [], "TRANSPORT_CONNECTION", f"{type(exc).__name__}" + (f" HTTP {status}" if status else ""), None
        adapter = TabularListAdapter(cfg)
        name = src.url.rsplit("/", 1)[-1]
        try:
            if src.kind == "csv":
                recs = adapter.parse_csv(text.lstrip("\ufeff"), retrieved_at=retrieved_at, document_name=name)
            else:
                from harvesters.otc.adapters.tabular import pdf_table_rows  # noqa: PLC0415
                recs = adapter.parse_rows(pdf_table_rows(data), retrieved_at=retrieved_at, document_name=name)
        except Exception as exc:  # noqa: BLE001 - an unreadable file is a format change, never "empty"
            return "FAILED", [], "PARSE_FORMAT_CHANGE", type(exc).__name__, None
        if adapter.rejected_ids or adapter.excluded_status:
            print(f"{cfg.source_id}: {adapter.rejected_ids} non-identifier row(s), "
                  f"{adapter.excluded_status} row(s) whose own status is not an offer - skipped")
        link_property_pages(cfg, recs, fetch_text, offline=bool(fixture))
        if recs:
            return "COMPLETE", recs, None, None, None
        if adapter.excluded_status and not adapter.rejected_ids:
            # Every row read, none carrying the source's own offered status: the source's statement.
            return "EMPTY", [], None, None, "no_offered_status"
        return "FAILED", [], "PARSE_NO_TABLE", "no row carrying the configured columns", None
    # html_table
    try:
        html = Path(fixture).read_text(encoding="utf-8") if fixture else fetch_text(src.url)
    except Exception as exc:  # noqa: BLE001 - transport failure is FAILED, never zero
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return "FAILED", [], "TRANSPORT_CONNECTION", f"{type(exc).__name__}" + (f" HTTP {status}" if status else ""), None
    adapter = TabularListAdapter(cfg)
    recs = adapter.parse_html_table(html, retrieved_at=retrieved_at)
    link_property_pages(cfg, recs, fetch_text, offline=bool(fixture))
    if adapter.rejected_ids or adapter.excluded_status:
        print(f"{cfg.source_id}: {adapter.rejected_ids} non-identifier row(s), "
              f"{adapter.excluded_status} row(s) whose own status is not an offer - skipped")
    if recs:
        return "COMPLETE", recs, None, None, None
    if adapter.empty_statement:
        return "EMPTY", [], None, None, "empty_marker"
    return "FAILED", [], "PARSE_NO_TABLE", "no table carrying the configured columns", None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", required=True)
    ap.add_argument("--fixture", action="append", default=[], help="SOURCE_ID=path (offline; no request)")
    ap.add_argument("--out-dir", default=str(OUT))
    a = ap.parse_args(argv)
    st = a.state.upper()
    fixtures = dict(f.split("=", 1) for f in a.fixture)
    import source_publication as SP  # noqa: PLC0415
    reg, review_report = SP.registry_with_reviews(st) if not fixtures else SP.registry_with_reviews(st, reviews={})
    problems = gate(st, reg=reg)
    if problems and not fixtures:
        for p in problems:
            print(f"::error title=harvest_{st.lower()}::{p} - 0 requests made")
        return 2
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0)
    fetch_json = fetch_text = fetch_bytes = None
    if not fixtures:
        import requests  # noqa: PLC0415 - only after the gate passed
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT

        def fetch_json(url):
            r = session.get(url, timeout=60)
            r.raise_for_status()
            return r.json()

        def fetch_text(url):
            r = session.get(url, timeout=60, headers=PAGE_HEADERS)
            r.raise_for_status()
            return r.text

        def fetch_bytes(url):
            r = session.get(url, timeout=60, headers=PAGE_HEADERS)
            r.raise_for_status()
            return r.content
    sources, gated = runnable_sources(st, reg)
    if fixtures:
        # Offline (tests): every configured source with a fixture is parsed;
        # nothing is synced from a fixture run.
        sources = [s for s in EX.SOURCES.get(st, ()) if s.config.source_id in fixtures]
        gated = [g for g in gated if g[0] not in fixtures]
    for sid, why in gated:
        print(f"{st} {sid} GATED publication={why} - 0 requests (an APPROVED review in the admin panel enables it)")
    per_county = defaultdict(list)
    records = []
    for src in sources:
        cfg = src.config
        try:
            status, recs, cat, detail, empty = run_source(src, fetch_json, fetch_text, retrieved_at=retrieved_at,
                                                         fixture=fixtures.get(cfg.source_id), fetch_bytes=fetch_bytes)
        except Exception as exc:  # noqa: BLE001 - one source never stops the others
            status, recs, cat, detail, empty = "FAILED", [], "UNKNOWN", type(exc).__name__, None
        # A record that fails validation is dropped (never written) and its
        # county read is INCOMPLETE - nothing is closed on an untrusted read.
        valid = [r for r in recs if not r.validate()]
        invalid = len(recs) - len(valid)
        if invalid and status == "COMPLETE":
            status = "INCOMPLETE"
        per_county[cfg.county].append((cfg, status, len(valid), cat, detail, empty, src.url))
        records += valid
        shapes = dict(Counter(shape(r.case_no) for r in valid).most_common(4))
        print(f"{st} {cfg.source_id} [{cfg.county}] {status} rows={len(valid)} invalid={invalid} "
              f"publication={SP.decision(reg.get(cfg.source_id))} id_shapes={shapes}"
              + (f" category={cat}" if cat else "") + (f" detail={detail}" if detail else "") + (f" empty={empty}" if empty else ""))
    # One identity per (county, source, case_no) - the upsert's conflict target; a batch
    # carrying it twice is rejected whole by Postgres. The FIRST source listing it wins
    # (SOURCES orders a county's current list before its previous-sales list).
    records, dupes = dedupe(records)
    if dupes:
        print(f"{st}: {dupes} duplicate identifier(s) dropped (first listing kept)")
    recorder = StatusRecorder(f"expansion_{st.lower()}", source_class="GOVERNMENT_DIRECT", source_id=f"expansion_{st.lower()}",
                              parser_version=PARSER_VERSION, path=out / f"harvest_{st.lower()}_status.json", state=st)
    # One status entry per (source, county) - never one merged verdict per
    # county. 2026-10-09: Detroit Land Bank lots read COMPLETE (30,706 rows)
    # while Detroit's programs layer (same county, Wayne) FAILED; the merged
    # county entry said FAILED, so the sync skipped every lot row and 30,758
    # rows kept their 2026-10-06 last read. Each source's own read now
    # decides what of THAT source is written or closed.
    for county, results in per_county.items():
        for cfg, status, rows, cat, detail, empty, url in results:
            sid = cfg.source_id
            if status == "FAILED":
                cat = cat if cat in ERROR_CATEGORIES else "UNKNOWN"
                recorder.failed(county, cat, f"{sid}: {detail or cat}", source_url=url, source_id=sid)
            elif status == "INCOMPLETE":
                recorder.incomplete(county, "PARSE_FORMAT_CHANGE", f"{sid}: {detail or 'record(s) failed validation'}",
                                    row_count=rows, source_url=url, parse_ok=True, source_id=sid)
            elif rows:
                recorder.complete(county, rows, source_url=url, source_id=sid)
            else:
                recorder.empty(county, empty or "empty_layer", source_url=url, source_id=sid)
    recorder.write()
    (out / f"harvest_{st.lower()}.json").write_text(json.dumps([r.to_harvest_row() for r in records], indent=2, sort_keys=True, default=str), encoding="utf-8")
    prows, paths = attach_purchase_paths(st, [r.to_properties_row() for r in records], harvest_date=retrieved_at.date().isoformat())
    (out / f"{st.lower()}_properties_rows.json").write_text(json.dumps(prows, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(f"{st}: verified acquisition path on {paths} of {sum(1 for r in prows if r.get('status') == 'active')} active row(s)")
    review = Counter(SP.decision(reg.get(r.source_id)) for r in records)
    print(f"{st}: {len(records)} record(s) across {len(per_county)} county unit(s); by source publication status: {dict(review)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
