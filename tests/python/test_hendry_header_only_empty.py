"""Hendry publishes an empty Lands Available list as its header row alone
(09-28-2026 list, read 2026-10-28). Only that exact shape, only for Hendry,
reads EMPTY ("empty_table"); anything after the header keeps it INCOMPLETE."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import harvest_laft_pdfs as H  # noqa: E402
import laft_status as LS  # noqa: E402

HEAD = ("LIST OF LANDS AVAILABLE FOR TAXES\n"
        "A Tax Deed Sale is Buyer Beware Market! The Clerks Office is not responsible for any errors.\n"
        "Ninety (90) days after the date of sale, the following property may be purchased ...\n"
        "sold within 3 years after placing it on the List of Land Available ...\n"
        "File No. Cert. No.Year Sale Date Parcel Identification Number Minimum Bid Taxes Address SOLD TO\n")


def test_header_alone_is_an_empty_list():
    assert H.header_only_list(HEAD)
    assert H.header_only_list(HEAD + "\n  \n")


def test_any_row_after_the_header_is_not_empty():
    assert not H.header_only_list(HEAD + "25-001 99-1234 2023 09/21/23 0-00-00-00-000-0000-0000 $1,000.00\n")
    assert not H.header_only_list(HEAD + "S Elm Street 1\n")


def test_needs_the_title_and_the_header():
    assert not H.header_only_list(HEAD.replace("LIST OF LANDS AVAILABLE FOR TAXES", "NOTICE"))
    assert not H.header_only_list("LIST OF LANDS AVAILABLE FOR TAXES\nnothing else\n")


def test_only_hendry_and_a_known_signal():
    assert H.HEADER_ONLY_EMPTY_COUNTIES == frozenset({"Hendry"})
    assert "empty_table" in LS.EMPTY_SIGNALS


def test_hendry_points_at_the_current_list():
    text = (ROOT / "data" / "laft_pdf_sources.csv").read_text()
    assert "munidocDownload/31143/9860e77035811/pdf" in text
    assert "8216f21582c5d" not in text
