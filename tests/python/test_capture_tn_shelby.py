"""scripts/capture_tn_shelby.py prints structure only: a sale book or a page
full of owner names, addresses, parcel numbers and amounts produces headings,
counts and shapes - never one of those values."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import capture_tn_shelby as C  # noqa: E402

SECRETS = ["JOHNSON MARY", "4471 ELVIS PRESLEY BLVD", "075123 00045", "$1,134.27", "SMITH HOLDINGS LLC",
           "LOT 12 BLK C SUBDIVISION", "Jane Q Purchaser", "38116"]

BOOK = [
    "SHELBY COUNTY TAX SALE 2202 SALE BOOK",
    "PARCEL NUMBER OWNER NAME PROPERTY ADDRESS HIGH BID PURCHASER",
    "075123 00045 JOHNSON MARY 4471 ELVIS PRESLEY BLVD 38116 $1,134.27 Jane Q Purchaser",
    "D0256 00003130 SMITH HOLDINGS LLC LOT 12 BLK C SUBDIVISION $1,390.00 TRUSTEE",
    "REDEMPTION PERIOD 90 DAYS",
    "April 21 2026",
]
PAGE = """<html><head><title>Shelby County Land Bank</title><script src="/js/map.js"></script></head><body>
<h1>Properties For Sale</h1><h2>4471 ELVIS PRESLEY BLVD JOHNSON MARY</h2>
<a href="https://landbank.shelbycountytn.gov/property/075123%2000045">4471 ELVIS PRESLEY BLVD</a>
<a href="https://www.shelbycountytn.gov/DocumentCenter/View/45087/TX-2024TS2202SaleBook">Sale Book</a>
<a href="https://evil.example.com/x">Click here</a>
<table><tr><td>SMITH HOLDINGS LLC</td><td>$1,134.27</td></tr></table>
<script>var u="https://services.arcgis.com/abc/arcgis/rest/services/LandBank/FeatureServer/0";</script>
</body></html>"""


def leaked(text: str) -> list[str]:
    return [s for s in SECRETS if s in text or s.replace(" ", "") in text.replace(" ", "")]


def test_pdf_structure_prints_headings_and_shapes_only():
    d = C.pdf_structure(BOOK)
    out = json.dumps(d)
    assert leaked(out) == [], leaked(out)
    assert "PARCEL NUMBER OWNER NAME PROPERTY ADDRESS HIGH BID PURCHASER" in d["safe_heading_lines"]
    assert "REDEMPTION PERIOD 99 DAYS" in d["safe_heading_lines"]
    assert d["lines_with_amount"] == 2 and d["keyword_counts"]["redemption"] == 1
    assert ["999999", 1] in [list(x) for x in d["first_token_shapes"]]
    assert d["years_seen"] == ["2026"]


def test_html_structure_withholds_values_and_keeps_endpoints():
    h = C.html_structure(PAGE, "https://landbank.shelbycountytn.gov/")
    out = json.dumps(h)
    assert leaked(out) == [], leaked(out)
    assert h["title"] == "Shelby County Land Bank"
    assert "Properties For Sale" in h["headings"] and "[text withheld]" in h["headings"]
    texts = {l["text"] for l in h["links"]}
    assert "[text withheld]" in texts and "Sale Book" in texts
    assert all("evil.example.com" not in l["href"] for l in h["links"])  # non-official hosts dropped
    assert "https://services.arcgis.com/abc/arcgis/rest/services/LandBank/FeatureServer/0" in h["endpoints"]
    assert h["script_srcs"] == ["https://landbank.shelbycountytn.gov/js/map.js"]


def test_digest_never_prints_values():
    report = {"generated_at": "x", "pages": [{"kind": "landbank_home", "url": "u", "status": 200,
              "html": C.html_structure(PAGE, "https://landbank.shelbycountytn.gov/")}],
              "sale_books": [{"kind": "sale_book", "url": "b", "status": 200, "pdf_pages": 3, "pdf": C.pdf_structure(BOOK)}],
              "scripts": [], "layers": []}
    assert leaked(C.digest(report)) == []


def test_wired_as_a_read_only_evidence_scope():
    wf = (REPO / ".github" / "workflows" / "harvest-and-sync.yml").read_text(encoding="utf-8")
    block = wf[wf.index('if [ "$SCOPE" = "tn_shelby" ]'):]
    block = block[:block.index("\n          fi\n")]
    assert "python3 scripts/capture_tn_shelby.py" in block and "SUPABASE" not in block
    assert "tn_shelby" in wf[wf.index("evidence_scope:"):wf.index("concurrency:")]


def test_json_shape_never_prints_values():
    import capture_tn_shelby as m
    data = {"props": {"pageProps": {"parcels": [{"parcelId": "G0219 00412", "owner": "JANE Q PUBLIC",
                                                 "address": "1234 ELM ST", "price": 4500.0}]},
                      "byId": {f"0{i}2034 0001{i}": {"x": 1} for i in range(8)}}}
    text = json.dumps(m.json_shape(data))
    for secret in ("G0219", "JANE", "ELM", "4500", "02034"):
        assert secret not in text
    assert "parcelId" in text and "len=1" in text and "<object with 8 keys>" in text


def test_data_urls_finds_api_paths_and_drops_noise():
    import capture_tn_shelby as m
    js = 'fetch("/api/properties?status=x");a="https://reactjs.org/docs/error";b="https://services.arcgis.com/x/arcgis/rest/services/LB/FeatureServer/0"'
    paths, hosts = m.data_urls(js)
    assert paths == ["/api/properties"]
    assert hosts == ["https://services.arcgis.com/x/arcgis/rest/services/LB/FeatureServer/0"]


def test_epropertyplus_path_pattern():
    import capture_tn_shelby as m
    js = 'u="/landmgmtpub/remote/public/property/getPublishedProperties";v="remote/public/x/y"'
    assert sorted(m.EPP_PATH.findall(js)) == ["/landmgmtpub/remote/public/property/getPublishedProperties", "remote/public/x/y"]


def test_inventory_summary_prints_vocabulary_never_rows():
    import capture_tn_shelby as m
    rows = [{"parcelNumber": "G0219 00412", "propertyAddress": "1234 ELM ST", "comments": "Call JANE Q PUBLIC 901-555-1212",
             "currentStatus": "Available", "available": "Yes", "city": "MEMPHIS", "askingPrice": 4500.0,
             "latitude": 35.1, "longitude": -90.0, "id": 77}]
    text = json.dumps(m.inventory_summary(rows, 1))
    for secret in ("G0219", "ELM", "JANE", "555", "4500", "77,"):
        assert secret not in text
    assert "Available" in text and "MEMPHIS" in text and "A9999 99999" in text
