"""harvest_expansion.table_header_digest: a page's table headings for a public log, never a data row."""
import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
HE = importlib.import_module("harvest_expansion")


def test_digest_lists_headings_masks_digits_and_skips_data_rows():
    html = ("<table><tr><th>Tax Deed #</th><th>Auction Date 2026</th></tr>"
            "<tr><td>2023-0012</td><td>11/18/2026</td></tr></table><p>no table here</p>")
    d = HE.table_header_digest(html)
    assert d == "1 table(s) [Tax Deed # | Auction Date 9999]"
    assert "0012" not in d and "11/18" not in d


def test_digest_of_a_page_without_tables():
    assert HE.table_header_digest("<div>Auctions are posted soon</div>") == "0 table(s) (none)"
