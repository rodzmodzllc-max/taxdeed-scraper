#!/usr/bin/env python3
"""The publication decision a state-adapter harvest and sync act on
(five-state enrichment sprint, 2026-10-01).

One rule for scripts/harvest_expansion.py and scripts/sync_state_inventory.py:

    effective publication = the registry CSV's publication_status, with the
    latest VALID admin review (public.source_publication_reviews, written
    from the app's admin panel) applied on top - the same apply_reviews()
    and the same validation scripts/publication_gate.py uses - and the two
    non-negotiable overrides (a blocked vendor is BLOCKED; a source under
    legal review is at most RESTRICTED).

Only APPROVED / APPROVED_GRANDFATHERED is publishable. A source that is
implemented and live-verified but UNREVIEWED (its owner has not taken a
publication decision) is NOT requested on a schedule and none of its rows
is written: approving it in the admin panel is what turns it on - no code
change. A review the validator refuses (e.g. APPROVED on a source that is
not PRODUCTION_VERIFIED) changes nothing.

Without credentials (tests, fixture runs) the CSV alone decides.

Collection vs customer publication (2026-10-02). Publication is a CUSTOMER
release decision; it no longer decides whether development can see the data.
`collectable()` is the collection rule: an AVAILABLE (laft) source is
collected, synced and shown to admins / customer preview whatever its review
state, unless the source is BLOCKED (a hard block - never requested). Its rows
carry their publication_status, so the frontend can keep customers on the
publication rule (app.js isCustomerPublishable / PUBLICATION_MODE). Auction and
lien sources keep the stricter rule (collected only once publishable) - this
change does not alter auction or certificate logic.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(REPO))
from harvesters.governance.county_source_registry import load_registry  # noqa: E402
from harvesters.governance.publication import PUBLISHABLE_STATUSES, effective_publication  # noqa: E402

REGISTRY = REPO / "data" / "county_source_registry.csv"


def registry_with_reviews(state: str, *, path: Path = REGISTRY, reviews: dict | None = None,
                          url: str | None = None, key: str | None = None) -> tuple[dict, dict]:
    """(source_id -> registry row with the latest valid review applied,
    report). `reviews` may be injected (tests); otherwise they are read
    with the service key when one is set."""
    import publication_gate as PG  # noqa: PLC0415 - shares its review machinery
    rows = load_registry(path)
    report: dict = {"reviews": "not read (no credentials)"}
    if reviews is None:
        url = url if url is not None else os.environ.get("SUPABASE_URL")
        key = key if key is not None else os.environ.get("SUPABASE_SERVICE_KEY")
        if url and key:
            api = PG.Api(url, key, dry_run=True)
            reviews = PG.fetch_reviews(api) if api.has_reviews_table() else {}
    if reviews is not None:
        rows, rep = PG.apply_reviews(rows, reviews)
        report = {"reviews": rep}
    return {r.source_id: r for r in rows if r.state == state}, report


def permitted(source_id, operation: str, state: str, county: str | None = None):
    """The per-operation permission decision (harvesters/governance/permissions.py)
    for a registry source. Fail closed: any error is a denial."""
    from harvesters.governance import permissions as PERM  # noqa: PLC0415
    return PERM.authorize(source_id, operation, state=state, county=county)


def publishable(row) -> bool:
    """Customer publication: the registry / admin-review decision AND a
    recorded `display` permission for the source (2026-10-12)."""
    if row is None or effective_publication(row) not in PUBLISHABLE_STATUSES:
        return False
    # The `display` record for each ledger this source feeds (a Florida record
    # names its ledger's listing dataset); allowed when any of them allows it.
    from harvesters.governance import permissions as PERM  # noqa: PLC0415
    ledgers = sorted(getattr(row, "ledger_set", None) or [])
    return any(PERM.listing_display(row.source_id, state=row.state, ledger=lg).allowed for lg in (ledgers or [None]))


# A hard block: never requested, never written, never shown - not even to admins.
COLLECTION_BLOCKED = frozenset({"BLOCKED"})


def owner_collection(row) -> bool:
    """Owner decision 2026-10-26 ("find every property and every source, and then
    we'll work on the legal"): the new-sources sprint's sources are collected for
    EVERY ledger - auctions and liens too, not only AVAILABLE - while their
    publication stays UNREVIEWED (admins see them labelled; customers do not).
    The recorded permission (condition 2 of collectable()) is still required."""
    try:
        from harvesters.otc.adapters import expansion as EX  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - fail closed
        return False
    return row is not None and row.source_id in EX.NEW_SOURCE_IDS


def collectable(row, record_source: str, operation: str = "fetch") -> bool:
    """May this source be requested (operation "fetch") or its rows written
    (operation "store")? Two independent conditions, both required:

      1. the publication rule - publishable sources always; an AVAILABLE
         (laft) source awaiting review too (UNREVIEWED / RESTRICTED - a review
         status, not a prohibition); a BLOCKED source never;
      2. a recorded permission for that operation (data/source_permissions.csv),
         which fails closed when missing, expired or unreadable."""
    if row is None:
        return False
    if not (publishable(row) or ((record_source == "laft" or owner_collection(row))
                                 and effective_publication(row) not in COLLECTION_BLOCKED)):
        return False
    return permitted(row.source_id, operation, row.state).allowed


def permission_decision(row, operation: str) -> str:
    """'' when allowed, else the permission reason code (for gate reports)."""
    if row is None:
        return "UNREGISTERED"
    d = permitted(row.source_id, operation, row.state)
    return "" if d.allowed else f"PERMISSION_{d.reason_code}"


def decision(row, record_source: str = "", operation: str = "fetch") -> str:
    """Why a source is or is not collected: its publication decision, or
    PERMISSION_<code> when the publication rule would collect it but its
    permission record does not allow `operation`."""
    if row is None:
        return "UNREGISTERED"
    pub = effective_publication(row)
    rule_ok = pub in PUBLISHABLE_STATUSES or ((record_source == "laft" or owner_collection(row)) and pub not in COLLECTION_BLOCKED)
    if rule_ok and record_source:
        why = permission_decision(row, operation)
        if why:
            return why
    return pub
