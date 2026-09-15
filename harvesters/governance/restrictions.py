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
# gate.filter_rows_for_customer_output() and gate.project_row_for_customer_
# output()). Kept as an explicit set here (data), not an inline check
# scattered across call sites.
#
# FIELD_SPECIFIC_RESTRICTION is included here (Phase 11 addition) for a
# fail-closed reason, not a broadening of intent: this registry's data
# model (SourceRecord.restrictions: tuple[Restriction, ...]) records THAT a
# field-specific restriction exists but not WHICH field it applies to -
# there is no restriction-to-field-name mapping anywhere in this codebase
# today. A restriction this module cannot resolve to a specific field
# cannot be safely narrowed to "suppress just that field" - per Phase 11's
# own instruction ("Unknown restriction -> deny exposure"), the only safe
# behavior until a future extension adds a field-name mapping is to block
# the whole row, the same as an unresolvable/unknown restriction would be.
# As of this phase, zero registry entries carry FIELD_SPECIFIC_RESTRICTION
# (see harvesters/governance/registry.py) - this is a forward-looking,
# zero-behavior-change-today addition, exercised only by
# tests/python/test_customer_api_enforcement.py's synthetic fixtures.
BLOCKS_CUSTOMER_DISPLAY = frozenset(
    {
        Restriction.NO_CUSTOMER_DISPLAY,
        Restriction.NO_REDISTRIBUTION,
        Restriction.SOURCE_ONLY_DISPLAY,
        Restriction.FIELD_SPECIFIC_RESTRICTION,
    }
)

# Restrictions that block a source's rows from an API/export surface
# specifically (a stricter or equal subset of BLOCKS_CUSTOMER_DISPLAY -
# anything that blocks customer display also blocks export, since export
# is itself a form of customer-facing display, plus NO_API_EXPORT itself).
BLOCKS_API_EXPORT = BLOCKS_CUSTOMER_DISPLAY | {Restriction.NO_API_EXPORT}


# Phase 11 (Customer/API Data-Restriction Enforcement) addition: a
# name-pattern mapping used by gate.py's row-projection functions to strip
# individual restricted-content-shaped fields from an otherwise-permitted
# row, rather than blocking the entire row (Restriction.NO_RAW_HTML /
# NO_IMAGES / NO_DOCUMENTS are field-shaped restrictions - a source can be
# APPROVED_WITH_RESTRICTIONS carrying one of these while every other field
# on its rows remains fully displayable).
#
# Deliberately keyword/substring-based rather than a fixed per-schema
# field allowlist: as of this phase, NEITHER TexasSaleRow
# (harvesters/texas_harvester.py) NOR the row dict
# scripts/sync-texas-to-supabase.py builds for Supabase contains any
# raw-HTML, image, or document field at all (confirmed by inspection -
# LGBS is a JSON API with no such fields; RealAuction's harvester extracts
# already-structured values, never raw page HTML or image/document URLs).
# This mapping is therefore provably inert today (see
# test_no_field_shape_keyword_matches_any_current_tx_row_field in the new
# test suite) and activates automatically, without a code change, the
# moment a future field whose name contains one of these keywords is
# added to a harvested row - rather than requiring every future harvester
# change to remember to also update an enforcement allowlist.
FIELD_SHAPE_KEYWORDS: dict[Restriction, tuple[str, ...]] = {
    Restriction.NO_RAW_HTML: ("raw_html", "html_raw", "page_html", "raw_body"),
    Restriction.NO_IMAGES: ("image", "img_url", "photo_url", "photo"),
    Restriction.NO_DOCUMENTS: ("document_url", "doc_url", "pdf_url", "document", "attachment_url"),
}


def restriction_from_str(value: str) -> Restriction:
    """Tolerant lookup so registry entries (and any future config-driven
    registry backing, e.g. a DB table) can specify restrictions by their
    plain string value without importing the enum everywhere."""
    return Restriction(value)
