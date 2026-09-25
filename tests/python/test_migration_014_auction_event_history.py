"""Migration 014 (auction-event history, Phase A) - contract tests.

Two layers, deliberately:

1. STATIC (always run, in CI too): the migration FILE is read as text and
   checked for exactly what it creates and, just as importantly, for what it
   must not touch - `properties`, `get_properties`, any existing trigger,
   index, policy or migration. No database, no network. Same discipline as
   every other migration test in this directory (test_phase58_api_projection,
   test_phase72_auction_link_kind).

2. LIVE (runs only where a local PostgreSQL is reachable; skipped otherwise):
   the migration is applied VERBATIM to a throwaway scratch database on a
   local cluster, on top of tests/python/fixtures/migration_014_scratch_fixture.sql
   (a minimal stand-in for the production objects 014 depends on: the three
   API roles, auth.uid(), profiles/is_approved(), touch_updated_at() and a
   `properties` table with its real primary key). The scratch database is
   created and dropped by this file. The Supabase project is never contacted
   - the DSN is a local unix socket, and `TDW_SCRATCH_PG` can point the test
   at a different local psql invocation. CI (python-governance-test.yml)
   starts no database, so the live layer reports SKIPPED there; it is meant
   to be run locally before the migration is authorized for production, and
   the run's output belongs in the PR.

Phase A performs no backfill and adds no writers, so the live layer also
asserts the two tables are created EMPTY.
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
MIGRATION = REPO / "scripts" / "migrations" / "014_auction_event_history.sql"
FIXTURE = REPO / "tests" / "python" / "fixtures" / "migration_014_scratch_fixture.sql"
DOC = REPO / "docs" / "production-data-contract.md"
MIG_013 = REPO / "scripts" / "migrations" / "013_auction_link_kind_and_tx_sale_status.sql"

SQL = MIGRATION.read_text(encoding="utf-8")

LIFECYCLE = ["scheduled", "completed", "cancelled", "withdrawn", "stayed", "pending_result", "superseded", "unknown"]
OUTCOME = ["sold", "redeemed", "struck_off", "future_sale", "no_sale", "unknown"]
URL_KIND = ["property", "sale", "county", "info"]


def sql_only() -> str:
    """The migration with comment lines removed, so a word that appears only
    in prose (e.g. 'properties.url_auction_kind' in a comment) is not read as
    a statement."""
    return "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--"))


def statements() -> list[str]:
    """Top-level statements, lower-cased and whitespace-collapsed."""
    body = sql_only()
    return [re.sub(r"\s+", " ", s).strip().lower() for s in body.split(";") if s.strip()]


def table_block(name: str) -> str:
    body = sql_only()
    m = re.search(rf"create table public\.{name}\s*\((.*?)\n\);", body, re.S)
    assert m, f"create table public.{name} (...) not found"
    return m.group(1)


def column_lines(name: str) -> dict[str, str]:
    """column name -> the rest of its definition line, for the table body."""
    out: dict[str, str] = {}
    for line in table_block(name).splitlines():
        s = line.strip()
        # Skip comments, constraint headers and their continuation lines.
        if not s or s.startswith(("--", "constraint", "unique (", "check (")):
            continue
        parts = s.rstrip(",").split(None, 1)
        if len(parts) == 2:
            out[parts[0]] = re.sub(r"\s+", " ", parts[1])
    return out


# ==================== STATIC: what 014 creates ====================


def test_s01_file_exists_and_is_one_transaction():
    assert MIGRATION.exists()
    st = statements()
    assert st[0] == "begin"
    assert st[-1] == "commit"


def test_s02_creates_exactly_the_two_tables():
    creates = [s for s in statements() if s.startswith("create table")]
    names = sorted(re.match(r"create table (public\.\S+)", s).group(1) for s in creates)
    assert names == ["public.auction_event_observations", "public.auction_events"]


def test_s03_auction_events_columns_types_nullability_defaults():
    cols = column_lines("auction_events")
    expected = {
        "id": ("uuid", "primary key default gen_random_uuid()"),
        "property_id": ("uuid", "not null references public.properties(id) on delete restrict"),
        "state": ("text", "not null"),
        "source": ("text", "not null"),
        "harvester_source": ("text", ""),
        "county": ("text", "not null"),
        "case_no": ("text", "not null"),
        "ledger_type": ("text", ""),
        "scheduled_sale_date": ("date", "not null"),
        "event_url": ("text", ""),
        "event_url_kind": ("text", ""),
        "opening_bid": ("numeric", ""),
        "lifecycle": ("text", "not null default 'scheduled'"),
        "outcome": ("text", "not null default 'unknown'"),
        "outcome_raw": ("text", ""),
        "outcome_observed_at": ("timestamptz", ""),
        "outcome_effective_date": ("date", ""),
        "winning_bid": ("numeric", ""),
        "bid_count": ("integer", ""),
        "winning_bidder_ref": ("text", ""),
        "source_event_ref": ("text", ""),
        "first_seen_at": ("timestamptz", "not null default now()"),
        "last_seen_at": ("timestamptz", "not null default now()"),
        "created_at": ("timestamptz", "not null default now()"),
        "updated_at": ("timestamptz", "not null default now()"),
    }
    assert set(cols) == set(expected), sorted(set(cols) ^ set(expected))
    for name, (typ, rest) in expected.items():
        definition = cols[name]
        assert definition.split()[0] == typ, (name, definition)
        assert definition[len(typ):].strip() == rest, (name, definition)


def test_s04_observations_columns_types_nullability_defaults():
    cols = column_lines("auction_event_observations")
    expected = {
        "id": ("bigint", "generated always as identity primary key"),
        "event_id": ("uuid", "not null references public.auction_events(id) on delete restrict"),
        "observed_at": ("timestamptz", "not null default now()"),
        "harvest_run_id": ("text", ""),
        "feed": ("text", "not null"),
        "raw_status": ("text", ""),
        "lifecycle": ("text", "not null"),
        "outcome": ("text", "not null default 'unknown'"),
        "opening_bid": ("numeric", ""),
        "winning_bid": ("numeric", ""),
        "bid_count": ("integer", ""),
        "evidence_url": ("text", ""),
        "created_at": ("timestamptz", "not null default now()"),
    }
    assert set(cols) == set(expected), sorted(set(cols) ^ set(expected))
    for name, (typ, rest) in expected.items():
        definition = cols[name]
        assert definition.split()[0] == typ, (name, definition)
        assert definition[len(typ):].strip() == rest, (name, definition)


def test_s05_no_bidder_purchaser_or_raw_json_columns():
    for table in ("auction_events", "auction_event_observations"):
        names = " ".join(column_lines(table))
        for banned in ("bidder_name", "purchaser", "winner_name", "bidder_id", "raw_json", "raw_data", "payload", "snapshot"):
            assert banned not in names, (table, banned)
    assert "jsonb" not in sql_only().lower()


def _check_values(constraint_name: str) -> list[str]:
    m = re.search(rf"constraint {constraint_name}\s+check \((.*?)\)\s*[,\n]", sql_only(), re.S)
    assert m, constraint_name
    return re.findall(r"'([a-z_]+)'", m.group(1))


def test_s06_lifecycle_and_outcome_checks_use_the_audited_vocabularies_only():
    assert _check_values("auction_events_lifecycle_check") == LIFECYCLE
    assert _check_values("auction_event_observations_lifecycle_check") == LIFECYCLE
    assert _check_values("auction_events_outcome_check") == OUTCOME
    assert _check_values("auction_event_observations_outcome_check") == OUTCOME
    for forbidden in ("left_feed", "closed", "active", "notfound", "dropped"):
        assert forbidden not in LIFECYCLE + OUTCOME
        assert forbidden not in _check_values("auction_events_outcome_check")


def test_s07_event_url_kind_check_matches_migration_013_vocabulary():
    assert _check_values("auction_events_event_url_kind_check") == URL_KIND
    # The same four values 013 put on properties.url_auction_kind.
    m = re.search(r"url_auction_kind in \((.*?)\)", MIG_013.read_text(encoding="utf-8"))
    assert re.findall(r"'([a-z]+)'", m.group(1)) == URL_KIND
    assert "event_url_kind is null or" in sql_only()


def test_s08_uniqueness_and_foreign_keys():
    body = sql_only()
    assert "unique (property_id, scheduled_sale_date)" in body
    assert "unique (event_id, observed_at)" in body
    assert body.count("on delete restrict") == 2
    assert "on delete cascade" not in body
    # None of the rejected identities is unique.
    for bad in ("unique (event_url", "unique (county", "unique (case_no", "unique (parcel"):
        assert bad not in body


def test_s09_indexes_are_the_justified_set_and_each_is_documented():
    idx = re.findall(r"create index (\w+)\s+on public\.(\w+)\s*\((.*?)\)(?:\s+where (.*?))?;", sql_only(), re.S)
    got = {name: (table, re.sub(r"\s+", " ", cols), (where or "").strip()) for name, table, cols, where in idx}
    assert got == {
        "auction_events_state_county_date_idx": ("auction_events", "state, county, scheduled_sale_date", ""),
        "auction_events_source_date_idx": ("auction_events", "source, scheduled_sale_date", ""),
        "auction_events_unresolved_idx": ("auction_events", "scheduled_sale_date", "outcome = 'unknown'"),
        "auction_event_observations_observed_at_idx": ("auction_event_observations", "observed_at", ""),
        "auction_event_observations_run_idx": ("auction_event_observations", "harvest_run_id", "harvest_run_id is not null"),
    }
    # Every index is preceded by a comment explaining it.
    for name in got:
        pos = SQL.index(f"create index {name}")
        preceding = SQL[:pos].rstrip().splitlines()[-1]
        assert preceding.strip().startswith("--"), name


def test_s10_rls_one_permissive_select_policy_per_table_gated_on_is_approved():
    body = sql_only()
    assert "alter table public.auction_events enable row level security" in body
    assert "alter table public.auction_event_observations enable row level security" in body
    policies = re.findall(r"create policy \"([^\"]+)\"\s+on public\.(\w+)\s+as (\w+)\s+for (\w+)\s+to (\w+)\s+using \((.*?)\);", body, re.S)
    assert sorted(p[1] for p in policies) == ["auction_event_observations", "auction_events"]
    for name, table, kind, cmd, role, using in policies:
        assert kind == "permissive", (table, kind)  # never the schema-v6 restrictive-only mistake
        assert cmd == "select", (table, cmd)
        assert role == "authenticated", (table, role)
        assert using.strip() == "public.is_approved()", (table, using)
    assert "as restrictive" not in body
    assert "for insert" not in body and "for update" not in body and "for delete" not in body and "for all" not in body


def test_s11_grants_anon_nothing_authenticated_select_service_role_dml():
    st = statements()
    grants = [s for s in st if s.startswith("grant ")]
    revokes = [s for s in st if s.startswith("revoke ")]
    assert "revoke all on table public.auction_events from public, anon, authenticated" in revokes
    assert "revoke all on table public.auction_event_observations from public, anon, authenticated" in revokes
    assert "grant select on table public.auction_events to authenticated" in grants
    assert "grant select on table public.auction_event_observations to authenticated" in grants
    assert "grant select, insert, update, delete on table public.auction_events to service_role" in grants
    assert "grant select, insert, update, delete on table public.auction_event_observations to service_role" in grants
    assert "grant usage, select on sequence public.auction_event_observations_id_seq to service_role" in grants
    assert not any(" to anon" in g or " to public" in g for g in grants)


# ==================== STATIC: what 014 must not touch ====================


def test_s12_migration_is_additive_only():
    st = statements()
    for s in st:
        assert not s.startswith("alter table public.properties"), s
        assert not s.startswith("drop "), s
        assert not s.startswith("insert "), s
        assert not s.startswith("update "), s
        assert not s.startswith("delete "), s
        assert not s.startswith("truncate "), s
        assert "get_properties" not in s, s
        assert not s.startswith("create or replace function"), s
        assert not s.startswith("create function"), s
        assert "alter policy" not in s and "drop policy" not in s, s
        assert "alter index" not in s and "drop index" not in s, s
    triggers = [s for s in st if s.startswith("create trigger")]
    assert triggers == ["create trigger auction_events_touch before update on public.auction_events for each row execute function public.touch_updated_at()"]
    # Nothing rewrites the observation log automatically.
    assert not any("auction_event_observations" in t for t in triggers)


def test_s13_existing_migrations_untouched_and_numbering_is_next():
    numbered = sorted(p.name for p in (REPO / "scripts" / "migrations").glob("*.sql"))
    assert numbered[-1] == "014_auction_event_history.sql"
    assert MIG_013.exists()
    # 013's own contract is unchanged (its test file still guards it); here we
    # only assert 014 does not redefine 013's objects.
    body = sql_only()
    assert "properties_url_auction_kind_check" not in body
    assert "tx_sale_status" not in body


def test_s14_no_writers_touched_in_this_phase_and_frontend_unaware():
    """Phase A ships no writers: no harvester or sync script references the
    new tables, and neither does the frontend."""
    for rel in (
        "scripts/sync-harvest-to-supabase.ps1", "scripts/sync-texas-to-supabase.py",
        "scripts/sync-laft-to-supabase.ps1", "scripts/sync-certificates-to-supabase.ps1",
        "harvesters/texas_harvester.py", "scripts/harvest_all_counties.ps1",
        "public/app.js", "public/explore.js", "public/satellite-map.js",
    ):
        text = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        assert "auction_events" not in text, rel
        assert "auction_event_observations" not in text, rel


def test_s15_data_contract_documents_the_eight_required_statements():
    doc = DOC.read_text(encoding="utf-8")
    section = doc.split("## 26. Auction-event history contract")[1]
    for required in (
        "`properties` remains the current-state representation",
        "`auction_events` represents individual scheduled auction events",
        "`auction_event_observations` preserves source observations over time",
        "`(property_id, scheduled_sale_date)` is the current event identity",
        "not equivalent to \"sold\"",
        "`unknown` outcomes remain `unknown`",
        "Bidder participation is not represented",
        "No customer-facing outcome analytics are enabled",
    ):
        assert required in section, required
    for claim in ("sell-through rate is", "% of properties sell", "win rate is"):
        assert claim not in section.lower()


# ==================== LIVE: apply to an isolated scratch database ====================


def _psql_prefix() -> list[str] | None:
    """How to reach a LOCAL psql, or None to skip. TDW_SCRATCH_PG overrides
    (e.g. 'psql -h localhost -U postgres'). Never a Supabase DSN."""
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
    db = f"tdw_mig014_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    try:
        for path in (FIXTURE, MIGRATION):
            r = _run(prefix, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(path), db=db)
            assert r.returncode == 0, f"{path.name} failed to apply:\n{r.stderr}"

        def run(sql: str) -> str:
            r = _run(prefix, "-v", "ON_ERROR_STOP=0", "-At", db=db, stdin=sql)
            return (r.stdout or "") + (r.stderr or "")

        yield run
    finally:
        _run(prefix, "-Atc", f"drop database if exists {db}", db="postgres")


def test_l01_tables_exist_and_are_empty(scratch):
    out = scratch("select (select count(*) from public.auction_events) || '/' || (select count(*) from public.auction_event_observations);")
    assert out.strip() == "0/0"


def test_l02_live_constraints_match_file(scratch):
    out = scratch("select conname from pg_constraint where conrelid::regclass::text like 'auction_event%' order by 1;")
    names = set(out.split())
    for expected in (
        "auction_events_property_sale_date_key", "auction_events_lifecycle_check", "auction_events_outcome_check",
        "auction_events_event_url_kind_check", "auction_events_property_id_fkey",
        "auction_event_observations_event_observed_key", "auction_event_observations_event_id_fkey",
        "auction_event_observations_lifecycle_check", "auction_event_observations_outcome_check",
    ):
        assert expected in names, expected
    out = scratch("select confdeltype from pg_constraint where conname in ('auction_events_property_id_fkey','auction_event_observations_event_id_fkey');")
    assert out.split() == ["r", "r"]  # r = RESTRICT


def test_l03_rls_policies_and_grants(scratch):
    out = scratch("select tablename||':'||rowsecurity from pg_tables where tablename like 'auction_event%' order by 1;")
    assert out.split() == ["auction_event_observations:true", "auction_events:true"]
    out = scratch("select tablename||':'||permissive||':'||cmd||':'||array_to_string(roles,',')||':'||qual from pg_policies where tablename like 'auction_event%' order by 1;")
    assert out.split() == [
        "auction_event_observations:PERMISSIVE:SELECT:authenticated:is_approved()",
        "auction_events:PERMISSIVE:SELECT:authenticated:is_approved()",
    ]
    out = scratch("select grantee||':'||table_name||':'||string_agg(privilege_type, ',' order by privilege_type) from information_schema.table_privileges where table_name like 'auction_event%' and grantee in ('anon','authenticated','service_role','PUBLIC') group by grantee, table_name order by grantee, table_name;")
    assert out.split() == [
        "authenticated:auction_event_observations:SELECT",
        "authenticated:auction_events:SELECT",
        "service_role:auction_event_observations:DELETE,INSERT,SELECT,UPDATE",
        "service_role:auction_events:DELETE,INSERT,SELECT,UPDATE",
    ]


def test_l04_event_identity_and_relisting(scratch):
    out = scratch("""
      insert into public.properties (id, state, source, county, case_no) values ('11111111-1111-1111-1111-111111111111','FL','auction','Lee','2026000001');
      insert into public.auction_events (property_id, state, source, county, case_no, scheduled_sale_date) values ('11111111-1111-1111-1111-111111111111','FL','auction','Lee','2026000001','2026-10-06');
      insert into public.auction_events (property_id, state, source, county, case_no, scheduled_sale_date) values ('11111111-1111-1111-1111-111111111111','FL','auction','Lee','2026000001','2026-10-06');
      insert into public.auction_events (property_id, state, source, county, case_no, scheduled_sale_date) values ('11111111-1111-1111-1111-111111111111','FL','auction','Lee','2026000001','2026-11-03');
      select count(*)||' events; defaults '||string_agg(distinct lifecycle||'/'||outcome, ',') from public.auction_events;
    """)
    assert 'violates unique constraint "auction_events_property_sale_date_key"' in out
    assert "2 events; defaults scheduled/unknown" in out


def test_l05_vocabulary_checks_reject_property_status_words(scratch):
    for column, value in (("lifecycle", "left_feed"), ("lifecycle", "active"), ("outcome", "closed"), ("outcome", "left_feed"), ("event_url_kind", "homepage")):
        out = scratch(f"update public.auction_events set {column} = '{value}' where scheduled_sale_date = '2026-11-03';")
        assert "violates check constraint" in out, (column, value)
    out = scratch("update public.auction_events set bid_count = -1 where scheduled_sale_date = '2026-11-03';")
    assert "violates check constraint" in out
    out = scratch("update public.auction_events set lifecycle = 'superseded', outcome = 'unknown' where scheduled_sale_date = '2026-10-06'; select lifecycle||'/'||(updated_at >= created_at) from public.auction_events where scheduled_sale_date = '2026-10-06';")
    assert "superseded/t" in out


def test_l06_fk_restrict_protects_history(scratch):
    out = scratch("delete from public.properties where id = '11111111-1111-1111-1111-111111111111';")
    assert 'violates foreign key constraint "auction_events_property_id_fkey"' in out
    out = scratch("""
      insert into public.auction_event_observations (event_id, observed_at, feed, raw_status, lifecycle) select id, '2026-09-25 10:00:00+00', 'waiting', 'Auctions Waiting', 'scheduled' from public.auction_events where scheduled_sale_date = '2026-10-06';
      insert into public.auction_event_observations (event_id, observed_at, feed, raw_status, lifecycle) select id, '2026-09-25 10:00:00+00', 'waiting', 'duplicate instant', 'scheduled' from public.auction_events where scheduled_sale_date = '2026-10-06';
      insert into public.auction_event_observations (event_id, observed_at, feed, raw_status, lifecycle) select id, '2026-09-25 10:00:00.000001+00', 'waiting', 'next microsecond', 'scheduled' from public.auction_events where scheduled_sale_date = '2026-10-06';
      delete from public.auction_events where scheduled_sale_date = '2026-10-06';
      select count(*) from public.auction_event_observations;
    """)
    assert 'violates unique constraint "auction_event_observations_event_observed_key"' in out
    assert 'violates foreign key constraint "auction_event_observations_event_id_fkey"' in out
    # stdout and stderr are concatenated; the count is the only bare number line.
    assert re.search(r"^2$", out, re.M), out


def test_l07_clients_read_only_when_approved_and_never_write(scratch):
    out = scratch("""
      insert into public.profiles (id, approved) values ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', true), ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', false);
      set role authenticated;
      select set_config('request.jwt.claims', '{"sub":"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","role":"authenticated"}', false);
      select 'approved_events='||count(*) from public.auction_events;
      select 'approved_obs='||count(*) from public.auction_event_observations;
      insert into public.auction_events (property_id, state, source, county, case_no, scheduled_sale_date) values ('11111111-1111-1111-1111-111111111111','FL','auction','Lee','x','2027-01-01');
      update public.auction_events set outcome = 'sold';
      delete from public.auction_event_observations;
      select set_config('request.jwt.claims', '{"sub":"bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb","role":"authenticated"}', false);
      select 'unapproved_events='||count(*) from public.auction_events;
      reset role;
      set role anon;
      select 'anon='||count(*) from public.auction_events;
      reset role;
    """)
    assert "approved_events=2" in out
    assert "approved_obs=2" in out
    assert out.count("permission denied for table auction_events") == 3  # insert, update, anon select
    assert "permission denied for table auction_event_observations" in out  # delete
    assert "unapproved_events=0" in out


def test_l08_service_role_is_the_future_writer(scratch):
    out = scratch("""
      set role service_role;
      insert into public.auction_events (property_id, state, source, county, case_no, scheduled_sale_date) values ('11111111-1111-1111-1111-111111111111','FL','auction','Lee','2026000001','2026-12-01');
      insert into public.auction_event_observations (event_id, feed, lifecycle) select id, 'waiting', 'scheduled' from public.auction_events where scheduled_sale_date = '2026-12-01';
      select 'svc_events='||count(*) from public.auction_events;
      reset role;
    """)
    assert "permission denied" not in out
    assert "svc_events=3" in out


def test_l09_reversible_drop_leaves_properties_intact(scratch):
    out = scratch("""
      drop table public.auction_event_observations;
      drop table public.auction_events;
      select 'props='||(select count(*) from public.properties)||' left='||(select count(*) from pg_tables where tablename like 'auction_event%');
    """)
    assert "props=1 left=0" in out
