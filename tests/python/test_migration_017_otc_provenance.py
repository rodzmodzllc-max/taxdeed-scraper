"""Migration 017 (OTC inventory / provenance / lifecycle columns) and 018
(county source registry table).

STATIC: the SQL adds only nullable columns and constraints, re-creates
get_properties() from 013's exact signature with the new columns appended,
re-pins search_path, backfills by deterministic rules only, and contains
no destructive statement.

LIVE (local PostgreSQL only, skipped otherwise): the fixture reproducing
the live properties table + 017 + 018 apply verbatim; the backfill lands
exactly as documented; the constraints reject the dishonest shapes; the
lifecycle's own writes (last_seen_at, close-out, reactivation) behave with
migration 006's trigger; approved users read the new columns through the
RPC, pending users read nothing; 018's table takes the whole registry CSV
under service_role and refuses client writes.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
M017 = REPO / "scripts/migrations/017_otc_inventory_provenance_lifecycle.sql"
M018 = REPO / "scripts/migrations/018_county_source_registry.sql"
FIXTURE = REPO / "tests/python/fixtures/migration_017_scratch_fixture.sql"
SQL17 = M017.read_text(encoding="utf-8")
SQL18 = M018.read_text(encoding="utf-8")
sys.path.insert(0, str(REPO / "scripts"))
import laft_lifecycle as L  # noqa: E402
from harvesters.governance.county_source_registry import load_registry, to_db_rows  # noqa: E402

NEW_COLUMNS = ["inventory_type", "source_authority", "source_id", "list_url", "document_url", "purchase_url", "purchase_url_kind",
               "purchase_amount", "purchase_amount_kind", "first_seen_at", "last_seen_at", "delisted_at", "source_published_at",
               "list_as_of", "source_document_sha256", "source_etag", "source_last_modified", "otc_provenance"]


def sql_only(sql: str) -> str:
    return "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))


# ==================== STATIC ====================


def test_s01_adds_exactly_the_documented_nullable_columns_and_nothing_destructive():
    body = sql_only(SQL17).lower()
    for col in NEW_COLUMNS:
        assert re.search(rf"add column if not exists {col} ", body), col
    assert body.count("add column if not exists") == len(NEW_COLUMNS)
    for forbidden in ("drop column", "drop table", "truncate", "delete from", "alter column bid", "drop not null", "set not null"):
        assert forbidden not in body, forbidden
    assert "drop function if exists public.get_properties(text, text, text, integer, integer)" in body
    assert body.count("drop function") == 1 and body.count("drop constraint if exists") == body.count("add constraint")
    assert body.strip().startswith("begin;") and body.strip().endswith("commit;")
    assert set(L.MIGRATION_017_COLUMNS) < set(NEW_COLUMNS)


def test_s02_first_seen_default_added_after_the_column_so_existing_rows_stay_null():
    body = sql_only(SQL17).lower()
    assert "add column if not exists first_seen_at timestamptz," in body
    assert "alter column first_seen_at set default now()" in body
    assert "first_seen_at timestamptz default" not in body and "first_seen_at timestamptz not null" not in body


def test_s03_constraints_encode_the_amount_and_url_semantics():
    body = sql_only(SQL17).lower()
    assert "purchase_amount_kind = 'not_published'" in body and "purchase_amount_kind <> 'not_published'" in body
    assert "(purchase_url is null) = (purchase_url_kind is null)" in body
    assert "purchase_amount >= 0" in body
    assert "last_seen_at >= first_seen_at" in body


def test_s04_get_properties_keeps_013s_signature_and_appends_the_customer_columns():
    body = SQL17
    sig = "create function public.get_properties(\n  p_state text,\n  p_ledger_type text default null,\n  p_status text default null,\n  p_limit integer default 20000,\n  p_offset integer default 0\n)"
    assert sig in body
    m013 = (REPO / "scripts/migrations/013_auction_link_kind_and_tx_sale_status.sql").read_text(encoding="utf-8")
    def cols(sql):
        seg = sql[sql.index("returns table (") + len("returns table ("):sql.index("\n)\nlanguage sql")]
        return "\n".join(l for l in seg.splitlines() if not l.strip().startswith("--")).strip()
    old_cols, new_cols = cols(m013), cols(body)
    assert new_cols.startswith(old_cols), "013's column list must be the untouched prefix"
    for col in ("inventory_type", "source_authority", "source_id", "list_url", "document_url", "purchase_url", "purchase_url_kind",
                "purchase_amount", "purchase_amount_kind", "first_seen_at", "last_seen_at", "delisted_at", "source_published_at", "list_as_of"):
        assert f" {col} " in new_cols or f"  {col} " in new_cols, col
    for evidence_only in ("source_document_sha256", "source_etag", "source_last_modified", "otc_provenance"):
        assert evidence_only not in new_cols
    assert "where state = p_state\n    and (p_ledger_type is null or ledger_type = p_ledger_type)\n    and (p_status is null or status = p_status)\n  order by county, case_no\n  limit p_limit\n  offset p_offset;" in body
    assert "alter function public.get_properties(text, text, text, integer, integer) set search_path = public;" in body
    assert "grant execute on function public.get_properties(text, text, text, integer, integer)\n  to anon, authenticated, service_role;" in body


def test_s05_backfill_rules_are_the_documented_ones_only():
    body = sql_only(SQL17)
    assert "when 'Struck off to Jurisdiction' then 'STRUCK_OFF_HELD_IN_TRUST'" in body
    assert "when 'Available for Future Sale' then 'FUTURE_RESALE'" in body
    assert "case when bid > 0 then bid else null end" in body
    assert "when bid > 0 then 'PUBLISHED_AMOUNT_KIND_UNSPECIFIED' else 'NOT_PUBLISHED' end" in body
    assert "purchase_amount      = case when bid > 0" in body and body.count("set purchase_amount ") == 1
    # The purchase_amount backfill is Florida-only.
    seg = body[body.index("set purchase_amount "):]
    assert "where state = 'FL' and source = 'laft' and purchase_amount_kind is null" in seg[:400]
    assert "lgbs.com" not in body and "sheriffsaleauctions" not in body
    assert "coalesce(p.inventory_type, 'POST_SALE_FIXED_PRICE')" in body


def test_s06_migration_018_shape_and_posture():
    body = sql_only(SQL18).lower()
    assert body.count("create table") == 1 and "create table public.county_source_registry" in body
    assert "enable row level security" in body and "using (public.is_approved())" in body
    assert "revoke all on public.county_source_registry from anon, public" in body
    assert "grant select, insert, update, delete on public.county_source_registry to service_role" in body
    assert "governance_status <> 'blocked' or canonical_url is null" in body
    assert "insert into" not in body and "properties" not in body.replace("no property data", "")


def test_s07_docs_and_config_list_017_and_018_as_unapplied():
    cfg = (REPO / "docs/production-configuration.md").read_text(encoding="utf-8")
    assert "017_otc_inventory_provenance_lifecycle.sql" in cfg and "018_county_source_registry.sql" in cfg
    model = (REPO / "docs/otc-inventory-model.md").read_text(encoding="utf-8")
    assert "NOT APPLIED" in model.upper() or "not applied" in model


# ==================== LIVE ====================


def _psql_prefix():
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


def _run(prefix, *args, db, timeout=120, stdin=None):
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
    db = f"tdw_mig017_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    staged = []
    try:
        for path in (FIXTURE, M017, M018):
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
USER_PENDING = "33333333-3333-3333-3333-333333333333"


def _cols(scratch, where):
    out = scratch(f"select coalesce(inventory_type,'-')||'|'||coalesce(source_authority,'-')||'|'||coalesce(source_id,'-')||'|'||coalesce(purchase_amount::text,'-')||'|'||coalesce(purchase_amount_kind,'-')||'|'||coalesce(list_url,'-')||'|'||coalesce(document_url,'-')||'|'||coalesce(first_seen_at::text,'-') from public.properties where {where};")
    return out.strip().split("|")


def test_l01_backfill_lands_exactly_as_documented(scratch):
    assert _cols(scratch, "county='Marion'") == ["POST_SALE_FIXED_PRICE", "GOVERNMENT_DIRECT", "fl_laft_pdfs", "-", "NOT_PUBLISHED",
        "https://www.marioncountyclerk.org/departments/records-recording/tax-deeds-and-lands-available-for-taxes/land-available-for-taxes-information/",
        "https://www.marioncountyclerk.org/uploads/2026/07/LAT-List-updated3.13.2026-1.pdf", "-"]
    assert _cols(scratch, "county='Putnam'")[:5] == ["POST_SALE_FIXED_PRICE", "GOVERNMENT_DIRECT", "fl_laft_html", "1234.56", "PUBLISHED_AMOUNT_KIND_UNSPECIFIED"]
    assert _cols(scratch, "county='Nowhere'") == ["POST_SALE_FIXED_PRICE", "-", "-", "-", "NOT_PUBLISHED", "-", "-", "-"]
    assert _cols(scratch, "county='Galveston'") == ["STRUCK_OFF_HELD_IN_TRUST", "VENDOR_COUNSEL", "tx_lgbs", "-", "-", "-", "-", "-"]
    assert _cols(scratch, "county='Liberty'") == ["-", "VENDOR_COUNSEL", "tx_lgbs", "-", "-", "-", "-", "-"]   # raw status NULL -> unresolved
    assert _cols(scratch, "county='Hardin'")[0] == "FUTURE_RESALE"
    assert _cols(scratch, "county='Dallas'")[1:3] == ["VENDOR_AUCTION", "tx_realauction"]
    assert _cols(scratch, "county='Concho'")[1:3] == ["VENDOR_COUNSEL", "tx_lgbs"]
    assert _cols(scratch, "county='Alachua'")[1:3] == ["VENDOR_AUCTION", "fl_realauction"]
    assert _cols(scratch, "county='Bay'")[1:3] == ["VENDOR_AUCTION", "fl_lienhub_certificates"]
    # No row was given a URL, a date or a purchase URL it did not have.
    assert scratch("select count(*) from public.properties where purchase_url is not null or list_as_of is not null or source_published_at is not null or last_seen_at is not null;").strip() == "0"
    assert scratch("select count(*) from public.properties where state='TX' and (list_url is not null or document_url is not null or purchase_amount is not null);").strip() == "0"
    # bid untouched.
    assert scratch("select bid from public.properties where county='Marion';").strip() == "0"
    assert scratch("select count(*) from public.properties where first_seen_at is not null;").strip() == "0"


def test_l02_constraints_reject_the_dishonest_shapes(scratch):
    out = scratch("""set role service_role;
      insert into public.properties (state,source,county,case_no,purchase_amount,purchase_amount_kind) values ('FL','laft','Z','Z1',5,'NOT_PUBLISHED');
      insert into public.properties (state,source,county,case_no,purchase_amount,purchase_amount_kind) values ('FL','laft','Z','Z2',5,null);
      insert into public.properties (state,source,county,case_no,purchase_amount,purchase_amount_kind) values ('FL','laft','Z','Z3',null,'OPENING_BID');
      insert into public.properties (state,source,county,case_no,purchase_amount,purchase_amount_kind) values ('FL','laft','Z','Z4',-1,'OPENING_BID');
      insert into public.properties (state,source,county,case_no,inventory_type) values ('FL','laft','Z','Z5','MAYBE');
      insert into public.properties (state,source,county,case_no,source_authority) values ('FL','laft','Z','Z6','SEARCH_ENGINE');
      insert into public.properties (state,source,county,case_no,purchase_url) values ('FL','laft','Z','Z7','https://x');
      insert into public.properties (state,source,county,case_no,purchase_url_kind) values ('FL','laft','Z','Z8','offer_form');
      insert into public.properties (state,source,county,case_no,first_seen_at,last_seen_at) values ('FL','laft','Z','Z9',now(),now()-interval '1 day');
      select count(*) from public.properties where county='Z';""")
    assert out.count("violates check constraint") == 9 and out.strip().splitlines()[0] == "0"  # stdout precedes stderr
    out = scratch("""set role service_role;
      insert into public.properties (state,source,county,case_no,purchase_amount,purchase_amount_kind,purchase_url,purchase_url_kind) values ('FL','laft','Z','OK',5,'OPENING_BID','https://x/form','offer_form');
      select purchase_amount_kind||':'||(first_seen_at is not null)::text from public.properties where county='Z';
      delete from public.properties where county='Z';""")
    assert "OPENING_BID:true" in out   # new rows get first_seen_at by default


def test_l03_lifecycle_writes_interact_correctly_with_the_gone_since_trigger(scratch):
    out = scratch("""set role service_role;
      update public.properties set status='closed', delisted_at=now() where county='Marion';
      select (gone_since is not null)::text||':'||(delisted_at is not null)::text from public.properties where county='Marion';
      update public.properties set status='active', last_seen_at=now() where county='Marion';
      select (gone_since is null)::text||':'||(last_seen_at is not null)::text from public.properties where county='Marion';""")
    assert out.split() == ["true:true", "true:true"]


def test_l04_rpc_exposes_the_new_columns_to_approved_users_only(scratch):
    out = scratch(f"""set role authenticated; set request.jwt.claims = '{{"sub":"{USER_A}","role":"authenticated"}}';
      select county||':'||coalesce(inventory_type,'-')||':'||coalesce(purchase_amount_kind,'-')||':'||coalesce(source_authority,'-') from public.get_properties('FL') order by 1;
      select count(*) from public.get_properties('TX');""")
    lines = out.split()
    assert "Marion:POST_SALE_FIXED_PRICE:NOT_PUBLISHED:GOVERNMENT_DIRECT" in lines and "Putnam:POST_SALE_FIXED_PRICE:PUBLISHED_AMOUNT_KIND_UNSPECIFIED:GOVERNMENT_DIRECT" in lines
    assert lines[-1] == "5"
    out = scratch(f"""set role authenticated; set request.jwt.claims = '{{"sub":"{USER_PENDING}","role":"authenticated"}}';
      select count(*) from public.get_properties('FL');""")
    assert out.strip() == "0"
    out = scratch(f"""set role authenticated; set request.jwt.claims = '{{"sub":"{USER_A}","role":"authenticated"}}';
      select otc_provenance from public.properties limit 1;""")
    assert "permission denied" in out   # evidence columns are not customer columns
    out = scratch("select proconfig from pg_proc where proname='get_properties';")
    assert "search_path=public" in out


def test_l05_migration_018_takes_the_whole_registry_and_refuses_client_writes(scratch):
    rows = to_db_rows(load_registry())
    cols = list(rows[0].keys())

    def lit(v):
        return "null" if v is None else "'" + str(v).replace("'", "''") + "'"
    values = ",\n".join("(" + ",".join(lit(r[c]) for c in cols) + ")" for r in rows)
    out = scratch(f"set role service_role;\ninsert into public.county_source_registry ({','.join(cols)}) values\n{values};\nselect count(*) from public.county_source_registry;")
    assert "ERROR" not in out, out[:600]
    assert out.strip().splitlines()[-1] == str(len(rows))
    out = scratch("""set role service_role;
      insert into public.county_source_registry (state,county,canonical_url,access_method,machine_format,verification_status,governance_status,last_checked,evidence_ref) values ('TX','Chambers','https://vendor/x.pdf','NONE','PDF','BLOCKED_VENDOR_ONLY','BLOCKED','2026-09-29','e');
      insert into public.county_source_registry (state,county,access_method,machine_format,verification_status,governance_status,last_checked,evidence_ref) values ('TX','Camp','UNKNOWN','HTML_TABLE','PRODUCTION_VERIFIED','APPROVED','2026-09-29','e');""")
    assert out.count("violates check constraint") == 2
    out = scratch(f"""set role authenticated; set request.jwt.claims = '{{"sub":"{USER_A}","role":"authenticated"}}';
      select count(*) from public.county_source_registry;
      update public.county_source_registry set notes='x';
      delete from public.county_source_registry;""")
    assert out.strip().splitlines()[0] == str(len(rows)) and out.count("permission denied for table county_source_registry") == 2
    out = scratch(f"""set role authenticated; set request.jwt.claims = '{{"sub":"{USER_PENDING}","role":"authenticated"}}';
      select count(*) from public.county_source_registry;""")
    assert out.strip() == "0"
    assert "permission denied" in scratch("set role anon; select count(*) from public.county_source_registry;")
