"""Migration 015 (customer write privileges + self-service account deletion)
- contract tests.

Two layers, same discipline as test_migration_014_auction_event_history.py:

1. STATIC (always run, in CI too): the migration FILE is read as text and
   checked for exactly what it does and what it must not touch. The
   "do not blindly revoke" rule is enforced here from the frontend source:
   every table the migration closes to client roles is asserted to be one
   the app never reads or writes, and every table the app DOES write is
   asserted to keep its DML grant.

2. LIVE (runs only where a local PostgreSQL is reachable; skipped otherwise):
   the migration is applied VERBATIM to a throwaway scratch database on top
   of tests/python/fixtures/migration_015_scratch_fixture.sql, then exercised
   role by role with `set role` + `request.jwt.claims`, the same mechanism
   Supabase's PostgREST uses. The Supabase project is never contacted.

What the live layer proves, in the brief's own words:
  - an approved user cannot INSERT/UPDATE/DELETE shared `properties` (or
    `county_calendar`);
  - customer-safe reads (get_properties() and the direct SELECT fallback)
    still work for an approved user, and return nothing for a pending one;
  - service_role writes still work (the harvest/sync path);
  - own-row isolation on favorites/hidden/bid_list/notes is intact and the
    bid-list limit trigger still fires after its EXECUTE revoke;
  - delete_my_account() removes exactly the caller's auth row, profile,
    notes, favorites, hidden and bid-list rows - never another user's rows
    and never a row of shared property intelligence;
  - anon cannot call delete_my_account(); a pending (approved=false) user
    can (they own their account either way).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "scripts" / "migrations" / "015_customer_write_privileges_and_account_deletion.sql"
FIXTURE = REPO / "tests" / "python" / "fixtures" / "migration_015_scratch_fixture.sql"
DOC = REPO / "docs" / "production-configuration.md"

SQL = MIGRATION.read_text(encoding="utf-8")
FRONTEND = [REPO / "public" / f for f in ("app.js", "explore.js", "satellite-map.js")]
FRONTEND_TEXT = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in FRONTEND)

USER_A = "11111111-1111-1111-1111-111111111111"
USER_B = "22222222-2222-2222-2222-222222222222"
USER_PENDING = "33333333-3333-3333-3333-333333333333"

LEGACY_TABLES = [
    "auction_records", "auctions", "tax_auctions", "tax_deeds", "tax_liens",
    "scrape_review_queue", "scraper_review_queue", "scraping_logs", "states",
]
CUSTOMER_TABLES = ["notes", "favorites", "hidden", "bid_list", "profiles"]
PINNED_FUNCTIONS = [
    "get_properties", "properties_sync_geom", "set_updated_at", "sync_ledger_type_from_source",
    "touch_updated_at", "track_gone_since", "track_gone_since_insert", "update_modified_column",
]


def sql_only() -> str:
    return "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--"))


def statements() -> list[str]:
    body = sql_only()
    # The delete_my_account body contains ';' inside $$ ... $$ - split those out first.
    body = re.sub(r"\$\$.*?\$\$", "$$BODY$$", body, flags=re.S)
    return [re.sub(r"\s+", " ", s).strip().lower() for s in body.split(";") if s.strip()]


def app_tables_referenced() -> set[str]:
    return set(re.findall(r'\.from\("([a-z_]+)"\)', FRONTEND_TEXT))


# ==================== STATIC ====================


def test_s01_file_exists_is_transactional_and_named_next():
    assert MIGRATION.exists()
    numbered = sorted(p.name for p in (REPO / "scripts" / "migrations").glob("*.sql"))
    assert numbered[numbered.index("014_auction_event_history.sql") + 1] == MIGRATION.name
    stmts = statements()
    assert stmts[0] == "begin"
    assert stmts[-1] == "commit"


def test_s02_properties_becomes_read_only_for_customers_without_a_zero_permissive_window():
    stmts = statements()
    create = next(i for i, s in enumerate(stmts) if s.startswith('create policy "properties: approved read"'))
    drop = next(i for i, s in enumerate(stmts) if s == 'drop policy "properties: approved only" on public.properties')
    # The SELECT policy must exist BEFORE the FOR ALL policy is dropped -
    # CLAUDE.md's 2026-08-24 outage was a table with zero permissive policies.
    assert create < drop
    # 026's once-per-statement form is kept (a bare is_approved() is per row).
    assert "for select to authenticated using ((select public.is_approved()))" in stmts[create]
    assert "with check" not in stmts[create]
    assert any(s == "revoke insert, update, delete, truncate, references, trigger on public.properties from anon, authenticated" for s in stmts)


def test_s03_county_calendar_same_posture():
    stmts = statements()
    create = next(i for i, s in enumerate(stmts) if s.startswith('create policy "county_calendar: approved read"'))
    drop = next(i for i, s in enumerate(stmts) if s == 'drop policy "county_calendar: approved only" on public.county_calendar')
    assert create < drop
    assert any(s == "revoke insert, update, delete, truncate, references, trigger on public.county_calendar from anon, authenticated" for s in stmts)


def test_s04_select_grants_and_get_properties_untouched():
    body = sql_only().lower()
    # 005a's column-level SELECT grant is the read path; 015 must not revoke
    # SELECT from authenticated on properties or recreate get_properties.
    assert "revoke select on public.properties" not in body
    assert "revoke all on public.properties" not in body
    assert "create function public.get_properties" not in body
    assert "create or replace function public.get_properties" not in body
    assert "drop function public.get_properties" not in body
    assert "alter function public.get_properties(text, text, text, integer, integer) set search_path = public" in body


def test_s05_customer_tables_keep_dml_for_authenticated_lose_everything_for_anon():
    stmts = statements()
    joined = ", ".join(f"public.{t}" for t in CUSTOMER_TABLES)
    assert f"revoke all on {joined} from anon" in stmts
    assert f"revoke truncate, references, trigger on {joined} from authenticated" in stmts
    for t in CUSTOMER_TABLES:
        # No statement may take INSERT/UPDATE/DELETE/SELECT from authenticated on a customer table.
        for s in stmts:
            if "from authenticated" in s and f"public.{t}" in s:
                assert not re.search(r"\b(insert|update|delete|select|all)\b", s.split(" on ")[0]), s


def test_s06_not_blindly_revoked_every_closed_table_is_unreferenced_by_the_app():
    """The brief: inspect app queries before revoking. Every table the
    migration closes entirely must be absent from every sb.from() in the
    frontend, and every table the app writes must not be closed."""
    referenced = app_tables_referenced()
    for t in LEGACY_TABLES:
        assert t not in referenced, f"{t} is referenced by the frontend - revoke would break it"
    stmts = statements()
    legacy_stmt = next(s for s in stmts if s.startswith("revoke all on public.auction_records"))
    for t in LEGACY_TABLES:
        assert f"public.{t}" in legacy_stmt
    assert legacy_stmt.endswith("from anon, authenticated")
    # Tables the app writes stay writable for authenticated.
    for t in ("notes", "favorites", "hidden", "bid_list", "profiles"):
        assert t in referenced
    # Tables the app only reads: properties (rpc + select fallback) and county_calendar.
    assert re.search(r'from\("properties"\)\.select\(', FRONTEND_TEXT)
    assert not re.search(r'from\("properties"\)\.(insert|update|delete|upsert)\(', FRONTEND_TEXT)
    assert not re.search(r'from\("county_calendar"\)\.(insert|update|delete|upsert)\(', FRONTEND_TEXT)


def test_s07_trigger_functions_closed_and_search_paths_pinned():
    stmts = statements()
    assert "revoke execute on function public.handle_new_user() from public, anon, authenticated" in stmts
    assert "revoke execute on function public.enforce_bid_list_limit() from public, anon, authenticated" in stmts
    for fn in PINNED_FUNCTIONS:
        assert any(s.startswith(f"alter function public.{fn}(") and s.endswith("set search_path = public") for s in stmts), fn


def test_s07b_guard_and_signed_in_only_helpers():
    body = sql_only()
    stmts = statements()
    guard = body.index("015 guard")
    assert guard < body.index('create policy "properties: approved read"')
    assert "polname = 'properties: approved only'" in body and "polname = 'county_calendar: approved only'" in body
    for fn in ("public.is_approved()", "public.is_admin()", "public.get_properties(text, text, text, integer, integer)"):
        assert f"revoke execute on function {fn} from public, anon" in stmts, fn
        assert f"grant execute on function {fn} to authenticated, service_role" in stmts, fn
    # Never weaken: no new grant to anon, no SECURITY DEFINER other than delete_my_account.
    assert not any(" to anon" in s and s.startswith("grant") for s in stmts)
    assert body.lower().count("security definer") == 1


def test_s08_delete_my_account_shape():
    body = sql_only()
    m = re.search(r"create function public\.delete_my_account\(\)(.*?)\$\$;", body, re.S)
    assert m
    fn = m.group(1)
    assert "security definer" in fn
    assert "set search_path = public" in fn
    assert "auth.uid()" in fn
    assert "raise exception" in fn  # no-session guard
    for t in ("public.notes", "public.favorites", "public.hidden", "public.bid_list", "public.profiles", "auth.users"):
        assert f"delete from {t}" in fn, t
    # Every delete is scoped to the caller - never a bare delete.
    for line in fn.splitlines():
        if line.strip().startswith("delete from"):
            assert "= uid" in line, line
    # Shared property intelligence is never named by the function.
    for shared in ("public.properties", "county_calendar", "auction_events", "auction_event_observations"):
        assert shared not in fn, shared
    stmts = statements()
    assert "revoke execute on function public.delete_my_account() from public, anon" in stmts
    assert "grant execute on function public.delete_my_account() to authenticated" in stmts


def test_s09_no_data_changes_no_service_role_changes_no_notes_policy_change():
    body = sql_only().lower()
    # service_role is only ever GIVEN execute (so revoking PUBLIC never takes
    # it away) - nothing is revoked from it and no table grant names it.
    for stmt in statements():
        if "service_role" in stmt:
            assert stmt.startswith("grant execute on function public.") and stmt.endswith("to authenticated, service_role"), stmt
    for verb in ("insert into", "update public.", "truncate table", "truncate public.", "drop table", "alter table"):
        assert verb not in body, verb
    # `delete from` only inside the function body.
    outside = re.sub(r"\$\$.*?\$\$", "", body, flags=re.S)
    assert "delete from" not in outside
    for notes_policy in ("notes: read if approved", "notes: approved only", "insert own note", "update own note", "delete own note"):
        assert notes_policy not in body


def test_s10_frontend_calls_the_rpc_and_labels_notes_as_shared():
    app = (REPO / "public" / "app.js").read_text(encoding="utf-8")
    assert 'rpc("delete_my_account")' in app
    # Notes are intentionally shared; the UI must say so where notes are written.
    assert "Shared with every approved member, with your email name - not private" in app
    for f in ("public/index.html", "public/tx.html"):
        html = (REPO / f).read_text(encoding="utf-8")
        assert "Team notes are shared" in html and "they are not private" in html, f


def test_s11_production_configuration_doc_names_the_migration_and_the_dashboard_items():
    doc = DOC.read_text(encoding="utf-8")
    assert MIGRATION.name in doc
    for item in ("Leaked password protection", "Site URL", "Redirect URLs", "delete_my_account"):
        assert item in doc, item


# ==================== LIVE ====================


def _psql_prefix() -> list[str] | None:
    override = os.environ.get("TDW_SCRATCH_PG")
    candidates = [override.split()] if override else []
    if shutil.which("psql"):
        candidates += [["psql"], ["su", "postgres", "-c", "psql"]]
    for cand in candidates:
        try:
            r = _run(cand, "-Atc", "select 1", db="postgres", timeout=15)
        except Exception:
            continue
        if r.returncode == 0 and r.stdout.strip() == "1":
            return cand
    return None


def _run(prefix: list[str], *args: str, db: str, timeout: int = 120, stdin: str | None = None) -> subprocess.CompletedProcess:
    if prefix[:2] == ["su", "postgres"]:
        cmd = ["su", "postgres", "-c", " ".join(["psql", "-d", db, *(f"'{a}'" if " " in a else a for a in args)])]
    else:
        cmd = [*prefix, "-d", db, *args]
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout)


@pytest.fixture(scope="module")
def scratch():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no local PostgreSQL reachable - live migration layer skipped (static layer still ran)")
    db = f"tdw_mig015_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    tmp_copies = []
    try:
        for path in (FIXTURE, MIGRATION):
            # `su postgres` cannot read files under the repo checkout when it
            # is owned by another user - stage a world-readable copy.
            staged = Path("/tmp") / f"{db}_{path.name}"
            staged.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            staged.chmod(0o644)
            tmp_copies.append(staged)
            r = _run(prefix, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(staged), db=db)
            assert r.returncode == 0, f"{path.name} failed to apply:\n{r.stderr}"

        def run(sql: str) -> str:
            r = _run(prefix, "-v", "ON_ERROR_STOP=0", "-Atq", db=db, stdin=sql)
            return (r.stdout or "") + (r.stderr or "")

        yield run
    finally:
        _run(prefix, "-Atc", f"drop database if exists {db}", db="postgres")
        for p in tmp_copies:
            p.unlink(missing_ok=True)


def as_user(uid: str | None, role: str = "authenticated") -> str:
    claims = f'{{"sub":"{uid}","role":"{role}"}}' if uid else ""
    return f"set role {role}; set request.jwt.claims = '{claims}';\n"


def test_l01_policies_and_grants_after_migration(scratch):
    out = scratch("select tablename||':'||permissive||':'||cmd||':'||array_to_string(roles,',')||':'||regexp_replace(qual, '\\s+', ' ', 'g') from pg_policies where tablename in ('properties','county_calendar') order by 1;")
    assert [l.replace("( SELECT", "(SELECT") for l in out.splitlines() if l.strip()] == [
        "county_calendar:PERMISSIVE:SELECT:authenticated:(SELECT is_approved() AS is_approved)",
        "properties:PERMISSIVE:SELECT:authenticated:(SELECT is_approved() AS is_approved)",
    ]
    out = scratch("select table_name||':'||grantee||':'||string_agg(privilege_type, ',' order by privilege_type) from information_schema.role_table_grants where table_schema='public' and grantee in ('anon','authenticated') group by table_name, grantee order by 1;")
    rows = dict(line.rsplit(":", 1) for line in out.split())
    assert "properties:anon" not in rows and "properties:authenticated" not in rows  # SELECT is column-level (005a)
    assert "county_calendar:anon" not in rows
    assert rows["county_calendar:authenticated"] == "SELECT"
    for t in CUSTOMER_TABLES:
        assert f"{t}:anon" not in rows, t
        assert rows[f"{t}:authenticated"] == "DELETE,INSERT,SELECT,UPDATE", t
    for t in LEGACY_TABLES:
        assert f"{t}:anon" not in rows and f"{t}:authenticated" not in rows, t
    # authenticated keeps the column-level SELECT on properties.
    out = scratch("select count(*) from information_schema.role_column_grants where table_name='properties' and grantee='authenticated' and privilege_type='SELECT';")
    assert int(out.strip()) > 0


def test_l02_approved_user_reads_but_cannot_mutate_shared_tables(scratch):
    out = scratch(as_user(USER_A) + "select count(*) from public.get_properties('FL'); select count(*) from public.properties; select count(*) from public.county_calendar;")
    assert out.split() == ["3", "3", "1"]
    out = scratch(as_user(USER_A) + """
      insert into public.properties (source, county, case_no) values ('auction','X','X-1');
      update public.properties set bid = 1 where county = 'Alachua';
      delete from public.properties where county = 'Alachua';
      insert into public.county_calendar (county, sale_date) values ('Z','2030-01-01');
      delete from public.county_calendar;
    """)
    assert out.count("permission denied for table properties") == 3, out
    assert out.count("permission denied for table county_calendar") == 2, out
    out = scratch("select count(*) from public.properties; select bid from public.properties where county='Alachua'; select count(*) from public.county_calendar;")
    assert out.split() == ["3", "5000", "1"]


def test_l03_pending_user_reads_nothing_and_anon_reads_nothing(scratch):
    out = scratch(as_user(USER_PENDING) + "select count(*) from public.get_properties('FL'); select count(*) from public.properties;")
    assert out.split() == ["0", "0"]
    out = scratch(as_user(None, "anon") + "select count(*) from public.properties;")
    assert "permission denied for table properties" in out


def test_l04_service_role_writes_still_work(scratch):
    out = scratch("set role service_role; insert into public.properties (source, county, case_no, status) values ('auction','Svc','S-1','active'); update public.properties set bid = 7 where county='Svc'; select ledger_type||':'||bid from public.properties where county='Svc'; delete from public.properties where county='Svc';")
    assert "auctions:7" in out  # the ledger_type trigger fired under its pinned search_path
    assert "denied" not in out


def test_l05_own_row_isolation_and_bid_list_trigger_intact(scratch):
    out = scratch(as_user(USER_A) + """
      insert into public.favorites (user_id, property_id) values ('%(a)s','aaaaaaaa-0000-0000-0000-000000000003');
      insert into public.favorites (user_id, property_id) values ('%(b)s','aaaaaaaa-0000-0000-0000-000000000003');
      select count(*) from public.favorites;
      select count(*) from public.hidden;
      update public.notes set body = 'changed by a' where author_id = '%(b)s';
      delete from public.notes where author_id = '%(b)s';
      select count(*) from public.notes;
      insert into public.bid_list (user_id, property_id) values ('%(a)s','aaaaaaaa-0000-0000-0000-000000000002');
      select count(*) from public.bid_list;
      select public.handle_new_user();
    """ % {"a": USER_A, "b": USER_B})
    assert 'violates row-level security policy for table "favorites"' in out
    assert "permission denied for function handle_new_user" in out
    nums = [l for l in out.splitlines() if l.strip().isdigit()]
    # favorites: A sees only own (2 after insert); hidden: own 1; notes: shared read, both remain (2); bid_list: own 2.
    assert nums == ["2", "1", "2", "2"], out
    out = scratch("select body from public.notes where author_id = '%s';" % USER_B)
    assert out.strip() == "note by b"
    # The 10-row cap still fires for the caller after the EXECUTE revoke.
    fill = "".join(
        f"insert into public.properties (id, source, county, case_no) values ('bbbbbbbb-0000-0000-0000-0000000000{i:02d}','auction','Fill','F-{i}');\n"
        for i in range(1, 12)
    )
    scratch("set role service_role;\n" + fill)
    adds = "".join(
        f"insert into public.bid_list (user_id, property_id) values ('{USER_A}','bbbbbbbb-0000-0000-0000-0000000000{i:02d}');\n"
        for i in range(1, 12)
    )
    out = scratch(as_user(USER_A) + adds + "select count(*) from public.bid_list;")
    assert "Bid list is full (10 max)" in out
    assert [l for l in out.splitlines() if l.strip().isdigit()][-1] == "10"
    scratch("set role service_role; delete from public.bid_list where property_id::text like 'bbbbbbbb%'; delete from public.properties where county='Fill';")


def test_l06_anon_cannot_delete_an_account_and_a_pending_user_can_delete_their_own(scratch):
    out = scratch(as_user(None, "anon") + "select public.delete_my_account();")
    assert "permission denied for function delete_my_account" in out
    # No JWT subject at all (authenticated role, empty claims): refused, nothing deleted.
    out = scratch("set role authenticated; set request.jwt.claims = ''; select public.delete_my_account();")
    assert "no signed-in user" in out
    assert scratch("select count(*) from auth.users;").strip() == "3"
    out = scratch(as_user(USER_PENDING) + "select public.delete_my_account();")
    assert "ERROR" not in out
    assert scratch("select count(*) from auth.users; select count(*) from public.profiles;").split() == ["2", "2"]


def test_l07_delete_my_account_removes_only_the_caller_and_never_shared_data(scratch):
    before = scratch("select count(*) from public.properties; select count(*) from public.county_calendar;").split()
    out = scratch(as_user(USER_A) + "select public.delete_my_account();")
    assert "ERROR" not in out, out
    out = scratch("""
      select 'users:'||count(*) from auth.users;
      select 'identities:'||count(*) from auth.identities;
      select 'sessions:'||count(*) from auth.sessions;
      select 'profiles:'||string_agg(email, ',' order by email) from public.profiles;
      select 'notes:'||string_agg(author_email, ',') from public.notes;
      select 'favorites:'||string_agg(user_id::text, ',') from public.favorites;
      select 'hidden:'||count(*) from public.hidden;
      select 'bid_list:'||string_agg(user_id::text, ',') from public.bid_list;
      select 'a_left:'||count(*) from auth.users where id = '%s';
    """ % USER_A)
    rows = dict(l.split(":", 1) for l in out.split())
    assert rows["users"] == "1" and rows["a_left"] == "0"
    assert rows["identities"] == "1" and rows["sessions"] == "0"
    assert rows["profiles"] == "b@example.com"
    assert rows["notes"] == "b@example.com"
    assert rows["favorites"] == USER_B
    assert rows["hidden"] == "0"
    assert rows["bid_list"] == USER_B
    after = scratch("select count(*) from public.properties; select count(*) from public.county_calendar;").split()
    assert after == before


def test_l08_function_hardening_visible_in_catalog(scratch):
    out = scratch("select proname||':'||coalesce(array_to_string(proconfig, ','), '') from pg_proc where proname = any(%s) order by 1;" % (
        "array[" + ",".join(f"'{f}'" for f in PINNED_FUNCTIONS) + "]"))
    assert out.split() == sorted(f"{f}:search_path=public" for f in PINNED_FUNCTIONS)
    out = scratch("""
      select has_function_privilege('anon','public.delete_my_account()','execute')::text
        ||':'|| has_function_privilege('authenticated','public.delete_my_account()','execute')::text
        ||':'|| has_function_privilege('anon','public.handle_new_user()','execute')::text
        ||':'|| has_function_privilege('authenticated','public.enforce_bid_list_limit()','execute')::text;
    """)
    assert out.strip() == "false:true:false:false"


def test_l09_helpers_and_read_rpc_signed_in_only(scratch):
    out = scratch("""
      select has_function_privilege('anon','public.is_approved()','execute')::text
        ||':'|| has_function_privilege('anon','public.is_admin()','execute')::text
        ||':'|| has_function_privilege('anon','public.get_properties(text,text,text,integer,integer)','execute')::text
        ||':'|| has_function_privilege('authenticated','public.is_approved()','execute')::text
        ||':'|| has_function_privilege('authenticated','public.get_properties(text,text,text,integer,integer)','execute')::text
        ||':'|| has_function_privilege('service_role','public.is_admin()','execute')::text;
    """)
    assert out.strip() == "false:false:false:true:true:true"
    out = scratch(as_user(None, "anon") + "select public.is_approved(); select count(*) from public.get_properties('FL');")
    assert out.count("permission denied for function") == 2, out


def test_l10_customer_read_keeps_once_per_statement_policy(scratch):
    out = scratch(as_user(USER_A) + "explain (costs off) select count(*) from public.properties;")
    assert "InitPlan" in out, out


def test_l11_guard_refuses_a_second_run_and_changes_nothing(scratch):
    staged = Path("/tmp") / f"mig015_rerun_{uuid.uuid4().hex[:8]}.sql"
    staged.write_text(SQL, encoding="utf-8")
    staged.chmod(0o644)
    try:
        out = scratch(f"\\i {staged}")
    finally:
        staged.unlink(missing_ok=True)
    assert "015 guard" in out, out
    out = scratch("select count(*) from pg_policy where polrelid = 'public.properties'::regclass;")
    assert out.strip() == "1"

