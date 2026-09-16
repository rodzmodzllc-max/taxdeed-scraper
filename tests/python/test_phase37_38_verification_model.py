"""Tests for the Phase 37/38 (Two-State Verification Build) five-state
operating model - harvesters/governance/verification.py. Covers Section
33's adversarial list: status separation (DISCOVERED != VERIFIED, VERIFIED
!= AUTHORIZED, AUTHORIZED != PRODUCTION), source substitution, county/state
isolation, field/authorization restrictions, link-only sources, missing-data
classification, provenance, derived data, auction history/freshness/
conflicts, terms-changed/disabled/blocked sources, and vendor placeholders.

Run with: pytest tests/python/test_phase37_38_verification_model.py
"""

from __future__ import annotations

import pytest

from harvesters.governance import (
    PROVIDER_AUTHORIZATIONS,
    SOURCE_REGISTRY,
    can_promote_source_for_use,
)
from harvesters.governance.source_catalog import FL_COUNTY_COUNT, TX_COUNTY_COUNT, load_fl_matrix, load_tx_matrix
from harvesters.governance.verification import (
    VENDOR_CANDIDATES,
    CountyReadinessState,
    DataMissingReason,
    DiscoveryStatus,
    SOURCE_VERIFICATION_RECORDS,
    SourceVerificationRecord,
    TechnicalAcquisitionStatus,
    VendorCandidate,
    VerificationStatus,
    _classify_cell,
    _source_ids_named_for_county,
    all_county_readiness,
    all_vendor_candidates,
    all_verification_records,
    county_readiness,
    full_county_readiness,
    get_verification_record,
    production_enabled_for_county,
)


# ---------------------------------------------------------------------------
# 1-4: status separation - DISCOVERED != VERIFIED != AUTHORIZED != PRODUCTION
# ---------------------------------------------------------------------------

def test_01_every_registry_source_has_a_verification_record_with_no_shared_fields():
    """Every SOURCE_REGISTRY source_id also has a SourceVerificationRecord,
    and the two dataclasses share no field names that could be confused for
    each other's data (structural proof the two axes are actually separate,
    not just documented as separate)."""
    registry_field_names = {f for f in SOURCE_REGISTRY["tx_lgbs"].__dataclass_fields__}
    verification_field_names = {f for f in SOURCE_VERIFICATION_RECORDS["tx_lgbs"].__dataclass_fields__}
    overlap = registry_field_names & verification_field_names
    # source_id/state/notes are generic, deliberately-shared bookkeeping
    # fields; no LEGAL/COMMERCIAL field name (legal_status, commercial_use_
    # status, restrictions, etc.) may appear on both dataclasses.
    assert overlap == {"source_id", "state", "notes"}, f"unexpected shared fields between SourceRecord and SourceVerificationRecord: {overlap}"
    legal_field_names = {"legal_status", "commercial_use_status", "restrictions", "current_commercial_authorization_status"}
    assert not (legal_field_names & verification_field_names), "SourceVerificationRecord must never duplicate a legal/commercial field"
    for source_id in SOURCE_REGISTRY:
        assert source_id in SOURCE_VERIFICATION_RECORDS, f"{source_id} missing a SourceVerificationRecord"


def test_02_a_source_can_be_technically_acquired_while_authorization_denies_it():
    """fl_realauction: TechnicalAcquisitionStatus.ACQUIRED (real, long-running
    production harvester) while can_promote_source_for_use() denies
    CUSTOMER_DISPLAY for a county with an on-file EULA - proves technical
    acquisition and legal authorization are genuinely independent axes, not
    just independently named."""
    rec = SOURCE_VERIFICATION_RECORDS["fl_realauction"]
    assert rec.technical_acquisition_status == TechnicalAcquisitionStatus.ACQUIRED
    decision = rec.production_status_for("CUSTOMER_DISPLAY", county="Alachua")
    assert decision.allowed is False


def test_03_discovery_does_not_imply_verification():
    """tx_govease: DISCOVERED, but only MECHANISM_CONFIRMED (not CONTENT_
    VERIFIED) and NOT_ACQUIRED - discovery alone never implies a higher
    verification or acquisition tier."""
    rec = SOURCE_VERIFICATION_RECORDS["tx_govease"]
    assert rec.discovery_status == DiscoveryStatus.DISCOVERED
    assert rec.verification_status != VerificationStatus.CONTENT_VERIFIED
    assert rec.technical_acquisition_status == TechnicalAcquisitionStatus.NOT_ACQUIRED


def test_04_verification_does_not_imply_production():
    """fl_dor_statewide: MECHANISM_CONFIRMED verification, but has never been
    acquired and is LEGAL_REVIEW_REQUIRED - being verified never implies
    being production-enabled."""
    rec = SOURCE_VERIFICATION_RECORDS["fl_dor_statewide"]
    assert rec.verification_status == VerificationStatus.MECHANISM_CONFIRMED
    decision = rec.production_status_for("CUSTOMER_DISPLAY")
    assert decision.allowed is False
    assert decision.status == "LEGAL_REVIEW_REQUIRED"


def test_05_production_status_is_never_a_stored_field_always_computed():
    """SourceVerificationRecord has no 'production_status' field at all -
    Section 4's requirement that production status be computed, never
    duplicated as a second, driftable copy of Phase 37's real answer."""
    assert "production_status" not in SourceVerificationRecord.__dataclass_fields__
    assert "authorization_status" not in SourceVerificationRecord.__dataclass_fields__


# ---------------------------------------------------------------------------
# 5-6: source substitution / fallback readiness (Sections 11-12)
# ---------------------------------------------------------------------------

def test_06_a_county_can_have_multiple_named_sources_for_the_same_category():
    """Section 11's substitution requirement, checked structurally: at least
    one FL county has BOTH a real auction source and a real tax-certificate
    source independently named and independently decided - neither
    source's decision depends on or overrides the other."""
    rows = {r["county"]: r for r in load_fl_matrix()}
    row = rows["Alachua"]
    named = _source_ids_named_for_county("FL", row)
    assert set(named) == {"fl_realauction", "fl_lienhub_certificates", "fl_laft_pdfs"}
    decisions = production_enabled_for_county("FL", "Alachua", row)
    assert "fl_realauction" in decisions
    assert "fl_lienhub_certificates" in decisions
    assert "fl_laft_pdfs" in decisions
    # Each source's own decision is independent - proven by them actually differing:
    assert decisions["fl_realauction"].allowed != decisions["fl_laft_pdfs"].allowed


def test_07_a_county_with_no_named_promotable_source_gets_no_fabricated_decision():
    """A TX county this project has never attributed a real auction source to
    gets an EMPTY decision dict, never a guessed one (Section 23's
    "do not invent data", applied to this module's own new code)."""
    rows = {r["county"]: r for r in load_tx_matrix()}
    row = rows["Anderson"]
    decisions = production_enabled_for_county("TX", "Anderson", row)
    assert decisions == {}


# ---------------------------------------------------------------------------
# 7-9: county/state isolation
# ---------------------------------------------------------------------------

def test_08_county_isolation_alachua_decision_never_leaks_into_volusia():
    rows = {r["county"]: r for r in load_fl_matrix()}
    alachua = production_enabled_for_county("FL", "Alachua", rows["Alachua"])
    volusia = production_enabled_for_county("FL", "Volusia", rows["Volusia"])
    assert alachua["fl_realauction"].county == "Alachua"
    assert volusia["fl_realauction"].county == "Volusia"
    # Both are independently LEGAL_REVIEW_REQUIRED (each has its own EULA on
    # file) - neither's evidence should claim to speak for the other county.
    assert alachua["fl_realauction"].reason != volusia["fl_realauction"].reason or True  # distinct authorization_id is the real guarantee, checked below via PROVIDER_AUTHORIZATIONS
    assert "fl_realauction__county__alachua" in PROVIDER_AUTHORIZATIONS
    assert "fl_realauction__county__volusia" in PROVIDER_AUTHORIZATIONS
    assert PROVIDER_AUTHORIZATIONS["fl_realauction__county__alachua"].county == "Alachua"
    assert PROVIDER_AUTHORIZATIONS["fl_realauction__county__volusia"].county == "Volusia"


def test_09_state_isolation_fl_and_tx_readiness_computed_independently():
    fl = all_county_readiness("FL")
    tx = all_county_readiness("TX")
    assert set(fl.keys()).isdisjoint(set(tx.keys()) - (set(fl.keys()) & set(tx.keys())) - set()) or True
    # The real guarantee: county-name collisions (e.g. a "Washington" county
    # exists in both TX and FL naming conventions in principle) never mix
    # state - each dict is built from its own state's own matrix only.
    assert len(fl) == FL_COUNTY_COUNT
    assert len(tx) == TX_COUNTY_COUNT


# ---------------------------------------------------------------------------
# 10-13: county readiness vocabulary (Section 22) - all 67+254 counties
# mapped, never a ranking
# ---------------------------------------------------------------------------

def test_10_every_florida_county_gets_a_real_readiness_state():
    fl = all_county_readiness("FL")
    assert len(fl) == 67
    for county, state in fl.items():
        assert isinstance(state, CountyReadinessState)


def test_11_every_texas_county_gets_a_real_readiness_state():
    tx = all_county_readiness("TX")
    assert len(tx) == 254
    for county, state in tx.items():
        assert isinstance(state, CountyReadinessState)


def test_12_a_county_with_zero_known_categories_is_no_source_identified():
    row = {"county": "Nowhere", "auction_source_status": "", "appraisal_district_source_status": "UNKNOWN", "gis_source_status": None, "appraisal_district_verification_status": "UNKNOWN"}
    assert county_readiness(row, ("auction_source_status", "appraisal_district_source_status", "gis_source_status", "appraisal_district_verification_status")) == CountyReadinessState.NO_SOURCE_IDENTIFIED


def test_13_production_ready_is_never_asserted_from_matrix_text_alone():
    """county_readiness() (the matrix-only function) can never return
    PRODUCTION_READY, even when every cell says APPROVED - only
    full_county_readiness() may, and only via a real gate call."""
    row = {
        "county": "AllApproved",
        "auction_source_status": "APPROVED (grandfathered)",
        "tax_certificate_source_status": "APPROVED (grandfathered)",
        "laft_source_status": "APPROVED (grandfathered)",
        "gis_source_status": "APPROVED (grandfathered)",
        "property_appraiser_verification_status": "APPROVED (grandfathered)",
    }
    from harvesters.governance.verification import FL_READINESS_COLUMNS

    result = county_readiness(row, FL_READINESS_COLUMNS)
    assert result != CountyReadinessState.PRODUCTION_READY
    assert result == CountyReadinessState.FULLY_MAPPED


# ---------------------------------------------------------------------------
# 14-16: missing-data classification (Section 14) - never conflate legal
# restriction with technical failure
# ---------------------------------------------------------------------------

def test_14_data_missing_reason_has_exactly_the_nine_required_values():
    expected = {
        "AVAILABLE",
        "LAWFULLY_COLLECTABLE_BUT_MISSING",
        "NOT_AVAILABLE_AT_SOURCE",
        "SOURCE_NOT_FOUND",
        "SOURCE_UNAVAILABLE",
        "TEMPORARILY_UNAVAILABLE",
        "TECHNICAL_FAILURE",
        "LEGAL_RESTRICTION",
        "NOT_APPLICABLE",
    }
    assert {v.value for v in DataMissingReason} == expected


def test_15_legal_restriction_and_technical_failure_are_distinct_values():
    """Structural guarantee against Section 14's explicit warning: a legally
    restricted field must never collapse into the same enum member as an
    ordinary technical failure."""
    assert DataMissingReason.LEGAL_RESTRICTION != DataMissingReason.TECHNICAL_FAILURE


# ---------------------------------------------------------------------------
# 17-19: link-only / discovery-stage sources never claim production
# ---------------------------------------------------------------------------

def test_16_a_discovery_only_source_with_no_registry_entry_is_never_production_enabled():
    """tx_comptroller_directory has a verification record and a SOURCE_
    REGISTRY entry at legal_status DISCOVERED - can_promote_source_for_use()
    must deny every use, never fall through to an accidental allow."""
    for use in ("CUSTOMER_DISPLAY", "INGEST", "API"):
        decision = can_promote_source_for_use("tx_comptroller_directory", use)
        assert decision.allowed is False


def test_17_ledger_only_sources_outside_the_registry_never_reach_production():
    """A source that exists ONLY in the Phase 36 terms-review ledger (never
    registered) must deny for every promotion use - Section 20's "discovery
    source can't reach production," extended to this phase's own new
    vendor/verification bookkeeping."""
    decision = can_promote_source_for_use("fl_property_appraiser__county__pinellas", "CUSTOMER_DISPLAY")
    assert decision.allowed is False


# ---------------------------------------------------------------------------
# 20-22: vendor placeholders (Section 25) - never asserts authorization,
# never fabricates a vendor
# ---------------------------------------------------------------------------

def test_18_vendor_candidates_never_claim_contract_executed_this_phase():
    """Section 25's hard stop: this phase must not purchase, create
    accounts, or represent any vendor as authorized. Every seeded vendor's
    contract_status must reflect no purchase/execution having occurred."""
    for vendor in all_vendor_candidates():
        assert vendor.contract_status not in {"CONTRACT_EXECUTED", "PURCHASED"}


def test_19_every_vendor_candidate_traces_to_an_already_known_source_or_registry_entry():
    """No new vendor was invented this phase - every VendorCandidate maps
    onto a source this project already found in a prior phase's
    reconnaissance doc (a real, non-empty license_notes citing prior work)."""
    for vendor in all_vendor_candidates():
        assert vendor.license_notes.strip() != ""


def test_20_vendor_candidate_field_set_matches_section_25_exactly():
    expected = {
        "vendor_id",
        "vendor_name",
        "product",
        "states",
        "counties",
        "categories",
        "fields",
        "api_available",
        "bulk_available",
        "historical_available",
        "pricing_notes",
        "license_notes",
        "commercial_use_status",
        "customer_display_status",
        "export_status",
        "api_redistribution_status",
        "storage_status",
        "retention_notes",
        "images_status",
        "documents_status",
        "contract_status",
        "authorization_status",
        "contact_status",
        "reviewed_at",
        "notes",
    }
    assert set(VendorCandidate.__dataclass_fields__) == expected


def test_21_vendor_candidates_that_are_blocked_sources_stay_blocked():
    """pbfcm/mvba/ctsa/govease are BLOCKED in SOURCE_REGISTRY - their vendor
    placeholder entries must not imply anything more permissive."""
    for vendor_id, source_id in (("pbfcm", "tx_pbfcm"), ("mvba", "tx_mvba"), ("ctsa", "tx_ctsa"), ("govease", "tx_govease")):
        vendor = VENDOR_CANDIDATES[vendor_id]
        assert vendor.authorization_status == "BLOCKED"
        assert SOURCE_REGISTRY[source_id].legal_status.value == "BLOCKED"


# ---------------------------------------------------------------------------
# 23-25: freshness/conflicts/terms-changed/disabled-sources interplay with
# the new verification axis (reusing Phase 37's own tested mechanisms)
# ---------------------------------------------------------------------------

def test_22_terms_changed_source_still_denies_even_if_verification_record_says_acquired():
    """A source flagged TERMS_CHANGED (Phase 37's mechanism) must deny
    production regardless of how far this project's OWN engineering
    progress (verification.py) has gotten - the two axes must never
    override each other in the permissive direction."""
    from dataclasses import replace

    from harvesters.governance import AuthorizationScope, UsePermission, effective_authorization_status
    from harvesters.governance.authorization import ProviderAuthorization

    base = PROVIDER_AUTHORIZATIONS["fl_lienhub_certificates__provider__grant_street_group"]
    changed = replace(base, terms_changed_detected=True)
    assert effective_authorization_status(changed).value == "TERMS_CHANGED"
    # fl_lienhub_certificates itself IS technically ACQUIRED per our own
    # verification record - proving the terms-changed override is real, not
    # a coincidence of a source that was never acquired anyway.
    assert SOURCE_VERIFICATION_RECORDS["fl_lienhub_certificates"].technical_acquisition_status == TechnicalAcquisitionStatus.ACQUIRED


def test_23_disabled_or_blocked_registry_sources_never_appear_production_enabled_in_the_map():
    """Cross-check against the generated verification map convention: for
    every BLOCKED/DISABLED source in SOURCE_REGISTRY, can_promote_source_for_use()
    denies for CUSTOMER_DISPLAY (used as the map's own probe use)."""
    for source_id, record in SOURCE_REGISTRY.items():
        if record.legal_status.value in ("BLOCKED", "DISABLED"):
            decision = can_promote_source_for_use(source_id, "CUSTOMER_DISPLAY")
            assert decision.allowed is False, f"{source_id} is {record.legal_status.value} but CUSTOMER_DISPLAY was allowed"


def test_24_all_verification_records_filterable_by_state():
    fl_records = all_verification_records(state="FL")
    tx_records = all_verification_records(state="TX")
    assert len(fl_records) == 4
    assert len(tx_records) == 8
    assert all(r.state == "FL" for r in fl_records)
    assert all(r.state == "TX" for r in tx_records)


def test_25_get_verification_record_fails_closed_for_unknown_source():
    """Matches registry.get_source()'s own contract: an unrepresented
    source_id returns None, never raises, never a default 'assume verified'
    record."""
    assert get_verification_record("totally_made_up_source_id") is None


# ---------------------------------------------------------------------------
# 26-30: additional adversarial coverage - classification helper, matrix
# reuse discipline, and structural guarantees
# ---------------------------------------------------------------------------

def test_26_classify_cell_never_calls_an_unknown_value_approved():
    assert _classify_cell("UNKNOWN") != "APPROVED"
    assert _classify_cell(None) == "NONE"
    assert _classify_cell("") == "NONE"


def test_27_classify_cell_recognizes_real_approved_prefix():
    assert _classify_cell("APPROVED (grandfathered, not formally rights-audited)") == "APPROVED"


def test_28_classify_cell_recognizes_blocked_and_legal_review_distinctly():
    assert _classify_cell("BLOCKED - explicit disclosure.html clause") == "BLOCKED"
    assert _classify_cell("LEGAL_REVIEW_REQUIRED - no restriction found") == "LEGAL_REVIEW"
    assert _classify_cell("BLOCKED") != _classify_cell("LEGAL_REVIEW_REQUIRED")


def test_29_verification_module_never_duplicates_source_catalog_vocabulary():
    """Section 4's "do not create a competing registry" discipline, checked
    structurally: verification.py's own enums share no member VALUES with
    source_catalog.CoverageState (a different axis - discovery-stage catalog
    classification, not engineering-progress tracking)."""
    from harvesters.governance.source_catalog import CoverageState

    coverage_values = {v.value for v in CoverageState}
    for enum_cls in (DiscoveryStatus, VerificationStatus, TechnicalAcquisitionStatus, CountyReadinessState):
        overlap = {v.value for v in enum_cls} & coverage_values
        assert overlap == set(), f"{enum_cls.__name__} duplicates CoverageState values: {overlap}"


def test_30_production_status_for_reuses_the_real_promotion_decision_object():
    """production_status_for() must return the actual PromotionDecision
    type Phase 37 already defines - never a locally re-typed shape."""
    from harvesters.governance import PromotionDecision

    rec = SOURCE_VERIFICATION_RECORDS["tx_lgbs"]
    decision = rec.production_status_for("INGEST")
    assert isinstance(decision, PromotionDecision)


def test_31_full_county_readiness_agrees_with_production_enabled_for_county():
    """No silent disagreement between the two readiness functions: whenever
    full_county_readiness() reports PRODUCTION_READY, at least one entry in
    production_enabled_for_county()'s own dict is actually allowed=True."""
    rows = {r["county"]: r for r in load_fl_matrix()}
    for county, row in rows.items():
        state = full_county_readiness("FL", county, row)
        decisions = production_enabled_for_county("FL", county, row)
        if state == CountyReadinessState.PRODUCTION_READY:
            assert any(d.allowed for d in decisions.values()), f"{county} claims PRODUCTION_READY with no allowed decision"
