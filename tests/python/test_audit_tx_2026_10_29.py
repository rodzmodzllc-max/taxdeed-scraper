"""Audit 2026-10-28, Texas findings (fixed 2026-10-29).

B4 / B20  the vendor-wins rule matches the CAD account with separators removed;
          a county-list row whose account an active vendor row holds is closed
          as superseded.
B5        a GovEase parcel page's own status banner is kept (no date derived).
B9 / B33  Bexar resale addresses in street-number order.
B17       the TX source_match carries no registry date.
B24 / F69 LGBS sale-list link = county_sale_list + '.pdf', only when published.
B32       PBFCM / MVBA / GovEase auction rows get a feed inventory status.
B40       document links are percent-encoded.
B42       incomplete vendor units are named in the log.

Synthetic values only; no network."""
from __future__ import annotations

import importlib
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import harvest_tx_county_sales as T  # noqa: E402
from harvesters import texas_vendors as V  # noqa: E402
from harvesters.governance import inventory_status as IS  # noqa: E402

SI = importlib.import_module("sync_state_inventory")
TC = importlib.import_module("texas_closeout")
A = importlib.import_module("apply_acquisition_paths")
TH = importlib.import_module("harvesters.texas_harvester")
RETRIEVED = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)


# ---------------------------------------------------------------- B4 / B20

def _bexar_row(case_no="99999-001-0001"):
    return {"state": "TX", "source": "laft", "county": "Bexar", "case_no": case_no, "parcel": case_no,
            "source_id": "tx_bexar_resale", "address": "1 Synth St", "status": "active"}


def _units():
    return {("tx_bexar_resale", "Bexar"): "COMPLETE"}


def test_account_key_drops_separators_only():
    assert SI.account_key("01235-043-0100") == SI.account_key("012350430100") == "012350430100"
    assert SI.account_key("D011 3204015") == SI.account_key("d011-3204015") == "D0113204015"
    assert SI.account_key("0001") == "0001" and SI.account_key(None) == ""


def test_county_list_never_writes_an_account_a_vendor_holds_under_another_spelling(monkeypatch):
    reg = SI.registry_rows("TX")
    monkeypatch.setattr(SI, "unit_status", lambda units, sid, county: "COMPLETE")
    stored = {("laft", "Bexar", "999990010001"): {"harvester_source": "tx_lgbs", "status": "active", "otc_provenance": {}}}
    out, counts = SI.plan("TX", [_bexar_row()], reg, _units(), stored_rows=stored, keep_other_sources=True)
    assert out == [] and counts["skipped_same_account_other_spelling"] == 1
    # The county list's own earlier row of the account is not refreshed either.
    stored[("laft", "Bexar", "99999-001-0001")] = {"harvester_source": "tx_bexar_resale", "status": "active", "otc_provenance": {}}
    out, counts = SI.plan("TX", [_bexar_row()], reg, _units(), stored_rows=stored, keep_other_sources=True)
    assert out == [] and counts["skipped_same_account_other_spelling"] == 1
    # A closed vendor row does not hold the account; without keep_other_sources nothing is skipped.
    closed = {("laft", "Bexar", "999990010001"): {"harvester_source": "tx_lgbs", "status": "closed", "otc_provenance": {}}}
    assert len(SI.plan("TX", [_bexar_row()], reg, _units(), stored_rows=closed, keep_other_sources=True)[0]) == 1
    assert len(SI.plan("TX", [_bexar_row()], reg, _units(), stored_rows=stored)[0]) == 1


def test_closeout_supersedes_a_county_list_row_an_active_vendor_row_holds():
    stored = [
        {"id": 1, "state": "TX", "source": "laft", "county": "Bexar", "case_no": "99999-001-0001",
         "harvester_source": "tx_bexar_resale", "status": "active"},
        {"id": 2, "state": "TX", "source": "laft", "county": "Bexar", "case_no": "999990010001",
         "harvester_source": "tx_lgbs", "status": "active"},
        {"id": 3, "state": "TX", "source": "laft", "county": "Bexar", "case_no": "99999-001-0002",
         "harvester_source": "tx_bexar_resale", "status": "active"},
        # Same account in ANOTHER ledger: not the same record.
        {"id": 4, "state": "TX", "source": "auction", "county": "Bexar", "case_no": "999990010002",
         "harvester_source": "tx_lgbs", "status": "active"},
        # Closed county row, listed again: not reopened while the vendor holds it.
        {"id": 5, "state": "TX", "source": "laft", "county": "Bexar", "case_no": "99999-001-0003",
         "harvester_source": "tx_bexar_resale", "status": "closed"},
        {"id": 6, "state": "TX", "source": "laft", "county": "Bexar", "case_no": "999990010003",
         "harvester_source": "tx_lgbs", "status": "active"},
    ]
    harvest = [{"harvester_source": "tx_bexar_resale", "source": "laft", "county": "Bexar", "account_number": c}
               for c in ("99999-001-0001", "99999-001-0002", "99999-001-0003")]
    units = {("tx_bexar_resale", "Bexar"): "COMPLETE"}
    p = TC.plan(harvest, stored, units, set(TC.SOURCE_IDS), max_share=TC.MAX_CLOSE_SHARE, now=RETRIEVED)
    assert p["supersede"] == [1] and p["close"] == [] and 5 not in p["reactivate"]
    assert p["supersede_by_unit"] == {"tx_bexar_resale:laft": 1}


# ---------------------------------------------------------------- B5

GOVEASE_PAGE = """<html><body><div class="alert alert-info mb-1">
  <strong>Auction Scheduled</strong> &nbsp;</div>
<div>Physical Address</div><div>1 SYNTH ST</div><div>Property Description</div>
<div>Account Number: 000111 Cause No. 2025-0001</div></body></html>"""


def test_govease_parcel_page_status_is_kept_and_no_date_is_derived():
    facts = V.parse_govease_parcel(GOVEASE_PAGE)
    assert facts["_status"] == "Auction Scheduled" and "_sale_date" not in facts
    row, why = V.govease_row("Wichita", {"Parcel #": "000111", "Auction Name": "2026 Synth County TX November Tax Sale"}, facts)
    assert why == "row" and row["sale_status"] == "Auction Scheduled" and row["auction_date"] is None


# ---------------------------------------------------------------- B9 / B33

def test_bexar_addresses_read_number_first():
    cases = {
        "Rotary, 407": "407 Rotary",
        "AmandaSt., 1234": "1234 Amanda St.",
        "SabinasN 1315 St": "1315 N Sabinas St",
        "CommerceE. St. 2630": "2630 E. Commerce St.",
        "HartE. 417 Ave.": "417 E. Hart Ave.",
        "VickersAve. #2, 1234": "1234 Vickers Ave. #2",
        "Goodrich211": "211 Goodrich",
        "ThompsonP1., 354": "354 Thompson Pl.",
        "McKayAve., 12": "12 McKay Ave.",
        "SanJoaquin 5. 1234 Ave": "1234 S. San Joaquin Ave",
        "CresthillRd.": "Cresthill Rd.",       # no number published: street words only
        "": None,
    }
    for cell, want in cases.items():
        assert T.bexar_address(cell) == want, cell


def test_bexar_parser_stores_the_normalized_address():
    text = ("Page 1\nBEXAR COUNTYRESALE PROPERTIES\nListUpdated October6, 2026\n"
            "Rotary, 407 21-TA1-01234 01234-000-0010 $12,345.67\n")
    rows, meta = T.parse_bexar_text(text, "u")
    assert meta["rows"] == 1 and rows[0]["address"] == "407 Rotary"


# ---------------------------------------------------------------- B17

def test_tx_source_match_carries_no_registry_date_and_old_dates_are_removed():
    m = A.source_match({"case_no": "1"}, listing="https://x.example/", read_on="2026-09-23", harvester="tx_lgbs")
    assert "read_at" not in m and "2026-09-23" not in m["basis"]
    old = {"identifier": "case_no", "value": "1", "source": "https://x.example/", "read_at": "2026-09-23",
           "basis": "row read from the source listing by the harvester (tx_lgbs); identity as the sync upserts it; "
                    "last successful source read 2026-09-23"}
    new = A.undated_match(old)
    assert "read_at" not in new and new["basis"].endswith("identity as the sync upserts it") and new["value"] == "1"
    lifecycle = {"identifier": "case_no", "value": "1", "read_at": "2026-10-28T00:00:00+00:00", "basis": "a lifecycle read"}
    assert A.undated_match(lifecycle) is lifecycle


# ---------------------------------------------------------------- B24 / F69

def test_lgbs_sale_list_is_the_published_pdf_only():
    base = "https://lists.example-counsel.test/County_Sale_list_SAMPLE_COUNTY_20261103"
    assert TH._lgbs_published_links({"county_sale_list": base, "sale_published": "Y"})[2] == base + ".pdf"
    assert TH._lgbs_published_links({"county_sale_list": base, "sale_published": "N"})[2] is None
    assert TH._lgbs_published_links({"county_sale_list": base})[2] is None
    assert TH._lgbs_published_links({"county_sale_list": base + ".pdf", "sale_published": "Y"})[2] == base + ".pdf"


# ---------------------------------------------------------------- B32

def test_vendor_auction_rows_get_a_feed_status():
    today = date(2026, 10, 29)
    for sid in ("tx_pbfcm", "tx_mvba", "tx_govease"):
        up = IS.status_for_row({"state": "TX", "source": "auction", "source_id": sid, "status": "active",
                                "sale_date": "2026-11-03"}, today=today)
        assert up.status == "upcoming"
        undated = IS.status_for_row({"state": "TX", "source": "auction", "source_id": sid, "status": "active"}, today=today)
        assert undated.status == "active" and "no sale date published" in undated.note
        gone = IS.status_for_row({"state": "TX", "source": "auction", "source_id": sid, "status": "closed"}, today=today)
        assert gone.status == "closed"


# ---------------------------------------------------------------- B40

def test_document_links_are_percent_encoded_and_existing_escapes_kept():
    page = ('<a href="/media/2026/02.26.2026_UPDATED TRUST PROPERTY LIST.pdf">Trust Property Tax Sales</a>'
            '<a href="/media/TRUST_All%20forms.pdf">Trust Property Tax Sales forms</a>')
    links = T.find_doc_link(page, "https://county.example.gov/dept/page", r"Trust Property Tax Sales")
    assert links == ["https://county.example.gov/media/2026/02.26.2026_UPDATED%20TRUST%20PROPERTY%20LIST.pdf",
                     "https://county.example.gov/media/TRUST_All%20forms.pdf"]
    assert not any(c.isspace() for u in links for c in u)


# ---------------------------------------------------------------- B42

def test_incomplete_units_are_named_with_their_signals():
    book = V.UnitBook()
    book.record("Alpha", "auction", V.COMPLETE, rows=3, signal="ROWS")
    book.record("Beta", "laft", V.INCOMPLETE, signal="IMAGE_ONLY")
    book.record("Beta", "auction", V.COMPLETE, rows=1, signal="ROWS")
    assert V.incomplete_unit_lines(book) == ["unit Beta INCOMPLETE (laft:INCOMPLETE:IMAGE_ONLY)"]
