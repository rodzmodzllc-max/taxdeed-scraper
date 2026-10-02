"""South Carolina AVAILABLE sprint (Georgetown / Spartanburg FLC lists).

Privacy first: the structural capture (scripts/capture_sc_available.py) is
fed a document and pages full of names, addresses and identifiers, and none
of them may reach its output or its digest."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import capture_sc_available as CAP  # noqa: E402

# Synthetic values that must NEVER appear in any output.
SECRETS = ["JOHNATHAN QUIMBY", "MARGARETHE OSTERWALD", "4417 SEAGRASS LANE", "PAWLEYS", "02-0112-019-00-00",
           "6-17-08-012.00", "1,234.56", "QUIMBY", "SEAGRASS", "0112", "019-00-00", "LOT 7 BLOCK C", "843-555-0199",
           "jdoe@example.org"]


class FakePage:
    def __init__(self, lines, tables=None, words=None):
        self.lines, self.tables, self.words = lines, tables or [], words or []

    def extract_text(self):
        return "\n".join(self.lines)

    def extract_tables(self):
        return self.tables

    def extract_words(self):
        return self.words


class FakePdf:
    def __init__(self, pages, title="2026 FLC LIST - UPDATED MAY 2026"):
        self.pages, self.metadata = pages, {"Title": title}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_pdf():
    header = ["Group", "Name", "TMS #", "Description", "Tax Sale Date", "Opening Bid"]
    rows = [["1", "JOHNATHAN QUIMBY", "02-0112-019-00-00", "LOT 7 BLOCK C 4417 SEAGRASS LANE PAWLEYS", "10/07/2024", "$1,234.56"],
            ["2", "MARGARETHE OSTERWALD", "6-17-08-012.00", "SEAGRASS", "10/06/2025", "1,234.56"],
            ["3", "QUIMBY", "", "", "", ""]]
    lines = ["2026 FLC LIST - UPDATED MAY 2026", "REAL ESTATE", " ".join(header)] + [" ".join(r) for r in rows] + \
            ["MOBILE HOMES", "JOHNATHAN QUIMBY 4417 SEAGRASS LANE PAWLEYS", "Page 1 of 2"]
    words = [{"text": w, "x0": 10 * i, "top": 50} for i, w in enumerate(" ".join(header).split())] + \
            [{"text": w, "x0": 5, "top": 80} for w in "JOHNATHAN QUIMBY SEAGRASS".split()]
    return FakePdf([FakePage(lines, tables=[[header] + rows], words=words)])


PAGE = """<html><head><title>Forfeited Land Commission | Georgetown County</title></head><body>
<p>Properties not sold at the tax sale are bid off to the Forfeited Land Commission and may be purchased by sealed bid application.</p>
<p>Contact JOHNATHAN QUIMBY at 843-555-0199 or jdoe@example.org to apply.</p>
<p>The owner may redeem the property during the redemption period of 12 months.</p>
<table><tr><td>JOHNATHAN QUIMBY</td><td>02-0112-019-00-00</td><td>4417 SEAGRASS LANE</td></tr>
<tr><td>The FLC list is available for purchase by sealed bid MARGARETHE OSTERWALD</td></tr></table>
<p>This site is provided as a public record and no warranty is made as to the accuracy of the information.</p>
<a href="/DocumentCenter/View/3019/2026-FLC-LIST">2026 FLC List</a> <a href="/Disclaimer">Disclaimer</a>
</body></html>"""


def _assert_clean(text: str):
    for s in SECRETS:
        assert s.lower() not in text.lower(), f"leaked {s!r}"


def test_structural_capture_never_emits_a_row_name_address_or_identifier(tmp_path):
    src = CAP.SOURCES[0]
    pdf = CAP.analyse_pdf(b"%PDF-1.4 fake", src, opener=lambda b: _fake_pdf())
    page = CAP.html_wording(PAGE, src["program_url"])
    report = {"generated_at": "2026-10-02T00:00:00+00:00", "sources": [
        {"source_id": src["source_id"], "county": src["county"], "program": {"url": src["program_url"], **page},
         "terms_pages": [], "document": {"url": src["document_url"], **pdf}}]}
    path = tmp_path / "s.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    dump, dig = json.dumps(report), CAP.digest(path)
    _assert_clean(dump)
    _assert_clean(dig)
    st = pdf["structure"]
    # ... while the structure the parser needs IS reported.
    assert st["id_tokens"] == 2 and st["id_shapes"] == {"99-9999-999-99-99": 1, "9-99-99-999.99": 1}
    assert "Group Name TMS # Description Tax Sale Date Opening Bid" in st["headings"]
    assert "MOBILE HOMES" in st["headings"] and "REAL ESTATE" in st["headings"]
    assert st["tables"][0]["header"] == ["Group", "Name", "TMS #", "Description", "Tax Sale Date", "Opening Bid"]
    assert st["tables"][0]["id_cells_by_column"] == {2: 2}
    assert pdf["title"] == "2026 FLC LIST - UPDATED MAY 2026"
    assert st["years"] == {"2024": 1, "2025": 1, "2026": 2}
    # County wording: the availability and terms sentences, never the table cells.
    assert any("sealed bid application" in s for s in page["availability_wording"])
    assert any("no warranty" in s for s in page["terms_wording"])
    assert page["phone_numbers_on_page"] == 1          # counted, never printed
    assert not any("02-0112" in l["href"] for l in page["links"])


def test_heading_filter_only_passes_whitelisted_words():
    assert CAP.heading_line("TAX SALE PROPERTIES (REAL ESTATE) AVAILABLE FOR ASSIGNMENT")
    assert CAP.heading_line("2026 FLC LIST - UPDATED MAY 2026")
    for bad in ("JOHNATHAN QUIMBY", "4417 SEAGRASS LANE", "LOT 7 BLOCK C", "Page 1 of 2", "02-0112-019-00-00"):
        assert not CAP.heading_line(bad)


def test_pdf_title_outside_the_whitelist_is_not_printed():
    out = CAP.analyse_pdf(b"%PDF-1.4", CAP.SOURCES[0], opener=lambda b: FakePdf([], title="JOHNATHAN QUIMBY list"))
    assert out["title"] == "(not printed)"


def test_sc_available_scope_is_read_only_and_runs_only_the_structural_capture():
    wf = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
    job = wf[wf.index("\n  evidence:"):]
    job = job[:job.index("\n  enrich:")]
    assert "SUPABASE" not in job and "secrets." not in job       # no database credential reaches the job
    block = job[job.index('if [ "$SCOPE" = "sc_available" ]'):]
    block = block[:block.index("fi\n")]
    assert "python3 scripts/capture_sc_available.py\n" in block and "exit 0" in block
    assert any("sc_available" in m for m in re.findall(r"options: \[(.*?)\]", wf))
    # The capture keeps the PDFs in memory and writes only its structural JSON.
    src = (ROOT / "scripts/capture_sc_available.py").read_text(encoding="utf-8")
    assert "write_bytes" not in src and src.count(".write_text(") == 1


# ---- the SC FLC parser (harvesters/otc/adapters/sc_flc.py) -------------------
# Sanitized fixtures built from the STRUCTURE the live read measured (run
# 37033274319): Georgetown = 8-column tables headed Group | Name | TMS # |
# Description | Tax Sale Date | (blank) | Opening Bid | (blank) under MOBILE
# HOMES (page 1 + continuation on page 2) and LAND (page 2); Spartanburg = one
# 5-column table under "2025 TAX SALE PROPERTIES (REAL ESTATE) AVAILABLE FOR
# ASSIGNMENT". Every value below is invented; no real row is committed.
from datetime import datetime, timezone  # noqa: E402

from harvesters.ledgers import SOURCE_LEDGERS  # noqa: E402,F401
from harvesters.otc.adapters import sc_flc as FLC  # noqa: E402

NOW = datetime(2026, 10, 2, 16, 27, tzinfo=timezone.utc)
GT_HEADER = ["Group", "Name", "TMS #", "Description", "Tax Sale Date", "", "Opening Bid", ""]


class FakeTable:
    def __init__(self, top, rows):
        self.bbox, self.rows = (30, top, 760, top + 200), rows

    def extract(self):
        return self.rows


class FlcPage:
    def __init__(self, headings, tables):
        self.headings, self.tables = headings, tables

    def extract_text_lines(self):
        return [{"text": t, "top": y} for t, y in self.headings]

    def find_tables(self):
        return self.tables


def _gt_row(tms, sale="10/07/2024", bid="$500.00", name="SAMPLE OWNER"):
    return ["1", name, tms, "SAMPLE DESCRIPTION", sale, "", bid, ""]


def georgetown_pages(land_rows):
    mobile = [_gt_row(f"0{i}-0000-00{i}-00-00.00{i}") for i in range(1, 4)]
    return [
        FlcPage([("Georgetown County, South Carolina", 38), ("Forfeited Land Commission", 56), ("MOBILE HOMES", 95)],
                [FakeTable(120, [GT_HEADER] + mobile)]),
        FlcPage([("Georgetown County, South Carolina", 38), ("Forfeited Land Commission", 56), ("LAND", 455)],
                [FakeTable(70, [_gt_row("09-0000-009-00-00.009")]), FakeTable(480, [GT_HEADER] + land_rows)]),
        FlcPage([("Forfeited Land Commission", 56)], []),
    ]


def test_georgetown_land_rows_past_redemption_are_available_and_mobile_homes_are_not():
    land = [_gt_row("11-1111-111-11-11", sale="10/07/2024"),        # past the 12-month redemption: AVAILABLE
            _gt_row("12-1111-111-11-11", sale="10/06/2025"),        # still in redemption: not qualified
            _gt_row("13-1111-111-11-11", sale="sometime"),          # unreadable date: fail closed
            _gt_row("1-11-11-111.11"),                              # malformed TMS
            _gt_row(""),                                            # no identifier
            _gt_row("11-1111-111-11-11", sale="10/07/2024")]        # duplicate of the first
    res = FLC.parse_pages(FLC.GEORGETOWN, georgetown_pages(land), retrieved_at=NOW)
    s = FLC.summary(res)
    assert s["sections"] == {"land": 6, "mobile_home": 4}
    assert s["rejected"] == {"duplicate_identifier": 1, "in_redemption_period": 1, "malformed_identifier": 1,
                             "missing_identifier": 1, "personal_property_section": 4, "sale_date_unreadable": 1}
    assert s["valid_identifiers"] == 8 and s["available_records"] == 1
    assert s["outcome"] == "FAILED"          # a malformed identifier means the format may have changed: never COMPLETE
    rec = res.records[0]
    assert (rec.state, rec.county, rec.case_no, rec.parcel) == ("SC", "Georgetown", "11-1111-111-11-11", "11-1111-111-11-11")
    assert rec.record_source == "laft" and rec.inventory_type.value == "POST_SALE"
    assert rec.amount == 500.0 and rec.amount_kind.value == "OPENING_BID"
    assert rec.owner_name is None                       # the Name column is never read into a record
    assert rec.list_url == FLC.GEORGETOWN.program_url and rec.document_url == FLC.GEORGETOWN.document_url
    assert rec.purchase_url.endswith("FLC-Procedures-and-Bid-Apps-PDF") and rec.purchase_url_kind.value == "application_form"
    assert rec.retrieved_at == NOW and rec.list_as_of is None   # "updated May 2026" is a month, never invented as a date
    assert rec.provenance["list_as_of_text"] == "updated May 2026" and rec.provenance["evidence_run"] == "37033274319"
    acq = rec.provenance["acquisition"]
    assert acq["payment"] == "Not published" and acq["online_purchase"] == "No online purchase link on file"
    assert rec.validate() == []


def test_georgetown_clean_list_is_complete_and_a_list_with_no_qualifying_land_is_empty():
    ok = FLC.parse_pages(FLC.GEORGETOWN, georgetown_pages([_gt_row("11-1111-111-11-11")]), retrieved_at=NOW)
    assert FLC.outcome(ok) == "COMPLETE" and len(ok.records) == 1
    none = FLC.parse_pages(FLC.GEORGETOWN, georgetown_pages([_gt_row("11-1111-111-11-11", sale="10/06/2025")]),
                           retrieved_at=NOW)
    assert FLC.outcome(none) == "EMPTY" and none.records == []
    # No header found anywhere (format change) -> FAILED, never EMPTY.
    broken = FLC.parse_pages(FLC.GEORGETOWN, [FlcPage([("LAND", 10)], [FakeTable(20, [["a", "b"], ["c", "d"]])])],
                             retrieved_at=NOW)
    assert FLC.outcome(broken) == "FAILED"
    assert FLC.parse_document(FLC.GEORGETOWN.source_id, b"<html>", retrieved_at=NOW).error == "NOT_A_PDF"


def test_spartanburg_rows_are_counted_but_never_available():
    header = ["ITEM #", "DESCRIPTION\nbest known property address", "DEFAULTING TAXPAYER\nOwner Name", "MAP NUMBER",
              "TOTAL TAX DUE\nBid Amount Needed"]
    rows = [[str(i), "SAMPLE ADDRESS", "SAMPLE OWNER", f"{i}-11-11-111.11", "$1,000.00"] for i in range(1, 5)]
    rows.append(["5", "SAMPLE ADDRESS", "SAMPLE OWNER", "1-1-11-111", "$1,000.00"])    # malformed MAP NUMBER
    page = FlcPage([("2025 TAX SALE PROPERTIES (REAL ESTATE) AVAILABLE FOR ASSIGNMENT", 58)], [FakeTable(260, [header] + rows)])
    res = FLC.parse_pages(FLC.SPARTANBURG, [page], retrieved_at=NOW)
    s = FLC.summary(res)
    assert s["valid_identifiers"] == 4 and s["rejected"] == {"malformed_identifier": 1, "redemption_assignment": 4}
    assert s["available_records"] == 0 and s["amounts_published"] == 4
    assert FLC.normalize_identifier(" 1-11-11-111.11 ") == "1-11-11-111.11"


def test_identifier_normalization_is_whitespace_only():
    assert FLC.normalize_identifier("02-0112- 019-00-00") == "02-0112-019-00-00"
    assert FLC.valid_identifier(FLC.GEORGETOWN, "02-0112-019-00-00")
    assert FLC.valid_identifier(FLC.GEORGETOWN, "02-0112-019-00-00.001")
    assert not FLC.valid_identifier(FLC.GEORGETOWN, "0201120190000")      # no re-punctuation is attempted
    assert not FLC.valid_identifier(FLC.SPARTANBURG, "02-0112-019-00-00")


def test_redemption_rule():
    from datetime import date
    assert FLC.redemption_over(date(2024, 10, 7), date(2026, 10, 2))
    assert not FLC.redemption_over(date(2025, 10, 6), date(2026, 10, 2))
    assert not FLC.redemption_over(date(2025, 10, 6), date(2026, 10, 6))   # the last day of the period is still inside
    assert FLC.parse_sale_date("2016") == date(2016, 12, 31)                 # a year alone: its latest day


def test_zero_existing_sc_matches_keeps_observations_unmatched_and_never_uses_owner_or_address():
    res = FLC.parse_pages(FLC.GEORGETOWN, georgetown_pages([_gt_row("11-1111-111-11-11")]), retrieved_at=NOW)
    york = [{"state": "SC", "county": "York", "parcel": "11-1111-111-11-11", "address": "SAMPLE ADDRESS"}]
    matched, unmatched = FLC.match_existing(res.records, york)          # same identifier, other county: no match
    assert matched == [] and len(unmatched) == 1
    same_owner_and_address = [{"state": "SC", "county": "Georgetown", "parcel": "99-9999-999-99-99",
                               "owner_name": "SAMPLE OWNER", "address": "SAMPLE DESCRIPTION"}]
    assert FLC.match_existing(res.records, same_owner_and_address)[0] == []
    exact = [{"state": "SC", "county": "Georgetown", "parcel": " 11-1111-111-11-11 "}]
    assert len(FLC.match_existing(res.records, exact)[0]) == 1
    assert FLC.match_existing(res.records, [])[1] == res.records        # unmatched records are kept, not fabricated


def test_harvest_refuses_before_any_request_unless_approved():
    calls = []
    for pub in ("REVIEW_REQUIRED", "UNREVIEWED", "HARD_BLOCKED"):
        try:
            FLC.harvest(FLC.GEORGETOWN.source_id, lambda u: calls.append(u), retrieved_at=NOW, publication=pub)
        except PermissionError:
            pass
    assert calls == []
    try:
        FLC.harvest(FLC.SPARTANBURG.source_id, lambda u: calls.append(u), retrieved_at=NOW, publication="APPROVED")
    except PermissionError:
        pass
    assert calls == []    # Spartanburg is not AVAILABLE inventory at all


def test_ledger_isolation():
    # The FLC adapter only ever emits AVAILABLE (laft) records ...
    src = (ROOT / "harvesters/otc/adapters/sc_flc.py").read_text(encoding="utf-8")
    assert 'record_source="laft"' in src
    assert not re.search(r'record_source\s*=\s*"(auction|certificate)"', src)
    res = FLC.parse_pages(FLC.GEORGETOWN, georgetown_pages([_gt_row("11-1111-111-11-11")]), retrieved_at=NOW)
    assert {r.record_source for r in res.records} == {"laft"}
    # ... and the existing SC auction source never emits AVAILABLE ones.
    from harvesters.otc.adapters import expansion as EX
    assert EX.SC_YORK.record_source == "auction"
    from harvesters.sources import available_coverage as AC
    assert all("AVAILABLE" in r.ledger_set for r in AC.production_available_sources("SC"))
    assert AC.production_available_sources("SC") == []    # no SC AVAILABLE source is in production
