"""Migration 026 (2026-10-04): the properties access rule evaluated once per
statement, and an index matching get_properties()'s page order.

STATIC: ALTER POLICY only (never DROP / CREATE POLICY), same policy name, the
same is_approved() call wrapped in a scalar sub-select for USING and WITH
CHECK, one index in the page query's exact order, nothing else.

LIVE (local PostgreSQL only, skipped otherwise): on a production-shaped
scratch schema (live column list, indexes, policy, auth.uid() and
is_approved() definitions, migration 025's get_properties()):
  - authorization is identical before and after for an approved admin, an
    approved customer, a pending account, an unknown user, anon and
    service_role - page results (row count, id checksum, order), direct
    reads, updates and WITH CHECK on insert;
  - Michigan and Louisiana deep pages come back complete, ordered, without
    duplicates or gaps;
  - the plan evaluates the access rule once (InitPlan) and reads the page
    from the new index without a sort;
  - the policy stays the single PERMISSIVE, ALL, PUBLIC policy;
  - the migration is idempotent.
"""
from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "scripts" / "migrations" / "026_properties_rls_initplan_and_page_index.sql"
M025 = REPO / "scripts" / "migrations" / "025_get_properties_narrow_sort.sql"
FIXTURE = REPO / "tests" / "python" / "fixtures" / "migration_026_scratch_fixture.sql"
SQL = MIGRATION.read_text(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_migration_016_source_health import _psql_prefix, _run  # noqa: E402

USERS = {"admin": "11111111-1111-1111-1111-111111111111", "customer": "22222222-2222-2222-2222-222222222222",
         "pending": "33333333-3333-3333-3333-333333333333", "unknown": "44444444-4444-4444-4444-444444444444"}
LEDGERS = (("MI", "buy"), ("MI", "auctions"), ("LA", "buy"), ("FL", "auctions"), ("FL", "buy"), ("FL", "lien"),
           ("CO", "lien"), ("WY", "auctions"), ("SC", "auctions"), ("TX", "buy"), ("TX", "auctions"))


def code() -> str:
    return "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--")).strip()


# ==================== STATIC ====================

def test_s01_policy_is_altered_in_place_never_dropped():
    body = code().lower()
    assert "drop policy" not in body and "create policy" not in body          # no instant without a permissive policy
    assert 'alter policy "properties: approved only" on public.properties' in body
    assert "using ((select public.is_approved()))" in body
    assert "with check ((select public.is_approved()))" in body
    assert "as restrictive" not in body and " to " not in body.split("alter policy", 1)[1].split(";")[0]   # roles untouched


def test_s02_one_index_in_the_page_order_and_nothing_else():
    body = code().lower()
    assert re.findall(r"create index if not exists (\w+)\s+on public\.properties \(([^)]*)\)", body) == [
        ("properties_state_ledger_county_case_id_idx", "state, ledger_type, county, case_no, id")]
    statements = [s.strip() for s in body.split(";") if s.strip()]
    assert len(statements) == 2
    for word in ("grant", "revoke", "drop", "delete", "update", "insert", "truncate", "create or replace function",
                 "alter table", "disable row level security", "security definer"):
        assert word not in body, word


def test_s03_the_index_order_is_get_properties_page_order():
    page = re.search(r"with page as \((.*?)\n  \)", M025.read_text(encoding="utf-8"), re.S).group(1)
    assert "where k.state = p_state" in page and "k.ledger_type = p_ledger_type" in page
    assert "order by county, case_no, id" in page


# ==================== LIVE ====================

@pytest.fixture(scope="module")
def scratch():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no local PostgreSQL reachable - live migration layer skipped (static layer still ran)")
    db = f"tdw_mig026_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    staged = []

    def stage(path: Path) -> str:
        copy = Path("/tmp") / f"{db}_{len(staged)}_{path.name}"
        copy.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        copy.chmod(0o644)
        staged.append(copy)
        return str(copy)

    def apply(path: Path):
        r = _run(prefix, "-v", "ON_ERROR_STOP=1", "-q", "-f", stage(path), db=db)
        assert r.returncode == 0, f"{path.name} failed to apply:\n{r.stderr}"

    def run(sql):
        r = _run(prefix, "-v", "ON_ERROR_STOP=0", "-Atq", db=db, stdin=sql)
        return (r.stdout or "") + (r.stderr or "")

    try:
        apply(FIXTURE)
        apply(M025)
        yield run, apply
    finally:
        _run(prefix, "-Atc", f"drop database if exists {db}", db="postgres")
        for c in staged:
            c.unlink(missing_ok=True)


def claims(uid: str) -> str:
    # A PostgREST-sized claims payload (auth.uid() parses it).
    return ('{"sub":"%s","role":"authenticated","aud":"authenticated","email":"x@example.com","aal":"aal1",'
            '"app_metadata":{"provider":"email","providers":["email"]},"user_metadata":{"email_verified":true}}' % uid)


def as_user(uid: str, sql: str) -> str:
    return f"reset role; set role authenticated; set request.jwt.claims = '{claims(uid)}';\n{sql}"


def page_fingerprint(label: str) -> str:
    values = ", ".join(f"('{s}','{l}')" for s, l in LEDGERS)
    return f"""select '{label}', st, lt, count(*), count(distinct id), md5(string_agg(id::text, ',' order by pg, ord)),
  count(*) filter (where (county, case_no, id::text) < prev)
from (select st, lt, pg, ord, id, county, case_no,
        lag((county, case_no, id::text)) over (partition by st, lt order by pg, ord) prev
      from (select s.st, s.lt, o.pg, t.ord, t.id, t.county, t.case_no
            from (values {values}) s(st, lt) cross join generate_series(0, 4) o(pg)
            cross join lateral (select row_number() over () ord, g.id, g.county, g.case_no
                                from get_properties(s.st, s.lt, null, 1000, o.pg * 1000) g) t) x) y
group by st, lt order by st, lt;"""


def authorization_snapshot(run) -> str:
    parts = []
    for label, uid in USERS.items():
        parts.append(as_user(uid, page_fingerprint(label)
                             + f"\nselect '{label} read', count(*) from public.properties;"
                             + f"\nbegin; with u as (update public.properties set lien_note = lien_note where state = 'WY' returning 1)"
                               f" select '{label} update', count(*) from u; rollback;"
                             + f"\nbegin; insert into public.properties (state, source, ledger_type, county, case_no)"
                               f" values ('ZZ', 'laft', 'buy', 'Test', '{label}'); select '{label} insert ok'; rollback;"))
    parts.append("reset role; set role anon; reset request.jwt.claims;\n" + page_fingerprint("anon")
                 + "\nselect 'anon read', count(*) from public.properties;")
    parts.append("reset role; set role service_role;\n" + page_fingerprint("service_role")
                 + "\nselect 'service read', count(*) from public.properties;")
    out = run("\n".join(parts))
    return "\n".join(l.split("ERROR:", 1)[-1].strip() if "ERROR:" in l else l
                     for l in out.splitlines() if "current transaction is aborted" not in l)


def policies(run) -> str:
    return run("select polname, polpermissive, polcmd, polroles::regrole[]::text from pg_policy "
               "where polrelid = 'public.properties'::regclass order by 1;")


def test_l01_authorization_pages_order_and_rows_unchanged(scratch):
    run, apply = scratch
    before_policies = policies(run)
    before = authorization_snapshot(run)
    # Baseline sanity: approved users see every ledger, pending / unknown / anon see nothing.
    assert "admin|MI|buy|3255|3255|" in before and "customer|LA|buy|1100|1100|" in before
    assert "pending read|0" in before and "unknown read|0" in before and "anon read|0" in before
    assert "pending|" not in before.replace("pending read", "").replace("pending update", "").replace("pending insert", "")
    assert before.count("new row violates row-level security policy") == 2          # pending + unknown
    assert "admin insert ok" in before and "customer insert ok" in before
    apply(MIGRATION)
    after = authorization_snapshot(run)
    assert after == before
    assert policies(run) == before_policies                                           # same single PERMISSIVE / ALL / PUBLIC policy
    assert before_policies.strip() == "properties: approved only|t|*|{-}"


def test_l02_deep_pages_complete_ordered_no_duplicates(scratch):
    run, apply = scratch
    apply(MIGRATION)
    out = as_user(USERS["customer"], page_fingerprint("c"))
    lines = {tuple(l.split("|")[1:3]): l.split("|")[3:] for l in run(out).splitlines() if l.startswith("c|")}
    total = {(s, l): int(n) for s, l, n in (r.split("|") for r in run(
        "select state, ledger_type, count(*) from public.properties group by 1, 2;").splitlines())}
    for key in (("MI", "buy"), ("LA", "buy")):
        count, distinct, _md5, violations = lines[key]
        assert int(count) == int(distinct) == total[key]                             # no gap, no duplicate
        assert violations == "0"                                                      # (county, case_no, id) order kept


def test_l03_plan_evaluates_the_rule_once_and_reads_the_index_without_a_sort(scratch):
    run, apply = scratch
    apply(MIGRATION)
    plan = run(as_user(USERS["customer"], "explain (costs off) select k.id from public.properties k "
                                          "where k.state = 'MI' and k.ledger_type = 'buy' "
                                          "order by county, case_no, id limit 1000 offset 2000;"))
    assert "InitPlan" in plan and "properties_state_ledger_county_case_id_idx" in plan
    assert "Sort" not in plan and "Filter: is_approved()" not in plan


def test_l04_idempotent(scratch):
    run, apply = scratch
    apply(MIGRATION)
    apply(MIGRATION)
    assert run("select count(*) from pg_indexes where indexname = 'properties_state_ledger_county_case_id_idx';").strip() == "1"
    assert "SELECT is_approved() AS is_approved" in run(
        "select pg_get_expr(polqual, polrelid) from pg_policy where polrelid = 'public.properties'::regclass;")
