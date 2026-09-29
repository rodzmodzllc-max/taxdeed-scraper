"""Migration 019 (escheatment_date / available_date from the county Lands
Available list).

STATIC: adds exactly two nullable date columns, nothing destructive,
re-creates get_properties() from 017's exact column list with the two
appended, re-pins search_path, no backfill.

LIVE (local PostgreSQL only, skipped otherwise): fixture + 017 + 018 + 019
apply verbatim; approved users read the two columns through the RPC; the
lifecycle's fill-blank carry (scripts/laft_source_fields.py) lands exactly
as planned on the scratch table and never overwrites a value.
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
M017 = REPO / "scripts/migrations/017_otc_inventory_provenance_lifecycle.sql"
M018 = REPO / "scripts/migrations/018_county_source_registry.sql"
M019 = REPO / "scripts/migrations/019_laft_list_dates.sql"
FIXTURE = REPO / "tests/python/fixtures/migration_017_scratch_fixture.sql"
SQL17 = M017.read_text(encoding="utf-8")
SQL19 = M019.read_text(encoding="utf-8")
sys.path.insert(0, str(REPO / "scripts"))
import laft_source_fields as SF  # noqa: E402

from test_migration_017_otc_provenance import _psql_prefix, _run  # noqa: E402

NEW = ["escheatment_date", "available_date"]


def sql_only(sql: str) -> str:
    return "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))


def _rpc_columns(sql: str) -> list[str]:
    body = sql_only(sql)
    m = re.search(r"as \$function\$\s*select(.*?)from public\.properties", body, re.S)
    assert m, "get_properties select list not found"
    return [c.strip() for c in m.group(1).replace("\n", " ").split(",") if c.strip()]


# ==================== STATIC ====================


def test_s01_adds_exactly_two_nullable_date_columns_and_nothing_destructive():
    body = sql_only(SQL19).lower()
    for col in NEW:
        assert re.search(rf"add column if not exists {col} date", body), col
    assert body.count("add column if not exists") == 2
    for forbidden in ("drop column", "drop table", "truncate", "delete from", "update public.properties", "insert into", "set not null", "drop not null"):
        assert forbidden not in body, forbidden
    assert body.count("drop function if exists public.get_properties(text, text, text, integer, integer)") == 1
    assert "set search_path = public" in body
    assert body.strip().startswith("begin;") and "commit;" in body


def test_s02_rpc_projection_is_017s_list_with_the_two_columns_appended():
    assert _rpc_columns(SQL19) == _rpc_columns(SQL17) + NEW
    assert "grant select (escheatment_date, available_date) on public.properties to authenticated" in sql_only(SQL19)
    assert "grant execute on function public.get_properties(text, text, text, integer, integer)" in sql_only(SQL19)


def test_s03_source_fields_script_treats_them_as_optional_probed_columns():
    assert set(SF.OPTIONAL_COLUMNS) == set(NEW)
    src = (REPO / "scripts/laft_lifecycle.py").read_text(encoding="utf-8")
    assert "has_migration_019" in src and "migration 019 not applied" in src


def test_s04_docs_list_019_as_unapplied():
    cfg = (REPO / "docs/production-configuration.md").read_text(encoding="utf-8")
    assert "019_laft_list_dates.sql" in cfg
    model = (REPO / "docs/otc-inventory-model.md").read_text(encoding="utf-8")
    assert "019_laft_list_dates.sql" in model


# ==================== LIVE ====================


@pytest.fixture(scope="module")
def scratch():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no local PostgreSQL reachable - live migration layer skipped (static layer still ran)")
    db = f"tdw_mig019_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    staged = []
    try:
        for path in (FIXTURE, M017, M018, M019):
            copy = Path("/tmp") / f"{db}_{path.name}"
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


USER_A = "11111111-1111-1111-1111-111111111111"


def test_l01_columns_exist_nullable_and_rpc_projects_them_to_approved_users(scratch):
    out = scratch("select column_name||':'||data_type||':'||is_nullable from information_schema.columns "
                  "where table_schema='public' and table_name='properties' and column_name in ('escheatment_date','available_date') order by 1;")
    assert out.split() == ["available_date:date:YES", "escheatment_date:date:YES"]
    out = scratch(f"""
        begin;
        set local role authenticated;
        set local request.jwt.claims = '{{"sub":"{USER_A}","role":"authenticated"}}';
        select count(*) from public.get_properties('FL') where escheatment_date is null and available_date is null;
        rollback;""")
    assert out.strip().split("\n")[0].isdigit() and int(out.strip().split("\n")[0]) > 0


def test_l02_fill_blank_carry_lands_and_never_overwrites(scratch):
    scratch("update public.properties set escheatment_date = date '2028-01-01' where county='Marion' and case_no = (select min(case_no) from public.properties where county='Marion');")
    rows = json.loads(scratch("select coalesce(json_agg(json_build_object('id', id, 'county', county, 'case_no', case_no, 'legal_desc', legal_desc, "
                              "'owner_name', owner_name, 'assessed', assessed, 'certificate_no', certificate_no, 'homestead', homestead, "
                              "'escheatment_date', escheatment_date, 'available_date', available_date, 'field_provenance', field_provenance)), '[]') "
                              "from public.properties where county='Marion' and source='laft';").strip())
    assert rows, "fixture has Marion laft rows"
    observed = {"Marion": {r["case_no"]: {"county": "Marion", "case_no": r["case_no"], "escheatment_date": "07/01/2029",
                                          "available_date": "2026-09-01", "certificate_no": "C-1"} for r in rows}}
    updates, counters = SF.plan_source_fields(observed, rows, list(SF.ALL_COLUMNS))
    gate = {"harvester": "fl_laft_pdfs", "entry": {"source_id": "fl_laft_pdfs", "source_url": "https://m", "checked_at": "2026-09-29T00:00:00+00:00"}}
    for u in updates:
        body = SF.patch_body(u, gate, "2026-09-29T00:00:00+00:00")
        sets = ", ".join(f"{col} = {'$$' + json.dumps(v) + '$$::jsonb' if col == 'field_provenance' else repr(v)}" for col, v in body.items())
        scratch(f"update public.properties set {sets} where id = '{u.id}';")
    pre = [r for r in rows if r["escheatment_date"]]
    assert len(pre) == 1 and counters.skipped_present.get("escheatment_date") == 1
    out = scratch("select count(*) filter (where escheatment_date = date '2029-07-01'), count(*) filter (where escheatment_date = date '2028-01-01'), "
                  "count(*) filter (where available_date = date '2026-09-01'), count(*) filter (where field_provenance->'available_date'->>'source' = 'county_list') "
                  "from public.properties where county='Marion' and source='laft';")
    got = [int(x) for x in out.strip().split("|")]
    assert got == [len(rows) - 1, 1, len(rows), len(rows)]
