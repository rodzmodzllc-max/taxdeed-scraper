"""AVAILABLE execution sprint (2026-10-01): conditional tax-roll columns
(acreage only where the source says the unit is acres), "not classified"
values never stored, multi-year rolls resolved to the latest year, raw source
classification kept in provenance, and the LGBS AVAILABLE refresh - exact
matching, ambiguity failing closed, no close on absence, no weaker-value
overwrite, stamping only after a complete walk, pagination past 1,000 rows."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "harvesters"))
import lgbs_available_refresh as L  # noqa: E402
from harvesters.enrichment import parcels as P  # noqa: E402

NOW = "2026-10-01T23:30:00+00:00"


def roll_cfg(**kw):
    base = dict(source_id="t_roll", state="LA", agency="A", dataset="Roll", landing_url="https://x.example/d/abcd-1234",
                layer_url="https://x.example/resource/abcd-1234.json", transport="socrata", id_field="assessment_no",
                id_rule="exact", field_map={"land_use": "structure_use", "legal_desc": "legal_description"},
                conditional_map={"acreage": ("units", "unit_type", ("ACREAGE",))},
                no_value={"land_use": ("NOT DETERMINED",)}, provenance_attrs=("unit_type", "vacant_lot_yn"),
                latest_field="tax_year", licence="Public Domain", publication_status="APPROVED", columns_verified=True)
    base.update(kw)
    return P.ParcelSourceConfig(**base)


def feat(year, **attrs):
    return {"attributes": {"assessment_no": "001-0001-1", "tax_year": year, **attrs}}


def test_multi_year_roll_resolves_to_the_latest_year_and_maps_acreage_only_for_acreage_units():
    cfg = roll_cfg()
    idx = P.index_features(cfg, [feat("2024", units="9", unit_type="ACREAGE", structure_use="RESIDENTIAL"),
                                 feat("2025", units="2.5", unit_type="ACREAGE", structure_use="RESIDENTIAL", vacant_lot_yn="YES")])
    [m] = P.match_rows(cfg, [{"id": 1, "parcel": "001-0001-1"}], idx)
    assert m.status == "MATCHED"
    fields, prov = P.plan_update(cfg, {"id": 1}, m, recorded_at=NOW)
    assert fields == {"land_use": "RESIDENTIAL", "acreage": 2.5}
    assert prov["acreage"]["source_attributes"] == {"unit_type": "ACREAGE", "vacant_lot_yn": "YES"}
    assert prov["acreage"]["record_of"] == "tax_year=2025 (latest published)"


def test_units_that_count_lots_or_improvements_are_never_acreage():
    cfg = roll_cfg()
    for unit_type in ("LOT", "IMPROVEMENT", "", None):
        idx = P.index_features(cfg, [feat("2025", units="1", unit_type=unit_type, structure_use="COMMERCIAL")])
        [m] = P.match_rows(cfg, [{"id": 1, "parcel": "001-0001-1"}], idx)
        fields, _ = P.plan_update(cfg, {"id": 1}, m, recorded_at=NOW)
        assert "acreage" not in fields and fields["land_use"] == "COMMERCIAL"


def test_not_classified_land_use_is_never_stored():
    cfg = roll_cfg()
    idx = P.index_features(cfg, [feat("2025", structure_use="NOT DETERMINED", legal_description="LOT 4 SUB X")])
    [m] = P.match_rows(cfg, [{"id": 1, "parcel": "001-0001-1"}], idx)
    fields, _ = P.plan_update(cfg, {"id": 1}, m, recorded_at=NOW)
    assert fields == {"legal_desc": "LOT 4 SUB X"}


def test_two_different_records_in_the_latest_year_fail_closed():
    cfg = roll_cfg()
    idx = P.index_features(cfg, [feat("2025", structure_use="RESIDENTIAL"), feat("2025", structure_use="COMMERCIAL")])
    [m] = P.match_rows(cfg, [{"id": 1, "parcel": "001-0001-1"}], idx)
    assert m.status == "AMBIGUOUS" and P.plan_update(cfg, {"id": 1}, m, recorded_at=NOW) == ({}, {})


def test_a_column_cannot_be_both_mapped_and_conditional():
    import pytest
    with pytest.raises(ValueError):
        roll_cfg(field_map={"acreage": "units"})


def test_conditional_attributes_are_requested():
    assert {"units", "unit_type", "vacant_lot_yn", "tax_year"} <= set(roll_cfg().out_fields())


# ------------------------------------------------------------ LGBS refresh

FEED_KW = dict(normalize_county=lambda c: (c or "").replace(" COUNTY", "").title() or None,
               status_to_ledger={"Struck off to Jurisdiction": "laft", "Scheduled for Auction": "auction"},
               to_float=lambda v: None if v in (None, "") else float(v), compose_address=lambda r: r.get("addr"))


def raw(acct, status="Struck off to Jurisdiction", state="TX", **kw):
    return {"state": state, "county": "LIBERTY COUNTY", "account_nbr": acct, "status": status, "sale_notes": kw.get("notes"),
            "value": kw.get("value"), "minimum_bid": None, "cause_nbr": kw.get("cause"), "addr": kw.get("addr"),
            "geometry": {"coordinates": [kw.get("lon"), kw.get("lat")]}}


def recs(*raws):
    return [r for r in (L.feed_record(x, **FEED_KW) for x in raws) if r]


def row(**kw):
    return {"id": 7, "county": "Liberty", "case_no": "100", "legal_desc": None, "assessed": None, "latitude": None,
            "longitude": None, "field_provenance": None, **kw}


def test_non_texas_records_are_dropped():
    assert recs(raw("100", state="PA")) == []


def test_observed_row_is_stamped_attested_and_filled_blank_only():
    idx = L.index_feed(recs(raw("100", notes="TR 4 ABST 12", value="5000", lat=30.1, lon=-94.8)))
    oc, body = L.plan_row(row(assessed=5000), idx, now=NOW, walk_complete=True)
    assert oc == "OBSERVED" and body["last_seen_at"] == NOW
    assert body["legal_desc"] == "TR 4 ABST 12" and (body["latitude"], body["longitude"]) == (30.1, -94.8)
    fp = body["field_provenance"]
    assert fp["assessed"]["source"] == "vendor_listing" and fp["assessed"]["attested"]
    assert fp["legal_desc"]["governance"] == "REVIEW_REQUIRED" and fp["legal_desc"]["field"] == "sale_notes"


def test_a_row_read_in_a_truncated_walk_is_still_observed_but_nothing_unseen_is_inferred():
    # Same rule as laft_lifecycle.OBSERVED_STATUSES (COMPLETE or INCOMPLETE).
    idx = L.index_feed(recs(raw("100")))
    oc, body = L.plan_row(row(), idx, now=NOW, walk_complete=False)
    assert oc == "OBSERVED" and body["last_seen_at"] == NOW
    assert L.plan_row(row(case_no="999"), idx, now=NOW, walk_complete=False) == ("NOT_IN_FEED", {})


def test_absence_and_other_statuses_are_counted_never_closed():
    idx = L.index_feed(recs(raw("200"), raw("100", status="Scheduled for Auction")))
    assert L.plan_row(row(case_no="300"), idx, now=NOW, walk_complete=True) == ("NOT_IN_FEED", {})
    assert L.plan_row(row(), idx, now=NOW, walk_complete=True) == ("OTHER_STATUS", {})


def test_two_feed_records_for_one_account_fail_closed():
    idx = L.index_feed(recs(raw("100"), raw("100")))
    assert L.plan_row(row(), idx, now=NOW, walk_complete=True) == ("AMBIGUOUS", {})


def test_a_stronger_stored_value_is_never_overwritten_or_reattributed():
    idx = L.index_feed(recs(raw("100", notes="FEED TEXT", value="1")))
    stored = {"legal_desc": {"source": "county_list"}, "assessed": {"source": "statewide_parcel"}}
    _, body = L.plan_row(row(legal_desc="COUNTY TEXT", assessed=9, field_provenance=stored), idx, now=NOW, walk_complete=True)
    assert "legal_desc" not in body and "assessed" not in body
    assert "field_provenance" not in body          # nothing re-attributed to the weaker vendor listing


def test_unequal_values_are_not_attested():
    idx = L.index_feed(recs(raw("100", value="10")))
    _, body = L.plan_row(row(assessed=99), idx, now=NOW, walk_complete=True)
    assert "assessed" not in (body.get("field_provenance") or {})


def test_rows_are_read_in_pages_past_one_thousand(monkeypatch):
    calls = []

    def fake(url, **kw):
        calls.append(url)
        return [{"id": i} for i in range(1000)] if len(calls) < 3 else [{"id": 1}]
    monkeypatch.setattr(L, "http_json", fake)
    rows = L.fetch_rows("https://db.example", "k")
    assert len(rows) == 2001 and "offset=2000" in calls[-1] and all("state=eq.TX" in c and "source=eq.laft" in c for c in calls)


def test_the_refresh_never_runs_the_harvester_sync_or_touches_another_ledger():
    src = (ROOT / "scripts" / "lgbs_available_refresh.py").read_text()
    assert "harvest_realauction" not in src and "TH.main" not in src and "subprocess" not in src
    assert "state=eq.TX&source=eq.laft" in src and "check_ingestion_gate" in src


def test_a_review_required_source_read_is_observed_never_verified():
    import enrich_available as EA
    from datetime import datetime, timezone
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    row = {"publication_status": "APPROVED_GRANDFATHERED", "last_seen_at": "2026-10-01T23:00:00+00:00", "source_id": "tx_lgbs"}
    assert EA.availability(row, now=now, review_required=frozenset({"tx_lgbs"}))[0] == "OBSERVED_REVIEW_REQUIRED"
    assert EA.availability({**row, "source_id": "fl_laft_pdfs"}, now=now, review_required=frozenset({"tx_lgbs"}))[0] == "VERIFIED_AVAILABLE"
    cov = EA.coverage([{**row, "id": 1, "state": "TX", "county": "Liberty", "source": "laft", "parcel": "1"}], now=now)
    assert cov["totals"]["availability"] == {"OBSERVED_REVIEW_REQUIRED": 1}


def test_a_second_layer_in_the_same_run_sees_the_first_layers_write():
    import enrich_statewide_parcels as ESP
    first = roll_cfg(source_id="t_first", field_map={"legal_desc": "legal_description"}, conditional_map={}, no_value={},
                     provenance_attrs=(), latest_field=None, counties=("East Baton Rouge",))
    second = roll_cfg(source_id="t_second", field_map={"legal_desc": "legal_description"}, conditional_map={}, no_value={},
                      provenance_attrs=(), latest_field=None, counties=("East Baton Rouge",))
    rows = [{"id": 1, "state": "LA", "county": "East Baton Rouge", "parcel": "001-0001-1", "legal_desc": None, "field_provenance": None}]
    writes = []
    fetch = lambda text: lambda url: [{"assessment_no": "001-0001-1", "legal_description": text}]  # noqa: E731
    ESP.run("LA", rows, fetch("FIRST"), write=lambda rid, f: writes.append(f["legal_desc"]), recorded_at=NOW, cfg=first)
    ESP.run("LA", rows, fetch("SECOND"), write=lambda rid, f: writes.append(f["legal_desc"]), recorded_at=NOW, cfg=second)
    assert writes == ["FIRST"] and rows[0]["legal_desc"] == "FIRST"


def test_a_column_the_latest_year_leaves_blank_comes_from_the_latest_year_that_publishes_it():
    cfg = roll_cfg(column_year_floor={"land_use": 2023}, latest_min=2024)
    feats = [feat("2022", structure_use="COMMERCIAL"), feat("2023", structure_use="RESIDENTIAL"),
             feat("2024", taxpayer_val="900"), feat("2025", legal_description="LOT 1")]
    cfg = P.ParcelSourceConfig(**{**cfg.__dict__, "field_map": {**cfg.field_map, "taxable_value": "taxpayer_val"}})
    idx = P.index_features(cfg, feats)
    [m] = P.match_rows(cfg, [{"id": 1, "parcel": "001-0001-1"}], idx)
    fields, prov = P.plan_update(cfg, {"id": 1}, m, recorded_at=NOW)
    assert fields["land_use"] == "RESIDENTIAL" and fields["legal_desc"] == "LOT 1"
    assert "taxable_value" not in fields                                  # 2025 record carries none; no fallback configured
    assert prov["land_use"]["record_of"].startswith("tax_year=2023")
    assert prov["legal_desc"]["record_of"] == "tax_year=2025 (latest published)"


def test_the_year_floor_and_disagreement_fail_closed():
    cfg = roll_cfg(column_year_floor={"land_use": 2023}, latest_min=2024)
    for feats in ([feat("2022", structure_use="RESIDENTIAL"), feat("2025")],                       # older than the floor
                  [feat("2023", structure_use="RESIDENTIAL"), feat("2023", structure_use="COMMERCIAL"), feat("2025")]):
        idx = P.index_features(cfg, feats)
        [m] = P.match_rows(cfg, [{"id": 1, "parcel": "001-0001-1"}], idx)
        fields, _ = P.plan_update(cfg, {"id": 1}, m, recorded_at=NOW)
        assert "land_use" not in fields


def test_a_row_with_its_own_instructions_link_still_gets_the_verified_application_form():
    import purchase_path_engine as PE
    row = {"case_no": "002-9125-0", "county": "East Baton Rouge", "purchase_url": "https://www.brla.gov/455/Adjudicated-Property",
           "purchase_url_kind": "purchase_instructions"}
    path, _ = PE.resolve(row, state="LA", source_id="la_ebr_adjudicated", county="East Baton Rouge", evidence=PE.load_evidence(),
                         registry_row={"canonical_url": "https://data.brla.gov/Housing-and-Development/Adjudicated-Property/a4h4-zi7e"},
                         harvest_date="2026-10-02")
    acq = path.acquisition()
    assert acq["application_url"].endswith("/9351/REQUEST-TO-PURCHASE-ADJUDICATED-PROPERTY")
    assert acq["phone"] == "(225) 389-3114" and len(acq["steps"]) == 5
