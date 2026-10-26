"""FL / TX county-source sprint (2026-10-26): the clerk-portal LAFT harvester,
the Texas county-list reader, their permission records, registry rows and
workflow wiring. Fixtures are SYNTHETIC values in the exact shapes read live
on 2026-10-26 (field names, table layouts, labels) - never a real row."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import harvest_laft_portals as P  # noqa: E402
import harvest_tx_county_sales as T  # noqa: E402
import laft_status as LS  # noqa: E402
from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import permissions as PERM  # noqa: E402
from harvesters.ledgers import Ledger, ledgers_for_source_id  # noqa: E402
from harvesters.ledgers import domains  # noqa: E402

ROWS = csr.load_registry()


# ------------------------------------------------------------------ FL clerk portal (Charlotte, Kendo grid)

def _kendo_entry(**kw):
    e = {"Applicant": "SYNTH APPLICANT LLC", "BaseBid": 1234.5, "CaseId": 101, "CaseNumber": "25-0001",
         "CertificateNumber": "2020-0001", "HighBid": 0.0, "Owners": "SYNTH OWNER", "ParcelId": "402100000000",
         "SaleDate": "2025-08-13T00:00:00", "Status": "LANDS AVAILABLE", "Surplus": 0.0}
    e.update(kw)
    return e


def test_kendo_rows_keep_only_lands_available_and_label_the_base_bid():
    payload = {"Data": [_kendo_entry(), _kendo_entry(CaseNumber="25-0002", Status="SOLD")], "Total": 2, "Errors": None}
    rows, meta = P.kendo_rows(payload, "Charlotte", "https://taxdeeds.example/TaxDeed/Lands")
    assert meta == {"total": 2, "rows": 1, "other_status": 1, "rejected": 0}
    r = rows[0]
    assert r["case_no"] == "25-0001" and r["parcel"] == "402100000000" and r["certificate_no"] == "2020-0001"
    assert r["bid"] == "1234.50" and r["bid_kind"] == "OPENING_BID" and r["bid_kind"] in LS.AMOUNT_KINDS
    assert r["sale_date"] == "08/13/2025" and r["source"] == "laft" and r["county"] == "Charlotte"
    # HighBid / Surplus are the failed auction's leftovers - never a price
    assert "HighBid" not in json.dumps(r) and "surplus" not in r


def test_kendo_shape_change_and_errors_are_never_a_silent_zero():
    for bad in ({"Total": 0}, {"Data": [], "Errors": None}, {"Data": [], "Total": 0, "Errors": {"x": 1}}, []):
        with pytest.raises(LS.CategorizedError):
            P.kendo_rows(bad, "Charlotte", "u")


def test_portal_classify_complete_empty_incomplete():
    assert P.classify({"total": 4, "read": 4, "rows": 4}) == ("COMPLETE", None)
    assert P.classify({"total": 0, "read": 0, "rows": 0}) == ("EMPTY", None)
    assert P.classify({"total": 9, "read": 4, "rows": 4}) == ("INCOMPLETE", "PARSE_COUNT_MISMATCH")
    assert P.classify({"total": None, "read": 0, "rows": 0}) == ("INCOMPLETE", "PARSE_FORMAT_CHANGE")
    assert P.classify({"total": 3, "read": 3, "rows": 0, "rejected": 3}) == ("INCOMPLETE", "PARSE_FORMAT_CHANGE")


def test_portal_csv_lists_charlotte_and_every_platform_is_known():
    with open(REPO / "data/laft_portal_sources.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert {r["County"] for r in rows} == {"Charlotte"}
    assert all(r["Platform"] in P.PLATFORMS and r["BaseUrl"].startswith("https://") for r in rows)


def test_portal_harvester_stops_before_any_request_without_permission(monkeypatch, tmp_path):
    class Denied:
        allowed = False
        reason_code = "NO_RECORD"
        reason = "test"
    monkeypatch.setattr(LS, "permission", lambda *a, **k: Denied())
    called = []
    monkeypatch.setattr(P.requests, "Session", lambda: called.append(1))
    assert P.main() == LS.PERMISSION_DENIED_EXIT and called == []


# ------------------------------------------------------------------ TX: Harris (tx_hctax)

HARRIS_HTML = """<html><body>
<h2>Harris County Delinquent Tax Sale Property Listing</h2><p>Sale Date: November 03, 2026</p>
<ul class="list-listings-2 list">
 <li class="row listing"><div class="listing-body"><h3><span class="address">1 SYNTH ST</span> <span class="city">HOUSTON </span>
  <span class="state">TX </span><span class="zip">77000 </span></h3>
  <h4><strong class="precinct">Precinct 1</strong> / Type: <strong>SALE 1</strong></h4>
  <div class='For Sale-small'><strong>For Sale</strong></div>
  <div class="account">Account#: <strong>0000000000001</strong></div><div class="SuitNumber">Cause#: <strong>201900001</strong></div>
  <div class="adjudgedValue">Adjudged Value: $<strong>72,000.00</strong></div><div class="minBid">Minimum Bid: $<strong>60,000.50</strong></div>
 </div>
 <div class="modal" id="listing-0000000000001"><table><tr><td class="modalCell">Judgment: </td><td class="modalCell">11/15/2024</td></tr></table>
  <p><strong>Description</strong></p><p>Lot 1 Block 1 Synthetic Addition</p></div></li>
 <li class="row listing"><div class="listing-body"><h4><strong class="precinct">Precinct 2</strong> / Type: <strong>RESALE 3</strong></h4>
  <div class='Cancelled-small'><strong>Cancelled</strong></div>
  <div class="account">Account#: <strong>0000000000002</strong></div></div></li>
 <li class="row listing"><div class="listing-body"><h4><strong class="precinct">Precinct 3</strong> / Type: <strong>EOS 2</strong></h4>
  <div class='For Sale-small'><strong>For Sale</strong></div>
  <div class="account">Account#: <strong>0000000000003</strong></div><div class="SuitNumber">Cause#: <strong>201900003</strong></div>
  <div>Sold with Account# <strong></strong></div></div></li>
</ul></body></html>"""


def test_harris_listing_keeps_for_sale_drops_cancelled_and_never_invents_a_bid():
    rows, meta = T.parse_harris(HARRIS_HTML, "https://hctax.example/listing")
    assert meta["listings"] == 3 and meta["for_sale"] == 2 and meta["cancelled"] == 1 and meta["rejected"] == 0
    assert meta["sale_date"] == "2026-11-03" and meta["types"] == {"SALE": 1, "EOS": 1}
    a, b = rows
    assert a["account_number"] == "0000000000001" and a["cause_number"] == "201900001" and a["auction_date"] == "2026-11-03"
    assert a["min_bid"] == 60000.50 and a["adjudged_value"] == 72000.0 and a["judgment_date"] == "11/15/2024"
    assert a["legal_description"] == "Lot 1 Block 1 Synthetic Addition" and a["source"] == "auction" and a["harvester_source"] == "tx_hctax"
    assert b["min_bid"] is None   # "Sold with Account#": no bid of its own
    with pytest.raises(LS.CategorizedError):
        T.parse_harris("<html>moved</html>")


# ------------------------------------------------------------------ TX: Bexar resale list (text layer)

BEXAR_TEXT = """Page 1
BEXAR COUNTYRESALE PROPERTIES
ListUpdated October6, 2026
Struckoffamtw/o
PropertyAddress SuitNo. AccountNo. interimtax!fees
SynthSt., 100 21-TA1-01234 01234-000-0010 $12,345.67
OtherAve., 200 2021-TA1-0O567 l1111-222-3333 $1,000.00
THE DOLLAR AMOUNTS LISTED ARE NOT GUARANTEED TO BE ACCURATE
PAGE 1
BEXAR COUNTY RESALE PROPERTIES
MULTIPLE ACCOUNTS
List Updated October 6, 2026
Property Address Suit No. Account No. Stuck OffAmount
22222-050-0171
Synth 2016-TA1-02622 22222-050-0172 $5,000.00
______________________________ _______________
Grove Rd 33333-000-0010
Lane Way 33333-000-0150
2023-TA1-01093 $6,000.06
Grove Rd 33333-000-0050
_____________ _____________________________
THE DOLLAR AMOUNTS LISTED ARE NOT GUARANTEED TO BE ACCURATE"""


def test_bexar_single_and_multiple_account_rows_and_ocr_digits():
    rows, meta = T.parse_bexar_text(BEXAR_TEXT, "u")
    assert meta == {"rows": 4, "rejected": 0, "multi_account_groups": 2, "list_as_of": "2026-10-06"}
    assert rows[1]["account_number"] == "11111-222-3333" and rows[1]["cause_number"] == "2021-TA1-00567"
    assert rows[0]["struck_off_amount"] == 12345.67 and rows[0]["amount_kind"] == "STRUCK_OFF_AMOUNT_WITHOUT_INTERIM_TAX_FEES"
    assert rows[2]["additional_accounts"] == ["22222-050-0172"] and rows[3]["additional_accounts"] == ["33333-000-0150", "33333-000-0050"]
    assert all(r["source"] == "laft" and r["min_bid"] is None for r in rows)   # a struck-off amount is never called a bid


def test_bexar_unparsed_line_makes_the_read_incomplete():
    rows, meta = T.parse_bexar_text(BEXAR_TEXT.replace("SynthSt., 100 21-TA1-01234 01234-000-0010 $12,345.67",
                                                       "SynthSt., 100 21-TA1-01234 garbled"), "u")
    assert meta["rejected"] == 1 and T.classify(rows, meta) == ("INCOMPLETE", "PARSE_FORMAT_CHANGE")


# ------------------------------------------------------------------ TX: Jefferson Notice of Sale (table)

def test_jefferson_tables_and_link_discovery():
    tables = [[["Sale\n#", "Cause #\nJudgment Date", "Acct #\nOrder Issue Date", "Style of Case", "Legal Description",
                "Adjudged Value\nAdd'l Delinquent\nTaxes Due", "Estimated\nMinimum Bid"],
               ["1", "23DCCV0001\n12/07/23", "011111-000-\n000500-00000", "JEFFERSON COUNTY, ET AL\nVS. SYNTH",
                "Lot 5 in Block 1 of Synth Addition,\nVolume 2, Page 40\n100 SYNTH ST,\nBEAUMONT, TX 77701",
                "$60,449.00\n$4,262.80\n(2023-2025)", "$20,994.22"],
               ["2", "23DCCV0002\n12/07/23", "bad", "x", "y", "$1.00", "$1.00"]]]
    rows, meta = T.parse_jefferson_tables(tables, "u", "2026-12-01")
    assert meta == {"rows": 1, "rejected": 1, "header_rows": 1}
    r = rows[0]
    assert r["account_number"] == "011111-000-000500-00000" and r["cause_number"] == "23DCCV0001"
    assert r["min_bid"] == 20994.22 and r["adjudged_value"] == 60449.0 and r["address"] == "100 SYNTH ST, BEAUMONT, TX 77701"
    assert T._jefferson_sale_date("offer for sale the following properties, on the first Tuesday in December, 2026, "
                                  "the same being the 1st day of said month") == "2026-12-01"
    page = '<a href="https://jeffcotax.example/wp-content/uploads/2026/10/December-1-2026-Notice-of-Sale-Final.pdf">x</a>'
    assert T.jefferson_notice_url(page).endswith("Notice-of-Sale-Final.pdf")
    with pytest.raises(LS.CategorizedError):
        T.jefferson_notice_url("<html>no link</html>")


def test_jefferson_bot_challenge_fails_closed_without_a_workaround():
    class Resp:
        status_code = 307
        text = "<html><title>You are being redirected...</title><script>var sucuri_cloudproxy_js=''</script></html>"
        def raise_for_status(self): pass
    class S:
        def get(self, *a, **k): return Resp()
    with pytest.raises(LS.CategorizedError) as e:
        T.harvest_jefferson(S())
    assert e.value.status_category == "ACCESS_DENIED"


# ------------------------------------------------------------------ TX: Montgomery / Orange / Trinity / Randall / Hood

def test_montgomery_trust_listing():
    tables = [[T.MONT_HEADER, ["0003502804507", "CONROE ISD TAX TRUST", "A0350 SYNTH TRACT", "91-05-00663", "$57,000", "$0.00", "CONROE ISD"],
               ["short", "row"]]]
    rows, meta = T.parse_montgomery_tables(tables, "u")
    assert meta == {"rows": 1, "rejected": 1}
    assert rows[0]["account_number"] == "0003502804507" and rows[0]["cad_market_value"] == 57000.0 and rows[0]["min_bid"] is None
    with pytest.raises(LS.CategorizedError):
        T.parse_montgomery_tables([[["x"]]], "u")


def test_orange_two_row_records_and_account_shapes():
    tables = [[["", "APPROXIMATE**\nLOCATION", "Legal Description", "", "Suit\nNumber", "Minimum*\nBid Amount", "NOTES"],
               ["", "", "Account Number", "", "", "", ""],
               ["1", "1 Synth Rd.\nORANGE", "2 Abst. 2 Synth Tract\nAccount Number", "", "220033-T", "$21,593.67", "0.292 acre\nLand w/imp."],
               ["", "", "", "000002-027501", "", "", ""],
               ["2", "2 Synth\nVIDOR", "Lot 15 Blk 1", "", "A180240-T", "$38,095.69", "Vacant"],
               ["", "", "", "006895-00150", "", "", ""]]]
    rows, meta = T.parse_orange_tables(tables, "u", "2026-02-26")
    assert meta == {"rows": 2, "rejected": 0, "list_as_of": "2026-02-26"}
    assert rows[0]["account_number"] == "000002-027501" and rows[0]["min_bid"] == 21593.67 and rows[0]["amount_kind"] == "MINIMUM_BID_ACCEPTED"
    assert rows[1]["account_number"] == "006895-00150" and rows[0]["legal_description"] == "2 Abst. 2 Synth Tract"


def test_trinity_resale_list():
    tables = [[["PID", "file_as_name", "legal_desc", "state_cd"], ["16658", "TRINITY COUNTY TRUSTEE", "A0012 SYNTH,10.0 ACRES", "E4"]]]
    rows, meta = T.parse_trinity_tables(tables, "u", "2026-09-22")
    assert meta == {"rows": 1, "rejected": 0} and rows[0]["trustee"] == "TRINITY COUNTY TRUSTEE" and rows[0]["amount_kind"] == "NOT_PUBLISHED"


def test_randall_numbered_entries():
    text = """RANDALL COUNTY TRUSTEE PROPERTY LISTING
STRUCK OFF PROPERTY
Account Number Description Minimum
Bid at Sale
1. 166908 Synth Addn #1, $48.00
Lot Block 0030
0000 Synth St. Amarillo, TX
Deed Filed: 07/07/1999
2. 1 66910 SYNTH ADDN # 12 LOTBLOCK 0043 N $121
Deed Filed:
Updated 10/02/2025
BID SUBMISSION FOR TRUSTEE PROPERTY"""
    rows, meta = T.parse_randall_text(text, "u")
    assert meta == {"rows": 2, "rejected": 0, "list_as_of": "2025-10-02"}
    assert rows[0]["account_number"] == "166908" and rows[0]["min_bid"] == 48.0 and rows[0]["amount_kind"] == "ORIGINAL_OPENING_BID"
    assert rows[0]["address"] == "0000 Synth St. Amarillo, TX" and rows[0]["deed_filed"] == "1999-07-07"
    assert rows[1]["account_number"] == "166910"


def test_hood_empty_list_is_empty_and_an_unreadable_one_is_not():
    page = ("<main><h2>Current Properties on the struck off property list</h2><div>Account Number</div><div>Legal Description</div>"
            "<div>Address</div><a>Bidder submission form</a></main>")
    rows, meta = T.parse_hood(page)
    assert rows == [] and T.classify(rows, meta) == ("EMPTY", None)
    rows, meta = T.parse_hood(page.replace("<div>Address</div>", "<div>Address</div><p>R000123 something</p>"))
    assert T.classify(rows, meta) == ("INCOMPLETE", "PARSE_FORMAT_CHANGE")
    with pytest.raises(LS.CategorizedError):
        T.parse_hood("<main>page moved</main>")


def test_find_doc_link_reads_links_from_the_page_never_composes():
    html = ('<a href= "https://x.example/TaxOffice/MCTX Tax Trust List 06272024.pdf?t=1"  target="_blank"  >PDF Format</a>'
            '<a href="/a.pdf">Other</a>')
    assert T.find_doc_link(html, "https://x.example/p", r"PDF Format", r"Tax\s*Trust.*\.pdf") == [
        "https://x.example/TaxOffice/MCTX Tax Trust List 06272024.pdf?t=1"]


# ------------------------------------------------------------------ outputs, ledgers, permissions, registry, workflow

def test_every_tx_county_source_is_permitted_to_read_collect_display_and_link_but_never_redistributed():
    """Owner decisions 2026-10-26: collect every source, then publish ("post their shit"). Every allowance is
    INTERIM (the owner's risk acceptance, never the county's grant); export / API redistribution is not granted.
    fetch / parse / store / display / link are state-level records, because the sync, the close-out and the
    publication check ask without a county."""
    for county, sid, dataset, _fn, ledger in T.SOURCES:
        for op in ("discover", "fetch", "parse", "store", "display", "link"):
            d = PERM.authorize(sid, op, state="TX", county=county, dataset=dataset)
            assert d.allowed and d.basis == "INTERIM" and not d.documented, (sid, op, d.reason_code)
        for op in ("fetch", "store", "display", "link"):
            assert PERM.authorize(sid, op, state="TX").allowed, (sid, op)
        assert not PERM.authorize(sid, "redistribute", state="TX", county=county, dataset=dataset).allowed, sid
        assert ledgers_for_source_id(sid) == {Ledger.AUCTIONS if ledger == "AUCTIONS" else Ledger.AVAILABLE}


def test_new_interim_records_are_owner_risk_acceptances_expiring_2027_04_12():
    recs = [r for r in PERM.Permissions.from_file().records if r.effective_on == "2026-10-26"]
    assert recs and all(r.status == "OWNER_PERMISSION_REQUIRED" and r.evidence_type == "INTERNAL_RISK_ACCEPTANCE"
                        and r.expires_on == "2027-04-12" and "2026-10-26" in r.reason for r in recs)
    assert {"fl_laft_portals", "tx_hctax", "tx_bexar_resale"} <= {r.source_id for r in recs}


def test_outputs_are_one_pair_per_ledger_and_the_domains_stay_isolated():
    assert T.LEDGER_FILES == {"AUCTIONS": ("harvest_tx_county_auctions.json", "harvest_tx_county_auctions_status.json"),
                              "AVAILABLE": ("harvest_tx_county_available.json", "harvest_tx_county_available_status.json")}
    domains.assert_isolated()
    assert "harvest_laft_portals.json" in domains.AVAILABLE_HARVESTER.harvest_files
    assert "fl_laft_portals" in domains.AVAILABLE_HARVESTER.source_ids


def test_registry_rows_for_the_sprint():
    charlotte = csr.lookup(ROWS, "FL", "Charlotte", "fl_laft_portals")
    assert charlotte.is_production and charlotte.harvester == "harvest_laft_portals.py" and charlotte.publication_status == "APPROVED"
    assert charlotte.restrictions.startswith("Owner approved customer publication 2026-10-26; legal review pending")
    for county, sid in (("Lake", "fl_laft_realtdm"), ("DeSoto", "fl_laft_html"), ("Wakulla", "fl_laft_html")):
        r = csr.lookup(ROWS, "FL", county, sid)
        assert r.is_production and r.last_checked == "2026-10-26"
    for county, sid, *_ in T.SOURCES:
        r = csr.lookup(ROWS, "TX", county, sid)
        assert r is not None and r.is_production and r.runnable and r.governance_status == "APPROVED", sid
        assert r.harvester == "scripts/harvest_tx_county_sales.py" and r.publication_status == "APPROVED", sid
        assert r.restrictions.startswith("Owner approved customer publication 2026-10-26; legal review pending"), sid
        assert r.publishing_unit_name and r.amount_kind and r.update_frequency and r.source_terminology, sid


def test_workflow_harvests_syncs_and_closes_the_texas_county_lists_per_source():
    wf = yaml.safe_load((REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8"))
    laft_runs = [s.get("run", "") for s in wf["jobs"]["laft"]["steps"]]
    assert any("harvest_laft_portals.py" in r for r in laft_runs)
    tx = wf["jobs"]["texas"]["steps"]
    names = [s.get("name") for s in tx]
    harvest = next(s for s in tx if "harvest_tx_county_sales.py" in s.get("run", ""))
    assert harvest.get("continue-on-error") is True and "SUPABASE" not in json.dumps(harvest)
    sync = next(s for s in tx if s.get("id") == "sync_county")
    assert sync.get("continue-on-error") is True and "steps.harvest_county.outcome == 'success'" in sync["if"]
    for ledger in ("auctions", "available"):
        assert (f"sync_state_inventory.py --state TX --keep-other-sources --rows out/tx_county_{ledger}_properties_rows.json "
                f"--status out/harvest_tx_county_{ledger}_status.json") in sync["run"]
    assert "--close-absent" not in sync["run"]          # closing is texas_closeout.py's, per source
    close = next(s for s in tx if "texas_closeout.py --harvest out/harvest_tx_county_auctions.json" in s.get("run", ""))
    assert close.get("continue-on-error") is True and "steps.sync_county.outcome == 'success'" in close["if"]
    for f in ("harvest_tx_county_available.json", "harvest_tx_county_auctions_status.json", "harvest_tx_county_available_status.json"):
        assert f in close["run"]
    assert names.index(harvest["name"]) < names.index(sync["name"]) < names.index(close["name"])
    # The vendor close-out step is unchanged and comes first.
    vendor = next(s for s in tx if s.get("run", "").strip() == "python3 scripts/texas_closeout.py")
    assert names.index(vendor["name"]) < names.index(close["name"])
    ev = next(s for s in wf["jobs"]["evidence"]["steps"] if "county_sources" in s.get("run", ""))
    assert "capture_county_sources.py" in ev["run"]
    assert "SUPABASE_SERVICE_KEY" not in json.dumps(wf["jobs"]["evidence"])


# ------------------------------------------------------------------ TX county lists -> properties rows -> sync -> close-out

import importlib  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from harvesters.ledgers import records as LR  # noqa: E402
from harvesters.governance import inventory_status as IS  # noqa: E402

SI = importlib.import_module("sync_state_inventory")
TC = importlib.import_module("texas_closeout")
RETRIEVED = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)


def _harris_rows():
    rows, _ = T.parse_harris(HARRIS_HTML, T.HARRIS_URL)
    return rows


def _contract_ok(row):
    row = dict(row, ledger_type=SI.LEDGER_TYPE_FOR_SOURCE[row["source"]], harvester_source=row["source_id"])
    return LR.problems(row) == []


def test_properties_rows_keep_the_account_identity_the_ledger_and_the_amount_kind():
    a, b = (T.to_properties_row(r, RETRIEVED) for r in _harris_rows())
    # AUCTIONS: the account is the identity (case_no) AND the parcel; the cause number is a lawsuit, kept in provenance.
    assert (a["state"], a["source"], a["county"], a["case_no"], a["parcel"]) == ("TX", "auction", "Harris", "0000000000001", "0000000000001")
    assert a["ledger_type"] == "auctions" and "inventory_type" not in a and a["source_id"] == "tx_hctax"
    assert a["min_bid"] == 60000.50 and "purchase_amount" not in a and a["sale_date"] == "2026-11-03"
    assert a["otc_provenance"]["cause_number"] == "201900001" and a["tx_sale_status"] == "For Sale"
    assert a["url_auction"] == T.HARRIS_URL and a["url_auction_kind"] == "sale" and a["status"] == "active"
    assert b.get("min_bid") is None and b["bid"] == 0                   # "Sold with Account#": no bid invented
    # AVAILABLE: struck-off inventory; Bexar's figure is a published amount of unstated kind, never a price or a bid.
    bex, _ = T.parse_bexar_text(BEXAR_TEXT, T.BEXAR_URL)
    p = T.to_properties_row(bex[0], RETRIEVED)
    assert p["source"] == "laft" and p["inventory_type"] == "STRUCK_OFF_HELD_IN_TRUST" and "ledger_type" not in p
    assert p["purchase_amount"] == 12345.67 and p["purchase_amount_kind"] == "PUBLISHED_AMOUNT_KIND_UNSPECIFIED"
    assert p["list_as_of"] == "2026-10-06" and p["otc_provenance"]["struck_off_amount"] == 12345.67
    assert p["case_no"] == p["parcel"] == "01234-000-0010" and p["otc_provenance"]["cause_number"] == "21-TA1-01234"
    # No published figure: NOT_PUBLISHED with the legacy 0 sentinel, never an amount.
    trin, _ = T.parse_trinity_tables([[["PID", "file_as_name", "legal_desc", "state_cd"], ["16658", "TRUSTEE", "A0012", "E4"]]],
                                     "https://trinity.example/list.pdf", "2026-09-22")
    t = T.to_properties_row(trin[0], RETRIEVED)
    assert t["purchase_amount"] is None and t["purchase_amount_kind"] == "NOT_PUBLISHED" and t["bid"] == 0
    assert t["list_url"] == T.TRINITY_PAGE and t["document_url"] == "https://trinity.example/list.pdf"
    # Every kind the harvester maps is in the stored vocabulary; every row passes the ledger contract.
    assert set(T.AMOUNT_KIND_FOR.values()) <= {"MINIMUM_PURCHASE_AMOUNT", "PUBLISHED_AMOUNT_KIND_UNSPECIFIED", "ORIGINAL_OPENING_BID"}
    assert all(_contract_ok(r) for r in (a, b, p, t))


def test_duplicate_accounts_keep_the_first_and_refused_rows_are_counted():
    rows = _harris_rows()
    out, refused = T.to_properties_rows(rows + [dict(rows[0])] + [dict(rows[0], account_number="")], RETRIEVED)
    assert len(out) == 2 and refused == 1


def _status(tmp_path, entries, name="status.json"):
    p = tmp_path / name
    p.write_text(json.dumps(entries), encoding="utf-8")
    return p


def test_sync_plan_writes_published_rows_and_never_takes_over_another_sources_row(tmp_path):
    reg = SI.registry_rows("TX")
    rows = [T.to_properties_row(r, RETRIEVED) for r in _harris_rows()]
    units = SI.units_for(_status(tmp_path, [{"source_id": "tx_hctax", "county": "Harris", "status": "COMPLETE", "row_count": 2,
                                              "transport_ok": True, "parse_ok": True}]))
    out, counts = SI.plan("TX", rows, reg, units)
    assert counts["upsert"] == 2 and counts["withheld_not_publishable"] == 0 and counts["written_review_pending"] == 0
    assert all(r["publication_status"] == "APPROVED" and r["ledger_type"] == "auctions" and r["harvester_source"] == "tx_hctax"
               and r["last_seen_at"] for r in out)
    # An LGBS row already holds the first account: with keep_other_sources it is left alone (counted), never taken over.
    stored = {("auction", "Harris", "0000000000001"): {"harvester_source": "tx_lgbs", "otc_provenance": {}}}
    out2, counts2 = SI.plan("TX", rows, reg, units, stored_rows=stored, keep_other_sources=True)
    assert counts2["skipped_row_of_other_source"] == 1 and [r["case_no"] for r in out2] == ["0000000000003"]
    # A FAILED read syncs nothing.
    failed = SI.units_for(_status(tmp_path, [{"source_id": "tx_hctax", "county": "Harris", "status": "FAILED"}], "f.json"))
    assert SI.plan("TX", rows, reg, failed)[1]["skipped_unit_not_read"] == 2


def test_closeout_closes_a_county_list_row_only_after_its_own_complete_read(tmp_path):
    assert TC.COUNTY_LIST_SOURCE_IDS == set(T.SOURCE_IDS)
    harvest = _harris_rows()[:1]          # the read lists 0000000000001 only
    stored = [{"id": 1, "state": "TX", "source": "auction", "county": "Harris", "case_no": "0000000000001",
               "harvester_source": "tx_hctax", "status": "active", "sale_date": "2026-11-03"},
              {"id": 2, "state": "TX", "source": "auction", "county": "Harris", "case_no": "0000000000009",
               "harvester_source": "tx_hctax", "status": "active", "sale_date": "2026-11-03"},
              {"id": 3, "state": "TX", "source": "auction", "county": "Harris", "case_no": "0000000000008",
               "harvester_source": "tx_lgbs", "status": "active", "sale_date": "2026-11-03"},
              {"id": 4, "state": "TX", "source": "laft", "county": "Bexar", "case_no": "99999-000-0001",
               "harvester_source": "tx_bexar_resale", "status": "active"}]
    ok = {"source_id": "tx_hctax", "county": "Harris", "status": "COMPLETE", "row_count": 1, "transport_ok": True, "parse_ok": True}
    bexar_failed = {"source_id": "tx_bexar_resale", "county": "Bexar", "status": "FAILED"}
    units = TC.units_from(_status(tmp_path, [ok, bexar_failed]))
    p = TC.plan(harvest, stored, units, set(TC.SOURCE_IDS), max_share=None, now=RETRIEVED)
    # Only the tx_hctax row its own COMPLETE read no longer lists; never the LGBS row, never Bexar (its read FAILED).
    assert [c["id"] for c in p["close"]] == [2]
    assert [c["id"] for c in TC.plan(harvest, stored, units, set(TC.SOURCE_IDS), now=RETRIEVED)["close"]] == [2]


def test_closeout_reads_several_harvest_and_status_files(tmp_path, monkeypatch):
    h1 = tmp_path / "a.json"
    h1.write_text(json.dumps(_harris_rows()), encoding="utf-8")
    h2 = tmp_path / "b.json"
    h2.write_text("[]", encoding="utf-8")
    s1 = _status(tmp_path, [{"source_id": "tx_hctax", "county": "Harris", "status": "COMPLETE", "row_count": 2,
                             "transport_ok": True, "parse_ok": True}])
    sent = []
    stored = [{"id": i, "state": "TX", "source": "auction", "county": "Harris", "case_no": c, "harvester_source": "tx_hctax",
               "status": "active", "sale_date": "2026-11-03"}
              for i, c in ((7, "0000000000005"), (8, "0000000000001"), (9, "0000000000003"))]
    monkeypatch.setattr(TC, "store_permitted", lambda: set(TC.SOURCE_IDS))
    monkeypatch.setattr(TC, "stored_rows", lambda base, key: stored)
    monkeypatch.setattr(TC, "_send", lambda url, body, key: sent.append((url, body)))
    monkeypatch.setenv("SUPABASE_URL", "https://x.example")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "k")
    assert TC.main(["--harvest", str(h1), "--harvest", str(h2), "--status", str(s1)]) == 0
    closes = [(u, b) for u, b in sent if b.get("status") == "closed"]
    assert len(closes) == 1 and "id=in.(7)" in closes[0][0]


def test_county_auction_rows_get_a_feed_status_and_available_rows_a_presence_status():
    today = RETRIEVED.date()
    a = T.to_properties_row(_harris_rows()[0], RETRIEVED)
    obs = IS.status_for_row(dict(a, harvester_source="tx_hctax"), today=today)
    assert obs.status == "upcoming" and "published tax-sale list" in obs.note
    bex, _ = T.parse_bexar_text(BEXAR_TEXT, T.BEXAR_URL)
    p = T.to_properties_row(bex[0], RETRIEVED)
    assert IS.status_for_row(dict(p, harvester_source="tx_bexar_resale"), today=today).status == "active"
