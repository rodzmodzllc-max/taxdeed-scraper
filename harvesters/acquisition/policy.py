"""Pre-acquisition source policy gate - Phase 39 Sections 8, 16, 17, 40.

This module is the single boundary between the acquisition engine and this
project's existing governance stack. It answers exactly one question -
"may this acquisition attempt proceed, and for what purpose" - and it
answers it by DELEGATING to the layers that already exist:

  - `governance.gate.check_ingestion_gate()`        (Phase 10A/11)
  - `governance.promotion.can_promote_source_for_use()` (Phase 37)
  - `governance.registry.SOURCE_REGISTRY`           (Phase 10A)
  - `governance.verification`                       (Phase 37/38)

It holds no authorization data of its own, defines no second approval
vocabulary, and can never return a MORE permissive answer than those
layers do (Section 7: "do not create a second competing authorization
system"; Section 71: technical success never becomes authorization).

The one genuinely new concept here is Section 17's distinction between two
PURPOSES for reaching a source:

  INTERNAL_TECHNICAL_TESTING
      Verifying that an endpoint exists, responds, and returns the fields
      an adapter expects. Section 17 explicitly permits this for a source
      whose COMMERCIAL authorization is unresolved - "do not prevent
      legitimate internal technical testing merely because commercial
      authorization is unresolved" - because an unresolved commercial
      question is not a prohibition on looking.

  PRODUCTION_ACQUISITION
      Pulling records intended to flow toward the customer-facing system.
      This requires the full Phase 37 promotion gate to allow the relevant
      use, per county, today.

Section 17's own limit on that distinction is enforced here and is the
most important rule in this module: **it may never be used to bypass a
source's actual access restrictions.** A source that is `BLOCKED` in
`SOURCE_REGISTRY` (an affirmative prohibition found in its own terms, or a
blanket robots disallow) is refused for BOTH purposes -
`INTERNAL_TECHNICAL_TESTING` does not unlock `tx_pbfcm`, `tx_mvba`,
`tx_ctsa` or `tx_govease`. The testing allowance applies only to the
narrower `LEGAL_REVIEW_REQUIRED`/`DISCOVERED` case, where no prohibition
has actually been found and the open question is commercial.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from ..governance.gate import check_ingestion_gate
from ..governance.promotion import can_promote_source_for_use
from ..governance.registry import SourceStatus, get_source
from .result import AcquisitionStatus


class AcquisitionPurpose(str, Enum):
    """Section 17's two purposes. Deliberately only two - a third, vaguer
    middle category would immediately become the place every awkward case
    gets filed."""

    INTERNAL_TECHNICAL_TESTING = "INTERNAL_TECHNICAL_TESTING"
    PRODUCTION_ACQUISITION = "PRODUCTION_ACQUISITION"


# Registry statuses that represent an AFFIRMATIVE prohibition or a
# deliberate shutdown, as opposed to an unresolved question. Nothing in
# this module permits reaching a source in one of these states, for any
# purpose. `TERMS_CHANGED` is included because Section 50's adversarial
# test 14 requires a terms change to stop silently preserving prior
# approval - the conservative reading is that a changed-terms source is
# not touched until a human re-reviews it.
HARD_REFUSAL_STATUSES = frozenset(
    {
        SourceStatus.BLOCKED,
        SourceStatus.DISABLED,
        SourceStatus.TERMS_CHANGED,
    }
)

# Statuses where the open question is COMMERCIAL rather than a found
# prohibition. Internal technical testing is permitted (Section 17);
# production acquisition is not (Section 8/40).
UNRESOLVED_STATUSES = frozenset(
    {
        SourceStatus.LEGAL_REVIEW_REQUIRED,
        SourceStatus.DISCOVERED,
        SourceStatus.UNDER_REVIEW,
    }
)


@dataclass(frozen=True)
class AcquisitionPolicyDecision:
    """Structured, never a bare boolean (the same discipline Phase 37's
    `PromotionDecision` established)."""

    source_id: str
    purpose: AcquisitionPurpose
    state: str | None
    county: str | None
    allowed: bool
    reason: str
    registry_status: str
    promotion_status: str | None = None
    acquisition_status_if_denied: AcquisitionStatus | None = None
    evidence: str = ""
    checked_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "purpose": self.purpose.value,
            "state": self.state,
            "county": self.county,
            "allowed": self.allowed,
            "reason": self.reason,
            "registry_status": self.registry_status,
            "promotion_status": self.promotion_status,
            "acquisition_status_if_denied": (
                self.acquisition_status_if_denied.value if self.acquisition_status_if_denied else None
            ),
            "evidence": self.evidence,
            "checked_at": self.checked_at,
        }


def check_acquisition_policy(
    source_id: str,
    *,
    purpose: AcquisitionPurpose = AcquisitionPurpose.PRODUCTION_ACQUISITION,
    state: str | None = None,
    county: str | None = None,
    use: str = "INGEST",
) -> AcquisitionPolicyDecision:
    """May an acquisition attempt against `source_id` proceed?

    Decision order, fail-closed at every step:

    1. Unknown `source_id` -> refuse. (Never "probably fine".)
    2. Registry status in `HARD_REFUSAL_STATUSES` -> refuse for BOTH
       purposes. An affirmative prohibition is not a commercial open
       question and internal testing does not unlock it.
    3. `purpose=INTERNAL_TECHNICAL_TESTING` and the status is an unresolved
       one -> allow, explicitly labelled as testing-only (Section 17).
       This allowance carries no production implication whatsoever.
    4. `purpose=PRODUCTION_ACQUISITION` -> defer entirely to Phase 37's
       `can_promote_source_for_use()` for the requested `use`, county and
       date. Its answer is returned unchanged.
    """
    record = get_source(source_id)
    if record is None:
        return AcquisitionPolicyDecision(
            source_id=source_id,
            purpose=purpose,
            state=state,
            county=county,
            allowed=False,
            reason=(
                f"'{source_id}' has no SOURCE_REGISTRY entry - an unregistered source is never acquired, "
                "for any purpose (fail-closed: missing != permitted)."
            ),
            registry_status="UNKNOWN",
            acquisition_status_if_denied=AcquisitionStatus.LEGAL_RESTRICTION,
            evidence="harvesters/governance/registry.py",
        )

    registry_status = record.legal_status
    evidence = "; ".join(record.doc_refs) or "harvesters/governance/registry.py"

    if registry_status in HARD_REFUSAL_STATUSES:
        return AcquisitionPolicyDecision(
            source_id=source_id,
            purpose=purpose,
            state=state,
            county=county,
            allowed=False,
            reason=(
                f"'{source_id}' is {registry_status.value} - an affirmative prohibition or deliberate "
                "shutdown. Refused for EVERY purpose, including internal technical testing: Section 17's "
                "testing allowance covers unresolved commercial questions, never a found prohibition."
            ),
            registry_status=registry_status.value,
            acquisition_status_if_denied=AcquisitionStatus.LEGAL_RESTRICTION,
            evidence=evidence,
        )

    if purpose == AcquisitionPurpose.INTERNAL_TECHNICAL_TESTING:
        if registry_status in UNRESOLVED_STATUSES or registry_status in (
            SourceStatus.APPROVED,
            SourceStatus.APPROVED_WITH_RESTRICTIONS,
        ):
            return AcquisitionPolicyDecision(
                source_id=source_id,
                purpose=purpose,
                state=state,
                county=county,
                allowed=True,
                reason=(
                    f"'{source_id}' is {registry_status.value}; internal technical testing is permitted "
                    "(Phase 39 Section 17). This allowance is explicitly NOT authorization for storage, "
                    "customer display, export, API redistribution, or any production use - those remain "
                    "governed solely by can_promote_source_for_use()."
                ),
                registry_status=registry_status.value,
                evidence=evidence,
            )
        return AcquisitionPolicyDecision(
            source_id=source_id,
            purpose=purpose,
            state=state,
            county=county,
            allowed=False,
            reason=f"'{source_id}' is {registry_status.value} - not a state in which testing is permitted.",
            registry_status=registry_status.value,
            acquisition_status_if_denied=AcquisitionStatus.LEGAL_RESTRICTION,
            evidence=evidence,
        )

    # PRODUCTION_ACQUISITION: the existing gates decide, unchanged.
    gate = check_ingestion_gate(source_id)
    if not gate.allowed:
        return AcquisitionPolicyDecision(
            source_id=source_id,
            purpose=purpose,
            state=state,
            county=county,
            allowed=False,
            reason=f"ingestion gate refused '{source_id}': {gate.reason}",
            registry_status=registry_status.value,
            acquisition_status_if_denied=AcquisitionStatus.LEGAL_RESTRICTION,
            evidence=evidence,
        )

    promotion = can_promote_source_for_use(source_id, use, state=state, county=county)
    return AcquisitionPolicyDecision(
        source_id=source_id,
        purpose=purpose,
        state=state,
        county=county,
        allowed=promotion.allowed,
        reason=promotion.reason,
        registry_status=registry_status.value,
        promotion_status=promotion.status,
        acquisition_status_if_denied=None if promotion.allowed else AcquisitionStatus.LEGAL_RESTRICTION,
        evidence=promotion.evidence or evidence,
    )


def check_fallback_allowed(
    primary_source_id: str,
    fallback_source_id: str,
    *,
    purpose: AcquisitionPurpose = AcquisitionPurpose.PRODUCTION_ACQUISITION,
    state: str | None = None,
    county: str | None = None,
    use: str = "INGEST",
    explicitly_configured: bool = False,
) -> AcquisitionPolicyDecision:
    """Section 16's no-silent-fallback rule, as an explicit function.

    Two independent conditions must BOTH hold before a fallback may run:

    1. The fallback was explicitly configured as a fallback for this
       primary (`explicitly_configured=True`). An adapter may never decide
       at runtime that some other source "looks equivalent" - Section 16's
       "fallback must be explicitly configured".
    2. The fallback independently passes its OWN policy check. A blocked
       source can never become reachable by being someone's fallback
       (Section 50's adversarial test 4).
    """
    if not explicitly_configured:
        return AcquisitionPolicyDecision(
            source_id=fallback_source_id,
            purpose=purpose,
            state=state,
            county=county,
            allowed=False,
            reason=(
                f"'{fallback_source_id}' is not an explicitly configured fallback for "
                f"'{primary_source_id}' - silent substitution is prohibited (Phase 39 Section 16)."
            ),
            registry_status=(get_source(fallback_source_id).legal_status.value if get_source(fallback_source_id) else "UNKNOWN"),
            acquisition_status_if_denied=AcquisitionStatus.LEGAL_RESTRICTION,
            evidence="harvesters/acquisition/policy.py::check_fallback_allowed",
        )
    return check_acquisition_policy(
        fallback_source_id, purpose=purpose, state=state, county=county, use=use
    )


def binary_content_allowed(
    source_id: str,
    *,
    kind: str,  # "IMAGE" | "DOCUMENT"
    state: str | None = None,
    county: str | None = None,
) -> AcquisitionPolicyDecision:
    """Section 41: binary content is never retained merely because a URL
    exists. Checks the specific image/document promotion uses rather than
    inheriting a structured-data decision."""
    use = "IMAGE_DOWNLOAD" if kind.upper() == "IMAGE" else "DOCUMENT_DOWNLOAD"
    decision = check_acquisition_policy(
        source_id,
        purpose=AcquisitionPurpose.PRODUCTION_ACQUISITION,
        state=state,
        county=county,
        use=use,
    )
    return decision
