#!/usr/bin/env python3
"""Record one dataset's health after a harvest job's sync step.

Monitoring only. This script never retries a harvest, never touches
`properties`, and never fails the job (every exit path is 0; problems are
printed as ::warning annotations). It reads the completeness/status file the
harvester already writes, counts the rows in the raw harvest, and upserts one
row into `public.source_health` (migration 016) with the service key the job
already holds. It also writes the same record - counts and unit names only,
never a row value - to out/public/source_health-<source>.json, so the public
artifact carries it, and appends a line to the job summary.

Health is derived, not stored (staleness depends on when you look):

  NOT_RUN     no attempt recorded
  FAILED      the last attempt's sync step failed
  INCOMPLETE  the last attempt synced, but at least one unit (county / vendor
              source) was reported INCOMPLETE by the harvester's own gate
  STALE       the last success is older than 2x the source's cadence
              (scheduled sources only; a manual source is never STALE by the
              clock - it is labelled manual, with its last run date)
  HEALTHY     synced, every unit complete, within cadence

Standard library only - the certificates job installs no Python packages.

Usage (all from the workflow):
  source_health.py --source fl_deeds --label "..." --state FL --mode scheduled
                   --cadence-hours 12 --status out/harvest_all_status.json
                   --rows out/harvest_all.json --outcome success|failure|skipped
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

STALE_MULTIPLIER = 2


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: str | None):
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"::warning title=source_health::{path}: {type(exc).__name__}: {exc}")
        return None


def units_from_status(status) -> tuple[list[str], list[str]]:
    """(complete_units, incomplete_units) from either status-file shape:
    a LIST of {county, status, rowCount, reason} (FL deeds/certificates) or
    a DICT {"sources": {name: {"complete": bool, ...}}} (Texas)."""
    complete, incomplete = [], []
    if isinstance(status, list):
        for u in status:
            if not isinstance(u, dict):
                continue
            name = str(u.get("county") or u.get("source") or u.get("name") or "?")
            (complete if str(u.get("status", "")).upper() == "COMPLETE" else incomplete).append(name)
    elif isinstance(status, dict):
        sources = status.get("sources") if isinstance(status.get("sources"), dict) else status
        for name, u in sources.items():
            if not isinstance(u, dict):
                continue
            if u.get("complete") is True or str(u.get("status", "")).upper() == "COMPLETE":
                complete.append(str(name))
            elif u.get("complete") is False or str(u.get("status", "")).upper() == "INCOMPLETE":
                incomplete.append(str(name))
    return sorted(complete), sorted(incomplete)


def row_count_of(rows_path: str | None, status) -> int | None:
    data = read_json(rows_path)
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("rows", "records", "properties"):
            if isinstance(data.get(key), list):
                return len(data[key])
    if isinstance(status, list):
        counts = [u.get("rowCount") for u in status if isinstance(u, dict) and isinstance(u.get("rowCount"), int)]
        if counts:
            return sum(counts)
    if isinstance(status, dict) and isinstance(status.get("tables"), dict):
        # backup manifest.json: {"tables": {name: {"rows": n, ...}}}
        return sum(int(t.get("rows", 0) or 0) for t in status["tables"].values() if isinstance(t, dict))
    return None


def derive_health(rec: dict, at: datetime | None = None) -> str:
    """Mirror of healthOf() in public/app.js - keep the two in step."""
    at = at or datetime.now(timezone.utc)
    if not rec.get("last_attempt_at"):
        return "NOT_RUN"
    if rec.get("last_attempt_status") == "FAILED":
        return "FAILED"
    if rec.get("completeness") == "INCOMPLETE":
        return "INCOMPLETE"
    cadence = rec.get("cadence_hours")
    if rec.get("mode") == "scheduled" and cadence:
        last_ok = rec.get("last_success_at")
        if not last_ok:
            return "FAILED"
        t = datetime.fromisoformat(str(last_ok).replace("Z", "+00:00"))
        if at - t > timedelta(hours=cadence * STALE_MULTIPLIER):
            return "STALE"
    return "HEALTHY"


def upsert(url: str, key: str, rec: dict) -> tuple[bool, str]:
    body = json.dumps(rec).encode()
    req = urllib.request.Request(
        f"{url.rstrip('/')}/rest/v1/source_health?on_conflict=source",
        data=body, method="POST",
        headers={
            "apikey": key, "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        text = exc.read().decode(errors="replace")[:400]
        if exc.code == 404 or "PGRST205" in text or "source_health" in text and "not find" in text:
            return False, f"source_health table not found (migration 016 not applied yet): HTTP {exc.code} {text}"
        return False, f"HTTP {exc.code} {text}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def fetch_existing(url: str, key: str, source: str) -> dict | None:
    req = urllib.request.Request(
        f"{url.rstrip('/')}/rest/v1/source_health?source=eq.{source}&select=last_success_at",
        headers={"apikey": key, "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            rows = json.loads(resp.read().decode())
            return rows[0] if rows else None
    except Exception:
        return None


def build_record(args, status, at: str) -> dict:
    complete, incomplete = units_from_status(status)
    rows = row_count_of(args.rows, status)
    outcome = (args.outcome or "").lower()
    synced = outcome == "success"
    if not synced:
        attempt_status = "FAILED"
    elif incomplete:
        attempt_status = "INCOMPLETE"
    else:
        attempt_status = "SUCCESS"
    if status is None:
        completeness = "UNKNOWN"
    else:
        completeness = "INCOMPLETE" if incomplete else "COMPLETE"
    error = None
    if not synced:
        error = f"sync step outcome: {outcome or 'unknown'}"
    elif incomplete:
        error = f"{len(incomplete)} unit(s) INCOMPLETE: {', '.join(incomplete[:12])}" + (" ..." if len(incomplete) > 12 else "")
    return {
        "source": args.source,
        "label": args.label,
        "state": args.state,
        "mode": args.mode,
        "cadence_hours": args.cadence_hours,
        "last_attempt_at": at,
        "last_attempt_status": attempt_status,
        "last_run_id": os.environ.get("GITHUB_RUN_ID"),
        "row_count": rows,
        "units_total": (len(complete) + len(incomplete)) if status is not None else None,
        "units_complete": len(complete) if status is not None else None,
        "units_incomplete": len(incomplete) if status is not None else None,
        "incomplete_units": incomplete,
        "completeness": completeness,
        "error": error,
        "_synced": synced,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--mode", choices=["scheduled", "manual"], default="scheduled")
    ap.add_argument("--cadence-hours", type=int, default=None)
    ap.add_argument("--status", default=None, help="the harvester's completeness/status file")
    ap.add_argument("--rows", default=None, help="the raw harvest file, for the row count")
    ap.add_argument("--outcome", default="", help="the sync step's outcome: success | failure | cancelled | skipped")
    ap.add_argument("--public-dir", default="out/public")
    ap.add_argument("--no-upsert", action="store_true", help="write the evidence file only")
    args = ap.parse_args(argv)

    at = now_iso()
    status = read_json(args.status)
    rec = build_record(args, status, at)
    synced = rec.pop("_synced")

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    previous_success = None
    if url and key and not args.no_upsert:
        existing = fetch_existing(url, key, args.source)
        previous_success = existing.get("last_success_at") if existing else None
    rec["last_success_at"] = at if synced else previous_success

    health = derive_health(rec)
    public = Path(args.public_dir)
    public.mkdir(parents=True, exist_ok=True)
    evidence = {**rec, "health": health, "note": "counts and unit names only; never row values"}
    (public / f"source_health-{args.source}.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    line = (f"source_health: {args.source} -> {health} (attempt {rec['last_attempt_status']}, "
            f"rows {rec['row_count']}, units {rec['units_complete']}/{rec['units_total']} complete)")
    print(line)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"- **{args.label}**: `{health}` - attempt {rec['last_attempt_status']}, rows {rec['row_count']}, "
                     f"units {rec['units_complete']}/{rec['units_total']} complete"
                     + (f", incomplete: {', '.join(rec['incomplete_units'][:12])}" if rec["incomplete_units"] else "") + "\n")
    if health in ("INCOMPLETE", "FAILED"):
        print(f"::warning title=Dataset {health}::{args.label}: {rec['error']}")

    if args.no_upsert:
        return 0
    if not url or not key:
        print("::warning title=source_health::SUPABASE_URL / SUPABASE_SERVICE_KEY not set - health recorded in the artifact only")
        return 0
    ok, msg = upsert(url, key, rec)
    if ok:
        print(f"source_health: upserted ({msg})")
    else:
        print(f"::warning title=source_health not recorded::{msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
