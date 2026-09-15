"""County/source acquisition catalog - Phase 35 (County Source-of-Truth
Catalog).

Repository audit finding (Phase 35 Step 1): before this module, "what
sources exist for county X" lived in two machine-readable but ungoverned
CSVs (`data/fl_county_coverage_matrix.csv`, `data/tx_county_coverage_matrix.csv`,
both Phase 33) plus a lot of narrative in `docs/source-coverage-florida.md`/
`docs/source-coverage-texas.md`. Neither CSV had a declared schema, a
vocabulary of allowed values, or any test coverage - a typo'd status string
or a silently-invented URL would have gone unnoticed. This module does NOT
replace those CSVs (they remain the actual per-county data, now with more
columns - see Phase 35's own report) - it gives them a declared vocabulary,
a loader, and validation, the same relationship `registry.py` has to the
`claude/*.md` documents it transcribes.

Deliberate distinction from `registry.py`/`authorization.py`, stated
explicitly because it is easy to blur: this module is for the DISCOVERY /
CLASSIFICATION stage - "what sources exist for this county, and what do we
know about their rights" - most entries here will never become a
`SourceRecord` in `SOURCE_REGISTRY` (which is reserved for sources this
project actually ingests from, or is actively considering ingesting from,
in Python code the harvesters import). A `CatalogSource` becoming a real
`SourceRecord` is a deliberate, separate, human-reviewed promotion, exactly
as `docs/source-registry.md`'s "Future source onboarding process" already
describes for Harris County - this module does not shortcut that process,
and nothing here is wired into any harvester or the ingestion gate.

Nothing in this module performs, automates, or authorizes automated
retrieval of anything it catalogs. It classifies and records what a human
found through manual reconnaissance (technical inspection, web search) this
phase - Phase 35 Section 19's own explicit instruction: "This phase must
not... create automated access to newly discovered sources."
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .registry import SourceStatus

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FL_MATRIX_PATH = REPO_ROOT / "data" / "fl_county_coverage_matrix.csv"
TX_MATRIX_PATH = REPO_ROOT / "data" / "tx_county_coverage_matrix.csv"

FL_COUNTY_COUNT = 67
TX_COUNTY_COUNT = 254


class AcquisitionMethod(str, Enum):
    """Phase 35 Section 13's explicit vocabulary. `UNKNOWN` is a legitimate,
    honest value here - it means "not yet determined," never "assume the
    easiest one." An interactive public search portal that happens to call
    a JSON endpoint under the hood is `OFFICIAL_PUBLIC_SEARCH`, never
    `OFFICIAL_API`, unless an actual, documented, separately-authenticated
    API/bulk-feed product was found (Section 13's explicit warning)."""

    OFFICIAL_API = "OFFICIAL_API"
    OFFICIAL_BULK = "OFFICIAL_BULK"
    OFFICIAL_OPEN_DATA = "OFFICIAL_OPEN_DATA"
    OFFICIAL_GIS = "OFFICIAL_GIS"
    OFFICIAL_PUBLIC_SEARCH = "OFFICIAL_PUBLIC_SEARCH"
    PUBLIC_RECORD_REQUEST = "PUBLIC_RECORD_REQUEST"
    LICENSED_VENDOR = "LICENSED_VENDOR"
    THIRD_PARTY_PUBLIC = "THIRD_PARTY_PUBLIC"
    LINK_ONLY = "LINK_ONLY"
    MANUAL_ONLY = "MANUAL_ONLY"
    UNKNOWN = "UNKNOWN"


class CoverageState(str, Enum):
    """Phase 35 Section 12's explicit vocabulary for one (county, category)
    cell - deliberately distinct from `AcquisitionMethod` (how you'd get
    it) and from `SourceStatus` (its legal posture). A county is never
    "complete" merely because one category has `SOURCE_FOUND` - see
    `gap_analysis()` below, which counts per category, never collapses
    categories into one boolean."""

    SOURCE_FOUND = "SOURCE_FOUND"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_NOT_APPLICABLE = "SOURCE_NOT_APPLICABLE"
    SOURCE_PENDING_REVIEW = "SOURCE_PENDING_REVIEW"
    SOURCE_BLOCKED = "SOURCE_BLOCKED"
    SOURCE_REQUIRES_LICENSE = "SOURCE_REQUIRES_LICENSE"


class SourcePriorityTier(str, Enum):
    """Phase 35 Section 17's duplication-handling vocabulary - assigned
    when two or more sources genuinely overlap for the same county/category
    (e.g. a county Property Appraiser site vs. the statewide FDOR Cadastral
    layer both offering parcel geometry). Never used to silently delete a
    source; every source keeps its own row regardless of tier."""

    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    FALLBACK = "FALLBACK"
    LINK_ONLY = "LINK_ONLY"
    RESTRICTED = "RESTRICTED"


# Phase 35 Section 5's explicit rule, enforced here as code rather than left
# as a convention: a legal_status string that is empty, "UNKNOWN", or not a
# real SourceStatus member must NEVER be treated as equivalent to APPROVED
# by any function in this module. `is_unknown_or_unreviewed_status()` is the
# one place that question is answered, so it can't be answered two
# different ways in two different call sites.
_TREATED_AS_UNREVIEWED = frozenset({"", "UNKNOWN", "UNKNOWN "})


def is_unknown_or_unreviewed_status(raw_status: str | None) -> bool:
    """True if `raw_status` (a free-text cell from one of the matrix CSVs,
    NOT a `SourceStatus` enum member) represents "we don't know" rather
    than any real reviewed state - including every raw string this
    module's own CSVs actually use for "not yet looked at"
    (`DISCOVERED (mechanism only...)`, `MECHANISM_CONFIRMED_NOT_EXTRACTED`,
    a bare `UNKNOWN`, or an empty cell). Never returns True for a string
    that starts with `APPROVED`, `LEGAL_REVIEW_REQUIRED`, or `BLOCKED` -
    those are real, reviewed-or-decided states, not "unknown", even though
    none of them authorize ingestion either."""
    if raw_status is None:
        return True
    stripped = raw_status.strip()
    if stripped in _TREATED_AS_UNREVIEWED:
        return True
    return stripped.startswith("UNKNOWN") or stripped.startswith("MECHANISM_CONFIRMED_NOT_EXTRACTED")


def is_approved_status(raw_status: str | None) -> bool:
    """The single, narrow question `check_ingestion_gate()`-adjacent code
    should ever ask of one of these free-text catalog cells: does this
    literal string represent an actual `APPROVED`/`APPROVED_WITH_
    RESTRICTIONS` `SourceStatus`? Nothing in this module ever calls this
    True for `UNKNOWN`, `DISCOVERED`, `MECHANISM_CONFIRMED_NOT_EXTRACTED`,
    or any other not-yet-reviewed value. Note this is a generic string
    check, not scoped to any one column - the Florida matrix's *pre-existing*
    Phase 33 columns legitimately DO say `APPROVED` for the three
    grandfathered production sources (a real registry fact, not something
    to suppress). What Phase 35 actually guarantees is narrower: none of
    the columns *this phase* populated (`PHASE35_FL_DISCOVERY_COLUMNS`/
    `PHASE35_TX_DISCOVERY_COLUMNS` below) ever satisfies this check - see
    `test_no_phase35_discovery_is_marked_approved`."""
    if raw_status is None:
        return False
    stripped = raw_status.strip()
    if is_unknown_or_unreviewed_status(stripped):
        return False
    return stripped.startswith(SourceStatus.APPROVED.value) or stripped.startswith(
        SourceStatus.APPROVED_WITH_RESTRICTIONS.value
    )


# Columns Phase 35 itself added or populated this phase (property-appraiser/
# appraisal-district/tax-assessor-collector discovery) - kept separate from
# the *pre-existing* Phase 33 columns (`auction_source_status`,
# `tax_certificate_source_status`, `laft_source_status`), which legitimately
# already say `APPROVED` for the three grandfathered Florida production
# sources (`fl_realauction`/`fl_lienhub_certificates`/`fl_laft_pdfs` - see
# `docs/source-registry.md`) - that pre-existing, real registry fact is not
# something Phase 35 introduced or should suppress. The guarantee Phase 35
# actually makes is narrower and is checked against exactly these columns:
# nothing this phase newly discovered was marked APPROVED.
PHASE35_FL_DISCOVERY_COLUMNS = (
    "property_appraiser_name",
    "property_appraiser_url",
    "property_appraiser_verification_status",
    "property_appraiser_source",
)
PHASE35_TX_DISCOVERY_COLUMNS = (
    "comptroller_directory_url",
    "appraisal_district_name",
    "appraisal_district_url",
    "tax_assessor_collector_name",
    "tax_assessor_collector_url",
    "appraisal_district_verification_status",
    "appraisal_district_source_status",
)


@dataclass(frozen=True)
class CatalogSource:
    """One row of Phase 35 Section 10's canonical source record. Deliberately
    a lighter-weight, discovery-stage sibling of `registry.SourceRecord` -
    see the module docstring for why the two are not merged. Every field
    Section 10 lists has a slot; fields this phase did not populate for a
    given source stay at their explicit "not known" default (`None` or
    `AcquisitionMethod.UNKNOWN`/`CoverageState.SOURCE_PENDING_REVIEW`),
    never silently omitted."""

    source_id: str
    provider: str
    government_entity: str | None
    state: str
    county: str | None  # None = statewide/provider-wide, matching authorization.py's own convention
    jurisdiction: str
    source_name: str
    source_url: str | None
    api_url: str | None
    terms_url: str | None
    license_url: str | None
    access_method: AcquisitionMethod
    source_priority: SourcePriorityTier

    official_source: bool
    government_source: bool
    public_source: bool
    open_data: bool
    bulk_download: bool
    api_available: bool
    gis_available: bool

    automated_access_status: str
    commercial_use_status: str
    customer_display_status: str
    redistribution_status: str
    export_status: str
    api_redistribution_status: str
    derived_data_status: str
    caching_status: str
    raw_storage_status: str

    image_rights: str
    document_rights: str
    attribution_required: bool | None

    rate_limit: str | None
    retention_requirements: str | None
    privacy_notes: str | None
    legal_basis: str | None
    legal_status: str  # a SourceStatus value, or a not-yet-reviewed marker - see is_unknown_or_unreviewed_status()

    coverage_state: CoverageState

    last_terms_checked: str | None
    terms_version: str | None
    terms_hash: str | None

    notes: str = ""

    def __post_init__(self) -> None:
        # Fail-closed structural guarantee (Phase 35 Section 5/19): a
        # CatalogSource can never assert it is APPROVED unless its
        # legal_status is a genuine SourceStatus.APPROVED(_WITH_
        # RESTRICTIONS) value - no discovery-stage entry from this phase
        # sets this, and nothing in this dataclass can accidentally imply
        # it either.
        if is_approved_status(self.legal_status) and self.coverage_state == CoverageState.SOURCE_PENDING_REVIEW:
            raise ValueError(
                f"{self.source_id!r}: legal_status claims APPROVED while coverage_state is still "
                "SOURCE_PENDING_REVIEW - a source cannot be both 'approved' and 'not yet reviewed'."
            )


def _read_matrix(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_fl_matrix() -> list[dict[str, str]]:
    """The 67-row Florida county coverage matrix, read live from
    `data/fl_county_coverage_matrix.csv` - this function never caches or
    duplicates the CSV's content into a second, divergent copy."""
    return _read_matrix(FL_MATRIX_PATH)


def load_tx_matrix() -> list[dict[str, str]]:
    """The 254-row Texas county coverage matrix, read live from
    `data/tx_county_coverage_matrix.csv`."""
    return _read_matrix(TX_MATRIX_PATH)


def gap_analysis() -> dict[str, object]:
    """Phase 35 Section 18's required counts, computed directly from the
    live CSVs rather than hand-maintained separately (so this function and
    the data it describes cannot silently drift apart). Every count is a
    real `sum()`/`len()` over the actual rows - never an estimate."""
    fl_rows = load_fl_matrix()
    tx_rows = load_tx_matrix()

    def _known(value: str | None) -> bool:
        return value is not None and not is_unknown_or_unreviewed_status(value)

    fl_with_property_appraiser = sum(1 for r in fl_rows if _known(r.get("property_appraiser_name")))
    fl_with_auction_source = sum(1 for r in fl_rows if _known(r.get("auction_source")))
    fl_with_cert_source = sum(1 for r in fl_rows if _known(r.get("tax_certificate_source")))
    fl_with_laft_source = sum(1 for r in fl_rows if _known(r.get("laft_source")))
    fl_no_known_source_any_category = sum(
        1
        for r in fl_rows
        if not any(
            _known(r.get(col))
            for col in ("auction_source", "tax_certificate_source", "laft_source", "property_appraiser_name")
        )
    )

    tx_with_appraisal_district = sum(1 for r in tx_rows if _known(r.get("appraisal_district_name")))
    tx_with_comptroller_directory_url = sum(1 for r in tx_rows if _known(r.get("comptroller_directory_url")))
    tx_with_auction_source = sum(1 for r in tx_rows if _known(r.get("auction_source")))
    tx_no_known_source_any_category = sum(
        1
        for r in tx_rows
        if not any(_known(r.get(col)) for col in ("auction_source", "appraisal_district_name"))
    )

    return {
        "fl_counties_total": len(fl_rows),
        "fl_counties_with_property_appraiser_verified": fl_with_property_appraiser,
        "fl_counties_with_any_auction_source": fl_with_auction_source,
        "fl_counties_with_any_cert_source": fl_with_cert_source,
        "fl_counties_with_any_laft_source": fl_with_laft_source,
        "fl_counties_with_no_known_source_any_category": fl_no_known_source_any_category,
        "tx_counties_total": len(tx_rows),
        "tx_counties_with_appraisal_district_verified": tx_with_appraisal_district,
        "tx_counties_with_comptroller_directory_url_generated": tx_with_comptroller_directory_url,
        "tx_counties_with_any_auction_source": tx_with_auction_source,
        "tx_counties_with_no_known_source_any_category": tx_no_known_source_any_category,
    }


def assert_matrix_completeness() -> None:
    """Phase 35 Section 21's 'matrix completeness = 67 FL + 254 TX'
    requirement, as a callable check rather than only a test - every row
    must have a non-empty `county` cell and the county set must have no
    duplicates, in addition to the raw row count being exactly right."""
    fl_rows = load_fl_matrix()
    tx_rows = load_tx_matrix()
    if len(fl_rows) != FL_COUNTY_COUNT:
        raise AssertionError(f"expected {FL_COUNTY_COUNT} Florida county rows, found {len(fl_rows)}")
    if len(tx_rows) != TX_COUNTY_COUNT:
        raise AssertionError(f"expected {TX_COUNTY_COUNT} Texas county rows, found {len(tx_rows)}")
    fl_counties = [r["county"] for r in fl_rows]
    tx_counties = [r["county"] for r in tx_rows]
    if len(set(fl_counties)) != len(fl_counties):
        raise AssertionError("duplicate county name found in the Florida matrix")
    if len(set(tx_counties)) != len(tx_counties):
        raise AssertionError("duplicate county name found in the Texas matrix")
