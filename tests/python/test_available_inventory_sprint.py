"""AVAILABLE inventory sprint: Detroit Land Bank (lots + programs), Oceana
County Land Bank, Horry County FLC yearly lists, Georgetown FLC.

Every source is UNREVIEWED for publication: it is collected and HELD
(scripts/harvest_expansion.py run_held -> out/<st>_held_rows.json), never
written to properties. All fixtures here are SYNTHETIC."""
import io
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import harvest_expansion as HE  # noqa: E402
import source_publication as SP  # noqa: E402
from harvesters.ledgers import SOURCE_LEDGERS, Ledger  # noqa: E402
from harvesters.otc.adapters import arcgis as AG, expansion as EX, sc_flc  # noqa: E402
from harvesters.otc.adapters.tabular import TabularListAdapter  # noqa: E402

AT = datetime(2026, 10, 2, 12, tzinfo=timezone.utc)
SPRINT = EX.AVAILABLE_SPRINT_SOURCE_IDS


def _src(sid):
    return next(s for st in EX.SOURCES.values() for s in st if s.config.source_id == sid)


# --- Detroit Land Bank -------------------------------------------------------

def test_dlba_lots_reads_only_the_for_sale_lot_statuses():
    cfg = EX.MI_DETROIT_LANDBANK_LOTS
    where = AG.query_params(cfg)["where"]
    for s in EX.DLBA_LOT_STATUSES:
        assert f"'{s}'" in where and s.endswith("For Sale")
    assert "Owned" not in where and "Structure" not in where
    payload = {"objectIdFieldName": "OBJECTID", "features": [
        {"attributes": {"OBJECTID": 1, "parcel_id": "99000001.", "name": "1 SYNTHETIC ST",
                        "inventory_status_socrata": "Side Lot For Sale", "latitude": 42.3, "longitude": -83.1}},
        {"attributes": {"OBJECTID": 2, "parcel_id": "99000002.", "name": "", "inventory_status_socrata": "Neighborhood Lot For Sale",
                        "latitude": None, "longitude": None}}]}
    page = AG.parse_page(cfg, payload, retrieved_at=AT)
    assert [r.case_no for r in page.records] == ["99000001.", "99000002."]
    r = page.records[0]
    assert r.parcel == r.case_no and r.county == "Wayne" and r.state == "MI" and r.record_source == "laft"
    assert r.amount is None and r.owner_name is None
    assert not r.validate()


def test_dlba_programs_excludes_the_auction_program():
    assert AG.query_params(EX.MI_DETROIT_LANDBANK_PROGRAMS)["where"] == "program <> 'Auction'"


def test_dlba_feature_without_parcel_fails_the_read_never_zero():
    payload = {"features": [{"attributes": {"parcel_id": None, "inventory_status_socrata": "Side Lot For Sale"}}]}
    with pytest.raises(AG.ArcGisError):
        AG.parse_page(EX.MI_DETROIT_LANDBANK_LOTS, payload, retrieved_at=AT)


# --- Oceana County Land Bank -------------------------------------------------

OCEANA = """<html><body><h2>Current Available Properties</h2>
<table><tr><th>Parcel ID Number</th><th>Property Address</th></tr>
<tr><td>64-099-001-001-00</td><td>1 SYNTHETIC RD</td></tr>
<tr><td>64-099-001-002-00</td><td></td></tr></table></body></html>"""


def test_oceana_table_parses_identifier_and_address_only():
    recs = TabularListAdapter(EX.MI_OCEANA_LANDBANK).parse_html_table(OCEANA, retrieved_at=AT)
    assert [r.case_no for r in recs] == ["64-099-001-001-00", "64-099-001-002-00"]
    assert recs[0].address == "1 SYNTHETIC RD" and recs[1].address in (None, "")
    assert all(r.amount is None and r.owner_name is None and r.record_source == "laft" for r in recs)
    assert all(not r.validate() for r in recs)


def test_oceana_page_without_the_identifier_column_is_not_a_list():
    page = OCEANA.replace("Parcel ID Number", "Something Else")
    assert TabularListAdapter(EX.MI_OCEANA_LANDBANK).parse_html_table(page, retrieved_at=AT) == []


# --- Horry County FLC --------------------------------------------------------

HORRY_PAGE = """<html><body>
<a href="/media/a/2025-flc-list.xlsx">2025 FLC List</a>
<a href="/media/b/2024-flc-list.xlsx">2024 FLC List</a>
<a href="https://elsewhere.example/2023.xlsx">2023 FLC List</a>
<a href="/media/c/2022-flc-list.pdf">2022 FLC List</a>
<a href="/media/d/guidelines.pdf">Guidelines</a></body></html>"""
BASE = "https://horrycountysc.gov/boards-and-commissions/forfeited-land-commission/"


def _xlsx(rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _horry_book():
    return _xlsx([["2024 FLC LIST"], ["PIN", "ITEM #", "TAXPAYER", "DESCRIPTION", "MINIMUM BID"],
                  [12345678901, 1, "SYNTHETIC TAXPAYER ONE", "LOT 1 SYNTHETIC", 1500.0],
                  [12345678902, 2, "SYNTHETIC TAXPAYER TWO", "LOT 2 SYNTHETIC", 275.5]])


def test_year_list_links_keep_same_host_xlsx_year_lists_only():
    assert sc_flc.year_list_links(HORRY_PAGE, BASE) == [
        (2024, "https://horrycountysc.gov/media/b/2024-flc-list.xlsx"),
        (2025, "https://horrycountysc.gov/media/a/2025-flc-list.xlsx")]


def test_list_year_redemption_rule():
    assert sc_flc.list_year_past_redemption(2024, date(2026, 1, 1))
    assert not sc_flc.list_year_past_redemption(2025, date(2026, 10, 2))
    assert not sc_flc.list_year_past_redemption(2024, date(2025, 12, 31))


def test_xlsx_rows_keep_long_identifiers_whole():
    rows = sc_flc.xlsx_rows(_horry_book())
    assert rows[2][0] == "12345678901" and rows[2][4] in ("1500", "1500.0")


def test_horry_source_reads_only_lists_past_redemption_and_never_the_taxpayer(capsys):
    fetched = []

    def fetch_bytes(url):
        fetched.append(url)
        return _horry_book()

    status, recs, *_ = HE.run_source(_src("sc_horry_forfeited_land"), None, lambda u: HORRY_PAGE,
                                     retrieved_at=AT, fetch_bytes=fetch_bytes)
    assert status == "COMPLETE"
    assert fetched == ["https://horrycountysc.gov/media/b/2024-flc-list.xlsx"]   # 2025 still in redemption
    assert [r.case_no for r in recs] == ["12345678901", "12345678902"]
    assert recs[0].amount == 1500.0 and recs[0].amount_kind.value == "OPENING_BID"
    assert recs[0].legal_desc == "LOT 1 SYNTHETIC"
    dump = json.dumps([r.to_properties_row() for r in recs], default=str)
    assert "TAXPAYER ONE" not in dump and all(r.owner_name is None for r in recs)
    assert "2024 FLC List" in recs[0].provenance["tax_sale_year"]


def test_horry_with_only_lists_in_redemption_is_empty_not_failed():
    page = '<a href="/media/a/2025-flc-list.xlsx">2025 FLC List</a>'
    status, recs, _, _, empty = HE.run_source(_src("sc_horry_forfeited_land"), None, lambda u: page,
                                              retrieved_at=AT, fetch_bytes=lambda u: pytest.fail("no fetch"))
    assert (status, recs, empty) == ("EMPTY", [], "no_list_past_redemption")


def test_horry_page_without_year_lists_fails():
    status, *_ = HE.run_source(_src("sc_horry_forfeited_land"), None, lambda u: "<p>moved</p>", retrieved_at=AT,
                               fetch_bytes=lambda u: b"")
    assert status == "FAILED"


# --- held collection ---------------------------------------------------------

def _reg(st):
    return SP.registry_with_reviews(st, reviews={})[0]


def test_held_sources_are_exactly_the_unreviewed_available_sources():
    mi = {s.config.source_id for s in HE.held_sources("MI", _reg("MI"))}
    sc = {s.config.source_id for s in HE.held_sources("SC", _reg("SC"))}
    assert mi == {"mi_detroit_landbank_lots", "mi_detroit_landbank_programs", "mi_oceana_landbank"}
    assert sc == {"sc_horry_forfeited_land", "sc_georgetown_forfeited_land"}
    assert "sc_oconee_tax_sale_list" not in sc          # UNREVIEWED auction source: gated, never held
    for st in ("WY", "CO", "WI"):
        assert HE.held_sources(st, _reg(st)) == []
    for sid in SPRINT:
        assert not SP.publishable(_reg(_src(sid).config.state).get(sid))


def test_sprint_sources_are_available_ledger_only():
    for sid in SPRINT:
        assert SOURCE_LEDGERS[sid] == {Ledger.AVAILABLE}
        assert _src(sid).config.record_source == "laft"
        assert EX.PUBLICATION[sid][0] == "UNREVIEWED"


def test_run_held_writes_held_file_and_status_never_the_sync_file(tmp_path, capsys):
    def fetch_text(url):
        if "oceana" in url:
            return OCEANA
        raise ConnectionError("synthetic transport failure")

    held = [_src("mi_oceana_landbank"), _src("mi_detroit_landbank_lots")]
    n = HE.run_held("MI", held, lambda u: (_ for _ in ()).throw(ConnectionError("down")), fetch_text, None,
                    retrieved_at=AT, out=tmp_path)
    assert n == 2
    rows = json.loads((tmp_path / "mi_held_rows.json").read_text())
    assert {r["publication_status"] for r in rows} == {"UNREVIEWED"}
    assert {r["county"] for r in rows} == {"Oceana"} and all(r["source"] == "laft" for r in rows)
    status = json.loads((tmp_path / "harvest_mi_held_status.json").read_text())
    blob = json.dumps(status)
    assert "Oceana:mi_oceana_landbank" in blob and "Wayne:mi_detroit_landbank_lots" in blob
    assert "FAILED" in blob and "COMPLETE" in blob                    # one failure isolated from the other
    assert not (tmp_path / "mi_properties_rows.json").exists()
    out = capsys.readouterr().out
    assert "64-099" not in out and "SYNTHETIC" not in out             # shapes only in the public log


def test_run_held_with_nothing_held_writes_nothing(tmp_path):
    assert HE.run_held("WY", [], None, None, None, retrieved_at=AT, out=tmp_path) == 0
    assert list(tmp_path.iterdir()) == []


def test_sync_reads_only_the_publishable_rows_file():
    src = (ROOT / "scripts/sync_state_inventory.py").read_text(encoding="utf-8")
    assert "held_rows" not in src
