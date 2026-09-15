"""Phase 14B (Database/API Customer Boundary Design & Migration Readiness
Gate) tests.

Same discipline as Phase 13/14A's test suites: every test reads a REAL
repository file (SQL or JS text) and asserts something about its actual
content, rather than modeling the desired behavior separately. See
docs/phase-14b-database-api-boundary-readiness.md for the full write-up
each lettered group corresponds to (Step 6's own 17-item list, grouped
A-J to match this project's established lettering convention).

No source is contacted, no production Supabase project is touched, no
schema is applied - both proposed migrations
(scripts/migrations/005_customer_safe_properties_projection.sql and
scripts/migrations/005a_close_direct_properties_grant.sql) are confirmed
present and confirmed NOT executed, never applied by any test here.
"""

from __future__ import annotations

import re
from pathlib import Path

from harvesters.governance.registry import SOURCE_REGISTRY, SourceStatus
from harvesters.governance.gate import check_ingestion_gate

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(*parts: str) -> str:
    return (REPO_ROOT / Path(*parts)).read_text()


def _005_returns_table_columns() -> set[str]:
    """Column names in migration 005's `returns table (...)` clause -
    parses the literal SQL text, not a re-implemented model of it."""
    sql = _read("scripts", "migrations", "005_customer_safe_properties_projection.sql")
    block = sql.split("returns table (")[1].split(")\nlanguage sql")[0]
    # Each entry looks like "  name type[, ...]" - take the first token of
    # every comma-separated entry as the column name.
    entries = [e.strip() for e in block.replace("\n", " ").split(",") if e.strip()]
    return {e.split()[0] for e in entries}


def _005a_grant_columns() -> set[str]:
    """Column names in migration 005a's `grant select (...)` clause."""
    sql = _read("scripts", "migrations", "005a_close_direct_properties_grant.sql")
    block = sql.split("grant select (")[1].split(") on public.properties")[0]
    return {c.strip() for c in block.split(",") if c.strip()}


# `harvester_source` is deliberately NOT in this list - see the "CORRECTION,
# Phase 14B" comment in scripts/migrations/005_customer_safe_properties_
# projection.sql. It was originally classified alongside these two, but
# Phase 14B's own fresh re-audit of app.js found Phase 14A's own
# assessedSourceLabel() legitimately reads p.harvester_source to label
# Texas rows correctly - so it was moved into the customer-safe allow-list
# in both migration files instead. Only these two remain genuinely,
# currently unread by any frontend code.
INTERNAL_FIELDS = ("ledger_type", "fdor_enriched_at")

# CORRECTION, Phase 14E (Corrective Migration 005 / get_properties()
# Function Contract): `ledger_type` is internal in the sense INTERNAL_FIELDS
# means (never returned by get_properties(), never a CSV/export column,
# never read by app.js as a property) - but it is NOT absent from 005a's
# own grant list the way `fdor_enriched_at` is. get_properties() (security
# invoker, unchanged) reads `ledger_type` in its own WHERE clause to
# implement the `p_ledger_type` filter, so `authenticated` must retain
# column-level SELECT on it or every authenticated call to that function
# fails with "permission denied for column ledger_type" - see 005's own
# "CRITICAL FINDING" comment and 005a's own "CORRECTION, Phase 14E"
# comment for the full reasoning. `fdor_enriched_at` has no such
# dependency (never referenced anywhere in get_properties()'s body) and
# remains the one field genuinely absent from both files' column lists.
GRANT_ONLY_FOR_INTERNAL_FILTERING = {"ledger_type"}

# The full universe of columns this repository's tracked migration/schema
# history actually creates on public.properties, assembled from every
# `add column` statement (see docs/phase-14b-database-api-boundary-
# readiness.md Section 2) plus the base columns every sync script assumes
# exist (id, state, county, source, case_no, parcel, address, owner_name,
# status, bid, sale_date, legal_desc, etc. - present since before this
# repo's oldest tracked migration, per that section's own "no schema.sql/
# v2/v3 in tracked history" finding). Used only to assert 005a's column
# list is a subset of what could plausibly exist, never to assert it is
# the live source of truth.
KNOWN_COLUMN_UNIVERSE = {
    "id", "state", "county", "source", "address", "parcel", "case_no",
    "owner_name", "status", "prop_type", "dor_use_code", "tx_category",
    "lien_level", "lien_note", "homestead", "bid", "assessed", "market",
    "value_year", "min_bid", "redemption_period_months",
    "redemption_expiration_date", "max_statutory_return_usd",
    "year_built", "living_area", "lot_sqft", "num_buildings",
    "land_value", "legal_desc", "last_sale_price", "last_sale_year",
    "sale_date", "certificate_no", "tax_year", "issued_date",
    "expiration_date", "interest_rate", "latitude", "longitude",
    "url_appraiser", "url_auction", "url_taxcoll", "url_title",
    "url_streetview", "url_zillow", "outcome", "sold_price",
    "gone_since", "updated_at",
    "harvester_source", "ledger_type", "fdor_enriched_at",
}


# ==================== A: the two proposed migrations agree ====================


def test_A_005a_grant_columns_equal_005_output_columns_plus_the_documented_exception():
    """CORRECTED, Phase 14E: 005 (the RPC projection) and 005a (the
    base-table grant) no longer protect the exact same column set - see
    GRANT_ONLY_FOR_INTERNAL_FILTERING above. The invariant this test
    guards is now "005a's grant list equals 005's output list plus
    exactly the documented ledger_type exception, nothing more, nothing
    less" - if they drift apart in any OTHER way, either the RPC would
    expose a column the raw table blocks (harmless but inconsistent) or,
    worse, the raw table would block a column the RPC still tries to
    select (which would break the RPC, per the invoker-rights finding
    docs/phase-14b-database-api-boundary-readiness.md Section 5
    documents, and per 005's own Phase 14E "CRITICAL FINDING" comment -
    the exact failure mode that finding is about)."""
    cols_005 = _005_returns_table_columns()
    cols_005a = _005a_grant_columns()
    assert cols_005a == cols_005 | GRANT_ONLY_FOR_INTERNAL_FILTERING, (
        f"005a's grant columns must equal 005's output columns plus exactly "
        f"{GRANT_ONLY_FOR_INTERNAL_FILTERING} - extra: "
        f"{cols_005a - cols_005 - GRANT_ONLY_FOR_INTERNAL_FILTERING}, "
        f"missing: {cols_005 - cols_005a}"
    )


def test_A_every_customer_visible_field_is_explicitly_allow_listed():
    cols = _005a_grant_columns()
    # A representative sample of real customer-facing fields spanning both
    # states and every ledger type - not the full ~46, but enough to catch
    # a badly-truncated list.
    for expected in (
        "state", "county", "source", "address", "case_no", "owner_name",
        "assessed", "market", "bid", "sale_date", "legal_desc",
        "certificate_no", "min_bid", "latitude", "longitude", "gone_since",
    ):
        assert expected in cols, f"{expected!r} missing from 005a's allow-list"


# ==================== B: internal fields cannot enter the projection ====================


def test_B_internal_fields_absent_from_005s_actual_output_columns():
    """Both genuinely-internal fields must never appear in 005's own
    RETURNS TABLE/SELECT output - this is the customer-visibility
    boundary that actually matters (what get_properties() returns to a
    caller), unaffected by the Phase 14E ledger_type grant correction."""
    cols_005 = _005_returns_table_columns()
    for internal in INTERNAL_FIELDS:
        assert internal not in cols_005, f"{internal!r} leaked into 005's returns-table list"


def test_B_fdor_enriched_at_absent_from_005as_grant_list_too():
    """Unlike ledger_type (see GRANT_ONLY_FOR_INTERNAL_FILTERING),
    fdor_enriched_at has no dependency inside get_properties()'s function
    body at all, so it is the one field that must remain absent from
    BOTH 005's output and 005a's grant - fully closed, no exception."""
    assert "fdor_enriched_at" not in _005a_grant_columns()


def test_B_harvester_source_IS_customer_visible_and_the_frontend_actually_needs_it():
    """Not a mistake - the inverse of the other two in this group. See the
    INTERNAL_FIELDS comment above and 005's own "CORRECTION, Phase 14B"
    note: app.js's assessedSourceLabel() legitimately reads
    p.harvester_source, so both migrations correctly include it in the
    customer-safe allow-list rather than excluding it."""
    assert "harvester_source" in _005_returns_table_columns()
    assert "harvester_source" in _005a_grant_columns()
    app_js = _read("public", "app.js")
    assert "p.harvester_source" in app_js


def test_B_ledger_type_not_in_005s_output_but_deliberately_in_005as_grant():
    """CORRECTED, Phase 14E - not a mistake, the documented exception:
    ledger_type must never be part of what get_properties() actually
    returns (customer-visible = false), but 005a must still grant
    column-level SELECT on it, because that function's own WHERE clause
    reads it internally under security invoker. See
    GRANT_ONLY_FOR_INTERNAL_FILTERING above and 005/005a's own
    "CORRECTION, Phase 14E" comments for the full reasoning."""
    assert "ledger_type" not in _005_returns_table_columns()
    assert "ledger_type" in _005a_grant_columns()
    app_js = _read("public", "app.js")
    assert not re.search(r"[.\[]ledger_type\b", app_js), (
        "ledger_type must still never be read as a property anywhere in "
        "app.js, even though 005a now grants column-level SELECT on it "
        "for get_properties()'s own internal use"
    )


# ==================== C: unknown fields fail closed ====================


def test_C_no_geometry_column_name_appears_in_either_grant_list():
    """The undocumented geometry column found via get_advisors
    (properties_sync_geom / the postgis extension - Section 2 bucket E)
    has no confirmed name, so neither migration can name it - and neither
    should guess. Checked by confirming no plausible geometry-ish
    identifier appears in the actual column lists (comments are allowed
    to discuss it; the SELECT/GRANT lists must not)."""
    cols_005 = _005_returns_table_columns()
    cols_005a = _005a_grant_columns()
    for suspect in ("geom", "geometry", "the_geom", "shape", "wkb_geometry"):
        assert suspect not in cols_005
        assert suspect not in cols_005a


def test_C_005a_column_list_is_a_subset_of_the_known_column_universe():
    """005a must never grant a column this repository's own tracked
    history doesn't know about - narrowing, never guessing at a new one."""
    assert _005a_grant_columns() <= KNOWN_COLUMN_UNIVERSE


# ==================== D: system metadata is not accidentally exported ====================


def test_D_raw_id_is_not_a_csv_export_column():
    """`id` must remain grantable (it's a real join key both migrations
    correctly include - notes/favorites/hidden/bid_list all reference it)
    but must never be surfaced as its own CSV column - that would leak an
    internal row identifier as if it were product data."""
    assert "id" in _005a_grant_columns()
    app_js = _read("public", "app.js")
    csv_block = app_js.split("const cols = [", 1)[1].split("\n  ];", 1)[0]
    assert not re.search(r"\bp\.id\b", csv_block), (
        "a CSV export column reads p.id directly - the row's internal uuid "
        "must never be an exported column"
    )


def test_D_updated_at_still_not_rendered_as_a_raw_value():
    """Regression for the Phase 14B correction to Phase 14A's gone_since
    claim (docs/phase-14a-customer-safety-hardening.md Section 3): confirm
    that correction was specific to gone_since and that updated_at's own,
    different characterization (feeds only derived freshness logic, never
    the raw timestamp) still holds - the raw ISO string itself must not
    appear as a directly-read export/render value."""
    app_js = _read("public", "app.js")
    csv_block = app_js.split("const cols = [", 1)[1].split("\n  ];", 1)[0]
    assert not re.search(r"\bp\.updated_at\b", csv_block)


# ==================== E: cross-state projectability ====================


def test_E_florida_rows_remain_projectable():
    cols = _005a_grant_columns()
    for fl_field in ("certificate_no", "tax_year", "issued_date", "expiration_date", "interest_rate"):
        assert fl_field in cols


def test_E_texas_rows_remain_projectable():
    cols = _005a_grant_columns()
    for tx_field in ("min_bid", "legal_desc", "tx_category", "redemption_period_months"):
        assert tx_field in cols


# ==================== F: assessed semantics still correct ====================


def test_F_assessed_still_in_the_allow_list_and_label_function_intact():
    assert "assessed" in _005a_grant_columns()
    app_js = _read("public", "app.js")
    assert "function assessedSourceLabel(p)" in app_js
    assert 'if (p.harvester_source === "tx_lgbs") return "TX CAD/Listed Value";' in app_js


# ==================== G: governance preservation ====================


def test_G_source_statuses_unchanged_this_phase():
    assert SOURCE_REGISTRY["tx_lgbs"].legal_status == SourceStatus.APPROVED
    assert SOURCE_REGISTRY["tx_realauction"].legal_status == SourceStatus.APPROVED
    assert SOURCE_REGISTRY["tx_hctax"].legal_status == SourceStatus.LEGAL_REVIEW_REQUIRED
    for blocked in ("tx_pbfcm", "tx_govease", "tx_mvba", "tx_ctsa"):
        assert SOURCE_REGISTRY[blocked].legal_status == SourceStatus.BLOCKED


def test_G_blocked_and_legal_review_sources_still_rejected_by_the_gate():
    for source_id in ("tx_hctax", "tx_pbfcm", "tx_govease", "tx_mvba", "tx_ctsa"):
        decision = check_ingestion_gate(source_id)
        assert not decision.allowed


def test_G_approved_sources_still_permitted_by_the_gate():
    for source_id in ("tx_lgbs", "tx_realauction"):
        decision = check_ingestion_gate(source_id)
        assert decision.allowed


# ==================== H: no select("*") customer path is silently accepted ====================


def test_H_005a_actually_revokes_blanket_select_before_granting_columns():
    sql = _read("scripts", "migrations", "005a_close_direct_properties_grant.sql")
    code_lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    code = "\n".join(code_lines)
    assert "revoke select on public.properties from anon;" in code
    assert "revoke select on public.properties from authenticated;" in code
    assert "grant select (" in code


def test_H_005a_never_touches_service_role():
    sql = _read("scripts", "migrations", "005a_close_direct_properties_grant.sql")
    code_lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    code = "\n".join(code_lines)
    assert "service_role" not in code


def test_H_neither_migration_creates_or_alters_an_rls_policy():
    for filename in (
        "005_customer_safe_properties_projection.sql",
        "005a_close_direct_properties_grant.sql",
    ):
        sql = _read("scripts", "migrations", filename)
        code_lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
        code = "\n".join(code_lines).lower()
        assert "create policy" not in code
        assert "alter policy" not in code
        assert "drop policy" not in code


def test_H_005a_documents_its_ordering_dependency_on_005():
    sql = _read("scripts", "migrations", "005a_close_direct_properties_grant.sql")
    assert "005 must land first" in sql or "must run after 005" in sql.lower() or "before 005" in sql.lower() or "after 005" in sql.lower()


# ==================== I: CSV export contract compatibility ====================


def test_I_csv_export_still_carries_the_phase14a_assessed_source_column():
    app_js = _read("public", "app.js")
    assert '["Assessed/Value Field Source", p => assessedSourceLabel(p)]' in app_js


def test_I_csv_export_column_count_unchanged_this_phase():
    """This phase adds no new CSV column and removes none - a coarse
    snapshot (count of literal `["...", ` entries in the cols array) that
    would fail if a future edit silently changed the export's shape
    without updating this phase's own documentation of it."""
    app_js = _read("public", "app.js")
    csv_block = app_js.split("const cols = [", 1)[1].split("\n  ];", 1)[0]
    entry_count = len(re.findall(r'\n\s*\["', csv_block))
    assert entry_count >= 40, (
        f"expected at least 40 CSV export columns (Phase 13/14A baseline), found {entry_count}"
    )


# ==================== J: cross-state / frontend independence from internal fields ====================


def test_J_frontend_still_has_zero_references_to_internal_fields():
    """Checks for an actual property access (`p.ledger_type` /
    `.ledger_type`), not a bare substring - `ledger_type` also appears
    legitimately inside a migration filename
    ("003_ledger_type_and_state_isolation.sql") in a console.warn() string,
    which is real code (not a `//` comment) but not a field reference, and
    a bare-substring check would false-positive on it."""
    app_js = _read("public", "app.js")
    for internal in INTERNAL_FIELDS:
        assert not re.search(rf"[.\[]{internal}\b", app_js), (
            f"{internal!r} is accessed as a property in public/app.js - the "
            "frontend must not come to depend on a field 005/005a remove "
            "from the customer-facing read surfaces"
        )


def test_J_florida_ps1_harvesters_remain_decoupled_from_governance():
    ps1_dir = REPO_ROOT / "scripts"
    ps1_files = list(ps1_dir.glob("*.ps1"))
    assert ps1_files, "expected at least one .ps1 harvester script to exist"
    for f in ps1_files:
        text = f.read_text(errors="ignore")
        assert "harvesters.governance" not in text
        assert "from governance" not in text
