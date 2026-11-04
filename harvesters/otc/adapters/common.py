"""What every state adapter shares: the run gate, the per-unit outcome rule
and the evidence record (2026-09-30, Arkansas / Louisiana onboarding).

The Alabama adapter carries its own copies of these (it came first and its
tests pin them); the newer state adapters use this module so the rules
exist once. The rules:

  * can_run(): the STATE gate first (states.is_activated), then the
    source's own flags - enabled, live_verified,
    identifier_format_established, parser_fixture_validated - then a
    source-of-record URL. A registered-but-inactive state is refused
    whatever the configuration claims.
  * classify(): COMPLETE / EMPTY / INCOMPLETE / FAILED for one unit's
    parse. Until the parser is fixture-validated against the live source
    NOTHING is COMPLETE or EMPTY: rows are INCOMPLETE (observed,
    completeness not asserted) and a zero is UNCONFIRMED_EMPTY, so the
    lifecycle can never close a row on the strength of an unverified
    parser.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ...governance import states
from ..model import OtcRecord

__all__ = ["CountyOutcome", "Evidence", "GateDecision", "HarvestResult", "can_run", "classify", "error_category"]


@dataclass(frozen=True)
class Evidence:
    key: str
    grade: str          # SEARCH_INDEX (title/URL/snippet from a web search) | AUDIT_NOTE (the 2026-09-29 audit's summary)
    observed_on: str
    url: str            # the indexed page ("" for an audit note that named none)
    statement: str      # what the indexed text says, as literally as the snippet allowed


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str


@dataclass
class CountyOutcome:
    county: str
    status: str                       # COMPLETE | EMPTY | INCOMPLETE | FAILED
    row_count: int = 0
    category: str | None = None       # a laft_status ERROR_CATEGORIES value for INCOMPLETE / FAILED
    reason: str | None = None
    empty_signal: str | None = None
    url: str | None = None
    report: object = None
    unmapped_columns: tuple[str, ...] = ()


@dataclass
class HarvestResult:
    records: list[OtcRecord] = field(default_factory=list)
    outcomes: list[CountyOutcome] = field(default_factory=list)
    units_offered: int = 0
    unresolved_units: list[str] = field(default_factory=list)
    requests: int = 0


def can_run(state: str, *, enabled: bool, live_verified: bool, identifier_format_established: bool,
            parser_fixture_validated: bool, list_url: str | None) -> GateDecision:
    if not states.is_activated(state):
        return GateDecision(False, f"state {state} is not activated - blockers: " + ", ".join(states.activation_blockers(state)))
    if not enabled:
        return GateDecision(False, "source configuration is not enabled")
    if not (live_verified and identifier_format_established and parser_fixture_validated):
        return GateDecision(False, "source not live-verified / identifier format not established / fixture not validated")
    if not list_url:
        return GateDecision(False, "no source-of-record URL configured")
    return GateDecision(True, "activated state, verified and enabled source")


def classify(*, parser_fixture_validated: bool, county: str, records: list, header_found: bool, data_rows: int,
             empty_marker: bool, url: str | None = None, report=None, unmapped: tuple[str, ...] = ()) -> CountyOutcome:
    n = len(records)
    base = dict(county=county, row_count=n, url=url, report=report, unmapped_columns=unmapped)
    if n:
        if parser_fixture_validated:
            return CountyOutcome(status="COMPLETE", **base)
        return CountyOutcome(status="INCOMPLETE", category="UNKNOWN",
                             reason="rows observed but the parser is not fixture-validated against the live source; completeness not asserted", **base)
    if header_found and data_rows > 0:
        return CountyOutcome(status="INCOMPLETE", category="PARSE_FORMAT_CHANGE",
                             reason="a recognised header whose every row was rejected (identifier gate)", **base)
    if empty_marker:
        if parser_fixture_validated:
            return CountyOutcome(status="EMPTY", empty_signal="empty_marker", **base)
        return CountyOutcome(status="INCOMPLETE", category="UNCONFIRMED_EMPTY",
                             reason="an empty-list phrase was seen but the parser is not fixture-validated; zero not trusted", **base)
    if header_found:
        if parser_fixture_validated:
            return CountyOutcome(status="EMPTY", empty_signal="empty_table", **base)
        return CountyOutcome(status="INCOMPLETE", category="UNCONFIRMED_EMPTY",
                             reason="a recognised header with zero rows, parser not fixture-validated; zero not trusted", **base)
    return CountyOutcome(status="INCOMPLETE", category="PARSE_NO_TABLE",
                         reason="no table with the expected header and no empty-list phrase", **base)


def error_category(exc: BaseException) -> str:
    name = type(exc).__name__.lower()
    category = getattr(exc, "status_category", None)
    if isinstance(category, str):
        return category
    if "timeout" in name:
        return "TRANSPORT_TIMEOUT"
    if "connection" in name or "ssl" in name or "proxy" in name:
        return "TRANSPORT_CONNECTION"
    if "http" in name:
        return "TRANSPORT_HTTP_4XX"
    return "UNKNOWN"
