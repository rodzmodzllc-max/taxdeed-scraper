"""Migration 024 (customer monitoring foundation) - contract tests.

STATIC: additive only; every customer table pairs a PERMISSIVE own-row policy
with a RESTRICTIVE is_approved() policy (never a RESTRICTIVE policy alone);
snapshots are service-role only; product events carry no free text.

LIVE (local PostgreSQL only, skipped otherwise): 024 applies verbatim on top of
the 015 scratch fixture; get_properties() keeps its columns and gains an `id`
tie-break; customers see only their own saved searches / alerts / preferences;
a pending account sees nothing; anon is denied; analytics are insert-own and
admin-read.
"""
from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "scripts" / "migrations" / "024_customer_monitoring_foundation.sql"
FIXTURE = REPO / "tests" / "python" / "fixtures" / "migration_015_scratch_fixture.sql"
SQL = MIGRATION.read_text(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_migration_016_source_health import _psql_prefix, _run  # noqa: E402

CUSTOMER_TABLES = ("saved_searches", "alert_preferences", "user_alerts")
USER_A = "11111111-1111-1111-1111-111111111111"
USER_B = "22222222-2222-2222-2222-222222222222"
USER_PENDING = "33333333-3333-3333-3333-333333333333"


def code() -> str:
    return "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--"))


def test_m01_additive_only():
    body = code().lower()
    assert "drop table" not in body and "drop column" not in body and "alter column" not in body and "delete from" not in body
    assert not re.search(r"alter table public\.properties\b(?! enable)", body)            # properties itself is untouched
    # get_properties is rewritten from its live definition, only the ORDER BY gains a tie-break
    assert "pg_get_functiondef('public.get_properties(text,text,text,integer,integer)'::regprocedure)" in body
    assert "order by county, case_no, id" in body and "refusing to guess" in body


def test_m02_every_customer_table_has_permissive_own_rows_and_restrictive_approved():
    body = code()
    assert "foreach t in array array['saved_searches', 'alert_preferences', 'user_alerts']" in body
    assert "as permissive for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid())" in body
    assert "as restrictive for all to public using (public.is_approved()) with check (public.is_approved())" in body
    assert '"product_events: insert own" on public.product_events\n  as permissive for insert' in body
    assert '"product_events: approved only" on public.product_events\n  as restrictive' in body
    # Snapshots: RLS on, no policy at all = service role only
    assert "alter table public.property_change_snapshots enable row level security;" in body
    assert "on public.property_change_snapshots" not in body.split("enable row level security;", 1)[1].split("create table if not exists public.property_change_events")[0].replace(
        "revoke all on public.property_change_snapshots from anon, authenticated;", "")


def test_m03_analytics_vocabulary_has_no_free_text_event():
    events = re.search(r"event text not null check \(event in \((.*?)\)\)", code(), re.S).group(1)
    names = re.findall(r"'([a-z_]+)'", events)
    assert set(names) >= {"search_performed", "property_viewed", "property_watched", "acquisition_source_opened",
                          "export_performed", "alert_created", "saved_search_created", "session_start"}
    assert "pg_column_size(props) < 2048" in code()


# ==================== LIVE ====================

@pytest.fixture(scope="module")
def scratch():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no local PostgreSQL reachable - live migration layer skipped (static layer still ran)")
    db = f"tdw_mig024_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    staged = []
    try:
        for path in (FIXTURE, MIGRATION, MIGRATION):           # applied twice: idempotent
            copy = Path("/tmp") / f"{db}_{len(staged)}_{path.name}"
            copy.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            copy.chmod(0o644)
            staged.append(copy)
            r = _run(prefix, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(copy), db=db)
            assert r.returncode == 0, f"{path.name} failed to apply:\n{r.stderr}"

        def run(sql):
            r = _run(prefix, "-v", "ON_ERROR_STOP=0", "-Atq", db=db, stdin=sql)
            return (r.stdout or "") + (r.stderr or "")
        yield run
    finally:
        _run(prefix, "-Atc", f"drop database if exists {db}", db="postgres")
        for c in staged:
            c.unlink(missing_ok=True)


def as_user(uid: str, sql: str) -> str:
    return f"""set role authenticated; set request.jwt.claims = '{{"sub":"{uid}","role":"authenticated"}}';\n{sql}"""


def test_l01_get_properties_pages_deterministically_and_count_matches(scratch):
    out = scratch("select pg_get_functiondef('public.get_properties(text,text,text,integer,integer)'::regprocedure);")
    assert "order by county, case_no, id" in out
    out = scratch(as_user(USER_A, "select count_properties('FL'); select count(*) from get_properties('FL', null, null, 2, 0); "
                                  "select count(*) from get_properties('FL', null, null, 2, 2);"))
    assert out.split() == ["3", "2", "1"]


def test_l02_saved_searches_alerts_preferences_are_own_rows_only(scratch):
    out = scratch(as_user(USER_A, "insert into saved_searches (name, state, criteria) values ('a', 'FL', '{\"ledger\":\"laft\"}'); "
                                  "insert into alert_preferences (watch_changes) values (true); select count(*) from saved_searches;"))
    assert "ERROR" not in out and out.strip().splitlines()[-1] == "1"
    out = scratch(as_user(USER_B, "select count(*) from saved_searches; select count(*) from alert_preferences; "
                                  f"insert into saved_searches (user_id, name, state) values ('{USER_A}', 'x', 'FL');"))
    assert out.splitlines()[0] == "0" and out.splitlines()[1] == "0" and "row-level security" in out
    out = scratch(as_user(USER_PENDING, "insert into saved_searches (name, state) values ('p', 'FL');"))
    assert "row-level security" in out
    out = scratch("set role anon; select count(*) from saved_searches;")
    assert "permission denied" in out


def test_l03_alerts_written_by_service_read_and_marked_by_owner(scratch):
    out = scratch(f"""set role service_role;
      insert into property_change_events (property_id, state, kind, field, old_value, new_value)
        values ('aaaaaaaa-0000-0000-0000-000000000003', 'FL', 'removed', 'status', 'available', 'closed') returning id;""")
    eid = out.strip().splitlines()[0]
    out = scratch(f"""set role service_role;
      insert into user_alerts (user_id, kind, property_id, change_event_id, title) values
        ('{USER_A}', 'watched_status', 'aaaaaaaa-0000-0000-0000-000000000003', {eid}, 'No longer on the list');""")
    assert "ERROR" not in out
    out = scratch(as_user(USER_A, "select count(*) from user_alerts; update user_alerts set read_at = now(); "
                                  "update user_alerts set title = 'x'; select count(*) from property_change_events;"))
    lines = [l for l in out.splitlines() if not l.startswith("ERROR")]
    assert lines == ["1", "1"] and "permission denied for table user_alerts" in out
    out = scratch(as_user(USER_B, "select count(*) from user_alerts; insert into user_alerts (user_id, kind, title) values "
                                  f"('{USER_B}', 'watched_status', 'x');"))
    assert out.splitlines()[0] == "0" and "permission denied for table user_alerts" in out   # a customer can never write an alert
    out = scratch(as_user(USER_PENDING, "select count(*) from property_change_events;"))
    assert out.strip() == "0"
    out = scratch(as_user(USER_A, "select count(*) from property_change_snapshots;"))
    assert "permission denied" in out


def test_l04_analytics_insert_own_admin_read(scratch):
    out = scratch(as_user(USER_A, "insert into product_events (event, state, props) values ('search_performed', 'FL', '{\"filters\":2}'); "
                                  f"insert into product_events (user_id, event) values ('{USER_B}', 'session_start'); "
                                  "insert into product_events (event) values ('typed_free_text'); select count(*) from product_events;"))
    assert "row-level security" in out and "check constraint" in out and out.splitlines()[0] == "0"   # not admin: cannot read
    out = scratch(f"update public.profiles set is_admin = true where id = '{USER_B}';")
    out = scratch(as_user(USER_B, "select event||':'||events||':'||users from product_usage_summary(30);"))
    assert "search_performed:1:1" in out
    out = scratch(as_user(USER_A, "select count(*) from product_usage_summary(30);"))
    assert out.strip() == "0"
