"""Phase 14D (Migration Reconciliation & Pre-Execution Re-Gate) tests.

Phase 14C's live preflight (docs/phase-14c-production-migration-
verification.md) found that migrations 005 and 005a, as committed through
Phase 14B, referenced three columns - `outcome`, `sold_price`,
`dor_use_code` - that do not exist on the live `public.properties` table,
which would have made either migration fail outright with a Postgres
"column does not exist" error if executed. This file is Phase 14D's Gate 5
deliverable: a reusable migration/schema compatibility test that parses the
migration files' actual SQL text and checks every referenced column
against an authoritative schema snapshot, specifically so "a migration
references a column that does not exist in production" cannot recur
silently.

The authoritative snapshot is NOT re-derived or fabricated here. Per Gate
5's own instruction ("do not fabricate a 47-column schema snapshot if the
repo already has a better authoritative representation"), the column list
below is transcribed verbatim from docs/phase-14c-production-migration-
verification.md Section 2, which recorded it via a direct, live
`information_schema.columns` query against production project
`cqnnnvpbocafuvpzfbzu` during Phase 14C - the best available authoritative
representation this repository has. No Supabase tool is called by this
file; no production project is contacted.

No source is contacted, no production Supabase project is touched, no
schema is applied - this test file only ever reads local repository files.
"""

from __future__ import annotations

from pathlib import Path

from harvesters.governance.registry import SOURCE_REGISTRY, SourceStatus

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(*parts: str) -> str:
    return (REPO_ROOT / Path(*parts)).read_text()


def _005_returns_table_columns() -> set[str]:
    sql = _read("scripts", "migrations", "005_customer_safe_properties_projection.sql")
    block = sql.split("returns table (")[1].split(")\nlanguage sql")[0]
    entries = [e.strip() for e in block.replace("\n", " ").split(",") if e.strip()]
    return {e.split()[0] for e in entries}


def _005a_grant_columns() -> set[str]:
    sql = _read("scripts", "migrations", "005a_close_direct_properties_grant.sql")
    block = sql.split("grant select (")[1].split(") on public.properties")[0]
    return {c.strip() for c in block.split(",") if c.strip()}


# Transcribed verbatim from docs/phase-14c-production-migration-
# verification.md Section 2 ("Live schema findings (Gate A1)") - the actual
# 47 columns `information_schema.columns` returned for `public.properties`
# in production during Phase 14C, 2026-09-14. This is a point-in-time
# snapshot, not a live query - see the module docstring.
LIVE_PRODUCTION_COLUMNS_PHASE_14C = {
    "id", "source", "county", "case_no", "parcel", "owner_name", "address",
    "bid", "assessed", "market", "status", "lien_level", "lien_note",
    "prop_type", "sale_date", "homestead", "url_streetview", "url_appraiser",
    "url_zillow", "url_taxcoll", "url_auction", "url_title", "updated_at",
    "gone_since", "interest_rate", "certificate_no", "tax_year",
    "issued_date", "expiration_date", "latitude", "longitude", "year_built",
    "living_area", "lot_sqft", "land_value", "legal_desc",
    "last_sale_price", "last_sale_year", "value_year", "num_buildings",
    "fdor_enriched_at", "state", "tx_category", "redemption_period_months",
    "redemption_expiration_date", "max_statutory_return_usd", "min_bid",
    "ledger_type", "harvester_source",
}

# NOTE (found while writing this test, Phase 14D): the Phase 14C doc's own
# prose says "47 columns", but the literal column-name block in that same
# document's Section 2 - reproduced verbatim above - lists 49 distinct,
# non-duplicated names. This is a small, pre-existing inconsistency inside
# Phase 14C's own documentation (a prose miscount, not a re-verified live
# fact either way - this phase does not re-query production, per Gate 5's
# own instruction to reuse rather than re-derive the existing snapshot).
# It does not affect anything Phase 14C or Phase 14D concluded: none of
# the three blocking columns (outcome, sold_price, dor_use_code) appear in
# this list under either count, so the blocker, its cause, and this
# phase's fix are unaffected. Asserted against the list's actual content
# (49) rather than the prose claim (47) because the list is what every
# compatibility check below actually relies on. Flagged in
# docs/phase-14d-migration-reconciliation.md as a known, non-blocking
# documentation-only discrepancy for a future live Gate A to resolve with
# a fresh count.
assert len(LIVE_PRODUCTION_COLUMNS_PHASE_14C) == 49, (
    "transcription of the Phase 14C live-schema snapshot's column-name "
    "block must have exactly 49 entries, matching docs/phase-14c-"
    "production-migration-verification.md Section 2's own listed names "
    "(NOT that section's prose count of 47 - see the comment above)"
)

# Columns a tracked migration adds but that were NOT yet live as of the
# Phase 14C snapshot above. `dor_use_code` (schema-v9-dor-use-code.sql) is
# the only member: Phase 14D's reconciliation keeps it in 005/005a's
# column lists, but only on the condition that schema-v9-dor-use-code.sql
# runs first - see that file's own "DEPENDENCY (added Phase 14D)" comment
# and 005/005a's own "CORRECTION, Phase 14D" comments.
PREREQUISITE_MIGRATION_COLUMNS = {"dor_use_code"}

# The intended schema state 005/005a are written against, per Phase 14D's
# corrected execution order (schema-v9-dor-use-code.sql -> 005 -> 005a):
# the live Phase 14C snapshot, plus dor_use_code once its own prerequisite
# migration has been run.
INTENDED_SCHEMA_AFTER_PREREQUISITES = (
    LIVE_PRODUCTION_COLUMNS_PHASE_14C | PREREQUISITE_MIGRATION_COLUMNS
)

# The two columns Phase 14D removed from both migrations - no writer
# anywhere in this repository, no tracked migration ever proposing to add
# them, confirmed absent live. Must never reappear in either migration's
# column list without a dedicated migration backing them.
DEFERRED_UNBUILT_FIELDS = ("outcome", "sold_price")


# ==================== compatibility: every referenced column exists in the intended schema ====================


def test_005_returns_table_columns_all_exist_in_intended_schema():
    """The core Phase 14C regression guard: every column 005's
    RETURNS TABLE clause names must exist in the schema state 005 is
    actually meant to run against (live-as-of-14C, plus its documented
    prerequisite). A column here that isn't in that set would make
    CREATE OR REPLACE FUNCTION fail outright, exactly as Phase 14C found."""
    missing = _005_returns_table_columns() - INTENDED_SCHEMA_AFTER_PREREQUISITES
    assert not missing, f"005 references column(s) absent from the intended schema: {missing}"


def test_005a_grant_columns_all_exist_in_intended_schema():
    """Same guard as above, for 005a's GRANT SELECT (...) column list."""
    missing = _005a_grant_columns() - INTENDED_SCHEMA_AFTER_PREREQUISITES
    assert not missing, f"005a references column(s) absent from the intended schema: {missing}"


def test_005_would_still_fail_without_its_documented_prerequisite():
    """Proves the schema-v9 dependency is real, not decorative: if
    dor_use_code is NOT added first (i.e. checked against the live Phase
    14C snapshot alone, with no prerequisite applied), 005's column list
    must NOT be a subset - confirming 005 genuinely cannot run before
    schema-v9-dor-use-code.sql, matching the ordering both files now
    document."""
    cols = _005_returns_table_columns()
    assert not cols <= LIVE_PRODUCTION_COLUMNS_PHASE_14C, (
        "005's columns unexpectedly fit the live-only schema - the "
        "documented schema-v9 prerequisite may no longer be necessary, "
        "which would need its own re-review, not a silent pass here"
    )
    still_missing = cols - LIVE_PRODUCTION_COLUMNS_PHASE_14C
    assert still_missing == PREREQUISITE_MIGRATION_COLUMNS, (
        f"expected exactly the documented prerequisite column(s) "
        f"{PREREQUISITE_MIGRATION_COLUMNS} to be the only gap versus the "
        f"live-only schema, found {still_missing}"
    )


# ==================== regression: the two deferred fields never come back silently ====================


def test_outcome_and_sold_price_removed_from_both_migrations():
    cols_005 = _005_returns_table_columns()
    cols_005a = _005a_grant_columns()
    for field in DEFERRED_UNBUILT_FIELDS:
        assert field not in cols_005, f"{field!r} leaked back into 005 - see docs/phase-14d-migration-reconciliation.md"
        assert field not in cols_005a, f"{field!r} leaked back into 005a - see docs/phase-14d-migration-reconciliation.md"


def test_outcome_and_sold_price_have_no_writer_anywhere_in_the_repo():
    """Regression guard for the Gate 1 finding that justified removing
    these fields: if a future phase adds a real writer for either field
    without also adding a tracked migration and re-including it in
    005/005a deliberately, this test should be revisited - it is not
    expected to fail on its own, but exists to make the "no writer today"
    claim this phase's reasoning depends on explicit and checkable."""
    search_roots = []
    for pattern in ("scripts/*.py", "scripts/*.ps1", "harvesters/**/*.py"):
        search_roots.extend(REPO_ROOT.glob(pattern))
    assert search_roots, "expected at least one script/harvester file to scan"
    for path in search_roots:
        text = path.read_text(errors="ignore")
        for field in DEFERRED_UNBUILT_FIELDS:
            assert f'"{field}"' not in text and f"'{field}'" not in text, (
                f"found a possible writer reference to {field!r} in {path} - "
                "re-review whether outcome/sold_price should still be "
                "excluded from 005/005a"
            )


def test_dor_use_code_still_kept_and_still_documented_as_gated():
    assert "dor_use_code" in _005_returns_table_columns()
    assert "dor_use_code" in _005a_grant_columns()


# ==================== documentation: the ordering dependency is written down, not implicit ====================


def test_schema_v9_documents_the_005_ordering_dependency():
    sql = _read("schema-v9-dor-use-code.sql")
    assert "MUST RUN BEFORE" in sql
    assert "005_customer_safe_properties_projection.sql" in sql


def test_005_documents_the_schema_v9_prerequisite():
    sql = _read("scripts", "migrations", "005_customer_safe_properties_projection.sql")
    assert "schema-v9-dor-use-code.sql" in sql
    assert "CORRECTION, Phase 14D" in sql


def test_005a_documents_the_schema_v9_prerequisite():
    sql = _read("scripts", "migrations", "005a_close_direct_properties_grant.sql")
    assert "schema-v9-dor-use-code.sql" in sql
    assert "CORRECTION, Phase 14D" in sql


def test_005_and_005a_column_lists_still_agree_after_the_correction():
    """Regression for test_A_005_and_005a_column_lists_are_identical
    (Phase 14B) - re-asserted here as a Phase 14D-scoped guard so a future
    reader of this file alone can see the invariant Phase 14D was
    required to preserve, not just that it existed before.

    UPDATED, Phase 14E (Corrective Migration 005 / get_properties()
    Function Contract): the invariant itself changed - get_properties()'s
    own WHERE clause reads `ledger_type` internally (security invoker),
    so 005a must grant it too even though 005 never returns it. See
    tests/python/test_phase14b_database_api_boundary.py's
    GRANT_ONLY_FOR_INTERNAL_FILTERING and its own updated test in this
    same group for the full reasoning. The Phase 14D-era invariant (exact
    equality) no longer holds; this guard now checks the corrected one:
    005a = 005's output plus exactly that one documented exception."""
    cols_005 = _005_returns_table_columns()
    cols_005a = _005a_grant_columns()
    assert cols_005a == cols_005 | {"ledger_type"}


# ==================== no production SQL was executed, no schema/RLS/source changes ====================


def test_no_migration_file_contains_drop_column_delete_or_truncate():
    for filename in (
        "005_customer_safe_properties_projection.sql",
        "005a_close_direct_properties_grant.sql",
    ):
        sql = _read("scripts", "migrations", filename)
        code_lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
        code = "\n".join(code_lines).lower()
        assert "drop column" not in code
        assert "delete from" not in code
        assert "truncate" not in code
    v9 = _read("schema-v9-dor-use-code.sql")
    v9_code_lines = [line for line in v9.splitlines() if not line.strip().startswith("--")]
    v9_code = "\n".join(v9_code_lines).lower()
    assert "drop column" not in v9_code
    assert "delete from" not in v9_code
    assert "truncate" not in v9_code


def test_governance_registry_unchanged_this_phase():
    assert SOURCE_REGISTRY["tx_lgbs"].legal_status == SourceStatus.APPROVED
    assert SOURCE_REGISTRY["tx_realauction"].legal_status == SourceStatus.APPROVED
    assert SOURCE_REGISTRY["tx_hctax"].legal_status == SourceStatus.LEGAL_REVIEW_REQUIRED
    for blocked in ("tx_pbfcm", "tx_govease", "tx_mvba", "tx_ctsa"):
        assert SOURCE_REGISTRY[blocked].legal_status == SourceStatus.BLOCKED
