#!/usr/bin/env python3
"""RealAuction closed-auction results: fetch and parse (auction-outcome
evidence sprint, 2026-09-30).

WHAT THIS IS

The FL deed harvester (scripts/harvest_all_counties.ps1) reads each county's
RealAuction sale day through the site's own anonymous AJAX endpoint:

    index.cfm?zaction=AUCTION&Zmethod=UPDATE&FNC=LOAD&AREA=W&PageDir=N&doR=1

AREA=W is "Auctions Waiting". The same page renders a second area, AREA=C
("Auctions Closed or Canceled"), through the SAME endpoint, for the same
anonymous session - no account, no credential, no token. This module reads
that area for a PAST sale day and parses each item into its published
labels (Case #, Parcel ID, Certificate #, ...) and its published status
lines (the ASTAT_* elements: e.g. an "Auction Status" label and its value).

The earlier evidence sprint fetched only the sale-day page SHELL
(zmethod=PREVIEW). That shell always carries the site's login form in its
header and never contains items (they arrive by AJAX), which is why that
capture saw "User Name" / "User Password" and zero items. The shell is not
outcome evidence and is never treated as such here: a response that is the
login form (see is_login_page) yields no items and is reported as such.

WHAT THIS NEVER DOES

- It never logs in, sends a credential, or reads anything the anonymous
  session is not served.
- It never turns a status wording into an outcome. Normalization is the job
  of scripts/auction_outcomes.py, and only through a reviewed wording table.
- It never composes an identifier: the case number is the item's own
  "Case #" cell, the same cell the harvester stores as properties.case_no.

Standard library + requests.
"""
from __future__ import annotations

import html as _html
import re
import time
from dataclasses import dataclass, field
from typing import Any

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
MAX_PAGES = 12
AREA_CLOSED = "C"
AREA_WAITING = "W"

# RealAuction compresses its item HTML with "@X" macros ("@A" = '<div class="',
# "@F" = '</th><td class="', ...). Labels and values are read the same way the
# harvester's Get-Field reads them: a CAD_LBL cell ending in ':' and the next
# CAD_DTA cell's text.
_LABEL_RE = re.compile(r'CAD_LBL"[^>]*>\s*([^@<:]{1,48}?)\s*:(?:@F|<)[\s\S]{0,200}?CAD_DTA">\s*([^@<]*(?:<a[^>]*>([^<]*)</a>)?[^@<]*)')
# The status lines of a closed item: ASTAT_MSGA / MSGB / MSGC / MSGD ...
_ASTAT_RE = re.compile(r'ASTAT_MSG([A-Z])[^>]*>\s*([^@<]*)')
_CLASS_RE = re.compile(r'class="([^"]{1,80})"')
_LOGIN_RE = re.compile(r"(user\s*name|user\s*password|LogIn|loginForm)", re.I)


def unescape(raw: str) -> str:
    """The AJAX body is a JSON string of HTML: undo its escaping only."""
    s = raw.replace('\\"', '"').replace("\\/", "/").replace("\\n", "\n").replace("\\t", " ")
    return s


def is_login_page(text: str) -> bool:
    """A response that is (or embeds) the login form and carries no item.
    Such a page is never outcome evidence."""
    return bool(_LOGIN_RE.search(text or "")) and "AITEM_" not in (text or "")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(text or "")).strip()


@dataclass
class ClosedItem:
    """One item of the Closed / Canceled area, as published. `labels` maps
    each published label (without its colon) to its cell text; `status`
    lists the ASTAT lines in page order as (slot letter, text)."""
    labels: dict[str, str] = field(default_factory=dict)
    status: list[tuple[str, str]] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)

    @property
    def case_no(self) -> str:
        return clean(re.sub(r"<[^>]+>", "", self.labels.get("Case #", "")))

    @property
    def parcel(self) -> str:
        return clean(re.sub(r"<[^>]+>", "", self.labels.get("Parcel ID", "")))

    @property
    def certificate(self) -> str:
        return clean(self.labels.get("Certificate #", ""))

    def status_pairs(self) -> list[tuple[str, str]]:
        """The status lines paired label -> value as the page lays them out:
        slot A is a label, slot B its value, C a label, D its value, ...
        Returned verbatim (cleaned whitespace only)."""
        lines = [clean(t) for _, t in self.status]
        pairs: list[tuple[str, str]] = []
        for i in range(0, len(lines) - 1, 2):
            pairs.append((lines[i].rstrip(":"), lines[i + 1]))
        return pairs


def parse_items(body: str) -> list[ClosedItem]:
    """Every AITEM_ block of one AJAX response, parsed. Unknown shapes parse
    to an item with empty labels - never to a guessed value."""
    text = unescape(body or "")
    if "AITEM_" not in text:
        return []
    items: list[ClosedItem] = []
    for block in text.split("AITEM_")[1:]:
        it = ClosedItem()
        for m in _LABEL_RE.finditer(block):
            label = clean(m.group(1))
            value = m.group(3) if m.group(3) else m.group(2)
            if label and label not in it.labels:
                it.labels[label] = clean(value)
        it.status = [(m.group(1), clean(m.group(2))) for m in _ASTAT_RE.finditer(block)]
        it.classes = sorted({c for m in _CLASS_RE.finditer(block) for c in m.group(1).split()})
        items.append(it)
    return items


@dataclass
class FetchResult:
    host: str
    sale_date: str                    # MM/DD/YYYY as the site takes it
    url: str                          # the sale-day page (the human-readable source)
    ok: bool = False
    error: str | None = None
    login_page: bool = False
    pages: int = 0
    items: list[ClosedItem] = field(default_factory=list)


def sale_day_url(host: str, sale_date: str) -> str:
    return f"https://{host}/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate={sale_date}"


def ajax_url(host: str, area: str, page: int) -> str:
    return (f"https://{host}/index.cfm?zaction=AUCTION&Zmethod=UPDATE&FNC=LOAD&AREA={area}"
            f"&PageDir={page}&doR=1&bypassPage=1&test=1")


def fetch_area(session: Any, host: str, sale_date: str, *, area: str = AREA_CLOSED,
               pause: float = 0.6, timeout: int = 25) -> FetchResult:
    """The harvester's own anonymous sequence (calendar -> sale-day page ->
    AJAX pages), for one area of one past sale day. Transport failures are
    reported, never retried into a different path."""
    res = FetchResult(host=host, sale_date=sale_date, url=sale_day_url(host, sale_date))
    base = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    try:
        session.get(f"https://{host}/index.cfm?zaction=user&zmethod=calendar", headers=base, timeout=timeout)
        r = session.get(res.url, headers={**base, "Referer": f"https://{host}/index.cfm?zaction=USER&zmethod=CALENDAR"},
                        timeout=timeout)
        if r.status_code != 200:
            res.error = f"HTTP {r.status_code} on the sale-day page"
            return res
        seen: set[str] = set()
        for page in range(MAX_PAGES):
            time.sleep(pause)
            rr = session.get(ajax_url(host, area, page), timeout=timeout,
                             headers={**base, "Accept": "application/json, text/javascript, */*; q=0.01",
                                      "X-Requested-With": "XMLHttpRequest", "Referer": res.url})
            if rr.status_code != 200:
                res.error = f"HTTP {rr.status_code} on area {area} page {page}"
                return res
            res.pages = page + 1
            if is_login_page(rr.text):
                res.login_page = True
                break
            batch = parse_items(rr.text)
            fresh = 0
            for it in batch:
                key = it.case_no or f"#{len(res.items)}"
                if key in seen:
                    continue
                seen.add(key)
                res.items.append(it)
                fresh += 1
            if not batch or fresh == 0:
                break
        res.ok = not res.login_page
        return res
    except Exception as exc:  # transport
        res.error = f"{type(exc).__name__}: {str(exc)[:160]}"
        return res


_DIGITS = re.compile(r"\d")


def shape(text: str) -> str:
    """Value-free shape of a cell: every digit becomes '#'. Words stay (a
    status wording is vocabulary, not a value)."""
    return _DIGITS.sub("#", text or "")


def value_free_summary(res: FetchResult) -> dict:
    """What the area publishes, without a single value: label names with
    counts, status-line pairs with digits masked (counts per distinct
    shape), class tokens, and how many items carry a case / parcel cell."""
    labels: dict[str, int] = {}
    pairs: dict[str, int] = {}
    classes: dict[str, int] = {}
    with_case = with_parcel = 0
    for it in res.items:
        for k in it.labels:
            labels[k] = labels.get(k, 0) + 1
        for a, b in it.status_pairs():
            key = f"{shape(a)} => {shape(b)}"
            pairs[key] = pairs.get(key, 0) + 1
        for c in it.classes:
            if c.upper().startswith(("ASTAT", "AUCTION", "AD_", "CAD_")):
                classes[c] = classes.get(c, 0) + 1
        with_case += bool(it.case_no)
        with_parcel += bool(it.parcel)
    return {"url": res.url, "date": res.sale_date, "ok": res.ok, "error": res.error, "login_page": res.login_page,
            "pages": res.pages, "items": len(res.items), "with_case": with_case, "with_parcel": with_parcel,
            "labels": dict(sorted(labels.items())), "status_pairs": dict(sorted(pairs.items(), key=lambda kv: -kv[1])),
            "classes": dict(sorted(classes.items()))}
