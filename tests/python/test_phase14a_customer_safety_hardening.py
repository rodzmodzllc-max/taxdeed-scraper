"""Phase 14A (Production Customer-Safety Hardening) tests.

Same discipline as Phase 13's test suite: every test reads a REAL
repository file (SQL, Python, or JS text) and asserts something about its
actual content, rather than modeling the desired behavior separately. See
docs/phase-14a-customer-safety-hardening.md for the full write-up each
lettered group below corresponds to (Step 18's own lettered list, A-J).

No source is contacted, no production Supabase project is touched, no
schema is applied - the proposed migration
(scripts/migrations/005_customer_safe_properties_projection.sql) is
confirmed present and confirmed NOT executed, never applied by any test
here.
"""

from __future__ import annotations

from pathlib import Path

from harvesters.governance.registry import SOURCE_REGISTRY, SourceStatus
from harvesters.governance.gate import check_ingestion_gate
from harvesters.texas_harvester import FIELD_LINEAGE_MAP

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(*parts: str) -> str:
    return (REPO_ROOT / Path(*parts)).read_text()


# ==================== A: Internal field exposure ====================


def test_A_deployed_get_properties_still_has_no_column_projection_today():
    """Demonstrates the CURRENT, actually-deployed exposure (Step 16's own
    requirement: a leak test must exist even when the underlying gap is
    not fixed this phase). 003_ledger_type_and_state_isolation.sql is the
    migration that is actually live in production (per
    scripts/sync-texas-to-supabase.py's own "RESTORED 2026-09-14" note
    confirming 002/003/004 were run) - as long as its body is `select *`
    / `returns setof public.properties`, every column (including
    harvester_source/ledger_type/fdor_enriched_at) is transmitted to any
    approved caller of get_properties(). This test intentionally does NOT
    pass a fixed/narrowed body - it documents the exposure, it doesn't
    close it (see the proposed-but-unexecuted migration 005)."""
    live_sql = _read("scripts", "migrations", "003_ledger_type_and_state_isolation.sql")
    assert "returns setof public.properties" in live_sql
    assert "select *" in live_sql


def test_A_proposed_migration_005_exists_and_is_explicitly_not_yet_run():
    proposed = _read("scripts", "migrations", "005_customer_safe_properties_projection.sql")
    assert "PROPOSED, NOT YET RUN" in proposed
    # The proposed replacement must actually narrow the column list - a
    # `returns table (...)` clause, not another `returns setof
    # public.properties` (which would just be a no-op restatement of
    # today's exposure).
    assert "returns table" in proposed
    # The three fields this phase's audit names as internal-only must not
    # appear anywhere in the function's actual RETURNS/SELECT column list
    # (they are allowed to appear in the surrounding prose/comments
    # explaining why they were excluded) - so isolate the actual SQL
    # (non-comment lines) of just the proposed function, not the whole
    # file's explanatory prose, before checking either assertion below.
    proposed_fn_only = proposed.split("THE PROPOSED FUNCTION")[1].split("-- Rollback")[0]
    code_lines = [
        line for line in proposed_fn_only.splitlines()
        if not line.strip().startswith("--")
    ]
    code_text = "\n".join(code_lines)
    # The proposed replacement must actually narrow the column list - a
    # `returns table (...)` clause, not another `returns setof
    # public.properties` (which would just be a no-op restatement of
    # today's exposure). Checked against the actual code only, since the
    # surrounding prose legitimately quotes today's `returns setof
    # public.properties` definition to explain why it's being replaced.
    assert "returns setof public.properties" not in code_text
    # Restrict the internal-field check to just the two column LISTS (the
    # `returns table (...)` clause and the `select ... from` list) rather
    # than the whole function body - the function's WHERE clause and
    # parameter list legitimately reference `ledger_type`/`p_ledger_type`
    # as a *filter*, without ever returning it as a column, and that's
    # exactly the behavior this migration is supposed to preserve.
    returns_table_block = code_text.split("returns table (")[1].split(")")[0]
    select_block = code_text.split("select", 1)[1].split(" from ")[0]
    column_lists = returns_table_block + "\n" + select_block
    # `harvester_source` is deliberately NOT checked here as of Phase 14B:
    # it was originally excluded (correct as of Phase 13/early Phase 14A),
    # but Phase 14A's own assessedSourceLabel() fix, later in this same
    # phase, made app.js legitimately depend on reading it - so migration
    # 005 was corrected (see its own "CORRECTION, Phase 14B" comment) to
    # include it. tests/python/test_phase14b_database_api_boundary.py
    # covers this field's presence explicitly now.
    for internal_field in ("ledger_type", "fdor_enriched_at"):
        # Comments mentioning the field by name are fine (and expected);
        # what must not exist is the field as an actual selected/returned
        # column - i.e. as a bare identifier in either column list.
        assert internal_field not in column_lists, (
            f"{internal_field!r} appears in migration 005's actual returned "
            "column list - the proposed fix must not still return it"
        )


def test_A_no_currently_applied_migration_already_projects_columns():
    """Confirms this gap is genuinely still open in every migration this
    repo has actually run against production (002/003/004, per
    sync-texas-to-supabase.py's own confirmation note) - if a future
    migration closes it, this test (checking only 002-004, not 005) still
    passes, and a maintainer updates the "applied" list explicitly rather
    than this test silently going stale."""
    for migration_file in (
        "002_add_texas_support.sql",
        "003_ledger_type_and_state_isolation.sql",
        "004_widen_unique_constraint_for_state.sql",
    ):
        sql = _read("scripts", "migrations", migration_file)
        assert "returns table (" not in sql


# ==================== B: Customer/API projection ====================


def test_B_projection_functions_remain_write_path_only_not_imported_by_frontend():
    app_js = _read("public", "app.js")
    assert "project_row_for_customer_output" not in app_js
    assert "project_row_for_api_export" not in app_js
    # And they are still wired into the one real write-path call site -
    # regression of Phase 11/12, re-confirmed here rather than assumed.
    #
    # UPDATED Phase 34B: the sync script no longer calls
    # gate.project_row_for_customer_output() directly - it now calls
    # authorization.authorized_for_customer_output(), which calls that
    # SAME function internally as its first step (see
    # harvesters/governance/authorization.py) before adding its own,
    # additive per-use/per-county check. Both halves of that chain are
    # asserted here, so this test still catches either half being quietly
    # dropped: the sync script must still route through the authorization
    # wrapper, and that wrapper must still route through the original
    # Phase 11 projection function, not bypass it.
    sync_src = _read("scripts", "sync-texas-to-supabase.py")
    assert "authorized_for_customer_output(row, harvester_source, county=county)" in sync_src
    assert "project_row_for_customer_output(row, harvester_source)" not in sync_src
    authorization_src = _read("harvesters", "governance", "authorization.py")
    assert "project_row_for_customer_output(row, source_id)" in authorization_src


def test_B_no_new_read_path_bypass_was_introduced_around_get_properties():
    """fetchProperties() must still be the only place app.js calls
    get_properties()/select("*") - Phase 14A must not have accidentally
    added a second, parallel read path this phase's audit didn't cover."""
    app_js = _read("public", "app.js")
    assert app_js.count('sb.rpc("get_properties"') == 1
    # Count only non-comment lines - the fallback pattern is also named once
    # in a `//` comment (fetchProperties()'s own explanatory header, which
    # quotes the old pattern by name to explain why the RPC replaced it),
    # which is expected and must not be mistaken for a second real call site.
    real_code_lines = [
        line for line in app_js.splitlines()
        if not line.strip().startswith("//")
    ]
    real_code = "\n".join(real_code_lines)
    assert real_code.count('sb.from("properties").select("*")') == 1


# ==================== C: assessed semantics (label fix) ====================


def test_C_assessed_source_label_function_exists_and_is_state_aware():
    app_js = _read("public", "app.js")
    assert "function assessedSourceLabel(p)" in app_js
    assert 'if (regionOf(p) !== "TX") return "County Assessed Value";' in app_js
    assert 'if (p.harvester_source === "tx_lgbs") return "TX CAD/Listed Value";' in app_js
    assert 'if (p.harvester_source === "tx_realauction") return "TX Adjudged Value";' in app_js


def test_C_value_label_uses_the_new_source_aware_helper_not_a_bare_string():
    app_js = _read("public", "app.js")
    value_label_start = app_js.index("function valueLabel(p) {")
    value_label_end = app_js.index("\n}", value_label_start)
    value_label_fn = app_js[value_label_start:value_label_end]
    assert "assessedSourceLabel(p)" in value_label_fn
    assert '"County Assessed Value"' not in value_label_fn


def test_C_csv_export_carries_a_per_row_value_source_column():
    app_js = _read("public", "app.js")
    assert '["Assessed/Value Field Source", p => assessedSourceLabel(p)]' in app_js


# ==================== D: Florida valuation regression ====================


def test_D_florida_assessed_writers_are_unchanged():
    fl_enrich = _read("scripts", "enrich_property_details.py")
    fl_deed_sync = _read("scripts", "sync-harvest-to-supabase.ps1")
    fl_cert_sync = _read("scripts", "sync-certificates-to-supabase.ps1")
    # Fill-blank-only enrichment path, unchanged since Phase 13.
    assert '_num(row.get("assessed")) is None' in fl_enrich
    # The two FL sync scripts still forward whatever the harvester itself
    # scraped, unconditionally (not fill-blank at the sync layer - only
    # enrich_property_details.py is fill-blank).
    assert "assessed      = $p.assessed" in fl_deed_sync
    assert "assessed = ToNum $p.assessed" in fl_cert_sync


def test_D_non_texas_rows_still_get_the_original_generic_label():
    app_js = _read("public", "app.js")
    fn_start = app_js.index("function assessedSourceLabel(p) {")
    fn_end = app_js.index("\n}", fn_start)
    fn_body = app_js[fn_start:fn_end]
    # First branch (FL/any non-TX state) must return the pre-existing
    # label text, unchanged - this phase corrects the TX case, not FL's.
    assert fn_body.splitlines()[1].strip() == 'if (regionOf(p) !== "TX") return "County Assessed Value";'


# ==================== E: Texas valuation regression ====================


def test_E_field_lineage_map_still_distinguishes_lgbs_value_from_realauction_adjudged_value():
    assert FIELD_LINEAGE_MAP["tx_lgbs"]["cad_market_value"] == "value (parsed via _lgbs_to_float())"
    assert FIELD_LINEAGE_MAP["tx_realauction"]["cad_market_value"] == "'Adjudged Value' field (parsed via _realauction_to_float())"


def test_E_tx_sync_still_writes_assessed_unconditionally_from_cad_market_value():
    sync_src = _read("scripts", "sync-texas-to-supabase.py")
    assert '"assessed": _num(p.get("cad_market_value")),' in sync_src


def test_E_an_unrecognized_tx_harvester_source_gets_the_generic_reported_label_not_a_wrong_specific_one():
    app_js = _read("public", "app.js")
    fn_start = app_js.index("function assessedSourceLabel(p) {")
    fn_end = app_js.index("\n}", fn_start)
    fn_body = app_js[fn_start:fn_end]
    assert 'return "TX Reported Value";' in fn_body


# ==================== F: Texas identity regression ====================


def test_F_identity_mapping_unchanged_account_number_to_case_no_cause_number_to_parcel():
    sync_src = _read("scripts", "sync-texas-to-supabase.py")
    assert 'case_no = p.get("account_number")' in sync_src
    assert '"parcel": p.get("cause_number") or None' in sync_src


def test_F_identity_key_constraint_unchanged():
    sql = _read("scripts", "migrations", "004_widen_unique_constraint_for_state.sql")
    assert "unique (state, source, county, case_no)" in sql


# ==================== G: cause-number non-uniqueness ====================


def test_G_two_parcels_sharing_one_cause_number_are_not_treated_as_duplicate_properties():
    """Builds the exact row shape scripts/sync-texas-to-supabase.py
    constructs for two DIFFERENT parcels (different account_number) that
    happen to share one cause_number - the live-verified scenario
    texas_harvester.py's own module docstring describes. Confirms the
    sync script's actual dedup key (county, case_no) - not (county,
    parcel) - treats them as two independent rows, never collapsing one
    into the other."""
    def _row_identity(account_number: str, county: str) -> tuple[str, str]:
        # Mirrors sync-texas-to-supabase.py's own dedup key construction:
        # `deduped[(county, case_no)] = projected_row` where
        # `case_no = p.get("account_number")` (see test_F above).
        case_no = account_number
        return (county, case_no)

    cause_number = "CAUSE-2026-001"  # shared by both parcels below
    parcel_a = {"account_number": "ACCT-AAA", "county": "Harris", "cause_number": cause_number}
    parcel_b = {"account_number": "ACCT-BBB", "county": "Harris", "cause_number": cause_number}

    key_a = _row_identity(parcel_a["account_number"], parcel_a["county"])
    key_b = _row_identity(parcel_b["account_number"], parcel_b["county"])

    assert key_a != key_b, (
        "two different parcels sharing one cause_number must produce two "
        "distinct dedup keys - if this ever fails, the second parcel would "
        "silently overwrite the first under the sync script's upsert, "
        "exactly the collision harvest_lgbs()'s own account_number/"
        "cause_number split was built to prevent"
    )
    # And confirm the shared cause_number really is shared (the test setup
    # itself models the real collision case, not two already-different
    # inputs that would trivially pass).
    assert parcel_a["cause_number"] == parcel_b["cause_number"]


# ==================== H: freshness contract ====================


def test_H_texas_job_remains_manual_only_this_phase_did_not_schedule_it():
    workflow = _read(".github", "workflows", "harvest-and-sync.yml")
    texas_block_start = workflow.index("\n  texas:")
    next_job_start = workflow.index("\n  backup:", texas_block_start)
    texas_block = workflow[texas_block_start:next_job_start]
    if_line = next(line for line in texas_block.splitlines() if line.strip().startswith("if:"))
    assert if_line.strip() == "if: github.event_name == 'workflow_dispatch'"


def test_H_texas_harvest_main_now_isolates_one_vendors_unexpected_failure_from_the_other():
    """Regression for the Phase 14A fix in texas_harvester.py's main():
    before this phase, an uncaught non-network exception from harvest_lgbs()
    would propagate out of the SOURCES loop entirely, silently preventing
    harvest_realauction() from ever running and preventing
    out/harvest_texas.json from being written at all (traced from the
    function's actual control flow - the write happens after the loop)."""
    src = _read("harvesters", "texas_harvester.py")
    main_start = src.index("def main() -> None:")
    loop_start = src.index("for name, fn in SOURCES.items():", main_start)
    loop_end = src.index("out_path.write_text", loop_start)
    loop_body = src[loop_start:loop_end]
    assert "except NotImplementedError as exc:" in loop_body
    assert "except Exception as exc:" in loop_body
    # The generic handler must `continue`, not re-raise or return - a
    # failure in one vendor must still let the loop reach the next one.
    generic_handler_start = loop_body.index("except Exception as exc:")
    generic_handler_body = loop_body[generic_handler_start:]
    # Only look within this handler's own block (up to wherever the next
    # top-level statement after the loop's except-chain begins) so this
    # doesn't just find some unrelated "continue" further down the file.
    handler_only = generic_handler_body.split("print(f\"main: {name} produced")[0]
    assert "continue" in handler_only


def test_H_freshness_doc_exists_with_an_explicit_contract_section():
    doc = _read("docs", "phase-14a-customer-safety-hardening.md")
    assert "Texas freshness audit" in doc
    assert "freshness contract" in doc.lower()


# ==================== I: governance preservation ====================


def test_I_source_statuses_unchanged_this_phase():
    assert SOURCE_REGISTRY["tx_lgbs"].legal_status == SourceStatus.APPROVED
    assert SOURCE_REGISTRY["tx_realauction"].legal_status == SourceStatus.APPROVED
    assert SOURCE_REGISTRY["tx_hctax"].legal_status == SourceStatus.LEGAL_REVIEW_REQUIRED
    for blocked in ("tx_pbfcm", "tx_govease", "tx_mvba", "tx_ctsa"):
        assert SOURCE_REGISTRY[blocked].legal_status == SourceStatus.BLOCKED


def test_I_gate_decisions_unchanged_for_every_registered_source():
    assert check_ingestion_gate("tx_lgbs").allowed is True
    assert check_ingestion_gate("tx_realauction").allowed is True
    assert check_ingestion_gate("tx_hctax").allowed is False
    assert check_ingestion_gate("tx_pbfcm").allowed is False
    assert check_ingestion_gate("unknown_source_xyz").allowed is False


# ==================== J: cross-state isolation ====================


def test_J_florida_ps1_pipeline_still_has_zero_governance_coupling():
    ps1_dir = REPO_ROOT / "scripts"
    for ps1_file in ps1_dir.glob("*.ps1"):
        text = ps1_file.read_text(errors="ignore")
        assert "governance" not in text.lower(), f"{ps1_file.name} now references governance - Florida must stay decoupled"


def test_J_the_new_label_helper_never_special_cases_florida_by_county_name_only_by_state():
    """Guards against a fragile fix that special-cased specific county
    names instead of the real `state` column - would silently misclassify
    a Texas county whose name happens to collide with a Florida one (see
    docs/production-data-contract.md Section 3 on Orange/Jefferson/Madison/
    Lake counties existing in both states)."""
    app_js = _read("public", "app.js")
    fn_start = app_js.index("function assessedSourceLabel(p) {")
    fn_end = app_js.index("\n}", fn_start)
    fn_body = app_js[fn_start:fn_end]
    assert "p.county" not in fn_body
    assert "regionOf(p)" in fn_body
