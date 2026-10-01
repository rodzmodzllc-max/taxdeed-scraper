#!/usr/bin/env python3
"""Enrich one activated state's property rows from its statewide parcel /
assessment layer (six-state expansion sprint) - the generic runner around
harvesters/enrichment/parcels.py.

    python3 scripts/enrich_statewide_parcels.py --state NC            # live
    python3 scripts/enrich_statewide_parcels.py --state NC --dry-run  # read + plan, no write

Refuses before any request unless the state is ACTIVATED and the state's
ParcelSourceConfig passes `enrichment_allowed()` (columns verified live,
publication APPROVED). Rows are matched on (county, normalized parcel id)
only; every written column carries a field_provenance entry and goes
through the shared precedence rule. Writes `out/public/enrichment-<st>.json`
- counts with their denominators, never a row value. Public log
discipline: counts only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
from harvesters.enrichment import parcels as P  # noqa: E402
from harvesters.enrichment.sources import for_state  # noqa: E402
from harvesters.governance import states  # noqa: E402
from scripts import field_provenance as FP  # noqa: E402

USER_AGENT = "taxdeed-scraper statewide-parcel-enrichment (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
READ_COLUMNS = ["id", "county", "parcel", "case_no", "field_provenance", "latitude", "longitude", *sorted(P.COLUMN_TYPES)]


def http_json(url: str, *, headers: dict | None = None, method: str = "GET", body: bytes | None = None, timeout: int = 60):
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


def fetch_rows(base: str, key: str, state: str, id_column: str = "parcel") -> list[dict]:
    rows, offset = [], 0
    hdr = {"apikey": key, "Authorization": f"Bearer {key}"}
    while True:
        q = urllib.parse.urlencode({"select": ",".join(READ_COLUMNS), "state": f"eq.{state}", "status": "eq.active",
                                    id_column: "not.is.null", "order": "id", "limit": 1000, "offset": offset})
        page = http_json(f"{base}/rest/v1/properties?{q}", headers=hdr) or []
        rows += page
        if len(page) < 1000:
            return rows
        offset += 1000


def patch(base: str, key: str, row_id: str, fields: dict) -> None:
    hdr = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Prefer": "return=minimal"}
    http_json(f"{base}/rest/v1/properties?id=eq.{row_id}", headers=hdr, method="PATCH", body=json.dumps(fields).encode())


def blank_for(row: dict, column: str) -> bool:
    """Blank for enrichment: empty, or - for address - the placeholder the
    harvest writes when a list publishes no street address ("Parcel <id>" /
    "Case <no>", OtcRecord.to_properties_row). A placeholder is not a value."""
    v = row.get(column)
    if FP.is_blank(v):
        return True
    if column == "address":
        return str(v).strip() in (f"Parcel {row.get('parcel')}", f"Case {row.get('case_no')}")
    return False


def run(state: str, rows: list[dict], fetch_json, *, write=None, recorded_at: str) -> dict:
    """The whole pipeline for one state, I/O injected. Returns the coverage
    report (counts only)."""
    cfg = for_state(state)
    report = {"state": state, "source_id": cfg.source_id if cfg else None}
    if cfg is None:
        return {**report, "skipped": "no statewide parcel source configured"}
    ok, why = P.enrichment_allowed(cfg)
    if not ok:
        return {**report, "skipped": why}
    cov = P.Coverage()
    by_county = defaultdict(list)
    for r in rows:
        by_county[r.get("county") or ""].append(r)
    for county, crow in sorted(by_county.items()):
        features, failed = [], False
        for url in P.query_urls(cfg, county, [r.get(cfg.row_id_column) for r in crow]):
            try:
                data = fetch_json(url)
            except Exception:  # noqa: BLE001 - a failed query attaches nothing
                failed = True
                break
            if not isinstance(data, dict) or "error" in data:
                failed = True
                break
            features += data.get("features") or []
        if failed:
            cov.failed_queries += 1
            cov.rows_considered += len(crow)
            continue
        idx = P.index_features(cfg, features)
        for m, row in zip(P.match_rows(cfg, crow, idx), crow):
            cov.add(m)
            fields, prov = P.plan_update(cfg, row, m, recorded_at=recorded_at)
            fields = FP.filter_by_provenance(row, {k: v for k, v in fields.items() if blank_for(row, k) or k in (row.get("field_provenance") or {})}, "statewide_parcel")
            if not fields:
                continue
            fields["field_provenance"] = FP.merge_field_provenance(row.get("field_provenance"), {k: prov[k] for k in fields})
            if write:
                write(row["id"], fields)
            cov.rows_written += 1
            for k in fields:
                if k != "field_provenance":
                    cov.fields_written[k] = cov.fields_written.get(k, 0) + 1
    return {**report, "dataset": cfg.dataset, "layer_url": cfg.layer_url, **cov.as_dict()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    st = a.state.upper()
    if not states.is_activated(st):
        print(f"skip: state {st} is not activated")
        return 0
    cfg = for_state(st)
    if cfg is None or not P.enrichment_allowed(cfg)[0]:
        print(f"skip: {st} statewide parcel source not cleared ({P.enrichment_allowed(cfg)[1] if cfg else 'none configured'})")
        return 0
    base, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("skip: SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
        return 0
    rows = fetch_rows(base, key, st, cfg.row_id_column)

    def fetch_json(url):
        time.sleep(0.3)
        return http_json(url)

    report = run(st, rows, fetch_json, write=None if a.dry_run else (lambda i, f: patch(base, key, i, f)),
                 recorded_at=FP.now_iso())
    out = Path(a.out or REPO / "out" / "public" / f"enrichment-{st.lower()}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("state", "rows_considered", "matched", "unmatched", "ambiguous", "no_identifier", "failed_queries", "rows_written", "skipped")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
