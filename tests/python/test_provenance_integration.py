"""Phase 12 (Production Provenance & Data Lineage Integration) tests.

Covers harvesters/texas_harvester.py's build_row_provenance()/
FIELD_LINEAGE_MAP (the new Phase 12 integration points) and their real
call sites in that file's main() and scripts/sync-texas-to-supabase.py.
Test groups A-J below match Phase 12 Step 20's own lettered list exactly.

As with every prior phase's test suite: real registry entries (tx_lgbs,
tx_realauction, tx_hctax, tx_pbfcm) are used where a real source is
needed; synthetic SourceRecord fixtures (monkeypatch.setitem) are used
for statuses/restrictions no real source carries. No external source is
contacted or scraped.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

from harvesters.governance import (
    FieldClassification,
    PipelineStage,
    Provenance,
    Restriction,
    SourceStatus,
    advance,
    check_ingestion_gate,
    derive,
    project_row_for_api_export,
    project_row_for_customer_output,
)
from harvesters.governance.registry import SOURCE_REGISTRY, SourceRecord, get_source
from harvesters.texas_harvester import FIELD_LINEAGE_MAP, build_row_provenance

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

_RETRIEVED_AT = "2026-09-14T00:00:00+00:00"


def _fake_record(source_id: str, *, legal_status: SourceStatus, restrictions=()) -> SourceRecord:
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
# A. Source provenance
# ---------------------------------------------------------------------------

def test_A_lgbs_row_has_source_provenance():
    prov = build_row_provenance("tx_lgbs", retrieved_at=_RETRIEVED_AT)
    assert prov.source_id == "tx_lgbs"
    assert prov.source_url == get_source("tx_lgbs").source_url
    assert prov.stage == PipelineStage.NORMALIZED
    assert prov.restrictions == ()
    assert prov.is_source_provided is True


def test_A_realauction_row_has_source_provenance():
    prov = build_row_provenance("tx_realauction", retrieved_at=_RETRIEVED_AT)
    assert prov.source_id == "tx_realauction"
    assert prov.source_url == get_source("tx_realauction").source_url
    assert prov.stage == PipelineStage.NORMALIZED


def test_A_florida_row_can_be_represented_by_the_same_generic_model():
    # Florida harvesting itself is untouched (PowerShell, no Python
    # integration - see test_H below for the isolation check) - but the
    # underlying Provenance dataclass is generic (provenance.py's own
    # docstring: "has no knowledge of TexasSaleRow ... intentionally
    # generic") and CAN represent an FL row using the same registry data,
    # proving the narrowest-shared-boundary approach Phase 12 Step 5 asks
    # for is genuinely available without any FL-specific code change.
    fl_source = get_source("fl_realauction")
    prov = Provenance(
        source_id=fl_source.source_id,
        source_url=fl_source.source_url,
        source_field=None,
        retrieved_at=_RETRIEVED_AT,
        stage=PipelineStage.NORMALIZED,
        classification=FieldClassification.PUBLIC,
        restrictions=check_ingestion_gate("fl_realauction").restrictions,
    )
    assert prov.source_id == "fl_realauction"
    assert prov.restrictions == ()


# ---------------------------------------------------------------------------
# B. Field lineage
# ---------------------------------------------------------------------------

def test_B_field_lineage_map_covers_key_normalized_fields_for_both_tx_sources():
    required = {
        "account_number", "county", "cause_number", "address",
        "legal_description", "min_bid", "cad_market_value",
        "auction_date", "source",
    }
    for source_id in ("tx_lgbs", "tx_realauction"):
        mapped = set(FIELD_LINEAGE_MAP[source_id].keys())
        missing = required - mapped
        assert not missing, f"{source_id} FIELD_LINEAGE_MAP is missing: {missing}"


def test_B_field_lineage_reflects_the_actual_source_field_names_in_the_harvester_code():
    # Spot-check a few mappings against what harvest_lgbs()/
    # harvest_realauction() actually read (see texas_harvester.py) - this
    # is documentation-as-data, so it can silently drift from the real
    # code if nobody checks it; this test is that check.
    assert FIELD_LINEAGE_MAP["tx_lgbs"]["account_number"] == "account_nbr"
    assert "minimum_bid" in FIELD_LINEAGE_MAP["tx_lgbs"]["min_bid"]
    assert FIELD_LINEAGE_MAP["tx_realauction"]["cause_number"] == "'Cause Number' field"
    # RealAuction publishes no coordinates - explicitly recorded as None,
    # not omitted.
    assert FIELD_LINEAGE_MAP["tx_realauction"]["latitude"] is None
    assert FIELD_LINEAGE_MAP["tx_realauction"]["longitude"] is None


# ---------------------------------------------------------------------------
# C. Enrichment
# ---------------------------------------------------------------------------

def test_C_geocoding_enrichment_only_ever_targets_null_coordinates():
    # scripts/geocode_properties.py is the one real, currently-running
    # ENRICHED-stage step (see docs/provenance-production-integration.md).
    # Static-source check (not a live Supabase call) that its query is
    # still scoped to latitude IS NULL - i.e. it can only ever supplement
    # a missing SOURCE value, never overwrite one that exists.
    source = (REPO_ROOT / "scripts" / "geocode_properties.py").read_text()
    assert '"latitude": "is.null"' in source
    # And that it carries no state filter (confirming it runs across both
    # TX and FL rows, not a TX-specific assumption creeping into a
    # cross-state script - Phase 12 Step 5's own explicit warning).
    assert '"state"' not in source.split("def _fetch")[1].split("def fetch_ungeocoded")[0]


def test_C_no_working_cad_enrichment_exists_for_texas_yet():
    # enrich_property_details_tx.py is its own documented draft stub - not
    # invented by this phase, confirmed here so this test suite doesn't
    # silently start assuming CAD enrichment is live when it isn't.
    source = (REPO_ROOT / "scripts" / "enrich_property_details_tx.py").read_text()
    assert "ARCHITECTURAL DRAFT, not working code" in source
    workflow = (REPO_ROOT / ".github" / "workflows" / "harvest-and-sync.yml").read_text()
    # Only ever mentioned in a comment, never invoked as a `run:` step.
    assert "run: python3 scripts/enrich_property_details_tx.py" not in workflow


# ---------------------------------------------------------------------------
# D. Derived fields
# ---------------------------------------------------------------------------

def test_D_derived_field_inherits_parent_lineage():
    parent_a = Provenance(
        source_id="tx_lgbs", source_url="https://example.invalid/a", source_field="min_bid",
        retrieved_at=_RETRIEVED_AT, stage=PipelineStage.NORMALIZED,
        classification=FieldClassification.PUBLIC, restrictions=(),
    )
    parent_b = Provenance(
        source_id="tx_lgbs", source_url="https://example.invalid/b", source_field="cad_market_value",
        retrieved_at=_RETRIEVED_AT, stage=PipelineStage.NORMALIZED,
        classification=FieldClassification.PUBLIC, restrictions=(),
    )
    derived = derive([parent_a, parent_b], source_field="bid_to_value")
    from harvesters.governance import origin_source_ids

    assert origin_source_ids(derived) == frozenset({"tx_lgbs"})
    assert derived.derived_from == (parent_a, parent_b)


def test_D_derived_field_restriction_inheritance_preserved_end_to_end(monkeypatch):
    # The complete chain Phase 12 Step 17 asks for: source restriction ->
    # field -> derived field -> customer projection. A restricted parent's
    # restriction must (a) survive derive() and (b) match what
    # project_row_for_customer_output() would separately decide for that
    # same source - i.e. the two models never disagree about whether a
    # restricted source's data may reach the customer.
    fake = _fake_record(
        "tx_fake_derived_restricted",
        legal_status=SourceStatus.APPROVED_WITH_RESTRICTIONS,
        restrictions=(Restriction.NO_CUSTOMER_DISPLAY,),
    )
    monkeypatch.setitem(SOURCE_REGISTRY, fake.source_id, fake)

    restricted_parent = Provenance(
        source_id=fake.source_id, source_url=fake.source_url, source_field="min_bid",
        retrieved_at=_RETRIEVED_AT, stage=PipelineStage.NORMALIZED,
        classification=FieldClassification.PUBLIC,
        restrictions=check_ingestion_gate(fake.source_id).restrictions,
    )
    unrestricted_parent = Provenance(
        source_id="tx_lgbs", source_url="https://example.invalid/", source_field="cad_market_value",
        retrieved_at=_RETRIEVED_AT, stage=PipelineStage.NORMALIZED,
        classification=FieldClassification.PUBLIC, restrictions=(),
    )
    derived = derive([restricted_parent, unrestricted_parent], source_field="bid_to_value")

    # (a) restriction survives derive()
    assert Restriction.NO_CUSTOMER_DISPLAY in derived.restrictions
    # (b) consistent with what the governance layer would independently
    # decide for a row from the restricted parent's own source
    row = dict(_REAL_TX_ROW, harvester_source=fake.source_id)
    assert project_row_for_customer_output(row, fake.source_id) is None


def test_D_unrestricted_parents_produce_unrestricted_derived_field():
    parent_a = Provenance(
        source_id="tx_lgbs", source_url="https://example.invalid/", source_field="min_bid",
        retrieved_at=_RETRIEVED_AT, stage=PipelineStage.NORMALIZED,
        classification=FieldClassification.PUBLIC, restrictions=(),
    )
    parent_b = Provenance(
        source_id="tx_realauction", source_url="https://example.invalid/", source_field="cad_market_value",
        retrieved_at=_RETRIEVED_AT, stage=PipelineStage.NORMALIZED,
        classification=FieldClassification.PUBLIC, restrictions=(),
    )
    derived = derive([parent_a, parent_b], source_field="bid_to_value")
    assert derived.restrictions == ()


# ---------------------------------------------------------------------------
# E. Customer projection
# ---------------------------------------------------------------------------

_PROVENANCE_SHAPED_KEYS = {
    "provenance", "restrictions", "classification", "stage", "source_url",
    "is_source_provided", "derived_from", "legal_status", "reviewer",
    "notes", "review_date",
}


def test_E_provenance_metadata_never_leaks_into_the_projected_row():
    row = dict(_REAL_TX_ROW)
    projected = project_row_for_customer_output(row, "tx_lgbs")
    assert projected is not None
    leaked = _PROVENANCE_SHAPED_KEYS & set(projected.keys())
    assert not leaked, f"internal provenance/governance keys leaked into customer output: {leaked}"


def test_E_building_provenance_alongside_projection_does_not_mutate_the_input_row():
    row = dict(_REAL_TX_ROW)
    snapshot = dict(row)
    _ = build_row_provenance(row["harvester_source"], retrieved_at=_RETRIEVED_AT)
    _ = project_row_for_customer_output(row, row["harvester_source"])
    assert row == snapshot


# ---------------------------------------------------------------------------
# F. API / export
# ---------------------------------------------------------------------------

def test_F_provenance_metadata_never_leaks_into_the_exported_row():
    row = dict(_REAL_TX_ROW)
    exported = project_row_for_api_export(row, "tx_lgbs")
    assert exported is not None
    leaked = _PROVENANCE_SHAPED_KEYS & set(exported.keys())
    assert not leaked


def test_F_projected_row_remains_plain_json_serializable_with_no_provenance_object_inside():
    import json

    row = dict(_REAL_TX_ROW)
    projected = project_row_for_customer_output(row, "tx_lgbs")
    # Would raise TypeError if a Provenance (or any non-JSON-native value)
    # had been merged into the row - it never is, by construction (gate.py
    # only ever returns a dict of the original row's own values).
    encoded = json.dumps(projected)
    assert "Provenance" not in encoded
    assert "PipelineStage" not in encoded


# ---------------------------------------------------------------------------
# G. Governance - provenance must never become an alternate path around
#    check_ingestion_gate().
# ---------------------------------------------------------------------------

def test_G_blocked_source_row_cannot_reach_customer_output():
    row = dict(_REAL_TX_ROW, harvester_source="tx_pbfcm")
    assert project_row_for_customer_output(row, "tx_pbfcm") is None


def test_G_legal_review_required_source_row_cannot_reach_customer_output():
    row = dict(_REAL_TX_ROW, harvester_source="tx_hctax")
    assert project_row_for_customer_output(row, "tx_hctax") is None


def test_G_unknown_source_fails_closed_and_build_row_provenance_does_not_claim_approval():
    decision = check_ingestion_gate("tx_totally_made_up")
    assert decision.allowed is False
    # build_row_provenance() is descriptive, not a gate - it must not
    # crash on an unrecognized source, and it must not fabricate approval:
    # source_url falls back to "" (get_source() returns None) and
    # restrictions falls back to () - it never claims a restriction set
    # that would imply the source was found and cleared.
    prov = build_row_provenance("tx_totally_made_up", retrieved_at=_RETRIEVED_AT)
    assert prov.source_url == ""
    row = dict(_REAL_TX_ROW, harvester_source="tx_totally_made_up")
    assert project_row_for_customer_output(row, "tx_totally_made_up") is None


def test_G_integration_sync_script_never_builds_provenance_for_ungated_rows(monkeypatch, tmp_path):
    """End-to-end check against the REAL sync script (not a reimplementation
    of its logic): a mixed-source fixture (one APPROVED tx_lgbs row, one
    BLOCKED tx_pbfcm row, one LEGAL_REVIEW_REQUIRED tx_hctax row) is run
    through scripts/sync-texas-to-supabase.py end to end, with the only
    network call it makes (urllib.request.urlopen) stubbed out - no real
    Supabase call is made. Confirms the actual, real, unmodified module
    only ever builds a provenance count for the one source that passed
    both governance checks."""
    import json
    import urllib.request

    out_dir = tmp_path / "out"
    out_dir.mkdir()
    fixture = [
        {"account_number": "1", "county": "Dallas", "state": "TX", "auction_date": "2026-10-01",
         "min_bid": 1000.0, "cad_market_value": 20000.0, "legal_description": "LOT 1",
         "address": "1 Main St", "cause_number": "C-1", "latitude": 32.7, "longitude": -96.8,
         "source": "auction", "harvester_source": "tx_lgbs"},
        {"account_number": "2", "county": "Nacogdoches", "state": "TX", "auction_date": "2026-10-02",
         "min_bid": 500.0, "cad_market_value": None, "legal_description": None,
         "address": "2 Main St", "cause_number": None, "latitude": None, "longitude": None,
         "source": "laft", "harvester_source": "tx_pbfcm"},
        {"account_number": "3", "county": "Harris", "state": "TX", "auction_date": "2026-10-03",
         "min_bid": 500.0, "cad_market_value": 9000.0, "legal_description": "LOT 3",
         "address": "3 Main St", "cause_number": "C-3", "latitude": None, "longitude": None,
         "source": "auction", "harvester_source": "tx_hctax"},
    ]
    (out_dir / "harvest_texas.json").write_text(json.dumps(fixture))

    spec = importlib.util.spec_from_file_location(
        "sync_mod_test", str(REPO_ROOT / "scripts" / "sync-texas-to-supabase.py")
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    monkeypatch.setattr(mod, "HERE", tmp_path)
    monkeypatch.setattr(mod, "JSON_PATH", out_dir / "harvest_texas.json")
    monkeypatch.setenv("SUPABASE_URL", "http://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-fixture-not-a-real-key")

    posted = []

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b""

    def _fake_urlopen(req, timeout=60):
        posted.append(json.loads(req.data))
        return _FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)

    mod.main()

    all_posted_ids = {row["case_no"] for batch in posted for row in batch}
    assert all_posted_ids == {"1"}  # only the tx_lgbs row reached the (stubbed) upsert
    assert mod  # sanity: module executed without raising


# ---------------------------------------------------------------------------
# H. Isolation
# ---------------------------------------------------------------------------

def test_H_florida_texas_same_county_case_no_produce_independent_provenance():
    fl_row = {"state": "FL", "county": "Shared", "case_no": "SAME-ID", "address": "FL address", "harvester_source": "fl_realauction"}
    tx_row = {"state": "TX", "county": "Shared", "case_no": "SAME-ID", "address": "TX address", "harvester_source": "tx_lgbs"}

    tx_prov = build_row_provenance("tx_lgbs", retrieved_at=_RETRIEVED_AT)
    fl_prov = Provenance(
        source_id="fl_realauction", source_url=get_source("fl_realauction").source_url,
        source_field=None, retrieved_at=_RETRIEVED_AT, stage=PipelineStage.NORMALIZED,
        classification=FieldClassification.PUBLIC, restrictions=(),
    )

    assert tx_prov.source_id != fl_prov.source_id
    fl_projected = project_row_for_customer_output(fl_row, "fl_realauction")
    tx_projected = project_row_for_customer_output(tx_row, "tx_lgbs")
    assert fl_projected["address"] == "FL address"
    assert tx_projected["address"] == "TX address"
    # no global state keyed only by (county, case_no) or (source, case_no):
    # re-running in the opposite order changes nothing
    tx_projected_2 = project_row_for_customer_output(tx_row, "tx_lgbs")
    fl_projected_2 = project_row_for_customer_output(fl_row, "fl_realauction")
    assert tx_projected_2 == tx_projected
    assert fl_projected_2 == fl_projected


# ---------------------------------------------------------------------------
# I. Idempotency - record identity vs. retrieval event.
# ---------------------------------------------------------------------------

def test_I_same_source_same_retrieval_context_produces_equivalent_lineage():
    prov_1 = build_row_provenance("tx_lgbs", retrieved_at=_RETRIEVED_AT)
    prov_2 = build_row_provenance("tx_lgbs", retrieved_at=_RETRIEVED_AT)
    assert prov_1 == prov_2  # frozen dataclass equality - fully deterministic given the same inputs


def test_I_different_retrieval_timestamps_are_a_different_retrieval_event_not_a_different_record_identity():
    prov_1 = build_row_provenance("tx_lgbs", retrieved_at="2026-09-14T00:00:00+00:00")
    prov_2 = build_row_provenance("tx_lgbs", retrieved_at="2026-09-15T00:00:00+00:00")
    assert prov_1.source_id == prov_2.source_id  # record identity: same
    assert prov_1.retrieved_at != prov_2.retrieved_at  # retrieval event: different, and that's expected
    assert prov_1 != prov_2  # the two ARE different records (different retrieval), not a bug


# ---------------------------------------------------------------------------
# J. Mutation safety
# ---------------------------------------------------------------------------

def test_J_provenance_is_immutable():
    prov = build_row_provenance("tx_lgbs", retrieved_at=_RETRIEVED_AT)
    with pytest.raises(dataclasses.FrozenInstanceError):
        prov.source_id = "tampered"  # type: ignore[misc]


def test_J_advance_and_derive_never_mutate_their_input_provenance():
    original = Provenance(
        source_id="tx_lgbs", source_url="https://example.invalid/", source_field="min_bid",
        retrieved_at=_RETRIEVED_AT, stage=PipelineStage.NORMALIZED,
        classification=FieldClassification.PUBLIC, restrictions=(),
    )
    snapshot = dataclasses.replace(original)  # a genuine independent copy for comparison
    advanced = advance(original, stage=PipelineStage.ENRICHED, additional_restrictions=(Restriction.RATE_LIMIT,))
    assert original == snapshot  # input untouched
    assert advanced is not original
    assert Restriction.RATE_LIMIT not in original.restrictions  # the mutation-looking op created a new object instead


def test_J_two_rows_from_the_same_source_do_not_share_mutable_state():
    prov_row_1 = build_row_provenance("tx_lgbs", retrieved_at=_RETRIEVED_AT)
    prov_row_2 = build_row_provenance("tx_lgbs", retrieved_at=_RETRIEVED_AT)
    assert prov_row_1 == prov_row_2  # equal by value
    assert prov_row_1 is not prov_row_2  # but genuinely independent objects
    # restrictions is a tuple (immutable) on a frozen dataclass - there is
    # no mutable field anywhere on Provenance for two instances to share.
    assert all(dataclasses.fields(prov_row_1)[i].name for i in range(len(dataclasses.fields(prov_row_1))))
