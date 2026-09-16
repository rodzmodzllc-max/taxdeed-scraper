"""Source-governance, approval, provenance, and restriction framework -
Phase 10A (Commercial Source Governance Infrastructure).

Re-exports the names most callers need, so e.g.
`from harvesters.governance import check_ingestion_gate, SOURCE_REGISTRY`
works without reaching into each submodule individually. See:

  - registry.py       - SourceStatus, SourceRecord, SOURCE_REGISTRY, get_source()
  - restrictions.py   - Restriction, BLOCKS_CUSTOMER_DISPLAY, BLOCKS_API_EXPORT
  - gate.py            - GateDecision, check_ingestion_gate(), filter_rows_for_customer_output(), filter_rows_for_api_export(), project_row_for_customer_output(), project_row_for_api_export() (Phase 11)
  - provenance.py      - PipelineStage, FieldClassification, Provenance, advance(), derive(), origin_source_ids()
  - authorization.py   - AuthorizationStatus, ProviderAuthorization, PROVIDER_AUTHORIZATIONS, check_authorized_use() (Phase 34A - provider/county-level "requested vs authorized" tracking, additive to and never weakening the gate above)
  - source_catalog.py  - AcquisitionMethod, CoverageState, CatalogSource, gap_analysis() (Phase 35 - the discovery/classification-stage county/source catalog; distinct from, and never a substitute for, SOURCE_REGISTRY above)
  - promotion.py        - PROMOTION_USES, PromotionDecision, can_promote_source_for_use() (Phase 37 - the single "may this source be used for this exact purpose" decision, composing (1)/(2)/(3) above in a fixed, fail-closed order; holds no authorization data of its own)
  - verification.py     - DiscoveryStatus, VerificationStatus, TechnicalAcquisitionStatus, DataMissingReason, CountyReadinessState, SourceVerificationRecord, VendorCandidate, county_readiness()/all_county_readiness() (Phase 37/38 - the engineering-progress axis: how far has this project gotten in finding/inspecting/acquiring a source, kept strictly separate from legal authorization above; production status is always computed live via promotion.py, never stored)
"""

from .authorization import (
    AuthorizationDocument,
    AuthorizationScope,
    AuthorizationStatus,
    AuditLogEntry,
    PROVIDER_AUTHORIZATIONS,
    ProviderAuthorization,
    UseDecision,
    UsePermission,
    authorization_for_scope,
    authorizations_for_source,
    authorized_for_api_export,
    authorized_for_customer_output,
    authorized_for_ingestion,
    check_authorized_use,
    compute_terms_hash,
    effective_authorization_status,
    flag_terms_changed,
    terms_hash_mismatch,
)
from .gate import (
    GateDecision,
    check_ingestion_gate,
    filter_rows_for_api_export,
    filter_rows_for_customer_output,
    project_row_for_api_export,
    project_row_for_customer_output,
)
from .provenance import (
    FieldClassification,
    PipelineStage,
    Provenance,
    advance,
    derive,
    origin_source_ids,
)
from .registry import (
    INGESTION_ALLOWED_STATUSES,
    SOURCE_REGISTRY,
    SourceRecord,
    SourceStatus,
    all_sources,
    get_source,
)
from .promotion import (
    PROMOTION_USE_TO_SCOPE_DIMENSION,
    PROMOTION_USES,
    PromotionDecision,
    can_promote_source_for_use,
)
from .restrictions import BLOCKS_API_EXPORT, BLOCKS_CUSTOMER_DISPLAY, FIELD_SHAPE_KEYWORDS, Restriction
from .verification import (
    CountyReadinessState,
    DataMissingReason,
    DiscoveryStatus,
    SOURCE_VERIFICATION_RECORDS,
    SourceVerificationRecord,
    TechnicalAcquisitionStatus,
    VENDOR_CANDIDATES,
    VendorCandidate,
    VerificationStatus,
    all_county_readiness,
    all_vendor_candidates,
    all_verification_records,
    county_readiness,
    full_county_readiness,
    get_verification_record,
    production_enabled_for_county,
)
from .source_catalog import (
    AcquisitionMethod,
    CatalogSource,
    CoverageState,
    FL_COUNTY_COUNT,
    SourcePriorityTier,
    TX_COUNTY_COUNT,
    assert_every_terms_review_row_has_evidence,
    assert_matrix_completeness,
    gap_analysis,
    is_approved_status,
    is_unknown_or_unreviewed_status,
    load_fl_matrix,
    load_terms_review,
    load_tx_matrix,
)

__all__ = [
    "GateDecision",
    "check_ingestion_gate",
    "filter_rows_for_api_export",
    "filter_rows_for_customer_output",
    "project_row_for_api_export",
    "project_row_for_customer_output",
    "FieldClassification",
    "PipelineStage",
    "Provenance",
    "advance",
    "derive",
    "origin_source_ids",
    "INGESTION_ALLOWED_STATUSES",
    "SOURCE_REGISTRY",
    "SourceRecord",
    "SourceStatus",
    "all_sources",
    "get_source",
    "BLOCKS_API_EXPORT",
    "BLOCKS_CUSTOMER_DISPLAY",
    "FIELD_SHAPE_KEYWORDS",
    "Restriction",
    "AuthorizationDocument",
    "AuthorizationScope",
    "AuthorizationStatus",
    "AuditLogEntry",
    "PROVIDER_AUTHORIZATIONS",
    "ProviderAuthorization",
    "UseDecision",
    "UsePermission",
    "authorization_for_scope",
    "authorizations_for_source",
    "authorized_for_api_export",
    "authorized_for_customer_output",
    "authorized_for_ingestion",
    "check_authorized_use",
    "compute_terms_hash",
    "effective_authorization_status",
    "flag_terms_changed",
    "terms_hash_mismatch",
    "PROMOTION_USE_TO_SCOPE_DIMENSION",
    "PROMOTION_USES",
    "PromotionDecision",
    "can_promote_source_for_use",
    "AcquisitionMethod",
    "CatalogSource",
    "CoverageState",
    "FL_COUNTY_COUNT",
    "SourcePriorityTier",
    "TX_COUNTY_COUNT",
    "assert_every_terms_review_row_has_evidence",
    "assert_matrix_completeness",
    "gap_analysis",
    "is_approved_status",
    "is_unknown_or_unreviewed_status",
    "load_fl_matrix",
    "load_terms_review",
    "load_tx_matrix",
    "CountyReadinessState",
    "DataMissingReason",
    "DiscoveryStatus",
    "SOURCE_VERIFICATION_RECORDS",
    "SourceVerificationRecord",
    "TechnicalAcquisitionStatus",
    "VENDOR_CANDIDATES",
    "VendorCandidate",
    "VerificationStatus",
    "all_county_readiness",
    "all_vendor_candidates",
    "all_verification_records",
    "county_readiness",
    "full_county_readiness",
    "get_verification_record",
    "production_enabled_for_county",
]
