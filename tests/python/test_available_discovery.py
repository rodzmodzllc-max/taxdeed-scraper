"""AVAILABLE multistate discovery (2026-10-02): discovered post-sale programs
are recorded for review, never published; each supported state's AVAILABLE
zero is named from repository facts; no auction or lien source ever counts
as an AVAILABLE source; the generated coverage file is current and value-free."""
import csv
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from harvesters.governance.county_source_registry import load_registry  # noqa: E402
from harvesters.sources import available_coverage as AC  # noqa: E402
from harvesters.sources import inventory as INV  # noqa: E402

APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")


def _rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_discovery_pages_and_catalog_agree_and_are_review_required():
    assert AC.problems() == []
    catalog = {r["source_id"]: r for r in _rows(INV.CATALOG_PATH)}
    pages = _rows(AC.DISCOVERY_PATH)
    assert pages, "the sprint records its discovered program pages"
    ev = AC.evidence()
    for p in pages:
        c = catalog[p["source_id"]]
        # Read by the value-free capture, never approved by it.
        assert c["governance"] == "REVIEW_REQUIRED"
        e = ev.get(p["source_id"])
        if e is None:
            assert c["access"] == "NOT_CHECKED"
        else:
            assert c["access"] == ("SOURCE_UNAVAILABLE" if e["availability"] == "UNAVAILABLE" else "ACCESSIBLE")
        roles = c["roles"].split("|")
        if e and e["availability"] in AC.REJECTED_AVAILABILITY:
            assert "availability" not in roles      # auction-only forfeited land is not AVAILABLE
        else:
            assert "availability" in roles
        assert p["url"].startswith("https://") and "web search" in p["found_via"]


def test_every_discovery_page_was_read_and_recorded():
    ev = AC.evidence()
    pages = _rows(AC.DISCOVERY_PATH)
    assert {p["source_id"] for p in pages} == set(ev)
    for e in ev.values():
        assert e["read_run"].isdigit() and e["read_at"].endswith("Z")
        assert e["evidence_url"].startswith("https://")
        if e["availability"] == "UNAVAILABLE":
            assert e["http_status"] != "200"
        # No read met current inventory + confirmed identifier + a publication
        # review, so no adapter is warranted and none was written.
        assert e["adapter_warranted"] == "no" and e["reason"]


def test_only_current_inventory_counts_and_rejected_pages_are_never_candidates():
    cov = {c["state"]: c for c in AC.coverage()}
    ev = AC.evidence()
    rejected = {sid for sid, e in ev.items() if e["availability"] in AC.REJECTED_AVAILABILITY}
    assert rejected == {"sc_aiken_forfeited_land", "sc_fairfield_forfeited_land"}
    for c in cov.values():
        ids = {x["source_id"] for x in c["candidates"]}
        assert not ids & rejected
        assert {x["source_id"] for x in c["rejected"]} <= rejected
    assert {x["county"] for x in cov["SC"]["rejected"]} == {"Aiken", "Fairfield"}
    current = {(c["state"], x["county"]) for c in cov.values() for x in c["candidates"]
               if x["availability"] == "CURRENT_INVENTORY"}
    assert current == {("SC", "Georgetown"), ("SC", "Spartanburg"), ("MI", "Lenawee")}
    # Empty / unavailable / seasonal pages are not inventory.
    for sid in ("sc_jasper_forfeited_land", "sc_lexington_forfeited_land", "wi_burnett_tax_deed_land"):
        assert ev[sid]["availability"] == "EMPTY"
    for sid in ("sc_richland_forfeited_land", "wi_marathon_tax_deed_property"):
        assert ev[sid]["availability"] == "UNAVAILABLE"
    # A confirmed identifier is a column the list itself publishes.
    assert {sid for sid, e in ev.items() if e["identifier_confirmed"] == "yes"} == {
        "sc_georgetown_forfeited_land", "sc_spartanburg_forfeited_land"}
    # Still REVIEW_REQUIRED: a read is not a publication review.
    for st in ("SC", "MI", "WI"):
        assert cov[st]["status"] == "REVIEW_REQUIRED" and cov[st]["production_sources"] == 0


def test_evidence_problems_catch_bad_rows(tmp_path, monkeypatch):
    rows = _rows(AC.EVIDENCE_PATH)
    def check(mutate):
        bad = [dict(r) for r in rows]
        mutate(bad)
        f = tmp_path / "ev.csv"
        with f.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(bad)
        monkeypatch.setattr(AC, "EVIDENCE_PATH", f)
        return AC.problems()
    def adapter_without_identifier(b):
        b[0]["adapter_warranted"] = "yes"          # York: seasonal, no identifier
    assert any("adapter needs" in p for p in check(adapter_without_identifier))
    def identifier_on_empty(b):
        j = next(i for i, r in enumerate(b) if r["availability"] == "EMPTY")
        b[j]["identifier_confirmed"], b[j]["identifier_field"] = "yes", "X"
    assert any("only a current list" in p for p in check(identifier_on_empty))
    def stray(b):
        b[0]["source_id"] = "zz_not_a_page"
    assert any("not in the discovery list" in p for p in check(stray))
    def http(b):
        b[0]["evidence_url"] = "http://example.gov/x"
    assert any("https" in p for p in check(http))
    def rejected_keeps_role(b):
        j = next(i for i, r in enumerate(b) if r["source_id"] == "sc_georgetown_forfeited_land")
        b[j]["availability"], b[j]["identifier_confirmed"] = "AUCTION_ONLY", "no"
    assert any("keeps the availability role" in p for p in check(rejected_keeps_role))
    monkeypatch.setattr(AC, "EVIDENCE_PATH", AC.REPO / "data" / "available_discovery_evidence.csv")


def test_no_discovered_candidate_becomes_a_registry_source_of_rows():
    """A candidate is recorded in the catalog only - no registry row (which is
    what harvesters and syncs read) was added for it."""
    reg_urls = {(r.canonical_url or r.document_url) for r in load_registry()}
    for p in _rows(AC.DISCOVERY_PATH):
        assert p["url"] not in reg_urls


def test_zero_states_are_named_and_correct():
    cov = {c["state"]: c for c in AC.coverage()}
    for st in ("MI", "SC", "WI"):
        assert cov[st]["status"] == "REVIEW_REQUIRED" and cov[st]["production_sources"] == 0 and cov[st]["candidates"]
    for st in ("CO", "WY"):
        assert cov[st]["status"] == "NO_QUALIFYING_PROGRAM" and cov[st]["research"]["mechanism"] == "COUNTY_HELD_LIEN"
    assert cov["FL"]["status"] == "SOURCE_TRACKED" and cov["LA"]["status"] == "SOURCE_TRACKED"
    assert cov["TX"]["status"] == "SOURCE_UNAVAILABLE"           # LGBS last read FAILED (manual-only)
    assert {c["status"] for c in cov.values()} <= set(AC.STATUSES)


def test_auction_and_lien_sources_never_count_as_available_sources():
    for st in INV.supported_states():
        for r in AC.production_available_sources(st):
            assert "AVAILABLE" in r.ledger_set
    auction_only = [r for r in load_registry() if r.ledger_set and "AVAILABLE" not in r.ledger_set
                    and r.verification_status == "PRODUCTION_VERIFIED"]
    assert auction_only, "fixture sanity: production auction / lien sources exist"
    # Michigan, Wyoming and South Carolina have production AUCTION sources and
    # still have no AVAILABLE source.
    for st in ("MI", "WY", "SC"):
        assert any(r.state == st for r in auction_only)
        assert AC.production_available_sources(st) == []


def test_status_precedence(monkeypatch):
    class R:  # minimal registry row
        def __init__(self, c):
            self.state, self.county, self.source_id, self.ledger_set = "ZZ", "X", "s", {"AVAILABLE"}
            self.verification_status, self.publication_status, self.completeness_status = "PRODUCTION_VERIFIED", "APPROVED", c
    for done, want in ((["FAILED", "FAILED"], "SOURCE_UNAVAILABLE"), (["EMPTY"], "SOURCE_EMPTY"),
                       (["MATCH_FAILED"], "MATCHING_FAILED"), (["COMPLETE", "FAILED"], "SOURCE_TRACKED")):
        monkeypatch.setattr(AC, "production_available_sources", lambda st, d=done: [R(c) for c in d])
        monkeypatch.setattr(AC, "discovery_candidates", lambda st, inv=None: [])
        assert AC.state_coverage("ZZ")["status"] == want
    monkeypatch.setattr(AC, "production_available_sources", lambda st: [])
    monkeypatch.setattr(AC, "research", lambda: {})
    assert AC.state_coverage("ZZ")["status"] == "NO_SOURCE_DISCOVERED"


def test_generated_files_are_current_and_value_free():
    r = subprocess.run([sys.executable, str(ROOT / "scripts/build_available_coverage.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    r = subprocess.run([sys.executable, str(ROOT / "scripts/build_source_inventory.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    doc = json.loads((ROOT / "public/available-coverage.json").read_text(encoding="utf-8"))
    text = json.dumps(doc)
    assert not re.search(r"\b\d{7,}\b", text), "no parcel-shaped identifier in the public coverage file"
    assert (ROOT / "available-coverage.json").read_text(encoding="utf-8") == (ROOT / "public/available-coverage.json").read_text(encoding="utf-8")


def test_frontend_labels_every_status_and_only_names_an_empty_available_ledger():
    m = re.search(r"const AVAILABLE_COVERAGE_LABELS = \{(.*?)\n\};", APP, re.S)
    assert m and set(re.findall(r"^\s+(\w+):", m.group(1), re.M)) == set(AC.STATUSES)
    body = APP[APP.index("// AVAILABLE only, and only when the ledger itself holds no row"):][:400]
    assert 'kind === "laft"' in body and '!ALL.some(p => p.source === "laft")' in body


def test_available_discovery_capture_scope_is_value_free_and_database_free():
    wf = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
    block = wf[wf.index('if [ "$SCOPE" = "available_discovery" ]'):]
    block = block[:block.index("fi\n")]
    assert "--candidates-file data/available_discovery_pages.csv" in block and "SUPABASE" not in block


def test_discovery_capture_reports_list_shapes_and_never_a_value(monkeypatch):
    """--discovery: FLC / over-the-counter links are selected and followed
    (same site only), every digit is masked, a table reports only its shape."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import capture_purchase_evidence as CPE
    monkeypatch.setattr(CPE, "DISCOVERY", True)
    html = """<html><head><title>Forfeited Land Commission</title></head><body>
      <h1>FLC</h1>
      <a href="/DocumentCenter/View/1/FLC-Properties-Available-for-Assignment">FLC Properties Available for Assignment Real Estate</a>
      <a href="https://othercounty.example.org/list">Properties available</a>
      <p>FLC properties are available for assignment until 10/31/2026 for a bid of $1,250.00 on parcel 123-45-6789.</p>
      <table><tr><th>Map #</th><th>Owner</th><th>Bid</th></tr>
             <tr><td>123-04-01-005</td><td>SMITH JOHN</td><td>$1,200</td></tr>
             <tr><td>123-04-01-006</td><td>DOE JANE</td><td>$900</td></tr></table>
    </body></html>"""
    out = CPE.extract_html(html, "https://county.example.gov/388/FLC")
    # Every captured TEXT is digit-free (hrefs are the page's own links; the
    # shape counts are counts, not values).
    texts = [out["title"], *out["headings"], *out["snippets"], *[l["text"] for l in out["links"]],
             *[h for t in out["table_shapes"] for h in t["header"]]]
    assert not any(re.search(r"\d", t) for t in texts), texts
    blob = json.dumps(out)
    assert "SMITH" not in blob and "DOE" not in blob
    assert out["table_shapes"] == [{"header": ["Map #", "Owner", "Bid"], "rows": 2, "rows_with_identifier_shape": 2}]
    links = {l["text"]: l for l in out["links"]}
    assert links["FLC Properties Available for Assignment Real Estate"]["follow"] is True
    assert links["Properties available"]["follow"] is False        # other site: listed, never followed
    assert any("available for assignment" in s.lower() for s in out["snippets"])
    # A sentence carrying a date / amount / parcel is row-like: counted, never printed.
    assert not any("bid of" in s for s in out["snippets"])


def test_discovery_mode_is_off_outside_the_scope():
    sys.path.insert(0, str(ROOT / "scripts"))
    import capture_purchase_evidence as CPE
    assert CPE.DISCOVERY is False
    wf = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
    assert "available_discovery_pages.csv --follow --discovery" in wf
    assert [l for l in wf.splitlines() if "capture_purchase_evidence.py" in l and "--discovery" in l] == \
        [l for l in wf.splitlines() if "available_discovery_pages.csv" in l and "capture_purchase_evidence.py" in l]


def test_discovery_never_prints_a_list_row_names_included(monkeypatch):
    """Run 37010171899 showed that masking digits is not enough: a PDF row
    still carried an owner's name. A row-like line (identifier-shaped digit
    run or an amount) is now only counted, never printed."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import capture_purchase_evidence as CPE
    monkeypatch.setattr(CPE, "DISCOVERY", True)

    class Page:
        def __init__(self, t): self.t = t
        def extract_text(self): return self.t

    class Pdf:
        pages = [Page("Georgetown County, South Carolina\nForfeited Land Commission\nMOBILE HOMES\n"
                      "Group Name TMS # Description Tax Sale Date Opening Bid\n"
                      "1001 Example Owner (H) 02-0001-002-03-04.000 1999 14x70 Example 10/6/2025 $512.00\n"
                      "1002 Another Person 02-0001-002-03-05.000 2001 16x80 Other 10/6/2025 $730.00\n"
                      "Properties are available for assignment until the end of the redemption period.")]
        def __enter__(self): return self
        def __exit__(self, *a): return False

    import types
    monkeypatch.setitem(sys.modules, "pdfplumber", types.SimpleNamespace(open=lambda b: Pdf()))
    out = CPE.extract_pdf(b"%PDF")
    printed = json.dumps({"s": out["snippets"], "f": out["pdf_shape"]["first_lines"]})
    assert "Example Owner" not in printed and "Another Person" not in printed, printed
    assert out["pdf_shape"]["lines_with_identifier_shape"] == 2
    assert any("available for assignment" in s for s in out["snippets"])
    assert "Group Name TMS # Description Tax Sale Date Opening Bid" in out["pdf_shape"]["first_lines"]
