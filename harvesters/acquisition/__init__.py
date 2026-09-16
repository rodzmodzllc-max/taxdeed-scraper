"""Acquisition engine - Phase 39 (Acquisition Engine & Full Data
Activation).

Turns the Phase 37/38 verified source map into a reusable technical
acquisition system. The five-layer model is preserved exactly:

    DISCOVERY -> VERIFICATION -> TECHNICAL ACQUISITION -> AUTHORIZATION -> PRODUCTION

This package owns the THIRD layer only. It never decides the fourth or
fifth: `policy.py` delegates every authorization question to
`harvesters/governance/` (Phases 10A/34A/34B/37/37-38), and nothing here
can return a more permissive answer than those layers already do.

Modules:
  - result.py       - AcquisitionStatus/AcquisitionResult/RetrievalMetadata (Sections 12-13)
  - transport.py    - injectable Transport, RateLimitPolicy, CircuitBreaker (Section 15)
  - adapter.py      - the SourceAdapter contract, provenance, idempotency (Sections 11, 29, 57)
  - policy.py       - pre-acquisition gate; testing vs production purpose (Sections 8, 16, 17)
  - categories.py   - DataCategory taxonomy and source tiers (Sections 6, 19, 27)
  - config.py       - county->mechanism configuration (Sections 5, 26, 47)
  - completeness.py - coverage metrics, missing-data reasons, source health (Sections 33-36)
  - checkpoint.py   - resumability (Section 56)
  - adapters/       - concrete adapters (JSON API, ArcGIS REST)
"""

from .adapter import (
    PROVENANCE_KEYS,
    AdapterConfig,
    SourceAdapter,
    deduplicate,
    has_provenance,
    idempotency_key,
    utc_now_iso,
)
from .categories import (
    BINARY_CATEGORIES,
    DATASET_PRIORITY,
    MATRIX_COLUMN_TO_CATEGORY,
    DataCategory,
    SourceTier,
    priority_rank,
    tier_rank,
)
from .checkpoint import Checkpoint, CheckpointStore
from .completeness import (
    ACQUISITION_STATUS_TO_MISSING_REASON,
    CoverageMetrics,
    MissingDataReason,
    SourceHealth,
    ValueConflict,
    classify_missing,
    detect_conflicts,
    field_coverage,
    metrics_from_results,
)
from .config import (
    IMPLEMENTED_MECHANISMS,
    SOURCE_MECHANISM,
    AcquisitionMechanism,
    CountySourceConfig,
    build_county_configs,
    counties_with_adapter,
    mechanism_summary,
)
from .policy import (
    HARD_REFUSAL_STATUSES,
    UNRESOLVED_STATUSES,
    AcquisitionPolicyDecision,
    AcquisitionPurpose,
    binary_content_allowed,
    check_acquisition_policy,
    check_fallback_allowed,
)
from .roster import (
    TX_LGBS_ROSTER_PATH,
    UNATTRIBUTED_RESIDUAL,
    ObservedCountyRecord,
    load_tx_lgbs_roster,
    observed_counties,
    observed_record_count,
    roster_totals,
)
from .result import (
    ACQUISITION_FAILURE_STATUSES,
    ACQUISITION_PRODUCED_RECORDS,
    AcquisitionResult,
    AcquisitionStatus,
    RawStorageStatus,
    RetrievalMetadata,
    TechnicalAcquisitionState,
    build_result,
    content_hash,
)
from .transport import (
    AccessRestricted,
    AuthenticationRequired,
    CircuitBreaker,
    EnvironmentBlockedTransport,
    EnvironmentEgressBlocked,
    FixtureTransport,
    RateLimited,
    RateLimitPolicy,
    SchemaError,
    SourceUnavailable,
    Transport,
    TransportError,
    TransportResponse,
    UrllibTransport,
)

__all__ = [
    # result
    "ACQUISITION_FAILURE_STATUSES",
    "ACQUISITION_PRODUCED_RECORDS",
    "AcquisitionResult",
    "AcquisitionStatus",
    "RawStorageStatus",
    "RetrievalMetadata",
    "TechnicalAcquisitionState",
    "build_result",
    "content_hash",
    # transport
    "AccessRestricted",
    "AuthenticationRequired",
    "CircuitBreaker",
    "EnvironmentBlockedTransport",
    "EnvironmentEgressBlocked",
    "FixtureTransport",
    "RateLimitPolicy",
    "RateLimited",
    "SchemaError",
    "SourceUnavailable",
    "Transport",
    "TransportError",
    "TransportResponse",
    "UrllibTransport",
    # adapter
    "PROVENANCE_KEYS",
    "AdapterConfig",
    "SourceAdapter",
    "deduplicate",
    "has_provenance",
    "idempotency_key",
    "utc_now_iso",
    # policy
    "HARD_REFUSAL_STATUSES",
    "UNRESOLVED_STATUSES",
    "AcquisitionPolicyDecision",
    "AcquisitionPurpose",
    "binary_content_allowed",
    "check_acquisition_policy",
    "check_fallback_allowed",
    # categories
    "BINARY_CATEGORIES",
    "DATASET_PRIORITY",
    "MATRIX_COLUMN_TO_CATEGORY",
    "DataCategory",
    "SourceTier",
    "priority_rank",
    "tier_rank",
    # config
    "IMPLEMENTED_MECHANISMS",
    "SOURCE_MECHANISM",
    "AcquisitionMechanism",
    "CountySourceConfig",
    "build_county_configs",
    "counties_with_adapter",
    "mechanism_summary",
    # completeness
    "ACQUISITION_STATUS_TO_MISSING_REASON",
    "CoverageMetrics",
    "MissingDataReason",
    "SourceHealth",
    "ValueConflict",
    "classify_missing",
    "detect_conflicts",
    "field_coverage",
    "metrics_from_results",
    # checkpoint
    "Checkpoint",
    "CheckpointStore",
    # roster (Phase 40)
    "TX_LGBS_ROSTER_PATH",
    "UNATTRIBUTED_RESIDUAL",
    "ObservedCountyRecord",
    "load_tx_lgbs_roster",
    "observed_counties",
    "observed_record_count",
    "roster_totals",
]
