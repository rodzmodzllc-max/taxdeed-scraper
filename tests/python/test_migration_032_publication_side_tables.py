"""Migration 032 (publication gate for the per-property side tables) - contract
tests. Written, NOT applied.

STATIC: 032 ALTERs (never drops) the read policy of each side table so a side
row is readable only when the caller can read its property; it refuses to run
without 031; it is idempotent; the shells used by the live layer carry the
pre-032 policies exactly as 014 / 021 / 024 create them.

LIVE (local PostgreSQL only, skipped otherwise): on 026's scratch schema + 031
+ the side-table shells + 032 (twice), a customer reads events, observations,
status history, change events and alerts only for CUSTOMER_PUBLISHED
properties - the same rows get_properties() and a direct properties read
return; an admin reads everything; pending / anon accounts read nothing;
without 031, 032 refuses.
"""
from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIG = ROOT / "scripts" / "migrations"
M032 = MIG / "032_publication_gate_side_tables.sql"
SQL = M032.read_text(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_migration_016_source_health import _psql_prefix, _run  # noqa: E402
from test_publication_state_gate import FIXTURE, IS_ADMIN_SQL, M025, M026, SEED, USERS, as_user  # noqa: E402

M031 = MIG / "031_publication_state_gate.sql"
SIDE_POLICIES = {
    "auction_events": ("014_auction_event_history.sql", "auction_events: approved read"),
    "auction_event_observations": ("014_auction_event_history.sql", "auction_event_observations: approved read"),
    "inventory_status_observations": ("021_inventory_status_provenance_freshness.sql", "inventory_status_observations: approved read"),
    "property_change_events": ("024_customer_monitoring_foundation.sql", "property_change_events: approved read"),
}


def code() -> str:
    return "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--"))


def test_s01_alters_never_drops_and_touches_no_data_or_properties_policy():
    body = code().lower()
    for bad in ("drop table", "drop column", "delete from", "truncate", "update public.", "insert into",
                'alter policy "properties', "on public.properties"):
        assert bad not in body, bad
    # The only DROP is the idempotent re-create of 032's own new policy.
    assert re.findall(r"drop policy if exists \"([^\"]+)\"", body) == ["user_alerts: property readable"]
    assert "alter policy %i on public.%i using ((select public.is_approved()) and %s)" in body


def test_s02_every_side_policy_named_matches_the_migration_that_creates_it():
    for tbl, (mig, pol) in SIDE_POLICIES.items():
        src = (MIG / mig).read_text(encoding="utf-8")
        assert f'"{pol}"' in src, (mig, pol)
        assert f"('{tbl}', '{pol}'," in SQL, tbl


def test_s03_side_rows_follow_the_callers_own_properties_read():
    assert "exists (select 1 from public.properties p where p.id = auction_events.property_id)" in SQL
    assert "exists (select 1 from public.auction_events e where e.id = auction_event_observations.event_id)" in SQL
    assert "exists (select 1 from public.properties p where p.id = inventory_status_observations.property_id)" in SQL
    assert "exists (select 1 from public.properties p where p.id = property_change_events.property_id)" in SQL
    assert 'as restrictive for select to authenticated' in SQL
    assert "property_id is null or exists (select 1 from public.properties p where p.id = user_alerts.property_id)" in SQL
    # No second copy of the publication rule that could drift from 031.
    assert "customer_published" not in code().lower()


def test_s04_requires_031_and_documents_order_and_rollback():
    assert "032 requires 031 (properties.publication_state) - apply 031 first" in SQL
    assert "apply (or re-apply) 032 AFTER 024" in SQL
    for pol in [p for _, p in SIDE_POLICIES.values()]:
        assert f'--   alter policy "{pol}" on public.' in SQL and "using (public.is_approved());" in SQL
    assert '--   drop policy if exists "user_alerts: property readable" on public.user_alerts;' in SQL


def test_s05_numbering_is_next():
    names = sorted(p.name for p in MIG.glob("*.sql"))
    assert names[-2:] == ["031_publication_state_gate.sql", "032_publication_gate_side_tables.sql"]


# ==================== LIVE ====================

# The side tables exactly as far as 032 cares: their key columns, RLS, grants,
# and the pre-032 read policies verbatim from 014 / 021 / 024.
SHELLS = """
create table public.auction_events (id uuid primary key default gen_random_uuid(),
  property_id uuid not null references public.properties(id), county text);
create table public.auction_event_observations (id bigint generated always as identity primary key,
  event_id uuid not null references public.auction_events(id), outcome_raw text);
create table public.inventory_status_observations (id bigint generated always as identity primary key,
  property_id uuid not null references public.properties(id), status text);
create table public.property_change_events (id bigserial primary key,
  property_id uuid not null references public.properties(id), kind text);
create table public.user_alerts (id bigserial primary key, user_id uuid not null,
  property_id uuid references public.properties(id), title text);
alter table public.auction_events enable row level security;
alter table public.auction_event_observations enable row level security;
alter table public.inventory_status_observations enable row level security;
alter table public.property_change_events enable row level security;
alter table public.user_alerts enable row level security;
create policy "auction_events: approved read" on public.auction_events as permissive for select to authenticated using (public.is_approved());
create policy "auction_event_observations: approved read" on public.auction_event_observations as permissive for select to authenticated using (public.is_approved());
create policy "inventory_status_observations: approved read" on public.inventory_status_observations as permissive for select to authenticated using (public.is_approved());
create policy "property_change_events: approved read" on public.property_change_events as permissive for select to authenticated using (public.is_approved());
create policy "user_alerts: own rows" on public.user_alerts as permissive for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "user_alerts: approved only" on public.user_alerts as restrictive for all to public using (public.is_approved()) with check (public.is_approved());
grant select on public.auction_events, public.auction_event_observations, public.inventory_status_observations,
  public.property_change_events, public.user_alerts to authenticated;
"""
SIDE_SEED = """
insert into public.auction_events (id, property_id, county)
  select ('eeeeeeee-0000-0000-0000-0000000000' || right(id::text, 2))::uuid, id, county from public.properties;
insert into public.auction_event_observations (event_id, outcome_raw) select id, 'x' from public.auction_events;
insert into public.inventory_status_observations (property_id, status) select id, 'x' from public.properties;
insert into public.property_change_events (property_id, kind) select id, 'x' from public.properties;
insert into public.user_alerts (user_id, property_id, title)
  select '%s'::uuid, id, 'x' from public.properties union all select '%s'::uuid, null, 'general';
""" % (USERS["customer"], USERS["customer"])

VISIBLE_TO_CUSTOMER = ["01", "03", "06"]   # the CUSTOMER_PUBLISHED rows of SEED
ALL = ["01", "02", "03", "04", "05", "06", "07", "08"]
SIDE_READS = {
    "auction_events": "select property_id from public.auction_events;",
    "auction_event_observations": "select e.property_id from public.auction_event_observations o join public.auction_events e on e.id = o.event_id;",
    "auction_event_observations_direct": "select '" + "aaaaaaaa-0000-0000-0000-0000000000' || right(event_id::text, 2) from public.auction_event_observations;",
    "inventory_status_observations": "select property_id from public.inventory_status_observations;",
    "property_change_events": "select property_id from public.property_change_events;",
    "user_alerts": "select property_id from public.user_alerts where property_id is not null;",
}


def ids(out: str) -> list[str]:
    return sorted(l.strip()[-2:] for l in out.splitlines() if l.strip().startswith("aaaaaaaa-"))


@pytest.fixture(scope="module")
def pg():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no local PostgreSQL reachable - live migration layer skipped (static layer still ran)")
    return prefix


def _db(prefix, steps):
    db = f"tdw_mig032_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    staged = []

    def apply(text, name, ok=True):
        copy = Path("/tmp") / f"{db}_{len(staged)}_{name}"
        copy.write_text(text, encoding="utf-8")
        copy.chmod(0o644)
        staged.append(copy)
        r = _run(prefix, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(copy), db=db)
        if ok:
            assert r.returncode == 0, f"{name} failed to apply:\n{r.stderr}"
        return r

    def run(sql):
        r = _run(prefix, "-v", "ON_ERROR_STOP=0", "-Atq", db=db, stdin=sql)
        return (r.stdout or "") + (r.stderr or "")

    def drop():
        _run(prefix, "-Atc", f"drop database if exists {db}", db="postgres")
        for c in staged:
            c.unlink(missing_ok=True)
    for text, name in steps:
        apply(text, name)
    return apply, run, drop


BASE = [(FIXTURE.read_text(encoding="utf-8"), FIXTURE.name), (M025.read_text(encoding="utf-8"), M025.name),
        (M026.read_text(encoding="utf-8"), M026.name), (IS_ADMIN_SQL, "is_admin.sql")]


@pytest.fixture(scope="module")
def scratch(pg):
    apply, run, drop = _db(pg, BASE + [(M031.read_text(encoding="utf-8"), M031.name), (SEED, "seed.sql"),
                                       (SHELLS, "shells.sql"), (SIDE_SEED, "side_seed.sql")])
    try:
        before = {k: ids(run(as_user(USERS["customer"], q))) for k, q in SIDE_READS.items()}
        apply(SQL, M032.name)
        apply(SQL, "032_again.sql")   # idempotent
        yield run, before
    finally:
        drop()


def test_l01_before_032_a_customer_reads_side_rows_of_withheld_properties(scratch):
    _, before = scratch
    for k, got in before.items():
        assert got == ALL, k   # the gap 032 closes


def test_l02_after_032_side_rows_agree_with_the_customers_property_reads(scratch):
    run, _ = scratch
    rpc = "select g.id from (values ('auctions'),('buy'),('lien')) v(l), lateral get_properties('FL', v.l, null, 1000, 0) g;"
    assert ids(run(as_user(USERS["customer"], rpc))) == VISIBLE_TO_CUSTOMER
    assert ids(run(as_user(USERS["customer"], "select id from public.properties;"))) == VISIBLE_TO_CUSTOMER
    for k, q in SIDE_READS.items():
        assert ids(run(as_user(USERS["customer"], q))) == VISIBLE_TO_CUSTOMER, k
    # A side row of a withheld property is not readable even by its id.
    q = "select count(*) from public.inventory_status_observations where property_id = 'aaaaaaaa-0000-0000-0000-000000000002';"
    assert run(as_user(USERS["customer"], q)).strip().splitlines()[-1] == "0"
    # Alerts without a property stay readable to their owner.
    q = "select count(*) from public.user_alerts where property_id is null;"
    assert run(as_user(USERS["customer"], q)).strip().splitlines()[-1] == "1"


def test_l03_admin_reads_every_side_row(scratch):
    run, _ = scratch
    for k, q in SIDE_READS.items():
        if k == "user_alerts":
            continue   # alerts are per owner; the admin owns none
        assert ids(run(as_user(USERS["admin"], q))) == ALL, k


def test_l04_pending_unknown_and_anon_read_nothing(scratch):
    run, _ = scratch
    for who in ("pending", "unknown"):
        for k, q in SIDE_READS.items():
            assert ids(run(as_user(USERS[who], q))) == [], (who, k)
    assert "permission denied" in run("reset role; set role anon; select * from public.auction_events;").lower()


def test_l05_policies_stay_permissive_select_and_the_only_permissive_read(scratch):
    run, _ = scratch
    out = run("select tablename || '|' || policyname || '|' || permissive || '|' || cmd from pg_policies "
              "where tablename in ('auction_events','auction_event_observations','inventory_status_observations',"
              "'property_change_events','user_alerts') order by tablename, policyname;")
    lines = [l for l in out.splitlines() if l.count("|") == 3]
    assert lines == [
        "auction_event_observations|auction_event_observations: approved read|PERMISSIVE|SELECT",
        "auction_events|auction_events: approved read|PERMISSIVE|SELECT",
        "inventory_status_observations|inventory_status_observations: approved read|PERMISSIVE|SELECT",
        "property_change_events|property_change_events: approved read|PERMISSIVE|SELECT",
        "user_alerts|user_alerts: approved only|RESTRICTIVE|ALL",
        "user_alerts|user_alerts: own rows|PERMISSIVE|ALL",
        "user_alerts|user_alerts: property readable|RESTRICTIVE|SELECT",
    ]


def test_l06_publishing_or_withholding_a_property_moves_its_side_rows_with_it(scratch):
    run, _ = scratch
    q = "select count(*) from public.auction_events where property_id = 'aaaaaaaa-0000-0000-0000-000000000002';"
    assert run(as_user(USERS["customer"], q)).strip().splitlines()[-1] == "0"
    run("update public.properties set publication_state = 'CUSTOMER_PUBLISHED' where id = 'aaaaaaaa-0000-0000-0000-000000000002';")
    assert run(as_user(USERS["customer"], q)).strip().splitlines()[-1] == "1"
    run("update public.properties set publication_state = 'ADMIN_ONLY_NO_PATH' where id = 'aaaaaaaa-0000-0000-0000-000000000002';")
    assert run(as_user(USERS["customer"], q)).strip().splitlines()[-1] == "0"


def test_l07_rollback_restores_the_pre_032_read_rules(pg):
    apply, run, drop = _db(pg, BASE + [(M031.read_text(encoding="utf-8"), M031.name), (SEED, "seed.sql"),
                                       (SHELLS, "shells.sql"), (SIDE_SEED, "side_seed.sql"), (SQL, M032.name)])
    try:
        rollback = "\n".join(l[4:] for l in SQL.splitlines() if l.startswith("--   alter policy") or l.startswith("--   drop policy"))
        assert rollback.count(";") == 5
        apply(rollback, "rollback.sql")
        for k, q in SIDE_READS.items():
            assert ids(run(as_user(USERS["customer"], q))) == ALL, k
    finally:
        drop()


def test_l08_without_031_032_refuses(pg):
    apply, run, drop = _db(pg, BASE + [(SHELLS, "shells.sql")])
    try:
        r = apply(SQL, M032.name, ok=False)
        assert r.returncode != 0 and "032 requires 031" in r.stderr
    finally:
        drop()


def test_l09_tables_not_created_yet_are_skipped_not_guessed(pg):
    apply, run, drop = _db(pg, BASE + [(M031.read_text(encoding="utf-8"), M031.name)])
    try:
        r = apply(SQL, M032.name)
        assert "does not exist yet - skipped" in r.stderr
    finally:
        drop()
