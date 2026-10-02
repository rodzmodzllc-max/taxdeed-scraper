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
