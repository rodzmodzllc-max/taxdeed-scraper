"""A server-side paged HTML table (new-sources sprint, 2026-10-26).

Some land-bank sites publish their inventory as one HTML table of 25 rows
per page, paged by a form POST that the server keeps in its own session
(Genesee County Land Bank, Michigan: `find_properties.asp?LRCsearch=do`
returns page 1 and "page 1 of N (listings 1-25)"; each POST of
`LRCpage=next` to `?LRCsearch=redo` returns the next page in the same
session). No login, no CAPTCHA - the same requests a visitor's browser makes.

The adapter is configuration-driven (`PagedTableConfig` wraps a
`TabularConfig` for the columns) and does not fetch: the caller injects
`post_text(url, data) -> str`, which must keep cookies between calls.

Outcome:
  COMPLETE  every page read, the last page reached ("page N of N") and the
            row count equals the site's own listing total
  EMPTY     the site's own "no listings" (page counter absent AND no table)
  FAILED    transport error, a page counter that stops advancing, a page cap
            hit, or fewer rows than the site's own total - nothing read is
            trusted

Exact totals and session recovery (thin-fields sprint, 2026-10-27). Genesee
prints the search's own size ("10668 properties found.") on every result
page; when `total_pattern` finds it, a part must read exactly that many
listings and the parts must add up to EXACTLY the unfiltered search's size
(no page-size tolerance). The site also answers HTTP 500 at random (about
every 50-60 pages, sandbox 2026-10-26) and a 500 may move its server-side
page cursor. With `stay_data` / `prev_data` a failed "next" is recovered in
place: the current page is re-requested ("stay", which re-renders it - read
live 2026-10-27), its counter says where the session is, and "prev" steps
back to the page that was not read yet. Every page is still accepted only
when its counter is exactly the next page number, so a recovery can never
skip or repeat a page; a page that cannot be recovered in
`recoveries_per_page` tries restarts the part (up to `attempts`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from ..model import OtcRecord
from .tabular import TabularConfig, TabularListAdapter

PAGE_COUNTER = re.compile(r"page\s+(\d+)\s+of\s+(\d+)\s+\(listings\s+(\d+)\s*-\s*(\d+)\)", re.I)


@dataclass(frozen=True)
class PagedTableConfig:
    table: TabularConfig
    first_url: str                 # POST here first (the search 'do' action)
    next_url: str                  # POST here for each next page (the 'redo' action)
    next_data: tuple[tuple[str, str], ...] = (("LRCpage", "next"),)
    # The first POST carries the search form's own (empty) fields: a POST with
    # no body is refused (HTTP 411 Length Required, Genesee 2026-10-26).
    first_data: tuple[tuple[str, str], ...] = (("LRCsort", ""), ("LRCpage", ""))
    max_pages: int = 1000
    delay_s: float = 0.5
    # The search form's own filter that splits the inventory into disjoint
    # parts (Genesee: FindTWP, one township / city / Flint quadrant at a
    # time). A long session-paged read can lose its place on a server error
    # (2026-10-26: an HTTP 500 moved the session on a page); a part is short,
    # and a part whose read fails is restarted from its own page 1 (up to
    # `attempts` times). The parts must add up to the unfiltered search's size.
    partition_field: str | None = None
    partition_values: tuple[str, ...] = ()
    attempts: int = 3
    # The site's own statement of the search's size (one group: the count).
    total_pattern: str | None = None
    # Session recovery after a failed "next" (both None = restart the part).
    stay_data: tuple[tuple[str, str], ...] | None = None
    prev_data: tuple[tuple[str, str], ...] | None = None
    recoveries_per_page: int = 4

    @property
    def source_id(self) -> str:
        return self.table.source_id

    def __getattr__(self, name):          # county, state, record_source, list_url, notes, ... from the table config
        return getattr(self.table, name)


@dataclass
class PagedResult:
    outcome: str
    records: list[OtcRecord] = field(default_factory=list)
    error_category: str | None = None
    error_detail: str | None = None
    pages: int = 0
    total: int | None = None
    rows_read: int = 0
    excluded_status: int = 0
    rejected_ids: int = 0
    unanswered_parts: int = 0


def counter(html: str) -> tuple[int, int, int, int] | None:
    from bs4 import BeautifulSoup  # noqa: PLC0415
    m = PAGE_COUNTER.search(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    return tuple(int(x) for x in m.groups()) if m else None


def stated_total(cfg: PagedTableConfig, html: str) -> int | None:
    """The search's size as the site states it, or None (no pattern / not printed)."""
    if not cfg.total_pattern:
        return None
    from bs4 import BeautifulSoup  # noqa: PLC0415
    m = re.search(cfg.total_pattern, BeautifulSoup(html, "html.parser").get_text(" ", strip=True), re.I)
    return int(m.group(1).replace(",", "")) if m else None


def _next_page(cfg: PagedTableConfig, post_text, want: int, sleep) -> tuple[str, int]:
    """The HTML of page `want` of the current session, and how many
    recoveries it took. A failed "next" is recovered in place when the
    configuration allows it (see the module docstring): the session's current
    page is re-requested and stepped back with "prev" when the failed request
    had already moved it. Raises _ReadError when the page cannot be reached."""
    try:
        return post_text(cfg.next_url, dict(cfg.next_data)), 0
    except Exception as exc:  # noqa: BLE001
        if cfg.stay_data is None or cfg.prev_data is None:
            raise _ReadError("TRANSPORT_CONNECTION", type(exc).__name__) from exc
        last_exc = exc
    for attempt in range(1, cfg.recoveries_per_page + 1):
        sleep(2.0 * attempt)
        try:
            html = post_text(cfg.next_url, dict(cfg.stay_data))
            c = counter(html)
            if c is None:
                raise _ReadError("PARSE_FORMAT_CHANGE", "no page counter while recovering the session")
            cur = c[0]
            if cur == want:
                return html, attempt
            if cur == want - 1:
                html = post_text(cfg.next_url, dict(cfg.next_data))
            elif cur > want:
                for _ in range(cur - want):
                    html = post_text(cfg.next_url, dict(cfg.prev_data))
            else:
                raise _ReadError("PARSE_FORMAT_CHANGE", f"session at page {cur} while recovering page {want}")
            c = counter(html)
            if c and c[0] == want:
                return html, attempt
        except _ReadError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    raise _ReadError("TRANSPORT_CONNECTION", f"{type(last_exc).__name__} (page {want} not recovered)")


class _ReadError(Exception):
    def __init__(self, category: str, detail: str, first_page_server_error: bool = False):
        super().__init__(detail)
        self.category, self.detail = category, detail
        self.first_page_server_error = first_page_server_error


def _read_search(cfg: PagedTableConfig, post_text, extra: dict, *, retrieved_at, sleep):
    """One search, every page in its session -> (records, listings, excluded, rejected, pages, page_size).
    Raises _ReadError on any transport failure, missing counter or lost session."""
    try:
        html = post_text(cfg.first_url, {**dict(cfg.first_data), **extra})
    except Exception as exc:  # noqa: BLE001
        status = getattr(getattr(exc, "response", None), "status_code", None)
        raise _ReadError("TRANSPORT_CONNECTION", type(exc).__name__ + (f" HTTP {status}" if status else ""),
                         first_page_server_error=bool(status and status >= 500)) from exc
    records, excluded, rejected, page_no, last, size = [], 0, 0, 0, 0, 0
    total = stated_total(cfg, html)
    for _ in range(cfg.max_pages):
        c = counter(html)
        adapter = TabularListAdapter(cfg.table)
        got = adapter.parse_html_table(html, retrieved_at=retrieved_at)
        if c is None:
            if page_no == 0:
                # No pager at all: the site prints its counter only for a result of
                # more than one page (Genesee 2026-10-26). One page, or none.
                n = len(got) + adapter.excluded_status + adapter.rejected_ids
                if total is not None and n != total:
                    raise _ReadError("PARSE_FORMAT_CHANGE", f"read {n} of the {total} listings the site states")
                return got, n, adapter.excluded_status, adapter.rejected_ids, (1 if n else 0), n
            raise _ReadError("PARSE_FORMAT_CHANGE", f"no page counter after page {page_no}")
        cur, total_pages, first, last = c
        if cur != page_no + 1:
            raise _ReadError("PARSE_FORMAT_CHANGE", f"page counter {cur} after page {page_no} (session paging lost)")
        if cur == 1:
            size = last - first + 1
        page_no = cur
        excluded += adapter.excluded_status
        rejected += adapter.rejected_ids
        records += got
        if cur >= total_pages:
            break
        sleep(cfg.delay_s)
        html, _recovered = _next_page(cfg, post_text, page_no + 1, sleep)
    else:
        raise _ReadError("PARSE_FORMAT_CHANGE", f"page cap {cfg.max_pages} hit")
    read = len(records) + excluded + rejected
    if read != last or (total is not None and read != total):
        raise _ReadError("PARSE_FORMAT_CHANGE", f"read {read} of {total if total is not None else last} listings")
    # Two pages of one session carrying the same listing means the cursor
    # repeated a page without its counter saying so: never trusted.
    if len({r.case_no for r in records}) != len(records):
        raise _ReadError("PARSE_FORMAT_CHANGE", "a listing appeared twice within one session")
    return records, last, excluded, rejected, page_no, size


def fetch_all(cfg: PagedTableConfig, post_text: Callable[[str, dict], str], *, retrieved_at: datetime,
              sleep: Callable[[float], None] | None = None) -> PagedResult:
    import time  # noqa: PLC0415
    sleep = sleep or time.sleep
    parts = [{cfg.partition_field: v} for v in cfg.partition_values] if cfg.partition_field else [{}]
    expect_pages = expect_size = expect_total = None
    if cfg.partition_field:
        # The unfiltered search's own size: page 1 only (its counter names the page count).
        # Retried like a part (2026-10-27: one live read got a page without its
        # counter on the first try and a normal page on the next).
        c = full = None
        for attempt in range(cfg.attempts):
            try:
                full = post_text(cfg.first_url, dict(cfg.first_data))
            except Exception as exc:  # noqa: BLE001
                if attempt == cfg.attempts - 1:
                    return PagedResult("FAILED", error_category="TRANSPORT_CONNECTION", error_detail=type(exc).__name__)
                sleep(3.0 * (attempt + 1))
                continue
            c = counter(full)
            if c is not None:
                break
            if attempt < cfg.attempts - 1:
                sleep(3.0 * (attempt + 1))
        if c is None:
            return PagedResult("FAILED", error_category="PARSE_FORMAT_CHANGE", error_detail="no page counter on the full search")
        expect_pages, expect_size = c[1], c[3] - c[2] + 1
        expect_total = stated_total(cfg, full)
    records: list[OtcRecord] = []
    seen: set[str] = set()
    listings = excluded = rejected = pages = unanswered = 0
    for extra in parts:
        for attempt in range(cfg.attempts):
            try:
                got, n, ex, rj, pg, _ = _read_search(cfg, post_text, extra, retrieved_at=retrieved_at, sleep=sleep)
                break
            except _ReadError as err:
                if attempt == cfg.attempts - 1:
                    if err.first_page_server_error and expect_pages is not None:
                        # Genesee (2026-10-26): a few township filters answer HTTP 500 on
                        # every try (the site's own fault, seen on parts with no listings).
                        # The part counts as unanswered; the add-up check below proves no
                        # listing was missed (else FAILED).
                        got, n, ex, rj, pg = [], 0, 0, 0, 0
                        unanswered += 1
                        break
                    return PagedResult("FAILED", error_category=err.category,
                                       error_detail=f"{err.detail}" + (f" (part {extra})" if extra else ""))
                sleep(3.0 * (attempt + 1))
        listings += n
        excluded += ex
        rejected += rj
        pages += pg
        for r in got:
            if r.case_no not in seen:
                seen.add(r.case_no)
                records.append(r)
    if expect_total is not None and listings != expect_total:
        return PagedResult("FAILED", error_category="PARSE_FORMAT_CHANGE",
                           error_detail=f"parts add up to {listings} listings; the full search states {expect_total} "
                                        f"({unanswered} part(s) unanswered)", pages=pages, total=listings)
    if expect_pages is not None and not ((expect_pages - 1) * expect_size < listings <= expect_pages * expect_size):
        return PagedResult("FAILED", error_category="PARSE_FORMAT_CHANGE",
                           error_detail=f"parts add up to {listings} listings; the full search has {expect_pages} pages of "
                                        f"{expect_size} ({unanswered} part(s) unanswered)", pages=pages, total=listings)
    read = len(records) + excluded + rejected
    return PagedResult("COMPLETE" if records else "EMPTY", records, pages=pages, total=listings, rows_read=read,
                       excluded_status=excluded, rejected_ids=rejected, unanswered_parts=unanswered)
