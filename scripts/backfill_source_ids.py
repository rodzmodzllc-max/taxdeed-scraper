"""Fill a blank `source_id` / `source_authority` on Florida rows whose source
is proven by the row itself (cross-state enrichment sprint, 2026-10-02).

Migration 017 backfilled `source_id` once (FL auction -> fl_realauction,
FL certificate -> fl_lienhub_certificates), but the PowerShell syncs that
insert those rows never send it, so every row first listed after 017 had no
source id (234 active FL auction rows on 2026-10-02) - and with it no source
provenance, no registry join and no auction-process record.

This step runs after each such sync and fills the blank only:

  * FL auction rows: `fl_realauction` ONLY when the row's own `url_auction`
    is a RealAuction county host (<county>.realtaxdeed.com /
    <county>.realforeclose.com) - the page the harvester read it from. A row
    with any other or no auction URL (e.g. Okaloosa's Bid4Assets) is left
    blank; nothing is guessed from the county;
  * FL certificate rows: `fl_lienhub_certificates` - the LienHub sync is the
    only writer of `state=FL, source=certificate`;
  * `source_id=is.null` is part of every filter, so a set id is never
    replaced, and re-running changes nothing (idempotent);
  * never status, dates, amounts, owners or outcomes.

    python3 scripts/backfill_source_ids.py --source auction [--dry-run]
    python3 scripts/backfill_source_ids.py --source certificate [--dry-run]

Counts only are printed (public logs).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

USER_AGENT = "taxdeed-scraper backfill-source-ids (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"

# (source, PostgREST filters beyond state/source/source_id, source_id, source_authority)
RULES: dict[str, list[tuple[dict, str, str]]] = {
    "auction": [
        ({"url_auction": "like.https://*.realtaxdeed.com/*"}, "fl_realauction", "VENDOR_AUCTION"),
        ({"url_auction": "like.https://*.realforeclose.com/*"}, "fl_realauction", "VENDOR_AUCTION"),
    ],
    "certificate": [
        ({}, "fl_lienhub_certificates", "VENDOR_AUCTION"),
    ],
}


def rule_queries(source: str) -> list[tuple[str, dict]]:
    """(query string, payload) per rule - pure, tested directly."""
    out = []
    for extra, sid, _authority in RULES[source]:
        q = {"state": "eq.FL", "source": f"eq.{source}", "source_id": "is.null", **extra}
        out.append((urllib.parse.urlencode(q, safe="*:/.,"), {"source_id": sid}))
    return out


def authority_queries(source: str) -> list[tuple[str, dict]]:
    """A blank source_authority on a row whose id this step (or 017) set."""
    out, seen = [], set()
    for _extra, sid, authority in RULES[source]:
        if sid in seen:
            continue
        seen.add(sid)
        q = {"state": "eq.FL", "source": f"eq.{source}", "source_id": f"eq.{sid}", "source_authority": "is.null"}
        out.append((urllib.parse.urlencode(q, safe="*:/.,"), {"source_authority": authority}))
    return out


def _req(method: str, url: str, key: str, body: dict | None = None, prefer: str = "return=minimal"):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        "Prefer": prefer, "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.headers.get("Content-Range"), resp.read()


def count(base: str, key: str, qs: str) -> int:
    rng, _ = _req("HEAD", f"{base}/rest/v1/properties?{qs}&select=id", key, prefer="count=exact")
    try:
        return int(str(rng).split("/")[-1])
    except ValueError:
        return -1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", choices=sorted(RULES), required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    base, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set - nothing applied")
        return 0
    report = {"source": a.source, "dry_run": a.dry_run, "source_id": {}, "source_authority": {}}
    for label, queries in (("source_id", rule_queries(a.source)), ("source_authority", authority_queries(a.source))):
        for qs, payload in queries:
            n = count(base, key, qs)
            tag = next(iter(payload.values()))
            report[label][tag] = report[label].get(tag, 0) + max(n, 0)
            if n and not a.dry_run:
                _req("PATCH", f"{base}/rest/v1/properties?{qs}", key, payload)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
