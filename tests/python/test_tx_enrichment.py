"""Texas enrichment (2026-10-27): property facts from the TxGIO StratMap county
files and the HCAD parcel layer, and county acquisition processes recorded
from capture run 40430155571 - applied to AVAILABLE and AUCTIONS rows by
ledger scope.

Everything here is offline: synthetic shapefiles, synthetic rows, the
repository's own data files."""
from __future__ import annotations

import csv
import io
import json
import sys
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import apply_acquisition_paths as AAP  # noqa: E402
import build_acquisition_evidence as BAE  # noqa: E402
import enrich_statewide_parcels as ESP  # noqa: E402
import purchase_path_engine as PE  # noqa: E402
from harvesters.enrichment import county_file as CF  # noqa: E402
from harvesters.enrichment import parcels as P  # noqa: E402
from harvesters.enrichment import sources as S  # noqa: E402
from harvesters.governance import permissions as PERM  # noqa: E402

shapefile = pytest.importorskip("shapefile")

DAY = __import__("datetime").date(2026, 10, 27)
WGS84 = ('GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
         'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]')
PROJECTED = 'PROJCS["NAD_1983_StatePlane_Texas_Central",GEOGCS["GCS_North_American_1983"]]'
FIELDS = ("PROP_ID", "GEO_ID", "STAT_LAND_", "LEGAL_AREA", "LGL_AREA_U", "LAND_VALUE", "IMP_VALUE", "MKT_VALUE",
          "TAX_YEAR", "YEAR_BUILT", "SOURCE", "DATE_ACQ", "SITUS_ADDR", "LEGAL_DESC")


def make_zip(tmp_path, records, prj=WGS84, name="county") -> Path:
    """A zipped polygon shapefile with the StratMap attribute names."""
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON)
    for f in FIELDS:
        w.field(f, "C", size=60)
    for i, rec in enumerate(records):
        x, y = -96.5 + i * 0.01, 32.0
        w.poly([[[x, y], [x, y + 0.001], [x + 0.001, y + 0.001], [x + 0.001, y], [x, y]]])
        w.record(*[str(rec.get(f, "")) for f in FIELDS])
    w.close()
    path = tmp_path / f"{name}.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{name}.shp", shp.getvalue())
        z.writestr(f"{name}.shx", shx.getvalue())
        z.writestr(f"{name}.dbf", dbf.getvalue())
        if prj:
            z.writestr(f"{name}.prj", prj)
    return path


def cfg(**kw) -> P.ParcelSourceConfig:
    base = dict(source_id="zz_county_files", state="TX", agency="test", dataset="test",
                landing_url="https://example.gov/", layer_url="https://example.gov/files/",
                file_url_template="https://example.gov/files/county_{fips}.zip", transport="county_file",
                id_field="PROP_ID", id_rule="alnum", row_id_column="case_no",
                county_id={"Alpha": (("GEO_ID",), "alnum"), "Beta": (("PROP_ID",), "numeric")},
                county_fips={"Alpha": "48001", "Beta": "48003"}, counties=("Alpha", "Beta"),
                field_map=dict(S.TX_STRATMAP.field_map), conditional_map=dict(S.TX_STRATMAP.conditional_map),
                value_year_field="TAX_YEAR", licence="test", publication_status="APPROVED", centroid=True,
                columns_verified=True, fill_blank_only=True, row_source_ids=("tx_lgbs",))
    base.update(kw)
    return P.ParcelSourceConfig(**base)


@pytest.fixture
def allow_permissions(monkeypatch):
    monkeypatch.setattr(P, "PERMISSION_CHECK", lambda c: (True, ""))


# --------------------------------------------------------------- configuration

def test_county_file_config_is_validated():
    with pytest.raises(ValueError, match="file_url_template"):
        cfg(file_url_template="http://example.gov/county_{fips}.zip")
    with pytest.raises(ValueError, match="measured identifier rule"):
        cfg(counties=("Alpha",))
    with pytest.raises(ValueError, match="FIPS"):
        cfg(county_fips={"Alpha": "48001"})
    with pytest.raises(ValueError, match="identifier rule"):
        cfg(county_id={"Alpha": (("GEO_ID",), "guess"), "Beta": (("PROP_ID",), "numeric")})
    c = cfg()
    assert c.file_url("Beta") == "https://example.gov/files/county_48003.zip"
    assert P.query_urls(c, "Alpha", ["1", "2"]) == ["https://example.gov/files/county_48001.zip"]
    assert P.query_urls(c, "Gamma", ["1"]) == []          # a county without a measured rule is never read


def test_stratmap_config_is_the_measured_one():
    c = S.TX_STRATMAP
    assert c.transport == "county_file" and c.row_id_column == "case_no" and c.fill_blank_only and c.centroid
    assert set(c.counties) == set(c.county_id) == set(c.county_fips)
    assert len(c.counties) == 83
    # Counties whose sampled accounts did not match are never covered.
    for county in ("Tarrant", "Hunt", "Matagorda", "Smith", "Grayson", "Hardin", "Red River", "Travis"):
        assert not c.covers(county)
    assert c.county_fips["Dallas"] == "48113" and c.county_fips["Harris"] == "48201"
    assert c.file_url("Dallas").endswith("/items/shp/stratmap-2026-land-parcels_48113_shp.zip")
    for county, (fields_, rule) in c.county_id.items():
        assert set(fields_) <= {"PROP_ID", "GEO_ID"} and rule in ("alnum", "numeric"), county
    # Never the columns the Texas listing syncs write themselves, never owners.
    mapped = set(c.field_map) | set(c.conditional_map)
    assert not mapped & {"address", "legal_desc", "owner_name", "assessed"}
    assert c.conditional_map["acreage"] == ("LEGAL_AREA", "LGL_AREA_U", ("ACRE", "ACRES", "AC"))
    assert c.row_source_ids == ("tx_lgbs", "tx_realauction", "tx_pbfcm", "tx_mvba", "tx_govease")


def test_hcad_config_and_overlap_rule():
    h = S.TX_HCAD
    assert h.counties == ("Harris",) and h.id_field == "HCAD_NUM" and h.fill_blank_only
    assert not {"address", "legal_desc", "owner_name"} & set(h.field_map)
    assert {c.source_id for c in S.for_county("TX", "Harris")} == {"tx_hcad_parcels", "tx_txgio_stratmap_parcels"}
    # Two county layers may overlap only when one of them is fill-blank only.
    from dataclasses import replace
    with pytest.raises(ValueError, match="overlaps"):
        S.register(replace(S.TX_JIM_WELLS_CAD, source_id="zz_overlap"))       # neither is fill-blank only
    assert "zz_overlap" not in {c.source_id for c in S.all_sources()}
    # The StratMap county files serve Jim Wells next to its own CAD layer (fill-blank only).
    assert {c.source_id for c in S.for_county("TX", "Jim Wells")} == {"tx_jim_wells_cad_parcels", "tx_txgio_stratmap_parcels"}


def test_new_sources_hold_interim_permissions_only():
    p = PERM.Permissions.from_file()
    for sid in ("tx_txgio_stratmap_parcels", "tx_hcad_parcels"):
        for op in ("fetch", "enrich", "store"):
            d = p.authorize(sid, op, state="TX", today=DAY)
            assert d.allowed and d.basis == "INTERIM" and not d.documented, (sid, op)
        for op in ("display", "redistribute"):
            assert not p.authorize(sid, op, state="TX", today=DAY).allowed
        assert P.enrichment_allowed(S.TX_STRATMAP if sid.startswith("tx_txgio") else S.TX_HCAD)[0]
    d = p.authorize("tx_county_sale_process", "discover", state="TX", today=DAY)
    assert d.allowed and not d.documented
    assert not p.authorize("tx_county_sale_process", "fetch", state="TX", today=DAY).allowed


def test_geocoder_never_queries_a_county_file_source():
    from harvesters.enrichment import geocode as G
    assert "tx_txgio_stratmap_parcels" not in {s.source_id for s in G.coordinate_sources()}
    assert "tx_hcad_parcels" in {s.source_id for s in G.coordinate_sources()}


# ------------------------------------------------------------------ the reader

def test_reader_keeps_only_requested_identifiers_and_the_polygon(tmp_path):
    z = make_zip(tmp_path, [{"GEO_ID": "1001", "LAND_VALUE": "5000"}, {"GEO_ID": "1002"}, {"GEO_ID": "1003"}])
    fts = CF.read_county_zip(z, cfg(), "Alpha", {"1002"})
    assert [f["attributes"]["GEO_ID"] for f in fts] == ["1002"]
    assert fts[0]["geometry"]["rings"] and len(fts[0]["geometry"]["rings"][0]) == 5


def test_reader_derives_no_geometry_from_a_projected_file(tmp_path):
    z = make_zip(tmp_path, [{"GEO_ID": "1001"}], prj=PROJECTED)
    fts = CF.read_county_zip(z, cfg(), "Alpha", {"1001"})
    assert len(fts) == 1 and "geometry" not in fts[0]
    z2 = make_zip(tmp_path, [{"GEO_ID": "1001"}], prj=None, name="noprj")
    assert "geometry" not in CF.read_county_zip(z2, cfg(), "Alpha", {"1001"})[0]


def test_reader_refuses_a_changed_format(tmp_path):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("readme.txt", "no shapefile")
    with pytest.raises(ValueError):
        CF.read_county_zip(path, cfg(), "Alpha", {"1"})
    z = make_zip(tmp_path, [{"GEO_ID": "1"}], name="ok")
    with pytest.raises(ValueError, match="identifier attribute"):
        CF.read_county_zip(z, cfg(county_id={"Alpha": (("ACCOUNT",), "alnum"), "Beta": (("PROP_ID",), "numeric")}), "Alpha", {"1"})


# ----------------------------------------------------------------- the pipeline

def _run(tmp_path, rows, records, c=None, county="Alpha"):
    c = c or cfg()
    z = make_zip(tmp_path, records)
    seen = []

    def fetcher(cfg_, county_, keys):
        seen.append((county_, sorted(keys)))
        return lambda url: {"features": CF.read_county_zip(z, cfg_, county_, keys)}
    writes = {}
    rep = ESP.run("TX", rows, None, write=lambda i, f: writes.__setitem__(i, f), recorded_at="2026-10-27T00:00:00+00:00",
                  cfg=c, county_fetcher=fetcher)
    return rep, writes, seen


def row(i, account, county="Alpha", source_id="tx_lgbs", **kw):
    return {"id": str(i), "county": county, "source": "laft", "source_id": source_id, "case_no": account,
            "field_provenance": {}, **kw}


def test_exact_match_fills_blank_facts_with_provenance(tmp_path, allow_permissions):
    rep, writes, seen = _run(tmp_path, [row(1, "10-01")], [
        {"GEO_ID": "1001", "STAT_LAND_": "C1", "LEGAL_AREA": "0.25", "LGL_AREA_U": "ACRES", "LAND_VALUE": "12000",
         "IMP_VALUE": "0", "MKT_VALUE": "12000", "TAX_YEAR": "2026", "YEAR_BUILT": "1985", "SOURCE": "ALPHA CAD"}])
    assert seen == [("Alpha", ["1001"])]
    w = writes["1"]
    assert (w["land_use"], w["acreage"], w["land_value"], w["market"], w["year_built"], w["value_year"]) == ("C1", 0.25, 12000.0, 12000.0, 1985, 2026)
    assert "improvement_value" not in w                       # a zero is not a published value
    assert 31.9 < w["latitude"] < 32.1 and -96.6 < w["longitude"] < -96.4
    prov = w["field_provenance"]["acreage"]
    assert prov["source"] == "statewide_parcel" and prov["source_id"] == "zz_county_files"
    assert prov["matched_id_field"] == "GEO_ID" and prov["id_rule"] == "alnum" and prov["matched_parcel_id"] == "1001"
    assert prov["layer_url"] == "https://example.gov/files/county_48001.zip"
    assert rep["matched"] == 1 and rep["rows_written"] == 1


def test_never_overwrites_and_never_guesses(tmp_path, allow_permissions):
    rows = [row(1, "1001", land_use="A1", market=99.0),          # filled columns stay as they are
            row(2, "2002"),                                       # no feature -> nothing
            row(3, "3003"),                                       # two features -> ambiguous, nothing
            row(4, "4004", source_id="tx_jefferson_sheriff_sale"),  # a source whose case_no is not the account
            row(5, "5005")]
    records = [{"GEO_ID": "1001", "STAT_LAND_": "C1", "MKT_VALUE": "5", "LAND_VALUE": "7"},
               {"GEO_ID": "3003", "LAND_VALUE": "1"}, {"GEO_ID": "3003", "LAND_VALUE": "2"},
               {"GEO_ID": "4004", "LAND_VALUE": "3"},
               {"GEO_ID": "5005", "YEAR_BUILT": "1990,2005", "LEGAL_AREA": "12", "LGL_AREA_U": "SQUARE METER", "LAND_VALUE": "9"}]
    rep, writes, _ = _run(tmp_path, rows, records)
    assert set(writes["1"]) - {"field_provenance", "latitude", "longitude", "value_year"} == {"land_value"}
    assert "2" not in writes and "3" not in writes and "4" not in writes
    assert "year_built" not in writes["5"] and "acreage" not in writes["5"]
    assert (rep["matched"], rep["unmatched"], rep["ambiguous"], rep["rows_considered"]) == (2, 1, 1, 4)


def test_numeric_rule_only_where_measured(tmp_path, allow_permissions):
    rep, writes, _ = _run(tmp_path, [row(1, "R0042", county="Beta")], [{"PROP_ID": "42", "LAND_VALUE": "10"}], county="Beta")
    assert writes["1"]["land_value"] == 10.0 and writes["1"]["field_provenance"]["land_value"]["id_rule"] == "numeric"
    rep, writes, _ = _run(tmp_path, [row(1, "R0042")], [{"GEO_ID": "42", "LAND_VALUE": "10"}])     # Alpha: alnum
    assert writes == {} and rep["unmatched"] == 1


def test_a_failed_county_read_writes_nothing(allow_permissions):
    def fetcher(cfg_, county_, keys):
        def fail(url):
            raise OSError("connection reset")
        return fail
    writes = {}
    rep = ESP.run("TX", [row(1, "1001")], None, write=lambda i, f: writes.__setitem__(i, f), recorded_at="x", cfg=cfg(),
                  county_fetcher=fetcher, retries=1, sleep=lambda s: None)
    assert writes == {} and rep["failed_queries"] == 1


def test_select_rows_batches_by_county_and_ledger():
    rows = [row(i, str(i), county=c) | {"source": s} for i, (c, s) in enumerate(
        [("A", "laft"), ("A", "auction"), ("B", "laft"), ("C", "certificate"), ("C", "laft"), ("C", "laft")])]
    assert {r["id"] for r in ESP.select_rows(rows, ledgers=["laft", "auction"])} == {"0", "1", "2", "4", "5"}
    assert {r["county"] for r in ESP.select_rows(rows, max_counties=1)} == {"C"}
    assert {r["id"] for r in ESP.select_rows(rows, counties=["A"], ledgers=["auction"])} == {"1"}


# --------------------------------------------------------------- how to buy

RUN = "40430155571"
NEW_UNITS = {("tx_lgbs", "Dallas"), ("tx_lgbs", "Tarrant"), ("tx_lgbs", "Harris"), ("tx_lgbs", "Jefferson"),
             ("tx_lgbs", "Orange"), ("tx_realauction", "Orange"), ("tx_lgbs", "Bexar"), ("tx_lgbs", "Fort Bend"),
             ("tx_realauction", "Galveston")}


def test_new_texas_evidence_rows_cite_the_capture():
    ev = {(e.source_id, e.county): e for e in PE.load_evidence() if e.state == "TX"}
    assert NEW_UNITS <= set(ev)
    with open(PE.EVIDENCE_PATH, newline="", encoding="utf-8") as fh:
        notes = {(r["source_id"], r["county"]): r["notes"] for r in csv.DictReader(fh) if r["state"] == "TX"}
    for key in NEW_UNITS:
        e = ev[key]
        assert e.applicable and e.evidence_url.startswith("https://") and e.instructions and e.steps, key
        assert e.observed_on == ("2026-10-01" if key == ("tx_realauction", "Galveston") else "2026-10-27"), key
        assert (RUN if e.observed_on == "2026-10-27" else "36858070184") in notes[key], key
        assert "lgbs.com" not in e.evidence_url and "lgbs.com" not in e.url
    # A named staff e-mail is never recorded (Bexar's document names one).
    assert ev[("tx_lgbs", "Bexar")].email == ""


def test_ledger_scope_file_is_valid_and_complete():
    scope = PE.load_ledger_scope()
    applicable = {(e.state, e.source_id, e.county) for e in PE.load_evidence() if e.applicable}
    assert set(scope) <= applicable
    assert {("TX",) + k for k in NEW_UNITS} <= set(scope)
    assert scope[("TX", "tx_lgbs", "Tarrant")] == {"AUCTIONS"}
    assert scope[("TX", "tx_lgbs", "Dallas")] == {"AVAILABLE"}
    assert scope[("TX", "tx_lgbs", "Harris")] == {"AUCTIONS", "AVAILABLE"}


def test_ledger_scope_rejects_bad_rows(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text("state,source_id,county,ledgers,basis\nTX,tx_lgbs,Dallas,EVERYTHING,x\n", encoding="utf-8")
    with pytest.raises(ValueError):
        PE.load_ledger_scope(p)
    p.write_text("state,source_id,county,ledgers,basis\nTX,tx_lgbs,Dallas,AVAILABLE,\n", encoding="utf-8")
    with pytest.raises(ValueError):
        PE.load_ledger_scope(p)


REG = {("tx_lgbs", "Galveston"): {"canonical_url": "https://taxsales.lgbs.com/", "last_checked": "2026-09-23",
                                  "verification_status": "PRODUCTION_VERIFIED"},
       ("tx_lgbs", "Goliad"): {"canonical_url": "https://taxsales.lgbs.com/", "last_checked": "2026-09-23",
                               "verification_status": "PRODUCTION_VERIFIED"},
       ("tx_realauction", "Orange"): {"canonical_url": "https://orange.texas.sheriffsaleauctions.com/index.cfm?zaction=USER&zmethod=CALENDAR",
                                      "last_checked": "2026-10-26", "verification_status": "PRODUCTION_VERIFIED"},
       ("tx_realauction", "Galveston"): {"canonical_url": "https://galveston.texas.sheriffsaleauctions.com/index.cfm?zaction=USER&zmethod=CALENDAR",
                                         "last_checked": "2026-10-26", "verification_status": "PRODUCTION_VERIFIED"}}


def plan(source, county, ledger):
    r = {"id": "1", "state": "TX", "county": county, "source": ledger, "source_id": source, "case_no": "A1",
         "status": "active", "otc_provenance": {}}
    return AAP.plan_row(r, registry=REG, evidence=PE.load_evidence(), state="TX", today="2026-10-27",
                        scope=PE.load_ledger_scope())


def test_evidence_applies_only_to_its_ledgers():
    payload, outcome = plan("tx_lgbs", "Tarrant", "auction")
    assert outcome == "path" and payload["purchase_path_type"] == "county_instructions"
    assert plan("tx_lgbs", "Tarrant", "laft")[1].startswith("no_verified_evidence")       # AUCTIONS-only process
    assert plan("tx_lgbs", "Dallas", "laft")[1] == "path"
    assert plan("tx_lgbs", "Dallas", "auction")[1].startswith("no_verified_evidence")     # resale-only process
    for ledger in ("laft", "auction"):
        assert plan("tx_lgbs", "Harris", ledger)[1] == "path"
    assert plan("tx_realauction", "Orange", "auction")[1] == "path"
    payload, _ = plan("tx_lgbs", "Orange", "laft")
    assert payload["purchase_path_type"] == "application_download"
    # An evidence row with no scope entry stays an AVAILABLE process.
    assert PE.evidence_ledgers(next(e for e in PE.load_evidence() if e.state == "FL"), PE.load_ledger_scope()) == {"AVAILABLE"}


def test_statewide_listing_reaches_counties_off_the_roster_but_never_borrows_a_county_site():
    payload, outcome = plan("tx_lgbs", "Dallas", "laft")           # Dallas is not on the 8-county LGBS roster
    assert outcome == "path" and payload["list_url"] == "https://taxsales.lgbs.com/"
    assert payload["otc_provenance"]["source_match"]["value"] == "A1"
    assert AAP.statewide_listing_row(REG, "tx_realauction", "Dallas") is None
    assert AAP.statewide_listing_row(REG, "tx_lgbs", "Navarro")["county"] == "Navarro"
    assert plan("tx_realauction", "Dallas", "auction") == (None, "no_registry_row")


def test_fetch_rows_reads_the_requested_ledgers_by_keyset(monkeypatch):
    seen = []
    monkeypatch.setattr(AAP, "_req", lambda method, url, key, body=None: seen.append(url) or [])
    AAP.fetch_rows("https://x.invalid", "k", "TX", None, ("laft", "auction"))
    q = parse_qs(urlsplit(seen[0]).query)
    assert q["source"] == ["in.(laft,auction)"] and "offset" not in q and "or" not in q


def test_available_records_leave_out_auction_only_processes():
    keys = {(r["state"], r["source_id"], r["county"]) for r in BAE.records()}
    assert ("TX", "tx_lgbs", "Dallas") in keys and ("TX", "tx_lgbs", "Harris") in keys
    assert ("TX", "tx_lgbs", "Tarrant") not in keys and ("TX", "tx_lgbs", "Fort Bend") not in keys
    assert ("TX", "tx_realauction", "Orange") not in keys


def test_workflow_applies_texas_enrichment_and_paths_to_both_ledgers():
    wf = (REPO / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8")
    assert "--source-id tx_hcad_parcels,tx_txgio_stratmap_parcels --ledgers laft,auction" in wf
    assert wf.count("apply_acquisition_paths.py --state TX --ledgers laft,auction") == 2
    assert "--source-id tx_lgbs --report out/public/acquisition-apply-tx.json" not in wf
