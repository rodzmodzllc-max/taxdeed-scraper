"""Texas sources batch (2026-10-25): Bexar County's struck-off property list
(County PDF, gated reader) and the Dallas County finding (the County's page
links only a vendor map; candidate only). Every fixture here is SYNTHETIC -
invented values in the shape of the live list, never a row from it.
docs/sources-batch-2026-10-25-texas.md.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import harvest_tx_bexar_struckoff as bx  # noqa: E402
import laft_status as ls  # noqa: E402
from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import permissions as PERM  # noqa: E402

DAY = date(2026, 10, 25)
SID, DATASET = "tx_bexar_struckoff", "struck_off_properties"


# ------------------------------------------------------------- fixtures

def text_pdf(pages: list[list[str]]) -> bytes:
    """A minimal, valid multi-page text PDF (Helvetica), built by hand."""
    objs = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids, pages_id = [], len(pages) * 2 + 2
    for lines in pages:
        stream = b"BT /F1 10 Tf 40 760 Td 12 TL " + b" ".join(
            b"(" + ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").encode("latin-1") + b") '" for ln in lines) + b" ET"
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
                            b"/Resources << /Font << /F1 %d 0 R >> >> >>" % (pages_id, content, font)))
    kids = b" ".join(b"%d 0 R" % i for i in page_ids)
    assert add(b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % len(page_ids)) == pages_id
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    out, offsets = io.BytesIO(), []
    out.write(b"%PDF-1.4\n")
    for i, body in enumerate(objs, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, catalog, xref))
    return out.getvalue()


HEAD = ["Page 1", "BEXAR COUNTY RESALE PROPERTIES", "List Updated January 2, 2026",
        "Struck off amt w/o", "Property Address Suit No. Account No. interim tax / fees"]
FOOT = ["THE DOLLAR AMOUNTS LISTED ARE NOT GUARANTEED TO BE ACCURATE"]


def row(n: int, *, suit=None, account=None, amount="$1,234.56", address=None) -> str:
    return " ".join([address or f"{100 + n} SYNTHETIC ST", suit or f"00-ZZ9-{n:05d}",
                     account or f"00000-000-{n:04d}", amount])


MULTI = ["Page 2", "BEXAR COUNTY RESALE PROPERTIES", "MULTIPLE ACCOUNTS", "List Updated January 2, 2026",
         "Property Address Suit No. Account No. Struck Off Amount", "00000-000-0901", "00000-000-0902",
         "SYNTHETIC ST 00000-000-0903", "00-ZZ9-00900 $9,999.99"]


# ------------------------------------------------------------- parsing

def test_bx01_complete_maps_account_cause_address_amount(tmp_path):
    r = ls.StatusRecorder(SID, path=tmp_path / "s.json", state="TX", source_class="GOVERNMENT_DIRECT", source_id=SID)
    out = bx.run(text_pdf([HEAD + [row(1), row(2, amount="$12,000.00")] + FOOT]), recorder=r)
    e = r.entries[-1]
    assert (e.status, e.row_count, e.state, e.list_as_of) == ("COMPLETE", 2, "TX", "2026-01-02")
    assert out[0] == {"state": "TX", "county": "Bexar", "source": "laft", "harvester_source": SID,
                      "inventory_type": "STRUCK_OFF_HELD_IN_TRUST", "case_no": "00000-000-0001",
                      "parcel": "00-ZZ9-00001", "address": "101 SYNTHETIC ST", "purchase_amount": 1234.56,
                      "purchase_amount_kind": "PUBLISHED_AMOUNT_KIND_UNSPECIFIED", "url_auction": bx.PAGE_URL,
                      "list_as_of": "2026-01-02"}
    assert out[1]["purchase_amount"] == 12000.0
    # The CAD account is case_no; the cause number is parcel (tx_lgbs / tx_realauction convention).
    assert all(o["case_no"].count("-") == 2 and o["parcel"].startswith("00-ZZ9-") for o in out)


@pytest.mark.parametrize("bad", [
    row(3, account="00000-00-0003"),        # a digit lost to OCR
    row(3, account="A0000-000-0003"),       # a letter for a digit
    row(3, suit="00-ZZ9-AB003"),            # a garbled cause number
    row(3, amount="$1,23456"),              # no cents
])
def test_bx02_garbled_lines_are_refused_and_counted_never_repaired(tmp_path, bad):
    r = ls.StatusRecorder(SID, path=tmp_path / "s.json", state="TX")
    out = bx.run(text_pdf([HEAD + [row(1), bad] + FOOT]), recorder=r)
    e = r.entries[-1]
    assert e.status == "INCOMPLETE" and e.error_category == "PARSE_FORMAT_CHANGE" and e.row_count == 1
    assert [o["case_no"] for o in out] == ["00000-000-0001"]


def test_bx03_multiple_account_section_is_counted_and_left_unread(tmp_path):
    r = ls.StatusRecorder(SID, path=tmp_path / "s.json", state="TX")
    pages = bx.pdf_lines(text_pdf([HEAD + [row(1)] + FOOT, MULTI + FOOT]))
    records, outcome = bx.parse_pages(pages)
    assert [x["case_no"] for x in records] == ["00000-000-0001"]
    assert outcome["multi_account_section"] and outcome["multi_account_accounts"] == 3
    status, cat, reason = bx.classify(records, outcome)
    assert (status, cat) == ("INCOMPLETE", "PARSE_FORMAT_CHANGE") and "multiple-account" in reason
    assert "9999.99" not in json.dumps(records)


def test_bx04_a_zero_is_never_empty(tmp_path):
    r = ls.StatusRecorder(SID, path=tmp_path / "s.json", state="TX")
    assert bx.run(text_pdf([HEAD + FOOT]), recorder=r) == []
    e = r.entries[-1]
    assert e.status == "INCOMPLETE" and e.error_category == "UNCONFIRMED_EMPTY"


def test_bx05_duplicate_accounts_keep_the_first(tmp_path):
    records, outcome = bx.parse_pages(bx.pdf_lines(text_pdf([HEAD + [row(1), row(1, amount="$5.00")] + FOOT])))
    assert len(records) == 1 and records[0]["purchase_amount"] == 1234.56 and outcome["duplicate"] == 1


@pytest.mark.parametrize("blob", [b"<html>not a pdf</html>", None])
def test_bx06_format_changes_fail(tmp_path, blob):
    r = ls.StatusRecorder(SID, path=tmp_path / "s.json", state="TX")
    pdf = blob if blob is not None else text_pdf([["SOME OTHER DOCUMENT", row(1)]])
    assert bx.run(pdf, recorder=r) == []
    assert r.entries[-1].status == "FAILED"


def test_bx07_link_is_discovered_by_its_text_never_constructed():
    page = ('<p>Other <a href="/DocumentCenter/View/1/General">General Information</a> '
            '<a href="/DocumentCenter/View/2/Synthetic-List">Current Struck-Off <b>Property</b> List</a></p>')
    assert bx.discover_pdf_url(page) == "https://www.bexar.org/DocumentCenter/View/2/Synthetic-List"
    with pytest.raises(ls.CategorizedError):
        bx.discover_pdf_url("<p>no list here</p>")
    with pytest.raises(ls.CategorizedError):
        bx.discover_pdf_url('<a href="https://example.com/x.pdf">Current Struck-Off Property List</a>')


def test_bx08_fixture_main_writes_its_own_tx_status_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bx, "OUT_DIR", tmp_path)
    monkeypatch.setattr(bx, "OUT_JSON", tmp_path / "out.json")
    monkeypatch.setattr(bx, "STATUS_PATH", tmp_path / "status.json")
    f = tmp_path / "list.pdf"
    f.write_bytes(text_pdf([HEAD + [row(1), row(2)] + FOOT]))
    assert bx.main(["--fixture", str(f)]) == 0
    status = json.loads((tmp_path / "status.json").read_text())
    assert [(e["county"], e["state"], e["status"], e["source_id"]) for e in status] == [("Bexar", "TX", "COMPLETE", SID)]
    assert len(json.loads((tmp_path / "out.json").read_text())) == 2
    printed = capsys.readouterr().out
    for secret in ("00000-000-0001", "00-ZZ9-00001", "SYNTHETIC ST", "1,234.56", "1234.56"):
        assert secret not in printed  # counts only in the log


# ------------------------------------------------------------- gates

def test_g01_interim_fetch_parse_store_only_never_documented_never_display():
    p = PERM.Permissions.from_file()
    for op in ("fetch", "parse", "store"):
        d = p.authorize(SID, op, state="TX", county="Bexar", dataset=DATASET, today=DAY)
        assert d.allowed and d.basis == "INTERIM" and not d.documented, (op, d.reason_code)
    for op in ("display", "redistribute", "fetch_via_proxy", "enrich"):
        assert not p.authorize(SID, op, state="TX", county="Bexar", dataset=DATASET, today=DAY).allowed
    assert not p.authorize(SID, "fetch", state="TX", county="Bexar", dataset=DATASET, today=date(2027, 4, 13)).allowed
    with open(REPO / "data/source_permissions.csv", newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["source_id"] == SID]
    assert sorted(r["operation"] for r in rows) == ["fetch", "parse", "store"]
    for r in rows:
        assert (r["status"], r["evidence_type"], r["effective_on"], r["expires_on"], r["conditions"], r["jurisdiction"]) == (
            "OWNER_PERMISSION_REQUIRED", "INTERNAL_RISK_ACCEPTANCE", "2026-10-25", "2027-04-12", "excluded_from_paid_tier", "TX")
        assert r["reason"].endswith("Not sold until legal review.")


def test_g02_live_read_refuses_before_any_request_without_permission(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("a request was made")

    monkeypatch.setattr(bx, "fetch_pdf", boom)
    monkeypatch.setattr(ls, "permission_gate", lambda *a, **k: ls.PERMISSION_DENIED_EXIT)
    assert bx.main([]) == ls.PERMISSION_DENIED_EXIT


def test_g03_registry_rows_are_candidates_never_runnable():
    rows = [r for r in csr.load_registry() if r.state == "TX" and r.county in ("Bexar", "Dallas")
            and "AVAILABLE" in r.ledger_set and r.source_authority == "GOVERNMENT_DIRECT"]
    by = {r.county: r for r in rows}
    assert set(by) == {"Bexar", "Dallas"} and len(rows) == 2
    b, d = by["Bexar"], by["Dallas"]
    assert b.source_id == SID and b.verification_status == "MANUAL_REVIEW_REQUIRED" and not b.harvester
    assert b.canonical_url.startswith("https://www.bexar.org/") and b.document_url.startswith("https://www.bexar.org/")
    assert d.source_id == "" and d.verification_status == "HISTORICAL_ONLY"
    assert "lgbs.com" not in (d.canonical_url + d.document_url)
    for r in (b, d):
        assert not r.runnable and not r.is_production and r.publication_status == "UNREVIEWED"
        assert r.last_checked == "2026-10-25"


def test_g04_wired_into_no_workflow_and_no_sync():
    texts = [p.read_text(encoding="utf-8") for p in (REPO / ".github/workflows").glob("*.yml")]
    texts += [p.read_text(encoding="utf-8") for p in (REPO / "scripts").glob("*.ps1")]
    texts += [p.read_text(encoding="utf-8") for p in (REPO / "scripts").glob("sync*.py")]
    for needle in ("harvest_tx_bexar_struckoff", "tx_bexar_struckoff", "harvest_tx_struckoff_status"):
        assert not any(needle in t for t in texts), needle


def test_g05_terms_and_dallas_candidate():
    with open(REPO / "data/available_financial_terms.csv", newline="", encoding="utf-8") as fh:
        t = [r for r in csv.DictReader(fh) if r["source_id"] == SID]
    assert len(t) == 1 and t[0]["basis"] == "BASE_PRICE_PLUS_ADDITIONS" and t[0]["additions"] == "recording_fees"
    with open(REPO / "data/available_source_candidates.csv", newline="", encoding="utf-8") as fh:
        c = {r["source_id"]: r for r in csv.DictReader(fh)}
    dal = c["tx_dallas_struckoff"]
    assert (dal["state"], dal["county"]) == ("TX", "Dallas") and dal["url"].startswith("https://www.dallascounty.org/")
    # No vendor host is ever recorded as a candidate source.
    for r in c.values():
        assert not any(v in r["url"] for v in ("lgbs.com", "pbfcm", "mvbalaw", "ctsa", "govease"))
