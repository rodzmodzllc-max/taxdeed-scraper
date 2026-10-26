"""Fayette County PA (2026-10-26): the harvester reads the Tax Claim Bureau's
Repository Sale page, follows the link whose file name carries the NEWEST
date, and reads that file - an XLSX workbook (its "Active" sheet only) or a
text PDF. Every page and workbook here is SYNTHETIC (built in the test); the
PDF is the existing synthetic fixture."""
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
import sync_state_inventory as SY  # noqa: E402
from harvesters.otc.adapters import expansion as EX  # noqa: E402
from harvesters.otc.adapters.tabular import latest_dated_link, workbook_sheet_rows  # noqa: E402

openpyxl = pytest.importorskip("openpyxl")

AT = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
PAGE = EX.PA_FAYETTE_PAGE
HOST = "https://www.fayettecountypa.org"
NEWEST = f"{HOST}/DocumentCenter/View/20002/Repository-Update-10-7-2026"
PDF_FIXTURE = ROOT / "tests/python/fixtures/available_five/pa_fayette_Repository-Update-10-7-2025.pdf"
HEADER = ["PARCEL", "Municipality", "OWNER", "DESCRIPTION", "SALE", "Min. Bid", "Comments"]

PAGE_HTML = f"""<html><body>
<a href="/DocumentCenter/View/5599/Repository-Bid-Form">Repository Bid Form</a>
<a href="/DocumentCenter/View/10840/Repository-Update-1-9-2026">Repository Update 1-9-2026</a>
<a href="/DocumentCenter/View/11120/Repository-Update-3-3-2026pdf">Repository Update 3-3-2026.pdf</a>
<a href="/DocumentCenter/View/20002/Repository-Update-10-7-2026">Repository Update 10-7-2026</a>
<a href="/DocumentCenter/View/20001/Repository-Update-9-28-2026">Repository Update 9-28-2026</a>
<a href="http://www.fayettecountypa.org/DocumentCenter/View/30000/Repository-Update-12-1-2026">insecure link</a>
<a href="https://elsewhere.example/DocumentCenter/View/30001/Repository-Update-12-2-2026">another host</a>
<a href="/930/Repository-Sale">Repository Sale</a>
</body></html>"""


def workbook(active_rows, completed_rows=(), *, sheets=("Active", "Completed")) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheets[0]
    for r in [["SYNTHETIC TAX CLAIM BUREAU"], ["Repository Sale Properties "], ["Bids to be opened monthly"], HEADER] + list(active_rows):
        ws.append(r)
    if len(sheets) > 1:
        done = wb.create_sheet(sheets[1])
        done.append(["parcel "])
        for r in completed_rows:
            done.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ACTIVE = [
    ["01-02-0003", "SYNTHETIC BORO", "SYNTHETIC OWNER A", "LOT 1 FIXTURE PLAN", "F&C 2015", 271.71, None],
    ["11-22-3333-001", "SYNTHETIC TWP", "SYNTHETIC OWNER B", "LOT 2 FIXTURE PLAN", "F&C 2019", 500, ""],
    ["22-33-4444-B1-2", "SYNTHETIC TWP", "SYNTHETIC OWNER C", "LOT 3 FIXTURE PLAN", "F&C 2021", 1250.5, None],
    ["33-44-5555", "SYNTHETIC TWP", "SYNTHETIC OWNER D", "LOT 4 FIXTURE PLAN", "F&C 2020", 900, " Bid received "],
    ["44-55-6666", "SYNTHETIC TWP", "SYNTHETIC OWNER E", "LOT 5 FIXTURE PLAN", "F&C 2020", 900, "BID  RECEIVED"],
]
COMPLETED = [["55-66-7777", "SYNTHETIC TWP", "SYNTHETIC OWNER F", "LOT 6 FIXTURE PLAN", "F&C 2018", 300, "Sold"],
             ["66-77-8888", "SYNTHETIC TWP", "SYNTHETIC OWNER G", "LOT 7 FIXTURE PLAN", "F&C 2018", 300, None]]


def fetchers(doc: bytes, calls: list):
    def fetch_text(url):
        calls.append(url)
        assert url == PAGE
        return PAGE_HTML

    def fetch_bytes(url):
        calls.append(url)
        return doc
    return fetch_text, fetch_bytes


def run(doc: bytes, calls=None):
    calls = [] if calls is None else calls
    ft, fb = fetchers(doc, calls)
    return HE.run_source(EX.SOURCES["PA"][0], None, ft, retrieved_at=AT, fetch_bytes=fb)


def test_config_reads_the_page_and_never_maps_the_owner():
    (src,) = [s for s in EX.SOURCES["PA"] if s.config.source_id == "pa_fayette_repository"]
    cfg = src.config
    assert src.kind == "latest_dated_document" and src.url == PAGE == cfg.list_url
    assert cfg.document_sheet == "Active" and cfg.status_exclude == ("Bid Received",)
    assert not cfg.columns.owner_name


def test_newest_dated_link_on_the_page_is_picked():
    url, when = latest_dated_link(PAGE_HTML, PAGE, EX.PA_FAYETTE_REPOSITORY)
    assert url == NEWEST and when == date(2026, 10, 7)          # not the http / other-host links, not page order
    assert latest_dated_link("<a href='/930/Repository-Sale'>x</a>", PAGE, EX.PA_FAYETTE_REPOSITORY) is None


def test_xlsx_active_sheet_only_title_rows_skipped_bid_received_excluded(capsys):
    calls = []
    status, recs, cat, _, _ = run(workbook(ACTIVE, COMPLETED), calls)
    assert calls == [PAGE, NEWEST]
    assert status == "COMPLETE" and cat is None
    assert [r.case_no for r in recs] == ["01-02-0003", "11-22-3333-001", "22-33-4444-B1-2"]   # Completed never read
    for r in recs:
        assert r.list_as_of == date(2026, 10, 7)                 # the file name's own date, never today
        assert r.document_url == NEWEST and r.list_url == PAGE
        assert r.owner_name is None and r.validate() == []
    assert recs[0].amount == 271.71 and recs[0].amount_kind.value == "OPENING_BID" and recs[1].amount == 500
    blob = json.dumps([r.to_properties_row() for r in recs], default=str)
    assert "SYNTHETIC OWNER" not in blob
    out = capsys.readouterr().out
    assert "offered=3 excluded=2 bad-id=0" in out and "SYNTHETIC" not in out and "01-02-0003" not in out


def test_rows_are_the_active_sheet_only():
    rows = workbook_sheet_rows(workbook(ACTIVE, COMPLETED), " active ")
    assert len(rows) == 4 + len(ACTIVE) and not any("55-66-7777" in c for r in rows for c in r)
    with pytest.raises(KeyError):
        workbook_sheet_rows(workbook(ACTIVE, COMPLETED), "Missing")


def test_pdf_path_still_works():
    status, recs, _, _, _ = run(PDF_FIXTURE.read_bytes())
    assert status == "COMPLETE" and [r.case_no for r in recs] == ["01-02-0003", "11-22-3333", "22-33-4444-002"]
    assert {r.list_as_of for r in recs} == {date(2026, 10, 7)} and {r.document_url for r in recs} == {NEWEST}


def test_no_dated_link_is_failed_and_nothing_is_downloaded():
    calls = []

    def fetch_bytes(url):
        calls.append(url)
        return b""
    status, recs, cat, _, _ = HE.run_source(EX.SOURCES["PA"][0], None, lambda u: "<html><a href='/x'>Bid form</a></html>",
                                            retrieved_at=AT, fetch_bytes=fetch_bytes)
    assert (status, recs, cat, calls) == ("FAILED", [], "PARSE_NO_TABLE", [])


@pytest.mark.parametrize("doc", [
    b"<html>moved</html>",                                                      # neither XLSX nor PDF
    "workbook-without-active",                                                  # no Active sheet
    "workbook-no-identifier",                                                   # header, but no identifier row
])
def test_unreadable_or_identifierless_file_is_a_format_change_never_empty(doc):
    if doc == "workbook-without-active":
        doc = workbook(ACTIVE, sheets=("Sheet1",))
    elif doc == "workbook-no-identifier":
        doc = workbook([["Total", "", "", "", "", 1000, ""], ["see notes", "", "", "", "", "", ""]])
    status, recs, cat, _, empty = run(doc)
    assert (status, recs, cat, empty) == ("FAILED", [], "PARSE_FORMAT_CHANGE", None)


def test_every_row_bid_received_is_the_sources_own_empty():
    status, recs, cat, _, empty = run(workbook([r for r in ACTIVE if r[6] and "id" in r[6].lower()]))
    assert (status, recs, empty) == ("EMPTY", [], "no_offered_status")


@pytest.mark.parametrize("where", ["page", "file"])
def test_transport_error_is_failed(where):
    def boom(url):
        raise ConnectionError("synthetic")
    ft = boom if where == "page" else (lambda u: PAGE_HTML)
    status, recs, cat, _, _ = HE.run_source(EX.SOURCES["PA"][0], None, ft, retrieved_at=AT, fetch_bytes=boom)
    assert (status, recs, cat) == ("FAILED", [], "TRANSPORT_CONNECTION")


def test_fixture_run_writes_complete_status_and_rows(tmp_path):
    doc = tmp_path / "Repository-Update-10-7-2026.xlsx"
    doc.write_bytes(workbook(ACTIVE, COMPLETED))
    assert HE.main(["--state", "PA", "--fixture", f"pa_fayette_repository={doc}", "--out-dir", str(tmp_path / "o")]) == 0
    rows = json.loads((tmp_path / "o" / "pa_properties_rows.json").read_text())
    assert SY.status_units(tmp_path / "o" / "harvest_pa_status.json") == {"Fayette": "COMPLETE"}
    assert sorted(r["case_no"] for r in rows) == ["01-02-0003", "11-22-3333-001", "22-33-4444-B1-2"]
    assert {r["list_as_of"] for r in rows} == {"2026-10-07"}
