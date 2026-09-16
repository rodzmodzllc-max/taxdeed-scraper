"""The SourceAdapter contract - Phase 39 Section 11.

Section 11's own instruction is followed literally: "Do not blindly use
this exact interface if the repository already has a better pattern. The
important requirement is a common contract."

The pattern this repository already has, and which this contract adopts
rather than replaces, is the **fetch/normalize split** that
`scripts/enrich_property_details_tx.py` arrived at independently:

    _fetch_hcad(parcel_id)            -> raw ArcGIS attributes   (network)
    hcad_attributes_to_generic(attrs) -> generic dict            (pure)
    normalize_cad_response(generic)   -> properties-table fields (pure)

and which `harvesters/texas_harvester.py` uses too (`harvest_lgbs()`'s
pagination loop around the pure `_lgbs_normalize_county()`/
`_lgbs_to_float()`/`_lgbs_compose_address()` helpers). That split is
already the right one: it is why those normalizers are testable today
without a network, and it is why this phase could verify HCAD's live field
contract without touching any parsing code. `SourceAdapter` formalizes it
and adds the three things that were missing: an injected transport, a
structured result, and a policy check that runs BEFORE any request.

What an adapter must never do (enforced by the tests in
`tests/python/test_phase39_acquisition_engine.py`):

  - reach the network directly - it goes through `self.transport`;
  - decide its own legal status - it calls `check_acquisition_policy()`;
  - return a bare list or `None` - it returns an `AcquisitionResult`;
  - invent a field the source did not publish (the "never fabricate a
    field the source doesn't publish" discipline this repository's
    Florida harvesters already state in their own docstrings).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .categories import DataCategory, SourceTier
from .policy import AcquisitionPolicyDecision, AcquisitionPurpose, check_acquisition_policy
from .result import (
    AcquisitionResult,
    AcquisitionStatus,
    RawStorageStatus,
    RetrievalMetadata,
    build_result,
)
from .transport import Transport, TransportError, UrllibTransport


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AdapterConfig:
    """Everything that varies between deployments of the SAME acquisition
    mechanism. Section 5's core requirement - "county configuration should
    drive reusable adapters" - is this dataclass: adding Dallas County's
    CAD is a new `AdapterConfig`, not a new module.

    `raw_storage_permitted` defaults to False (Section 14's fail-closed
    posture): a source must be affirmatively marked as permitting raw
    retention before any adapter keeps a payload.
    """

    source_id: str
    state: str
    county: str | None  # None = statewide / multi-county
    base_url: str
    categories: tuple[DataCategory, ...]
    tier: SourceTier
    retrieval_method: str
    field_map: dict = field(default_factory=dict)
    query_params: dict = field(default_factory=dict)
    raw_storage_permitted: bool = False
    page_size: int | None = None
    notes: str = ""

    @property
    def jurisdiction(self) -> str:
        """Always state-qualified - Section 30's "do not use county name
        alone as a universal identifier" and Section 50's adversarial test
        6 (Florida and Texas identities cannot collide)."""
        return f"{self.state}/{self.county}" if self.county else f"{self.state}/statewide"


class SourceAdapter(abc.ABC):
    """One acquisition mechanism. Subclasses implement `_acquire()` and
    `normalize()`; everything else - policy checking, result construction,
    error classification, retrieval bookkeeping - is handled here so no
    adapter can accidentally skip it."""

    def __init__(self, config: AdapterConfig, transport: Transport | None = None):
        self.config = config
        self.transport = transport or UrllibTransport()
        self._retrievals: list[RetrievalMetadata] = []

    # -- identity -----------------------------------------------------
    @property
    def source_id(self) -> str:
        return self.config.source_id

    @property
    def jurisdiction(self) -> str:
        return self.config.jurisdiction

    @property
    def categories(self) -> tuple[DataCategory, ...]:
        return self.config.categories

    # -- the contract -------------------------------------------------
    def discover(self) -> AcquisitionPolicyDecision:
        """Is this source represented and reachable in principle? Returns
        the policy decision rather than a boolean, so a caller always has
        the reason."""
        return check_acquisition_policy(
            self.source_id,
            purpose=AcquisitionPurpose.INTERNAL_TECHNICAL_TESTING,
            state=self.config.state,
            county=self.config.county,
        )

    def verify(self) -> AcquisitionResult:
        """A minimal, single-request technical check: does the endpoint
        answer, and does it carry the fields this adapter expects? Runs
        under `INTERNAL_TECHNICAL_TESTING` purpose (Section 17). Default
        implementation performs one `acquire()` limited to a single record;
        subclasses may override for a cheaper probe."""
        return self.acquire(limit=1, purpose=AcquisitionPurpose.INTERNAL_TECHNICAL_TESTING)

    def health_check(self) -> AcquisitionResult:
        """Alias of `verify()` kept because Section 11 names both; source
        HEALTH over time is computed by `health.py` from stored results,
        not by this single call."""
        return self.verify()

    def acquire(
        self,
        *,
        limit: int | None = None,
        purpose: AcquisitionPurpose = AcquisitionPurpose.PRODUCTION_ACQUISITION,
        checkpoint: dict | None = None,
    ) -> AcquisitionResult:
        """Template method. Policy is checked first, always; a refusal
        short-circuits before any network call is made."""
        started_at = utc_now_iso()
        self._retrievals = []

        decision = check_acquisition_policy(
            self.source_id,
            purpose=purpose,
            state=self.config.state,
            county=self.config.county,
            use="INGEST",
        )
        if not decision.allowed:
            return build_result(
                source_id=self.source_id,
                jurisdiction=self.jurisdiction,
                status=AcquisitionStatus.LEGAL_RESTRICTION,
                started_at=started_at,
                retrieval_method=self.config.retrieval_method,
                categories=tuple(c.value for c in self.categories),
                errors=(decision.reason,),
                raw_storage_status=RawStorageStatus.NOT_APPLICABLE,
            )

        try:
            return self._acquire(started_at=started_at, limit=limit, checkpoint=checkpoint)
        except TransportError as exc:
            return build_result(
                source_id=self.source_id,
                jurisdiction=self.jurisdiction,
                status=exc.status,
                started_at=started_at,
                retrieval_method=self.config.retrieval_method,
                categories=tuple(c.value for c in self.categories),
                errors=(f"{exc.error_code}: {exc}",),
                retrievals=tuple(self._retrievals),
                raw_storage_status=self._raw_storage_status(),
            )

    @abc.abstractmethod
    def _acquire(
        self, *, started_at: str, limit: int | None, checkpoint: dict | None
    ) -> AcquisitionResult:  # pragma: no cover - abstract
        """Subclass hook. May raise any `TransportError`; `acquire()`
        converts it into a correctly-classified result."""

    @abc.abstractmethod
    def normalize(self, raw_record: dict) -> dict | None:  # pragma: no cover - abstract
        """Map one raw source record into this project's normalized shape.
        Returns `None` for a record that should be skipped (not an error).
        Must attach provenance via `attach_provenance()`."""

    # -- helpers available to every adapter ---------------------------
    def _raw_storage_status(self) -> RawStorageStatus:
        return RawStorageStatus.NOT_STORED if self.config.raw_storage_permitted else RawStorageStatus.RESTRICTED

    def record_retrieval(self, metadata: RetrievalMetadata) -> None:
        self._retrievals.append(metadata)

    def attach_provenance(
        self,
        record: dict,
        *,
        source_record_id: str | None,
        retrieved_at: str,
        source_timestamp: str | None = None,
        normalization_version: str = "1",
    ) -> dict:
        """Section 28/29: every normalized record carries where it came
        from. These five keys are the acquisition engine's provenance
        contract and are asserted by the test suite; they are deliberately
        prefixed so they can never collide with a source's own field
        names."""
        record = dict(record)
        record["_source_id"] = self.source_id
        record["_source_record_id"] = source_record_id
        record["_retrieved_at"] = retrieved_at
        record["_source_timestamp"] = source_timestamp
        record["_normalization_version"] = normalization_version
        return record


PROVENANCE_KEYS = (
    "_source_id",
    "_source_record_id",
    "_retrieved_at",
    "_source_timestamp",
    "_normalization_version",
)


def has_provenance(record: dict) -> bool:
    """Section 29's lineage requirement, as a checkable predicate."""
    return all(key in record for key in PROVENANCE_KEYS)


def idempotency_key(record: dict) -> tuple:
    """Section 57: stable identity for deduplication across repeated runs.

    Uses `(_source_id, _source_record_id)` - the source's OWN identifier,
    never a hash of mutable content (a re-published record with a corrected
    bid must dedupe to the same key, not look like a new record). Falls
    back to the normalized `case_no`/`county`/`state` triple this
    repository's existing `(state, source, county, case_no)` uniqueness
    constraint already uses (migration 004), so the acquisition engine's
    notion of identity cannot diverge from the database's.
    """
    source_record_id = record.get("_source_record_id")
    if source_record_id:
        return (record.get("_source_id"), source_record_id)
    return (
        record.get("state"),
        record.get("_source_id"),
        record.get("county"),
        record.get("case_no") or record.get("account_number"),
    )


def deduplicate(records: list[dict]) -> tuple[list[dict], int]:
    """Returns `(unique_records, duplicates_dropped)`. Keeps the FIRST
    occurrence - a later page re-listing an earlier record (real, observed
    behavior on paginated sources) must not overwrite the first copy with
    a partial one."""
    seen: set[tuple] = set()
    unique: list[dict] = []
    dropped = 0
    for record in records:
        key = idempotency_key(record)
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        unique.append(record)
    return unique, dropped
