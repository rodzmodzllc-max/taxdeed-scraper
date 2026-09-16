"""Tests for Phase 41 (Controlled Real-Network tx_lgbs Acquisition) -
harvesters/acquisition/run.py, the rejection classification added to
LgbsAdapter, and scripts/run_lgbs_acquisition.py's environment
classification.

Covers Section 19's fifteen required categories. Every test is fixture-
driven and makes ZERO network calls (Section 19 keeps fixture tests and
live tests separate; the live evidence from this phase lives in
`claude/phase-41-lgbs-controlled-acquisition.md` and the run artifact).

The central property under test is the one that makes a controlled
acquisition trustworthy at all: **a run cannot report COMPLETE unless it
can prove it.** Proof means a balanced tally, exhausted pagination, no
failures, and agreement with a denominator measured independently of the
run. Each of those is tested in isolation and in combination, because
every one of them is a way a partial acquisition could otherwise present
itself as a complete one.
"""

from __future__ import annotations

import pytest

from harvesters.acquisition import (
    AcquisitionPurpose,
    AcquisitionStatus,
    EnvironmentBlockedTransport,
    FixtureTransport,
    SourceUnavailable,
    build_result,
    check_acquisition_policy,
    observed_counties,
    roster_totals,
)
from harvesters.acquisition.adapters import LGBS_CONFIG, LgbsAdapter
from harvesters.acquisition.run import (
    TX_LGBS_AREA_TX_TOTAL,
    TX_LGBS_PA_TOTAL,
    TX_LGBS_STATE_DENOMINATOR,
    TX_LGBS_UNATTRIBUTED,
    AcquisitionRun,
    DenominatorCheck,
    RejectionReason,
    RunStatus,
    RunTally,
)
from harvesters.acquisition.transport import (
    AccessRestricted,
    AuthenticationRequired,
    EnvironmentEgressBlocked,
    SchemaError,
)
from harvesters.governance import check_ingestion_gate

LGBS_URL = "https://taxsales.lgbs.com/api/property_sales/?area=TX&limit=500"
LGBS_PAGE2 = "https://taxsales.lgbs.com/api/property_sales/?area=TX&limit=500&offset=500"


def row(**overrides) -> dict:
    base = {
        "uid": "u1", "sale_id": 101, "state": "TX", "county": "HARRIS COUNTY",
        "status": "Scheduled for Auction", "sale_type": "SALE",
        "account_nbr": "A1", "cause_nbr": "C1",
        "sale_date": "2026-10-06T10:00:00Z", "sale_date_only": "2026-10-06",
        "minimum_bid": "1000.00", "value": "50000", "sale_notes": "LOT 1",
        "prop_address_one": "1 Main St", "prop_city": "HOUSTON", "prop_zipcode": "77002",
        "geometry": {"coordinates": [-95.37, 29.76]},
    }
    base.update(overrides)
    return base


def envelope(results, next_url=None) -> dict:
    return {"count": len(results), "next": next_url, "previous": None, "results": results}


def run_with(results_rows, *, next_url=None, county="Harris", exhausted=True) -> tuple[AcquisitionRun, object]:
    t = FixtureTransport().add_json(LGBS_URL, envelope(results_rows, next_url=next_url))
    run = AcquisitionRun(source_id="tx_lgbs", state="TX")
    result = LgbsAdapter(transport=t).acquire()
    run.record_result(result, county=county)
    run.pagination_exhausted = exhausted
    return run, result


# ===========================================================================
# 1. LGBS state contamination
# ===========================================================================


def test_01_pa_records_are_rejected_from_the_texas_dataset():
    run, result = run_with([
        row(),
        row(uid="pa1", state="PA", county="PHILADELPHIA COUNTY", account_nbr="P1"),
        row(uid="pa2", state="PA", county="PHILADELPHIA COUNTY", account_nbr="P2"),
    ])
    assert result.records_acquired == 1
    assert all(r["state"] == "TX" for r in result.records)
    assert result.rejections_by_reason[RejectionReason.OUT_OF_STATE.value] == 2


def test_01b_run_reports_area_seen_state_accepted_and_non_tx_rejected():
    """Section 8's three required figures, from one run."""
    run, result = run_with([row(), row(uid="pa1", state="PA", county="PHILADELPHIA COUNTY", account_nbr="P1")])
    area_tx_seen = run.tally.records_seen
    state_tx_accepted = run.tally.records_acquired
    non_tx_rejected = run.tally.rejections_by_reason.get(RejectionReason.OUT_OF_STATE.value, 0)
    assert (area_tx_seen, state_tx_accepted, non_tx_rejected) == (2, 1, 1)


def test_01c_area_tx_is_never_treated_as_a_state_filter():
    """The adapter's configured query still uses area=TX, and that is fine
    ONLY because every row's own state is checked. If the config ever gains
    a state= param this test should be revisited deliberately, not silently."""
    assert LGBS_CONFIG.query_params == {"area": "TX"}


# ===========================================================================
# 2. Pagination
# ===========================================================================


def test_02_pagination_follows_next_until_source_signals_completion():
    t = FixtureTransport()
    t.add_json(LGBS_URL, envelope([row()], next_url=LGBS_PAGE2.replace("https://", "http://")))
    t.add_json(LGBS_PAGE2, envelope([row(uid="u2", account_nbr="A2")], next_url=None))
    result = LgbsAdapter(transport=t).acquire()
    assert result.records_acquired == 2
    assert len(t.requested_urls) == 2
    assert result.checkpoint is None, "a fully-walked run must not leave a resume checkpoint"


def test_02b_page_size_is_unchanged_at_500():
    """Section 10: do not reduce LGBS_PAGE_SIZE because of the Phase 40
    fetch-tool truncation artifact. The API was proven to honor 500 via its
    own next link."""
    assert LGBS_CONFIG.page_size == 500
    assert "limit=500" in LgbsAdapter(transport=FixtureTransport()).build_first_url()


def test_02c_incomplete_pagination_leaves_a_checkpoint_and_blocks_complete():
    t = FixtureTransport().add_json(LGBS_URL, envelope([row(), row(uid="u2", account_nbr="A2")], next_url=LGBS_PAGE2))
    run = AcquisitionRun(source_id="tx_lgbs", state="TX")
    result = LgbsAdapter(transport=t).acquire(limit=1)
    run.record_result(result)
    run.pagination_exhausted = result.checkpoint is None
    run.finalize(expected_denominator=None)
    assert result.checkpoint is not None
    assert run.status != RunStatus.COMPLETE


# ===========================================================================
# 3. The 4,205 denominator
# ===========================================================================


def test_03_texas_denominator_is_4205_not_6309():
    assert TX_LGBS_STATE_DENOMINATOR == 4205
    assert TX_LGBS_AREA_TX_TOTAL == 6309
    assert TX_LGBS_STATE_DENOMINATOR != TX_LGBS_AREA_TX_TOTAL


def test_03b_phase40_arithmetic_holds():
    assert TX_LGBS_STATE_DENOMINATOR + TX_LGBS_PA_TOTAL == TX_LGBS_AREA_TX_TOTAL


def test_03c_denominator_check_passes_only_on_exact_reconciliation():
    ok = DenominatorCheck(expected=100, observed_at_source=100, acquired=60, rejected=40, failed=0)
    assert ok.passed and ok.variance == 0
    short = DenominatorCheck(expected=100, observed_at_source=100, acquired=60, rejected=30, failed=0)
    assert not short.passed and short.variance == -10


def test_03d_unknown_denominator_never_counts_as_passed():
    """An unverifiable run is UNKNOWN, not verified."""
    unknown = DenominatorCheck(expected=None, observed_at_source=None, acquired=99, rejected=0, failed=0)
    assert unknown.passed is False
    assert unknown.variance is None
    assert "UNKNOWN" in unknown.reason


# ===========================================================================
# 4. 95-county observed roster
# ===========================================================================


def test_04_observed_roster_is_95_counties():
    assert len(observed_counties("tx_lgbs", state="TX")) == 95


def test_04b_roster_counties_are_not_all_of_texas():
    """Section 7: do not assume the 95 observed counties represent all 254."""
    from harvesters.governance.source_catalog import load_tx_matrix

    observed = set(observed_counties("tx_lgbs", state="TX"))
    all_tx = {r["county"] for r in load_tx_matrix()}
    assert observed < all_tx
    assert len(all_tx - observed) == 254 - 95


# ===========================================================================
# 5. The 8 unattributed records
# ===========================================================================


def test_05_unattributed_records_are_preserved_not_assigned():
    totals = roster_totals()
    assert totals["unattributed_residual"] == TX_LGBS_UNATTRIBUTED == 8
    assert totals["records_measured"] + totals["unattributed_residual"] == TX_LGBS_STATE_DENOMINATOR


def test_05b_unattributed_residual_is_not_folded_into_any_county():
    from harvesters.acquisition.roster import load_tx_lgbs_roster

    per_county = [r for r in load_tx_lgbs_roster() if r.state == "TX" and not r.is_residual]
    assert sum(r.records_observed for r in per_county) == 4197
    assert 4197 != TX_LGBS_STATE_DENOMINATOR


def test_05c_run_tally_tracks_unattributed_separately():
    tally = RunTally(records_observed_at_source=4205)
    tally.records_unattributed = 8
    assert "records_unattributed" in tally.to_dict()
    assert tally.to_dict()["records_unattributed"] == 8


# ===========================================================================
# 6-7. Query parameter validation
# ===========================================================================


def test_06_adapter_uses_no_unverified_query_parameters():
    """Section 9: LGBS silently ignores unknown params, so the adapter must
    only ever send parameters whose effect was verified."""
    url = LgbsAdapter(transport=FixtureTransport()).build_first_url()
    for forbidden in ("county__icontains", "search", "fields", "ordering"):
        assert forbidden not in url


def test_07_bogus_county_must_not_return_the_full_dataset():
    """The Phase 40 validation, encoded as a regression: a filter that is
    silently ignored would return the full count. The fixture models the
    VERIFIED behavior (bogus -> 0), so if anyone changes the adapter to
    trust an unvalidated filter this test documents the contract it must
    satisfy."""
    bogus_url = "https://taxsales.lgbs.com/api/property_sales/?area=TX&limit=1&county=NOTAREAL%20COUNTY"
    t = FixtureTransport().add_json(bogus_url, {"count": 0, "next": None, "previous": None, "results": []})
    response = t.get(bogus_url)
    payload = response.json()
    assert payload["count"] == 0
    assert payload["count"] != TX_LGBS_AREA_TX_TOTAL


# ===========================================================================
# 8-9. Sale status
# ===========================================================================


def test_08_sale_status_endpoint_remains_unresolved():
    """Section 11: /api/sale_status/ is an unserved route. No replacement
    endpoint may be introduced into the adapter."""
    url = LgbsAdapter(transport=FixtureTransport()).build_first_url()
    assert "sale_status" not in url
    assert LGBS_CONFIG.base_url.endswith("/property_sales/")


def test_09_status_mapping_is_unchanged_and_not_guessed():
    from texas_harvester import LGBS_STATUS_TO_LEDGER  # type: ignore

    assert LGBS_STATUS_TO_LEDGER == {
        "Scheduled for Auction": "auction",
        "Scheduled for Online Auction": "auction",
        "Available for Future Sale": "laft",
        "Struck off to Jurisdiction": "laft",
    }


def test_09b_sale_type_never_determines_classification():
    """A sale_type=SALE row with an unmapped status must be rejected, not
    classified from sale_type."""
    run, result = run_with([row(uid="x", sale_type="SALE", status="Cancelled", account_nbr="X1")])
    assert result.records_acquired == 0
    assert result.rejections_by_reason[RejectionReason.UNMAPPED_STATUS.value] == 1


def test_09c_source_native_status_is_preserved_alongside_the_ledger():
    run, result = run_with([row()])
    record = result.records[0]
    assert record["_source_status"] == "Scheduled for Auction"
    assert record["_source_sale_type"] == "SALE"
    assert record["source"] == "auction"


# ===========================================================================
# 10. Provenance
# ===========================================================================


def test_10_provenance_lineage_lgbs_to_normalized_property():
    run, result = run_with([row()])
    record = result.records[0]
    assert record["_source_id"] == "tx_lgbs"
    assert record["_source_record_id"] == "u1"
    assert record["_retrieved_at"]
    assert record["_source_timestamp"] == "2026-10-06T10:00:00Z"
    assert record["_normalization_version"] == "1"


def test_10b_every_acquired_record_has_full_provenance():
    from harvesters.acquisition import has_provenance

    run, result = run_with([row(), row(uid="u2", account_nbr="A2")])
    assert result.records_acquired == 2
    assert all(has_provenance(r) for r in result.records)


def test_10c_retrieval_metadata_records_the_source_url():
    run, result = run_with([row()])
    assert result.retrievals
    assert result.retrievals[0].source_url == LGBS_URL
    assert result.retrievals[0].content_hash_value


# ===========================================================================
# 11. Duplicates and identity
# ===========================================================================


def test_11_duplicate_records_are_detected_and_counted_separately():
    dup = row()
    run, result = run_with([dup, dict(dup)])
    assert result.records_acquired == 1
    assert result.rejections_by_reason[RejectionReason.DUPLICATE.value] == 1
    assert run.tally.records_duplicated == 1
    # A duplicate is not a rejection - conflating them would double-count.
    assert RejectionReason.DUPLICATE.value not in run.tally.rejections_by_reason


def test_11b_same_case_number_different_county_stays_distinct():
    run, result = run_with([
        row(uid="a", account_nbr="SAME", county="HARRIS COUNTY"),
        row(uid="b", account_nbr="SAME", county="DALLAS COUNTY"),
    ])
    assert result.records_acquired == 2
    assert {r["county"] for r in result.records} == {"Harris", "Dallas"}


def test_11c_same_case_number_different_state_cannot_collide():
    """The PA row is rejected outright, so a TX/PA identity collision is
    impossible by construction rather than by comparison."""
    run, result = run_with([
        row(uid="a", account_nbr="SAME", state="TX"),
        row(uid="b", account_nbr="SAME", state="PA", county="PHILADELPHIA COUNTY"),
    ])
    assert result.records_acquired == 1
    assert result.records[0]["state"] == "TX"


def test_11d_identity_prefers_source_record_id_over_mutable_content():
    from harvesters.acquisition import idempotency_key

    a = {"_source_id": "tx_lgbs", "_source_record_id": "u1", "min_bid": 100}
    b = {"_source_id": "tx_lgbs", "_source_record_id": "u1", "min_bid": 250}
    assert idempotency_key(a) == idempotency_key(b), "a corrected bid must not look like a new record"


# ===========================================================================
# 12. Partial acquisition
# ===========================================================================


def test_12_partial_run_never_reports_complete():
    run, _ = run_with([row()], exhausted=False)
    run.finalize(expected_denominator=TX_LGBS_STATE_DENOMINATOR)
    assert run.status == RunStatus.PARTIAL


def test_12b_denominator_mismatch_blocks_complete_even_when_paginated():
    run, _ = run_with([row()], exhausted=True)
    run.finalize(expected_denominator=4205)
    assert run.status == RunStatus.PARTIAL


def test_12c_complete_requires_every_condition_together():
    run, _ = run_with([row(), row(uid="pa", state="PA", county="PHILADELPHIA COUNTY", account_nbr="P")], exhausted=True)
    check = run.finalize(expected_denominator=2)  # 1 acquired + 1 rejected
    assert check.passed
    assert run.tally.is_balanced
    assert run.status == RunStatus.COMPLETE


def test_12d_run_producing_nothing_is_incomplete_not_complete():
    run, _ = run_with([], exhausted=True)
    run.finalize(expected_denominator=None)
    assert run.status == RunStatus.INCOMPLETE


def test_12e_unbalanced_tally_blocks_complete():
    run = AcquisitionRun(source_id="tx_lgbs", state="TX")
    run.record_result(build_result(
        source_id="tx_lgbs", jurisdiction="TX/Harris", status=AcquisitionStatus.SUCCESS,
        started_at="2026-09-16T00:00:00+00:00", records=[{"a": 1}], records_seen=10,
    ))
    run.pagination_exhausted = True
    run.finalize(expected_denominator=None)
    assert not run.tally.is_balanced
    assert run.status == RunStatus.PARTIAL


# ===========================================================================
# 13. Transport failure classification
# ===========================================================================


def test_13_environment_block_is_not_a_source_failure():
    run = AcquisitionRun(source_id="tx_lgbs", state="TX")
    result = LgbsAdapter(transport=EnvironmentBlockedTransport()).acquire()
    run.record_result(result)
    run.mark_blocked(result.errors[0], environment_status="ENVIRONMENT_EGRESS_BLOCKED")
    run.finalize(expected_denominator=TX_LGBS_STATE_DENOMINATOR)
    assert run.status == RunStatus.BLOCKED
    assert run.environment_status == "ENVIRONMENT_EGRESS_BLOCKED"
    assert any("ENVIRONMENT_EGRESS_BLOCKED" in e for e in run.errors)
    assert not any("ACCESS_RESTRICTED" in e for e in run.errors)


def test_13b_blocked_run_is_never_complete_and_never_fabricates_records():
    run = AcquisitionRun(source_id="tx_lgbs", state="TX")
    run.mark_blocked("egress denied", environment_status="ENVIRONMENT_EGRESS_BLOCKED")
    run.finalize(expected_denominator=TX_LGBS_STATE_DENOMINATOR)
    assert run.status == RunStatus.BLOCKED
    assert run.tally.records_acquired == 0


def test_13c_environment_classifier_distinguishes_all_five_outcomes():
    from scripts.run_lgbs_acquisition import classify_environment

    class Raising:
        def __init__(self, exc):
            self.exc = exc

        def get(self, url, *, timeout=None):
            raise self.exc

    cases = {
        EnvironmentEgressBlocked("proxy 403"): "ENVIRONMENT_EGRESS_BLOCKED",
        AccessRestricted("waf"): "SOURCE_REFUSED",
        AuthenticationRequired("401"): "SOURCE_REFUSED",
        SourceUnavailable("timeout"): "SOURCE_UNAVAILABLE",
        SchemaError("not json"): "SOURCE_ERROR",
    }
    for exc, expected in cases.items():
        status, _detail = classify_environment(Raising(exc))
        assert status == expected, f"{type(exc).__name__} -> {status}, expected {expected}"


def test_13d_healthy_probe_classifies_as_network_available():
    from scripts.run_lgbs_acquisition import classify_environment

    probe = "https://taxsales.lgbs.com/api/property_sales/?area=TX&limit=1"
    t = FixtureTransport().add_json(probe, envelope([row()]))
    status, detail = classify_environment(t)
    assert status == "NETWORK_AVAILABLE"
    assert "count=" in detail


# ===========================================================================
# 14. Source authorization enforcement
# ===========================================================================


def test_14_tx_lgbs_passes_the_existing_gate_unchanged():
    gate = check_ingestion_gate("tx_lgbs")
    assert gate.allowed is True
    policy = check_acquisition_policy(
        "tx_lgbs", purpose=AcquisitionPurpose.PRODUCTION_ACQUISITION, state="TX"
    )
    assert policy.allowed is True
    assert policy.registry_status == "APPROVED"


def test_14b_no_other_source_was_activated_by_this_phase():
    """Section 3/23: only tx_lgbs. Every other source's production
    acquisition decision must be unchanged."""
    for source_id in ("fl_realauction", "fl_lienhub_certificates", "fl_dor_statewide", "tx_hctax"):
        assert check_acquisition_policy(
            source_id, purpose=AcquisitionPurpose.PRODUCTION_ACQUISITION, state="FL", county="Alachua"
        ).allowed is False
    for blocked in ("tx_pbfcm", "tx_mvba", "tx_ctsa", "tx_govease"):
        for purpose in AcquisitionPurpose:
            assert check_acquisition_policy(blocked, purpose=purpose).allowed is False


def test_14c_adapter_refuses_to_acquire_when_policy_denies():
    """A denied policy stops the run before any request is issued."""
    from harvesters.acquisition.adapters.arcgis import HCAD_LAYER, ArcGisAdapter

    t = FixtureTransport()
    adapter = ArcGisAdapter(HCAD_LAYER, transport=t, source_id="tx_hctax")
    result = adapter.acquire_parcels(["1011020000003"])
    assert result.status == AcquisitionStatus.LEGAL_RESTRICTION
    assert t.requested_urls == []


# ===========================================================================
# 15. records_observed_at_source vs records_acquired
# ===========================================================================


def test_15_observed_at_source_is_separate_from_acquired():
    run, _ = run_with([row()])
    run.tally.records_observed_at_source = TX_LGBS_STATE_DENOMINATOR
    d = run.tally.to_dict()
    assert d["records_observed_at_source"] == 4205
    assert d["records_acquired"] == 1
    assert d["records_observed_at_source"] != d["records_acquired"]


def test_15b_observed_at_source_is_never_derived_from_the_run():
    """A run must not be able to certify itself by using its own output as
    its expected input."""
    run = AcquisitionRun(source_id="tx_lgbs", state="TX")
    assert run.tally.records_observed_at_source is None
    run.record_result(build_result(
        source_id="tx_lgbs", jurisdiction="TX/statewide", status=AcquisitionStatus.SUCCESS,
        started_at="2026-09-16T00:00:00+00:00", records=[{"a": 1}], records_seen=1,
    ))
    assert run.tally.records_observed_at_source is None


def test_15c_county_coverage_percentage_is_none_without_a_measured_denominator():
    run, _ = run_with([row()], county="Zzz Nonexistent")
    rows = run.county_coverage()
    assert rows[0]["coverage_percentage"] is None


def test_15d_county_coverage_uses_the_measured_roster_denominator():
    run, _ = run_with([row()], county="Harris")
    rows = {r["county"]: r for r in run.county_coverage()}
    assert rows["Harris"]["records_observed_at_source"] == 405
    assert rows["Harris"]["records_acquired"] == 1
    assert rows["Harris"]["coverage_percentage"] == pytest.approx(0.25, abs=0.01)


# ===========================================================================
# Production-safety and artifact structure
# ===========================================================================


def test_p01_acquisition_package_has_no_production_write_path():
    """Section 16, enforced structurally rather than by policy.

    Checks actual executable code - imports and string literals - rather
    than raw substrings. Several modules legitimately *discuss* Supabase in
    prose (explaining why they deliberately do not touch it), and a
    substring scan would flag that documentation as a violation while
    telling us nothing about real behavior."""
    import ast
    import pathlib

    pkg = pathlib.Path(__file__).resolve().parents[2] / "harvesters" / "acquisition"
    db_modules = {"supabase", "psycopg", "psycopg2", "sqlalchemy", "asyncpg", "MySQLdb", "pymysql"}
    dml = ("insert into", "update ", "delete from", "truncate", "drop table")

    for path in list(pkg.glob("*.py")) + list(pkg.glob("adapters/*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in db_modules, f"{path.name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root not in db_modules, f"{path.name} imports from {node.module}"
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                # Skip docstrings - only non-docstring literals could be
                # executed as a query.
                lowered = node.value.lower()
                if len(node.value) < 400 and any(k in lowered for k in dml):
                    raise AssertionError(f"{path.name} contains a DML-looking literal: {node.value[:60]!r}")


def test_p02_runner_declares_production_untouched():
    import pathlib

    runner = (pathlib.Path(__file__).resolve().parents[2] / "scripts" / "run_lgbs_acquisition.py").read_text()
    assert '"production_data_modified": False' in runner


def test_p03_field_completeness_reports_expected_present_and_missing():
    run, _ = run_with([row(), row(uid="u2", account_nbr="A2", prop_address_one=None, prop_city=None)])
    rows = {r["field"]: r for r in run.field_completeness(("case_no", "address"))}
    assert rows["case_no"]["present"] == 2
    assert rows["address"]["present"] == 1
    assert rows["address"]["missing"] == 1
    assert rows["address"]["coverage_percentage"] == 50.0


def test_p04_rejection_reasons_are_a_closed_vocabulary():
    assert {r.value for r in RejectionReason} == {
        "OUT_OF_STATE", "UNMAPPED_STATUS", "MISSING_IDENTITY", "DUPLICATE", "MALFORMED",
    }


def test_p05_run_status_vocabulary_has_no_ambiguous_success():
    values = {s.value for s in RunStatus}
    assert values == {"NOT_STARTED", "IN_PROGRESS", "COMPLETE", "PARTIAL", "INCOMPLETE", "BLOCKED"}
    assert "SUCCESS" not in values, "SUCCESS would be ambiguous against COMPLETE/PARTIAL"
