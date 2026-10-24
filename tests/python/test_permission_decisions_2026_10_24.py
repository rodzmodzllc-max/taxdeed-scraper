"""The owner's permission decisions of 2026-10-24, pinned.

1. RealAuction (fl_realauction sale calendar, tx_realauction): minimal facts
   plus a deep link, on an internal risk acceptance that records RealAuction's
   refusal (ticket 914220) - never permission.
2. Indian River (every ledger) and Volusia Lands Available: link only. The
   record owners refused reuse in writing; nothing is fetched, stored or shown,
   and the website names the county and links to its official pages.
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

from harvesters.governance import minimal_facts as MF  # noqa: E402
from harvesters.governance import permissions as P  # noqa: E402

DAY = date(2026, 10, 25)
LEDGER_OF_SOURCE = {"fl_realauction": "auction", "fl_laft_html": "laft", "fl_laft_pdfs": "laft"}


def perms():
    p = P.Permissions.from_file()
    assert p.error is None, p.error
    return p


# --- 1. RealAuction: minimal facts, risk acceptance, not permission ----------

def test_realauction_is_an_internal_risk_acceptance_that_records_the_refusal():
    p = perms()
    for sid, kw in (("fl_realauction", dict(state="FL", county="Leon", dataset="sale_calendar")),
                    ("tx_realauction", dict(state="TX"))):
        for op in ("fetch", "parse", "store", "display"):
            d = p.authorize(sid, op, today=DAY, **kw)
            assert d.allowed and d.basis == "INTERIM" and not d.documented, (sid, op)
            assert d.evidence_type == "INTERNAL_RISK_ACCEPTANCE", (sid, op)
            assert "ticket 914220" in d.evidence_ref and "NOT permission" in d.reason, (sid, op)
            assert d.expires_on == "2027-04-12"


def test_realauction_authorization_records_say_declined_and_grant_nothing():
    from harvesters.governance import authorization as A
    for rid in ("fl_realauction__county__alachua", "fl_realauction__county__volusia"):
        r = A.PROVIDER_AUTHORIZATIONS[rid]
        assert r.request_status == A.AuthorizationStatus.DECLINED
        assert r.authorization_status not in A.AUTHORIZATION_GRANTED_STATUSES
        assert r.audit_log[-1].event == "declined" and "914220" in r.audit_log[-1].who


def test_minimal_row_keeps_only_sale_facts_and_links_for_realauction():
    row = {"state": "TX", "source": "auction", "county": "Harris", "case_no": "A1", "parcel": "C-1", "address": "1 Main",
           "bid": 10, "min_bid": 10, "assessed": 999, "sale_date": "2026-11-03", "legal_desc": "LOT 1",
           "latitude": 29.7, "longitude": -95.3, "url_auction": "https://x", "url_auction_kind": "sale",
           "tx_sale_status": "Scheduled", "harvester_source": "tx_realauction"}
    kept = MF.minimal_row(row, "tx_realauction")
    assert set(kept) <= MF.MINIMAL_FACT_COLUMNS
    for gone in ("assessed", "legal_desc", "latitude", "longitude"):
        assert gone not in kept
    assert kept["bid"] == 10 and kept["url_auction"] == "https://x"
    # Any other source is untouched (LGBS keeps its own fields).
    assert MF.minimal_row(row, "tx_lgbs") is row


def test_texas_sync_applies_minimal_facts_after_the_ledger_contract():
    text = (ROOT / "scripts" / "sync-texas-to-supabase.py").read_text(encoding="utf-8")
    i_contract = text.index("if LEDGER_RECORDS.problems(row):")
    i_min = text.index("row = MINIMAL_FACTS.minimal_row(row, harvester_source)")
    i_proj = text.index("projected_row = authorized_for_customer_output(row")
    assert i_contract < i_min < i_proj


def test_florida_sync_writes_only_minimal_fact_columns():
    text = (ROOT / "scripts" / "sync-harvest-to-supabase.ps1").read_text(encoding="utf-8")
    block = text[text.index("$rows += [ordered]@{"): text.index("# Every row must belong to the AUCTIONS ledger")]
    keys = set(re.findall(r"^\s{8}([a-z_]+)\s+=", block, flags=re.M))
    assert {"county", "case_no", "parcel", "bid", "sale_date", "url_auction", "url_auction_kind"} <= keys
    assert keys <= MF.MINIMAL_FACT_COLUMNS, keys - MF.MINIMAL_FACT_COLUMNS
    assert "assessed" not in keys


# --- 2. Indian River and Volusia: link only ------------------------------------

def test_link_only_counties_are_restricted_everywhere_but_link():
    p = perms()
    cases = [("fl_realauction", "Indian River", "sale_calendar"), ("fl_realauction", "Indian River", "closed_results"),
             ("fl_laft_html", "Indian River", "lands_available"), ("fl_laft_pdfs", "Volusia", "lands_available")]
    for sid, county, ds in cases:
        for op in ("fetch", "parse", "store", "display"):
            d = p.authorize(sid, op, state="FL", county=county, dataset=ds, today=DAY)
            assert not d.allowed and d.reason_code == "RESTRICTED", (sid, county, op)
            assert d.evidence_type == "PROHIBITION_FOUND"
        link = p.authorize(sid, "link", state="FL", county=county, today=DAY)
        assert link.allowed and link.basis == "LINK_ONLY", (sid, county)
    # Neighbouring counties and Volusia's RealAuction sale calendar are unchanged.
    assert p.authorize("fl_realauction", "fetch", state="FL", county="Brevard", dataset="sale_calendar", today=DAY).allowed
    assert p.authorize("fl_realauction", "fetch", state="FL", county="Volusia", dataset="sale_calendar", today=DAY).allowed
    assert p.authorize("fl_laft_html", "fetch", state="FL", county="Escambia", dataset="lands_available", today=DAY).allowed
    assert p.authorize("fl_laft_pdfs", "fetch", state="FL", county="Brevard", dataset="lands_available", today=DAY).allowed


def test_the_powershell_harvester_skips_exactly_the_denied_counties():
    res = subprocess.run([sys.executable, str(ROOT / "scripts" / "source_permission_check.py"), "--source", "fl_realauction",
                          "--operation", "fetch", "--operation", "parse", "--state", "FL", "--dataset", "sale_calendar",
                          "--list-denied-counties", str(ROOT / "data" / "realauction_counties.csv")],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert res.stdout.split("\n") == ["Indian River", ""]
    ps1 = (ROOT / "scripts" / "harvest_all_counties.ps1").read_text(encoding="utf-8")
    assert "--list-denied-counties" in ps1
    loop = ps1[ps1.index(":countyLoop foreach"):]
    skip = loop.index("if ($permDeniedCounties -contains $c.County)")
    assert skip < loop.index("& curl")          # before any request


def test_html_and_outcome_readers_check_the_county_before_any_request():
    html = (ROOT / "scripts" / "harvest_laft_html.py").read_text(encoding="utf-8")
    loop = html[html.index("for i, src in enumerate(sources, 1):"):]
    assert loop.index('_LS.permission("fl_laft_html", "fetch", county=county)') < loop.index("conditional_get(")
    outcomes = (ROOT / "scripts" / "auction_outcomes.py").read_text(encoding="utf-8")
    loop = outcomes[outcomes.index("for county, iso in days:"):]
    assert loop.index('county=county, dataset="closed_results"') < loop.index("RR.fetch_area(")


def _app_link_only_units() -> list[dict]:
    app = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
    m = re.search(r"var LINK_ONLY_UNITS = (\[.*?\n\]);", app, flags=re.S)
    assert m, "LINK_ONLY_UNITS not found in app.js"
    return json.loads(m.group(1))


def test_the_website_link_only_list_matches_the_permission_records():
    with (ROOT / "data" / "source_permissions.csv").open(newline="", encoding="utf-8") as f:
        recs = [r for r in csv.DictReader(f) if r["status"] == "LINK_ONLY" and r["source_id"] in LEDGER_OF_SOURCE]
    expected = {(r["jurisdiction"].split(":")[0], r["jurisdiction"].split(":")[1], LEDGER_OF_SOURCE[r["source_id"]], r["source_id"])
                for r in recs}
    units = _app_link_only_units()
    assert {(u["state"], u["county"], u["ledger"], u["source_id"]) for u in units} == expected
    by_key = {(r["jurisdiction"], r["source_id"]): r for r in recs}
    for u in units:
        rec = by_key[(f"{u['state']}:{u['county']}", u["source_id"])]
        assert u["links"], u
        for link in u["links"]:
            assert link["url"].startswith("https://") and link["url"] in rec["reason"], (u["county"], link["url"])


# --- 3. DOR: written permission on file, statewide data covered ---------------

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
