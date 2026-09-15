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
    effective_authorization_status,
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
from .restrictions import BLOCKS_API_EXPORT, BLOCKS_CUSTOMER_DISPLAY, FIELD_SHAPE_KEYWORDS, Restriction

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
    "effective_authorization_status",
]
