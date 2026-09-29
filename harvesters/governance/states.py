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

FL and TX are the only production states. Nothing else is registered in
code; tests register a hypothetical state through `registered()` and
unregister it again. There is no environment-variable or file-based
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


_STATES: dict[str, StateConfig] = {}


def _register(cfg: StateConfig) -> StateConfig:
    _STATES[cfg.code] = cfg
    return cfg


FL = _register(StateConfig(
    code="FL", name="Florida", publishing_units=(PublishingUnit.COUNTY.value,),
    production_inventory_types=frozenset({"POST_SALE_FIXED_PRICE"}),
    lifecycle_inventory_type="POST_SALE_FIXED_PRICE", production=True,
    lifecycle_inventory_basis="harvester constant (F.S. 197.502(7) Lands Available list)"))
TX = _register(StateConfig(
    code="TX", name="Texas", publishing_units=(PublishingUnit.COUNTY.value,),
    production_inventory_types=frozenset({"", "STRUCK_OFF_HELD_IN_TRUST", "FUTURE_RESALE"}),
    lifecycle_inventory_type=None, production=True))

PRODUCTION_STATES = frozenset({"FL", "TX"})


def get_state(code: str) -> StateConfig | None:
    return _STATES.get(code)


def is_supported(code: str) -> bool:
    return code in _STATES


def supported_states() -> frozenset[str]:
    return frozenset(_STATES)


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
