"""Completeness, coverage metrics, missing-data classification and source
health - Phase 39 Sections 33-36, 59.

Extends (never replaces) Phase 37/38's completeness framework: that phase
answered "how far has research gotten with this source"
(`governance.verification`); this module answers "how much data did the
engine actually obtain, and how fresh is it". The two are joined only at
the reporting layer, never merged into one number - Section 70's "no
fabricated coverage" is mostly a matter of keeping these separate, because
a source that is fully DISCOVERED and fully VERIFIED can still have
acquired exactly zero records.

Every figure this module produces is computed from real
`AcquisitionResult` objects. Nothing here estimates, extrapolates from a
sample, or fills an unknown with a plausible default: an unknown
denominator produces `None`, not a percentage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .result import (
    ACQUISITION_FAILURE_STATUSES,
    ACQUISITION_PRODUCED_RECORDS,
    AcquisitionResult,
    AcquisitionStatus,
)


class MissingDataReason(str, Enum):
    """Section 34's exact nine-value vocabulary.

    Deliberately a SEPARATE enum from Phase 37/38's
    `governance.verification.DataMissingReason`, which has an overlapping
    but different membership (that one includes `AVAILABLE` and
    `LAWFULLY_COLLECTABLE_BUT_MISSING` for the research axis; this one
    includes `NOT_YET_ACQUIRED` and `MISSING_FROM_RECORD` for the
    acquisition axis). Merging them would force one axis to carry the
    other's vocabulary - `MISSING_FROM_RECORD` is meaningless as a research
    finding, and `LAWFULLY_COLLECTABLE_BUT_MISSING` is meaningless as a
    per-field acquisition outcome. `RESEARCH_TO_ACQUISITION_REASON` below
    is the one explicit bridge between them.
    """

    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_AVAILABLE_AT_SOURCE = "NOT_AVAILABLE_AT_SOURCE"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    LEGAL_RESTRICTION = "LEGAL_RESTRICTION"
    NOT_YET_ACQUIRED = "NOT_YET_ACQUIRED"
    MISSING_FROM_RECORD = "MISSING_FROM_RECORD"


# The one mapping from an acquisition OUTCOME to the reason a field that
# would have come from it is missing. Section 34's explicit warning - "do
# not classify a legally restricted field as an ordinary technical
# failure" - is enforced here, in one place, rather than at each call site.
ACQUISITION_STATUS_TO_MISSING_REASON: dict[AcquisitionStatus, MissingDataReason] = {
    AcquisitionStatus.SUCCESS: MissingDataReason.MISSING_FROM_RECORD,
    AcquisitionStatus.PARTIAL_SUCCESS: MissingDataReason.MISSING_FROM_RECORD,
    AcquisitionStatus.NO_DATA: MissingDataReason.NOT_AVAILABLE_AT_SOURCE,
    AcquisitionStatus.SOURCE_UNAVAILABLE: MissingDataReason.SOURCE_UNAVAILABLE,
    AcquisitionStatus.TECHNICAL_FAILURE: MissingDataReason.TECHNICAL_FAILURE,
    AcquisitionStatus.SCHEMA_FAILURE: MissingDataReason.TECHNICAL_FAILURE,
    AcquisitionStatus.RATE_LIMITED: MissingDataReason.TEMPORARILY_UNAVAILABLE,
    AcquisitionStatus.AUTHENTICATION_REQUIRED: MissingDataReason.LEGAL_RESTRICTION,
    AcquisitionStatus.ACCESS_RESTRICTED: MissingDataReason.LEGAL_RESTRICTION,
    AcquisitionStatus.LEGAL_RESTRICTION: MissingDataReason.LEGAL_RESTRICTION,
    AcquisitionStatus.NOT_APPLICABLE: MissingDataReason.NOT_APPLICABLE,
}


def classify_missing(
    *,
    field_present: bool,
    acquisition_status: AcquisitionStatus | None,
    source_known: bool = True,
    category_applicable: bool = True,
) -> MissingDataReason | None:
    """Section 34: every missing value gets a specific reason, never a bare
    NULL. Returns `None` when the field IS present (nothing to classify)."""
    if field_present:
        return None
    if not category_applicable:
        return MissingDataReason.NOT_APPLICABLE
    if not source_known:
        return MissingDataReason.SOURCE_NOT_FOUND
    if acquisition_status is None:
        return MissingDataReason.NOT_YET_ACQUIRED
    return ACQUISITION_STATUS_TO_MISSING_REASON.get(acquisition_status, MissingDataReason.TECHNICAL_FAILURE)


@dataclass(frozen=True)
class CoverageMetrics:
    """Section 35's per-(county, source, category) counts.

    `records_expected` is `None` whenever the source does not publish a
    total - and most do not. A `coverage_percentage` computed against a
    guessed denominator would be exactly the fabricated coverage Section 70
    prohibits, so `coverage_percentage` returns `None` in that case rather
    than a number that looks authoritative.
    """

    state: str
    county: str | None
    source_id: str
    category: str | None
    records_expected: int | None
    records_discovered: int
    records_acquired: int
    records_normalized: int
    records_failed: int
    records_restricted: int
    last_attempt: str | None = None
    last_success: str | None = None

    @property
    def coverage_percentage(self) -> float | None:
        if not self.records_expected:
            return None
        return round(100.0 * self.records_acquired / self.records_expected, 2)

    @property
    def freshness_seconds(self) -> float | None:
        if not self.last_success:
            return None
        last = datetime.fromisoformat(self.last_success)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - last).total_seconds()

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "county": self.county,
            "source_id": self.source_id,
            "category": self.category,
            "records_expected": self.records_expected,
            "records_discovered": self.records_discovered,
            "records_acquired": self.records_acquired,
            "records_normalized": self.records_normalized,
            "records_failed": self.records_failed,
            "records_restricted": self.records_restricted,
            "coverage_percentage": self.coverage_percentage,
            "last_attempt": self.last_attempt,
            "last_success": self.last_success,
        }


def metrics_from_results(
    results: list[AcquisitionResult],
    *,
    state: str,
    county: str | None,
    source_id: str,
    category: str | None = None,
    records_expected: int | None = None,
) -> CoverageMetrics:
    """Fold real attempt results into one metrics record. Section 59's
    freshness rule is enforced here: `last_success` only advances for a
    result that actually produced records."""
    last_attempt = None
    last_success = None
    acquired = discovered = failed = restricted = 0

    for result in results:
        if last_attempt is None or (result.started_at or "") > last_attempt:
            last_attempt = result.started_at
        if result.status in ACQUISITION_PRODUCED_RECORDS:
            if last_success is None or (result.completed_at or result.started_at) > last_success:
                last_success = result.completed_at or result.started_at
        discovered += result.records_seen
        acquired += result.records_acquired
        failed += result.records_failed
        restricted += result.records_restricted

    return CoverageMetrics(
        state=state,
        county=county,
        source_id=source_id,
        category=category,
        records_expected=records_expected,
        records_discovered=discovered,
        records_acquired=acquired,
        records_normalized=acquired,  # this engine normalizes at acquisition time; they cannot diverge
        records_failed=failed,
        records_restricted=restricted,
        last_attempt=last_attempt,
        last_success=last_success,
    )


def field_coverage(records: list[dict], field_name: str) -> tuple[int, int, float | None]:
    """Section 35's per-field coverage: `(records_with_value, total,
    percentage)`. A field present but null counts as missing - the question
    is whether a usable VALUE was obtained, not whether a key exists."""
    total = len(records)
    if total == 0:
        return (0, 0, None)
    with_value = sum(1 for r in records if r.get(field_name) not in (None, "", []))
    return (with_value, total, round(100.0 * with_value / total, 2))


@dataclass
class SourceHealth:
    """Section 36. Deliberately carries NO authorization field - Section
    36's "do not confuse source health with legal approval". A source can
    be perfectly healthy and entirely unauthorized."""

    source_id: str
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    blocked: int = 0
    records_seen: int = 0
    records_acquired: int = 0
    records_failed: int = 0
    last_attempt: str | None = None
    last_success: str | None = None
    latencies_seconds: list[float] = field(default_factory=list)
    schema_hashes: set = field(default_factory=set)

    @property
    def success_rate(self) -> float | None:
        if not self.attempts:
            return None
        return round(self.successes / self.attempts, 4)

    @property
    def failure_rate(self) -> float | None:
        if not self.attempts:
            return None
        return round(self.failures / self.attempts, 4)

    @property
    def mean_latency_seconds(self) -> float | None:
        if not self.latencies_seconds:
            return None
        return round(sum(self.latencies_seconds) / len(self.latencies_seconds), 3)

    @property
    def schema_changed(self) -> bool:
        """Section 50's adversarial test 8: more than one distinct payload
        hash across attempts for a fixed query is a schema-change SIGNAL,
        surfaced for a human rather than acted on automatically."""
        return len(self.schema_hashes) > 1

    def record(self, result: AcquisitionResult) -> None:
        self.attempts += 1
        self.last_attempt = result.started_at
        self.records_seen += result.records_seen
        self.records_acquired += result.records_acquired
        self.records_failed += result.records_failed

        if result.status in ACQUISITION_PRODUCED_RECORDS:
            self.successes += 1
            self.last_success = result.completed_at or result.started_at
        elif result.status in ACQUISITION_FAILURE_STATUSES:
            self.failures += 1
        elif result.status == AcquisitionStatus.LEGAL_RESTRICTION:
            self.blocked += 1

        for retrieval in result.retrievals:
            duration = retrieval.duration_seconds()
            if duration is not None:
                self.latencies_seconds.append(duration)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "attempts": self.attempts,
            "successes": self.successes,
            "failures": self.failures,
            "blocked": self.blocked,
            "success_rate": self.success_rate,
            "failure_rate": self.failure_rate,
            "records_seen": self.records_seen,
            "records_acquired": self.records_acquired,
            "records_failed": self.records_failed,
            "last_attempt": self.last_attempt,
            "last_success": self.last_success,
            "mean_latency_seconds": self.mean_latency_seconds,
            "schema_changed": self.schema_changed,
        }


@dataclass(frozen=True)
class ValueConflict:
    """Section 58: two sources disagreeing is recorded, never silently
    resolved by overwrite."""

    field_name: str
    values: tuple[tuple[str, object, str | None], ...]  # (source_id, value, retrieved_at)

    @property
    def is_conflict(self) -> bool:
        distinct = {v for _sid, v, _ts in self.values if v is not None}
        return len(distinct) > 1


def detect_conflicts(records: list[dict], field_name: str) -> ValueConflict:
    """Collect every source's value for one field across records describing
    the same thing. Returns the conflict record; it is the CALLER's job (a
    documented reconciliation policy) to choose, not this function's."""
    values = tuple(
        (r.get("_source_id", "unknown"), r.get(field_name), r.get("_retrieved_at"))
        for r in records
        if field_name in r
    )
    return ValueConflict(field_name=field_name, values=values)
