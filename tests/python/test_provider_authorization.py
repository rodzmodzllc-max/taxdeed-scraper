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

from harvesters.governance import SOURCE_REGISTRY, SourceStatus, check_ingestion_gate
from harvesters.governance.authorization import (
    AUTHORIZATION_GRANTED_STATUSES,
    PROVIDER_AUTHORIZATIONS,
    AuthorizationDocument,
    AuthorizationScope,
    AuthorizationStatus,
    AuditLogEntry,
    ProviderAuthorization,
    UsePermission,
    authorization_for_scope,
    authorizations_for_source,
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
        assert record.audit_log[0].event == "created"
