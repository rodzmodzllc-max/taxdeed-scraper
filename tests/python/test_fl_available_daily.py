"""Florida AVAILABLE (laft) daily verification (2026-10-26).

Synthetic fixtures only (no live site, no production row):

  * HTML harvester: the Vue `<tax-deed-sales :taxdeeds=...>` list (Franklin /
    Taylor theme) - only `landavailables` entries are inventory; a tax-deed
    sale entry (Lafayette's page) never is; sold / unrecognised statuses
  * the counties' own empty statements (Hamilton, Holmes, Gulf) read EMPTY
  * PDF harvester: a 410 Gone is a dead link like a 404; the Municode node
    page is rendered for its document link; a discovered document is read
    only when it says it is the Lands Available list
  * scripts/stale_rows_report.py --daily-laft: per county, rows not seen in
    36 h and the reason from the status file; exit 1 when any
"""
from __future__ import annotations

import csv
import html as _html
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))

if "playwright.sync_api" not in sys.modules:
    pw = types.ModuleType("playwright")
    sa = types.ModuleType("playwright.sync_api")
    sa.sync_playwright = None
    sys.modules["playwright"] = pw
    sys.modules["playwright.sync_api"] = sa

import harvest_laft_html as H  # noqa: E402
import harvest_laft_pdfs as P  # noqa: E402
import laft_status as LS  # noqa: E402
import stale_rows_report as S  # noqa: E402

from test_laft_harvester_gates import _minimal_pdf  # noqa: E402


# ==================== Vue list (Franklin / Taylor) ====================

def _entry(post_type="landavailables", status="", file="99-001", parcel="R00000-001", cert="1 of 2024", **kw):
    e = {"ID": 1, "title": file or cert, "link": f"https://www.example-clerk.gov/{post_type}/{file or 'x'}/",
         "cert": cert, "parcel": parcel, "file": file, "status": status,
         "formatted_sale_date": "07/06/2026", "opening_bid": "1000.50",
         "pdf_file": {"url": "https://www.example-clerk.gov/uploads/2026/10/TD99-001.pdf", "title": "TD#99-001"}}
    e.update(kw)
    return e


def _page(entries, extra_text="") -> bytes:
    attr = _html.escape(json.dumps(entries), quote=True)
    return (f'<html><body><main><p>Lands Available for Taxes {extra_text}</p>'
            f'<tax-deed-sales class="pb-8" :taxdeeds="{attr}"></tax-deed-sales></main></body></html>').encode()


def test_vue_landavailables_entries_are_read_as_rows():
    page = _page([_entry(), _entry(file="", parcel="20-07S-04W-0000-0000-0010", cert="459-2013",
                                   original_bid="2170.56", opening_bid="",
                                   formatted_sale_date="03/04/2024 10:00 am",
                                   formatted_escheatment_date="06/04/2027")])
    rows, outcome = H.extract_rows_with_outcome(page, "Taylor", "https://www.example-clerk.gov/lands/")
    assert outcome["vue_component"] and outcome["rows"] == 2 and not outcome["unrecognised_status"]
    a, b = rows
    assert a["case_no"] == "99-001" and a["parcel"] == "R00000-001" and a["certificate_no"] == "1 of 2024"
    assert a["sale_date"] == "07/06/2026" and a["bid"] == "1000.50" and a["bid_kind"] == "ORIGINAL_OPENING_BID"
    assert a["url_auction"] == "https://www.example-clerk.gov/lands/" and a["source"] == "laft"
    assert {l["href"] for l in a["row_links"]} == {"https://www.example-clerk.gov/landavailables/99-001/",
                                                   "https://www.example-clerk.gov/uploads/2026/10/TD99-001.pdf"}
    # no file number -> the parcel-derived case number every other harvester uses
    assert b["case_no"] == "2007S04W000000000010" and b["escheatment_date"] == "06/04/2027"
    assert b["sale_date"] == "03/04/2024" and b["bid"] == "2170.56"


def test_vue_tax_deed_sale_entries_are_never_lands_available():
    # Lafayette's tax-deeds page: the same component carrying a scheduled sale
    page = _page([_entry(post_type="taxdeeds", status="scheduled")])
    rows, outcome = H.extract_rows_with_outcome(page, "Lafayette", "https://x/")
    assert rows == [] and not outcome.get("vue_component") and not outcome["empty_marker"]


def test_vue_sold_and_unrecognised_statuses():
    page = _page([_entry(), _entry(file="99-002", parcel="R00000-002", status="Sold"),
                  _entry(file="99-003", parcel="R00000-003", status="pending review")])
    rows, outcome = H.extract_rows_with_outcome(page, "Taylor", "https://x/")
    assert [r["case_no"] for r in rows] == ["99-001"]
    assert outcome["sold_rows"] == [{"county": "Taylor", "case_no": "99-002", "parcel": "R00000-002", "source": "laft"}]
    assert outcome["unrecognised_status"] == 1


def test_vue_rejects_implausible_identifiers():
    rows, outcome = H.extract_rows_with_outcome(_page([_entry(file="", parcel="Account")]), "Taylor", "https://x/")
    assert rows == [] and outcome["rejected"] == 1


def test_main_records_unrecognised_status_as_incomplete_with_rows(tmp_path, monkeypatch):
    page = _page([_entry(), _entry(file="99-003", parcel="R00000-003", status="pending review")])
    src = tmp_path / "src.csv"
    src.write_text("County,Url,SourcePage,Notes\nTaylor,https://www.example-clerk.gov/lands/,,\n", encoding="utf-8")
    monkeypatch.setattr(H, "SOURCES_CSV", src)
    monkeypatch.setattr(H, "OUT_DIR", tmp_path)
    monkeypatch.setattr(H, "OUT_JSON", tmp_path / "h.json")
    monkeypatch.setattr(H, "OUT_CSV", tmp_path / "h.csv")
    monkeypatch.setenv("LAFT_STATUS_PATH", str(tmp_path / "status.json"))
    monkeypatch.setattr(H._LS, "permission_gate", lambda *_a, **_k: 0)
    monkeypatch.setattr(H, "load_cache", lambda *_a: {})
    monkeypatch.setattr(H, "save_cache", lambda *_a: None)
    monkeypatch.setattr(H, "record_cache_stats", lambda *_a: None)
    monkeypatch.setattr(H, "write_evidence", lambda *_a: None)
    monkeypatch.setattr(H, "load_freshness", lambda *_a: {})
    monkeypatch.setattr(H, "conditional_get", lambda *_a, **_k: (200, page, {}))
    assert H.main() == 0
    entry = json.loads((tmp_path / "status.json").read_text())[0]
    assert entry["status"] == "INCOMPLETE" and entry["error_category"] == "PARSE_FORMAT_CHANGE" and entry["row_count"] == 1


@pytest.mark.parametrize("text", [
    "No available properties at this time.",                                   # Hamilton
    "UPDATED FEBRUARY 2026-THERE ARE NO LOLA FILES AT THIS TIME",             # Holmes
    "Gulf County Does Not Have Any Property On The List Of Lands.",           # Gulf
])
def test_county_empty_statements_read_empty(text):
    rows, outcome = H.extract_rows_with_outcome(f"<html><body><p>{text}</p></body></html>".encode(), "X", "https://x/")
    assert rows == [] and outcome["empty_marker"]


# ==================== PDF successor discovery ====================

class _Resp:
    def __init__(self, url, text="", code=200):
        self.url, self.text, self.status_code = url, text, code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise P.requests.exceptions.HTTPError(response=self)


MUNI_PAGE = "https://library.municode.com/FL/example_clerk/munidocs/munidocs?nodeId=abc123"
DEAD = "https://mcclibraryfunctions.azurewebsites.us/api/munidocDownload/1/dead00/pdf"
SALE_DOC = "https://mcclibraryfunctions.azurewebsites.us/api/munidocDownload/1/aaaa11/pdf"
LAFT_DOC = "https://mcclibraryfunctions.azurewebsites.us/api/munidocDownload/1/bbbb22/pdf"


def _patch_fetch(monkeypatch, docs: dict, dead_code=404):
    def cond(_req, u, _entry, **_k):
        if u == DEAD:
            raise P.requests.exceptions.HTTPError(response=_Resp(u, "", dead_code))
        return 200, docs[u], {}
    monkeypatch.setattr(P, "conditional_get", cond)
    monkeypatch.setattr(P.requests, "get", lambda u, **k: _Resp(u, "<html><app-root></app-root></html>"))


def test_municode_page_is_rendered_and_the_lands_available_document_is_chosen(monkeypatch):
    docs = {SALE_DOC: _minimal_pdf(["NOTICE OF APPLICATION FOR TAX DEED"]),
            LAFT_DOC: _minimal_pdf(["LIST OF LANDS AVAILABLE FOR TAXES", "File No. Parcel"])}
    _patch_fetch(monkeypatch, docs)
    rendered = []

    def render(url):
        rendered.append(url)
        # the viewer frame shows the sale notice; the LAFT document is listed by name
        return (f'<iframe src="{SALE_DOC}"></iframe>'
                f'<a href="{LAFT_DOC}">Lands Available List</a><a href="{SALE_DOC}">Tax Deed Notice</a>')

    status, content, _v, used, origin = P._fetch_with_successor(DEAD, MUNI_PAGE, None, render=render)
    assert used == LAFT_DOC and content == docs[LAFT_DOC] and rendered == [MUNI_PAGE] and origin == MUNI_PAGE


def test_a_discovered_document_that_is_not_the_list_is_never_read(monkeypatch):
    _patch_fetch(monkeypatch, {SALE_DOC: _minimal_pdf(["NOTICE OF APPLICATION FOR TAX DEED"])})
    with pytest.raises(LS.CategorizedError) as exc:
        P._fetch_with_successor(DEAD, MUNI_PAGE, None, render=lambda _u: f'<iframe src="{SALE_DOC}"></iframe>')
    assert exc.value.status_category == "PARSE_FORMAT_CHANGE"
    category, _ = LS.describe_exception(exc.value)
    assert category == "PARSE_FORMAT_CHANGE"


def test_a_410_gone_is_a_dead_link_and_rendering_only_applies_to_municode(monkeypatch):
    _patch_fetch(monkeypatch, {}, dead_code=410)
    calls = []
    with pytest.raises(P.requests.exceptions.HTTPError) as exc:
        P._fetch_with_successor(DEAD, "https://www.example-clerk.gov/tax-deeds/", None,
                                render=lambda u: calls.append(u) or "")
    assert exc.value.response.status_code == 410 and calls == []
    assert 410 in P.SUCCESSOR_ON_STATUS and 404 in P.SUCCESSOR_ON_STATUS


def test_municode_child_node_stays_in_the_same_library():
    html = ('<a href="/FL/example_clerk/munidocs/munidocs?nodeId=lola1">Lands Available for Taxes</a>'
            '<a href="/FL/other_city/munidocs/munidocs?nodeId=x">Lands Available</a>'
            '<a href="https://evil.example.com/FL/example_clerk/munidocs/munidocs?nodeId=y">Lands Available</a>'
            '<a href="/FL/example_clerk/munidocs/munidocs?nodeId=z">Minutes</a>')
    assert P.municode_lands_available_nodes(html, MUNI_PAGE) == [
        "https://library.municode.com/FL/example_clerk/munidocs/munidocs?nodeId=lola1"]


def test_successor_text_check():
    assert P.successor_is_lands_available("https://x/List%20of%20Lands%20Available%2020261014.pdf", b"%PDF")
    assert P.successor_is_lands_available(LAFT_DOC, _minimal_pdf(["LANDS AVAILABLE FOR TAXES"]))
    assert not P.successor_is_lands_available(SALE_DOC, _minimal_pdf(["NOTICE OF TAX DEED SALE"]))
    assert not P.successor_is_lands_available(SALE_DOC, b"not a pdf")


def test_every_registered_pdf_source_is_https():
    rows = list(csv.DictReader(open(REPO / "data/laft_pdf_sources.csv", encoding="utf-8")))
    assert rows and all(r["Url"].startswith("https://") and (r["SourcePage"] or "https://").startswith("https://")
                        for r in rows)


# ==================== daily verification ====================

NOW = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)


def _row(county, hours=None, **kw):
    r = {"state": "FL", "source": "laft", "county": county, "status": "active",
         "last_seen_at": (NOW - timedelta(hours=hours)).isoformat() if hours is not None else None}
    r.update(kw)
    return r


STATUS = [
    {"state": "FL", "county": "Alachua", "status": "COMPLETE", "source_id": "fl_laft_realtdm"},
    {"state": "FL", "county": "Escambia", "status": "FAILED", "error_category": "PROXY_FAILURE", "source_id": "fl_laft_html"},
    {"state": "FL", "county": "Hendry", "status": "FAILED", "error_category": "TRANSPORT_HTTP_404", "source_id": "fl_laft_pdfs"},
    {"state": "FL", "county": "Taylor", "status": "INCOMPLETE", "error_category": "PARSE_NO_TABLE", "source_id": "fl_laft_html"},
    {"state": "FL", "county": "Lee", "status": "COMPLETE", "source_id": "fl_laft_realtdm"},
]


def test_daily_check_counts_and_reasons():
    rows = [_row("Alachua", 2), _row("Alachua", 3), _row("Escambia", 600), _row("Hendry"),
            _row("Taylor", 48), _row("Lee", 40), _row("Bay", 50),
            _row("Bay", 1, status="closed"), _row("Bay", 50, state="LA"), _row("Bay", 50, source="auction")]
    check = S.daily_laft_check(rows, STATUS, NOW)
    assert check["Alachua"] == {"active": 2, "seen": 2, "unverified": 0, "never_read": 0, "reason": "", "detail": ""}
    assert check["Escambia"]["reason"] == "SOURCE_UNAVAILABLE" and "PROXY_FAILURE" in check["Escambia"]["detail"]
    assert check["Hendry"]["reason"] == "SOURCE_UNAVAILABLE" and check["Hendry"]["never_read"] == 1
    assert check["Taylor"]["reason"] == "READ_INCOMPLETE"
    assert check["Lee"]["reason"] == "READ_BUT_NOT_ON_LIST"
    assert check["Bay"]["reason"] == "NOT_READ_TODAY" and check["Bay"]["active"] == 1
    text, errors = S.render_daily(check)
    assert len(errors) == 5 and all(e.startswith("::error ") for e in errors)
    assert "RESULT: FAIL - 5 of 7 active row(s) in 5 county(ies)" in text


def test_daily_check_worst_source_wins_and_a_verified_state_passes():
    entries = [{"state": "FL", "county": "Polk", "status": "COMPLETE"},
               {"state": "FL", "county": "Polk", "status": "FAILED", "error_category": "PARSE_FORMAT_CHANGE"}]
    assert S.county_read_reason(entries)[0] == "READ_FAILED"
    check = S.daily_laft_check([_row("Polk", 1)], entries, NOW)
    text, errors = S.render_daily(check)
    assert errors == [] and "RESULT: PASS" in text


def test_daily_cli_exit_codes_and_value_free_output(tmp_path, capsys):
    rows = [_row("Alachua", 2, case_no="SECRET-CASE", parcel="SECRET-PARCEL", address="1 SECRET ST"),
            _row("Escambia", 600, case_no="SECRET-2")]
    (tmp_path / "rows.json").write_text(json.dumps(rows))
    (tmp_path / "status.json").write_text(json.dumps(STATUS))
    out_json = tmp_path / "daily.json"
    rc = S.main(["--daily-laft", "--rows", str(tmp_path / "rows.json"), "--status", str(tmp_path / "status.json"),
                 "--now", NOW.isoformat(), "--json", str(out_json)])
    printed = capsys.readouterr().out + out_json.read_text()
    assert rc == 1 and "Escambia" in printed and "SECRET" not in printed
    (tmp_path / "rows.json").write_text(json.dumps(rows[:1]))
    assert S.main(["--daily-laft", "--rows", str(tmp_path / "rows.json"), "--now", NOW.isoformat()]) == 0


def test_daily_check_is_the_laft_jobs_last_step():
    wf = (REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
    i = wf.index("scripts/stale_rows_report.py --daily-laft --state FL --status out/harvest_laft_status.json")
    assert wf.index("detect_property_changes.py --state TX --source laft") < i
    step = wf[wf.rindex("- name:", 0, i):i]
    assert "continue-on-error: true" in step and "if: always()" in step
