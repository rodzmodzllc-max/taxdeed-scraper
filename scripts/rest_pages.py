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

`send_idempotent` is the write-side twin, for idempotent writes only.
Error messages carry the HTTP status and the
PostgREST table path only, never a query value (a parcel or an owner
name never reaches a public log).
"""
from __future__ import annotations

import json
import random
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

# The patient profile (2026-11-08, LA-1 / LA-3): the Louisiana lifecycle and
# inventory-status reads run while the ten expansion matrix legs write, and a
# statement-timeout 500 outlasted the default 2 + 4 + 8 s (run 42364763870,
# 2026-11-07; run 42018857948, 2026-11-05). Seven attempts, 5 s doubling to a
# 60 s cap, each wait jittered by up to +50 % so parallel readers do not retry
# in step: ~3.5 minutes of waiting at most before the error is raised.
PATIENT_ATTEMPTS = 7
PATIENT_BACKOFF_SECONDS = 5.0
PATIENT_MAX_WAIT_SECONDS = 60.0
PATIENT_JITTER = 0.5


def wait_seconds(attempt: int, backoff: float, *, max_wait: float | None = None, jitter: float = 0.0,
                 rand: Callable[[], float] = random.random) -> float:
    """The wait after failed `attempt` (1-based): `backoff * 2**(attempt-1)`,
    capped at `max_wait`, then stretched by up to `jitter` (a fraction)."""
    base = backoff * (2 ** (attempt - 1))
    if max_wait is not None:
        base = min(base, max_wait)
    return base * (1 + jitter * rand()) if jitter else base


def get_json(url: str, headers: dict, *, timeout: float = 120, attempts: int = ATTEMPTS,
             backoff: float = BACKOFF_SECONDS, sleep: Callable[[float], None] = time.sleep,
             opener: Callable = urllib.request.urlopen, max_wait: float | None = None,
             jitter: float = 0.0, rand: Callable[[], float] = random.random):
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
        sleep(wait_seconds(attempt, backoff, max_wait=max_wait, jitter=jitter, rand=rand))
    raise AssertionError("unreachable")


def get_json_patient(url: str, headers: dict, *, timeout: float = 120, sleep: Callable[[float], None] = time.sleep,
                     opener: Callable | None = None, rand: Callable[[], float] = random.random):
    """`get_json` with the patient profile: for reads that run next to the
    expansion legs' writes (a GET only - idempotent). `opener` defaults to
    urllib.request.urlopen looked up at call time (tests patch it)."""
    opener = opener or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout))
    return get_json(url, headers, timeout=timeout, attempts=PATIENT_ATTEMPTS, backoff=PATIENT_BACKOFF_SECONDS,
                    sleep=sleep, opener=opener, max_wait=PATIENT_MAX_WAIT_SECONDS, jitter=PATIENT_JITTER, rand=rand)


WRITE_ATTEMPTS = 4              # 1 + 3 retries
WRITE_BACKOFF_SECONDS = 5.0     # 5 s, 10 s, 20 s


def send_idempotent(make_request: Callable[[], urllib.request.Request], *, timeout: float = 120,
                    attempts: int = WRITE_ATTEMPTS, backoff: float = WRITE_BACKOFF_SECONDS,
                    sleep: Callable[[float], None] = time.sleep, opener: Callable | None = None,
                    retry_statuses: frozenset = RETRY_STATUSES) -> bytes:
    """Send an IDEMPOTENT write (a PATCH by id / filter, an upsert on its
    conflict key), retrying the same transient failures `get_json` retries
    (audit B43, 2026-10-29: both scheduled harvests of 2026-10-27 stopped on
    a single HTTP 503 / read timeout during a database overload episode).
    A 4xx is raised at once, unchanged; after the last attempt the last
    error is raised unchanged. `make_request` builds a fresh Request per
    attempt. Returns the response body. `opener` defaults to
    urllib.request.urlopen looked up at call time (tests patch it)."""
    opener = opener or (lambda req, timeout: urllib.request.urlopen(req, timeout=timeout))
    for attempt in range(1, attempts + 1):
        try:
            with opener(make_request(), timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in retry_statuses or attempt == attempts:
                raise
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError):
            if attempt == attempts:
                raise
        sleep(backoff * (2 ** (attempt - 1)))
    raise AssertionError("unreachable")


def keyset_query(params: dict, after, page: int = PAGE, *, key: str = "id") -> str:
    """The query string for one keyset page. `params` must not carry its own
    order / limit / offset / `key` filter - paging owns those. `key` is a
    unique, indexed column (the primary key: `id`, or `property_id` for
    property_change_snapshots)."""
    clash = {"order", "limit", "offset", key} & set(params)
    if clash:
        raise ValueError(f"keyset paging owns {sorted(clash)}")
    q = dict(params)
    q["order"] = f"{key}.asc"
    q["limit"] = str(page)
    if after is not None:
        q[key] = f"gt.{after}"
    return urllib.parse.urlencode(q, safe="(),.*:")


def read_all(base_url: str, table: str, headers: dict, params: dict, *, page: int = PAGE,
             fetch: Callable[[str], list] | None = None, attempts: int = ATTEMPTS,
             backoff: float = BACKOFF_SECONDS, key: str = "id", patient: bool = False) -> list[dict]:
    """Every row of `table` matching `params`, by keyset pages on `key`.
    `params` must select `key` (or `*`, which includes it). A short page ends
    the read. `patient` uses the patient retry profile (get_json_patient)."""
    cols = [c.strip() for c in str(params.get("select", key)).split(",")]
    if key not in cols and "*" not in cols:
        raise ValueError(f"keyset paging needs `{key}` in select")
    url = f"{base_url.rstrip('/')}/rest/v1/{table}"
    if fetch is None:
        if patient:
            fetch = lambda qs: get_json_patient(f"{url}?{qs}", headers)  # noqa: E731
        else:
            fetch = lambda qs: get_json(f"{url}?{qs}", headers, attempts=attempts, backoff=backoff)  # noqa: E731
    rows: list[dict] = []
    after = None
    while True:
        chunk = fetch(keyset_query(params, after, page, key=key)) or []
        rows.extend(chunk)
        if len(chunk) < page:
            return rows
        after = chunk[-1][key]
