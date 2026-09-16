"""Tests for the Phase 34A provider-authorization framework
(harvesters/governance/authorization.py). Covers every scenario Phase
34A Step 17 lists, grouped the same way the instructions grouped them:
Authorization, Governance, Regression. Run with:

    pytest tests/python/test_provider_authorization.py

Existing tests in test_source_governance.py are untouched and continue to
cover the pre-existing gate.py/registry.py behavior this module builds on
top of, never replaces.
"""

from __future__ import annotations

import datetime

import pytest

from harvesters.governance import INGESTION_ALLOWED_STATUSES, SOURCE_REGISTRY, SourceStatus, check_ingestion_gate
from harvesters.governance.authorization import (
    AUTHORIZATION_GRANTED_STATUSES,
    PROVIDER_AUTHORIZATIONS,
    AuthorizationDocument,
    AuthorizationScope,
    AuthorizationStatus,
    AuditLogEntry,
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


def _minimal_record(**overrides) -> ProviderAuthorization:
    """A bare-bones, valid ProviderAuthorization for tests that need a
    fresh record rather than one of the two real Phase 34A entries -
    keeps each test's specific override front and center instead of
    repeating every field."""
    defaults = dict(
        authorization_id="test__fixture",
        source_id="fl_realauction",
        provider="Test Provider",
        government_entity=None,
        state="FL",
        county="TestCounty",
        deployment_scope="county",
        requested_by=None,
        request_date=None,
        contact_name=None,
        contact_email=None,
        request_status=AuthorizationStatus.REQUEST_NOT_STARTED,
        authorization_status=AuthorizationStatus.REQUEST_NOT_STARTED,
        document=AuthorizationDocument(),
        agreement_url=None,
        agreement_version=None,
        agreement_date=None,
        effective_date=None,
        expiration_date=None,
        review_due_date=None,
        scope=AuthorizationScope(),
        attribution_required=None,
        rate_limit=None,
        retention_requirement=None,
        privacy_restrictions=None,
        technical_restrictions=None,
        written_permission=False,
        reviewed_by=None,
        reviewed_at=None,
        notes="test fixture",
    )
    defaults.update(overrides)
    return ProviderAuthorization(**defaults)


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

def test_unknown_authorization_is_not_approved():
    decision = check_authorized_use("fl_realauction", "automated_access", county="NoSuchCounty")
    assert decision.allowed is False
    assert decision.authorization_status is None  # no record at all, not merely a denied one


def test_contacted_source_is_not_approved():
    record = _minimal_record(
        authorization_id="test__contacted",
        request_status=AuthorizationStatus.CONTACTED,
        authorization_status=AuthorizationStatus.CONTACTED,
    )
    assert record.authorization_status == AuthorizationStatus.CONTACTED
    assert record.authorization_status not in AUTHORIZATION_GRANTED_STATUSES
    assert effective_authorization_status(record) == AuthorizationStatus.CONTACTED


def test_received_document_is_not_automatically_approved():
    record = _minimal_record(
        authorization_id="test__received",
        request_status=AuthorizationStatus.RECEIVED,
        authorization_status=AuthorizationStatus.RECEIVED,
        document=AuthorizationDocument(document_name="Some Agreement", is_pending=True),
    )
    assert record.authorization_status == AuthorizationStatus.RECEIVED
    assert record.authorization_status not in AUTHORIZATION_GRANTED_STATUSES


def test_cannot_construct_authorized_true_without_granted_status():
    # Structural guarantee (Step 6/7), enforced by __post_init__ - not
    # left to a caller to remember to check.
    with pytest.raises(ValueError, match="is not permitted while authorization_status"):
        _minimal_record(
            authorization_id="test__invalid",
            authorization_status=AuthorizationStatus.CONTACTED,
            scope=AuthorizationScope(automated_access=UsePermission(requested=True, authorized=True)),
        )


def test_cannot_assert_written_permission_without_a_document_on_file():
    with pytest.raises(ValueError, match="written_permission=True requires an actual document on file"):
        _minimal_record(authorization_id="test__invalid2", written_permission=True)


def test_approved_authorization_permits_only_explicitly_authorized_actions():
    record = _minimal_record(
        authorization_id="test__approved_partial",
        authorization_status=AuthorizationStatus.APPROVED_WITH_RESTRICTIONS,
        written_permission=True,
        document=AuthorizationDocument(document_name="X", document_location="docs/agreements/x.pdf", is_pending=False),
        scope=AuthorizationScope(
            automated_access=UsePermission(requested=True, authorized=True),
            commercial_use=UsePermission(requested=True, authorized=True),
            api_redistribution=UsePermission(requested=True, authorized=False),  # explicitly NOT granted
        ),
    )
    PROVIDER_AUTHORIZATIONS[record.authorization_id] = record
    try:
        allowed = check_authorized_use("fl_realauction", "automated_access", county="TestCounty")
        denied = check_authorized_use("fl_realauction", "api_redistribution", county="TestCounty")
        assert allowed.allowed is True
        assert denied.allowed is False
        assert "does not authorize 'api_redistribution'" in denied.reason
    finally:
        del PROVIDER_AUTHORIZATIONS[record.authorization_id]


def test_restricted_authorization_blocks_prohibited_actions():
    record = _minimal_record(
        authorization_id="test__restricted",
        authorization_status=AuthorizationStatus.APPROVED_WITH_RESTRICTIONS,
        scope=AuthorizationScope(customer_display=UsePermission(requested=True, authorized=False)),
    )
    PROVIDER_AUTHORIZATIONS[record.authorization_id] = record
    try:
        decision = check_authorized_use("fl_realauction", "customer_display", county="TestCounty")
        assert decision.allowed is False
    finally:
        del PROVIDER_AUTHORIZATIONS[record.authorization_id]


def test_expired_authorization_blocks_use():
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    record = _minimal_record(
        authorization_id="test__expired",
        authorization_status=AuthorizationStatus.APPROVED,
        expiration_date=yesterday,
        scope=AuthorizationScope(automated_access=UsePermission(requested=True, authorized=True)),
    )
    assert effective_authorization_status(record) == AuthorizationStatus.EXPIRED
    PROVIDER_AUTHORIZATIONS[record.authorization_id] = record
    try:
        decision = check_authorized_use("fl_realauction", "automated_access", county="TestCounty")
        assert decision.allowed is False
        assert decision.authorization_status == AuthorizationStatus.EXPIRED
    finally:
        del PROVIDER_AUTHORIZATIONS[record.authorization_id]


def test_not_yet_expired_authorization_still_works():
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    record = _minimal_record(
        authorization_id="test__not_expired",
        authorization_status=AuthorizationStatus.APPROVED,
        expiration_date=tomorrow,
        scope=AuthorizationScope(automated_access=UsePermission(requested=True, authorized=True)),
    )
    assert effective_authorization_status(record) == AuthorizationStatus.APPROVED


def test_revoked_authorization_blocks_use():
    record = _minimal_record(
        authorization_id="test__revoked",
        authorization_status=AuthorizationStatus.REVOKED,
    )
    assert effective_authorization_status(record) == AuthorizationStatus.REVOKED
    PROVIDER_AUTHORIZATIONS[record.authorization_id] = record
    try:
        decision = check_authorized_use("fl_realauction", "automated_access", county="TestCounty")
        assert decision.allowed is False
    finally:
        del PROVIDER_AUTHORIZATIONS[record.authorization_id]


def test_terms_changed_source_blocks_new_use():
    record = _minimal_record(
        authorization_id="test__terms_changed",
        authorization_status=AuthorizationStatus.TERMS_CHANGED,
    )
    assert effective_authorization_status(record) == AuthorizationStatus.TERMS_CHANGED
    assert record.authorization_status not in AUTHORIZATION_GRANTED_STATUSES


def test_county_specific_authorization_does_not_automatically_authorize_another_county():
    # Real Phase 34A data: Alachua has a record, a made-up third county does not.
    alachua = check_authorized_use("fl_realauction", "automated_access", county="Alachua")
    other = check_authorized_use("fl_realauction", "automated_access", county="Orange")
    assert alachua.authorization_status == AuthorizationStatus.LEGAL_REVIEW_REQUIRED  # a record exists
    assert other.authorization_status is None  # no record at all for Orange
    assert alachua.allowed is False and other.allowed is False  # neither is actually granted today


def test_realauction_provider_authorization_does_not_automatically_authorize_every_deployment():
    # A hypothetical APPROVED record for a THIRD, previously-unlisted
    # fl_realauction county (Duval - no real record exists for it) must
    # not leak to Volusia, to Alachua, or to a provider-wide (county=None)
    # check - authorization_for_scope() matches (source_id, county)
    # exactly, never widens.
    hypothetically_approved = _minimal_record(
        authorization_id="test__duval_approved",
        source_id="fl_realauction",
        county="Duval",
        authorization_status=AuthorizationStatus.APPROVED,
        scope=AuthorizationScope(automated_access=UsePermission(requested=True, authorized=True)),
    )
    PROVIDER_AUTHORIZATIONS[hypothetically_approved.authorization_id] = hypothetically_approved
    try:
        assert check_authorized_use("fl_realauction", "automated_access", county="Duval").allowed is True
        assert check_authorized_use("fl_realauction", "automated_access", county="Volusia").allowed is False
        assert check_authorized_use("fl_realauction", "automated_access", county="Alachua").allowed is False
        assert check_authorized_use("fl_realauction", "automated_access", county=None).allowed is False
        # And the real, on-file Alachua/Volusia records must remain exactly what they are (LEGAL_REVIEW_REQUIRED, denied).
        for county in ("Alachua", "Volusia"):
            record = authorization_for_scope("fl_realauction", county)
            assert record is not None
            assert record.authorization_status == AuthorizationStatus.LEGAL_REVIEW_REQUIRED
    finally:
        del PROVIDER_AUTHORIZATIONS[hypothetically_approved.authorization_id]


def test_lienhub_authorization_does_not_automatically_authorize_unrelated_sources():
    lienhub_records = authorizations_for_source("fl_lienhub_certificates")
    assert len(lienhub_records) == 1
    assert lienhub_records[0].source_id == "fl_lienhub_certificates"
    # No LienHub record's source_id ever equals fl_realauction/fl_laft_pdfs/anything else.
    for other_source in ("fl_realauction", "fl_laft_pdfs", "tx_lgbs"):
        assert authorization_for_scope(other_source, None) is None or authorization_for_scope(other_source, None).source_id == other_source
        assert all(r.source_id != "fl_lienhub_certificates" for r in authorizations_for_source(other_source))


def test_check_authorized_use_rejects_unknown_use_name():
    with pytest.raises(ValueError, match="not a recognized authorization-scope dimension"):
        check_authorized_use("fl_realauction", "totally_made_up_use", county="Alachua")


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------

def test_legal_review_required_remains_blocked_from_customer_facing_production():
    for source_id in ("fl_realauction", "fl_lienhub_certificates"):
        record = SOURCE_REGISTRY[source_id]
        assert record.current_commercial_authorization_status is not None
        assert record.current_commercial_authorization_status.startswith("LEGAL_REVIEW_REQUIRED")
        # The OLD, whole-source ingestion gate is untouched by this phase -
        # legal_status/historical_project_status both stay APPROVED, exactly
        # as Phase 33.5 left them (Step 12: never weaken the existing gate).
        assert record.legal_status == SourceStatus.APPROVED
        assert record.historical_project_status == SourceStatus.APPROVED
        assert check_ingestion_gate(source_id).allowed is True


def test_automated_access_denied_means_harvester_cannot_proceed_per_new_gate():
    for source_id, county in (("fl_realauction", "Alachua"), ("fl_realauction", "Volusia"), ("fl_lienhub_certificates", None)):
        decision = check_authorized_use(source_id, "automated_access", county=county)
        assert decision.allowed is False, (source_id, county)


def test_customer_display_denied_means_frontend_must_not_expose_the_source():
    for source_id, county in (("fl_realauction", "Alachua"), ("fl_lienhub_certificates", None)):
        decision = check_authorized_use(source_id, "customer_display", county=county)
        assert decision.allowed is False, (source_id, county)


def test_export_denied_means_export_cannot_include_restricted_data():
    for source_id, county in (("fl_realauction", "Alachua"), ("fl_lienhub_certificates", None)):
        decision = check_authorized_use(source_id, "customer_export", county=county)
        assert decision.allowed is False, (source_id, county)


def test_api_redistribution_denied_means_customer_api_cannot_expose_the_data():
    for source_id, county in (("fl_realauction", "Alachua"), ("fl_lienhub_certificates", None)):
        decision = check_authorized_use(source_id, "api_redistribution", county=county)
        assert decision.allowed is False, (source_id, county)


def test_new_gate_never_grants_what_the_old_gate_would_deny():
    # The new per-use gate can only ADD restriction, never remove it. If a
    # hypothetical future source_id fails the old ingestion gate, the new
    # gate must deny too, regardless of any authorization record that might
    # exist for it.
    hypothetical = _minimal_record(
        authorization_id="test__unknown_source",
        source_id="this_source_id_does_not_exist_in_the_registry",
        county=None,
        authorization_status=AuthorizationStatus.APPROVED,
        scope=AuthorizationScope(automated_access=UsePermission(requested=True, authorized=True)),
    )
    PROVIDER_AUTHORIZATIONS[hypothetical.authorization_id] = hypothetical
    try:
        decision = check_authorized_use("this_source_id_does_not_exist_in_the_registry", "automated_access")
        assert decision.allowed is False
        assert decision.ingestion_gate_allowed is False
    finally:
        del PROVIDER_AUTHORIZATIONS[hypothetical.authorization_id]


# ---------------------------------------------------------------------------
# Data integrity of the two real Phase 34A authorization records
# ---------------------------------------------------------------------------

def test_real_lienhub_record_reflects_the_supplied_agreement():
    record = PROVIDER_AUTHORIZATIONS["fl_lienhub_certificates__provider__grant_street_group"]
    assert record.provider == "Grant Street Group"
    assert record.authorization_status == AuthorizationStatus.LEGAL_REVIEW_REQUIRED
    assert record.written_permission is False
    assert record.document.is_pending is True
    assert record.document.document_location is None  # Step 15: never fabricate a path
    assert all(not getattr(record.scope, dim).authorized for dim in (
        "automated_access", "commercial_use", "storage", "customer_display", "customer_export", "api_redistribution",
    ))


def test_real_realauction_records_are_county_scoped_not_provider_wide():
    alachua = PROVIDER_AUTHORIZATIONS["fl_realauction__county__alachua"]
    volusia = PROVIDER_AUTHORIZATIONS["fl_realauction__county__volusia"]
    assert alachua.county == "Alachua"
    assert volusia.county == "Volusia"
    assert alachua.deployment_scope == "county"
    assert volusia.deployment_scope == "county"
    assert alachua.provider == volusia.provider == "RealAuction.com, LLC"
    for record in (alachua, volusia):
        assert record.authorization_status == AuthorizationStatus.LEGAL_REVIEW_REQUIRED
        assert record.written_permission is False
        assert record.document.is_pending is True
        assert record.document.document_location is None


def test_no_authorization_record_claims_written_permission():
    # Global guarantee across every record currently in the registry, not
    # just the two named ones - Phase 34A Step 9/24: this phase never
    # represents that authorization has been obtained.
    for record in PROVIDER_AUTHORIZATIONS.values():
        assert record.written_permission is False, record.authorization_id
        assert record.document.is_pending is True, record.authorization_id
        assert record.document.document_location is None, record.authorization_id
        for dim in (
            "automated_access", "commercial_use", "storage", "historical_storage", "normalization",
            "derived_data", "customer_display", "customer_export", "api_access", "api_redistribution",
            "image_use", "document_use",
        ):
            assert getattr(record.scope, dim).authorized is False, (record.authorization_id, dim)


def test_every_real_record_has_at_least_one_audit_log_entry():
    for record in PROVIDER_AUTHORIZATIONS.values():
        assert len(record.audit_log) >= 1, record.authorization_id


# ---------------------------------------------------------------------------
# Phase 34B: Authorization Gate Integration & Source-Policy Hardening.
#
# The tests below are additional, explicitly named for direct traceability
# to Phase 34B's own Section 8/9/10/11/12/13/14/15/16/21 requirements, even
# where the underlying guarantee is already exercised by a Phase 34A test
# above (e.g. Sections 8/9/10) - Phase 34B's instructions ask for each
# scenario "by name", so each gets its own test here rather than relying on
# a reader to trace it back to an equivalent Phase 34A test. None of these
# weaken, replace, or duplicate the effect of any existing test; every one
# is additive.
# ---------------------------------------------------------------------------


def test_phase34b_section8_alachua_authorization_does_not_leak_to_volusia_or_vice_versa():
    """Section 8's own named scenario: check (fl_realauction, Alachua) against
    the Alachua-scoped record, then confirm Volusia does not inherit it, and
    the reverse (Volusia does not inherit Alachua)."""
    alachua_decision = check_authorized_use("fl_realauction", "automated_access", county="Alachua")
    volusia_decision = check_authorized_use("fl_realauction", "automated_access", county="Volusia")
    assert alachua_decision.authorization_status == AuthorizationStatus.LEGAL_REVIEW_REQUIRED
    assert volusia_decision.authorization_status == AuthorizationStatus.LEGAL_REVIEW_REQUIRED
    # Each is denied on its OWN record's status, not by inheriting the other's.
    assert authorization_for_scope("fl_realauction", "Alachua").authorization_id == "fl_realauction__county__alachua"
    assert authorization_for_scope("fl_realauction", "Volusia").authorization_id == "fl_realauction__county__volusia"
    assert authorization_for_scope("fl_realauction", "Alachua") is not authorization_for_scope("fl_realauction", "Volusia")


def test_phase34b_section9_lienhub_fails_automated_commercial_authorization_check():
    """Section 9's own named scenario: fl_lienhub_certificates remains
    LEGAL_REVIEW_REQUIRED and fails an automated-commercial-authorization
    check across every dimension a commercial pipeline would need."""
    record = PROVIDER_AUTHORIZATIONS["fl_lienhub_certificates__provider__grant_street_group"]
    assert record.authorization_status == AuthorizationStatus.LEGAL_REVIEW_REQUIRED
    for use in ("automated_access", "commercial_use", "customer_display", "customer_export", "api_redistribution"):
        decision = check_authorized_use("fl_lienhub_certificates", use, county=None)
        assert decision.allowed is False, use
        assert decision.authorization_status == AuthorizationStatus.LEGAL_REVIEW_REQUIRED


def test_phase34b_section10_only_alachua_and_volusia_are_represented_for_realauction():
    """Section 10's own named scenario: confirm no other RealAuction county
    has silently gained an authorization record - exactly two records exist
    for fl_realauction, scoped to exactly {Alachua, Volusia}."""
    records = authorizations_for_source("fl_realauction")
    counties = {r.county for r in records}
    assert counties == {"Alachua", "Volusia"}
    assert len(records) == 2


def test_phase34b_section11_blocked_source_denied_before_any_authorization_lookup():
    """Section 11's fail-closed matrix: a BLOCKED source (tx_pbfcm) must be
    denied by the ingestion gate itself, with the authorization-record
    lookup never even reached (ingestion_gate_allowed=False, authorization_
    status=None - not merely 'no record found')."""
    assert SOURCE_REGISTRY["tx_pbfcm"].legal_status == SourceStatus.BLOCKED
    decision = check_authorized_use("tx_pbfcm", "automated_access")
    assert decision.allowed is False
    assert decision.ingestion_gate_allowed is False
    assert decision.authorization_status is None
    assert authorized_for_ingestion("tx_pbfcm") is False


def test_phase34b_section11_disabled_status_is_not_an_ingestion_allowed_status():
    """No SourceRecord in the current registry uses SourceStatus.DISABLED
    (only BLOCKED sources exist today: tx_pbfcm, tx_mvba, tx_ctsa,
    tx_govease) - fabricating a fake registry entry to exercise DISABLED
    would violate this phase's 'never fabricate' rule, so this test instead
    confirms the enum-level guarantee DISABLED and BLOCKED both rely on:
    neither is a member of INGESTION_ALLOWED_STATUSES, so check_ingestion_
    gate() (and everything built on top of it, including this module) would
    deny a DISABLED source exactly the same way it denies a BLOCKED one, by
    the same code path, with no separate carve-out for DISABLED anywhere in
    gate.py or authorization.py to go stale."""
    assert SourceStatus.DISABLED not in INGESTION_ALLOWED_STATUSES
    assert SourceStatus.BLOCKED not in INGESTION_ALLOWED_STATUSES
    assert not any(r.legal_status == SourceStatus.DISABLED for r in SOURCE_REGISTRY.values())


def test_phase34b_section12_historical_approved_status_never_satisfies_a_current_authorization_check():
    """Section 12: a historical APPROVED legal_status must never, by itself,
    satisfy a current commercial authorization check. fl_realauction and
    fl_lienhub_certificates both carry historical_project_status=APPROVED
    (and legal_status=APPROVED) yet both are denied by check_authorized_use()
    - proving the function never reads those two SourceRecord fields at all,
    only the separate, real ProviderAuthorization records."""
    import inspect

    from harvesters.governance import authorization as auth_module

    source_code = inspect.getsource(auth_module)
    assert "historical_project_status" not in source_code
    assert "current_commercial_authorization_status" not in source_code

    for source_id in ("fl_realauction", "fl_lienhub_certificates"):
        record = SOURCE_REGISTRY[source_id]
        assert record.legal_status == SourceStatus.APPROVED
        assert record.historical_project_status == SourceStatus.APPROVED
        county = "Alachua" if source_id == "fl_realauction" else None
        assert check_authorized_use(source_id, "automated_access", county=county).allowed is False


def test_phase34b_section13_future_effective_date_denies_as_not_yet_effective():
    """Section 13: an authorization whose effective_date is in the future
    must be treated as NOT_YET_EFFECTIVE (denied), symmetrically with an
    expired one being denied."""
    record = _minimal_record(
        authorization_id="test__not_yet_effective",
        authorization_status=AuthorizationStatus.APPROVED,
        effective_date="2099-01-01",
        scope=AuthorizationScope(automated_access=UsePermission(requested=True, authorized=True)),
    )
    assert effective_authorization_status(record) == AuthorizationStatus.NOT_YET_EFFECTIVE
    PROVIDER_AUTHORIZATIONS[record.authorization_id] = record
    try:
        decision = check_authorized_use("fl_realauction", "automated_access", county="TestCounty")
        assert decision.allowed is False
        assert decision.authorization_status == AuthorizationStatus.NOT_YET_EFFECTIVE
    finally:
        del PROVIDER_AUTHORIZATIONS[record.authorization_id]


def test_phase34b_section13_effective_date_after_expiration_date_is_rejected_at_construction():
    """Data-integrity companion to the NOT_YET_EFFECTIVE test above: a record
    describing a window that never exists (effective_date after
    expiration_date) must fail fast at construction time, not silently pick
    an interpretation later."""
    with pytest.raises(ValueError, match="expiration_date"):
        _minimal_record(
            authorization_id="test__impossible_window",
            effective_date="2026-06-01",
            expiration_date="2026-01-01",
        )


def test_phase34b_section14_restriction_matrix_across_the_four_dimensions():
    """Section 14's restriction matrix: for an APPROVED_WITH_RESTRICTIONS
    record, each of the four production-facing dimensions
    (automated_access, customer_display, customer_export, api_redistribution)
    is authorized or denied strictly per its OWN UsePermission.authorized
    flag - never blanket-granted because the record's overall status is
    granted, and never blanket-denied either."""
    matrix = [
        # (automated, display, export, api) -> expected allowed per dimension
        (True, False, False, False),
        (True, True, False, False),
        (True, True, True, False),
        (True, True, True, True),
        (False, False, False, False),
    ]
    for i, (automated, display, export, api) in enumerate(matrix):
        record = _minimal_record(
            authorization_id=f"test__matrix_{i}",
            authorization_status=AuthorizationStatus.APPROVED_WITH_RESTRICTIONS,
            scope=AuthorizationScope(
                automated_access=UsePermission(requested=True, authorized=automated),
                customer_display=UsePermission(requested=True, authorized=display),
                customer_export=UsePermission(requested=True, authorized=export),
                api_redistribution=UsePermission(requested=True, authorized=api),
            ),
        )
        PROVIDER_AUTHORIZATIONS[record.authorization_id] = record
        try:
            assert check_authorized_use("fl_realauction", "automated_access", county="TestCounty").allowed is automated, i
            assert check_authorized_use("fl_realauction", "customer_display", county="TestCounty").allowed is display, i
            assert check_authorized_use("fl_realauction", "customer_export", county="TestCounty").allowed is export, i
            assert check_authorized_use("fl_realauction", "api_redistribution", county="TestCounty").allowed is api, i
        finally:
            del PROVIDER_AUTHORIZATIONS[record.authorization_id]


def test_phase34b_section15_discovered_source_denied_via_the_old_gate_no_op_path():
    """Section 15: a DISCOVERED source (tx_comptroller_directory - not yet
    reviewed at all, zero ProviderAuthorization records) is denied by
    authorized_for_ingestion() via the unmodified old-gate no-op path, the
    same as it always was before Phase 34B - proving the new wrapper adds
    no new behavior for a source that hasn't opted into the framework."""
    assert SOURCE_REGISTRY["tx_comptroller_directory"].legal_status == SourceStatus.DISCOVERED
    assert authorizations_for_source("tx_comptroller_directory") == ()
    assert authorized_for_ingestion("tx_comptroller_directory") is False
    assert authorized_for_ingestion("tx_comptroller_directory") == check_ingestion_gate("tx_comptroller_directory").allowed


def test_phase34b_section16_use_decision_carries_a_populated_checked_at_timestamp():
    """Section 16: every UseDecision (including a denial) carries a real,
    populated checked_at timestamp, distinct from record fields, and no
    sensitive data (credentials, personal data) appears on the dataclass -
    only source_id/use/county/status/reason/timestamp."""
    decision = check_authorized_use("fl_lienhub_certificates", "automated_access", county=None)
    assert isinstance(decision, UseDecision)
    assert decision.checked_at  # non-empty
    # Must parse as a real ISO datetime, not a placeholder string.
    datetime.datetime.fromisoformat(decision.checked_at)
    expected_fields = {"source_id", "use", "county", "allowed", "ingestion_gate_allowed", "authorization_status", "reason", "checked_at"}
    assert {f.name for f in decision.__dataclass_fields__.values()} == expected_fields


# ---------------------------------------------------------------------------
# Phase 34B: the three new production-boundary wrapper functions
# (authorized_for_ingestion / authorized_for_customer_output /
# authorized_for_api_export) - the actual new call surface wired into
# scripts/sync-texas-to-supabase.py this phase.
# ---------------------------------------------------------------------------


def test_new_customer_output_check_is_a_no_op_for_sources_with_no_authorization_records():
    """The central Phase 34B safety guarantee: for any source_id with ZERO
    ProviderAuthorization records (today, every real TX source), the new
    wrapper functions must return byte-for-byte the same result as the
    pre-existing, unmodified gate.py functions - proving Phase 34B changes
    nothing about current TX production behavior."""
    from harvesters.governance.gate import project_row_for_api_export, project_row_for_customer_output

    for source_id in ("tx_lgbs", "tx_realauction"):
        assert authorizations_for_source(source_id) == ()
        row = {"case_no": "1", "harvester_source": source_id, "state": "TX", "county": "Dallas"}
        assert authorized_for_customer_output(row, source_id, county="Dallas") == project_row_for_customer_output(row, source_id)
        assert authorized_for_api_export(row, source_id, county="Dallas") == project_row_for_api_export(row, source_id)
        assert authorized_for_ingestion(source_id) == check_ingestion_gate(source_id).allowed


def test_authorized_for_customer_output_denies_a_source_with_a_record_but_no_granted_display_use():
    """For a source_id that HAS entered the framework (fl_realauction), the
    wrapper is held to the stricter standard even though the old projection
    function alone would have allowed the row through (fl_realauction has
    no field-shape restrictions, so project_row_for_customer_output() alone
    returns the row unchanged) - the new per-use authorization check is what
    actually blocks it."""
    from harvesters.governance.gate import project_row_for_customer_output

    row = {"case_no": "1", "harvester_source": "fl_realauction", "state": "FL", "county": "Alachua"}
    assert project_row_for_customer_output(row, "fl_realauction") is not None  # old function alone would allow it
    assert authorized_for_customer_output(row, "fl_realauction", county="Alachua") is None  # new wrapper denies it


def test_authorized_for_api_export_requires_both_export_and_api_redistribution_dimensions():
    """authorized_for_api_export() denies if EITHER customer_export OR
    api_redistribution is not authorized - a record granting only one of
    the two must not pass."""
    record = _minimal_record(
        authorization_id="test__export_only",
        authorization_status=AuthorizationStatus.APPROVED_WITH_RESTRICTIONS,
        scope=AuthorizationScope(
            customer_export=UsePermission(requested=True, authorized=True),
            api_redistribution=UsePermission(requested=True, authorized=False),
        ),
    )
    PROVIDER_AUTHORIZATIONS[record.authorization_id] = record
    try:
        row = {"case_no": "1", "harvester_source": "fl_realauction", "state": "FL", "county": "TestCounty"}
        assert authorized_for_api_export(row, "fl_realauction", county="TestCounty") is None
    finally:
        del PROVIDER_AUTHORIZATIONS[record.authorization_id]


def test_authorized_for_ingestion_holds_a_framework_source_to_automated_access_specifically():
    for source_id, county in (("fl_realauction", "Alachua"), ("fl_lienhub_certificates", None)):
        assert authorized_for_ingestion(source_id, county=county) is False
