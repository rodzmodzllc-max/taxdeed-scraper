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


def test_all_links_include_table_and_external_links_and_skip_govease():
    html = ("<a href='/x.pdf'>Tax Sale List</a><table><tr><td><a href='https://vendor.example/sale'>JANE Q PUBLIC</a></td>"
            "</tr></table><a href='https://www.govease.com/x'>x</a>")
    links = M.all_links(html, "https://chanceryclerkandmaster.nashville.gov/p/")
    hrefs = {l["href"]: l for l in links}
    assert hrefs["https://chanceryclerkandmaster.nashville.gov/x.pdf"]["official"] is True
    assert hrefs["https://vendor.example/sale"]["in_table"] is True and hrefs["https://vendor.example/sale"]["text"] == "[text withheld]"
    assert not any("govease" in h for h in hrefs)


def test_forms_print_field_names_never_values():
    html = ("<form action='/search' method='post'><input name='parcel' value='093-45.00'>"
            "<input name='owner' value='JANE Q PUBLIC'><input type='hidden' name='__VIEWSTATE' value='x'></form>")
    out = json.dumps(M.forms(html, "https://rcchancery.com/delinquent_sales"))
    assert '"parcel"' in out and '"owner"' in out and "__VIEWSTATE" not in out
    for s in SECRETS:
        assert s not in out


def test_page_sets_and_workflow_scope():
    assert set(M.PAGE_SETS) == {"davidson_hamilton", "montgomery_rutherford_knox", "blount_campbell"}
    assert {c for c, _, _ in M.MONTGOMERY_RUTHERFORD_KNOX} == {"montgomery", "rutherford", "knox"}
    wf = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text()
    block = wf[wf.index('if [ "$SCOPE" = "tn_montgomery_rutherford_knox" ]'):]
    block = block[:block.index("\n          fi\n")]
    assert "capture_tn_counties.py --set montgomery_rutherford_knox" in block


def test_blount_campbell_scope():
    assert {c for c, _, _ in M.BLOUNT_CAMPBELL} == {"blount", "campbell"}
    wf = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text()
    block = wf[wf.index('if [ "$SCOPE" = "tn_blount_campbell" ]'):]
    block = block[:block.index("\n          fi\n")]
    assert "capture_tn_counties.py --set blount_campbell" in block


def test_arcgis_app_ids_and_webmap_discovery():
    eps = ["https://blountgis.maps.arcgis.com/apps/webappviewer/index.html?id=47aa62b29af74cc0b2a1d63ac5ec8e4d",
           "https://experience.arcgis.com/experience/35c2ae08d1644d91abef7d281ddac36a/"]
    ids = {m for e in eps for m in M.APP_ID.findall(e)}
    assert ids == {"47aa62b29af74cc0b2a1d63ac5ec8e4d", "35c2ae08d1644d91abef7d281ddac36a"}
    data = {"map": {"itemId": "a" * 32}, "dataSources": {"ds": {"itemId": "b" * 32, "x": [{"webmap": "c" * 32}]}}}
    assert M._webmap_ids(data) == {"a" * 32, "b" * 32, "c" * 32}
