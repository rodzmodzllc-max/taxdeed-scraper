"""The generic AVAILABLE source capture (scripts/capture_available_sources.py)
must never emit a row, a name, an address or an identifier - for HTML tables,
followed list pages and ArcGIS layers alike."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import capture_available_sources as CAP  # noqa: E402

SECRETS = ["JOHNATHAN QUIMBY", "4417 SEAGRASS", "SEAGRASS", "64-017-620-002-00", "21012345.001", "QUIMBY, MARGARETHE",
           "843-555-0199", "jdoe@example.org", "OSTERWALD"]

PAGE = """<html><head><title>Land Bank | Sample County</title></head><body>
<p>The Land Bank Authority sells vacant lots it acquired through tax foreclosure; submit an application to purchase.</p>
<p>Questions: JOHNATHAN QUIMBY 843-555-0199 jdoe@example.org</p>
<table><tr><th>Parcel ID</th><th>Address</th><th>Price</th><th>JOHNATHAN QUIMBY</th></tr>
<tr><td>64-017-620-002-00</td><td>4417 SEAGRASS LANE</td><td>$500</td><td>OSTERWALD</td></tr>
<tr><td>64-017-620-003-00</td><td>4419 SEAGRASS LANE</td><td>$750</td><td></td></tr></table>
<a href="/DocumentCenter/View/1/Available-Lots">Available Lots</a></body></html>"""


class Resp:
    def __init__(self, body, ctype="text/html", status=200):
        self.status_code, self.ok = status, status == 200
        self.headers = {"content-type": ctype}
        self.text = body if isinstance(body, str) else ""
        self.content = body.encode() if isinstance(body, str) else body
        self._json = body if isinstance(body, dict) else None

    def json(self):
        if self._json is None:
            raise ValueError
        return self._json


class Session:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, **kw):
        self.calls.append(url)
        for prefix, resp in self.routes:
            if url.startswith(prefix):
                return resp
        return Resp("", status=404)


def _clean(text):
    for s in SECRETS:
        assert s.lower() not in text.lower(), f"leaked {s!r}"


def test_html_tables_and_followed_pages_emit_structure_only():
    page2 = PAGE.replace("Land Bank | Sample County", "Available Lots")
    s = Session([("https://x.gov/DocumentCenter", Resp(page2)), ("https://x.gov/", Resp(PAGE))])
    out = CAP.capture_html(s, "https://x.gov/land-bank", {"source_id": "t"})
    dump = json.dumps(out)
    _clean(dump)
    t = out["tables"][0]
    assert t["rows"] == 2 and t["header"] == ["Parcel ID", "Address", "Price", "(not printed)"]
    assert t["id_cells_by_column"] == {0: 2} and t["id_shapes"] == {"99-999-999-999-99": 2}
    assert out["followed"] and out["followed"][0]["tables"][0]["rows"] == 2
    assert any("tax foreclosure" in x for x in out["availability_wording"])


def test_arcgis_layer_emits_fields_counts_shapes_and_safe_categories_only():
    layer = "https://services.arcgis.com/x/FeatureServer/0"
    feats = [{"attributes": {"PARCEL_ID": "21012345.001", "OWNER": "QUIMBY, MARGARETHE", "ADDRESS": "4417 SEAGRASS",
                             "STATUS": "For Sale", "PROGRAM_TYPE": "JOHNATHAN QUIMBY TRUST 7"}},
             {"attributes": {"PARCEL_ID": "21012346.002", "OWNER": "OSTERWALD", "ADDRESS": "", "STATUS": "For Sale",
                             "PROGRAM_TYPE": "Side Lot"}}]
    routes = [
        (layer + "/query?where=1%3D1&returnCountOnly", Resp({"count": 2})),
        (layer + "/query", Resp({"features": feats})),
        (layer + "?", Resp({"name": "Properties For Sale", "geometryType": "esriGeometryPolygon", "fields": [
            {"name": "PARCEL_ID", "alias": "Parcel ID", "type": "esriFieldTypeString"},
            {"name": "OWNER", "alias": "Owner", "type": "esriFieldTypeString"},
            {"name": "ADDRESS", "alias": "Address", "type": "esriFieldTypeString"},
            {"name": "STATUS", "alias": "Status", "type": "esriFieldTypeString"},
            {"name": "PROGRAM_TYPE", "alias": "Program", "type": "esriFieldTypeString"}]})),
        ("https://www.arcgis.com/sharing/rest/content/items/abc", Resp({"title": "Properties For Sale", "type": "Feature Service",
                                                                       "url": layer, "licenseInfo": "<p>Public domain</p>",
                                                                       "snippet": "Land bank inventory"})),
    ]
    out = CAP.capture_arcgis_item(Session(routes), "abc")
    dump = json.dumps(out)
    _clean(dump)
    lay = out["layers"][0]
    assert lay["count"] == 2 and lay["sampled"] == 2
    assert lay["id_shapes"] == {"PARCEL_ID": {"99999999.999": 2}}
    assert lay["category_values"] == {"STATUS": {"For Sale": 2}, "PROGRAM_TYPE": {"Side Lot": 1}}
    assert lay["filled"]["ADDRESS"] == 1 and out["license"] == "Public domain"
    path = ROOT / "out" / "test-available-source-structure.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"sources": [{"source_id": "t", "state": "MI", "county": "X", "kind": "arcgis_item", "result": out}]}))
    _clean(CAP.digest(path))
    path.unlink()


def test_available_sources_scope_is_read_only():
    wf = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
    job = wf[wf.index("\n  evidence:"):]
    job = job[:job.index("\n  enrich:")]
    assert "SUPABASE" not in job and "secrets." not in job
    block = job[job.index('if [ "$SCOPE" = "available_sources" ]'):]
    block = block[:block.index("fi\n")]
    assert "python3 scripts/capture_available_sources.py\n" in block and "exit 0" in block
    src = (ROOT / "scripts/capture_available_sources.py").read_text(encoding="utf-8")
    assert "write_bytes" not in src and src.count(".write_text(") == 1
    assert all(re.fullmatch(r"https://\S+|[0-9a-f]{32}", c["url"]) for c in CAP.candidates())


def test_xlsx_lists_emit_headers_counts_and_shapes_only():
    import io
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["2025 FLC LIST"])
    ws.append(["Map Number", "Owner Name", "Address", "Opening Bid", "Tax Sale Date"])
    ws.append(["123-45-67-890", "QUIMBY, MARGARETHE", "4417 SEAGRASS", 1234.56, "10/07/2024"])
    ws.append(["123-45-67-891", "JOHNATHAN QUIMBY", "", 99, "2024"])
    buf = io.BytesIO()
    wb.save(buf)
    out = CAP.xlsx_structure(buf.getvalue())
    _clean(json.dumps(out))
    sh = out["sheets"][0]
    assert sh["rows"] == 2 and sh["header"][0] == "Map Number" and sh["header"][1] == "Owner Name"
    assert sh["id_cells_by_column"] == {0: 2} and sh["id_shapes"] == {"999-99-99-999": 2}
    assert sh["years"] == {"2024": 2}


def test_wording_with_a_person_name_is_never_printed():
    import capture_sc_available as SCC
    page = ("<p>If you are interested in one of the properties, you must send your request in writing to: Forfeited Land "
            "Commission C/O Quimby Osterwald P.</p><p>Members: Chairman Johnathan Quimby and Secretary Margarethe "
            "Osterwald approve each sale of forfeited land.</p><p>The Forfeited Land Commission sells forfeited land "
            "after the redemption period.</p>")
    out = SCC.html_wording(page, "https://x.gov/flc")
    _clean(json.dumps(out))
    assert out["availability_wording"] == ["The Forfeited Land Commission sells forfeited land after the redemption period."]
