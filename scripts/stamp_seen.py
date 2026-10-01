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
    python3 scripts/stamp_seen.py --state FL --source certificate --harvest out/harvest_certificates.json --case-key case_no

Counts only are printed (public logs).
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


def observed(rows: list, case_key: str) -> dict[str, list[str]]:
    """county -> sorted unique case numbers read this run."""
    out: dict[str, set] = defaultdict(set)
    for r in rows if isinstance(rows, list) else []:
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", required=True)
    ap.add_argument("--source", required=True, choices=("auction", "laft", "certificate"))
    ap.add_argument("--harvest", required=True)
    ap.add_argument("--case-key", default="case_no")
    a = ap.parse_args(argv)
    path = Path(a.harvest)
    if not path.exists():
        print(f"{a.state} {a.source}: no harvest file ({path.name}) - nothing stamped")
        return 0
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        print(f"{a.state} {a.source}: harvest file is not JSON - nothing stamped")
        return 0
    by_county = observed(rows, a.case_key)
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
