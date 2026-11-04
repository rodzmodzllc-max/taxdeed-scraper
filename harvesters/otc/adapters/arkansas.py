"""Arkansas - the Commissioner of State Lands' Post Auction Sales List
(source adapter, 2026-09-30).

THE SOURCE (Arkansas Commissioner of State Lands, COSL). Evidence grade:
SEARCH INDEX - the agency's own page titles, URLs, a query string and text
snippets as a web search indexed them on 2026-09-30 (`COSL_EVIDENCE`).
Nothing has been fetched from this repository: cosl.org is egress-blocked
from the sandbox and from the assistant's fetch tool. The list page's
HTML layout, its columns, the county selector's values and pagination are
UNVERIFIED; the parser's structural assumptions are exercised on SYNTHETIC
fixtures only (tests/python/fixtures/arkansas/), and the
`parser_fixture_validated` requirement stays unmet.

  Established from the indexed text:
    * "Properties certified to the Commissioner of State Lands that are
      offered at the initial public auction but do not sell are made
      available for sale through the Post Auction Sales process thirty
      (30) days from the date of the initial public offering."
                                                        -> inventory type POST_SALE
    * The list is "organized by county"; the indexed URL was
      /Home/PostAuctionView?county=DALLAS (one value, upper-case).
                                                        -> STATE publisher, county per query
    * "the tax due amount represents the minimum bid required to purchase
      the parcel"; "legal descriptions which describe acreage are included
      in each entry".                                   -> amount kind OPENING_BID; legal description
    * "Beginning July 1, 2021 ... prospective buyers may bid on these
      parcels through the online auction available on auction.cosl.org."
                                                        -> purchase goes through the State's auction site
    * The delinquent owner "maintains the right to redeem ... ten (10)
      business days following the official post auction sale date"; a
      redeemed purchase is refunded in full.           -> redemption semantics (not a field)

  NOT established: the list's column headers; the parcel-number format;
  the county selector's values beyond one observation (multi-word
  counties such as "Hot Spring" are NOT guessed - see county_url); any
  per-parcel auction link; terms of use.

WHAT THIS MODULE DOES: `COSL_SOURCE` (not enabled), `county_url()` (the
per-county list URL in the ONE observed shape, single-word counties
only), `parse_list_html()` (a header-mapped table reader via the generic
TabularListAdapter, identifier plausibility gate, candidate labels),
`classify_outcome()`, and a gated `harvest()` with an injected transport.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable
from urllib.parse import urlencode

from ...governance import states
from ...governance.states import PublishingUnit
from ..model import AmountKind, InventoryType, OtcRecord, PurchaseUrlKind, SourceAuthority
from . import common
from .common import CountyOutcome, Evidence, GateDecision, HarvestResult
from .tabular import ColumnMap, TabularConfig, TabularListAdapter

__all__ = ["ARKANSAS_COUNTIES", "COSL_EVIDENCE", "COSL_SOURCE", "ArkansasSourceConfig", "can_run", "classify_outcome",
           "county_url", "harvest", "parse_list_html", "requirement_evidence"]

STATE = "AR"
STATUS_FILE_NAME = "harvest_arkansas_status.json"
HARVEST_FILE_NAME = "harvest_arkansas.json"
EVIDENCE_DATE = "2026-09-30"
COSL_HOST = "cosl.org"
COSL_POST_AUCTION_URL = "https://cosl.org/Home/PostAuctionView"
COSL_BUYERS_URL = "https://cosl.org/Home/Buyers"
COSL_FAQ_URL = "https://cosl.org/Home/Faq"
COSL_LAWS_URL = "https://cosl.org/Home/Laws"
COSL_AUCTION_URL = "https://auction.cosl.org/"
COUNTY_QUERY_PARAM = "county"
OBSERVED_COUNTY_VALUE = "DALLAS"       # the one selector value seen: the county name, upper case

ARKANSAS_COUNTIES = frozenset({
    "Arkansas", "Ashley", "Baxter", "Benton", "Boone", "Bradley", "Calhoun", "Carroll", "Chicot", "Clark", "Clay", "Cleburne",
    "Cleveland", "Columbia", "Conway", "Craighead", "Crawford", "Crittenden", "Cross", "Dallas", "Desha", "Drew", "Faulkner",
    "Franklin", "Fulton", "Garland", "Grant", "Greene", "Hempstead", "Hot Spring", "Howard", "Independence", "Izard", "Jackson",
    "Jefferson", "Johnson", "Lafayette", "Lawrence", "Lee", "Lincoln", "Little River", "Logan", "Lonoke", "Madison", "Marion",
    "Miller", "Mississippi", "Monroe", "Montgomery", "Nevada", "Newton", "Ouachita", "Perry", "Phillips", "Pike", "Poinsett",
    "Polk", "Pope", "Prairie", "Pulaski", "Randolph", "St. Francis", "Saline", "Scott", "Searcy", "Sebastian", "Sevier", "Sharp",
    "Stone", "Union", "Van Buren", "Washington", "White", "Woodruff", "Yell",
})
assert len(ARKANSAS_COUNTIES) == 75

COSL_EVIDENCE: tuple[Evidence, ...] = (
    Evidence("post_auction_list", "SEARCH_INDEX", EVIDENCE_DATE, COSL_POST_AUCTION_URL,
             "Title 'Post Auction Sales List - Arkansas Commissioner of State Lands'. Indexed URL carried "
             f"?{COUNTY_QUERY_PARAM}={OBSERVED_COUNTY_VALUE}. Snippet: the list 'is organized by county'."),
    Evidence("faq", "SEARCH_INDEX", EVIDENCE_DATE, COSL_FAQ_URL,
             "Snippets: parcels 'offered at the initial public auction but do not sell are made available for sale through the Post "
             "Auction Sales process thirty (30) days from the date of the initial public offering'; the owner 'maintains the right to "
             "redeem ... ten (10) business days following the official post auction sale date'; 'Beginning July 1, 2021 ... "
             "prospective buyers may bid on these parcels through the online auction available on auction.cosl.org'."),
    Evidence("buyers", "SEARCH_INDEX", EVIDENCE_DATE, COSL_BUYERS_URL,
             "Snippets: 'the tax due amount represents the minimum bid required to purchase the parcel'; 'legal descriptions which "
             "describe acreage are included in each entry, along with any additional legal claim or lien information, and the "
             "delinquent tax owed on the parcel'."),
    Evidence("auction_site", "SEARCH_INDEX", EVIDENCE_DATE, COSL_AUCTION_URL, "Title 'Home - COSL Online Auction'."),
    Evidence("laws", "SEARCH_INDEX", EVIDENCE_DATE, COSL_LAWS_URL, "Title 'Laws Governing the Redemption and Sale of Tax ...'."),
    Evidence("audit_note", "AUDIT_NOTE", "2026-09-29", "",
             "50-state audit group 1: 'COSL Post Auction Sales List, per-county ?county= app, daily updates stated, negotiated after 2 yrs' "
             "- the daily cadence and the negotiated-sale rule were NOT corroborated by the 2026-09-30 search."),
)


def requirement_evidence() -> dict[str, str]:
    return {
        "source_of_record_identified": "search index names COSL and its Post Auction Sales List page; not read directly",
        "live_source_verified": "no page fetched from this repository (egress blocked)",
        "publishing_unit_coverage_established": "per-county query seen once (county=DALLAS); the selector's values were not read",
        "identifier_format_established": "no parcel number observed; nothing is normalized",
        "inventory_semantics_established": "'do not sell ... made available ... thirty days' seen in a snippet; the list's own wording not read",
        "purchase_path_established": "bidding through auction.cosl.org per a snippet; no per-parcel link observed",
        "amount_semantics_established": "'tax due amount represents the minimum bid' seen in a snippet; the column not read",
        "parser_fixture_validated": "parser exercised on SYNTHETIC fixtures only",
        "governance_approved": "terms of use not reviewed; registry governance_status TERMS_NOT_VERIFIED",
        "production_registry_authorized": "no decision taken",
    }


# Generic empty-list phrases; COSL's own wording is not known.
EMPTY_MARKERS = ("no parcels", "no properties", "no records found", "no results", "nothing available", "0 parcels")
_HAS_DIGIT = re.compile(r"\d")
IDENTIFIER_MAX_LEN = 40


@dataclass(frozen=True)
class ArkansasSourceConfig:
    source_id: str
    publishing_unit_name: str
    tabular: TabularConfig                      # the header-mapped list reader's configuration (state AR, county set per page)
    list_url: str
    application_url: str | None = None         # the State's buyer instructions page
    application_url_kind: PurchaseUrlKind | None = None
    auction_platform_url: str | None = None    # where bids are placed (NOT a purchase_url: not property-specific)
    county_query_param: str = COUNTY_QUERY_PARAM
    observed_county_values: tuple[str, ...] = ()
    source_terminology: str = ""
    live_verified: bool = False
    identifier_format_established: bool = False
    parser_fixture_validated: bool = False
    enabled: bool = False
    evidence: str = ""

    def __post_init__(self) -> None:
        for name in ("list_url", "application_url", "auction_platform_url"):
            value = getattr(self, name)
            if value is not None and not value.startswith("https://"):
                raise ValueError(f"{name} must be https")
        if (self.application_url is None) != (self.application_url_kind is None):
            raise ValueError("application_url and application_url_kind go together")
        if self.application_url_kind is not None and self.application_url_kind not in (
                PurchaseUrlKind.APPLICATION_FORM, PurchaseUrlKind.PURCHASE_INSTRUCTIONS):
            raise ValueError("an application page is application_form or purchase_instructions - never a property purchase kind")
        if self.application_url == self.list_url:
            raise ValueError("the list page is not an application page")
        if self.tabular.state != STATE:
            raise ValueError("the tabular configuration must be Arkansas")
        if self.enabled and not (self.live_verified and self.identifier_format_established and self.parser_fixture_validated):
            raise ValueError("a source cannot be enabled before it is live-verified, its identifier format established "
                             "and its parser fixture validated")


def can_run(cfg: ArkansasSourceConfig) -> GateDecision:
    return common.can_run(STATE, enabled=cfg.enabled, live_verified=cfg.live_verified,
                          identifier_format_established=cfg.identifier_format_established,
                          parser_fixture_validated=cfg.parser_fixture_validated, list_url=cfg.list_url)


def county_url(cfg: ArkansasSourceConfig, county: str) -> str | None:
    """The per-county list URL in the ONE observed shape (the county name,
    upper case, in `county=`). Built only for a single-word county: how the
    site spells a multi-word county ('Hot Spring', 'St. Francis', 'Van
    Buren', 'Little River') has not been observed, so those are reported
    unresolved rather than guessed."""
    if county not in ARKANSAS_COUNTIES:
        raise ValueError(f"{county!r} is not one of the 75 Arkansas counties")
    if not re.match(r"^[A-Za-z]+$", county):
        return None
    return cfg.list_url + "?" + urlencode({cfg.county_query_param: county.upper()})


def _plausible(value: str | None) -> bool:
    return bool(value) and "\n" not in value and bool(_HAS_DIGIT.search(value)) and len(value) <= IDENTIFIER_MAX_LEN


def parse_list_html(cfg: ArkansasSourceConfig, html: str | bytes, *, county: str, retrieved_at: datetime,
                    url: str | None = None) -> tuple[list[OtcRecord], dict]:
    """One county's list page -> (records, outcome). The generic tabular
    reader finds the table whose header matches the most configured
    labels; records are re-stamped with the county the page was queried
    for, the page URL as list_url, the identifier gate applied, and the
    State's instructions page as the purchase path (never the list page).
    outcome = {header_table_found, data_rows, empty_marker, rejected_identifier}."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True).lower()
    tab = TabularConfig(**{**vars(cfg.tabular), "county": county, "list_url": url or cfg.list_url,
                           "purchase_url": cfg.application_url, "purchase_url_kind": cfg.application_url_kind})
    adapter = TabularListAdapter(tab)
    header_idx, _fields = adapter._find_header(_rows_of(soup, adapter))
    header_found = header_idx is not None
    raw = adapter.parse_html_table(html, retrieved_at=retrieved_at)
    out: list[OtcRecord] = []
    rejected = 0
    for rec in raw:
        if not _plausible(rec.case_no):
            rejected += 1
            continue
        rec.parcel = rec.case_no                       # COSL lists parcel numbers; the parcel is the identity
        rec.provenance.update({
            "adapter": "arkansas",
            "publishing_unit": PublishingUnit.STATE.value,
            "publishing_unit_name": cfg.publishing_unit_name,
            "source_terminology": cfg.source_terminology or None,
            "county": "the county the list was queried for",
            "identifier": "parcel number as published by the source; no normalization (format not established)",
            "inventory_type": f"configuration: {cfg.tabular.inventory_type.value}",
            "purchase_url": (f"State buyer-instructions page ({cfg.application_url_kind.value})" if cfg.application_url
                             else "no online path published"),
            "auction_platform": cfg.auction_platform_url,
            "amount": (rec.provenance.get("amount") + " (COSL: the tax due amount is the minimum bid)" if rec.amount is not None
                       else "no published amount on the row"),
        })
        out.append(rec)
    outcome = {"header_table_found": header_found, "data_rows": len(raw), "empty_marker": any(m in text for m in EMPTY_MARKERS),
               "rejected_identifier": rejected}
    return out, outcome


def _rows_of(soup, adapter: TabularListAdapter) -> list[list[str]]:
    best: list[list[str]] = []
    best_score = 0
    for table in soup.find_all("table"):
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])] for tr in table.find_all("tr")]
        rows = [r for r in rows if r]
        score = max((sum(1 for c in r if adapter._lookup.get(_norm(c))) for r in rows), default=0)
        if score > best_score:
            best, best_score = rows, score
    return best


def _norm(label: str) -> str:
    from .tabular import _norm as tabular_norm
    return tabular_norm(label)


def classify_outcome(cfg: ArkansasSourceConfig, county: str, records: list[OtcRecord], outcome: dict, *, url: str | None = None) -> CountyOutcome:
    return common.classify(parser_fixture_validated=cfg.parser_fixture_validated, county=county, records=records,
                           header_found=bool(outcome.get("header_table_found")), data_rows=int(outcome.get("data_rows") or 0),
                           empty_marker=bool(outcome.get("empty_marker")), url=url, report=outcome)


def harvest(cfg: ArkansasSourceConfig, fetch_text: Callable[[str], str], *, retrieved_at: datetime,
            counties: list[str] | None = None) -> HarvestResult:
    """The live flow - one list page per county - REFUSED unless can_run()
    allows it, before the first request. Multi-word counties are reported
    unresolved (no URL shape observed for them). A county whose fetch
    raises is FAILED (class name only). The transport is injected."""
    decision = can_run(cfg)
    if not decision.allowed:
        raise RuntimeError(f"Arkansas source {cfg.source_id} may not run: {decision.reason}")
    result = HarvestResult()
    wanted = sorted(ARKANSAS_COUNTIES if counties is None else set(counties) & ARKANSAS_COUNTIES)
    result.units_offered = len(wanted)
    for county in wanted:
        url = county_url(cfg, county)
        if url is None:
            result.unresolved_units.append(county)
            continue
        try:
            html = fetch_text(url)
            result.requests += 1
            recs, outcome = parse_list_html(cfg, html, county=county, retrieved_at=retrieved_at, url=url)
        except Exception as exc:  # noqa: BLE001
            result.outcomes.append(CountyOutcome(county=county, status="FAILED", category=common.error_category(exc),
                                                 reason=type(exc).__name__, url=url))
            continue
        result.records.extend(recs)
        result.outcomes.append(classify_outcome(cfg, county, recs, outcome, url=url))
    return result


# ---------------------------------------------------------------------------
# The COSL source, configured from the evidence ledger. NOT enabled.
# ---------------------------------------------------------------------------
COSL_SOURCE = ArkansasSourceConfig(
    source_id="ar_cosl_post_auction",
    publishing_unit_name="Arkansas Commissioner of State Lands",
    tabular=TabularConfig(
        source_id="ar_cosl_post_auction", state=STATE, county="STATEWIDE",
        source_authority=SourceAuthority.GOVERNMENT_DIRECT, inventory_type=InventoryType.POST_SALE,
        # Candidate labels: the evidence names parcel numbers, legal
        # descriptions (with acreage) and the tax due; the exact headers
        # have not been read. A header outside these is simply not mapped.
        columns=ColumnMap(case_no=("Parcel Number", "Parcel No", "Parcel #", "Parcel"),
                          legal_desc=("Legal Description", "Legal", "Description"),
                          address=("Address", "Property Address", "Physical Address"),
                          amount=("Tax Due", "Taxes Due", "Amount Due", "Minimum Bid", "Delinquent Tax"),
                          status=("Status",)),
        amount_kind=AmountKind.OPENING_BID,        # "the tax due amount represents the minimum bid required to purchase the parcel"
        list_url=COSL_POST_AUCTION_URL, columns_verified=False,
        notes="search-index evidence only; columns not read"),
    list_url=COSL_POST_AUCTION_URL,
    application_url=COSL_BUYERS_URL,
    application_url_kind=PurchaseUrlKind.PURCHASE_INSTRUCTIONS,
    auction_platform_url=COSL_AUCTION_URL,
    observed_county_values=(OBSERVED_COUNTY_VALUE,),
    source_terminology="Post Auction Sales List; parcels certified to the Commissioner of State Lands; tax due = minimum bid; "
                       "online auction (auction.cosl.org); 10-business-day redemption after the post auction sale date",
    evidence="harvesters/otc/adapters/arkansas.py COSL_EVIDENCE (search index, 2026-09-30); docs/arkansas-louisiana-onboarding.md",
)
