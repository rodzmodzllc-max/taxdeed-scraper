"""Migration 035 (per-county parcel-boundary refresh) - contract tests.

035 upgrades 034 as it runs in production (034 was found applied directly on
2026-10-21). STATIC: nothing deleted or rewritten except Florida's
source-level refresh state; writer functions service-role only; the customer
read stays invoker rights. LIVE (local PostgreSQL with PostGIS, skipped
otherwise): 034 applied, then the state production holds (a Florida boundary
and a Florida source-level refresh from one county's read), then 035 twice:
stored boundaries survive untouched, Florida's statewide refresh is cleared,
3-argument refresh calls still work, per-county refresh is recorded only on
COMPLETE, and a customer read names the property's own county refresh.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
M034 = ROOT / "scripts/migrations/034_parcel_boundaries.sql"
M035 = ROOT / "scripts/migrations/035_parcel_boundary_county_refresh.sql"
SQL = M035.read_text(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_migration_016_source_health import _psql_prefix, _run  # noqa: E402
from test_migration_034_parcel_boundaries import P_OTHER, P_PUB, row, sq, upsert  # noqa: E402
from test_publication_state_gate import (FIXTURE, IS_ADMIN_SQL, M025, M026, SEED, USERS,  # noqa: E402
                                         as_user)
from test_publication_state_gate import SQL as SQL031  # noqa: E402

FL, UT = "fl_dor_pto_parcel_gis", "ut_ugrc_lir_saltlake"


def code() -> str:
    return "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--"))


def top_level() -> str:
    """The migration's own statements, without function bodies."""
    import re  # noqa: PLC0415
    return re.sub(r"\$\$.*?\$\$", "$$ $$", code(), flags=re.S)


# --- static --------------------------------------------------------------------

def test_s01_nothing_is_deleted_and_properties_are_untouched():
    body = top_level().lower()
    for bad in ("drop table", "drop column", "delete from", "truncate", "update public.properties",
                "alter table public.properties", "update public.parcel_boundaries "):
        assert bad not in body, bad
    # The only updates are Florida's source-level refresh state and its change notice.
    assert body.count("update public.parcel_boundary_sources") == 2
    assert body.count("where source_id = 'fl_dor_pto_parcel_gis'") == 2


def test_s02_writers_are_service_role_only_and_the_read_is_invoker_rights():
    for fn in ("upsert_parcel_boundaries(text, jsonb)", "record_parcel_boundary_refresh(text, text, timestamptz, text, text, date)"):
        assert f"revoke all on function public.{fn} from public, anon, authenticated;" in SQL
        assert f"grant execute on function public.{fn} to service_role;" in SQL
    assert "drop function if exists public.record_parcel_boundary_refresh(text, text, timestamptz);" in SQL
    assert "revoke all on public.parcel_boundary_refresh_units from anon, authenticated;" in SQL
    read = SQL[SQL.index("create or replace function public.get_property_boundary"):]
    read = read[:read.index("$$;")]
    assert "security invoker" in read and "join public.properties p on p.id = b.property_id" in read
    assert "public.parcel_boundary_refresh_of(b.source_id, p.county), s.expected_refresh_cadence" in read
    assert "coalesce" not in read.lower()


def test_s03_freshness_helper_returns_recorded_timestamps_only():
    helper = SQL[SQL.index("create or replace function public.parcel_boundary_refresh_of"):]
    helper = helper[:helper.index("$$;")]
    assert "security definer" in helper and "set search_path = public" in helper
    assert "now()" not in helper.lower() and "coalesce" not in helper.lower()
    assert "grant execute on function public.parcel_boundary_refresh_of(text, text) to authenticated, service_role;" in SQL
    assert "revoke all on function public.parcel_boundary_refresh_of(text, text) from public, anon;" in SQL


# --- live ------------------------------------------------------------------------

@pytest.fixture(scope="module")
def scratch():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no local PostgreSQL reachable - live migration layer skipped (static layer still ran)")
    probe = _run(prefix, "-Atc", "select count(*) from pg_available_extensions where name = $$postgis$$", db="postgres")
    if probe.returncode != 0 or probe.stdout.strip() != "1":
        pytest.skip("PostGIS is not installed on the local PostgreSQL - live layer skipped")
    db = f"tdw_mig035_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    staged = []

    def apply(text: str, name: str, single_transaction: bool = False):
        copy = Path("/tmp") / f"{db}_{len(staged)}_{name}"
        copy.write_text(text, encoding="utf-8")
        copy.chmod(0o644)
        staged.append(copy)
        flags = ("-v", "ON_ERROR_STOP=1", "-q") + (("-1",) if single_transaction else ())
        r = _run(prefix, *flags, "-f", str(copy), db=db)
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
        apply(M034.read_text(encoding="utf-8"), M034.name)
        # The state production holds before 035: a Florida boundary written by a
        # one-county read, which also set Florida's source-level refresh.
        fl_row = row(P_OTHER, "broward#1", sq(-80.2, 26.1), "f").replace(
            '"source_dataset":"Parcels_SaltLake_LIR"', '"source_dataset":"DOR PTO PIN 2025F Broward"').replace(
            '"state":"UT","county":"Salt Lake"', '"state":"FL","county":"Bay"')
        assert '"inserted": 1' in upsert(run, FL, [fl_row])
        run(f"set role service_role; select public.record_parcel_boundary_refresh('{FL}', 'COMPLETE', '2026-10-21T10:49:22Z');")
        apply(SQL, M035.name, single_transaction=True)          # as Supabase applies a migration
        apply(SQL, "035_again.sql", single_transaction=True)    # idempotent
        yield run
    finally:
        _run(prefix, "-Atc", f"drop database if exists {db}", db="postgres")
        for c in staged:
            c.unlink(missing_ok=True)


def test_l01_existing_boundaries_survive_and_florida_statewide_refresh_is_cleared(scratch):
    assert scratch("select count(*), count(source_dataset_date) from public.parcel_boundaries;").strip() == "1|0"
    assert scratch(f"select last_successful_refresh_at is null and last_attempt_at is null from "
                   f"public.parcel_boundary_sources where source_id = '{FL}';").strip() == "t"
    assert "NAD83 treated as WGS84" in scratch(f"select change_notice from public.parcel_boundary_sources where source_id = '{FL}';")


def test_l02_a_three_argument_refresh_still_records_a_whole_layer_source(scratch):
    scratch(f"set role service_role; select public.record_parcel_boundary_refresh('{UT}', 'COMPLETE', '2026-10-22T00:00:00Z');")
    assert scratch(f"select last_successful_refresh_at at time zone 'UTC' from public.parcel_boundary_sources "
                   f"where source_id = '{UT}';").strip() == "2026-10-22 00:00:00"
    scratch(f"set role service_role; select public.record_parcel_boundary_refresh('{UT}', 'FAILED', '2026-10-23T00:00:00Z');")
    assert scratch(f"select last_successful_refresh_at at time zone 'UTC', consecutive_failures from "
                   f"public.parcel_boundary_sources where source_id = '{UT}';").strip() == "2026-10-22 00:00:00|1"


def test_l03_customers_read_the_propertys_own_county_refresh_and_never_the_bookkeeping(scratch):
    read = lambda: scratch(as_user(USERS["customer"], f"select source_last_successful_refresh_at at time zone 'UTC', "  # noqa: E731
                                                      f"source_dataset_date from public.get_property_boundary('{P_OTHER}');")).strip()
    assert read() == "|"                                   # no county refresh recorded: not yet recorded
    scratch(f"set role service_role; select public.record_parcel_boundary_refresh('{FL}', 'COMPLETE', "
            f"'2026-10-24T00:00:00Z', 'Leon', 'DOR PTO PIN parcel shapefile leon_pin', '2026-08-20');")
    assert read() == "|"                                   # Leon's refresh never stands in for Bay's
    scratch(f"set role service_role; select public.record_parcel_boundary_refresh('{FL}', 'COMPLETE', "
            f"'2026-10-25T00:00:00Z', 'Bay', 'DOR PTO PIN parcel shapefile bay_pin', '2026-08-21');")
    assert read() == "2026-10-25 00:00:00|"
    scratch(f"set role service_role; select public.record_parcel_boundary_refresh('{FL}', 'FAILED', "
            f"'2026-10-26T00:00:00Z', 'Bay');")
    assert read() == "2026-10-25 00:00:00|"               # a failed read keeps the last success
    assert scratch(f"select dataset, dataset_date, last_attempt_status, consecutive_failures from "
                   f"public.parcel_boundary_refresh_units where source_id = '{FL}' and unit = 'Bay';").strip() == \
        "DOR PTO PIN parcel shapefile bay_pin|2026-08-21|FAILED|1"
    assert scratch(f"select last_successful_refresh_at is null from public.parcel_boundary_sources "
                   f"where source_id = '{FL}';").strip() == "t"
    assert "permission denied" in scratch(as_user(USERS["customer"], "select * from public.parcel_boundary_refresh_units;"))


def test_l04_the_dataset_date_is_stored_and_returned(scratch):
    r = row(P_OTHER, "bay_pin#9", sq(-85.6, 30.2), "9").replace(
        '"source_dataset":"Parcels_SaltLake_LIR"', '"source_dataset":"DOR PTO PIN parcel shapefile bay_pin","source_dataset_date":"2026-08-21"')
    assert '"replaced": 1' in upsert(scratch, FL, [r])
    out = scratch(as_user(USERS["customer"], f"select source_dataset, source_dataset_date, source_feature_id "
                                             f"from public.get_property_boundary('{P_OTHER}');")).strip()
    assert out == "DOR PTO PIN parcel shapefile bay_pin|2026-08-21|bay_pin#9"


def test_l05_clients_cannot_write_or_call_the_writers(scratch):
    for who in ("customer", "pending"):
        for stmt in (f"select public.record_parcel_boundary_refresh('{FL}', 'COMPLETE', now(), 'Bay');",
                     f"select public.upsert_parcel_boundaries('{FL}', '[]'::jsonb);",
                     "insert into public.parcel_boundary_refresh_units (source_id, unit) values ('x', 'y');"):
            assert "permission denied" in scratch(as_user(USERS[who], stmt)), (who, stmt)
    # Anonymous callers read nothing at all.
    assert "permission denied" in scratch(f"set role anon; select * from public.get_property_boundary('{P_PUB}');")


def test_l06_the_listing_join_method_is_storable_and_others_are_not(scratch):
    from test_migration_034_parcel_boundaries import P_HELD
    ok = row(P_HELD, "x#1", sq(-84.3, 30.4), "a").replace('"EXACT_PARCEL_ID"', '"PARCEL_NUMBER_LOCATION_CONFIRMED"')
    out = upsert(scratch, FL, [ok])
    assert '"inserted": 1' in out or '"replaced": 1' in out
    assert scratch(f"select match_method from public.parcel_boundaries where property_id = '{P_HELD}';").strip() \
        == "PARCEL_NUMBER_LOCATION_CONFIRMED"
    bad = scratch(f"insert into public.parcel_boundaries (property_id, state, county, parcel, source_id, source_dataset, "
                  f"source_feature_id, geom, match_method, simplify_tolerance_deg, content_sha256, source_observed_at) values "
                  f"('{P_PUB}', 'FL', 'Bay', 'p', '{FL}', 'd', 'f', ST_GeomFromText('MULTIPOLYGON(((0 0,1 0,1 1,0 0)))', 4326), "
                  f"'NEAREST', 0, repeat('a', 64), now());")
    assert "parcel_boundaries_match_method_check" in bad
