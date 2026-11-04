"""Florida DOR county parcel shapefiles: reader, projection, identifier join,
README caveats and refresh safety (2026-10-20).

Synthetic shapefiles are written with pyshp (an independent writer) and
coordinates cross-checked with PROJ (pyproj); both are test-only and the tests
that need them skip without them. Every fixture value is synthetic - nothing
here is a real parcel number or polygon.
"""
from __future__ import annotations

import ast
import json
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.boundary import fl_dor as FD  # noqa: E402
from harvesters.boundary import plan as PL  # noqa: E402
from harvesters.boundary import sources as S  # noqa: E402
from harvesters.boundary import shapefile as SF  # noqa: E402
from harvesters.governance import permissions as P  # noqa: E402
from harvesters.governance import source_approvals as A  # noqa: E402

import parcel_boundary_refresh as R  # noqa: E402

shp = pytest.importorskip("shapefile", reason="pyshp (test-only) is not installed")

FL = "fl_dor_pto_parcel_gis"
TODAY = date(2026, 10, 21)
pyproj = pytest.importorskip("pyproj", reason="pyproj (test-only) is not installed")
# Published-style projections (standard CRS definitions, not parcel data).
PRJ = {"fl_north_ftus": pyproj.CRS.from_epsg(2883).to_wkt(version="WKT1_ESRI"),    # NAD83(HARN) Florida North
       "fl_east_ftus": pyproj.CRS.from_epsg(2881).to_wkt(version="WKT1_ESRI"),     # NAD83(HARN) Florida East
       "fl_west_ftus": pyproj.CRS.from_epsg(2882).to_wkt(version="WKT1_ESRI"),     # NAD83(HARN) Florida West
       "fl_gdl_albers_m": pyproj.CRS.from_epsg(3087).to_wkt(version="WKT1_ESRI"),  # NAD83(HARN) Florida GDL Albers
       "nad83_geographic": pyproj.CRS.from_epsg(4269).to_wkt(version="WKT1_ESRI"),
       "nad27_utm17": pyproj.CRS.from_epsg(26717).to_wkt(version="WKT1_ESRI")}


def square(x, y, h=0.0004, clockwise=True):
    ring = [(x, y), (x, y + h), (x + h, y + h), (x + h, y), (x, y)]      # clockwise
    return ring if clockwise else ring[::-1]


def write_shp(tmp_path, name, features, *, prj=PRJ["fl_north_ftus"], parcel_type="C", co_no=None,
              extra_fields=(), deleted=(), lonlat=True):
    """features: list of (parcelno, rings or None), rings in lon/lat unless
    lonlat=False (then already in the file's projection). Returns the .shp path."""
    if lonlat and prj is not None:
        try:
            crs = pyproj.CRS.from_wkt(prj)
            fwd = pyproj.Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True).transform
            features = [(pid, None if rings is None else [[fwd(x, y) for x, y in r] for r in rings])
                        for pid, rings in features]
        except pyproj.exceptions.CRSError:
            pass
    w = shp.Writer(str(tmp_path / name), shapeType=shp.POLYGON)
    if parcel_type == "C":
        w.field("PARCELNO", "C", size=30)
    else:
        w.field("PARCELNO", "N", size=20, decimal=0)
    if co_no is not None:
        w.field("CO_NO", "N", size=2, decimal=0)
    for f in extra_fields:
        w.field(f, "C", size=30)
    for i, (pid, rings) in enumerate(features):
        if rings is None:
            w.null()
        else:
            w.poly([list(r) for r in rings])
        vals = [pid if parcel_type == "C" else (int(pid) if pid else None)]
        if co_no is not None:
            vals.append(co_no)
        vals += ["OWNER NAME (SYNTHETIC)"] * len(extra_fields)
        w.record(*vals)
    w.close()
    if prj is not None:
        (tmp_path / f"{name}.prj").write_text(prj)
    if deleted:   # mark DBF records deleted
        dbf = tmp_path / f"{name}.dbf"
        data = bytearray(dbf.read_bytes())
        n, hlen, rlen = int.from_bytes(data[4:8], "little"), int.from_bytes(data[8:10], "little"), int.from_bytes(data[10:12], "little")
        for i in deleted:
            data[hlen + i * rlen] = ord("*")
        dbf.write_bytes(bytes(data))
    return tmp_path / f"{name}.shp"


def rec(pid, nal=None, county="Leon", use="00", extra_prov=None):
    prov = {}
    if nal is not None:
        prov["prop_type"] = {"source": "fdor_nal", "matched_parcel_id": nal}
    if extra_prov:
        prov.update(extra_prov)
    return {"id": pid, "state": "FL", "county": county, "parcel": f"listing-{pid}", "dor_use_code": use,
            "field_provenance": prov}


# --- the reader --------------------------------------------------------------

def test_reader_keeps_leading_zeros_inner_spaces_and_skips_unrequested_columns(tmp_path):
    p = write_shp(tmp_path, "leon_pin", [("0012345000", [square(-84.3, 30.4)]),
                                          ("2 29 43 01 010 0050-F02.0", [square(-84.31, 30.4)])],
                  extra_fields=("OWN_NAME",))
    r = FD.read_county(p, "Leon")
    assert r.status == "COMPLETE"
    assert [f["properties"]["PARCELNO"] for f in r.features] == ["0012345000", "2 29 43 01 010 0050-F02.0"]
    assert all(set(f["properties"]) == {"PARCELNO", "FID"} for f in r.features)   # owner never kept
    assert all(set(f["properties"]) <= {"PARCELNO", "CO_NO", "FID"} for f in SF.read_pin_features(p))
    assert r.dataset == "DOR PTO PIN parcel shapefile leon_pin" and r.dataset_date == date.today().isoformat()
    assert [f["properties"]["FID"] for f in r.features] == [0, 1]


def test_a_numeric_parcelno_field_refuses_the_file(tmp_path):
    p = write_shp(tmp_path, "num", [("12345", [square(-84.3, 30.4)])], parcel_type="N")
    r = FD.read_county(p, "Leon")
    assert r.status == "FAILED" and "not a character field" in r.reason and r.features == []


@pytest.mark.parametrize("prj,needle", [(None, "no .prj"),
                                        (PRJ["nad83_geographic"], "UNSUPPORTED_PROJECTION"),
                                        (PRJ["nad27_utm17"], "UNSUPPORTED_PROJECTION"),
                                        ("not a projection", "cannot be read")])
def test_an_unknown_or_unsupported_coordinate_system_refuses_the_file(tmp_path, prj, needle):
    p = write_shp(tmp_path, "x", [("1", [square(-84.3, 30.4)])], prj=prj, lonlat=False)
    r = FD.read_county(p, "Leon")
    assert r.status == "FAILED" and needle in r.reason


def test_wrong_county_par_and_condominium_files_are_refused(tmp_path):
    p = write_shp(tmp_path, "pin", [("1", [square(-84.3, 30.4)])], co_no=11)        # 11 = Alachua
    assert FD.read_county(p, "Leon").reason.startswith("WRONG_COUNTY")
    assert FD.read_county(p, "Alachua").status == "COMPLETE"
    assert FD.read_county(p, "Leon", variant="PAR").reason == "PAR_FILE_NOT_ALLOWED"
    assert FD.read_county(p, "Alachua", variant="PAR", allow_par_geometry=True).status == "COMPLETE"
    c = write_shp(tmp_path, "dade_condo", [("1", [square(-80.2, 25.8)])])
    assert FD.read_county(c, "Miami-Dade").reason == "CONDOMINIUM_FILE_NOT_INGESTED"
    assert FD.read_county(p, "Atlantis").reason == "UNKNOWN_COUNTY"


def test_blank_identifiers_null_shapes_and_deleted_records_are_counted_not_kept(tmp_path):
    p = write_shp(tmp_path, "mix", [("", [square(-84.3, 30.4)]), ("2", None),
                                    ("4", [square(-84.32, 30.4)]), ("5", [square(-84.33, 30.4)])], deleted=(3,))
    r = FD.read_county(p, "Leon")
    assert r.counts == {"NO_PARCELNO": 1, "NULL_SHAPE": 1}
    assert [f["properties"]["PARCELNO"] for f in r.features] == ["4"]


def test_a_degenerate_ring_is_refused_by_the_geometry_step(tmp_path):
    bad = [[(-84.3, 30.4), (-84.3, 30.401), (-84.3, 30.4)]]           # three points: not a polygon
    fs = feats_from(tmp_path, [("9", bad), ("8", [square(-84.31, 30.4)])])
    good, refused = PL.prepare_features(fs, S.FL_DOR)
    assert [g["attributes"]["PARCELNO"] for g in good] == ["8"] and refused["INVALID_GEOMETRY"] == 1


def test_holes_are_kept_inside_their_outer_ring(tmp_path):
    outer = square(-84.3, 30.4, 0.001)
    hole = square(-84.2997, 30.4003, 0.0002, clockwise=False)
    p = write_shp(tmp_path, "hole", [("7", [outer, hole])])
    geo = FD.read_county(p, "Leon").features[0]["geometry"]
    assert len(geo["coordinates"]) == 1 and len(geo["coordinates"][0]) == 2


def test_a_truncated_shapefile_is_a_failed_read(tmp_path):
    p = write_shp(tmp_path, "cut", [("1", [square(-84.3, 30.4)]), ("2", [square(-84.31, 30.4)])])
    p.write_bytes(p.read_bytes()[:-20])
    assert FD.read_county(p, "Leon").status == "FAILED"


def test_a_zip_is_read_the_same_as_loose_files(tmp_path):
    import zipfile
    p = write_shp(tmp_path, "z", [("0001", [square(-84.3, 30.4)])])
    zp = tmp_path / "z.zip"
    with zipfile.ZipFile(zp, "w") as z:
        for ext in (".shp", ".shx", ".dbf", ".prj"):
            z.write(p.with_suffix(ext), "z" + ext)
    assert FD.read_county(zp, "Leon").features[0]["properties"]["PARCELNO"] == "0001"


# --- projection ----------------------------------------------------------------

@pytest.mark.parametrize("name", ["fl_gdl_albers_m", "fl_east_ftus", "fl_west_ftus", "fl_north_ftus"])
def test_projected_files_are_converted_to_lonlat(tmp_path, name):
    lon, lat = {"fl_east_ftus": (-80.2, 26.1), "fl_west_ftus": (-82.0, 28.0)}.get(name, (-84.3, 30.4))
    p = write_shp(tmp_path, "proj", [("9", [square(lon, lat, 0.001)])], prj=PRJ[name])
    got = FD.read_county(p, "Leon").features[0]["geometry"]["coordinates"][0][0]
    want = square(lon, lat, 0.001)
    # NAD83(HARN) to WGS84 is within a couple of metres; 3e-5 degrees is about 3 m.
    assert max(max(abs(a - b) for a, b in zip(g, w)) for g, w in zip(got, want)) < 3e-5


# --- our side: which records may be joined ---------------------------------------

def test_the_join_key_is_the_validated_nal_parcel_id_only():
    assert FD.nal_parcel_id(rec("a", "0012345000")) == ("0012345000", "")
    assert FD.nal_parcel_id(rec("a")) == (None, "NO_VALIDATED_NAL_ID")
    two = rec("a", "1", extra_prov={"address": {"source": "fdor_nal", "matched_parcel_id": "2"}})
    assert FD.nal_parcel_id(two) == (None, "CONFLICTING_NAL_IDS")
    other = rec("a", extra_prov={"x": {"source": "county_list", "matched_parcel_id": "9"}})
    assert FD.nal_parcel_id(other) == (None, "NO_VALIDATED_NAL_ID")


@pytest.mark.parametrize("county,use,reason", [("Leon", "04", "CONDO_UNIT"), ("Miami-Dade", "04", "CONDO_UNIT_SEPARATE_FILE"),
                                               ("St. Johns", "04", "CONDO_UNIT_SEPARATE_FILE"), ("Leon", "94", "RIGHT_OF_WAY"),
                                               ("Leon", "00", ""), ("Leon", None, "")])
def test_condominium_units_and_rights_of_way_are_never_joined(county, use, reason):
    assert FD.record_exclusion(rec("a", "1", county=county, use=use), county) == reason
    eligible, counts = FD.prepare_records([rec("a", "1", county=county, use=use)], county)
    assert (eligible == []) == bool(reason) and (counts.get(reason) == 1 if reason else counts == {})


def test_county_codes_match_the_enrichment_table():
    tree = ast.parse((REPO / "scripts/enrich_property_details.py").read_text())
    table = next(ast.literal_eval(n.value) for n in tree.body
                 if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "COUNTY_CODES")
    assert table == FD.COUNTY_CODES and len(table) == 67


# --- the join -------------------------------------------------------------------------

def plan(records, feats, stored=None, status="COMPLETE"):
    eligible, _ = FD.prepare_records(records, "Leon")
    return PL.plan_refresh(eligible, feats, stored or {}, S.FL_DOR, read_status=status, observed_at="2026-10-21T00:00:00Z",
                           dataset="DOR PTO PIN parcel shapefile leon_pin", dataset_date="2026-08-20")


def feats_from(tmp_path, rows, name="leon_pin"):
    return FD.read_county(write_shp(tmp_path, name, rows), "Leon").features


def test_matching_is_exact_no_leading_zero_case_or_dash_normalization(tmp_path):
    fs = feats_from(tmp_path, [("0012345000", [square(-84.3, 30.4)]), ("12-34-56", [square(-84.31, 30.4)]),
                               ("AB100", [square(-84.32, 30.4)])])
    out = plan([rec("a", "0012345000"), rec("b", "12345000"), rec("c", "123456"), rec("d", "ab100")], fs)
    assert [r["property_id"] for r in out["rows"]] == ["a"]
    row = out["rows"][0]
    assert row["parcel"] == "0012345000" and row["source_dataset"] == "DOR PTO PIN parcel shapefile leon_pin"
    assert row["source_dataset_date"] == "2026-08-20" and row["source_feature_id"] == "0"
    assert out["counts"]["unmatched"] == 3 and out["counts"]["unclaimed_features"] == 2


def test_stacked_polygons_and_duplicate_records_are_ambiguous(tmp_path):
    fs = feats_from(tmp_path, [("100", [square(-84.3, 30.4)]), ("100", [square(-84.3, 30.4, 0.0005)]),
                               ("200", [square(-84.31, 30.4)])])
    out = plan([rec("a", "100"), rec("b", "200"), rec("c", "200")], fs)
    assert out["rows"] == [] and out["counts"]["ambiguous"] == 3


def test_a_multi_parcel_polygon_is_attached_to_none_of_its_parcels(tmp_path):
    same = [square(-84.3, 30.4)]
    fs = feats_from(tmp_path, [("300", same), ("301", same), ("302", [square(-84.31, 30.4)])])
    out = plan([rec("a", "300"), rec("b", "301"), rec("c", "302")], fs)
    assert [r["property_id"] for r in out["rows"]] == ["c"]
    assert out["counts"]["MULTI_PARCEL_GEOMETRY"] == 2 and out["counts"]["multi_parcel_geometry"] == 2


def test_condominium_and_right_of_way_records_are_not_attached_even_with_a_matching_polygon(tmp_path):
    fs = feats_from(tmp_path, [("400", [square(-84.3, 30.4)]), ("401", [square(-84.31, 30.4)])])
    out = plan([rec("a", "400", use="04"), rec("b", "401", use="94")], fs)
    assert out["rows"] == []


def test_unmatched_geometry_is_counted_and_never_attached(tmp_path):
    fs = feats_from(tmp_path, [("500", [square(-84.3, 30.4)])])
    out = plan([rec("a"), rec("b", "999")], fs)
    assert out["rows"] == [] and out["counts"]["unclaimed_features"] == 1


@pytest.mark.parametrize("status", ["FAILED", "REFUSED", "JOIN_NOT_VALIDATED", "INCOMPLETE"])
def test_a_failed_refused_or_unvalidated_read_changes_nothing(tmp_path, status):
    fs = feats_from(tmp_path, [("600", [square(-84.3, 30.4)])])
    out = plan([rec("a", "600")], fs, stored={"a": {"source_id": FL, "content_sha256": "1" * 64}}, status=status)
    assert out["rows"] == [] and out["counts"] == {"skipped_read_not_complete": 1}


def test_format_check_needs_the_validated_ids_format_in_the_file(tmp_path):
    fs = feats_from(tmp_path, [("12345", [square(-84.3, 30.4)])])
    eligible, _ = FD.prepare_records([rec("a", "12-345")], "Leon")
    ok, why = FD.format_check(eligible, fs)
    assert not ok and why.startswith("FORMAT_MISMATCH") and "12-345" not in why and "12345" not in why
    eligible, _ = FD.prepare_records([rec("a", "99999")], "Leon")
    assert FD.format_check(eligible, fs) == (True, "")
    assert FD.format_check([], fs)[1] == "NO_VALIDATED_IDS"


# --- the refresh script (files) ----------------------------------------------------------

class FakeDb:
    def __init__(self, rows, stored=None, applied=True):
        self.rows, self._stored, self.applied = rows, stored or {}, applied
        self.upserts, self.refreshes = [], []

    def migration_applied(self, per_county=False):
        return self.applied is True or (self.applied == "034" and not per_county)

    def properties(self, src, county=None):
        return [r for r in self.rows if county is None or r["county"] == county]

    def stored(self, ids):
        return {k: v for k, v in self._stored.items() if k in ids}

    def upsert(self, source_id, rows):
        self.upserts.append((source_id, rows))
        return {"inserted": len(rows)}

    def record_refresh(self, source_id, status, at, unit=None, dataset=None, dataset_date=None):
        self.refreshes.append((source_id, status, unit, dataset, dataset_date))


def test_apply_writes_matches_and_records_the_county_with_its_dataset(tmp_path):
    p = write_shp(tmp_path, "leon_pin", [("700", [square(-84.3, 30.4)]), ("701", [square(-84.31, 30.4)])])
    db, lines = FakeDb([rec("a", "700"), rec("b", "999"), rec("c", "701", use="04")]), []
    rc = R.run(FL, apply=True, db=db, out=lines.append, today=TODAY, files={"county": "Leon", "path": str(p)})
    assert rc == 0 and [r["property_id"] for r in db.upserts[0][1]] == ["a"]
    assert db.refreshes == [(FL, "COMPLETE", "Leon", "DOR PTO PIN parcel shapefile leon_pin", date.today().isoformat())]
    printed = "\n".join(lines)
    assert "700" not in printed and "701" not in printed and "CONDO_UNIT" in printed


def test_a_failed_read_writes_nothing_and_leaves_the_last_success(tmp_path):
    p = write_shp(tmp_path, "num", [("700", [square(-84.3, 30.4)])], parcel_type="N")
    db = FakeDb([rec("a", "700")], stored={"a": {"source_id": FL, "content_sha256": "1" * 64}})
    lines = []
    assert R.run(FL, apply=True, db=db, out=lines.append, today=TODAY, files={"county": "Leon", "path": str(p)}) == 5
    assert db.upserts == [] and db.refreshes[0][:3] == (FL, "FAILED", "Leon")
    assert "last successful refresh unchanged" in lines[-1]


def test_a_format_mismatch_writes_nothing(tmp_path):
    p = write_shp(tmp_path, "leon_pin", [("700", [square(-84.3, 30.4)])])
    db = FakeDb([rec("a", "7-00")])
    assert R.run(FL, apply=True, db=db, out=lambda m: None, today=TODAY, files={"county": "Leon", "path": str(p)}) == 5
    assert db.upserts == [] and db.refreshes[0][1] == "JOIN_NOT_VALIDATED"


def test_files_source_needs_a_county_and_a_file(tmp_path):
    db = FakeDb([])
    assert R.run(FL, apply=False, db=db, out=lambda m: None, today=TODAY, files={}) == 2


def test_dry_run_reads_but_writes_nothing(tmp_path):
    p = write_shp(tmp_path, "leon_pin", [("700", [square(-84.3, 30.4)])])
    db = FakeDb([rec("a", "700")])
    assert R.run(FL, apply=False, db=db, out=lambda m: None, today=TODAY, files={"county": "Leon", "path": str(p)}) == 0
    assert db.upserts == [] and db.refreshes == []


# --- permission scope ----------------------------------------------------------------------

def test_readme_review_opens_parse_for_the_dor_files_only():
    assert A.load()[FL].readme_reviewed
    assert P.authorize(FL, "parse", state="FL", dataset="county_parcel_geometry", today=TODAY).allowed
    for ds in (None, "tax_roll_attributes", "nal", "statewide_parcels"):
        assert not P.authorize(FL, "parse", state="FL", dataset=ds, today=TODAY).allowed
    for sid, ds in (("fl_fdor_cadastral", "parcel_centroid"), ("fl_dor_statewide", None)):
        for op in ("store", "display"):
            assert not P.authorize(sid, op, state="FL", dataset=ds, today=TODAY).allowed
    assert not P.authorize(FL, "redistribute", state="FL", dataset="county_parcel_geometry", today=TODAY).allowed


def test_the_register_records_the_readme_caveats_and_their_handling():
    c = A.load()[FL].technical_caveats
    assert c.startswith("Reviewed from the Parcel Shapefiles Readme")
    for needle in ("PIN files", "PAR files", "PARCEL_ID", "CSV", "Chapter 119", "rights-of-way", "Multi-parcel",
                   "stacked", "Miami-Dade", "St. Johns", "Condominiums"):
        assert needle.lower() in c.lower(), needle


# --- scoped read: only the joinable keys are kept --------------------------------

def test_a_scoped_read_keeps_only_joinable_keys_and_still_sees_the_whole_file(tmp_path):
    shared = [square(-84.30, 30.4)]
    p = write_shp(tmp_path, "leon_pin", [
        ("100", [square(-84.31, 30.4)]),          # in scope, unique
        ("200", shared), ("999", shared),         # one polygon under two PARCELNOs, one of them out of scope
        ("300", [square(-84.32, 30.4)]), ("300", [square(-84.33, 30.4)]),   # stacked, in scope
        ("AB-1", [square(-84.34, 30.4)]),         # out of scope, another identifier shape
    ])
    r = FD.read_county(p, "Leon", keys={"100", "200", "300"})
    assert r.status == "COMPLETE"
    assert sorted(f["properties"]["PARCELNO"] for f in r.features) == ["100", "300", "300"]
    assert r.counts == {"NOT_IN_SCOPE": 2, "MULTI_PARCEL_GEOMETRY": 1, "DUPLICATE_IDENTIFIER_KEYS": 1}
    assert r.duplicate_keys == {"300"}                                 # the stacked pair, in scope
    assert r.identifier_shapes == {"d3", "A2-d1"}                     # from every feature, value-free
    out = plan([rec("a", "100"), rec("b", "200"), rec("c", "300")], r.features)
    assert [x["property_id"] for x in out["rows"]] == ["a"]           # 200 never gets the shared polygon; 300 ambiguous
    ok, _ = FD.format_check([{"nal_parcel_id": "100"}], [], r.identifier_shapes)
    assert ok


def test_the_refresh_reads_only_the_validated_keys(tmp_path, monkeypatch):
    p = write_shp(tmp_path, "leon_pin", [("700", [square(-84.3, 30.4)]), ("701", [square(-84.31, 30.4)])])
    seen = {}
    real = FD.read_county
    monkeypatch.setattr(FD, "read_county", lambda *a, **k: (seen.update(k), real(*a, **k))[1])
    db = FakeDb([rec("a", "700"), rec("b")])
    assert R.run(FL, apply=False, db=db, out=lambda m: None, today=TODAY, files={"county": "Leon", "path": str(p)}) == 0
    assert seen["keys"] == {"700"}


# --- location validation -----------------------------------------------------------

def test_florida_bounds_are_the_geocoders():
    from harvesters.enrichment.geocode import STATE_BOUNDS
    assert FD.FLORIDA_BOUNDS == STATE_BOUNDS["FL"]


def test_a_polygon_outside_florida_is_dropped(tmp_path):
    # Written in a Florida projection, but the coordinates put it in Georgia.
    p = write_shp(tmp_path, "leon_pin", [("1", [square(-84.3, 30.4)]), ("2", [square(-84.3, 32.5)])])
    r = FD.read_county(p, "Leon", keys={"1", "2"})
    assert [f["properties"]["PARCELNO"] for f in r.features] == ["1"] and r.counts == {"OUT_OF_STATE": 1}


def _located(pid, nal, lat=None, lon=None):
    row = dict(rec(pid, nal), nal_parcel_id=nal)
    if lat is not None:
        row.update(latitude=lat, longitude=lon)
    return row


def test_a_polygon_far_from_the_records_own_point_is_refused():
    feats = [{"type": "Feature", "properties": {"PARCELNO": k, "FID": i},
              "geometry": {"type": "MultiPolygon", "coordinates": [[square(-84.3 - i * 0.01, 30.4)]]}}
             for i, k in enumerate(("near", "far", "nocoords"))]
    records = [_located("a", "near", 30.4002, -84.2998),        # inside the polygon
               _located("b", "far", 30.50, -84.30),               # about 11 km north
               _located("c", "nocoords")]
    kept, counts = FD.location_check(records, feats)
    assert [f["properties"]["PARCELNO"] for f in kept] == ["near", "nocoords"]
    assert counts == {"LOCATION_CONFIRMED": 1, "LOCATION_MISMATCH": 1, "NO_RECORD_COORDINATES": 1}
    out = plan(records, kept)
    assert sorted(r["property_id"] for r in out["rows"]) == ["a", "c"]        # b stays unmatched, never wrong


def test_the_refresh_applies_the_location_check(tmp_path):
    p = write_shp(tmp_path, "leon_pin", [("700", [square(-84.3, 30.4)])])
    far = dict(rec("a", "700"), latitude=30.6, longitude=-84.3)
    db, lines = FakeDb([far]), []
    assert R.run(FL, apply=True, db=db, out=lines.append, today=TODAY, files={"county": "Leon", "path": str(p)}) == 0
    assert db.upserts in ([], [(FL, [])])
    assert "LOCATION_MISMATCH" in "\n".join(lines)


def test_a_files_source_needs_035_as_well_as_034(tmp_path):
    p = write_shp(tmp_path, "leon_pin", [("700", [square(-84.3, 30.4)])])
    db, lines = FakeDb([rec("a", "700")], applied="034"), []
    assert R.run(FL, apply=True, db=db, out=lines.append, today=TODAY, files={"county": "Leon", "path": str(p)}) == 4
    assert db.upserts == [] and db.refreshes == [] and "035" in "\n".join(lines)


# --- a malformed shape does not fail the county ------------------------------------

def _zero_shape(shp_path, index):
    """Rewrite record `index` as a polygon with no parts and no points (the
    2026 Alachua file carried one such PolygonZ). Record length unchanged."""
    data = bytearray(shp_path.read_bytes())
    pos = 100
    for _ in range(index):
        pos += 8 + int.from_bytes(data[pos + 4:pos + 8], "big") * 2
    body = pos + 8
    data[body + 36:body + 40] = (0).to_bytes(4, "little")      # numParts
    data[body + 40:body + 44] = (0).to_bytes(4, "little")      # numPoints
    shp_path.write_bytes(bytes(data))


def test_one_malformed_shape_is_counted_and_the_rest_of_the_county_reads(tmp_path):
    p = write_shp(tmp_path, "leon_pin", [("1", [square(-84.30, 30.4)]), ("2", [square(-84.31, 30.4)]),
                                          ("3", [square(-84.32, 30.4)])])
    _zero_shape(p, 1)
    r = FD.read_county(p, "Leon")
    assert r.status == "COMPLETE" and r.counts == {"MALFORMED_SHAPE": 1}
    assert [f["properties"]["PARCELNO"] for f in r.features] == ["1", "3"]
    assert [f["properties"]["FID"] for f in r.features] == [0, 2]
    scoped = FD.read_county(p, "Leon", keys={"2", "3"})
    assert [f["properties"]["PARCELNO"] for f in scoped.features] == ["3"]
    assert scoped.counts == {"MALFORMED_SHAPE": 1, "NOT_IN_SCOPE": 1}


def test_a_truncated_file_still_fails_the_whole_county(tmp_path):
    p = write_shp(tmp_path, "cut2", [("1", [square(-84.3, 30.4)]), ("2", [square(-84.31, 30.4)])])
    p.write_bytes(p.read_bytes()[:-20])
    r = FD.read_county(p, "Leon")
    assert r.status == "FAILED" and "TRUNCATED_FILE" in r.reason


# --- listing-parcel join, confirmed by the record's own point (2026-10-22) -----------

def lrec(pid, parcel, lat=None, lon=None, use="00", nal=None):
    row = dict(rec(pid, nal, use=use), parcel=parcel)
    if lat is not None:
        row.update(latitude=lat, longitude=lon)
    return row


class SourceDb(FakeDb):
    def properties(self, src, county=None, source=None):
        self.asked_source = source
        return [r for r in self.rows if county is None or r["county"] == county]


def run_listing(tmp_path, features, rows, **kw):
    p = write_shp(tmp_path, "leon_pin", features)
    db, lines = SourceDb(rows), []
    rc = R.run(FL, apply=True, db=db, out=lines.append, today=TODAY,
               files={"county": "Leon", "path": str(p), "source": "laft", "listing_join": True, **kw})
    return rc, db, "\n".join(lines)


def test_a_listing_parcel_joins_only_when_its_own_point_is_inside_the_polygon(tmp_path):
    rc, db, text = run_listing(tmp_path,
        [("1234560010", [square(-84.30, 30.40, 0.001)]), ("1234560020", [square(-84.31, 30.40, 0.001)])],
        [lrec("in", "12-3456-0010", 30.4005, -84.2995),          # separators differ, point inside
         lrec("out", "12-3456-0020", 30.4005, -84.2995),         # matches, but its point is in the other parcel
         lrec("nopoint", "12-3456-0020")])
    assert rc == 0 and db.asked_source == "laft"
    rows = db.upserts[0][1]
    assert [r["property_id"] for r in rows] == ["in"]
    assert rows[0]["match_method"] == "PARCEL_NUMBER_LOCATION_CONFIRMED" and rows[0]["parcel"] == "1234560010"
    assert "LOCATION_NOT_INSIDE" in text and "NO_RECORD_POINT" in text
    assert "1234560010" not in text and "12-3456" not in text                    # counts only


def test_leading_zeros_are_kept_and_ambiguous_spellings_are_refused(tmp_path):
    rc, db, text = run_listing(tmp_path,
        [("00123450", [square(-84.30, 30.40, 0.001)]),                           # zeros kept: 123450 never matches
         ("9-8765", [square(-84.31, 30.40, 0.001)]), ("98-765", [square(-84.32, 30.40, 0.001)])],
        [lrec("zeros", "123450", 30.4005, -84.2995), lrec("amb", "98765", 30.4005, -84.3095)])
    assert db.upserts in ([], [(FL, [])])
    assert "LISTING_UNMATCHED" in text and "LISTING_FORMAT_AMBIGUOUS" in text


def test_validated_ids_still_join_exactly_and_listing_join_is_opt_in(tmp_path):
    feats = [("0012345000", [square(-84.30, 30.40, 0.001)]), ("1234560010", [square(-84.31, 30.40, 0.001)])]
    rc, db, _ = run_listing(tmp_path, feats, [lrec("v", "listing-v", 30.4005, -84.2995, nal="0012345000"),
                                              lrec("l", "123456-0010", 30.4005, -84.3095)])
    assert sorted((r["property_id"], r["match_method"]) for r in db.upserts[0][1]) == [
        ("l", "PARCEL_NUMBER_LOCATION_CONFIRMED"), ("v", "EXACT_PARCEL_ID")]
    p = write_shp(tmp_path, "leon_pin2", feats)
    db2 = FakeDb([lrec("l", "123456-0010", 30.4005, -84.3095)])
    R.run(FL, apply=True, db=db2, out=lambda m: None, today=TODAY, files={"county": "Leon", "path": str(p)})
    assert db2.upserts in ([], [(FL, [])])                                      # without listing_join: nothing


def test_condo_and_right_of_way_are_never_listing_joined(tmp_path):
    rc, db, text = run_listing(tmp_path, [("1234560010", [square(-84.30, 30.40, 0.001)])],
                               [lrec("c", "123456-0010", 30.4005, -84.2995, use="04"),
                                lrec("r", "123456-0010", 30.4005, -84.2995, use="94")])
    assert db.upserts in ([], [(FL, [])]) and "CONDO_UNIT" in text and "RIGHT_OF_WAY" in text


# --- ambiguity is decided before distance (2026-10-22) ------------------------------------
# A PARCELNO carried by more than one record of the county file is never joined, in
# either match mode, whatever the distance from the property's own point and however
# the other record fares in the read. One record whose shape has several parts is one
# parcel. SYNTHETIC identifiers and coordinates only.

def _at(row, lat=30.4002, lon=-84.2998):
    return dict(row, latitude=lat, longitude=lon)


def _refresh(tmp_path, features, rows, *, listing_join=False, apply=True):
    p = write_shp(tmp_path, "leon_pin", features)
    db, lines = FakeDb(rows), []
    rc = R.run(FL, apply=apply, db=db, out=lines.append, today=TODAY,
               files={"county": "Leon", "path": str(p), "listing_join": listing_join})
    written = [r for _, batch in db.upserts for r in batch]
    return rc, db, written, "\n".join(lines)


def test_two_polygons_with_the_same_validated_id_both_near_are_ambiguous(tmp_path):
    rc, db, written, text = _refresh(tmp_path, [("800", [square(-84.3, 30.4)]), ("800", [square(-84.3006, 30.4)])],
                                     [_at(rec("a", "800"))])
    assert rc == 0 and written == []
    assert "AMBIGUOUS_DUPLICATE_IDENTIFIER" in text and "800" not in text
    assert db.refreshes[0][1] == "COMPLETE"   # the read itself was complete; the record is simply not joined


@pytest.mark.parametrize("far_lon", [-84.35, -84.6])
def test_a_far_duplicate_is_not_dropped_to_make_the_near_one_unique(tmp_path, far_lon):
    # One polygon contains the property's point, the other (same PARCELNO) is several km
    # away. Distance must not choose: no write.
    rc, _, written, text = _refresh(tmp_path, [("801", [square(-84.3, 30.4)]), ("801", [square(far_lon, 30.4)])],
                                    [_at(rec("a", "801"))])
    assert rc == 0 and written == []
    assert "AMBIGUOUS_DUPLICATE_IDENTIFIER" in text and "LOCATION_MISMATCH" not in text


def test_a_duplicate_whose_other_record_is_unreadable_is_still_ambiguous(tmp_path):
    # The second record has no shape: it is dropped from the polygons, but it still claims
    # the PARCELNO, so the first is not unique.
    rc, _, written, text = _refresh(tmp_path, [("802", [square(-84.3, 30.4)]), ("802", None)],
                                    [_at(rec("a", "802"))])
    assert rc == 0 and written == [] and "AMBIGUOUS_DUPLICATE_IDENTIFIER" in text


def test_a_far_duplicate_is_ambiguous_in_the_listing_number_mode_too(tmp_path):
    listing = dict(_at(rec("a")), parcel="12-345-0803")      # no validated NAL id
    rc, _, written, text = _refresh(tmp_path, [("123450803", [square(-84.3, 30.4)]),
                                               ("123450803", [square(-84.6, 30.4)])],
                                    [listing], listing_join=True)
    assert rc == 0 and written == []
    assert "AMBIGUOUS_DUPLICATE_IDENTIFIER" in text and "LOCATION_CONFIRMED_INSIDE" not in text


def test_one_record_with_several_parts_is_one_parcel_and_is_attached(tmp_path):
    # A single shapefile record whose shape has two separate parts: the file itself says
    # both parts belong to the same parcel, so it is one MultiPolygon, not a duplicate.
    rc, _, written, text = _refresh(tmp_path, [("804", [square(-84.3, 30.4), square(-84.2992, 30.4)])],
                                    [_at(rec("a", "804"))])
    assert rc == 0 and [r["property_id"] for r in written] == ["a"]
    assert len(written[0]["geometry"]["coordinates"]) == 2
    assert "AMBIGUOUS" not in text


def test_distinct_identifiers_with_overlapping_polygons_each_keep_their_own(tmp_path):
    # Overlapping (not identical) polygons under different PARCELNO values are two parcels;
    # each record gets its own. Identical geometry under two ids is refused
    # (test_a_multi_parcel_polygon_is_attached_to_none_of_its_parcels).
    rc, _, written, _ = _refresh(tmp_path, [("805", [square(-84.3, 30.4)]), ("806", [square(-84.2998, 30.4)])],
                                 [_at(rec("a", "805")), _at(rec("b", "806"), lon=-84.2996)])
    assert rc == 0
    assert sorted((r["property_id"], r["source_feature_id"]) for r in written) == [("a", "0"), ("b", "1")]


def test_missing_or_unvalidated_ids_are_never_joined(tmp_path):
    rows = [_at(rec("a")),                                                    # no provenance at all
            _at(rec("b", extra_prov={"parcel": {"source": "county_list", "matched_parcel_id": "807"}})),
            _at(rec("c", "807", extra_prov={"other": {"source": "fdor_nal", "matched_parcel_id": "808"}}))]
    rc, _, written, text = _refresh(tmp_path, [("807", [square(-84.3, 30.4)]), ("808", [square(-84.31, 30.4)])], rows)
    assert rc == 0 and written == []
    assert "NO_VALIDATED_NAL_ID" in text and "CONFLICTING_NAL_IDS" in text


def test_the_reader_counts_duplicates_across_every_in_scope_record(tmp_path):
    p = write_shp(tmp_path, "leon_pin", [("809", [square(-84.3, 30.4)]), ("809", None), ("810", [square(-84.31, 30.4)]),
                                         ("811", [square(-84.32, 30.4), square(-84.3192, 30.4)])])
    r = FD.read_county(p, "Leon", keys={"809", "810", "811"})
    assert r.duplicate_keys == {"809"} and r.counts["DUPLICATE_IDENTIFIER_KEYS"] == 1
    scoped = FD.read_county(p, "Leon", keys={"810"})
    assert scoped.duplicate_keys == set()          # out-of-scope keys are not counted
    kept, counts = FD.reject_duplicate_keys([{"join_key": "809"}, {"join_key": "810"}], r.duplicate_keys)
    assert kept == [{"join_key": "810"}] and counts == {"AMBIGUOUS_DUPLICATE_IDENTIFIER": 1}


def test_location_check_never_narrows_a_duplicated_identifier():
    near = {"type": "Feature", "properties": {"PARCELNO": "812", "FID": 0},
            "geometry": {"type": "MultiPolygon", "coordinates": [[square(-84.3, 30.4)]]}}
    far = {"type": "Feature", "properties": {"PARCELNO": "812", "FID": 1},
           "geometry": {"type": "MultiPolygon", "coordinates": [[square(-84.6, 30.4)]]}}
    kept, counts = FD.location_check([_at({"nal_parcel_id": "812"})], [near, far])
    assert kept == [near, far] and counts == {"DUPLICATE_IDENTIFIER": 2}
