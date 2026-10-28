"""East Baton Rouge parcel centroids (2026-10-28).

The approved Open Data BR Tax Parcel layer (la_ebr_tax_parcels, Socrata,
Public Domain) already matched the adjudicated rows on assessment_num and
read their polygon (the_geom) for the derived lot area; it now also gives the
matched record its point: the area-weighted centroid of that polygon
(PARCEL_GIS / PARCEL_CENTROID). Pins: GeoJSON centroids (holes, orientation),
the socrata config rule, the factory run (provenance, AMBIGUOUS gets nothing,
outside Louisiana refused, a stronger stored point kept) and the authoritative
geocoder's socrata lookup. Every response is a fixture; every identifier is
synthetic."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(1, str(REPO / "scripts"))

from harvesters.enrichment import geocode as G, parcels as P, sources as S  # noqa: E402
from harvesters.sources import coordinates as C  # noqa: E402
import enrich_statewide_parcels as ESP  # noqa: E402

NOW = "2026-10-28T00:00:00+00:00"
EBR = next(c for c in S.all_sources() if c.source_id == "la_ebr_tax_parcels")


def _ring(x, y, d, ccw=True):
    r = [[x, y], [x + d, y], [x + d, y + d], [x, y + d], [x, y]]
    return r if ccw else r[::-1]


def _multi(x, y, d=0.0004, ccw=True):
    return {"type": "MultiPolygon", "coordinates": [[_ring(x, y, d, ccw)]]}


def _rec(num, geom, **kw):
    return {"assessment_num": num, "sum_assessed_value": "900", "the_geom": geom, **kw}


def _row(rid, num, **kw):
    return {"id": rid, "state": "LA", "county": "East Baton Rouge", "source": "laft", "source_id": "la_ebr_adjudicated",
            "parcel": num, "field_provenance": {}, **kw}


# ------------------------------------------------------------------ centroid geometry

def test_geojson_centroid_matches_the_esri_one_and_ignores_orientation():
    esri = {"rings": [_ring(-91.1, 30.4, 0.001, ccw=False)]}
    for geom in (_multi(-91.1, 30.4, 0.001), _multi(-91.1, 30.4, 0.001, ccw=False),
                 {"type": "Polygon", "coordinates": [_ring(-91.1, 30.4, 0.001)]}):
        assert P.polygon_centroid(geom) == pytest.approx((30.4005, -91.0995))
    assert P.polygon_centroid(esri) == pytest.approx((30.4005, -91.0995))


def test_geojson_hole_is_subtracted_whatever_its_winding():
    outer, hole = _ring(0.0, 0.0, 4.0), _ring(0.0, 0.0, 2.0)       # hole in the lower-left quarter
    for h in (hole, hole[::-1]):
        lat, lng = P.polygon_centroid({"type": "Polygon", "coordinates": [outer, h]})
        assert lat == pytest.approx(7 / 3) and lng == pytest.approx(7 / 3)


def test_multipolygon_parts_are_area_weighted_and_degenerate_is_none():
    geom = {"type": "MultiPolygon", "coordinates": [[_ring(0.0, 0.0, 2.0)], [_ring(10.0, 0.0, 1.0, ccw=False)]]}
    lat, lng = P.polygon_centroid(geom)
    assert lng == pytest.approx((4 * 1 + 1 * 10.5) / 5) and lat == pytest.approx((4 * 1 + 1 * 0.5) / 5)
    assert P.polygon_centroid(None) is None
    assert P.polygon_centroid({"type": "Point", "coordinates": [1, 2]}) is None
    assert P.polygon_centroid({"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [0, 0]]]}) is None


# ------------------------------------------------------------------ config

def test_ebr_layer_supplies_centroids_from_the_geom():
    assert EBR.centroid and EBR.transport == "socrata" and EBR.geometry_field == "the_geom"
    assert {"latitude", "longitude", "lot_sqft"} <= EBR.written_columns()
    assert "the_geom" in P.query_urls(EBR, "East Baton Rouge", ["123-4567-8"])[0]


def test_a_socrata_centroid_needs_the_geometry_column():
    base = dict(source_id="x_test", state="LA", agency="t", dataset="t", landing_url="https://e.gov", id_field="A",
                id_rule="exact", field_map={}, licence="t", publication_status="APPROVED",
                layer_url="https://e.gov/resource/abcd-1234.json", transport="socrata")
    with pytest.raises(ValueError, match="geometry_field"):
        P.ParcelSourceConfig(**base, centroid=True)
    assert P.ParcelSourceConfig(**base, centroid=True, geometry_field="g").centroid


# ------------------------------------------------------------------ the factory run

def _run(rows, recs):
    writes = {}
    rep = ESP.run("LA", rows, lambda url: recs, write=lambda i, f: writes.__setitem__(i, f), recorded_at=NOW, cfg=EBR)
    return rep, writes


def test_matched_record_gets_its_parcel_centroid_with_provenance():
    rep, writes = _run([_row("1", "123-4567-8")], [_rec("123-4567-8", _multi(-91.1, 30.4))])
    w = writes["1"]
    assert (w["latitude"], w["longitude"]) == pytest.approx((30.4002, -91.0998))
    fp = w["field_provenance"]["latitude"]
    assert fp["source"] == "statewide_parcel" and fp["source_id"] == "la_ebr_tax_parcels"
    assert fp["matched_parcel_id"] == "123-4567-8" and "centroid" in fp["derived"]
    assert "coordinates" not in str(fp)                                      # geometry never stored
    assert C.coordinate_provenance({**_row("1", "x"), **w})["method"] == "PARCEL_GIS"
    assert rep["fields_written"]["latitude"] == 1


def test_two_records_for_one_number_get_no_point():
    rep, writes = _run([_row("1", "123-4567-8")],
                       [_rec("123-4567-8", _multi(-91.1, 30.4)), _rec("123-4567-8", _multi(-91.2, 30.5))])
    assert rep["ambiguous"] == 1 and writes == {}


def test_a_point_outside_louisiana_is_refused():
    _, writes = _run([_row("1", "123-4567-8")], [_rec("123-4567-8", _multi(-84.3, 30.4))])     # Tallahassee
    assert "latitude" not in writes.get("1", {}) and "longitude" not in writes.get("1", {})


def test_a_stored_point_of_equal_or_higher_rank_is_kept():
    stored = {"latitude": 30.45, "longitude": -91.15,
              "field_provenance": {"latitude": {"source": "statewide_parcel"}, "longitude": {"source": "statewide_parcel"}}}
    _, writes = _run([_row("1", "123-4567-8", **stored)], [_rec("123-4567-8", _multi(-91.1, 30.4))])
    assert "latitude" not in writes.get("1", {})


def test_a_weaker_stored_point_is_upgraded():
    stored = {"latitude": 30.45, "longitude": -91.15,
              "field_provenance": {"latitude": {"source": "census_geocoder"}, "longitude": {"source": "census_geocoder"}}}
    _, writes = _run([_row("1", "123-4567-8", **stored)], [_rec("123-4567-8", _multi(-91.1, 30.4))])
    assert writes["1"]["latitude"] == pytest.approx(30.4002)


# ------------------------------------------------------------------ authoritative geocoder

def test_geocoder_lists_the_ebr_layer_and_reads_socrata_answers():
    src = next(s for s in G.coordinate_sources() if s.source_id == "la_ebr_tax_parcels")
    assert (src.method, src.geometry, src.provenance_source) == ("PARCEL_GIS", "PARCEL_CENTROID", "statewide_parcel")
    rows = [_row("1", "123-4567-8"), _row("2", "123-4567-9"), _row("3", "123-4567-0")]
    recs = [_rec("123-4567-8", _multi(-91.1, 30.4)),
            _rec("123-4567-9", _multi(-91.1, 30.4)), _rec("123-4567-9", _multi(-91.2, 30.5))]
    out = G.lookup_parcel_layer(src, rows, lambda url: recs)
    assert out["1"].status == "MATCHED" and out["1"].lat == pytest.approx(30.4002)
    assert out["2"].status == "AMBIGUOUS" and out["3"].status == "NO_MATCH"
    # A SODA error object (not a list) is an unavailable source, never a match.
    err = G.lookup_parcel_layer(src, rows, lambda url: {"error": True, "message": "x"})
    assert {lk.status for lk in err.values()} == {"SOURCE_UNAVAILABLE"}
