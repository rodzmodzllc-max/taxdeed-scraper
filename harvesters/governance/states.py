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

FL and TX are the only production states. AL (Alabama, 2026-09-29) is
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
# parish or municipality after no one bought it at the tax sale. The first
# concrete source is East Baton Rouge's open-data dataset (harvesters/otc/
# adapters/louisiana.py EBR_EVIDENCE). Registered, NOT production.
LA = _register(StateConfig(
    code="LA", name="Louisiana", publishing_units=(PublishingUnit.PARISH.value, PublishingUnit.MUNICIPALITY.value),
    production_inventory_types=frozenset({"ADJUDICATED_PROPERTY"}),
    lifecycle_inventory_type="ADJUDICATED_PROPERTY",
    lifecycle_inventory_basis="parish open data: 'adjudicated to the Parish ... in compliance with the laws of the State of "
                              "Louisiana' (search-index evidence 2026-09-30, harvesters/otc/adapters/louisiana.py EBR_EVIDENCE)",
    production=False, activation=frozenset()))

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
