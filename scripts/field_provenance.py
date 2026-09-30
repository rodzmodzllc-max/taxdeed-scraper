#!/usr/bin/env python3
"""Per-column provenance for public.properties.field_provenance (the jsonb
column migration 009 added and, until 2026-09-29, nothing wrote).

Every enrichment writer that fills a `properties` column records WHICH
source supplied the value, so a later writer can tell a blank from a value
another source already supplied, and so a weaker source never replaces a
stronger one. The column is internal audit metadata (migration 012 withholds
it from get_properties()); it is never customer output.

Shape (one entry per column, keyed by the column name):

    {"legal_desc": {"source": "county_list", "source_id": "fl_laft_pdfs",
                    "recorded_at": "2026-09-29T12:00:00+00:00",
                    "list_url": "...", "document_url": "...",
                    "document_sha256": "...", "list_as_of": "2026-09-15"},
     "acreage":    {"source": "fdor_nal", "recorded_at": "...",
                    "matched_parcel_id": "..."}}

PRECEDENCE RULE (documented here, enforced by may_write()):

  1. A blank column may be filled by any source.
  2. A column that already holds a value is replaced only by a source of
     STRICTLY higher rank. Equal rank never overwrites - the first
     government source in stays, because neither the county's own list nor
     the statewide tax roll is provably fresher than the other for the
     same field.
  3. hand_research outranks every pipeline source (a person looked); the
     pipeline never touches a hand-researched value.
  4. A stored value with NO provenance entry (written before this module
     existed, or by a sync) is treated as rank UNKNOWN_RANK: a pipeline
     source may not overwrite it either, except through the writer's own
     pre-existing rule set (scripts/enrich_property_details.py's
     build_update_fields keeps its documented fill-blank / straight-write
     columns; this module only adds the "never clobber a provenanced
     value" layer on top).

Standard library only.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

RANK = {
    "hand_research": 3,
    "county_list": 2,      # the county's own Lands Available list (harvest row)
    "fdor_nal": 2,         # FDOR statewide cadastral / NAL tax-roll layer
    "county_gis": 2,       # a county-run parcel layer (Santa Rosa, Flagler)
    "statewide_parcel": 2, # a state's statewide parcel / assessment layer (harvesters/enrichment/parcels.py) - FDOR's peer
    "vendor_listing": 1,   # a vendor/counsel listing (LGBS, RealAuction)
}
UNKNOWN_RANK = 2  # a value with no entry: treated like a government source
SOURCES = frozenset(RANK)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def provenance_entry(source: str, **meta) -> dict:
    """One provenance entry. `source` must be a known source; metadata keys
    with a None value are dropped so the stored JSON says only what is
    known."""
    if source not in SOURCES:
        raise ValueError(f"unknown provenance source {source!r}")
    entry = {"source": source, "recorded_at": meta.pop("recorded_at", None) or now_iso()}
    for k, v in meta.items():
        if v is not None:
            entry[k] = v
    return entry


def load_provenance(value) -> dict:
    """The stored field_provenance as a dict (PostgREST returns jsonb as a
    parsed object; a legacy text value is tolerated; anything else is an
    empty dict)."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def merge_field_provenance(existing, updates: dict[str, dict]) -> dict:
    """existing (stored) + updates (column -> entry) -> the new jsonb value.
    Entries for columns not in `updates` are kept verbatim."""
    merged = load_provenance(existing)
    for column, entry in updates.items():
        if not isinstance(entry, dict) or entry.get("source") not in SOURCES:
            raise ValueError(f"invalid provenance entry for {column!r}")
        merged[column] = entry
    return merged


def is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def rank_of(entry) -> int:
    if not isinstance(entry, dict):
        return UNKNOWN_RANK
    return RANK.get(entry.get("source"), UNKNOWN_RANK)


def may_write(existing_provenance, column: str, new_source: str, current_value) -> bool:
    """The precedence rule above, for one column."""
    if new_source not in SOURCES:
        raise ValueError(f"unknown provenance source {new_source!r}")
    if is_blank(current_value):
        return True
    existing = load_provenance(existing_provenance).get(column)
    return RANK[new_source] > rank_of(existing)


def filter_by_provenance(row: dict, fields: dict, new_source: str, *, provenance_key: str = "field_provenance") -> dict:
    """Drop from `fields` every column the precedence rule forbids writing
    on `row`. A row with no provenance entry for a column keeps the writer's
    own rule (the value is only in `fields` because that rule allowed it),
    so only a PROVENANCED value of equal or higher rank blocks a write."""
    prov = load_provenance(row.get(provenance_key))
    kept = {}
    for column, value in fields.items():
        entry = prov.get(column)
        if entry is not None and not is_blank(row.get(column)) and RANK[new_source] <= rank_of(entry):
            continue
        kept[column] = value
    return kept
