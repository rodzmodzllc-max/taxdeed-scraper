"""New-sources sprint (owner decision 2026-10-26): every source added in this
sprint parses fixtures shaped exactly like the live responses read on
2026-10-26 (field names, header labels, page structure - every VALUE below is
synthetic), is collected for admins and never customer-published, and holds
only owner-accepted INTERIM permission records (never display)."""
from __future__ import annotations

import dataclasses
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
from harvesters.governance import permissions as PERM  # noqa: E402
from harvesters.ledgers import SOURCE_LEDGERS, Ledger  # noqa: E402
from harvesters.otc.adapters import arcgis as AG, epropertyplus as EPP, expansion as EX  # noqa: E402
from harvesters.otc.adapters import paged_table as PT, tax_sale_info as TSI  # noqa: E402
from harvesters.otc.model import AmountKind  # noqa: E402

AT = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
DAY = date(2026, 10, 26)


def _src(source_id, county=None):
    for srcs in EX.SOURCES.values():
        for s in srcs:
            if s.config.source_id == source_id and (county is None or s.config.county == county):
                return s
    raise AssertionError(source_id)


# ---------------------------------------------------------------- governance --

def test_every_new_source_is_unreviewed_collected_and_never_displayed():
    assert EX.NEW_SOURCE_IDS
    perms = PERM.Permissions.from_file()
    for sid in EX.NEW_SOURCE_IDS:
        src = _src(sid)
        st = src.config.state
        reg = SP.registry_with_reviews(st, reviews={})[0]
        row = reg[sid]
        assert row.is_production and row.publication_status == "UNREVIEWED", sid
        assert "Owner decision 2026-10-26" in row.restrictions
        assert SP.collectable(row, src.config.record_source) and not SP.publishable(row), sid
        assert SP.owner_collection(row)
        for op in ("discover", "fetch", "parse", "store"):
            d = perms.authorize(sid, op, state=st, today=DAY)
            assert d.allowed and d.basis == "INTERIM", (sid, op, d.reason_code)
        assert perms.authorize(sid, "display", state=st, today=DAY).reason_code == "NO_RECORD"
        assert not perms.authorize(sid, "fetch", state=st, today=date(2027, 4, 13)).allowed       # expires
        want = {"auction": Ledger.AUCTIONS, "laft": Ledger.AVAILABLE, "certificate": Ledger.LIENS_CERTIFICATES}
        assert SOURCE_LEDGERS[sid] == {want[src.config.record_source]}, sid


def test_owner_collection_never_reaches_a_source_outside_the_sprint():
    reg = SP.registry_with_reviews("WI", reviews={})[0]
    assert not SP.owner_collection(reg["wi_dane_tax_deed_auction"])
    assert not SP.collectable(reg["wi_dane_tax_deed_auction"], "auction")          # unreviewed auction: still not collected


def test_the_gate_lets_each_new_state_run():
    for st in ("MI", "MO", "PA", "SC", "CO", "MN"):
        reg = SP.registry_with_reviews(st, reviews={})[0]
        assert HE.gate(st, reg=reg) == []
        run, _ = HE.runnable_sources(st, reg)
        assert {s.config.source_id for s in run} >= {sid for sid in EX.NEW_SOURCE_IDS if _src(sid).config.state == st}


# ------------------------------------------------------------- ePropertyPlus --

def _epp_row(**kw):
    base = {"id": 1, "parcelNumber": "JA00000000000000001", "county": "Jackson", "state": "MO", "city": "Kansas City",
            "propertyAddress1": "1 SYNTHETIC ST", "propertyClass": "Residential Vacant", "inventoryType": "Land Bank",
            "askingPrice": 1000.0, "comments": "never mapped", "latitude": 39.05, "longitude": -94.5,
            "legalDescription": "LOT 1 SYNTHETIC PLAT"}
    base.update(kw)
    return base


def test_kc_reads_list_presence_keeps_jackson_and_drops_the_vendor_test_row():
    rows = [_epp_row(), _epp_row(id=2, parcelNumber="JA00000000000000002", county="JACKSON "),
            _epp_row(id=3, parcelNumber="JA00000000000000003", county="Clay"),
            _epp_row(id=4, parcelNumber="AAA-AAAA", inventoryType="ePP TEST")]
    payload = {"success": True, "size": len(rows), "rows": rows}
    res = EPP.fetch_all(EX.MO_KC_LANDBANK, lambda url: payload, retrieved_at=AT)
    assert res.outcome == "COMPLETE" and [r.case_no for r in res.records] == ["JA00000000000000001", "JA00000000000000002"]
    assert res.excluded_county == 1 and res.excluded_status == 1
    r = res.records[0]
    assert r.amount == 1000.0 and r.amount_kind is AmountKind.PUBLISHED_AMOUNT_KIND_UNSPECIFIED
    assert r.county == "Jackson" and r.legal_desc == "LOT 1 SYNTHETIC PLAT" and r.latitude == 39.05
    assert "comments" not in json.dumps(r.provenance)


def test_pittsburgh_reads_only_its_custom_available_for_sale_status():
    rows = [_epp_row(parcelNumber="0003K00037000000", county="Allegheny", state="PA", s_custom_0010="Available for Sale"),
            _epp_row(id=2, parcelNumber="0003K00038000000", county="Allegheny", state="PA", s_custom_0010="Sale Pending"),
            _epp_row(id=3, parcelNumber="0003K00039000000", county="Allegheny", state="PA", s_custom_0010=None)]
    res = EPP.fetch_all(EX.PA_PITTSBURGH_CITY_PROPERTY, lambda url: {"success": True, "size": 3, "rows": rows}, retrieved_at=AT)
    assert [r.case_no for r in res.records] == ["0003K00037000000"] and res.excluded_status == 2
    assert res.records[0].source_status_text == "Available for Sale"


def test_wayne_county_land_bank_reads_its_available_flag():
    rows = [_epp_row(parcelNumber="30004020981000", county="WAYNE", state="MI", available="Y"),
            _epp_row(id=2, parcelNumber="30004020982000", county="WAYNE", state="MI", available="N")]
    res = EPP.fetch_all(EX.MI_WAYNE_COUNTY_LANDBANK, lambda url: {"success": True, "size": 2, "rows": rows}, retrieved_at=AT)
    assert [r.case_no for r in res.records] == ["30004020981000"]


def test_a_tenant_missing_its_offered_field_is_a_format_change():
    rows = [_epp_row(parcelNumber="30004020981000", county="WAYNE", state="MI")]          # no `available` field
    res = EPP.fetch_all(EX.MI_WAYNE_COUNTY_LANDBANK, lambda url: {"success": True, "size": 1, "rows": rows}, retrieved_at=AT)
    assert res.outcome == "FAILED"


# -------------------------------------------------------------- Tax-Sale.info --

AUCTIONS_HTML = """<html><body><h1>2026 UPCOMING AUCTIONS</h1>
<div class="entry clearfix"><div class="entry-c"><ul class="entry-meta clearfix"><li><a href="/listings/auction/807">
10:00am EDT to 7:00pm EDT October 30, 2026</a></li></ul><div class="entry-content"><p><b>Ready to Browse:</b>
<a href="/listings/catalog/1">Saginaw</a>, <a href="/listings/catalog/2">Saint Clair</a>, <a href="/listings/catalog/3">Lapeer DNR</a>
</p></div></div></div>
<h1>PAST AUCTIONS FROM THIS SEASON</h1>
<div class="entry clearfix"><ul class="entry-meta"><li>August 3, 2026</li></ul>
<a href="/listings/catalog/9">Saginaw</a></div></body></html>"""
SURPLUS_HTML = """<html><body><h1>SURPLUS PROPERTIES</h1><p>Surplus Property Sales Including
<a href="/listings/catalog/11">Otsego Surplus 2026</a>, <a href="/listings/catalog/12">Bay Surplus 2026</a></p>
<p><a href="/listings/catalog/1">Saginaw</a></p></body></html>"""
CSV_HEADER = ('"Lot Number","Minimum Bid","Current Taxes","Parcel Id",County,Address,"Local Unit",Section,Township,Range,SEV,'
              '"Legal Description",CIS,"Comment 2",Latitude,Longitude,"Alt Latitude","Alt Longitude"\n')
CSV_ROW = '{lot},{bid},16.68,{pid},{county},"1 SYNTHETIC RD","SYNTHETIC TWP",25,20N,03E,1400,"LOT 1 SYNTHETIC",,"free text",43.42,W83.95,,\n'


def _tsi_fetch(pages):
    def ft(url):
        return pages[url]
    return ft


def test_tax_sale_info_reads_only_upcoming_catalogs_with_the_auction_date():
    cats = TSI.upcoming_catalogs(AUCTIONS_HTML)
    assert [(c.catalog_id, c.county, c.sale_date) for c in cats] == [
        ("1", "Saginaw", date(2026, 10, 30)), ("2", "St. Clair", date(2026, 10, 30)), ("3", "Lapeer", date(2026, 10, 30))]
    pages = {TSI.AUCTIONS_URL: AUCTIONS_HTML,
             TSI.CSV_URL.format(id="1"): CSV_HEADER + CSV_ROW.format(lot=1, bid="100.00", pid="10-12-5-17-4629-000", county="saginaw")
             + CSV_ROW.format(lot=2, bid='"1,250.00"', pid="10-12-5-17-4630-000", county="saginaw")}
    cfg = next(c for c in EX.MI_TSI_AUCTIONS if c.county == "Saginaw")
    TSI._PAGE_CACHE.clear()
    res = TSI.fetch_county(cfg, _tsi_fetch(pages), retrieved_at=AT)
    assert res.outcome == "COMPLETE" and len(res.records) == 2
    r = res.records[1]
    assert r.record_source == "auction" and r.sale_date == date(2026, 10, 30) and r.amount == 1250.0
    assert r.amount_kind is AmountKind.OPENING_BID and r.longitude == -83.95 and r.latitude == 43.42
    assert "free text" not in json.dumps(r.provenance) and not r.validate()


def test_tax_sale_info_county_without_a_catalog_is_empty_and_a_bad_page_is_failed():
    cfg = next(c for c in EX.MI_TSI_AUCTIONS if c.county == "Alger")
    TSI._PAGE_CACHE.clear()
    assert TSI.fetch_county(cfg, _tsi_fetch({TSI.AUCTIONS_URL: AUCTIONS_HTML}), retrieved_at=AT).outcome == "EMPTY"
    TSI._PAGE_CACHE.clear()
    assert TSI.fetch_county(cfg, _tsi_fetch({TSI.AUCTIONS_URL: "<html>maintenance</html>"}), retrieved_at=AT).outcome == "FAILED"


def test_tax_sale_info_surplus_is_available_inventory():
    cfg = next(c for c in EX.MI_TSI_SURPLUS if c.county == "Otsego")
    pages = {TSI.SURPLUS_URL: SURPLUS_HTML,
             TSI.CSV_URL.format(id="11"): CSV_HEADER + CSV_ROW.format(lot=690438, bid="700.00", pid="091-500-000-123-00", county="otsego-surplus-2026")}
    TSI._PAGE_CACHE.clear()
    res = TSI.fetch_county(cfg, _tsi_fetch(pages), retrieved_at=AT)
    assert res.outcome == "COMPLETE" and res.records[0].record_source == "laft" and res.records[0].sale_date is None
    assert [c.county for c in TSI.surplus_catalogs(SURPLUS_HTML)] == ["Otsego", "Bay"]


# ------------------------------------------------------------------- Horry SC --

def _horry_xlsx(rows, sheets=1):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "UPCOMINGTAXSALEWEBSITE"
    ws.append(["2026 REAL ESTATE DELINQUENT TAX SALE LIST AS OF 10/23/2026", None, None, None, None, None])
    ws.append([None] * 6)
    ws.append(["Item Number", "PIN", "Owner Name", "New Owner Name", "Description", "FLC Bid Amount"])
    for r in rows:
        ws.append(r)
    for i in range(sheets - 1):
        wb.create_sheet(f"extra{i}")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


HORRY_PAGE = ('<html><a href="/media/aa/2026-real-estate-delinquent-list-101326.xlsx">old</a>'
              '<a href="/media/bb/2026-real-estate-delinquent-list-102326.xlsx">2026 Real Estate Delinquent list 10.23.26</a>'
              '<a href="/media/cc/2026-mobile-home-delinquent-list-102426.xlsx">mobile</a></html>')


def test_horry_follows_the_newest_real_estate_list_and_never_maps_owners():
    data = _horry_xlsx([[4, 39307010208, "SYNTHETIC OWNER LLC", None, "SYNTHETIC UNIT 301", 10920.3],
                        [24, 29209030001, "SYNTHETIC OWNER", None, "SYNTHETIC LOT", 1021.08]])
    asked = []

    def ft(url):
        return HORRY_PAGE

    def fb(url):
        asked.append(url)
        return data
    status, recs, cat, _, _ = HE.run_source(_src("sc_horry_tax_sale"), None, ft, retrieved_at=AT, fetch_bytes=fb)
    assert status == "COMPLETE" and asked == ["https://www.horrycountysc.gov/media/bb/2026-real-estate-delinquent-list-102326.xlsx"]
    assert [r.case_no for r in recs] == ["39307010208", "29209030001"]
    assert recs[0].amount == 10920.3 and recs[0].amount_kind is AmountKind.OPENING_BID and recs[0].record_source == "auction"
    assert recs[0].list_as_of == date(2026, 10, 23) and recs[0].owner_name is None


def test_horry_workbook_with_several_sheets_is_a_format_change():
    data = _horry_xlsx([[4, 39307010208, "X", None, "Y", 1.0]], sheets=2)
    status, recs, cat, _, _ = HE.run_source(_src("sc_horry_tax_sale"), None, lambda u: HORRY_PAGE, retrieved_at=AT,
                                            fetch_bytes=lambda u: data)
    assert status == "FAILED" and recs == []


# -------------------------------------------------------------- ArcGIS layers --

def _layer(features):
    return {"objectIdFieldName": "OBJECTID", "geometryType": "esriGeometryPoint", "spatialReference": {"wkid": 4326},
            "features": [{"attributes": a, "geometry": {"x": -94.9, "y": 47.0}} for a in features]}


@pytest.mark.parametrize("cfg, attrs, n", [
    (EX.CO_SAGUACHE_TAX_SALE, [{"TaxSale_Account": "R000001", "TaxSale_Parcel": 459501200057, "Legal_Description": "TRACT 7",
                                "Total_Due": 751.48, "Deeded_Acres": 45, "TaxSale_Owner": "SYNTHETIC", "City": "SYNTHETIC"}], 1),
    (EX.MN_WRIGHT_TAX_FORFEIT, [{"PID": "101050000020", "LEGAL": "OUTLOT A", "Auction_Starting_Price": 414.64,
                                 "Status": "Open", "EMV__Assessment_2025_": 2000, "CalculatedArea": 0.44}], 1),
    (EX.MN_HUBBARD_TFL_OTC, [{"Parcel_Number": "20.43.01291", "Minimum_Bid": None, "Sales_Status": "OTC", "Notes": "free"}], 1),
    (EX.MN_STPAUL_HRA, [{"ParcelID": "012345678901", "SiteAddress": "1 SYNTHETIC AVE", "Legal_Description": "LOT 1",
                         "Marketing_Status": "5 - Available on the open market, subject to disposition policy",
                         "LandHeldForResale_ActVa_EMVTotal": 1000}], 1),
])
def test_arcgis_layers_parse_with_their_live_field_names(cfg, attrs, n):
    res = AG.fetch_all(cfg, lambda url: _layer(attrs), retrieved_at=AT)
    assert res.outcome == "COMPLETE" and len(res.records) == n and not res.records[0].validate()
    assert res.records[0].owner_name is None


def test_a_layer_ignoring_the_status_filter_is_untrusted():
    res = AG.fetch_all(EX.MN_WRIGHT_TAX_FORFEIT, lambda url: _layer([{"PID": "101050000020", "Status": "Closed"}]), retrieved_at=AT)
    assert res.outcome == "FAILED"


# ------------------------------------------------------ Genesee paged table --

def _gpage(cur, total, first, last, rows):
    body = "".join(f"<tr><td>{p}</td><td>1 SYNTHETIC</td><td>FLINT</td><td>48504</td><td>Res Vac Lot</td><td>{t}</td></tr>"
                   for p, t in rows)
    return (f"<html><table><tr><td></td><td>page {cur} of {total} (listings {first}-{last})</td><td>next page &gt;</td></tr></table>"
            "<table><tr><th>Parcel ID</th><th>Address</th><th>City</th><th>ZIP</th><th>Class</th><th>Sale Type</th></tr>"
            f"{body}</table></html>")


GEN_ONE = dataclasses.replace(EX.MI_GENESEE_LANDBANK, partition_field=None, partition_values=())


def test_genesee_pages_through_the_session_and_drops_the_demolition_program():
    pages = [_gpage(1, 2, 1, 2, [("41-05-257-024", "Vacant Land"), ("41-05-257-025", "Demolition Program")]),
             _gpage(2, 2, 3, 3, [("41-05-257-026", "Listed with Realtor")])]
    calls = []

    def post(url, data):
        calls.append((url, data))
        return pages[len(calls) - 1]
    res = PT.fetch_all(GEN_ONE, post, retrieved_at=AT, sleep=lambda s: None)
    assert res.outcome == "COMPLETE" and [r.case_no for r in res.records] == ["41-05-257-024", "41-05-257-026"]
    assert res.excluded_status == 1 and calls[1] == (GEN_ONE.next_url, {"LRCpage": "next"})
    assert res.records[1].source_status_text == "Listed with Realtor"


def test_genesee_lost_session_or_short_read_is_failed():
    one = dataclasses.replace(GEN_ONE, attempts=1)
    pages = [_gpage(1, 2, 1, 1, [("41-05-257-024", "Vacant Land")]), _gpage(1, 2, 1, 1, [("41-05-257-024", "Vacant Land")])]
    it = iter(pages)
    assert PT.fetch_all(one, lambda u, d: next(it), retrieved_at=AT, sleep=lambda s: None).outcome == "FAILED"
    short = [_gpage(1, 1, 1, 5, [("41-05-257-024", "Vacant Land")])]
    it = iter(short)
    assert PT.fetch_all(one, lambda u, d: next(it), retrieved_at=AT, sleep=lambda s: None).outcome == "FAILED"


class _Boom(Exception):
    response = type("R", (), {"status_code": 500})()


def test_genesee_restarts_a_part_after_a_server_error():
    pages = [_gpage(1, 2, 1, 1, [("41-05-257-024", "Vacant Land")]), _Boom(),
             _gpage(1, 2, 1, 1, [("41-05-257-024", "Vacant Land")]), _gpage(2, 2, 2, 2, [("41-05-257-026", "Vacant Land")])]
    it = iter(pages)

    def post(url, data):
        x = next(it)
        if isinstance(x, Exception):
            raise x
        return x
    res = PT.fetch_all(GEN_ONE, post, retrieved_at=AT, sleep=lambda s: None)
    assert res.outcome == "COMPLETE" and len(res.records) == 2


def test_genesee_parts_must_add_up_to_the_full_search():
    cfg = dataclasses.replace(EX.MI_GENESEE_LANDBANK, partition_values=("01", "02"))
    full = _gpage(1, 1, 1, 3, [("41-05-257-024", "Vacant Land")])          # the unfiltered search: 1 page of up to 3
    parts = {"01": _gpage(1, 1, 1, 2, [("01-05-257-001", "Vacant Land"), ("01-05-257-002", "Vacant Land")]),
             "02": _gpage(1, 1, 1, 1, [("02-05-257-001", "Vacant Land")])}

    def post(url, data):
        return parts[data["FindTWP"]] if "FindTWP" in data else full
    res = PT.fetch_all(cfg, post, retrieved_at=AT, sleep=lambda s: None)
    assert res.outcome == "COMPLETE" and len(res.records) == 3
    big = _gpage(1, 2, 1, 3, [("41-05-257-024", "Vacant Land")])           # full search says 2 pages of 3 (4-6 listings)
    res = PT.fetch_all(cfg, lambda u, d: parts[d["FindTWP"]] if "FindTWP" in d else big, retrieved_at=AT, sleep=lambda s: None)
    assert res.outcome == "FAILED" and "add up" in res.error_detail
