"""Acquisition-path sprint (2026-10-01): the acquisition path is ENRICHMENT,
never a publication decision. Publication stays the source decision
(publication_status); each part of the acquisition record - listing, match,
path, evidence page, last-verified date - is measured independently and a
missing part reads "Not yet verified". Texas rows (LGBS, no lifecycle read)
get their county-level record from scripts/apply_acquisition_paths.py."""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import apply_acquisition_paths as A  # noqa: E402
import capture_purchase_evidence as C  # noqa: E402
import laft_lifecycle as L  # noqa: E402
import publication_gate as G  # noqa: E402
import purchase_path_engine as PE  # noqa: E402

APP = (REPO / "public/app.js").read_text(encoding="utf-8")
WORKFLOW = (REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")

REG = {("tx_lgbs", "Galveston"): {"canonical_url": "https://taxsales.lgbs.com/", "verification_status": "PRODUCTION_VERIFIED",
                                  "last_checked": "2026-09-23", "state": "TX", "source_id": "tx_lgbs", "county": "Galveston"}}


def _ev(**kw) -> PE.EvidenceRow:
    base = dict(state="TX", source_id="tx_lgbs", county="Galveston", path_type="county_instructions",
                url="https://www.galvestoncountytx.gov/our-county/tax-assessor-collector/property-tax/sheriff-sale-information",
                evidence="County page: struck-off property is re-offered at future Sheriff Sales", observed_on="2026-10-01",
                enabled=True, third_party_permitted=True, evidence_url="https://www.galvestoncountytx.gov/our-county/tax-assessor-collector/property-tax/sheriff-sale-information",
                evidence_type="county_page", source_title="Sheriff Sale Information", review_state="verified",
                office="Tax Assessor-Collector", phone="409-766-2481", steps=("Watch for the next Sheriff's resale", "Bid at the sale"))
    base.update(kw)
    return PE.EvidenceRow(**base)


def _tx(**kw) -> dict:
    base = {"id": "r1", "state": "TX", "county": "Galveston", "source": "laft", "source_id": "tx_lgbs", "harvester_source": "tx_lgbs",
            "case_no": "129500040015000", "parcel": "23-TX-0644", "status": "active", "list_url": None, "document_url": None,
            "purchase_url": None, "purchase_path_type": None, "purchase_path_scope": None, "otc_provenance": None}
    base.update(kw)
    return base


def _published(**kw) -> dict:
    row = {"source": "laft", "list_url": "https://clerk.example.gov/laft", "purchase_path_type": "phone_mail", "purchase_path_observed_on": "2026-10-01",
           "otc_provenance": {"source_match": {"identifier": "case_no", "value": "A-1"}, "purchase_evidence_url": "https://clerk.example.gov/how"}}
    row.update(kw)
    return row


# 1. A Texas row with a verified county record gets listing, match and path from county-level evidence.
def test_g01_texas_row_inherits_the_county_level_record_with_listing_and_match():
    payload, outcome = A.plan_row(_tx(), registry=REG, evidence=[_ev()], state="TX", today="2026-10-01")
    assert outcome == "path"
    assert payload["list_url"] == "https://taxsales.lgbs.com/"
    assert payload["purchase_path_type"] == "county_instructions" and payload["purchase_path_scope"] == "source"
    assert payload["purchase_url"].startswith("https://www.galvestoncountytx.gov/") and payload["purchase_path_observed_on"] == "2026-10-01"
    prov = payload["otc_provenance"]
    assert prov["source_match"] == {"identifier": "case_no", "value": "129500040015000", "parcel": "23-TX-0644", "source": "https://taxsales.lgbs.com/",
                                    "basis": prov["source_match"]["basis"], "read_at": "2026-09-23"}
    assert "last successful source read 2026-09-23" in prov["source_match"]["basis"]
    assert prov["purchase_evidence_url"].startswith("https://www.galvestoncountytx.gov/") and prov["acquisition"]["steps"]
    full = dict(_tx(), **payload)
    assert PE.acquisition_gaps(full) == []


# 2. A county with no verified evidence gets its listing and match, no path - and stays published.
def test_g02_no_verified_evidence_means_no_path_but_the_row_stays_published():
    payload, outcome = A.plan_row(_tx(county="Goliad"), registry={("tx_lgbs", "Goliad"): dict(REG[("tx_lgbs", "Galveston")], county="Goliad")},
                                  evidence=[_ev()], state="TX", today="2026-10-01")
    assert outcome == "no_verified_evidence"
    assert "purchase_path_type" not in payload and "purchase_url" not in payload
    full = dict(_tx(county="Goliad"), **payload)
    assert PE.acquisition_gaps(full) == ["no_acquisition_path", "no_evidence_page", "no_verified_date"]
    assert PE.acquisition_state(full) == "source_only"                       # official source link, path not yet verified
    assert "publication_status" not in payload                                # publication is never touched


# 3. An evidence row that is not verified never becomes a path.
def test_g03_an_unverified_evidence_row_is_never_applied():
    for bad in (_ev(review_state="needs_review"), _ev(enabled=False), _ev(evidence_url="")):
        payload, outcome = A.plan_row(_tx(), registry=REG, evidence=[bad], state="TX", today="2026-10-01")
        assert outcome == "no_verified_evidence" and "purchase_path_type" not in (payload or {})


# 4. Search engines, blocked vendors and bare homepages are refused as purchase links.
@pytest.mark.parametrize("url,why", [
    ("https://www.google.com/search?q=galveston+struck+off", "untrusted host"),
    ("https://taxsales.lgbs.com/map", "untrusted host"),
    ("https://www.pbfcm.com/taxsale.html", "untrusted host"),
    ("https://www.galvestoncountytx.gov/", "a bare homepage"),
    ("https://www.galvestoncountytx.gov/buy/{parcel}", "guessed URL"),
])
def test_g04_untrusted_and_guessed_urls_are_refused(url, why):
    reason = PE.rejection_reason(url, canonical_url="https://taxsales.lgbs.com/", list_url="https://taxsales.lgbs.com/", document_url=None,
                                 third_party_permitted=True)
    assert reason and why in reason


# 5. No property-specific URL is ever invented from county evidence.
def test_g05_county_evidence_never_produces_a_property_scope_or_property_url():
    payload, _ = A.plan_row(_tx(), registry=REG, evidence=[_ev()], state="TX", today="2026-10-01")
    assert payload["purchase_path_scope"] == "source" and payload["purchase_url_kind"] == "purchase_instructions"
    assert "129500040015000" not in payload["purchase_url"] and "23-TX-0644" not in payload["purchase_url"]
    with pytest.raises(ValueError):
        # direct_property_url is property-scope: the evidence table can never carry one.
        problems = PE.evidence_problems(_ev(path_type="direct_property_url"))
        raise ValueError("; ".join(problems))


# 6. Stronger evidence is never overwritten by weaker.
def test_g06_a_stored_property_scope_path_is_kept():
    row = _tx(purchase_path_type="direct_property_url", purchase_path_scope="property", purchase_url="https://www.galvestoncountytx.gov/bid/1",
              otc_provenance={"source_match": {"value": "x"}, "list_url": "https://taxsales.lgbs.com/"})
    payload, outcome = A.plan_row(row, registry=REG, evidence=[_ev()], state="TX", today="2026-10-01")
    assert outcome in ("kept_stronger_property_path", "kept_stronger_property_path_unchanged")
    assert "purchase_path_type" not in (payload or {}) and "purchase_url" not in (payload or {})


# 7. Existing provenance is kept; only the path / match keys change; nothing else is touched.
def test_g07_existing_provenance_is_kept_and_no_lifecycle_columns_are_written():
    row = _tx(otc_provenance={"inventory_type": "kept", "source_match": {"identifier": "case_no", "value": "keep-me"}})
    payload, _ = A.plan_row(row, registry=REG, evidence=[_ev()], state="TX", today="2026-10-01")
    assert payload["otc_provenance"]["inventory_type"] == "kept" and payload["otc_provenance"]["source_match"]["value"] == "keep-me"
    assert not set(payload) & {"last_seen_at", "status", "bid", "min_bid", "purchase_amount", "owner_name", "result_amount", "result_party"}
    # Idempotent: applying the same record twice changes nothing.
    again, outcome = A.plan_row(dict(row, **payload), registry=REG, evidence=[_ev()], state="TX", today="2026-10-01")
    assert again is None and outcome == "path_unchanged"


# 8. The five independently measured parts, and the frontend mirrors them exactly.
def test_g08_acquisition_gaps_and_frontend_parity_and_no_withholding():
    assert PE.acquisition_gaps(_published()) == []
    assert PE.acquisition_gaps({"source": "auction"}) == []
    assert PE.acquisition_gaps(_published(list_url=None)) == ["no_source_listing"]
    assert PE.acquisition_gaps(_published(otc_provenance={"purchase_evidence_url": "https://e"})) == ["no_source_match"]
    assert PE.acquisition_gaps(_published(purchase_path_type="none_published")) == ["no_acquisition_path"]
    assert PE.acquisition_gaps(_published(purchase_path_observed_on=None)) == ["no_verified_date"]
    url_row = _published(purchase_path_type="county_instructions", purchase_url="https://clerk.example.gov/how",
                         otc_provenance={"source_match": {"value": "A-1"}})
    assert PE.acquisition_gaps(url_row) == []
    m = re.search(r"const ACQUISITION_GAP_REASONS = \{(.*?)\n\};", APP, re.S).group(1)
    js = dict(re.findall(r'(\w+): "([^"]+)"', m))
    assert js == PE.ACQUISITION_GAP_REASONS
    # Publication is the source decision only: the customer filter never consults the acquisition record.
    assert "ALL = ALL.filter(p => { if (isPublishable(p)) return true; if (p.source in WITHHELD) WITHHELD[p.source]++; return false; });" in APP
    assert "acquisitionGap" not in re.search(r"function isPublishable\(p\) \{(.*?)\n\}", APP, re.S).group(1)
    assert "WITHHELD_ACQ" not in APP and "ledgerWithheldAcq" not in APP and "acquisitionGate" not in APP
    assert PE.acquisition_state(_published()) == "partial"                   # a path without steps: partial, still a path


# 9. Truthful CTA labels only - every label names what the link is.
def test_g09_cta_labels_are_the_truthful_set():
    fn = re.search(r"function acquisitionCta\(a\) \{(.*?)\n\}", APP, re.S).group(1)
    labels = set(re.findall(r'label: "([^"]+)"', fn))
    assert labels == {"Open county acquisition page", "Start application", "Download application", "View purchase instructions",
                      "Contact county to purchase"}
    avail = re.search(r"function availabilityLink\(p\) \{(.*?)\n\}", APP, re.S).group(1)
    assert "View official availability" in avail and "delinquent-tax counsel" in avail
    block = re.search(r"function acquireBlockHtml\(p\) \{(.*?)\n\}\n", APP, re.S).group(1)
    for heading in ("Why this property is available", "How to acquire", '"Method"', '"Official source"', '"Last verified"',
                    '"Acquisition path"', '"Official availability source"', "Open official source", "See the official source for current instructions.",
                    '"Additional acquisition details"', "Not yet verified"):
        assert heading in block, heading
    assert not re.search(r"\b(score|badge|recommend|AI)\b", block)


# 10. A run whose status entry carries no list date never writes NULL over a stored one.
def test_g10_lifecycle_never_writes_null_dates():
    p = L.provenance_payload({"county": "East Baton Rouge", "case_no": "A"}, {"harvester": "la_ebr_adjudicated", "entry": {}}, "2026-10-01T00:00:00+00:00")
    assert "list_as_of" not in p and "source_published_at" not in p
    assert "kept" in p["otc_provenance"]["list_as_of"]


# --- wiring: report, workflow, candidate capture ---------------------------------------------

def test_g11_coverage_report_separates_inventory_from_acquisition_enrichment():
    complete = _published(county="Bay", source_id="x", purchase_path_type="county_instructions", purchase_url="https://clerk.example.gov/how",
                          otc_provenance={"source_match": {"value": "A-1"}, "acquisition": {"steps": ["Apply"], "phone": "1"}})
    rows = [complete, _published(county="Bay", source_id="x"), dict(_tx(), list_url="https://taxsales.lgbs.com/", publication_status="APPROVED_GRANDFATHERED"),
            dict(_tx(), publication_status=None), dict(_tx(status="closed"))]
    rep = G.acquisition_coverage_report(rows)
    assert {k: rep[k] for k in ("verified_inventory", "published", "with_acquisition_path", "without_acquisition_path",
                                "with_direct_acquisition_url", "official_source_only", "partial_process", "not_yet_verified")} == \
        {"verified_inventory": 4, "published": 4, "with_acquisition_path": 2, "without_acquisition_path": 2,
         "with_direct_acquisition_url": 1, "official_source_only": 1, "partial_process": 1, "not_yet_verified": 2}
    assert rep["without_path_by_county"] == {"Galveston (tx_lgbs)": 2}
    assert "withheld" not in json.dumps(rep)


def test_g12_texas_step_makes_no_source_request_and_is_never_the_lgbs_harvest():
    step = WORKFLOW.split("Texas - acquisition paths from verified county evidence")[1].split("\n  expansion:")[0]
    assert "apply_acquisition_paths.py --state TX --source-id tx_lgbs" in step and "continue-on-error: true" in step
    assert "texas_harvester" not in step and "lgbs.com" not in step
    src = (REPO / "scripts/apply_acquisition_paths.py").read_text(encoding="utf-8")
    assert "requests" not in src and "texas_harvester" not in src


def test_g13_candidate_pages_are_https_official_and_never_blocked_vendors():
    rows = C.candidate_rows()
    assert rows and {r["state"] for r in rows} == {"FL", "TX"}
    for r in rows:
        host = re.sub(r"^https://([^/]+)/.*$", r"\1", r["url"] + "/")
        assert r["url"].startswith("https://") and not C.NEVER_FOLLOW.search(host + "."), r
        assert not re.search(r"google|bing|lgbs|pbfcm|mvba|ctsa|govease", r["url"], re.I)
    assert "acquisition_candidates" in WORKFLOW and "--candidates --follow" in WORKFLOW


def test_g14_committed_evidence_from_the_candidate_capture():
    by = {(e.state, e.county): e for e in PE.load_evidence()}
    exp = {("FL", "Alachua"): ("fl_laft_realtdm", "quoted_amount", "(352) 374-3615", "taxdeeds@alachuaclerk.org"),
           ("FL", "Duval"): ("fl_laft_pioneer", "phone_mail", "", "Ask.TaxDeeds@DuvalClerk.com"),
           ("FL", "Highlands"): ("fl_laft_realtdm", "quoted_amount", "(863) 402-6565", "clkbustd@hcclerk.org"),
           ("TX", "Galveston"): ("tx_lgbs", "county_instructions", "(409) 766-2312", "")}
    for key, (sid, ptype, phone, email) in exp.items():
        e = by[key]
        assert (e.source_id, e.path_type, e.phone, e.email, e.observed_on) == (sid, ptype, phone, email, "2026-10-01"), key
        assert "run 36858070184" in e.notes and e.review_state == "verified" and e.steps, key
    assert by[("FL", "Duval")].application_url.endswith("392460_2_Land-s-Available-Request-Form.pdf")
    # Counties whose official pages published no acquisition process stay without a row (fail closed).
    for key in [("FL", c) for c in ("Bay", "Hillsborough", "Indian River", "Miami-Dade", "Polk", "Putnam", "St. Lucie", "Escambia",
                                    "Hendry", "Lee", "Osceola", "Palm Beach", "Sarasota", "Gadsden")] + \
               [("TX", c) for c in ("Liberty", "Leon", "Maverick", "Jim Wells", "Hardin", "Van Zandt", "Goliad")]:
        assert key not in by, key
