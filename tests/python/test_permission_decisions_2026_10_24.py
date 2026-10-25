"""The owner's permission decisions of 2026-10-24, pinned.

1. RealAuction (fl_realauction sale calendar, tx_realauction): collection
   continues unchanged on an internal risk acceptance that records
   RealAuction's refusal (ticket 914220) - never permission.
2. Indian River (every ledger) and Volusia Lands Available: the record owners
   refused reuse in writing. Collection continues pending legal review; the
   records' display is RESTRICTED (the website side is the UI session's).
3. Florida DOR's written response (2026-10-12) is on file and covers the
   statewide parcel data it names (fl_fdor_cadastral).
"""
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from harvesters.governance import permissions as P  # noqa: E402

DAY = date(2026, 10, 25)
LEDGER_OF_SOURCE = {"fl_realauction": "auction", "fl_laft_html": "laft", "fl_laft_pdfs": "laft"}


def perms():
    p = P.Permissions.from_file()
    assert p.error is None, p.error
    return p


# --- 1. RealAuction: risk acceptance, not permission, collection unchanged ---

def test_realauction_is_an_internal_risk_acceptance_that_records_the_refusal():
    p = perms()
    for sid, kw in (("fl_realauction", dict(state="FL", county="Leon", dataset="sale_calendar")),
                    ("tx_realauction", dict(state="TX"))):
        for op in ("fetch", "parse", "store", "display"):
            d = p.authorize(sid, op, today=DAY, **kw)
            assert d.allowed and d.basis == "INTERIM" and not d.documented, (sid, op)
            assert d.evidence_type == "INTERNAL_RISK_ACCEPTANCE", (sid, op)
            assert "ticket 914220" in d.evidence_ref and "NOT permission" in d.reason, (sid, op)
            assert "Collection continues unchanged" in d.reason, (sid, op)
            assert d.expires_on == "2027-04-12"


def test_realauction_authorization_records_say_declined_and_grant_nothing():
    from harvesters.governance import authorization as A
    for rid in ("fl_realauction__county__alachua", "fl_realauction__county__volusia"):
        r = A.PROVIDER_AUTHORIZATIONS[rid]
        assert r.request_status == A.AuthorizationStatus.DECLINED
        assert r.authorization_status not in A.AUTHORIZATION_GRANTED_STATUSES
        assert r.audit_log[-1].event == "declined" and "914220" in r.audit_log[-1].who


# --- 2. Indian River and Volusia: link only ------------------------------------

def test_held_counties_keep_collecting_but_are_never_displayed():
    p = perms()
    cases = [("fl_realauction", "Indian River", "sale_calendar"), ("fl_realauction", "Indian River", "closed_results"),
             ("fl_laft_html", "Indian River", "lands_available"), ("fl_laft_pdfs", "Volusia", "lands_available")]
    for sid, county, ds in cases:
        for op in ("fetch", "parse", "store"):
            d = p.authorize(sid, op, state="FL", county=county, dataset=ds, today=DAY)
            assert d.allowed and d.basis == "INTERIM" and not d.documented, (sid, county, op)
            assert d.evidence_type == "INTERNAL_RISK_ACCEPTANCE" and "legal review" in d.reason
        disp = p.authorize(sid, "display", state="FL", county=county, dataset=ds, today=DAY)
        assert not disp.allowed and disp.reason_code == "RESTRICTED", (sid, county)
        link = p.authorize(sid, "link", state="FL", county=county, today=DAY)
        assert link.allowed and link.basis == "LINK_ONLY", (sid, county)
    assert p.authorize("fl_realauction", "display", state="FL", county="Volusia", dataset="sale_calendar", today=DAY).allowed


def test_no_working_harvester_is_switched_off():
    res = subprocess.run([sys.executable, str(ROOT / "scripts" / "source_permission_check.py"), "--source", "fl_realauction",
                          "--operation", "fetch", "--operation", "parse", "--state", "FL", "--dataset", "sale_calendar",
                          "--list-denied-counties", str(ROOT / "data" / "realauction_counties.csv")],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert res.stdout == ""                     # every RealAuction county is still read
    p = perms()
    for sid, csv_name in (("fl_laft_html", "laft_html_sources.csv"), ("fl_laft_pdfs", "laft_pdf_sources.csv")):
        with (ROOT / "data" / csv_name).open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                d = p.authorize(sid, "fetch", state="FL", county=r["County"], dataset="lands_available", today=DAY)
                assert d.allowed, (sid, r["County"], d.reason_code)
    ps1 = (ROOT / "scripts" / "harvest_all_counties.ps1").read_text(encoding="utf-8")
    loop = ps1[ps1.index(":countyLoop foreach"):]
    assert loop.index("if ($permDeniedCounties -contains $c.County)") < loop.index("& curl")   # guard stays first


def test_every_held_county_has_a_link_and_no_display():
    # The website side (hiding these rows from customers and linking to the
    # Clerk's pages) is the UI session's to build; the records it will read are
    # pinned here: each held unit has a LINK_ONLY record naming an https link
    # and a RESTRICTED display record.
    with (ROOT / "data" / "source_permissions.csv").open(newline="", encoding="utf-8") as f:
        recs = list(csv.DictReader(f))
    links = {(r["source_id"], r["jurisdiction"]): r for r in recs if r["status"] == "LINK_ONLY" and r["source_id"] in LEDGER_OF_SOURCE}
    restricted = {(r["source_id"], r["jurisdiction"]) for r in recs if r["operation"] == "display" and r["status"] == "RESTRICTED"}
    assert set(links) == {("fl_realauction", "FL:Indian River"), ("fl_laft_html", "FL:Indian River"), ("fl_laft_pdfs", "FL:Volusia")}
    assert set(links) <= restricted
    for rec in links.values():
        assert "https://" in rec["reason"]


def test_dor_written_permission_is_on_file_and_covers_the_statewide_data():
    from harvesters.governance import authorization as A
    p = perms()
    doc = ROOT / "docs" / "agreements" / "fl-dor-pto-parcel-data-2026-10-12.md"
    text = doc.read_text(encoding="utf-8")
    assert "There are no restrictions placed on the data." in text and "geodata.floridagio.gov" in text
    assert "@" not in text                      # no e-mail address in the public repository
    for rid in ("fl_dor_pto_parcel_gis__provider__dor_pto", "fl_fdor_cadastral__provider__dor_pto"):
        r = A.PROVIDER_AUTHORIZATIONS[rid]
        assert r.written_permission and r.document.document_location == str(doc.relative_to(ROOT))
        assert r.document.document_hash.removeprefix("sha256:") in text
        assert not r.scope.customer_export.authorized and not r.scope.api_redistribution.authorized
    for ds in ("parcel_attributes", "parcel_centroid"):
        assert p.authorize("fl_fdor_cadastral", "enrich", state="FL", dataset=ds, today=DAY).basis == "DOCUMENTED"
    assert not p.authorize("fl_fdor_cadastral", "redistribute", state="FL", dataset="parcel_attributes", today=DAY).allowed


def test_ugrc_transcript_carries_the_disclaimer_recorded_in_the_register():
    from harvesters.governance import source_approvals as SA
    text = (ROOT / "docs" / "agreements" / "ugrc-parcel-licensing-2026-10-13.md").read_text(encoding="utf-8")
    assert "@" not in text
    disclaimer = SA.get("ut_ugrc_lir_saltlake").disclaimer
    flat = " ".join(l.strip("> -").strip() for l in text.splitlines())
    for sentence in ("provided as a public service for informational purposes only",
                     "You agree that your sole remedy for any dissatisfaction or claims is to discontinue use of the data."):
        assert sentence in disclaimer and sentence in flat
