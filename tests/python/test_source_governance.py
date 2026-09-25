"""Focused tests for the Phase 10A source-governance layer
(harvesters/governance/). Uses pytest, the only Python test framework
installed in this environment - this repo had no pre-existing Python test
suite to match conventions against (its one existing test,
tests/run_test.mjs, is a Playwright/Node end-to-end test for the frontend,
a different language and a different layer entirely - see that file's own
header comment). Run with:

    pytest tests/python/

These tests are NOT wired into any GitHub Actions workflow as of Phase
10A - see docs/data-provenance.md's "Remaining risks" section for that
honestly-flagged gap. Run locally before trusting a change to
harvesters/governance/ or its two call sites
(harvesters/texas_harvester.py, scripts/sync-texas-to-supabase.py).

Test numbering below matches Phase 10A Step 12's own numbered list (1-14)
so each test's purpose can be checked directly against that spec, plus a
few additional tests this suite's author judged necessary for the
fail-closed guarantee Step 14 requires.
"""

from __future__ import annotations

import importlib

import pytest

from harvesters.governance import (
    FieldClassification,
    PipelineStage,
    Restriction,
    SourceStatus,
    advance,
    check_ingestion_gate,
    derive,
    filter_rows_for_api_export,
    filter_rows_for_customer_output,
    origin_source_ids,
)
from harvesters.governance.provenance import Provenance
from harvesters.governance.registry import SOURCE_REGISTRY, SourceRecord


def _prov(source_id: str, *, stage=PipelineStage.RAW, restrictions=(), retrieved_at="2026-09-14T00:00:00Z"):
    return Provenance(
        source_id=source_id,
        source_url=f"https://example.invalid/{source_id}",
        source_field="min_bid",
        retrieved_at=retrieved_at,
        stage=stage,
        classification=FieldClassification.PUBLIC,
        restrictions=tuple(restrictions),
    )


# ---------------------------------------------------------------------------
# 1. APPROVED source passes the ingestion gate.
# ---------------------------------------------------------------------------

def test_1_approved_source_passes_gate():
    decision = check_ingestion_gate("tx_lgbs")
    assert decision.allowed is True
    assert decision.status == SourceStatus.APPROVED


# ---------------------------------------------------------------------------
# 2. APPROVED_WITH_RESTRICTIONS source passes ingestion but restrictions
#    remain attached.
# ---------------------------------------------------------------------------

def test_2_approved_with_restrictions_passes_and_keeps_restrictions(monkeypatch):
    fake = SourceRecord(
        source_id="tx_fake_restricted",
        source_name="Fake restricted source (test fixture)",
        state="TX",
        jurisdiction="Test County",
        source_url="https://example.invalid/",
        source_type="government",
        official_or_vendor="official",
        access_method="http_get_html_single_page",
        automation_status="READY",
        legal_status=SourceStatus.APPROVED_WITH_RESTRICTIONS,
        commercial_use_status="PERMITTED WITH CONDITIONS",
        storage_status="PERMITTED",
        customer_display_status="PERMITTED WITH ATTRIBUTION",
        redistribution_status="NOT PERMITTED",
        api_export_status="NOT PERMITTED",
        historical_retention_status="PERMITTED",
        document_image_rights_status="NOT APPLICABLE",
        attribution_required=True,
        rate_limit="1/day",
        robots_status="ALLOW",
        terms_status="REVIEWED",
        review_date="2026-09-14",
        reviewer="test fixture",
        notes="Test fixture only - not a real source.",
        restrictions=(Restriction.ATTRIBUTION_REQUIRED, Restriction.NO_API_EXPORT),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)

    decision = check_ingestion_gate("tx_fake_restricted")
    assert decision.allowed is True
    assert decision.status == SourceStatus.APPROVED_WITH_RESTRICTIONS
    assert Restriction.ATTRIBUTION_REQUIRED in decision.restrictions
    assert Restriction.NO_API_EXPORT in decision.restrictions


# ---------------------------------------------------------------------------
# 3-6. LEGAL_REVIEW_REQUIRED / BLOCKED / DISABLED / TERMS_CHANGED are all
#      rejected.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "status",
    [
        SourceStatus.LEGAL_REVIEW_REQUIRED,
        SourceStatus.BLOCKED,
        SourceStatus.DISABLED,
        SourceStatus.TERMS_CHANGED,
    ],
)
def test_3_to_6_non_approved_statuses_are_rejected(monkeypatch, status):
    fake = SourceRecord(
        source_id=f"tx_fake_{status.value.lower()}",
        source_name="Fake source (test fixture)",
        state="TX",
        jurisdiction="Test County",
        source_url="https://example.invalid/",
        source_type="government",
        official_or_vendor="official",
        access_method="http_get_html_single_page",
        automation_status="READY",
        legal_status=status,
        commercial_use_status="N/A",
        storage_status="N/A",
        customer_display_status="N/A",
        redistribution_status="N/A",
        api_export_status="N/A",
        historical_retention_status="N/A",
        document_image_rights_status="N/A",
        attribution_required=False,
        rate_limit=None,
        robots_status="N/A",
        terms_status="N/A",
        review_date="2026-09-14",
        reviewer="test fixture",
        notes="Test fixture only.",
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)

    decision = check_ingestion_gate(fake.source_id)
    assert decision.allowed is False
    assert decision.status == status


def test_3_real_pbfcm_is_blocked_and_rejected():
    decision = check_ingestion_gate("tx_pbfcm")
    assert decision.status == SourceStatus.BLOCKED
    assert decision.allowed is False


def test_govease_mvba_ctsa_all_blocked_and_rejected():
    for source_id in ("tx_govease", "tx_mvba", "tx_ctsa"):
        decision = check_ingestion_gate(source_id)
        assert decision.status == SourceStatus.BLOCKED, source_id
        assert decision.allowed is False, source_id


# ---------------------------------------------------------------------------
# 7. A restricted source field cannot become unrestricted downstream.
# ---------------------------------------------------------------------------

def test_7_restriction_cannot_be_dropped_downstream():
    raw = _prov("tx_pbfcm", stage=PipelineStage.RAW, restrictions=(Restriction.NO_REDISTRIBUTION,))
    normalized = advance(raw, stage=PipelineStage.NORMALIZED)
    enriched = advance(normalized, stage=PipelineStage.ENRICHED)
    customer = advance(enriched, stage=PipelineStage.CUSTOMER)

    assert Restriction.NO_REDISTRIBUTION in normalized.restrictions
    assert Restriction.NO_REDISTRIBUTION in enriched.restrictions
    assert Restriction.NO_REDISTRIBUTION in customer.restrictions

    # advance() has no parameter that can REMOVE a restriction - only
    # additional_restrictions, which only adds. This is a structural
    # guarantee, not just a convention this test happens to exercise.
    import inspect

    sig = inspect.signature(advance)
    assert "remove_restrictions" not in sig.parameters
    assert "restrictions" not in sig.parameters  # can't be passed a fresh/overriding set


# ---------------------------------------------------------------------------
# 8. Provenance survives normalization.
# ---------------------------------------------------------------------------

def test_8_provenance_survives_normalization():
    raw = _prov("tx_lgbs", stage=PipelineStage.RAW)
    normalized = advance(raw, stage=PipelineStage.NORMALIZED, classification=FieldClassification.PUBLIC)

    assert normalized.source_id == raw.source_id
    assert normalized.source_url == raw.source_url
    assert normalized.retrieved_at == raw.retrieved_at
    assert normalized.stage == PipelineStage.NORMALIZED


# ---------------------------------------------------------------------------
# 9. Provenance survives enrichment.
# ---------------------------------------------------------------------------

def test_9_provenance_survives_enrichment():
    raw = _prov("tx_lgbs", stage=PipelineStage.RAW)
    normalized = advance(raw, stage=PipelineStage.NORMALIZED)
    enriched = advance(normalized, stage=PipelineStage.ENRICHED, additional_restrictions=(Restriction.RATE_LIMIT,))

    assert enriched.source_id == raw.source_id
    assert enriched.stage == PipelineStage.ENRICHED
    assert Restriction.RATE_LIMIT in enriched.restrictions


def test_advance_rejects_moving_backward():
    enriched = _prov("tx_lgbs", stage=PipelineStage.ENRICHED)
    with pytest.raises(ValueError):
        advance(enriched, stage=PipelineStage.RAW)


# ---------------------------------------------------------------------------
# 10. Derived fields retain lineage to their originating source(s).
# ---------------------------------------------------------------------------

def test_10_derived_field_retains_lineage_to_multiple_sources():
    min_bid_prov = _prov("tx_lgbs", restrictions=(Restriction.RATE_LIMIT,))
    market_value_prov = _prov("tx_hctax", restrictions=())  # a different source entirely

    ratio_prov = derive([min_bid_prov, market_value_prov], source_field="bid_to_value_ratio")

    assert ratio_prov.stage == PipelineStage.DERIVED
    assert ratio_prov.is_source_provided is False
    assert origin_source_ids(ratio_prov) == frozenset({"tx_lgbs", "tx_hctax"})
    # the restriction from ONE parent still applies to the derived value -
    # deriving a metric from restricted data does not launder the
    # restriction away.
    assert Restriction.RATE_LIMIT in ratio_prov.restrictions


def test_derive_of_a_derive_still_traces_to_original_sources():
    a = _prov("tx_lgbs")
    b = _prov("tx_realauction")
    intermediate = derive([a, b], source_field="combined_value")
    c = _prov("tx_hctax")
    final = derive([intermediate, c], source_field="final_score")

    assert origin_source_ids(final) == frozenset({"tx_lgbs", "tx_realauction", "tx_hctax"})


# ---------------------------------------------------------------------------
# 11. Customer output respects source restrictions.
# ---------------------------------------------------------------------------

def test_11_customer_output_respects_no_customer_display_restriction(monkeypatch):
    fake = SourceRecord(
        source_id="tx_fake_no_customer_display",
        source_name="Fake source (test fixture)",
        state="TX",
        jurisdiction="Test County",
        source_url="https://example.invalid/",
        source_type="vendor_platform",
        official_or_vendor="vendor",
        access_method="html_scrape",
        automation_status="READY",
        legal_status=SourceStatus.APPROVED_WITH_RESTRICTIONS,
        commercial_use_status="INTERNAL ANALYTICS ONLY",
        storage_status="PERMITTED",
        customer_display_status="NOT PERMITTED",
        redistribution_status="NOT PERMITTED",
        api_export_status="NOT PERMITTED",
        historical_retention_status="PERMITTED",
        document_image_rights_status="N/A",
        attribution_required=False,
        rate_limit=None,
        robots_status="ALLOW",
        terms_status="REVIEWED",
        review_date="2026-09-14",
        reviewer="test fixture",
        notes="Test fixture only.",
        restrictions=(Restriction.NO_CUSTOMER_DISPLAY,),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)

    rows = [{"account_number": "1"}, {"account_number": "2"}]
    assert filter_rows_for_customer_output(rows, "tx_fake_no_customer_display") == []
    # same rows, an unrestricted approved source: nothing filtered out.
    assert filter_rows_for_customer_output(rows, "tx_lgbs") == rows


# ---------------------------------------------------------------------------
# 12. API/export output respects source restrictions.
# ---------------------------------------------------------------------------

def test_12_api_export_respects_no_api_export_restriction(monkeypatch):
    fake = SourceRecord(
        source_id="tx_fake_no_api_export",
        source_name="Fake source (test fixture)",
        state="TX",
        jurisdiction="Test County",
        source_url="https://example.invalid/",
        source_type="vendor_platform",
        official_or_vendor="vendor",
        access_method="html_scrape",
        automation_status="READY",
        legal_status=SourceStatus.APPROVED_WITH_RESTRICTIONS,
        commercial_use_status="DISPLAY OK, NO EXPORT",
        storage_status="PERMITTED",
        customer_display_status="PERMITTED",
        redistribution_status="PERMITTED IN-APP ONLY",
        api_export_status="NOT PERMITTED",
        historical_retention_status="PERMITTED",
        document_image_rights_status="N/A",
        attribution_required=False,
        rate_limit=None,
        robots_status="ALLOW",
        terms_status="REVIEWED",
        review_date="2026-09-14",
        reviewer="test fixture",
        notes="Test fixture only.",
        restrictions=(Restriction.NO_API_EXPORT,),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)

    rows = [{"account_number": "1"}]
    # customer display is fine (no_api_export doesn't block display)...
    assert filter_rows_for_customer_output(rows, "tx_fake_no_api_export") == rows
    # ...but export/API specifically is blocked.
    assert filter_rows_for_api_export(rows, "tx_fake_no_api_export") == []


def test_customer_and_api_output_both_empty_for_a_rejected_source():
    rows = [{"account_number": "1"}]
    assert filter_rows_for_customer_output(rows, "tx_hctax") == []
    assert filter_rows_for_api_export(rows, "tx_hctax") == []


# ---------------------------------------------------------------------------
# 13. Harris remains blocked from automated ingestion while
#     LEGAL_REVIEW_REQUIRED.
# ---------------------------------------------------------------------------

def test_13_harris_hctax_is_legal_review_required_and_rejected():
    record = SOURCE_REGISTRY["tx_hctax"]
    assert record.legal_status == SourceStatus.LEGAL_REVIEW_REQUIRED

    decision = check_ingestion_gate("tx_hctax")
    assert decision.allowed is False
    assert decision.status == SourceStatus.LEGAL_REVIEW_REQUIRED

    # No harvester exists for Harris at all - the gate has nothing to
    # protect in texas_harvester.py's SOURCES dict, which is itself part
    # of the guarantee (see harvesters/texas_harvester.py's SOURCES).
    from harvesters.texas_harvester import SOURCES

    assert "tx_hctax" not in SOURCES


def test_harris_status_was_not_upgraded_or_downgraded():
    # Guards against a future edit silently reclassifying Harris based on
    # "interpretation" rather than an actual resolution of the Section 6
    # rights questions in claude/harris-hctax-rights-resolution-package.md -
    # Phase 10A Step 10's explicit instruction.
    record = SOURCE_REGISTRY["tx_hctax"]
    assert record.legal_status not in (SourceStatus.APPROVED, SourceStatus.APPROVED_WITH_RESTRICTIONS)
    assert "claude/harris-hctax-rights-resolution-package.md" in record.doc_refs


# ---------------------------------------------------------------------------
# 14. Existing Florida/Texas behavior remains intact.
# ---------------------------------------------------------------------------

def test_14_lgbs_and_realauction_unchanged_and_approved():
    texas_harvester = importlib.import_module("harvesters.texas_harvester")

    # SOURCES dict still has exactly the same 4 keys, mapped to functions
    # of the same names, as before Phase 10A.
    assert set(texas_harvester.SOURCES.keys()) == {"tx_pbfcm", "tx_lgbs", "tx_realauction", "tx_govease"}
    assert texas_harvester.SOURCES["tx_lgbs"].__name__ == "harvest_lgbs"
    assert texas_harvester.SOURCES["tx_realauction"].__name__ == "harvest_realauction"
    assert texas_harvester.SOURCES["tx_pbfcm"].__name__ == "harvest_pbfcm"
    assert texas_harvester.SOURCES["tx_govease"].__name__ == "harvest_govease"

    # TexasSaleRow's field set is byte-for-byte unchanged by this phase -
    # a governance layer that had to modify the production dataclass to
    # exist would violate Phase 10A's own "do not change verified
    # LGBS/RealAuction behavior" rule.
    from dataclasses import fields

    field_names = {f.name for f in fields(texas_harvester.TexasSaleRow)}
    assert field_names == {
        "account_number",
        "county",
        "state",
        "auction_date",
        "min_bid",
        "cad_market_value",
        "legal_description",
        "address",
        "cause_number",
        "latitude",
        "longitude",
        "source",
        "harvester_source",
        # Phase 72 (auction-link provenance) added exactly these three, and
        # nothing else. Pinned here for the same reason as the rest of the
        # set: a change to the production row shape must be deliberate.
        "auction_url",
        "auction_url_kind",
        "sale_status",
    }

    # Both production sources are registered APPROVED (reflecting existing
    # production status, per Phase 10A's explicit instruction), so the
    # gate integrated into main() does not change their behavior.
    for source_id in ("tx_lgbs", "tx_realauction"):
        decision = check_ingestion_gate(source_id)
        assert decision.allowed is True, source_id
        assert decision.status == SourceStatus.APPROVED, source_id


def test_florida_sources_registered_for_state_agnostic_design_but_untouched():
    fl_ids = {r.source_id for r in SOURCE_REGISTRY.values() if r.state == "FL"}
    # Phase 33 added fl_dor_statewide (a real, formally-reviewed-this-phase
    # LEGAL_REVIEW_REQUIRED entry - see claude/phase-33-source-compliance-audit.md)
    # alongside the three Phase 10A grandfathered-APPROVED entries. It is
    # deliberately NOT in the "allowed" group below: unlike the grandfathered
    # three, it was never in production use, and this phase's own review
    # found no commercial/redistribution permission - LEGAL_REVIEW_REQUIRED
    # is the correct, conservative status, not APPROVED.
    assert fl_ids == {
        "fl_realauction",
        "fl_laft_pdfs",
        "fl_lienhub_certificates",
        "fl_dor_statewide",
    }
    grandfathered_approved_ids = {"fl_realauction", "fl_laft_pdfs", "fl_lienhub_certificates"}
    for source_id in grandfathered_approved_ids:
        decision = check_ingestion_gate(source_id)
        assert decision.allowed is True, source_id

    dor_decision = check_ingestion_gate("fl_dor_statewide")
    assert dor_decision.allowed is False
    assert dor_decision.status == SourceStatus.LEGAL_REVIEW_REQUIRED

    # None of Florida's actual harvesting is Python - it's all PowerShell
    # (see scripts/harvest_all_counties.ps1 etc.) and none of it imports
    # this governance package. This test can only assert that fact
    # structurally: no .ps1 file in scripts/ mentions "governance".
    import subprocess

    result = subprocess.run(
        ["grep", "-rl", "governance", "--include=*.ps1", "."],
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2] / "scripts"),
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "", "no PowerShell (Florida) script should reference the governance package"


# ---------------------------------------------------------------------------
# Additional fail-closed guarantees (Phase 10A Step 14).
# ---------------------------------------------------------------------------

def test_unknown_source_fails_closed():
    decision = check_ingestion_gate("this_source_id_does_not_exist")
    assert decision.allowed is False
    assert decision.status == SourceStatus.LEGAL_REVIEW_REQUIRED  # missing != approved


def test_empty_or_none_source_id_fails_closed():
    assert check_ingestion_gate(None).allowed is False
    assert check_ingestion_gate("").allowed is False


def test_every_registered_source_has_a_legal_status_that_is_a_real_enum_member():
    # Guards against a future entry accidentally setting legal_status to a
    # raw string or None instead of a SourceStatus member, which would
    # silently bypass the `in INGESTION_ALLOWED_STATUSES` check.
    for source_id, record in SOURCE_REGISTRY.items():
        assert isinstance(record.legal_status, SourceStatus), source_id


def test_blocked_vendors_are_all_representable_in_the_registry():
    for source_id in ("tx_pbfcm", "tx_mvba", "tx_ctsa", "tx_govease"):
        record = SOURCE_REGISTRY[source_id]
        assert record.legal_status == SourceStatus.BLOCKED
        assert record.doc_refs, f"{source_id} should cite the doc(s) its BLOCKED status came from"


# ---------------------------------------------------------------------------
# Phase 33 additions: fl_dor_statewide and tx_comptroller_directory.
# ---------------------------------------------------------------------------

def test_fl_dor_statewide_is_legal_review_required_and_rejected():
    # A free, official, statewide .gov data portal is still not APPROVED
    # without an actual finding of permission - "public and free" is not
    # itself a legal-status upgrade (Phase 33 Rule 9).
    decision = check_ingestion_gate("fl_dor_statewide")
    assert decision.status == SourceStatus.LEGAL_REVIEW_REQUIRED
    assert decision.allowed is False
    record = SOURCE_REGISTRY["fl_dor_statewide"]
    assert record.state == "FL"
    assert record.official_or_vendor == "official"


def test_tx_comptroller_directory_is_discovered_and_rejected():
    # DISCOVERED is the least-developed status - confirming the source
    # exists must not, by itself, advance it any further.
    decision = check_ingestion_gate("tx_comptroller_directory")
    assert decision.status == SourceStatus.DISCOVERED
    assert decision.allowed is False
    record = SOURCE_REGISTRY["tx_comptroller_directory"]
    assert record.state == "TX"
    assert record.official_or_vendor == "official"


def test_no_silent_fallback_from_an_approved_source_to_an_unapproved_one():
    # Phase 33 Section 44's "no silent fallback" rule, expressed as a
    # structural guarantee of this codebase rather than a scenario test:
    # there is no fallback-selection function anywhere in the governance
    # package (or its two call sites) that would pick a second source_id
    # if a first one's gate check failed - check_ingestion_gate() only
    # ever answers "is THIS one source_id allowed", never "which of these
    # sources should I use instead". If such a function is ever added, it
    # must independently gate-check whatever it falls back to; this test
    # documents that today there is nothing to bypass because there is no
    # fallback mechanism at all.
    import inspect

    from harvesters import governance

    fallback_named_things = [
        name
        for name in dir(governance)
        if "fallback" in name.lower() or "fallback" in (inspect.getdoc(getattr(governance, name)) or "").lower()
    ]
    assert fallback_named_things == [], (
        "a fallback-selection mechanism appeared in harvesters.governance without an "
        "accompanying test verifying it re-checks the gate for whatever it falls back to"
    )


def test_every_new_phase33_source_cites_the_phase33_report():
    for source_id in ("fl_dor_statewide", "tx_comptroller_directory"):
        record = SOURCE_REGISTRY[source_id]
        assert "claude/phase-33-source-compliance-audit.md" in record.doc_refs, source_id


# ---------------------------------------------------------------------------
# Phase 33.5 additions: the three grandfathered Florida production sources
# now carry a real rights-audit citation and annotated findings, but their
# legal_status and ingestion-gate behavior are unchanged - this phase's own
# rules forbid altering production approval unilaterally. These tests guard
# both halves of that guarantee at once.
# ---------------------------------------------------------------------------

def test_phase33_5_grandfathered_fl_sources_still_approved_and_unenforced_but_now_documented():
    for source_id in ("fl_realauction", "fl_laft_pdfs", "fl_lienhub_certificates"):
        record = SOURCE_REGISTRY[source_id]
        # legal_status/ingestion behavior: byte-for-byte unchanged by the audit.
        assert record.legal_status == SourceStatus.APPROVED, source_id
        decision = check_ingestion_gate(source_id)
        assert decision.allowed is True, source_id
        # documentation: the audit's own citation must now be present, and the
        # placeholder "Not formally reviewed." must be gone from every status
        # field this phase actually investigated (robots/terms at minimum).
        assert "claude/phase-33-5-florida-production-source-rights-audit.md" in record.doc_refs, source_id
        assert record.robots_status != "Not formally reviewed.", source_id
        assert record.terms_status != "Not formally reviewed.", source_id
        assert record.review_date == "2026-09-15", source_id


def test_phase33_5_realauction_and_lienhub_carry_their_distinct_new_findings():
    # Each of the two vendor-platform FL sources got a materially different
    # kind of new evidence this phase - assert each one's specific finding
    # actually landed in the registry, not just generic boilerplate text.
    realauction = SOURCE_REGISTRY["fl_realauction"]
    assert "ROBOTS_DISALLOWED" in realauction.robots_status
    assert "alachua.realtaxdeed.com" in realauction.robots_status

    lienhub = SOURCE_REGISTRY["fl_lienhub_certificates"]
    assert "WAF" in lienhub.commercial_use_status
    assert "403" in lienhub.commercial_use_status


def test_phase33_5_did_not_touch_texas_or_other_florida_records():
    # Narrow-annotation discipline: only the three named grandfathered FL
    # sources were edited this phase. Spot-check a TX record and the newest
    # Phase 33 FL record are untouched (still cite only their own phases).
    assert "claude/phase-33-5-florida-production-source-rights-audit.md" not in SOURCE_REGISTRY["tx_realauction"].doc_refs
    assert "claude/phase-33-5-florida-production-source-rights-audit.md" not in SOURCE_REGISTRY["fl_dor_statewide"].doc_refs
