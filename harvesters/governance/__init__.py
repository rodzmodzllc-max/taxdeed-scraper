"""Source-governance, approval, provenance, and restriction framework -
Phase 10A (Commercial Source Governance Infrastructure).

Re-exports the names most callers need, so e.g.
`from harvesters.governance import check_ingestion_gate, SOURCE_REGISTRY`
works without reaching into each submodule individually. See:

  - registry.py     - SourceStatus, SourceRecord, SOURCE_REGISTRY, get_source()
  - restrictions.py - Restriction, BLOCKS_CUSTOMER_DISPLAY, BLOCKS_API_EXPORT
  - gate.py          - GateDecision, check_ingestion_gate(), filter_rows_for_customer_output(), filter_rows_for_api_export()
  - provenance.py    - PipelineStage, FieldClassification, Provenance, advance(), derive(), origin_source_ids()
"""

from .gate import (
    GateDecision,
    check_ingestion_gate,
    filter_rows_for_api_export,
    filter_rows_for_customer_output,
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
from .restrictions import BLOCKS_API_EXPORT, BLOCKS_CUSTOMER_DISPLAY, Restriction

__all__ = [
    "GateDecision",
    "check_ingestion_gate",
    "filter_rows_for_api_export",
    "filter_rows_for_customer_output",
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
    "Restriction",
]
