#!/usr/bin/env python3
"""Attach each county's verified auction sale process to its ACTIVE auction
rows (cross-state enrichment sprint, 2026-10-02).

For every active `source=auction` row of a state, the matching verified row
of data/auction_process_evidence.csv (scripts/auction_process_engine.resolve)
becomes `otc_provenance.auction_process` - county-level guidance, the same
record for every row of that county's sale. Rules:

  * a refreshed record REPLACES the stored one (never mixes two pages);
    every other otc_provenance key is kept;
  * `sale_date` is written only when the row's sale_date is BLANK and the
    evidence row says the stated date applies to the current sale list
    (sale_date_applies=yes); its field_provenance entry names the page. A
    stored sale date is never replaced, and a FUTURE sale (next_sale_date) is
    never written onto a row;
  * never status, amounts, owners, outcomes, last_seen_at or any lifecycle
    field; never a closed / gone row;
  * a county without a verified row is left exactly as it is (the page then
    says "Not yet verified").

    python3 scripts/apply_auction_process.py --state FL [--dry-run]

Counts only are printed (public logs). Reads page by id (PostgREST max-rows).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import auction_process_engine as E  # noqa: E402
import field_provenance as FP  # noqa: E402

USER_AGENT = "taxdeed-scraper apply-auction-process (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
SELECT = "id,state,county,source,source_id,harvester_source,status,sale_date,otc_provenance,field_provenance"
GONE = frozenset({"closed", "expired", "gone", "sold", "redeemed", "cancelled", "canceled"})
PAGE = 1000


def plan_row(row: dict, rows: list, *, now: str) -> tuple[dict | None, str]:
    """(PATCH body or None, outcome). Pure - tested directly."""
    if str(row.get("status") or "active").lower() in GONE:
        return None, "not_active"
    sid = row.get("source_id") or row.get("harvester_source")
    ev = E.resolve(rows, state=row.get("state") or "", source_id=sid, county=row.get("county") or "")
    if ev is None:
        return None, "no_verified_process"
    rec = E.record(ev)
    stored = row.get("otc_provenance") if isinstance(row.get("otc_provenance"), dict) else {}
    prov = dict(stored)
    prov["auction_process"] = rec
    body: dict = {}
    if prov != stored:
        body["otc_provenance"] = prov
    outcome = "process"
    if rec.get("sale_date") and not row.get("sale_date"):
        body["sale_date"] = rec["sale_date"]
        body["field_provenance"] = FP.merge_field_provenance(row.get("field_provenance"), {
            "sale_date": FP.provenance_entry("county_list", source_id=ev.source_id, method="sale date published on the county's sale page",
                                             evidence_url=ev.evidence_url, observed_on=ev.observed_on, recorded_at=now)})
        outcome = "process_and_sale_date"
    if not body:
        return None, outcome + "_unchanged"
    return body, outcome


def _req(method: str, url: str, key: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "Prefer": "return=minimal", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def fetch_rows(base: str, key: str, state: str) -> list[dict]:
    rows, last = [], None
    while True:
        q = {"select": SELECT, "state": f"eq.{state}", "source": "eq.auction", "order": "id", "limit": str(PAGE)}
        if last:
            q["id"] = f"gt.{last}"
        page = _req("GET", f"{base}/rest/v1/properties?{urllib.parse.urlencode(q)}", key) or []
        rows.extend(page)
        if len(page) < PAGE:
            return rows
        last = page[-1]["id"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", default="out/public/auction-process-apply.json")
    a = ap.parse_args(argv)
    base, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set - nothing applied")
        return 0
    evidence = E.load()
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    rows = fetch_rows(base, key, a.state)
    tally, by_county, patched = Counter(), {}, 0
    for r in rows:
        body, outcome = plan_row(r, evidence, now=now)
        tally[outcome] += 1
        by_county.setdefault(r.get("county") or "?", Counter())[outcome] += 1
        if body is None or a.dry_run:
            continue
        _req("PATCH", f"{base}/rest/v1/properties?id=eq.{urllib.parse.quote(str(r['id']))}", key, body)
        patched += 1
    report = {"state": a.state, "dry_run": a.dry_run, "rows": len(rows), "patched": patched, "outcomes": dict(tally),
              "by_county": {c: dict(v) for c, v in sorted(by_county.items())}}
    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    Path(a.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
