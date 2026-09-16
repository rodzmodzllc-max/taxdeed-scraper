"""Acquisition runs and denominator validation - Phase 41 (Controlled
Real-Network tx_lgbs Acquisition).

Repository audit finding (Phase 41 Section 1): Phase 39 gave every
acquisition ATTEMPT a structured result (`AcquisitionResult`), and Phase 40
measured what a source HOLDS (`roster.py`). Neither answers the question a
controlled acquisition actually has to answer:

    "This run pulled N records. Is N right?"

`AcquisitionResult` cannot answer it - it describes one request against one
endpoint and has no notion of an expected total. `SourceHealth` cannot
answer it either; it aggregates attempts, not correctness. So a run that
silently stopped at page 3 of 9 would have produced nine perfectly
well-formed `SUCCESS` results and a dataset missing two thirds of Texas,
with nothing in the system contradicting it.

This module adds that missing layer. An `AcquisitionRun` aggregates the
results of one logical acquisition and validates the outcome against a
**source-side denominator measured independently of the run itself** -
for `tx_lgbs`, the 4,205 that Phase 40 established from `?state=TX`.

Three design rules, each of which exists because of a specific way this
could go wrong:

1. **A run is never COMPLETE by default.** `RunStatus` starts at
   `NOT_STARTED` and can only reach `COMPLETE` by passing an explicit
   denominator check AND recording pagination as exhausted. Phase 41
   Section 17 states the rule plainly - "do not convert partial acquisition
   into success merely because some records were obtained" - and the only
   reliable way to enforce that is to make success the hard path rather
   than the default.

2. **Every record leaving the source is accounted for exactly once.** The
   tally identity `observed = acquired + rejected + failed + duplicated`
   must hold, and `validate()` refuses to certify a run where it does not.
   A record that is dropped for a reason nobody counted is how a 33%
   Pennsylvania contamination becomes invisible.

3. **`records_observed_at_source` is never the same number as
   `records_acquired`.** Phase 40 established the separation; this module
   carries it into the run model rather than letting a run report its own
   input count as its output count.

This module performs NO production write of any kind. It produces
artifacts, tallies and reports. Phase 41 Section 16's prohibition is
structural here: there is no Supabase client, no credential field, and no
write path anywhere in this package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .completeness import SourceHealth, field_coverage
from .result import (
    ACQUISITION_FAILURE_STATUSES,
    ACQUISITION_PRODUCED_RECORDS,
    AcquisitionResult,
    AcquisitionStatus,
)


class RunStatus(str, Enum):
    """Outcome of a whole acquisition run, as distinct from one attempt.

    `COMPLETE` is deliberately hard to reach: it requires pagination to have
    been observed as exhausted AND the denominator check to have passed. A
    run that pulled records but cannot prove it pulled all of them is
    `PARTIAL`, which is a truthful description, not a failure state."""

    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INCOMPLETE = "INCOMPLETE"
    BLOCKED = "BLOCKED"


class RejectionReason(str, Enum):
    """Why a record the source returned did not enter the normalized
    dataset. A rejection is NOT a failure - it is the engine working. The
    distinction matters because `OUT_OF_STATE` rejections are expected and
    healthy for `tx_lgbs` (a third of the feed), while `MALFORMED` ones are
    a source-quality signal."""

    OUT_OF_STATE = "OUT_OF_STATE"
    UNMAPPED_STATUS = "UNMAPPED_STATUS"
    MISSING_IDENTITY = "MISSING_IDENTITY"
    DUPLICATE = "DUPLICATE"
    MALFORMED = "MALFORMED"


@dataclass
class RunTally:
    """Phase 41 Section 6's required counters, plus the identity that makes
    them checkable.

    `records_observed_at_source` is the count the SOURCE reported it holds -
    measured independently, never derived from what the run pulled.
    """

    records_observed_at_source: int | None = None
    records_seen: int = 0
    records_acquired: int = 0
    records_normalized: int = 0
    records_rejected: int = 0
    records_failed: int = 0
    records_duplicated: int = 0
    records_unattributed: int = 0
    rejections_by_reason: dict = field(default_factory=dict)

    def reject(self, reason: RejectionReason, count: int = 1) -> None:
        self.records_rejected += count
        key = reason.value
        self.rejections_by_reason[key] = self.rejections_by_reason.get(key, 0) + count

    @property
    def accounted_for(self) -> int:
        """Every record the source handed over must land in exactly one
        bucket."""
        return self.records_acquired + self.records_rejected + self.records_failed + self.records_duplicated

    @property
    def is_balanced(self) -> bool:
        """The accounting identity. A run where this is False has lost
        records somewhere and must never be certified COMPLETE."""
        return self.records_seen == self.accounted_for

    @property
    def unaccounted(self) -> int:
        return self.records_seen - self.accounted_for

    def to_dict(self) -> dict:
        return {
            "records_observed_at_source": self.records_observed_at_source,
            "records_seen": self.records_seen,
            "records_acquired": self.records_acquired,
            "records_normalized": self.records_normalized,
            "records_rejected": self.records_rejected,
            "records_failed": self.records_failed,
            "records_duplicated": self.records_duplicated,
            "records_unattributed": self.records_unattributed,
            "rejections_by_reason": dict(self.rejections_by_reason),
            "accounted_for": self.accounted_for,
            "is_balanced": self.is_balanced,
            "unaccounted": self.unaccounted,
        }


@dataclass(frozen=True)
class DenominatorCheck:
    """Validation of a run against an independently measured source-side
    total.

    `expected` is `None` when no denominator is known - and in that case
    `passed` is `False`, never `True`. An unverifiable run is not a passing
    run; it is a run whose correctness is unknown, which is exactly the
    state Phase 41 Section 6 requires be visible."""

    expected: int | None
    observed_at_source: int | None
    acquired: int
    rejected: int
    failed: int

    @property
    def reconciled_total(self) -> int:
        """What the run says it saw, from its own buckets."""
        return self.acquired + self.rejected + self.failed

    @property
    def variance(self) -> int | None:
        if self.expected is None:
            return None
        return self.reconciled_total - self.expected

    @property
    def passed(self) -> bool:
        return self.expected is not None and self.variance == 0

    @property
    def reason(self) -> str:
        if self.expected is None:
            return "no independently measured denominator available - run correctness is UNKNOWN, not verified"
        if self.variance == 0:
            return f"reconciled total {self.reconciled_total} matches measured denominator {self.expected}"
        return (
            f"reconciled total {self.reconciled_total} differs from measured denominator "
            f"{self.expected} by {self.variance:+d}"
        )

    def to_dict(self) -> dict:
        return {
            "expected": self.expected,
            "observed_at_source": self.observed_at_source,
            "acquired": self.acquired,
            "rejected": self.rejected,
            "failed": self.failed,
            "reconciled_total": self.reconciled_total,
            "variance": self.variance,
            "passed": self.passed,
            "reason": self.reason,
        }


@dataclass
class AcquisitionRun:
    """One logical acquisition of one source, across however many requests,
    pages or jurisdictions it takes."""

    source_id: str
    state: str
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None
    status: RunStatus = RunStatus.NOT_STARTED
    tally: RunTally = field(default_factory=RunTally)
    health: SourceHealth | None = None
    results: list[AcquisitionResult] = field(default_factory=list)
    pages_retrieved: int = 0
    pagination_exhausted: bool = False
    environment_status: str = "UNKNOWN"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    per_county: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.health is None:
            self.health = SourceHealth(source_id=self.source_id)

    # -- recording ----------------------------------------------------
    def record_result(self, result: AcquisitionResult, *, county: str | None = None) -> None:
        """Fold one attempt into the run. Deliberately does NOT decide the
        run's status - that is `finalize()`'s job, and only after the
        denominator check."""
        self.status = RunStatus.IN_PROGRESS
        self.results.append(result)
        self.health.record(result)
        self.pages_retrieved += max(1, len(result.retrievals))

        self.tally.records_seen += result.records_seen
        self.tally.records_acquired += result.records_acquired
        self.tally.records_normalized += result.records_acquired
        self.tally.records_failed += result.records_failed

        # An adapter that classifies its skips reports them per reason; the
        # run uses those counts verbatim rather than guessing. An adapter
        # that does not classify leaves `rejections_by_reason` empty, and
        # its skips are recorded as UNCLASSIFIED - visible as a gap rather
        # than silently attributed to a reason nobody measured.
        duplicates = result.rejections_by_reason.get(RejectionReason.DUPLICATE.value, 0)
        if not result.rejections_by_reason:
            duplicates = self._duplicates_from_warnings(result)

        if duplicates:
            self.tally.records_duplicated += duplicates

        if result.rejections_by_reason:
            for reason_value, count in result.rejections_by_reason.items():
                if reason_value == RejectionReason.DUPLICATE.value:
                    continue  # counted as duplicated, not rejected
                self.tally.records_rejected += count
                self.tally.rejections_by_reason[reason_value] = (
                    self.tally.rejections_by_reason.get(reason_value, 0) + count
                )
        else:
            unclassified = max(0, result.records_skipped - duplicates)
            if unclassified:
                self.tally.records_rejected += unclassified
                self.tally.rejections_by_reason["UNCLASSIFIED"] = (
                    self.tally.rejections_by_reason.get("UNCLASSIFIED", 0) + unclassified
                )

        if result.status in ACQUISITION_FAILURE_STATUSES:
            self.errors.extend(result.errors)
        self.warnings.extend(result.warnings)

        if county:
            bucket = self.per_county.setdefault(
                county,
                {"records_acquired": 0, "records_failed": 0, "records_rejected": 0, "attempts": 0},
            )
            bucket["records_acquired"] += result.records_acquired
            bucket["records_failed"] += result.records_failed
            bucket["records_rejected"] += result.records_skipped
            bucket["attempts"] += 1

    @staticmethod
    def _duplicates_from_warnings(result: AcquisitionResult) -> int:
        for warning in result.warnings:
            if "duplicate" in warning.lower():
                for token in warning.split():
                    if token.isdigit():
                        return int(token)
        return 0

    def mark_blocked(self, reason: str, *, environment_status: str) -> None:
        """The environment (not the source) prevented the run. Recorded as
        its own terminal status so it can never be mistaken for a source
        failure or for an empty-but-successful run."""
        self.status = RunStatus.BLOCKED
        self.environment_status = environment_status
        self.errors.append(reason)
        self.completed_at = datetime.now(timezone.utc).isoformat()

    # -- validation ---------------------------------------------------
    def denominator_check(self, expected: int | None) -> DenominatorCheck:
        return DenominatorCheck(
            expected=expected,
            observed_at_source=self.tally.records_observed_at_source,
            acquired=self.tally.records_acquired,
            rejected=self.tally.records_rejected,
            failed=self.tally.records_failed,
        )

    def finalize(self, *, expected_denominator: int | None = None) -> DenominatorCheck:
        """Close the run and assign its true status.

        `COMPLETE` requires ALL of: no failures, pagination observed as
        exhausted, a balanced tally, and a passing denominator check. Any
        one of those missing yields `PARTIAL` or `INCOMPLETE` - never
        `COMPLETE`."""
        if self.status == RunStatus.BLOCKED:
            return self.denominator_check(expected_denominator)

        self.completed_at = datetime.now(timezone.utc).isoformat()
        check = self.denominator_check(expected_denominator)

        if not self.tally.is_balanced:
            self.warnings.append(
                f"tally is unbalanced: {self.tally.records_seen} seen vs {self.tally.accounted_for} accounted for "
                f"({self.tally.unaccounted:+d} unaccounted)"
            )

        has_failures = self.tally.records_failed > 0 or any(
            r.status in ACQUISITION_FAILURE_STATUSES for r in self.results
        )
        produced_anything = any(r.status in ACQUISITION_PRODUCED_RECORDS for r in self.results)

        if not produced_anything:
            self.status = RunStatus.INCOMPLETE
        elif has_failures or not self.pagination_exhausted or not self.tally.is_balanced or not check.passed:
            self.status = RunStatus.PARTIAL
        else:
            self.status = RunStatus.COMPLETE
        return check

    # -- reporting ----------------------------------------------------
    def county_coverage(self) -> list[dict]:
        """Phase 41 Section 7's per-county report. `coverage_percentage` is
        `None` - never 0 or 100 - when no per-county denominator was
        measured."""
        from .roster import observed_record_count

        rows = []
        for county in sorted(self.per_county):
            bucket = self.per_county[county]
            observed = observed_record_count(county, self.source_id, state=self.state)
            acquired = bucket["records_acquired"]
            rows.append({
                "county": county,
                "records_observed_at_source": observed,
                "records_acquired": acquired,
                "records_normalized": acquired,
                "records_failed": bucket["records_failed"],
                "coverage_percentage": (
                    round(100.0 * acquired / observed, 2) if observed else None
                ),
            })
        return rows

    def field_completeness(self, fields: tuple[str, ...]) -> list[dict]:
        """Phase 41 Section 13's field-level report over every acquired
        record in this run."""
        records = [r for result in self.results for r in result.records]
        rows = []
        for name in fields:
            present, total, pct = field_coverage(records, name)
            rows.append({
                "field": name,
                "expected": total,
                "present": present,
                "missing": total - present,
                "coverage_percentage": pct,
            })
        return rows

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "state": self.state,
            "status": self.status.value,
            "environment_status": self.environment_status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "pages_retrieved": self.pages_retrieved,
            "pagination_exhausted": self.pagination_exhausted,
            "tally": self.tally.to_dict(),
            "health": self.health.to_dict() if self.health else None,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


# The Texas source-side denominator Phase 40 measured from `?state=TX`,
# independently of any acquisition run. Kept as a named constant so a run
# can never validate itself against a number it produced.
#
# NOTE the deliberate exclusion of 6,309 (`?area=TX`): that figure includes
# 2,104 Philadelphia, PA records and is NOT the Texas denominator. Phase 41
# Section 6 is explicit - "Do NOT use 6,309 as the Texas denominator."
TX_LGBS_STATE_DENOMINATOR = 4205
TX_LGBS_AREA_TX_TOTAL = 6309
TX_LGBS_PA_TOTAL = 2104
TX_LGBS_UNATTRIBUTED = 8

assert TX_LGBS_STATE_DENOMINATOR + TX_LGBS_PA_TOTAL == TX_LGBS_AREA_TX_TOTAL, (
    "the Phase 40 arithmetic must hold: state=TX + state=PA == area=TX"
)
