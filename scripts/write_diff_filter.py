#!/usr/bin/env python3
"""Drop unchanged rows before a sync upserts them (2026-10-26).

The CLI and I/O half of scripts/write_diff.py, whose `split()` is the one
rule (a row whose stored copy already holds the same values is not written;
`last_seen_at` aside, re-stamped once its stored value is older than
FRESH_HOURS). Used by:

  * the three Florida PowerShell syncs (sync-harvest-to-supabase.ps1,
    sync-laft-to-supabase.ps1, sync-certificates-to-supabase.ps1) through
    their identical "Write only what changed" helper block
    (`Select-ChangedRows`), so the comparison is never re-implemented in
    PowerShell;
  * scripts/sync-texas-to-supabase.py through `filter_rows()`.

    write_diff_filter.py --state FL --source auction --in rows.json --out keep.json

Reads the stored rows for the identities in rows.json - (state, source,
county, case_no), the syncs' own conflict target - by keyset pages
(scripts/rest_pages.py; only the columns being sent plus id, the identity
and last_seen_at), writes the rows `write_diff.split` keeps (same order,
same keys) and prints counts only (new / changed / restamp /
unchanged_skipped) - never a parcel, an owner name or an address.

FAIL OPEN: if the stored rows cannot be read (or the environment is not
set), every row is kept - the sync writes exactly what it wrote before this
filter existed. A read error never loses a sync. Exit 2 only when rows.json
itself cannot be read; the PowerShell helper then also keeps every row.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import rest_pages as RP  # noqa: E402
import write_diff as WD  # noqa: E402

USER_AGENT = "taxdeed-scraper write-diff-filter (+https://github.com/rodzmodzllc-max/taxdeed-scraper)"
IDENTITY = ("state", "source", "county", "case_no")
COUNTY_CHUNK = 40  # counties per in.(...) filter - keeps every URL short


def _in_list(values) -> str:
    return "in.(" + ",".join('"' + str(v).replace('"', '') + '"' for v in values) + ")"


def key_of(row: dict, default_state: str | None = None) -> tuple:
    return (str(row.get("state") or default_state or ""), str(row.get("source") or ""),
            str(row.get("county") or ""), str(row.get("case_no") or ""))


def columns_for(rows: list[dict]) -> list[str]:
    cols = {"id", "last_seen_at", *IDENTITY}
    for r in rows:
        cols.update(k for k in r if isinstance(k, str))
    return sorted(cols)


def _opener(req, timeout=None):
    # Looked up at call time (rest_pages binds urlopen at import), so a
    # caller's patched urllib.request.urlopen is the one used.
    return urllib.request.urlopen(req, timeout=timeout)


def read_stored(base: str, key: str, *, state: str, rows: list[dict], fetch=None) -> list[dict]:
    """Every stored row of `state` sharing a (source, county) with `rows`."""
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "User-Agent": USER_AGENT}
    select = ",".join(columns_for(rows))
    sources = sorted({str(r.get("source") or "") for r in rows} - {""})
    counties = sorted({str(r.get("county") or "") for r in rows} - {""})
    out: list[dict] = []
    for i in range(0, len(counties), COUNTY_CHUNK):
        params = {"select": select, "state": f"eq.{state}",
                  "source": f"eq.{sources[0]}" if len(sources) == 1 else _in_list(sources),
                  "county": _in_list(counties[i:i + COUNTY_CHUNK])}
        if fetch is None:
            url = f"{base.rstrip('/')}/rest/v1/properties"
            page_fetch = lambda qs, _u=url: RP.get_json(f"{_u}?{qs}", headers, opener=_opener)  # noqa: E731
        else:
            page_fetch = fetch
        out.extend(RP.read_all(base, "properties", headers, params, fetch=page_fetch))
    return out


def filter_rows(rows: list[dict], *, state: str, base: str | None = None, key: str | None = None,
                label: str = "sync", now=None, fetch=None, log=None) -> tuple[list[dict], dict]:
    """(rows to write, counts). Fails open: when the stored rows cannot be
    read, every row is returned and counts carry `read_failed: 1`."""
    log = log or (lambda m: print(m, file=sys.stderr))
    rows = [r for r in rows if isinstance(r, dict)]
    base = base if base is not None else os.environ.get("SUPABASE_URL", "")
    key = key if key is not None else os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not rows:
        return [], {"new": 0, "changed": 0, "restamp": 0, "unchanged_skipped": 0}
    if not base or not key:
        log(f"::warning title=write_diff::{label}: SUPABASE_URL / SUPABASE_SERVICE_KEY not set - "
            f"stored rows not compared; writing all {len(rows)} row(s) (fail open)")
        return list(rows), {"new": 0, "changed": 0, "restamp": 0, "unchanged_skipped": 0, "read_failed": 1}
    try:
        stored = read_stored(base, key, state=state, rows=rows, fetch=fetch)
    except Exception as exc:  # noqa: BLE001 - fail open: the old behaviour (write every row)
        log(f"::warning title=write_diff::{label}: stored rows could not be read ({type(exc).__name__}) - "
            f"writing all {len(rows)} row(s) (fail open)")
        return list(rows), {"new": 0, "changed": 0, "restamp": 0, "unchanged_skipped": 0, "read_failed": 1}
    by_key = {key_of(s, state): s for s in stored if isinstance(s, dict)}
    keep, counts = WD.split(rows, by_key, lambda r: key_of(r, state), now=now)
    log(f"Write only what changed ({label}): {len(rows)} row(s), {len(stored)} stored row(s) read; "
        f"new={counts['new']} changed={counts['changed']} restamp={counts['restamp']} "
        f"unchanged_skipped={counts['unchanged_skipped']}")
    return keep, counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", default="FL")
    ap.add_argument("--source", default="sync", help="label for the log line only")
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        rows = json.loads(Path(a.inp).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        print("write_diff_filter: rows could not be read - the caller keeps every row", file=sys.stderr)
        return 2
    rows = rows if isinstance(rows, list) else [rows]
    keep, _ = filter_rows(rows, state=a.state, label=a.source)
    Path(a.out).write_text(json.dumps(keep), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
