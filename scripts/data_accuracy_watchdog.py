#!/usr/bin/env python3
"""Daily data-accuracy watchdog (2026-11-08).

Runs once a day after the harvests (`.github/workflows/data-accuracy-watchdog.yml`)
and checks the data pipe itself, not one source. Read-only: it never writes to
the database, never closes or re-statuses a row.

Per state x ledger x source (source = source_id, else harvester_source, else
properties.source), over ACTIVE rows (status not closed / dropped / sold /
notfound):

  active            rows on file
  not_seen_7d       last_seen_at NULL or older than 7 days
  missing_county    county blank
  past_sale         auction rows whose sale_date is before today
  change            active count vs the previous run (cache file)

Whole-population checks:

  dup_case_same_source    two active rows of ONE source on (state, county,
                          case_no) - the sync's identity; HARD
  dup_case_cross_source   the same (state, county, case_no) from two sources
                          (e.g. a Texas vendor listing and an auction list);
                          reported, not hard - two sources may list one case
  dup_parcel              two active rows of one source and ledger on the
                          shared property key (harvesters/ledgers/records.py
                          property_key: normalized parcel; the CAD account for
                          Texas tax-suit sources). HARD for Auctions and
                          Available; Liens & Certificates are reported only,
                          since one parcel can carry several certificates
  past_dated_auctions     active auction rows more than PAST_GRACE_DAYS past
                          their sale date; HARD above PAST_AUCTION_MAX
  source_drop             a source whose active count fell by more than
                          DROP_RATIO since the previous run (previous count at
                          least DROP_MIN_ROWS); HARD
  failing_units           county_source_registry units whose last attempt was
                          FAILED / INCOMPLETE and whose last success is older
                          than 48 h (or never); reported

Output is counts only, never a parcel, case number, address or name: the job
log and out/public/data-accuracy.json. Exit 1 only on a HARD break, so the run
shows red; everything else is printed and the run stays green.

    python3 scripts/data_accuracy_watchdog.py                       # SUPABASE_URL / SUPABASE_SERVICE_KEY
    python3 scripts/data_accuracy_watchdog.py --rows rows.json --registry reg.json --now 2026-11-08T15:41:00Z
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(REPO))

import rest_pages  # noqa: E402
from harvesters.ledgers import ledger_for_row  # noqa: E402
from harvesters.ledgers.records import property_key  # noqa: E402

GONE = ("closed", "dropped", "sold", "notfound")
SELECT = "id,state,county,case_no,parcel,source,source_id,harvester_source,ledger_type,status,sale_date,last_seen_at"
REG_SELECT = "id,state,county,source_id,last_attempt_at,last_attempt_status,last_success_at,consecutive_failures"
CACHE_PATH = REPO / "out" / ".harvest_cache" / "data-accuracy-counts.json"
JSON_OUT = REPO / "out" / "public" / "data-accuracy.json"

NOT_SEEN_DAYS = 7
PAST_GRACE_DAYS = int(os.environ.get("WATCHDOG_PAST_GRACE_DAYS", "3"))
PAST_AUCTION_MAX = int(os.environ.get("WATCHDOG_PAST_AUCTION_MAX", "25"))
DROP_RATIO = 0.5
DROP_MIN_ROWS = int(os.environ.get("WATCHDOG_DROP_MIN_ROWS", "20"))
FAILING_HOURS = 48
BAD_STATUSES = frozenset({"FAILED", "INCOMPLETE"})


# ---------------------------------------------------------------- helpers

def source_of(row: dict) -> str:
    return str(row.get("source_id") or row.get("harvester_source") or row.get("source") or "unknown")


def ledger_of(row: dict) -> str:
    led = ledger_for_row(row)
    return led.value if led else "UNCLASSIFIED"


def is_active(row: dict) -> bool:
    return str(row.get("status") or "active").strip().lower() not in GONE


def parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def norm_case(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().upper()


def unit_name(state: str, ledger: str, source: str) -> str:
    return f"{state}|{ledger}|{source}"


# ---------------------------------------------------------------- checks

def tally(rows, now: datetime) -> dict:
    """{unit: {active, not_seen_7d, missing_county, past_sale}} over active rows."""
    out: dict = defaultdict(lambda: {"active": 0, "not_seen_7d": 0, "missing_county": 0, "past_sale": 0})
    cutoff = now - timedelta(days=NOT_SEEN_DAYS)
    today = now.date()
    for r in rows:
        if not is_active(r):
            continue
        cell = out[unit_name(str(r.get("state") or ""), ledger_of(r), source_of(r))]
        cell["active"] += 1
        seen = parse_ts(r.get("last_seen_at"))
        if seen is None or seen < cutoff:
            cell["not_seen_7d"] += 1
        if not str(r.get("county") or "").strip():
            cell["missing_county"] += 1
        sale = parse_date(r.get("sale_date"))
        if r.get("source") == "auction" and sale is not None and sale < today:
            cell["past_sale"] += 1
    return dict(out)


def duplicates(rows) -> dict:
    """Duplicate groups (counts only), per state x source."""
    case_groups: dict = defaultdict(set)      # (state, county, case) -> sources
    case_same: dict = defaultdict(int)        # (state, source, county, case) -> rows
    parcel_groups: dict = defaultdict(int)    # (ledger, source, key) -> rows
    for r in rows:
        if not is_active(r):
            continue
        state = str(r.get("state") or "").upper()
        county = str(r.get("county") or "").strip().casefold()
        src = source_of(r)
        case = norm_case(r.get("case_no"))
        if case:
            case_groups[(state, county, case)].add(src)
            case_same[(state, src, county, case)] += 1
        key = property_key(r)
        if key is not None:
            parcel_groups[(ledger_of(r), src, key)] += 1

    same = defaultdict(int)
    for (state, src, _c, _k), n in case_same.items():
        if n > 1:
            same[f"{state}|{src}"] += 1
    cross = defaultdict(int)
    for (state, _c, _k), srcs in case_groups.items():
        if len(srcs) > 1:
            cross[f"{state}|{'+'.join(sorted(srcs))}"] += 1
    parcel_hard = defaultdict(int)
    parcel_info = defaultdict(int)
    for (ledger, src, key), n in parcel_groups.items():
        if n > 1:
            name = f"{key[0]}|{ledger}|{src}"
            if ledger == "LIENS_CERTIFICATES":
                parcel_info[name] += 1
            else:
                parcel_hard[name] += 1
    return {"dup_case_same_source": dict(same), "dup_case_cross_source": dict(cross),
            "dup_parcel_hard": dict(parcel_hard), "dup_parcel_certificates": dict(parcel_info)}


def past_dated_auctions(rows, now: datetime, grace_days: int = PAST_GRACE_DAYS) -> dict:
    """Active auction rows more than `grace_days` past their sale date, per state|source."""
    limit = now.date() - timedelta(days=grace_days)
    out: dict = defaultdict(int)
    for r in rows:
        if not is_active(r) or r.get("source") != "auction":
            continue
        sale = parse_date(r.get("sale_date"))
        if sale is not None and sale < limit:
            out[f"{str(r.get('state') or '')}|{source_of(r)}"] += 1
    return dict(out)


def changes(current: dict, previous: dict | None) -> tuple[dict, list[dict]]:
    """Per-source active-count change vs the previous run, and the sources that
    fell by more than DROP_RATIO. Sources are state|source (ledgers summed)."""
    cur = defaultdict(int)
    for unit, cell in current.items():
        state, _ledger, src = unit.split("|", 2)
        cur[f"{state}|{src}"] += cell["active"]
    prev = (previous or {}).get("sources") or {}
    delta = {}
    drops = []
    for name in sorted(set(cur) | set(prev)):
        now_n, before = cur.get(name, 0), prev.get(name)
        if before is None:
            delta[name] = {"previous": None, "current": now_n}
            continue
        delta[name] = {"previous": before, "current": now_n, "change": now_n - before}
        if before >= DROP_MIN_ROWS and now_n < before * (1 - DROP_RATIO):
            drops.append({"source": name, "previous": before, "current": now_n})
    return delta, drops


def failing_units(registry, now: datetime) -> dict:
    """Registry units failing for at least FAILING_HOURS, counted per state|source|status."""
    limit = now - timedelta(hours=FAILING_HOURS)
    out: dict = defaultdict(int)
    for u in registry:
        status = str(u.get("last_attempt_status") or "").upper()
        if status not in BAD_STATUSES or not u.get("last_attempt_at"):
            continue
        ok = parse_ts(u.get("last_success_at"))
        if ok is not None and ok >= limit:
            continue
        out[f"{u.get('state') or ''}|{u.get('source_id') or ''}|{status}"] += 1
    return dict(out)


def evaluate(rows, registry, previous: dict | None, now: datetime) -> dict:
    """The whole report plus the hard breaks. Pure: no I/O."""
    units = tally(rows, now)
    dups = duplicates(rows)
    past = past_dated_auctions(rows, now)
    delta, drops = changes(units, previous)
    failing = failing_units(registry, now)
    hard = []
    if dups["dup_case_same_source"]:
        hard.append(f"duplicate (state, county, case_no) within one source: {sum(dups['dup_case_same_source'].values())} groups")
    if dups["dup_parcel_hard"]:
        hard.append(f"duplicate property key within one source (Auctions / Available): {sum(dups['dup_parcel_hard'].values())} groups")
    past_total = sum(past.values())
    if past_total > PAST_AUCTION_MAX:
        hard.append(f"{past_total} active auctions more than {PAST_GRACE_DAYS} days past their sale date (max {PAST_AUCTION_MAX})")
    for d in drops:
        hard.append(f"source {d['source']} fell from {d['previous']} to {d['current']} active rows")
    return {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "thresholds": {"not_seen_days": NOT_SEEN_DAYS, "past_grace_days": PAST_GRACE_DAYS,
                       "past_auction_max": PAST_AUCTION_MAX, "drop_ratio": DROP_RATIO,
                       "drop_min_rows": DROP_MIN_ROWS, "failing_hours": FAILING_HOURS},
        "totals": {k: sum(c[k] for c in units.values()) for k in ("active", "not_seen_7d", "missing_county", "past_sale")},
        "units": dict(sorted(units.items())),
        "duplicates": dups,
        "past_dated_auctions": dict(sorted(past.items())),
        "change_vs_previous": delta,
        "source_drops": drops,
        "failing_units": dict(sorted(failing.items())),
        "hard_breaks": hard,
    }


def snapshot(report: dict) -> dict:
    """What the next run compares against (counts only)."""
    return {"generated_at": report["generated_at"],
            "sources": {k: v["current"] for k, v in report["change_vs_previous"].items() if v["current"]}}


def render(report: dict) -> str:
    lines = ["state | ledger | source | active | not_seen_7d | missing_county | past_sale"]
    for unit, c in report["units"].items():
        lines.append(f"{unit.replace('|', ' | ')} | {c['active']} | {c['not_seen_7d']} | {c['missing_county']} | {c['past_sale']}")
    t = report["totals"]
    lines.append(f"TOTAL active={t['active']} not_seen_7d={t['not_seen_7d']} missing_county={t['missing_county']} past_sale={t['past_sale']}")
    for title, table in (("duplicate case within one source", report["duplicates"]["dup_case_same_source"]),
                         ("same case from several sources (info)", report["duplicates"]["dup_case_cross_source"]),
                         ("duplicate property key, Auctions / Available", report["duplicates"]["dup_parcel_hard"]),
                         ("several certificates per parcel (info)", report["duplicates"]["dup_parcel_certificates"]),
                         ("auctions past their sale date", report["past_dated_auctions"]),
                         ("registry units FAILED / INCOMPLETE >= 48 h", report["failing_units"])):
        lines.append(f"-- {title}: {sum(table.values())}")
        for k, n in sorted(table.items()):
            lines.append(f"   {k}: {n}")
    moved = {k: v for k, v in report["change_vs_previous"].items() if v.get("change")}
    lines.append(f"-- sources whose active count changed since the previous run: {len(moved)}")
    for k, v in moved.items():
        lines.append(f"   {k}: {v['previous']} -> {v['current']} ({v['change']:+d})")
    lines.append(f"-- HARD breaks: {len(report['hard_breaks'])}")
    lines.extend(f"   {h}" for h in report["hard_breaks"])
    return "\n".join(lines)


# ---------------------------------------------------------------- I/O

def production_states() -> list[str]:
    from harvesters.governance.states import PRODUCTION_STATES  # noqa: PLC0415
    return sorted(PRODUCTION_STATES)


def fetch_live(base: str, key: str) -> tuple[list, list]:
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    active = f"(status.is.null,status.not.in.({','.join(GONE)}))"
    rows: list = []
    for st in production_states():
        rows.extend(rest_pages.read_all(base, "properties", headers,
                                        {"select": SELECT, "state": f"eq.{st}", "or": active}))
    registry = rest_pages.read_all(base, "county_source_registry", headers, {"select": REG_SELECT})
    return rows, registry


def load_json(path) -> object:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rows", help="offline: JSON list of properties rows")
    ap.add_argument("--registry", help="offline: JSON list of county_source_registry rows")
    ap.add_argument("--now", help="ISO timestamp (default: now, UTC)")
    ap.add_argument("--cache", default=str(CACHE_PATH))
    ap.add_argument("--json", default=str(JSON_OUT))
    ap.add_argument("--no-cache-write", action="store_true")
    args = ap.parse_args(argv)

    now = parse_ts(args.now) if args.now else datetime.now(timezone.utc)
    if args.rows:
        rows = load_json(args.rows) or []
        registry = load_json(args.registry) or [] if args.registry else []
    else:
        base, key = os.environ.get("SUPABASE_URL", "").rstrip("/"), os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not base or not key:
            print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set (or pass --rows)", file=sys.stderr)
            return 2
        rows, registry = fetch_live(base, key)

    previous = load_json(args.cache)
    report = evaluate(rows, registry, previous if isinstance(previous, dict) else None, now)
    print(render(report))

    out = Path(args.json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if not args.no_cache_write:
        cache = Path(args.cache)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(snapshot(report), indent=2, sort_keys=True) + "\n")
    return 1 if report["hard_breaks"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
