"""Thin-fields sprint (2026-10-27; docs/enrich-thin-fields-2026-10-27.md).

Pins: the Colorado statewide layer's second identifier (Saguache's parcel
number), the two new county layers (Oklahoma City government-owned parcels,
Oconee SC parcels), the derived lot area (the matched parcel polygon's own
area, labelled as derived, never over a published value), the "normalized"
identifier query, the ePropertyPlus lot / building facts kept as published,
and Genesee's exact-total, in-place session recovery reader. No request is
made here: every response is a fixture; every identifier is synthetic."""
from __future__ import annotations

import dataclasses
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(REPO / "scripts"))

from harvesters.enrichment import parcels as P, sources as S  # noqa: E402
from harvesters.governance import permissions as PERM  # noqa: E402
from harvesters.otc.adapters import epropertyplus as EPP, expansion as EX, paged_table as PT  # noqa: E402
import enrich_statewide_parcels as ESP  # noqa: E402
import sync_state_inventory as SY  # noqa: E402

DAY = date(2026, 10, 27)
NOW = "2026-10-27T00:00:00+00:00"
AT = datetime(2026, 10, 27, tzinfo=timezone.utc)


def cfg(sid):
    return next(c for c in S.all_sources() if c.source_id == sid)


def _arcgis(features):
    return lambda url: {"features": features}


# ------------------------------------------------------------------ new layers

NEW = {
    "ok_okc_government_owned_parcels": ("OK", ("Oklahoma",), "Pin", "digits", {"land_use"}),
    "sc_oconee_county_parcels": ("SC", ("Oconee",), "TMS_NUMBER", "exact", {"acreage", "latitude", "longitude"}),
}


def test_new_layers_are_county_scoped_exact_identifier_layers_on_interim_permission():
    p = PERM.Permissions.from_file()
    assert p.error is None
    for sid, (st, counties, id_field, rule, cols) in NEW.items():
        c = cfg(sid)
        assert (c.state, c.counties, c.id_field, c.id_rule) == (st, counties, id_field, rule), sid
        assert c.columns_verified and c.publication_status == "APPROVED" and "2026-10-27" in c.notes, sid
        assert c.written_columns() == cols, sid
        assert P.enrichment_allowed(c)[0], sid
        for op in ("fetch", "enrich"):
            d = p.authorize(sid, op, state=st, today=DAY)
            assert d.allowed and d.basis == "INTERIM" and not d.documented, (sid, op)
            assert d.evidence_type == "INTERNAL_RISK_ACCEPTANCE" and "excluded_from_paid_tier" in d.conditions
        for op in ("display", "redistribute", "store"):
            assert not p.authorize(sid, op, state=st, today=DAY).allowed, (sid, op)


def test_okc_land_use_is_fill_blank_only_queried_without_dashes_and_unspecified_is_no_value():
    c = cfg("ok_okc_government_owned_parcels")
    assert c.fill_blank_only and c.id_query == "normalized"
    url = P.query_urls(c, "Oklahoma", ["1234-56-789-0123"])[0]
    assert "%271234567890123%27" in url and "1234-56" not in url          # the layer's own dash-free PIN, quoted
    m = P.MatchResult("r1", "MATCHED", {"attributes": {"Pin": "1234567890123", "CLUCat": "Undeveloped"}}, "1234567890123")
    assert P.plan_update(c, {"id": "r1"}, m, recorded_at=NOW)[0] == {"land_use": "Undeveloped"}
    m2 = P.MatchResult("r1", "MATCHED", {"attributes": {"Pin": "1234567890123", "CLUCat": "Unspecified"}}, "1234567890123")
    assert P.plan_update(c, {"id": "r1"}, m2, recorded_at=NOW)[0] == {}
    # A row that already carries a land use is never touched by a fill-blank layer.
    row = {"id": "1", "state": "OK", "county": "Oklahoma", "parcel": "1234-56-789-0123", "land_use": "VACANT",
           "field_provenance": {}}
    writes = []
    ESP.run("OK", [row], _arcgis([{"attributes": {"Pin": "1234567890123", "CLUCat": "Undeveloped"}}]),
            write=lambda i, f: writes.append(f), recorded_at=NOW, cfg=c)
    assert writes == []


def test_colorado_statewide_layer_matches_an_account_or_a_parcel_number_never_both_ways_at_once():
    c = cfg("co_oit_public_parcels")
    assert c.alt_id_fields == ("parcel_id",) and c.batch_size <= 25
    url = P.query_urls(c, "Saguache", ["123456789012"])[0]
    assert "parcel_id+IN" in url and "account+IN" in url
    feats = [{"attributes": {"countyName": "Saguache", "account": "R000001", "parcel_id": "123456789012", "landAcres": 4.5}},
             {"attributes": {"countyName": "Morgan", "account": "R000002", "parcel_id": "999999999999", "situsAdd": "1 MAIN ST"}}]
    idx = P.index_features(c, feats)
    rows = [{"id": "a", "county": "Saguache", "parcel": "123456789012"},       # Saguache: the parcel number
            {"id": "b", "county": "Morgan", "parcel": "R000002"},             # Morgan: the account
            {"id": "c", "county": "Morgan", "parcel": "123456789012"}]        # another county's parcel number
    assert [m.status for m in P.match_rows(c, rows, idx)] == ["MATCHED", "MATCHED", "UNMATCHED"]
    # One key reaching two different features through the two attributes is ambiguous.
    clash = feats + [{"attributes": {"countyName": "Saguache", "account": "123456789012", "parcel_id": "555555555555"}}]
    assert P.match_rows(c, rows[:1], P.index_features(c, clash))[0].status == "AMBIGUOUS"


# ------------------------------------------------------------------ derived lot area

def _square(lng0, lat0, d, *, esri=True, hole=None):
    ring = [[lng0, lat0], [lng0, lat0 + d], [lng0 + d, lat0 + d], [lng0 + d, lat0], [lng0, lat0]]     # clockwise
    rings = [ring if esri else ring[::-1]]
    if hole:
        h0, hd = hole
        hr = [[h0[0], h0[1]], [h0[0] + hd, h0[1]], [h0[0] + hd, h0[1] + hd], [h0[0], h0[1] + hd], [h0[0], h0[1]]]
        rings.append(hr if esri else hr[::-1])
    return {"rings": rings} if esri else {"type": "Polygon", "coordinates": rings}


def test_polygon_area_is_close_to_the_true_area_and_holes_subtract():
    # 0.001 deg square at 38.6 N (St. Louis): about 111.2 m x 86.9 m = 104,000 sq ft.
    g = _square(-90.2, 38.6, 0.001)
    a = P.polygon_area_sqft(g)
    expected = (6371007.181 * 3.141592653589793 / 180 * 0.001) ** 2 * 0.78152 * 10.7639
    assert abs(a / expected - 1) < 0.005
    assert P.polygon_area_sqft(_square(-90.2, 38.6, 0.001, esri=False)) == a          # GeoJSON winding, same area
    holed = P.polygon_area_sqft(_square(-90.2, 38.6, 0.001, hole=((-90.1998, 38.6002), 0.0005)))
    assert 0.70 < holed / a < 0.80                                                      # a quarter cut out
    multi = {"type": "MultiPolygon", "coordinates": [_square(-90.2, 38.6, 0.001, esri=False)["coordinates"]] * 2}
    assert abs(P.polygon_area_sqft(multi) - 2 * a) <= 1
    assert P.polygon_area_sqft(None) is None and P.polygon_area_sqft({"rings": [[[0, 0], [0, 0]]]}) is None


def test_derived_lot_area_is_labelled_and_never_replaces_a_published_value():
    c = cfg("mo_stl_parcels_coordinates")
    assert c.derived_lot_area and "lot_sqft" in c.written_columns() and "lot_sqft" not in c.field_map
    feat = {"attributes": {"ParcelId": "12345678901", "AsdTotal": 0}, "geometry": _square(-90.2, 38.6, 0.0003)}
    fields, prov = P.plan_update(c, {"id": "r1"}, P.MatchResult("r1", "MATCHED", feat, "12345678901"), recorded_at=NOW)
    assert fields["lot_sqft"] > 0 and prov["lot_sqft"]["derived"] == P.DERIVED_AREA_NOTE
    assert "not the deed or assessed" in P.DERIVED_AREA_NOTE
    # A published lot size (the list's own, county_list provenance) is kept.
    row = {"id": "1", "state": "MO", "county": "St. Louis City", "parcel": "12345678901", "lot_sqft": 2500,
           "latitude": 38.6, "longitude": -90.2, "field_provenance": {"lot_sqft": {"source": "county_list"}}}
    writes = []
    ESP.run("MO", [row], _arcgis([feat]), write=lambda i, f: writes.append(f), recorded_at=NOW, cfg=c)
    assert all("lot_sqft" not in w for w in writes)


def test_socrata_geometry_is_read_only_for_the_derived_area():
    c = cfg("la_ebr_tax_parcels")
    assert c.derived_lot_area and c.geometry_field == "the_geom" and "the_geom" in c.out_fields()
    recs = [{"assessment_num": "123-4567-8", "sum_assessed_value": "900",
             "the_geom": {"type": "MultiPolygon", "coordinates": [_square(-91.1, 30.4, 0.0004, esri=False)["coordinates"]]}}]
    row = {"id": "1", "state": "LA", "county": "East Baton Rouge", "parcel": "123-4567-8", "field_provenance": {}}
    writes = []
    rep = ESP.run("LA", [row], lambda url: recs, write=lambda i, f: writes.append(f), recorded_at=NOW, cfg=c)
    assert rep["fields_written"].get("lot_sqft") == 1 and writes[0]["lot_sqft"] > 0
    assert writes[0]["field_provenance"]["lot_sqft"]["derived"] == P.DERIVED_AREA_NOTE
    assert "the_geom" not in json.dumps(writes[0]["field_provenance"])           # geometry never stored


def test_a_derived_area_needs_polygon_geometry():
    base = dict(source_id="x_test", state="LA", agency="t", dataset="t", landing_url="https://e.gov", id_field="A",
                id_rule="exact", field_map={}, licence="t", publication_status="APPROVED")
    with pytest.raises(ValueError, match="derived lot area"):
        P.ParcelSourceConfig(**base, layer_url="https://e.gov/resource/abcd-1234.json", transport="socrata", derived_lot_area=True)
    with pytest.raises(ValueError, match="geometry_field"):
        P.ParcelSourceConfig(**base, layer_url="https://e.gov/arcgis/rest/services/X/FeatureServer/0", geometry_field="g")
    with pytest.raises(ValueError, match="published .mapped. or derived"):
        P.ParcelSourceConfig(**{**base, "field_map": {"lot_sqft": "SQFT"}},
                             layer_url="https://e.gov/arcgis/rest/services/X/FeatureServer/0", derived_lot_area=True)
    ok = P.ParcelSourceConfig(**base, layer_url="https://e.gov/arcgis/rest/services/X/FeatureServer/0", derived_lot_area=True)
    assert "returnGeometry=true" in P.query_urls(ok, "X", ["1"])[0]


# ------------------------------------------------------------------ ePropertyPlus lot / building facts

def _kc_row(pid, **kw):
    return {"parcelNumber": pid, "county": "Jackson", "inventoryType": "Land Bank", "latitude": 39.1, "longitude": -94.5, **kw}


def test_epropertyplus_lot_and_building_facts_are_kept_as_published():
    assert EX.MO_KC_LANDBANK.lot_sqft_field == "parcelSquareFootage"
    assert EX.PA_PITTSBURGH_CITY_PROPERTY.lot_sqft_field == "parcelSquareFootage"
    assert (EX.MI_SAGINAW_LANDBANK.year_built_field, EX.MI_SAGINAW_LANDBANK.living_area_field) == ("yearBuilt", "structureSquareFootage")
    assert EX.TN_SHELBY_LANDBANK.lot_sqft_field is None                  # Shelby publishes only length x width: never multiplied
    cfg_ = dataclasses.replace(EX.MO_KC_LANDBANK, year_built_field="yearBuilt", living_area_field="structureSquareFootage")
    rows = [_kc_row("JA00000000000000001", parcelSquareFootage=4356.4, yearBuilt=1925, structureSquareFootage=1200),
            _kc_row("JA00000000000000002", parcelSquareFootage=0, yearBuilt=19251960, structureSquareFootage=None),
            _kc_row("JA00000000000000003")]
    recs, _ = EPP.parse_rows(cfg_, rows, retrieved_at=AT)
    assert [(r.lot_sqft, r.year_built, r.living_area) for r in recs] == [(4356, 1925, 1200), (None, None, None), (None, None, None)]
    out = recs[0].to_properties_row()
    assert (out["lot_sqft"], out["year_built"], out["living_area"]) == (4356, 1925, 1200)
    assert "lot_sqft" not in recs[2].to_properties_row()                  # an absent figure never writes NULL
    assert not recs[0].validate()
    assert {"lot_sqft", "year_built", "living_area"} <= set(SY.LIST_FIELDS)


# ------------------------------------------------------------------ Genesee: exact totals, in-place recovery

def _gpage(cur, total_pages, first, last, rows, stated):
    body = "".join(f"<tr><td>{p}</td><td>1 SYNTHETIC</td><td>FLINT</td><td>48504</td><td>Res Vac Lot</td><td>Vacant Land</td></tr>"
                   for p in rows)
    counter = f"page {cur} of {total_pages} (listings {first}-{last})" if total_pages else ""
    return (f"<html><div>{stated} properties found.</div><table><tr><td></td><td>{counter}</td><td>next</td></tr></table>"
            "<table><tr><th>Parcel ID</th><th>Address</th><th>City</th><th>ZIP</th><th>Class</th><th>Sale Type</th></tr>"
            f"{body}</table></html>")


class _Boom(Exception):
    response = type("R", (), {"status_code": 500})()


ONE = dataclasses.replace(EX.MI_GENESEE_LANDBANK, partition_field=None, partition_values=())
P1 = _gpage(1, 3, 1, 1, ["41-05-257-001"], 3)
P2 = _gpage(2, 3, 2, 2, ["41-05-257-002"], 3)
P3 = _gpage(3, 3, 3, 3, ["41-05-257-003"], 3)


def _scripted(script):
    calls = []

    def post(url, data):
        calls.append(data.get("LRCpage"))
        x = script.pop(0)
        if isinstance(x, Exception):
            raise x
        return x
    return post, calls


def test_genesee_states_its_total_and_recovers_from_a_server_error_in_place():
    assert EX.MI_GENESEE_LANDBANK.total_pattern and EX.MI_GENESEE_LANDBANK.prev_data == (("LRCpage", "prev"),)
    # A 500 on "next" that did NOT move the cursor: "stay" shows page 1, "next" again reaches page 2.
    post, calls = _scripted([P1, _Boom(), P1, P2, P3])
    res = PT.fetch_all(ONE, post, retrieved_at=AT, sleep=lambda s: None)
    assert res.outcome == "COMPLETE" and [r.case_no for r in res.records] == ["41-05-257-001", "41-05-257-002", "41-05-257-003"]
    assert calls == ["", "next", "", "next", "next"]
    # A 500 that DID move the cursor (to page 3): "stay" shows page 3, "prev" steps back to page 2.
    post, calls = _scripted([P1, _Boom(), P3, P2, P3])
    res = PT.fetch_all(ONE, post, retrieved_at=AT, sleep=lambda s: None)
    assert res.outcome == "COMPLETE" and len(res.records) == 3 and calls == ["", "next", "", "prev", "next"]


def test_genesee_short_of_its_stated_total_or_repeating_a_listing_is_failed():
    one = dataclasses.replace(ONE, attempts=1)
    short = [_gpage(1, 2, 1, 1, ["41-05-257-001"], 3), _gpage(2, 2, 2, 2, ["41-05-257-002"], 3)]
    post, _ = _scripted(short)
    res = PT.fetch_all(one, post, retrieved_at=AT, sleep=lambda s: None)
    assert res.outcome == "FAILED" and "of 3" in res.error_detail
    dup = [_gpage(1, 2, 1, 1, ["41-05-257-001"], 2), _gpage(2, 2, 2, 2, ["41-05-257-001"], 2)]
    post, _ = _scripted(dup)
    res = PT.fetch_all(one, post, retrieved_at=AT, sleep=lambda s: None)
    assert res.outcome == "FAILED" and "twice" in res.error_detail
    # A page that cannot be recovered fails the part (and, with one attempt, the read).
    post, _ = _scripted([P1] + [_Boom()] * (1 + one.recoveries_per_page))
    assert PT.fetch_all(one, post, retrieved_at=AT, sleep=lambda s: None).outcome == "FAILED"


def test_genesee_parts_must_add_up_to_exactly_the_stated_total():
    cfg_ = dataclasses.replace(EX.MI_GENESEE_LANDBANK, partition_values=("01", "02"))
    parts = {"01": _gpage(1, 0, 0, 0, ["01-05-257-001", "01-05-257-002"], 2), "02": _gpage(1, 0, 0, 0, ["02-05-257-001"], 1)}

    def post_for(stated):
        full = _gpage(1, 1, 1, 25, [], stated)
        return lambda u, d: parts[d["FindTWP"]] if "FindTWP" in d else full
    assert PT.fetch_all(cfg_, post_for(3), retrieved_at=AT, sleep=lambda s: None).outcome == "COMPLETE"
    res = PT.fetch_all(cfg_, post_for(4), retrieved_at=AT, sleep=lambda s: None)        # within one page, but not exact
    assert res.outcome == "FAILED" and "states 4" in res.error_detail


def test_genesee_full_search_without_its_counter_is_retried_before_failing():
    cfg_ = dataclasses.replace(EX.MI_GENESEE_LANDBANK, partition_values=("01",))
    part = _gpage(1, 0, 0, 0, ["01-05-257-001"], 1)
    script = ["<html>no counter</html>", _gpage(1, 1, 1, 25, [], 1), part]
    res = PT.fetch_all(cfg_, lambda u, d: script.pop(0), retrieved_at=AT, sleep=lambda s: None)
    assert res.outcome == "COMPLETE" and len(res.records) == 1
    never = PT.fetch_all(cfg_, lambda u, d: "<html>no counter</html>", retrieved_at=AT, sleep=lambda s: None)
    assert never.outcome == "FAILED" and "no page counter on the full search" in never.error_detail
