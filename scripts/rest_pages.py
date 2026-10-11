"""Whole-population reads from PostgREST that survive load (2026-10-10).

Two production failures had one shape:

* 2026-10-08 SC and 2026-10-09 LA: `sync_state_inventory.stored_provenance`
  read every stored row of the state (with two jsonb columns) in
  `order=id&limit=1000&offset=N` pages. Each page made Postgres sort the
  state's WHOLE filtered set before skipping N rows (East Baton Rouge:
  10,334 wide rows, external merge sort on disk, 1.3 s per page, measured
  read-only 2026-10-10), and with eleven state jobs starting together a
  page crossed the statement timeout -> HTTP 500 -> the sync stopped, the
  Louisiana lifecycle step was skipped and 10,334 rows kept their
  2026-10-03 / 10-06 last read.
* 2026-10-10 deeds job: `geocode_properties._fetch` hit the same 500 and
  the job stopped before the FDOR / FEMA / NAIP steps.

This module is the one place a script reads a population:

* keyset paging - `id=gt.<last id>&order=id.asc&limit=<page>` walks the
  primary-key index, so every page costs the same however deep it is
  (no sort, no spill: measured 2026-10-10 on the MI population);
* a bounded retry, GET only (idempotent), on the statuses a loaded
  PostgREST / Cloudflare front returns transiently (500 / 502 / 503 / 504 /
  520-524) and on a connection error or timeout. A 4xx is never retried -
  it is a request that will not succeed by repeating it.

Nothing here writes. Error messages carry the HTTP status and the
PostgREST table path only, never a query value (a parcel or an owner
name never reaches a public log).
"""
from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

PAGE = 1000                     # PostgREST max-rows on this project
ATTEMPTS = 4                    # 1 + 3 retries
BACKOFF_SECONDS = 2.0           # 2 s, 4 s, 8 s
RETRY_STATUSES = frozenset({500, 502, 503, 504, 520, 521, 522, 523, 524})


def get_json(url: str, headers: dict, *, timeout: float = 120, attempts: int = ATTEMPTS,
             backoff: float = BACKOFF_SECONDS, sleep: Callable[[float], None] = time.sleep,
             opener: Callable = urllib.request.urlopen):
    """GET `url` and decode its JSON body, retrying only transient failures.

    A non-transient HTTP error (a 4xx) is raised at once, unchanged - callers
    that probe for a missing column (HTTP 400) keep working. After the last
    attempt the last error is raised unchanged as well (its message is the
    status line only, never the query)."""
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with opener(req, timeout=timeout) as resp:
                return json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRY_STATUSES or attempt == attempts:
                raise
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError):
            if attempt == attempts:
                raise
        sleep(backoff * (2 ** (attempt - 1)))
    raise AssertionError("unreachable")


def keyset_query(params: dict, after, page: int = PAGE) -> str:
    """The query string for one keyset page. `params` must not carry its own
    order / limit / offset / id filter - paging owns those."""
    clash = {"order", "limit", "offset", "id"} & set(params)
    if clash:
        raise ValueError(f"keyset paging owns {sorted(clash)}")
    q = dict(params)
    q["order"] = "id.asc"
    q["limit"] = str(page)
    if after is not None:
        q["id"] = f"gt.{after}"
    return urllib.parse.urlencode(q, safe="(),.*:")


def read_all(base_url: str, table: str, headers: dict, params: dict, *, page: int = PAGE,
             fetch: Callable[[str], list] | None = None) -> list[dict]:
    """Every row of `table` matching `params`, by keyset pages. `params`
    must select `id`. A short page ends the read."""
    if "id" not in [c.strip() for c in str(params.get("select", "id")).split(",")]:
        raise ValueError("keyset paging needs `id` in select")
    url = f"{base_url.rstrip('/')}/rest/v1/{table}"
    fetch = fetch or (lambda qs: get_json(f"{url}?{qs}", headers))
    rows: list[dict] = []
    after = None
    while True:
        chunk = fetch(keyset_query(params, after, page)) or []
        rows.extend(chunk)
        if len(chunk) < page:
            return rows
        after = chunk[-1]["id"]
