"""Acquisition sprint (2026-09-30): for every AVAILABLE property whose source
supports it, a verified, actionable acquisition path backed by the source's
own evidence - online, application, e-mail, phone, mail, in person or a
multi-step county process. Absence stays explicit."""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance import publication as pub  # noqa: E402
import laft_lifecycle as L  # noqa: E402
import purchase_path_engine as PE  # noqa: E402

APP = (REPO / "public/app.js").read_text(encoding="utf-8")
EVIDENCE = PE.load_evidence()
BY_COUNTY = {e.county: e for e in EVIDENCE if e.state == "FL"}


def _row(**kw) -> dict:
    base = {"county": "Citrus", "case_no": "CI-7", "parcel": "1515", "address": "15 Manatee Ln", "bid": 0}
    base.update(kw)
    return base


# ==================== 1. the evidence record carries the actionable process ====================

def test_a01_v3_columns_and_every_committed_row_names_an_office_and_at_least_one_published_channel():
    with open(PE.EVIDENCE_PATH, newline="", encoding="utf-8") as fh:
        assert next(csv.reader(fh)) == PE.EVIDENCE_COLUMNS
    assert PE.EVIDENCE_COLUMNS[-8:] == ["office", "address", "phone", "email", "mailing_address", "steps", "application_url", "payment"]
    # 16 Florida rows + East Baton Rouge LA (property-enrichment sprint, run 36835470121)
    # + Alachua, Duval, Highlands FL and Galveston TX (acquisition-path sprint, run 36858070184).
    assert len(EVIDENCE) == 21 and [(e.state, e.county) for e in EVIDENCE if e.state != "FL"] == [("LA", "East Baton Rouge"), ("TX", "Galveston")]
    for e in EVIDENCE:
        assert e.office, e.county
        # Something a person can act on - or, when the page published no
        # contact the capture can attribute to this process, the row says so
        # and never counts as a complete record (PE.complete_record).
        if not (e.phone or e.email or e.mailing_address or e.address or e.application_url):
            assert "No phone recorded" in e.notes, e.county
            assert not PE.complete_record(PE.PurchasePath(e.path_type, "source", e.evidence, e.observed_on, steps=e.steps, office=e.office).acquisition()), e.county
        assert e.steps and all(len(st) > 20 for st in e.steps), e.county           # the process, as published
        assert PE.evidence_problems(e) == []
        # No invented e-mail: a protected address on a portal page stays blank.
        assert "@" in e.email or e.email == "", e.county
        assert "[email protected]" not in e.email and "[email protected]" not in " ".join(e.steps), e.county


def test_a02_acquisition_mode_is_what_the_customer_does_first():
    m = PE.acquisition_mode
    assert m("none_published", (), ()) == "none"
    assert m("in_person", ("phone", "in_person"), ("a", "b", "c")) == "in_person"     # the source says in person
    assert m("phone_mail", ("email", "phone"), ("a",)) == "email"
    assert m("phone_mail", ("phone",), ("a", "b")) == "phone"
    assert m("phone_mail", ("mail",), ()) == "mail"
    assert m("phone_mail", ("email", "mail"), ("a", "b", "c", "d")) == "multi_step"
    assert m("quoted_amount", ("phone",), ("a",)) == "contact"
    assert m("amount_plus_costs", (), ()) == "contact"
    assert m("direct_property_url", ("online",), ()) == "online"
    assert m("application_download", ("application",), ()) == "application"
    assert m("county_instructions", ("instructions",), ()) == "instructions"
    assert set(PE.ACQUISITION_MODE_LABELS) == set(PE.ACQUISITION_MODES)


def test_a03_the_committed_rows_resolve_to_the_expected_modes_and_channels():
    ctx = L.PathContext(csr.REGISTRY_PATH, "FL", have_023=True, harvest_date="2026-09-30")
    got = {}
    for r in csr.production_rows(csr.load_registry(), "FL"):
        if "AVAILABLE" not in r.ledger_set:
            continue
        path, reasons = ctx.resolve(_row(county=r.county), source_id=r.source_id, county=r.county, list_url=r.canonical_url, document_url=None)
        assert reasons == [], (r.county, reasons)
        if path is not None:
            got[r.county] = (path.acquisition_mode, path.channels)
    assert set(got) == set(BY_COUNTY)
    assert got["Pasco"] == ("multi_step", ("phone", "mail", "in_person"))
    assert got["Brevard"] == ("multi_step", ("email", "mail"))
    assert got["Dixie"][0] == "in_person"
    assert got["Citrus"] == ("email", ("email", "phone", "in_person"))
    assert got["Leon"] == ("email", ("email",))
    assert got["Levy"][0] == "phone" and got["Clay"][0] == "phone"
    for c in ("Calhoun", "Franklin", "Hernando", "Madison", "Sumter", "Taylor", "Volusia", "Orange"):
        assert got[c][0] == "contact", c


# ==================== 2. provenance: the customer sees the record ====================

def test_a04_path_provenance_carries_the_acquisition_record_verbatim():
    path = PE.PurchasePath("phone_mail", "source", "e", "2026-09-30", evidence_url="https://c.gov/lands", source_title="Lands",
                           instructions="Call us", office="Clerk", phone="(000) 000-0000", email="a@b.gov", mailing_address="PO Box 1",
                           steps=("one", "two"), application_url="https://c.gov/app.pdf", payment="certified funds")
    prov = path.provenance()
    acq = prov["acquisition"]
    assert acq["mode"] == "email" and acq["channels"] == ["application", "email", "phone", "mail"]
    for k in ("office", "phone", "email", "mailing_address", "application_url", "payment"):
        assert acq[k] == getattr(path, k)
    assert acq["steps"] == ["one", "two"] and acq["evidence_url"] == "https://c.gov/lands" and acq["observed_on"] == "2026-09-30"
    assert prov["purchase_instructions"] == "Call us"
    # The 023 columns are untouched by the record (no schema change).
    assert set(path.columns()) == {"purchase_path_type", "purchase_path_scope", "purchase_path_evidence", "purchase_path_observed_on"}


def test_a05_lifecycle_writes_source_match_from_the_identity_the_sync_upserts_and_the_acquisition_record(tmp_path):
    gate = {"status": "COMPLETE", "harvester": "fl_laft_pioneer",
            "entry": {"source_url": "https://search.citrusclerk.org/TaxSmartWeb", "source_id": "fl_laft_pioneer"}}
    ctx = L.PathContext(csr.REGISTRY_PATH, "FL", have_023=True, harvest_date="2026-09-30")
    payload = L.provenance_payload(_row(certificate_no="C-77"), gate, "2026-09-30T10:00:00+00:00", state="FL", path_ctx=ctx)
    sm = payload["otc_provenance"]["source_match"]
    assert sm["identifier"] == "case_no" and sm["value"] == "CI-7" and sm["parcel"] == "1515" and sm["certificate_no"] == "C-77"
    assert sm["source"] == "https://search.citrusclerk.org/TaxSmartWeb" and sm["read_at"] == "2026-09-30T10:00:00+00:00"
    acq = payload["otc_provenance"]["acquisition"]
    assert acq["mode"] == "email" and acq["email"] == "TaxDeeds@CitrusClerk.org" and acq["address"].startswith("110 N Apopka Ave")
    assert len(acq["steps"]) == 2
    # A parcel-only list row matches by parcel; a row with neither is no observation.
    p2 = L.provenance_payload({"county": "Citrus", "parcel": "99"}, gate, "2026-09-30T10:00:00+00:00", state="FL", path_ctx=ctx)
    assert p2["otc_provenance"]["source_match"]["identifier"] == "parcel"
    assert L.source_match_of({"county": "Citrus"}, list_url="x", document_url=None, read_at="t") is None


def test_a06_a_county_without_evidence_gets_no_acquisition_record_and_no_match_is_invented():
    gate = {"status": "COMPLETE", "harvester": "fl_laft_html", "entry": {"source_url": "https://x.gov/list", "source_id": "fl_laft_html"}}
    ctx = L.PathContext(csr.REGISTRY_PATH, "FL", have_023=True, harvest_date="2026-09-30")
    payload = L.provenance_payload(_row(county="Putnam", case_no="P-1"), gate, "2026-09-30T00:00:00+00:00", state="FL", path_ctx=ctx)
    assert "purchase_path_type" not in payload and "acquisition" not in payload["otc_provenance"]
    assert payload["otc_provenance"]["source_match"]["value"] == "P-1"        # the listing itself is still deterministic


# ==================== 3. the metrics ====================

def test_a07_measure_reports_source_listing_match_and_acquisition_coverage_by_mode():
    rows = [
        {"purchase_path_type": "phone_mail", "purchase_path_scope": "source", "last_seen_at": "t", "list_as_of": "2026-09-01",
         "otc_provenance": {"list_url": "https://l", "source_match": {"identifier": "case_no", "value": "1"},
                            "acquisition": {"mode": "email", "email": "a@b.gov", "steps": ["x"]}}},
        {"purchase_path_type": "in_person", "purchase_path_scope": "source", "otc_provenance": {"document_url": "https://d.pdf", "acquisition": {"mode": "in_person"}}},
        {"purchase_path_type": None, "otc_provenance": {"list_url": "https://l"}},
        {"purchase_path_type": "none_published", "purchase_path_scope": "source", "otc_provenance": {}},
    ]
    c = PE.measure(rows)
    assert (c["rows"], c["with_source_listing"], c["with_source_match"], c["with_acquisition_path"], c["acquisition_unverified"]) == (4, 3, 1, 2, 2)
    assert c["by_mode"] == {"email": 1, "in_person": 1} and c["with_contact"] == 1 and c["with_steps"] == 1
    assert c["with_direct_document"] == 1 and c["with_source_date"] == 1 and c["with_last_verified"] == 1
    assert c["pct_with_acquisition_path"] == 50.0 and c["pct_with_source_listing"] == 75.0


def test_a08_publication_measurement_counts_an_offline_process_as_a_purchase_path():
    rows = [{"source": "laft", "state": "FL", "county": "Dixie", "otc_provenance": {"source_id": "fl_laft_html"}, "purchase_path_type": "in_person", "last_seen_at": "2026-09-30T00:00:00+00:00"}]
    m = pub.measure(rows, {}, now=__import__("datetime").datetime(2026, 9, 30, tzinfo=__import__("datetime").timezone.utc))
    c = m["counts"] if "counts" in m else m
    assert c["with_purchase_path"] == 1


# ==================== 4. the frontend contract ====================

def test_a09_frontend_labels_mirror_the_engine_and_absence_wording_is_never_no_link():
    m = re.search(r"const ACQUISITION_MODE_LABELS = \{(.*?)\n\};", APP, re.S).group(1)
    keys = set(re.findall(r'^\s*([a-z_]+): "', m, re.M)) | set(re.findall(r', ([a-z_]+): "', m))
    assert keys == set(PE.ACQUISITION_MODES)
    for k, v in PE.ACQUISITION_MODE_LABELS.items():
        assert f'{k}: "{v}"' in m, k
    block = APP[APP.index("function acquisitionOf"):APP.index("function typedPurchasePath")]
    assert "Not yet verified" in block and "No online purchase link" not in block
    assert 'href="tel:' in block and 'href="mailto:' in block and "acq-steps" in block
    dec = APP[APP.index("function availableDecisionHtml"):APP.index("function auctionDecisionHtml")]
    for qid in ("why", "how", "contact", "proof", "source", "fresh", "history", "related", "unknown"):
        assert f'q("{qid}",' in dec, qid
    assert '"How do I acquire it?"' in dec and '"Who do I contact, and where do I go?"' in dec
    assert "source_match" in dec and "List document (PDF / file)" in dec
    gaps = APP[APP.index("function dataGaps"):APP.index("function opportunitySummaryHtml")]
    assert "Acquisition path not yet verified" in gaps and "Purchase link not on file" not in gaps
    cols = APP[APP.index("const availableCols = ["):APP.index("const cols = [")]
    for h in ("Acquisition Path", "Acquisition Steps (published by the source)", "County Office", "County Phone", "County E-mail",
              "County Address (in person)", "County Mailing Address", "Application / Instructions Document", "Matched To Source By"):
        assert f'["{h}"' in cols, h
    assert (REPO / "public/sw.js").read_text(encoding="utf-8").count('const CACHE = "tdw-shell-v73"') == 1
    for f in ("app.js", "styles.css", "sw.js"):
        assert (REPO / f).read_bytes() == (REPO / "public" / f).read_bytes(), f
