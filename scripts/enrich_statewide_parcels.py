#!/usr/bin/env python3
"""Enrich one activated state's property rows from its statewide parcel /
assessment layer (six-state expansion sprint) - the generic runner around
harvesters/enrichment/parcels.py.

    python3 scripts/enrich_statewide_parcels.py --state NC            # live
    python3 scripts/enrich_statewide_parcels.py --state NC --dry-run  # read + plan, no write

    # 2026-10-27: every cleared layer of the state (county assessor layers
    # first, then the statewide one) over every ACTIVE row of every ledger,
    # at most N rows per layer a run, resuming after the previous run's row:
    python3 scripts/enrich_statewide_parcels.py --state SC,CO --all-layers --limit 500 [--dry-run]

With --all-layers a patch is sent only when it changes the row
(scripts/write_diff.py), a "Parcel <id>" placeholder counts as a missing
address, and the report is out/public/enrichment-<st>-layers.json.

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
from harvesters.enrichment.sources import all_sources, for_state  # noqa: E402
from harvesters.governance import states  # noqa: E402
from scripts import field_provenance as FP  # noqa: E402
from scripts import write_diff as WD  # noqa: E402
from scripts import enrichment_queue as EQ  # noqa: E402

USER_AGENT = "taxdeed-scraper statewide-parcel-enrichment (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
READ_COLUMNS = ["id", "state", "source", "source_id", "harvester_source", "county", "parcel", "case_no", "field_provenance", "latitude", "longitude", *sorted(P.COLUMN_TYPES)]


def http_json(url: str, *, headers: dict | None = None, method: str = "GET", body: bytes | None = None, timeout: int = 60):
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


def fetch_rows(base: str, key: str, state: str, id_column: str | None = None) -> list[dict]:
    """Every ACTIVE row of the state (every ledger), by keyset pages with a
    bounded retry (scripts/rest_pages.py - offset pages crossed the statement
    timeout under load). With `id_column`, only rows carrying it."""
    from scripts import rest_pages as RP  # noqa: PLC0415
    hdr = {"apikey": key, "Authorization": f"Bearer {key}", "User-Agent": USER_AGENT}
    params = {"select": ",".join(READ_COLUMNS), "state": f"eq.{state}", "status": "eq.active"}
    if id_column:
        params[id_column] = "not.is.null"
    return RP.read_all(base, "properties", hdr, params)


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
        return str(v).strip() in (f"Parcel {row.get('parcel')}", f"Case {row.get('case_no')}", f"Account {row.get('case_no')}")
    return False


def _query_failure(exc) -> str:
    """A value-free cause for a failed layer query (never the URL: it carries
    the identifiers)."""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return f"http_{code}"
    if isinstance(exc, (TimeoutError,)) or "timed out" in str(exc).lower():
        return "timeout"
    if isinstance(exc, ValueError):
        return "bad_json"
    return type(exc).__name__


def _fetch_with_retry(fetch_json, url, retries: int, sleep, kinds: dict):
    """fetch_json(url), retried `retries` more times on a transport error or
    an ArcGIS error envelope. Run 382 (2026-10-26): both Colorado county
    queries failed once and the whole state's enrichment read 0 matched /
    2 failed queries, where the run before matched 117 - one transient
    failure must not cost a county its run. Returns (data, ok)."""
    for attempt in range(retries + 1):
        try:
            data = fetch_json(url)
        except Exception as exc:  # noqa: BLE001 - a failed query attaches nothing
            kind = _query_failure(exc)
        else:
            if isinstance(data, dict) and "error" in data:
                err = data.get("error")
                code = err.get("code") if isinstance(err, dict) else None
                kind = f"arcgis_error_{code}" if code else "arcgis_error"
            else:
                return data, True
        kinds[kind] = kinds.get(kind, 0) + 1
        if attempt < retries:
            sleep(2.0 * (attempt + 1))
    return None, False


def download_county_file(url: str, dest_dir: str) -> str:
    """Download one county file (county_file transport) to dest_dir; returns
    the local path. Raises on any HTTP / transport error (a failed read)."""
    path = os.path.join(dest_dir, "county.zip")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as resp, open(path, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    return path


def county_file_fetcher(cfg, county: str, keys: set):
    """fetch_json-shaped callable for one county of a county_file source:
    url -> {"features": [...]} holding only the requested identifiers."""
    import tempfile  # noqa: PLC0415
    from harvesters.enrichment import county_file as CF  # noqa: PLC0415

    def fetch(url):
        with tempfile.TemporaryDirectory() as tmp:
            return {"features": CF.read_county_zip(download_county_file(url, tmp), cfg, county, keys)}
    return fetch


def _point_in_state(state: str, lat, lng) -> bool:
    """True unless the state has known bounds and the point lies outside them."""
    from harvesters.enrichment import geocode as GC  # noqa: PLC0415
    if state not in GC.STATE_BOUNDS or lat is None or lng is None:
        return True
    return GC.in_state(float(lat), float(lng), state)


def _row_blank(row: dict, column: str) -> bool:
    if column in ("latitude", "longitude"):
        return FP.is_blank(row.get("latitude")) and FP.is_blank(row.get("longitude"))
    return blank_for(row, column)


def run(state: str, rows: list[dict], fetch_json, *, write=None, recorded_at: str, cfg=None, outcomes=None,
        retries: int = 0, sleep=time.sleep, county_fetcher=None) -> dict:
    """The whole pipeline for one state, I/O injected. Returns the coverage
    report (counts only). `cfg` names a specific layer (a county-scoped one);
    the default is the state's statewide layer. `outcomes`, when given, is a
    dict filled with row id -> MATCHED / UNMATCHED / AMBIGUOUS / NO_IDENTIFIER
    / SOURCE_UNAVAILABLE (the all-sources engine's per-row outcome)."""
    cfg = cfg or for_state(state)
    report = {"state": state, "source_id": cfg.source_id if cfg else None}
    if cfg is None:
        return {**report, "skipped": "no statewide parcel source configured"}
    ok, why = P.enrichment_allowed(cfg)
    if not ok:
        return {**report, "skipped": why}
    cov = P.Coverage()
    unchanged = 0
    failure_kinds: dict = {}
    by_county = defaultdict(list)
    for r in rows:
        if cfg.takes_row(r):
            by_county[r.get("county") or ""].append(r)
    for county, crow in sorted(by_county.items()):
        if not cfg.covers(county):
            continue
        features, failed = [], False
        fetch = fetch_json
        if cfg.transport == "county_file":
            rule = cfg.id_rule_for(county)
            keys = {P.normalize_id(r.get(cfg.row_id_column), rule) for r in crow} - {None}
            fetch = (county_fetcher or county_file_fetcher)(cfg, county, keys)
        lost: list[dict] = []
        for batch_rows, url in _batches(cfg, county, crow):
            data, ok_ = _fetch_with_retry(fetch, url, retries, sleep, failure_kinds)
            if ok_ and cfg.transport == "socrata":
                # A SODA resource answers with a list of records (or an error object).
                ok_ = isinstance(data, list)
                if ok_:
                    features += [{"attributes": rec} for rec in data if isinstance(rec, dict)]
            elif ok_:
                ok_ = isinstance(data, dict) and "error" not in data
                if ok_:
                    features += data.get("features") or []
            if not ok_:
                # A failed batch attaches nothing to ITS rows only (run 405,
                # 2026-10-27: one Detroit batch of ~314 answered 404 three times
                # and the whole county - 31,348 rows - was given up).
                cov.failed_queries += 1
                lost += batch_rows
                if batch_rows is crow:
                    failed = True
                    break
        if lost:
            cov.rows_considered += len(lost)
            if outcomes is not None:
                outcomes.update({r["id"]: "SOURCE_UNAVAILABLE" for r in lost})
            lost_ids = {id(r) for r in lost}
            crow = [r for r in crow if id(r) not in lost_ids]
        if failed or not crow:
            continue
        idx = P.index_features(cfg, features, county if cfg.county_id else None)
        for m, row in zip(P.match_rows(cfg, crow, idx), crow):
            cov.add(m)
            if outcomes is not None:
                outcomes[row["id"]] = m.status
            fields, prov = P.plan_update(cfg, row, m, recorded_at=recorded_at)
            if cfg.fill_blank_only:
                fields = {k: v for k, v in fields.items() if _row_blank(row, k)}
            if "latitude" in fields and not _point_in_state(state, fields.get("latitude"), fields.get("longitude")):
                fields.pop("latitude", None)    # a centroid outside the row's state is not its location
                fields.pop("longitude", None)
            cand = {k: v for k, v in fields.items() if blank_for(row, k) or k in (row.get("field_provenance") or {})}
            # A placeholder ("Parcel <id>") is no value: the precedence rule
            # sees it as blank, so an address a sync once overwrote with its
            # placeholder (Colorado, 2026-10-26) can be filled again.
            seen = {**row, **{k: None for k in cand if blank_for(row, k)}}
            fields = FP.filter_by_provenance(seen, cand, "statewide_parcel")
            if not fields:
                continue
            fields["field_provenance"] = FP.merge_field_provenance(row.get("field_provenance"), {k: prov[k] for k in fields})
            if WD.unchanged(fields, row):
                # scripts/write_diff.py: a patch that would store what the row
                # already holds (provenance compared without recorded_at) is
                # never sent.
                unchanged += 1
                continue
            if write:
                write(row["id"], fields)
            # Later layers in the same run see this write: a stale snapshot
            # must never let a second layer treat a just-filled column as blank.
            row.update(fields)
            cov.rows_written += 1
            for k in fields:
                if k != "field_provenance":
                    cov.fields_written[k] = cov.fields_written.get(k, 0) + 1
    return {**report, "dataset": cfg.dataset, "layer_url": cfg.layer_url, **cov.as_dict(),
            "unchanged_skipped": unchanged,
            "query_failures_by_cause": dict(sorted(failure_kinds.items()))}


def _batches(cfg, county: str, crow: list[dict]):
    """(rows, url) per query. A county file is one request for every row; an
    ArcGIS / Socrata layer is asked one batch of identifiers at a time, and
    each batch carries exactly the rows whose identifier it asks for, so a
    failed batch costs only those rows."""
    if cfg.transport == "county_file":
        for url in P.query_urls(cfg, county, [r.get(cfg.row_id_column) for r in crow]):
            yield crow, url
        return
    by_id = defaultdict(list)
    for r in crow:
        key = str(r.get(cfg.row_id_column) or "").strip()
        if key:
            by_id[key].append(r)
    ids = sorted(by_id)
    for i in range(0, len(ids), cfg.batch_size):
        chunk = ids[i:i + cfg.batch_size]
        for url in P.query_urls(cfg, county, chunk):
            yield [r for k in chunk for r in by_id[k]], url


def select_rows(rows: list[dict], *, counties: list[str] | None = None, max_counties: int | None = None,
                ledgers: list[str] | None = None) -> list[dict]:
    """The rows of one batch: optionally only some ledgers (properties.source)
    and counties, and at most `max_counties` counties (largest first, then by
    name) - so an overnight run can be split into bounded slices."""
    rows = [r for r in rows if not ledgers or (r.get("source") or "") in ledgers]
    if counties:
        rows = [r for r in rows if (r.get("county") or "") in counties]
    if max_counties:
        size: dict = defaultdict(int)
        for r in rows:
            size[r.get("county") or ""] += 1
        keep = set(sorted(size, key=lambda c: (-size[c], c))[:max_counties])
        rows = [r for r in rows if (r.get("county") or "") in keep]
    return rows


# ------------------------------------------------------------ every layer, batched

# value_year only ever accompanies a value: it never makes a row a target.
_NOT_A_GAP = frozenset({"value_year", "longitude"})
DEFAULT_CHECKPOINT = REPO / "out" / ".harvest_cache" / "parcel_enrichment_checkpoint.json"


def layers_for_state(state: str, source_ids=None) -> list:
    """Every registered layer of the state, county-scoped first (the county's
    own assessor is the closer source - sources.for_county's order), then the
    statewide one; narrowed to `source_ids` when given."""
    from harvesters.enrichment.sources import all_sources  # noqa: PLC0415
    mine = [c for c in all_sources() if c.state == state and (not source_ids or c.source_id in source_ids)]
    return [c for c in mine if c.counties] + [c for c in mine if not c.counties]


def gap_columns(cfg) -> frozenset:
    return cfg.written_columns() - _NOT_A_GAP


def targets_for(cfg, rows: list[dict]) -> list[dict]:
    """The rows this layer could fill: its counties, carrying the identifier
    it is keyed on, missing at least one column it publishes (a placeholder
    address is missing). Sorted by id - the batch order."""
    cols = gap_columns(cfg)
    out = [r for r in rows if cfg.covers(r.get("county") or "") and cfg.takes_row(r)
           and str(r.get(cfg.row_id_column) or "").strip()
           and any(_row_blank(r, c) if cfg.fill_blank_only else blank_for(r, c) for c in cols)]
    return sorted(out, key=lambda r: str(r.get("id")))


def take_batch(cfg, targets: list[dict], limit: int | None, checkpoint) -> list[dict]:
    """At most `limit` targets, continuing after the row the layer's previous
    run stopped at and wrapping once (enrichment_queue.take_after): a row a
    layer cannot fill is retried after one full pass, never at the head of
    every run. No limit = every target."""
    if not limit or limit >= len(targets):
        return list(targets)
    by_id = {str(r.get("id")): r for r in targets}
    keys = sorted(by_id)
    cursor = checkpoint.cursor((cfg.source_id, "")) if checkpoint else None
    return [by_id[k] for k in EQ.take_after(keys, cursor, limit)]


def run_all_layers(state: str, rows: list[dict], fetch_json, *, write=None, recorded_at: str, limit: int | None = None,
                   checkpoint=None, source_ids=None, retries: int = 2, sleep=time.sleep) -> list[dict]:
    """Every cleared layer of the state over the state's active rows (every
    ledger), one bounded batch per layer. A refused layer is reported and
    makes no request. The checkpoint (never in a dry run: pass None) records
    the last row each layer considered."""
    reports = []
    for cfg in layers_for_state(state, source_ids):
        ok, why = P.enrichment_allowed(cfg)
        if not ok:
            reports.append({"state": state, "source_id": cfg.source_id, "skipped": why})
            continue
        targets = targets_for(cfg, rows)
        batch = take_batch(cfg, targets, limit, checkpoint)
        if not batch:
            reports.append({"state": state, "source_id": cfg.source_id, "targets": 0, "rows_considered": 0,
                            "skipped": "no row misses a column this layer publishes"})
            continue
        rep = run(state, batch, fetch_json, write=write, recorded_at=recorded_at, cfg=cfg, retries=retries, sleep=sleep)
        rep["targets"] = len(targets)
        reports.append(rep)
        if checkpoint is not None:
            checkpoint.advance((cfg.source_id, ""), max(str(r.get("id")) for r in batch))
    return reports


SUMMARY_KEYS = ("state", "source_id", "targets", "rows_considered", "matched", "unmatched", "ambiguous", "no_identifier",
                "failed_queries", "query_failures_by_cause", "rows_written", "unchanged_skipped", "fields_written", "skipped")


def _main_all_layers(a) -> int:
    base, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    source_ids = {s.strip() for s in a.source_id.split(",") if s.strip()} or None
    checkpoint = None if a.dry_run else EQ.Checkpoint(a.checkpoint)

    def fetch_json(url):
        time.sleep(0.3)
        return http_json(url)

    for st in [s.strip().upper() for s in a.state.split(",") if s.strip()]:
        if not states.is_activated(st):
            print(f"skip: state {st} is not activated")
            continue
        layers = layers_for_state(st, source_ids)
        if not any(P.enrichment_allowed(c)[0] for c in layers):
            print(f"skip: {st} has no cleared parcel layer" + (f" among {sorted(source_ids)}" if source_ids else ""))
            continue
        if not base or not key:
            print("skip: SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
            return 0
        rows = select_rows(fetch_rows(base, key, st), counties=[c.strip() for c in a.counties.split(",") if c.strip()] or None,
                           max_counties=a.max_counties or None,
                           ledgers=[x.strip() for x in a.ledgers.split(",") if x.strip()] or None)
        reports = run_all_layers(st, rows, fetch_json, write=None if a.dry_run else (lambda i, f: patch(base, key, i, f)),
                                 recorded_at=FP.now_iso(), limit=a.limit, checkpoint=checkpoint, source_ids=source_ids)
        out = Path(a.out or REPO / "out" / "public" / f"enrichment-{st.lower()}-layers.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"state": st, "mode": "dry-run" if a.dry_run else "apply", "limit": a.limit,
                                   "active_rows": len(rows), "layers": reports}, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
        # Counts only - never an identifier, address, owner or value.
        print(f"{st}: {len(rows)} active row(s); mode {'dry-run (nothing written)' if a.dry_run else 'apply'}")
        for rep in reports:
            print(json.dumps({k: rep.get(k) for k in SUMMARY_KEYS if k in rep}, sort_keys=True))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", required=True, help="a postal code (several comma-separated with --all-layers)")
    ap.add_argument("--dry-run", action="store_true", help="read and match, write nothing, advance no checkpoint")
    ap.add_argument("--all-layers", action="store_true",
                    help="every cleared layer of the state (county-scoped and statewide) over every active row of every "
                         "ledger, not only the statewide layer")
    ap.add_argument("--source-id", default="",
                    help="comma-separated layer ids (with --all-layers: a filter; without: these layers, in this order); "
                         "blank = every layer (--all-layers) or the state's statewide layer")
    ap.add_argument("--limit", type=int, default=None,
                    help="(--all-layers) at most N rows per layer this run, resuming after the previous run's last row")
    ap.add_argument("--checkpoint", default=str(DEFAULT_CHECKPOINT))
    ap.add_argument("--ledgers", default="", help="comma-separated properties.source values (laft,auction,certificate); blank = all")
    ap.add_argument("--counties", default="", help="comma-separated counties of this batch; blank = every covered county")
    ap.add_argument("--max-counties", type=int, default=0, help="at most this many counties (largest first) in this batch")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if a.limit is not None and a.limit < 1:
        print("::error::--limit must be a positive integer")
        return 2
    if a.all_layers:
        return _main_all_layers(a)
    st = a.state.upper()
    if not states.is_activated(st):
        print(f"skip: state {st} is not activated")
        return 0
    if a.source_id:
        # One layer or several (comma-separated, run in that order over the same
        # rows - a later layer sees what an earlier one filled).
        ids = [s.strip() for s in a.source_id.split(",") if s.strip()]
        cfgs = [next((c for c in all_sources() if c.source_id == sid and c.state == st), None) for sid in ids]
    else:
        ids, cfgs = ["(statewide)"], [for_state(st)]
    cleared = []
    for sid, cfg in zip(ids, cfgs):
        if cfg is None or not P.enrichment_allowed(cfg)[0]:
            what = "statewide parcel source" if sid == "(statewide)" else f"parcel source {sid}"
            print(f"skip: {st} {what} not cleared ({P.enrichment_allowed(cfg)[1] if cfg else 'none configured'})")
        else:
            cleared.append(cfg)
    if not cleared:
        return 0
    base, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("skip: SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
        return 0
    all_rows = fetch_rows(base, key, st, cleared[0].row_id_column)
    all_rows = select_rows(all_rows, counties=[c.strip() for c in a.counties.split(",") if c.strip()] or None,
                           max_counties=a.max_counties or None,
                           ledgers=[x.strip() for x in a.ledgers.split(",") if x.strip()] or None)

    def fetch_json(url):
        time.sleep(0.3)
        return http_json(url)

    for cfg in cleared:
        rows = [r for r in all_rows if cfg.covers(r.get("county") or "") and r.get(cfg.row_id_column) not in (None, "")]
        report = run(st, rows, fetch_json, write=None if a.dry_run else (lambda i, f: patch(base, key, i, f)),
                     recorded_at=FP.now_iso(), retries=2, cfg=cfg)
        report["dry_run"] = a.dry_run
        name = f"enrichment-{st.lower()}" + (f"-{cfg.source_id}" if a.source_id else "")
        out = Path(a.out if a.out and len(cleared) == 1 else REPO / "out" / "public" / f"{name}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({k: report.get(k) for k in ("state", "source_id", "rows_considered", "matched", "unmatched", "ambiguous",
                                                       "no_identifier", "failed_queries", "query_failures_by_cause", "rows_written",
                                                       "fields_written", "skipped", "dry_run")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
