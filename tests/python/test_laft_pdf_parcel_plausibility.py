"""Tests for the parcel plausibility gate in scripts/harvest_laft_pdfs.py.

Five rows reached production on 2026-09-18 whose "parcel" was not a parcel:

    Leon    laft  parcel="PARCELNUMBER"           (a column header)
    Volusia laft  parcel="IDNUMBER"               (the split second line of
                                                   "SHORT PARCEL ID NUMBER")
    Volusia laft  parcel="CURRENTPURCHASEPRICE,C" (a footnote fragment)
    Volusia laft  parcel="WNISTHEORIGINALOPENING" (another footnote fragment)
    Pasco   laft  parcel=<465-char disclaimer>    (a whole paragraph)

Each became a property card with that string as its identity, because
extract_rows() runs both pdfplumber table strategies on every page and
concatenates their tables, so one strategy's header/footnote rows land as
body rows of the other's. sync-laft-to-supabase.ps1 has no gone-tracking, so
nothing ever retired them. These tests drive the real parser functions with
literal table cells - no PDF, no network.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
SCRIPT = SCRIPTS / "harvest_laft_pdfs.py"

# What actually reached production, verbatim from the properties table.
PRODUCTION_JUNK = [
    "PARCEL NUMBER",
    "ID NUMBER",
    "CURRENT PURCHASE PRICE, C",
    "WN IS THE ORIGINAL OPENING",
    "****2025XX000042TDAXXXESCHEATEDTOCOUNTY09/17/2028****2025XX000042TDAXXX18115520"
    "9/18/2025$3,492.7331-26-16-0120-00A00-0100PAPPASCOLONYSUBPB5PG4THESOUTH140.00FT"
    "OFTHEFOLLOWINGDESC:BEGATSWCOROFLOT9BLOCK\"A\"THALGWLYBDYLINEOFPAPASCOLONY",
]

# Real stored parcel formats, one per county shape seen live 2026-09-18.
REAL_PARCELS = [
    "383205430110",                # Volusia (12 digits)
    "110250U0240",                 # Leon (alnum)
    "31-26-16-0120-00A00-0100",    # Pasco
    "R27 222 19 1560 0000 0081",   # Hernando (spaces, 25 chars - the longest)
    "19E18S140040 00230 0270",     # Citrus
    "02239-137",                   # Indian River
    "2-01-43-29-010-0050-F020",    # Hendry
    "01-3123-034-0860",            # Miami-Dade
    "10-27-25-C1-00001.0100",      # dotted STRAP
    "0035260000",                  # Hillsborough (10 digits)
]


@pytest.fixture()
def laft(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))  # `from harvest_cache import ...`
    spec = importlib.util.spec_from_file_location("_laft_pdfs", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_laft_pdfs"] = mod
    spec.loader.exec_module(mod)
    return mod


# --- looks_like_parcel ------------------------------------------------------


@pytest.mark.parametrize("value", PRODUCTION_JUNK)
def test_production_junk_is_rejected(laft, value):
    assert laft.looks_like_parcel(value) is False


@pytest.mark.parametrize("value", REAL_PARCELS)
def test_real_parcel_shapes_are_accepted(laft, value):
    assert laft.looks_like_parcel(value) is True


@pytest.mark.parametrize("value", [None, "", "   ", "-", "N/A", "Unknown", "Parcel #"])
def test_blank_and_placeholder_values_are_rejected(laft, value):
    assert laft.looks_like_parcel(value) is False


def test_length_cap_sits_above_every_real_format(laft):
    assert laft.MAX_PARCEL_LEN >= max(len(laft.normalize_parcel(p)) for p in REAL_PARCELS)
    assert laft.looks_like_parcel("1" * laft.MAX_PARCEL_LEN) is True
    assert laft.looks_like_parcel("1" * (laft.MAX_PARCEL_LEN + 1)) is False


# --- is_plausible_record ----------------------------------------------------


def test_paragraph_in_parcel_cell_drops_the_row_even_with_case_no(laft, capsys):
    # Pasco: case_no "2. The" came from the same disclaimer paragraph.
    rec = {"case_no": "2. The", "parcel": PRODUCTION_JUNK[4], "address": "Office of the Clerk"}
    assert laft.is_plausible_record(rec) is False
    assert "dropped row whose parcel cell is a header/paragraph" in capsys.readouterr().out


def test_header_label_in_parcel_cell_drops_the_row_even_with_case_no(laft):
    # A leaked header row where the case column is also a header label.
    rec = {"case_no": "Tax Deed #", "parcel": "Parcel #", "sale_date": "Sale Date"}
    assert laft.is_plausible_record(rec) is False


def test_placeholder_parcel_is_discarded_but_row_with_real_case_no_survives(laft, capsys):
    rec = {"case_no": "2025-TD-0042", "parcel": "N/A", "address": "123 MAIN ST"}
    assert laft.is_plausible_record(rec) is True
    assert "parcel" not in rec
    assert "discarded non-parcel value" in capsys.readouterr().out


def test_placeholder_parcel_without_case_no_drops_the_row(laft):
    assert laft.is_plausible_record({"parcel": "ID NUMBER"}) is False
    assert laft.is_plausible_record({"parcel": "CURRENT PURCHASE PRICE, C"}) is False


def test_record_with_real_parcel_is_kept(laft):
    assert laft.is_plausible_record({"parcel": "383205430110"}) is True


def test_record_with_case_no_and_no_parcel_cell_is_kept(laft):
    # A county that publishes a case number but no parcel column at all.
    assert laft.is_plausible_record({"case_no": "2025-TD-0042"}) is True


def test_record_with_neither_identifier_is_dropped(laft):
    assert laft.is_plausible_record({"address": "123 MAIN ST"}) is False


def test_sold_rows_are_still_dropped(laft):
    assert laft.is_plausible_record({"parcel": "383205430110", "sold_to": "J DOE"}) is False


# --- through the real table parser ------------------------------------------


def test_leon_header_row_leaking_into_body_is_dropped(laft):
    # The lines-strategy table's header appears again as a body row in the
    # text-strategy table for the same page.
    table = [
        ["PARCEL NUMBER", "Legal Address", "OPENING BID"],
        ["110250U0240", "1234 SOME RD", "$1,500.00"],
        ["PARCEL NUMBER", "Legal Address", "OPENING BID"],
        ["461514G0000", "99 OTHER ST", "$900.00"],
    ]
    rows = laft._rows_from_table(table, "Leon", "https://example.test/leon.pdf")
    assert [r["parcel"] for r in rows] == ["110250U0240", "461514G0000"]
    assert all(r["case_no"] == r["parcel"] for r in rows)


def test_volusia_split_header_and_footnotes_are_dropped(laft):
    table = [
        ["CERTIFICATE NUMBER", "SHORT PARCEL", "DATE OF ORIGINAL SALE"],
        [None, "ID NUMBER", None],
        ["2019-00123", "383205430110", "05/15/2021"],
        ["2019-00456", "950400000012", "05/15/2021"],
        [None, "CURRENT PURCHASE PRICE, C", None],
        [None, "WN IS THE ORIGINAL OPENING", None],
    ]
    rows = laft._rows_from_table(table, "Volusia", "https://example.test/v.pdf")
    assert [r["parcel"] for r in rows] == ["383205430110", "950400000012"]
    assert [r["certificate_no"] for r in rows] == ["2019-00123", "2019-00456"]


def test_pasco_disclaimer_paragraph_is_dropped(laft):
    table = [
        ["Tax Deed #", "Tax Certificate #", "Sale Date", "Initial Bid", "Parcel #"],
        ["2. The", None, None, None, PRODUCTION_JUNK[4]],
        ["2025-042-TDA", "1811552", "09/18/2025", "$3,492.73", "31-26-16-0120-00A00-0100"],
    ]
    rows = laft._rows_from_table(table, "Pasco", "https://example.test/p.pdf")
    assert len(rows) == 1
    assert rows[0]["case_no"] == "2025-042-TDA"
    assert rows[0]["parcel"] == "31-26-16-0120-00A00-0100"


def test_label_value_parser_applies_the_same_gate(laft):
    text = (
        "Sale #: 2025-001 Sale Date: 01/02/2025 Parcel #: 12734-001-000 Description: LOT 1\n"
        "Sale #: 2025-002 Sale Date: 01/02/2025 Parcel #: see the current purchase price, c "
        "Description: footnote text\n"
    )
    rows = laft.extract_label_value_rows(text, "Marion", "https://example.test/m.pdf")
    # The second property keeps its real Sale # but never stores footnote
    # text as its parcel.
    assert [r["case_no"] for r in rows] == ["2025-001", "2025-002"]
    assert rows[0]["parcel"] == "12734-001-000"
    assert "parcel" not in rows[1]
