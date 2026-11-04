"""Migration 028 (2026-10-05): the list payload and the detail provenance read.

STATIC: get_properties_list() returns migration 025's columns in the same
order plus provenance_scope, sorts the same narrow keys the same way, keeps
STABLE / search_path / SECURITY INVOKER, and only slims otc_provenance /
field_provenance; get_property_provenance() returns the full pair; nothing is
dropped, revoked or altered; 025 / 026 / get_properties() are untouched. The
key lists agree across the SQL, the test stub and app.js.

LIVE (local PostgreSQL only, skipped otherwise): on the migration-026
production-shaped scratch schema with 025 + 026 + 028 applied:
  - every page of get_properties_list() holds exactly the rows, in exactly
    the order, of get_properties() - for every role (RLS unchanged);
  - every non-provenance column is identical;
  - purchase_instructions and the harvest internals are gone from the list,
    every other otc key (acquisition record included) is kept, field
    provenance is reduced to the review markers, and the payload is smaller;
  - get_property_provenance() returns the full, unchanged pair, and only to a
    role the properties policy lets read the row;
  - the migration is idempotent.
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MIG = REPO / "scripts" / "migrations"
M028 = MIG / "028_property_list_payload.sql"
M025 = MIG / "025_get_properties_narrow_sort.sql"
M026 = MIG / "026_properties_rls_initplan_and_page_index.sql"
FIXTURE = REPO / "tests" / "python" / "fixtures" / "migration_026_scratch_fixture.sql"
STUB = (REPO / "tests" / "vendor" / "supabase-stub.js").read_text(encoding="utf-8")
APP = (REPO / "public" / "app.js").read_text(encoding="utf-8")
SQL = M028.read_text(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_migration_016_source_health import _psql_prefix, _run  # noqa: E402

USERS = {"admin": "11111111-1111-1111-1111-111111111111", "customer": "22222222-2222-2222-2222-222222222222",
         "pending": "33333333-3333-3333-3333-333333333333", "unknown": "44444444-4444-4444-4444-444444444444"}


def code(sql: str) -> str:
    return "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))


def returned(sql: str, fn: str) -> list[str]:
    body = re.search(rf"function public\.{fn}\(.*?returns table\((.*?)\)\nlanguage", sql, re.S).group(1)
    return [c.strip().split(" ")[0] for c in body.split(",\n")]


def dropped_keys_sql() -> list[str]:
    arr = re.search(r"then p\.otc_provenance - array\[(.*?)\]", SQL, re.S).group(1)
    return re.findall(r"'([a-z_]+)'", arr)


# ==================== STATIC ====================

def test_s01_list_columns_are_025_columns_plus_provenance_scope():
    cols025 = returned(M025.read_text(encoding="utf-8"), "get_properties")
    assert returned(SQL, "get_properties_list") == cols025 + ["provenance_scope"]
    assert len(cols025) == 105


def test_s02_same_sort_paging_volatility_security():
    body = code(SQL)
    fn = body.split("create or replace function public.get_property_provenance")[0]
    assert "p_limit integer default 20000" in fn and "p_offset integer default 0" in fn
    assert "order by county, case_no, id\n    limit p_limit\n    offset p_offset" in fn
    assert "join public.properties p on p.id = page.pid" in fn
    assert fn.rstrip().endswith("order by page.k_county, page.k_case, page.pid;\n$function$;")
    assert body.count("\nstable\n") == 2 and body.count("set search_path to 'public'") == 2
    assert "security definer" not in body.lower()


def test_s03_only_provenance_columns_are_reshaped():
    sel = re.search(r"\n  select\n(.*?)\n  from page", SQL, re.S).group(1)
    plain = [l.strip().rstrip(",") for l in sel.splitlines() if re.fullmatch(r"\s*p\.[a-z_]+,?", l)]
    cols = returned(SQL, "get_properties_list")
    expect = [f"p.{c}" for c in cols if c not in ("otc_provenance", "field_provenance", "provenance_scope")]
    assert plain == expect


def test_s04_adds_two_functions_and_changes_nothing_else():
    body = code(SQL).lower()
    assert re.findall(r"create or replace function public\.(\w+)", body) == ["get_properties_list", "get_property_provenance"]
    for word in ("drop ", "revoke", "alter ", "delete ", "update ", "insert ", "truncate", "create policy", "create index",
                 "get_properties(", "disable row level security"):
        assert word not in body, word
    grants = re.findall(r"grant execute on function public\.(\w+)\(([^)]*)\) to ([^;]+);", body)
    assert grants == [("get_properties_list", "text, text, text, integer, integer", "anon, authenticated, service_role"),
                      ("get_property_provenance", "uuid", "anon, authenticated, service_role")]


def test_s05_detail_function_returns_the_full_pair_unmodified():
    fn = SQL.split("create or replace function public.get_property_provenance")[1]
    assert "returns table(id uuid, otc_provenance jsonb, field_provenance jsonb)" in fn
    assert "select p.id, p.otc_provenance, p.field_provenance" in fn and "where p.id = p_id" in fn


def test_s06_025_and_026_are_unchanged():
    # 025 / 026 are applied in production: their files must not be edited.
    assert "get_properties_list" not in M025.read_text(encoding="utf-8")
    assert "get_properties_list" not in M026.read_text(encoding="utf-8")


def test_s07_key_lists_agree_across_sql_stub_and_app():
    stub_dropped = json.loads(re.search(r"const LIST_OTC_DROPPED_KEYS = (\[.*?\]);", STUB).group(1))
    assert dropped_keys_sql() == stub_dropped
    # Every dropped key is one no list surface reads: the frontend reads only
    # purchase_instructions, and only through acquisitionProvenance(), which
    # refills it from the identical county record.
    for k in stub_dropped:
        if k == "purchase_instructions":
            continue
        for js in ("app.js", "explore.js", "satellite-map.js"):
            text = (REPO / "public" / js).read_text(encoding="utf-8")
            assert not re.search(rf"\.{k}\b|\[\"{k}\"\]", text), (k, js)
    # what list cards, exports and the acquisition block read is kept
    for kept in ("acquisition", "source_match", "purchase_evidence_url", "purchase_statement", "amount", "auction_process"):
        assert kept not in stub_dropped
    assert "rec.purchase_instructions && (rec.purchase_evidence_url || \"\") === (op.purchase_evidence_url || \"\")" in APP
    review_sql = re.findall(r"'(tx_[a-z_]+)'", re.search(r"->> 'source_id' in \((.*?)\)\)", SQL).group(1))
    review_stub = json.loads(re.search(r"const LIST_REVIEW_SOURCE_IDS = (\[.*?\]);", STUB).group(1))
    review_app = re.findall(r"^\s+(tx_[a-z_]+):", re.search(r"const REVIEW_REQUIRED_SOURCES = \{(.*?)\};", APP, re.S).group(1), re.M)
    assert review_sql == review_stub == review_app


def test_s08_frontend_reads_the_list_rpc_with_fallback_and_lazy_detail():
    assert 'var LIST_RPC = "get_properties_list";' in APP
    assert 'LIST_RPC = "get_properties";' in APP                         # PGRST202 fallback until 028 is applied
    assert 'sb.rpc("get_property_provenance", { p_id: p.id })' in APP
    assert 'p.provenance_scope === "list"' in APP


# ==================== LIVE ====================

EXTRA = """
-- rows shaped like production Available rows: a county acquisition record,
-- purchase instructions, a full source_match and a governance entry.
insert into public.properties (source, ledger_type, state, county, case_no, parcel, address, status,
  field_provenance, otc_provenance, publication_status, updated_at)
select 'laft', 'buy', 'LA', 'East Baton Rouge', 'Z' || lpad(g::text, 6, '0'), 'Z' || g, null, 'active',
  jsonb_build_object(
    'land_use', jsonb_build_object('source', 'statewide_parcel', 'source_id', 'la_ebr_tax_roll', 'evidence', repeat('r', 300)),
    'address', jsonb_build_object('source', 'county_list', 'source_id', 'tx_lgbs', 'governance', 'REVIEW_REQUIRED', 'evidence', repeat('g', 200))),
  jsonb_build_object('source_id', 'la_ebr_adjudicated', 'list_url', 'https://example.test/list', 'amount', null,
    'purchase_path_mode', 'application', 'purchase_evidence_url', 'https://example.test/process',
    'purchase_evidence_title', 'Process', 'purchase_evidence_type', 'html',
    'purchase_instructions', repeat('Submit the form. ', 90),
    'acquisition', jsonb_build_object('mode', 'application', 'steps', jsonb_build_array(repeat('s', 400), repeat('t', 400)), 'office', 'Office'),
    'source_match', jsonb_build_object('identifier', 'assessment_num', 'value', 'Z' || g, 'method', 'exact', 'note', repeat('n', 120))),
  'APPROVED', now()
from generate_series(1, 1500) g;
vacuum analyze public.properties;
"""


@pytest.fixture(scope="module")
def scratch():
    prefix = _psql_prefix()
    if prefix is None:
        pytest.skip("no local PostgreSQL reachable - live migration layer skipped (static layer still ran)")
    db = f"tdw_mig028_{uuid.uuid4().hex[:8]}"
    assert _run(prefix, "-Atc", f"create database {db}", db="postgres").returncode == 0
    staged = []

    def stage(text: str, name: str) -> str:
        copy = Path("/tmp") / f"{db}_{len(staged)}_{name}"
        copy.write_text(text, encoding="utf-8")
        copy.chmod(0o644)
        staged.append(copy)
        return str(copy)

    def apply(path: Path | None = None, text: str | None = None):
        r = _run(prefix, "-v", "ON_ERROR_STOP=1", "-q", "-f",
                 stage(text if text is not None else path.read_text(encoding="utf-8"), path.name if path else "extra.sql"), db=db)
        assert r.returncode == 0, f"apply failed:\n{r.stderr}"

    def run(sql):
        r = _run(prefix, "-v", "ON_ERROR_STOP=0", "-Atq", db=db, stdin=sql)
        return (r.stdout or "") + (r.stderr or "")

    try:
        apply(FIXTURE)
        apply(M025)
        apply(M026)
        apply(text=EXTRA)
        apply(M028)
        yield run, apply
    finally:
        _run(prefix, "-Atc", f"drop database if exists {db}", db="postgres")
        for c in staged:
            c.unlink(missing_ok=True)


def as_role(label: str, sql: str) -> str:
    if label == "anon":
        return f"reset role; set role anon; reset request.jwt.claims;\n{sql}"
    if label == "service_role":
        return f"reset role; set role service_role;\n{sql}"
    claims = '{"sub":"%s","role":"authenticated"}' % USERS[label]
    return f"reset role; set role authenticated; set request.jwt.claims = '{claims}';\n{sql}"


def pages(fn: str, state: str, ledger: str, cols: str = "id") -> str:
    return (f"select string_agg(x, ',' order by pg, ord) from (select o.pg, t.ord, t.x from generate_series(0, 3) o(pg) "
            f"cross join lateral (select row_number() over () ord, ({cols})::text x from {fn}('{state}', '{ledger}', null, 1000, o.pg * 1000) g) t) y;")


@pytest.mark.parametrize("state,ledger", [("LA", "buy"), ("MI", "buy"), ("FL", "auctions"), ("FL", "lien"), ("TX", "buy")])
@pytest.mark.parametrize("role", ["admin", "customer", "pending", "unknown", "anon", "service_role"])
def test_l01_pages_rows_order_identical_for_every_role(scratch, role, state, ledger):
    run, _ = scratch
    full = run(as_role(role, pages("get_properties", state, ledger)))
    lst = run(as_role(role, pages("get_properties_list", state, ledger)))
    assert full == lst
    if role in ("pending", "unknown", "anon"):
        assert full.strip() == ""                                           # RLS still hides everything
    else:
        assert full.count(",") >= 100


def test_l02_every_non_provenance_column_identical(scratch):
    run, _ = scratch
    out = run(as_role("customer", """
      select count(*) filter (where (to_jsonb(f) - 'otc_provenance' - 'field_provenance')
                                 is distinct from (to_jsonb(l) - 'otc_provenance' - 'field_provenance' - 'provenance_scope')),
             count(*), bool_and(l.provenance_scope = 'list')
      from get_properties('LA', 'buy', null, 5000, 0) f join get_properties_list('LA', 'buy', null, 5000, 0) l using (id);"""))
    mismatched, total, scoped = out.strip().split("|")
    assert mismatched == "0" and int(total) == 2600 and scoped == "t"


def test_l03_heavy_keys_gone_list_keys_kept_payload_smaller(scratch):
    run, _ = scratch
    out = run(as_role("customer", """
      select l.otc_provenance::text, l.field_provenance::text from get_properties_list('LA', 'buy', null, 5000, 0) l
      where l.case_no = 'Z000007';"""))
    otc, fp = out.strip().split("|")
    otc, fp = json.loads(otc), json.loads(fp)
    assert "purchase_instructions" not in otc
    assert otc["acquisition"]["mode"] == "application" and len(otc["acquisition"]["steps"]) == 2   # kept whole
    assert otc["purchase_path_mode"] == "application" and otc["purchase_evidence_url"] == "https://example.test/process"
    assert otc["source_match"]["value"] == "Z7" and otc["source_match"]["method"] == "exact"
    assert "amount" in otc and otc["amount"] is None                         # a stated null is kept, not dropped
    assert fp == {"address": {"source": "county_list", "source_id": "tx_lgbs", "governance": "REVIEW_REQUIRED"}}
    sizes = run(as_role("customer", """
      select (select sum(length(to_jsonb(g)::text)) from get_properties('LA', 'buy', null, 5000, 0) g where g.case_no like 'Z%'),
             (select sum(length(to_jsonb(g)::text)) from get_properties_list('LA', 'buy', null, 5000, 0) g where g.case_no like 'Z%');"""))
    full, slim = map(int, sizes.strip().split("|"))
    assert slim < full * 0.75


def test_l04_detail_returns_full_pair_only_where_rls_allows(scratch):
    run, _ = scratch
    pid = run("select id from public.properties where case_no = 'Z000007';").strip()
    stored = run(f"select otc_provenance::text || '|' || field_provenance::text from public.properties where id = '{pid}';").strip()
    got = run(as_role("customer", f"select otc_provenance::text || '|' || field_provenance::text from get_property_provenance('{pid}');")).strip()
    assert got == stored and "purchase_instructions" in got and "acquisition" in got
    for role in ("pending", "unknown", "anon"):
        assert run(as_role(role, f"select count(*) from get_property_provenance('{pid}');")).strip() == "0"


def test_l05_idempotent_and_get_properties_unchanged(scratch):
    run, apply = scratch
    before = run("select md5(pg_get_functiondef('public.get_properties(text,text,text,integer,integer)'::regprocedure));")
    apply(M028)
    apply(M028)
    assert run("select md5(pg_get_functiondef('public.get_properties(text,text,text,integer,integer)'::regprocedure));") == before
    assert run("select count(*) from pg_proc where proname in ('get_properties_list', 'get_property_provenance');").strip() == "2"
