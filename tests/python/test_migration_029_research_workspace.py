"""Migration 029 (research workspace) - contract tests. Written, NOT applied.

STATIC: additive only (properties untouched, nothing dropped); both customer
tables pair a PERMISSIVE own-row policy with a RESTRICTIVE is_approved()
policy; helper calls are InitPlans; every default grant is revoked first;
research_state is the customer's vocabulary only, never a source status.

LIVE (local PostgreSQL only, skipped otherwise): 029 applies verbatim (twice)
on top of the 015 scratch fixture; a customer creates lists, saves
properties, changes the workflow state; another customer sees none of it; a
pending account and anon are refused; an item cannot be put in another
user's list; the workflow state never reaches public.properties.
"""
from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "scripts" / "migrations" / "029_research_workspace.sql"
FIXTURE = REPO / "tests" / "python" / "fixtures" / "migration_015_scratch_fixture.sql"
SQL = MIGRATION.read_text(encoding="utf-8")
APP = (REPO / "public" / "app.js").read_text(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_migration_016_source_health import _psql_prefix, _run  # noqa: E402

USER_A = "11111111-1111-1111-1111-111111111111"
USER_B = "22222222-2222-2222-2222-222222222222"
USER_PENDING = "33333333-3333-3333-3333-333333333333"
PROP = "aaaaaaaa-0000-0000-0000-000000000001"
STATES = ("DISCOVERED", "RESEARCHING", "DUE_DILIGENCE", "ACQUISITION_READY", "PASSED", "ACQUIRED")


def code() -> str:
    return "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--"))


def test_r01_additive_only_and_properties_untouched():
    body = code().lower()
    for bad in ("drop table", "drop column", "alter column", "delete from", "truncate"):
        assert bad not in body
    assert "alter table public.properties" not in body and "update public.properties" not in body
    assert "create table if not exists public.research_lists" in body and "create table if not exists public.research_items" in body


def test_r02_rls_pattern_and_grants():
    body = code()
    assert "foreach t in array array['research_lists', 'research_items']" in body
    assert "as permissive for all to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()))" in body
    assert "as restrictive for all to public using ((select public.is_approved())) with check ((select public.is_approved()))" in body
    assert "revoke all on public.%I from anon, authenticated" in body
    assert "grant select, insert, update, delete on public.research_items to authenticated;" in body
    for fn in ("research_items_same_owner", "research_limits"):
        assert f"revoke all on function public.{fn}() from public, anon, authenticated;" in body


def test_r03_customer_workflow_vocabulary_matches_the_frontend_and_is_not_a_source_status():
    m = re.search(r"research_state in \((.*?)\)\)", code(), re.S)
    assert tuple(re.findall(r"'([A-Z_]+)'", m.group(1))) == STATES
    js = re.search(r"var RESEARCH_STATES = (?:RESEARCH_STATES \|\| )?\[(.*?)\];", APP, re.S)
    assert tuple(re.findall(r'"([A-Z_]+)"', js.group(1))) == STATES
    # None of the customer's states is a government / source status word the app uses.
    for st in STATES:
        assert st.lower() not in ("available", "auction", "sold", "redeemed", "closed", "active")


# ==================== LIVE ====================

@pytest.fixture(scope="module")
def scratch():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no local PostgreSQL reachable - live migration layer skipped (static layer still ran)")
    db = f"tdw_mig029_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    staged = []
    try:
        for path in (FIXTURE, MIGRATION, MIGRATION):
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


def test_l01_owner_creates_list_saves_property_and_moves_workflow_state(scratch):
    out = scratch(as_user(USER_A, f"""insert into research_lists (name) values ('October Florida Auction') returning id;"""))
    lid = out.strip().splitlines()[0]
    out = scratch(as_user(USER_A, f"""insert into research_items (list_id, property_id, note) values ('{lid}', '{PROP}', 'check flood');
      update research_items set research_state = 'DUE_DILIGENCE', diligence = '{{"acq_path": {{"reviewed": true}}}}';
      select research_state || '|' || (state_changed_at >= saved_at) from research_items;"""))
    assert "ERROR" not in out and out.strip().splitlines()[-1] == "DUE_DILIGENCE|true"
    out = scratch(as_user(USER_A, "update research_items set research_state = 'SOLD';"))
    assert "check constraint" in out                                           # never a source status
    out = scratch(as_user(USER_A, f"insert into research_items (list_id, property_id) values ('{lid}', '{PROP}');"))
    assert "duplicate key" in out                                             # one row per (list, property)
    # The customer's state never reaches the property row.
    out = scratch(f"select count(*) from information_schema.columns where table_name = 'properties' and column_name like 'research%';")
    assert out.strip() == "0"


def test_l02_other_customers_pending_and_anon_see_nothing(scratch):
    out = scratch(as_user(USER_B, "select count(*) from research_lists; select count(*) from research_items;"))
    assert out.split() == ["0", "0"]
    out = scratch(as_user(USER_A, "select id from research_lists limit 1;"))
    lid = out.strip().splitlines()[0]
    out = scratch(as_user(USER_B, f"insert into research_items (list_id, property_id) values ('{lid}', '{PROP}');"))
    assert "research list not found" in out or "row-level security" in out   # not into someone else's list
    out = scratch(as_user(USER_B, f"insert into research_lists (user_id, name) values ('{USER_A}', 'x');"))
    assert "row-level security" in out
    out = scratch(as_user(USER_PENDING, "insert into research_lists (name) values ('p');"))
    assert "row-level security" in out
    out = scratch("set role anon; select count(*) from research_lists;")
    assert "permission denied" in out


def test_l03_deleting_a_list_removes_its_items_only(scratch):
    out = scratch(as_user(USER_A, """insert into research_lists (name) values ('Watch') returning id;"""))
    lid = out.strip().splitlines()[0]
    out = scratch(as_user(USER_A, f"""insert into research_items (list_id, property_id) values ('{lid}', 'aaaaaaaa-0000-0000-0000-000000000002');
      delete from research_lists where id = '{lid}'; select count(*) from research_items; select count(*) from research_lists;"""))
    assert out.split()[-2:] == ["1", "1"]
