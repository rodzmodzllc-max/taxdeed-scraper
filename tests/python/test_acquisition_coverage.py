"""Acquisition sprint 2 (2026-09-30): verified acquisition evidence and the
deterministic property-to-source match survive a temporary source failure;
the capture job follows only tax-deed links present on the source page; the
commercial metric counts a complete record, not a typed mode."""
from __future__ import annotations

import re
import sys
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from harvesters.governance import county_source_registry as csr  # noqa: E402
import capture_purchase_evidence as CAP  # noqa: E402
import laft_lifecycle as L  # noqa: E402
import purchase_path_engine as PE  # noqa: E402

APP = (REPO / "public/app.js").read_text(encoding="utf-8")
CTX = L.PathContext(csr.REGISTRY_PATH, "FL", have_023=True, harvest_date="2026-09-30")
PROV = {"source_id": "fl_laft_pioneer", "list_url": "https://search.citrusclerk.org/TaxSmartWeb", "document_url": None,
        "harvester": "fl_laft_pioneer", "purchase_url": "none invented"}


def _db(**kw):
    base = {"id": 7, "county": "Citrus", "case_no": "2024-0075TD", "parcel": "19E", "status": "active",
            "last_seen_at": "2026-09-30T04:00:00+00:00", "otc_provenance": dict(PROV)}
    base.update(kw)
    return base


# ==================== 1. temporary failure never erases ====================

def test_c01_unread_row_gets_match_from_its_last_read_and_the_verified_acquisition_record():
    (row_id, payload), = L.carry_plan([_db()], set(), CTX, have_023=True)
    assert row_id == 7
    prov = payload["otc_provenance"]
    sm = prov["source_match"]
    assert sm["identifier"] == "case_no" and sm["value"] == "2024-0075TD" and sm["parcel"] == "19E"
    assert sm["read_at"] == "2026-09-30T04:00:00+00:00" and sm["source"] == PROV["list_url"]
    assert "not read this run" in sm["basis"]
    assert prov["acquisition"]["email"] == "TaxDeeds@CitrusClerk.org" and prov["acquisition"]["observed_on"] == "2026-09-30"
    assert payload["purchase_path_type"] == "phone_mail"
    assert "last_seen_at" not in payload and "status" not in payload        # the row was not read: nothing about freshness changes
    for k in PROV:
        assert prov[k] == PROV[k]                                            # nothing removed or rewritten


def test_c02_existing_match_and_evidence_are_kept_and_an_up_to_date_row_is_not_patched():
    first = L.carry_plan([_db()], set(), CTX, have_023=True)[0][1]
    settled = _db(otc_provenance=first["otc_provenance"], **{k: v for k, v in first.items() if k != "otc_provenance"})
    assert L.carry_plan([settled], set(), CTX, have_023=True) == []
    # A stored match is never replaced by the carry (the read-time one stays).
    stored = dict(first["otc_provenance"], source_match={"identifier": "case_no", "value": "2024-0075TD", "read_at": "2026-09-29T00:00:00+00:00"})
    out = L.carry_plan([_db(otc_provenance=stored, purchase_path_type="phone_mail")], set(), CTX, have_023=True)
    assert not out or out[0][1].get("otc_provenance", stored)["source_match"]["read_at"] == "2026-09-29T00:00:00+00:00"


def test_c03_no_evidence_for_the_county_means_nothing_is_invented_and_nothing_is_erased():
    prov = dict(PROV, source_id="fl_laft_realtdm", acquisition={"mode": "phone", "observed_on": "2026-09-01"})
    rows = [_db(county="Polk", otc_provenance=prov, purchase_path_type="phone_mail")]
    out = L.carry_plan(rows, set(), CTX, have_023=True)
    # Only the deterministic match is added; the existing acquisition record stays untouched (never erased).
    assert len(out) == 1 and set(out[0][1]) == {"otc_provenance"}
    assert out[0][1]["otc_provenance"]["acquisition"] == prov["acquisition"]
    assert "purchase_path_type" not in out[0][1]


def test_c04_observed_closed_never_read_and_unstamped_rows_are_skipped():
    rows = [_db(id=1), _db(id=2, status="closed"), _db(id=3, last_seen_at=None, county="Polk", otc_provenance=dict(PROV, source_id="x")),
            _db(id=4, otc_provenance=None)]
    out = dict(L.carry_plan(rows, {("Citrus", "2024-0075TD")}, CTX, have_023=True))
    assert 1 not in out and 2 not in out and 4 not in out                    # observed this run / closed / never stamped
    assert 3 not in out                                                      # never read: no match, no evidence for source "x"


def test_c04b_unstamped_row_with_a_source_id_receives_its_countys_verified_process_but_no_match():
    # Production 2026-10-06: Pasco's only Available row (fl_laft_pdfs) had no
    # otc_provenance and no last_seen_at, so its county's VERIFIED process
    # never reached it and the customer read "not yet verified".
    row = {"id": 9, "county": "Pasco", "case_no": "2019-TD-1", "parcel": "12-34", "status": "active", "last_seen_at": None,
           "otc_provenance": None, "source_id": "fl_laft_pdfs", "list_url": "https://www.pascoclerk.com/x", "document_url": None}
    (row_id, payload), = L.carry_plan([row], set(), CTX, have_023=True)
    assert row_id == 9
    assert payload["purchase_path_type"] == "phone_mail"
    prov = payload["otc_provenance"]
    assert prov.get("acquisition") and "source_match" not in prov            # never read: no property-to-list match is claimed
    assert "last_seen_at" not in payload and "status" not in payload
    # No evidence for the county: nothing is attached, nothing is written.
    assert L.carry_plan([dict(row, county="Gadsden", source_id="fl_laft_html")], set(), CTX, have_023=True) == []
    # Neither provenance nor a source_id: skipped, exactly as before.
    assert L.carry_plan([dict(row, source_id=None)], set(), CTX, have_023=True) == []


# The production Pasco parse artifact (2026-10-06, read-only): case "2. The"
# and a 465-character run-together parcel. Shape reproduced, text synthetic.
JUNK_PARCEL = ("PARCEL 12-34-56-0010-00100-0010 ESCHEATEDTOCOUNTY " * 10).strip()


def _unstamped(**kw):
    row = {"id": 11, "county": "Pasco", "case_no": "2019-TD-1", "parcel": "12-34-56-0010-00100-0010",
           "status": "active", "last_seen_at": None, "otc_provenance": None, "source_id": "fl_laft_pdfs",
           "list_url": "https://www.pascoclerk.com/x", "document_url": None}
    row.update(kw)
    return row


def test_c04d_legitimate_unstamped_row_receives_its_countys_verified_process():
    (row_id, payload), = L.carry_plan([_unstamped()], set(), CTX, have_023=True)
    assert row_id == 11 and payload["purchase_path_type"] == "phone_mail"
    assert payload["otc_provenance"].get("acquisition")
    # A row with only one of the two identifiers is still a legitimate row.
    assert L.carry_plan([_unstamped(parcel=None)], set(), CTX, have_023=True)
    assert L.carry_plan([_unstamped(case_no="")], set(), CTX, have_023=True)


def test_c04e_malformed_identifier_receives_nothing_and_is_not_touched():
    junk = _unstamped(case_no="2. The", parcel=JUNK_PARCEL)
    before = dict(junk)
    assert len(JUNK_PARCEL) > 400
    assert L.carry_plan([junk], set(), CTX, have_023=True) == []
    assert junk == before                                   # nothing closed, edited or removed
    # Each rule on its own is enough to withhold the county's process.
    for bad in ({"parcel": JUNK_PARCEL},                     # over the parcel length limit
                {"case_no": "2. The"},                       # a single digit is not an identity
                {"parcel": "12-34\n56-78"},                  # spans a line break
                {"parcel": "SEE ATTACHED", "case_no": None}, # no digit
                {"parcel": None, "case_no": None}):          # no identifier at all
        assert L.carry_plan([_unstamped(**bad)], set(), CTX, have_023=True) == [], bad
    assert not L.carry_identifiers_valid(junk)
    assert L.carry_identifiers_valid(_unstamped())


def test_c04f_unavailable_county_evidence_receives_nothing():
    # Hendry's two production rows (identifiers valid, county evidence UNAVAILABLE).
    for case_no, parcel in (("23-09", "2-01-43-29-010-0050-F020"),
                            ("23-09 / Cert 15-2918", "2 29 43 01 010 0050-F02.0")):
        row = _unstamped(county="Hendry", case_no=case_no, parcel=parcel, list_url=None)
        assert L.carry_identifiers_valid(row)
        assert L.carry_plan([row], set(), CTX, have_023=True) == []


def test_c04g_copied_evidence_never_claims_a_county_list_match():
    for row in (_unstamped(), _unstamped(document_url="https://www.pascoclerk.com/list.pdf")):
        (_, payload), = L.carry_plan([row], set(), CTX, have_023=True)
        prov = payload["otc_provenance"]
        assert "source_match" not in prov
        assert "last_seen_at" not in payload and "status" not in payload
        assert prov.get("source_id") in (None, "fl_laft_pdfs")   # evidence from the row's own source only
    other = _unstamped(source_id="fl_laft_html")              # same county, a source with no Pasco evidence
    assert L.carry_plan([other], set(), CTX, have_023=True) == []


def test_c04c_lifecycle_reads_the_row_columns_the_unstamped_carry_needs():
    assert {"source_id", "list_url", "document_url"} <= set(L.CARRY_017_COLUMNS)
    assert set(L.CARRY_017_COLUMNS) <= set(L.CARRY_COLUMNS)


def test_c05_parcel_only_identity_matches_by_parcel_and_no_fuzzy_key_is_ever_used():
    (_, payload), = L.carry_plan([_db(case_no="", parcel="12-34")], set(), CTX, have_023=True)
    assert payload["otc_provenance"]["source_match"]["identifier"] == "parcel"
    src = Path(L.__file__).read_text(encoding="utf-8")
    block = src[src.index("def carry_plan"):src.index("def published_at_from_last_modified")]
    for key in ("owner_name", "address", "latitude", "longitude"):
        assert f'get("{key}")' not in block and f"['{key}']" not in block, key


def test_c06_lifecycle_runs_the_carry_for_every_county_on_record_not_only_this_runs():
    src = Path(L.__file__).read_text(encoding="utf-8")
    assert "counties_all = sorted(set(counties) |" in src and "carry_plan(db_rows, set(plan.observe)" in src
    assert 'counts["carried"]' in src


# ==================== 2. capture follows only present tax-deed links ====================

def test_c07_follow_candidates_are_present_tax_deed_links_on_official_hosts_only():
    page = {"url": "https://clerk.example.gov/lands", "links": [
        {"href": "https://clerk.example.gov/tax-deeds/", "text": "Tax Deeds & Lands Available for Taxes", "same_site": True, "document": False,
         "follow": bool(CAP.FOLLOW_VOCAB.search("Tax Deeds & Lands Available for Taxes"))},
        {"href": "https://clerk.example.gov/passports/application-process/", "text": "Application Process", "same_site": True, "document": False,
         "follow": bool(CAP.FOLLOW_VOCAB.search("Application Process") or CAP.FOLLOW_VOCAB.search("https://clerk.example.gov/passports/application-process/"))},
        {"href": "https://www.google.com/search?q=tax+deed", "text": "tax deed", "same_site": False, "document": False, "follow": True},
        {"href": "https://www.govease.com/tax-deed", "text": "tax deed", "same_site": False, "document": False, "follow": True},
        {"href": "https://clerk.example.gov/lands-available-application.pdf", "text": "Lands Available application", "same_site": True, "document": True, "follow": True},
    ]}
    got = [c["href"] for c in CAP.follow_candidates([page], {page["url"]})]
    assert got == ["https://clerk.example.gov/lands-available-application.pdf", "https://clerk.example.gov/tax-deeds/"]
    assert len(CAP.follow_candidates([page] * 3, set())) <= CAP.MAX_FOLLOW_PER_COUNTY


def test_c08_evidence_job_stays_manual_only_and_passes_follow():
    wf = (REPO / ".github/workflows/harvest-and-sync.yml").read_text(encoding="utf-8")
    job = wf[wf.index("\n  evidence:"):]
    assert "if: github.event_name == 'workflow_dispatch' && github.event.inputs.job == 'evidence'" in job
    assert "--follow" in job and "event_name == 'schedule'" not in job


# ==================== 3. evidence refusals ====================

def test_c09_application_url_is_refused_for_search_engines_vendors_templates_and_http():
    e = PE.load_evidence()[0]
    for bad in ("https://www.google.com/x.pdf", "https://www.govease.com/app.pdf", "http://clerk.gov/app.pdf", "https://clerk.gov/{id}.pdf"):
        assert PE.evidence_problems(replace(e, application_url=bad)), bad
    assert PE.evidence_problems(replace(e, application_url="https://www.brevardclerk.us/lands-available-application.pdf")) == []


# ==================== 4. the metric ====================

def test_c10_a_typed_mode_without_steps_or_a_channel_is_not_a_complete_record():
    rows = [
        {"purchase_path_type": "quoted_amount", "otc_provenance": {}},                                          # typed, no record
        {"purchase_path_type": "amount_plus_costs", "otc_provenance": {"acquisition": {"mode": "multi_step", "steps": ["a", "b", "c"]}}},  # no channel
        {"purchase_path_type": "phone_mail", "otc_provenance": {"acquisition": {"mode": "phone", "steps": ["call"], "phone": "(1) 1"}}},
        {"purchase_path_type": None, "otc_provenance": {}},
    ]
    c = PE.measure(rows)
    assert (c["with_acquisition_path"], c["with_complete_record"], c["acquisition_unverified"]) == (3, 1, 1)
    assert c["pct_with_complete_record"] == 25.0


# ==================== 5. customer page ====================

def test_c11_scope_labels_and_last_verified_freshness_on_the_acquisition_answer():
    block = APP[APP.index("function acquisitionHtml"):APP.index("function typedPurchasePath")]
    assert "Property-specific: the source published this instruction for this parcel." in block
    assert "County process: the county publishes this acquisition process for the properties on its list." in block
    assert "not an approval for this parcel" in block and "does not prove the county will still sell it today" in block
    assert "Acquisition process last verified" in block and "retry pending - this is the last verified process" in block
    assert "First step:" in block
    dec = APP[APP.index("function availableDecisionHtml"):APP.index("function auctionDecisionHtml")]
    assert "Property-specific: this parcel appears on the official county list." in dec


def test_c12_capture_never_records_a_per_property_link_or_a_digit_run():
    html = """<html><head><title>LAFT</title></head><body>
      <a href="https://ptax.example-fl.com/detail?accountNumber=031024257000100080&taxYear=2020">Tax Collector Information</a>
      <a href="/tax-deeds/">Tax Deeds &amp; Lands Available for Taxes</a>
      <p>To purchase property from the list, contact the Tax Deed Division at (352) 555-0100.</p>
      <table><tr><td>Parcel 12-34-56-7890123 Owner Name</td></tr></table></body></html>"""
    out = CAP.extract_html(html, "https://clerk.example.gov/laft")
    assert [l["href"] for l in out["links"]] == ["https://clerk.example.gov/tax-deeds/"]
    assert not any(CAP.LONG_DIGITS.search(sn) for sn in out["snippets"]) and "Owner Name" not in " ".join(out["snippets"])
