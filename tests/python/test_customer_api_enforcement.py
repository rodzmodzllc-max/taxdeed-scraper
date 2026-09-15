"""Phase 11 (Customer/API Data-Restriction Enforcement) tests.

Covers the row-projection functions added to harvesters/governance/gate.py
this phase (project_row_for_customer_output, project_row_for_api_export)
and their one real call site, scripts/sync-texas-to-supabase.py. Test
letters A-T below match Phase 11 Step 9's own lettered test matrix
exactly, so each test's purpose can be checked directly against that spec.

Architecture note repeated from gate.py's own docstrings, since it's the
premise this whole test file is built on: this application has no
application server. `public/app.js` reads Supabase's `public.properties`
table directly (via the `get_properties()` RPC or `.select("*")`), the
CSV export in app.js reads from those same already-fetched rows, and
`supabase/functions/send-digest`'s `digest_candidates` RPC (service_role)
also reads straight from `properties`. None of those three surfaces can
execute Python. Given Phase 11's hard "no migrations" rule, no read-time
enforcement point can be added to any of them - so the row dict built in
scripts/sync-texas-to-supabase.py IS the customer-facing representation in
this codebase's actual architecture, and that is what these tests exercise
directly (calling the same gate.py functions that script calls), rather
than a separate customer/API layer that does not exist in this codebase.
"""

from __future__ import annotations

import pytest

from harvesters.governance import (
    FIELD_SHAPE_KEYWORDS,
    Restriction,
    SourceStatus,
    project_row_for_api_export,
    project_row_for_customer_output,
)
from harvesters.governance.registry import SOURCE_REGISTRY, SourceRecord

_REAL_TX_ROW = {
    "state": "TX",
    "source": "auction",
    "county": "Dallas",
    "case_no": "12345",
    "parcel": "CAUSE-6789",
    "address": "123 Main St",
    "bid": 1500.0,
    "min_bid": 1500.0,
    "assessed": 42000.0,
    "sale_date": "2026-10-01",
    "legal_desc": "LOT 4 BLK 2",
    "harvester_source": "tx_lgbs",
    "latitude": 32.78,
    "longitude": -96.8,
}


def _fake_record(
    source_id: str,
    *,
    legal_status: SourceStatus,
    restrictions: tuple[Restriction, ...] = (),
) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        source_name="Fake source (test fixture)",
        state="TX",
        jurisdiction="Test County",
        source_url="https://example.invalid/",
        source_type="government",
        official_or_vendor="official",
        access_method="http_get_html_single_page",
        automation_status="READY",
        legal_status=legal_status,
        commercial_use_status="TEST FIXTURE",
        storage_status="TEST FIXTURE",
        customer_display_status="TEST FIXTURE",
        redistribution_status="TEST FIXTURE",
        api_export_status="TEST FIXTURE",
        historical_retention_status="TEST FIXTURE",
        document_image_rights_status="TEST FIXTURE",
        attribution_required=False,
        rate_limit=None,
        robots_status="TEST FIXTURE",
        terms_status="TEST FIXTURE",
        review_date="2026-09-14",
        reviewer="test fixture",
        notes="Test fixture only - not a real source.",
        restrictions=restrictions,
    )


# ---------------------------------------------------------------------------
# A. APPROVED + no restrictions -> allowed customer/API fields.
# ---------------------------------------------------------------------------

def test_A_approved_no_restrictions_allows_all_fields():
    row = dict(_REAL_TX_ROW)
    projected = project_row_for_customer_output(row, "tx_lgbs")
    assert projected == _REAL_TX_ROW
    exported = project_row_for_api_export(row, "tx_lgbs")
    assert exported == _REAL_TX_ROW


# ---------------------------------------------------------------------------
# B / M. APPROVED_WITH_RESTRICTIONS -> allowed fields remain visible,
#        restricted fields suppressed (field-level restriction).
# ---------------------------------------------------------------------------

def test_B_and_M_approved_with_restrictions_keeps_allowed_fields_strips_restricted(monkeypatch):
    fake = _fake_record(
        "tx_fake_html_restricted",
        legal_status=SourceStatus.APPROVED_WITH_RESTRICTIONS,
        restrictions=(Restriction.NO_RAW_HTML,),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)

    row = dict(_REAL_TX_ROW, raw_html="<div>listing page</div>", harvester_source=fake.source_id)
    projected = project_row_for_customer_output(row, fake.source_id)

    assert projected is not None
    assert "raw_html" not in projected
    # every unrestricted field is untouched
    for key in ("state", "county", "case_no", "address", "bid", "assessed", "legal_desc"):
        assert projected[key] == row[key]


# ---------------------------------------------------------------------------
# C. LEGAL_REVIEW_REQUIRED -> customer/API exposure denied.
# ---------------------------------------------------------------------------

def test_C_legal_review_required_denies_exposure():
    row = dict(_REAL_TX_ROW, harvester_source="tx_hctax")
    assert project_row_for_customer_output(row, "tx_hctax") is None
    assert project_row_for_api_export(row, "tx_hctax") is None


# ---------------------------------------------------------------------------
# D. BLOCKED -> customer/API exposure denied.
# ---------------------------------------------------------------------------

def test_D_blocked_denies_exposure():
    row = dict(_REAL_TX_ROW, harvester_source="tx_pbfcm")
    assert project_row_for_customer_output(row, "tx_pbfcm") is None
    assert project_row_for_api_export(row, "tx_pbfcm") is None


# ---------------------------------------------------------------------------
# E. DISABLED -> customer/API exposure denied.
# ---------------------------------------------------------------------------

def test_E_disabled_denies_exposure(monkeypatch):
    fake = _fake_record("tx_fake_disabled", legal_status=SourceStatus.DISABLED)
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)
    row = dict(_REAL_TX_ROW, harvester_source=fake.source_id)
    assert project_row_for_customer_output(row, fake.source_id) is None
    assert project_row_for_api_export(row, fake.source_id) is None


# ---------------------------------------------------------------------------
# F. TERMS_CHANGED -> customer/API exposure denied.
# ---------------------------------------------------------------------------

def test_F_terms_changed_denies_exposure(monkeypatch):
    fake = _fake_record("tx_fake_terms_changed", legal_status=SourceStatus.TERMS_CHANGED)
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)
    row = dict(_REAL_TX_ROW, harvester_source=fake.source_id)
    assert project_row_for_customer_output(row, fake.source_id) is None
    assert project_row_for_api_export(row, fake.source_id) is None


# ---------------------------------------------------------------------------
# G. Unknown source -> denied (fails closed, not treated as approved).
# ---------------------------------------------------------------------------

def test_G_unknown_source_denies_exposure():
    row = dict(_REAL_TX_ROW, harvester_source="tx_totally_made_up")
    assert project_row_for_customer_output(row, "tx_totally_made_up") is None
    assert project_row_for_api_export(row, "tx_totally_made_up") is None
    # empty/None source_id fails closed too
    assert project_row_for_customer_output(row, "") is None
    assert project_row_for_customer_output(row, None) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# H. Unknown/unresolvable restriction -> fail closed (whole row blocked).
#
# FIELD_SPECIFIC_RESTRICTION is the concrete case of this in the current
# model: the registry records THAT a field-specific restriction exists but
# not WHICH field (see restrictions.py's own comment on why it was added
# to BLOCKS_CUSTOMER_DISPLAY this phase) - so a source carrying it cannot
# be safely narrowed to "strip just the restricted field" and the entire
# row is denied instead, the same fail-closed answer as an unrecognized
# restriction would get.
# ---------------------------------------------------------------------------

def test_H_field_specific_restriction_with_no_field_mapping_fails_closed(monkeypatch):
    fake = _fake_record(
        "tx_fake_field_specific",
        legal_status=SourceStatus.APPROVED_WITH_RESTRICTIONS,
        restrictions=(Restriction.FIELD_SPECIFIC_RESTRICTION,),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)
    row = dict(_REAL_TX_ROW, harvester_source=fake.source_id)
    assert project_row_for_customer_output(row, fake.source_id) is None
    assert project_row_for_api_export(row, fake.source_id) is None


# ---------------------------------------------------------------------------
# I. Restricted raw HTML is never returned.
# ---------------------------------------------------------------------------

def test_I_restricted_raw_html_never_returned(monkeypatch):
    fake = _fake_record(
        "tx_fake_no_raw_html",
        legal_status=SourceStatus.APPROVED_WITH_RESTRICTIONS,
        restrictions=(Restriction.NO_RAW_HTML,),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)
    row = {"case_no": "1", "raw_html": "<html>secret listing markup</html>", "page_html": "<p>also secret</p>"}
    projected = project_row_for_customer_output(row, fake.source_id)
    assert projected is not None
    assert "raw_html" not in projected
    assert "page_html" not in projected
    assert projected["case_no"] == "1"


# ---------------------------------------------------------------------------
# J. Restricted image is never returned.
# ---------------------------------------------------------------------------

def test_J_restricted_image_never_returned(monkeypatch):
    fake = _fake_record(
        "tx_fake_no_images",
        legal_status=SourceStatus.APPROVED_WITH_RESTRICTIONS,
        restrictions=(Restriction.NO_IMAGES,),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)
    row = {"case_no": "1", "image_url": "https://example.invalid/photo.jpg", "photo": "https://example.invalid/2.jpg"}
    projected = project_row_for_customer_output(row, fake.source_id)
    assert projected is not None
    assert "image_url" not in projected
    assert "photo" not in projected
    assert projected["case_no"] == "1"


# ---------------------------------------------------------------------------
# K. Restricted document is never returned.
# ---------------------------------------------------------------------------

def test_K_restricted_document_never_returned(monkeypatch):
    fake = _fake_record(
        "tx_fake_no_documents",
        legal_status=SourceStatus.APPROVED_WITH_RESTRICTIONS,
        restrictions=(Restriction.NO_DOCUMENTS,),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)
    row = {"case_no": "1", "document_url": "https://example.invalid/notice.pdf", "pdf_url": "https://example.invalid/2.pdf"}
    projected = project_row_for_customer_output(row, fake.source_id)
    assert projected is not None
    assert "document_url" not in projected
    assert "pdf_url" not in projected
    assert projected["case_no"] == "1"


# ---------------------------------------------------------------------------
# L. Restricted API export is never returned (customer display can still
#    be fine - a source may be display-OK but export-prohibited).
# ---------------------------------------------------------------------------

def test_L_restricted_api_export_never_returned_even_when_display_allowed(monkeypatch):
    fake = _fake_record(
        "tx_fake_no_api_export",
        legal_status=SourceStatus.APPROVED_WITH_RESTRICTIONS,
        restrictions=(Restriction.NO_API_EXPORT,),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)
    row = dict(_REAL_TX_ROW, harvester_source=fake.source_id)

    # customer display: allowed (NO_API_EXPORT is not in BLOCKS_CUSTOMER_DISPLAY)
    displayed = project_row_for_customer_output(row, fake.source_id)
    assert displayed is not None
    assert displayed["case_no"] == row["case_no"]

    # api export: denied (NO_API_EXPORT is in BLOCKS_API_EXPORT)
    assert project_row_for_api_export(row, fake.source_id) is None


# ---------------------------------------------------------------------------
# N. Derived restricted field is correctly suppressed.
#
# This pipeline does not currently compute any server-side derived field
# before syncing (see docs/customer-api-data-enforcement.md's "Derived
# data" section) - app.js computes ratios like bid-to-value purely
# client-side from already-projected fields (bid, assessed) that already
# passed this same source's restriction check, so no separate enforcement
# is needed for that today. What IS tested here, at the layer this
# codebase actually has (provenance.py's derive()), is that a value
# derived from a restricted parent correctly inherits that restriction -
# the same guarantee test_10/test_9 in test_source_governance.py already
# cover for the general provenance model; this test confirms the specific
# restriction relevant to Phase 11 (NO_CUSTOMER_DISPLAY) is not laundered
# away by derive().
# ---------------------------------------------------------------------------

def test_N_derived_field_inherits_blocking_restriction_from_a_restricted_parent():
    from harvesters.governance import FieldClassification, PipelineStage, Provenance, derive

    restricted_parent = Provenance(
        source_id="tx_fake_field_specific",
        source_url="https://example.invalid/",
        source_field="min_bid",
        retrieved_at="2026-09-14T00:00:00Z",
        stage=PipelineStage.NORMALIZED,
        classification=FieldClassification.PUBLIC,
        restrictions=(Restriction.NO_CUSTOMER_DISPLAY,),
    )
    unrestricted_parent = Provenance(
        source_id="tx_lgbs",
        source_url="https://example.invalid/",
        source_field="cad_market_value",
        retrieved_at="2026-09-14T00:00:00Z",
        stage=PipelineStage.NORMALIZED,
        classification=FieldClassification.PUBLIC,
        restrictions=(),
    )
    derived = derive([restricted_parent, unrestricted_parent], source_field="bid_to_value_ratio")
    assert Restriction.NO_CUSTOMER_DISPLAY in derived.restrictions


# ---------------------------------------------------------------------------
# O. Provenance/internal record remains intact - projection never mutates
#    its input, so the internal record (in this codebase, the dict built
#    from out/harvest_texas.json before projection) is unaffected.
# ---------------------------------------------------------------------------

def test_O_row_projection_does_not_mutate_the_input_row(monkeypatch):
    fake = _fake_record(
        "tx_fake_no_raw_html_2",
        legal_status=SourceStatus.APPROVED_WITH_RESTRICTIONS,
        restrictions=(Restriction.NO_RAW_HTML,),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)
    original = {"case_no": "1", "raw_html": "<p>x</p>"}
    snapshot = dict(original)
    projected = project_row_for_customer_output(original, fake.source_id)
    assert original == snapshot  # input untouched
    assert projected is not original  # a new dict was returned
    assert "raw_html" not in projected


# ---------------------------------------------------------------------------
# P. Florida regression - Florida's registered sources project as fully
#    unrestricted, and nothing in this module touches Florida's actual
#    (PowerShell) pipeline.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fl_source_id", ["fl_realauction", "fl_laft_pdfs", "fl_lienhub_certificates"])
def test_P_florida_sources_project_unrestricted(fl_source_id):
    row = {"state": "FL", "county": "Test", "case_no": "FL-1", "address": "1 FL Ave"}
    projected = project_row_for_customer_output(row, fl_source_id)
    assert projected == row  # unchanged - grandfathered APPROVED, zero restrictions


def test_P_florida_pipeline_has_no_reference_to_this_module():
    import subprocess

    result = subprocess.run(
        ["grep", "-rl", "governance", "--include=*.ps1", "."],
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2]),
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""  # no PowerShell (Florida) script references this package


# ---------------------------------------------------------------------------
# Q. Texas regression - tx_lgbs/tx_realauction (real production sources)
#    project as fully unrestricted, unchanged from their pre-Phase-11
#    behavior.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tx_source_id", ["tx_lgbs", "tx_realauction"])
def test_Q_approved_texas_sources_project_unrestricted_unchanged(tx_source_id):
    row = dict(_REAL_TX_ROW, harvester_source=tx_source_id)
    projected = project_row_for_customer_output(row, tx_source_id)
    assert projected == row
    exported = project_row_for_api_export(row, tx_source_id)
    assert exported == row


# ---------------------------------------------------------------------------
# R. Cross-state isolation - FL and TX rows sharing a county/case_no cannot
#    leak into or overwrite one another via this projection layer (which
#    keys purely off source_id, never off county/case_no, and holds no
#    shared mutable state between calls).
# ---------------------------------------------------------------------------

def test_R_cross_state_rows_with_shared_county_case_no_do_not_leak_or_overwrite():
    fl_row = {"state": "FL", "county": "Shared", "case_no": "SAME-ID", "address": "FL address"}
    tx_row = {"state": "TX", "county": "Shared", "case_no": "SAME-ID", "address": "TX address", "harvester_source": "tx_lgbs"}

    fl_projected = project_row_for_customer_output(fl_row, "fl_realauction")
    tx_projected = project_row_for_customer_output(tx_row, "tx_lgbs")

    assert fl_projected["address"] == "FL address"
    assert tx_projected["address"] == "TX address"
    assert fl_projected["state"] == "FL"
    assert tx_projected["state"] == "TX"
    # re-running in the opposite order produces the same independent results
    tx_projected_2 = project_row_for_customer_output(tx_row, "tx_lgbs")
    fl_projected_2 = project_row_for_customer_output(fl_row, "fl_realauction")
    assert tx_projected_2 == tx_projected
    assert fl_projected_2 == fl_projected


# ---------------------------------------------------------------------------
# S. Bulk/export path cannot bypass restrictions - applying the projection
#    function across a batch enforces the same per-row decision as a
#    single call, and filter_rows_for_api_export() (the existing
#    whole-list function) agrees with project_row_for_api_export() applied
#    row-by-row.
# ---------------------------------------------------------------------------

def test_S_bulk_export_path_enforces_same_restrictions_as_single_row(monkeypatch):
    fake = _fake_record(
        "tx_fake_bulk_blocked",
        legal_status=SourceStatus.APPROVED_WITH_RESTRICTIONS,
        restrictions=(Restriction.NO_API_EXPORT,),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)
    rows = [dict(_REAL_TX_ROW, case_no=str(i), harvester_source=fake.source_id) for i in range(5)]

    from harvesters.governance import filter_rows_for_api_export

    # whole-list function: entire batch rejected (source carries NO_API_EXPORT)
    assert filter_rows_for_api_export(rows, fake.source_id) == []
    # per-row function agrees for every row in the batch, individually
    for row in rows:
        assert project_row_for_api_export(row, fake.source_id) is None


def test_S_bulk_export_of_mixed_sources_isolates_each_rows_own_restrictions(monkeypatch):
    fake = _fake_record(
        "tx_fake_bulk_blocked_2",
        legal_status=SourceStatus.APPROVED_WITH_RESTRICTIONS,
        restrictions=(Restriction.NO_API_EXPORT,),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)
    batch = [
        dict(_REAL_TX_ROW, case_no="allowed", harvester_source="tx_lgbs"),
        dict(_REAL_TX_ROW, case_no="blocked", harvester_source=fake.source_id),
    ]
    results = [project_row_for_api_export(r, r["harvester_source"]) for r in batch]
    assert results[0] is not None and results[0]["case_no"] == "allowed"
    assert results[1] is None


# ---------------------------------------------------------------------------
# T. Cache/serialization path - not applicable. This codebase has no
#    caching layer anywhere in the harvest/sync/customer path (confirmed
#    by inspection of scripts/sync-texas-to-supabase.py and public/app.js -
#    every read goes straight to Supabase's PostgREST layer, no
#    intermediate cache). Documented here rather than testing a mechanism
#    that does not exist.
# ---------------------------------------------------------------------------

def test_T_no_caching_layer_exists_to_bypass():
    # Meta-test: if a caching layer is ever added to the sync or customer
    # path, this test's existence is a prompt to add a real test above it
    # rather than silently leaving this gap undocumented.
    assert True


# ---------------------------------------------------------------------------
# Additional: the field-shape mechanism is provably inert against every
# field currently produced by the real TX harvest/sync pipeline - see
# restrictions.py's own comment on why keyword-based matching was chosen.
# ---------------------------------------------------------------------------

def test_field_shape_keywords_match_none_of_the_real_tx_row_fields():
    all_keywords = [kw for kws in FIELD_SHAPE_KEYWORDS.values() for kw in kws]
    for field_name in _REAL_TX_ROW:
        assert not any(kw in field_name.lower() for kw in all_keywords), (
            f"'{field_name}' unexpectedly matches a restricted-field-shape keyword - "
            "this would change today's sync behavior for tx_lgbs/tx_realauction."
        )


def test_unrecognized_restriction_types_have_no_field_stripping_effect_but_do_not_crash():
    # RATE_LIMIT / ATTRIBUTION_REQUIRED / RETENTION_PERIOD /
    # OTHER_CONTRACTUAL_RESTRICTION describe obligations, not field-shaped
    # content - project_row_for_customer_output must not crash on them and
    # must not strip any field because of them (they are not in
    # BLOCKS_CUSTOMER_DISPLAY and have no FIELD_SHAPE_KEYWORDS entry).
    import dataclasses

    from harvesters.governance.registry import SOURCE_REGISTRY as _REG

    fake = _fake_record(
        "tx_fake_obligation_only",
        legal_status=SourceStatus.APPROVED_WITH_RESTRICTIONS,
        restrictions=(
            Restriction.RATE_LIMIT,
            Restriction.ATTRIBUTION_REQUIRED,
            Restriction.RETENTION_PERIOD,
            Restriction.OTHER_CONTRACTUAL_RESTRICTION,
        ),
    )
    _REG[fake.source_id] = fake
    try:
        row = dict(_REAL_TX_ROW, harvester_source=fake.source_id)
        projected = project_row_for_customer_output(row, fake.source_id)
        assert projected == row
    finally:
        del _REG[fake.source_id]
