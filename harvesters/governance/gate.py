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
from .restrictions import BLOCKS_API_EXPORT, BLOCKS_CUSTOMER_DISPLAY, FIELD_SHAPE_KEYWORDS, Restriction


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


def _strip_restricted_field_shapes(row: dict, restrictions: tuple[Restriction, ...]) -> dict:
    """Return a NEW dict (the input `row` is never mutated - see
    test_row_projection_does_not_mutate_the_input_row) with any key whose
    name matches a field-shape keyword (restrictions.FIELD_SHAPE_KEYWORDS)
    for a restriction the source actually carries removed. A restriction
    with no entry in FIELD_SHAPE_KEYWORDS (e.g. RATE_LIMIT,
    ATTRIBUTION_REQUIRED, RETENTION_PERIOD, OTHER_CONTRACTUAL_RESTRICTION -
    restrictions that describe an obligation about HOW data is used, not
    WHICH field is restricted) has nothing to strip here by design; those
    are documented, not enforced by field removal, in
    docs/customer-api-data-enforcement.md."""
    projected = dict(row)
    for restriction in restrictions:
        keywords = FIELD_SHAPE_KEYWORDS.get(restriction)
        if not keywords:
            continue
        for key in list(projected.keys()):
            if any(kw in key.lower() for kw in keywords):
                del projected[key]
    return projected


def _project_row(row: dict, source_id: str, blocking_restrictions: frozenset[Restriction]) -> dict | None:
    """Shared implementation for project_row_for_customer_output() and
    project_row_for_api_export() below - both are the same two-step
    decision (whole-row gate, then field-shape stripping) against a
    different blocking-restriction set."""
    decision = check_ingestion_gate(source_id)
    if not decision.allowed:
        return None
    if any(r in blocking_restrictions for r in decision.restrictions):
        return None
    return _strip_restricted_field_shapes(row, decision.restrictions)


def project_row_for_customer_output(row: dict, source_id: str) -> dict | None:
    """Phase 11 (Customer/API Data-Restriction Enforcement): the per-row,
    field-aware counterpart to filter_rows_for_customer_output() above.
    Given ONE already-harvested row (any dict - a Supabase upsert payload
    row, in this codebase's actual usage) and the source_id it came from,
    returns:
      - None if the source fails the ingestion gate (see
        check_ingestion_gate) OR carries a restriction in
        BLOCKS_CUSTOMER_DISPLAY - the row must not reach a customer-visible
        surface at all.
      - Otherwise, a NEW dict (the input is never mutated) with any
        restricted-content-shaped field (raw HTML / images / documents -
        see restrictions.FIELD_SHAPE_KEYWORDS) removed, while every
        unrestricted field is passed through unchanged.

    This is deliberately the SAME governance decision
    (check_ingestion_gate + BLOCKS_CUSTOMER_DISPLAY) filter_rows_for_
    customer_output() already used for whole-source rejection - this
    function does not duplicate that logic, it extends it to field
    granularity. See scripts/sync-texas-to-supabase.py for this
    codebase's one real call site: in this application's architecture
    (a static frontend reading Supabase's `public.properties` table
    directly, with no application server and no field-level RLS - see
    docs/data-licensing.md), the row handed to the Supabase upsert IS the
    customer-facing representation, so this is where that representation
    must be projected."""
    return _project_row(row, source_id, BLOCKS_CUSTOMER_DISPLAY)


def project_row_for_api_export(row: dict, source_id: str) -> dict | None:
    """Same shape as project_row_for_customer_output(), but for an
    API/export surface specifically (BLOCKS_API_EXPORT, a superset of
    BLOCKS_CUSTOMER_DISPLAY - see restrictions.py). Not currently called
    by any production code path (this application has no export/API
    surface distinct from the customer-facing `properties` table itself -
    see docs/customer-api-data-enforcement.md's "Export path" section) -
    provided so a future distinct export/API feature has a ready,
    already-tested enforcement function to call rather than needing to
    reinvent one."""
    return _project_row(row, source_id, BLOCKS_API_EXPORT)
