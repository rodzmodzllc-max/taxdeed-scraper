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


def publishable(row) -> bool:
    return row is not None and effective_publication(row) in PUBLISHABLE_STATUSES


def decision(row) -> str:
    return effective_publication(row) if row is not None else "UNREGISTERED"
