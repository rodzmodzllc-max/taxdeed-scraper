"""Phase 22B (Customer/API Restriction-Enforcement Implementation) -
independent verification suite.

## Why this file exists despite Phase 11 already having done this work

Phase 22A's own readiness audit (based on the "tax florida app" claude.ai
Project's older Phase 11 *readiness-gate* doc, not on a fresh read of the
actual current source) scoped "Track F" as: wire
filter_rows_for_customer_output()/filter_rows_for_api_export() into the
customer/API boundary, which those older docs described as unbuilt.

Re-investigating from the actual current repository at the start of Phase
22B (harvesters/governance/gate.py, registry.py, restrictions.py,
scripts/sync-texas-to-supabase.py, docs/customer-api-data-enforcement.md,
tests/python/test_customer_api_enforcement.py - all read in full) found
that this work already shipped, correctly, as commit 320a83c ("Phase 11:
complete customer API data restriction enforcement"), already on
origin/main, already exercised by 26 passing tests. That earlier Phase 11
work independently reached the same architectural conclusion Phase 22B's
own instructions describe reaching if Python can't run client-side: it
can't (public/app.js is browser JS with no Python bridge; there is no
application server; public.properties has no field-level RLS), so the
smallest correct enforcement boundary is write-time row projection in
scripts/sync-texas-to-supabase.py - which is exactly what's there.

No production code changed for Phase 22B as a result - there is nothing to
"implement" that Phase 11 didn't already implement correctly. This file is
Phase 22B's own independent regression anchor: it re-derives the same
guarantees the task's "Tests" section lists, from fixtures/paths this
phase itself chose, using only synthetic data for the restricted-source
cases (no real source's legal_status or restrictions changes here or
anywhere in this phase - see SOURCE_REGISTRY untouched except via
monkeypatch, reverted after each test). It exists so a future change to
harvesters/governance/gate.py that weakens Phase 11's guarantees is caught
by two independent test suites, authored in two different phases for two
different stated reasons, not just one.

See the "tax florida app" claude.ai Project doc for this phase's full
readiness/implementation report, including the Florida-pipeline coverage
gap this file deliberately does NOT attempt to close (see
test_florida_pipeline_still_has_zero_governance_wiring below).
"""

from __future__ import annotations

from harvesters.governance import (
    FIELD_SHAPE_KEYWORDS,
    Restriction,
    SourceStatus,
    project_row_for_api_export,
    project_row_for_customer_output,
)
from harvesters.governance.registry import SOURCE_REGISTRY, SourceRecord

# The exact row shape scripts/sync-texas-to-supabase.py builds today (see
# that file's row-building loop) - not an invented schema.
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

_REAL_FL_ROW = {
    "state": "FL",
    "source": "auction",
    "county": "Alachua",
    "case_no": "26-CV-1234",
    "parcel": "07214-031-000",
    "address": "1832 SW 42ND AVE",
    "bid": 4800.0,
    "assessed": 210000.0,
    "sale_date": "2026-11-03",
    "legal_desc": "LOT 7 BLK 3",
}

# Every property-row field public/app.js's CSV export (exportCsvBtn click
# handler, the `cols` array) actually reads via a `p => p.<field>` accessor,
# transcribed directly from app.js as of this phase (Phase 22B) - a fixed
# allowlist of named columns, not a dynamic dump of whatever keys a row
# happens to carry. Kept here, distinct from _REAL_TX_ROW/_REAL_FL_ROW
# above, specifically so a change to this list is a deliberate, visible
# edit to this test file, not an accidental drift.
_APP_JS_CSV_ACCESSED_FIELDS = (
    "county", "source", "address", "parcel", "case_no", "owner_name", "status",
    "prop_type", "dor_use_code", "tx_category", "lien_level", "homestead", "bid",
    "assessed", "market", "value_year", "year_built", "living_area", "lot_sqft",
    "num_buildings", "land_value", "last_sale_price", "last_sale_year", "legal_desc",
    "sale_date", "certificate_no", "min_bid", "redemption_period_months",
    "redemption_expiration_date", "max_statutory_return_usd", "tax_year",
    "issued_date", "expiration_date", "interest_rate", "url_appraiser",
    "url_taxcoll", "url_auction", "url_title",
)


def _fake_restricted_source(
    source_id: str,
    *,
    legal_status: SourceStatus = SourceStatus.APPROVED_WITH_RESTRICTIONS,
    restrictions: tuple[Restriction, ...],
) -> SourceRecord:
    return SourceRecord(
        source_id=source_id,
        source_name="Phase 22B fixture source (not real)",
        state="TX",
        jurisdiction="Test County",
        source_url="https://example.invalid/",
        source_type="government",
        official_or_vendor="official",
        access_method="http_get_html_single_page",
        automation_status="READY",
        legal_status=legal_status,
        commercial_use_status="TEST FIXTURE - Phase 22B",
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
        review_date="2026-09-15",
        reviewer="Phase 22B test fixture - not a real review",
        notes="Synthetic fixture for Phase 22B regression coverage only - never a real source.",
        restrictions=restrictions,
    )


# ---------------------------------------------------------------------------
# 1. An approved unrestricted source continues to produce the exact
#    current output - both today's live TX sources and today's live FL
#    (grandfathered) sources, pinned as this phase's own baseline.
# ---------------------------------------------------------------------------

def test_approved_tx_sources_unchanged_output():
    for source_id in ("tx_lgbs", "tx_realauction"):
        row = dict(_REAL_TX_ROW, harvester_source=source_id)
        assert project_row_for_customer_output(row, source_id) == row
        assert project_row_for_api_export(row, source_id) == row


def test_approved_fl_sources_unchanged_output():
    for source_id in ("fl_realauction", "fl_laft_pdfs", "fl_lienhub_certificates"):
        row = dict(_REAL_FL_ROW)
        assert project_row_for_customer_output(row, source_id) == row
        assert project_row_for_api_export(row, source_id) == row


# ---------------------------------------------------------------------------
# 2. A hypothetical restricted source is filtered appropriately - both the
#    whole-row-blocking case and the field-stripping case, fixture-only.
# ---------------------------------------------------------------------------

def test_hypothetical_whole_row_blocking_restriction_is_filtered(monkeypatch):
    fake = _fake_restricted_source(
        "phase22_fake_source_only_display",
        restrictions=(Restriction.SOURCE_ONLY_DISPLAY,),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)
    row = dict(_REAL_TX_ROW, harvester_source=fake.source_id)
    assert project_row_for_customer_output(row, fake.source_id) is None
    assert project_row_for_api_export(row, fake.source_id) is None


def test_hypothetical_field_shaped_restriction_strips_only_that_field(monkeypatch):
    fake = _fake_restricted_source(
        "phase22_fake_source_no_images",
        restrictions=(Restriction.NO_IMAGES,),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)
    row = dict(_REAL_TX_ROW, harvester_source=fake.source_id, photo_url="https://example.invalid/x.jpg")
    projected = project_row_for_customer_output(row, fake.source_id)
    assert projected is not None
    assert "photo_url" not in projected
    for key in _REAL_TX_ROW:
        assert projected[key] == row[key]


# ---------------------------------------------------------------------------
# 3. Restricted fields cannot leak through CSV/export.
#
# Two independent guarantees, both checked: (a) the projection layer
# strips restricted-content-shaped fields before a row ever reaches
# public.properties (the table public/app.js's CSV export reads from -
# traced directly in app.js this phase: exportCsvBtn's handler reads only
# the in-memory `ALL` array populated once by fetchProperties()/loadAll(),
# never a second query); (b) even independent of (a), app.js's CSV export
# is a fixed named-column allowlist (see _APP_JS_CSV_ACCESSED_FIELDS
# above), not a dynamic dump of every key a row carries - so a
# restricted-shaped field surviving projection by some future bug still
# could not reach the CSV unless a column were deliberately added for it.
# This test pins guarantee (b) mechanically: today's real CSV column list
# contains no field-shape-restricted name.
# ---------------------------------------------------------------------------

def test_csv_export_column_list_contains_no_restricted_field_shapes():
    all_keywords = [kw for kws in FIELD_SHAPE_KEYWORDS.values() for kw in kws]
    for field_name in _APP_JS_CSV_ACCESSED_FIELDS:
        assert not any(kw in field_name.lower() for kw in all_keywords), (
            f"public/app.js's CSV export reads '{field_name}', which matches a "
            "restricted-field-shape keyword - if this is intentional, the CSV "
            "column needs its own restriction-awareness; this test exists so "
            "that addition is a deliberate decision, not an accident."
        )


def test_restricted_field_stripped_at_projection_never_reaches_the_row_csv_reads_from(monkeypatch):
    fake = _fake_restricted_source(
        "phase22_fake_source_no_raw_html",
        restrictions=(Restriction.NO_RAW_HTML,),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)
    # A row carrying a restricted-shaped field the CSV export doesn't even
    # have a column for today - the point is that it's gone from the row
    # BEFORE that row could ever become a public.properties row a future
    # CSV-column addition might read from.
    row = dict(_REAL_TX_ROW, harvester_source=fake.source_id, raw_html="<div>secret</div>")
    projected = project_row_for_customer_output(row, fake.source_id)
    assert projected is not None
    assert "raw_html" not in projected


# ---------------------------------------------------------------------------
# 4. Missing restriction metadata fails closed where the governance
#    contract requires it.
# ---------------------------------------------------------------------------

def test_unknown_source_id_fails_closed():
    row = dict(_REAL_TX_ROW, harvester_source="phase22_totally_unregistered")
    assert project_row_for_customer_output(row, "phase22_totally_unregistered") is None
    assert project_row_for_api_export(row, "phase22_totally_unregistered") is None


def test_empty_or_missing_source_id_fails_closed():
    row = dict(_REAL_TX_ROW)
    assert project_row_for_customer_output(row, "") is None
    assert project_row_for_customer_output(row, None) is None  # type: ignore[arg-type]
    assert project_row_for_api_export(row, "") is None
    assert project_row_for_api_export(row, None) is None  # type: ignore[arg-type]


def test_field_specific_restriction_with_no_resolvable_field_mapping_fails_closed(monkeypatch):
    # The registry can record THAT a field-specific restriction exists
    # without recording WHICH field - there is no restriction-to-field-name
    # mapping anywhere in this codebase (see restrictions.py's own
    # comment). That is exactly the "required policy metadata is missing"
    # case Phase 22B's instructions call out - the contract is to deny the
    # whole row, never guess which field to strip.
    fake = _fake_restricted_source(
        "phase22_fake_field_specific_no_mapping",
        restrictions=(Restriction.FIELD_SPECIFIC_RESTRICTION,),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)
    row = dict(_REAL_TX_ROW, harvester_source=fake.source_id)
    assert project_row_for_customer_output(row, fake.source_id) is None
    assert project_row_for_api_export(row, fake.source_id) is None


# ---------------------------------------------------------------------------
# 5. Existing 48-field customer output remains unchanged.
#
# This phase changed no production code, so the 48-field contract (48
# columns from get_properties(), audited in Phase 15/18) is untouched by
# definition. What's checked here, concretely: none of the real fields
# this codebase's own TX sync row or FL-visible CSV columns use collide
# with a restriction-stripping keyword, i.e. applying Phase 11's mechanism
# to today's real production data is a verified no-op, not merely assumed.
# ---------------------------------------------------------------------------

def test_real_production_field_names_are_unaffected_by_restriction_stripping():
    all_keywords = [kw for kws in FIELD_SHAPE_KEYWORDS.values() for kw in kws]
    real_field_names = set(_REAL_TX_ROW) | set(_REAL_FL_ROW) | set(_APP_JS_CSV_ACCESSED_FIELDS)
    for field_name in real_field_names:
        assert not any(kw in field_name.lower() for kw in all_keywords), (
            f"'{field_name}' unexpectedly matches a restricted-field-shape keyword - "
            "this would change today's real production output for an APPROVED source."
        )


# ---------------------------------------------------------------------------
# 6. Existing state/source isolation remains intact.
# ---------------------------------------------------------------------------

def test_fl_and_tx_rows_are_independently_governed_with_no_cross_leakage():
    fl_row = dict(_REAL_FL_ROW, case_no="SHARED-ID")
    tx_row = dict(_REAL_TX_ROW, case_no="SHARED-ID", harvester_source="tx_lgbs")

    fl_projected = project_row_for_customer_output(fl_row, "fl_realauction")
    tx_projected = project_row_for_customer_output(tx_row, "tx_lgbs")

    assert fl_projected["state"] == "FL"
    assert tx_projected["state"] == "TX"
    assert fl_projected["address"] == _REAL_FL_ROW["address"]
    assert tx_projected["address"] == _REAL_TX_ROW["address"]


def test_florida_pipeline_still_has_zero_governance_wiring():
    """Documents, rather than closes, the one real remaining gap this
    phase found: Florida's PowerShell sync scripts (sync-harvest-to-
    supabase.ps1, sync-certificates-to-supabase.ps1, sync-laft-to-
    supabase.ps1) call this Python governance package nowhere - a
    deliberate Phase 10A Step 9 decision ("don't touch Florida's
    production behavior"), reconfirmed still true today, not a defect
    introduced or left open by Track F/Phase 11/Phase 22.

    Extending real enforcement to Florida would require either a new
    cross-process call from PowerShell into this Python package (a new
    service-shaped boundary) or an independent reimplementation of the
    same projection rules in PowerShell (duplicated governance logic in a
    second language) - both are a material architecture change, not the
    smallest safe fix, and Phase 22B's own instructions are to STOP and
    report rather than build one. See this phase's report in the "tax
    florida app" claude.ai Project for the full writeup. All three FL
    registry entries remain APPROVED with zero restrictions (grandfathered,
    not formally reviewed - registry.py's own notes), so there is no live
    restriction this gap is currently failing to enforce; it's a named
    structural limitation, not an active leak.
    """
    import subprocess
    from pathlib import Path

    result = subprocess.run(
        ["grep", "-rl", "governance", "--include=*.ps1", "."],
        cwd=str(Path(__file__).resolve().parents[2]),
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == "", (
        "A PowerShell script now references harvesters/governance - if Florida's "
        "pipeline has been wired into governance, update this test (and Phase 22B's "
        "report) to reflect that the gap has been closed rather than leaving this "
        "assertion stale."
    )
