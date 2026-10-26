"""data/county_source_registry.csv + harvesters/governance/county_source_registry.py."""
from __future__ import annotations

import csv
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from harvesters.governance import county_source_registry as csr  # noqa: E402
from harvesters.governance.source_catalog import load_fl_matrix, load_tx_matrix  # noqa: E402
import build_county_source_registry as builder  # noqa: E402

ROWS = csr.load_registry()
KNOWN = {"FL": frozenset(r["county"] for r in load_fl_matrix()), "TX": frozenset(r["county"] for r in load_tx_matrix())}


def test_r01_registry_is_valid_and_matches_its_generator():
    assert csr.validate_registry(ROWS, known_counties=KNOWN) == []
    assert (REPO / "data/county_source_registry.csv").read_text(encoding="utf-8") == builder.render(builder.build_rows())


def test_r02_every_florida_county_has_exactly_one_row_and_52_are_production():
    # Per ledger (2026-09-30): every FL county has exactly ONE AVAILABLE-ledger
    # row; the AUCTIONS and LIENS & CERTIFICATES rows sit beside them.
    fl = [r for r in ROWS if r.state == "FL"]
    avail = [r for r in fl if "AVAILABLE" in r.ledger_set or not r.ledger_set]
    assert len(fl) == 147 and len(avail) == 67 and len({r.county for r in avail}) == 67 and len({r.county for r in fl}) == 67
    prod = [r for r in csr.production_rows(ROWS, "FL") if "AVAILABLE" in r.ledger_set]
    # 52 until 2026-10-26, when Lake (realTDM), DeSoto and Wakulla (static HTML) and Charlotte (clerk portal) joined.
    assert len(prod) == 52 + len(builder.FL_ADDED_2026_10_26) == 56
    assert csr.expected_harvest_units(ROWS) == sorted((r.source_id, r.county) for r in prod)
    assert {r.source_id for r in prod} == {"fl_laft_pdfs", "fl_laft_html", "fl_laft_pioneer", "fl_laft_realtdm",
                                           "fl_laft_orange", "fl_laft_stlucie", "fl_laft_osceola", "fl_laft_hillsborough", "fl_laft_leon",
                                           "fl_laft_portals"}
    added = [r for r in prod if r.county in builder.FL_ADDED_2026_10_26]
    assert {r.county for r in added} == {"Lake", "DeSoto", "Wakulla", "Charlotte"}
    # Publication is decided per SOURCE: a county added to an existing platform source carries its decision;
    # the new clerk-portal source is published by the owner's 2026-10-26 decision (legal review pending).
    for r in added:
        assert r.publication_status == ("APPROVED" if r.source_id == "fl_laft_portals" else "APPROVED_GRANDFATHERED"), r.county
        if r.source_id == "fl_laft_portals":
            assert r.restrictions.startswith("Owner approved customer publication 2026-10-26; legal review pending")


def test_r03_production_rows_mirror_the_harvester_csvs_exactly():
    def names(path, col="County"):
        with open(REPO / "data" / path, newline="", encoding="utf-8") as fh:
            return {r[col] for r in csv.DictReader(fh)}
    by_source = {}
    for r in csr.production_rows(ROWS, "FL"):
        by_source.setdefault(r.source_id, set()).add(r.county)
    assert by_source["fl_laft_pdfs"] == names("laft_pdf_sources.csv")
    assert by_source["fl_laft_html"] == names("laft_html_sources.csv")
    assert by_source["fl_laft_pioneer"] == names("laft_pioneer_counties.csv")
    assert by_source["fl_laft_realtdm"] == names("laft_realtdm_counties.csv")
    for single in ("orange", "stlucie", "osceola", "hillsborough", "leon"):
        assert len(by_source[f"fl_laft_{single}"]) == 1
    # Every production row's document/canonical URL is the harvester's own registered URL.
    with open(REPO / "data/laft_pdf_sources.csv", newline="", encoding="utf-8") as fh:
        for src in csv.DictReader(fh):
            row = csr.lookup(ROWS, "FL", src["County"], "fl_laft_pdfs")
            assert row.document_url == src["Url"] and row.canonical_url == src["SourcePage"]
            assert row.source_authority == ("GOVERNMENT_PLATFORM" if "azurewebsites" in src["Url"] else "GOVERNMENT_DIRECT")


def test_r04_candidates_are_never_runnable_and_blocked_vendors_carry_no_url():
    for r in ROWS:
        if not r.is_production:
            assert not r.runnable and not r.harvester, r
            assert r.completeness_status == "UNKNOWN", r
        if r.source_id in csr.BLOCKED_SOURCE_IDS:
            assert r.governance_status == "BLOCKED" and r.canonical_url == "" and r.verification_status == "BLOCKED_VENDOR_ONLY", r
    fl_cands = {r.county: r.verification_status for r in ROWS if r.state == "FL" and not r.is_production}
    # Re-checked live 2026-10-26: Lake, DeSoto, Wakulla and Charlotte moved to production; the pages
    # of eight more were read and publish no Lands Available list.
    assert fl_cands == {
        "Broward": "SEARCH_EVIDENCE_ONLY", "Baker": "SOURCE_EXISTS_ACCESS_UNKNOWN", "Jefferson": "HISTORICAL_ONLY",
        "Okaloosa": "NOT_FOUND_AFTER_SEARCH", "Collier": "NOT_FOUND_AFTER_SEARCH", "Gilchrist": "NOT_FOUND_AFTER_SEARCH",
        "Monroe": "NOT_FOUND_AFTER_SEARCH", "Nassau": "NOT_FOUND_AFTER_SEARCH", "Suwannee": "NOT_FOUND_AFTER_SEARCH",
        "Jackson": "NOT_FOUND_AFTER_SEARCH", "Liberty": "NOT_FOUND_AFTER_SEARCH",
    }


def test_r05_texas_rows_are_lgbs_production_search_candidates_or_blocked_only():
    tx = [r for r in ROWS if r.state == "TX"]
    VENDORS = {"tx_pbfcm", "tx_mvba", "tx_govease"}  # unblocked by the owner's decision of 2026-10-26
    county_ids = {"tx_hctax", "tx_bexar_resale", "tx_jefferson_sheriff_sale", "tx_montgomery_tax_trust",
                  "tx_orange_trust_property", "tx_trinity_cad_resale", "tx_randall_trustee_property", "tx_hood_cad_struck_off"}
    prod = [r for r in tx if r.is_production and "AVAILABLE" in r.ledger_set and r.source_id not in VENDORS | county_ids]
    assert {r.county for r in prod} == {"Galveston", "Liberty", "Leon", "Maverick", "Jim Wells", "Hardin", "Van Zandt", "Goliad"}
    assert all(r.source_id == "tx_lgbs" and r.source_authority == "VENDOR_COUNSEL" and r.inventory_type == "" for r in prod)
    # The AUCTIONS-only production rows (2026-09-30) are the 24 RealAuction counties.
    auctions_only = [r for r in tx if r.is_production and "AVAILABLE" not in r.ledger_set and r.source_id not in VENDORS | county_ids]
    assert len(auctions_only) == 24 and all(r.source_id == "tx_realauction" and r.ledger_set == {"AUCTIONS"} for r in auctions_only)
    # The vendor rows mirror data/tx_vendor_counties.csv (the live roster of 2026-10-26): production
    # verified, APPROVED_GRANDFATHERED, the owner's decision in their restrictions.
    import csv
    with open(REPO / "data/tx_vendor_counties.csv", newline="", encoding="utf-8") as fh:
        roster = {(r["source_id"], r["county"]) for r in csv.DictReader(fh)}
    vend = [r for r in tx if r.source_id in VENDORS]
    assert {(r.source_id, r.county) for r in vend} == roster and len(roster) == 61
    assert all(r.is_production and r.publication_status == "APPROVED_GRANDFATHERED"
               and "Owner decision 2026-10-26" in r.restrictions for r in vend)
    cands = [r for r in tx if r.verification_status == "SEARCH_EVIDENCE_ONLY"]
    assert len(cands) == 14 and all(r.inventory_type == "" and r.source_authority == "GOVERNMENT_DIRECT" for r in cands)
    # 2026-10-26: county lists read live by scripts/harvest_tx_county_sales.py, synced by
    # scripts/sync_state_inventory.py and published by the owner's decision (legal review pending).
    read = [r for r in tx if r.source_id in county_ids]
    assert sorted(r.source_id for r in read) == sorted(s[1] for s in builder.TX_COUNTY_SOURCES)
    assert all(r.is_production and r.runnable and r.harvester == "scripts/harvest_tx_county_sales.py"
               and r.governance_status == "APPROVED" and r.publication_status == "APPROVED"
               and r.source_authority == "GOVERNMENT_DIRECT" for r in read)
    assert {r.source_id for r in read if r.ledger_set == {"AUCTIONS"}} == {"tx_hctax", "tx_jefferson_sheriff_sale"}
    assert all(r.inventory_type == "STRUCK_OFF_HELD_IN_TRUST" for r in read if r.ledger_set == {"AVAILABLE"})
    harris = csr.lookup(ROWS, "TX", "Harris", "tx_hctax")
    assert harris.restrictions.startswith("Owner approved customer publication 2026-10-26; legal review pending")
    # No blocked-vendor-only rows remain; tx_ctsa (still blocked) has none and no URL anywhere.
    assert [r for r in tx if r.verification_status == "BLOCKED_VENDOR_ONLY"] == []
    assert not any("countytaxsaleapp" in r.canonical_url for r in ROWS)


def test_r06_validator_catches_the_dangerous_shapes():
    base = dict(state="FL", county="Marion", source_id="fl_laft_pdfs", harvester="x.py", inventory_type="POST_SALE_FIXED_PRICE",
                source_authority="GOVERNMENT_DIRECT", canonical_url="https://m", document_url="", purchase_url="", purchase_url_kind="",
                access_method="HTTP_GET_PDF", machine_format="PDF", verification_status="PRODUCTION_VERIFIED",
                governance_status="APPROVED_GRANDFATHERED", last_checked="2026-09-29", completeness_status="COMPLETE",
                evidence_ref="e", notes="")
    assert csr.validate_row(csr.CountySourceRow(**base), known_counties=KNOWN) == []
    bad = [
        dict(verification_status="SEARCH_EVIDENCE_ONLY"),                      # candidate naming a harvester + completeness
        dict(governance_status="LEGAL_REVIEW_REQUIRED"),                        # production under legal review
        dict(source_id="tx_ctsa"),                                              # blocked vendor with URL / not BLOCKED
        dict(canonical_url="http://m"),                                         # non-https
        dict(purchase_url="https://m/form"),                                    # url without kind
        dict(county="Atlantis"),                                                # unknown county
        dict(inventory_type="MAYBE"),                                           # out of vocabulary
        dict(verification_status="PRODUCTION_VERIFIED", harvester=""),          # production without harvester
    ]
    for change in bad:
        assert csr.validate_row(csr.CountySourceRow(**{**base, **change}), known_counties=KNOWN), change
    with pytest.raises(ValueError):
        csr.load_registry(REPO / "data/laft_pdf_sources.csv")


def test_r07_to_db_rows_uses_nulls_and_the_migration_018_column_set():
    # The live (018) shape is the FL/TX county rows; the Alabama, Arkansas
    # and Louisiana candidates (2026-09-29/30) are refused by the 018 bridge
    # and need 020; so do the six six-state-expansion rows (2026-09-30) and the
    # five five-state-sprint rows (2026-10-01).
    fl_tx = [r for r in ROWS if r.state in ("FL", "TX")]
    rows = csr.to_db_rows(fl_tx)
    # New-sources sprint (2026-10-26): every registry row it added is outside FL / TX.
    from harvesters.otc.adapters import expansion as EX
    new = sum(1 for r in ROWS if r.source_id in EX.NEW_SOURCE_IDS)
    assert len(rows) == len(fl_tx) == len(ROWS) - 4 - 6 - 5 - 5 - 4 - 1 - new and all(set(r) == set(csr.COLUMNS) for r in rows)
    with pytest.raises(ValueError, match="migration 018"):
        csr.to_db_rows(ROWS)
    dallas = next(r for r in rows if r["county"] == "Dallas" and r["state"] == "TX" and r["source_id"] is None)
    assert dallas["harvester"] is None and dallas["document_url"] is None
    # (The PBFCM / MVBA blocked-vendor-only rows, which carried no URL, are gone since the owner unblocked them on
    # 2026-10-26; a candidate's missing document URL is still NULL.)
    sql = (REPO / "scripts/migrations/018_county_source_registry.sql").read_text(encoding="utf-8")
    for col in csr.COLUMNS:
        assert re.search(rf"^\s+{col}\s", sql, re.M), col


# Sources whose published address moved AFTER migration 017 was applied. 017
# is an applied, historical migration and is never edited: its one-time
# backfill keeps the address that was current then, while the registry
# follows the source. Each entry names why it moved.
#   Brevard (2026-10-26): the clerk redesigned www.brevardclerk.us - the
#   _cache PDF answered 410 and /lands-available 404 (runs #366, #379); the
#   same file (same File_id) is now linked from the Tax Deeds & Auctions page.
MOVED_SINCE_017 = {
    ("Brevard", "fl_laft_pdfs"): (
        "https://www.brevardclerk.us/lands-available",
        "https://www.brevardclerk.us/_cache/files/7/b/7b8e6515-1af7-4968-977f-cc32647e2257/"
        "A61EE6220F52FD754C0693E0343635FF.lola.pdf",
    ),
}


def test_r08_migration_017_backfill_values_equal_the_registry():
    sql = (REPO / "scripts/migrations/017_otc_inventory_provenance_lifecycle.sql").read_text(encoding="utf-8")
    block = sql[sql.index("with fl_sources("):sql.index(")\nupdate public.properties p")]
    tuples = re.findall(r"\('([^']*)', '([^']*)', '([^']*)', '([^']*)', '([^']*)'\)", block)
    # Migration 017 was written (and applied) before the 2026-10-26 additions; it covers the 52 earlier sources.
    expected = sorted((r.county, r.source_id, r.source_authority,
                       *MOVED_SINCE_017.get((r.county, r.source_id), (r.canonical_url, r.document_url)))
                      for r in csr.production_rows(ROWS, "FL")
                      if "AVAILABLE" in r.ledger_set and r.county not in builder.FL_ADDED_2026_10_26)
    for (county, sid), _old in MOVED_SINCE_017.items():
        now = csr.lookup(ROWS, "FL", county, sid)
        assert (now.canonical_url, now.document_url) != _old, f"{county} no longer moved - drop it from MOVED_SINCE_017"
    assert sorted(tuples) == expected and len(tuples) == 52


def test_r09_generator_is_deterministic_and_registers_no_new_source_as_production():
    out = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0,'scripts'); import build_county_source_registry as b; print(b.render(b.build_rows()))"],
                         capture_output=True, text=True, cwd=REPO)
    assert out.returncode == 0 and out.stdout.strip() == (REPO / "data/county_source_registry.csv").read_text(encoding="utf-8").strip()
    for county, *_ in builder.FL_CANDIDATES:
        assert csr.lookup(ROWS, "FL", county).verification_status != "PRODUCTION_VERIFIED"
    for county, _url, _fmt, _gov, _note, *sid in builder.TX_CANDIDATES:
        assert csr.lookup(ROWS, "TX", county, sid[0] if sid else "").verification_status != "PRODUCTION_VERIFIED"
    for county, sid, *_ in builder.TX_COUNTY_SOURCES:     # published 2026-10-26 (owner decision)
        assert csr.lookup(ROWS, "TX", county, sid).verification_status == "PRODUCTION_VERIFIED"
