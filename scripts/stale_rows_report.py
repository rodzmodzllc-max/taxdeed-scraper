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
    python3 scripts/stale_rows_report.py --daily-laft --state FL --status out/harvest_laft_status.json
        # daily verification: exit 1 when an active FL Lands Available row was
        # not seen on its county list in the last 36 h, per county with the reason
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


# ---------------------------------------------------------------------------
# Daily verification of Florida AVAILABLE (laft) rows (2026-10-26)
# ---------------------------------------------------------------------------
# The owner's rule: every Florida Lands Available row we display must have
# been seen on its county's current list within the last day. This check is
# the laft job's last step: per county, how many active rows were NOT seen in
# the last DAILY_WINDOW_HOURS, and why - read from today's status file
# (out/harvest_laft_status.json), never guessed. Counts and county names
# only. It FAILS (exit 1, one ::error:: line per county) whenever any row is
# unverified; it never writes and never closes anything.
DAILY_WINDOW_HOURS = 36
_TRANSPORT_PREFIXES = ("TRANSPORT_", "PROXY_", "ACCESS_")
# Worst first: the reason a county gets when its sources disagree.
_STATUS_RANK = {"FAILED": 0, "INCOMPLETE": 1, "EMPTY": 2, "COMPLETE": 3}


def county_read_reason(entries: list[dict]) -> tuple[str, str]:
    """(reason code, detail) for a county from its status entries today."""
    if not entries:
        return "NOT_READ_TODAY", "no harvester recorded a read of this county in today's run"
    worst = min(entries, key=lambda e: _STATUS_RANK.get(str(e.get("status")), -1))
    status = str(worst.get("status") or "")
    cat = str(worst.get("error_category") or "")
    src = str(worst.get("source_id") or worst.get("harvester") or "")
    if status == "FAILED":
        code = "SOURCE_UNAVAILABLE" if cat.startswith(_TRANSPORT_PREFIXES) else "READ_FAILED"
        return code, f"{src}: FAILED {cat}".strip()
    if status == "INCOMPLETE":
        return "READ_INCOMPLETE", f"{src}: INCOMPLETE {cat}".strip()
    if status in ("COMPLETE", "EMPTY"):
        # The list was read in full and the row was not on it: the lifecycle
        # closes such rows in the same job, so a survivor here is a bug.
        return "READ_BUT_NOT_ON_LIST", f"{src}: {status} - row absent from the list it was read from"
    return "UNKNOWN_STATUS", f"{src}: {status or 'no status'}"


def daily_laft_check(rows, status_entries, now: datetime, *, state: str = "FL",
                     window_hours: int = DAILY_WINDOW_HOURS) -> dict:
    """{county: {active, seen, unverified, never_read, reason, detail}} over
    active `state` laft rows, plus the counties' totals."""
    from datetime import timedelta  # noqa: PLC0415
    cutoff = now - timedelta(hours=window_hours)
    by_county: dict = {}
    for r in rows:
        if r.get("state") != state or r.get("source") != "laft":
            continue
        if str(r.get("status") or "active").strip().lower() in GONE:
            continue
        county = str(r.get("county") or "")
        cell = by_county.setdefault(county, {"active": 0, "seen": 0, "unverified": 0, "never_read": 0,
                                             "reason": "", "detail": ""})
        cell["active"] += 1
        seen = LH.parse_ts(r.get("last_seen_at"))
        if seen is not None and seen >= cutoff:
            cell["seen"] += 1
        else:
            cell["unverified"] += 1
            if seen is None:
                cell["never_read"] += 1
    entries_by_county: dict = defaultdict(list)
    for e in status_entries or []:
        if isinstance(e, dict) and str(e.get("state") or "FL") == state:
            entries_by_county[str(e.get("county") or "")].append(e)
    for county, cell in by_county.items():
        if cell["unverified"]:
            cell["reason"], cell["detail"] = county_read_reason(entries_by_county.get(county, []))
    return by_county


def render_daily(check: dict, window_hours: int = DAILY_WINDOW_HOURS) -> tuple[str, list[str]]:
    """(table text, ::error:: lines)."""
    lines = [f"Florida Lands Available - daily verification (seen on the county list in the last {window_hours} h)",
             "county | active | seen | NOT seen | never read | reason"]
    errors: list[str] = []
    for county in sorted(check):
        c = check[county]
        lines.append(f"{county} | {c['active']} | {c['seen']} | {c['unverified']} | {c['never_read']} | "
                     f"{c['reason'] or 'verified'}{(' - ' + c['detail']) if c['detail'] else ''}")
        if c["unverified"]:
            errors.append(f"::error title=FL Available not verified today::{county}: {c['unverified']} of "
                          f"{c['active']} active row(s) not seen on the county list in {window_hours} h - "
                          f"{c['reason']} ({c['detail']})")
    active = sum(c["active"] for c in check.values())
    unverified = sum(c["unverified"] for c in check.values())
    by_reason: dict = defaultdict(list)
    for county, c in check.items():
        if c["unverified"]:
            by_reason[c["reason"]].append(county)
    lines.append(f"TOTAL | {active} | {active - unverified} | {unverified} | "
                 f"{sum(c['never_read'] for c in check.values())} |")
    for reason in sorted(by_reason):
        lines.append(f"  {reason}: {', '.join(sorted(by_reason[reason]))}")
    lines.append("RESULT: " + ("PASS - every active Florida Lands Available row was seen today"
                               if not unverified else
                               f"FAIL - {unverified} of {active} active row(s) in "
                               f"{sum(1 for c in check.values() if c['unverified'])} county(ies) not verified today"))
    return "\n".join(lines), errors


def fetch(state: str | None, source: str | None = None) -> list[dict]:
    import rest_pages as RP  # noqa: PLC0415 - only the live mode needs the network helper
    base, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set (or pass --rows)")
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    params = {"select": SELECT}
    if state:
        params["state"] = f"eq.{state}"
    if source:
        params["source"] = f"eq.{source}"
    return RP.read_all(base, "properties", headers, params)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state")
    ap.add_argument("--rows", help="a JSON list of properties rows (offline; no network)")
    ap.add_argument("--now", help="ISO timestamp to measure against (default: now)")
    ap.add_argument("--json", help="also write the counts to this path")
    ap.add_argument("--daily-laft", action="store_true",
                    help="daily verification of the state's Lands Available rows: exit 1 when any active row "
                         f"was not seen in the last {DAILY_WINDOW_HOURS} h (needs --state, default FL)")
    ap.add_argument("--status", help="today's laft status file (with --daily-laft), e.g. out/harvest_laft_status.json")
    a = ap.parse_args(argv)
    now = LH.parse_ts(a.now) if a.now else datetime.now(timezone.utc)
    if now is None:
        raise SystemExit("--now is not a timestamp")
    if a.rows:
        rows = json.loads(Path(a.rows).read_text(encoding="utf-8"))
        if a.state:
            rows = [r for r in rows if r.get("state") == a.state]
    else:
        rows = fetch(a.state or ("FL" if a.daily_laft else None), "laft" if a.daily_laft else None)
    if a.daily_laft:
        statuses: list = []
        if a.status:
            try:
                data = json.loads(Path(a.status).read_text(encoding="utf-8"))
                statuses = data if isinstance(data, list) else []
            except (OSError, ValueError):
                print(f"status file {a.status} unreadable - every unverified county reads NOT_READ_TODAY")
        check = daily_laft_check(rows, statuses, now, state=a.state or "FL")
        text, errors = render_daily(check)
        print(text)
        for line in errors:
            print(line)
        if a.json:
            Path(a.json).parent.mkdir(parents=True, exist_ok=True)
            Path(a.json).write_text(json.dumps({"generated_at": now.isoformat(), "window_hours": DAILY_WINDOW_HOURS,
                                                "counties": check}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 1 if errors else 0
    table = tally(rows, now)
    print(render(table))
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(as_json(table, now), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
