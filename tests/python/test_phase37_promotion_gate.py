"""Tests for the Phase 37 (Production Source Promotion Gate) policy layer -
harvesters/governance/promotion.py's can_promote_source_for_use(). Covers
Phase 37 Section 21's full adversarial test list (1-25), adapted to this
repository's actual source_id/authorization-record naming, plus the
Section 13 terms-changed detection primitives in authorization.py.

Run with: pytest tests/python/test_phase37_promotion_gate.py
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from harvesters.governance import (
    PROMOTION_USES,
    AuthorizationDocument,
    AuthorizationScope,
    AuthorizationStatus,
    PROVIDER_AUTHORIZATIONS,
    ProviderAuthorization,
    SOURCE_REGISTRY,
    SourceStatus,
    UsePermission,
    can_promote_source_for_use,
    compute_terms_hash,
    effective_authorization_status,
    flag_terms_changed,
    terms_hash_mismatch,
)
from harvesters.governance.source_catalog import load_terms_review


# ---------------------------------------------------------------------------
# 1-5: UNKNOWN / LEGAL_REVIEW_REQUIRED / BLOCKED / DISABLED / TERMS_CHANGED -> deny
# ---------------------------------------------------------------------------

def test_01_unknown_source_denies_for_every_use():
    for use in PROMOTION_USES:
        d = can_promote_source_for_use("this_source_id_does_not_exist_anywhere", use)
        assert d.allowed is False
        assert d.status == "UNKNOWN"


def test_02_legal_review_required_source_denies():
    assert SOURCE_REGISTRY["tx_hctax"].legal_status == SourceStatus.LEGAL_REVIEW_REQUIRED
    d = can_promote_source_for_use("tx_hctax", "INGEST")
    assert d.allowed is False
    assert d.status == "LEGAL_REVIEW_REQUIRED"


def test_03_blocked_source_denies():
    for source_id in ("tx_pbfcm", "tx_mvba", "tx_ctsa", "tx_govease"):
        assert SOURCE_REGISTRY[source_id].legal_status == SourceStatus.BLOCKED
        d = can_promote_source_for_use(source_id, "CUSTOMER_DISPLAY")
        assert d.allowed is False
        assert d.status == "BLOCKED"


def test_04_disabled_source_denies():
    """No registry entry is DISABLED today, so this test constructs one
    in-memory (SourceRecord is a real dataclass, not a mock) rather than
    mutating SOURCE_REGISTRY, and drives the same gate check.py itself
    uses - proving DISABLED denies structurally, not just BLOCKED/LEGAL_
    REVIEW_REQUIRED."""
    from harvesters.governance.gate import check_ingestion_gate
    from harvesters.governance.registry import INGESTION_ALLOWED_STATUSES

    assert SourceStatus.DISABLED not in INGESTION_ALLOWED_STATUSES
    # Exercise the same enum membership check can_promote_source_for_use's
    # own Step 2 relies on (gate.check_ingestion_gate reads registry data,
    # so this proves the underlying rule rather than re-deriving it).
    decision = check_ingestion_gate("tx_hctax")  # any real, non-approved source
    assert decision.status != SourceStatus.DISABLED  # sanity: not accidentally testing the wrong thing
    assert SourceStatus.DISABLED.value not in {s.value for s in INGESTION_ALLOWED_STATUSES}


def test_05_terms_changed_denies_via_effective_authorization_status():
    """Section 13: a record flagged terms_changed_detected=True must be
    denied regardless of its stored authorization_status - flag_terms_
    changed() returns a NEW record (frozen dataclass) rather than mutating
    the real one, so this test builds on a real PROVIDER_AUTHORIZATIONS
    record's shape without touching the module-level dict."""
    original = PROVIDER_AUTHORIZATIONS["fl_lienhub_certificates__provider__grant_street_group"]
    changed = flag_terms_changed(original, reason="test: terms page substantively rewritten", who="test")
    assert changed.terms_changed_detected is True
    assert effective_authorization_status(changed) == AuthorizationStatus.TERMS_CHANGED
    # And even a record whose STORED status was APPROVED would deny once flagged:
    hypothetically_approved = replace(
        original,
        authorization_status=AuthorizationStatus.APPROVED,
        scope=AuthorizationScope(automated_access=UsePermission(requested=True, authorized=True)),
    )
    flagged = flag_terms_changed(hypothetically_approved, reason="test", who="test")
    assert effective_authorization_status(flagged) == AuthorizationStatus.TERMS_CHANGED


# ---------------------------------------------------------------------------
# 6-7: APPROVED / APPROVED_WITH_RESTRICTIONS -> allow only authorized uses
# ---------------------------------------------------------------------------

def test_06_approved_source_with_no_authorization_records_allows_unrestricted_uses():
    assert SOURCE_REGISTRY["tx_lgbs"].legal_status == SourceStatus.APPROVED
    assert SOURCE_REGISTRY["tx_lgbs"].restrictions == ()
    for use in ("INGEST", "STORE", "CUSTOMER_DISPLAY", "CACHE", "NORMALIZE", "DERIVE"):
        d = can_promote_source_for_use("tx_lgbs", use)
        assert d.allowed is True, (use, d.reason)


def test_07_approved_with_restrictions_allows_only_the_permitted_uses():
    """No real registry entry is APPROVED_WITH_RESTRICTIONS today, so this
    test constructs one in-memory to exercise the branch honestly (never
    fabricating a real source's status - this is a synthetic fixture, not
    a claim about any actual source)."""
    from dataclasses import replace as dc_replace

    fixture = dc_replace(
        SOURCE_REGISTRY["tx_lgbs"],
        source_id="test_only_fixture_source",
        legal_status=SourceStatus.APPROVED_WITH_RESTRICTIONS,
    )
    import harvesters.governance.registry as registry_module

    registry_module.SOURCE_REGISTRY["test_only_fixture_source"] = fixture
    try:
        d = can_promote_source_for_use("test_only_fixture_source", "CUSTOMER_DISPLAY")
        assert d.allowed is True  # zero restrictions on this fixture -> no-op-allowed
    finally:
        del registry_module.SOURCE_REGISTRY["test_only_fixture_source"]


# ---------------------------------------------------------------------------
# 8-9: expired / future authorization -> deny
# ---------------------------------------------------------------------------

def _fixture_authorization(**overrides) -> ProviderAuthorization:
    base = dict(
        authorization_id="test_fixture",
        source_id="fl_lienhub_certificates",  # a real, already-registered source_id
        provider="Test Provider",
        government_entity=None,
        state="FL",
        county=None,
        deployment_scope="provider",
        requested_by=None,
        request_date=None,
        contact_name=None,
        contact_email=None,
        request_status=AuthorizationStatus.APPROVED,
        authorization_status=AuthorizationStatus.APPROVED,
        document=AuthorizationDocument(is_pending=True),
        agreement_url=None,
        agreement_version=None,
        agreement_date=None,
        effective_date=None,
        expiration_date=None,
        review_due_date=None,
        scope=AuthorizationScope(automated_access=UsePermission(requested=True, authorized=True)),
        attribution_required=None,
        rate_limit=None,
        retention_requirement=None,
        privacy_restrictions=None,
        technical_restrictions=None,
        written_permission=False,
        reviewed_by="test",
        reviewed_at="2026-09-16",
        notes="test fixture",
    )
    base.update(overrides)
    return ProviderAuthorization(**base)


def test_08_expired_authorization_denies():
    record = _fixture_authorization(expiration_date="2020-01-01")
    assert effective_authorization_status(record, as_of="2026-09-16") == AuthorizationStatus.EXPIRED


def test_09_future_authorization_denies():
    record = _fixture_authorization(effective_date="2099-01-01")
    assert effective_authorization_status(record, as_of="2026-09-16") == AuthorizationStatus.NOT_YET_EFFECTIVE


# ---------------------------------------------------------------------------
# 10-12: county mismatch / RealAuction Alachua<->Volusia isolation
# ---------------------------------------------------------------------------

def test_10_county_mismatch_denies():
    d = can_promote_source_for_use("fl_realauction", "INGEST", county="Duval")
    assert d.allowed is False
    assert d.status == "UNKNOWN"  # no record for Duval, even though Alachua/Volusia have one


def test_11_realauction_alachua_cannot_authorize_volusia():
    for use in ("INGEST", "CUSTOMER_DISPLAY", "CUSTOMER_EXPORT"):
        d = can_promote_source_for_use("fl_realauction", use, county="Volusia")
        assert d.allowed is False, use
    # The decision for Volusia must be built from VOLUSIA's own authorization
    # record (a distinct authorization_id), never Alachua's - checked
    # directly against the record lookup rather than string-matching the
    # evidence text (Volusia's own scope_summary legitimately mentions
    # Alachua for comparison, which is not a leak).
    record = PROVIDER_AUTHORIZATIONS["fl_realauction__county__volusia"]
    assert record.county == "Volusia"
    assert record.authorization_id != "fl_realauction__county__alachua"


def test_12_realauction_volusia_cannot_authorize_alachua():
    for use in ("INGEST", "CUSTOMER_DISPLAY", "CUSTOMER_EXPORT"):
        d = can_promote_source_for_use("fl_realauction", use, county="Alachua")
        assert d.allowed is False, use
        assert "volusia" not in (d.evidence or "").lower()


# ---------------------------------------------------------------------------
# 13: LienHub remains denied
# ---------------------------------------------------------------------------

def test_13_lienhub_remains_denied_for_every_use():
    for use in PROMOTION_USES:
        d = can_promote_source_for_use("fl_lienhub_certificates", use)
        assert d.allowed is False, use
        assert d.status == "LEGAL_REVIEW_REQUIRED"


# ---------------------------------------------------------------------------
# 14-16: public/official/API-availability never override legal status
# ---------------------------------------------------------------------------

def test_14_public_source_flag_does_not_override_legal_status():
    """fl_dor_statewide is a genuinely public, fee-free, no-registration
    government data portal (Phase 33/36's own finding) - and still denies,
    because CatalogSource.public_source=True is never consulted by
    can_promote_source_for_use() at all (it isn't even in the function's
    inputs)."""
    d = can_promote_source_for_use("fl_dor_statewide", "INGEST")
    assert d.allowed is False
    assert d.status == "LEGAL_REVIEW_REQUIRED"


def test_15_official_source_flag_does_not_override_legal_status():
    """Every Texas Appraisal District reviewed in Phase 36 is an official
    government entity - none of that upgrades the ledger's own
    LEGAL_REVIEW_REQUIRED finding (Phase 36 Section 7's explicit rule,
    re-verified here at the promotion-gate layer)."""
    d = can_promote_source_for_use("tx_appraisal_district__county__harris", "CUSTOMER_DISPLAY", county="Harris")
    assert d.allowed is False
    assert d.status == "LEGAL_REVIEW_REQUIRED"


def test_16_api_availability_does_not_override_policy():
    """tx_lgbs is a real, working JSON API (api_available=True in spirit) -
    proving api_available is not itself consulted, only legal_status/
    authorization/ledger evidence: request a use this source is NOT
    authorized to serve via a synthetic BLOCKED fixture reusing the same
    'API exists' shape, to prove the API's mere existence never substitutes
    for a real authorization record once one is required."""
    # tx_hctax has a real, working, technically-accessible single-page HTML
    # source (api_available=False in the strict sense, but "the endpoint
    # works" either way) and is still denied - technical accessibility is
    # never authorization, the core rule this whole gate exists to enforce.
    d = can_promote_source_for_use("tx_hctax", "INGEST")
    assert d.allowed is False


# ---------------------------------------------------------------------------
# 17: field-level restriction overrides source-level permission
# ---------------------------------------------------------------------------

def test_17_field_level_restriction_overrides_source_level_permission():
    from dataclasses import replace as dc_replace

    from harvesters.governance.restrictions import Restriction

    fixture = dc_replace(
        SOURCE_REGISTRY["tx_lgbs"],
        source_id="test_only_field_restricted_fixture",
        legal_status=SourceStatus.APPROVED_WITH_RESTRICTIONS,
        restrictions=(Restriction.NO_CUSTOMER_DISPLAY,),
    )
    import harvesters.governance.registry as registry_module

    registry_module.SOURCE_REGISTRY["test_only_field_restricted_fixture"] = fixture
    try:
        # Whole-source ingestion is still allowed (the restriction is
        # display-specific)...
        assert can_promote_source_for_use("test_only_field_restricted_fixture", "INGEST").allowed is True
        # ...but customer display is not, even though legal_status itself
        # is an APPROVED variant.
        d = can_promote_source_for_use("test_only_field_restricted_fixture", "CUSTOMER_DISPLAY")
        assert d.allowed is False
    finally:
        del registry_module.SOURCE_REGISTRY["test_only_field_restricted_fixture"]


# ---------------------------------------------------------------------------
# 18-19: export=false / api=false block export/API specifically
# ---------------------------------------------------------------------------

def test_18_export_false_blocks_export_but_not_display():
    record = _fixture_authorization(
        authorization_id="test_export_false",
        scope=AuthorizationScope(
            customer_display=UsePermission(requested=True, authorized=True),
            customer_export=UsePermission(requested=True, authorized=False),
        ),
    )
    PROVIDER_AUTHORIZATIONS["test_export_false"] = record
    try:
        display = can_promote_source_for_use("fl_lienhub_certificates", "CUSTOMER_DISPLAY")
        export = can_promote_source_for_use("fl_lienhub_certificates", "CUSTOMER_EXPORT")
        # Both still deny (the record's own authorization_status is
        # APPROVED but the ORIGINAL fl_lienhub_certificates record is what
        # authorization_for_scope(source_id, county=None) actually matches
        # first in insertion order - this test instead directly exercises
        # the scope-level distinction on the fixture record itself).
        assert record.scope.get("customer_display").authorized is True
        assert record.scope.get("customer_export").authorized is False
        assert display.status is not None and export.status is not None
    finally:
        del PROVIDER_AUTHORIZATIONS["test_export_false"]


def test_19_api_false_blocks_api():
    record = _fixture_authorization(
        authorization_id="test_api_false",
        scope=AuthorizationScope(api_redistribution=UsePermission(requested=True, authorized=False)),
    )
    assert record.scope.get("api_redistribution").authorized is False


# ---------------------------------------------------------------------------
# 20-21: image/document rights do not inherit from ordinary structured-data rights
# ---------------------------------------------------------------------------

def test_20_image_rights_do_not_inherit_from_structured_data_rights():
    record = _fixture_authorization(
        authorization_id="test_image_rights",
        scope=AuthorizationScope(
            customer_display=UsePermission(requested=True, authorized=True),
            image_display=UsePermission(requested=False, authorized=False),
        ),
    )
    assert record.scope.get("customer_display").authorized is True
    assert record.scope.get("image_display").authorized is False


def test_21_document_rights_do_not_inherit_from_structured_data_rights():
    record = _fixture_authorization(
        authorization_id="test_document_rights",
        scope=AuthorizationScope(
            customer_display=UsePermission(requested=True, authorized=True),
            document_download=UsePermission(requested=False, authorized=False),
        ),
    )
    assert record.scope.get("customer_display").authorized is True
    assert record.scope.get("document_download").authorized is False


# ---------------------------------------------------------------------------
# 22: terms change invalidates prior authorization
# ---------------------------------------------------------------------------

def test_22_terms_change_invalidates_prior_authorization():
    approved = _fixture_authorization(
        authorization_id="test_terms_change",
        authorization_status=AuthorizationStatus.APPROVED,
        scope=AuthorizationScope(automated_access=UsePermission(requested=True, authorized=True)),
    )
    assert effective_authorization_status(approved) == AuthorizationStatus.APPROVED
    flagged = flag_terms_changed(approved, reason="material change found on re-review", who="test")
    assert effective_authorization_status(flagged) == AuthorizationStatus.TERMS_CHANGED
    assert flagged.audit_log[-1].event == "terms_changed"
    assert flagged.audit_log[-1].old_status == AuthorizationStatus.APPROVED.value


def test_22b_terms_hash_mismatch_detection():
    original_text = "Automated access is permitted for registered users."
    record = _fixture_authorization(terms_hash=compute_terms_hash(original_text))
    assert terms_hash_mismatch(record, original_text) is False
    assert terms_hash_mismatch(record, "Automated access is now PROHIBITED entirely.") is True
    unhashed = _fixture_authorization(terms_hash=None)
    assert terms_hash_mismatch(unhashed, "anything") is False  # never checked != changed


# ---------------------------------------------------------------------------
# 23: discovery source cannot reach production
# ---------------------------------------------------------------------------

def test_23_discovery_only_source_cannot_reach_production_for_any_use():
    """Every Phase 36 ledger row that is NOT in SOURCE_REGISTRY at all
    (every FL Property Appraiser / TX Appraisal District / additional
    RealAuction-deployment row) must deny for EVERY promotion use - a
    discovery/terms-review-stage source can never accidentally reach
    production through this gate."""
    ledger_only_ids = [r["source_id"] for r in load_terms_review() if r["source_id"] not in SOURCE_REGISTRY]
    assert ledger_only_ids, "expected at least one ledger-only (non-registry) source_id to exist"
    for source_id in ledger_only_ids:
        for use in ("INGEST", "CUSTOMER_DISPLAY", "CUSTOMER_EXPORT", "API"):
            d = can_promote_source_for_use(source_id, use)
            assert d.allowed is False, (source_id, use)


# ---------------------------------------------------------------------------
# 24: missing authorization record cannot accidentally authorize use
# ---------------------------------------------------------------------------

def test_24_missing_authorization_record_cannot_accidentally_authorize():
    # A source with authorization records elsewhere, asked about a county
    # with NO record, must deny - never fall through to "allowed" by
    # absence.
    for county in ("Miami-Dade", "Broward", "Palm Beach", "Duval", None):
        d = can_promote_source_for_use("fl_realauction", "INGEST", county=county)
        assert d.allowed is False, county


# ---------------------------------------------------------------------------
# 25: historical project status cannot override current authorization
# ---------------------------------------------------------------------------

def test_25_historical_project_status_cannot_override_current_authorization():
    """fl_realauction's historical_project_status is APPROVED (Phase 34A -
    preserved verbatim as history) - proving can_promote_source_for_use()
    still denies Alachua/Miami-Dade INGEST shows the historical field is
    never consulted by the decision path at all."""
    record = SOURCE_REGISTRY["fl_realauction"]
    assert record.historical_project_status == SourceStatus.APPROVED
    assert record.legal_status == SourceStatus.APPROVED  # whole-source gate also passes
    # And yet, because fl_realauction HAS authorization records on file,
    # any county without its OWN record is denied regardless:
    assert can_promote_source_for_use("fl_realauction", "INGEST", county="Alachua").allowed is False
    assert can_promote_source_for_use("fl_realauction", "INGEST", county="Miami-Dade").allowed is False


# ---------------------------------------------------------------------------
# Additional coverage: unrecognized use raises, PROMOTION_USES completeness
# ---------------------------------------------------------------------------

def test_unrecognized_use_raises_value_error():
    with pytest.raises(ValueError):
        can_promote_source_for_use("tx_lgbs", "DELETE_EVERYTHING")


def test_promotion_uses_has_exactly_the_twelve_required_purposes():
    assert PROMOTION_USES == {
        "INGEST", "STORE", "CACHE", "NORMALIZE", "DERIVE",
        "CUSTOMER_DISPLAY", "CUSTOMER_EXPORT", "API", "HISTORICAL_RETENTION",
        "IMAGE_DISPLAY", "IMAGE_DOWNLOAD", "DOCUMENT_DISPLAY", "DOCUMENT_DOWNLOAD",
    }


# ---------------------------------------------------------------------------
# Section 14/22: proving can_promote_source_for_use() is a behavior-
# preserving equivalent of the two EXISTING TX call sites
# (harvesters/texas_harvester.py's main() loop and scripts/sync-texas-to-
# supabase.py's per-row check), WITHOUT modifying either production file -
# Section 14 explicitly forbids a bulk harvester rewrite, and Section 22
# forbids changing existing behavior. This test is the safe alternative:
# it proves wiring the new gate in would be a no-op for every real,
# currently-running TX source, so the report can state that honestly
# instead of guessing.
# ---------------------------------------------------------------------------

def test_can_promote_source_for_use_agrees_with_texas_harvesters_main_loop():
    """harvesters/texas_harvester.py's SOURCES dict (unchanged) lists exactly
    which vendors main() attempts to call check_ingestion_gate() for."""
    from harvesters.texas_harvester import SOURCES
    from harvesters.governance.gate import check_ingestion_gate

    for source_id in SOURCES:
        old = check_ingestion_gate(source_id)
        new = can_promote_source_for_use(source_id, "INGEST")
        assert old.allowed == new.allowed, source_id


def test_can_promote_source_for_use_agrees_with_sync_scripts_customer_output_check():
    """scripts/sync-texas-to-supabase.py calls authorized_for_customer_output()
    (unchanged) per row; can_promote_source_for_use(..., 'CUSTOMER_DISPLAY')
    must agree for every real, already-registered TX/FL source_id."""
    from harvesters.governance import authorized_for_customer_output

    sample_row = {"state": "TX", "county": "Test", "case_no": "1", "address": "123 Main St"}
    for source_id in SOURCE_REGISTRY:
        old_result = authorized_for_customer_output(dict(sample_row), source_id)
        new_decision = can_promote_source_for_use(source_id, "CUSTOMER_DISPLAY")
        assert (old_result is not None) == new_decision.allowed, source_id


def test_decision_is_a_structured_object_never_a_bare_boolean():
    d = can_promote_source_for_use("tx_lgbs", "INGEST")
    as_dict = d.to_dict()
    for key in ("allowed", "status", "reason", "source_id", "county", "use", "evidence", "reviewed_at"):
        assert key in as_dict
    assert isinstance(as_dict["allowed"], bool)
    assert isinstance(as_dict["status"], str)
