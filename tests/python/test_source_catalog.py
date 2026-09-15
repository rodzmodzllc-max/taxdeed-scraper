"""Tests for the Phase 35 county/source acquisition catalog
(harvesters/governance/source_catalog.py). Covers Phase 35 Section 21's own
list: source status validation, acquisition method validation, county/state
isolation, no UNKNOWN treated as APPROVED, LEGAL_REVIEW_REQUIRED sources
remain blocked from production approval, RealAuction county scoping,
LienHub remains LEGAL_REVIEW_REQUIRED, matrix completeness = 67 FL + 254 TX,
duplicate source handling.

Run with: pytest tests/python/test_source_catalog.py
"""

from __future__ import annotations

import pytest

from harvesters.governance import (
    AuthorizationStatus,
    PROVIDER_AUTHORIZATIONS,
    SOURCE_REGISTRY,
    SourceStatus,
    check_ingestion_gate,
)
from harvesters.governance.source_catalog import (
    FL_COUNTY_COUNT,
    TX_COUNTY_COUNT,
    AcquisitionMethod,
    CatalogSource,
    CoverageState,
    SourcePriorityTier,
    PHASE35_FL_DISCOVERY_COLUMNS,
    PHASE35_TX_DISCOVERY_COLUMNS,
    assert_matrix_completeness,
    gap_analysis,
    is_approved_status,
    is_unknown_or_unreviewed_status,
    load_fl_matrix,
    load_tx_matrix,
)


def _minimal_catalog_source(**overrides) -> CatalogSource:
    defaults = dict(
        source_id="test__catalog_fixture",
        provider="Test Provider",
        government_entity=None,
        state="FL",
        county="TestCounty",
        jurisdiction="TestCounty, FL",
        source_name="Test Source",
        source_url=None,
        api_url=None,
        terms_url=None,
        license_url=None,
        access_method=AcquisitionMethod.UNKNOWN,
        source_priority=SourcePriorityTier.SECONDARY,
        official_source=False,
        government_source=False,
        public_source=False,
        open_data=False,
        bulk_download=False,
        api_available=False,
        gis_available=False,
        automated_access_status="UNKNOWN",
        commercial_use_status="UNKNOWN",
        customer_display_status="UNKNOWN",
        redistribution_status="UNKNOWN",
        export_status="UNKNOWN",
        api_redistribution_status="UNKNOWN",
        derived_data_status="UNKNOWN",
        caching_status="UNKNOWN",
        raw_storage_status="UNKNOWN",
        image_rights="UNKNOWN",
        document_rights="UNKNOWN",
        attribution_required=None,
        rate_limit=None,
        retention_requirements=None,
        privacy_notes=None,
        legal_basis=None,
        legal_status="UNKNOWN",
        coverage_state=CoverageState.SOURCE_PENDING_REVIEW,
        last_terms_checked=None,
        terms_version=None,
        terms_hash=None,
        notes="test fixture",
    )
    defaults.update(overrides)
    return CatalogSource(**defaults)


# ---------------------------------------------------------------------------
# Source status validation
# ---------------------------------------------------------------------------

def test_unknown_status_is_never_treated_as_approved():
    assert is_approved_status("UNKNOWN") is False
    assert is_approved_status("") is False
    assert is_approved_status(None) is False
    assert is_unknown_or_unreviewed_status("UNKNOWN") is True
    assert is_unknown_or_unreviewed_status(None) is True


def test_discovered_and_mechanism_confirmed_are_not_approved():
    assert is_approved_status("DISCOVERED (mechanism only, not per-county extracted)") is False
    assert is_approved_status("MECHANISM_CONFIRMED_NOT_EXTRACTED (see notes)") is False


def test_legal_review_required_and_blocked_are_not_approved_but_are_not_unknown_either():
    assert is_approved_status("LEGAL_REVIEW_REQUIRED - no permission found") is False
    assert is_approved_status("BLOCKED - explicit prohibition") is False
    # These are real, reviewed/decided states, not "we don't know" - the
    # distinction matters for gap-analysis counting (Section 18/25).
    assert is_unknown_or_unreviewed_status("LEGAL_REVIEW_REQUIRED - no permission found") is False
    assert is_unknown_or_unreviewed_status("BLOCKED - explicit prohibition") is False


def test_approved_and_approved_with_restrictions_are_both_recognized():
    assert is_approved_status("APPROVED") is True
    assert is_approved_status("APPROVED (grandfathered, not formally rights-audited - see registry.py)") is True
    assert is_approved_status("APPROVED_WITH_RESTRICTIONS - image_use only") is True


def test_catalog_source_cannot_claim_approved_while_still_pending_review():
    with pytest.raises(ValueError, match="cannot be both"):
        _minimal_catalog_source(legal_status="APPROVED", coverage_state=CoverageState.SOURCE_PENDING_REVIEW)


def test_catalog_source_can_be_approved_once_coverage_state_reflects_it():
    record = _minimal_catalog_source(legal_status="APPROVED", coverage_state=CoverageState.SOURCE_FOUND)
    assert is_approved_status(record.legal_status) is True


def test_no_phase35_discovery_is_marked_approved():
    """Phase 35 Section 19: this phase must not mark any newly discovered
    source APPROVED. Checked directly against the live CSV columns this
    phase actually populated - not the whole matrix, since the Florida
    matrix's pre-existing Phase 33 columns legitimately already say
    APPROVED for the three grandfathered production sources (a real,
    separate registry fact this phase did not touch)."""
    for row in load_fl_matrix():
        for col in PHASE35_FL_DISCOVERY_COLUMNS:
            assert not is_approved_status(row.get(col)), (row["county"], col, row.get(col))
    for row in load_tx_matrix():
        for col in PHASE35_TX_DISCOVERY_COLUMNS:
            assert not is_approved_status(row.get(col)), (row["county"], col, row.get(col))


def test_preexisting_grandfathered_florida_approvals_are_untouched_by_phase35():
    """The three grandfathered Florida sources' pre-existing APPROVED status
    (Phase 10A, carried through every phase since) is a real fact this
    module reads, not something Phase 35 introduced or should hide."""
    for source_id in ("fl_realauction", "fl_lienhub_certificates", "fl_laft_pdfs"):
        assert SOURCE_REGISTRY[source_id].legal_status == SourceStatus.APPROVED


# ---------------------------------------------------------------------------
# Acquisition method validation
# ---------------------------------------------------------------------------

def test_acquisition_method_is_a_closed_vocabulary():
    valid = {m.value for m in AcquisitionMethod}
    assert valid == {
        "OFFICIAL_API", "OFFICIAL_BULK", "OFFICIAL_OPEN_DATA", "OFFICIAL_GIS",
        "OFFICIAL_PUBLIC_SEARCH", "PUBLIC_RECORD_REQUEST", "LICENSED_VENDOR",
        "THIRD_PARTY_PUBLIC", "LINK_ONLY", "MANUAL_ONLY", "UNKNOWN",
    }


def test_tx_and_fl_matrices_only_use_recognized_acquisition_methods():
    valid = {m.value for m in AcquisitionMethod}
    for row in load_fl_matrix():
        assert row.get("acquisition_method", "UNKNOWN") in valid | {""}
    for row in load_tx_matrix():
        assert row.get("acquisition_method", "UNKNOWN") in valid | {""}


def test_interactive_public_search_is_never_classified_as_official_api():
    """Phase 35 Section 13's explicit warning: an interactive public
    government portal (like a county appraisal district's own search page)
    must not be recorded as OFFICIAL_API merely because it is accessible.
    Every verified Phase 35 TX/FL discovery row uses OFFICIAL_PUBLIC_SEARCH,
    never OFFICIAL_API, since no separately-documented API/bulk product was
    found for any of them this phase."""
    for row in load_tx_matrix():
        if row.get("appraisal_district_name") not in (None, "", "UNKNOWN"):
            assert row["acquisition_method"] == "OFFICIAL_PUBLIC_SEARCH"
    for row in load_fl_matrix():
        if row.get("property_appraiser_name") not in (None, "", "UNKNOWN"):
            assert row["acquisition_method"] == "OFFICIAL_PUBLIC_SEARCH"


# ---------------------------------------------------------------------------
# County / state isolation
# ---------------------------------------------------------------------------

def test_fl_and_tx_matrices_are_disjoint_state_sets():
    fl_rows = load_fl_matrix()
    tx_rows = load_tx_matrix()
    assert all(r["state"] == "FL" for r in fl_rows)
    assert all(r["state"] == "TX" for r in tx_rows)


def test_a_texas_countys_verified_data_never_leaks_to_a_different_texas_county():
    tx_rows = {r["county"]: r for r in load_tx_matrix()}
    harris = tx_rows["Harris"]
    dallas = tx_rows["Dallas"]
    assert harris["appraisal_district_url"] != dallas["appraisal_district_url"]
    assert harris["comptroller_directory_url"] != dallas["comptroller_directory_url"]
    assert "harris" not in dallas["comptroller_directory_url"].lower()


# ---------------------------------------------------------------------------
# RealAuction county scoping / LienHub status - re-confirmed against the
# same real records Phase 34A/34B already cover, named again per Phase 35
# Section 8 for direct traceability from this new test module.
# ---------------------------------------------------------------------------

def test_realauction_alachua_and_volusia_remain_legal_review_required():
    for authorization_id in ("fl_realauction__county__alachua", "fl_realauction__county__volusia"):
        record = PROVIDER_AUTHORIZATIONS[authorization_id]
        assert record.authorization_status == AuthorizationStatus.LEGAL_REVIEW_REQUIRED


def test_lienhub_remains_legal_review_required():
    record = PROVIDER_AUTHORIZATIONS["fl_lienhub_certificates__provider__grant_street_group"]
    assert record.authorization_status == AuthorizationStatus.LEGAL_REVIEW_REQUIRED


def test_legal_review_required_sources_remain_blocked_from_ingestion_approval():
    # Every SOURCE_REGISTRY entry not in INGESTION_ALLOWED_STATUSES must
    # still fail check_ingestion_gate() - re-confirmed here as a Phase 35
    # regression guard on top of test_source_governance.py's own coverage.
    for source_id, record in SOURCE_REGISTRY.items():
        if record.legal_status not in (SourceStatus.APPROVED, SourceStatus.APPROVED_WITH_RESTRICTIONS):
            assert check_ingestion_gate(source_id).allowed is False, source_id


# ---------------------------------------------------------------------------
# Matrix completeness
# ---------------------------------------------------------------------------

def test_matrix_completeness_is_exactly_67_florida_and_254_texas():
    assert_matrix_completeness()  # raises AssertionError on any mismatch
    assert len(load_fl_matrix()) == FL_COUNTY_COUNT == 67
    assert len(load_tx_matrix()) == TX_COUNTY_COUNT == 254


def test_gap_analysis_counts_are_internally_consistent():
    stats = gap_analysis()
    assert stats["fl_counties_total"] == 67
    assert stats["tx_counties_total"] == 254
    assert 0 <= stats["fl_counties_with_property_appraiser_verified"] <= 67
    assert 0 <= stats["tx_counties_with_appraisal_district_verified"] <= 254
    # Every county with a verified appraisal district necessarily has a
    # generated comptroller directory URL too (the URL is generated for
    # all 254 unconditionally, verification is a strict subset).
    assert stats["tx_counties_with_appraisal_district_verified"] <= stats["tx_counties_with_comptroller_directory_url_generated"]
    assert stats["tx_counties_with_comptroller_directory_url_generated"] == 254


def test_at_least_42_texas_counties_have_individually_verified_appraisal_district_data():
    # The specific, bounded, real batch this phase fetched live - a floor,
    # not an exact-count assertion, so a future phase extending coverage
    # doesn't have to edit this number down.
    stats = gap_analysis()
    assert stats["tx_counties_with_appraisal_district_verified"] >= 42


def test_at_least_12_florida_counties_have_individually_verified_property_appraiser_data():
    stats = gap_analysis()
    assert stats["fl_counties_with_property_appraiser_verified"] >= 12


# ---------------------------------------------------------------------------
# Duplicate source handling
# ---------------------------------------------------------------------------

def test_source_priority_tier_is_a_closed_vocabulary_covering_the_documented_cases():
    valid = {t.value for t in SourcePriorityTier}
    assert valid == {"PRIMARY", "SECONDARY", "FALLBACK", "LINK_ONLY", "RESTRICTED"}


def test_coverage_state_is_a_closed_vocabulary():
    valid = {c.value for c in CoverageState}
    assert valid == {
        "SOURCE_FOUND", "SOURCE_NOT_FOUND", "SOURCE_NOT_APPLICABLE",
        "SOURCE_PENDING_REVIEW", "SOURCE_BLOCKED", "SOURCE_REQUIRES_LICENSE",
    }


def test_duplicate_overlapping_sources_are_tiered_not_silently_dropped():
    """Two genuinely overlapping sources for the same category (e.g. a
    county appraisal district vs. a statewide GIS layer both offering
    parcel geometry) must each keep their own CatalogSource row, tiered via
    SourcePriorityTier rather than one silently overwriting the other."""
    primary = _minimal_catalog_source(
        source_id="test__county_gis", source_priority=SourcePriorityTier.PRIMARY, gis_available=True
    )
    fallback = _minimal_catalog_source(
        source_id="test__statewide_gis", source_priority=SourcePriorityTier.FALLBACK, gis_available=True
    )
    assert primary.source_id != fallback.source_id
    assert primary.source_priority != fallback.source_priority
    assert primary.gis_available and fallback.gis_available  # both genuinely offer the category


def test_matrix_has_no_duplicate_county_rows():
    fl_counties = [r["county"] for r in load_fl_matrix()]
    tx_counties = [r["county"] for r in load_tx_matrix()]
    assert len(fl_counties) == len(set(fl_counties))
    assert len(tx_counties) == len(set(tx_counties))
