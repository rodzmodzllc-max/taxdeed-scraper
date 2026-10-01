#!/usr/bin/env python3
"""Give every active AVAILABLE row of a source WITHOUT a lifecycle read its
county-level acquisition record (Acquisition-path sprint, 2026-10-01).

Florida and Louisiana rows get their acquisition path from
scripts/laft_lifecycle.py on every read. Texas AVAILABLE rows come from the
manual-only LGBS harvest and is
never retried from here: nothing ever resolved a path for them, so all 421
active Texas rows had no listing link, no match and no process. This step
closes that gap WITHOUT a source read:

  * the source listing is the registry's canonical page for the row's
    (source_id, county) - the page the harvester read the row from - never a
    composed property URL;
  * the deterministic match is the identity the sync upserted the row under
    (case_no, else parcel), dated by the registry's last successful read of
    that source; no name, address or proximity match;
  * the acquisition record is the VERIFIED county-level evidence row
    (data/purchase_path_evidence.csv) for the row's (state, source_id,
    county), through the same engine the lifecycle uses
    (scripts/purchase_path_engine.resolve). One record per county, inherited
    by every row of that county;
  * nothing stronger is overwritten: a stored property-scope path is never
    replaced by a source-scope one; existing otc_provenance keys are kept and
    only the path / match keys are added or refreshed; a county without a
    verified evidence row gets its listing and match only - the row stays
    published under the source rules and its page says the acquisition path
    is not yet verified (enrichment, never a publication decision);
  * never last_seen_at, status, amounts, owners or outcomes.

    python3 scripts/apply_acquisition_paths.py --state TX --source-id tx_lgbs [--dry-run]

Counts only are printed (public logs).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.parse  # noqa: I001 - stdlib only: this step makes no request to any source
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import purchase_path_engine as PE  # noqa: E402

REGISTRY = HERE.parent / "data" / "county_source_registry.csv"
USER_AGENT = "taxdeed-scraper apply-acquisition-paths (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
SELECT = ("id,state,county,source,source_id,harvester_source,case_no,parcel,status,list_url,document_url,"
          "purchase_url,purchase_url_kind,purchase_path_type,purchase_path_scope,purchase_path_evidence,"
          "purchase_path_observed_on,otc_provenance")
PATH_PROV_KEYS = ("purchase_evidence_url", "purchase_evidence_type", "purchase_evidence_title", "purchase_instructions",
                  "purchase_path_observed_on", "acquisition")
GONE = frozenset({"closed", "expired", "gone", "sold", "redeemed", "cancelled", "canceled"})


def load_registry(path: Path, state: str) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    if not path.is_file():
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("state") == state:
                out[(r.get("source_id") or "", r.get("county") or "")] = r
    return out


def source_match(row: dict, *, listing: str, read_on: str | None, harvester: str) -> dict | None:
    case_no, parcel = str(row.get("case_no") or "").strip(), str(row.get("parcel") or "").strip()
    if case_no:
        m = {"identifier": "case_no", "value": case_no}
        if parcel:
            m["parcel"] = parcel
    elif parcel:
        m = {"identifier": "parcel", "value": parcel}
    else:
        return None
    m["source"] = listing
    m["basis"] = (f"row read from the source listing by the harvester ({harvester}); identity as the sync upserts it"
                  + (f"; last successful source read {read_on}" if read_on else ""))
    if read_on:
        m["read_at"] = read_on
    return m


def plan_row(row: dict, *, registry: dict, evidence: list, state: str, today: str) -> tuple[dict | None, str]:
    """(PATCH payload or None, outcome label). Pure - tested directly."""
    if str(row.get("status") or "active").lower() in GONE:
        return None, "not_active"
    source_id = row.get("source_id") or row.get("harvester_source") or ""
    county = row.get("county") or ""
    reg = registry.get((source_id, county))
    if reg is None:
        return None, "no_registry_row"
    stored = row.get("otc_provenance") if isinstance(row.get("otc_provenance"), dict) else {}
    listing = row.get("list_url") or row.get("document_url") or stored.get("list_url") or stored.get("document_url") or reg.get("canonical_url") or ""
    if not listing.startswith("https://"):
        return None, "no_source_listing"
    path, refusals = PE.resolve(row, state=state, source_id=source_id, county=county, registry_row=reg, evidence=evidence,
                                list_url=listing, document_url=row.get("document_url"), harvest_date=today)
    prov = dict(stored)
    prov.setdefault("source_id", source_id)
    prov.setdefault("harvester", source_id)
    if not prov.get("list_url") and not prov.get("document_url"):
        prov["list_url"] = listing
    read_on = reg.get("last_checked") if PE._DATE.match(reg.get("last_checked") or "") else None
    if not (isinstance(prov.get("source_match"), dict) and prov["source_match"].get("value")):
        m = source_match(row, listing=listing, read_on=read_on, harvester=row.get("harvester_source") or source_id)
        if m:
            prov["source_match"] = m
    payload: dict = {}
    if not row.get("list_url") and not row.get("document_url"):
        payload["list_url"] = listing
    outcome = "no_verified_evidence"
    if path is not None:
        if row.get("purchase_path_scope") == "property" and path.scope != "property":
            outcome = "kept_stronger_property_path"
        else:
            payload.update(path.columns())
            for k in PATH_PROV_KEYS:
                prov.pop(k, None)               # a refreshed record replaces the old one, never mixes with it
            prov.update(path.provenance())
            prov["purchase_path_mode"] = path.mode
            prov["purchase_url"] = f"{path.path_type} ({path.scope}-scope): {path.evidence}"
            outcome = "path"
    elif refusals:
        prov["purchase_url"] = "no verified acquisition path; refused: " + "; ".join(refusals)
    if prov != stored:
        payload["otc_provenance"] = prov
    payload = {k: v for k, v in payload.items() if row.get(k) != v}     # only what changes
    if not payload:
        return None, outcome + "_unchanged"
    return payload, outcome


def _req(method: str, url: str, key: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "Prefer": "return=minimal", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def fetch_rows(base: str, key: str, state: str, source_id: str | None) -> list[dict]:
    rows, offset = [], 0
    while True:
        q = {"select": SELECT, "state": f"eq.{state}", "source": "eq.laft", "order": "id", "limit": "1000", "offset": str(offset)}
        if source_id:
            q["source_id"] = f"eq.{source_id}"
        page = _req("GET", f"{base.rstrip('/')}/rest/v1/properties?{urllib.parse.urlencode(q)}", key) or []
        rows.extend(page)
        if len(page) < 1000:
            return rows
        offset += 1000


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", required=True)
    ap.add_argument("--source-id", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", default="out/public/acquisition-apply.json")
    a = ap.parse_args(argv)
    base, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set - nothing applied")
        return 0
    registry = load_registry(REGISTRY, a.state)
    evidence = PE.load_evidence()
    today = date.today().isoformat()
    rows = fetch_rows(base, key, a.state, a.source_id)
    tally: Counter = Counter()
    by_county: dict[str, Counter] = {}
    patched = 0
    for r in rows:
        payload, outcome = plan_row(r, registry=registry, evidence=evidence, state=a.state, today=today)
        tally[outcome] += 1
        by_county.setdefault(r.get("county") or "?", Counter())[outcome] += 1
        if payload is None or a.dry_run:
            continue
        _req("PATCH", f"{base.rstrip('/')}/rest/v1/properties?id=eq.{urllib.parse.quote(str(r['id']))}", key, payload)
        patched += 1
    report = {"state": a.state, "source_id": a.source_id, "dry_run": a.dry_run, "rows": len(rows), "patched": patched,
              "outcomes": dict(tally), "by_county": {c: dict(v) for c, v in sorted(by_county.items())}}
    Path(a.report).parent.mkdir(parents=True, exist_ok=True)
    Path(a.report).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
