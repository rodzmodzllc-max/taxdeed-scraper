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
    """(sources to request, [(source_id, publication decision)] gated). Only a
    source whose effective publication (registry + latest valid admin
    review, scripts/source_publication.py) is APPROVED* is requested: an
    UNREVIEWED / RESTRICTED / BLOCKED source makes zero requests - except an
    AVAILABLE source still awaiting review, which held_sources() collects."""
    import source_publication as SP  # noqa: PLC0415
    run, gated = [], []
    for src in EX.SOURCES.get(state, ()):
        row = reg.get(src.config.source_id)
        if SP.publishable(row):
            run.append(src)
        elif (src.config.source_id, SP.decision(row)) not in gated:
            gated.append((src.config.source_id, SP.decision(row)))
    return run, gated


# A held source: an AVAILABLE (laft) source whose publication is UNREVIEWED.
# It is read, normalized and kept with its provenance in out/<st>_held_rows.json
# (private; never synced) with its own status file - REVIEW_REQUIRED collects
# and holds. A RESTRICTED / BLOCKED / unregistered source is never requested,
# and an AUCTION or LIENS source awaiting review is never requested either.
HOLDABLE = frozenset({"UNREVIEWED"})


def held_sources(state: str, reg: dict) -> list:
    import source_publication as SP  # noqa: PLC0415
    out = []
    for src in EX.SOURCES.get(state, ()):
        row = reg.get(src.config.source_id)
        if row is not None and not SP.publishable(row) and SP.decision(row) in HOLDABLE \
                and src.config.record_source == "laft" and src not in out:
            out.append(src)
    return out


def run_source(src, fetch_json, fetch_text, *, retrieved_at, fixture: str | None = None, fetch_bytes=None):
    """-> (status, records, category, detail, empty_signal)."""
    cfg = src.config
    if src.kind == "arcgis":
        if fixture:
            payload = json.loads(Path(fixture).read_text(encoding="utf-8"))
            fj = lambda url: payload  # noqa: E731 - one page fixture
        else:
            fj = fetch_json
        res = AG.fetch_all(cfg, fj, retrieved_at=retrieved_at)
        if res.outcome == "FAILED":
            return "FAILED", [], CATEGORY_MAP.get(res.error_category, res.error_category), res.error_detail, None
        if res.outcome == "EMPTY" and res.skipped_cycle:
            # Every row belongs to a sale cycle the county has published no date
            # for (e.g. last year's list): no current inventory - its own signal.
            return "EMPTY", [], None, None, "past_cycle"
        return res.outcome, res.records, None, None, ("empty_layer" if res.outcome == "EMPTY" else None)
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
            recs = []
            for year, url in current:
                adapter = TabularListAdapter(cfg)
                for r in adapter._records(sc_flc.xlsx_rows(fetch_bytes(url)), retrieved_at=retrieved_at, document_name=None):
                    r.provenance["tax_sale_year"] = f"the '{year} FLC List' workbook (past the redemption period)"
                    r.provenance["document"] = url
                    recs.append(r)
        except Exception as exc:  # noqa: BLE001
            status = getattr(getattr(exc, "response", None), "status_code", None)
            return "FAILED", [], "TRANSPORT_CONNECTION", f"{type(exc).__name__}" + (f" HTTP {status}" if status else ""), None
        if not links:
            return "FAILED", [], "PARSE_NO_TABLE", "no '<YEAR> FLC List' workbook linked", None
        return ("COMPLETE", recs, None, None, None) if recs else ("EMPTY", [], None, None, "no_list_past_redemption")
    # html_table
    try:
        html = Path(fixture).read_text(encoding="utf-8") if fixture else fetch_text(src.url)
    except Exception as exc:  # noqa: BLE001 - transport failure is FAILED, never zero
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return "FAILED", [], "TRANSPORT_CONNECTION", f"{type(exc).__name__}" + (f" HTTP {status}" if status else ""), None
    adapter = TabularListAdapter(cfg)
    recs = adapter.parse_html_table(html, retrieved_at=retrieved_at)
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
    held = [] if fixtures else held_sources(st, reg)
    held_ids = {h.config.source_id for h in held}
    gated = [g for g in gated if g[0] not in held_ids]
    if fixtures:
        # Offline (tests): every configured source with a fixture is parsed;
        # nothing is synced from a fixture run.
        sources = [s for s in EX.SOURCES.get(st, ()) if s.config.source_id in fixtures]
        gated = [g for g in gated if g[0] not in fixtures]
    for sid, why in gated:
        print(f"{st} {sid} GATED publication={why} - 0 requests (an APPROVED review in the admin panel enables it)")
    held_records = run_held(st, held, fetch_json, fetch_text, fetch_bytes, retrieved_at=retrieved_at, out=out)
    per_county = defaultdict(list)
    records = []
    for src in sources:
        cfg = src.config
        status, recs, cat, detail, empty = run_source(src, fetch_json, fetch_text, retrieved_at=retrieved_at,
                                                     fixture=fixtures.get(cfg.source_id), fetch_bytes=fetch_bytes)
        per_county[cfg.county].append((cfg, status, len(recs), cat, detail, empty, src.url))
        records += recs
        shapes = dict(Counter(shape(r.case_no) for r in recs).most_common(4))
        print(f"{st} {cfg.source_id} [{cfg.county}] {status} rows={len(recs)} id_shapes={shapes}"
              + (f" category={cat}" if cat else "") + (f" detail={detail}" if detail else "") + (f" empty={empty}" if empty else ""))
    # One identity per (county, source, case_no) - the upsert's conflict target; a batch
    # carrying it twice is rejected whole by Postgres. The FIRST source listing it wins
    # (SOURCES orders a county's current list before its previous-sales list).
    records, dupes = dedupe(records)
    if dupes:
        print(f"{st}: {dupes} duplicate identifier(s) dropped (first listing kept)")
    recorder = StatusRecorder(f"expansion_{st.lower()}", source_class="GOVERNMENT_DIRECT", source_id=f"expansion_{st.lower()}",
                              parser_version=PARSER_VERSION, path=out / f"harvest_{st.lower()}_status.json", state=st)
    for county, results in per_county.items():
        url = results[0][6]
        failed = [r for r in results if r[1] == "FAILED"]
        rows = sum(r[2] for r in results)
        if failed:
            cat = failed[0][3] if failed[0][3] in ERROR_CATEGORIES else "UNKNOWN"
            recorder.failed(county, cat, f"{failed[0][0].source_id}: {failed[0][4] or cat}", source_url=url)
        elif rows:
            recorder.complete(county, rows, source_url=url)
        else:
            recorder.empty(county, results[0][5] or "empty_layer", source_url=url)
    recorder.write()
    bad = [r for r in records if r.validate()]
    if bad:
        print(f"::error title=harvest_{st.lower()}::{len(bad)} record(s) failed validation - none written")
        return 2
    (out / f"harvest_{st.lower()}.json").write_text(json.dumps([r.to_harvest_row() for r in records], indent=2, sort_keys=True, default=str), encoding="utf-8")
    prows, paths = attach_purchase_paths(st, [r.to_properties_row() for r in records], harvest_date=retrieved_at.date().isoformat())
    (out / f"{st.lower()}_properties_rows.json").write_text(json.dumps(prows, indent=2, sort_keys=True, default=str), encoding="utf-8")
    print(f"{st}: verified acquisition path on {paths} of {sum(1 for r in prows if r.get('status') == 'active')} active row(s)")
    print(f"{st}: {len(records)} record(s) across {len(per_county)} county unit(s); {held_records} held AVAILABLE record(s)")
    return 0


def run_held(st: str, held: list, fetch_json, fetch_text, fetch_bytes, *, retrieved_at, out: Path) -> int:
    """Collect and hold the AVAILABLE sources awaiting a publication review:
    read, normalize, keep provenance and the acquisition path in
    out/<st>_held_rows.json (private, never synced), with their own status
    file out/harvest_<st>_held_status.json for freshness. A failure here never
    affects the publishable sources' harvest or sync. -> held record count."""
    if not held:
        return 0
    recorder = StatusRecorder(f"expansion_{st.lower()}_held", source_class="GOVERNMENT_DIRECT", source_id=f"expansion_{st.lower()}_held",
                              parser_version=PARSER_VERSION, path=out / f"harvest_{st.lower()}_held_status.json", state=st)
    kept = []
    for src in held:
        cfg = src.config
        try:
            status, recs, cat, detail, empty = run_source(src, fetch_json, fetch_text, retrieved_at=retrieved_at, fetch_bytes=fetch_bytes)
        except Exception as exc:  # noqa: BLE001 - one held source never stops the others
            status, recs, cat, detail, empty = "FAILED", [], "UNKNOWN", type(exc).__name__, None
        recs, _ = dedupe(recs)
        valid = [r for r in recs if not r.validate()]
        unit = f"{cfg.county}:{cfg.source_id}"
        if status == "FAILED":
            recorder.failed(unit, cat if cat in ERROR_CATEGORIES else "UNKNOWN", f"{cfg.source_id}: {detail or cat}", source_url=src.url)
        elif valid:
            recorder.complete(unit, len(valid), source_url=src.url)
        else:
            recorder.empty(unit, empty or "empty_layer", source_url=src.url)
        shapes = dict(Counter(shape(r.case_no) for r in valid).most_common(3))
        print(f"{st} {cfg.source_id} [{cfg.county}] HELD publication=UNREVIEWED {status} rows={len(valid)} "
              f"invalid={len(recs) - len(valid)} id_shapes={shapes}" + (f" category={cat}" if cat else ""))
        kept += valid
    recorder.write()
    rows = [r.to_properties_row() for r in kept]
    for row in rows:
        row["publication_status"] = "UNREVIEWED"   # held: the sync never reads this file
    rows, paths = attach_purchase_paths(st, rows, harvest_date=retrieved_at.date().isoformat())
    (out / f"{st.lower()}_held_rows.json").write_text(json.dumps(rows, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return len(rows)


if __name__ == "__main__":
    sys.exit(main())
