#!/usr/bin/env python3
"""Read-only staleness report: which active rows a successful source read has
actually observed recently (2026-10-25).

For every ACTIVE properties row (status not closed / dropped / sold /
notfound), harvesters/ledgers/health.py row_observation() decides:

  never_read  last_seen_at is NULL - no successful read ever stamped the row
  stale       last_seen_at is older than the row's ledger window
              (AUCTIONS 7 d, AVAILABLE 14 d, LIENS & CERTIFICATES 7 d)
  fresh       observed within the window

Counts only, per state x source x county (source = source_id, else
harvester_source, else properties.source). Never prints an identifier, an
address or a name, and never writes anything: a stale row is not closed
here or anywhere else on staleness alone.

    python3 scripts/stale_rows_report.py                 # every state (SUPABASE_URL / SUPABASE_SERVICE_KEY)
    python3 scripts/stale_rows_report.py --state FL
    python3 scripts/stale_rows_report.py --rows rows.json --now 2026-10-25T00:00:00Z   # offline
    python3 scripts/stale_rows_report.py --json out/public/stale-rows.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(REPO))

from harvesters.ledgers import health as LH  # noqa: E402
from harvesters.ledgers import ledger_for_row  # noqa: E402

GONE = frozenset({"closed", "dropped", "sold", "notfound"})
SELECT = "id,state,county,source,source_id,harvester_source,status,last_seen_at"
COLUMNS = ("never_read", "stale", "fresh")


def source_of(row: dict) -> str:
    return str(row.get("source_id") or row.get("harvester_source") or row.get("source") or "unknown")


def tally(rows, now: datetime) -> dict:
    """{(state, source, county): {never_read, stale, fresh, ledger}} over active rows."""
    out: dict = defaultdict(lambda: {"never_read": 0, "stale": 0, "fresh": 0, "ledger": ""})
    for r in rows:
        if str(r.get("status") or "active").strip().lower() in GONE:
            continue
        ledger = ledger_for_row(r)
        key = (str(r.get("state") or ""), source_of(r), str(r.get("county") or ""))
        state = LH.row_observation(r, now, ledger)
        cell = out[key]
        cell[state.lower()] += 1
        cell["ledger"] = ledger.value if ledger else ""
    return dict(out)


def totals(table: dict) -> dict:
    t = {c: 0 for c in COLUMNS}
    for cell in table.values():
        for c in COLUMNS:
            t[c] += cell[c]
    return t


def render(table: dict) -> str:
    lines = ["state | source | county | ledger | never_read | stale | fresh"]
    for (st, src, county) in sorted(table):
        c = table[(st, src, county)]
        lines.append(f"{st} | {src} | {county} | {c['ledger']} | {c['never_read']} | {c['stale']} | {c['fresh']}")
    t = totals(table)
    lines.append(f"TOTAL | | | | {t['never_read']} | {t['stale']} | {t['fresh']}")
    return "\n".join(lines)


def as_json(table: dict, now: datetime) -> dict:
    return {"generated_at": now.isoformat(), "windows_days": {k.value: v for k, v in LH.FRESHNESS_DAYS.items()},
            "units": [{"state": st, "source": src, "county": county, **table[(st, src, county)]}
                      for (st, src, county) in sorted(table)],
            "totals": totals(table)}


def fetch(state: str | None) -> list[dict]:
    import rest_pages as RP  # noqa: PLC0415 - only the live mode needs the network helper
    base, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set (or pass --rows)")
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    params = {"select": SELECT}
    if state:
        params["state"] = f"eq.{state}"
    return RP.read_all(base, "properties", headers, params)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state")
    ap.add_argument("--rows", help="a JSON list of properties rows (offline; no network)")
    ap.add_argument("--now", help="ISO timestamp to measure against (default: now)")
    ap.add_argument("--json", help="also write the counts to this path")
    a = ap.parse_args(argv)
    now = LH.parse_ts(a.now) if a.now else datetime.now(timezone.utc)
    if now is None:
        raise SystemExit("--now is not a timestamp")
    if a.rows:
        rows = json.loads(Path(a.rows).read_text(encoding="utf-8"))
        if a.state:
            rows = [r for r in rows if r.get("state") == a.state]
    else:
        rows = fetch(a.state)
    table = tally(rows, now)
    print(render(table))
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(as_json(table, now), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
