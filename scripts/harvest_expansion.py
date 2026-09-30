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
    for row in rows:
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


def gate(state: str, registry_path: Path = REGISTRY) -> list[str]:
    """Why this state's sources may not run (empty = allowed)."""
    problems = []
    if not states.is_activated(state):
        problems.append(f"state {state} is not activated: {', '.join(states.activation_blockers(state))}")
    reg = {r.source_id: r for r in load_registry(registry_path) if r.state == state}
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


def run_source(src, fetch_json, fetch_text, *, retrieved_at, fixture: str | None = None):
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
        return res.outcome, res.records, None, None, ("empty_layer" if res.outcome == "EMPTY" else None)
    # html_table
    try:
        html = Path(fixture).read_text(encoding="utf-8") if fixture else fetch_text(src.url)
    except Exception as exc:  # noqa: BLE001 - transport failure is FAILED, never zero
        return "FAILED", [], "TRANSPORT_CONNECTION", f"{type(exc).__name__}", None
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
    problems = gate(st)
    if problems and not fixtures:
        for p in problems:
            print(f"::error title=harvest_{st.lower()}::{p} - 0 requests made")
        return 2
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0)
    fetch_json = fetch_text = None
    if not fixtures:
        import requests  # noqa: PLC0415 - only after the gate passed
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT

        def fetch_json(url):
            r = session.get(url, timeout=60)
            r.raise_for_status()
            return r.json()

        def fetch_text(url):
            r = session.get(url, timeout=60)
            r.raise_for_status()
            return r.text
    per_county = defaultdict(list)
    records = []
    for src in EX.SOURCES.get(st, ()):
        cfg = src.config
        status, recs, cat, detail, empty = run_source(src, fetch_json, fetch_text, retrieved_at=retrieved_at,
                                                     fixture=fixtures.get(cfg.source_id))
        per_county[cfg.county].append((cfg, status, len(recs), cat, detail, empty, src.url))
        records += recs
        shapes = dict(Counter(shape(r.case_no) for r in recs).most_common(4))
        print(f"{st} {cfg.source_id} [{cfg.county}] {status} rows={len(recs)} id_shapes={shapes}"
              + (f" category={cat}" if cat else "") + (f" empty={empty}" if empty else ""))
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
    print(f"{st}: {len(records)} record(s) across {len(per_county)} county unit(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
