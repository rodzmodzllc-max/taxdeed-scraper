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
  * a new row, or a row with any changed value, is written as before;
  * read-time stamps nested inside a jsonb column (VOLATILE_PATHS:
    otc_provenance.retrieved_at, otc_provenance.source_match.read_at) never
    make a row "changed" either - they say when the row was read, which
    last_seen_at already records (2026-10-26: Louisiana's ~4,500 rows were
    rewritten every run because each read carried a new retrieved_at).

Pure functions; no request is made here. Counts only in any log line.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

FRESH_HOURS = 20
# Columns that never make a row "changed" on their own.
IGNORE = frozenset({"last_seen_at", "updated_at", "created_at", "id"})
# Nested read-time stamps, as (column, key, key ...): compared as if absent.
VOLATILE_PATHS = frozenset({("otc_provenance", "retrieved_at"), ("otc_provenance", "source_match", "read_at")})


def strip_paths(column: str, value, paths=VOLATILE_PATHS):
    """`value` (the column's value) with every path of `paths` that starts at
    `column` removed. Never mutates its input."""
    tails = [p[1:] for p in paths if p and p[0] == column and len(p) > 1]
    if not tails or not isinstance(value, dict):
        return value

    def drop(v, tail):
        if not isinstance(v, dict):
            return v
        if len(tail) == 1:
            return {k: x for k, x in v.items() if k != tail[0]}
        if tail[0] not in v:
            return v
        return {**v, tail[0]: drop(v[tail[0]], tail[1:])}

    for tail in tails:
        value = drop(value, tail)
    return value


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


def unchanged(row: dict, stored: dict | None, ignore=IGNORE, ignore_paths=VOLATILE_PATHS) -> bool:
    """True when every column `row` would write already holds that value
    (`ignore` columns skipped; `ignore_paths` nested keys compared as absent)."""
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
        elif not same(strip_paths(k, v, ignore_paths), strip_paths(k, stored.get(k), ignore_paths)):
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


# ---------------------------------------------------------------------------
# Paced re-stamps (2026-10-27).
#
# Measured: Michigan's sync re-stamped ~32,000 unchanged rows in ~15 minutes
# (04:20-04:36 UTC) because a 'restamp' row went out as a FULL-ROW upsert -
# every column of the row, 200 rows per INSERT ... ON CONFLICT DO UPDATE,
# back to back. A re-stamp changes one column. It is now sent as one small
# PATCH {"last_seen_at": <this read>} per RESTAMP_BATCH ids (`id=in.(...)`),
# guarded so a row stamped at or after this read is never moved backwards,
# with RESTAMP_PAUSE_SECONDS between batches so other writers and customer
# reads get the database in between. No index covers last_seen_at or
# updated_at, so the update can stay a HOT update.
#
# Why NOT spread re-stamps over the day by an id-hash bucket: the states are
# read twice a day (03:37 / 11:37 UTC) and GitHub drops scheduled runs (it
# dropped both early runs on 2026-10-27). A bucketed row would be re-stamped
# only on some reads, so one dropped run pushes it past 24 h and toward the
# 36 h rules (the frontend's "not on the county's current sale list", the
# daily verification freshness). Every read that lists a row still re-stamps
# it once FRESH_HOURS have passed; only the shape and pace of the write changed.

RESTAMP_BATCH = 200          # ~7.5 KB of uuids per URL
RESTAMP_PAUSE_SECONDS = 0.5


def split_restamps(rows: list[dict], stored_by_key: dict, key, now: datetime | None = None,
                   hours: float = FRESH_HOURS) -> tuple[list[dict], list, dict]:
    """(rows to upsert, stored ids to re-stamp only, counts). Like `split`,
    but a row whose only due write is the re-stamp is returned as its stored
    id instead of a full row. A stored row without an id stays a full row."""
    counts = {"new": 0, "changed": 0, "restamp": 0, "unchanged_skipped": 0}
    out, ids = [], []
    for r in rows:
        stored = stored_by_key.get(key(r))
        why = needs_write(r, stored, now, hours)
        if why is None:
            counts["unchanged_skipped"] += 1
            continue
        counts[why] += 1
        if why == "restamp" and stored.get("id") not in (None, ""):
            ids.append(stored["id"])
        else:
            out.append(r)
    return out, ids, counts


def restamp_queries(ids: list, seen_at: str, size: int = RESTAMP_BATCH) -> list[str]:
    """One PostgREST query string per batch of ids: the ids, and only rows
    whose last_seen_at is missing or older than `seen_at`."""
    from urllib.parse import quote
    if size < 1:
        raise ValueError("size must be >= 1")
    guard = f"or=(last_seen_at.is.null,last_seen_at.lt.{quote(str(seen_at), safe='')})"
    unique = list(dict.fromkeys(str(i) for i in ids))
    return [f"id=in.({','.join(unique[i:i + size])})&{guard}" for i in range(0, len(unique), size)]


def run_restamps(ids: list, seen_at: str, patch, *, size: int = RESTAMP_BATCH,
                 pause: float = RESTAMP_PAUSE_SECONDS, sleep=None) -> tuple[int, int]:
    """(requests sent, batches failed). `patch(query, body)` sends one PATCH;
    an exception fails that batch only (its rows keep their last_seen_at and
    the next read re-stamps them). Pauses between batches."""
    import time
    sleep = sleep or time.sleep
    body = {"last_seen_at": seen_at}
    sent = failed = 0
    for n, query in enumerate(restamp_queries(ids, seen_at, size)):
        if n and pause > 0:
            sleep(pause)
        try:
            patch(query, body)
            sent += 1
        except Exception as exc:  # noqa: BLE001 - one batch failing stamps nothing for it
            failed += 1
            print(f"::warning title=restamp::a re-stamp batch failed ({type(exc).__name__})")
    return sent, failed
