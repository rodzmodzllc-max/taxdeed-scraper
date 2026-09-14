"""Reusable ingestion / customer-output enforcement gate - Phase 10A Step 4
and Step 8.

Three call sites use this module in this repo as of Phase 10A:

  1. harvesters/texas_harvester.py's main() - checked BEFORE a harvest_*()
     function is ever called, so a LEGAL_REVIEW_REQUIRED/BLOCKED/DISABLED/
     TERMS_CHANGED source's harvester never runs at all (primary
     enforcement point).
  2. scripts/sync-texas-to-supabase.py - checked again, per-row, before a
     row is included in the Supabase upsert payload (defense-in-depth: if
     out/harvest_texas.json was ever produced or hand-edited outside
     main()'s own gate check, this second check still catches it before
     the row becomes customer-visible - this table has no field-level RLS,
     so "reaches `properties`" and "customer-visible" are effectively the
     same event today, which is exactly why this is the second and last
     real chokepoint that exists in this codebase's current architecture).
  3. Available for a future customer/API layer (filter_rows_for_customer_output /
     filter_rows_for_api_export below) - not yet wired into public/app.js or
     any export feature, because no APPROVED_WITH_RESTRICTIONS source
     exists yet that would need it; documented as a known gap in
     docs/data-licensing.md rather than built speculatively (Phase 10A
     Step 8's "do not build a new customer API if one already exists" -
     there IS an existing customer path, the Supabase `properties` table
     itself, and gate #2 above is this phase's integration into it).

FAIL-CLOSED, throughout: an unknown source_id, a status this module
doesn't recognize as one of the two INGESTION_ALLOWED_STATUSES, or a
missing/empty source_id are all treated as "not allowed" - never as
approved. See test_source_governance.py's test_unknown_source_fails_closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from .registry import INGESTION_ALLOWED_STATUSES, SourceStatus, get_source
from .restrictions import BLOCKS_API_EXPORT, BLOCKS_CUSTOMER_DISPLAY, Restriction


@dataclass(frozen=True)
class GateDecision:
    source_id: str
    allowed: bool
    status: SourceStatus
    restrictions: tuple[Restriction, ...]
    reason: str


def check_ingestion_gate(source_id: str | None) -> GateDecision:
    """The single reusable enforcement decision. Never raises - always
    returns a GateDecision, so a caller cannot accidentally proceed past
    an exception without checking `.allowed` first."""
    if not source_id:
        return GateDecision(
            source_id=source_id or "",
            allowed=False,
            status=SourceStatus.LEGAL_REVIEW_REQUIRED,
            restrictions=(),
            reason="empty/missing source_id - fails closed as LEGAL_REVIEW_REQUIRED, never treated as approved",
        )

    record = get_source(source_id)
    if record is None:
        return GateDecision(
            source_id=source_id,
            allowed=False,
            status=SourceStatus.LEGAL_REVIEW_REQUIRED,
            restrictions=(),
            reason=(
                f"'{source_id}' is not in the source registry - unknown sources fail closed as "
                "LEGAL_REVIEW_REQUIRED and are never treated as approved (missing != approved)"
            ),
        )

    allowed = record.legal_status in INGESTION_ALLOWED_STATUSES
    if allowed:
        reason = f"'{source_id}' is {record.legal_status.value} - ingestion permitted"
        if record.restrictions:
            reason += f", subject to restrictions: {', '.join(r.value for r in record.restrictions)}"
    else:
        reason = f"'{source_id}' is {record.legal_status.value} - ingestion NOT permitted"

    return GateDecision(
        source_id=source_id,
        allowed=allowed,
        status=record.legal_status,
        restrictions=record.restrictions,
        reason=reason,
    )


def filter_rows_for_customer_output(rows: list, source_id: str) -> list:
    """Given a list of already-harvested rows (any shape with attribute or
    dict access is fine - this function never reads a row's fields, only
    counts them) from ONE source, return the subset that may reach a
    customer-visible surface. Returns [] entirely if the gate itself
    rejects the source, or if the source carries a restriction in
    BLOCKS_CUSTOMER_DISPLAY (no_customer_display / no_redistribution /
    source_only_display) - those restrictions currently apply at the
    whole-source level (this codebase has no per-field customer-output
    path yet to enforce a narrower, field-specific restriction against -
    see docs/data-licensing.md's "Remaining risks" section for the honest
    gap this leaves for a future APPROVED_WITH_RESTRICTIONS source with a
    field_specific_restriction)."""
    decision = check_ingestion_gate(source_id)
    if not decision.allowed:
        return []
    if any(r in BLOCKS_CUSTOMER_DISPLAY for r in decision.restrictions):
        return []
    return list(rows)


def filter_rows_for_api_export(rows: list, source_id: str) -> list:
    """Same shape as filter_rows_for_customer_output, but for an API/export
    surface specifically - a stricter check (BLOCKS_API_EXPORT is a
    superset of BLOCKS_CUSTOMER_DISPLAY), since a source may be fine for
    in-app display but still carry `no_api_export`/rate-limit-only
    restrictions."""
    decision = check_ingestion_gate(source_id)
    if not decision.allowed:
        return []
    if any(r in BLOCKS_API_EXPORT for r in decision.restrictions):
        return []
    return list(rows)
