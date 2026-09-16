"""Acquisition result and retrieval-metadata model - Phase 39 (Acquisition
Engine & Full Data Activation), Sections 12-13.

Repository audit finding (Phase 39 Section 2): before this module, every
harvester in this project reported its own outcome in its own ad-hoc way -
`harvest_lgbs()` prints a summary line to stderr and returns a list (an
empty list meaning, indistinguishably, "the source published nothing
today", "the request failed on page 1", or "every row was filtered out");
`harvest_pbfcm()`/`harvest_govease()` raise `NotImplementedError`;
`enrich_property_details_tx.py`'s `_fetch_*()` functions return `None` for
both "no such parcel" and "this CAD has no usable endpoint". There was no
way for any caller - a workflow, a dashboard, a completeness report - to
tell those cases apart after the fact.

This module gives every acquisition attempt ONE structured outcome with a
SPECIFIC status. Phase 39 Section 12's explicit rule is enforced by
construction: there is deliberately no generic `FAILED` member on
`AcquisitionStatus`. A caller that genuinely cannot determine a reason
must use `TECHNICAL_FAILURE` and populate `error_code`/`error_message`;
it can never paper over a known-but-unrecorded reason with a generic
value, because no generic value exists.

Deliberate non-duplication (Section 7's "do not create a second competing
authorization system"): nothing in this module has any opinion about
legal status. `AcquisitionStatus.LEGAL_RESTRICTION` records only that a
legal gate - `harvesters.governance`'s, consulted by
`harvesters/acquisition/policy.py` - was the reason an attempt did not
proceed. It never decides that; it reports it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class AcquisitionStatus(str, Enum):
    """Phase 39 Section 12's exact vocabulary. Note the deliberate absence
    of a generic `FAILED` - see the module docstring."""

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    NO_DATA = "NO_DATA"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
    SCHEMA_FAILURE = "SCHEMA_FAILURE"
    RATE_LIMITED = "RATE_LIMITED"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
    LEGAL_RESTRICTION = "LEGAL_RESTRICTION"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# The statuses under which an attempt actually produced usable records.
# Used by the completeness/health layers so "did this work" is answered in
# exactly one place rather than re-derived per call site (the same
# discipline registry.INGESTION_ALLOWED_STATUSES already establishes).
ACQUISITION_PRODUCED_RECORDS = frozenset(
    {
        AcquisitionStatus.SUCCESS,
        AcquisitionStatus.PARTIAL_SUCCESS,
    }
)

# Statuses that mean "this source could not be reached or read", as
# distinct from "it was reached and had nothing" (NO_DATA) and from "we
# chose not to reach it" (LEGAL_RESTRICTION / NOT_APPLICABLE). Phase 39
# Section 50's adversarial test 19 ("source failure is distinguishable
# from no records") is this set's reason for existing.
ACQUISITION_FAILURE_STATUSES = frozenset(
    {
        AcquisitionStatus.SOURCE_UNAVAILABLE,
        AcquisitionStatus.TECHNICAL_FAILURE,
        AcquisitionStatus.SCHEMA_FAILURE,
        AcquisitionStatus.RATE_LIMITED,
        AcquisitionStatus.AUTHENTICATION_REQUIRED,
        AcquisitionStatus.ACCESS_RESTRICTED,
    }
)


class TechnicalAcquisitionState(str, Enum):
    """Phase 39 Section 7's source-level lifecycle vocabulary, kept
    separate from both `AcquisitionStatus` (the outcome of ONE attempt)
    and from `governance.verification.TechnicalAcquisitionStatus` (Phase
    37/38's coarser, hand-maintained engineering-progress axis).

    The relationship, stated so the three are never confused:
      - `governance.verification.TechnicalAcquisitionStatus` = "how far has
        a human gotten with this source", transcribed from research docs.
      - `TechnicalAcquisitionState` (here) = "what is the acquisition
        ENGINE's current standing for this source", derived from real
        attempt history.
      - `AcquisitionStatus` = "how did this one attempt end".
    """

    DISCOVERED = "DISCOVERED"
    VERIFIED = "VERIFIED"
    TECHNICAL_ACQUISITION_READY = "TECHNICAL_ACQUISITION_READY"
    TECHNICAL_ACQUISITION_IN_PROGRESS = "TECHNICAL_ACQUISITION_IN_PROGRESS"
    TECHNICAL_ACQUISITION_SUCCESS = "TECHNICAL_ACQUISITION_SUCCESS"
    TECHNICAL_ACQUISITION_FAILED = "TECHNICAL_ACQUISITION_FAILED"
    TECHNICAL_ACQUISITION_BLOCKED = "TECHNICAL_ACQUISITION_BLOCKED"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    AUTHORIZED = "AUTHORIZED"
    PRODUCTION_ENABLED = "PRODUCTION_ENABLED"
    DISABLED = "DISABLED"


class RawStorageStatus(str, Enum):
    """Phase 39 Section 14. `RESTRICTED` is not a failure - it is the
    correct, intended outcome for a source whose policy does not permit
    retaining raw payloads. Metadata about the retrieval may still be
    recorded (Section 14's own allowance); the bytes are not."""

    STORED = "STORED"
    NOT_STORED = "NOT_STORED"
    RESTRICTED = "RESTRICTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(payload: bytes | str) -> str:
    """Stable SHA-256 of a retrieved payload, for Section 13's
    `content_hash` and Section 50's adversarial test 8 (schema-change
    detection). Mirrors `authorization.compute_terms_hash()`'s existing
    algorithm choice rather than introducing a second hashing convention."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class RetrievalMetadata:
    """Phase 39 Section 13's exact field list. Deliberately carries NO
    credential, token, cookie, or authorization-header field - Section 13's
    "do not store sensitive credentials or secret values in logs" is
    enforced structurally here (there is nowhere to put one) rather than
    left to caller discipline."""

    source_id: str
    state: str | None
    county: str | None
    source_url: str | None
    retrieval_method: str
    started_at: str
    completed_at: str | None = None
    http_status: int | None = None
    records_seen: int = 0
    records_acquired: int = 0
    records_failed: int = 0
    content_type: str | None = None
    content_hash_value: str | None = None
    source_updated_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    def duration_seconds(self) -> float | None:
        if not self.completed_at:
            return None
        start = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.completed_at)
        return (end - start).total_seconds()


@dataclass(frozen=True)
class AcquisitionResult:
    """Phase 39 Section 11's structured acquisition result.

    `records` holds the NORMALIZED records an adapter produced. It is
    deliberately a plain tuple of dicts rather than a state-specific row
    type (`TexasSaleRow`, the Florida harvesters' own shape) so the
    acquisition core stays state-agnostic - Section 25's "state-specific
    rules should remain outside the generic acquisition core" and Section
    74's "adding another state should not require redesigning acquisition
    result handling".
    """

    source_id: str
    jurisdiction: str  # "TX/Harris", "FL/Alachua", "FL/statewide" - never a bare county name
    status: AcquisitionStatus
    started_at: str
    completed_at: str | None = None
    records_seen: int = 0
    records_acquired: int = 0
    records_failed: int = 0
    records_skipped: int = 0
    records_restricted: int = 0
    categories: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    source_timestamp: str | None = None
    retrieval_method: str = "unknown"
    raw_storage_status: RawStorageStatus = RawStorageStatus.NOT_APPLICABLE
    retrievals: tuple[RetrievalMetadata, ...] = field(default_factory=tuple)
    records: tuple[dict, ...] = field(default_factory=tuple)
    checkpoint: dict | None = None
    # Phase 41: why records were skipped, keyed by a `run.RejectionReason`
    # value. Additive and optional - an adapter that does not classify its
    # skips leaves this empty, and `records_skipped` remains the total.
    # Without this, a run cannot report Phase 41 Section 8's required
    # `non_tx_rejected` separately from an ordinary unmapped-status skip.
    rejections_by_reason: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Structural guarantee for Section 70 ("no fabricated coverage"):
        # a result may never claim to have acquired more records than it
        # actually carries, and SUCCESS may never be claimed with zero
        # records (that is NO_DATA's job, and the two must stay
        # distinguishable - Section 50's adversarial test 19).
        if self.records and self.records_acquired != len(self.records):
            raise ValueError(
                f"{self.source_id}: records_acquired={self.records_acquired} disagrees with "
                f"len(records)={len(self.records)} - an acquisition result may never overstate what it holds"
            )
        if self.status == AcquisitionStatus.SUCCESS and self.records_acquired == 0:
            raise ValueError(
                f"{self.source_id}: SUCCESS with zero records acquired is not representable - "
                "use NO_DATA (source reached, published nothing) so the two stay distinguishable"
            )
        if self.status == AcquisitionStatus.PARTIAL_SUCCESS and self.records_acquired == 0:
            raise ValueError(
                f"{self.source_id}: PARTIAL_SUCCESS requires at least one acquired record"
            )

    @property
    def succeeded(self) -> bool:
        """True only when real records were produced. Deliberately NOT
        'not a failure' - NO_DATA, LEGAL_RESTRICTION and NOT_APPLICABLE
        are all non-failures that produced nothing."""
        return self.status in ACQUISITION_PRODUCED_RECORDS

    @property
    def failed(self) -> bool:
        return self.status in ACQUISITION_FAILURE_STATUSES

    def to_dict(self, *, include_records: bool = False) -> dict:
        """Reporting shape. `include_records` defaults to False so a
        summary report can never accidentally serialize source content it
        may not be authorized to redistribute (Section 40)."""
        payload = {
            "source_id": self.source_id,
            "jurisdiction": self.jurisdiction,
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "records_seen": self.records_seen,
            "records_acquired": self.records_acquired,
            "records_failed": self.records_failed,
            "records_skipped": self.records_skipped,
            "records_restricted": self.records_restricted,
            "categories": list(self.categories),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "source_timestamp": self.source_timestamp,
            "retrieval_method": self.retrieval_method,
            "raw_storage_status": self.raw_storage_status.value,
            "retrieval_count": len(self.retrievals),
        }
        if include_records:
            payload["records"] = [dict(r) for r in self.records]
        return payload


def build_result(
    *,
    source_id: str,
    jurisdiction: str,
    status: AcquisitionStatus,
    started_at: str,
    records: tuple[dict, ...] | list[dict] = (),
    **kwargs,
) -> AcquisitionResult:
    """Convenience constructor that fills `completed_at` and keeps
    `records_acquired` in sync with `records` automatically, so no caller
    can drift the two apart by hand (the invariant `__post_init__`
    enforces)."""
    records_tuple = tuple(records)
    kwargs.setdefault("records_acquired", len(records_tuple))
    kwargs.setdefault("completed_at", _utc_now_iso())
    return AcquisitionResult(
        source_id=source_id,
        jurisdiction=jurisdiction,
        status=status,
        started_at=started_at,
        records=records_tuple,
        **kwargs,
    )
