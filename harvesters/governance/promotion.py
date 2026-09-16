"""Production source-promotion policy gate - Phase 37 (Production Source
Promotion Gate).

Repository audit finding (Phase 37 Section 1): before this module, this
project already had three separate, independently correct governance
layers, built up over Phases 10A/11/34A/34B/35/36:

  1. `registry.py`/`gate.py` (Phase 10A/11) - a whole-source, provider-
     agnostic ingestion gate: is `source_id`'s `legal_status` one of the
     two `INGESTION_ALLOWED_STATUSES`, plus a coarse "does a restriction
     block this surface" check.
  2. `authorization.py` (Phase 34A/34B) - a per-use, per-county refinement
     ON TOP OF (1): for a source that has an actual `ProviderAuthorization`
     record on file, is THIS SPECIFIC use authorized for THIS SPECIFIC
     county, as of THIS SPECIFIC date.
  3. `source_catalog.py` (Phase 35/36) - a discovery-stage catalog plus a
     narrower per-source terms/evidence ledger (`data/phase36_terms_review.csv`)
     for sources that are not, and mostly never will be, promoted into (1)
     at all.

Each of those layers already answers its own question correctly and is
already tested. What did NOT exist before this phase is ONE function that
answers Phase 37's actual question - "may THIS source be used for THIS
exact purpose" - by consulting whichever of the three layers actually has
data for that source_id, in a fixed, fail-closed order, and returning one
structured decision. This module is exactly that function
(`can_promote_source_for_use()`) and nothing else - it deliberately holds
NO new authorization data, NO new state machine, and NO parallel enum of
its own approval states. It re-exports and composes (1)-(3) unchanged.

Phase 37 Section 4's explicit instruction ("reuse the existing
authorization framework... do not create a competing authorization
architecture... if an extension is necessary, extend the existing
framework") is why `authorization.py` itself gained five new
`AuthorizationScope` dimensions (`caching`, `image_display`,
`image_download`, `document_display`, `document_download` - see that
module's own comments) rather than this module inventing a second,
parallel per-use vocabulary that would have to be kept in sync by hand.

Decision order for `can_promote_source_for_use(source_id, use, ...)`,
fail-closed at every step (an unresolved question at any layer denies -
it never falls through to a more permissive layer):

  1. If `source_id` is in NEITHER `SOURCE_REGISTRY`, NOR
     `PROVIDER_AUTHORIZATIONS` (at any county), NOR the Phase 36 terms-
     review ledger - deny with status UNKNOWN. An entirely unrepresented
     source_id is never treated as approved (Phase 37 Section 20's
     "discovery vs. production" distinction, taken to its logical
     conclusion: a source with NO governance record of any kind is,
     structurally, even further from production than a DISCOVERED one).

  2. If `source_id` IS in `SOURCE_REGISTRY`: run the existing whole-source
     ingestion gate (`gate.check_ingestion_gate`). A non-allowed
     `legal_status` (LEGAL_REVIEW_REQUIRED / BLOCKED / DISABLED /
     TERMS_CHANGED / unknown) denies immediately, citing that status - this
     never changes based on which `use` was asked about, because Phase 10A's
     whole-source gate was never meant to. An allowed `legal_status` also
     checks whether a whole-source `Restriction` blocks the SPECIFIC
     surface `use` maps to (the same `BLOCKS_CUSTOMER_DISPLAY`/
     `BLOCKS_API_EXPORT` sets `gate.py`'s own row-projection functions
     already use - never re-derived here).

  3. If `source_id` has at least one `ProviderAuthorization` record on file
     (at ANY county/deployment_scope - `authorizations_for_source()`): defer
     ENTIRELY to `authorization.check_authorized_use()`, using the mapped
     `AuthorizationScope` dimension for `use`. This is the exact,
     unmodified Phase 34A/34B decision - a source with even one
     authorization record on file is held to the strict "this specific use,
     this specific county, currently effective" standard, matching this
     project's own documented design rule (see `authorization.py`'s
     module-level comment on `authorized_for_ingestion`/`authorized_for_
     customer_output`/`authorized_for_api_export`).

  4. Otherwise (in `SOURCE_REGISTRY`, gate passed, ZERO authorization
     records anywhere): if the Phase 36 ledger has NO row for this
     source_id either, this is today's exact, unmodified production
     no-op path (`tx_lgbs`, `tx_realauction`, `fl_laft_pdfs` today) -
     allowed, matching current behavior byte-for-byte (Phase 37 Section 22's
     regression requirement).

  5. If `source_id` is NOT in `SOURCE_REGISTRY` at all, but IS in the Phase
     36 ledger (every FL Property Appraiser / TX Appraisal District /
     RealAuction-deployment / statewide row Phase 36 reviewed): deny,
     citing that ledger row's own `legal_status` and `evidence_reference`.
     Every ledger row is `LEGAL_REVIEW_REQUIRED` or `DISCOVERED` as of
     Phase 36 (`test_no_row_in_the_terms_review_ledger_is_approved`), so
     this branch always denies today - but it denies with the SPECIFIC,
     evidence-backed reason Phase 36 actually found, not a generic "unknown
     source" message, and it stays correct automatically if a future phase
     ever adds an `APPROVED` row to that ledger.

This module performs NO county harvesting, creates NO new scrapers, and
changes NO existing source's `legal_status`/`authorization_status`/ledger
`legal_status` (Phase 37's hard-stop list). It is read/decision logic only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .authorization import (
    ALL_USE_DIMENSIONS,
    authorization_for_scope,
    authorizations_for_source,
    check_authorized_use,
)
from .gate import check_ingestion_gate
from .registry import get_source
from .restrictions import BLOCKS_API_EXPORT, BLOCKS_CUSTOMER_DISPLAY, Restriction
from .source_catalog import load_terms_review

# Phase 37 Section 2's exact vocabulary - "do not reduce these into one
# boolean." Twelve purposes, no more, no fewer than Section 2 lists.
PROMOTION_USES: frozenset[str] = frozenset(
    {
        "INGEST",
        "STORE",
        "CACHE",
        "NORMALIZE",
        "DERIVE",
        "CUSTOMER_DISPLAY",
        "CUSTOMER_EXPORT",
        "API",
        "HISTORICAL_RETENTION",
        "IMAGE_DISPLAY",
        "IMAGE_DOWNLOAD",
        "DOCUMENT_DISPLAY",
        "DOCUMENT_DOWNLOAD",
    }
)

# The one place a Phase 37 promotion-use name is translated to the existing
# `AuthorizationScope` dimension name it reuses (Phase 34A/34B, extended
# this phase - see authorization.py). `API` maps to `api_redistribution`
# (this project's own customer-facing API/export surface), deliberately
# distinct from `authorization.py`'s separate `api_access` dimension (does
# an official API/feed exist that THIS PROJECT may consume as an input -
# an ingestion-side question, not a promotion-to-customers question, and
# not one of Section 2's twelve purposes).
PROMOTION_USE_TO_SCOPE_DIMENSION: dict[str, str] = {
    "INGEST": "automated_access",
    "STORE": "storage",
    "CACHE": "caching",
    "NORMALIZE": "normalization",
    "DERIVE": "derived_data",
    "CUSTOMER_DISPLAY": "customer_display",
    "CUSTOMER_EXPORT": "customer_export",
    "API": "api_redistribution",
    "HISTORICAL_RETENTION": "historical_storage",
    "IMAGE_DISPLAY": "image_display",
    "IMAGE_DOWNLOAD": "image_download",
    "DOCUMENT_DISPLAY": "document_display",
    "DOCUMENT_DOWNLOAD": "document_download",
}
assert set(PROMOTION_USE_TO_SCOPE_DIMENSION) == PROMOTION_USES, "every promotion use must map to exactly one scope dimension"
assert set(PROMOTION_USE_TO_SCOPE_DIMENSION.values()) <= ALL_USE_DIMENSIONS, "every mapped dimension must be a real AuthorizationScope field"

# Which whole-source Restriction set (gate.py's own, never re-derived) gates
# a given promotion use for a source with ZERO ProviderAuthorization
# records anywhere - i.e. today's actual no-op production path. A use with
# no entry here (INGEST/STORE/CACHE/NORMALIZE/DERIVE) is an internal/
# backend activity gate.py's existing restriction sets were never meant to
# cover - only the whole-source legal_status gates those.
_SURFACE_RESTRICTION_SETS: dict[str, frozenset[Restriction]] = {
    "CUSTOMER_DISPLAY": BLOCKS_CUSTOMER_DISPLAY,
    "IMAGE_DISPLAY": BLOCKS_CUSTOMER_DISPLAY,
    "DOCUMENT_DISPLAY": BLOCKS_CUSTOMER_DISPLAY,
    "CUSTOMER_EXPORT": BLOCKS_API_EXPORT,
    "API": BLOCKS_API_EXPORT,
    "IMAGE_DOWNLOAD": BLOCKS_API_EXPORT,
    "DOCUMENT_DOWNLOAD": BLOCKS_API_EXPORT,
}


@dataclass(frozen=True)
class PromotionDecision:
    """The structured decision Phase 37 Section 8 requires - never a bare
    boolean. `status` is always one of the recognized vocabulary strings
    (a `SourceStatus`/`AuthorizationStatus` value, the Phase 36 ledger's own
    `legal_status` value, or the literal `"UNKNOWN"` for a source with no
    governance record at all) - never a bespoke string invented per call
    site."""

    source_id: str
    use: str
    state: str | None
    county: str | None
    allowed: bool
    status: str
    reason: str
    evidence: str
    reviewed_at: str | None
    checked_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        """The exact key set Phase 37 Section 8's example shows, plus
        `state`/`checked_at` (this project's own `UseDecision`/`GateDecision`
        pattern of always including a real wall-clock timestamp of when the
        decision was computed)."""
        return {
            "allowed": self.allowed,
            "status": self.status,
            "reason": self.reason,
            "source_id": self.source_id,
            "state": self.state,
            "county": self.county,
            "use": self.use,
            "evidence": self.evidence,
            "reviewed_at": self.reviewed_at,
            "checked_at": self.checked_at,
        }


def _find_terms_review_row(source_id: str, county: str | None) -> dict[str, str] | None:
    """Exact `source_id` match against the Phase 36 ledger - no fuzzy or
    inferred cross-namespace mapping (Phase 37 Section 8's "do not invent
    unsupported evidence"). The ledger's own `source_id` values
    (`fl_property_appraiser__county__pinellas`, `tx_appraisal_district__
    county__harris`, `fl_realauction__county__miami_dade`, ...) are a
    DIFFERENT, deliberately more granular namespace than `SOURCE_REGISTRY`'s
    (`fl_realauction`, one entry for ~47 counties) - a caller asking about
    one of those ledger-only sources passes the ledger's own source_id
    directly, never `fl_realauction` plus a county string. If more than one
    row happens to share a `source_id` (not currently possible - the ledger
    has no duplicates, see `test_phase36_terms_review.py`'s isolation
    tests), `county` narrows it; otherwise the first match is returned."""
    rows = [r for r in load_terms_review() if r.get("source_id") == source_id]
    if not rows:
        return None
    if county is not None:
        scoped = [r for r in rows if r.get("county") == county]
        if scoped:
            return scoped[0]
    return rows[0]


def can_promote_source_for_use(
    source_id: str,
    use: str,
    *,
    state: str | None = None,
    county: str | None = None,
    as_of: str | None = None,
) -> PromotionDecision:
    """The Phase 37 Section 8 entry point: "may this source be used for this
    exact purpose?" See this module's own docstring for the full 5-step
    decision order. Raises `ValueError` immediately for an unrecognized
    `use` (a typo must never silently resolve to a decision that looks like
    a real denial - matches `authorization.check_authorized_use()`'s own
    behavior for the same reason). Never raises for an unknown `source_id`
    - that is ordinary, checkable, fail-closed data (a denied
    `PromotionDecision`), the same design `registry.get_source()` and
    `gate.check_ingestion_gate()` already use."""
    if use not in PROMOTION_USES:
        raise ValueError(f"{use!r} is not a recognized promotion use. Valid: {sorted(PROMOTION_USES)}")
    scope_dimension = PROMOTION_USE_TO_SCOPE_DIMENSION[use]

    registry_record = get_source(source_id)
    has_authorization_records = bool(authorizations_for_source(source_id))
    ledger_row = _find_terms_review_row(source_id, county)

    # Step 1: entirely unrepresented source_id.
    if registry_record is None and not has_authorization_records and ledger_row is None:
        return PromotionDecision(
            source_id=source_id,
            use=use,
            state=state,
            county=county,
            allowed=False,
            status="UNKNOWN",
            reason=(
                f"'{source_id}' has no SOURCE_REGISTRY entry, no ProviderAuthorization record, and no Phase 36 "
                "terms-review ledger row - an entirely unrepresented source_id is never treated as approved for "
                "any use (fail-closed: missing != approved)."
            ),
            evidence="none - source_id is not represented in any governance data structure",
            reviewed_at=None,
        )

    # Step 2: whole-source registry gate, if this source_id is registered.
    if registry_record is not None:
        gate_decision = check_ingestion_gate(source_id)
        if not gate_decision.allowed:
            return PromotionDecision(
                source_id=source_id,
                use=use,
                state=state,
                county=county,
                allowed=False,
                status=registry_record.legal_status.value,
                reason=f"registry legal_status is {registry_record.legal_status.value} - {gate_decision.reason}",
                evidence="; ".join(registry_record.doc_refs) or "harvesters/governance/registry.py",
                reviewed_at=registry_record.review_date,
            )
        if use == "HISTORICAL_RETENTION" and Restriction.NO_HISTORICAL_RETENTION in gate_decision.restrictions:
            return PromotionDecision(
                source_id=source_id,
                use=use,
                state=state,
                county=county,
                allowed=False,
                status=registry_record.legal_status.value,
                reason=f"'{source_id}' carries restriction {Restriction.NO_HISTORICAL_RETENTION.value}",
                evidence="; ".join(registry_record.doc_refs) or "harvesters/governance/registry.py",
                reviewed_at=registry_record.review_date,
            )
        blocking_set = _SURFACE_RESTRICTION_SETS.get(use)
        if blocking_set and any(r in blocking_set for r in gate_decision.restrictions):
            blocking = [r.value for r in gate_decision.restrictions if r in blocking_set]
            return PromotionDecision(
                source_id=source_id,
                use=use,
                state=state,
                county=county,
                allowed=False,
                status=registry_record.legal_status.value,
                reason=(
                    f"'{source_id}' is {registry_record.legal_status.value} but carries a restriction blocking "
                    f"'{use}': {blocking}"
                ),
                evidence="; ".join(registry_record.doc_refs) or "harvesters/governance/registry.py",
                reviewed_at=registry_record.review_date,
            )

    # Step 3: per-use, per-county provider authorization (Phase 34A/34B) -
    # a source with ANY authorization record on file is held to the strict
    # standard for EVERY county, including one with no record of its own.
    if has_authorization_records:
        use_decision = check_authorized_use(source_id, scope_dimension, county=county, as_of=as_of)
        record = authorization_for_scope(source_id, county)
        status = use_decision.authorization_status.value if use_decision.authorization_status else "UNKNOWN"
        if record is not None:
            evidence = record.document.scope_summary or record.agreement_url or "harvesters/governance/authorization.py"
            reviewed_at = record.reviewed_at
        else:
            evidence = (
                f"no ProviderAuthorization record exists for source_id={source_id!r}, county={county!r} - "
                f"other counties/deployments under this source_id DO have records, which is exactly why this "
                "one is held to the strict standard rather than falling through to the no-op path below"
            )
            reviewed_at = None
        return PromotionDecision(
            source_id=source_id,
            use=use,
            state=state,
            county=county,
            allowed=use_decision.allowed,
            status=status,
            reason=use_decision.reason,
            evidence=evidence,
            reviewed_at=reviewed_at,
        )

    # Step 5: not in SOURCE_REGISTRY at all, but the Phase 36 ledger has a
    # row - deny citing that row's own evidence (never a generic message).
    if registry_record is None and ledger_row is not None:
        ledger_status = ledger_row.get("legal_status") or "DISCOVERED"
        allowed = ledger_status in ("APPROVED", "APPROVED_WITH_RESTRICTIONS")
        return PromotionDecision(
            source_id=source_id,
            use=use,
            state=state,
            county=county,
            allowed=allowed,
            status=ledger_status,
            reason=(
                f"Phase 36 terms-review ledger row for '{source_id}' is {ledger_status} - "
                f"{ledger_row.get('approval_notes') or ledger_row.get('legal_basis') or 'no further detail on file'}"
            ),
            evidence=ledger_row.get("evidence_reference") or "data/phase36_terms_review.csv",
            reviewed_at=ledger_row.get("reviewed_at"),
        )

    # Step 4: registered, gate passed, zero authorization records, no
    # ledger row either - today's exact, unmodified production no-op path.
    assert registry_record is not None  # only remaining branch - guards against a silent 6th case
    return PromotionDecision(
        source_id=source_id,
        use=use,
        state=state,
        county=county,
        allowed=True,
        status=registry_record.legal_status.value,
        reason=(
            f"'{source_id}' is {registry_record.legal_status.value} with no per-use ProviderAuthorization record "
            f"and no restriction blocking '{use}' - matches this project's existing, unmodified production "
            "behavior for a source that has not opted into the Phase 34A per-use authorization framework "
            "(e.g. tx_lgbs, tx_realauction, fl_laft_pdfs today)."
        ),
        evidence="; ".join(registry_record.doc_refs) or "harvesters/governance/registry.py",
        reviewed_at=registry_record.review_date,
    )
