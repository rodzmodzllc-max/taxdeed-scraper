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
    assert len(fl) == 146 and len(avail) == 67 and len({r.county for r in avail}) == 67 and len({r.county for r in fl}) == 67
    prod = [r for r in csr.production_rows(ROWS, "FL") if "AVAILABLE" in r.ledger_set]
    assert len(prod) == 52
    assert csr.expected_harvest_units(ROWS) == sorted((r.source_id, r.county) for r in prod)
    assert {r.source_id for r in prod} == {"fl_laft_pdfs", "fl_laft_html", "fl_laft_pioneer", "fl_laft_realtdm",
                                           "fl_laft_orange", "fl_laft_stlucie", "fl_laft_osceola", "fl_laft_hillsborough", "fl_laft_leon"}


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
    assert fl_cands == {
        "Broward": "SEARCH_EVIDENCE_ONLY", "Okaloosa": "SEARCH_EVIDENCE_ONLY", "DeSoto": "SEARCH_EVIDENCE_ONLY", "Wakulla": "SEARCH_EVIDENCE_ONLY",
        "Charlotte": "SOURCE_EXISTS_ACCESS_UNKNOWN", "Collier": "SOURCE_EXISTS_ACCESS_UNKNOWN", "Gilchrist": "SOURCE_EXISTS_ACCESS_UNKNOWN",
        "Lake": "SOURCE_EXISTS_ACCESS_UNKNOWN", "Monroe": "SOURCE_EXISTS_ACCESS_UNKNOWN", "Nassau": "SOURCE_EXISTS_ACCESS_UNKNOWN",
        "Suwannee": "SOURCE_EXISTS_ACCESS_UNKNOWN", "Jefferson": "HISTORICAL_ONLY",
        "Baker": "NOT_FOUND_AFTER_SEARCH", "Jackson": "NOT_FOUND_AFTER_SEARCH", "Liberty": "NOT_FOUND_AFTER_SEARCH",
    }


def test_r05_texas_rows_are_lgbs_production_search_candidates_or_blocked_only():
    tx = [r for r in ROWS if r.state == "TX"]
    prod = [r for r in tx if r.is_production and "AVAILABLE" in r.ledger_set]
    assert {r.county for r in prod} == {"Galveston", "Liberty", "Leon", "Maverick", "Jim Wells", "Hardin", "Van Zandt", "Goliad"}
    assert all(r.source_id == "tx_lgbs" and r.source_authority == "VENDOR_COUNSEL" and r.inventory_type == "" for r in prod)
    # The AUCTIONS-only production rows (2026-09-30) are the 24 RealAuction counties, nothing else.
    auctions_only = [r for r in tx if r.is_production and "AVAILABLE" not in r.ledger_set]
    assert len(auctions_only) == 24 and all(r.source_id == "tx_realauction" and r.ledger_set == {"AUCTIONS"} for r in auctions_only)
    cands = [r for r in tx if r.verification_status == "SEARCH_EVIDENCE_ONLY"]
    assert len(cands) == 20 and all(r.inventory_type == "" and r.source_authority == "GOVERNMENT_DIRECT" for r in cands)
    harris = csr.lookup(ROWS, "TX", "Harris")
    assert harris.governance_status == "LEGAL_REVIEW_REQUIRED" and harris.source_id == "tx_hctax" and not harris.runnable
    blocked = [r for r in tx if r.verification_status == "BLOCKED_VENDOR_ONLY"]
    assert len(blocked) == 14 and {r.source_id for r in blocked} == {"tx_pbfcm", "tx_mvba"}
    assert not any("pbfcm.com" in r.canonical_url or "mvbalaw" in r.canonical_url for r in ROWS)


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
        dict(source_id="tx_pbfcm"),                                             # blocked vendor with URL / not BLOCKED
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
    assert len(rows) == len(fl_tx) == len(ROWS) - 4 - 6 - 5 - 5 - 4 and all(set(r) == set(csr.COLUMNS) for r in rows)
    with pytest.raises(ValueError, match="migration 018"):
        csr.to_db_rows(ROWS)
    baker = next(r for r in rows if r["county"] == "Baker" and r["state"] == "FL")
    assert baker["source_id"] is None and baker["canonical_url"] is None and baker["harvester"] is None
    sql = (REPO / "scripts/migrations/018_county_source_registry.sql").read_text(encoding="utf-8")
    for col in csr.COLUMNS:
        assert re.search(rf"^\s+{col}\s", sql, re.M), col


def test_r08_migration_017_backfill_values_equal_the_registry():
    sql = (REPO / "scripts/migrations/017_otc_inventory_provenance_lifecycle.sql").read_text(encoding="utf-8")
    block = sql[sql.index("with fl_sources("):sql.index(")\nupdate public.properties p")]
    tuples = re.findall(r"\('([^']*)', '([^']*)', '([^']*)', '([^']*)', '([^']*)'\)", block)
    expected = sorted((r.county, r.source_id, r.source_authority, r.canonical_url, r.document_url)
                      for r in csr.production_rows(ROWS, "FL") if "AVAILABLE" in r.ledger_set)
    assert sorted(tuples) == expected and len(tuples) == 52


def test_r09_generator_is_deterministic_and_registers_no_new_source_as_production():
    out = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0,'scripts'); import build_county_source_registry as b; print(b.render(b.build_rows()))"],
                         capture_output=True, text=True, cwd=REPO)
    assert out.returncode == 0 and out.stdout.strip() == (REPO / "data/county_source_registry.csv").read_text(encoding="utf-8").strip()
    for county, *_ in builder.FL_CANDIDATES:
        assert csr.lookup(ROWS, "FL", county).verification_status != "PRODUCTION_VERIFIED"
    for county, *_ in builder.TX_CANDIDATES:
        assert csr.lookup(ROWS, "TX", county, "" if county != "Harris" else "tx_hctax").verification_status != "PRODUCTION_VERIFIED"
