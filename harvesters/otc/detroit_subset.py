"""Detroit Land Bank customer-facing subset (2026-10-03).

A VISIBILITY rule between the full collected inventory and the publication
gate. It never deletes, closes, rejects or reclassifies a row, and it never
changes a source's publication decision:

    SOURCE COLLECTION -> FULL ADMIN INVENTORY -> VERIFIED STRUCTURE FILTER
        -> DETERMINISTIC ~50% CUSTOMER SUBSET -> PUBLICATION GATE -> CUSTOMER

It applies ONLY to the two Detroit Land Bank Authority sources (Wayne County,
MI). Every other source - Oceana, Horry, Georgetown, FL, LA, TX and every
other state - is outside it and never capped.

**Verified structure.** The only structure indicator the DLBA publishes is
its own "DLBA Inventory Status" field (``inventory_status_socrata``, stored
as ``inventory_status_raw``). Only the value "Marketed Structure For Sale"
is an offered structure. The four "... Lot For Sale" values are vacant lots
by the source's own wording, and the DLBA's Vacant Land Policy defines Side,
Neighborhood and Oversize lots as "vacant residential property without a
structure". The programs layer (Own It Now / Renovation Programs / Economic
Development) publishes no structure field, so none of its records is
structure-qualified. A structure is never inferred from a program name,
address, size, value, imagery or zoning.

**Deterministic ~50% selection.** For a structure-qualified record, the key is
the source id and the parcel number as published, joined by "|". It is
hashed with 32-bit FNV-1a over its UTF-8 bytes. The record is in the
customer subset when ``hash % 100 < 50``. The same parcel is always in or
always out until the source's parcel number or status changes; database
order, time and randomness play no part. ``public/app.js``
(``detroitSubsetStatus``) implements the same rule, and
``tests/python/fixtures/detroit_subset_cases.json`` pins both to the same
answers.
"""
from __future__ import annotations

DETROIT_SOURCE_IDS = frozenset({"mi_detroit_landbank_lots", "mi_detroit_landbank_programs"})
# The one source whose own status field can say "structure".
STRUCTURE_SOURCE_ID = "mi_detroit_landbank_lots"
# The source's own status values that name an OFFERED structure
# (harvesters/otc/adapters/expansion.DLBA_STRUCTURE_STATUSES).
STRUCTURE_STATUSES = frozenset({"Marketed Structure For Sale"})
SUBSET_PERCENT = 50

# Reasons, as the app labels them for an admin. A record outside the subset
# is never "invalid", "closed" or "unavailable".
IN_SUBSET = "in_subset"
NOT_STRUCTURE = "not_structure"
NOT_SELECTED = "not_selected"

_FNV_OFFSET = 0x811C9DC5
_FNV_PRIME = 0x01000193


def fnv1a32(text: str) -> int:
    """32-bit FNV-1a over the UTF-8 bytes of ``text``."""
    h = _FNV_OFFSET
    for b in text.encode("utf-8"):
        h ^= b
        h = (h * _FNV_PRIME) & 0xFFFFFFFF
    return h


def selection_key(source_id: str, parcel: str) -> str:
    return f"{source_id}|{(parcel or '').strip()}"


def selected(source_id: str, parcel: str) -> bool:
    """The deterministic ~50% rule (structure is checked separately)."""
    return fnv1a32(selection_key(source_id, parcel)) % 100 < SUBSET_PERCENT


def is_detroit(row: dict) -> bool:
    return (row or {}).get("source_id") in DETROIT_SOURCE_IDS


def structure_qualified(row: dict) -> bool:
    """True only when the source's own status names an offered structure."""
    return (row.get("source_id") == STRUCTURE_SOURCE_ID
            and str(row.get("inventory_status_raw") or "").strip() in STRUCTURE_STATUSES)


def subset_status(row: dict) -> str | None:
    """None for a row outside the Detroit sources (never capped); otherwise
    IN_SUBSET, NOT_STRUCTURE or NOT_SELECTED."""
    if not is_detroit(row):
        return None
    if not structure_qualified(row):
        return NOT_STRUCTURE
    parcel = row.get("parcel") or row.get("case_no") or ""
    return IN_SUBSET if selected(row["source_id"], str(parcel)) else NOT_SELECTED


def in_customer_inventory(row: dict) -> bool:
    """The input to the publication gate: every non-Detroit row, plus the
    Detroit subset. Publication status is still decided by the gate."""
    return subset_status(row) in (None, IN_SUBSET)


def customer_inventory(rows: list[dict]) -> list[dict]:
    return [r for r in rows if in_customer_inventory(r)]


def summary(rows: list[dict]) -> dict:
    """Counts for the admin view and the docs: collected / structure-
    qualified / in the customer subset, Detroit only."""
    det = [r for r in rows if is_detroit(r)]
    qual = [r for r in det if structure_qualified(r)]
    return {"collected": len(det), "structure_qualified": len(qual),
            "customer_subset": sum(1 for r in qual if subset_status(r) == IN_SUBSET)}
