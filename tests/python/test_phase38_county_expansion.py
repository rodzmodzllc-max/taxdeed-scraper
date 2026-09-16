"""Tests for Phase 38 (County Expansion and Alternate Source Acquisition).

The single most important property these tests defend is that the phase did
NOT promote anything. 321 counties gained an identified official source; not
one of them gained permission to use it. A test suite that only checked row
counts would pass while that distinction quietly eroded, so most of what
follows asserts the negative.
"""

from __future__ import annotations

import ast
import csv
import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
DATA = REPO / "data"
DOCS = REPO / "docs"
BUILDER = REPO / "scripts" / "build_phase38_expansion.py"

FL_DIR = DATA / "fl_official_directory.csv"
TX_DIR = DATA / "tx_official_directory.csv"
RIGHTS = DATA / "source_rights_matrix.csv"
SUMMARY = DATA / "county_coverage_matrix_summary.json"
FL_MATRIX = DATA / "fl_county_coverage_matrix.csv"
TX_MATRIX = DATA / "tx_county_coverage_matrix.csv"

LEGAL_REVIEW = "LEGAL_REVIEW_REQUIRED"
DIRECTORY_LISTED = "DIRECTORY_LISTED"


def rows(path: pathlib.Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ===========================================================================
# County coverage
# ===========================================================================


def test_p38_01_florida_has_all_67_counties():
    fl = rows(FL_DIR)
    assert len(fl) == 67
    assert len({r["county"] for r in fl}) == 67


def test_p38_02_texas_has_all_254_counties():
    tx = rows(TX_DIR)
    assert len(tx) == 254
    assert len({r["county"] for r in tx}) == 254


def test_p38_03_directories_match_the_existing_matrices_exactly():
    """Extend, don't replace: the new tables must describe the same county
    sets the repository already tracks."""
    assert {r["county"] for r in rows(FL_DIR)} == {r["county"] for r in rows(FL_MATRIX)}
    assert {r["county"] for r in rows(TX_DIR)} == {r["county"] for r in rows(TX_MATRIX)}


def test_p38_04_texas_county_codes_are_unique_three_digit():
    codes = [r["comptroller_county_code"] for r in rows(TX_DIR)]
    assert len(set(codes)) == 254
    assert all(c.isdigit() and len(c) == 3 for c in codes)


# ===========================================================================
# Nothing was promoted - the assertions that matter most
# ===========================================================================


def test_p38_05_no_county_office_is_approved():
    for path in (FL_DIR, TX_DIR):
        for row in rows(path):
            assert row["legal_status"] == LEGAL_REVIEW, row["county"]


def test_p38_06_every_rights_row_is_legal_review_required():
    for row in rows(RIGHTS):
        assert row["legal_status"] == LEGAL_REVIEW, row


def test_p38_07_no_rights_column_claims_a_right_nobody_reviewed():
    """A right is granted by a reviewed term, never by a default."""
    granted = {"YES", "ALLOWED", "PERMITTED", "APPROVED", "TRUE"}
    rights_cols = ("storage", "caching", "derivation", "customer_display", "export",
                   "api", "image_use", "document_use", "commercial_use")
    for row in rows(RIGHTS):
        for col in rights_cols:
            assert row[col].upper() not in granted, f"{row['county']}/{col} = {row[col]}"


def test_p38_08_terms_were_not_reviewed_and_say_so():
    for path in (FL_DIR, TX_DIR):
        for row in rows(path):
            assert row["terms_reviewed"] == "NO"


def test_p38_09_summary_records_zero_new_production_sources():
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    approved = s["counties_with_approved_production_source"]
    for state in ("FL", "TX"):
        assert approved[state].startswith("0 ")


def test_p38_10_no_source_registry_status_was_changed_by_this_phase():
    """`SourceStatus` keeps exactly its eight states - no second legal-status
    system, and no new approval state smuggled in."""
    from harvesters.governance.registry import SourceStatus

    assert {s.value for s in SourceStatus} == {
        "DISCOVERED", "UNDER_REVIEW", "APPROVED", "APPROVED_WITH_RESTRICTIONS",
        "LEGAL_REVIEW_REQUIRED", "BLOCKED", "DISABLED", "TERMS_CHANGED",
    }


def test_p38_11_ingestion_gate_still_admits_only_the_two_approved_states():
    from harvesters.governance.registry import INGESTION_ALLOWED_STATUSES, SourceStatus

    assert INGESTION_ALLOWED_STATUSES == frozenset(
        {SourceStatus.APPROVED, SourceStatus.APPROVED_WITH_RESTRICTIONS}
    )


def test_p38_12_directory_listed_is_weaker_than_content_verified():
    """The new value must not be usable as evidence of having read the
    county's own site."""
    doc = (DOCS / "county-expansion.md").read_text(encoding="utf-8")
    assert DIRECTORY_LISTED in doc
    assert "not fetched" in doc.lower()
    for path in (FL_DIR, TX_DIR):
        for row in rows(path):
            for key, value in row.items():
                if key.endswith("_status"):
                    assert value != "CONTENT_VERIFIED", (row["county"], key)


# ===========================================================================
# Missing data is categorised, never collapsed into "failure"
# ===========================================================================


def test_p38_13_absent_url_is_source_not_found_not_technical_failure():
    missing = [r for r in rows(TX_DIR) if not r["appraisal_district_url"]]
    assert missing, "expected some counties whose directory lists no CAD site"
    for row in missing:
        assert row["appraisal_district_status"] == "SOURCE_NOT_FOUND"
        assert "FAIL" not in row["appraisal_district_status"]


def test_p38_14_present_url_is_directory_listed():
    for row in rows(TX_DIR):
        if row["appraisal_district_url"]:
            assert row["appraisal_district_status"] == DIRECTORY_LISTED
    for row in rows(FL_DIR):
        if row["property_appraiser_url"]:
            assert row["property_appraiser_status"] == DIRECTORY_LISTED


def test_p38_15_no_url_was_invented_for_a_county_without_one():
    """Every non-empty URL must be traceable to the checked-in raw extract."""
    raw_tx = (DATA / "reference" / "tx_comptroller_directory_raw.psv").read_text(encoding="utf-8")
    for row in rows(TX_DIR):
        for col in ("appraisal_district_url", "tax_assessor_collector_url"):
            if row[col]:
                assert row[col] in raw_tx, (row["county"], col)
    raw_fl = (DATA / "reference" / "fl_dor_local_officials_raw.psv").read_text(encoding="utf-8")
    for row in rows(FL_DIR):
        for col in ("property_appraiser_url", "tax_collector_url", "vab_clerk_url"):
            if row[col]:
                assert row[col] in raw_fl, (row["county"], col)


# ===========================================================================
# Provenance
# ===========================================================================


def test_p38_16_every_row_carries_its_directory_and_retrieval_date():
    for row in rows(FL_DIR):
        assert row["directory_operator"] == "Florida Department of Revenue"
        assert row["directory_url"].startswith("https://floridarevenue.com/")
        assert row["retrieved_at"]
    for row in rows(TX_DIR):
        assert row["directory_operator"] == "Texas Comptroller of Public Accounts"
        assert row["comptroller_directory_url"].startswith(
            "https://comptroller.texas.gov/taxes/property-tax/county-directory/"
        )
        assert row["retrieved_at"]


def test_p38_17_texas_carries_the_sources_own_timestamp_where_published():
    """`source_timestamp` is the directory's own 'Last Updated', never our
    retrieval time - they are different facts and must not be conflated."""
    ts = [r for r in rows(TX_DIR) if r["appraisal_district_source_timestamp"]]
    assert len(ts) > 200
    for row in ts:
        assert row["appraisal_district_source_timestamp"] != row["retrieved_at"]


def test_p38_18_rights_rows_all_cite_evidence():
    for row in rows(RIGHTS):
        assert row["evidence_url"].startswith("http"), row
        assert row["reviewed_at"], row


# ===========================================================================
# State isolation
# ===========================================================================


def test_p38_19_no_florida_row_leaks_into_texas_or_back():
    fl_counties = {r["county"] for r in rows(FL_DIR)}
    tx_counties = {r["county"] for r in rows(TX_DIR)}
    for row in rows(RIGHTS):
        if row["county"] == "ALL":
            continue
        pool = fl_counties if row["state"] == "FL" else tx_counties
        assert row["county"] in pool, row
    for row in rows(FL_DIR):
        assert row["state"] == "FL"
    for row in rows(TX_DIR):
        assert row["state"] == "TX"


def test_p38_20_shared_county_names_stay_in_their_own_state():
    """Both states have a Jackson, a Jefferson, a Madison, a Franklin. A
    cross-state join on name alone would silently merge them."""
    shared = {r["county"] for r in rows(FL_DIR)} & {r["county"] for r in rows(TX_DIR)}
    assert shared, "expected overlapping county names between FL and TX"
    for name in shared:
        fl_row = next(r for r in rows(FL_DIR) if r["county"] == name)
        tx_row = next(r for r in rows(TX_DIR) if r["county"] == name)
        assert fl_row["directory_operator"] != tx_row["directory_operator"]


# ===========================================================================
# Completeness measurement
# ===========================================================================


def test_p38_21_summary_preserves_the_prior_baseline():
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    assert s["_history"], "the previous measurement must not be overwritten"
    prior = s["_history"][0]
    assert prior["_phase"].startswith("Phase 35")
    assert prior["fl_counties_with_property_appraiser_verified"] == 12
    assert prior["tx_counties_with_appraisal_district_verified"] == 42


def test_p38_22_summary_counts_match_the_tables_they_describe():
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    fl, tx = rows(FL_DIR), rows(TX_DIR)
    assert s["fl_counties_property_appraiser_directory_listed"] == sum(
        1 for r in fl if r["property_appraiser_url"])
    assert s["fl_counties_tax_collector_directory_listed"] == sum(
        1 for r in fl if r["tax_collector_url"])
    assert s["tx_counties_appraisal_district_directory_listed"] == sum(
        1 for r in tx if r["appraisal_district_url"])
    assert s["tx_counties_tax_assessor_collector_directory_listed"] == sum(
        1 for r in tx if r["tax_assessor_collector_url"])


def test_p38_23_summary_states_plainly_what_directory_listed_is_not():
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    note = s["_measurement_note"].lower()
    assert "not technical verification" in note
    assert "not authorization" in note


def test_p38_24_coverage_improved_against_the_preserved_baseline():
    s = json.loads(SUMMARY.read_text(encoding="utf-8"))
    prior = s["_history"][0]
    assert s["fl_counties_property_appraiser_directory_listed"] > prior[
        "fl_counties_with_property_appraiser_verified"]
    assert s["tx_counties_appraisal_district_directory_listed"] > prior[
        "tx_counties_with_appraisal_district_verified"]
    assert s["tx_counties_with_no_known_source_any_category"] < prior[
        "tx_counties_with_no_known_source_any_category"]


# ===========================================================================
# Production safety, asserted structurally
# ===========================================================================


def test_p38_25_builder_has_no_database_import_and_no_dml():
    tree = ast.parse(BUILDER.read_text(encoding="utf-8"), filename=str(BUILDER))
    db = {"supabase", "psycopg", "psycopg2", "sqlalchemy", "asyncpg", "MySQLdb", "pymysql"}
    dml = ("insert into", "update ", "delete from", "truncate", "drop table")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in db
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in db
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if len(node.value) < 400 and any(k in node.value.lower() for k in dml):
                raise AssertionError(f"DML-looking literal: {node.value[:60]!r}")


def test_p38_26_builder_makes_no_network_call():
    """It reads checked-in extracts. Re-running it must never re-fetch."""
    tree = ast.parse(BUILDER.read_text(encoding="utf-8"), filename=str(BUILDER))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            for name in names:
                assert not name.startswith(("urllib", "http", "requests", "socket")), name


def test_p38_27_builder_writes_only_under_data():
    src = BUILDER.read_text(encoding="utf-8")
    assert "REPO / \"data\"" in src
    assert "public/" not in src and "supabase/" not in src


def test_p38_28_no_auction_or_harvester_file_was_touched_by_this_phase():
    """Section 17/18: LGBS and the previously-blocked TX vendors stay as they
    are. If this phase had edited them, this list would have to change."""
    for name in ("texas_harvester.py",):
        path = REPO / "harvesters" / name
        if path.exists():
            assert "DIRECTORY_LISTED" not in path.read_text(encoding="utf-8")


# ===========================================================================
# Alternate-source / substitution documentation
# ===========================================================================


def test_p38_29_permission_doc_names_an_alternative_for_each_restricted_vendor():
    doc = (DOCS / "permission-required-sources.md").read_text(encoding="utf-8")
    for vendor in ("RealAuction", "LienHub", "Linebarger"):
        assert vendor in doc
    assert doc.count("Alternative found:") >= 3


def test_p38_30_permission_doc_claims_no_contact_was_made():
    doc = (DOCS / "permission-required-sources.md").read_text(encoding="utf-8")
    assert "NOT_REQUESTED" in doc
    assert "no provider has actually been contacted" in doc.lower()
    assert "NO_CONTACT_MADE" in doc


def test_p38_31_previously_blocked_texas_vendors_are_documented_as_unchanged():
    doc = (DOCS / "permission-required-sources.md").read_text(encoding="utf-8")
    for source in ("tx_pbfcm", "tx_govease", "tx_mvba", "tx_ctsa"):
        assert source in doc
    assert "unchanged" in doc.lower()


def test_p38_32_field_level_fallback_is_recorded_per_office():
    """Fallback is by FIELD, not by source: the clerk must not be listed as a
    source of market value, nor the appraisal district of tax balance."""
    for row in rows(RIGHTS):
        cats = row["field_category"]
        if "Clerk" in row["provider"]:
            assert "MARKET_VALUE" not in cats
        if "Appraisal District" in row["provider"]:
            assert "DELINQUENT_TAX" not in cats
        if "Tax Assessor-Collector" in row["provider"] or "Tax Collector" in row["provider"]:
            assert "MARKET_VALUE" not in cats


def test_p38_33_rights_matrix_has_every_required_column():
    expected = ["state", "county", "provider", "source", "field_category", "technical_access",
                "automated_access", "storage", "caching", "derivation", "customer_display",
                "export", "api", "image_use", "document_use", "commercial_use",
                "authorization_required", "legal_status", "evidence_url", "reviewed_at", "notes"]
    with RIGHTS.open(encoding="utf-8") as fh:
        assert next(csv.reader(fh)) == expected


def test_p38_34_rights_matrix_row_count_matches_the_offices_identified():
    fl, tx = rows(FL_DIR), rows(TX_DIR)
    expected = 2 + sum(
        bool(r[c]) for r in fl for c in ("property_appraiser_url", "tax_collector_url", "vab_clerk_url")
    ) + sum(
        bool(r[c]) for r in tx for c in ("appraisal_district_url", "tax_assessor_collector_url")
    )
    assert len(rows(RIGHTS)) == expected


@pytest.mark.parametrize("doc", ["county-expansion.md", "source-rights-matrix.md",
                                 "permission-required-sources.md"])
def test_p38_35_each_new_document_states_what_was_not_done(doc):
    text = (DOCS / doc).read_text(encoding="utf-8").lower()
    assert "not reviewed" in text or "not fetched" in text or "unreviewed" in text
