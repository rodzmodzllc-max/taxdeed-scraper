"""PBFCM / MVBA / GovEase Texas harvesters (owner decision 2026-10-26).

Every fake below is shaped exactly like the live response read on 2026-10-26
(harvesters/texas_vendors.py module docstring, docs/texas-vendor-sources.md):
the PBFCM index's <li class="tax-list-entity"> entries (with commented-out
inactive counties and an external texascg.com link), pdfplumber's
extract_tables() output for the three PBFCM / MVBA table families and the
positioned-text Harris resale layout, mvbataxsales.com's /api/auctions and
/api/getitems JSON, GovEase's county picker, browse table and parcel page.
Values are synthetic. No network.
"""
from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "harvesters"))

from harvesters import texas_vendors as V  # noqa: E402
from harvesters import tx_sale_tables as T  # noqa: E402


# --- fakes ---------------------------------------------------------------------

class FakeFetcher:
    """Answers by URL (exact, or the longest registered prefix); records calls."""

    def __init__(self, pages: dict, fail: dict | None = None):
        self.pages = pages
        self.fail = fail or {}
        self.calls: list[tuple[str, dict | None]] = []
        self.requests = 0

    def request(self, url, data=None, *, accept="*/*"):
        self.calls.append((url, data))
        self.requests += 1
        for key, cat in self.fail.items():
            if url.startswith(key):
                raise V.FetchError(url, cat)
        if (url, json.dumps(data, sort_keys=True)) in self.pages:
            body = self.pages[(url, json.dumps(data, sort_keys=True))]
        elif url in self.pages:
            body = self.pages[url]
        else:
            raise V.FetchError(url, "NOT_FOUND", "unregistered in fake")
        return body if isinstance(body, bytes) else body.encode()


PBFCM_SALE_INDEX = """
<ul id="taxList1">
  <!--<li class="tax-list-entity" onclick="toggleProperties('divAnderson');"><span class="tax-list-entity-flex"><span class="tax-list-entity-title">ANDERSON COUNTY</span></span>
      <ul><li class="tax-list-file"><a href="docs/taxdocs/sales/09-2026andersontaxsale.pdf" target="_blank">Anderson County</a></li></ul></li>-->
  <li class="tax-list-entity" onclick="toggleProperties('divBrazoria');"><span class="tax-list-entity-flex"><span class="tax-list-entity-title">BRAZORIA COUNTY</span></span>
      <ul><li class="tax-list-file"><a href="docs/taxdocs/sales/11-2026brazoriataxsale.pdf" target="_blank" onclick="_gaq.push(['_trackpageview', '11-2026brazoriataxsale.pdf']);">Brazoria County<span class="tax-list-file-addl"></span></a></li></ul></li>
  <li class="tax-list-entity" onclick="toggleProperties('divFortBend');"><span class="tax-list-entity-flex"><span class="tax-list-entity-title">FORT BEND COUNTY</span></span>
      <ul><li class="tax-list-file"><a href="docs/taxdocs/sales/11-2026ftbendpct1taxsale.pdf" target="_blank">Ft Bend County Pct 1</a></li></ul></li>
  <li class="tax-list-entity" onclick="toggleProperties('divPaloPinto');"><span class="tax-list-entity-flex"><span class="tax-list-entity-title">PALO PINTO COUNTY</span></span>
      <ul><li class="tax-list-file"><a href="docs/taxdocs/sales/goveasepalopintotaxsale.pdf" target="_blank">Palo Pinto County</a></li></ul></li>
</ul>"""

PBFCM_RESALE_INDEX = """
<li class="tax-list-entity" onclick="toggleProperties('divCrosby');"><span class="tax-list-entity-flex"><span class="tax-list-entity-title">CROSBY COUNTY</span></span>
  <ul><li class="tax-list-file"><a href="http://texascg.com/property-list/?location=ralls" target="_blank">City of Ralls TCG</a></li></ul></li>
<li class="tax-list-entity" onclick="toggleProperties('divHarris');"><span class="tax-list-entity-flex"><span class="tax-list-entity-title">HARRIS COUNTY</span></span>
  <ul><li class="tax-list-file"><a href="docs/taxdocs/resales/laporteisdtaxresale.pdf" target="_blank">La Porte ISD</a></li>
      <li class="tax-list-file"><a href="" target="_blank">Graham ISD</a></li></ul></li>
<li class="tax-list-entity" onclick="toggleProperties('divBrazoria');"><span class="tax-list-entity-flex"><span class="tax-list-entity-title">BRAZORIA COUNTY</span></span>
  <ul><li class="tax-list-file"><a href="docs/taxdocs/resales/brazoriataxresale.pdf" target="_blank">Brazoria County</a></li></ul></li>
"""

# pdfplumber extract_tables() output, family 1 (Brazoria-style, one ruled table per page).
BRAZORIA_TABLES = [
    [["Accepted payment methods are CASH, MONEY ORDER OR CASHIER'S CHECK made payable to"]],
    [["Item\nNo.", "Cause No.", "Legal Description", None, None, "Geographic\nID", "Minimum\nBid"],
     ["1", "119698-T\nBRAZORIA\nCOUNTY, ET AL\nVS.\nDOE, JOHN", "TRACT 1: LOT 6 OF HASTINGS ACRES, BRAZORIA\nCOUNTY, TEXAS.\nAdjudged Aggregate Value: $89,680.00",
      None, None, "4710-0006-000\n9610-5200-736", "$10,713.03\n2025-2026\nTaxes Due"],
     ["2", "133026-T", "LOT 18, BLOCK 4, HAZELDALE ESTATES.\nAdjudged Value: $329,130.00", None, None, "4775-0004-018\nPULLED", ""]],
    # The next page: no header of its own, same width -> continues the header above.
    [["3", "132932-T\nContinued", None, None, "TRACT 2: 2.082 ACRES OUT OF THE ZENO PHILLIPS SURVEY.\nAdjudged Value: $119,730.00",
      "0118-0074-000", "$12,055.71\n2026 Taxes\nDue"]],
]

# Family 2 (Harris precincts): one combined cause / court / date column, address in the legal cell.
HARRIS_TABLES = [
    [["", "Cause No:\nDistrict Court:\nJudgment Date:", "Style of Case:",
      "Legal Description (Per Appraisal District):\nProperty Address (Per Appraisal District):", "Adjudged\nValue:",
      "Estimated\nMinimum:", "Cad Account #\nOther Account"],
     ["1.", "202049669\n270TH\nDISTRICT\nCOURT\n1-May-26", "PASADENA ISD vs.\nDOE, JANE", "LT 34 BLK 5\nPASADENA GARDENS\n1203 JACKSON AVE,\nPASADENA, TX 77506",
      "$76,280.00", "$63,365.50", "0710250050034"],
     ["2.", "202338634\n334TH\nDISTRICT\nCOURT\n26-Mar-26", "HARRIS COUNTY vs.\nROE, RICHARD", "LT 7 BLK 2\nWEST JACKSON PARK",
      "$170,821.00", "CANCEL\n$16,626.38", "LED\n0752150020007"]],
]

# Family 3 (MVBA bid sheet): the account lives inside the description.
MVBA_TABLES = [
    [["TRACT", "SUIT #", "STYLE", "PROPERTY DESCRIPTION, APPROXIMATE ADDRESS, ACCT #", "MIN BID"],
     ["1", "21DCV325695", "Tax Appraisal District of\nBell County v Jane Doe",
      "The North one-half of Lot 2, Block 5, Lee Addition, City of Belton, Bell County, Texas (Volume 3113, Page\n388), 601 S Beal St, Belton, Texas 76513-3546; Account #44517\nJudgment Through Tax Year: 2024",
      "$8,500.00"]],
]

# Header split over several rows (Maverick / Uvalde / San Jacinto), data on the next page.
SPLIT_HEADER_TABLES = [
    [["Cause No:", "", "", "", "", ""], ["", "", "", "", "", "CAD"],
     ["District Court:", "", "", "Adjudged", "Estimated", ""], ["", "Style of Case:", "Legal Description:", "", "", "Account #"],
     ["Judgment Date:", "", "", "Value:", "Minimum:", ""]],
    [["24-09-06348-TX\n293RD DISTRICT\nCOURT\n6-March-2026", "EAGLE PASS ISD\nvs. JOHN DOE", "A TRACT OF LAND CONTAINING 0.255 ACRES",
      "$221,702", "$8,737.58", "15897"],
     ["30,346\n46TH JUDICIAL\nDISTRICT COURT\n15-Jul-26", "VERNON ISD vs.\nJANE DOE", "1 acre, more or less, Block 8, Section 3",
      "$5,000.00", "$4,059.88", "4771"]],
]

# A blank bid form (no legal description column) is not a property list.
BID_FORM_TABLES = [[["CAUSE NUMBER", "ACCOUNT NUMBER", "AMOUNT OF OFFER", "Amount of Payment Accompanying Offer"],
                    ["", "", "", ""]]]

HARRIS_RESALE_LAYOUT = """
                                      CITY OF LA PORTE
                                   Property Available for Resale
CASE #                            JUDGMENT              VALUE AT       HCAD ACCOUNT #
PREVIOUS OWNER                    AMOUNT                THE TIME OF    PROPERTY
LEGAL DESCRIPTION                 (ON SALE DATE)        JUDGMENT       ADDRESS
 2011-19935                       $14,060.00 +p/j tax     $14,060.00   0061150000035
 Jane Doe                         year(s)
 LTS 28 29 30 & 31 BLK 25
 BAY FRONT TO LA PORTE                                                 0 Blackwell
 2005-43921                       $23,331.41 +p/j tax     $30,500.00   0062490000017
 Richard Roe                      year(s)                              ***
 TR 30 BLK 5                                                           Sold at the
 CREEKMONT SEC 1                                                       November 2026
                                                                       tax sale
      If you would like to purchase property, please contact our Harris County Post-Judgment
"""


# --- the table reader ----------------------------------------------------------

def test_family_1_rows_header_continuation_and_pulled():
    r = T.read_tables(BRAZORIA_TABLES)
    assert [x.account for x in r.rows] == ["4710-0006-000", "0118-0074-000"]
    first, cont = r.rows
    assert first.cause == "119698-T" and first.min_bid == 10713.03 and first.value == 89680.0
    assert cont.cause == "132932-T" and cont.value == 119730.0 and cont.min_bid == 12055.71
    assert r.skipped_status == 1  # PULLED is never stored as offered


def test_family_2_cancelled_row_skipped_and_address_from_legal_cell():
    r = T.read_tables(HARRIS_TABLES)
    assert len(r.rows) == 1 and r.skipped_status == 1
    row = r.rows[0]
    assert row.account == "0710250050034" and row.cause == "202049669"
    assert row.address == "1203 JACKSON AVE, PASADENA, TX 77506"
    assert row.min_bid == 63365.5 and row.value == 76280.0


def test_family_3_account_label_inside_the_description():
    r = T.read_tables(MVBA_TABLES)
    row = r.rows[0]
    assert row.account == "44517" and row.cause == "21DCV325695" and row.min_bid == 8500.0
    assert row.address == "601 S Beal St, Belton, Texas 76513-3546"


def test_split_header_continues_onto_the_next_page_and_keeps_comma_causes():
    r = T.read_tables(SPLIT_HEADER_TABLES)
    assert [(x.account, x.cause) for x in r.rows] == [("15897", "24-09-06348-TX"), ("4771", "30,346")]
    assert r.rows[0].value == 221702.0 and r.rows[1].min_bid == 4059.88


def test_bid_form_is_not_a_list():
    r = T.read_tables(BID_FORM_TABLES)
    assert r.rows == [] and r.tables_used == 0


def test_positioned_text_resale_layout():
    r = T.read_case_layout(HARRIS_RESALE_LAYOUT)
    assert [(x.cause, x.account) for x in r.rows] == [("2011-19935", "0061150000035")]
    assert r.rows[0].min_bid == 14060.0 and r.rows[0].value == 14060.0 and r.rows[0].address == "0 Blackwell"
    assert r.rows[0].legal == "LTS 28 29 30 & 31 BLK 25 BAY FRONT TO LA PORTE"   # the previous owner is never stored
    assert r.skipped_status == 1                                                    # 'Sold at the ... tax sale'


def test_sale_date_only_from_the_heading():
    assert T.sale_date_from_text("BRAZORIA COUNTY SALES FOR NOVEMBER 3, 2026, BEGINNING AT 10:00 A.M.") == "2026-11-03"
    assert T.sale_date_from_text("MAVERICK COUNTY TAX SALE FOR NOVEMBER 3RD, 2026") == "2026-11-03"
    assert T.sale_date_from_text("no date here") is None
    assert T.sale_date_from_text("x" * 500 + " NOVEMBER 3, 2026") is None  # never deep in the body


@pytest.mark.parametrize("res,expected", [
    (T.TableReadResult(chars=0), ("INCOMPLETE", "IMAGE_ONLY")),
    (T.TableReadResult(rows=[T.SaleTableRow("1", None, None, None, None, None)], chars=10), ("COMPLETE", "ROWS")),
    (T.TableReadResult(rows=[T.SaleTableRow("1", None, None, None, None, None)], skipped_no_account=1, chars=10),
     ("INCOMPLETE", "ROWS_WITH_UNREAD")),
    (T.TableReadResult(tables_used=1, skipped_status=2, chars=10), ("EMPTY", "LIST_WITHOUT_OFFERED_ROWS")),
    (T.TableReadResult(chars=10, text="FOR INFORMATION ON TAX FORECLOSED PROPERTIES ... www.texascg.com"), ("EMPTY", "REDIRECT_NOTICE")),
    (T.TableReadResult(chars=10, text="Lots of prose and no table"), ("INCOMPLETE", "UNRECOGNISED_LAYOUT")),
])
def test_document_status(res, expected):
    assert V.document_status(res) == expected


def test_canonical_county_never_guesses():
    assert V.canonical_county("FORT BEND COUNTY") == "Fort Bend"
    assert V.canonical_county("Ft Bend County Pct 1") == "Fort Bend"
    assert V.canonical_county("McLennan - MVBA") == "McLennan"
    assert V.canonical_county("MCLENNAN") == "McLennan"
    assert V.canonical_county("Gotham") is None and V.canonical_county("") is None


# --- PBFCM ------------------------------------------------------------------------

def _pbfcm_fetcher(**fail):
    pdf = b"%PDF-1.7 fake"
    pages = {V.PBFCM_BASE + "taxsale.html": PBFCM_SALE_INDEX, V.PBFCM_BASE + "taxresale.html": PBFCM_RESALE_INDEX}
    for name in ("sales/11-2026brazoriataxsale.pdf", "sales/11-2026ftbendpct1taxsale.pdf", "sales/goveasepalopintotaxsale.pdf",
                 "resales/laporteisdtaxresale.pdf", "resales/brazoriataxresale.pdf"):
        pages[V.PBFCM_BASE + "docs/taxdocs/" + name] = pdf + name.encode()
    return FakeFetcher(pages, fail)


def _fake_read_pdf(data: bytes):
    name = data.decode()
    if "brazoriataxsale" in name:
        r = T.read_tables(BRAZORIA_TABLES)
        r.chars, r.text = 100, "BRAZORIA COUNTY SALES FOR NOVEMBER 3, 2026"
    elif "ftbendpct1" in name:
        r = T.read_tables(HARRIS_TABLES)
        r.chars, r.text = 100, "FORT BEND COUNTY TAX SALE NOVEMBER 3, 2026"
    elif "palopinto" in name:
        r = T.TableReadResult(chars=50, text="Tax Sales are now being conducted exclusively by means of Online auction by GovEase")
    elif "laporteisd" in name:
        r = T.read_case_layout(HARRIS_RESALE_LAYOUT)
        r.chars, r.text = 100, "Property Available for Resale"
    else:  # brazoriataxresale: a scanned image
        r = T.TableReadResult(chars=0)
    return r


def test_pbfcm_harvest_rows_ledgers_and_units():
    f = _pbfcm_fetcher()
    stats = {}
    rows = V.harvest_pbfcm(fetcher=f, stats=stats, read_pdf=_fake_read_pdf)
    by = {(r["county"], r["source"], r["account_number"]): r for r in rows}
    assert set(by) == {("Brazoria", "auction", "4710-0006-000"), ("Brazoria", "auction", "0118-0074-000"),
                       ("Fort Bend", "auction", "0710250050034"), ("Harris", "laft", "0061150000035")}
    b = by[("Brazoria", "auction", "4710-0006-000")]
    assert b["harvester_source"] == "tx_pbfcm" and b["cause_number"] == "119698-T" and b["auction_date"] == "2026-11-03"
    assert b["sale_list_url"] == V.PBFCM_BASE + "docs/taxdocs/sales/11-2026brazoriataxsale.pdf"
    assert b["auction_url"] is None and b["state"] == "TX"
    h = by[("Harris", "laft", "0061150000035")]
    assert h["auction_date"] is None  # a resale list states no sale date
    u = stats["units"]
    assert u["Brazoria"]["ledgers"] == {"auction": "COMPLETE", "laft": "INCOMPLETE"} and u["Brazoria"]["status"] == "INCOMPLETE"
    assert u["Palo Pinto"]["status"] == "EMPTY" and u["Harris"]["status"] == "COMPLETE"
    assert stats["skipped_links"] == {"external_links": 1, "unknown_county": 0, "blank_links": 1}
    assert stats["complete"] is False  # the scanned Brazoria resale list is not a complete read
    # The status-file entries every reader uses (harvesters/ledgers/health.py).
    from harvesters.ledgers import health as LH
    ent = {e["county"]: e for e in stats["county_entries"]}
    assert all(e["source_id"] == "tx_pbfcm" for e in ent.values())
    assert LH.reader_status(ent["Palo Pinto"]) == "EMPTY" and LH.reader_status(ent["Harris"]) == "COMPLETE"
    assert LH.reader_status(ent["Brazoria"]) == "INCOMPLETE"
    # Only the firm's own PDFs were requested: never the external texascg.com link, never a commented-out county.
    assert not any("texascg" in u or "anderson" in u for u, _ in f.calls)


def test_pbfcm_index_failure_and_document_refusal_are_failed_not_empty():
    f = _pbfcm_fetcher(**{V.PBFCM_BASE + "docs/taxdocs/sales/11-2026brazoria": "ACCESS_REFUSED",
                          V.PBFCM_BASE + "taxresale.html": "TRANSPORT"})
    stats = {}
    V.harvest_pbfcm(fetcher=f, stats=stats, read_pdf=_fake_read_pdf)
    assert stats["units"]["Brazoria"]["status"] == "FAILED"
    from harvesters.ledgers import health as LH
    brazoria = next(e for e in stats["county_entries"] if e["county"] == "Brazoria")
    assert LH.reader_status(brazoria) == "SOURCE_UNAVAILABLE"   # a refusal closes nothing
    # The resale index was not read: no county is vouched for, so nothing of the unread list can be closed.
    assert all(LH.reader_status(e) not in ("COMPLETE", "EMPTY") for e in stats["county_entries"])
    assert stats["index_errors"] == {"taxresale.html": "TRANSPORT"} and stats["complete"] is False


# --- MVBA -------------------------------------------------------------------------

MVBA_MONTH = """<main><a href="https://mvbalaw.com/wp-content/TaxUploads/1126_Bell.pdf">Bell County</a>
<a href="https://www.mvbataxsales.com/register">MVBA Online Sale Registration Link</a></main>"""
MVBA_TRUST = """<main><a href="https://mvbalaw.com/wp-content/TaxUploads/BanderaSaleInfo.pdf">Bandera County Sale Information</a>
<a href="https://mvbalaw.com/wp-content/TaxUploads/RunnelsTrust.pdf">Runnels County</a></main>"""
RUNNELS_TABLES = [[["Cause #", "Styling", "Tax Account", "Legal Description", "Market Value", "Struck off Date", "Vol Page"],
                   ["4945", "The County of Runnels vs. Jane Doe", "R11676", "32'x55' out of Lot 6, Block 12, O.T. Wingate", "$320.00",
                    "4-Apr-23", "532/103"]]]
AUCTIONS = {"result": "success", "data": [
    {"id": "62", "title": "MVBA PUBLIC TAX SALES", "completed": "0", "item_count": "0", "starts": ""},
    {"id": "185", "title": "COMAL COUNTY ONLINE PROPERTY TAX SALE (November 3, 2026)", "completed": "0", "item_count": "3",
     "starts": "2026-11-03T16:00:00-0500", "auction_id_slug": "comal-county-online-property-tax-sale-november-3-2026-185"}]}


def _item(n, desc, extra="", auction="185", bid="5705.21"):
    return {"id": str(4000 + n), "auction_id": auction, "lot_number": f"{n:04d}", "description": desc, "extra_info": extra,
            "minimum_bid": bid, "starting_bid": bid,
            "item_url": f"https://www.mvbataxsales.com/auction/{auction}/item/lot-{n}/"}


ITEMS_P1 = {"total": 3, "total_pages": 2, "page": "1", "items": [
    _item(1, "<p>** WITHDRAWN FROM SALE ** Account No. 72118, 1.75 Acres, Comal County, Texas ::::: Suit No. T-9933E</p>",
          extra='<div class="item_extra_info">**WITHDRAWN FROM SALE**</div>'),
    _item(2, "Account No. 67473, Lot 7, Block 3, Villa Rio Addition, City of New Braunfels, Comal County, Texas ::::: "
             "Suit No. T-10289C, The County of Comal, Texas v John Doe, Judgment Through Tax Year 2024 ::::: "
             "Approximate Property Address: 445 Rio Dr, New Braunfels, Texas"),
    _item(9, "Account No. 999, somewhere, Harrison County, Texas ::::: Suit No. 1", auction="183")]}
ITEMS_P2 = {"total": 3, "total_pages": 2, "page": "2", "items": [
    _item(3, "Account No. R010091816 - A Manufactured Home Only, 1980, Comal County, Texas ::::: Suit No. 24-0552T", bid="4579.86")]}


def _mvba_fetcher():
    def key(url, data):
        return (url, json.dumps(data, sort_keys=True))
    pages = {
        V.MVBA_MONTH_URL: MVBA_MONTH, V.MVBA_TRUST_URL: MVBA_TRUST,
        "https://mvbalaw.com/wp-content/TaxUploads/1126_Bell.pdf": b"%PDF bell",
        "https://mvbalaw.com/wp-content/TaxUploads/RunnelsTrust.pdf": b"%PDF runnels",
        key(f"{V.MVBA_AUCTION_SITE}/api/auctions", {"filters[page]": "1", "past_sales": "false"}): json.dumps(AUCTIONS),
        key(f"{V.MVBA_AUCTION_SITE}/api/getitems", {"auction_id": "185", "filters[page]": "1"}): json.dumps(ITEMS_P1),
        key(f"{V.MVBA_AUCTION_SITE}/api/getitems", {"auction_id": "185", "filters[page]": "2"}): json.dumps(ITEMS_P2),
    }
    return FakeFetcher(pages)


def _mvba_read_pdf(data):
    if b"bell" in data:
        r = T.read_tables(MVBA_TABLES)
        r.chars, r.text = 100, "DELINQUENT TAX SALE BELL COUNTY, TEXAS November 3, 2026 at 10:00 AM"
    else:
        r = T.read_tables(RUNNELS_TABLES)
        r.chars, r.text = 100, "RUNNELS IN-TRUST PROPERTY"
    return r


def test_mvba_pdfs_and_online_auction():
    f = _mvba_fetcher()
    stats = {}
    rows = V.harvest_mvba(fetcher=f, stats=stats, read_pdf=_mvba_read_pdf)
    by = {(r["county"], r["source"], r["account_number"]): r for r in rows}
    assert set(by) == {("Bell", "auction", "44517"), ("Runnels", "laft", "R11676"),
                       ("Comal", "auction", "67473"), ("Comal", "auction", "R010091816")}
    c = by[("Comal", "auction", "67473")]
    assert c["cause_number"] == "T-10289C" and c["min_bid"] == 5705.21 and c["auction_date"] == "2026-11-03"
    assert c["address"] == "445 Rio Dr, New Braunfels, Texas" and c["auction_url_kind"] == "property"
    assert c["legal_description"].startswith("Lot 7, Block 3") and c["sale_list_url"] is None
    assert by[("Runnels", "laft", "R11676")]["cad_market_value"] == 320.0
    assert stats["online"]["skipped"] == {"withdrawn": 1}   # the other auction's item is never mixed in
    assert stats["units"]["Comal"]["status"] == "COMPLETE" and stats["complete"] is True
    assert stats["skipped_links"]["information_only"] == 1   # 'Sale Information' is not a list


# --- GovEase ----------------------------------------------------------------------

PICKER = """<select><option value="ca|cakernreoffer|1564">CA - Kern Reoffer</option>
<option value="tx|txdenton|1355">TX - Denton</option>
<option value="tx|txmclennan|1444">TX - McLennan - MVBA</option>
<option value="tx|txparker|1545">TX - Parker</option>
<option value="tx|txwichita|1429" selected>TX - Wichita</option></select>
<select><option value="tx|txwichita|1429" selected>TX - Wichita</option></select>"""


def _browse(heads, rows, post="/tx/txwichita/1429/browse"):
    th = "".join(f'<th class="no-sort"><div>{h}</div></th>' for h in heads)
    trs = ""
    for link, cells in rows:
        tds = "".join(f"<td>{c}</td>" for c in cells)
        trs += f'<tr role="row" class="odd nobid" style="cursor: pointer;"><td class="dtr-control "></td><td></td><td><a href="{link}" target="_blank">1</a></td>{tds}</tr>'
    return (f'<input id="SearchCriteria_PostUrl" name="SearchCriteria.PostUrl" type="hidden" value="{post}" />'
            f'<table id="dt-auctions" class="table"><thead class="bg-primary-600"><tr role="row">{th}</tr></thead><tbody>{trs}</tbody></table>'
            + PICKER)


STD_HEADS = ["", "Watch", "Unique #", "Parcel #", "Owner Name", "Minimum Bid", "Parcel Address:", "Auction Name:", "Auction Type:", "Bidding", "My Bid"]
WICHITA = _browse(STD_HEADS, [
    ("/tx/txwichita/1429/openparcel/2391661/112423", ["112423", "<span>Jane Doe</span>", "$8,445.13", "305 W Franklin Ave",
                                                      "2026 Wichita County TX November Tax Foreclosure Sale", "Redeemable Tax Deed", "", ""])])
DENTON = _browse(STD_HEADS, [
    ("/tx/txdenton/1355/openparcel/1/24-10711-467", ["24-10711-467", "Jane Doe", "$7,663.56", "4020 MOORCROFT ROAD", "x", "Redeemable Tax Deed", "", ""]),
    ("/tx/txdenton/1355/openparcel/2/24-11037-442", ["24-11037-442", "John Doe", "$37,713.48", "8140 ROBERTSON DR", "x", "Redeemable Tax Deed", "", ""])],
    post="/tx/txdenton/1355/browse")
DESC_HEADS = ["", "Watch", "Unique #", "Parcel #", "Owner Name", "Minimum Bid", "Property Description:", "Parcel Address:",
              "Auction Name:", "Auction Type:", "Time Left", "Bids Placed / Current Bids", "My Bid"]
MCLENNAN = _browse(DESC_HEADS, [
    ("/tx/txmclennan/1444/openstandardparcel/30387/2022-2447-3",
     ["2022-2447-3", "The City of Moody, T...", "$13,400.00", "Account #380070000193005 Judgment Through Tax Year: 2025 PARCELMAP",
      "302 3rd Street", "2026 McLennan County November Online Constables Sale (MVBA)", "Redeemable Tax Deed", "08d 03h", "", ""])],
    post="/tx/txmclennan/1444/browsestandard")
PARKER = _browse(DESC_HEADS, [], post="/tx/txparker/1545/browsestandard")


def _parcel(desc_html, legal, address="", sale=""):
    msg = f'<span id="main-message-detail">This auction is scheduled to begin {sale} 10:00:00 AM CST</span>' if sale else ""
    return (f'{msg}<div class="panel-hdr">Parcel: X</div><span class="fw-500">Minimum Bid</span><span>$1.00</span>'
            f'<span class="fw-500">Physical Address</span><span class="no-translate">{address}</span>'
            f'<span class="fw-500">Property Description</span><div><span>{desc_html}</span></div>'
            f'<span class="fw-500">Legal Description</span><span>{legal}</span><span class="fw-500">Tax Year</span><span>2026</span>'
            '<span>© Copyright [2026] GovEase, LLC.</span>')


def _govease_fetcher():
    b = V.GOVEASE_BASE
    pages = {
        V.GOVEASE_SEED: WICHITA,
        f"{b}/tx/txwichita/1429/browse": WICHITA,
        f"{b}/tx/txdenton/1355/browse": DENTON,
        f"{b}/tx/txmclennan/1444/browse": MCLENNAN,
        f"{b}/tx/txparker/1545/browse": PARKER,
        f"{b}/tx/txwichita/1429/openparcel/2391661/112423": _parcel(
            "<p>Cause No.: DC30-TX2025-1359</p><p>Adjudged Value: 57462</p>", "Lot 4, Block 29, Original Townsite Electra"),
        f"{b}/tx/txdenton/1355/openparcel/1/24-10711-467": _parcel(
            "HOA - THIS IS AN HOA FORECLOSURE<br>Some Owners Association vs Jane Doe", "LOT 5, BLOCK 25"),
        f"{b}/tx/txdenton/1355/openparcel/2/24-11037-442": _parcel(
            "ACCOUNT NUMBER: 237918DEN<br>ADJUDGED VALUE: $147,042.00", "HERITAGE VILLAGE PH 1 BLK J LOT 3"),
        f"{b}/tx/txmclennan/1444/openstandardparcel/30387/2022-2447-3": _parcel(
            "Account #380070000193005 Judgment Through Tax Year: 2025", "Part of Block 36, Original Townsite City of Moody",
            sale="11/03/2026"),
    }
    return FakeFetcher(pages)


def test_govease_counties_identity_and_hoa_exclusion():
    f = _govease_fetcher()
    stats = {}
    rows = V.harvest_govease(fetcher=f, stats=stats)
    by = {(r["county"], r["account_number"]): r for r in rows}
    assert set(by) == {("Wichita", "112423"), ("Denton", "237918DEN"), ("McLennan", "380070000193005")}
    w = by[("Wichita", "112423")]
    assert w["cause_number"] == "DC30-TX2025-1359" and w["cad_market_value"] == 57462.0 and w["min_bid"] == 8445.13
    assert w["auction_url"] == f"{V.GOVEASE_BASE}/tx/txwichita/1429/openparcel/2391661/112423" and w["auction_url_kind"] == "property"
    assert w["auction_date"] is None and w["source"] == "auction" and w["harvester_source"] == "tx_govease"
    # Denton's 'Parcel #' is the suit number; the labelled account wins and the table value becomes the cause.
    d = by[("Denton", "237918DEN")]
    assert d["cause_number"] == "24-11037-442" and d["cad_market_value"] == 147042.0
    m = by[("McLennan", "380070000193005")]
    assert m["cause_number"] == "2022-2447-3" and m["auction_date"] == "2026-11-03"
    assert stats["skipped_rows"] == {"not_a_tax_sale": 1}
    assert stats["units"]["Parker"]["status"] == "EMPTY" and stats["units"]["Wichita"]["status"] == "COMPLETE"
    assert not any(u.startswith(V.GOVEASE_BASE + "/ca/") or "/CA/" in u for u, _ in f.calls)  # Texas only


def test_govease_picker_failure_is_failed():
    stats = {}
    V.harvest_govease(fetcher=FakeFetcher({}, {V.GOVEASE_SEED: "ACCESS_REFUSED"}), stats=stats)
    assert stats["complete"] is False and stats["index_errors"] == {"county_picker": "ACCESS_REFUSED"}


def test_govease_parcel_without_any_account_label_and_a_suit_shaped_parcel_is_not_stored():
    row, why = V.govease_row("Grayson", {"Parcel #": "T-20-3333", "_link": None}, {})
    assert row is None and why == "no_account"


# --- polite fetcher ---------------------------------------------------------------

class _Resp:
    def __init__(self, body=b"ok"):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def test_polite_fetcher_paces_identifies_itself_and_never_works_around_a_refusal():
    t = [0.0]
    slept = []
    seen = []

    def clock():
        return t[0]

    def sleep(s):
        slept.append(s)
        t[0] += s

    def opener(req, timeout):
        seen.append(req)
        if "refused" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
        return _Resp()

    f = V.PoliteFetcher(min_interval=0.1, opener=opener, sleep=sleep, clock=clock)
    assert f.min_interval == 1.0                          # never faster than 1 request / second
    f.request("https://a.example/1")
    f.request("https://a.example/2")
    assert slept == [1.0]
    assert all(r.get_header("User-agent") == "taxdeed-scraper/1.0" for r in seen)
    with pytest.raises(V.FetchError) as e:
        f.request("https://a.example/refused")
    assert e.value.category == "ACCESS_REFUSED" and sum("refused" in r.full_url for r in seen) == 1  # not retried
    with pytest.raises(V.FetchError):
        f.request("http://a.example/plain")               # https only
    assert V.USER_AGENT == "taxdeed-scraper/1.0"


def test_texas_harvester_wraps_the_vendors_as_texas_sale_rows(monkeypatch):
    import texas_harvester as TH
    monkeypatch.setattr(V, "harvest_govease", lambda stats=None, limit=None, county_slugs=None:
                        [V._row(source_id="tx_govease", ledger="auction", county="Parker", account="R1")])
    monkeypatch.setattr(TH, "_texas_vendors", lambda: V)
    rows = TH.harvest_govease()
    assert isinstance(rows[0], TH.TexasSaleRow) and rows[0].account_number == "R1" and rows[0].harvester_source == "tx_govease"
    assert {"tx_pbfcm", "tx_mvba", "tx_govease"} <= set(TH.FIELD_LINEAGE_MAP) and "tx_ctsa" not in TH.SOURCES
    for name in ("tx_pbfcm", "tx_mvba", "tx_govease"):
        import inspect
        assert "stats" in inspect.signature(TH.SOURCES[name]).parameters   # per-(source, county) status reaches the status file
