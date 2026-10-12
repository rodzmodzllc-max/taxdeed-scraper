"""Migration 032 (parcel boundaries, NOT applied) - static and live checks.

Static: the file's policy, grants and read contract.
Live (skipped unless a scratch PostgreSQL is reachable through TDW_SCRATCH_PG,
for example TDW_SCRATCH_PG="psql -h /var/tmp/pgtest -p 5499 -U postgres"):
the migration is applied verbatim to a scratch database that models the
production pieces it depends on (properties + publication gate, profiles,
is_approved), and each access case is asserted as the role that would hit it.
PostGIS is required for the live layer.
"""
import os
import re
import subprocess
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "scripts" / "migrations" / "032_parcel_boundaries.sql"

SETUP = """
create extension if not exists postgis;
do $$ begin
  if not exists (select 1 from pg_roles where rolname='anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname='authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname='service_role') then create role service_role nologin bypassrls; end if;
end $$;
grant usage on schema public to anon, authenticated, service_role;
-- Supabase grants service_role full table access by default; modelled here so the
-- write test below exercises the CHECK constraint, not a missing privilege.
alter default privileges in schema public grant all on tables to service_role;
create schema if not exists auth;
create or replace function auth.uid() returns uuid language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''),
                  nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')::uuid $$;
create table public.profiles (id uuid primary key, approved boolean not null default false, is_admin boolean not null default false);
create or replace function public.is_approved() returns boolean language sql stable security definer set search_path = public
  as $$ select coalesce((select approved from profiles where id = auth.uid()), false) $$;
create or replace function public.is_admin() returns boolean language sql stable security definer set search_path = public
  as $$ select coalesce((select is_admin from profiles where id = auth.uid()), false) $$;
create table public.properties (id bigint primary key, publication_state text not null default 'CUSTOMER_PUBLISHED');
alter table public.properties enable row level security;
create policy "properties: approved and published" on public.properties as permissive for select to authenticated
  using ((select public.is_approved()) and (publication_state = 'CUSTOMER_PUBLISHED' or (select public.is_admin())));
grant select on public.properties to authenticated;
insert into profiles values ('00000000-0000-0000-0000-000000000a01', true, false),
  ('00000000-0000-0000-0000-000000000b01', false, false), ('00000000-0000-0000-0000-0000000ad001', true, true);
insert into properties values (1, 'CUSTOMER_PUBLISHED'), (2, 'WITHHELD');
"""

SEED = """
insert into public.parcel_boundaries (property_id, state, county, parcel, geom, source_id, boundary_policy, match_method,
  source_observed_at, content_sha256, attribution) values
 (1, 'FL', 'Test', 'P1', ST_Multi(ST_GeomFromText('POLYGON((0 0,0 1,1 1,1 0,0 0))', 4326)), 'fixture_src', 'APPROVED', 'EXACT_PARCEL_ID', now(), repeat('a',64), 'Fixture attribution'),
 (2, 'FL', 'Test', 'P2', ST_Multi(ST_GeomFromText('POLYGON((2 2,2 3,3 3,3 2,2 2))', 4326)), 'fixture_src', 'APPROVED', 'EXACT_PARCEL_ID', now(), repeat('b',64), 'Fixture attribution');
"""

CUSTOMER = "00000000-0000-0000-0000-000000000a01"
UNAPPROVED = "00000000-0000-0000-0000-000000000b01"
ADMIN = "00000000-0000-0000-0000-0000000ad001"


# ==================== STATIC ====================


def test_migration_is_not_applied_marker_and_reversible():
    text = MIGRATION.read_text(encoding="utf-8")
    assert "NOT APPLIED" in text
    assert "drop table if exists public.parcel_boundaries" in text


def test_table_grants_and_policy_require_property_visibility():
    text = MIGRATION.read_text(encoding="utf-8")
    assert "revoke all on public.parcel_boundaries from anon, authenticated;" in text
    assert "grant select on public.parcel_boundaries to authenticated;" in text
    policy = re.search(r"create policy parcel_boundaries_approved_read.*?\);", text, re.S).group(0)
    assert "is_approved" in policy and "exists (select 1 from public.properties p" in policy


def test_attribution_is_required_and_non_blank():
    text = MIGRATION.read_text(encoding="utf-8")
    assert "attribution       text not null check (btrim(attribution) <> '')" in text


def test_rpc_is_invoker_with_locked_grants_and_contract_columns():
    text = MIGRATION.read_text(encoding="utf-8")
    assert "security invoker" in text
    assert "revoke all on function public.get_property_boundary(bigint) from public, anon;" in text
    assert "grant execute on function public.get_property_boundary(bigint) to authenticated;" in text
    for col in ("property_id bigint", "boundary jsonb", "display_permitted boolean", "attribution text",
                "source_id text", "match_method text", "source_observed_at timestamptz"):
        assert col in text, col


# ==================== LIVE ====================


def _psql_prefix():
    override = os.environ.get("TDW_SCRATCH_PG")
    if not override:
        return None
    cmd = override.split()
    r = subprocess.run([*cmd, "-d", "postgres", "-Atc", "select 1"], capture_output=True, text=True, timeout=15)
    return cmd if r.returncode == 0 and r.stdout.strip() == "1" else None


@pytest.fixture(scope="module")
def scratch():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no scratch PostgreSQL (set TDW_SCRATCH_PG) - live layer skipped")
    db = f"tdw_mig032_{uuid.uuid4().hex[:8]}"

    def psql(sql: str, dbname: str = db) -> subprocess.CompletedProcess:
        return subprocess.run([*prefix, "-d", dbname, "-v", "ON_ERROR_STOP=0", "-Atq"], input=sql,
                              capture_output=True, text=True, timeout=120)

    assert subprocess.run([*prefix, "-d", "postgres", "-Atc", f"create database {db}"], capture_output=True, text=True).returncode == 0
    try:
        assert psql(SETUP).returncode == 0
        r = subprocess.run([*prefix, "-d", db, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(MIGRATION)], capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr
        assert psql(SEED).returncode == 0

        def as_role(role: str, uid: str | None, sql: str) -> str:
            claims = f'{{"sub":"{uid}","role":"{role}"}}' if uid else "{}"
            res = psql(f"begin; set local role {role}; set local request.jwt.claims = '{claims}'; {sql}; rollback;")
            return (res.stdout + res.stderr).strip()

        yield as_role
    finally:
        subprocess.run([*prefix, "-d", "postgres", "-Atc", f"drop database if exists {db}"], capture_output=True, text=True)


def test_customer_rpc_returns_only_visible_property(scratch):
    assert scratch("authenticated", CUSTOMER, "select count(*) from public.get_property_boundary(1)") == "1"
    assert scratch("authenticated", CUSTOMER, "select count(*) from public.get_property_boundary(2)") == "0"


def test_customer_direct_table_read_cannot_bypass_publication_gate(scratch):
    assert scratch("authenticated", CUSTOMER, "select string_agg(property_id::text, ',' order by property_id) from public.parcel_boundaries") == "1"


def test_unapproved_account_reads_nothing(scratch):
    assert scratch("authenticated", UNAPPROVED, "select count(*) from public.parcel_boundaries") == "0"
    assert scratch("authenticated", UNAPPROVED, "select count(*) from public.get_property_boundary(1)") == "0"


def test_admin_sees_the_property_the_gate_withholds(scratch):
    assert scratch("authenticated", ADMIN, "select count(*) from public.get_property_boundary(2)") == "1"


def test_anon_has_no_table_or_rpc_access(scratch):
    out = scratch("anon", None, "select count(*) from public.parcel_boundaries")
    assert "permission denied" in out
    out = scratch("anon", None, "select count(*) from public.get_property_boundary(1)")
    assert "permission denied" in out


def test_blank_attribution_cannot_be_written(scratch):
    out = scratch("service_role", None,
                  "insert into public.parcel_boundaries (property_id, state, county, parcel, geom, source_id, boundary_policy, "
                  "match_method, source_observed_at, content_sha256, attribution) values (1, 'FL', 'T', 'P9', "
                  "ST_Multi(ST_GeomFromText('POLYGON((5 5,5 6,6 6,6 5,5 5))', 4326)), 'x', 'APPROVED', 'EXACT_PARCEL_ID', "
                  "now(), repeat('c',64), '   ')")
    assert "check constraint" in out
