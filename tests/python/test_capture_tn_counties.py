"""Privacy and wiring of the Davidson / Hamilton structure capture: synthetic
PII never reaches its output."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import capture_tn_counties as M  # noqa: E402

SECRETS = ("JANE Q PUBLIC", "1234 ELM", "093-45.00", "4500.00", "BRAINERD")


def test_table_headers_pass_whitelisted_headers_and_withhold_rows():
    rows = [["Map Parcel", "Owner", "Property Address", "Minimum Bid"],
            ["093-45.00", "JANE Q PUBLIC", "1234 ELM ST BRAINERD", "4500.00"],
            ["093-46.00", "JOHN DOE", "99 OAK", "1.00"]]
    out = json.dumps(M.table_headers(rows))
    assert "Map Parcel" in out and "Minimum Bid" in out and "Property Address" in out
    for s in SECRETS:
        assert s not in out


def test_html_tables_print_only_header_cells():
    html = ("<table id='t'><tr><th>Parcel ID</th><th>Sale Date</th></tr>"
            "<tr><td>093-45.00</td><td>JANE Q PUBLIC</td></tr></table>")
    out = json.dumps(M.html_tables(html))
    assert "Parcel ID" in out and "Sale Date" in out and '"rows": 2' in out
    for s in SECRETS:
        assert s not in out


def test_digest_of_a_pdf_entry_never_prints_row_text():
    page = {"kind": "rpo_sold_list", "county": "hamilton", "url": "https://www.hamiltontn.gov/x.pdf", "status": 200,
            "content_type": "application/pdf", "pdf_pages": 1,
            "pdf": M.C.pdf_structure(["SOLD PROPERTY LIST", "093-45.00 JANE Q PUBLIC 1234 ELM ST $4,500.00"]),
            "pdf_tables": [M.table_headers([["Map Parcel", "Sold Price"], ["093-45.00", "4500.00"]])]}
    text = M.digest({"generated_at": "t", "pages": [page]})
    assert "Map Parcel" in text and "SOLD PROPERTY LIST" in text
    for s in SECRETS + ("4,500",):
        assert s not in text


def test_workflow_scope_runs_the_probe():
    wf = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text()
    block = wf[wf.index('if [ "$SCOPE" = "tn_davidson_hamilton" ]'):]
    block = block[:block.index("\n          fi\n")]
    assert "python3 scripts/capture_tn_counties.py" in block and "exit 0" in block
