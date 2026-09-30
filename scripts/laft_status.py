#!/usr/bin/env python3
"""Per-county harvest status for the Florida Lands Available for Taxes
(LAFT) harvesters - the machine-readable completeness gate the master
LAFT/OTC audit (2026-09-29, Phase A2) found missing.

Every one of the nine LAFT harvesters (scripts/harvest_laft_*.py) runs as
its own process and used to report a county only as a row count printed to
the public log. A zero was indistinguishable from "the clerk's list is
empty", "the parser found no table", "the site returned 403", "the proxy
died", and "the PDF link is dead". This module gives each harvester one
place to say WHICH of those happened, per county, in a shape every
downstream consumer can read:

    out/harvest_laft_status.json   - a JSON LIST, one entry per (harvester,
                                     county) attempt, merged across the nine
                                     processes (each harvester replaces only
                                     its own entries)

Consumers:
  - scripts/laft_lifecycle.py      - close-out gate: only a COMPLETE or
                                     EMPTY county may have absent rows
                                     closed; anything else fails closed
  - scripts/source_health.py       - units_from_status() reads the
                                     `county` / `status` / `rowCount` keys
                                     (the deeds status-file shape), so
                                     fl_laft completeness stops being UNKNOWN
  - scripts/artifact_evidence.py   - included verbatim in the public
                                     evidence file (counts, names, statuses,
                                     URLs; never a row value)

STATUS VOCABULARY (one per entry, never inferred from the row count alone):

  COMPLETE    transport succeeded, the parser recognised the source's real
              structure, and at least one row was extracted - or the source
              was byte-identical to a previous successful parse (from_cache)
  EMPTY       transport succeeded AND the source itself said there is
              nothing listed: an explicit empty-marker phrase, a recognised
              header row with zero data rows, or a platform-reported count
              of 0. `empty_signal` names which. This is an authoritative
              observation and may close out inventory.
  INCOMPLETE  transport succeeded but the result cannot be trusted as a
              full inventory: no recognisable table AND no empty marker
              (Brevard's procedural PDF), a platform count/parsed-row
              mismatch, truncated pagination, a zero the harvester cannot
              distinguish from a broken parser (UNCONFIRMED_EMPTY). Rows
              that WERE parsed are still emitted and observed; absent rows
              are never closed.
  FAILED      transport, access or a hard format failure - no observation
              of any kind was possible (HTTP 403/404/5xx, timeout,
              connection reset, proxy failure, placeholder tenant, dead
              document link).
  SOURCE_UNAVAILABLE
              assigned by the READER: a FAILED entry whose error category
              is a transport / proxy / access failure - the source could
              not be reached or refused the request. Closes nothing, like
              FAILED; kept distinct so a source outage is never read as a
              parser failure (or as an empty list).
  STALE       assigned by the READER, not the harvester: the entry's
              checked_at is older than the reader's freshness window, so
              a status file left behind by an earlier run is never treated
              as today's observation.
  NOT_RUN     assigned by the READER for a county the source registry
              expects a harvester to cover but for which no entry exists.

PUBLIC LOG DISCIPLINE: the status file and every line this module prints
carry county names, statuses, counts, source URLs, error CATEGORIES and
exception class names - never a parcel number, address, owner, case number
or amount. `describe_exception()` deliberately drops the exception message
(a vendor error body could echo request data) and keeps only the class
name and, for HTTP errors, the status code.
"""
from __future__ import annotations

import json
import re
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

STATUS_PATH = Path(__file__).resolve().parent / "../out/harvest_laft_status.json"

STATUSES = ("COMPLETE", "EMPTY", "INCOMPLETE", "FAILED", "SOURCE_UNAVAILABLE", "STALE", "NOT_RUN")
# READER-side: a FAILED entry whose error category is a transport / proxy /
# access failure (the source could not be reached or refused us) reads as
# SOURCE_UNAVAILABLE - distinct from a FAILED parse of a page that WAS
# served. Harvesters never write it; both close nothing.
UNAVAILABLE_CATEGORY_PREFIXES = ("TRANSPORT_", "PROXY_", "ACCESS_")
# The two statuses that constitute an authoritative, whole-list observation
# - the ONLY ones under which a previously seen row that is now absent may
# be closed out. Everything else fails closed.
CLOSEOUT_ELIGIBLE = frozenset({"COMPLETE", "EMPTY"})

SOURCE_CLASSES = ("GOVERNMENT_DIRECT", "GOVERNMENT_PLATFORM", "VENDOR_COUNSEL", "VENDOR_AUCTION")

EMPTY_SIGNALS = ("empty_marker", "empty_table", "reported_count_zero", "empty_list")

ERROR_CATEGORIES = (
    "TRANSPORT_HTTP_403_BLOCKED",  # WAF / IP block signature (direct request)
    "TRANSPORT_HTTP_404",          # registered URL no longer exists (dead document link)
    "TRANSPORT_HTTP_4XX",
    "TRANSPORT_HTTP_5XX",
    "TRANSPORT_TIMEOUT",
    "TRANSPORT_CONNECTION",        # connection reset / refused / DNS
    "PROXY_FAILURE",               # the ScraperAPI fallback itself failed
    "PROXY_NOT_CONFIGURED",        # 403 and no proxy key to fall back to
    "ACCESS_DENIED",               # login / disclaimer gate not passed
    "PLACEHOLDER_TENANT",          # realTDM "TEST" tenant
    "PARSE_NO_TABLE",              # nothing table-like and no empty marker
    "PARSE_FORMAT_CHANGE",         # page/JSON shape no longer recognised
    "PARSE_COUNT_MISMATCH",        # platform-reported count != rows parsed
    "PARSE_TRUNCATED",             # source says more rows exist than shown
    "UNCONFIRMED_EMPTY",           # zero rows, no signal that zero is real
    "UNKNOWN",
)

PARSER_VERSION_KEY = "parser_version"

# What a published LAFT amount IS. Set per row by the harvester that read
# it (`bid_kind`), from the source's own column label or the platform's own
# field name - never guessed. Mirrors harvesters/otc/model.py's AmountKind
# (a test keeps the two in step); duplicated here because scripts/ is run
# as a plain directory, not a package.
AMOUNT_KINDS = (
    "MINIMUM_PURCHASE_AMOUNT",
    "OPENING_BID",
    "ORIGINAL_OPENING_BID",
    "FIXED_PURCHASE_PRICE",
    "ESTIMATED_PURCHASE_PRICE",
    "PUBLISHED_AMOUNT_KIND_UNSPECIFIED",
    "NOT_PUBLISHED",
    # Model vocabulary only (not in migration 017's constraint): the source
    # publishes no figure, the price is quoted to an applicant. No FL
    # harvester emits it; scripts/laft_lifecycle.py keeps it out of the DB.
    "QUOTED_ON_APPLICATION",
)

# The kinds public.properties can store today (migration 017). Mirrors
# harvesters/otc/model.py's DB_SUPPORTED_AMOUNT_KINDS (same test keeps them
# in step).
DB_AMOUNT_KINDS = AMOUNT_KINDS[:7]

# Column-label -> amount kind, keyed by the same normalised header text the
# PDF/HTML harvesters' HEADER_MAP uses. A label not listed here still maps
# to `bid` through HEADER_MAP; its kind is then recorded as
# PUBLISHED_AMOUNT_KIND_UNSPECIFIED rather than invented.
AMOUNT_KIND_BY_HEADER = {
    "amount to purchase": "FIXED_PURCHASE_PRICE",
    "purchase price": "FIXED_PURCHASE_PRICE",
    "opening bid": "OPENING_BID",
    "opening bid amount": "OPENING_BID",
    "initial bid": "OPENING_BID",
    "base bid": "OPENING_BID",
    "minimum bid": "MINIMUM_PURCHASE_AMOUNT",
    "min bid": "MINIMUM_PURCHASE_AMOUNT",
    "original opening bid": "ORIGINAL_OPENING_BID",
    "estimated purchase price": "ESTIMATED_PURCHASE_PRICE",
    "price": "PUBLISHED_AMOUNT_KIND_UNSPECIFIED",
}


# ---------------------------------------------------------------------------
# Identifier plausibility gate (2026-09-29, enrichment phase)
# ---------------------------------------------------------------------------
# Production held five FL LAFT rows whose "parcel" was header or paragraph
# text a PDF/HTML parser had swallowed - Volusia "IDNUMBER" /
# "CURRENTPURCHASEPRICE,C" / "WNISTHEORIGINALOPENING" (wrapped column
# headings from the text-strategy table), Pasco a 400-character run of the
# whole page (a label-scanner value that ran to the end of the text), and
# Escambia a second header line whose case cell read "Account". None of
# those can ever match a parcel layer, and each showed a customer a
# "property" that does not exist. The rule below is the smallest
# deterministic gate that rejects all five and accepts every real
# identifier format observed in production (FL parcels up to 26 chars,
# Hendry's "23-09 / Cert 15-2918" case numbers, TX "512026XX000151TDAXXX"):
#   - an identifier contains at least one digit;
#   - a parcel is at most IDENT_MAX_LEN characters, a case number at most
#     CASE_MAX_LEN, after whitespace is collapsed;
#   - it contains no line break.
# A row whose parcel OR case number fails the gate is dropped whole and
# counted in the parser outcome as `rejected` - never "repaired".
IDENT_MAX_LEN = 40
CASE_MAX_LEN = 60
_HAS_DIGIT = re.compile(r"\d")


def plausible_identifier(value, *, kind: str = "parcel") -> bool:
    if value is None:
        return False
    text = re.sub(r"[ \t]+", " ", str(value)).strip()
    if not text or "\n" in text or "\r" in text:
        return False
    if not _HAS_DIGIT.search(text):
        return False
    return len(text) <= (CASE_MAX_LEN if kind == "case_no" else IDENT_MAX_LEN)


def record_identifiers_plausible(record: dict) -> bool:
    """True when every identifier the record carries passes the gate (a
    record with neither is the caller's problem, not this gate's)."""
    parcel, case_no = record.get("parcel"), record.get("case_no")
    if parcel is not None and str(parcel).strip() and not plausible_identifier(parcel, kind="parcel"):
        return False
    if case_no is not None and str(case_no).strip() and not plausible_identifier(case_no, kind="case_no"):
        return False
    return True


# ---------------------------------------------------------------------------
# List as-of date (2026-09-29, enrichment phase)
# ---------------------------------------------------------------------------
# migration 017's list_as_of: "the list's own as-of date (from its filename
# or title) when it has one. Never the retrieval date." Two deterministic
# readings, in order: a dated phrase in the document text ("as of
# 09/15/2026", "updated 9/15/2026", "revised: 2026-09-15", "current as of
# ..."), then an 8-digit YYYYMMDD in the document's filename (Pasco:
# "...Taxes%2020260706.pdf"). Anything else -> None.
_AS_OF_TEXT = re.compile(
    r"(?i)\b(?:as of|updated|revised|last updated|current as of|list date|dated)\s*:?\s*"
    r"(\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})")
_FILENAME_DATE = re.compile(r"(?<!\d)((?:19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?!\d)")


def _iso_or_none(text: str) -> str | None:
    from datetime import datetime as _dt
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return _dt.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def extract_list_as_of(document_text: str | None = None, url: str | None = None) -> str | None:
    if document_text:
        m = _AS_OF_TEXT.search(document_text)
        if m:
            iso = _iso_or_none(m.group(1))
            if iso:
                return iso
    if url:
        from urllib.parse import unquote as _unquote
        name = _unquote(str(url)).rsplit("/", 1)[-1]
        m = _FILENAME_DATE.search(name)
        if m:
            return _iso_or_none(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    return None


def amount_kind_for_header(normalised_header: str | None) -> str:
    return AMOUNT_KIND_BY_HEADER.get((normalised_header or "").strip().lower(), "PUBLISHED_AMOUNT_KIND_UNSPECIFIED")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CountyStatus:
    county: str
    harvester: str
    status: str
    state: str = "FL"
    source_class: str | None = None
    source_id: str | None = None
    checked_at: str = field(default_factory=now_iso)
    row_count: int = 0
    transport_ok: bool | None = None
    parse_ok: bool | None = None
    empty_marker_observed: bool = False
    empty_signal: str | None = None
    source_url: str | None = None
    document_url: str | None = None
    parser_version: str | None = None
    from_cache: bool = False
    error_category: str | None = None
    error_detail: str | None = None
    document_sha256: str | None = None
    document_etag: str | None = None
    document_last_modified: str | None = None
    # The list's own as-of date (ISO), read off the document text or its
    # filename by extract_list_as_of() - never the retrieval date.
    list_as_of: str | None = None
    reason: str | None = None

    def validate(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        if self.source_class is not None and self.source_class not in SOURCE_CLASSES:
            raise ValueError(f"unknown source_class {self.source_class!r}")
        if self.empty_signal is not None and self.empty_signal not in EMPTY_SIGNALS:
            raise ValueError(f"unknown empty_signal {self.empty_signal!r}")
        if self.error_category is not None and self.error_category not in ERROR_CATEGORIES:
            raise ValueError(f"unknown error_category {self.error_category!r}")
        if self.status == "EMPTY" and not self.empty_signal:
            raise ValueError("EMPTY requires an explicit empty_signal - a bare zero is never EMPTY")
        if self.status == "EMPTY" and self.row_count:
            raise ValueError("EMPTY cannot carry rows")
        if self.status == "COMPLETE" and self.row_count < 1 and not self.from_cache:
            raise ValueError("COMPLETE requires at least one row (zero rows is EMPTY or INCOMPLETE)")
        if self.status in ("FAILED", "INCOMPLETE") and not self.error_category:
            raise ValueError(f"{self.status} requires an error_category")
        if self.status == "FAILED" and self.row_count:
            raise ValueError("FAILED cannot carry rows - nothing was observed")

    def to_json(self) -> dict:
        d = asdict(self)
        # `rowCount` duplicates row_count in the deeds status-file spelling
        # so scripts/source_health.py's units_from_status()/row_count_of()
        # read this file unchanged.
        d["rowCount"] = self.row_count
        return d


def describe_exception(exc: BaseException) -> tuple[str, str]:
    """(error_category, redacted detail) for an exception raised while
    fetching or parsing one county. The detail is the exception CLASS and,
    for HTTP errors, the status code - never the message."""
    name = type(exc).__name__
    status = None
    resp = getattr(exc, "response", None)
    if resp is not None:
        status = getattr(resp, "status_code", None)
    lowered = name.lower()
    if status is not None:
        detail = f"{name}: HTTP {status}"
        if status == 403:
            return "TRANSPORT_HTTP_403_BLOCKED", detail
        if status == 404:
            return "TRANSPORT_HTTP_404", detail
        if 400 <= status < 500:
            return "TRANSPORT_HTTP_4XX", detail
        if status >= 500:
            return "TRANSPORT_HTTP_5XX", detail
    category = getattr(exc, "status_category", None)
    if category in ERROR_CATEGORIES:
        return category, name
    if "timeout" in lowered:
        return "TRANSPORT_TIMEOUT", name
    if "connection" in lowered or "ssl" in lowered or "proxy" in lowered:
        return "TRANSPORT_CONNECTION", name
    if lowered in ("jsondecodeerror", "valueerror") or "decode" in lowered:
        return "PARSE_FORMAT_CHANGE", name
    return "UNKNOWN", name


class CategorizedError(RuntimeError):
    """A harvester-raised failure that already knows its category, so
    describe_exception() never has to guess from the message text."""

    def __init__(self, category: str, message: str = "") -> None:
        if category not in ERROR_CATEGORIES:
            raise ValueError(f"unknown error_category {category!r}")
        super().__init__(message or category)
        self.status_category = category


class StatusRecorder:
    """One per harvester process. Collects entries for the counties this
    harvester attempted, then merges them into the shared status file."""

    def __init__(self, harvester: str, *, source_class: str | None = None,
                 source_id: str | None = None, parser_version: str | None = None,
                 path: Path | str | None = None, state: str = "FL") -> None:
        self.harvester = harvester
        self.source_class = source_class
        self.source_id = source_id or harvester
        self.parser_version = parser_version
        self.state = state
        self.path = Path(path) if path else Path(os.environ.get("LAFT_STATUS_PATH") or STATUS_PATH)
        self.entries: list[CountyStatus] = []

    # ---- recording helpers -------------------------------------------------
    def _add(self, entry: CountyStatus) -> CountyStatus:
        entry.validate()
        # Replace an earlier entry for the same county from this harvester
        # (a retry within one run supersedes the first attempt).
        self.entries = [e for e in self.entries if e.county != entry.county]
        self.entries.append(entry)
        return entry

    def _base(self, county: str, **kw) -> dict:
        base = dict(county=county, harvester=self.harvester, state=self.state,
                    source_class=self.source_class, source_id=self.source_id,
                    parser_version=self.parser_version)
        base.update(kw)
        return base

    def complete(self, county: str, row_count: int, *, source_url: str | None = None,
                 from_cache: bool = False, **kw) -> CountyStatus:
        return self._add(CountyStatus(status="COMPLETE", row_count=row_count, transport_ok=True,
                                      parse_ok=True, from_cache=from_cache,
                                      **self._base(county, source_url=source_url, **kw)))

    def empty(self, county: str, signal: str, *, source_url: str | None = None, **kw) -> CountyStatus:
        return self._add(CountyStatus(status="EMPTY", row_count=0, transport_ok=True, parse_ok=True,
                                      empty_marker_observed=(signal == "empty_marker"), empty_signal=signal,
                                      **self._base(county, source_url=source_url, **kw)))

    def incomplete(self, county: str, category: str, reason: str, *, row_count: int = 0,
                   source_url: str | None = None, transport_ok: bool = True, parse_ok: bool = False,
                   **kw) -> CountyStatus:
        return self._add(CountyStatus(status="INCOMPLETE", row_count=row_count, transport_ok=transport_ok,
                                      parse_ok=parse_ok, error_category=category, reason=reason,
                                      **self._base(county, source_url=source_url, **kw)))

    def failed(self, county: str, exc_or_category, reason: str | None = None, *,
               source_url: str | None = None, **kw) -> CountyStatus:
        if isinstance(exc_or_category, BaseException):
            category, detail = describe_exception(exc_or_category)
        else:
            category, detail = str(exc_or_category), None
        transport_ok = not category.startswith(("TRANSPORT_", "PROXY_", "ACCESS_"))
        return self._add(CountyStatus(status="FAILED", row_count=0, transport_ok=transport_ok, parse_ok=False,
                                      error_category=category, error_detail=detail,
                                      reason=reason or category,
                                      **self._base(county, source_url=source_url, **kw)))

    # ---- persistence ---------------------------------------------------------
    def write(self) -> Path:
        """Merge this harvester's entries into the shared file. Entries from
        OTHER harvesters are preserved; this harvester's previous entries are
        replaced wholesale (so a county dropped from a source CSV disappears
        rather than lingering as a stale entry)."""
        existing = load_status(self.path)
        kept = [e for e in existing if e.get("harvester") != self.harvester]
        merged = kept + [e.to_json() for e in self.entries]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)
        return self.path

    def summary_line(self) -> str:
        counts: dict[str, int] = {}
        for e in self.entries:
            counts[e.status] = counts.get(e.status, 0) + 1
        parts = ", ".join(f"{k} {counts[k]}" for k in STATUSES if k in counts)
        return f"status ({self.harvester}): {parts or 'no counties attempted'}"


def load_status(path: Path | str = STATUS_PATH) -> list[dict]:
    """The status file as a list of dicts, or [] when absent/unreadable.
    Never raises - a reader that cannot read the file must fail CLOSED on
    its own (no county is COMPLETE without an entry saying so)."""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def effective_status(entry: dict, *, now: float | None = None, max_age_hours: float = 36.0) -> str:
    """The status a READER should act on: the recorded status, downgraded to
    STALE when the entry is older than the freshness window. Unknown or
    unparsable timestamps are STALE, never trusted."""
    recorded = str(entry.get("status") or "").upper()
    if recorded not in STATUSES or recorded in ("STALE", "NOT_RUN", "SOURCE_UNAVAILABLE"):
        return "NOT_RUN"
    checked = entry.get("checked_at")
    if not checked:
        return "STALE"
    try:
        t = datetime.fromisoformat(str(checked).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
    except ValueError:
        return "STALE"
    now_t = datetime.fromtimestamp(now if now is not None else time.time(), tz=timezone.utc)
    if (now_t - t).total_seconds() > max_age_hours * 3600:
        return "STALE"
    if recorded == "FAILED" and str(entry.get("error_category") or "").startswith(UNAVAILABLE_CATEGORY_PREFIXES):
        return "SOURCE_UNAVAILABLE"
    return recorded


def statuses_by_county(entries: list[dict], *, expected: list[tuple[str, str]] | None = None,
                       now: float | None = None, max_age_hours: float = 36.0) -> dict[str, dict]:
    """{county: {"status": effective, "harvester": ..., "entry": ...}}.

    A county attempted by more than one harvester (should not happen, but
    two source CSVs could disagree) is resolved to the WEAKEST status - a
    FAILED attempt anywhere means the county is not confirmed complete.
    `expected` is a list of (harvester, county) pairs the registry says
    should have run; any missing pair becomes NOT_RUN."""
    order = {"SOURCE_UNAVAILABLE": 0, "FAILED": 0, "NOT_RUN": 1, "STALE": 2, "INCOMPLETE": 3, "EMPTY": 4, "COMPLETE": 5}
    out: dict[str, dict] = {}
    for e in entries:
        county = e.get("county")
        if not county:
            continue
        eff = effective_status(e, now=now, max_age_hours=max_age_hours)
        cur = out.get(county)
        if cur is None or order[eff] < order[cur["status"]]:
            out[county] = {"status": eff, "harvester": e.get("harvester"), "entry": e}
    for harvester, county in expected or []:
        if county not in out:
            out[county] = {"status": "NOT_RUN", "harvester": harvester, "entry": None}
    return out
