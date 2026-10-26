"""Write only what changed (2026-10-26).

Production overload 2026-10-26 ~19:40-19:57 UTC: one harvest run rewrote
~15,770 `properties` rows in ten minutes - every harvested row was upserted
again whether or not anything in it had changed, and `last_seen_at` was
stamped on every row read even when it had been stamped an hour earlier.
Each of those writes is a new tuple (properties_touch bumps updated_at),
dead tuples piled up (n_dead_tup 18,070), the planner's statistics went
stale and customer reads of `get_properties()` crossed the statement
timeout.

This module is the one rule every sync uses before it writes:

  * a row whose stored copy already holds the same values is NOT written -
    `last_seen_at` aside, and `field_provenance` compared without the
    per-entry `recorded_at` stamps (they change every run by design);
  * such an unchanged row is re-stamped (written once) only when its stored
    `last_seen_at` is missing or older than FRESH_HOURS - so freshness is
    still recorded at least once a day for every row a read lists (the
    Dashboard's stale rule is 36 h), and a second run the same day writes
    nothing for it;
  * a new row, or a row with any changed value, is written as before.

Pure functions; no request is made here. Counts only in any log line.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

FRESH_HOURS = 20
# Columns that never make a row "changed" on their own.
IGNORE = frozenset({"last_seen_at", "updated_at", "created_at", "id"})


def _ts(value):
    if not isinstance(value, str) or len(value) < 19 or value[4:5] != "-" or value[10:11] not in ("T", " "):
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _num(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            f = float(value.strip())
        except ValueError:
            return None
        return f if math.isfinite(f) else None
    return None


def strip_recorded(prov):
    """field_provenance without the per-entry recorded_at stamps."""
    if not isinstance(prov, dict):
        return prov
    return {k: ({kk: vv for kk, vv in v.items() if kk != "recorded_at"} if isinstance(v, dict) else v)
            for k, v in prov.items()}


def same(a, b) -> bool:
    """Value equality as Postgres stores it: numbers by value (12.5 == "12.50"),
    timestamps by instant, '' and None distinct, dicts / lists element-wise."""
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b or (isinstance(a, bool) and isinstance(b, bool) and a == b)
    if a == b:
        return True
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None and not (isinstance(a, str) and isinstance(b, str)):
        return na == nb
    ta, tb = _ts(a), _ts(b)
    if ta is not None and tb is not None:
        return ta == tb
    return False


def unchanged(row: dict, stored: dict | None, ignore=IGNORE) -> bool:
    """True when every column `row` would write already holds that value."""
    if stored is None:
        return False
    for k, v in row.items():
        if k in ignore:
            continue
        if k not in stored:
            return False
        if k == "field_provenance":
            if not same(strip_recorded(v), strip_recorded(stored.get(k))):
                return False
        elif not same(v, stored.get(k)):
            return False
    return True


def fresh(last_seen, now: datetime | None = None, hours: float = FRESH_HOURS) -> bool:
    t = _ts(last_seen) if isinstance(last_seen, str) else last_seen
    if t is None:
        return False
    now = now or datetime.now(timezone.utc)
    return now - t < timedelta(hours=hours)


def stale_before(now: datetime | None = None, hours: float = FRESH_HOURS) -> str:
    """The ISO instant before which a stored last_seen_at is due a re-stamp."""
    now = now or datetime.now(timezone.utc)
    return (now - timedelta(hours=hours)).replace(microsecond=0).isoformat()


def needs_write(row: dict, stored: dict | None, now: datetime | None = None, hours: float = FRESH_HOURS) -> str | None:
    """None (skip), or why the row is written: 'new' / 'changed' / 'restamp'."""
    if stored is None:
        return "new"
    if not unchanged(row, stored):
        return "changed"
    if "last_seen_at" in row and not fresh(stored.get("last_seen_at"), now, hours):
        return "restamp"
    return None


def split(rows: list[dict], stored_by_key: dict, key, now: datetime | None = None,
          hours: float = FRESH_HOURS) -> tuple[list[dict], dict]:
    """(rows to write, counts). `key(row)` -> the identity stored_by_key uses."""
    counts = {"new": 0, "changed": 0, "restamp": 0, "unchanged_skipped": 0}
    out = []
    for r in rows:
        why = needs_write(r, stored_by_key.get(key(r)), now, hours)
        if why is None:
            counts["unchanged_skipped"] += 1
            continue
        counts[why] += 1
        out.append(r)
    return out, counts
