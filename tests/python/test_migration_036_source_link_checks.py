"""Migration 036 (source_link_checks) - contract tests. Written, NOT applied.

STATIC: additive and idempotent; RLS on with the InitPlan is_approved() read
policy; grants revoked from anon / authenticated before the explicit grants;
service_role is the only writer.

LIVE (local PostgreSQL only, skipped otherwise): 036 applies verbatim (twice)
on the 015 scratch fixture; an approved account reads, a pending account and
anon read nothing / are refused; no customer can write; the BROKEN streak
constraint holds.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "scripts" / "migrations" / "036_source_link_checks.sql"
FIXTURE = REPO / "tests" / "python" / "fixtures" / "migration_015_scratch_fixture.sql"
SQL = MIGRATION.read_text(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_migration_016_source_health import _psql_prefix, _run  # noqa: E402

CUSTOMER = "11111111-1111-1111-1111-111111111111"     # approved in the fixture
PENDING = "33333333-3333-3333-3333-333333333333"


def code() -> str:
    return "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--")).lower()


def test_s01_additive_and_idempotent():
    body = code()
    for bad in ("drop table", "drop column", "delete from", "truncate", "alter table public.properties"):
        assert bad not in body
    assert "create table if not exists public.source_link_checks" in body
    assert "drop policy if exists" in body and "drop trigger if exists" in body


def test_s02_rls_and_grants():
    body = code()
    assert "enable row level security" in body
    assert "using ((select public.is_approved()))" in body
    i_revoke = body.index("revoke all on public.source_link_checks from public, anon, authenticated;")
    i_grant = body.index("grant select on public.source_link_checks to authenticated;")
    assert i_revoke < i_grant
    assert "grant select, insert, update, delete on public.source_link_checks to service_role;" in body
    assert "to authenticated" in body and "insert" not in body[i_grant:i_grant + 60]


# ==================== LIVE ====================

@pytest.fixture(scope="module")
def scratch():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no local PostgreSQL reachable - live migration layer skipped (static layer still ran)")
    db = f"tdw_mig036_{uuid.uuid4().hex[:8]}"
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


def test_l01_service_role_writes_and_approved_reads(scratch):
    out = scratch("set role service_role; insert into source_link_checks (url, host, status, http_code, consecutive_failures, first_failed_at)"
                  " values ('https://example.gov/list.pdf', 'example.gov', 'BROKEN', 404, 2, now()),"
                  " ('https://example.gov/ok', 'example.gov', 'OK', 200, 0, null);")
    assert "ERROR" not in out
    assert scratch(as_user(CUSTOMER, "select count(*) from source_link_checks where status = 'BROKEN' and consecutive_failures >= 2;")).strip() == "1"


def test_l02_pending_anon_and_customer_writes_refused(scratch):
    assert scratch(as_user(PENDING, "select count(*) from source_link_checks;")).strip() == "0"
    assert "permission denied" in scratch("set role anon; select count(*) from source_link_checks;")
    out = scratch(as_user(CUSTOMER, "insert into source_link_checks (url, status) values ('https://x.gov/', 'OK');"))
    assert "permission denied" in out
    out = scratch(as_user(CUSTOMER, "update source_link_checks set status = 'OK';"))
    assert "permission denied" in out
    out = scratch(as_user(CUSTOMER, "delete from source_link_checks;"))
    assert "permission denied" in out


def test_l03_streak_only_on_broken(scratch):
    out = scratch("set role service_role; insert into source_link_checks (url, status, consecutive_failures) values ('https://y.gov/', 'BLOCKED', 3);")
    assert "violates check constraint" in out
    out = scratch("set role service_role; insert into source_link_checks (url, status) values ('https://z.gov/', 'GONE');")
    assert "violates check constraint" in out
