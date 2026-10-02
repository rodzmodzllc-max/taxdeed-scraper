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
    for p in pages:
        c = catalog[p["source_id"]]
        # Found by search only: never approved, never marked as read.
        assert c["governance"] == "REVIEW_REQUIRED" and c["access"] == "NOT_CHECKED"
        assert "availability" in c["roles"].split("|")
        assert p["url"].startswith("https://") and "web search" in p["found_via"]


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
    assert any("available for assignment" in s for s in out["snippets"])


def test_discovery_mode_is_off_outside_the_scope():
    sys.path.insert(0, str(ROOT / "scripts"))
    import capture_purchase_evidence as CPE
    assert CPE.DISCOVERY is False
    wf = (ROOT / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
    assert "available_discovery_pages.csv --follow --discovery" in wf
    assert [l for l in wf.splitlines() if "capture_purchase_evidence.py" in l and "--discovery" in l] == \
        [l for l in wf.splitlines() if "available_discovery_pages.csv" in l and "capture_purchase_evidence.py" in l]
