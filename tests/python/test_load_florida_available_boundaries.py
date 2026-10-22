"""Florida Available outline loader: county file listing, per-county refresh,
Available records only. SYNTHETIC files and rows only - no network, no
database, no parcel number from a real file or the real database."""
from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

shp = pytest.importorskip("shapefile", reason="pyshp (test-only) is not installed")
pyproj = pytest.importorskip("pyproj", reason="pyproj (test-only) is not installed")

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("load_fl_available", ROOT / "scripts" / "load_florida_available_boundaries.py")
L = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(L)

CRS = pyproj.CRS.from_epsg(2883)        # NAD83(HARN) / Florida North (ftUS)
FWD = pyproj.Transformer.from_crs(CRS.geodetic_crs, CRS, always_xy=True).transform


def _square(lon, lat, h=0.001):
    return [FWD(x, y) for x, y in [(lon, lat), (lon, lat + h), (lon + h, lat + h), (lon + h, lat), (lon, lat)]]


def _zip(features, stem):
    def fetch(url, dest: Path):
        base = dest.parent / stem
        w = shp.Writer(str(base), shapeType=shp.POLYGON)
        w.field("PARCELNO", "C", size=24)
        for pid, (lon, lat) in features:
            w.poly([_square(lon, lat)])
            w.record(pid)
        w.close()
        base.with_suffix(".prj").write_text(CRS.to_wkt(version="WKT1_ESRI"))
        with zipfile.ZipFile(dest, "w") as z:
            for ext in (".shp", ".shx", ".dbf", ".prj"):
                z.write(base.with_suffix(ext), stem + ext)
    return fetch


class FakeDb:
    def __init__(self, rows, applied=True):
        self.rows, self.applied, self.upserts, self.refreshes, self.sources = rows, applied, [], [], []

    def migration_applied(self, per_county=False):
        return self.applied

    def properties(self, src, county=None, source=None):
        self.sources.append(source)
        return [r for r in self.rows if r["county"] == county and r["source"] == source]

    def stored(self, ids):
        return {}

    def upsert(self, source_id, rows):
        self.upserts.append(rows)
        return {"inserted": len(rows)}

    def record_refresh(self, source_id, status, at, unit=None, dataset=None, dataset_date=None):
        self.refreshes.append((status, unit))


def _row(pid, county, parcel, lat, lon, source="laft"):
    return {"id": pid, "state": "FL", "county": county, "parcel": parcel, "dor_use_code": "00", "source": source,
            "field_provenance": {}, "latitude": lat, "longitude": lon}


def test_the_county_file_comes_from_the_portal_listing_and_condo_files_are_never_used():
    class Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"value": [{"Name": n} for n in (
                "leon_2026pin.zip", "palmbeach_2026pin.zip", "sarasota_2026pin.shp.zip", "miamidade_2026pin.zip",
                "miamidade_condos_2026.zip", "stjohnscondos_2026.zip", "stjohns_2026pin.zip", "bay_2025pin.zip",
                "notes.pdf")]}
    seen = {}
    files = L.list_pin_files(2026, get=lambda url, **kw: (seen.setdefault("url", url), Resp())[1])
    assert files == {"Leon": "leon_2026pin.zip", "Palm Beach": "palmbeach_2026pin.zip",
                     "Sarasota": "sarasota_2026pin.shp.zip", "Miami-Dade": "miamidade_2026pin.zip",
                     "St. Johns": "stjohns_2026pin.zip"}
    assert "2026F%20PIN" in seen["url"] and "condo" not in "".join(files.values())
    assert L.file_url(2026, "leon_2026pin.zip").endswith("/Map%20Data/2026F/2026F%20PIN/leon_2026pin.zip")


def _run(rows, files, fetchers, mode="dry_run", confirm="", only=None, applied=True):
    db, lines = FakeDb(rows, applied=applied), []
    counties = {}
    for r in rows:
        if r["source"] == "laft":
            counties[r["county"]] = counties.get(r["county"], 0) + 1
    rc = L.run(mode, confirm, year=2026, only=only, db=db, list_files=lambda y: files,
               fetch=lambda url, dest: fetchers[url.rsplit("/", 1)[1]](url, dest),
               counties_of=lambda d: counties, out=lines.append)
    return rc, db, "\n".join(lines)


def test_dry_run_reads_only_available_records_and_writes_nothing():
    rows = [_row("a", "Leon", "12-3456-0010", 30.4005, -84.2995), _row("x", "Leon", "12-3456-0010", 30.4005, -84.2995,
                                                                        source="auction")]
    rc, db, text = _run(rows, {"Leon": "leon_2026pin.zip"},
                        {"leon_2026pin.zip": _zip([("1234560010", (-84.30, 30.40))], "leon_2026pin")})
    assert rc == 0 and db.upserts == [] and db.refreshes == []
    assert set(db.sources) == {"laft"}
    assert "would write 1" in text and "1234560010" not in text and "12-3456" not in text


def test_apply_writes_each_county_and_a_failed_download_only_fails_its_own_county():
    rows = [_row("a", "Leon", "12-3456-0010", 30.4005, -84.2995), _row("b", "Bay", "999-1", 30.2, -85.6),
            _row("c", "Putnam", "77-1", 29.6, -81.9)]
    def broken(url, dest):
        raise ConnectionError("synthetic")
    rc, db, text = _run(rows, {"Leon": "leon_2026pin.zip", "Bay": "bay_2026pin.zip"},
                        {"leon_2026pin.zip": _zip([("1234560010", (-84.30, 30.40))], "leon_2026pin"),
                         "bay_2026pin.zip": broken}, mode="apply", confirm="APPLY")
    assert rc == 1
    assert [r["property_id"] for batch in db.upserts for r in batch] == ["a"]
    assert sorted(db.refreshes) == [("COMPLETE", "Leon"), ("FAILED", "Bay"), ("FAILED", "Putnam")]
    assert "NO_COUNTY_FILE" in text


def test_apply_needs_the_confirmation_and_both_migrations():
    rows = [_row("a", "Leon", "12-3456-0010", 30.4005, -84.2995)]
    assert _run(rows, {}, {}, mode="apply")[0] == 2
    rc, db, text = _run(rows, {}, {}, applied=False)
    assert rc == 4 and "035" in text and db.upserts == []
