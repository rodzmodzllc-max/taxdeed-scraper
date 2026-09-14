"""Restriction vocabulary - Phase 10A (Commercial Source Governance
Infrastructure).

Restrictions are explicit, enumerable data attached to a SourceRecord
(see registry.py), never comments buried in harvester code. A restriction
travels with a source's data through the pipeline (see provenance.py) and
is checked at the ingestion gate (see gate.py) and at customer/API output
time - never silently dropped by a transformation.

This module intentionally holds ONLY the restriction vocabulary and a
couple of small, restriction-shaped helpers. It has no knowledge of any
particular source (see registry.py for that) and no knowledge of any
particular row/dataclass shape (see provenance.py for that) - kept small
and dependency-free on purpose so both of those can import it without a
circular-import risk.
"""

from __future__ import annotations

from enum import Enum


class Restriction(str, Enum):
    """One discrete, checkable restriction a source's rights review may
    have found. A SourceRecord carries zero or more of these
    (`SourceRecord.restrictions`); every one of them must remain
    attached to a value all the way through RAW -> ... -> EXPORT/API
    (see provenance.py's `advance()`/`derive()` - restrictions are only
    ever unioned in, never dropped)."""

    ATTRIBUTION_REQUIRED = "attribution_required"
    NO_RAW_HTML = "no_raw_html"
    NO_IMAGES = "no_images"
    NO_DOCUMENTS = "no_documents"
    NO_REDISTRIBUTION = "no_redistribution"
    NO_CUSTOMER_DISPLAY = "no_customer_display"
    NO_API_EXPORT = "no_api_export"
    NO_HISTORICAL_RETENTION = "no_historical_retention"
    FIELD_SPECIFIC_RESTRICTION = "field_specific_restriction"
    RATE_LIMIT = "rate_limit"
    RETENTION_PERIOD = "retention_period"
    SOURCE_ONLY_DISPLAY = "source_only_display"
    OTHER_CONTRACTUAL_RESTRICTION = "other_contractual_restriction"


# Restrictions that, if present on a source, mean rows from that source
# must never reach a customer-visible surface at all (used by
# gate.filter_rows_for_customer_output()). Kept as an explicit set here
# (data), not an inline check scattered across call sites.
BLOCKS_CUSTOMER_DISPLAY = frozenset(
    {
        Restriction.NO_CUSTOMER_DISPLAY,
        Restriction.NO_REDISTRIBUTION,
        Restriction.SOURCE_ONLY_DISPLAY,
    }
)

# Restrictions that block a source's rows from an API/export surface
# specifically (a stricter or equal subset of BLOCKS_CUSTOMER_DISPLAY -
# anything that blocks customer display also blocks export, since export
# is itself a form of customer-facing display, plus NO_API_EXPORT itself).
BLOCKS_API_EXPORT = BLOCKS_CUSTOMER_DISPLAY | {Restriction.NO_API_EXPORT}


def restriction_from_str(value: str) -> Restriction:
    """Tolerant lookup so registry entries (and any future config-driven
    registry backing, e.g. a DB table) can specify restrictions by their
    plain string value without importing the enum everywhere."""
    return Restriction(value)
