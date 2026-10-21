"""Florida DOR PIN shapefile reader (harvesters/boundary/shapefile.py).

Every fixture is SYNTHETIC: squares built in the published projection near
Broward, with invented PARCELNO values. No parcel from the real file is in this
repository. The projection WKT is the published .prj name, which is a standard
CRS definition and not parcel data.
"""
from __future__ import annotations

import pyproj
import pytest

shapefile = pytest.importorskip("shapefile")

from harvesters.boundary import plan as P  # noqa: E402
from harvesters.boundary import shapefile as R  # noqa: E402
from harvesters.boundary import sources as S  # noqa: E402
from harvesters.governance.source_approvals import match_geometries  # noqa: E402

# The projection the Broward PIN file is published in (its .prj WKT, as read
# from the owner-supplied file). Only the name is checked by the reader.
PRJ_WKT = pyproj.CRS.from_epsg(2881).to_wkt()
PRJ_WKT = PRJ_WKT.replace('NAD83(HARN) / Florida East (ftUS)', 'NAD_1983_HARN_StatePlane_Florida_East_FIPS_0901_Feet')
PRJ_WKT = PRJ_WKT.replace('NAD83 / Florida East (ftUS)', 'NAD_1983_HARN_StatePlane_Florida_East_FIPS_0901_Feet')
X0, Y0 = 900000.0, 650000.0      # State Plane feet, near Broward
S_FT = 100.0

def _cw(x, y, s):   # clockwise square = a shapefile outer ring
    return [(x, y), (x, y + s), (x + s, y + s), (x + s, y), (x, y)]

def _ccw(x, y, s):  # counter-clockwise square = a hole
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]


def _write(tmp_path, *, prj=True, prj_text=None):
    base = tmp_path / "broward_synthetic_pin"
    w = shapefile.Writer(str(base), shapeType=shapefile.POLYGON)
    w.field("PARCELNO", "C", size=12)
    w.record("10000000001A")                                    # letters are kept
    w.poly([_cw(X0, Y0, S_FT)])
    w.record("10000000002")                                     # a hole
    w.poly([_cw(X0 + 300, Y0, 200.0), _ccw(X0 + 375, Y0 + 75, 50.0)])
    w.record("10000000003")                                     # two parts, one parcel
    w.poly([_cw(X0 + 600, Y0, S_FT), _cw(X0 + 800, Y0, S_FT)])
    w.record("10000000004")                                     # stacked: same PARCELNO twice
    w.poly([_cw(X0, Y0 + 300, S_FT)])
    w.record("10000000004")
    w.poly([_cw(X0 + 200, Y0 + 300, S_FT)])
    w.record("10000000005")                                     # null shape
    w.null()
    w.close()
    if prj:
        base.with_suffix(".prj").write_text(prj_text if prj_text is not None else PRJ_WKT, encoding="utf-8")
    return base.with_suffix(".shp")


def test_reads_wgs84_polygons_with_holes_parts_and_null_shapes(tmp_path):
    feats = list(R.read_pin_features(_write(tmp_path)))
    assert len(feats) == 6
    by = {f["properties"]["PARCELNO"]: f for f in feats if f["geometry"] is not None}
    assert set(by) == {"10000000001A", "10000000002", "10000000003", "10000000004"}
    # PARCELNO is kept exactly as published (letters, no reformatting)
    assert feats[0]["properties"]["PARCELNO"] == "10000000001A"
    # the square with a hole: one polygon, outer ring then the hole
    holed = by["10000000002"]["geometry"]["coordinates"]
    assert len(holed) == 1 and len(holed[0]) == 2
    # the two-part feature: two polygons
    assert len(by["10000000003"]["geometry"]["coordinates"]) == 2
    # coordinates are WGS84 near Broward (about -80.2, 26.1)
    lon, lat = by["10000000001A"]["geometry"]["coordinates"][0][0][0]
    assert -80.4 < lon < -80.0 and 25.9 < lat < 26.3
    # the null shape carries no geometry, not an empty one
    assert [f for f in feats if f["properties"]["PARCELNO"] == "10000000005"][0]["geometry"] is None


def test_refuses_a_file_in_another_projection(tmp_path):
    with pytest.raises(R.UnsupportedProjection):
        list(R.read_pin_features(_write(tmp_path, prj_text=pyproj.CRS.from_epsg(4326).to_wkt())))


def test_refuses_a_file_with_no_projection_file(tmp_path):
    with pytest.raises(R.UnsupportedProjection):
        list(R.read_pin_features(_write(tmp_path, prj=False)))


def test_counts_only_summary_never_carries_a_parcel_number(tmp_path):
    feats = list(R.read_pin_features(_write(tmp_path)))
    summary = R.summarize(feats)
    assert summary == {"features": 6, "null_geometry": 1, "distinct_parcelno": 5,
                       "shared_parcelno_values": 1, "features_sharing_a_parcelno": 2, "largest_share": 2}
    assert not any("1000000000" in str(v) for v in summary.values())


def test_a_shared_parcelno_is_ambiguous_and_never_associated(tmp_path):
    feats = list(R.read_pin_features(_write(tmp_path)))
    good, refused = P.prepare_features(feats, S.FL_DOR)
    records = [{"id": 1, "parcel": "10000000004"}, {"id": 2, "parcel": "10000000001A"}, {"id": 3, "parcel": "10000000099"}]
    out = {m.property_id: m.outcome for m in match_geometries(
        records, good, record_key="parcel", feature_key="PARCELNO", normalize=lambda v: P.normalize_id(v, S.FL_DOR.id_rule) or "")}
    assert out == {1: "AMBIGUOUS", 2: "MATCHED", 3: "UNMATCHED"}
    assert refused["INVALID_GEOMETRY"] == 1          # only the null shape
    assert refused.get("NO_FEATURE_ID", 0) == 0


def test_a_null_shape_is_refused_by_the_geometry_step_not_stored(tmp_path):
    feats = list(R.read_pin_features(_write(tmp_path)))
    good, refused = P.prepare_features(feats, S.FL_DOR)
    assert all(g["geometry"] is not None for g in good)
    assert refused["INVALID_GEOMETRY"] == 1
