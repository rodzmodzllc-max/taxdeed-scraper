#!/usr/bin/env python3
"""Daily freshness verification (2026-10-25).

The harvests run every day; nothing checked afterwards that they actually
refreshed what customers see. A source can fail quietly (LienHub returned
HTTP 403 for every county, a sync can stop at a timeout) and its rows keep
reading "active" with an old last read. The website reads Supabase live,
so a fresh database is a fresh site and a stale one is a stale site.

This script answers, once a day and counts only, for every production
source (state, source_id) in data/county_source_registry.csv:

    active rows | rows read within --stale-hours | newest last read

and classifies it:

    FRESH        every active row was read within the window
    PARTIAL      some were (normal for an auction ledger: a sale that left
                 the county's list keeps its old read until its sale day)
    STALE        none were - the source did not refresh
    MANUAL       a manual-only source (unit_freshness.MANUAL_ONLY_SOURCES);
                 reported, never failed - it has no schedule
    NO_ROWS      no active rows (nothing to verify)

Output: out/public/daily-freshness.json, a Markdown table on
$GITHUB_STEP_SUMMARY, one `::warning::` per STALE / PARTIAL source.
Exit 1 when any scheduled source is STALE (unless --no-fail), so the run
shows red in the Actions tab.

Read-only: HEAD / GET with `Prefer: count=exact`. No row value, parcel or
owner ever reaches the output - only source ids, counts and timestamps.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from rest_pages import get_json  # noqa: E402
from unit_freshness import MANUAL_ONLY_SOURCES, STALE_HOURS  # noqa: E402

REGISTRY = ROOT / "data" / "county_source_registry.csv"
OUT = ROOT / "out" / "public" / "daily-freshness.json"

FRESH, PARTIAL, STALE, MANUAL, NO_ROWS = "FRESH", "PARTIAL", "STALE", "MANUAL", "NO_ROWS"


def production_sources(path: Path = REGISTRY) -> list[tuple[str, str]]:
    """(state, source_id) of every PRODUCTION_VERIFIED registry row, deduped."""
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return sorted({(r["state"], r["source_id"]) for r in rows
                   if r.get("source_id") and r.get("verification_status") == "PRODUCTION_VERIFIED"})


def classify(source_id: str, active: int, fresh: int) -> str:
    if source_id in MANUAL_ONLY_SOURCES:
        return MANUAL
    if active == 0:
        return NO_ROWS
    if fresh >= active:
        return FRESH
    return PARTIAL if fresh > 0 else STALE


def count_of(content_range: str | None) -> int:
    """PostgREST Content-Range `0-0/123` or `*/0` -> 123 / 0."""
    if not content_range or "/" not in content_range:
        raise ValueError("no count in Content-Range")
    total = content_range.rsplit("/", 1)[1]
    if total == "*":
        raise ValueError("count not returned")
    return int(total)


class Api:
    def __init__(self, url: str, key: str, opener: Callable = urllib.request.urlopen):
        self.base = url.rstrip("/") + "/rest/v1/properties"
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}"}
        self.opener = opener

    def _qs(self, params: dict) -> str:
        return urllib.parse.urlencode(params, safe="(),.*:")

    def count(self, params: dict) -> int:
        req = urllib.request.Request(f"{self.base}?{self._qs({**params, 'select': 'id', 'limit': '1'})}",
                                     headers={**self.headers, "Prefer": "count=exact"}, method="HEAD")
        with self.opener(req, timeout=120) as resp:
            return count_of(resp.headers.get("Content-Range"))

    def newest(self, params: dict) -> str | None:
        rows = get_json(f"{self.base}?{self._qs({**params, 'select': 'last_seen_at', 'order': 'last_seen_at.desc.nullslast', 'limit': '1'})}",
                        self.headers, opener=self.opener) or []
        return rows[0].get("last_seen_at") if rows else None


def check(api, sources: list[tuple[str, str]], *, now: datetime, stale_hours: float) -> list[dict]:
    cutoff = (now - timedelta(hours=stale_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for state, sid in sources:
        base = {"state": f"eq.{state}", "source_id": f"eq.{sid}", "status": "eq.active"}
        active = api.count(base)
        fresh = api.count({**base, "last_seen_at": f"gte.{cutoff}"}) if active else 0
        newest = api.newest(base) if active else None
        out.append({"state": state, "source_id": sid, "active": active, "fresh": fresh,
                    "newest_last_seen_at": newest, "status": classify(sid, active, fresh)})
    return out


def report(results: list[dict], *, at: str, stale_hours: float) -> dict:
    by = {}
    for r in results:
        by[r["status"]] = by.get(r["status"], 0) + 1
    return {"generated_at": at, "stale_hours": stale_hours, "summary": dict(sorted(by.items())),
            "stale_sources": [f"{r['state']}:{r['source_id']}" for r in results if r["status"] == STALE],
            "sources": results}


def markdown(rep: dict) -> str:
    lines = [f"## Daily freshness ({rep['generated_at']}, window {rep['stale_hours']:g} h)", "",
             "| State | Source | Status | Read in window / active | Newest read |", "|---|---|---|---|---|"]
    for r in rep["sources"]:
        lines.append(f"| {r['state']} | `{r['source_id']}` | {r['status']} | {r['fresh']} / {r['active']} | "
                     f"{r['newest_last_seen_at'] or 'never'} |")
    lines += ["", "Summary: " + ", ".join(f"{k} {v}" for k, v in rep["summary"].items())]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stale-hours", type=float, default=STALE_HOURS)
    ap.add_argument("--no-fail", action="store_true", help="report only; never exit 1")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set - nothing checked", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    results = check(Api(url, key), production_sources(), now=now, stale_hours=args.stale_hours)
    rep = report(results, at=at, stale_hours=args.stale_hours)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    md = markdown(rep)
    print(md)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(md)
    for r in results:
        if r["status"] in (STALE, PARTIAL):
            print(f"::warning::{r['state']} {r['source_id']}: {r['status']} - {r['fresh']} of {r['active']} "
                  f"active rows read in the last {args.stale_hours:g} h (newest {r['newest_last_seen_at'] or 'never'})")
    return 1 if rep["stale_sources"] and not args.no_fail else 0


if __name__ == "__main__":
    sys.exit(main())
