"""Tests for the Phase 36 (Source Terms and Commercial-Use Verification)
per-source terms/evidence ledger (data/phase36_terms_review.csv, read via
harvesters.governance.source_catalog.load_terms_review()). Covers Phase 36
Section 19's own list: unresolved commercial rights remain
LEGAL_REVIEW_REQUIRED, LienHub remains LEGAL_REVIEW_REQUIRED, RealAuction
Alachua/Volusia remain county-scoped, unknown != approved, county
isolation, source policy completeness.

Run with: pytest tests/python/test_phase36_terms_review.py
"""

from __future__ import annotations

from harvesters.governance import (
    AuthorizationStatus,
    PROVIDER_AUTHORIZATIONS,
    SOURCE_REGISTRY,
    SourceStatus,
)
from harvesters.governance.source_catalog import (
    assert_every_terms_review_row_has_evidence,
    is_approved_status,
    is_unknown_or_unreviewed_status,
    load_terms_review,
)

VALID_LEGAL_STATUSES = {
    "DISCOVERED", "UNDER_REVIEW", "APPROVED", "APPROVED_WITH_RESTRICTIONS",
    "LEGAL_REVIEW_REQUIRED", "BLOCKED", "DISABLED", "TERMS_CHANGED",
}

REQUIRED_FIELDS = (
    "source_id", "provider", "government_entity", "state", "county",
    "source_url", "terms_url", "license_url", "access_method",
    "automated_access_status", "commercial_use_status", "customer_display_status",
    "redistribution_status", "export_status", "api_redistribution_status",
    "derived_data_status", "caching_status", "raw_storage_status",
    "image_rights", "document_rights", "attribution_required",
    "retention_requirements", "privacy_notes",
    "legal_basis", "legal_status", "approval_notes", "evidence_reference", "reviewed_at",
)


# ---------------------------------------------------------------------------
# Unresolved commercial rights remain LEGAL_REVIEW_REQUIRED / unknown != approved
# ---------------------------------------------------------------------------

def test_no_row_in_the_terms_review_ledger_is_approved():
    """Phase 36's central guarantee: this phase's own research did not, by
    itself, establish affirmative commercial-use permission for any source -
    zero rows are APPROVED or APPROVED_WITH_RESTRICTIONS."""
    for row in load_terms_review():
        assert not is_approved_status(row["legal_status"]), (row["source_id"], row["legal_status"])


def test_only_recognized_legal_status_values_are_used():
    for row in load_terms_review():
        assert row["legal_status"] in VALID_LEGAL_STATUSES, (row["source_id"], row["legal_status"])


def test_every_asserted_status_beyond_discovered_has_an_evidence_reference():
    assert_every_terms_review_row_has_evidence()  # raises AssertionError on any gap


def test_a_row_actually_reviewed_and_found_inconclusive_is_legal_review_required_not_discovered():
    """Phase 36 Section 11's explicit escalation rule: once a source was
    actually reviewed this phase and the finding was inconclusive (no
    restriction found, no permission found), it must be recorded as
    LEGAL_REVIEW_REQUIRED, not left at the weaker DISCOVERED state - DISCOVERED
    is reserved for a source that was not reviewed at all this phase."""
    rows = {r["source_id"]: r for r in load_terms_review()}
    reviewed_and_inconclusive = rows["tx_appraisal_district__county__harris"]
    assert reviewed_and_inconclusive["legal_status"] == "LEGAL_REVIEW_REQUIRED"
    assert reviewed_and_inconclusive["evidence_reference"] not in ("", "UNKNOWN")


def test_a_source_not_actually_reviewed_this_phase_stays_discovered():
    """The symmetric guarantee: a source this phase could not actually
    review (a JS-rendered portal with no extractable content) is NOT
    escalated to LEGAL_REVIEW_REQUIRED just because a review was attempted -
    that would misrepresent 'we tried and got nothing' as 'we reviewed the
    terms and found them unclear'."""
    rows = {r["source_id"]: r for r in load_terms_review()}
    not_reviewed = rows["tx_appraisal_district__county__montgomery"]
    assert not_reviewed["legal_status"] == "DISCOVERED"


# ---------------------------------------------------------------------------
# LienHub remains LEGAL_REVIEW_REQUIRED / RealAuction Alachua+Volusia remain
# county-scoped
# ---------------------------------------------------------------------------

def test_lienhub_remains_legal_review_required_after_phase36():
    record = PROVIDER_AUTHORIZATIONS["fl_lienhub_certificates__provider__grant_street_group"]
    assert record.authorization_status == AuthorizationStatus.LEGAL_REVIEW_REQUIRED
    rows = {r["source_id"]: r for r in load_terms_review()}
    ledger_row = rows["fl_lienhub_certificates__provider__grant_street_group"]
    assert ledger_row["legal_status"] == "LEGAL_REVIEW_REQUIRED"
    assert ledger_row["automated_access_status"].startswith("NO")


def test_realauction_alachua_and_volusia_remain_legal_review_required_and_county_scoped():
    for authorization_id in ("fl_realauction__county__alachua", "fl_realauction__county__volusia"):
        assert PROVIDER_AUTHORIZATIONS[authorization_id].authorization_status == AuthorizationStatus.LEGAL_REVIEW_REQUIRED

    rows = {r["source_id"]: r for r in load_terms_review()}
    alachua = rows["fl_realauction__county__alachua"]
    volusia = rows["fl_realauction__county__volusia"]
    assert alachua["county"] == "Alachua"
    assert volusia["county"] == "Volusia"
    assert alachua["legal_status"] == "LEGAL_REVIEW_REQUIRED"
    assert volusia["legal_status"] == "LEGAL_REVIEW_REQUIRED"
    # Distinct rows, distinct evidence - Alachua's robots.txt re-check this
    # phase is not silently copied onto Volusia's row.
    assert alachua["evidence_reference"] != volusia["evidence_reference"]


def test_realauction_alachua_finding_does_not_leak_into_volusias_row():
    rows = {r["source_id"]: r for r in load_terms_review()}
    volusia = rows["fl_realauction__county__volusia"]
    assert "ROBOTS_DISALLOWED" not in volusia["legal_basis"]
    alachua = rows["fl_realauction__county__alachua"]
    assert "ROBOTS_DISALLOWED" in alachua["legal_basis"]


def test_preexisting_registry_statuses_untouched_by_phase36():
    """Phase 36 is read-only research - it must not have changed any
    SOURCE_REGISTRY legal_status."""
    expected = {
        "tx_lgbs": SourceStatus.APPROVED,
        "tx_realauction": SourceStatus.APPROVED,
        "tx_hctax": SourceStatus.LEGAL_REVIEW_REQUIRED,
        "tx_pbfcm": SourceStatus.BLOCKED,
        "tx_mvba": SourceStatus.BLOCKED,
        "tx_ctsa": SourceStatus.BLOCKED,
        "tx_govease": SourceStatus.BLOCKED,
        "fl_realauction": SourceStatus.APPROVED,
        "fl_laft_pdfs": SourceStatus.APPROVED,
        "fl_lienhub_certificates": SourceStatus.APPROVED,
        "fl_dor_statewide": SourceStatus.LEGAL_REVIEW_REQUIRED,
    }
    for source_id, status in expected.items():
        assert SOURCE_REGISTRY[source_id].legal_status == status, source_id


# ---------------------------------------------------------------------------
# County isolation
# ---------------------------------------------------------------------------

def test_florida_property_appraiser_rows_are_each_scoped_to_their_own_county():
    rows = [r for r in load_terms_review() if r["source_id"].startswith("fl_property_appraiser__county__")]
    counties = [r["county"] for r in rows]
    assert len(counties) == len(set(counties)), "duplicate county in FL property-appraiser terms-review rows"
    assert len(rows) == 12  # every county Phase 35 individually verified


def test_texas_appraisal_district_rows_are_each_scoped_to_their_own_county():
    rows = [r for r in load_terms_review() if r["source_id"].startswith("tx_appraisal_district__county__")]
    counties = [r["county"] for r in rows]
    assert len(counties) == len(set(counties))
    assert set(counties) == {"Harris", "Dallas", "Bexar", "Tarrant", "Montgomery", "Denton"}


def test_a_pinellas_specific_finding_does_not_appear_on_any_other_countys_row():
    rows = load_terms_review()
    pinellas = next(r for r in rows if r.get("county") == "Pinellas")
    assert "electronic data harvesting" in pinellas["legal_basis"]
    for row in rows:
        if row.get("county") != "Pinellas":
            assert "electronic data harvesting" not in row["legal_basis"]


# ---------------------------------------------------------------------------
# Source policy completeness (Section 10's field list)
# ---------------------------------------------------------------------------

def test_every_row_has_every_required_field_populated():
    for row in load_terms_review():
        for field_name in REQUIRED_FIELDS:
            assert field_name in row, (row.get("source_id"), field_name)
            assert row[field_name] is not None and row[field_name] != "", (row.get("source_id"), field_name)


def test_statewide_rows_use_not_applicable_for_image_document_rights_where_appropriate():
    """A tabular/GIS statewide data product (no photos/documents) should say
    NOT_APPLICABLE for image_rights/document_rights, never a bare UNKNOWN
    that implies the question was simply never asked."""
    rows = {r["source_id"]: r for r in load_terms_review()}
    dor = rows["fl_dor_statewide__nal_sdf_nap_gis"]
    assert dor["image_rights"].startswith("NOT_APPLICABLE")
    assert dor["document_rights"].startswith("NOT_APPLICABLE")


def test_unknown_commercial_use_status_never_appears_bare_on_a_reviewed_source():
    """Section 11's rule applied to the ledger's own commercial_use_status
    column: a source this phase actually reviewed never leaves that column
    as a bare 'UNKNOWN' - it is escalated to a LEGAL_REVIEW_REQUIRED-carrying
    string once review happened, even if the review found nothing
    conclusive. Sources not reviewed this phase are allowed to say so
    explicitly (still not 'UNKNOWN' bare - see DISCOVERED-labelled strings)."""
    for row in load_terms_review():
        assert row["commercial_use_status"] != "UNKNOWN", row["source_id"]


# ---------------------------------------------------------------------------
# Section 5 extension: additional RealAuction deployments beyond Alachua/Volusia
# ---------------------------------------------------------------------------

def test_additional_realauction_deployments_are_evidence_based_and_county_scoped():
    """Section 5 asks for RealAuction coverage beyond Alachua/Volusia 'where
    evidence is available'. The three additional rows added this phase
    (Miami-Dade, Brevard, Travis TX) must each carry their own live-fetched
    evidence, stay LEGAL_REVIEW_REQUIRED (never inferred up to APPROVED just
    because a robots.txt check ran clean), and must not silently borrow
    Alachua/Volusia's EULA-content evidence for a county whose own EULA text
    was never obtained."""
    rows = {r["source_id"]: r for r in load_terms_review()}
    for source_id, county in (
        ("fl_realauction__county__miami_dade", "Miami-Dade"),
        ("fl_realauction__county__brevard", "Brevard"),
        ("tx_realauction__county__travis", "Travis"),
    ):
        row = rows[source_id]
        assert row["county"] == county
        assert row["legal_status"] == "LEGAL_REVIEW_REQUIRED"
        assert not is_approved_status(row["legal_status"])
        assert "ROBOTS_DISALLOWED" in row["legal_basis"]
        # These rows are robots.txt-only evidence, not EULA-content evidence -
        # they must say so rather than borrowing Alachua/Volusia's EULA finding.
        assert "EULA text" in row["commercial_use_status"] or "EULA" in row["legal_basis"] or "not independently obtained" in row["commercial_use_status"]


def test_realauction_platform_wide_robots_finding_spans_both_subdomain_patterns_and_both_states():
    """The robots.txt block was independently confirmed this phase against
    both RealAuction subdomain conventions (.realtaxdeed.com and
    .realforeclose.com) and in both Florida and Texas - real evidence that
    the technical access control is platform-wide, even though EULA content
    still must be reviewed per county before any commercial-use conclusion."""
    rows = {r["source_id"]: r for r in load_terms_review()}
    hosts = {
        rows["fl_realauction__county__alachua"]["source_url"]: "realtaxdeed",
        rows["fl_realauction__county__miami_dade"]["source_url"]: "realtaxdeed",
        rows["fl_realauction__county__brevard"]["source_url"]: "realforeclose",
        rows["tx_realauction__county__travis"]["source_url"]: "realforeclose",
    }
    assert any("realtaxdeed" in h for h in hosts) and any("realforeclose" in h for h in hosts)
    assert rows["tx_realauction__county__travis"]["state"] == "TX"
    assert rows["fl_realauction__county__brevard"]["state"] == "FL"


def test_gap_analysis_and_terms_review_do_not_contradict_each_other():
    """Cross-check: every Phase-35-verified county that Phase 36 chose to
    terms-review actually exists in the Phase 35 verified set (no row
    invents a county Phase 35 never looked at)."""
    from harvesters.governance.source_catalog import load_fl_matrix, load_tx_matrix

    fl_verified = {r["county"] for r in load_fl_matrix() if not is_unknown_or_unreviewed_status(r.get("property_appraiser_name"))}
    tx_verified = {r["county"] for r in load_tx_matrix() if not is_unknown_or_unreviewed_status(r.get("appraisal_district_name"))}

    for row in load_terms_review():
        if row["source_id"].startswith("fl_property_appraiser__county__"):
            assert row["county"] in fl_verified, row["county"]
        if row["source_id"].startswith("tx_appraisal_district__county__"):
            assert row["county"] in tx_verified, row["county"]
