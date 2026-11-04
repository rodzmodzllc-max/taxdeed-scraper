"""Shared work-unit helpers for the coordinate-keyed backfills (FEMA flood
hazard, NAIP aerial imagery).

A unit is (state, county), never a bare county name: county names repeat
across states (York SC / York ..., Douglas CO / Douglas ..., Albany WY /
Albany ...), and a name-only unit both merged two states' backlogs into one
capped slice and let one state's rows starve another's. `ENRICH_STATE`
(comma-separated postal codes) narrows a run to some states - the manual
backfill dispatch uses it; the scheduled steps leave it unset.
"""
from __future__ import annotations

import os
import random
from collections import Counter
from typing import Iterable


def state_filter() -> list[str]:
    raw = os.environ.get("ENRICH_STATE", "")
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def state_param(states: list[str]) -> dict:
    """PostgREST filter for the selected states (none = every state).

    One state is sent as `eq.`, never `in.(XX)` (audit B26, 2026-10-29):
    PostgREST renders `in.` as `state = ANY('{XX}')`, for which the planner
    walked the primary key in id order and filtered every row - 6.8 s for
    Missouri's first flood page, at the statement timeout (HTTP 500) - while
    `state = 'XX'` uses properties_state_id_idx (44 ms)."""
    if not states:
        return {}
    if len(states) == 1:
        return {"state": f"eq.{states[0]}"}
    return {"state": "in.(" + ",".join(states) + ")"}


def outstanding_units(rows: Iterable[dict], *, shuffle: bool = True) -> list[tuple[tuple[str, str], int]]:
    """((state, county), outstanding rows) for every unit with work left."""
    counts = Counter((r.get("state") or "", r.get("county")) for r in rows if r.get("county"))
    units = sorted(counts)
    if shuffle:
        random.shuffle(units)
    return [(u, counts[u]) for u in units]


def unit_params(unit: tuple[str, str]) -> dict:
    state, county = unit
    params = {"county": f"eq.{county}"}
    if state:
        params["state"] = f"eq.{state}"
    return params


def label(unit: tuple[str, str]) -> str:
    state, county = unit
    return f"{county}, {state}" if state else county


# PostgREST answers at most API_MAX_ROWS rows per request (the project's
# max-rows setting), whatever `limit` asks for: a larger read is paged.
API_MAX_ROWS = 1000


def get_paged(get, url: str, params: dict, limit: int, *, page: int = API_MAX_ROWS) -> list:
    """Up to `limit` rows from a PostgREST read, in pages of `page` rows,
    keyset-paged by id (`order=id.asc`, `id=gt.<last id>`). `get(url,
    params)` returns the parsed JSON list. A short page ends the read.

    2026-10-26: this read used `offset`, which makes Postgres walk and
    discard every skipped row - at offset 18,802 in Detroit's 30,549 rows
    the request hit the statement timeout (HTTP 500) and failed the deeds
    job (scheduled run 376). Keyset pages cost the same at any depth.
    `id` is always selected (it is the page cursor); an `offset` param is
    ignored. `params['id']` (e.g. `gt.<uuid>` / `lt.<uuid>`) bounds the
    first page."""
    params = {k: v for k, v in params.items() if k != "offset"}
    select = params.get("select")
    if select and "id" not in [c.strip() for c in select.split(",")]:
        params["select"] = select + ",id"
    params["order"] = "id.asc"
    bound = str(params.get("id") or "")
    upper = bound if bound.startswith(("lt.", "lte.")) else None
    if upper:
        params.pop("id")
        params["and"] = f"(id.{upper})"
    out: list = []
    cursor = None
    while len(out) < limit:
        want = min(page, limit - len(out))
        q = dict(params, limit=str(want))
        if cursor is not None:
            q["id"] = f"gt.{cursor}"
        rows = get(url, q)
        rows = rows if isinstance(rows, list) else []
        out += rows
        if len(rows) < want or not rows:
            break
        cursor = rows[-1].get("id") if isinstance(rows[-1], dict) else None
        if cursor is None:
            break
    return out


def get_window(get, url: str, params: dict, limit: int, *, start: str | None = None) -> list:
    """Up to `limit` rows starting at a random point of the backlog (id
    order), wrapping to the beginning: the same rotation the old random
    `offset` gave (a county's backlog advances run to run) without a deep
    offset. `start` = the id to begin after (random when None)."""
    import uuid  # noqa: PLC0415
    start = start or str(uuid.uuid4())
    first = get_paged(get, url, dict(params, id=f"gt.{start}"), limit)
    if len(first) >= limit:
        return first
    rest = get_paged(get, url, dict(params, id=f"lte.{start}"), limit - len(first))
    return first + rest
