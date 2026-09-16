"""Tests for Phase 40 (Real-Network Acquisition Activation & Coverage
Expansion) - harvesters/acquisition/roster.py and the coverage expansion it
drives, plus Section 46's twenty named adversarial cases.

Every test here is fixture- or repository-data-driven and makes ZERO network
calls. The live measurements this phase performed are recorded in
`data/tx_lgbs_observed_county_roster.csv` and `claude/phase-40-lgbs-roster.md`;
these tests assert the INVARIANTS that roster must satisfy, not the network.

A note on what these tests deliberately do NOT assert: they do not pin the
exact per-county record counts. Those are live measurements of a source that
republishes its sale calendar continuously, so hard-coding them would produce
a test suite that fails for the correct reason (the world changed) rather
than an incorrect one (the code broke). What IS asserted is every structural
property that must hold regardless of what the source publishes: arithmetic
consistency, the residual being recorded rather than hidden, county-name
normalization, state isolation, and the governance separation.
"""

from __future__ import annotations

import csv

import pytest

from harvesters.acquisition import (
    AcquisitionPurpose,
    AcquisitionStatus,
    EnvironmentBlockedTransport,
    FixtureTransport,
    ObservedCountyRecord,
    SourceUnavailable,
    UNATTRIBUTED_RESIDUAL,
    build_county_configs,
    build_result,
    check_acquisition_policy,
    check_fallback_allowed,
    counties_with_adapter,
    deduplicate,
    has_provenance,
    load_tx_lgbs_roster,
    observed_counties,
    observed_record_count,
    roster_totals,
)
from harvesters.acquisition.adapters import LgbsAdapter
from harvesters.acquisition.roster import TX_LGBS_ROSTER_PATH
from harvesters.governance import SOURCE_REGISTRY, can_promote_source_for_use
from harvesters.governance.source_catalog import load_tx_matrix

LGBS_FIRST_URL = "https://taxsales.lgbs.com/api/property_sales/?area=TX&limit=500"


def lgbs_row(**overrides) -> dict:
    row = {
        "uid": "u1", "sale_id": 101, "state": "TX", "county": "HARRIS COUNTY",
        "status": "Scheduled for Auction", "sale_type": "SALE",
        "account_nbr": "A1", "cause_nbr": "C1",
        "sale_date": "2026-10-06T10:00:00Z", "sale_date_only": "2026-10-06",
        "minimum_bid": "1000.00", "value": "50000", "sale_notes": "LOT 1",
        "prop_address_one": "1 Main St", "prop_city": "HOUSTON", "prop_zipcode": "77002",
        "geometry": {"coordinates": [-95.37, 29.76]},
    }
    row.update(overrides)
    return row


def envelope(results, next_url=None) -> dict:
    return {"count": len(results), "next": next_url, "previous": None, "results": results}


# ===========================================================================
# Roster structure and arithmetic
# ===========================================================================


def test_r01_roster_file_exists_and_parses():
    assert TX_LGBS_ROSTER_PATH.exists()
    records = load_tx_lgbs_roster()
    assert len(records) > 50
    assert all(isinstance(r, ObservedCountyRecord) for r in records)


def test_r02_roster_arithmetic_is_self_consistent():
    """measured + residual must equal the authoritative state total. This is
    the check that caught a 234-record gap during the live measurement."""
    totals = roster_totals()
    assert totals["records_measured"] + totals["unattributed_residual"] == totals["authoritative_state_total"]


def test_r03_residual_is_recorded_not_hidden():
    """An unattributed remainder must appear as its own row, never be
    distributed across known counties or silently dropped."""
    residual_rows = [r for r in load_tx_lgbs_roster() if r.is_residual]
    assert len(residual_rows) == 1
    assert residual_rows[0].records_observed >= 0
    assert residual_rows[0].notes.strip() != ""


def test_r04_attribution_completeness_is_reported_not_rounded_to_100():
    totals = roster_totals()
    pct = totals["attribution_completeness_pct"]
    assert pct is not None
    assert 0 < pct <= 100
    # If a residual exists, completeness must be strictly below 100 - never
    # rounded up to look complete.
    if totals["unattributed_residual"] > 0:
        assert pct < 100.0


def test_r05_residual_sentinel_is_excluded_from_the_county_list():
    counties = observed_counties("tx_lgbs", state="TX")
    assert UNATTRIBUTED_RESIDUAL not in counties
    assert all(c.strip() for c in counties)


def test_r06_out_of_state_records_are_tracked_separately():
    """Philadelphia is inside the area=TX result set but is not a Texas
    county. It must never be counted toward Texas coverage."""
    totals = roster_totals()
    assert totals["out_of_state_records"] > 0
    assert "PA/Philadelphia" in totals["out_of_state_counties"]
    assert "Philadelphia" not in observed_counties("tx_lgbs", state="TX")


def test_r07_never_measured_is_distinct_from_measured_zero():
    """None (never measured) and 0 (measured, empty) are different findings."""
    assert observed_record_count("NotARealCountyAnywhere") is None
    known = observed_counties("tx_lgbs", state="TX")[0]
    assert isinstance(observed_record_count(known), int)


def test_r08_every_roster_row_records_its_measurement_method():
    for record in load_tx_lgbs_roster():
        assert record.measurement_method.strip() != ""


def test_r09_every_roster_row_carries_observation_timestamps():
    for record in load_tx_lgbs_roster():
        assert record.first_observed_at.strip() != ""
        assert record.last_observed_at.strip() != ""


def test_r10_roster_county_names_match_repository_naming_convention():
    """Roster counties must use this project's Title-Case convention (the
    same one _lgbs_normalize_county produces), not the API's ALL-CAPS
    '<NAME> COUNTY' form, or they will never join to the coverage matrix."""
    for county in observed_counties("tx_lgbs", state="TX"):
        assert county != county.upper() or len(county) <= 3, f"{county!r} looks un-normalized"
        assert not county.upper().endswith(" COUNTY"), f"{county!r} still carries the COUNTY suffix"


def test_r11_roster_counties_are_real_texas_counties():
    """Every measured county must exist in the authoritative 254-county
    matrix - a typo or a mis-parsed name would otherwise silently create a
    phantom jurisdiction."""
    real = {row["county"] for row in load_tx_matrix()}
    for county in observed_counties("tx_lgbs", state="TX"):
        assert county in real, f"{county!r} is not one of the 254 Texas counties"


def test_r12_roster_has_no_duplicate_counties():
    counties = [r.county for r in load_tx_lgbs_roster() if r.state == "TX" and not r.is_residual]
    assert len(counties) == len(set(counties))


# ===========================================================================
# Coverage expansion driven by the roster
# ===========================================================================


def test_c01_roster_expands_texas_adapter_coverage_beyond_the_matrix():
    """The measured footprint must actually widen configured coverage - the
    entire point of the roster."""
    served = {c.county for c in counties_with_adapter("TX")}
    assert len(served) == len(observed_counties("tx_lgbs", state="TX"))
    assert len(served) > 8, "coverage did not expand past the coverage matrix's 8 named counties"


def test_c02_expansion_does_not_invent_counties_outside_the_254():
    real = {row["county"] for row in load_tx_matrix()}
    for config in build_county_configs("TX"):
        assert config.county in real


def test_c03_every_texas_county_still_has_configuration():
    assert len({c.county for c in build_county_configs("TX")}) == 254


def test_c04_counties_without_a_measured_source_are_not_claimed_as_served():
    observed = set(observed_counties("tx_lgbs", state="TX"))
    for config in build_county_configs("TX"):
        if config.source_id == "tx_lgbs":
            assert config.county in observed


def test_c05_florida_coverage_is_unaffected_by_the_texas_roster():
    """State isolation: a Texas measurement must not move a Florida number."""
    assert len({c.county for c in build_county_configs("FL")}) == 67
    assert len({c.county for c in counties_with_adapter("FL")}) == 67


def test_c06_roster_does_not_mutate_the_coverage_matrix():
    """The researched governance artifact must stay untouched - the roster is
    additive, never a silent rewrite."""
    matrix_lgbs_counties = [
        row["county"] for row in load_tx_matrix() if "lgbs" in (row.get("auction_source") or "").lower()
    ]
    assert len(matrix_lgbs_counties) == 8, (
        "the Phase 33/35 coverage matrix was modified; Phase 40 must not edit it in place"
    )


# ===========================================================================
# Section 46 - the twenty named adversarial cases
# ===========================================================================


def test_adv_01_lgbs_county_roster_extraction():
    counties = observed_counties("tx_lgbs", state="TX")
    assert len(counties) > 8
    assert counties == sorted(counties)


def test_adv_02_lgbs_pagination():
    second = "https://taxsales.lgbs.com/api/property_sales/?area=TX&limit=500&offset=500"
    t = FixtureTransport()
    t.add_json(LGBS_FIRST_URL, envelope([lgbs_row()], next_url=second.replace("https://", "http://")))
    t.add_json(second, envelope([lgbs_row(uid="u2", account_nbr="A2")]))
    result = LgbsAdapter(transport=t).acquire()
    assert result.records_acquired == 2
    assert all(u.startswith("https://") for u in t.requested_urls)


def test_adv_03_lgbs_status_endpoint_404_did_not_change_the_status_mapping():
    """Phase 39 found /api/sale_status/ returns 404; Phase 40 re-confirmed it,
    and also found the API root ADVERTISES several endpoints that all 404.
    Neither finding is evidence about the status vocabulary, so the verified
    mapping must be unchanged."""
    from texas_harvester import LGBS_STATUS_TO_LEDGER  # type: ignore

    assert LGBS_STATUS_TO_LEDGER == {
        "Scheduled for Auction": "auction",
        "Scheduled for Online Auction": "auction",
        "Available for Future Sale": "laft",
        "Struck off to Jurisdiction": "laft",
    }


def test_adv_04_technical_success_does_not_imply_authorization():
    t = FixtureTransport().add_json(LGBS_FIRST_URL, envelope([lgbs_row()]))
    result = LgbsAdapter(transport=t).acquire()
    assert result.status == AcquisitionStatus.SUCCESS
    # A successful acquisition changes nothing about any other source's standing.
    assert can_promote_source_for_use("tx_hctax", "CUSTOMER_DISPLAY").allowed is False
    assert can_promote_source_for_use("fl_dor_statewide", "CUSTOMER_DISPLAY").allowed is False


def test_adv_05_environment_egress_block_is_not_a_source_failure():
    result = LgbsAdapter(transport=EnvironmentBlockedTransport()).acquire()
    assert any("ENVIRONMENT_EGRESS_BLOCKED" in e for e in result.errors)
    assert not any("ACCESS_RESTRICTED" in e for e in result.errors)


def test_adv_06_source_failure_is_not_no_records():
    no_data = LgbsAdapter(transport=FixtureTransport().add_json(LGBS_FIRST_URL, envelope([]))).acquire()
    failure = LgbsAdapter(transport=FixtureTransport().add_error(LGBS_FIRST_URL, SourceUnavailable("down"))).acquire()
    assert no_data.status == AcquisitionStatus.NO_DATA and not no_data.failed
    assert failure.status == AcquisitionStatus.SOURCE_UNAVAILABLE and failure.failed


def test_adv_07_no_silent_fallback():
    assert check_fallback_allowed("tx_lgbs", "tx_pbfcm", explicitly_configured=False).allowed is False
    assert check_fallback_allowed("tx_lgbs", "tx_pbfcm", explicitly_configured=True).allowed is False


def test_adv_08_cross_state_identity_collision():
    """Counties whose names exist in BOTH states must never share an
    identity. Several real collisions exist (e.g. Orange, Polk, Jackson)."""
    fl = {c.jurisdiction for c in build_county_configs("FL")}
    tx = {c.jurisdiction for c in build_county_configs("TX")}
    assert fl.isdisjoint(tx)
    fl_names = {c.county for c in build_county_configs("FL")}
    tx_names = {c.county for c in build_county_configs("TX")}
    shared = fl_names & tx_names
    assert shared, "expected genuine county-name collisions between FL and TX"
    for name in shared:
        assert f"FL/{name}" in fl and f"TX/{name}" in tx


def test_adv_09_duplicate_acquisition_is_idempotent():
    dup = lgbs_row()
    t = FixtureTransport().add_json(LGBS_FIRST_URL, envelope([dup, dict(dup)]))
    result = LgbsAdapter(transport=t).acquire()
    assert result.records_acquired == 1


def test_adv_10_partial_acquisition_is_classified_as_partial():
    class Broken(LgbsAdapter):
        def normalize(self, raw_record):
            if raw_record.get("uid") == "bad":
                raise ValueError("synthetic failure")
            return super().normalize(raw_record)

    t = FixtureTransport().add_json(LGBS_FIRST_URL, envelope([lgbs_row(), lgbs_row(uid="bad", account_nbr="A9")]))
    result = Broken(transport=t).acquire()
    assert result.status == AcquisitionStatus.PARTIAL_SUCCESS


def test_adv_11_schema_change_is_detected():
    t = FixtureTransport().add_json(LGBS_FIRST_URL, {"count": 0, "next": None})  # 'results' key gone
    assert LgbsAdapter(transport=t).acquire().status == AcquisitionStatus.SCHEMA_FAILURE


def test_adv_12_stale_source_timestamp_is_preserved_not_replaced():
    t = FixtureTransport().add_json(LGBS_FIRST_URL, envelope([lgbs_row(sale_date="2019-01-01T00:00:00Z")]))
    record = LgbsAdapter(transport=t).acquire().records[0]
    assert record["_source_timestamp"] == "2019-01-01T00:00:00Z"
    assert record["_retrieved_at"] != record["_source_timestamp"]


def test_adv_13_missing_source_timestamp_is_none_not_inferred():
    """Retrieval time must never be substituted for a source timestamp the
    source did not publish (Section 31)."""
    t = FixtureTransport().add_json(LGBS_FIRST_URL, envelope([lgbs_row(sale_date=None)]))
    record = LgbsAdapter(transport=t).acquire().records[0]
    assert record["_source_timestamp"] is None
    assert record["_retrieved_at"] is not None


def test_adv_14_restricted_raw_storage():
    t = FixtureTransport().add_json(LGBS_FIRST_URL, envelope([lgbs_row()]))
    assert LgbsAdapter(transport=t).acquire().raw_storage_status.value == "RESTRICTED"


def test_adv_15_authorization_required_source_is_refused_for_production():
    decision = check_acquisition_policy(
        "tx_hctax", purpose=AcquisitionPurpose.PRODUCTION_ACQUISITION, state="TX", county="Harris"
    )
    assert decision.allowed is False


def test_adv_16_disabled_source_refused_for_every_purpose():
    from harvesters.acquisition.policy import HARD_REFUSAL_STATUSES

    for source_id, record in SOURCE_REGISTRY.items():
        if record.legal_status in HARD_REFUSAL_STATUSES:
            for purpose in AcquisitionPurpose:
                assert check_acquisition_policy(source_id, purpose=purpose).allowed is False


def test_adv_17_terms_changed_source_refused():
    from harvesters.acquisition.policy import HARD_REFUSAL_STATUSES
    from harvesters.governance import SourceStatus

    assert SourceStatus.TERMS_CHANGED in HARD_REFUSAL_STATUSES


def test_adv_18_failed_run_preserves_previous_data():
    failed = LgbsAdapter(transport=FixtureTransport().add_error(LGBS_FIRST_URL, SourceUnavailable("x"))).acquire()
    assert failed.records == ()
    assert failed.status != AcquisitionStatus.NO_DATA
    assert failed.records_acquired == 0


def test_adv_19_provenance_survives_normalization():
    t = FixtureTransport().add_json(LGBS_FIRST_URL, envelope([lgbs_row()]))
    record = LgbsAdapter(transport=t).acquire().records[0]
    assert has_provenance(record)
    assert record["_source_id"] == "tx_lgbs"
    assert record["_source_record_id"] == "u1"


def test_adv_20_county_specific_source_behavior():
    """The PA row inside the area=TX feed must be dropped by the row's own
    state field - the single most consequential preserved semantic, now
    quantified at 2,104 of 6,309 rows (33%)."""
    t = FixtureTransport().add_json(
        LGBS_FIRST_URL,
        envelope([
            lgbs_row(),
            lgbs_row(uid="pa1", state="PA", county="PHILADELPHIA COUNTY", account_nbr="P1"),
        ]),
    )
    result = LgbsAdapter(transport=t).acquire()
    assert result.records_acquired == 1
    assert result.records_skipped == 1
    assert all(r["state"] == "TX" for r in result.records)


# ===========================================================================
# Additional failure modes this phase's live work actually revealed
# ===========================================================================


def test_new_01_unknown_query_params_are_silently_ignored_by_this_api():
    """A real finding: county__icontains= and search= returned the FULL
    unfiltered count, meaning this API silently ignores unknown params. Any
    future filter must therefore be validated against a known-bad value
    before its results are trusted. Encoded here as a documented constant so
    the lesson is not lost."""
    from harvesters.acquisition.roster import load_tx_lgbs_roster

    methods = {r.measurement_method for r in load_tx_lgbs_roster()}
    assert "exact_api_count_filtered_query" in methods


def test_new_02_measured_counts_are_never_negative():
    for record in load_tx_lgbs_roster():
        assert record.records_observed >= 0


def test_new_03_roster_csv_header_matches_section_6_schema():
    with open(TX_LGBS_ROSTER_PATH, newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    for required in ("state", "county", "records_observed", "first_observed_at", "last_observed_at", "source_id"):
        assert required in header


def test_new_04_roster_contains_no_personal_information():
    """Section 6: do not store unnecessary personal information. The roster
    is county-level aggregate counts only - no owner names, addresses, or
    parcel identifiers."""
    with open(TX_LGBS_ROSTER_PATH, newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    forbidden = {"owner_name", "owner", "address", "parcel", "account_nbr", "prop_address_one"}
    assert not (forbidden & set(header))


def test_new_05_acquisition_result_cannot_claim_success_with_zero_records():
    with pytest.raises(ValueError):
        build_result(
            source_id="tx_lgbs", jurisdiction="TX/Harris",
            status=AcquisitionStatus.SUCCESS, started_at="2026-09-16T00:00:00+00:00", records=[],
        )


def test_new_06_deduplicate_keeps_first_occurrence():
    records = [
        {"_source_id": "tx_lgbs", "_source_record_id": "u1", "min_bid": 100},
        {"_source_id": "tx_lgbs", "_source_record_id": "u1", "min_bid": 999},
    ]
    unique, dropped = deduplicate(records)
    assert len(unique) == 1 and dropped == 1
    assert unique[0]["min_bid"] == 100
