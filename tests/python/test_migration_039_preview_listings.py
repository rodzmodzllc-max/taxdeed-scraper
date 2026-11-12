"""Migration 039 (2026-11-12): the Free preview read for accounts awaiting approval.

STATIC: get_preview_listings() is SECURITY DEFINER with a pinned search_path,
returns only the safe columns (no address, parcel, case, owner, amount,
coordinates, photo, url or provenance), filters to customer-publishable rows,
caps the page at 60 rows, orders deterministically, and is executable by
authenticated callers only. The test stub's mirror returns the same columns.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL = (ROOT / "scripts" / "migrations" / "039_preview_listings.sql").read_text(encoding="utf-8")
STUB = (ROOT / "tests" / "vendor" / "supabase-stub.js").read_text(encoding="utf-8")
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")

SAFE_COLUMNS = ["preview_id", "state", "county", "ledger_type", "source", "source_id",
                "land_use", "dor_use_code", "acreage", "lot_sqft", "sale_month"]
FORBIDDEN = ["address", "parcel", "case_no", "certificate_no", "owner", "owner_name", "bid", "min_bid",
             "purchase_amount", "amount", "assessed", "market", "land_value", "taxable_value",
             "improvement_value", "last_sale_price", "prior_sale_price", "latitude", "longitude",
             "photo_url", "url", "url_auction", "url_appraiser", "url_taxcoll", "url_title",
             "list_url", "document_url", "purchase_url", "otc_provenance", "field_provenance",
             "provenance", "legal_desc", "interest_rate", "geom", "boundary"]


def code() -> str:
    """The SQL without comments, lower-cased, whitespace collapsed."""
    lines = [ln.split("--", 1)[0] for ln in SQL.splitlines()]
    return re.sub(r"\s+", " ", " ".join(lines)).lower().strip()


def returns_columns() -> list[str]:
    m = re.search(r"returns table\((.*?)\)\s*language", code())
    assert m, "RETURNS TABLE(...) not found"
    return [c.strip().split(" ")[0] for c in m.group(1).split(",")]


def select_list() -> str:
    m = re.search(r"as \$\$ select (.*?) from public\.properties p", code())
    assert m, "select list not found"
    return m.group(1)


def test_one_function_security_definer_with_pinned_search_path():
    c = code()
    assert c.count("create or replace function public.get_preview_listings(") == 1
    assert "p_state text, p_ledger_type text default null, p_limit integer default 60, p_offset integer default 0" in c
    assert "language sql stable security definer" in c
    assert "set search_path = public, pg_temp" in c
    assert "security invoker" not in c


def test_returns_only_the_safe_columns():
    assert returns_columns() == SAFE_COLUMNS


def test_no_forbidden_column_in_the_select_list_or_returns():
    sel = select_list()
    # every selected expression names its alias, or is p.<safe column>
    tokens = set(re.findall(r"p\.([a-z_]+)", sel))
    allowed_inputs = {"id", "state", "county", "ledger_type", "source", "source_id", "prop_type",
                      "land_use", "dor_use_code", "acreage", "lot_sqft", "sale_date"}
    assert tokens <= allowed_inputs, tokens - allowed_inputs
    for word in FORBIDDEN:
        assert not re.search(rf"\b{re.escape(word)}\b", sel), word
        assert word not in returns_columns(), word
    # the real uuid never leaves: the id is hashed
    assert "md5('tdw-preview:' || p.id::text) as preview_id" in sel
    assert not re.search(r"\bp\.id\b(?!::text\))", sel)


def test_sale_month_is_truncated_and_auction_only():
    assert "case when p.source = 'auction' and p.sale_date is not null then date_trunc('month', p.sale_date)::date end as sale_month" in select_list()


def test_customer_publishable_rows_only():
    c = code()
    for rule in ("auth.uid() is not null", "p.state = p_state", "p.status = 'active'", "p.delisted_at is null",
                 "p.publication_status in ('approved', 'approved_grandfathered')",
                 "not in ('mi_detroit_landbank_lots', 'mi_detroit_landbank_programs')",
                 "p.last_seen_at >= now() - interval '7 days'", "p.sale_date >= current_date",
                 "to_jsonb(p) ->> 'publication_state' = 'customer_published'"):
        assert rule in c, rule


def test_limit_is_capped_at_60_and_order_is_deterministic():
    c = code()
    assert "limit least(greatest(coalesce(p_limit, 60), 0), 60)" in c
    assert "offset greatest(coalesce(p_offset, 0), 0)" in c
    assert "order by p.county, p.source, p.id" in c


def test_grants_authenticated_only():
    c = code()
    sig = "public.get_preview_listings(text, text, integer, integer)"
    assert f"revoke all on function {sig} from public, anon;" in c
    assert f"grant execute on function {sig} to authenticated, service_role;" in c
    assert not re.search(r"grant [^;]* to [^;]*\banon\b", c)
    assert not re.search(r"grant [^;]* to [^;]*\bpublic\b", c)


def test_no_table_policy_or_data_statement():
    c = code()
    for word in ("create policy", "drop policy", "alter policy", "alter table", "drop function",
                 "insert into", "update public.", "delete from", "truncate"):
        assert word not in c, word


def test_stub_mirror_returns_the_same_columns_and_the_app_calls_it_for_pending_only():
    m = re.search(r"PREVIEW_COLUMNS = \[([^\]]*)\]", STUB)
    assert m, "stub PREVIEW_COLUMNS not found"
    cols = [x.strip().strip('"').strip("'") for x in m.group(1).split(",") if x.strip()]
    assert cols == SAFE_COLUMNS
    assert 'sb.rpc("get_preview_listings"' in APP
