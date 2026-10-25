"""Florida sources batch (2026-10-25): Charlotte Clerk Lands Available (JSON
endpoint), Leon Tax Collector county-held certificates (zipped .xlsx), and the
Lake realTDM candidate. Every fixture here is SYNTHETIC - invented values in
the shape of the live sources, never a row from them.
docs/sources-batch-2026-10-25-florida.md.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import harvest_laft_charlotte as ch  # noqa: E402
import harvest_leon_certificates as leon  # noqa: E402
import laft_status as ls  # noqa: E402
from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import permissions as PERM  # noqa: E402

DAY = date(2026, 10, 25)
SECRET_OWNER = "SYNTHETIC OWNER DO NOT STORE"
SECRET_APPLICANT = "SYNTHETIC APPLICANT LLC"


def _rec(tmp_path, name="t"):
    return ls.StatusRecorder(name, path=tmp_path / "s.json", source_class="GOVERNMENT_DIRECT")


# ------------------------------------------------------------- Charlotte

def _ch_row(case="99-0001", parcel="000000000001", status="LANDS AVAILABLE", base=1234.5):
    return {"Applicant": SECRET_APPLICANT, "CaseNumber": case, "CertificateNumber": "2020-0001", "ParcelId": parcel,
            "SaleDate": "2026-01-15T00:00:00", "Status": status, "BaseBid": base, "HighBid": 9999.0, "Surplus": 0.0,
            "Owners": SECRET_OWNER, "CaseId": 11111}


def _env(rows, total=None):
    return {"Data": rows, "Total": len(rows) if total is None else total, "AggregateResults": None, "Errors": None}


def test_ch01_complete_maps_only_the_listed_fields(tmp_path):
    r = _rec(tmp_path)
    out = ch.run([_env([_ch_row(), _ch_row(case="99-0002", parcel="0000 0000 0002", base=0)])], recorder=r)
    assert r.entries[-1].status == "COMPLETE" and r.entries[-1].row_count == 2
    assert out[0] == {"county": "Charlotte", "source": "laft", "url_auction": ch.PAGE_URL, "case_no": "99-0001",
                      "parcel": "000000000001", "certificate_no": "2020-0001", "sale_date": "01/15/2026",
                      "bid": "1234.50", "bid_kind": "OPENING_BID"}
    assert out[1]["parcel"] == "000000000002" and "bid" not in out[1]
    blob = json.dumps(out)
    assert SECRET_OWNER not in blob and SECRET_APPLICANT not in blob and "9999" not in blob


def test_ch02_zero_is_empty_only_on_the_endpoints_own_count(tmp_path):
    r = _rec(tmp_path)
    assert ch.run([_env([])], recorder=r) == []
    e = r.entries[-1]
    assert e.status == "EMPTY" and e.empty_signal == "reported_count_zero"


@pytest.mark.parametrize("pages,category", [
    ([_env([_ch_row()], total=3)], "PARSE_COUNT_MISMATCH"),
    ([_env([_ch_row(status="SOLD")])], "UNCONFIRMED_EMPTY"),
    ([_env([_ch_row(case="", parcel="NO DIGITS")])], "PARSE_FORMAT_CHANGE"),
])
def test_ch03_untrusted_zero_or_partial_read_is_incomplete(tmp_path, pages, category):
    r = _rec(tmp_path)
    ch.run(pages, recorder=r)
    assert r.entries[-1].status == "INCOMPLETE" and r.entries[-1].error_category == category


def test_ch04_count_mismatch_still_emits_the_rows_read(tmp_path):
    r = _rec(tmp_path)
    out = ch.run([_env([_ch_row()], total=2)], recorder=r)
    assert len(out) == 1 and r.entries[-1].row_count == 1


@pytest.mark.parametrize("payload", [[], {"Data": None, "Total": 1}, {"Data": [], "Total": 0, "Errors": {"x": 1}}])
def test_ch05_unrecognised_envelope_fails(tmp_path, payload):
    r = _rec(tmp_path)
    assert ch.run([payload], recorder=r) == []
    assert r.entries[-1].status == "FAILED" and r.entries[-1].error_category == "PARSE_FORMAT_CHANGE"


def test_ch06_token_is_read_from_the_page_or_fails():
    assert ch.find_token('<input name="__RequestVerificationToken" type="hidden" value="abc" />') == "abc"
    with pytest.raises(ls.CategorizedError):
        ch.find_token("<html></html>")


def test_ch07_live_read_pages_until_the_reported_total(tmp_path, monkeypatch):
    calls = []

    class Resp:
        def __init__(self, text=None, payload=None):
            self.text, self._p, self.status_code = text, payload, 200

        def raise_for_status(self):
            pass

        def json(self):
            return self._p

    class Session:
        def get(self, url, **kw):
            calls.append(("GET", url))
            return Resp(text='<input name="__RequestVerificationToken" value="tok" />')

        def post(self, url, data=None, **kw):
            calls.append(("POST", url, data["page"], data["__RequestVerificationToken"]))
            page = int(data["page"])
            rows = [_ch_row(case=f"99-{page:04d}")]
            return Resp(payload=_env(rows, total=2))

    monkeypatch.setattr(ch.requests, "Session", Session)
    r = _rec(tmp_path)
    out = ch.run(recorder=r)
    assert [c[0] for c in calls] == ["GET", "POST", "POST"] and calls[1][1] == ch.DATA_URL and calls[1][3] == "tok"
    assert len(out) == 2 and r.entries[-1].status == "COMPLETE"


# ------------------------------------------------------------- Leon

HEADER = ["bidderno", "ceryear ", "cernumber ", "cerpartno ", "rollyear ", "interestrate ", "issuedate ", "holdername ",
          "holderaddr1 ", "propertynumber ", "ownername ", "address1 ", " city ", " zipcode ", "justvalue ",
          "taxablevalue ", " faceamt ", " legaldesc ", " acreage"]


def _leon_row(year=2024, number=101, part=0, parcel="   1100000000000", face=321.45):
    return [900, year, number, part, year - 1, 18, int(f"{year}0601"), "SYNTHETIC COUNTY HOLDER", "1 SYNTHETIC WAY",
            parcel, SECRET_OWNER, "999 SYNTHETIC MAILING RD", "NOWHERE", 99999, 50000, 40000, face,
            "SYNTHETIC  LEGAL   TEXT", 0.5]


def _zip(rows, header=HEADER, name="OpenCountyCertificates20261001.xlsx", extra=None):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    if header is not None:
        ws.append(header)
    for r in rows:
        ws.append(r)
    xb = io.BytesIO()
    wb.save(xb)
    zb = io.BytesIO()
    with zipfile.ZipFile(zb, "w") as z:
        z.writestr(name, xb.getvalue())
        if extra:
            z.writestr(extra, b"x")
    return zb.getvalue()


def test_le01_complete_maps_the_certificate_and_never_the_owner(tmp_path):
    r = _rec(tmp_path)
    out = leon.run(_zip([_leon_row(), _leon_row(number=102, part=2, parcel="   21 29 A0010")]), as_of="2026-10-01", recorder=r)
    assert r.entries[-1].status == "COMPLETE" and r.entries[-1].row_count == 2
    assert out[0] == {"source": "certificate", "county": "Leon", "host": "leontaxcollector.net", "case_no": "2024-101",
                      "certificate_no": "2024-101", "url_auction": leon.PAGE_URL, "tax_year": "2023",
                      "issued_date": "2024-06-01", "bid": 321.45, "interest_rate": 18.0, "parcel": "1100000000000",
                      "legal_desc": "SYNTHETIC LEGAL TEXT", "list_as_of": "2026-10-01"}
    assert out[1]["case_no"] == "2024-102-2" and out[1]["parcel"] == "2129A0010"
    blob = json.dumps(out)
    for secret in (SECRET_OWNER, "SYNTHETIC MAILING", "NOWHERE", "SYNTHETIC COUNTY HOLDER", "50000", "40000"):
        assert secret not in blob


def test_le02_header_with_no_rows_is_empty(tmp_path):
    r = _rec(tmp_path)
    assert leon.run(_zip([]), recorder=r) == []
    assert r.entries[-1].status == "EMPTY" and r.entries[-1].empty_signal == "empty_table"


def test_le03_unusable_rows_are_incomplete_and_duplicates_dropped(tmp_path):
    r = _rec(tmp_path)
    bad = _leon_row()
    bad[1] = None
    leon.run(_zip([bad]), recorder=r)
    assert r.entries[-1].status == "INCOMPLETE"
    out = leon.run(_zip([_leon_row(), _leon_row()]), recorder=r)
    assert len(out) == 1


@pytest.mark.parametrize("blob", [
    b"not a zip",
    "header",
    "two",
    "csv",
])
def test_le04_format_changes_fail(tmp_path, blob):
    if blob == "header":
        blob = _zip([_leon_row()], header=["a", "b", "c"])
    elif blob == "two":
        blob = _zip([_leon_row()], extra="second.xlsx")
    elif blob == "csv":
        blob = _zip([_leon_row()], name="list.csv")
    r = _rec(tmp_path)
    assert leon.run(blob, recorder=r) == []
    assert r.entries[-1].status == "FAILED" and r.entries[-1].error_category == "PARSE_FORMAT_CHANGE"


def test_le05_zip_link_is_discovered_on_the_page_never_constructed():
    html = ('<a href="/Portals/69/userFiles/CertFiles/OpenCertificates20261001.zip">x</a>'
            '<a href="/Portals/69/userFiles/CertFiles/OpenCountyCertificates20261001.zip">y</a>')
    url, as_of = leon.discover_zip_url(html)
    assert url == "https://www.leontaxcollector.net/Portals/69/userFiles/CertFiles/OpenCountyCertificates20261001.zip"
    assert as_of == "2026-10-01"
    with pytest.raises(ls.CategorizedError):
        leon.discover_zip_url('<a href="/AllCertificates20261001.zip">z</a>')


def test_le06_fixture_main_writes_its_own_status_file(tmp_path, monkeypatch):
    monkeypatch.setattr(leon, "OUT_DIR", tmp_path)
    monkeypatch.setattr(leon, "OUT_JSON", tmp_path / "harvest_certificates_leon.json")
    monkeypatch.setattr(leon, "STATUS_PATH", tmp_path / "harvest_certificates_leon_status.json")
    z = tmp_path / "OpenCountyCertificates20261001.zip"
    z.write_bytes(_zip([_leon_row()]))
    assert leon.main(["--fixture", str(z)]) == 0
    status = json.loads((tmp_path / "harvest_certificates_leon_status.json").read_text())
    assert [(e["county"], e["status"], e["source_id"], e["list_as_of"]) for e in status] == [
        ("Leon", "COMPLETE", "fl_leon_tc_certificates", "2026-10-01")]
    assert len(json.loads((tmp_path / "harvest_certificates_leon.json").read_text())) == 1


# ------------------------------------------------------------- gates

@pytest.mark.parametrize("sid,dataset", [("fl_laft_charlotte", "lands_available"),
                                         ("fl_leon_tc_certificates", "county_held_certificates")])
def test_g01_interim_fetch_parse_store_only_never_documented_never_display(sid, dataset):
    p = PERM.Permissions.from_file()
    for op in ("fetch", "parse", "store"):
        d = p.authorize(sid, op, state="FL", dataset=dataset, today=DAY)
        assert d.allowed and d.basis == "INTERIM" and not d.documented, (sid, op, d.reason_code)
    for op in ("display", "redistribute", "fetch_via_proxy"):
        assert not p.authorize(sid, op, state="FL", dataset=dataset, today=DAY).allowed
    assert not p.authorize(sid, "fetch", state="FL", dataset=dataset, today=date(2027, 4, 13)).allowed
    with open(REPO / "data/source_permissions.csv", newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["source_id"] == sid]
    assert len(rows) == 3
    for r in rows:
        assert (r["status"], r["evidence_type"], r["effective_on"], r["expires_on"], r["conditions"]) == (
            "OWNER_PERMISSION_REQUIRED", "INTERNAL_RISK_ACCEPTANCE", "2026-10-25", "2027-04-12", "excluded_from_paid_tier")
        assert r["reason"].endswith("not sold until legal review.")


def test_g02_live_reads_refuse_before_any_request_without_permission(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a request was made")

    monkeypatch.setattr(ch.requests, "Session", boom)
    monkeypatch.setattr(leon.requests, "Session", boom)
    monkeypatch.setattr(ls, "permission_gate", lambda *a, **k: ls.PERMISSION_DENIED_EXIT)
    assert ch.main([]) == ls.PERMISSION_DENIED_EXIT
    assert leon.main([]) == ls.PERMISSION_DENIED_EXIT


def test_g03_registry_rows_are_candidates_never_runnable():
    rows = csr.load_registry()
    want = {("Charlotte", "fl_laft_charlotte"): "MANUAL_REVIEW_REQUIRED",
            ("Leon", "fl_leon_tc_certificates"): "MANUAL_REVIEW_REQUIRED"}
    got = {(r.county, r.source_id): r for r in rows if r.state == "FL" and (r.county, r.source_id) in want}
    assert set(got) == set(want)
    for k, r in got.items():
        assert r.verification_status == want[k] and not r.runnable and not r.harvester
        assert r.publication_status == "UNREVIEWED" and r.last_checked == "2026-10-25"
    lake = [r for r in rows if r.state == "FL" and r.county == "Lake" and "AVAILABLE" in r.ledger_set]
    assert len(lake) == 1 and not lake[0].is_production and lake[0].canonical_url.startswith("https://lake.realtdm.com/")
    with open(REPO / "data/laft_realtdm_counties.csv", newline="", encoding="utf-8") as fh:
        assert "Lake" not in {r["County"] for r in csv.DictReader(fh)}


def test_g04_wired_into_no_workflow_and_no_sync():
    texts = [p.read_text(encoding="utf-8") for p in (REPO / ".github/workflows").glob("*.yml")]
    texts += [p.read_text(encoding="utf-8") for p in (REPO / "scripts").glob("*.ps1")]
    for needle in ("harvest_laft_charlotte", "harvest_leon_certificates", "harvest_certificates_leon"):
        assert not any(needle in t for t in texts), needle


def test_g05_charlotte_terms_match_the_clerk_counties():
    with open(REPO / "data/available_financial_terms.csv", newline="", encoding="utf-8") as fh:
        rows = {(r["source_id"], r["county"]): r for r in csv.DictReader(fh) if r["state"] == "FL"}
    c, leon_laft = rows[("fl_laft_charlotte", "")], rows[("fl_laft_leon", "")]
    assert c["basis"] == leon_laft["basis"] == "OPENING_BID_PLUS_ADDITIONS"
    assert c["additions"] == leon_laft["additions"]
    # Lake (a realTDM tenant if confirmed) is covered by the source-wide realTDM row.
    assert rows[("fl_laft_realtdm", "")]["basis"] == "BASE_PRICE_PLUS_ADDITIONS"
