"""A bounded, fair, resumable work queue for the enrichment steps (2026-10-10).

Measured problem (read-only production, 2026-10-10): the address geocoder read
its 250-row budget in physical order and never recorded a row it could not
match. 248 address-context rows that keep failing (FL certificates /
auctions, SC, CO, TX, MI) filled 248 of the 250 slots every run, so the 9,759
Missouri rows behind them got about two attempts a run. The FEMA flood step had
the mirror-image problem: a per-county cap of 40 with no hand-on of unused
budget, so one-county Tennessee would have needed ~51 runs.

This module is the shared mechanism:

* `env_limit()` - one validated integer setting: default, 1..maximum, a clear
  error otherwise (never an unbounded run).
* `plan_slices()` - pass 1 gives every unit (state, county) up to `per_unit`
  rows before any unit gets more; pass 2 hands what pass 1 left unused, round
  robin and `per_unit` at a time, to units that still have a backlog.
  Total <= budget; no unit beyond its backlog.
* `rotate()` - the unit order starts where the previous run's pass 1 stopped,
  so a budget smaller than units x per_unit still reaches every unit in turn.
* `Checkpoint` - a small JSON file (kept in the job's existing
  out/.harvest_cache, which actions/cache restores and saves) holding, per
  unit, the last row key processed and the next unit to serve. Written
  atomically after every row, so an interrupted run resumes after the last
  row it finished - never skipping, never repeating.
* `take_after()` - a unit's next rows after its cursor, wrapping to the start
  only once the unit's backlog has been walked: a row that did not match is
  retried after one full pass of its unit, never at the head of every run.

Nothing here reaches the network.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def env_limit(name: str, default: int, maximum: int, env=None) -> int:
    """A positive integer setting, `default` when unset. Raises ValueError for
    a non-integer, a value below 1 or above `maximum`."""
    env = os.environ if env is None else env
    raw = str(env.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not an integer") from None
    if value < 1 or value > maximum:
        raise ValueError(f"{name}={value} is outside 1..{maximum}")
    return value


def plan_slices(units, budget: int, per_unit: int) -> list:
    """[(unit, limit, outstanding)] for one run. `units` is [(unit, outstanding)]
    in the order to serve. Pure."""
    give = []
    left = budget
    for _unit, outstanding in units:
        n = max(0, min(per_unit, outstanding or 0, left))
        give.append(n)
        left -= n
    # Pass 2: the leftover goes round-robin, per_unit at a time, to units
    # that still have a backlog - never all of it to the first one in line.
    while left > 0:
        moved = 0
        for i, (_unit, outstanding) in enumerate(units):
            if left <= 0:
                break
            extra = max(0, min(per_unit, (outstanding or 0) - give[i], left))
            give[i] += extra
            left -= extra
            moved += extra
        if not moved:
            break
    return [(unit, n, outstanding) for (unit, outstanding), n in zip(units, give) if n > 0]


def unit_key(unit) -> str:
    state, county = unit
    return f"{state or ''}|{county or ''}"


def rotate(units: list, start_after: str | None) -> list:
    """`units` (sorted) starting with the first unit whose key is greater than
    `start_after` - the unit after the last one the previous run served."""
    if not start_after:
        return list(units)
    keys = [unit_key(u) for u, _ in units]
    for i, k in enumerate(keys):
        if k > start_after:
            return list(units[i:]) + list(units[:i])
    return list(units)


def take_after(keys: list, cursor, n: int) -> list:
    """The next `n` keys of a unit's sorted `keys` after `cursor`, wrapping to
    the start once (never returning a key twice)."""
    if n <= 0 or not keys:
        return []
    if cursor is None:
        return keys[:n]
    after = [k for k in keys if k > cursor]
    before = [k for k in keys if k <= cursor]
    return (after + before)[:n]


class Checkpoint:
    """{"units": {unit_key: last row key}, "next_unit": unit_key}. A missing,
    unreadable or malformed file is an empty checkpoint (start from the top) -
    never an error that stops enrichment."""

    def __init__(self, path):
        self.path = Path(path) if path else None
        self.data = {"units": {}, "next_unit": None}
        if self.path and self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("units"), dict):
                    self.data = {"units": {str(k): v for k, v in raw["units"].items()},
                                 "next_unit": raw.get("next_unit")}
            except (OSError, ValueError):
                pass

    def cursor(self, unit):
        return self.data["units"].get(unit_key(unit))

    def advance(self, unit, row_key) -> None:
        self.data["units"][unit_key(unit)] = row_key
        self.save()

    def set_next_unit(self, key) -> None:
        self.data["next_unit"] = key
        self.save()

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.path)
