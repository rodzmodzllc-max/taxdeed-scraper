"""Broward outline loader: download + the shared Florida refresh path.

SYNTHETIC files and property rows only. No network, no database, and no
parcel number from the real file or the real database is in this file.
"""
from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

shp = pytest.importorskip("shapefile", reason="pyshp (test-only) is not installed")
pyproj = pytest.importorskip("pyproj", reason="pyproj (test-only) is not installed")

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("load_broward", ROOT / "scripts" / "load_florida_broward_boundaries.py")
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)

FL = "fl_dor_pto_parcel_gis"
CRS = pyproj.CRS.from_epsg(2881)                 # NAD83(HARN) / Florida East (ftUS), as Broward publishes
FWD = pyproj.Transformer.from_crs(CRS.geodetic_crs, CRS, always_xy=True).transform


def _square(lon, lat, h=0.0004):
    return [FWD(x, y) for x, y in [(lon, lat), (lon, lat + h), (lon + h, lat + h), (lon + h, lat), (lon, lat)]]


def _zip_fetch(features):
    """A fake download that writes a synthetic Broward PIN zip."""
    def fetch(url, dest: Path):
        base = dest.parent / "broward_2025pin"
        w = shp.Writer(str(base), shapeType=shp.POLYGON)
        w.field("PARCELNO", "C", size=12)
        for pid, (lon, lat) in features:
            w.poly([_square(lon, lat)])
            w.record(pid)
        w.close()
        base.with_suffix(".prj").write_text(CRS.to_wkt(version="WKT1_ESRI"))
        with zipfile.ZipFile(dest, "w") as z:
            for ext in (".shp", ".shx", ".dbf", ".prj"):
                z.write(base.with_suffix(ext), "broward_2025pin" + ext)
    return fetch


class FakeDb:
    def __init__(self, rows, applied=True):
        self.rows, self.applied, self.upserts, self.refreshes = rows, applied, [], []

    def migration_applied(self):
        return self.applied

    def properties(self, src, county=None):
        return [r for r in self.rows if r["county"] == county]

    def stored(self, ids):
        return {}

    def upsert(self, source_id, rows):
        self.upserts.append(rows)
        return {"inserted": len(rows)}

    def record_refresh(self, source_id, status, at, unit=None, dataset=None, dataset_date=None):
        self.refreshes.append((status, unit))


def _rec(pid, nal=None, use="00", parcel="484106-07-0240"):
    prov = {"prop_type": {"source": "fdor_nal", "matched_parcel_id": nal}} if nal else {}
    return {"id": pid, "state": "FL", "county": "Broward", "parcel": parcel, "dor_use_code": use, "field_provenance": prov}


FILE = [("484106070240", (-80.20, 26.10)), ("484106070250", (-80.21, 26.10)), ("48410607026A", (-80.22, 26.10))]


def test_dry_run_matches_only_validated_nal_ids_and_writes_nothing():
    db, lines = FakeDb([_rec("a", "484106070240"), _rec("b"), _rec("c", "48410607026A", use="04")]), []
    assert L.run("dry_run", "", db=db, fetch=_zip_fetch(FILE), out=lines.append) == 0
    assert db.upserts == [] and db.refreshes == []
    text = "\n".join(lines)
    assert "would write 1" in text and "NO_VALIDATED_NAL_ID" in text and "CONDO_UNIT" in text
    assert "484106" not in text                                           # never a parcel number


def test_the_listing_parcel_is_never_reformatted_into_a_key():
    # The listing's own parcel equals the PARCELNO once dashes go, but with no
    # validated NAL id the record is not joined.
    db, lines = FakeDb([_rec("b", None, parcel="4841-0607-0240")]), []
    L.run("dry_run", "", db=db, fetch=_zip_fetch(FILE), out=lines.append)
    assert "would write 0" in "\n".join(lines)


def test_apply_writes_the_match_and_records_broward_not_the_statewide_source():
    db = FakeDb([_rec("a", "484106070240")])
    assert L.run("apply", "APPLY", db=db, fetch=_zip_fetch(FILE), out=lambda m: None) == 0
    assert [r["property_id"] for r in db.upserts[0]] == ["a"]
    assert db.refreshes == [("COMPLETE", "Broward")]


def test_a_failed_download_writes_nothing_and_records_a_broward_failure():
    def broken(url, dest):
        raise ConnectionError("synthetic")
    db = FakeDb([_rec("a", "484106070240")])
    assert L.run("apply", "APPLY", db=db, fetch=broken, out=lambda m: None) == 1
    assert db.upserts == [] and db.refreshes == [("FAILED", "Broward")]


def test_apply_needs_the_confirmation_and_the_migration():
    db = FakeDb([])
    assert L.run("apply", "", db=db, fetch=_zip_fetch(FILE), out=lambda m: None) == 2
    db = FakeDb([], applied=False)
    called = []
    assert L.run("dry_run", "", db=db, fetch=lambda u, d: called.append(u), out=lambda m: None) == 4
    assert called == [] and db.upserts == []


def test_extract_refuses_a_path_that_leaves_the_target_folder(tmp_path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("../escape.shp", b"x")
    with pytest.raises(RuntimeError, match="unsafe path"):
        L.extract_shapefile(bad, tmp_path)
