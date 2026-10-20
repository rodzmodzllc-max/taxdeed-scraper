"""Migration 034 (parcel boundaries) - contract tests. Written, NOT applied.

STATIC: additive only (no drop of anything that exists, no delete, no write to
`properties`); one boundary per property and one property per source feature;
writes only through service_role functions; the customer read is invoker
rights and returns the source's full attribution.

LIVE (local PostgreSQL with PostGIS only, skipped otherwise): on 026's scratch
schema + 031 (publication gate) + 034 applied twice, the writer inserts,
replaces, skips unchanged / invalid / other-source / already-attached
features and never deletes; a COMPLETE refresh advances the last success
and a failed one does not; a customer reads a boundary (with credit, licence
link, change notice, disclaimer and metadata) only for a property the
publication gate lets them read; pending and anonymous callers read nothing;
clients cannot write.
"""
from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
M034 = ROOT / "scripts/migrations/034_parcel_boundaries.sql"
SQL = M034.read_text(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_migration_016_source_health import _psql_prefix, _run  # noqa: E402
from test_publication_state_gate import (FIXTURE, IS_ADMIN_SQL, M025, M026, SEED, USERS,  # noqa: E402
                                         as_user)
from test_publication_state_gate import SQL as SQL031  # noqa: E402


def code() -> str:
    return "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--"))


# --- static --------------------------------------------------------------------

def test_s01_additive_and_never_deletes():
    body = code().lower()
    for bad in ("drop table", "drop column", "delete from", "truncate", "update public.properties",
                "alter table public.properties", "on public.properties"):
        assert bad not in body, bad
    assert "not applied" in SQL.lower()


def test_s02_one_boundary_per_property_and_one_property_per_feature():
    assert re.search(r"property_id\s+uuid primary key references public\.properties\(id\)", SQL)
    assert "constraint parcel_boundaries_one_feature unique (source_id, source_dataset, source_feature_id)" in SQL
    assert "geometry(MultiPolygon, 4326)" in SQL and "ST_IsValid(geom)" in SQL


def test_s03_writes_are_service_role_only_and_reads_are_invoker_rights():
    for fn in ("upsert_parcel_boundaries(text, jsonb)", "record_parcel_boundary_refresh(text, text, timestamptz)"):
        assert f"revoke all on function public.{fn} from public, anon, authenticated;" in SQL
        assert f"grant execute on function public.{fn} to service_role;" in SQL
    assert "revoke all on public.parcel_boundaries from anon, authenticated;" in SQL
    assert "grant select on public.parcel_boundaries to authenticated;" in SQL
    assert "grant insert" not in SQL.lower() and "grant update" not in SQL.lower()
    assert "revoke all on function public.get_property_boundary(uuid) from public, anon;" in SQL


def test_s04_seeded_sources_never_overwrite_refresh_state():
    assert "on conflict (source_id) do nothing;" in SQL


# --- live ------------------------------------------------------------------------

P_PUB, P_HELD, P_OTHER = ("aaaaaaaa-0000-0000-0000-000000000001", "aaaaaaaa-0000-0000-0000-000000000002",
                          "aaaaaaaa-0000-0000-0000-000000000003")


def sq(x, y, h=0.0003):
    return ('{"type":"MultiPolygon","coordinates":[[[[%s,%s],[%s,%s],[%s,%s],[%s,%s],[%s,%s]]]]}'
            % (x, y, x + h, y, x + h, y + h, x, y + h, x, y))


def row(pid, fid, geo, sha):
    return ('{"property_id":"%s","state":"UT","county":"Salt Lake","parcel":"P-%s","source_dataset":"Parcels_SaltLake_LIR",'
            '"source_feature_id":"%s","geometry":%s,"match_method":"EXACT_PARCEL_ID","simplify_tolerance_deg":0.000005,'
            '"source_observed_at":"2026-10-21T00:00:00Z","content_sha256":"%s"}' % (pid, fid, fid, geo, sha * 64))


@pytest.fixture(scope="module")
def scratch():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no local PostgreSQL reachable - live migration layer skipped (static layer still ran)")
    probe = _run(prefix, "-Atc", "select count(*) from pg_available_extensions where name = $$postgis$$", db="postgres")
    if probe.returncode != 0 or probe.stdout.strip() != "1":
        pytest.skip("PostGIS is not installed on the local PostgreSQL - live layer skipped")
    db = f"tdw_mig034_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    staged = []

    def apply(text: str, name: str):
        copy = Path("/tmp") / f"{db}_{len(staged)}_{name}"
        copy.write_text(text, encoding="utf-8")
        copy.chmod(0o644)
        staged.append(copy)
        r = _run(prefix, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(copy), db=db)
        assert r.returncode == 0, f"{name} failed to apply:\n{r.stderr}"

    def run(sql):
        r = _run(prefix, "-v", "ON_ERROR_STOP=0", "-Atq", db=db, stdin=sql)
        return (r.stdout or "") + (r.stderr or "")

    try:
        for path in (FIXTURE, M025, M026):
            apply(path.read_text(encoding="utf-8"), path.name)
        apply(IS_ADMIN_SQL, "is_admin.sql")
        apply(SQL031, "031.sql")
        apply(SEED, "seed.sql")
        apply(SQL, M034.name)
        apply(SQL, "034_again.sql")      # idempotent
        yield run
    finally:
        _run(prefix, "-Atc", f"drop database if exists {db}", db="postgres")
        for c in staged:
            c.unlink(missing_ok=True)


def upsert(run, source, rows):
    out = run(f"set role service_role; select public.upsert_parcel_boundaries('{source}', '[{','.join(rows)}]'::jsonb);")
    return out.strip()


def test_l01_writer_inserts_skips_and_never_deletes(scratch):
    ut = "ut_ugrc_lir_saltlake"
    out = upsert(scratch, ut, [
        row(P_PUB, "1", sq(-111.9, 40.7), "a"),
        row(P_HELD, "2", sq(-111.9, 40.71), "b"),
        row(P_OTHER, "1", sq(-111.9, 40.72), "c"),                                      # feature 1 already attached
        row("aaaaaaaa-0000-0000-0000-0000000000ff", "9", sq(-111.9, 40.73), "d"),        # no such property
        row(P_OTHER, "5", '{"type":"MultiPolygon","coordinates":[[[[0,0],[1,1],[1,0],[0,1],[0,0]]]]}', "e"),  # self-intersecting
    ])
    assert '"inserted": 2' in out and '"feature_already_attached": 1' in out and '"no_property": 1' in out
    assert '"invalid": 1' in out and '"deleted": 0' in out
    same = upsert(scratch, ut, [row(P_PUB, "1", sq(-111.9, 40.7), "a")])
    assert '"unchanged": 1' in same
    moved = upsert(scratch, ut, [row(P_PUB, "1", sq(-111.9, 40.7001), "f")])
    assert '"replaced": 1' in moved
    other = upsert(scratch, "fl_dor_pto_parcel_gis", [row(P_PUB, "77", sq(-82.0, 29.6), "g")])
    assert '"kept_other_source": 1' in other
    assert scratch("set role service_role; select count(*), min(source_id) from public.parcel_boundaries;").strip() == f"2|{ut}"
    # A failed refresh leaves every boundary in place; nothing in 034 deletes.
    scratch(f"set role service_role; select public.record_parcel_boundary_refresh('{ut}', 'INCOMPLETE', now());")
    assert scratch("set role service_role; select count(*) from public.parcel_boundaries;").strip() == "2"


def test_l02_only_a_complete_refresh_advances_the_last_success(scratch):
    ut = "ut_ugrc_lir_saltlake"
    scratch(f"set role service_role; select public.record_parcel_boundary_refresh('{ut}', 'COMPLETE', '2026-10-21T00:00:00Z');")
    scratch(f"set role service_role; select public.record_parcel_boundary_refresh('{ut}', 'FAILED', '2026-10-22T00:00:00Z');")
    out = scratch(f"select last_successful_refresh_at at time zone 'UTC', last_attempt_status, consecutive_failures, "
                  f"expected_refresh_cadence from public.parcel_boundary_sources where source_id = '{ut}';").strip()
    assert out == "2026-10-21 00:00:00|FAILED|1|Generally monthly"
    assert "unknown parcel boundary source" in scratch(
        "set role service_role; select public.record_parcel_boundary_refresh('nope', 'COMPLETE', now());")


def test_l03_customer_reads_a_boundary_with_full_attribution_only_where_the_gate_allows(scratch):
    q = ("select source_id, attribution, license_name, license_url, change_notice <> '', disclaimer_url, metadata_url <> '', "
         "source_dataset, source_feature_id, boundary->>'type' from public.get_property_boundary('%s');")
    out = scratch(as_user(USERS["customer"], q % P_PUB)).strip()
    assert out == ("ut_ugrc_lir_saltlake|Utah Geospatial Resource Center (UGRC)|CC BY 4.0|"
                   "https://creativecommons.org/licenses/by/4.0/|t|https://gis.utah.gov/documentation/policy/license/|t|"
                   "Parcels_SaltLake_LIR|1|MultiPolygon")
    # The held property's boundary is invisible to the customer, through the RPC and the table.
    assert scratch(as_user(USERS["customer"], q % P_HELD)).strip() == ""
    assert scratch(as_user(USERS["customer"], "select count(*) from public.parcel_boundaries;")).strip() == "1"
    assert scratch(as_user(USERS["admin"], "select count(*) from public.parcel_boundaries;")).strip() == "2"
    for who in ("pending", "unknown"):
        assert scratch(as_user(USERS[who], q % P_PUB)).strip() == ""
    assert "permission denied" in scratch(f"reset role; set role anon; select * from public.get_property_boundary('{P_PUB}');")


def test_l04_display_grant_withdrawn_hides_every_boundary_of_that_source(scratch):
    scratch("set role postgres; update public.parcel_boundary_sources set display_approved = false where source_id = 'ut_ugrc_lir_saltlake';")
    try:
        assert scratch(as_user(USERS["customer"], f"select count(*) from public.get_property_boundary('{P_PUB}');")).strip() == "0"
        assert scratch(as_user(USERS["admin"], "select count(*) from public.parcel_boundaries;")).strip() == "0"
    finally:
        scratch("set role postgres; update public.parcel_boundary_sources set display_approved = true where source_id = 'ut_ugrc_lir_saltlake';")


def test_l05_clients_cannot_write_or_call_the_writer(scratch):
    for who in ("customer", "admin"):
        out = scratch(as_user(USERS[who], f"delete from public.parcel_boundaries where property_id = '{P_PUB}';"))
        assert "permission denied" in out
        out = scratch(as_user(USERS[who], "select public.upsert_parcel_boundaries('ut_ugrc_lir_saltlake', '[]'::jsonb);"))
        assert "permission denied" in out
    assert scratch("set role service_role; select count(*) from public.parcel_boundaries;").strip() == "2"


def test_l06_reapplying_034_keeps_refresh_state(scratch):
    out = scratch("select last_successful_refresh_at is not null from public.parcel_boundary_sources "
                  "where source_id = 'ut_ugrc_lir_saltlake';").strip()
    assert out == "t"


def test_read_returns_source_freshness_from_recorded_timestamps_only():
    # The outline credit names TAXACQ's own last successful refresh and the
    # source's published cadence. Both come straight from the register; the
    # read never invents a date (a NEVER refresh reads null).
    fn = SQL[SQL.index("create or replace function public.get_property_boundary"):]
    fn = fn[:fn.index("$$;")]
    assert "source_last_successful_refresh_at timestamptz" in fn
    assert "source_expected_cadence text" in fn
    assert "s.last_successful_refresh_at, s.expected_refresh_cadence" in fn
    assert "coalesce" not in fn.lower()
