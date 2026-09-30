"""The statewide parcel / assessment sources the enrichment factory may use,
one ParcelSourceConfig per state (six-state expansion sprint).

A config here is a description of a live layer, not permission: the
factory's `enrichment_allowed()` still refuses any source whose columns
were not verified live or whose publication decision is not APPROVED.
Evidence for every value below is the manual evidence run named in each
config's `notes` (docs/six-state-expansion.md).
"""
from __future__ import annotations

from .parcels import ParcelSourceConfig

PARCEL_SOURCES: dict[str, ParcelSourceConfig] = {}


def register(cfg: ParcelSourceConfig) -> ParcelSourceConfig:
    if cfg.state in PARCEL_SOURCES:
        raise ValueError(f"{cfg.state} already has a statewide parcel source")
    PARCEL_SOURCES[cfg.state] = cfg
    return cfg


def for_state(state: str) -> ParcelSourceConfig | None:
    return PARCEL_SOURCES.get(state)
