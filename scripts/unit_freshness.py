#!/usr/bin/env python3
"""Per-unit source freshness: last attempted, last successful, consecutive
failures - for every (state, source_id/harvester, county) the harvesters
report (production-readiness program, 2026-09-30).

scripts/source_health.py records ONE row per dataset (migration 016). The
harvesters' status files (scripts/laft_status.py and the deeds /
certificates / Texas / Alabama equivalents) record one entry per unit per
RUN. Neither says, for a county, "when did we last actually read this
list successfully?" - which is what a customer needs to tell stale from
current, and what a harvester needs to stop hammering a source that has
been refusing it for days.

This script merges this run's status entries into a persisted per-unit
record and writes three things:

  out/.harvest_cache/unit_freshness.json   the persisted record (rides the
                                           workflow's change-detection cache)
  out/public/unit-freshness.json           counts, unit names, timestamps,
                                           statuses (never a row value)
  public.county_source_registry            last_attempt_at / last_attempt_status
                                           / last_success_at /
                                           last_success_row_count /
                                           consecutive_failures - ONLY when
                                           migration 021's columns exist
                                           (probed) and credentials are set;
                                           the registry's approved-read
                                           policy (018) then exposes it to
                                           the Dashboard

RULES
  * A FAILED attempt never advances last_success_at, never touches
    last_success_row_count, and increments consecutive_failures.
  * INCOMPLETE is an attempt (last_attempt_*) but not a success and not a
    failure streak: the source answered, the parser could not vouch for
    the whole list.
  * COMPLETE / EMPTY are the only successes (the same CLOSEOUT_ELIGIBLE set
    the lifecycle uses).
  * An entry whose reason starts with BACKOFF_PREFIX was NOT attempted (the
    harvester held off): it is recorded as skipped and changes nothing.
  * STALE / NOT_RUN are reader-side statuses and never appear in a
    harvester's file; they are ignored if they do.
  * The registry row is matched on (state, source_id, county) exactly; a
    unit with no registry row is kept in the file only.

BACK-OFF (`backoff_decision`): after MIN_FAILURES consecutive FAILED
attempts whose category is a block signature (HTTP 403, proxy failure,
access denied), a harvester should attempt the unit at most once per
HOLD_HOURS. Everything else is attempted every run. A held unit reports
FAILED with a "backoff hold" reason so the lifecycle fails closed exactly
as for a real failure - a hold is never mistaken for an empty list.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PERSIST_PATH = REPO / "out" / ".harvest_cache" / "unit_freshness.json"
REPORT_PATH = REPO / "out" / "public" / "unit-freshness.json"
REGISTRY_PATH = REPO / "data" / "county_source_registry.csv"

SUCCESS = frozenset({"COMPLETE", "EMPTY"})
ATTEMPT = frozenset({"COMPLETE", "EMPTY", "INCOMPLETE", "FAILED"})
BLOCK_CATEGORIES = ("TRANSPORT_HTTP_403_BLOCKED", "PROXY_FAILURE", "PROXY_NOT_CONFIGURED", "ACCESS_DENIED")
BACKOFF_PREFIX = "backoff hold"
MIN_FAILURES = 3
HOLD_HOURS = 48.0
USER_AGENT = "taxdeed-scraper/1.0 (+https://github.com/rodzmodzllc-max/taxdeed-scraper; unit freshness)"
REGISTRY_COLUMNS = ("last_attempt_at", "last_attempt_status", "last_success_at", "last_success_row_count", "consecutive_failures")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def unit_key(state: str, source_id: str, county: str) -> str:
    return f"{state}|{source_id}|{county}"


def normalize_entry(e: dict, *, default_state: str, default_source: str | None) -> dict | None:
    """One status-file entry -> {state, source_id, county, status, checked_at,
    row_count, error_category, reason, skipped}. None = not a unit entry."""
    county = str(e.get("county") or "").strip()
    status = str(e.get("status") or "").strip().upper()
    if not county or status not in ATTEMPT:
        return None
    source_id = str(e.get("source_id") or e.get("harvester") or default_source or "").strip()
    if not source_id:
        return None
    reason = str(e.get("reason") or "")
    rows = e.get("row_count", e.get("rowCount"))
    try:
        rows = int(rows) if rows is not None else None
    except (TypeError, ValueError):
        rows = None
    return {"state": str(e.get("state") or default_state), "source_id": source_id, "county": county, "status": status,
            "checked_at": str(e.get("checked_at") or ""), "row_count": rows,
            "error_category": e.get("error_category"), "reason": reason,
            "skipped": reason.startswith(BACKOFF_PREFIX)}


def merge(previous: dict, entries: list[dict], *, at: str) -> tuple[dict, dict]:
    """Merge this run's entries into the persisted record. Returns
    (record, counts)."""
    record = {k: dict(v) for k, v in (previous or {}).items() if isinstance(v, dict)}
    counts = {"units": 0, "attempted": 0, "succeeded": 0, "incomplete": 0, "failed": 0, "skipped": 0}
    for e in entries:
        key = unit_key(e["state"], e["source_id"], e["county"])
        cur = record.setdefault(key, {"state": e["state"], "source_id": e["source_id"], "county": e["county"],
                                      "last_attempt_at": None, "last_attempt_status": None, "last_success_at": None,
                                      "last_success_row_count": None, "consecutive_failures": 0, "last_error_category": None})
        counts["units"] += 1
        if e["skipped"]:
            counts["skipped"] += 1
            cur["last_skipped_at"] = e["checked_at"] or at
            continue
        counts["attempted"] += 1
        cur["last_attempt_at"] = e["checked_at"] or at
        cur["last_attempt_status"] = e["status"]
        if e["status"] in SUCCESS:
            counts["succeeded"] += 1
            cur["last_success_at"] = e["checked_at"] or at
            cur["last_success_row_count"] = e["row_count"] if e["row_count"] is not None else 0
            cur["consecutive_failures"] = 0
            cur["last_error_category"] = None
        elif e["status"] == "INCOMPLETE":
            counts["incomplete"] += 1
            cur["consecutive_failures"] = 0
            cur["last_error_category"] = e.get("error_category")
        else:
            counts["failed"] += 1
            cur["consecutive_failures"] = int(cur.get("consecutive_failures") or 0) + 1
            cur["last_error_category"] = e.get("error_category")
    return record, counts


def backoff_decision(unit: dict | None, *, now: datetime | None = None, min_failures: int = MIN_FAILURES,
                     hold_hours: float = HOLD_HOURS) -> tuple[bool, str]:
    """(attempt, reason). Attempt unless the unit has failed MIN_FAILURES
    times in a row with a block signature and was attempted within
    HOLD_HOURS."""
    if not unit:
        return True, "no history"
    failures = int(unit.get("consecutive_failures") or 0)
    category = str(unit.get("last_error_category") or "")
    if failures < min_failures or not category.startswith(BLOCK_CATEGORIES):
        return True, "attempt"
    last = unit.get("last_attempt_at")
    try:
        t = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return True, "attempt (unreadable last_attempt_at)"
    age_h = ((now or datetime.now(timezone.utc)) - t).total_seconds() / 3600.0
    if age_h >= hold_hours:
        return True, f"attempt (hold of {hold_hours:g}h elapsed after {failures} blocked failures)"
    return False, f"{BACKOFF_PREFIX}: {failures} consecutive {category} failures; next attempt after {hold_hours:g}h (last {age_h:.0f}h ago)"


def load_persisted(path: Path | str = PERSIST_PATH) -> dict:
    p = Path(path)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def lookup(record: dict, state: str, source_id: str, county: str) -> dict | None:
    return record.get(unit_key(state, source_id, county))


def read_status(path: Path) -> list:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def registry_units(path: Path | str = REGISTRY_PATH) -> dict[str, dict]:
    """(state, source_id, county) -> registry row, for the PATCH matching."""
    import csv
    p = Path(path)
    if not p.is_file():
        return {}
    out: dict[str, dict] = {}
    with open(p, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[unit_key(r.get("state", ""), r.get("source_id", ""), r.get("county", ""))] = r
    return out


def registry_patches(record: dict, units: dict[str, dict]) -> list[tuple[dict, dict]]:
    """[(match, body)] for every unit the registry knows."""
    out = []
    for key, u in record.items():
        if key not in units:
            continue
        # Only values this record HAS: a job without the persisted file (a
        # fresh cache) knows nothing about earlier successes, and NULL must
        # never overwrite the registry's stored last_success_at.
        body = {c: u.get(c) for c in REGISTRY_COLUMNS if u.get(c) is not None}
        body["consecutive_failures"] = int(u.get("consecutive_failures") or 0)
        out.append(({"state": u["state"], "source_id": u["source_id"], "county": u["county"]}, body))
    return out


class RegistryApi:
    def __init__(self, url: str, key: str, *, dry_run: bool = False) -> None:
        self.base = url.rstrip("/") + "/rest/v1/county_source_registry"
        self.key = key
        self.dry_run = dry_run
        self.requests_made = 0

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "User-Agent": USER_AGENT, "Content-Type": "application/json"}
        h.update(extra or {})
        return h

    def has_columns(self) -> bool:
        req = urllib.request.Request(f"{self.base}?select={','.join(REGISTRY_COLUMNS)}&limit=0", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=60):
                self.requests_made += 1
                return True
        except urllib.error.HTTPError as exc:
            if exc.code == 400:
                return False
            raise

    def patch(self, match: dict, body: dict) -> None:
        if self.dry_run:
            return
        q = "&".join(f"{k}=eq.{urllib.parse.quote(str(v), safe='')}" for k, v in match.items())
        req = urllib.request.Request(f"{self.base}?{q}", data=json.dumps(body, default=str).encode(), method="PATCH",
                                     headers=self._headers({"Prefer": "return=minimal"}))
        with urllib.request.urlopen(req, timeout=60):
            self.requests_made += 1


def public_report(record: dict, counts: dict, *, at: str) -> dict:
    units = []
    for key in sorted(record):
        u = record[key]
        units.append({k: u.get(k) for k in ("state", "source_id", "county", "last_attempt_at", "last_attempt_status",
                                             "last_success_at", "last_success_row_count", "consecutive_failures", "last_error_category")})
    return {"generated_at": at, "counts": counts, "units": units,
            "note": "unit names, statuses, timestamps and counts only; never a row value"}


def main(argv=None) -> int:
    import urllib.parse  # noqa: F401 - used by RegistryApi.patch
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--status", action="append", default=[], metavar="PATH[:SOURCE_ID]",
                    help="a harvester status file; ':SOURCE_ID' names the source for files whose entries carry none (deeds, certificates)")
    ap.add_argument("--state", default="FL", help="default state for entries that carry none")
    ap.add_argument("--persist", default=str(PERSIST_PATH))
    ap.add_argument("--report", default=str(REPORT_PATH))
    ap.add_argument("--registry", default=str(REGISTRY_PATH))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    at = now_iso()
    entries: list[dict] = []
    for spec in args.status:
        path, _, default_source = spec.partition(":")
        for e in read_status(Path(path)):
            n = normalize_entry(e, default_state=args.state, default_source=default_source or None)
            if n:
                entries.append(n)
    record, counts = merge(load_persisted(args.persist), entries, at=at)

    pp = Path(args.persist)
    pp.parent.mkdir(parents=True, exist_ok=True)
    pp.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    rp = Path(args.report)
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(public_report(record, counts, at=at), indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"unit freshness: {counts['units']} unit entries this run - attempted {counts['attempted']}, succeeded {counts['succeeded']}, "
          f"incomplete {counts['incomplete']}, failed {counts['failed']}, skipped (back-off hold) {counts['skipped']}; "
          f"{len(record)} units on record")
    held = [u for u in record.values() if not backoff_decision(u, now=datetime.now(timezone.utc))[0]]
    if held:
        print("  held (blocked-source back-off): " + ", ".join(f"{u['state']}/{u['county']} ({u['source_id']})" for u in held))

    url, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("  SUPABASE_URL / SUPABASE_SERVICE_KEY not set - registry not updated (file outputs only)")
        return 0
    api = RegistryApi(url, key, dry_run=args.dry_run)
    try:
        if not api.has_columns():
            print("  migration 021 not applied - county_source_registry freshness columns absent; registry not updated")
            return 0
        patches = registry_patches(record, registry_units(args.registry))
        for match, body in patches:
            api.patch(match, body)
        print(f"  registry: {len(patches)} unit row(s) patched{' (dry run)' if args.dry_run else ''}")
    except (urllib.error.URLError, OSError) as exc:
        print(f"::warning title=unit_freshness::registry update failed: {type(exc).__name__} - file outputs are complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
