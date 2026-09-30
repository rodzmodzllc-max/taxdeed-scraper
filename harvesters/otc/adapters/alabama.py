"""Alabama state-held tax-delinquent land - source adapter (2026-09-30).

THE SOURCE (Alabama Department of Revenue, Property Tax Division / State
Land Commissioner). What is established, and how well:

  EVIDENCE GRADE: SEARCH INDEX. On 2026-09-30 a web search returned the
  agency's own page titles, URLs, query strings and text snippets for the
  pages named in `ADOR_EVIDENCE` below. No page or document has been
  fetched from this repository - revenue.alabama.gov is egress-blocked
  from the sandbox and from the assistant's fetch tool alike - so the HTML
  layout of the results page, its columns, its pagination and the
  transcript document format are UNVERIFIED. Every structural assumption
  the parser makes is therefore a candidate, exercised only against
  SYNTHETIC fixtures (tests/python/fixtures/alabama/*SYNTHETIC*), and the
  `parser_fixture_validated` activation requirement stays unmet until a
  real page has been saved and parsed.

  Established from the source's own indexed text:
    * Land on which taxes went unpaid is sold to the State and held in
      State inventory; the Division publishes "a listing by county of tax
      delinquent properties currently in State inventory" (county
      "transcripts", "updated weekly").                     -> STATE_HELD_TAX_LAND
    * "Tax Delinquent Properties for Sale Search": searchable by County,
      CS Number, Parcel Number, or the name in which the property was
      assessed when it sold to the State.                   -> the four row fields
    * "select the CS Number link to generate an online application";
      "request a price quote ... by submitting an electronic application
      ... your price quote ... will be emailed ... 10 calendar days to
      remit".                                              -> QUOTED_ON_APPLICATION,
                                                              per-property APPLICATION link
    * Certificate held by the State < 3 years -> an assignment of the
      certificate; > 3 years -> a tax deed; neither gives clear title.
                                                            -> instrument semantics (not a field)
    * One CS-number-shaped value (8 digits, leading zero) and the query
      parameter names of the search and detail pages were seen in the
      indexed URLs.                                         -> identifier shape "d8"; parameters

  NOT established: the results table's headers and layout; any column
  beyond the four above (no year sold, tax year, acreage, amount or
  description is claimed); the county selector's values (one value, 68,
  was seen with no county name attached - it is NOT mapped); pagination;
  the transcript PDF format; terms of use.

WHAT THIS MODULE DOES
  * `ADOR_SOURCE` - the concrete configuration for the source above,
    NOT enabled, NOT live-verified (`can_run()` is false; the state is not
    activated either).
  * `parse_search_results_html()` - a header-mapped HTML-table reader for
    the results page: finds the table whose header carries the CS Number
    label, reads each row as published, and takes the CS Number cell's
    own link as the property's application link. Unknown columns are
    counted by label and never carried.
  * `parse_county_options()` - reads the county <select> of the search
    page (name = `COUNTY_QUERY_PARAM`) so a live run maps county names to
    selector values from the page itself, never from a table typed here.
  * `parse_rows()` - structured rows -> `OtcRecord`s. Deterministic, per
    row: identifier as published (CS number; no reformatting), parcel as
    published, county from the row (or the query), the name assessed at
    sale, status through the configured vocabulary, amount None +
    QUOTED_ON_APPLICATION, purchase link = the row's own application link
    (kind application_form) else the source-level instructions page.
  * `classify_outcome()` - COMPLETE / EMPTY / INCOMPLETE for one county's
    parse. Until the parser is fixture-validated against the live source,
    rows are reported INCOMPLETE (observed, never asserted complete) and a
    zero is never EMPTY - so the lifecycle can never close a row on the
    strength of an unverified parser.
  * `harvest()` - the live flow (landing page -> county options -> one
    results page per county), REFUSED unless `can_run()` allows it. The
    transport is an injected `fetch_text(url)`; this module imports no
    HTTP client (a test enforces it).
  * `to_harvest_row()` - an `OtcRecord` -> the harvest-row shape
    scripts/laft_lifecycle.py reads (bid "" + bid_kind QUOTED_ON_APPLICATION,
    owner_name = the name assessed at sale, provenance carried).

`OtcRecord.to_properties_row()` refuses these records today: migration
017's constraints do not allow the inventory type or the amount kind
(migration 020, NOT applied, widens them). Alabama is registered and NOT
activated (harvesters/governance/states.py); nothing here changes that.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable
from urllib.parse import urlencode, urljoin, urlsplit

from ...governance import states
from ...governance.states import STATEWIDE_UNIT, PublishingUnit
from ..model import AmountKind, InventoryType, OtcRecord, PurchaseUrlKind, SourceAuthority

__all__ = ["ADOR_EVIDENCE", "ADOR_SOURCE", "ALABAMA_COUNTIES", "AlabamaFieldMap", "AlabamaParseReport",
           "AlabamaSourceConfig", "AlabamaStatus", "CountyOutcome", "Evidence", "GateDecision", "HarvestResult",
           "IDENTIFIER_LINK_KEY", "IDENTIFIER_MAX_LEN", "can_run", "classify_outcome", "county_results_url",
           "harvest", "identifier_shape", "normalize_identifier", "parse_county_options", "parse_rows",
           "parse_search_results_html", "requirement_evidence", "to_harvest_row"]

STATE = "AL"
STATUS_FILE_NAME = "harvest_alabama_status.json"   # never the FL status file: county names overlap (Escambia, Jackson, ...)
HARVEST_FILE_NAME = "harvest_alabama.json"

# The 67 counties of Alabama - the closed set a per-county row may name.
# County NAMES only; no county numbering convention is assumed anywhere.
ALABAMA_COUNTIES = frozenset({
    "Autauga", "Baldwin", "Barbour", "Bibb", "Blount", "Bullock", "Butler", "Calhoun", "Chambers", "Cherokee",
    "Chilton", "Choctaw", "Clarke", "Clay", "Cleburne", "Coffee", "Colbert", "Conecuh", "Coosa", "Covington",
    "Crenshaw", "Cullman", "Dale", "Dallas", "DeKalb", "Elmore", "Escambia", "Etowah", "Fayette", "Franklin",
    "Geneva", "Greene", "Hale", "Henry", "Houston", "Jackson", "Jefferson", "Lamar", "Lauderdale", "Lawrence",
    "Lee", "Limestone", "Lowndes", "Macon", "Madison", "Marengo", "Marion", "Marshall", "Mobile", "Monroe",
    "Montgomery", "Morgan", "Perry", "Pickens", "Pike", "Randolph", "Russell", "St. Clair", "Shelby", "Sumter",
    "Talladega", "Tallapoosa", "Tuscaloosa", "Walker", "Washington", "Wilcox", "Winston",
})
assert len(ALABAMA_COUNTIES) == 67
_COUNTY_BY_KEY = {re.sub(r"[^a-z]", "", c.lower()): c for c in ALABAMA_COUNTIES}


# ---------------------------------------------------------------------------
# Evidence ledger: what the source is, from the source's own indexed text
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Evidence:
    key: str
    grade: str          # SEARCH_INDEX (title/URL/snippet from a web search) | AUDIT_NOTE (the 2026-09-29 audit's summary)
    observed_on: str
    url: str            # the indexed page ("" for an audit note that named none)
    statement: str      # what the indexed text says, as literally as the snippet allowed


EVIDENCE_DATE = "2026-09-30"
ADOR_HOST = "www.revenue.alabama.gov"
ADOR_SEARCH_URL = "https://www.revenue.alabama.gov/property-tax/delinquent-search/"
ADOR_DETAIL_URL = "https://www.revenue.alabama.gov/property-tax/delinquent-search-detail/"
ADOR_LAND_SALES_URL = "https://www.revenue.alabama.gov/property-tax/tax-delinquent-property-and-land-sales/"
ADOR_FAQ_LIST_URL = "https://www.revenue.alabama.gov/faqs/where-can-i-find-a-list-of-tax-delinquent-property/"
ADOR_FAQ_CATEGORY_URL = "https://www.revenue.alabama.gov/faq-categories/land-sales/"
COUNTY_QUERY_PARAM = "ador-delinquent-county"          # seen in the indexed search URL
COUNTY_SUBMIT_PARAM = "_ador-delinquent-county-submit"  # seen in the indexed search URL (value "submit")
DETAIL_QUERY_PARAM = "ador-view-application"            # seen in the indexed detail URL
OBSERVED_CS_NUMBER_SHAPE = "d8"                         # the one CS-number-shaped value seen: 8 digits, leading zero
OBSERVED_COUNTY_SELECTOR_VALUE = "68"                   # one selector value seen; its county name is unknown - never mapped

ADOR_EVIDENCE: tuple[Evidence, ...] = (
    Evidence("search_page", "SEARCH_INDEX", EVIDENCE_DATE, ADOR_SEARCH_URL,
             "Title 'Tax Delinquent Properties for Sale Search'. Indexed URL carried "
             f"?{COUNTY_QUERY_PARAM}={OBSERVED_COUNTY_SELECTOR_VALUE}&{COUNTY_SUBMIT_PARAM}=submit. Snippet: search "
             "'by County, CS Number, Parcel Number, or by the person's name in which the property was assessed when it sold to the State'."),
    Evidence("detail_page", "SEARCH_INDEX", EVIDENCE_DATE, ADOR_DETAIL_URL,
             f"Title 'Tax Delinquent Properties for Sale Search Detail'. Indexed URL carried ?{DETAIL_QUERY_PARAM}=<8 digits, leading zero>."),
    Evidence("land_sales_page", "SEARCH_INDEX", EVIDENCE_DATE, ADOR_LAND_SALES_URL,
             "Title 'Tax Delinquent Property and Land Sales'. Snippets: 'a listing by county of tax delinquent properties currently in "
             "State inventory'; 'How to Read County Transcript Instructions'; transcripts 'updated weekly'; "
             "'Application for Purchase of Land Sold to State of Alabama for Delinquent Taxes'."),
    Evidence("faq_list", "SEARCH_INDEX", EVIDENCE_DATE, ADOR_FAQ_LIST_URL,
             "Snippets: 'select the CS Number link to generate an online application'; 'request a price quote for state-held tax "
             "delinquent property by submitting an electronic application'; the quote 'will be emailed'; '10 calendar days' to remit."),
    Evidence("faq_land_sales", "SEARCH_INDEX", EVIDENCE_DATE, ADOR_FAQ_CATEGORY_URL,
             "Snippet: a certificate held by the State less than three years -> an assignment of the certificate; over three years -> "
             "a tax deed; neither gives clear title."),
    Evidence("audit_note", "AUDIT_NOTE", "2026-09-29", "",
             "50-state audit group 1: 'state ADOR transcripts, weekly, per-county PDF WWW_TRANS_NN, search app'. Not corroborated "
             "by the 2026-09-30 search; no transcript URL is known."),
)


def requirement_evidence() -> dict[str, str]:
    """For each ACTIVATION_REQUIREMENTS item: what evidence exists and why
    it does not satisfy the requirement. All ten are UNMET today; this is
    the reviewer's map, not a claim."""
    return {
        "source_of_record_identified": "search index names the agency and its search/land-sales pages (ADOR_EVIDENCE); not read directly",
        "live_source_verified": "no page fetched from this repository (egress blocked); needs a saved live page",
        "publishing_unit_coverage_established": "statewide search with a county selector per the index; the selector's values were not read",
        "identifier_format_established": "one CS-number-shaped value (8 digits) seen in an indexed URL; a single observation is not a format",
        "inventory_semantics_established": "'currently in State inventory' / sold / assignment vs deed wording seen in snippets; the list's own status wording not read",
        "purchase_path_established": "'select the CS Number link to generate an online application' seen in a snippet; the link itself not read",
        "amount_semantics_established": "'price quote ... by submitting an electronic application' seen in a snippet -> QUOTED_ON_APPLICATION; the page not read",
        "parser_fixture_validated": "parser exercised on SYNTHETIC fixtures only; no fixture captured from the live source",
        "governance_approved": "terms of use not reviewed; registry governance_status TERMS_NOT_VERIFIED",
        "production_registry_authorized": "no decision taken",
    }


# The normalized inventory status vocabulary. `source_status_text` on the
# record always keeps the source's own wording; this is only what the
# configuration's status vocabulary maps it to.
class AlabamaStatus(str):
    AVAILABLE_FOR_SALE = "AVAILABLE_FOR_SALE"   # on the list, purchasable by application
    SOLD = "SOLD"                              # the State has sold it
    REDEEMED = "REDEEMED"                      # the former owner redeemed it
    WITHDRAWN = "WITHDRAWN"                    # removed from sale by the State
    UNKNOWN = "UNKNOWN"                        # wording the vocabulary does not cover


STATUSES = frozenset({AlabamaStatus.AVAILABLE_FOR_SALE, AlabamaStatus.SOLD, AlabamaStatus.REDEEMED,
                      AlabamaStatus.WITHDRAWN, AlabamaStatus.UNKNOWN})

# The only identifier rule that exists before the real format is
# established: printable, single-line, has a digit, bounded length. It is
# a plausibility gate, not a format - a value that passes is stored AS
# PUBLISHED, never reformatted (no digit stripping, no dash transform, no
# leading-zero removal: the one observed CS number starts with 0).
IDENTIFIER_MAX_LEN = 40
_HAS_DIGIT = re.compile(r"\d")
_SHAPE_TOKEN = re.compile(r"\d+|[A-Za-z]+")

# Pseudo-column the HTML reader fills with the CS Number cell's own link,
# resolved against the page URL. A configuration that maps
# fields.property_url to this key says "the identifier's link IS the
# property's application link" (what the FAQ snippet describes).
IDENTIFIER_LINK_KEY = "__identifier_link"

# Generic "nothing listed" phrases. ADOR's own wording is NOT known; these
# only ever matter once the parser is fixture-validated (classify_outcome).
EMPTY_MARKERS = ("no records found", "no properties found", "no results found", "no records were found",
                 "no properties were found", "no properties are currently", "0 records found")

PROPERTY_LINK_KINDS = frozenset({PurchaseUrlKind.ONLINE_PURCHASE, PurchaseUrlKind.OFFER_FORM,
                                 PurchaseUrlKind.BID_FORM, PurchaseUrlKind.APPLICATION_FORM})


@dataclass(frozen=True)
class AlabamaFieldMap:
    """Source column label(s) -> record field. A slot is one label or a
    tuple of alternative labels the source might print for the same
    column; labels are matched after lower-casing and punctuation/space
    collapse (see `_norm_label`). Only `identifier` and (for a statewide
    list without a per-county query) `county` are required. `amount` is
    read only when the configuration's amount_kind is a PUBLISHED kind;
    `balance` names a column that is explicitly NOT a price (taxes due,
    redemption amount) so a reader can see it was deliberately ignored."""
    identifier: str | tuple[str, ...]
    parcel: str | tuple[str, ...] | None = None          # a parcel number column distinct from the identifier
    county: str | tuple[str, ...] | None = None
    assessed_name: str | tuple[str, ...] | None = None   # the name in which the property was assessed when it sold to the State
    status: str | tuple[str, ...] | None = None
    legal_desc: str | tuple[str, ...] | None = None
    address: str | tuple[str, ...] | None = None
    amount: str | tuple[str, ...] | None = None
    balance: str | tuple[str, ...] | None = None
    property_url: str | tuple[str, ...] | None = None   # a PROPERTY-specific link column, or IDENTIFIER_LINK_KEY
    list_as_of: str | tuple[str, ...] | None = None     # the list's own date column/field, if any

    def labels(self, slot: str) -> tuple[str, ...]:
        value = getattr(self, slot)
        if value is None:
            return ()
        return (value,) if isinstance(value, str) else tuple(value)

    def slots(self) -> list[str]:
        return [s for s in vars(self) if getattr(self, s) is not None]


@dataclass(frozen=True)
class AlabamaSourceConfig:
    source_id: str
    publishing_unit: str                       # PublishingUnit.STATE or COUNTY
    publishing_unit_name: str                  # the agency / county office that publishes the list
    fields: AlabamaFieldMap
    source_authority: SourceAuthority = SourceAuthority.GOVERNMENT_DIRECT
    inventory_type: InventoryType = InventoryType.STATE_HELD_TAX_LAND
    amount_kind: AmountKind = AmountKind.QUOTED_ON_APPLICATION
    county: str | None = None                  # fixed county for a COUNTY-level list
    list_url: str | None = None                # the list / search page (https) - the source of record
    document_url: str | None = None            # the transcript / file (https)
    application_url: str | None = None         # the agency's application / instructions page (https)
    application_url_kind: PurchaseUrlKind | None = None   # application_form | purchase_instructions
    # What a link found in the mapped property_url column IS. The FAQ says
    # the CS Number link generates an application for that property.
    property_url_kind: PurchaseUrlKind = PurchaseUrlKind.ONLINE_PURCHASE
    # Hosts a property link may live on (a link elsewhere is rejected and
    # counted). None = any https host.
    property_url_hosts: tuple[str, ...] | None = None
    # Source status wording -> AlabamaStatus. Only wording listed here is
    # normalized; anything else is UNKNOWN with the text preserved.
    status_vocabulary: dict = field(default_factory=dict)
    # The source's own words for the inventory, kept beside the normalized type.
    source_terminology: str = ""
    # Identifier shapes actually observed on the source (identifier_shape()
    # spellings). Empty = none observed; a row whose shape is not listed is
    # still stored as published, just counted (report.identifier_shape_unobserved).
    observed_identifier_shapes: tuple[str, ...] = ()
    # Live-flow parameters (the search page's own query names).
    county_query_param: str | None = None
    county_submit_param: str | None = None
    # ---- activation evidence (all false until a reviewed commit says otherwise)
    live_verified: bool = False                # a page/document was fetched and read directly
    identifier_format_established: bool = False
    parser_fixture_validated: bool = False
    enabled: bool = False
    evidence: str = ""                         # where the evidence for the flags above lives

    def __post_init__(self) -> None:
        if self.publishing_unit not in (PublishingUnit.STATE.value, PublishingUnit.COUNTY.value):
            raise ValueError(f"Alabama publishes by STATE or COUNTY, not {self.publishing_unit!r}")
        if self.publishing_unit == PublishingUnit.COUNTY.value:
            if self.county not in ALABAMA_COUNTIES:
                raise ValueError(f"a COUNTY-level Alabama list must name one of the 67 counties, not {self.county!r}")
        elif self.county is not None:
            raise ValueError("a STATE-level list names the county per row (fields.county), not in the configuration")
        if self.publishing_unit == PublishingUnit.STATE.value and not self.fields.county and not self.county_query_param:
            raise ValueError("a STATE-level list must map the county column (fields.county) or name the county query parameter")
        if not self.publishing_unit_name.strip():
            raise ValueError("publishing_unit_name is required")
        for name in ("list_url", "document_url", "application_url"):
            value = getattr(self, name)
            if value is not None and not value.startswith("https://"):
                raise ValueError(f"{name} must be https")
        if (self.application_url is None) != (self.application_url_kind is None):
            raise ValueError("application_url and application_url_kind go together")
        if self.application_url_kind is not None and self.application_url_kind not in (
                PurchaseUrlKind.APPLICATION_FORM, PurchaseUrlKind.PURCHASE_INSTRUCTIONS):
            raise ValueError("an application page is application_form or purchase_instructions - never a property purchase kind")
        if self.application_url is not None and self.application_url in (self.list_url, self.document_url):
            raise ValueError("the list page / document is not an application page")
        if self.property_url_kind not in PROPERTY_LINK_KINDS:
            raise ValueError("a property link is online_purchase, offer_form, bid_form or application_form - never purchase_instructions")
        if not isinstance(self.amount_kind, AmountKind) or not isinstance(self.inventory_type, InventoryType):
            raise ValueError("amount_kind / inventory_type must be vocabulary members")
        if self.amount_kind is AmountKind.QUOTED_ON_APPLICATION and self.fields.amount:
            raise ValueError("a QUOTED_ON_APPLICATION source publishes no price: do not map an amount column "
                             "(map the column as `balance` if it is a tax balance)")
        for wording, status in self.status_vocabulary.items():
            if status not in STATUSES:
                raise ValueError(f"status vocabulary maps {wording!r} to unknown status {status!r}")
        if (self.county_query_param is None) != (self.county_submit_param is None):
            raise ValueError("county_query_param and county_submit_param go together")
        if self.enabled and not (self.live_verified and self.identifier_format_established and self.parser_fixture_validated):
            raise ValueError("a source cannot be enabled before it is live-verified, its identifier format established "
                             "and its parser fixture validated")


@dataclass
class AlabamaParseReport:
    accepted: int = 0
    rejected_identifier: int = 0     # blank / no digit / too long / multi-line
    rejected_county: int = 0         # not one of the 67 counties, or missing on a statewide list
    county_mismatch: int = 0         # the row names a county other than the one queried (row wins; counted)
    unknown_status: int = 0          # wording outside the configured vocabulary (record kept, status UNKNOWN)
    amount_ignored: int = 0          # a figure in a non-price column (balance) or under QUOTED_ON_APPLICATION
    parcel_dropped: int = 0          # a parcel value that failed the plausibility gate (record kept without it)
    identifier_shape_unobserved: int = 0   # an identifier whose shape the source has not been observed to use
    property_links: int = 0          # rows that carried a property-specific link
    rejected_property_url: int = 0   # a property link that was not https, was on another host or equalled the list page
    unmapped_columns: tuple[str, ...] = ()  # header labels the HTML reader saw and did not map (labels only)


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str


def _norm_label(label) -> str:
    key = re.sub(r"[^a-z0-9 ]", " ", str(label or "").strip().lower())
    return re.sub(r"\s+", " ", key).strip()


def _label_lookup(fm: AlabamaFieldMap) -> dict[str, str]:
    """normalized label -> slot. IDENTIFIER_LINK_KEY is a pseudo-column, not
    a header, so it never enters the lookup."""
    out: dict[str, str] = {}
    for slot in fm.slots():
        for label in fm.labels(slot):
            if label == IDENTIFIER_LINK_KEY:
                continue
            out[_norm_label(label)] = slot
    return out


def _slot_values(raw: dict, fm: AlabamaFieldMap) -> dict[str, object]:
    """A raw row keyed by whatever the source printed -> {slot: value},
    matching labels the same way the HTML reader does."""
    lookup = _label_lookup(fm)
    out: dict[str, object] = {}
    for key, value in raw.items():
        if key == IDENTIFIER_LINK_KEY:
            if fm.property_url == IDENTIFIER_LINK_KEY or (isinstance(fm.property_url, tuple) and IDENTIFIER_LINK_KEY in fm.property_url):
                out["property_url"] = value
            continue
        slot = lookup.get(_norm_label(key))
        if slot and slot not in out:
            out[slot] = value
    return out


def normalize_identifier(value) -> str | None:
    """The identifier AS PUBLISHED, or None. No reformatting of any kind:
    until the real format is established there is nothing to normalize to,
    and a Florida-style dash/space transform would be a guess."""
    if value is None:
        return None
    text = str(value)
    if "\n" in text or "\r" in text:
        return None
    text = re.sub(r"[ \t]+", " ", text).strip()
    if not text or not _HAS_DIGIT.search(text) or len(text) > IDENTIFIER_MAX_LEN:
        return None
    return text


def identifier_shape(value: str) -> str:
    """A format-only spelling of an identifier: runs of digits become d<n>,
    runs of letters A<n>, everything else is kept literally. '01881497' ->
    'd8'; '12-34-56' -> 'd2-d2-d2'. Used to COUNT unobserved shapes, never
    to rewrite a value."""
    out: list[str] = []
    pos = 0
    for m in _SHAPE_TOKEN.finditer(value):
        out.append(value[pos:m.start()])
        tok = m.group(0)
        out.append(f"d{len(tok)}" if tok.isdigit() else f"A{len(tok)}")
        pos = m.end()
    out.append(value[pos:])
    return "".join(out)


def _text(value) -> str | None:
    if value is None:
        return None
    t = re.sub(r"\s+", " ", str(value)).strip()
    return t or None


def _amount(value) -> float | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9.]", "", str(value))
    if not re.match(r"^\d+(\.\d+)?$", cleaned):
        return None
    return float(cleaned)


def _date(value) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _county_name(value) -> str | None:
    """A county cell -> the canonical county name, or None. Case and
    punctuation are ignored and a trailing 'County' is tolerated; nothing
    else is guessed (a division label like 'Jefferson - Bessemer' does not
    match, deliberately - it is not one of the 67 names)."""
    t = _text(value)
    if not t:
        return None
    key = re.sub(r"[^a-z]", "", re.sub(r"(?i)\bcounty\b", "", t).lower())
    return _COUNTY_BY_KEY.get(key)


def can_run(cfg: AlabamaSourceConfig) -> GateDecision:
    """Every reason this configuration may not touch a live source. The
    state gate comes first: a registered-but-inactive state is refused
    whatever the configuration claims."""
    if not states.is_activated(STATE):
        return GateDecision(False, "state AL is not activated - blockers: " + ", ".join(states.activation_blockers(STATE)))
    if not cfg.enabled:
        return GateDecision(False, "source configuration is not enabled")
    if not (cfg.live_verified and cfg.identifier_format_established and cfg.parser_fixture_validated):
        return GateDecision(False, "source not live-verified / identifier format not established / fixture not validated")
    if not cfg.list_url:
        return GateDecision(False, "no source-of-record URL configured")
    return GateDecision(True, "activated state, verified and enabled source")


# ---------------------------------------------------------------------------
# Structured rows -> records
# ---------------------------------------------------------------------------
def parse_rows(cfg: AlabamaSourceConfig, rows: list[dict], *, retrieved_at: datetime,
               list_as_of: date | None = None, default_county: str | None = None,
               list_url: str | None = None) -> tuple[list[OtcRecord], AlabamaParseReport]:
    """Already-structured rows (a fixture, or the HTML reader's output) ->
    OtcRecords. Deterministic, per row, never across rows:
      identity     (AL, laft, county, identifier-as-published)
      parcel       the parcel column as published (plausibility gate only)
      county       the row's own county column; else `default_county` (the
                   county the page was queried for); a COUNTY-level list
                   fixes it from the configuration
      owner_name   the name assessed at sale, as published
      inventory    cfg.inventory_type (STATE_HELD_TAX_LAND)
      amount       None + QUOTED_ON_APPLICATION unless cfg declares a
                   published kind AND the mapped amount column has a figure
      status       cfg.status_vocabulary[text] or UNKNOWN; text preserved
      purchase     a property link only from the mapped property_url
                   column (https, allowed host, not the list page) with
                   cfg.property_url_kind; otherwise cfg.application_url with
                   its application kind; otherwise none
      list_as_of   the row's own date column, else the caller's list date;
                   never retrieved_at
    `list_url` overrides cfg.list_url on the records (the per-county
    results URL a row was actually read from)."""
    fm = cfg.fields
    report = AlabamaParseReport()
    out: list[OtcRecord] = []
    page_url = list_url or cfg.list_url
    not_a_link = {u for u in (cfg.list_url, cfg.document_url, cfg.application_url, page_url) if u}
    if default_county is not None and default_county not in ALABAMA_COUNTIES:
        raise ValueError(f"default_county must be one of the 67 counties, not {default_county!r}")
    for raw in rows:
        v = _slot_values(raw, fm)
        identifier = normalize_identifier(v.get("identifier"))
        if identifier is None:
            report.rejected_identifier += 1
            continue
        shape = identifier_shape(identifier)
        if cfg.observed_identifier_shapes and shape not in cfg.observed_identifier_shapes:
            report.identifier_shape_unobserved += 1
        if cfg.publishing_unit == PublishingUnit.COUNTY.value:
            county = cfg.county
        else:
            county = _county_name(v.get("county")) if "county" in v else None
            if county is None and _text(v.get("county")):
                report.rejected_county += 1        # a county cell that is not an Alabama county
                continue
            if county is None:
                county = default_county
            elif default_county is not None and county != default_county:
                report.county_mismatch += 1        # the row's own statement wins; the mismatch is counted
            if county is None:
                report.rejected_county += 1
                continue
        parcel = normalize_identifier(v.get("parcel")) if "parcel" in v else None
        if "parcel" in v and _text(v.get("parcel")) and parcel is None:
            report.parcel_dropped += 1
        status_text = _text(v.get("status")) if fm.status else None
        status = cfg.status_vocabulary.get((status_text or "").lower(), AlabamaStatus.UNKNOWN) if status_text else AlabamaStatus.UNKNOWN
        if status_text and status == AlabamaStatus.UNKNOWN:
            report.unknown_status += 1
        amount, kind = None, cfg.amount_kind
        if fm.amount and cfg.amount_kind not in (AmountKind.QUOTED_ON_APPLICATION, AmountKind.NOT_PUBLISHED):
            amount = _amount(v.get("amount"))
            if amount is None:
                kind = AmountKind.NOT_PUBLISHED
        if fm.balance and _amount(v.get("balance")) is not None:
            report.amount_ignored += 1        # a tax balance is not a price; deliberately not carried
        if amount is None and kind not in (AmountKind.QUOTED_ON_APPLICATION, AmountKind.NOT_PUBLISHED):
            kind = AmountKind.NOT_PUBLISHED
        purchase_url, purchase_kind = None, None
        if fm.property_url:
            link = _text(v.get("property_url"))
            if link:
                host = urlsplit(link).hostname or ""
                host_ok = cfg.property_url_hosts is None or host in cfg.property_url_hosts
                if link.startswith("https://") and host_ok and link not in not_a_link:
                    purchase_url, purchase_kind = link, cfg.property_url_kind
                    report.property_links += 1
                else:
                    report.rejected_property_url += 1
        if purchase_url is None and cfg.application_url:
            purchase_url, purchase_kind = cfg.application_url, cfg.application_url_kind
        row_as_of = _date(v.get("list_as_of")) if fm.list_as_of else None
        as_of = row_as_of or list_as_of
        owner_name = _text(v.get("assessed_name")) if fm.assessed_name else None
        prov = {
            "adapter": "alabama",
            "publishing_unit": cfg.publishing_unit,
            "publishing_unit_name": cfg.publishing_unit_name,
            "source_terminology": cfg.source_terminology or None,
            "identifier": "as published by the source; no normalization",
            "identifier_shape": shape,
            "parcel": ("parcel number as published by the source; no normalization" if parcel else
                       "no parcel number published on the row" if "parcel" in v else "no parcel column"),
            "county": ("row's own county column" if "county" in v and _county_name(v.get("county")) else
                       "the county the list was queried for" if default_county else "configuration (county-level list)"),
            "owner_name": ("the name in which the property was assessed when it sold to the State, as published - not asserted to be the current owner"
                           if owner_name else "no assessed name published on the row" if fm.assessed_name else "no assessed-name column"),
            "inventory_type": f"configuration: {cfg.inventory_type.value}",
            "status": (f"source wording {status_text!r} -> {status}" if status_text else "no status column"),
            "amount": (f"{kind.value}: no price is published; the State quotes it on application" if kind is AmountKind.QUOTED_ON_APPLICATION
                       else f"column {fm.labels('amount')[0]!r} = {kind.value}" if amount is not None else "no published amount"),
            "purchase_url": (f"property-specific {purchase_kind.value} link published on the row (the identifier's own link)"
                             if purchase_kind in PROPERTY_LINK_KINDS and purchase_url != cfg.application_url
                             else f"agency application page ({purchase_kind.value})" if purchase_kind else "no online path published"),
            "list_as_of": ("row's own date column" if row_as_of else "list date stated by the source" if as_of else "not stated"),
        }
        out.append(OtcRecord(
            state=STATE, county=county, case_no=identifier, source_id=cfg.source_id,
            source_authority=cfg.source_authority, inventory_type=cfg.inventory_type, retrieved_at=retrieved_at,
            parcel=parcel, address=_text(v.get("address")) if fm.address else None,
            legal_desc=_text(v.get("legal_desc")) if fm.legal_desc else None,
            owner_name=owner_name,
            amount=amount, amount_kind=kind,
            list_url=page_url, document_url=cfg.document_url,
            purchase_url=purchase_url, purchase_url_kind=purchase_kind,
            list_as_of=as_of, source_status_text=status_text,
            # normalized_status + the verbatim wording travel in the provenance
            # so scripts/inventory_status_writer.py can read them off the
            # stored row (properties has no source_status_text column).
            provenance={**prov, "normalized_status": status, "source_status_text": status_text},
        ))
        report.accepted += 1
    return out, report


# ---------------------------------------------------------------------------
# HTML readers (structure UNVERIFIED - see the module header)
# ---------------------------------------------------------------------------
def parse_search_results_html(cfg: AlabamaSourceConfig, html: str | bytes, *, retrieved_at: datetime,
                              base_url: str | None = None, list_as_of: date | None = None,
                              default_county: str | None = None) -> tuple[list[OtcRecord], AlabamaParseReport, dict]:
    """The results page -> (records, report, outcome). The table whose
    header row carries the identifier label (and the most other mapped
    labels) is the list; every later <tr> is a row, read as published. The
    identifier cell's own <a href> is resolved against `base_url` (else
    cfg.list_url) and offered to parse_rows as IDENTIFIER_LINK_KEY. Header
    labels with no slot are reported by label only.

    outcome = {header_table_found, data_rows, empty_marker, unmapped_columns}
    - `empty_marker` is the page text carrying one of EMPTY_MARKERS."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    lookup = _label_lookup(cfg.fields)
    page_url = base_url or cfg.list_url
    best = None  # (score, rows, header_index, slots, labels)
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        for idx, tr in enumerate(trs):
            labels = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
            slots = [lookup.get(_norm_label(lb)) for lb in labels]
            if "identifier" not in slots:
                continue
            score = sum(1 for s in slots if s)
            if best is None or score > best[0]:
                best = (score, trs, idx, slots, labels)
    text = soup.get_text(" ", strip=True).lower()
    outcome = {"header_table_found": best is not None, "data_rows": 0,
               "empty_marker": any(m in text for m in EMPTY_MARKERS), "unmapped_columns": []}
    raw_rows: list[dict] = []
    if best is not None:
        _score, trs, idx, slots, labels = best
        outcome["unmapped_columns"] = sorted({lb for lb, s in zip(labels, slots) if lb and not s})
        ident_col = slots.index("identifier")
        for tr in trs[idx + 1:]:
            cells = tr.find_all(["td", "th"])
            if not cells or all(not c.get_text(strip=True) for c in cells):
                continue
            if any(c.name == "th" for c in cells) and len(cells) == len(slots) and \
                    [lookup.get(_norm_label(c.get_text(" ", strip=True))) for c in cells] == slots:
                continue  # a repeated header row
            raw: dict = {}
            for i, cell in enumerate(cells):
                if i >= len(labels):
                    break
                raw[labels[i]] = cell.get_text(" ", strip=True)
                if i == ident_col:
                    a = cell.find("a", href=True)
                    if a is not None and page_url:
                        raw[IDENTIFIER_LINK_KEY] = urljoin(page_url, a["href"].strip())
            raw_rows.append(raw)
        outcome["data_rows"] = len(raw_rows)
    records, report = parse_rows(cfg, raw_rows, retrieved_at=retrieved_at, list_as_of=list_as_of,
                                 default_county=default_county, list_url=page_url)
    report.unmapped_columns = tuple(outcome["unmapped_columns"])
    return records, report, outcome


def parse_county_options(html: str | bytes, *, param: str = COUNTY_QUERY_PARAM) -> tuple[dict[str, str], list[str]]:
    """The search page's county <select name=param> -> ({county: value},
    [unmatched option labels]). Only labels that are one of the 67 county
    names map; a blank value or a placeholder ('Select a county') is
    skipped; anything else (a division label, 'All') is reported unmatched
    - never mapped by guess. No table of selector values lives in code."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", attrs={"name": param})
    if select is None:
        return {}, []
    mapped: dict[str, str] = {}
    unmatched: list[str] = []
    for opt in select.find_all("option"):
        label = opt.get_text(" ", strip=True)
        value = (opt.get("value") if opt.has_attr("value") else label) or ""
        value = value.strip()
        if not value or not label:
            continue
        county = _county_name(label)
        if county is None:
            unmatched.append(label)
        elif county in mapped and mapped[county] != value:
            unmatched.append(label)             # two options for one county: ambiguous, keep the first, report the second
        else:
            mapped[county] = value
    return mapped, unmatched


def county_results_url(cfg: AlabamaSourceConfig, value: str) -> str:
    """The per-county results URL, built ONLY from the search page's own
    query parameter names and an option value read off that page."""
    if not (cfg.list_url and cfg.county_query_param and cfg.county_submit_param):
        raise ValueError("no county query configured for this source")
    return cfg.list_url + "?" + urlencode({cfg.county_query_param: value, cfg.county_submit_param: "submit"})


# ---------------------------------------------------------------------------
# Outcome classification and the (gated) live flow
# ---------------------------------------------------------------------------
@dataclass
class CountyOutcome:
    county: str
    status: str                       # COMPLETE | EMPTY | INCOMPLETE | FAILED
    row_count: int = 0
    category: str | None = None       # a laft_status ERROR_CATEGORIES value for INCOMPLETE / FAILED
    reason: str | None = None
    empty_signal: str | None = None   # for EMPTY
    url: str | None = None
    report: AlabamaParseReport | None = None
    unmapped_columns: tuple[str, ...] = ()


def classify_outcome(cfg: AlabamaSourceConfig, county: str, records: list[OtcRecord], report: AlabamaParseReport,
                     outcome: dict, *, url: str | None = None) -> CountyOutcome:
    """One county's parse -> a status entry. The rule that matters: until
    `cfg.parser_fixture_validated` is true, nothing is COMPLETE and nothing
    is EMPTY - rows are INCOMPLETE (observed, completeness not asserted)
    and a zero is UNCONFIRMED_EMPTY - so an unverified parser can never let
    the lifecycle close a row out."""
    n = len(records)
    validated = cfg.parser_fixture_validated
    base = dict(county=county, row_count=n, url=url, report=report, unmapped_columns=report.unmapped_columns)
    if n:
        if validated:
            return CountyOutcome(status="COMPLETE", **base)
        return CountyOutcome(status="INCOMPLETE", category="UNKNOWN",
                             reason="rows observed but the parser is not fixture-validated against the live source; completeness not asserted", **base)
    if outcome.get("header_table_found") and outcome.get("data_rows", 0) > 0:
        return CountyOutcome(status="INCOMPLETE", category="PARSE_FORMAT_CHANGE",
                             reason="a recognised table whose every row was rejected (identifier / county gates)", **base)
    if outcome.get("empty_marker"):
        if validated:
            return CountyOutcome(status="EMPTY", empty_signal="empty_marker", **base)
        return CountyOutcome(status="INCOMPLETE", category="UNCONFIRMED_EMPTY",
                             reason="an empty-list phrase was seen but the parser is not fixture-validated; zero not trusted", **base)
    if outcome.get("header_table_found"):
        if validated:
            return CountyOutcome(status="EMPTY", empty_signal="empty_table", **base)
        return CountyOutcome(status="INCOMPLETE", category="UNCONFIRMED_EMPTY",
                             reason="a recognised header with zero rows, parser not fixture-validated; zero not trusted", **base)
    return CountyOutcome(status="INCOMPLETE", category="PARSE_NO_TABLE",
                         reason="no table with the identifier label and no empty-list phrase", **base)


@dataclass
class HarvestResult:
    records: list[OtcRecord] = field(default_factory=list)
    outcomes: list[CountyOutcome] = field(default_factory=list)
    counties_offered: int = 0
    unmatched_options: list[str] = field(default_factory=list)
    requests: int = 0


def harvest(cfg: AlabamaSourceConfig, fetch_text: Callable[[str], str], *, retrieved_at: datetime,
            counties: list[str] | None = None) -> HarvestResult:
    """The only path that reaches a live source, and it refuses unless
    can_run() allows it - before the first request. Flow: the search page
    -> its county options -> one results page per county (all of them, or
    `counties`) -> records + a per-county outcome. The transport is the
    injected `fetch_text(url)`; this module never imports an HTTP client.
    A county whose fetch raises is FAILED (class name only - the message is
    never recorded, it could echo request data); one failure never stops
    the others."""
    decision = can_run(cfg)
    if not decision.allowed:
        raise RuntimeError(f"Alabama source {cfg.source_id} may not run: {decision.reason}")
    if not (cfg.county_query_param and cfg.county_submit_param):
        raise RuntimeError("live flow needs the search page's county query parameters")
    result = HarvestResult()
    landing = fetch_text(cfg.list_url)
    result.requests += 1
    options, unmatched = parse_county_options(landing, param=cfg.county_query_param)
    result.counties_offered, result.unmatched_options = len(options), unmatched
    wanted = sorted(options) if counties is None else [c for c in sorted(options) if c in set(counties)]
    for county in wanted:
        url = county_results_url(cfg, options[county])
        try:
            html = fetch_text(url)
            result.requests += 1
            recs, report, outcome = parse_search_results_html(cfg, html, retrieved_at=retrieved_at, base_url=url,
                                                              default_county=county)
        except Exception as exc:  # noqa: BLE001 - one county must not kill the run; class name only
            result.outcomes.append(CountyOutcome(county=county, status="FAILED", category=_category(exc),
                                                 reason=type(exc).__name__, url=url))
            continue
        result.records.extend(recs)
        result.outcomes.append(classify_outcome(cfg, county, recs, report, outcome, url=url))
    return result


def _category(exc: BaseException) -> str:
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


# ---------------------------------------------------------------------------
# Record -> the harvest-row shape scripts/laft_lifecycle.py reads
# ---------------------------------------------------------------------------
def to_harvest_row(rec: OtcRecord) -> dict:
    """The row shape the FL harvesters write to out/harvest_laft*.json and
    the lifecycle reads (identity = county + case_no; bid/bid_kind;
    url_auction = the list page; purchase_url/kind as published). Every
    value is the record's; an absent value is absent, never defaulted."""
    row = {
        "state": rec.state,
        "source": "laft",
        "county": rec.county,
        "case_no": rec.case_no,
        "parcel": rec.parcel,
        "owner_name": rec.owner_name,
        "address": rec.address,
        "legal_desc": rec.legal_desc,
        "bid": "" if rec.amount is None else rec.amount,
        "bid_kind": rec.amount_kind.value,
        "url_auction": rec.list_url,
        "purchase_url": rec.purchase_url,
        "purchase_url_kind": rec.purchase_url_kind.value if rec.purchase_url_kind else None,
        "inventory_type": rec.inventory_type.value if rec.inventory_type else None,
        "source_id": rec.source_id,
        "source_authority": rec.source_authority.value,
        "list_as_of": rec.list_as_of.isoformat() if rec.list_as_of else None,
        "source_status_text": rec.source_status_text,
        "otc_provenance": dict(rec.provenance),
    }
    return {k: v for k, v in row.items() if v is not None}


# ---------------------------------------------------------------------------
# The ADOR source, configured from the evidence ledger. NOT enabled.
# ---------------------------------------------------------------------------
ADOR_STATUS_VOCABULARY = {
    # Candidate wording from the indexed snippets ("currently in State
    # inventory", "sold", "redeemed"). The list's own status column - if it
    # has one - has not been read; anything else stays UNKNOWN + verbatim.
    "available": AlabamaStatus.AVAILABLE_FOR_SALE,
    "available for sale": AlabamaStatus.AVAILABLE_FOR_SALE,
    "in state inventory": AlabamaStatus.AVAILABLE_FOR_SALE,
    "sold": AlabamaStatus.SOLD,
    "redeemed": AlabamaStatus.REDEEMED,
    "withdrawn": AlabamaStatus.WITHDRAWN,
}

ADOR_SOURCE = AlabamaSourceConfig(
    source_id="al_ador_state_land",
    publishing_unit=PublishingUnit.STATE.value,
    publishing_unit_name="Alabama Department of Revenue, Property Tax Division (State Land Commissioner)",
    fields=AlabamaFieldMap(
        # The four fields the FAQ snippet names as search criteria. Each
        # tuple is the evidence label first, then spellings a header might
        # use for the SAME field; a header outside these is reported, not mapped.
        identifier=("CS Number", "CS No", "CS #", "CS"),
        parcel=("Parcel Number", "Parcel No", "Parcel #", "Parcel"),
        county=("County",),
        assessed_name=("Name", "Assessed Name", "Name Assessed", "Assessed To", "Name in which assessed"),
        status=("Status",),
        property_url=IDENTIFIER_LINK_KEY,     # "select the CS Number link to generate an online application"
    ),
    list_url=ADOR_SEARCH_URL,
    document_url=None,                        # the per-county transcript document: URL and format unknown
    application_url=ADOR_LAND_SALES_URL,      # the process page ("Application for Purchase of Land Sold to State ...")
    application_url_kind=PurchaseUrlKind.PURCHASE_INSTRUCTIONS,
    property_url_kind=PurchaseUrlKind.APPLICATION_FORM,   # the CS Number link generates an application, not a checkout
    property_url_hosts=(ADOR_HOST,),
    status_vocabulary=ADOR_STATUS_VOCABULARY,
    source_terminology="tax delinquent properties currently in State inventory; county transcript; CS Number; "
                       "Application for Purchase of Land Sold to State of Alabama for Delinquent Taxes; price quote",
    observed_identifier_shapes=(OBSERVED_CS_NUMBER_SHAPE,),
    county_query_param=COUNTY_QUERY_PARAM,
    county_submit_param=COUNTY_SUBMIT_PARAM,
    live_verified=False,
    identifier_format_established=False,
    parser_fixture_validated=False,
    enabled=False,
    evidence="harvesters/otc/adapters/alabama.py ADOR_EVIDENCE (search index, 2026-09-30); docs/alabama-onboarding.md",
)
