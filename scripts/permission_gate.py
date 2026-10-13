"""Fail-closed source-permission check for the plain-directory scripts in
scripts/ (they are run as files, not as a package). One call per entry point,
before any request or write; harvesters/governance/permissions.py decides.

    import permission_gate as PG
    if not PG.allowed("fema_nfhl", ("fetch", "enrich"), state="US", label="enrich_flood_zone"):
        return 3
"""
from __future__ import annotations

import os
import sys

DENIED_EXIT = 3


def decide(source_id: str, operation: str, *, state: str, county: str | None = None, dataset: str | None = None):
    """The PermissionDecision, or None when governance cannot be loaded."""
    try:
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if repo not in sys.path:
            sys.path.insert(0, repo)
        from harvesters.governance import permissions as PERM  # noqa: PLC0415
        return PERM.authorize(source_id, operation, state=state, county=county, dataset=dataset)
    except Exception:  # noqa: BLE001 - no governance means no permission
        return None


def allowed(source_id: str, operations, *, state: str, county: str | None = None, dataset: str | None = None,
            label: str = "", level: str = "error") -> bool:
    """True only when every operation is permitted. Prints one workflow
    annotation (no data values) when it is not."""
    for op in operations:
        d = decide(source_id, op, state=state, county=county, dataset=dataset)
        if d is None or not d.allowed:
            code = "GOVERNANCE_UNAVAILABLE" if d is None else d.reason_code
            why = "permission configuration could not be loaded" if d is None else d.reason
            print(f"::{level} title={label or source_id}::{source_id} {op} not permitted [{code}] {why} - "
                  f"0 requests made, nothing written", flush=True)
            return False
    return True
