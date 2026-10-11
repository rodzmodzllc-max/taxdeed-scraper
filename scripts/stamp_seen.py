"""Stamp `last_seen_at` on the rows a harvest actually read this run.

The Florida deed (auction) and LienHub certificate syncs are PowerShell
upserts that never set `last_seen_at`, so the Dashboard's per-row freshness
and the 36-hour stale check had nothing to read for ~3,800 Florida rows. This
step runs right AFTER such a sync:

  * a row is stamped only if its (county, case number) is in this run's
    harvest file - being in the file is the observation; a county whose read
    failed contributes nothing, and nothing is ever un-stamped or closed;
  * the timestamp is taken after the upsert, so a row the sync just inserted
    (first_seen_at = the insert's now()) never gets a last_seen_at before its
    first_seen_at (properties_seen_order_check);
  * one PATCH per county per chunk of case numbers, filtered by state and
    source - never a row of another state or ledger.

    python3 scripts/stamp_seen.py --state FL --source auction --harvest out/harvest_all.json --case-key case
    python3 scripts/stamp_seen.py --state FL --source certificate --harvest out/harvest_certificates.json --case-key case_no \
        --status out/harvest_certificates_status.json

`--status` (data-quality fix, 2026-10-01) makes the read's own completeness
gate explicit: with it, only counties the harvester marked COMPLETE (or
EMPTY) are stamped. A missing or unreadable status file stamps nothing - an
unavailable or incomplete source never refreshes a row's last read. A
PowerShell `ConvertTo-Json` of a one-element array is a bare object, so a
single-row harvest (or a single-county status file) is read as a list of one.

Counts only are printed (public logs).

`--provenance` (2026-10-11): the same read also stamps field_provenance for
the columns the harvest row itself supplied. The PowerShell upserts write
the list's own values (case, parcel, address, bid, assessed, sale date, the
sale URL; a certificate's number, tax year, dates, rate) but never say so,
and 937 of 1,185 active Florida auction rows carried no provenance at all on
2026-10-11. Each stamped row gets one `vendor_listing` entry per non-blank
list column that has no entry yet - an existing entry (an enricher's, or an
earlier stamp) is never replaced or downgraded, so the step is idempotent
and a rerun writes nothing. One PATCH per row that gains an entry, keyed by
id; a row that is not stored, or whose county was not COMPLETE / EMPTY, is
untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

USER_AGENT = "taxdeed-scraper stamp-seen (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
CHUNK = 150
# The read outcomes that vouch for a county's whole list (laft_status's
# CLOSEOUT_ELIGIBLE). INCOMPLETE / FAILED / SOURCE_UNAVAILABLE never stamp.
STAMP_ELIGIBLE = frozenset({"COMPLETE", "EMPTY"})


def as_list(data) -> list:
    """A JSON document as a list of rows: PowerShell serializes a one-element
    array as a bare object."""
    if isinstance(data, list):
        return data
    return [data] if isinstance(data, dict) else []


def read_json(path: Path):
    """Parsed JSON, or None when the file is missing or not JSON (a BOM is tolerated)."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError:
        return None


def eligible_counties(status) -> set[str]:
    """Counties whose read this run is COMPLETE / EMPTY in a harvester status file."""
    return {str(e.get("county") or "").strip() for e in as_list(status)
            if isinstance(e, dict) and str(e.get("status") or "").upper() in STAMP_ELIGIBLE} - {""}


def observed(rows: list, case_key: str) -> dict[str, list[str]]:
    """county -> sorted unique case numbers read this run."""
    out: dict[str, set] = defaultdict(set)
    for r in as_list(rows):
        if not isinstance(r, dict):
            continue
        county, case = str(r.get("county") or "").strip(), str(r.get(case_key) or "").strip()
        if county and case:
            out[county].add(case)
    return {c: sorted(v) for c, v in sorted(out.items())}


def _quote(v: str) -> str:
    # PostgREST in.() list item: double-quoted, inner quotes / backslashes escaped.
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'


def patch_urls(base: str, state: str, source: str, by_county: dict[str, list[str]]) -> list[str]:
    urls = []
    for county, cases in by_county.items():
        for i in range(0, len(cases), CHUNK):
            chunk = cases[i:i + CHUNK]
            q = urllib.parse.urlencode({"state": f"eq.{state}", "source": f"eq.{source}", "county": f"eq.{county}",
                                        "case_no": "in.(" + ",".join(_quote(c) for c in chunk) + ")"})
            urls.append(f"{base.rstrip('/')}/rest/v1/properties?{q}")
    return urls


# Harvest-row key -> properties column, per source: the columns the sync's own
# payload carries (scripts/sync-harvest-to-supabase.ps1 / sync-certificates-
# to-supabase.ps1). Only these get a provenance entry; a value the list left
# blank gets none.
PROVENANCE_COLUMNS = {
    "auction": {"parcel": "parcel", "address": "address", "bid": "bid", "assessed": "assessed", "sale_date": "sale_date",
                "appraiser": "url_appraiser", "auction_url": "url_auction"},
    "certificate": {"certificate_no": "certificate_no", "tax_year": "tax_year", "issued_date": "issued_date",
                    "expiration_date": "expiration_date", "bid": "bid", "address": "address", "owner_name": "owner_name",
                    "parcel": "parcel", "assessed": "assessed", "interest_rate": "interest_rate", "url_auction": "url_auction"},
}
PROVENANCE_SOURCE = "vendor_listing"   # RealAuction / Bid4Assets / LienHub: a vendor platform's list (scripts/field_provenance.RANK)


def source_id_for(source: str, county: str) -> str:
    if source == "certificate":
        return "fl_lienhub_certificates"
    return "fl_bid4assets_okaloosa" if county == "Okaloosa" else "fl_realauction"


def provenance_updates(harvest_row: dict, stored_provenance, *, source: str, county: str, recorded_at: str) -> dict:
    """Column -> entry for every non-blank list column that has no stored
    provenance entry. Never replaces an entry: the list's claim is recorded
    once, and an enricher's higher-ranked entry stays."""
    import field_provenance as FP
    existing = FP.load_provenance(stored_provenance)
    updates = {}
    for key, column in PROVENANCE_COLUMNS.get(source, {}).items():
        value = harvest_row.get(key)
        if FP.is_blank(value) or column in existing:
            continue
        updates[column] = FP.provenance_entry(PROVENANCE_SOURCE, source_id=source_id_for(source, county), recorded_at=recorded_at)
    return updates


def plan_provenance(rows: list, stored: list[dict], *, source: str, county: str, case_key: str, recorded_at: str) -> list[tuple]:
    """[(row id, merged field_provenance)] for the stored rows of one county
    that gain at least one entry from this run's harvest rows."""
    import field_provenance as FP
    by_case = {}
    for r in rows:
        if str(r.get("county") or "") == county and r.get(case_key) not in (None, ""):
            by_case[str(r[case_key])] = r
    out = []
    for st in stored:
        hr = by_case.get(str(st.get("case_no") or ""))
        if hr is None:
            continue
        updates = provenance_updates(hr, st.get("field_provenance"), source=source, county=county, recorded_at=recorded_at)
        if updates:
            out.append((st["id"], FP.merge_field_provenance(st.get("field_provenance"), updates)))
    return out


def stamp_provenance(base: str, key: str, *, state: str, source: str, rows: list, by_county: dict, case_key: str,
                     recorded_at: str) -> tuple[int, int, int]:
    """(rows read back, rows patched, failures). Reads each eligible county's
    stored rows by keyset (scripts/rest_pages), plans, PATCHes by id."""
    import rest_pages as RP
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": USER_AGENT}
    read = patched = failed = 0
    for county in sorted(by_county):
        try:
            stored = RP.read_all(base, "properties", headers, {"select": "id,case_no,field_provenance", "state": f"eq.{state}",
                                                              "source": f"eq.{source}", "county": f"eq.{county}"})
        except Exception as exc:  # noqa: BLE001 - one county's read failing stamps nothing for it
            failed += 1
            print(f"::warning title=stamp_seen::provenance read failed for one county ({type(exc).__name__})")
            continue
        read += len(stored)
        for row_id, merged in plan_provenance(rows, stored, source=source, county=county, case_key=case_key, recorded_at=recorded_at):
            body = json.dumps({"field_provenance": merged}).encode()
            req = urllib.request.Request(f"{base.rstrip('/')}/rest/v1/properties?id=eq.{urllib.parse.quote(str(row_id))}",
                                         data=body, method="PATCH", headers={**headers, "Prefer": "return=minimal"})
            try:
                with urllib.request.urlopen(req, timeout=120):
                    patched += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"::warning title=stamp_seen::a provenance PATCH failed ({type(exc).__name__})")
    return read, patched, failed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", required=True)
    ap.add_argument("--source", required=True, choices=("auction", "laft", "certificate"))
    ap.add_argument("--harvest", required=True)
    ap.add_argument("--case-key", default="case_no")
    ap.add_argument("--status", help="harvester status file; only its COMPLETE / EMPTY counties are stamped")
    ap.add_argument("--provenance", action="store_true", help="also record field_provenance for the list's own columns (idempotent)")
    a = ap.parse_args(argv)
    path = Path(a.harvest)
    if not path.exists():
        print(f"{a.state} {a.source}: no harvest file ({path.name}) - nothing stamped")
        return 0
    rows = read_json(path)
    if rows is None:
        print(f"{a.state} {a.source}: harvest file is not JSON - nothing stamped")
        return 0
    by_county = observed(rows, a.case_key)
    if a.status:
        status = read_json(Path(a.status))
        if status is None:
            print(f"{a.state} {a.source}: no readable status file ({Path(a.status).name}) - nothing stamped (fail closed)")
            return 0
        ok = eligible_counties(status)
        held = sorted(set(by_county) - ok)
        by_county = {c: v for c, v in by_county.items() if c in ok}
        if held:
            print(f"{a.state} {a.source}: {len(held)} county unit(s) not COMPLETE / EMPTY this run - not stamped")
    base, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("skip: SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
        return 0
    seen_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    body = json.dumps({"last_seen_at": seen_at}).encode()
    stamped = failed = 0
    for url in patch_urls(base, a.state.upper(), a.source, by_county):
        req = urllib.request.Request(url, data=body, method="PATCH", headers={
            "apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
            "Prefer": "return=representation,count=exact", "User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                stamped += len(json.loads(resp.read() or b"[]"))
        except Exception as exc:  # noqa: BLE001 - one failed chunk stamps nothing, the rest continue
            failed += 1
            print(f"::warning title=stamp_seen::a chunk was not stamped ({type(exc).__name__})")
    total = sum(len(v) for v in by_county.values())
    print(f"{a.state} {a.source}: {total} identities read this run across {len(by_county)} county unit(s); "
          f"{stamped} stored row(s) stamped last_seen_at={seen_at}; {failed} chunk(s) failed")
    if a.provenance and a.source in PROVENANCE_COLUMNS:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        read, patched, pfailed = stamp_provenance(base, key, state=a.state.upper(), source=a.source, rows=rows, by_county=by_county,
                                                  case_key=a.case_key, recorded_at=seen_at)
        print(f"{a.state} {a.source}: provenance - {read} stored row(s) read back, {patched} gained list-column entries, {pfailed} failure(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
