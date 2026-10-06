"""AVAILABLE commercial release (2026-09-30): migration 023, the
purchase-path engine (ten evidence-backed types, refusals), source-published
outcome ingestion, the reactivation transition and result fields in the
inventory-status writer, the admin publication-review flow in the gate,
the workflow job selector, the frontend contract, and the FL / TX / AL /
AR / LA / AZ regressions around them."""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from harvesters.otc.adapters import expansion as EX  # noqa: E402

from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import publication as pub  # noqa: E402
from harvesters.governance import states  # noqa: E402
from harvesters.ledgers import BLOCKED_SOURCE_IDS  # noqa: E402
import inventory_status_writer as W  # noqa: E402
import laft_lifecycle as L  # noqa: E402
import laft_purchase_paths as PP  # noqa: E402
import outcome_ingest as OI  # noqa: E402
import publication_gate as PG  # noqa: E402
import purchase_path_engine as PE  # noqa: E402

EXPANSION_STATES = {"MI", "WY", "SC", "CO", "WI", "MO", "OK", "PA", "MN"}   # + AVAILABLE expansion 2026-10-04
ROWS = csr.load_registry()
MIG = REPO / "scripts/migrations/023_available_commercial_release.sql"
APP = (REPO / "public/app.js").read_text(encoding="utf-8")
TODAY = date(2026, 9, 30)
REG = {"verification_status": "PRODUCTION_VERIFIED", "canonical_url": "https://www.example-clerk.gov/lands-available/list",
       "last_checked": "2026-09-20"}


def _harvest_row(**kw) -> dict:
    base = {"county": "Volusia", "case_no": "2024-TD-1", "parcel": "1234-56", "status": "active"}
    base.update(kw)
    return base


# ==================== 1. the purchase-path engine ====================

def test_e01_ten_path_types_and_the_db_constraint_agree():
    assert len(PE.PATH_TYPES) == 10 and len(set(PE.PATH_TYPES)) == 10
    sql = MIG.read_text(encoding="utf-8")
    block = sql[sql.index("properties_purchase_path_type_check"):sql.index("properties_purchase_path_scope_check")]
    assert all(f"'{t}'" in block for t in PE.PATH_TYPES)
    assert PE.URL_TYPES | PE.NON_URL_TYPES == set(PE.PATH_TYPES) and not (PE.URL_TYPES & PE.NON_URL_TYPES)
    assert set(PE.MODE_FOR_TYPE) == set(PE.PATH_TYPES) and set(PE.MODE_FOR_TYPE.values()) <= set(PP.PURCHASE_PATH_MODES)
    # The frontend labels every type (a Playwright test renders two of them).
    for t in PE.PATH_TYPES:
        assert f"{t}:" in APP, t


def test_e02_evidence_table_holds_only_verified_captured_rows_and_outcome_rules_ship_empty():
    # Customer Value / Evidence Acquisition sprint (2026-09-30): the evidence
    # table carries rows ONLY for counties whose own page/document was read by
    # the repository's capture job. Every row must be reviewable by a person:
    # a verified review state, an https evidence page, the source's own title,
    # its published instructions, and an observed date - never a guess.
    rows = PE.load_evidence()
    assert rows, "the committed evidence table is expected to carry captured rows"
    assert all(PE.evidence_problems(r) == [] for r in rows)
    for r in rows:
        assert r.applicable and r.enabled and r.review_state == "verified", (r.county, r.path_type)
        assert r.evidence_url.startswith("https://") and r.source_title and r.instructions and r.observed_on, r.county
        assert r.evidence_type in PE.EVIDENCE_TYPES and r.path_type in PE.PATH_TYPES, r.county
        assert r.state in ("FL", "LA", "TX") and r.county != "*", (r.state, r.county)  # no wildcard, no unread state
        # third_party_permitted only where the listing is a vendor's (Texas: delinquent-tax
        # counsel) and the URL is the county's OWN office page the evidence was read from.
        assert not r.third_party_permitted or (r.state == "TX" and r.url == r.evidence_url
                                               and r.url.startswith("https://sheriff.galvestoncountytx.gov/")), r.county
        # No invented property URL: a URL appears only on an instructions-page row, and only as
        # the same government site's own page the evidence was read from.
        assert r.url == "" or (r.path_type == "county_instructions" and (
            (r.url.startswith("https://www.brla.gov/") and r.evidence_url.startswith("https://www.brla.gov/"))
            or (r.url.startswith("https://sheriff.galvestoncountytx.gov/") and r.url == r.evidence_url))), r.county
        assert re.search(r"\brun[s]? 3669828546|\bruns 36717720575|\brun 36835470121|\brun 36858070184", r.notes), r.county  # traceable to the capture run(s)
    assert len({(r.state, r.source_id, r.county) for r in rows}) == len(rows)   # one row per source/county
    assert OI.load_rules() == []
    with open(PE.EVIDENCE_PATH, newline="", encoding="utf-8") as fh:
        assert next(csv.reader(fh)) == PE.EVIDENCE_COLUMNS
    with open(OI.RULES_PATH, newline="", encoding="utf-8") as fh:
        assert next(csv.reader(fh)) == OI.RULE_COLUMNS


@pytest.mark.parametrize("url,reason", [
    ("http://www.example-clerk.gov/buy/1", "not https"),
    ("https://www.example-clerk.gov/", "a bare homepage"),
    ("https://www.google.com/search?q=lands+available", "search engine"),
    ("https://www.govease.com/property/1", "blocked vendor"),
    ("https://www.example-clerk.gov/lands-available/list", "the list page or the document itself"),
    ("https://www.example-clerk.gov/TaxDeed/Detail/{id}", "guessed URL pattern"),
    ("https://www.example-clerk.gov/TaxDeed/Detail/XXXX", "guessed URL pattern"),
    ("https://third-party-listings.com/parcel/1", "third-party host"),
    ("https://www.example-clerk.gov/search?q=1234", "search-results page"),
])
def test_e03_engine_refuses_every_forbidden_url_shape(url, reason):
    got = PE.rejection_reason(url, canonical_url=REG["canonical_url"], list_url=REG["canonical_url"], document_url=None)
    assert got and reason in got, (url, got)


def test_e04_same_site_and_permitted_third_party_are_accepted():
    assert PE.rejection_reason("https://clerk.example-clerk.gov/buy/1", canonical_url=REG["canonical_url"], list_url=None, document_url=None) is None
    assert PE.rejection_reason("https://third-party-listings.com/parcel/1", canonical_url=REG["canonical_url"], list_url=None,
                               document_url=None, third_party_permitted=True) is None


def test_e05_nothing_verified_means_no_path_and_no_none_published():
    path, reasons = PE.resolve(_harvest_row(), state="FL", source_id="fl_laft_html", county="Volusia", registry_row=REG,
                               evidence=[], list_url=REG["canonical_url"], document_url=None, harvest_date="2026-09-30")
    assert path is None and reasons == []
    # none_published is a claim about the source's wording: only a registry
    # mode 'none' with that wording produces it.
    reg = dict(REG, purchase_path_mode="none", purchase_path_evidence="The Clerk does not sell these parcels online or otherwise (page wording)")
    path, _ = PE.resolve(_harvest_row(), state="FL", source_id="fl_laft_html", county="Volusia", registry_row=reg, evidence=[])
    assert path.path_type == "none_published" and path.scope == "source" and "page wording" in path.evidence and path.observed_on == "2026-09-20"
    assert path.columns()["purchase_path_type"] == "none_published" and "purchase_url" not in path.columns()


def test_e06_precedence_row_link_then_evidence_table_then_registry(tmp_path):
    ev = tmp_path / "ev.csv"
    with open(ev, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(PE.EVIDENCE_COLUMNS)
        w.writerow(["FL", "fl_laft_html", "*", "county_instructions", "https://www.example-clerk.gov/lands-available/how-to-buy",
                    "Clerk page 'How to purchase' names the steps", "2026-09-18", "yes", "no", "",
                    "https://www.example-clerk.gov/lands-available/how-to-buy", "county_page", "How to Purchase Lands Available",
                    "Submit the application form to the Tax Deeds office; payment by cashier's check.", "verified",
                    "the county publishes a purchase-instructions page", "that any specific parcel is still available"])
    evidence = PE.load_evidence(ev)
    assert len(evidence) == 1 and evidence[0].applicable
    reg = dict(REG, purchase_url="https://www.example-clerk.gov/apply", purchase_url_kind="application_form")
    # 1. the row's own verified link (property scope) wins
    row = _harvest_row(purchase_url="https://www.example-clerk.gov/TaxDeed/Buy/1234", purchase_url_kind="online_purchase",
                       purchase_url_basis="rule column='Purchase' verified 2026-09-25: property-level online_purchase link published on the list row")
    path, _ = PE.resolve(row, state="FL", source_id="fl_laft_html", county="Volusia", registry_row=reg, evidence=evidence, list_url=REG["canonical_url"])
    assert (path.path_type, path.scope, path.observed_on, path.url_kind) == ("direct_property_url", "property", "2026-09-25", "online_purchase")
    assert path.columns()["purchase_url"] == row["purchase_url"]
    # 2. else the evidence table (source scope)
    path, _ = PE.resolve(_harvest_row(), state="FL", source_id="fl_laft_html", county="Volusia", registry_row=reg, evidence=evidence, list_url=REG["canonical_url"])
    assert (path.path_type, path.scope, path.observed_on) == ("county_instructions", "source", "2026-09-18") and path.url.endswith("/how-to-buy")
    prov = path.provenance()
    assert prov["purchase_evidence_url"].endswith("/how-to-buy") and prov["purchase_evidence_type"] == "county_page"
    assert prov["purchase_instructions"].startswith("Submit the application form") and prov["purchase_path_observed_on"] == "2026-09-18"
    # 3. else the registry row's source-level page
    path, _ = PE.resolve(_harvest_row(), state="FL", source_id="fl_laft_html", county="Volusia", registry_row=reg, evidence=[], list_url=REG["canonical_url"])
    assert (path.path_type, path.scope, path.observed_on) == ("application_page", "source", "2026-09-20") and path.url.endswith("/apply")
    # a registry row that is not production-verified establishes nothing
    path, _ = PE.resolve(_harvest_row(), state="FL", source_id="fl_laft_html", county="Volusia", registry_row=dict(reg, verification_status="CANDIDATE"), evidence=[])
    assert path is None


def test_e07_a_refused_row_link_is_a_reason_never_a_path():
    row = _harvest_row(purchase_url="https://www.google.com/search?q=parcel", purchase_url_kind="online_purchase", purchase_url_basis="rule x verified 2026-09-25")
    path, reasons = PE.resolve(row, state="FL", source_id="fl_laft_html", county="Volusia", registry_row=REG, evidence=[])
    assert path is None and reasons and "refused" in reasons[0]


def test_e08_evidence_table_validation_refuses_the_dishonest_rows(tmp_path):
    def write(*cells):
        p = tmp_path / "e.csv"
        with open(p, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh); w.writerow(PE.EVIDENCE_COLUMNS); w.writerow(cells)
        return p
    V2 = ["https://x.gov/lands", "county_page", "Lands Available", "wording", "verified", "", ""]
    with pytest.raises(ValueError, match="enabled row needs observed_on"):
        PE.load_evidence(write("FL", "fl_laft_html", "*", "in_person", "", "wording", "", "yes", "no", "", *V2))
    with pytest.raises(ValueError, match="carries no url"):
        PE.load_evidence(write("FL", "fl_laft_html", "*", "in_person", "https://x.gov/a", "w", "2026-09-01", "no", "no", "", *V2))
    with pytest.raises(ValueError, match="property-scope"):
        PE.load_evidence(write("FL", "fl_laft_html", "*", "direct_property_url", "https://x.gov/a", "w", "2026-09-01", "no", "no", "", *V2))
    with pytest.raises(ValueError, match="path_type"):
        PE.load_evidence(write("FL", "fl_laft_html", "*", "online_link", "https://x.gov/a", "w", "2026-09-01", "no", "no", "", *V2))
    # Customer-value sprint: an enabled row that is not review_state=verified,
    # has no https evidence page, or cites a search engine as its evidence
    # page is refused - a capture is never a path until a person verified it.
    with pytest.raises(ValueError, match="review_state=verified"):
        PE.load_evidence(write("FL", "fl_laft_html", "*", "in_person", "", "w", "2026-09-01", "yes", "no", "", "https://x.gov/lands", "county_page", "t", "i", "needs_review", "", ""))
    with pytest.raises(ValueError, match="https evidence_url"):
        PE.load_evidence(write("FL", "fl_laft_html", "*", "in_person", "", "w", "2026-09-01", "yes", "no", "", "", "county_page", "t", "i", "verified", "", ""))
    with pytest.raises(ValueError, match="search engine or a blocked vendor"):
        PE.load_evidence(write("FL", "fl_laft_html", "*", "in_person", "", "w", "2026-09-01", "yes", "no", "", "https://www.google.com/search?q=lands", "county_page", "t", "i", "verified", "", ""))
    # The original ten-column header still loads (rows are simply not applicable until verified).
    p10 = tmp_path / "v1.csv"
    with open(p10, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(PE.EVIDENCE_COLUMNS_V1); w.writerow(["FL", "fl_laft_html", "*", "in_person", "", "w", "2026-09-01", "no", "no", ""])
    rows = PE.load_evidence(p10)
    assert len(rows) == 1 and not rows[0].applicable


def test_e09_lifecycle_writes_023_columns_only_when_probed_and_keeps_mode_semantics(tmp_path):
    reg = tmp_path / "reg.csv"
    with open(csr.REGISTRY_PATH, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh)); cols = list(rows[0].keys())
    # A county WITHOUT a committed evidence row, so the registry mode is what
    # the lifecycle sees (a verified evidence page outranks the registry).
    with_evidence = {(e.source_id, e.county) for e in PE.load_evidence()}
    county = next(r["county"] for r in rows if r["state"] == "FL" and r["source_id"] == "fl_laft_html"
                  and r["verification_status"] == "PRODUCTION_VERIFIED" and ("fl_laft_html", r["county"]) not in with_evidence)
    for r in rows:
        if r["state"] == "FL" and r["county"] == county and r["source_id"] == "fl_laft_html":
            r["purchase_path_mode"], r["purchase_path_evidence"] = "in_person_only", "Bids are accepted in person at the Clerk's office (list header)"
    with open(reg, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader(); w.writerows(rows)
    gate = {"status": "COMPLETE", "harvester": "fl_laft_html", "entry": {"source_url": "https://x.gov/list", "source_id": "fl_laft_html"}}
    for have in (False, True):
        ctx = L.PathContext(reg, "FL", have_023=have, harvest_date="2026-09-30")
        payload = L.provenance_payload(_harvest_row(county=county), gate, "2026-09-30T00:00:00+00:00", state="FL", path_ctx=ctx)
        assert payload["otc_provenance"]["purchase_path_mode"] == "in_person_only"
        assert payload["otc_provenance"]["purchase_url"].startswith("in_person (source-scope)")
        assert ("purchase_path_type" in payload) is have
        if have:
            assert payload["purchase_path_type"] == "in_person" and payload["purchase_path_scope"] == "source"
            assert payload["purchase_path_observed_on"] and "purchase_url" not in payload
    # Without a context the payload is byte-for-byte the pre-023 shape.
    plain = L.provenance_payload(_harvest_row(county=county), gate, "2026-09-30T00:00:00+00:00", state="FL")
    assert "purchase_path_type" not in plain and plain["otc_provenance"]["purchase_path_mode"] == "unknown"


def test_e10_committed_registry_alone_establishes_no_path_and_only_captured_evidence_types_one():
    # The registry never establishes a path on its own (every FL production
    # row still carries purchase_path_mode "unknown"). A typed path exists
    # exactly for the counties whose page was captured and reviewed, at
    # SOURCE scope, carrying the evidence page and the published instructions.
    ctx = L.PathContext(csr.REGISTRY_PATH, "FL", have_023=True, harvest_date="2026-09-30")
    evidence = {(e.source_id, e.county): e for e in PE.load_evidence()}
    typed = 0
    for r in csr.production_rows(ROWS, "FL"):
        if "AVAILABLE" not in r.ledger_set:
            continue
        path, reasons = ctx.resolve(_harvest_row(county=r.county), source_id=r.source_id, county=r.county, list_url=r.canonical_url, document_url=None)
        assert reasons == [], (r.county, r.source_id)
        ev = evidence.get((r.source_id, r.county))
        if ev is None:
            assert path is None, (r.county, r.source_id)                       # no county page read; nothing invented
            continue
        typed += 1
        assert path is not None and path.path_type == ev.path_type and path.scope == "source", (r.county, r.source_id)
        assert path.url in ("", None) or ev.path_type in PE.URL_TYPES
        prov = path.provenance()
        assert prov["purchase_evidence_url"] == ev.evidence_url and prov["purchase_instructions"] == ev.instructions
        assert prov["purchase_path_observed_on"] == ev.observed_on and ev.observed_on in ("2026-09-30", "2026-10-01")
    fl_evidence = [k for k, e in evidence.items() if e.state == "FL"]
    assert typed == len(fl_evidence), (typed, len(fl_evidence))                  # every committed FL row is reachable
    # Every path type the table uses is a real, labelled type - the frontend names it.
    for e in evidence.values():
        assert f'{e.path_type}:' in APP


# ==================== 2. outcome ingestion ====================

def test_o01_no_rule_no_outcome_and_identity_only_sold_files_yield_nothing(tmp_path):
    recs = [{"county": "Volusia", "case_no": "1", "source_columns": {"Sold To": "J. Buyer", "Sale Date": "09/01/2026", "Amount": "$1,200.00"}}]
    assert OI.outcomes_by_identity(recs, [], state="FL", source_id="fl_laft_html") == {}
    sold = tmp_path / "sold.json"
    sold.write_text(json.dumps([{"county": "Volusia", "case_no": "1", "parcel": "p", "source": "laft"}]), encoding="utf-8")
    assert OI.load_result_files([sold]) == {}


def test_o02_an_enabled_rule_maps_only_the_named_column_and_the_party_only_when_permitted(tmp_path):
    def rules(*rows):
        p = tmp_path / "r.csv"
        with open(p, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh); w.writerow(OI.RULE_COLUMNS); w.writerows(rows)
        return OI.load_rules(p)
    rs = rules(["FL", "fl_laft_html", "*", "Sold To", "result_status", "sold", "no", "yes", "2026-09-20", "list column verified", ""],
               ["FL", "fl_laft_html", "*", "Sale Date", "result_date", "", "no", "yes", "2026-09-20", "list column verified", ""],
               ["FL", "fl_laft_html", "*", "Amount", "result_amount", "", "no", "yes", "2026-09-20", "list column verified", ""])
    recs = [{"county": "Volusia", "case_no": "1", "source_columns": {"Sold To": "J. Buyer", "Sale Date": "09/01/2026", "Amount": "$1,200.00", "Bidder": "x"}},
            {"county": "Volusia", "case_no": "2", "source_columns": {"Sold To": "", "Sale Date": "09/02/2026"}}]
    out = OI.outcomes_by_identity(recs, rs, state="FL", source_id="fl_laft_html")
    assert out == {("Volusia", "1"): {"result_status": "sold", "raw": "Sold To", "result_date": "2026-09-01", "result_amount": 1200.0}}
    with pytest.raises(ValueError, match="party_permitted"):
        rules(["FL", "fl_laft_html", "*", "Sold To", "result_party", "", "no", "yes", "2026-09-20", "ev", ""])
    with pytest.raises(ValueError, match="needs verified_on"):
        rules(["FL", "fl_laft_html", "*", "Sold To", "result_status", "sold", "no", "yes", "", "", ""])
    with pytest.raises(ValueError, match="result_status"):
        rules(["FL", "fl_laft_html", "*", "Sold To", "result_status", "probably_sold", "no", "no", "", "", ""])


# ==================== 3. the writer: reactivation + result fields ====================

def test_w01_reactivated_transition_and_result_fields_ride_only_with_023():
    rows = [{"id": "a", "state": "FL", "county": "Volusia", "case_no": "1", "source": "laft", "status": "active", "inventory_status": "closed"},
            {"id": "b", "state": "FL", "county": "Volusia", "case_no": "2", "source": "laft", "status": "active", "inventory_status": "available_otc"},
            {"id": "c", "state": "FL", "county": "Volusia", "case_no": "3", "source": "laft", "status": "active", "inventory_status": None}]
    results = {("Volusia", "2"): {"result_date": "2026-09-01", "result_amount": 1200.0, "result_party": "J. Buyer", "raw": "Sold To"}}
    changes, counts = W.plan(rows, today=TODAY, sold={("Volusia", "2")}, results=results)
    by = {c["id"]: c for c in changes}
    assert by["a"]["transition"] == "reactivated" and by["a"]["status"] == "available_otc"
    assert by["b"]["transition"] == "result_published" and by["b"]["result"] == {"result_amount": 1200.0, "result_date": "2026-09-01", "result_party": "J. Buyer"}
    assert by["c"]["transition"] == "newly_observed" and "result" not in by["c"]
    assert counts["by_transition"] == {"reactivated": 1, "result_published": 1, "newly_observed": 1} and counts["results_with_fields"] == 1
    # 022-only deployment: `reactivated` is not in 022's check constraint,
    # the result columns do not exist - neither reaches the API.
    obs = W.observations(changes, observed_at="2026-09-30T00:00:00+00:00", run_id="r", include_transition=True, include_results=False)
    byo = {o["property_id"]: o for o in obs}
    assert byo["a"]["transition"] == "status_changed" and "result_amount" not in byo["b"]
    assert all("result_amount" not in p for p, _ in W.group_changes(changes))
    # 023 deployment: both.
    obs = W.observations(changes, observed_at="2026-09-30T00:00:00+00:00", run_id="r", include_transition=True, include_results=True)
    byo = {o["property_id"]: o for o in obs}
    assert byo["a"]["transition"] == "reactivated" and byo["b"]["result_party"] == "J. Buyer"
    payloads = [p for p, ids in W.group_changes(changes, include_results=True) if "b" in ids]
    assert payloads[0]["result_amount"] == 1200.0 and payloads[0]["inventory_status"] == "sold"


def test_w02_absence_is_never_a_result_even_with_result_fields_on_file():
    rows = [{"id": "a", "state": "FL", "county": "Volusia", "case_no": "1", "source": "laft", "status": "closed", "inventory_status": "available_otc"}]
    changes, _ = W.plan(rows, today=TODAY, sold=set(), results={("Volusia", "1"): {"result_amount": 5.0}})
    assert changes[0]["status"] == "closed" and changes[0]["transition"] == "removed" and "result" not in changes[0]


# ==================== 4. the admin review flow in the gate ====================

def test_g01_reviews_are_validated_like_csv_values_and_the_strictest_override_stands():
    reviews = {("FL", "fl_laft_pdfs"): {"id": 3, "publication_status": "RESTRICTED", "restrictions": "terms under review", "decided_at": "2026-09-30T00:00:00Z"},
               ("TX", "tx_hctax"): {"id": 2, "publication_status": "APPROVED", "evidence": "x", "decided_at": "2026-09-30T00:00:00Z"},
               ("AL", "al_ador_state_land"): {"id": 4, "publication_status": "APPROVED", "evidence": "x", "decided_at": "2026-09-30T00:00:00Z"},
               ("TX", "tx_pbfcm"): {"id": 6, "publication_status": "APPROVED", "evidence": "x", "decided_at": "2026-09-30T00:00:00Z"},
               ("ZZ", "nope"): {"id": 5, "publication_status": "APPROVED", "decided_at": "2026-09-30T00:00:00Z"}}
    out, rep = PG.apply_reviews(ROWS, reviews)
    assert list(rep["applied"]) == ["FL/fl_laft_pdfs"]
    assert set(rep["rejected"]) >= {"TX/tx_hctax", "AL/al_ador_state_land"}
    assert any("LEGAL_REVIEW_REQUIRED" in r for r in rep["rejected"]["TX/tx_hctax"]["reasons"])
    assert any("not PRODUCTION_VERIFIED" in r for r in rep["rejected"]["AL/al_ador_state_land"]["reasons"])
    assert "ZZ/nope" in rep["unknown_source"]
    # A blocked vendor can never be approved - by rejection or by having no registry row at all.
    assert "TX/tx_pbfcm" in rep["rejected"] or "TX/tx_pbfcm" in rep["unknown_source"]
    decisions = pub.decisions_by_source(out)
    assert decisions["fl_laft_pdfs"].publication == "RESTRICTED" and not decisions["fl_laft_pdfs"].customer_publishable
    assert decisions["tx_hctax"].publication == "RESTRICTED"
    for sid in BLOCKED_SOURCE_IDS:
        if sid in decisions:
            assert decisions[sid].publication == "BLOCKED"
    # An unreviewed source stays unreviewed: a review never converts unknown into approved by omission.
    assert decisions["al_ador_state_land"].publication == "UNREVIEWED"


def test_g02_latest_review_per_source_wins_by_decided_at_then_id():
    rows = [{"id": 1, "state": "FL", "source_id": "s", "publication_status": "APPROVED", "decided_at": "2026-09-01T00:00:00Z"},
            {"id": 3, "state": "FL", "source_id": "s", "publication_status": "RESTRICTED", "decided_at": "2026-09-02T00:00:00Z"},
            {"id": 2, "state": "FL", "source_id": "s", "publication_status": "UNREVIEWED", "decided_at": "2026-09-02T00:00:00Z"}]
    assert PG.latest_reviews(rows)[("FL", "s")]["id"] == 3


def test_g03_registry_only_run_takes_no_reviews_and_writes_the_report(tmp_path, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False); monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    report = tmp_path / "gate.json"
    assert PG.main(["--state", "FL", "--report", str(report)]) == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["mode"] == "registry-only (no credentials)" and "reviews" not in data
    assert all(d["publication"] == "APPROVED_GRANDFATHERED" for k, d in data["sources"].items() if k.startswith("fl_laft_") and "candidate" not in k)


# ==================== 5. migration 023 ====================

def test_m01_migration_023_shape_appends_to_022_and_touches_nothing_destructive():
    sql = MIG.read_text(encoding="utf-8")
    prev = (REPO / "scripts/migrations/022_available_publication_gate.sql").read_text(encoding="utf-8")
    body = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert "drop column" not in body.lower() and "drop table" not in body.lower() and "delete from" not in body.lower()
    assert body.count("drop function if exists public.get_properties(text, text, text, integer, integer);") == 1
    assert "language sql\nstable" in body and "set search_path = public" in body
    def returns(text):
        return text[text.index("returns table ("):text.index(")\nlanguage sql")]
    r22, r23 = returns(prev), returns(sql)
    assert r23.startswith(r22.rstrip()) or r23.replace(",\n  -- 023: purchase-path evidence and source-published results", "").startswith(r22.rstrip()[:-1])
    tail = r23[len(r22.rstrip()) - 0:]
    for col in ("purchase_path_type text", "purchase_path_scope text", "purchase_path_evidence text", "purchase_path_observed_on date",
                "result_amount numeric", "result_date date", "result_party text"):
        assert col in r23 and r23.rindex(col) > r23.index("publication_status text"), col
    # The select list ends with the same seven, in the same order, and the WHERE / ORDER / LIMIT / OFFSET are 022's.
    sel = body[body.index("  select\n"):body.index("$function$;")]
    assert sel.rstrip().endswith("purchase_path_type, purchase_path_scope, purchase_path_evidence,\n    purchase_path_observed_on,\n    result_amount, result_date, result_party\n  from public.properties\n  where state = p_state\n    and (p_ledger_type is null or ledger_type = p_ledger_type)\n    and (p_status is null or status = p_status)\n  order by county, case_no\n  limit p_limit\n  offset p_offset;")
    for c in ("properties_purchase_path_type_check", "properties_purchase_path_scope_check", "properties_purchase_path_evidence_check",
              "properties_purchase_path_url_check", "inventory_status_observations_transition_check", "source_publication_reviews"):
        assert c in body
    assert "'reactivated'" in body
    # Reviews: admins only, append-only, service_role reads, customers nothing.
    reviews = body[body.index("create table if not exists public.source_publication_reviews"):body.index("drop function if exists public.get_properties")]
    assert "using (public.is_admin())" in reviews and "with check (public.is_admin() and decided_by = auth.uid())" in reviews
    assert "grant select, insert on table public.source_publication_reviews to authenticated" in reviews
    assert "grant select on table public.source_publication_reviews to service_role" in reviews
    assert "for update" not in reviews and "for delete" not in reviews
    assert "check (publication_status <> 'RESTRICTED' or (restrictions is not null" in reviews


def test_m02_docs_and_config_list_023():
    conf = (REPO / "docs/production-configuration.md").read_text(encoding="utf-8")
    assert "023_available_commercial_release.sql" in conf
    ledger = (REPO / "docs/available-ledger.md").read_text(encoding="utf-8")
    assert "purchase_path_engine" in ledger and "source_publication_reviews" in ledger
    assert "023_available_commercial_release" in (REPO / "CLAUDE.md").read_text(encoding="utf-8")


# ==================== 6. workflow ====================

def test_wf01_job_selector_gates_every_job_and_never_schedules_texas():
    wf = yaml.safe_load((REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8"))
    on = wf.get("on") or wf.get(True)
    job = on["workflow_dispatch"]["inputs"]["job"]
    assert job["default"] == "all" and job["options"] == ["all", "deeds", "certificates", "laft", "texas", "backup", "evidence", "outcomes", "expansion", "enrich", "storage", "available"]
    # The enrichment backfill (property-enrichment sprint) is manual-only, never part of "all".
    assert wf["jobs"]["enrich"]["if"] == "github.event_name == 'workflow_dispatch' && github.event.inputs.job == 'enrich'"
    # The evidence capture is manual-only and is NOT part of "all" (it is a
    # read of county pages, not a harvest).
    assert wf["jobs"]["evidence"]["if"] == "github.event_name == 'workflow_dispatch' && github.event.inputs.job == 'evidence'"
    # Auction-outcome evidence: the stand-alone outcome read is manual-only too.
    assert wf["jobs"]["outcomes"]["if"] == "github.event_name == 'workflow_dispatch' && github.event.inputs.job == 'outcomes'"
    assert on["schedule"] == [{"cron": "0 10 * * *"}, {"cron": "0 22 * * *"}, {"cron": "0 12 * * *"}]
    for name, crons in (("deeds", ("0 10 * * *", "0 22 * * *")), ("certificates", ("0 12 * * *",)), ("laft", ("0 12 * * *",)), ("backup", ("0 12 * * *",)),
                        ("expansion", ("0 12 * * *",))):   # six-state expansion (2026-09-30): the existing 12:00 slot
        cond = wf["jobs"][name]["if"]
        assert f"github.event.inputs.job == '{name}'" in cond and "github.event.inputs.job == 'all'" in cond and "github.event.inputs.job == ''" in cond
        for c in crons:
            assert f"github.event.schedule == '{c}'" in cond
    texas = wf["jobs"]["texas"]["if"]
    assert texas.startswith("github.event_name == 'workflow_dispatch'") and "schedule" not in texas and "job == 'texas'" in texas
    assert "job == 'laft'" not in texas


# ==================== 7. frontend contract ====================

def test_f01_decision_page_answers_eleven_questions_from_fields_and_never_scores():
    block = APP[APP.index("function availableDecisionHtml"):APP.index("function inventoryHistoryHtml")]
    for qid in ("what", "available", "how", "cost", "where", "known", "unknown", "source", "fresh", "history", "related"):
        assert f'q("{qid}",' in block, qid
    assert "Not yet verified - no published acquisition process has been established from evidence" in APP[APP.index("function acquisitionHtml"):APP.index("function typedPurchasePath")]
    assert "acquisitionHtml(p)" in block                                  # the answer is the acquisition record
    assert "Not yet geocoded - no point is shown for this parcel" in block
    assert not re.search(r"score|badge|recommend", block, re.I)
    assert "typedPurchasePath(p)" in block and "dataGaps(p)" in block and "crossLedgerSummary(p)" in block
    # The cross-ledger summary is built from the deterministic parcel match only.
    xl = APP[APP.index("function crossLedgerSummary"):APP.index("function availableDecisionHtml")]
    assert "relatedRecordsFor(p)" in xl and "relatedWhen(" in xl


def test_f02_history_is_append_only_wording_and_export_is_published_fields_only():
    hist = APP[APP.index("function inventoryHistoryHtml"):APP.index("async function hydrateInventoryHistory")]
    assert "never as a sale" in hist and "reactivated" in APP[APP.index("const TRANSITION_LABELS"):APP.index("function availableDecisionHtml")]
    exp = APP[APP.index("const availableCols = ["):APP.index("  const cols = [")]
    headers = re.findall(r'^\s+\["([^"]+)",', exp, re.M)
    assert "Purchase Path" in headers and "Purchase Path Scope" in headers and "Latitude" in headers and "Last Read From Source" in headers
    for forbidden in ("publication", "provenance", "basis", "harvester", "Data Source", "governance"):
        assert not any(forbidden.lower() in h.lower() for h in headers), forbidden
    assert 'state.ledger === "laft" ? availableCols : state.ledger === "certificate" ? certificateCols : cols' in APP


def test_f03_filters_read_stored_fields_and_the_admin_panel_is_admin_gated():
    assert 'if (state.availLandUse !== "any" && String(p.land_use || "") !== state.availLandUse) return false;' in APP
    assert "if (state.availGeocoded && !(hasNum(p.latitude) && hasNum(p.longitude))) return false;" in APP
    assert "if (state.availValues && !(hasNum(p.market) || hasNum(p.assessed))) return false;" in APP
    # Admin-gated twice over: the panel loads only inside the admin-only governance
    # view (account menu / #/governance, 2026-09-30), and the loader refuses a non-admin.
    assert "if (IS_ADMIN) refreshAdminApprovals();" in APP and "await refreshAdminPublication();" in APP
    assert "if (!IS_ADMIN) { wrap.hidden = true; list.innerHTML = \"\"; return; }" in APP
    panel = APP[APP.index("async function refreshAdminPublication"):APP.index("// The properties fetch itself")]
    assert 'sb.from("source_publication_reviews").insert(row)' in panel and "RESTRICTED needs a reason." in panel and "An approval needs evidence." in panel
    for f in ("public/index.html", "public/tx.html"):
        html = (REPO / f).read_text(encoding="utf-8")
        assert 'id="adminPublication" hidden' in html and 'id="availLandUseFilter"' in html and 'id="availGeocoded"' in html and 'id="availValues"' in html
    assert (REPO / "public/sw.js").read_text(encoding="utf-8").count('const CACHE = "tdw-shell-v86"') == 1


# ==================== 8. regressions ====================

def test_r01_fl_tx_al_ar_la_az_regressions_hold():
    assert states.is_activated("FL") and states.is_activated("TX") and states.is_activated("LA")   # LA: 2026-09-30
    for code in ("AL", "AR", "AZ"):
        assert not states.is_activated(code)
    for r in ROWS:
        eff = pub.effective_publication(r)
        if r.source_id == "la_ebr_adjudicated":
            # The one reviewed (not grandfathered) approval: owner decision 2026-09-30, dated list.
            assert eff == "APPROVED" and r.is_production and "as of" in r.restrictions
        elif r.state in EXPANSION_STATES and r.source_id in EX.SIX_STATE_SOURCE_IDS:
            # Six-state expansion (2026-09-30): a reviewed owner decision, not grandfathered.
            assert eff == "APPROVED" and r.is_production and "owner on 2026-09-30" in r.restrictions, (r.state, r.source_id)
        elif r.state in EXPANSION_STATES:
            # Five-state sprint (2026-10-01): APPROVED only on a licence the source states (quoted), else UNREVIEWED.
            if eff == "APPROVED":
                assert r.is_production and "Creative Commons" in r.restrictions, (r.state, r.source_id)
            else:
                expected = "not customer-published" if r.source_id in (EX.AVAILABLE_SPRINT_SOURCE_IDS | EX.AVAILABLE_FIVE_SOURCE_IDS) else "no row is written"
                assert eff == "UNREVIEWED" and expected in r.restrictions, (r.state, r.source_id)
        elif r.is_production:
            assert eff == "APPROVED_GRANDFATHERED", (r.state, r.source_id)
        elif r.source_id in BLOCKED_SOURCE_IDS:
            assert eff == "BLOCKED"
        elif r.governance_status == "LEGAL_REVIEW_REQUIRED":
            assert eff == "RESTRICTED"
        else:
            assert eff == "UNREVIEWED"
    assert not any(r.runnable for r in ROWS if r.state not in {"FL", "TX", "LA"} | EXPANSION_STATES)
    assert [r.source_id for r in ROWS if r.state == "LA" and r.runnable] == ["la_ebr_adjudicated"]
    assert not any(r.runnable for r in ROWS if r.source_id in BLOCKED_SOURCE_IDS)
    # The AVAILABLE harvest units the registry expects (the laft job's own
    # "52 unit entries this run"): FL 52, TX 8 - unchanged by this release.
    assert len(csr.expected_harvest_units(ROWS, "FL")) == 52 and len(csr.expected_harvest_units(ROWS, "TX")) == 8
