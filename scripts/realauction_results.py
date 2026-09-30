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
import urllib.parse
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
    raw_pages: list[str] = field(default_factory=list)
    aids: list[str] = field(default_factory=list)
    update_raw: str | None = None
    update_error: str | None = None
    truncated: bool = False           # the page limit was reached with items still arriving


def sale_day_url(host: str, sale_date: str) -> str:
    return f"https://{host}/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate={sale_date}"


def update_url(host: str, aids: list[str]) -> str:
    """The page's own status-refresh call: the item ids the area response
    lists in `rlist`, and nothing else."""
    return f"https://{host}/index.cfm?zaction=AUCTION&ZMETHOD=UPDATE&FNC=UPDATE&ref={','.join(aids)}"


def update_items(body: str) -> list[dict]:
    """The per-item status records of a status-refresh response
    (ADATA.AITEM), each a dict of the site's own short keys."""
    import json as _json
    try:
        data = _json.loads(body)
    except Exception:
        return []
    items = ((data or {}).get("ADATA") or {}).get("AITEM") if isinstance(data, dict) else None
    if isinstance(items, dict):
        items = [items]
    return [i for i in (items or []) if isinstance(i, dict)]


def rlist_ids(body: str) -> list[str]:
    import json as _json
    try:
        data = _json.loads(body)
    except Exception:
        return []
    raw = data.get("rlist") if isinstance(data, dict) else None
    return [x.strip() for x in str(raw or "").split(",") if x.strip().isdigit()]


def ajax_url(host: str, area: str, page: int, *, reset: bool = True) -> str:
    """page 0 with reset=True is the first page. The site's own pager asks for
    the NEXT page with PageDir=1 and doR=0 (doR=1 re-reads the first page -
    measured: a second doR=1 call returned the same ten items)."""
    return (f"https://{host}/index.cfm?zaction=AUCTION&Zmethod=UPDATE&FNC=LOAD&AREA={area}"
            f"&PageDir={page}&doR={1 if reset else 0}&bypassPage=1&test=1")


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
            url = ajax_url(host, area, 0, reset=True) if page == 0 else ajax_url(host, area, 1, reset=False)
            rr = session.get(url, timeout=timeout,
                             headers={**base, "Accept": "application/json, text/javascript, */*; q=0.01",
                                      "X-Requested-With": "XMLHttpRequest", "Referer": res.url})
            if rr.status_code != 200:
                res.error = f"HTTP {rr.status_code} on area {area} page {page}"
                return res
            res.pages = page + 1
            res.raw_pages.append(rr.text)
            res.aids.extend(a for a in rlist_ids(rr.text) if a not in res.aids)
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
        else:
            res.truncated = True
        res.ok = not res.login_page
        if res.ok and res.aids:
            time.sleep(pause)
            try:
                ur = session.get(update_url(host, res.aids), timeout=timeout,
                                 headers={**base, "Accept": "application/json, text/javascript, */*; q=0.01",
                                          "X-Requested-With": "XMLHttpRequest", "Referer": res.url})
                res.update_raw = ur.text if ur.status_code == 200 else None
                if ur.status_code != 200:
                    res.update_error = f"HTTP {ur.status_code}"
            except Exception as exc:
                res.update_error = f"{type(exc).__name__}"
        return res
    except Exception as exc:  # transport
        res.error = f"{type(exc).__name__}: {str(exc)[:160]}"
        return res


_DIGITS = re.compile(r"\d")


def shape(text: str) -> str:
    """Value-free shape of a cell: every digit becomes '#'. Words stay (a
    status wording is vocabulary, not a value)."""
    return _DIGITS.sub("#", text or "")


_TEXT_NODE = re.compile(r">([^<@]+)")


def mask_text(fragment: str, keep: re.Pattern | None = None) -> str:
    """Mask every text node of an HTML fragment to its shape (letters -> 'a',
    digits -> '#'), except nodes matching `keep` (label / status vocabulary)."""
    def sub(m: re.Match) -> str:
        t = m.group(1)
        if keep is not None and keep.search(t) and not _DIGITS.search(t):
            return ">" + t
        return ">" + re.sub(r"[A-Za-z]", "a", _DIGITS.sub("#", t))
    masked = _ATTR_VALUE.sub(lambda m: f'{m.group(1)}="…"', fragment)
    masked = _TEXT_NODE.sub(sub, masked)
    # Belt and braces: no digit survives anywhere (attribute, script, text).
    return _DIGITS.sub("#", masked)


# Every attribute that can carry an identifier (a link's parcel key, an item
# id) is blanked before anything is printed - a capture once printed the
# appraiser links' parcel keys into a public job log.
_ATTR_VALUE = re.compile(r'\b(href|src|onclick|onClick|aid|id|value|data-[a-z-]+)\s*=\s*"[^"]*"', re.I)


_KEEP_WORDS = re.compile(r"(auction|status|sold|cancel|redeem|withdr|struck|county|bidder|amount|case|parcel|"
                         r"certificate|opening|assessed|type|address|date|plaintiff|party|to\b|postpon|result)", re.I)


def structure_sample(body: str) -> dict:
    """Value-free structure of one AJAX response: its top-level JSON keys
    and, for every non-HTML key, the value's shape; plus the first item
    block with every text node masked except label / status vocabulary."""
    import json as _json
    out: dict = {}
    try:
        data = _json.loads(body)
    except Exception:
        data = None
    if isinstance(data, dict):
        out["json_keys"] = sorted(data.keys())
        shapes = {}
        for k, v in data.items():
            if isinstance(v, str) and "AITEM_" in v:
                continue
            txt = v if isinstance(v, str) else _json.dumps(v)
            shapes[k] = mask_text(">" + txt[:400], _KEEP_WORDS)[1:] if not _KEEP_WORDS.search(txt[:400]) else re.sub(r"\d", "#", txt[:400])
        out["other_keys"] = shapes
    text = unescape(body or "")
    if "AITEM_" in text:
        block = text.split("AITEM_")[1][:2200]
        out["first_item_skeleton"] = mask_text(block, _KEEP_WORDS)
    return out


_STATUS_VOCAB = re.compile(r"^(auction |)(sold|cancel\w*|redeem\w*|withdr\w*|struck\w*|closed|postpon\w*|status|amount|sold to|"
                           r"canceled per county|canceled per \w+|auction status|auction sold|3rd party bidder|"
                           r"certificate holder|county|plaintiff|bankruptcy|no bid\w*|not sold|lands available)[\w ]{0,30}$", re.I)


# Exact purchaser CATEGORIES a sale-result page may print (never a name).
_EXACT_CATEGORIES = frozenset({"3rd party bidder", "certificate holder", "county", "plaintiff", "the county"})


def vocab_or_shape(value: Any) -> str:
    """A string is printed verbatim only when it is status vocabulary with no
    digit; otherwise only its shape (letters 'a', digits '#'). Names,
    amounts, dates and identifiers therefore never reach a log."""
    t = clean(str(value))
    if t.lower() in _EXACT_CATEGORIES:
        return t
    if re.fullmatch(r"[A-Z]", t):
        return t          # a one-letter status code identifies nothing
    if t and len(t) <= 48 and _STATUS_VOCAB.match(t) and not _DIGITS.search(t):
        return t
    return re.sub(r"[A-Za-z]", "a", _DIGITS.sub("#", t))[:48]


def json_shape(value: Any, depth: int = 0) -> Any:
    """Value-free structure of a JSON value: dict keys kept, strings reduced
    by vocab_or_shape, lists summarized by their first two elements."""
    if depth > 5:
        return "…"
    if isinstance(value, dict):
        return {k: json_shape(v, depth + 1) for k, v in list(value.items())[:40]}
    if isinstance(value, list):
        return {"len": len(value), "first": [json_shape(v, depth + 1) for v in value[:2]]}
    if isinstance(value, (int, float)):
        return "#"
    if value is None or isinstance(value, bool):
        return value
    s = str(value)
    if "<" in s and ">" in s:
        return "HTML:" + mask_text(s[:600], _KEEP_WORDS)
    return vocab_or_shape(s)


_JS_KEYS = re.compile(r"ASTAT|PageDir|Auction Sold|Canceled|Redeem|Withdr|Struck|\.A\s*==|\bA\s*==|case\s*['\"][A-Z]['\"]|AREA=")


def page_script_snippets(session: Any, host: str, sale_url: str, *, timeout: int = 25, limit: int = 40) -> dict:
    """The sale-day page's OWN scripts (same host only), and short windows
    around the code that renders an item's status line and pages the list -
    how the page itself turns a status record into words. Code, not data."""
    out: dict = {"scripts": [], "snippets": []}
    try:
        r = session.get(sale_url, headers={"User-Agent": UA}, timeout=timeout)
        srcs = re.findall(r'<script[^>]+src="([^"]+)"', r.text or "", re.I)
        inline = re.findall(r"<script[^>]*>([\s\S]*?)</script>", r.text or "", re.I)
    except Exception as exc:
        out["error"] = type(exc).__name__
        return out
    bodies: list[tuple[str, str]] = [("inline", "\n".join(inline))]
    for src in srcs[:12]:
        url = urllib.parse.urljoin(sale_url, src)
        if urllib.parse.urlsplit(url).hostname != host or re.search(r"/(JQUERY|3rdParty)/|jquery", url, re.I):
            continue
        out["scripts"].append(urllib.parse.urlsplit(url).path)
        try:
            bodies.append((urllib.parse.urlsplit(url).path, session.get(url, headers={"User-Agent": UA}, timeout=timeout).text))
        except Exception:
            continue
    for name, body in bodies:
        for m in _JS_KEYS.finditer(body or ""):
            a, b = max(0, m.start() - 160), min(len(body), m.end() + 220)
            snip = re.sub(r"\s+", " ", body[a:b])
            if all(snip[:80] not in x for x in out["snippets"]):
                out["snippets"].append(f"{name}: {snip}")
            if len(out["snippets"]) >= limit:
                return out
    return out


def RR_clean(v: Any) -> str:
    return clean(str(v or ""))


def status_word(value: Any) -> str:
    """A status cell printed verbatim only when it is a short run of words
    (letters, spaces, hyphens; at most four words, no digit); anything else
    only as its shape. Status wordings ('Redeemed', 'Canceled per County')
    pass; a date, an amount or an identifier never does."""
    t = clean(str(value or ""))
    if t and len(t) <= 40 and re.fullmatch(r"[A-Za-z][A-Za-z\- ]*", t) and len(t.split()) <= 4:
        return t
    return re.sub(r"[A-Za-z]", "a", _DIGITS.sub("#", t))[:40]


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
    skel = structure_sample(res.raw_pages[0]) if res.raw_pages else {}
    upd: Any = None
    if res.update_raw is not None:
        import json as _json
        try:
            upd = json_shape(_json.loads(res.update_raw))
        except Exception:
            upd = "NOT_JSON:" + mask_text(res.update_raw[:600], _KEEP_WORDS)
    tally: dict[str, int] = {}
    if res.update_raw is not None:
        for it in update_items(res.update_raw):
            a = RR_clean(it.get("A"))
            if re.fullmatch(r"[A-Z]", a):
                # A one-letter code in A; the status wording is B.
                key = f"A={a} | B={status_word(it.get('B'))} | C={vocab_or_shape(it.get('C', ''))}"
            else:
                key = f"A={vocab_or_shape(a)} | C={vocab_or_shape(it.get('C', ''))} | D={vocab_or_shape(it.get('D', ''))} | SL={vocab_or_shape(it.get('SL', ''))}"
            tally[key] = tally.get(key, 0) + 1
    return {"status_tally": dict(sorted(tally.items(), key=lambda kv: -kv[1])), "structure": skel, "update": upd, "update_error": res.update_error, "aids": len(res.aids), "url": res.url, "date": res.sale_date, "ok": res.ok, "error": res.error, "login_page": res.login_page,
            "pages": res.pages, "items": len(res.items), "with_case": with_case, "with_parcel": with_parcel,
            "labels": dict(sorted(labels.items())), "status_pairs": dict(sorted(pairs.items(), key=lambda kv: -kv[1])),
            "classes": dict(sorted(classes.items()))}
