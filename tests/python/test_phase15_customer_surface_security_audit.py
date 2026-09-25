"""Phase 15 (End-to-End Customer Surface Security & Contract Verification)
tests.

Two things this phase found and is guarding against regression for:

1. tests/vendor/supabase-stub.js (the mocked Supabase client the Playwright
   frontend regression suite, tests/run_test.mjs, runs against) had NO
   `rpc()` method at all, even though public/app.js's fetchProperties() has
   unconditionally called `sb.rpc("get_properties", {p_state})` as its
   primary path since 003_ledger_type_and_state_isolation.sql (2026-09-08).
   Live-reproduced this phase (not just inferred from mtimes): with the
   original stub, tests/run_test.mjs hangs and times out waiting for
   `.county-group` because fetchProperties() throws a TypeError calling
   `sb.rpc` (undefined) and no property data is ever loaded - the suite
   that every migration in this project (003/005/005a) has cited in its own
   TEST PLAN section as the way to verify frontend behavior was silently
   unable to exercise the real property-loading path at all. Fixed by
   adding an `rpc()` implementation to the stub. Group A guards against this
   regressing silently again.

2. Section 5 of docs/production-data-contract.md (Phase 13) and migration
   005's own RETURNS TABLE clause (Phase 14) are two independent
   enumerations of "the customer-safe column set" that have never been
   cross-checked against the CSV export's actual field reads. Group B does
   that reconciliation directly against both real files - every `p.<field>`
   read inside the CSV `cols` array literal must be a column 005 actually
   returns (or a documented non-DB derived/id-adjacent name), so a future
   CSV column addition can't reintroduce ledger_type/fdor_enriched_at (or
   any other column outside the customer contract) undetected.

No source is contacted, no production Supabase project is touched, no
schema is applied, no browser is launched - this file only reads local
repository files, the same discipline every phase's test file in this
project already follows.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(*parts: str) -> str:
    return (REPO_ROOT / Path(*parts)).read_text()


def _stub_js() -> str:
    return _read("tests", "vendor", "supabase-stub.js")


def _app_js() -> str:
    return _read("public", "app.js")


def _005_sql() -> str:
    return _read("scripts", "migrations", "005_customer_safe_properties_projection.sql")


def _returns_table_columns(sql: str) -> set[str]:
    block = sql.split("returns table (")[1].split(")\nlanguage sql")[0]
    # Comment lines inside the block are prose, not columns.
    block = "\n".join(l for l in block.splitlines() if not l.strip().startswith("--"))
    entries = [e.strip() for e in block.replace("\n", " ").split(",") if e.strip()]
    return {e.split()[0] for e in entries}


def _005_returns_table_columns() -> set[str]:
    """The live get_properties() contract. 005 defined it; 012 (Phase 58)
    and 013 (Phase 72) each dropped and recreated the function with columns
    APPENDED, so the live RETURNS TABLE is the latest of those definitions.
    Read the highest-numbered migration that (re)creates the function, so a
    CSV column added alongside a projection change reconciles against the
    contract that is actually live rather than against 005 alone."""
    latest = None
    for path in sorted((REPO_ROOT / "scripts" / "migrations").glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        if "create function public.get_properties(" in text and "returns table (" in text:
            latest = text
    assert latest is not None
    return _returns_table_columns(latest)


def _csv_cols_block() -> str:
    """The literal `const cols = [ ... ];` array inside the CSV export
    click handler - isolated by its own start/end markers so a change
    elsewhere in the file (e.g. a different `cols` variable) can't be
    mistaken for this one."""
    app_js = _app_js()
    start = app_js.index("const cols = [")
    end = app_js.index("\n  ];", start)
    return app_js[start:end]


# ==================== A: Playwright stub rpc() regression guard ====================


def test_A_supabase_stub_implements_rpc():
    """Regression guard for the exact defect this phase found and fixed:
    the stub client object returned by createClient() must expose an
    `rpc` method - app.js calls `sb.rpc(...)` unconditionally as
    fetchProperties()'s primary path, and a stub with no `rpc` key makes
    that call throw synchronously (`sb.rpc is not a function`), silently
    starving every property-dependent assertion in tests/run_test.mjs
    with no property data ever loading (live-reproduced this phase: the
    suite hangs and times out waiting for `.county-group` with the
    original, pre-fix stub)."""
    stub = _stub_js()
    # Isolate the object literal createClient() returns so a `rpc` method
    # defined somewhere unrelated in the file can't satisfy this check.
    body = stub.split("export function createClient()", 1)[1]
    assert re.search(r"\brpc\s*\(", body), (
        "tests/vendor/supabase-stub.js's createClient() must implement an "
        "rpc() method - app.js's fetchProperties() calls sb.rpc(...) "
        "unconditionally and has no fallback for a client that lacks the "
        "method entirely (only for a *function* the RPC layer reports as "
        "missing, a different error shape - see test below)"
    )


def test_A_stub_rpc_handles_get_properties_specifically():
    """The one RPC app.js actually calls must be handled by name, not just
    a generic passthrough - a stub that always returns the same canned
    rows regardless of function name would silently pass even if app.js
    started calling the wrong RPC name."""
    stub = _stub_js()
    body = stub.split("async rpc(", 1)[1]
    assert '"get_properties"' in body or "'get_properties'" in body


def test_A_stub_rpc_falls_back_to_a_pgrst202_shape_for_unknown_functions():
    """Mirrors PostgREST's real "function not found" error shape
    (rpc.error.code === "PGRST202") for any RPC name other than
    get_properties, so app.js's own missingFn fallback-detection logic
    (fetchProperties()'s `missingFn = rpc.error.code === "PGRST202" || ...`)
    remains exercisable against this stub if a future test needs it,
    instead of the stub silently returning success for a typo'd RPC name."""
    stub = _stub_js()
    body = stub.split("async rpc(", 1)[1].split("\n    }", 1)[0]
    assert "PGRST202" in body


def test_A_fetchProperties_still_calls_get_properties_as_its_primary_path():
    """Companion regression check: the stub fix is only meaningful if this
    remains true. If a future change made fetchProperties() call something
    else first, the stub's rpc() implementation would need updating too -
    this test makes that dependency explicit rather than implicit."""
    app_js = _app_js()
    assert 'sb.rpc("get_properties", { p_state: PAGE_STATE })' in app_js


# ==================== B: CSV field reconciliation against 005's live contract ====================


# Names the CSV `cols` array calls as functions (derived/computed values,
# or a state-derivation helper) rather than reading a `p.<field>` DB column
# directly inline - out of scope for this direct-field reconciliation, same
# boundary docs/production-data-contract.md Section 5 already draws between
# "column" and "client-derived, never-stored figure." Listed explicitly,
# not detected structurally, so an addition to this list is a deliberate,
# reviewable decision rather than a silent regex loosening.
CSV_HELPER_FUNCTIONS_NOT_DIRECT_COLUMN_READS = {
    "regionOf",
    "assessedSourceLabel",
    "marketOf",
    "valueRatio",
    "fees",
    "buildingValue",
    "accruedInterestEst",
    "tdaEligibleMs",
    "fallbackStreetviewUrl",
    "fallbackZillowUrl",
}


def _csv_direct_field_reads() -> set[str]:
    """Every `p.<identifier>` read directly inside the cols array literal
    (e.g. `p.county`, `p.bid`) - excludes helper-function calls like
    `assessedSourceLabel(p)`, which read columns elsewhere in the file and
    are out of scope for this direct-textual reconciliation (see the
    constant above)."""
    block = _csv_cols_block()
    return set(re.findall(r"\bp\.([A-Za-z_][A-Za-z0-9_]*)\b", block))


def test_B_every_direct_csv_column_read_is_in_005s_customer_safe_output():
    """The core reconciliation this phase's Section 14 asks for: every
    field the CSV export reads directly off a property row must be a
    column get_properties() (the corrected, live-since-Phase-14H version)
    actually returns. A field here that is NOT in 005's output would mean
    the CSV either silently exports `undefined` (if the RPC path is used,
    since 005 no longer returns non-listed columns) or - worse - depends
    on the raw-table select("*") fallback path staying reachable, which is
    exactly the bypass this phase's frontend audit checked for separately."""
    direct_reads = _csv_direct_field_reads()
    output_cols = _005_returns_table_columns()
    unexplained = direct_reads - output_cols
    assert not unexplained, (
        f"CSV export reads column(s) {sorted(unexplained)} directly, but "
        "005_customer_safe_properties_projection.sql's RETURNS TABLE clause "
        "does not include them - either the CSV column is dead (the RPC "
        "path returns undefined for it) or it silently depends on the "
        "select(\"*\") fallback ever running, which must not be the case "
        "for a column meant to be part of the live customer contract"
    )


def test_B_csv_never_reads_ledger_type_or_fdor_enriched_at_directly():
    """Belt-and-suspenders on top of test_B above (which would already
    catch this, since neither column is in 005's output) - scoped
    precisely to the CSV `cols` array text itself, per this phase's own
    Section 5 instruction to explicitly verify these two are excluded."""
    block = _csv_cols_block()
    assert "ledger_type" not in block
    assert "fdor_enriched_at" not in block


def test_B_csv_helper_function_list_is_still_accurate():
    """Guards the CSV_HELPER_FUNCTIONS_NOT_DIRECT_COLUMN_READS allowlist
    itself against silent drift: every name in it must still actually
    appear, called with `(p)` or `(p,`, inside the cols array - if a future
    edit removes a helper call this list assumes exists, that's worth
    catching rather than leaving stale scope-narrowing in place."""
    block = _csv_cols_block()
    for fn in CSV_HELPER_FUNCTIONS_NOT_DIRECT_COLUMN_READS:
        assert re.search(rf"\b{re.escape(fn)}\(p[,)]", block), (
            f"{fn} is listed as a CSV helper-function exception but no "
            "longer appears (called with p) in the cols array - remove it "
            "from the allowlist if it's genuinely gone"
        )


def test_B_005_output_reconciles_with_phase13_baseline_exclusions():
    """Cross-check against the pre-005 contract doc's own excluded-fields
    list (docs/production-data-contract.md Section 6): outcome/sold_price/
    harvester_source's disposition must match what that document and this
    phase's live-verified 005 both say - outcome/sold_price genuinely
    absent (no writer, not part of the live schema), harvester_source
    genuinely present (the frontend has a real, load-bearing read of it via
    assessedSourceLabel())."""
    output_cols = _005_returns_table_columns()
    assert "outcome" not in output_cols
    assert "sold_price" not in output_cols
    assert "ledger_type" not in output_cols
    assert "fdor_enriched_at" not in output_cols
    assert "harvester_source" in output_cols
