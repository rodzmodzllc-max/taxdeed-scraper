"""Tests for the Phase 39 acquisition engine - harvesters/acquisition/.

Two blocks:

  A. Section 49's adapter test harness - success, empty, malformed,
     timeout, HTTP error, rate limiting, schema change, missing required
     field, duplicate record, partial response, pagination, source
     unavailable, authorization restriction. All fixture-driven; this file
     makes ZERO external network calls (Section 49's explicit requirement).

  B. Section 50's twenty named adversarial cases, each testing a property
     that must hold for the engine to be safe to run at all.

The fixtures reproduce the real, live-verified response SHAPES recorded in
each adapter's docstring (LGBS's DRF envelope and 29 result fields; HCAD's
and FDOR's ArcGIS feature/attributes envelopes) with SYNTHETIC values.
That is deliberate: storing real source records in this repository would
be retaining and redistributing source content whose rights are exactly
what Phases 34A/37 left unresolved, so the tests exercise the real parse
path without baking in real property data.
"""

from __future__ import annotations

import json

import pytest

from harvesters.acquisition import (
    AccessRestricted,
    AcquisitionPurpose,
    AcquisitionResult,
    AcquisitionStatus,
    AuthenticationRequired,
    CircuitBreaker,
    CoverageMetrics,
    DataCategory,
    EnvironmentBlockedTransport,
    EnvironmentEgressBlocked,
    FixtureTransport,
    MissingDataReason,
    RateLimited,
    RateLimitPolicy,
    RawStorageStatus,
    SchemaError,
    SourceHealth,
    SourceUnavailable,
    TransportResponse,
    build_county_configs,
    build_result,
    check_acquisition_policy,
    check_fallback_allowed,
    classify_missing,
    content_hash,
    counties_with_adapter,
    deduplicate,
    detect_conflicts,
    field_coverage,
    has_provenance,
    idempotency_key,
    mechanism_summary,
    metrics_from_results,
)
from harvesters.acquisition.adapters import ArcGisAdapter, LgbsAdapter
from harvesters.acquisition.adapters.arcgis import FDOR_COUNTY_CODES, FDOR_LAYER, HCAD_LAYER, TAD_LAYER
from harvesters.acquisition.checkpoint import Checkpoint, CheckpointStore
from harvesters.governance import SOURCE_REGISTRY, can_promote_source_for_use

LGBS_FIRST_URL = "https://taxsales.lgbs.com/api/property_sales/?area=TX&limit=500"
LGBS_SECOND_URL = "https://taxsales.lgbs.com/api/property_sales/?area=TX&limit=500&offset=500"


def lgbs_row(**overrides) -> dict:
    """One LGBS result object in the real, live-verified field shape."""
    row = {
        "uid": "u1",
        "sale_id": 101,
        "state": "TX",
        "county": "HARRIS COUNTY",
        "status": "Scheduled for Auction",
        "sale_type": "SALE",
        "account_nbr": "A1",
        "cause_nbr": "C1",
        "sale_date": "2026-10-06T10:00:00Z",
        "sale_date_only": "2026-10-06",
        "minimum_bid": "1000.00",
        "value": "50000",
        "sale_notes": "LOT 1 BLK 2",
        "prop_address_one": "1 Main St",
        "prop_city": "HOUSTON",
        "prop_zipcode": "77002",
        "geometry": {"coordinates": [-95.37, 29.76]},
    }
    row.update(overrides)
    return row


def lgbs_envelope(results, next_url=None) -> dict:
    return {"count": len(results), "next": next_url, "previous": None, "results": results}


def hcad_features(**attr_overrides) -> dict:
    attrs = {
        "HCAD_NUM": "1011020000003",
        "state_class": "A1",
        "land_use": "1001",
        "total_market_val": 199689.0,
        "land_value": 61382.0,
        "bld_value": 138307.0,
        "Acreage": None,
        "land_sqft": 7697.0,
    }
    attrs.update(attr_overrides)
    return {"features": [{"attributes": attrs}]}


def fdor_features(**attr_overrides) -> dict:
    attrs = {
        "PARCEL_ID": "07702-000-000",
        "CO_NO": 11,
        "ASMNT_YR": 2025,
        "JV": 144984,
        "AV_NSD": 84709,
        "LND_VAL": 0,
        "DOR_UC": "052",
        "OWN_NAME": " SMITH JOHN ",
        "ACT_YR_BLT": 1958,
        "TOT_LVG_AR": 1840,
        "LND_SQFOOT": 16456,
        "NO_BULDNG": 1,
        "S_LEGAL": "LOT 4 BLK 2",
        "PHY_ADDR1": "123 MAIN ST",
        "SALE_PRC1": 0,
        "SALE_YR1": 0,
        "JV_HMSTD": 0,
    }
    attrs.update(attr_overrides)
    return {"features": [{"attributes": attrs}]}


def lgbs_adapter(transport: FixtureTransport) -> LgbsAdapter:
    return LgbsAdapter(transport=transport)


def hcad_adapter(transport: FixtureTransport) -> ArcGisAdapter:
    return ArcGisAdapter(HCAD_LAYER, transport=transport, source_id="tx_hctax")


def fdor_adapter(transport: FixtureTransport) -> ArcGisAdapter:
    return ArcGisAdapter(FDOR_LAYER, transport=transport, source_id="fl_dor_statewide")


TESTING = AcquisitionPurpose.INTERNAL_TECHNICAL_TESTING


# ===========================================================================
# A. Section 49 - adapter test harness
# ===========================================================================


def test_a01_successful_acquisition():
    t = FixtureTransport().add_json(LGBS_FIRST_URL, lgbs_envelope([lgbs_row()]))
    result = lgbs_adapter(t).acquire()
    assert result.status == AcquisitionStatus.SUCCESS
    assert result.records_acquired == 1
    assert result.records[0]["county"] == "Harris"
    assert result.records[0]["source"] == "auction"


def test_a02_empty_response_is_no_data_not_success():
    """An empty result set means the source published nothing - it must be
    distinguishable from both success and failure."""
    t = FixtureTransport().add_json(LGBS_FIRST_URL, lgbs_envelope([]))
    result = lgbs_adapter(t).acquire()
    assert result.status == AcquisitionStatus.NO_DATA
    assert result.records_acquired == 0
    assert not result.succeeded
    assert not result.failed


def test_a03_malformed_response_is_schema_failure():
    t = FixtureTransport()
    t.responses[LGBS_FIRST_URL] = TransportResponse(
        url=LGBS_FIRST_URL, http_status=200, body=b"<html>not json</html>", content_type="text/html"
    )
    result = lgbs_adapter(t).acquire()
    assert result.status == AcquisitionStatus.SCHEMA_FAILURE


def test_a04_missing_results_key_is_schema_failure_not_no_data():
    """A response envelope that lost its 'results' key is a SCHEMA change,
    never an empty day - conflating them would silently zero out a county."""
    t = FixtureTransport().add_json(LGBS_FIRST_URL, {"count": 0, "next": None})
    result = lgbs_adapter(t).acquire()
    assert result.status == AcquisitionStatus.SCHEMA_FAILURE


def test_a05_timeout_is_source_unavailable():
    t = FixtureTransport().add_error(LGBS_FIRST_URL, SourceUnavailable("timeout after 30s"))
    result = lgbs_adapter(t).acquire()
    assert result.status == AcquisitionStatus.SOURCE_UNAVAILABLE
    assert result.failed


def test_a06_http_error_classified_specifically():
    from harvesters.acquisition.transport import _classify_http_error

    assert isinstance(_classify_http_error(401, "u"), AuthenticationRequired)
    assert isinstance(_classify_http_error(403, "u"), AccessRestricted)
    assert isinstance(_classify_http_error(429, "u"), RateLimited)
    assert isinstance(_classify_http_error(404, "u"), SourceUnavailable)
    assert isinstance(_classify_http_error(503, "u"), SourceUnavailable)


def test_a07_rate_limited_has_its_own_status():
    t = FixtureTransport().add_error(LGBS_FIRST_URL, RateLimited("HTTP 429"))
    result = lgbs_adapter(t).acquire()
    assert result.status == AcquisitionStatus.RATE_LIMITED
    assert result.status != AcquisitionStatus.TECHNICAL_FAILURE


def test_a08_schema_change_detected_by_payload_hash():
    health = SourceHealth(source_id="tx_lgbs")
    t1 = FixtureTransport().add_json(LGBS_FIRST_URL, lgbs_envelope([lgbs_row()]))
    r1 = lgbs_adapter(t1).acquire()
    t2 = FixtureTransport().add_json(LGBS_FIRST_URL, lgbs_envelope([lgbs_row(sale_notes="CHANGED")]))
    r2 = lgbs_adapter(t2).acquire()
    for retrieval in list(r1.retrievals) + list(r2.retrievals):
        health.schema_hashes.add(retrieval.content_hash_value)
    assert health.schema_changed is True


def test_a09_record_missing_required_field_is_skipped_not_fabricated():
    """A row with no account number cannot be given one - it is skipped,
    and the skip is counted."""
    t = FixtureTransport().add_json(
        LGBS_FIRST_URL, lgbs_envelope([lgbs_row(account_nbr=None), lgbs_row(uid="u2", account_nbr="A2")])
    )
    result = lgbs_adapter(t).acquire()
    assert result.records_acquired == 1
    assert result.records_skipped == 1
    assert result.records_seen == 2


def test_a10_duplicate_records_deduplicated_keeping_first():
    dup = lgbs_row()
    t = FixtureTransport().add_json(LGBS_FIRST_URL, lgbs_envelope([dup, dict(dup)]))
    result = lgbs_adapter(t).acquire()
    assert result.records_acquired == 1
    assert any("duplicate" in w for w in result.warnings)


def test_a11_partial_success_when_some_records_fail_normalization():
    class BrokenAdapter(LgbsAdapter):
        def normalize(self, raw_record):
            if raw_record.get("uid") == "bad":
                raise ValueError("synthetic normalization failure")
            return super().normalize(raw_record)

    t = FixtureTransport().add_json(
        LGBS_FIRST_URL, lgbs_envelope([lgbs_row(), lgbs_row(uid="bad", account_nbr="A9")])
    )
    result = BrokenAdapter(transport=t).acquire()
    assert result.status == AcquisitionStatus.PARTIAL_SUCCESS
    assert result.records_acquired == 1
    assert result.records_failed == 1


def test_a12_pagination_follows_next_and_upgrades_http_to_https():
    t = FixtureTransport()
    t.add_json(LGBS_FIRST_URL, lgbs_envelope([lgbs_row()], next_url=LGBS_SECOND_URL.replace("https://", "http://")))
    t.add_json(LGBS_SECOND_URL, lgbs_envelope([lgbs_row(uid="u2", account_nbr="A2")]))
    result = lgbs_adapter(t).acquire()
    assert result.records_acquired == 2
    assert len(t.requested_urls) == 2
    assert all(u.startswith("https://") for u in t.requested_urls)


def test_a13_source_unavailable_when_no_fixture_registered():
    result = lgbs_adapter(FixtureTransport()).acquire()
    assert result.status == AcquisitionStatus.SOURCE_UNAVAILABLE


def test_a14_authorization_restriction_short_circuits_before_any_request():
    """A denied policy must stop the run BEFORE a request is made - the
    fixture transport records zero URLs."""
    t = FixtureTransport().add_json(LGBS_FIRST_URL, lgbs_envelope([lgbs_row()]))
    adapter = hcad_adapter(t)  # tx_hctax is LEGAL_REVIEW_REQUIRED
    result = adapter.acquire_parcels(["1011020000003"])
    assert result.status == AcquisitionStatus.LEGAL_RESTRICTION
    assert t.requested_urls == []


def test_a15_limit_stops_pagination_early():
    t = FixtureTransport()
    t.add_json(LGBS_FIRST_URL, lgbs_envelope([lgbs_row(), lgbs_row(uid="u2", account_nbr="A2")], next_url=LGBS_SECOND_URL))
    result = lgbs_adapter(t).acquire(limit=1)
    assert result.records_acquired == 1
    assert len(t.requested_urls) == 1


def test_a16_arcgis_adapter_acquires_under_testing_purpose():
    t = FixtureTransport()
    adapter = hcad_adapter(t)
    t.add_json(adapter.build_query_url("1011020000003"), hcad_features())
    result = adapter.acquire_parcels(["1011020000003"], purpose=TESTING)
    assert result.status == AcquisitionStatus.SUCCESS
    record = result.records[0]
    assert record["cad_market_value"] == 199689.0
    assert record["tx_category"] == "A1"


def test_a17_arcgis_error_envelope_is_schema_failure():
    t = FixtureTransport()
    adapter = hcad_adapter(t)
    t.add_json(adapter.build_query_url("X"), {"error": {"code": 400, "message": "Invalid where clause"}})
    result = adapter.acquire_parcels(["X"], purpose=TESTING)
    assert result.status == AcquisitionStatus.SCHEMA_FAILURE


def test_a18_arcgis_parcel_not_in_layer_is_skipped_not_failed():
    t = FixtureTransport()
    adapter = hcad_adapter(t)
    t.add_json(adapter.build_query_url("NOPE"), {"features": []})
    result = adapter.acquire_parcels(["NOPE"], purpose=TESTING)
    assert result.status == AcquisitionStatus.NO_DATA
    assert result.records_skipped == 1
    assert result.records_failed == 0


def test_a19_arcgis_with_no_parcels_is_not_applicable():
    result = hcad_adapter(FixtureTransport()).acquire_parcels([], purpose=TESTING)
    assert result.status == AcquisitionStatus.NOT_APPLICABLE


def test_a20_florida_statewide_county_scoped_query_works():
    t = FixtureTransport()
    adapter = fdor_adapter(t)
    url = adapter.build_county_query_url("Alachua", result_record_count=100)
    t.add_json(url, fdor_features())
    result = adapter.acquire_county("Alachua", limit=100, purpose=TESTING)
    assert result.status == AcquisitionStatus.SUCCESS
    assert result.jurisdiction == "FL/Alachua"
    record = result.records[0]
    assert record["market"] == 144984.0
    assert record["assessed"] == 84709.0
    assert record["value_year"] == 2025


def test_a21_fdor_zero_is_no_data_sentinel_not_a_real_zero():
    """FDOR's documented 0-as-no-data rule, preserved from
    enrich_property_details.py::_num."""
    t = FixtureTransport()
    adapter = fdor_adapter(t)
    t.add_json(adapter.build_county_query_url("Alachua", result_record_count=100), fdor_features())
    record = adapter.acquire_county("Alachua", limit=100, purpose=TESTING).records[0]
    assert record["land_value"] is None  # LND_VAL was 0
    assert record["last_sale_price"] is None  # SALE_PRC1 was 0
    assert record["market"] == 144984.0  # a real value is untouched


def test_a22_fdor_county_codes_match_the_production_script():
    """The county-code table in the adapter must agree with the one the
    production Florida enrichment script already uses - read from that
    script's own source text, not re-declared here."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "scripts" / "enrich_property_details.py").read_text()
    for county, code in FDOR_COUNTY_CODES.items():
        assert f'"{county}": {code}' in source, f"{county}:{code} disagrees with enrich_property_details.py"
    assert len(FDOR_COUNTY_CODES) == 67


def test_a23_fdor_sentinel_rule_matches_the_production_script_text():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "scripts" / "enrich_property_details.py").read_text()
    assert "return num if num > 0 else None" in source


def test_a24_unknown_county_for_statewide_layer_raises_rather_than_guessing():
    with pytest.raises(ValueError):
        fdor_adapter(FixtureTransport()).build_county_query_url("Nowhere")


def test_a25_layer_without_county_field_refuses_county_query():
    with pytest.raises(ValueError):
        hcad_adapter(FixtureTransport()).build_county_query_url("Harris")


# ===========================================================================
# Transport, checkpoints, metrics
# ===========================================================================


def test_b01_circuit_breaker_trips_after_threshold_and_resets_on_success():
    breaker = CircuitBreaker(threshold=3)
    for _ in range(2):
        breaker.record_failure()
    assert not breaker.tripped
    breaker.record_failure()
    assert breaker.tripped
    breaker.record_success()
    assert not breaker.tripped


def test_b02_backoff_is_exponential_capped_and_jittered():
    policy = RateLimitPolicy(backoff_base_seconds=1.0, backoff_max_seconds=8.0, jitter_seconds=0.0)
    assert policy.backoff_for(1) == 1.0
    assert policy.backoff_for(2) == 2.0
    assert policy.backoff_for(3) == 4.0
    assert policy.backoff_for(9) == 8.0  # capped


def test_b03_environment_block_is_distinct_from_source_failure():
    """A sandbox egress refusal must never be recorded as a finding about
    the source - this distinction is why EnvironmentEgressBlocked exists."""
    result = lgbs_adapter(EnvironmentBlockedTransport()).acquire()
    assert result.status == AcquisitionStatus.SOURCE_UNAVAILABLE
    assert any("ENVIRONMENT_EGRESS_BLOCKED" in e for e in result.errors)
    assert not any("ACCESS_RESTRICTED" in e for e in result.errors)


def test_b04_checkpoint_round_trips_and_is_jurisdiction_scoped(tmp_path):
    store = CheckpointStore(tmp_path / "cp.json")
    store.save(Checkpoint(source_id="tx_lgbs", state="TX", county="Harris", page=3))
    store.save(Checkpoint(source_id="tx_lgbs", state="TX", county="Dallas", page=7))
    assert store.load("tx_lgbs", state="TX", county="Harris").page == 3
    assert store.load("tx_lgbs", state="TX", county="Dallas").page == 7
    assert store.load("tx_lgbs", state="TX", county="Travis") is None


def test_b05_acquisition_emits_resumable_checkpoint_on_partial_walk():
    t = FixtureTransport()
    t.add_json(LGBS_FIRST_URL, lgbs_envelope([lgbs_row(), lgbs_row(uid="u2", account_nbr="A2")], next_url=LGBS_SECOND_URL))
    result = lgbs_adapter(t).acquire(limit=1)
    assert result.checkpoint is not None


def test_b06_acquisition_resumes_from_checkpoint_url():
    t = FixtureTransport().add_json(LGBS_SECOND_URL, lgbs_envelope([lgbs_row(uid="u2", account_nbr="A2")]))
    result = lgbs_adapter(t).acquire(checkpoint={"next_url": LGBS_SECOND_URL})
    assert result.records_acquired == 1
    assert t.requested_urls == [LGBS_SECOND_URL]


def test_b07_corrupt_checkpoint_store_does_not_crash(tmp_path):
    path = tmp_path / "cp.json"
    path.write_text("{ not json")
    assert CheckpointStore(path).load("tx_lgbs", state="TX") is None


def test_b08_coverage_percentage_is_none_without_a_real_denominator():
    metrics = CoverageMetrics(
        state="TX", county="Harris", source_id="tx_lgbs", category="AUCTION",
        records_expected=None, records_discovered=10, records_acquired=8,
        records_normalized=8, records_failed=0, records_restricted=0,
    )
    assert metrics.coverage_percentage is None


def test_b09_coverage_percentage_computed_when_denominator_is_known():
    metrics = CoverageMetrics(
        state="TX", county="Harris", source_id="tx_lgbs", category="AUCTION",
        records_expected=10000, records_discovered=9850, records_acquired=9850,
        records_normalized=9850, records_failed=0, records_restricted=0,
    )
    assert metrics.coverage_percentage == 98.5


def test_b10_field_coverage_counts_nulls_as_missing():
    records = [{"bid": 1}, {"bid": None}, {"bid": 3}, {}]
    with_value, total, pct = field_coverage(records, "bid")
    assert (with_value, total, pct) == (2, 4, 50.0)


def test_b11_source_health_tracks_success_and_failure_rates():
    health = SourceHealth(source_id="tx_lgbs")
    t = FixtureTransport().add_json(LGBS_FIRST_URL, lgbs_envelope([lgbs_row()]))
    health.record(lgbs_adapter(t).acquire())
    health.record(lgbs_adapter(FixtureTransport().add_error(LGBS_FIRST_URL, SourceUnavailable("x"))).acquire())
    assert health.attempts == 2
    assert health.successes == 1
    assert health.failures == 1
    assert health.success_rate == 0.5


def test_b12_metrics_last_success_only_advances_on_real_records():
    empty = build_result(
        source_id="tx_lgbs", jurisdiction="TX/Harris",
        status=AcquisitionStatus.NO_DATA, started_at="2026-09-16T00:00:00+00:00",
    )
    metrics = metrics_from_results([empty], state="TX", county="Harris", source_id="tx_lgbs")
    assert metrics.last_attempt is not None
    assert metrics.last_success is None


def test_b13_conflicting_values_are_recorded_not_overwritten():
    records = [
        {"_source_id": "a", "market": 400000, "_retrieved_at": "t1"},
        {"_source_id": "b", "market": 425000, "_retrieved_at": "t2"},
    ]
    conflict = detect_conflicts(records, "market")
    assert conflict.is_conflict is True
    assert len(conflict.values) == 2


def test_b14_missing_data_reason_never_collapses_legal_into_technical():
    legal = classify_missing(field_present=False, acquisition_status=AcquisitionStatus.LEGAL_RESTRICTION)
    technical = classify_missing(field_present=False, acquisition_status=AcquisitionStatus.TECHNICAL_FAILURE)
    assert legal == MissingDataReason.LEGAL_RESTRICTION
    assert technical == MissingDataReason.TECHNICAL_FAILURE
    assert legal != technical


def test_b15_missing_data_reason_distinguishes_never_attempted():
    assert classify_missing(field_present=False, acquisition_status=None) == MissingDataReason.NOT_YET_ACQUIRED
    assert classify_missing(field_present=True, acquisition_status=None) is None


# ===========================================================================
# B. Section 50 - the twenty named adversarial cases
# ===========================================================================


def test_adv_01_unauthorized_source_cannot_become_production():
    for source_id in ("tx_hctax", "fl_dor_statewide"):
        decision = check_acquisition_policy(source_id, purpose=AcquisitionPurpose.PRODUCTION_ACQUISITION)
        assert decision.allowed is False


def test_adv_02_technical_success_does_not_imply_authorization():
    """The engine can fully, successfully acquire from a source whose
    production promotion is still denied. Both facts must be true at once."""
    t = FixtureTransport()
    adapter = hcad_adapter(t)
    t.add_json(adapter.build_query_url("1011020000003"), hcad_features())
    technical = adapter.acquire_parcels(["1011020000003"], purpose=TESTING)
    assert technical.status == AcquisitionStatus.SUCCESS
    assert can_promote_source_for_use("tx_hctax", "CUSTOMER_DISPLAY").allowed is False


def test_adv_03_legal_review_source_cannot_become_customer_visible():
    for source_id in ("tx_hctax", "fl_dor_statewide", "fl_realauction", "fl_lienhub_certificates"):
        assert can_promote_source_for_use(source_id, "CUSTOMER_DISPLAY", county="Alachua").allowed is False


def test_adv_04_blocked_source_cannot_be_used_as_a_fallback():
    decision = check_fallback_allowed(
        "tx_lgbs", "tx_pbfcm", explicitly_configured=True, county="Harris", state="TX"
    )
    assert decision.allowed is False


def test_adv_04b_unconfigured_fallback_is_refused_even_if_approved():
    """Silent substitution is refused on its own, before the fallback's own
    status is even considered."""
    decision = check_fallback_allowed("fl_laft_pdfs", "tx_lgbs", explicitly_configured=False)
    assert decision.allowed is False
    assert "not an explicitly configured fallback" in decision.reason


def test_adv_05_source_state_remains_county_specific():
    fl = build_county_configs("FL")
    alachua = {c.source_id for c in fl if c.county == "Alachua"}
    baker = {c.source_id for c in fl if c.county == "Baker"}
    assert alachua != baker  # Baker has no LAFT source; Alachua does
    assert "fl_laft_pdfs" in alachua


def test_adv_06_florida_and_texas_identities_cannot_collide():
    """Every jurisdiction string is state-qualified, so a county name
    appearing in both states can never produce one identity."""
    fl = {c.jurisdiction for c in build_county_configs("FL")}
    tx = {c.jurisdiction for c in build_county_configs("TX")}
    assert fl.isdisjoint(tx)
    assert all(j.startswith("FL/") for j in fl)
    assert all(j.startswith("TX/") for j in tx)


def test_adv_07_duplicate_source_records_reconcile_correctly():
    records = [
        {"_source_id": "tx_lgbs", "_source_record_id": "u1", "min_bid": 100},
        {"_source_id": "tx_lgbs", "_source_record_id": "u1", "min_bid": 150},
        {"_source_id": "tx_lgbs", "_source_record_id": "u2", "min_bid": 200},
    ]
    unique, dropped = deduplicate(records)
    assert len(unique) == 2
    assert dropped == 1
    assert unique[0]["min_bid"] == 100  # first wins; a later partial never overwrites


def test_adv_08_source_schema_change_is_detected():
    a = content_hash(json.dumps(lgbs_envelope([lgbs_row()]), sort_keys=True))
    b = content_hash(json.dumps(lgbs_envelope([lgbs_row(sale_notes="X")]), sort_keys=True))
    assert a != b
    health = SourceHealth(source_id="tx_lgbs")
    health.schema_hashes.update({a, b})
    assert health.schema_changed


def test_adv_09_missing_data_gets_correct_reason():
    cases = {
        AcquisitionStatus.NO_DATA: MissingDataReason.NOT_AVAILABLE_AT_SOURCE,
        AcquisitionStatus.SOURCE_UNAVAILABLE: MissingDataReason.SOURCE_UNAVAILABLE,
        AcquisitionStatus.RATE_LIMITED: MissingDataReason.TEMPORARILY_UNAVAILABLE,
        AcquisitionStatus.ACCESS_RESTRICTED: MissingDataReason.LEGAL_RESTRICTION,
        AcquisitionStatus.NOT_APPLICABLE: MissingDataReason.NOT_APPLICABLE,
    }
    for status, expected in cases.items():
        assert classify_missing(field_present=False, acquisition_status=status) == expected


def test_adv_10_stale_source_is_reported():
    metrics = CoverageMetrics(
        state="TX", county="Harris", source_id="tx_lgbs", category=None,
        records_expected=None, records_discovered=1, records_acquired=1,
        records_normalized=1, records_failed=0, records_restricted=0,
        last_success="2020-01-01T00:00:00+00:00",
    )
    assert metrics.freshness_seconds > 60 * 60 * 24 * 365


def test_adv_11_restricted_binary_content_is_not_stored():
    """Every configured adapter defaults to raw_storage RESTRICTED, and no
    adapter this phase retains image or document bytes."""
    t = FixtureTransport().add_json(LGBS_FIRST_URL, lgbs_envelope([lgbs_row()]))
    result = lgbs_adapter(t).acquire()
    assert result.raw_storage_status == RawStorageStatus.RESTRICTED
    assert DataCategory.IMAGE not in lgbs_adapter(t).categories
    assert DataCategory.DOCUMENT not in lgbs_adapter(t).categories


def test_adv_11b_binary_promotion_uses_are_checked_separately():
    from harvesters.acquisition import binary_content_allowed

    assert binary_content_allowed("fl_realauction", kind="IMAGE", county="Alachua").allowed is False
    assert binary_content_allowed("fl_realauction", kind="DOCUMENT", county="Alachua").allowed is False


def test_adv_12_api_and_export_restrictions_remain_enforced():
    for use in ("CUSTOMER_EXPORT", "API"):
        assert can_promote_source_for_use("fl_lienhub_certificates", use, county="Alachua").allowed is False


def test_adv_13_source_disablement_prevents_new_acquisition():
    from harvesters.acquisition.policy import HARD_REFUSAL_STATUSES
    from harvesters.governance import SourceStatus

    assert SourceStatus.DISABLED in HARD_REFUSAL_STATUSES
    for source_id, record in SOURCE_REGISTRY.items():
        if record.legal_status in HARD_REFUSAL_STATUSES:
            for purpose in AcquisitionPurpose:
                assert check_acquisition_policy(source_id, purpose=purpose).allowed is False


def test_adv_14_terms_change_does_not_silently_preserve_approval():
    from harvesters.acquisition.policy import HARD_REFUSAL_STATUSES
    from harvesters.governance import SourceStatus

    assert SourceStatus.TERMS_CHANGED in HARD_REFUSAL_STATUSES


def test_adv_15_failed_acquisition_does_not_delete_valid_prior_data():
    """A failed run carries zero records and cannot be mistaken for an
    authoritative empty set that would clear a prior successful load."""
    failed = lgbs_adapter(FixtureTransport().add_error(LGBS_FIRST_URL, SourceUnavailable("down"))).acquire()
    assert failed.records == ()
    assert failed.failed is True
    assert failed.succeeded is False
    assert failed.status != AcquisitionStatus.NO_DATA


def test_adv_16_source_timestamp_is_preserved():
    t = FixtureTransport().add_json(LGBS_FIRST_URL, lgbs_envelope([lgbs_row()]))
    record = lgbs_adapter(t).acquire().records[0]
    assert record["_source_timestamp"] == "2026-10-06T10:00:00Z"


def test_adv_17_provenance_survives_normalization():
    t = FixtureTransport().add_json(LGBS_FIRST_URL, lgbs_envelope([lgbs_row()]))
    record = lgbs_adapter(t).acquire().records[0]
    assert has_provenance(record)
    assert record["_source_id"] == "tx_lgbs"
    assert record["_source_record_id"] == "u1"
    assert record["_retrieved_at"]


def test_adv_17b_source_native_values_preserved_beside_normalized_ones():
    t = FixtureTransport().add_json(LGBS_FIRST_URL, lgbs_envelope([lgbs_row()]))
    record = lgbs_adapter(t).acquire().records[0]
    assert record["_source_status"] == "Scheduled for Auction"
    assert record["_source_sale_type"] == "SALE"
    assert record["source"] == "auction"  # normalized ledger, derived from status not sale_type


def test_adv_18_derived_fields_retain_calculation_provenance():
    """The engine's normalization version travels with every record, so a
    value produced by a different normalization revision is identifiable."""
    t = FixtureTransport().add_json(LGBS_FIRST_URL, lgbs_envelope([lgbs_row()]))
    record = lgbs_adapter(t).acquire().records[0]
    assert record["_normalization_version"] == "1"


def test_adv_19_source_failure_distinguishable_from_no_records():
    no_data = lgbs_adapter(FixtureTransport().add_json(LGBS_FIRST_URL, lgbs_envelope([]))).acquire()
    failure = lgbs_adapter(FixtureTransport().add_error(LGBS_FIRST_URL, SourceUnavailable("down"))).acquire()
    assert no_data.status == AcquisitionStatus.NO_DATA
    assert failure.status == AcquisitionStatus.SOURCE_UNAVAILABLE
    assert no_data.failed is False
    assert failure.failed is True


def test_adv_20_one_county_failure_does_not_mark_the_state_successful():
    good = build_result(
        source_id="fl_dor_statewide", jurisdiction="FL/Alachua",
        status=AcquisitionStatus.SUCCESS, started_at="2026-09-16T00:00:00+00:00",
        records=[{"parcel": "1"}],
    )
    bad = build_result(
        source_id="fl_dor_statewide", jurisdiction="FL/Baker",
        status=AcquisitionStatus.SOURCE_UNAVAILABLE, started_at="2026-09-16T00:00:00+00:00",
    )
    assert good.jurisdiction != bad.jurisdiction
    assert good.succeeded and bad.failed
    per_county = {r.jurisdiction: r.status for r in (good, bad)}
    assert per_county["FL/Baker"] == AcquisitionStatus.SOURCE_UNAVAILABLE


# ===========================================================================
# Structural guarantees
# ===========================================================================


def test_c01_no_generic_failed_status_exists():
    assert "FAILED" not in {s.value for s in AcquisitionStatus}


def test_c02_success_with_zero_records_is_unrepresentable():
    with pytest.raises(ValueError):
        AcquisitionResult(
            source_id="x", jurisdiction="TX/Harris",
            status=AcquisitionStatus.SUCCESS, started_at="2026-09-16T00:00:00+00:00",
        )


def test_c03_result_cannot_overstate_records_it_holds():
    with pytest.raises(ValueError):
        AcquisitionResult(
            source_id="x", jurisdiction="TX/Harris",
            status=AcquisitionStatus.SUCCESS, started_at="2026-09-16T00:00:00+00:00",
            records=({"a": 1},), records_acquired=99,
        )


def test_c04_retrieval_metadata_has_no_credential_field():
    from harvesters.acquisition import RetrievalMetadata

    forbidden = {"token", "api_key", "apikey", "password", "secret", "authorization", "cookie", "service_key"}
    assert not (forbidden & set(RetrievalMetadata.__dataclass_fields__))


def test_c05_result_summary_excludes_records_by_default():
    t = FixtureTransport().add_json(LGBS_FIRST_URL, lgbs_envelope([lgbs_row()]))
    payload = lgbs_adapter(t).acquire().to_dict()
    assert "records" not in payload


def test_c06_every_county_in_both_states_has_configuration():
    assert len({c.county for c in build_county_configs("FL")}) == 67
    assert len({c.county for c in build_county_configs("TX")}) == 254


def test_c07_adapters_serve_many_jurisdictions_not_one_scraper_each():
    """Section 5's core requirement, measured: two adapters cover every
    county-source pair that has an implemented mechanism."""
    served = counties_with_adapter("FL") + counties_with_adapter("TX")
    mechanisms = {c.mechanism for c in served}
    assert len(mechanisms) <= 2
    assert len(served) > 50


def test_c08_unimplemented_mechanisms_are_not_claimed_as_acquirable():
    for state in ("FL", "TX"):
        for config in build_county_configs(state):
            if config.mechanism.value in ("HTML_PUBLIC_SEARCH", "DOCUMENT_PDF", "NONE", "LICENSED_PROVIDER"):
                assert config.adapter_available is False


def test_c09_mechanism_summary_counts_every_config_row():
    for state in ("FL", "TX"):
        assert sum(mechanism_summary(state).values()) == len(build_county_configs(state))


def test_c10_idempotency_key_prefers_source_record_id():
    assert idempotency_key({"_source_id": "s", "_source_record_id": "r"}) == ("s", "r")
    fallback = idempotency_key({"state": "TX", "_source_id": "s", "county": "Harris", "case_no": "A1"})
    assert fallback == ("TX", "s", "Harris", "A1")
