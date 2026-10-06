#!/usr/bin/env python3
"""Authoritative geocoding pipeline: plan, dry run, apply.

  --mode plan     read the active records, classify each one (missing /
                  upgrade / already authoritative / no identifier / no
                  source / source not cleared) and order the candidates by
                  the enrichment priority rules. No source request, no write.
  --mode dry-run  the plan, then the source lookups for the candidates:
                  matched / no match / ambiguous / source unavailable /
                  parser failure, and how many coordinates WOULD be written.
                  Nothing is written.
  --mode apply    the dry run, and the writes. Requires --confirm-apply as
                  well; without it the run stops before the first lookup.

Coordinates come only from harvesters.enrichment.geocode's sources (FDOR
statewide cadastral and Santa Rosa's parcel layer in Florida; the cleared
statewide / county parcel layers elsewhere), matched on the record's own
identifier, one feature per identifier. Rules: docs/enrichment-geocoding.md.

The log and out/public/geocode-<mode>.json are counts only - no parcel
number, address, value or name (CI logs are public).

Environment: SUPABASE_URL, SUPABASE_SERVICE_KEY (apply needs the service
key; plan / dry-run only read). --rows FILE runs on a local JSON list instead.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from harvesters.enrichment import geocode as G  # noqa: E402
from harvesters.enrichment import priority as PR  # noqa: E402

USER_AGENT = "taxdeed-scraper authoritative-geocoding (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
READ_COLUMNS = ("id,state,county,ledger_type,source,status,publication_status,parcel,case_no,latitude,longitude,"
                "field_provenance,source_id,harvester_source,legal_desc,assessed,market,taxable_value,acreage,lot_sqft,"
                "land_use,dor_use_code,purchase_path_type,otc_provenance,photo_url")
PAGE = 1000
FL_PACING_SECONDS = 0.3


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def http_json(url: str, *, headers: dict | None = None, method: str = "GET", body: bytes | None = None, timeout: int = 60):
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw) if raw else None


def read_rows(base: str, key: str, states: list[str]) -> list[dict]:
    """Every active / available row of the states, paged by id (PostgREST
    caps any response at 1,000 rows)."""
    hdr = {"apikey": key, "Authorization": f"Bearer {key}"}
    rows: list[dict] = []
    for st in states:
        offset = 0
        while True:
            q = urllib.parse.urlencode({"select": READ_COLUMNS, "state": f"eq.{st}", "status": "in.(active,available)",
                                        "order": "id.asc", "limit": PAGE, "offset": offset})
            page = http_json(f"{base}/rest/v1/properties?{q}", headers=hdr) or []
            rows += page
            if len(page) < PAGE:
                break
            offset += len(page)
    return rows


def patch(base: str, key: str, row_id: str, fields: dict) -> None:
    hdr = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Prefer": "return=minimal"}
    http_json(f"{base}/rest/v1/properties?id=eq.{urllib.parse.quote(str(row_id))}", headers=hdr, method="PATCH",
              body=json.dumps(fields).encode())


# --- Florida lookups: the FDOR enricher's own exact, county-scoped matching ---
def fl_lookup(src: G.CoordinateSource, row: dict) -> G.Lookup:
    from scripts import enrich_property_details as EP  # requests; imported only when Florida is looked up
    import requests
    parcel, county = str(row.get("parcel") or "").strip(), str(row.get("county") or "")
    try:
        if src.lookup_kind == "fdor":
            attrs, centroid, cand = EP.lookup_fdor(county, parcel)
        else:
            attrs, centroid, cand = EP.lookup_santa_rosa_gis(parcel)
    except EP.FdorParserRejection:
        return G.Lookup("PARSER_FAILURE", reason="the layer returned an unreadable body")
    except (EP.FdorUnavailable, requests.RequestException):
        return G.Lookup("SOURCE_UNAVAILABLE", reason="the layer did not answer with a result")
    if cand == EP.AMBIGUOUS_MATCH:
        return G.Lookup("AMBIGUOUS", reason="the identifier matched more than one parcel")
    if attrs is None:
        return G.Lookup("NO_MATCH")
    if not isinstance(centroid, dict):
        return G.Lookup("PARSER_FAILURE", reason="the matched parcel carried no centroid")
    field = "ALT_KEY" if isinstance(cand, str) and cand.startswith(EP.ALT_KEY_PREFIX) else "PARCEL_ID"
    if src.lookup_kind == "santa_rosa":
        field = "PAR_NUM"
    ident = cand[len(EP.ALT_KEY_PREFIX):] if field == "ALT_KEY" else str(cand or "")
    return G.classify_point(centroid.get("y"), centroid.get("x"), "FL", matched_identifier=ident, matched_field=field)


def run(rows: list[dict], *, mode: str, allow_upgrade: bool, limit: int | None, ctx: PR.Context,
        fetch_json=None, fl_lookup_fn=None, write=None, recorded_at: str | None = None, pace: float = 0.0) -> dict:
    """The whole pipeline with I/O injected (tests pass fakes)."""
    recorded_at = recorded_at or now_iso()
    rep = G.Report(mode=mode, allow_upgrade=allow_upgrade, rows_read=len(rows))
    plan = []
    for r in PR.ordered(rows, ctx):
        cls, src = G.plan_row(r, allow_upgrade=allow_upgrade)
        rep.plan[cls] = rep.plan.get(cls, 0) + 1
        if cls in G.LOOKUP_CLASSES:
            plan.append((r, src))
            rule = PR.rule_of(r, ctx)
            rep.by_rule[rule] = rep.by_rule.get(rule, 0) + 1
            rep.by_source[src.source_id] = rep.by_source.get(src.source_id, 0) + 1
    rep.candidates = len(plan)
    if limit is not None:
        plan = plan[:limit]
    if mode == "plan":
        return rep.as_dict()

    # Parcel layers are queried in batches per source; Florida row by row.
    results: dict[str, G.Lookup] = {}
    by_src: dict[str, list] = {}
    for r, src in plan:
        by_src.setdefault(src.source_id, []).append((r, src))
    for sid, items in by_src.items():
        src = items[0][1]
        if src.lookup_kind == "parcel_layer":
            results.update(G.lookup_parcel_layer(src, [r for r, _ in items], fetch_json))
        else:
            for r, _ in items:
                results[r["id"]] = fl_lookup_fn(src, r)
                if pace:
                    time.sleep(pace)
    for r, src in plan:
        lk = results.get(r["id"]) or G.Lookup("SOURCE_UNAVAILABLE", reason="no answer")
        rep.looked_up += 1
        rep.add_outcome(lk.status)
        action, payload = G.decide(r, src, lk, allow_upgrade=allow_upgrade, recorded_at=recorded_at)
        if action == "skip":
            if lk.status == "MATCHED":
                rep.skip(payload)
            continue
        rep.would_write += 1
        if mode == "apply":
            try:
                write(r["id"], payload)
                rep.written += 1
            except Exception:  # noqa: BLE001 - one failed write never stops the run
                rep.write_errors += 1
    return rep.as_dict()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=("plan", "dry-run", "apply"), default="plan")
    ap.add_argument("--confirm-apply", action="store_true", help="required with --mode apply")
    ap.add_argument("--allow-upgrade", action="store_true",
                    help="also replace stored coordinates whose origin is weaker (unrecorded / vendor / address geocode)")
    ap.add_argument("--states", default="", help="comma-separated postal codes; blank = every state with a coordinate source")
    ap.add_argument("--limit", type=int, default=None, help="look up at most N candidates (in priority order)")
    ap.add_argument("--rows", help="read rows from this JSON file instead of the database")
    ap.add_argument("--out", default=str(REPO / "out" / "public"))
    a = ap.parse_args(argv)
    if a.mode == "apply" and not a.confirm_apply:
        print("refused: --mode apply writes production coordinates and needs --confirm-apply as well")
        return 2
    states = [s.strip().upper() for s in a.states.split(",") if s.strip()] or sorted({s.state for s in G.coordinate_sources()})
    base, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if a.rows:
        rows = [r for r in json.loads(Path(a.rows).read_text(encoding="utf-8")) if str(r.get("state") or "") in states]
    elif base and key:
        rows = read_rows(base, key, states)
    else:
        print("skip: SUPABASE_URL / SUPABASE_SERVICE_KEY not set and no --rows file")
        return 0
    write = (lambda rid, fields: patch(base, key, rid, fields)) if a.mode == "apply" else None
    report = run(rows, mode=a.mode, allow_upgrade=a.allow_upgrade, limit=a.limit, ctx=PR.Context.from_repo(),
                 fetch_json=lambda url: http_json(url), fl_lookup_fn=fl_lookup, write=write, pace=FL_PACING_SECONDS)
    report["states"] = states
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"geocode-{a.mode}.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
