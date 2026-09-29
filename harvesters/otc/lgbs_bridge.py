"""How the existing Texas LGBS `laft` rows are represented in the OTC
vocabulary - without changing, re-fetching or re-attributing them.

The 421 rows in production (2026-09-29) were written by
scripts/sync-texas-to-supabase.py from harvesters/texas_harvester.py's
LGBS walk, where LGBS_STATUS_TO_LEDGER maps two raw statuses onto the
`laft` ledger. What is actually known about each row:

  - it came from LGBS, delinquent-tax counsel, not from the county
    (source_authority VENDOR_COUNSEL, source_id tx_lgbs);
  - its raw status, when the row carries tx_sale_status (migration 013;
    NULL on every row that predates the 2026-09-25 writer change);
  - no list/document/purchase URL (LGBS publishes none per property);
  - min_bid, the vendor's own figure with its own documented meaning.

Migration 017's backfill applies exactly `classify_lgbs_status()`; this
module is the same rule in Python so tests can pin the two together.
"""
from __future__ import annotations

from .model import InventoryType, SourceAuthority

LGBS_STATUS_TO_INVENTORY: dict[str, InventoryType] = {
    "Struck off to Jurisdiction": InventoryType.STRUCK_OFF_HELD_IN_TRUST,
    "Available for Future Sale": InventoryType.FUTURE_RESALE,
}


def classify_lgbs_status(tx_sale_status: str | None) -> InventoryType | None:
    """None when the raw status is absent or is not one of the two OTC
    statuses - never a guess between struck-off and future-resale."""
    if not tx_sale_status:
        return None
    return LGBS_STATUS_TO_INVENTORY.get(tx_sale_status.strip())


def lgbs_row_provenance(row: dict) -> dict:
    """The 017 columns for an existing LGBS laft row, from the row itself.
    Nothing here reads the vendor or invents a URL."""
    inv = classify_lgbs_status(row.get("tx_sale_status"))
    return {
        "source_authority": SourceAuthority.VENDOR_COUNSEL.value,
        "source_id": "tx_lgbs",
        "inventory_type": inv.value if inv else None,
        "list_url": None,
        "document_url": None,
        "purchase_url": None,
        "purchase_url_kind": None,
        "purchase_amount": None,          # min_bid keeps its own meaning; not reinterpreted
        "purchase_amount_kind": None,     # not classified by this migration
        "otc_provenance": {
            "source_id": "tx_lgbs",
            "authority": "delinquent-tax counsel publication, not a county document",
            "inventory_type": ("from the vendor's raw status (tx_sale_status)" if inv else
                               "unresolved: the row carries no raw status (pre-013 write) - not guessed"),
            "urls": "none published per property by the vendor",
        },
    }
