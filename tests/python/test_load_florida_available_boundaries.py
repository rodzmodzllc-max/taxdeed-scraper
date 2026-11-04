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
        wanted = set(str(source).split(","))
        return [r for r in self.rows if r["county"] == county and r["source"] in wanted]

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


# --- match mode: validated_id_only -------------------------------------------
# A record outlines in validated_id_only mode only through its validated NAL
# PARCEL_ID (field_provenance fdor_nal matched_parcel_id). Never through its
# listing parcel number, however unique, and never because its point lies inside
# a polygon. SYNTHETIC identifiers only.

class StoringDb(FakeDb):
    """FakeDb that remembers what was upserted, so a rerun sees it as stored."""

    def __init__(self, rows, applied=True):
        super().__init__(rows, applied)
        self.store = {}

    def stored(self, ids):
        return {i: self.store[i] for i in ids if i in self.store}

    def upsert(self, source_id, rows):
        self.upserts.append(rows)
        for r in rows:
            self.store[r["property_id"]] = {"source_id": source_id, "content_sha256": r["content_sha256"]}
        return {"inserted": len(rows)}


def _nal(row, nal, source="fdor_nal"):
    return dict(row, field_provenance={"parcel": {"source": source, "matched_parcel_id": nal}})


def _run_mode(rows, features, match_mode, mode="apply", db=None):
    db = db or StoringDb(rows)
    lines = []
    counties = {}
    for r in rows:
        counties[r["county"]] = counties.get(r["county"], 0) + 1
    rc = L.run(mode, "APPLY" if mode == "apply" else "", year=2026, db=db,
               list_files=lambda y: {"Leon": "leon_2026pin.zip"},
               fetch=lambda url, dest: _zip(features, "leon_2026pin")(url, dest),
               counties_of=lambda d: counties, out=lines.append, match_mode=match_mode)
    written = [r for batch in db.upserts for r in batch]
    return rc, db, written, "\n".join(lines)


def test_validated_id_only_joins_a_validated_nal_id_to_its_own_parcel():
    rows = [_nal(_row("a", "Leon", "12-3456-0010", 30.4005, -84.2995), "1234560010")]
    rc, db, written, text = _run_mode(rows, [("1234560010", (-84.30, 30.40)), ("1234560020", (-84.31, 30.41))],
                                      "validated_id_only")
    assert rc == 0
    assert [(r["property_id"], r["match_method"]) for r in written] == [("a", "EXACT_PARCEL_ID")]
    assert db.refreshes == [("COMPLETE", "Leon")]
    assert '"match_mode": "validated_id_only"' in text and '"listing_join": false' in text


def test_validated_id_only_never_falls_back_to_a_unique_listing_number_even_with_the_point_inside():
    # Unique listing parcel, own point inside that polygon: the default mode
    # outlines it, validated_id_only does not.
    rows = [_row("a", "Leon", "12-3456-0010", 30.4005, -84.2995)]
    feats = [("1234560010", (-84.30, 30.40))]
    rc, _, written, text = _run_mode(rows, feats, "validated_id_only")
    assert rc == 0 and written == []
    assert "NO_VALIDATED_NAL_ID" in text and "PARCEL_NUMBER_LOCATION_CONFIRMED" not in text
    rc, _, written, _ = _run_mode(rows, feats, "listing_location_confirmed")
    assert [r["match_method"] for r in written] == ["PARCEL_NUMBER_LOCATION_CONFIRMED"]


def test_validated_id_only_rejects_unvalidated_and_conflicting_ids():
    unvalidated = _nal(_row("u", "Leon", "12-3456-0010", 30.4005, -84.2995), "1234560010", source="county_list")
    conflicting = dict(_row("c", "Leon", "12-3456-0020", 30.4105, -84.3095),
                       field_provenance={"parcel": {"source": "fdor_nal", "matched_parcel_id": "1234560020"},
                                         "address": {"source": "fdor_nal", "matched_parcel_id": "1234560099"}})
    missing = _row("m", "Leon", "", 30.4005, -84.2995)
    rc, _, written, text = _run_mode([unvalidated, conflicting, missing],
                                     [("1234560010", (-84.30, 30.40)), ("1234560020", (-84.31, 30.41))],
                                     "validated_id_only")
    assert rc == 0 and written == []
    assert "CONFLICTING_NAL_IDS" in text and "NO_VALIDATED_NAL_ID" in text


def test_validated_id_only_never_attaches_an_ambiguous_parcel():
    rows = [_nal(_row("a", "Leon", "12-3456-0010", 30.4005, -84.2995), "1234560010")]
    # Two different polygons near the record carry the same PARCELNO: never attached.
    rc, _, written, _ = _run_mode(rows, [("1234560010", (-84.30, 30.40)), ("1234560010", (-84.3015, 30.4015))],
                                  "validated_id_only")
    assert rc == 0 and written == []


def test_validated_id_only_keeps_condo_units_and_rights_of_way_out():
    condo = dict(_nal(_row("k", "Leon", "12-3456-0010", 30.4005, -84.2995), "1234560010"), dor_use_code="04")
    row_ = dict(_nal(_row("r", "Leon", "12-3456-0020", 30.4105, -84.3095), "1234560020"), dor_use_code="94")
    rc, _, written, text = _run_mode([condo, row_], [("1234560010", (-84.30, 30.40)), ("1234560020", (-84.31, 30.41))],
                                     "validated_id_only")
    assert rc == 0 and written == []
    assert "CONDO_UNIT" in text and "RIGHT_OF_WAY" in text


def test_validated_id_only_rerun_writes_nothing_new():
    rows = [_nal(_row("a", "Leon", "12-3456-0010", 30.4005, -84.2995), "1234560010")]
    feats = [("1234560010", (-84.30, 30.40))]
    rc, db, written, _ = _run_mode(rows, feats, "validated_id_only")
    assert rc == 0 and len(written) == 1
    rc, db, written, text = _run_mode(rows, feats, "validated_id_only", db=db)
    assert rc == 0 and len(written) == 1          # nothing added on the rerun
    assert "would write" not in text and len(db.store) == 1


def test_validated_id_only_format_mismatch_fails_only_that_county_and_writes_nothing():
    # The validated id's shape is not the file's PARCELNO shape: the join is not
    # validated, nothing is attached and the county is recorded as unsuccessful.
    rows = [_nal(_row("a", "Leon", "12-3456-0010", 30.4005, -84.2995), "12-3456-0010")]
    rc, db, written, text = _run_mode(rows, [("1234560010", (-84.30, 30.40))], "validated_id_only")
    assert rc == 1 and written == []
    assert db.refreshes and all(status != "COMPLETE" for status, _ in db.refreshes)
    assert "JOIN_NOT_VALIDATED" in text


def test_validated_id_only_dry_run_writes_nothing():
    rows = [_nal(_row("a", "Leon", "12-3456-0010", 30.4005, -84.2995), "1234560010")]
    rc, db, written, text = _run_mode(rows, [("1234560010", (-84.30, 30.40))], "validated_id_only", mode="dry_run")
    assert rc == 0 and written == [] and db.refreshes == []
    assert "would write 1" in text and "1234560010" not in text


def test_an_unknown_match_mode_is_refused_before_anything_is_read():
    db = FakeDb([])
    lines = []
    rc = L.run("dry_run", "", year=2026, db=db, list_files=lambda y: (_ for _ in ()).throw(AssertionError("read")),
               counties_of=lambda d: (_ for _ in ()).throw(AssertionError("read")), out=lines.append,
               match_mode="nearest")
    assert rc == 2 and db.sources == [] and "unknown match mode" in lines[0]


def test_the_default_match_mode_is_unchanged_and_the_cli_and_workflow_expose_the_choice():
    import inspect
    assert L.DEFAULT_MATCH_MODE == "listing_location_confirmed"
    assert inspect.signature(L.run).parameters["match_mode"].default == "listing_location_confirmed"
    assert L.MATCH_MODES == {"listing_location_confirmed": True, "validated_id_only": False}
    wf = (ROOT / ".github/workflows/parcel-boundaries-florida-available.yml").read_text(encoding="utf-8")
    assert "options: [listing_location_confirmed, validated_id_only]" in wf
    assert '--match-mode "$MATCH_MODE"' in wf


# --- ledgers: Available by default, auctions and certificates when named ------

def test_ledgers_default_to_available_and_all_three_are_read_only_when_named():
    rows = [_row("a", "Leon", "12-3456-0010", 30.4005, -84.2995),
            _row("x", "Leon", "12-3456-0020", 30.4105, -84.3095, source="auction"),
            _row("c", "Leon", "12-3456-0030", 30.4205, -84.3195, source="certificate")]
    feats = [("1234560010", (-84.30, 30.40)), ("1234560020", (-84.31, 30.41)), ("1234560030", (-84.32, 30.42))]
    rc, db, written, text = _run_mode(rows, feats, "listing_location_confirmed")
    assert rc == 0 and [r["property_id"] for r in written] == ["a"]
    assert set(db.sources) == {"laft"} and '"ledgers": ["laft"]' in text
    db, lines = StoringDb(rows), []
    rc = L.run("apply", "APPLY", year=2026, db=db, list_files=lambda y: {"Leon": "leon_2026pin.zip"},
               fetch=lambda url, dest: _zip(feats, "leon_2026pin")(url, dest),
               counties_of=lambda d: {"Leon": 3}, out=lines.append,
               ledgers=("certificate", "auction", "laft"))
    written = sorted((r["property_id"], r["match_method"]) for batch in db.upserts for r in batch)
    assert rc == 0 and written == [("a", "PARCEL_NUMBER_LOCATION_CONFIRMED"), ("c", "PARCEL_NUMBER_LOCATION_CONFIRMED"),
                                   ("x", "PARCEL_NUMBER_LOCATION_CONFIRMED")]
    assert db.sources == ["laft,auction,certificate"]
    assert '"ledgers": ["laft", "auction", "certificate"]' in "\n".join(lines)


def test_an_unknown_or_empty_ledger_set_is_refused_before_anything_is_read():
    for bad in (("laft", "deeds"), ()):
        db, lines = FakeDb([]), []
        rc = L.run("dry_run", "", year=2026, db=db, list_files=lambda y: (_ for _ in ()).throw(AssertionError("read")),
                   counties_of=lambda d: (_ for _ in ()).throw(AssertionError("read")), out=lines.append, ledgers=bad)
        assert rc == 2 and db.sources == [] and "ledgers must be" in lines[0]


def test_the_ledger_filter_and_the_workflow_input(monkeypatch):
    import importlib.util as iu
    assert L.ledger_filter(("laft",)) == "eq.laft"
    assert L.ledger_filter(("laft", "auction", "certificate")) == "in.(laft,auction,certificate)"
    spec = iu.spec_from_file_location("pbr", ROOT / "scripts" / "parcel_boundary_refresh.py")
    R = iu.module_from_spec(spec); spec.loader.exec_module(R)
    seen = {}

    class Src:
        location, state, counties = "files", "FL", ()
    db = R.Db.__new__(R.Db)
    db.url, db.h = "https://example.invalid", {}
    import types
    fake = types.ModuleType("rest_pages")
    fake.read_all = lambda url, table, h, params: seen.setdefault("p", params) and []
    monkeypatch.setitem(__import__("sys").modules, "rest_pages", fake)
    db.properties(Src(), "Leon", source="laft,auction,certificate")
    assert seen["p"]["source"] == "in.(laft,auction,certificate)"
    seen.clear()
    db.properties(Src(), "Leon", source="laft")
    assert seen["p"]["source"] == "eq.laft"
    wf = (ROOT / ".github/workflows/parcel-boundaries-florida-available.yml").read_text(encoding="utf-8")
    assert 'options: [laft, "laft,auction,certificate"]' in wf and "default: laft" in wf
    assert '--ledgers "$LEDGERS"' in wf


def _http_error(status):
    import requests
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(response=resp)


def test_download_retries_a_dropped_connection_and_removes_the_partial_file(tmp_path):
    import requests
    dest = tmp_path / "f.zip"
    calls, sleeps = [], []

    def once(url, d):
        calls.append(url)
        d.write_bytes(b"partial")
        if len(calls) < 3:
            raise requests.ConnectionError("dropped")
        d.write_bytes(b"whole")

    L.download("u", dest, once=once, sleep=sleeps.append)
    assert len(calls) == 3 and dest.read_bytes() == b"whole"
    assert sleeps == list(L.DOWNLOAD_BACKOFF_S[:2])


def test_download_gives_up_after_the_last_attempt(tmp_path):
    import requests

    def once(url, d):
        raise requests.ConnectionError("dropped")

    with pytest.raises(requests.ConnectionError):
        L.download("u", tmp_path / "f.zip", once=once, sleep=lambda s: None)


def test_download_retries_5xx_but_never_4xx(tmp_path):
    seen = []

    def once_5xx(url, d):
        seen.append(1)
        if len(seen) == 1:
            raise _http_error(503)

    L.download("u", tmp_path / "f.zip", once=once_5xx, sleep=lambda s: None)
    assert len(seen) == 2

    seen4 = []

    def once_404(url, d):
        seen4.append(1)
        raise _http_error(404)

    import requests
    with pytest.raises(requests.HTTPError):
        L.download("u", tmp_path / "g.zip", once=once_404, sleep=lambda s: None)
    assert len(seen4) == 1
