"""Phase 14E (Corrective Migration 005 / get_properties() Function
Contract) tests.

Phase 14C/14F's production execution attempt applied schema-v9
successfully, then failed on 005 with a live Postgres error:

    ERROR:  42P13: cannot change return type of existing function
    HINT:  Use DROP FUNCTION get_properties(text,text,text,integer,integer)
           first.

This file proves, statically against the actual repository files, that
the corrected 005/005a fix that specific defect (an explicit DROP
FUNCTION before CREATE, wrapped in a transaction) without silently
losing anything: the EXECUTE grant, the function's argument signature
(so app.js's existing RPC call keeps working with no frontend deploy),
its SECURITY INVOKER mode, and the customer-safe column boundary. It
also proves, from PostgreSQL privilege semantics and the actual function
body, the second defect this phase's own analysis found: get_properties()
reads `ledger_type` in its WHERE clause even though it never returns it,
so 005a must still grant that one column - a documented, narrow exception
to an otherwise-closed boundary, covered here and in
tests/python/test_phase14b_database_api_boundary.py's own updated group B.

No source is contacted, no production Supabase project is touched, no
schema is applied - this file only ever reads local repository files.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(*parts: str) -> str:
    return (REPO_ROOT / Path(*parts)).read_text()


def _005_full_sql() -> str:
    return _read("scripts", "migrations", "005_customer_safe_properties_projection.sql")


def _005_executable_code() -> str:
    """The actual forward-migration SQL (between `begin;` and the
    `-- Rollback` comment block), comments stripped - mirrors the
    comment-stripping pattern every other phase's test file already uses
    for this kind of check."""
    full = _005_full_sql()
    block = full.split("begin;", 1)[1].split("-- Rollback", 1)[0]
    code_lines = [line for line in block.splitlines() if not line.strip().startswith("--")]
    return "\n".join(code_lines)


def _005a_full_sql() -> str:
    return _read("scripts", "migrations", "005a_close_direct_properties_grant.sql")


def _005_returns_table_columns() -> set[str]:
    sql = _005_full_sql()
    block = sql.split("returns table (")[1].split(")\nlanguage sql")[0]
    entries = [e.strip() for e in block.replace("\n", " ").split(",") if e.strip()]
    return {e.split()[0] for e in entries}


def _005a_grant_columns() -> set[str]:
    sql = _005a_full_sql()
    block = sql.split("grant select (")[1].split(") on public.properties")[0]
    return {c.strip() for c in block.split(",") if c.strip()}


def _param_block(sql: str, after: str, before: str) -> str:
    return sql.split(after, 1)[1].split(before, 1)[0]


# ==================== 1/2: DROP FUNCTION fixes the exact live failure ====================


def test_1_005_drops_the_exact_live_function_signature_before_recreating():
    """The DROP FUNCTION target must exactly match the signature
    Postgres's own error HINT named (text,text,text,integer,integer, as
    `int`/`integer` are the same type) - and it must be `if exists`, so
    this file stays idempotent if re-run after a partial attempt."""
    code = _005_executable_code()
    assert "drop function if exists public.get_properties(text, text, text, int, int);" in code
    # Ordering: the DROP must come before the CREATE, not after.
    drop_pos = code.index("drop function if exists")
    create_pos = code.index("create or replace function public.get_properties(")
    assert drop_pos < create_pos


def test_2_005_no_longer_attempts_a_bare_create_or_replace_across_a_return_type_change():
    """Regression for the exact 42P13 failure: the live function is
    `returns setof public.properties`; that exact phrase must not appear
    in the executable forward migration (it only appears inside the
    Rollback comment block, which intentionally reproduces the pre-005
    shape for reverting)."""
    code = _005_executable_code()
    assert "returns setof public.properties" not in code
    assert "returns table (" in code


def test_005_wraps_drop_and_create_in_one_explicit_transaction():
    """Checked against the raw forward-migration text (not comment-
    stripped, since the comment-stripping helper's own split on `begin;`
    consumes that token) - uses the full, specific DROP FUNCTION
    statement text (not just the substring "drop function if exists",
    which also appears, correctly, inside this file's own explanatory
    header prose above the statement) so this can't be fooled by that
    prose."""
    full = _005_full_sql()
    forward = full.split("-- Rollback", 1)[0]
    assert "begin;" in forward
    assert "commit;" in forward
    begin_pos = forward.index("begin;")
    drop_pos = forward.index("drop function if exists public.get_properties(text, text, text, int, int);")
    grant_pos = forward.index("grant execute on function public.get_properties")
    commit_pos = forward.rindex("commit;")
    assert begin_pos < drop_pos < grant_pos < commit_pos


def test_rollback_comment_also_drops_before_recreating():
    """The rollback (reverting FROM the new named-columns shape BACK TO
    `returns setof public.properties`) is exactly the same return-type
    change in reverse, so it needs the identical drop-then-create fix -
    not just the forward migration."""
    full = _005_full_sql()
    rollback = full.split("-- Rollback", 1)[1]
    assert "drop function if exists public.get_properties(text, text, text, int, int);" in rollback


# ==================== 10/11/12: signature, grants, security mode preserved ====================


def test_10_app_js_rpc_call_remains_compatible_005s_argument_signature_unchanged():
    """The corrected 005 must declare the exact same parameter list (names,
    types, order, defaults) as the function app.js already calls via
    `sb.rpc("get_properties", { p_state: PAGE_STATE })` - proven here by
    comparing 005's actual parameter block, byte-for-byte, against
    003_ledger_type_and_state_isolation.sql's original (still the live
    signature, since only 005 executing successfully would change it, and
    it hasn't yet). PostgREST/Supabase resolves an RPC call by function
    name plus JSON argument names, so this identity is exactly what makes
    a frontend deploy unnecessary alongside this migration."""
    live_sql = _read("scripts", "migrations", "003_ledger_type_and_state_isolation.sql")
    live_params = _param_block(
        live_sql, "create or replace function public.get_properties(", ")\nreturns setof"
    )
    corrected_params = _param_block(
        _005_executable_code(), "create or replace function public.get_properties(", ")\nreturns table"
    )
    assert live_params.strip() == corrected_params.strip()

    app_js = _read("public", "app.js")
    assert 'sb.rpc("get_properties", { p_state: PAGE_STATE })' in app_js


def test_11_005_grant_execute_preserves_the_full_live_role_set_not_narrowed():
    """Regression for the phase's own hard rule ("do not silently lose
    EXECUTE privileges"): DROP FUNCTION discards every grant the old
    function held. Phase 14E/14F's live audit found EXECUTE is currently
    held by service_role, authenticated, anon, postgres, and PUBLIC - not
    just `authenticated` (003's own original, narrower grant). The
    corrected file must re-grant the exact live set, not silently narrow
    to 003's original intent as a side effect of fixing the DROP/CREATE
    defect - narrowing is a separate, future, explicitly-scoped decision."""
    code = _005_executable_code()
    assert (
        "grant execute on function public.get_properties(text, text, text, int, int)\n"
        "  to service_role, authenticated, anon, postgres, public;" in code
    )


def test_12_005_still_security_invoker_not_definer():
    """This phase's own hard rule: do not change SECURITY INVOKER to
    SECURITY DEFINER as a workaround for anything - it was not touched,
    and must not have been, by this correction."""
    code = _005_executable_code()
    assert "security invoker" in code
    assert "security definer" not in code


# ==================== 14: 005a's compatibility with the corrected function ====================


def test_14_005a_grants_ledger_type_for_internal_filtering_but_005_never_returns_it():
    """The core Phase 14E finding, proven from the actual function body
    and the actual grant list together, not asserted in isolation:
    get_properties() (security invoker, unchanged) reads `ledger_type` in
    its own WHERE clause to implement the p_ledger_type filter - so
    `authenticated` must retain column-level SELECT on it, or every
    authenticated call to get_properties() fails with "permission denied
    for column ledger_type" the moment 005a's narrowed grant takes
    effect. 005 must still never RETURN it (that's the whole point of
    this migration pair)."""
    where_clause = _005_executable_code().split("where state = p_state", 1)[1].split("order by", 1)[0]
    assert "ledger_type = p_ledger_type" in where_clause, (
        "expected get_properties()'s WHERE clause to still filter on "
        "ledger_type internally - if this changed, the ledger_type grant "
        "exception in 005a may no longer be necessary and should be "
        "re-reviewed, not left in place unexamined"
    )
    assert "ledger_type" not in _005_returns_table_columns()
    assert "ledger_type" in _005a_grant_columns()


def test_14_fdor_enriched_at_has_no_such_dependency_and_stays_fully_closed():
    """Unlike ledger_type, fdor_enriched_at is never referenced anywhere
    in get_properties()'s function body (not in the WHERE clause, not in
    ORDER BY, not in the SELECT list) - so it has no privilege dependency
    forcing a grant, and remains absent from both 005's output and 005a's
    grant list with no exception."""
    code = _005_executable_code()
    # Isolate just the function body (from `as $$` to the closing `$$;`)
    # so a passing mention in a header comment elsewhere in the file can
    # never satisfy this check.
    body = code.split("as $$", 1)[1].split("$$;", 1)[0]
    assert "fdor_enriched_at" not in body
    assert "fdor_enriched_at" not in _005a_grant_columns()


def test_005a_documents_the_ledger_type_exception_explicitly():
    sql = _005a_full_sql()
    assert "CORRECTION, Phase 14E" in sql
    assert "ledger_type" in sql
    assert "security invoker" in sql.lower()


# ==================== full contract sanity: nothing else moved ====================


def test_005_output_column_set_unchanged_from_phase_14d_by_this_correction():
    """This phase fixes DROP/CREATE mechanics and the EXECUTE grant - it
    must not, as a side effect, change which columns 005 actually
    returns. dor_use_code stays in, outcome/sold_price stay out,
    ledger_type/fdor_enriched_at stay out - exactly Phase 14D's own
    column decision, untouched by this phase's DDL-shape fix."""
    cols = _005_returns_table_columns()
    assert "dor_use_code" in cols
    assert "harvester_source" in cols
    for excluded in ("outcome", "sold_price", "ledger_type", "fdor_enriched_at"):
        assert excluded not in cols
