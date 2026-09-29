"""Over-the-counter / struck-off / future-resale inventory framework.

The data contract (`model.OtcRecord`), the run gate (`gate`), the generic
tabular list adapter (`adapters.tabular`) and the bridge that describes the
existing LGBS rows in the same vocabulary (`lgbs_bridge`).

What is deliberately NOT here: a single live Texas government source
adapter. Every Texas government list the 2026-09-29 audit found is
SEARCH_EVIDENCE_ONLY in data/county_source_registry.csv - none has been
fetched and read from this repository - so `gate.evaluate_source()` refuses
all of them, and the adapter is exercised only on fixtures. Verification
(fetch, read, record columns and terms) is the step that comes before any
of them can run; that step is a human's, not this package's.
"""

from .model import (DB_SUPPORTED_AMOUNT_KINDS, DB_SUPPORTED_INVENTORY_TYPES, AmountKind, InventoryType,
                    OtcRecord, PurchaseUrlKind, SourceAuthority, UrlRef)

__all__ = ["AmountKind", "DB_SUPPORTED_AMOUNT_KINDS", "DB_SUPPORTED_INVENTORY_TYPES", "InventoryType",
           "OtcRecord", "PurchaseUrlKind", "SourceAuthority", "UrlRef"]
