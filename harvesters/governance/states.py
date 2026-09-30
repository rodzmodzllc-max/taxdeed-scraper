"""Supported states for the OTC / LAFT / struck-off framework.

Until 2026-09-29 the framework hard-coded "FL" and "TX" in four places
(`OtcRecord.validate()`, `county_source_registry.validate_row()`,
`scripts/laft_lifecycle.py`, `scripts/sanity_check_laft.ps1`). This module
is the one place a state is declared, so that a future, DIRECTLY VERIFIED
state is added by configuration rather than by editing each of those.

Registering a state here does NOT activate it. It makes the state
structurally acceptable to the model, the registry validator and the
lifecycle script - nothing more. A row for a registered state still needs
a PRODUCTION_VERIFIED registry entry, an approved governance status, a
named harvester and a source-of-record URL before `otc.gate.evaluate_source`
lets anything run, and the production `properties` table still has to be
able to hold the row's inventory type and amount kind (see
`DB_SUPPORTED_*` in county_source_registry / otc.model).

FL, TX and (2026-09-30) LA are the production states. AL (Alabama, 2026-09-29) is
registered as a NON-production state so the model, the registry and the
adapters can REPRESENT its inventory concept; it cannot run anywhere until
every ACTIVATION_REQUIREMENTS item is satisfied in a reviewed commit (see
`is_activated`). Tests register hypothetical states through `registered()`
and unregister them again. There is no environment-variable or file-based
override on purpose: a state enters this list through a reviewed commit.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


class PublishingUnit(str, Enum):
    """The kind of government unit a source row describes. FL and TX
    inventories are published per county; the 50-state audit found parish
    (LA), borough (AK), municipal (New England) and statewide (AR, MS, AL,
    WV) publishers."""
    COUNTY = "COUNTY"
    PARISH = "PARISH"
    BOROUGH = "BOROUGH"
    MUNICIPALITY = "MUNICIPALITY"
    STATE = "STATE"


# The `county` value a STATE-level registry row / harvester status entry
# carries: the whole state is the unit, so there is no county to name.
STATEWIDE_UNIT = "STATEWIDE"

# What must be established, each in a reviewed commit, before a state's rows
# may exist in production (the state activation gate). A production state
# satisfies all of them by definition; a registered non-production state
# lists what it has, and `activation_blockers()` names the rest.
ACTIVATION_REQUIREMENTS = (
    "source_of_record_identified",        # the authoritative publisher and its page/document
    "live_source_verified",               # fetched and read directly, not a search snippet
    "publishing_unit_coverage_established",  # which units (state / counties / ...) the source covers
    "identifier_format_established",      # the identifier's real shape, from the source itself
    "inventory_semantics_established",    # what "available" / "sold" / "redeemed" mean there
    "purchase_path_established",          # property link vs application page vs none
    "amount_semantics_established",       # what any published figure IS (or that none is)
    "parser_fixture_validated",           # a fixture taken from the real source parses deterministically
    "governance_approved",                # terms reviewed; registry governance_status APPROVED
    "production_registry_authorized",     # an explicit decision to add the PRODUCTION_VERIFIED row
)


@dataclass(frozen=True)
class StateConfig:
    code: str                                   # "FL"
    name: str                                   # "Florida"
    publishing_units: tuple[str, ...]           # PublishingUnit values this state's sources may use
    # Inventory types a PRODUCTION_VERIFIED registry row may carry ("" =
    # unclassified allowed). FL rows are always the statutory fixed-price
    # list; TX rows are struck-off / future-resale or unclassified.
    production_inventory_types: frozenset[str]
    # What scripts/laft_lifecycle.py stamps on observed rows (None = the
    # lifecycle never asserts an inventory type for this state).
    lifecycle_inventory_type: str | None
    production: bool                            # rows may exist in public.properties today
    # Why the lifecycle may assert that type - written into otc_provenance
    # so a row says where its classification came from. Required whenever
    # lifecycle_inventory_type is set.
    lifecycle_inventory_basis: str | None = None
    # ACTIVATION_REQUIREMENTS this state has satisfied. A production state
    # must satisfy all of them; a non-production state may satisfy some.
    activation: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not STATE_CODE_RE.match(self.code):
            raise ValueError(f"state code must be two capital letters: {self.code!r}")
        if not self.name.strip():
            raise ValueError("state name required")
        units = {u.value for u in PublishingUnit}
        for u in self.publishing_units:
            if u not in units:
                raise ValueError(f"unknown publishing unit {u!r}")
        if not self.publishing_units:
            raise ValueError("at least one publishing unit required")
        if (self.lifecycle_inventory_type is None) != (self.lifecycle_inventory_basis is None):
            raise ValueError("lifecycle_inventory_type and lifecycle_inventory_basis go together")
        unknown = set(self.activation) - set(ACTIVATION_REQUIREMENTS)
        if unknown:
            raise ValueError(f"unknown activation requirement(s): {sorted(unknown)}")
        if self.production and set(self.activation) != set(ACTIVATION_REQUIREMENTS):
            raise ValueError(f"{self.code}: a production state must satisfy every activation requirement")

    @property
    def activated(self) -> bool:
        return self.production and set(ACTIVATION_REQUIREMENTS) <= set(self.activation)


_STATES: dict[str, StateConfig] = {}


def _register(cfg: StateConfig) -> StateConfig:
    _STATES[cfg.code] = cfg
    return cfg


ALL_REQUIREMENTS = frozenset(ACTIVATION_REQUIREMENTS)

FL = _register(StateConfig(
    code="FL", name="Florida", publishing_units=(PublishingUnit.COUNTY.value,),
    production_inventory_types=frozenset({"POST_SALE_FIXED_PRICE"}),
    lifecycle_inventory_type="POST_SALE_FIXED_PRICE", production=True,
    lifecycle_inventory_basis="harvester constant (F.S. 197.502(7) Lands Available list)",
    activation=ALL_REQUIREMENTS))
TX = _register(StateConfig(
    code="TX", name="Texas", publishing_units=(PublishingUnit.COUNTY.value,),
    production_inventory_types=frozenset({"", "STRUCK_OFF_HELD_IN_TRUST", "FUTURE_RESALE"}),
    lifecycle_inventory_type=None, production=True, activation=ALL_REQUIREMENTS))
# Alabama (2026-09-29): the researched concept is state-held tax-delinquent
# land sold by the Alabama Department of Revenue (Property Tax Division /
# State Land Commissioner), published per county, with the price quoted on
# application rather than an auction opening bid. Everything about it so far
# is SEARCH-INDEX evidence (the 50-state audit, 2026-09-29): no page or
# document has been fetched from this repository (2026-09-30: the agency's
# own page titles, URLs, query strings and snippets were seen in a web
# search - still search-index evidence, see the adapter's ADOR_EVIDENCE).
# Registered so the model can represent it; NOT production; no activation
# requirement satisfied. See docs/alabama-onboarding.md and
# harvesters/otc/adapters/alabama.py.
AL = _register(StateConfig(
    code="AL", name="Alabama", publishing_units=(PublishingUnit.STATE.value, PublishingUnit.COUNTY.value),
    production_inventory_types=frozenset({"STATE_HELD_TAX_LAND"}),
    # What the lifecycle WOULD stamp once the state is activated and
    # migration 020 makes the value storable (lifecycle_inventory() refuses
    # both conditions today). The basis is the source's own indexed wording.
    lifecycle_inventory_type="STATE_HELD_TAX_LAND",
    lifecycle_inventory_basis="ADOR: 'tax delinquent properties currently in State inventory' (land sold to the State; "
                              "search-index evidence 2026-09-30, harvesters/otc/adapters/alabama.py ADOR_EVIDENCE)",
    production=False, activation=frozenset()))

# Arkansas (2026-09-30): the Commissioner of State Lands' Post Auction
# Sales List - parcels certified to the State that did not sell at the
# initial public auction, offered per county, bid through the State's own
# online auction. Search-index evidence only (harvesters/otc/adapters/
# arkansas.py COSL_EVIDENCE); registered, NOT production, no requirement
# satisfied.
AR = _register(StateConfig(
    code="AR", name="Arkansas", publishing_units=(PublishingUnit.STATE.value, PublishingUnit.COUNTY.value),
    production_inventory_types=frozenset({"POST_SALE"}),
    lifecycle_inventory_type="POST_SALE",
    lifecycle_inventory_basis="COSL: 'Post Auction Sales List' - parcels not sold at the initial public auction, offered by "
                              "the State (search-index evidence 2026-09-30, harvesters/otc/adapters/arkansas.py COSL_EVIDENCE)",
    production=False, activation=frozenset()))
# Louisiana (2026-09-30): adjudicated property - property adjudicated to a
# parish or municipality after no one bought it at the tax sale. The source
# is East Baton Rouge's open-data dataset (harvesters/otc/adapters/
# louisiana.py EBR_EVIDENCE). ACTIVATED 2026-09-30 (state-expansion sprint):
# every requirement below was established from the LIVE source (manual
# evidence runs 36752875012 / 36753767965, docs/state-expansion.md) and the
# owner approved publication of the dated list. Coverage is ONE parish.
LA = _register(StateConfig(
    code="LA", name="Louisiana", publishing_units=(PublishingUnit.PARISH.value, PublishingUnit.MUNICIPALITY.value),
    production_inventory_types=frozenset({"ADJUDICATED_PROPERTY"}),
    lifecycle_inventory_type="ADJUDICATED_PROPERTY",
    lifecycle_inventory_basis="East Baton Rouge open data: 'If no one buys the property at the tax sale, the property will then be "
                              "adjudicated to the Parish of East Baton Rouge in compliance with the laws of the State of Louisiana' "
                              "(dataset a4h4-zi7e description, read live 2026-09-30)",
    production=True, activation=ALL_REQUIREMENTS))

# Arizona (2026-09-30): the first state whose only concrete source is a
# LIENS & CERTIFICATES product - the Maricopa County Treasurer's "Current
# State CP Listing" (certificates of purchase held by the State, bought by
# assignment). No AVAILABLE inventory type; no auction source configured.
# Search-index evidence (harvesters/otc/adapters/arizona.py MARICOPA_EVIDENCE);
# registered, NOT production.
AZ = _register(StateConfig(
    code="AZ", name="Arizona", publishing_units=(PublishingUnit.COUNTY.value,),
    production_inventory_types=frozenset({""}),
    lifecycle_inventory_type=None, production=False, activation=frozenset()))

# ---- Six-state expansion (2026-10-01) -------------------------------------
# Each source below was read LIVE by the manual evidence job (runs
# 36778382226, 36779189506, 36780071129 and pass 4, 2026-09-30) and approved
# for publication by the owner on 2026-09-30 knowing no explicit reuse
# licence is published (docs/six-state-expansion.md). The per-source
# configurations are harvesters/otc/adapters/expansion.py; the per-state
# requirement evidence is EXPANSION_EVIDENCE below. Their inventory is
# AUCTIONS (MI, WY, SC, WI) or LIENS & CERTIFICATES (CO) - no AVAILABLE
# inventory type is asserted for any of them.
EXPANSION_EVIDENCE: dict[str, dict[str, str]] = {}


def _expansion(code: str, name: str, source_of_record: str, coverage: str, identifier: str, semantics: str,
               purchase: str, amount: str) -> StateConfig:
    EXPANSION_EVIDENCE[code] = {
        "source_of_record_identified": source_of_record,
        "live_source_verified": "read by the manual evidence job (job=evidence, evidence_scope=expansion), runs 36778382226 / "
                                "36779189506 / 36780071129 / pass 4, 2026-09-30",
        "publishing_unit_coverage_established": coverage,
        "identifier_format_established": identifier,
        "inventory_semantics_established": semantics,
        "purchase_path_established": purchase,
        "amount_semantics_established": amount,
        "parser_fixture_validated": "tests/python/fixtures/expansion/ carries the LIVE column names verbatim with synthetic "
                                    "values in the live shapes; the shared adapter parses it deterministically",
        "governance_approved": "owner publication decision 2026-09-30 (no explicit reuse licence published by the source)",
        "production_registry_authorized": "owner decision 2026-09-30 (docs/six-state-expansion.md)",
    }
    return _register(StateConfig(code=code, name=name, publishing_units=(PublishingUnit.COUNTY.value,),
                                 production_inventory_types=frozenset({""}), lifecycle_inventory_type=None,
                                 production=True, activation=ALL_REQUIREMENTS))


MI = _expansion("MI", "Michigan",
                "Eaton County Treasurer 'For Sale 2026' layer and Lenawee County '2026 Tax Sale' layer (county ArcGIS items)",
                "two counties (Eaton, Lenawee); the other 81 are not covered",
                "the layers' own parcel attributes: Eaton lparcel (shapes 999-999-999-999-99 / 99-99-99-99-999-999), Lenawee TAXID",
                "parcels offered at the county treasurer's foreclosure / tax sale auction; Eaton publishes its own 'Has Been Sold' flag",
                "no purchase link on the layer; the auction itself is the path",
                "MinBid / minbid = the published minimum bid (OPENING_BID)")
WY = _expansion("WY", "Wyoming",
                "Albany County Treasurer '2026 tax sale properties, 1st list' layer",
                "one county (Albany); the other 22 are not covered",
                "the layer's accountno (case) and pidn (parcel) attributes",
                "parcels on the Treasurer's 2026 tax sale list - a lien sale; no certificate exists before the sale (AUCTIONS)",
                "no purchase link on the layer",
                "TOTAL has no alias saying what it totals -> PUBLISHED_AMOUNT_KIND_UNSPECIFIED, never called a bid")
SC = _expansion("SC", "South Carolina",
                "York County 'Tax Sale Properties 2026 View' layer",
                "one county (York); the other 45 are not covered",
                "the layer's TAXMAPID ('Tax Parcel ID') attribute",
                "parcels on the county's tax sale property list (AUCTIONS)",
                "no purchase link on the layer",
                "no amount published -> NOT_PUBLISHED")
CO = _expansion("CO", "Colorado",
                "Morgan County Treasurer 'County Held Tax Lien Sale Certificates' page",
                "one county (Morgan); the other 63 are not covered",
                "CERT # (shape 9999-99999) is the record id; ACCT # (shape A999999) the county account",
                "county-held tax lien sale certificates, which 'may be purchased ... for the amount shown' (LIENS & CERTIFICATES)",
                "buy from the Morgan County Treasurer (the page's own words); no online purchase link",
                "'Purchase Amount to <date>' = the fixed purchase amount good to the date in the header (FIXED_PURCHASE_PRICE)")
WI = _expansion("WI", "Wisconsin",
                "Green County 'Current Tax Deed Sales' page (Current/Upcoming Sales and Previous Sales tables)",
                "one county (Green); the other 71 are not covered",
                "Tax Parcel Number (shapes 99999 9999 9999 / 99-999 9999.9999)",
                "county tax-deed sales by sealed bid; the Previous Sales table publishes completed sales with a Sale Price",
                "sealed bid form to the County Clerk (page); no online purchase link",
                "Minimum Bid Amount = the published minimum bid (OPENING_BID); Sale Price = a published result")

# West Virginia (2026-10-01): the State Auditor's statewide land-sale /
# certified-lands search (statuses CERTIFIED, SOLD, REDEEMED, NO BID,
# DEEDED...). Owner-approved for publication, but NOT activated: its county
# list loads through client script the evidence job could not reproduce
# deterministically, so no parser exists (docs/six-state-expansion.md).
WV = _register(StateConfig(
    code="WV", name="West Virginia", publishing_units=(PublishingUnit.STATE.value, PublishingUnit.COUNTY.value),
    production_inventory_types=frozenset({""}), lifecycle_inventory_type=None, production=False,
    activation=frozenset({"source_of_record_identified", "live_source_verified", "publishing_unit_coverage_established",
                          "inventory_semantics_established", "governance_approved"})))
# Utah (2026-10-01): UGRC's statewide parcels + LIR (CC BY 4.0) are approved
# for enrichment, but no current inventory source exists (Utah County: 'No
# properties are available for auction at this time'; next sale May 2027).
# NOT activated: a state without inventory would be an empty market.
UT = _register(StateConfig(
    code="UT", name="Utah", publishing_units=(PublishingUnit.COUNTY.value,),
    production_inventory_types=frozenset({""}), lifecycle_inventory_type=None, production=False,
    activation=frozenset({"governance_approved"})))

# States whose rows may exist in public.properties: exactly the activated ones.
PRODUCTION_STATES = frozenset(code for code, cfg in _STATES.items() if cfg.activated)


def get_state(code: str) -> StateConfig | None:
    return _STATES.get(code)


def is_supported(code: str) -> bool:
    return code in _STATES


def supported_states() -> frozenset[str]:
    return frozenset(_STATES)


def is_activated(code: str) -> bool:
    """May this state's sources run and its rows exist in production? Only
    a production state that satisfies every ACTIVATION_REQUIREMENTS item."""
    cfg = _STATES.get(code)
    return bool(cfg) and cfg.activated


def activation_blockers(code: str) -> list[str]:
    """The activation requirements a state has NOT satisfied (all of them
    for an unregistered code), in ACTIVATION_REQUIREMENTS order."""
    cfg = _STATES.get(code)
    if cfg is None:
        return ["not_registered", *ACTIVATION_REQUIREMENTS]
    missing = [r for r in ACTIVATION_REQUIREMENTS if r not in cfg.activation]
    if not cfg.production and "production_registry_authorized" not in missing:
        missing.append("production_registry_authorized")
    return missing


def state_problems(code: str) -> list[str]:
    """Why a state code is not acceptable, as strings. Empty = acceptable."""
    if not isinstance(code, str) or not STATE_CODE_RE.match(code or ""):
        return [f"state {code!r} is not a two-letter code"]
    if code not in _STATES:
        return [f"state {code!r} is not a registered state (harvesters/governance/states.py)"]
    return []


@contextmanager
def registered(cfg: StateConfig):
    """Temporarily register a state (tests only). Refuses to shadow a
    production state so FL/TX configuration can never be altered this way."""
    if cfg.code in PRODUCTION_STATES:
        raise ValueError(f"{cfg.code} is a production state and cannot be re-registered")
    previous = _STATES.get(cfg.code)
    _STATES[cfg.code] = cfg
    try:
        yield cfg
    finally:
        if previous is None:
            _STATES.pop(cfg.code, None)
        else:
            _STATES[cfg.code] = previous
