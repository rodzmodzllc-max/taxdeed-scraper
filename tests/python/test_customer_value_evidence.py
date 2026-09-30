"""Customer Value / Evidence Acquisition sprint (2026-09-30): the evidence
capture workflow, the v2 evidence record and its provenance on the row, the
honesty rules around outcomes and lifecycle, cross-ledger identity, the
per-ledger customer exports, and the contracts that must not move."""
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

from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import inventory_status as IS  # noqa: E402
from harvesters.ledgers import domains  # noqa: E402
import capture_purchase_evidence as CAP  # noqa: E402
import inventory_status_writer as W  # noqa: E402
import laft_lifecycle as L  # noqa: E402
import purchase_path_engine as PE  # noqa: E402

APP = (REPO / "public/app.js").read_text(encoding="utf-8")
TODAY = date(2026, 9, 30)
V2_TAIL = ["https://www.example-clerk.gov/lands-available/", "county_page", "Lands Available for Taxes | Clerk",
           "Submit an Application to Purchase to the Tax Deeds office; payment by cashier's check.", "verified",
           "the county publishes its purchase process", "that any parcel is still available"]


def _write(tmp_path, *rows):
    p = tmp_path / "ev.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(PE.EVIDENCE_COLUMNS); w.writerows(rows)
    return p


# ==================== 1. capture is value-free ====================

def test_c01_capture_keeps_process_text_and_drops_every_row_value():
    html = """<html><head><title>Lands Available for Taxes | Clerk</title></head><body><h1>Lands Available</h1>
    <p>To purchase a property from the List of Lands Available, submit the Application to Purchase to the Tax Deeds
    Department at (352) 555-0100 or taxdeeds@example.gov. Payment must be by cashier's check.</p>
    <a href="/tax-deeds/purchase-instructions">How to Purchase</a><a href="https://www.google.com/search?q=x">search</a>
    <table><tr><td>Case 2024-TD-000123</td><td>Parcel 1234567890</td><td>Owner J. Doe</td><td>$5,000.00</td></tr></table>
    <p>Reference parcel 0011223344 for details.</p></body></html>"""
    r = CAP.extract_html(html, "https://www.exampleclerk.gov/lands-available/")
    assert r["title"].startswith("Lands Available") and r["phones"] == ["(352) 555-0100"] and r["emails"] == ["taxdeeds@example.gov"]
    assert any(s.startswith("To purchase a property") for s in r["snippets"])
    joined = " ".join(r["snippets"])
    assert "1234567890" not in joined and "2024-TD" not in joined and "J. Doe" not in joined and "0011223344" not in joined
    assert [l["href"] for l in r["links"]] == ["https://www.exampleclerk.gov/tax-deeds/purchase-instructions"]   # the search engine link is not evidence


def test_c02_evidence_job_is_manual_only_and_never_part_of_all():
    wf = yaml.safe_load((REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8"))
    ev = wf["jobs"]["evidence"]
    assert ev["if"] == "github.event_name == 'workflow_dispatch' && github.event.inputs.job == 'evidence'"
    runs = " ".join(str(s.get("run", "")) for s in ev["steps"])
    assert "capture_purchase_evidence.py" in runs and "artifact_evidence.py" in runs
    assert "SUPABASE_SERVICE_KEY" not in json.dumps(ev)          # the capture never touches the database
    on = wf.get("on") or wf.get(True)
    assert on["schedule"] == [{"cron": "0 10 * * *"}, {"cron": "0 22 * * *"}, {"cron": "0 12 * * *"}]


# ==================== 2. evidence record -> typed path with provenance ====================

def test_e01_verified_county_instructions_page_creates_a_typed_path_with_provenance(tmp_path):
    rows = PE.load_evidence(_write(tmp_path, ["FL", "fl_laft_html", "Volusia", "county_instructions",
                                             "https://www.example-clerk.gov/lands-available/how-to-purchase",
                                             "Clerk page names the application and payment steps", "2026-09-30", "yes", "no", "", *V2_TAIL]))
    path, reasons = PE.resolve({"county": "Volusia"}, state="FL", source_id="fl_laft_html", county="Volusia",
                               registry_row={"verification_status": "PRODUCTION_VERIFIED", "canonical_url": "https://www.example-clerk.gov/lands-available/"},
                               evidence=rows, list_url="https://www.example-clerk.gov/lands-available/")
    assert reasons == [] and path.path_type == "county_instructions" and path.scope == "source"
    assert path.columns()["purchase_url"].endswith("/how-to-purchase") and path.columns()["purchase_path_observed_on"] == "2026-09-30"
    prov = path.provenance()
    assert prov["purchase_evidence_url"] == V2_TAIL[0] and prov["purchase_evidence_type"] == "county_page"
    assert prov["purchase_evidence_title"] == V2_TAIL[2] and prov["purchase_instructions"] == V2_TAIL[3]


def test_e02_verified_non_url_process_creates_a_typed_path_without_a_url(tmp_path):
    rows = PE.load_evidence(_write(tmp_path, ["FL", "fl_laft_pdfs", "*", "phone_mail", "", "The list says to contact the Tax Deeds office by phone or mail to purchase",
                                             "2026-09-30", "yes", "no", "", *V2_TAIL]))
    path, _ = PE.resolve({}, state="FL", source_id="fl_laft_pdfs", county="Marion", registry_row={"verification_status": "PRODUCTION_VERIFIED"}, evidence=rows)
    assert path.path_type == "phone_mail" and "purchase_url" not in path.columns() and path.mode == "phone_mail"


@pytest.mark.parametrize("url", [
    "https://www.example-clerk.gov/",                                   # county homepage
    "https://www.google.com/search?q=lands+available+volusia",          # search result
    "https://www.govease.com/lands/1",                                  # blocked vendor
    "https://www.example-clerk.gov/lands-available/",                   # the list page itself
    "https://www.example-clerk.gov/TaxDeed/Detail/{id}",                # guessed pattern
    "http://www.example-clerk.gov/how-to-purchase",                     # not https
    "https://listings-aggregator.com/volusia",                          # unverified third party
])
def test_e03_forbidden_urls_never_become_paths_even_when_a_row_claims_them(tmp_path, url):
    rows = PE.load_evidence(_write(tmp_path, ["FL", "fl_laft_html", "*", "county_instructions", url, "claimed", "2026-09-30", "yes", "no", "", *V2_TAIL]))
    path, reasons = PE.resolve({}, state="FL", source_id="fl_laft_html", county="Volusia",
                               registry_row={"verification_status": "PRODUCTION_VERIFIED", "canonical_url": "https://www.example-clerk.gov/lands-available/"},
                               evidence=rows, list_url="https://www.example-clerk.gov/lands-available/")
    assert path is None and reasons and "refused" in reasons[0]


def test_e04_insufficient_proof_creates_no_path(tmp_path):
    # needs_review / no evidence page / disabled: loadable, never applicable.
    p = _write(tmp_path, ["FL", "fl_laft_html", "*", "in_person", "", "wording", "2026-09-30", "no", "no", "", *V2_TAIL],
               ["FL", "fl_laft_html", "*", "in_person", "", "wording", "2026-09-30", "no", "no", "", V2_TAIL[0], "county_page", "t", "i", "needs_review", "", ""])
    rows = PE.load_evidence(p)
    assert len(rows) == 2 and not any(r.applicable for r in rows)
    path, reasons = PE.resolve({}, state="FL", source_id="fl_laft_html", county="Volusia", registry_row={"verification_status": "PRODUCTION_VERIFIED"}, evidence=rows)
    assert path is None and reasons == []


def test_e05_lifecycle_carries_evidence_provenance_and_observed_date_onto_the_row(tmp_path):
    ev = _write(tmp_path, ["FL", "fl_laft_html", "*", "phone_mail", "", "Contact the Tax Deeds office to purchase (list header)", "2026-09-28", "yes", "no", "", *V2_TAIL])
    county = next(r.county for r in csr.load_registry() if r.state == "FL" and r.source_id == "fl_laft_html" and r.is_production)
    ctx = L.PathContext(csr.REGISTRY_PATH, "FL", have_023=True, evidence_path=ev, harvest_date="2026-09-30")
    gate = {"status": "COMPLETE", "harvester": "fl_laft_html", "entry": {"source_url": "https://x.gov/list", "source_id": "fl_laft_html"}}
    payload = L.provenance_payload({"county": county, "case_no": "1", "status": "active"}, gate, "2026-09-30T00:00:00+00:00", state="FL", path_ctx=ctx)
    assert payload["purchase_path_type"] == "phone_mail" and payload["purchase_path_observed_on"] == "2026-09-28"   # the evidence date, not the harvest date
    op = payload["otc_provenance"]
    assert op["purchase_evidence_url"] == V2_TAIL[0] and op["purchase_instructions"] == V2_TAIL[3] and op["purchase_path_mode"] == "phone_mail"
    assert "purchase_url" not in payload


def test_e06_committed_evidence_table_rows_are_valid_and_every_enabled_row_is_verified():
    rows = PE.load_evidence()
    for r in rows:
        assert r.state in ("FL", "TX") and r.source_id and r.observed_on
        if r.enabled:
            assert r.applicable and r.evidence_type and r.instructions
            assert not r.url or r.url.startswith("https://")
    # An enabled row must name a source the registry marks production-verified.
    prod = {(r.state, r.source_id) for r in csr.load_registry() if r.is_production}
    assert all((r.state, r.source_id) in prod for r in rows if r.enabled)


# ==================== 3. outcomes and lifecycle honesty ====================

def test_o01_disappearance_is_closed_never_sold_or_redeemed():
    for status in ("closed", "dropped", "notfound"):
        obs = IS.status_for_row({"state": "FL", "source": "laft", "status": status}, today=TODAY)
        assert obs.status == "closed" and obs.basis == "LIST_PRESENCE"
        obs = IS.status_for_row({"state": "FL", "source": "auction", "status": status, "sale_date": "2026-09-01"}, today=TODAY)
        assert obs.status == "closed"
    past = IS.status_for_row({"state": "FL", "source": "auction", "status": "active", "sale_date": "2026-09-01"}, today=TODAY)
    assert past.status == "unknown" and "not distinguishable" in past.note
    with pytest.raises(Exception):
        IS.StatusObservation("sold", "LIST_PRESENCE")       # a result needs the source's own status


def test_o02_writer_never_carries_a_winning_bid_or_party_without_a_source_result():
    rows = [{"id": "a", "state": "FL", "county": "Volusia", "case_no": "1", "source": "auction", "status": "closed", "sale_date": "2026-09-01", "inventory_status": "upcoming"}]
    changes, _ = W.plan(rows, today=TODAY, results={("Volusia", "1"): {"result_amount": 9999.0, "result_party": "Someone"}})
    assert changes[0]["status"] == "closed" and changes[0]["transition"] == "removed" and "result" not in changes[0]
    # An explicit source result (the list's own Sold To column) is accepted, with its fields.
    rows = [{"id": "b", "state": "FL", "county": "Volusia", "case_no": "2", "source": "laft", "status": "active", "inventory_status": "available_otc"}]
    changes, _ = W.plan(rows, today=TODAY, sold={("Volusia", "2")}, results={("Volusia", "2"): {"result_date": "2026-09-20"}})
    assert changes[0]["status"] == "sold" and changes[0]["raw"] == "Sold To" and changes[0]["result"] == {"result_date": "2026-09-20"}


def test_o03_unavailable_or_incomplete_source_closes_nothing():
    def gate(status):
        return {"status": status, "observed_ok": status in L.OBSERVED_STATUSES, "closeout_ok": status in ("COMPLETE", "EMPTY"), "entry": {}}
    gates = {"Volusia": gate("SOURCE_UNAVAILABLE"), "Marion": gate("INCOMPLETE"), "Lee": gate("COMPLETE")}
    db = [{"id": 1, "county": "Volusia", "case_no": "a", "status": "active"}, {"id": 2, "county": "Marion", "case_no": "b", "status": "active"},
          {"id": 3, "county": "Lee", "case_no": "c", "status": "active"}]
    plan = L.plan_lifecycle(gates, {"Volusia": {}, "Marion": {}, "Lee": {}}, db)
    closed = {r["id"] for r in plan.close}
    assert closed == {3}


# ==================== 4. frontend contract ====================

def test_f01_cross_ledger_uses_deterministic_identity_and_current_previous_wording():
    assert 'norm ? `${regionOf(p)}|${String(p.county || "").toLowerCase()}|${norm}` : ""' in APP    # parcelKey: exact state|county|parcel
    block = APP[APP.index("function relatedWhen"):APP.index("function relatedRecordLine")]
    assert "Previously listed" in block and "Currently listed" in block and "isGone(o)" in block
    assert not re.search(r"sold|redeem", block, re.I)
    xl = APP[APP.index("function crossLedgerSummary"):APP.index("// ==================== Available decision page")]
    assert "relatedRecordsFor(p)" in xl and "why a record moved between ledgers is not recorded" in xl


def test_f02_decision_blocks_answer_the_questions_from_fields_and_never_infer_a_result():
    av = APP[APP.index("function availableDecisionHtml"):APP.index("function auctionDecisionHtml")]
    for qid in ("what", "why", "available", "how", "proof", "cost", "where", "known", "unknown", "source", "fresh", "history", "related"):
        assert f'q("{qid}",' in av, qid
    assert "acquisitionHtml(p)" in av and "acquisitionContactHtml(acq)" in av and "dorUseLabel(p.dor_use_code)" in av
    acqb = APP[APP.index("function acquisitionOf"):APP.index("function typedPurchasePath")]
    assert "purchase_evidence_url" in acqb and "purchase_instructions" in acqb
    au = APP[APP.index("function auctionDecisionHtml"):APP.index("function certificateDecisionHtml")]
    for qid in ("what", "when", "bid", "known", "source", "result", "related", "unknown"):
        assert f'q("{qid}",' in au, qid
    assert "p.inventory_status_raw" in au and "Winning bids and bidder counts are never inferred" in au
    ce = APP[APP.index("function certificateDecisionHtml"):APP.index("function inventoryHistoryHtml")]
    for qid in ("what", "amount", "terms", "redemption", "source", "related", "unknown"):
        assert f'q("{qid}",' in ce, qid
    assert "no return is estimated here" in ce
    assert not re.search(r"\b(score|badge|recommend|deal quality)\b", av + au + ce, re.I)


def test_f03_exports_are_customer_fields_only_per_ledger():
    cert = APP[APP.index("const certificateCols = ["):APP.index("const exportCols =")]
    headers = re.findall(r'^\s+\["([^"]+)",', cert, re.M)
    assert "Certificate #" in headers and "Interest Rate (as published)" in headers and "Same Parcel In Other Ledgers" in headers
    for forbidden in ("publication", "provenance", "basis", "harvester_source", "Lien Notes", "Opening Bid", "Fees"):
        assert not any(forbidden.lower() in h.lower() for h in headers), forbidden
    avail = APP[APP.index("const availableCols = ["):APP.index("  const cols = [")]
    ah = re.findall(r'^\s+\["([^"]+)",', avail, re.M)
    assert "Purchase Instructions (published by the source)" in ah and "Purchase Evidence Page" in ah and "First Observed" in ah and "Last Read From Source" in ah
    auction = APP[APP.index("  const cols = ["):APP.index("const certificateCols = [")]
    assert '["Result (per the source)"' in auction and "inventory_status_raw" in auction
    assert 'state.ledger === "laft" ? availableCols : state.ledger === "certificate" ? certificateCols : cols' in APP
    # Withheld inventory never reaches ALL, so it never reaches any export.
    assert "ALL = ALL.filter(p => { if (isPublishable(p)) return true;" in APP


# ==================== 5. contracts that must not move ====================

def test_k01_get_properties_contract_and_ledger_isolation_intact():
    sql = (REPO / "scripts/migrations/023_available_commercial_release.sql").read_text(encoding="utf-8")
    assert "result_amount, result_date, result_party\n  from public.properties" in sql
    assert sorted(p.name for p in (REPO / "scripts/migrations").glob("02*.sql"))[-1] == "023_available_commercial_release.sql"   # no new migration this sprint
    domains.assert_isolated()
    assert (REPO / "public/sw.js").read_text(encoding="utf-8").count('const CACHE = "tdw-shell-v57"') == 1


def test_c03_publication_measurement_counts_a_typed_non_url_path_as_a_purchase_path():
    from harvesters.governance import publication as pub
    rows = [{"source": "laft", "state": "FL", "county": "Citrus", "otc_provenance": {"source_id": "fl_laft_pioneer"}, "purchase_path_type": "phone_mail", "last_seen_at": "2026-09-30T00:00:00+00:00"},
            {"source": "laft", "state": "FL", "county": "Bay", "otc_provenance": {"source_id": "fl_laft_pioneer"}, "purchase_path_type": None, "last_seen_at": "2026-09-30T00:00:00+00:00"}]
    m = pub.measure(rows, {}, now=__import__("datetime").datetime(2026, 9, 30, tzinfo=__import__("datetime").timezone.utc))
    c = m["counts"] if "counts" in m else m
    assert (c["with_purchase_path"], c["without_purchase_path"]) == (1, 1)
