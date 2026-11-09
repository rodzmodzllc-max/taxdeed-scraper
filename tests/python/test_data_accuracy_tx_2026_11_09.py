"""Texas data-accuracy fixes (2026-11-09), synthetic fixtures only.

TX-02  Bexar's resale-list text layer reads a '1' as '!' in some rows (in the
       suit number's 'TA1', in its digits and in the account). Rows with
       'TA!' were silently dropped (not even counted as rejected) and rows
       with a '!' in the digits were rejected, so every read was INCOMPLETE
       and nothing absent could ever be closed. A '!' now reads as '1' in
       the identifiers, and as '1' (next to a digit) or 'l' in the address.
TX-06  PBFCM documents that read INCOMPLETE on every run (shapes observed
       2026-11-09, values synthetic here):
       - an account cell whose first line is the id and the rest a note
         (Willis ISD) was skipped as "a description";
       - Trinity's sale list names the account as 'PID #12345' or ends the
         description with the unlabelled real-property account 'R12345';
       - the City of Cleveland resale list is labelled entries ('Cause #: /
         Tax ID: / Property Description:'), no table;
       - Potter's sale notice sends the reader to the county's site for the
         listing: a redirect notice (EMPTY), not an unread layout.
       A row with no published identifier stays unread (INCOMPLETE).
TX-03  MVBA sale / trust lists (part 2):
       - 'Georgetown' matched the 'GEO' label first and hid the real
         'Account #R123456' after it (Williamson, Hill);
       - Bandera's trust list prints its header as page text above
         header-less tables (Subdivision Name | Section | Blk | Lots | PID# |
         Value | Court Cost | Suit #). A row naming two PIDs is one package:
         unread, never split.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

T = importlib.import_module("harvest_tx_county_sales")
from harvesters import texas_vendors as V  # noqa: E402
from harvesters import tx_sale_tables as TT  # noqa: E402
CS = importlib.import_module("test_county_sources_2026_10_26")

BANG_LINES = [
    "SynthSt., 100 21-TA!-01234 01234-000-0010 $12,345.67",       # 'TA1' read as 'TA!' (was dropped silently)
    "Mi!!Ave., 300 !9-TAX-9!234 45678-000-0020 $2,000.00",          # '!' in the suit digits (was rejected)
    "PineRd., 21! 22-TA1-55555 56789-000-002! $3,000.00",          # '!' in the account and the house number
]


def _text(lines):
    head, _, tail = CS.BEXAR_TEXT.partition("THE DOLLAR AMOUNTS")
    return head + "\n".join(lines) + "\nTHE DOLLAR AMOUNTS" + tail


def test_bexar_bang_rows_are_read_and_the_list_is_complete():
    rows, meta = T.parse_bexar_text(_text(BANG_LINES), "u")
    assert meta["rejected"] == 0 and meta["rows"] == 4 + len(BANG_LINES)
    assert T.classify(rows, meta) == ("COMPLETE", None)
    added = rows[2:2 + len(BANG_LINES)]
    assert [r["cause_number"] for r in added] == ["21-TA1-01234", "19-TAX-91234", "22-TA1-55555"]
    assert [r["account_number"] for r in added] == ["01234-000-0010", "45678-000-0020", "56789-000-0021"]
    assert added[1]["address"] == "300 Mill Ave."
    assert added[2]["address"] == "211 Pine Rd."
    assert not any("!" in (r["address"] or "") + r["cause_number"] + r["account_number"] for r in rows)


def test_a_really_garbled_line_still_makes_the_read_incomplete():
    rows, meta = T.parse_bexar_text(_text(["SynthSt., 100 21-TA!-01234 garbled"]), "u")
    assert meta["rejected"] == 1 and T.classify(rows, meta) == ("INCOMPLETE", "PARSE_FORMAT_CHANGE")


# ------------------------------------------------------------------ TX-06

def test_an_account_cell_with_a_note_under_the_id_is_read():
    head = ["", "PREVIOUS OWNER", "JUDGMENT AMOUNT", "APPRAISED VALUE", "ACCOUNT NUMBER", "DATE OF TAX DEED"]
    note = "12.3456.78.90123\n**Note**\n*Mobile home not\nincluded in this sale\nper the judgment entered\nin the cause above*"
    assert len(note) > 80
    r = TT.read_tables([[head, ["1.", "Synth Owner", "$1,000.00", "$20,000.00", note, "1/2/2020"],
                         ["2.", "Synth Owner", "$1,000.00", "$20,000.00", "12.3456.78.90124", "1/2/2020"]]])
    assert [x.account for x in r.rows] == ["12.3456.78.90123", "12.3456.78.90124"] and r.skipped_no_account == 0


def test_a_long_description_in_the_account_column_is_still_not_an_account():
    head = ["Cause No", "Account", "Minimum Bid"]
    desc = "Lot 1 Block 2 Synthetic Addition being the same land described in Volume 123 Page 456 of the deed records"
    r = TT.read_tables([[head, ["C-1001", desc, "$1,000.00"]]])
    assert r.rows == [] and r.skipped_no_account == 1


def test_trinity_pid_label_and_trailing_r_account():
    head = ["Case No.", "Legal Description/Address (if available)", "Estimated Minimum Bid"]
    rows = [
        head,
        ["1234 Synth County, et al Vs. Synth", "Tract 1. Lot 10, Blk 2, Synth Addition in Vol 100 and Pg 200,R12345 "
         "(Does not Include MH Label # ABC1234567)", "$5,000.00"],
        ["", "Tract 2. Lot 11, Section 3 Synth Estates in Vol. 101 and Pg. 201 R12346", "$4,000.00"],
        ["", "Tract 3. BEING 1.00 ACRE IN THE SYNTH SURVEY, IDENTIFIED UNDER PID #54321 (SUBJECT TO 2026 TAXES)",
         "$3,000.00"],
        ["", "TRACT ONE: BEING 1.00 ACRE; TRACT TWO: BEING 2.00 ACRES IN THE SYNTH SURVEY (SUBJECT TO 2026 TAXES)",
         "$2,000.00"],
    ]
    r = TT.read_tables([rows])
    assert [x.account for x in r.rows] == ["R12345", "R12346", "54321"]
    assert r.skipped_no_account == 1   # no identifier published: never invented
    assert V.document_status(TT.TableReadResult(rows=r.rows, skipped_no_account=1, chars=10)) == (
        "INCOMPLETE", "ROWS_WITH_UNREAD")


def test_an_r_in_the_middle_of_a_description_is_not_an_account():
    head = ["Case No.", "Legal Description", "Minimum Bid"]
    r = TT.read_tables([[head, ["1234", "Lot 1, R12345 Synth Addition, Synth County Texas", "$1,000.00"]]])
    assert r.rows == [] and r.skipped_no_account == 1


LABEL_TEXT = """(last updated November 1, 2026)
TRUST PROPERTY
CITY OF SYNTH
Cause #: CV12345678
Judgment: 01-2-2020 Synth vs Synth
Sale: 03-04-2021
Struck-Off amount: $1,234.56
Successful bidder will also have to pay $100.00 for city liens.
Tax ID: 12345/123456-123456-123
Address: Synth St.
Property Description: Lot 1 Block 2 Synth Addition
to the City of Synth, Synth County, Texas
2026 Value: $20,000.00
Cause #: CV12345679
Judgment: 1-2-2020 Synth
Sale: 03-04-2021
Struck-Off amount: $2,000.00
Tax ID: 12346/123456-123456-124
Address: 100 W. Synth Ave.
Property Description: Lot 2 Block 2 Synth Addition
2026 Value: $30,000.00
A bid for less than the struck-off amount will also need to be approved.
Cause #: CV12345680
Judgment: 1-2-2020 Synth
Struck-Off amount: $3,000.00
Address: 200 Synth Rd.
Property Description: Lot 3 Block 2 Synth Addition
2026 Value: $10,000.00
"""


def test_label_layout_entries_are_read():
    r = TT.read_label_layout(LABEL_TEXT)
    assert [x.account for x in r.rows] == ["12345", "12346"]
    a, b = r.rows
    assert a.cause == "CV12345678" and a.min_bid == 1234.56 and a.value == 20000.0
    assert a.legal == "Lot 1 Block 2 Synth Addition to the City of Synth, Synth County, Texas"
    assert a.address == "Synth St." and b.address == "100 W. Synth Ave." and b.value == 30000.0
    assert r.skipped_no_account == 1   # the third entry publishes no Tax ID
    assert TT.read_label_layout("Lots of prose\nand no labels").rows == []


def test_a_notice_sending_the_reader_to_the_county_listing_is_a_redirect():
    res = TT.TableReadResult(chars=500, text="SYNTH COUNTY SALES FOR DECEMBER 1, 2026 ... See www.synthcountytax.com "
                                             "for complete listing FOR FURTHER INFORMATION ...")
    assert V.document_status(res) == ("EMPTY", "REDIRECT_NOTICE")
    # A document with rows is read as rows whatever its notes say.
    res.rows = [TT.SaleTableRow("1", None, None, None, None, None)]
    assert V.document_status(res) == ("COMPLETE", "ROWS")


# ------------------------------------------------------------------ TX-03 (MVBA lists)

def test_a_place_name_does_not_hide_the_account_label():
    head = ["TRACT", "SUIT #", "STYLE", "PROPERTY DESCRIPTION, APPROXIMATE ADDRESS, ACCT #", "MIN BID"]
    desc = ("Tract 1 being 1.00 acres out of the Synth Survey, Abstract 12, City of Georgetown, Synth County, "
            "Texas (Volume 100, Page 200 of the Official Records), 100 Synth Rd, Georgetown, Texas 78626 "
            "Account #R123456")
    r = TT.read_tables([[head, ["1", "26-0001-T426", "The County of Synth Texas vs. Synth", desc, "$10,000.00"]]])
    assert [x.account for x in r.rows] == ["R123456"] and r.skipped_no_account == 0
    plural = desc.replace("Account #R123456", "Accounts #R123456 and #R123457")
    r = TT.read_tables([[head, ["2", "26-0002-T426", "The County of Synth Texas vs. Synth", plural, "$1.00"]]])
    assert r.rows == [] and r.skipped_no_account == 1   # a two-account package is never stored under one


LOT_HEADER = "Subdivision Name Section Blk Lots PID# Value Court Cost Suit #"


def test_lot_list_with_the_header_in_the_page_text():
    assert TT._LOT_LIST_HEADER.search("Land held in trust\n" + LOT_HEADER + "\nSynth Acres")
    tables = [[
        ["Synth Acres", "A", "1A", "5", "123456", "$ 12,000.00", "N/A", "Gift"],
        ["Synth Ranch Estates", "2", "", "Lot 7", "123457", "$ 3,500.00", "$120.00", "21-123"],
        ["Synth Hills", "B", "3", "8 & 9", "123458 and 123459", "$ 9,000.00", "N/A", "Gift"],
    ]]
    r = TT.read_lot_list(tables)
    assert [x.account for x in r.rows] == ["123456", "123457"] and r.skipped_no_account == 1
    a, b = r.rows
    assert a.legal == "Synth Acres, Section A, Blk 1A, Lots 5" and a.value == 12000.0 and a.cause is None
    assert b.legal == "Synth Ranch Estates, Section 2, Lot 7" and b.cause == "21-123"
    assert a.min_bid is None and b.min_bid is None   # the list publishes no price
    assert V.document_status(TT.TableReadResult(rows=r.rows, skipped_no_account=1, chars=10))[0] == "INCOMPLETE"
