"""Alabama state-held tax-delinquent land - adapter FOUNDATION (2026-09-29).

The researched concept (50-state audit, search-index evidence only): land
on which taxes went unpaid is sold to the State of Alabama and held by the
Alabama Department of Revenue, Property Tax Division (the State Land
Commissioner); the Division publishes per-county lists ("transcripts") of
such land available for purchase, and a buyer applies for a specific
parcel and receives a QUOTED price - there is no auction opening bid. In
this framework that is inventory type STATE_HELD_TAX_LAND, amount kind
QUOTED_ON_APPLICATION, publishing unit STATE (with the county named on
each row) and purchase path "application / instructions page" until a
property-level link is actually observed.

NOTHING here has been verified against the live source: no page or
document was fetched from this repository (egress to the agency is not
available here), so the identifier format, the column layout, the status
wording and the URLs are all UNESTABLISHED. This module therefore:

  * defines the CONTRACT - configuration, field map, normalization rules,
    the record shape - so a verified Alabama source is configuration plus a
    fixture, not new code;
  * REFUSES to run: `can_run()` is false until the configuration says the
    source was live-verified, its identifier format established and its
    parser fixture validated AND `states.is_activated("AL")` (which needs
    a reviewed commit satisfying every ACTIVATION_REQUIREMENTS item);
  * never fetches (a `fetch_text` callable is injected, like the ArcGIS
    adapter) and names no endpoint;
  * rejects rather than guesses: an identifier is accepted only as
    published (no Florida-style reformatting, no digit stripping, no
    inferred county code), a status is normalized only through the
    configuration's own vocabulary, an amount is stored only when the
    configuration declares a PUBLISHED kind and the row carries it, and a
    tax balance / assessed value column is never a price.

The records it produces are `OtcRecord`s; `to_properties_row()` refuses
them today because migration 017's constraints do not allow the inventory
type or the amount kind (migration 020, NOT applied, widens them).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from ...governance import states
from ...governance.states import STATEWIDE_UNIT, PublishingUnit
from ..model import AmountKind, InventoryType, OtcRecord, PurchaseUrlKind, SourceAuthority

__all__ = ["ALABAMA_COUNTIES", "AlabamaFieldMap", "AlabamaParseReport", "AlabamaSourceConfig", "AlabamaStatus",
           "GateDecision", "can_run", "harvest", "normalize_identifier", "parse_rows", "IDENTIFIER_MAX_LEN"]

STATE = "AL"

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
# PUBLISHED, never reformatted.
IDENTIFIER_MAX_LEN = 40
_HAS_DIGIT = re.compile(r"\d")


@dataclass(frozen=True)
class AlabamaFieldMap:
    """Source column/field name -> record field. Only `identifier` and
    (for a statewide list) `county` are required. `amount` is read only
    when the configuration's amount_kind is a PUBLISHED kind; `balance`
    names a column that is explicitly NOT a price (taxes due, redemption
    amount) so a reader can see it was deliberately ignored."""
    identifier: str
    county: str | None = None
    status: str | None = None
    legal_desc: str | None = None
    address: str | None = None
    amount: str | None = None
    balance: str | None = None
    property_url: str | None = None            # a PROPERTY-specific link column, if the source has one
    list_as_of: str | None = None              # the list's own date column/field, if any


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
    list_url: str | None = None                # the list page (https) - the source of record
    document_url: str | None = None            # the transcript / file (https)
    application_url: str | None = None         # the agency's application / instructions page (https)
    application_url_kind: PurchaseUrlKind | None = None   # application_form | purchase_instructions
    # Source status wording -> AlabamaStatus. Only wording listed here is
    # normalized; anything else is UNKNOWN with the text preserved.
    status_vocabulary: dict = field(default_factory=dict)
    # The source's own words for the inventory, kept beside the normalized type.
    source_terminology: str = ""
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
        if self.publishing_unit == PublishingUnit.STATE.value and not self.fields.county:
            raise ValueError("a STATE-level list must map the county column (fields.county)")
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
        if not isinstance(self.amount_kind, AmountKind) or not isinstance(self.inventory_type, InventoryType):
            raise ValueError("amount_kind / inventory_type must be vocabulary members")
        if self.amount_kind is AmountKind.QUOTED_ON_APPLICATION and self.fields.amount:
            raise ValueError("a QUOTED_ON_APPLICATION source publishes no price: do not map an amount column "
                             "(map the column as `balance` if it is a tax balance)")
        for wording, status in self.status_vocabulary.items():
            if status not in STATUSES:
                raise ValueError(f"status vocabulary maps {wording!r} to unknown status {status!r}")
        if self.enabled and not (self.live_verified and self.identifier_format_established and self.parser_fixture_validated):
            raise ValueError("a source cannot be enabled before it is live-verified, its identifier format established "
                             "and its parser fixture validated")


@dataclass
class AlabamaParseReport:
    accepted: int = 0
    rejected_identifier: int = 0     # blank / no digit / too long / multi-line
    rejected_county: int = 0         # not one of the 67 counties, or missing on a statewide list
    unknown_status: int = 0          # wording outside the configured vocabulary (record kept, status UNKNOWN)
    amount_ignored: int = 0          # a figure in a non-price column (balance) or under QUOTED_ON_APPLICATION
    property_links: int = 0          # rows that carried a property-specific link
    rejected_property_url: int = 0   # a property link that was not https or equalled the list page


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str


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


def harvest(cfg: AlabamaSourceConfig, fetch_text, *, retrieved_at: datetime):
    """The only path that could reach a live source, and it refuses unless
    can_run() allows it. Even then the transport is the injected
    `fetch_text(url)`; this module never imports an HTTP client."""
    decision = can_run(cfg)
    if not decision.allowed:
        raise RuntimeError(f"Alabama source {cfg.source_id} may not run: {decision.reason}")
    raise NotImplementedError("Alabama transport is not implemented: the source has not been live-verified, "
                              "so there is no established document format to fetch and parse")


def parse_rows(cfg: AlabamaSourceConfig, rows: list[dict], *, retrieved_at: datetime,
               list_as_of: date | None = None) -> tuple[list[OtcRecord], AlabamaParseReport]:
    """Already-structured rows (a fixture, or a future verified parser's
    output) -> OtcRecords. Deterministic, per row, never across rows:
      identity     (AL, laft, county, identifier-as-published)
      inventory    cfg.inventory_type (STATE_HELD_TAX_LAND)
      amount       None + QUOTED_ON_APPLICATION unless cfg declares a
                   published kind AND the mapped amount column has a figure
      status       cfg.status_vocabulary[text] or UNKNOWN; text preserved
      purchase     a property link only from the mapped property_url
                   column (https, not the list page) -> online_purchase;
                   otherwise cfg.application_url with its application kind;
                   otherwise none
      list_as_of   the row's own date column, else the caller's list date;
                   never retrieved_at
    """
    fm = cfg.fields
    report = AlabamaParseReport()
    out: list[OtcRecord] = []
    for raw in rows:
        identifier = normalize_identifier(raw.get(fm.identifier))
        if identifier is None:
            report.rejected_identifier += 1
            continue
        if cfg.publishing_unit == PublishingUnit.COUNTY.value:
            county = cfg.county
        else:
            county = _text(raw.get(fm.county))
            if county not in ALABAMA_COUNTIES:
                report.rejected_county += 1
                continue
        status_text = _text(raw.get(fm.status)) if fm.status else None
        status = cfg.status_vocabulary.get((status_text or "").lower(), AlabamaStatus.UNKNOWN) if status_text else AlabamaStatus.UNKNOWN
        if status_text and status == AlabamaStatus.UNKNOWN:
            report.unknown_status += 1
        amount, kind = None, cfg.amount_kind
        if fm.amount and cfg.amount_kind not in (AmountKind.QUOTED_ON_APPLICATION, AmountKind.NOT_PUBLISHED):
            amount = _amount(raw.get(fm.amount))
            if amount is None:
                kind = AmountKind.NOT_PUBLISHED
        if fm.balance and _amount(raw.get(fm.balance)) is not None:
            report.amount_ignored += 1        # a tax balance is not a price; deliberately not carried
        if amount is None and kind not in (AmountKind.QUOTED_ON_APPLICATION, AmountKind.NOT_PUBLISHED):
            kind = AmountKind.NOT_PUBLISHED
        purchase_url, purchase_kind = None, None
        if fm.property_url:
            link = _text(raw.get(fm.property_url))
            if link:
                if link.startswith("https://") and link not in (cfg.list_url, cfg.document_url, cfg.application_url):
                    purchase_url, purchase_kind = link, PurchaseUrlKind.ONLINE_PURCHASE
                    report.property_links += 1
                else:
                    report.rejected_property_url += 1
        if purchase_url is None and cfg.application_url:
            purchase_url, purchase_kind = cfg.application_url, cfg.application_url_kind
        row_as_of = _date(raw.get(fm.list_as_of)) if fm.list_as_of else None
        as_of = row_as_of or list_as_of
        prov = {
            "adapter": "alabama",
            "publishing_unit": cfg.publishing_unit,
            "publishing_unit_name": cfg.publishing_unit_name,
            "source_terminology": cfg.source_terminology or None,
            "identifier": "as published by the source; no normalization (format not established)",
            "inventory_type": f"configuration: {cfg.inventory_type.value}",
            "status": (f"source wording {status_text!r} -> {status}" if status_text else "no status column"),
            "amount": (f"{kind.value}: no price is published; the State quotes it on application" if kind is AmountKind.QUOTED_ON_APPLICATION
                       else f"column {fm.amount!r} = {kind.value}" if amount is not None else "no published amount"),
            "purchase_url": ("property-specific link published on the row" if purchase_kind is PurchaseUrlKind.ONLINE_PURCHASE
                             else f"agency application page ({purchase_kind.value})" if purchase_kind else "no online path published"),
            "list_as_of": ("row's own date column" if row_as_of else "list date stated by the source" if as_of else "not stated"),
        }
        out.append(OtcRecord(
            state=STATE, county=county, case_no=identifier, source_id=cfg.source_id,
            source_authority=cfg.source_authority, inventory_type=cfg.inventory_type, retrieved_at=retrieved_at,
            parcel=identifier, address=_text(raw.get(fm.address)) if fm.address else None,
            legal_desc=_text(raw.get(fm.legal_desc)) if fm.legal_desc else None,
            amount=amount, amount_kind=kind,
            list_url=cfg.list_url, document_url=cfg.document_url,
            purchase_url=purchase_url, purchase_url_kind=purchase_kind,
            list_as_of=as_of, source_status_text=status_text, provenance={**prov, "normalized_status": status},
        ))
        report.accepted += 1
    return out, report
