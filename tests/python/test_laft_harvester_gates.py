"""Empty-vs-broken gates in the nine Florida LAFT harvesters, exercised on
fixtures (never a live site): a zero must be EMPTY only with an explicit
signal, INCOMPLETE otherwise, and FAILED on transport/proxy/format errors.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

# playwright.sync_api is only needed at run time by two harvesters; stub it
# for import so their pure parsers can be tested here.
if "playwright.sync_api" not in sys.modules:
    pw = types.ModuleType("playwright")
    sa = types.ModuleType("playwright.sync_api")
    sa.sync_playwright = None
    sys.modules["playwright"] = pw
    sys.modules["playwright.sync_api"] = sa

import laft_status as ls  # noqa: E402
import harvest_laft_html as html_h  # noqa: E402
import harvest_laft_hillsborough as hills  # noqa: E402
import harvest_laft_leon as leon  # noqa: E402
import harvest_laft_orange as orange  # noqa: E402
import harvest_laft_osceola as osceola  # noqa: E402
import harvest_laft_pdfs as pdf_h  # noqa: E402
import harvest_laft_pioneer as pioneer  # noqa: E402
import harvest_laft_realtdm as realtdm  # noqa: E402
import harvest_laft_stlucie as stlucie  # noqa: E402


def _recorder(tmp_path, name="t"):
    return ls.StatusRecorder(name, path=tmp_path / "s.json")


# ---------------------------------------------------------------- PDF


def _minimal_pdf(text_lines: list[str]) -> bytes:
    """A one-page, uncompressed PDF with the given lines of Helvetica text -
    enough for pdfplumber's text extraction and both table strategies."""
    content_lines = ["BT", "/F1 11 Tf", "72 720 Td", "13 TL"]
    for line in text_lines:
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content_lines.append(f"({safe}) Tj T*")
    content_lines.append("ET")
    content = "\n".join(content_lines).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def test_pdf01_explicit_empty_marker_is_empty_not_incomplete():
    rows, outcome = pdf_h.extract_rows_with_outcome(_minimal_pdf(["LIST OF LANDS AVAILABLE", "There are no properties available at this time."]), "Glades", "https://g")
    assert rows == [] and outcome["empty_marker"] is True


def test_pdf02_procedural_text_without_a_table_is_unconfirmed_not_empty():
    """Brevard's LOLA.pdf: instructions only, no header row, no marker."""
    rows, outcome = pdf_h.extract_rows_with_outcome(_minimal_pdf(["Lands Available for Taxes", "To purchase, submit a written request to the Clerk.", "Fees apply."]), "Brevard", "https://b")
    assert rows == [] and outcome["empty_marker"] is False and outcome["rows"] == 0


def test_pdf03_label_block_rows_carry_bid_kind_from_the_source_label():
    text = ["Sale #: 2026-011 Sale Date: 03/03/2026 Parcel #: 12345-000 Minimum Bid: $1,250.00 Description: LOT 1",
            "Sale #: 2026-012 Sale Date: 03/03/2026 Parcel #: 12346-000 Description: LOT 2"]
    rows = pdf_h.extract_label_value_rows(" ".join(text), "Marion", "https://m")
    assert [r["case_no"] for r in rows] == ["2026-011", "2026-012"]
    assert rows[0]["bid"] == "$1,250.00" and rows[0]["bid_kind"] == "MINIMUM_PURCHASE_AMOUNT"
    assert "bid" not in rows[1] and "bid_kind" not in rows[1]


def test_pdf04_table_rows_carry_bid_kind_and_extract_rows_is_unchanged():
    table = [["File No.", "Parcel ID", "Opening Bid"], ["F-1", "P-1", "$500.00"], ["F-2", "P-2", ""]]
    rows = pdf_h._rows_from_table(table, "Hendry", "https://h")
    assert rows[0]["bid_kind"] == "OPENING_BID" and "bid_kind" not in rows[1]
    assert pdf_h.extract_rows(_minimal_pdf(["nothing available"]), "X", "https://x") == []


def test_pdf05_municode_successor_discovery_and_source_class():
    dead = "https://mcclibraryfunctions.azurewebsites.us/api/munidocDownload/31143/8216f21582c5d/pdf"
    page = '<html><iframe src="https://mcclibraryfunctions.azurewebsites.us/api/munidocDownload/31143/0badcafe0123/pdf"></iframe></html>'
    assert pdf_h.discover_successor_pdf(page, dead).endswith("/0badcafe0123/pdf")
    assert pdf_h.discover_successor_pdf(page.replace("0badcafe0123", "8216f21582c5d"), dead) is None
    assert pdf_h.discover_successor_pdf("<html>angular app</html>", dead) is None
    assert pdf_h.discover_successor_pdf('<a href="/api/munidocDownload/1/ab12/pdf">', dead) == "https://mcclibraryfunctions.azurewebsites.us/api/munidocDownload/1/ab12/pdf"
    assert pdf_h.source_class_for_url(dead) == "GOVERNMENT_PLATFORM"
    assert pdf_h.source_class_for_url("https://bradfordclerk.com/x.pdf") == "GOVERNMENT_DIRECT"


def test_pdf06_a_404_with_no_successor_is_failed_404_never_empty(tmp_path, monkeypatch):
    import requests

    class R:
        status_code = 404
        content = b""
        headers = {}
        text = "<html>angular</html>"

        def raise_for_status(self):
            raise requests.exceptions.HTTPError("404", response=self)

    def fake_get(url, **kw):
        return R()

    monkeypatch.setattr(pdf_h.requests, "get", fake_get)
    rec = _recorder(tmp_path)
    try:
        pdf_h._fetch_with_successor("https://x/dead.pdf", "https://x/page", None)
    except Exception as exc:  # noqa: BLE001
        rec.failed("Hendry", exc, source_url="https://x/page")
    e = rec.entries[0]
    assert e.status == "FAILED" and e.error_category == "TRANSPORT_HTTP_404"


# ---------------------------------------------------------------- HTML


def test_html01_recognised_header_with_zero_rows_is_empty_table():
    page = b"<html><body><table><tr><th>Case Number</th><th>Parcel ID</th><th>Amount to Purchase</th></tr></table></body></html>"
    rows, outcome = html_h.extract_rows_with_outcome(page, "Manatee", "https://m")
    assert rows == [] and outcome["header_table_found"] is True and outcome["empty_marker"] is False


def test_html02_no_table_no_marker_is_unconfirmed():
    page = b"<html><body><p>Lands Available for Taxes</p><p>Contact the clerk.</p></body></html>"
    rows, outcome = html_h.extract_rows_with_outcome(page, "Lafayette", "https://l")
    assert rows == [] and outcome["header_table_found"] is False and outcome["empty_marker"] is False and outcome["card_rows"] is False


def test_html03_marker_is_empty_and_rows_carry_bid_kind():
    page = b"<html><body><p>There are no properties at this time.</p></body></html>"
    assert html_h.extract_rows_with_outcome(page, "Gulf", "https://g")[1]["empty_marker"] is True
    page = (b"<table><tr><th>Case #</th><th>Parcel #</th><th>Opening Bid Amount</th></tr>"
            b"<tr><td>2026-1</td><td>01-02</td><td>$3,000.00</td></tr><tr><td>2026-2</td><td>01-03</td><td></td></tr></table>")
    rows, outcome = html_h.extract_rows_with_outcome(page, "Escambia", "https://e")
    assert outcome["rows"] == 2 and rows[0]["bid_kind"] == "OPENING_BID" and "bid_kind" not in rows[1]
    assert html_h.extract_rows(page, "Escambia", "https://e") == rows


def test_html04_putnam_card_rows_are_estimated_purchase_price():
    page = (b"<table><tr><td>T.D. 2026-9</td><td>Some Owner</td></tr>"
            b"<tr><td>links</td><td>LOT 4 BLK 2 Parcel Number 01-02-03</td><td>Auction date: 01/02/2026 Available for Purchase: 03/04/2026 Estimated Purchase Price: $2,100.50</td></tr></table>")
    rows, outcome = html_h.extract_rows_with_outcome(page, "Putnam", "https://p")
    assert outcome["card_rows"] is True and rows[0]["bid"] == "2,100.50" and rows[0]["bid_kind"] == "ESTIMATED_PURCHASE_PRICE"


def test_html05_proxy_failures_are_categorized_not_zero(monkeypatch):
    import requests

    class R:
        def __init__(self, code):
            self.status_code = code
            self.content = b""

        def raise_for_status(self):
            if self.status_code >= 400:
                raise requests.exceptions.HTTPError(str(self.status_code), response=self)

    class S:
        def __init__(self, codes):
            self.codes = list(codes)

        def get(self, url, **kw):
            return R(self.codes.pop(0))

    monkeypatch.setattr(html_h, "SCRAPERAPI_KEY", "")
    with pytest.raises(ls.CategorizedError) as ei:
        html_h.fetch(S([403]), "https://u")
    assert ei.value.status_category == "PROXY_NOT_CONFIGURED"
    monkeypatch.setattr(html_h, "SCRAPERAPI_KEY", "k")
    monkeypatch.setattr(html_h.time, "sleep", lambda s: None)
    with pytest.raises(ls.CategorizedError) as ei:
        html_h.fetch(S([403, 500, 500, 500]), "https://u")
    assert ei.value.status_category == "PROXY_FAILURE"
    assert ls.describe_exception(ei.value)[0] == "PROXY_FAILURE"
    # A non-403 error on the direct request propagates as itself.
    with pytest.raises(requests.exceptions.HTTPError):
        html_h.fetch(S([500]), "https://u")


# ---------------------------------------------------------------- realTDM


REALTDM_PAGE = '<html><title>realTDM : Alachua - Case Search</title><a data-status-id="1171">List of Lands - Available For Public</a>{body}</html>'


def test_realtdm01_zero_cards_on_a_recognised_page_without_a_marker_is_unconfirmed():
    html = REALTDM_PAGE.format(body="<div>Search results</div>").encode()
    rows = realtdm._parse_cases(html, "Alachua", "https://a")
    out = realtdm.classify_results_page(html, rows)
    assert rows == [] and out == {"page_recognised": True, "empty_marker": False, "rows": 0}


def test_realtdm02_marker_makes_it_empty_and_unrecognised_page_is_format_change():
    html = REALTDM_PAGE.format(body="<div>No cases found.</div>").encode()
    assert realtdm.classify_results_page(html, [])["empty_marker"] is True
    other = b"<html><title>Sign in</title><form>password</form></html>"
    assert realtdm.classify_results_page(other, [])["page_recognised"] is False


def test_realtdm03_placeholder_and_missing_label_are_categorized():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup('<html><title>realTDM : TEST - Case Search</title><h1>TEST</h1></html>', "html.parser")
    assert realtdm._is_placeholder_tenant(soup) is True
    assert realtdm._find_status_id(BeautifulSoup('<a data-status-id="5">Other</a>', "html.parser"), realtdm.STATUS_LABELS) is None
    assert realtdm.BID_KIND == "FIXED_PURCHASE_PRICE"


# ---------------------------------------------------------------- Pioneer


class _PioneerSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def get(self, url, **kw):
        self.calls += 1
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return o


class _JsonResp:
    def __init__(self, payload, status=200, ok_json=True):
        self._payload = payload
        self.status_code = status
        self.headers = {"Content-Type": "application/json" if ok_json else "text/html"}
        self._ok_json = ok_json

    def raise_for_status(self):
        pass

    def json(self):
        if not self._ok_json:
            raise ValueError("no json")
        return self._payload


def test_pioneer01_reported_zero_is_empty_and_mismatch_is_incomplete(monkeypatch, tmp_path):
    rows, outcome = pioneer.harvest_county(_PioneerSession([_JsonResp({"records": 0, "rows": []})]), "Martin", "https://m")
    assert rows == [] and outcome == {"reported": 0, "rows": 0}
    cells = ["Applicant", "2026-1TD", "C-1", "P-1", "Jan 1, 2026", "Lands Available", "$1,635.56", "", "", "Owner"]
    rows, outcome = pioneer.harvest_county(_PioneerSession([_JsonResp({"records": 2, "rows": [{"cell": cells}]})]), "Levy", "https://l")
    assert outcome == {"reported": 2, "rows": 1} and rows[0]["bid_kind"] == "OPENING_BID"
    with pytest.raises(ls.CategorizedError) as ei:
        pioneer.harvest_county(_PioneerSession([_JsonResp(None, ok_json=False)]), "Bay", "https://b")
    assert ei.value.status_category == "PARSE_FORMAT_CHANGE"
    with pytest.raises(ls.CategorizedError):
        pioneer.harvest_county(_PioneerSession([_JsonResp({"rows": []})]), "Bay", "https://b")


def test_pioneer02_connection_reset_is_retried_then_failed(monkeypatch):
    import requests
    monkeypatch.setattr(pioneer.time, "sleep", lambda s: None)
    s = _PioneerSession([requests.exceptions.ConnectionError("reset"), _JsonResp({"records": 0, "rows": []})])
    rows, outcome = pioneer.harvest_county(s, "Walton", "https://w")
    assert s.calls == 2 and outcome["reported"] == 0
    s = _PioneerSession([requests.exceptions.ConnectionError("reset")] * pioneer.TRANSPORT_ATTEMPTS)
    with pytest.raises(requests.exceptions.ConnectionError):
        pioneer.harvest_county(s, "Walton", "https://w")
    assert s.calls == pioneer.TRANSPORT_ATTEMPTS
    assert ls.describe_exception(requests.exceptions.ConnectionError("reset"))[0] == "TRANSPORT_CONNECTION"


# ---------------------------------------------------------------- single-county harvesters


def test_leon01_envelope_rules():
    assert leon.parse_payload({"data": []}) == []
    rows = leon.parse_payload({"data": [{"NewCert": "C1", "Parcel_Number": "P1", "Opening_Bid": "77,445.14", "Auction_Date": "10/22/2025"}]})
    assert rows[0]["bid_kind"] == "OPENING_BID" and rows[0]["sale_date"] == "10/22/2025"
    with pytest.raises(ls.CategorizedError):
        leon.parse_payload({"rows": []})
    with pytest.raises(ls.CategorizedError):
        leon.parse_payload([])


def test_osceola01_outcomes(tmp_path):
    rec = _recorder(tmp_path)
    osceola.record_outcome(rec, [], {"reported": 0, "rows": 0})
    assert rec.entries[-1].status == "EMPTY" and rec.entries[-1].empty_signal == "reported_count_zero"
    osceola.record_outcome(rec, [], {"reported": None, "rows": 0})
    assert rec.entries[-1].status == "INCOMPLETE" and rec.entries[-1].error_category == "UNCONFIRMED_EMPTY"
    osceola.record_outcome(rec, [{"case_no": "1"}], {"reported": 3, "rows": 1})
    assert rec.entries[-1].status == "INCOMPLETE" and rec.entries[-1].error_category == "PARSE_COUNT_MISMATCH" and rec.entries[-1].row_count == 1
    osceola.record_outcome(rec, [{"case_no": "1"}], {"reported": 1, "rows": 1})
    assert rec.entries[-1].status == "COMPLETE"
    rows, reported = osceola._parse_response({"0": {"tax_number": "T1", "trans_amt": 100.0, "_total_rows": 1}})
    assert rows[0]["bid_kind"] == "OPENING_BID" and reported == 1


def test_orange01_outcomes(tmp_path):
    rows, out = orange._parse_results_with_outcome("<html>0 items found</html>")
    assert out["empty_marker"] is True and rows == []
    rows, out = orange._parse_results_with_outcome("<html><body>Welcome, please acknowledge the disclaimer</body></html>")
    assert out["page_recognised"] is False
    html = "Tax Sale 2026-01 Sale Date: 01/02/2026 Applicant Name: Someone Status: Lands Available Parcel: 01-02 Min Bid: $1,000.00 High Bid: $0.00"
    rows, out = orange._parse_results_with_outcome(html)
    assert rows[0]["bid_kind"] == "MINIMUM_PURCHASE_AMOUNT" and out["rows"] == 1
    rec = _recorder(tmp_path)
    orange.record_outcome(rec, [], {"empty_marker": False, "page_recognised": True, "rows": 0})
    assert rec.entries[-1].error_category == "UNCONFIRMED_EMPTY"
    orange.record_outcome(rec, [], {"empty_marker": False, "page_recognised": False, "rows": 0})
    assert rec.entries[-1].error_category == "PARSE_FORMAT_CHANGE"


def test_stlucie01_outcomes(tmp_path):
    rows, out = stlucie._parse_results_with_outcome("<html><p>nothing</p></html>")
    assert out["table_found"] is False
    rows, out = stlucie._parse_results_with_outcome('<table id="dgResults"><tr><th>Case Number</th><th>Opening Bid</th></tr></table>')
    assert out["table_found"] is True and rows == []
    rows, out = stlucie._parse_results_with_outcome('<table id="dgResults"><tr><th>Case Number</th><th>Opening Bid</th></tr><tr><td>C1</td><td>$5.00</td></tr></table>')
    assert rows[0]["bid_kind"] == "OPENING_BID"
    rec = _recorder(tmp_path)
    stlucie.record_outcome(rec, [], {"table_found": False, "rows": 0})
    assert rec.entries[-1].status == "INCOMPLETE" and rec.entries[-1].error_category == "UNCONFIRMED_EMPTY"
    stlucie.record_outcome(rec, [], {"table_found": True, "rows": 0})
    assert rec.entries[-1].status == "EMPTY" and rec.entries[-1].empty_signal == "empty_table"


def test_hillsborough01_outcomes(tmp_path):
    rows, out = hills._parse_results_with_outcome(["File #", "Folio #", "Opening Bid"], [["F1", "P1", "$9.00"], ["F1", "P1", "$9.00"]], "")
    assert len(rows) == 1 and rows[0]["bid_kind"] == "OPENING_BID" and out["grid_rendered"] is True
    rec = _recorder(tmp_path)
    hills.record_outcome(rec, [], {"grid_rendered": False, "truncated": False, "rows": 0})
    assert rec.entries[-1].error_category == "UNCONFIRMED_EMPTY"
    hills.record_outcome(rec, [], {"grid_rendered": True, "truncated": False, "rows": 0})
    assert rec.entries[-1].status == "EMPTY"
    hills.record_outcome(rec, rows, {"grid_rendered": True, "truncated": True, "rows": 1})
    assert rec.entries[-1].status == "INCOMPLETE" and rec.entries[-1].error_category == "PARSE_TRUNCATED" and rec.entries[-1].row_count == 1


# ---------------------------------------------------------------- every harvester records


def test_all01_every_laft_harvester_writes_the_status_file_and_names_its_source_class():
    expected_class = {
        "harvest_laft_pdfs.py": "GOVERNMENT_DIRECT", "harvest_laft_html.py": "GOVERNMENT_DIRECT",
        "harvest_laft_realtdm.py": "GOVERNMENT_PLATFORM", "harvest_laft_pioneer.py": "GOVERNMENT_PLATFORM",
        "harvest_laft_orange.py": "GOVERNMENT_DIRECT", "harvest_laft_stlucie.py": "GOVERNMENT_PLATFORM",
        "harvest_laft_osceola.py": "GOVERNMENT_PLATFORM", "harvest_laft_hillsborough.py": "GOVERNMENT_PLATFORM",
        "harvest_laft_leon.py": "GOVERNMENT_DIRECT",
    }
    for name, cls in expected_class.items():
        src = (REPO / "scripts" / name).read_text(encoding="utf-8")
        assert "StatusRecorder(" in src and "recorder.write()" in src, name
        assert f'source_class="{cls}"' in src, name
        assert "recorder.failed(" in src, name
        # No harvester prints a raw exception without its category alongside.
        assert 'print(f"    ERROR: {exc}"' not in src and 'print(f"      ERROR: {exc}"' not in src, name
