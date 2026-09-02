#!/usr/bin/env python3
"""Export the live Supabase tables to plain JSON/CSV files as a portable backup.

Why this exists (2026-09-02 audit): the harvest workflow already uploads each
run's RAW harvest as a 30-day artifact, so a failed sync never loses freshly
scraped data. But nothing anywhere backed up the DATABASE - and the database
is where all the irreplaceable material lives:

  * hand research that no scrape can regenerate (lien_level, lien_note,
    owner research, notes, favorites, bid list)
  * the enrichment this project spent real effort building (just value,
    parcel-centroid coordinates, year built, living area, lot size, legal
    description, sale history)
  * `status` / `gone_since` history, which is derived from the SEQUENCE of
    harvests over time and cannot be reconstructed from any single one

Re-running every harvester from scratch would restore none of that. A raw
harvest is a snapshot of what the counties publish TODAY; it is not a backup.

This is deliberately a plain-files export rather than anything clever:
newline-delimited JSON plus CSV, no vendor format, no restore tooling
required. Anything that can read JSON can read it - Postgres, SQLite, pandas,
a spreadsheet, or a future version of this app on a different backend. That
is the point of a backup: it has to be usable when the thing that produced it
is unavailable.

Exports are paginated, so table size is not a limit. Each run writes a
manifest with per-table row counts and a SHA-256 of every file, so a
truncated or corrupted export is detectable rather than silently trusted.

`profiles` is EXCLUDED by default on purpose - it holds account/approval data
about real people rather than property data. Set EXPORT_INCLUDE_PROFILES=1 if
a full disaster-recovery copy is genuinely wanted.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
OUT_DIR = Path(__file__).resolve().parent / "../out/backup"
PAGE_SIZE = int(os.environ.get("EXPORT_PAGE_SIZE", "1000"))

# Operational data by default. Override with a comma-separated list.
DEFAULT_TABLES = ["properties", "notes", "county_calendar"]
TABLES = [t.strip() for t in os.environ.get("EXPORT_TABLES", ",".join(DEFAULT_TABLES)).split(",") if t.strip()]
if os.environ.get("EXPORT_INCLUDE_PROFILES") == "1" and "profiles" not in TABLES:
    TABLES.append("profiles")

if not SUPABASE_URL or not SERVICE_KEY:
    print("SUPABASE_URL / SUPABASE_SERVICE_KEY environment variables are not set - check the workflow's secrets.", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Accept": "application/json",
}


def fetch_table(table: str, get=None) -> list[dict]:
    """Page through an entire table.

    Ordered by a stable key so pagination can't skip or duplicate rows when
    the table is written to mid-export (the harvest and this backup can
    legitimately overlap). Falls back to unordered only if the table has no
    `id`, which would make an ordered page request 400.
    """
    get = get or (lambda url, **kw: requests.get(url, **kw))
    rows: list[dict] = []
    order = "id"
    offset = 0
    while True:
        params = {"select": "*", "limit": str(PAGE_SIZE), "offset": str(offset)}
        if order:
            params["order"] = order
        resp = get(f"{SUPABASE_URL}/rest/v1/{table}", headers=HEADERS, params=params, timeout=60)
        if resp.status_code == 400 and order:
            # No `id` column on this table - retry unordered rather than fail.
            order = None
            continue
        resp.raise_for_status()
        page = resp.json()
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        offset += PAGE_SIZE


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_table(table: str, rows: list[dict]) -> dict:
    """Write one table as JSON (always) and CSV (when it has rows)."""
    json_path = OUT_DIR / f"{table}.json"
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2, default=str)
    written = {"rows": len(rows), "json": json_path.name, "json_sha256": _sha256(json_path)}

    if rows:
        # Union of keys, not just the first row's - a nullable column absent
        # from row 0 would otherwise be silently dropped from the CSV.
        fieldnames = sorted({k for r in rows for k in r.keys()})
        csv_path = OUT_DIR / f"{table}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in rows:
                writer.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fieldnames})
        written["csv"] = csv_path.name
        written["csv_sha256"] = _sha256(csv_path)
    return written


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "supabase_project": SUPABASE_URL.split("//")[-1].split(".")[0],
        "tables": {},
    }
    failures = []

    for table in TABLES:
        try:
            rows = fetch_table(table)
            manifest["tables"][table] = write_table(table, rows)
            print(f"  {table}: {len(rows)} rows", flush=True)
        except requests.RequestException as exc:
            # One missing/renamed table must not cost us the backup of every
            # other table - record it and carry on.
            print(f"  {table}: ERROR {exc}", file=sys.stderr, flush=True)
            manifest["tables"][table] = {"error": str(exc)}
            failures.append(table)

    with open(OUT_DIR / "manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    exported = sum(t.get("rows", 0) for t in manifest["tables"].values())
    print(f"\nBacked up {exported} rows across {len(TABLES) - len(failures)}/{len(TABLES)} tables -> {OUT_DIR}")

    # A backup that silently contains nothing is worse than a failed one,
    # because it looks like a backup. Fail loudly instead.
    if not exported:
        print("Backup produced ZERO rows across every table - failing rather than storing an empty backup.", file=sys.stderr)
        return 1
    if failures:
        print(f"WARNING: these tables did not export: {', '.join(failures)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
