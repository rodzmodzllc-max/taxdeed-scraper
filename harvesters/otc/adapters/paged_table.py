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
    delay_s: float = 0.3

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


def counter(html: str) -> tuple[int, int, int, int] | None:
    from bs4 import BeautifulSoup  # noqa: PLC0415
    m = PAGE_COUNTER.search(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
    return tuple(int(x) for x in m.groups()) if m else None


def _retrying(post_text, sleep, attempts: int = 3):
    """A POST that answered 5xx is retried (bounded, with back-off). A retry
    that moved the server-side session past a page is caught by the page
    counter check (FAILED, never a silent skip)."""
    def call(url, data):
        for i in range(attempts):
            try:
                return post_text(url, data)
            except Exception as exc:  # noqa: BLE001
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status is None or status < 500 or i == attempts - 1:
                    raise
                sleep(2.0 * (i + 1))
    return call


def fetch_all(cfg: PagedTableConfig, post_text: Callable[[str, dict], str], *, retrieved_at: datetime,
              sleep: Callable[[float], None] | None = None) -> PagedResult:
    import time  # noqa: PLC0415
    sleep = sleep or time.sleep
    post_text = _retrying(post_text, sleep)
    records: list[OtcRecord] = []
    excluded = rejected = 0
    seen: set[str] = set()
    try:
        html = post_text(cfg.first_url, dict(cfg.first_data))
    except Exception as exc:  # noqa: BLE001
        return PagedResult("FAILED", error_category="TRANSPORT_CONNECTION", error_detail=type(exc).__name__)
    page_no, total_pages, last_listing = 0, None, 0
    for _ in range(cfg.max_pages):
        c = counter(html)
        adapter = TabularListAdapter(cfg.table)
        got = adapter.parse_html_table(html, retrieved_at=retrieved_at)
        if c is None:
            if not got and page_no == 0:
                return PagedResult("EMPTY", pages=0, total=0)
            return PagedResult("FAILED", error_category="PARSE_FORMAT_CHANGE", error_detail=f"no page counter after page {page_no}")
        cur, total_pages, first, last = c
        if cur != page_no + 1:
            return PagedResult("FAILED", error_category="PARSE_FORMAT_CHANGE",
                               error_detail=f"page counter {cur} after page {page_no} (session paging lost)")
        page_no, last_listing = cur, last
        excluded += adapter.excluded_status
        rejected += adapter.rejected_ids
        for r in got:
            if r.case_no not in seen:
                seen.add(r.case_no)
                records.append(r)
        if cur >= total_pages:
            break
        sleep(cfg.delay_s)
        try:
            html = post_text(cfg.next_url, dict(cfg.next_data))
        except Exception as exc:  # noqa: BLE001
            return PagedResult("FAILED", error_category="TRANSPORT_CONNECTION", error_detail=type(exc).__name__)
    else:
        return PagedResult("FAILED", error_category="PARSE_FORMAT_CHANGE", error_detail=f"page cap {cfg.max_pages} hit")
    read = len(records) + excluded + rejected
    if read < last_listing:
        # fewer rows than the site's own listing total: a page was lost or repeated
        return PagedResult("FAILED", error_category="PARSE_FORMAT_CHANGE", error_detail=f"read {read} of {last_listing} listings",
                           pages=page_no, total=last_listing, rows_read=read)
    return PagedResult("COMPLETE" if records else "EMPTY", records, pages=page_no, total=last_listing, rows_read=read,
                       excluded_status=excluded, rejected_ids=rejected)
