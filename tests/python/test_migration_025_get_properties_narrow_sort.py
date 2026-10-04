"""Migration 025 (2026-10-04 incident: MI / LA "Couldn't load property data").

get_properties() must sort only narrow keys and fetch full rows by id, keep
the exact RETURNS TABLE column list, select every returned column, and keep
the (county, case_no, id) order that paging and migration 024 rely on.
"""
from __future__ import annotations

import re
from pathlib import Path

SQL = (Path(__file__).resolve().parents[2] / "scripts" / "migrations" / "025_get_properties_narrow_sort.sql").read_text(encoding="utf-8")


def _returned():
    body = re.search(r"returns table\((.*?)\)\nlanguage", SQL, re.S).group(1)
    return [c.strip().split(" ")[0] for c in body.split(",\n")]


def test_every_returned_column_is_selected_in_order_from_the_full_row():
    cols = _returned()
    sel = re.search(r"\n  select\n(.*?)\n  from page", SQL, re.S).group(1)
    assert [s.strip().rstrip(",") for s in sel.splitlines()] == [f"p.{c}" for c in cols]
    assert len(cols) == 105 and cols[0] == "id" and cols[-1] == "result_party"


def test_sorts_narrow_keys_then_joins_by_primary_key():
    page = re.search(r"with page as \((.*?)\n  \)", SQL, re.S).group(1)
    assert "select k.id as pid, k.county as k_county, k.case_no as k_case" in page
    assert "order by county, case_no, id" in page                  # 024 detects this and leaves 025 alone
    assert "limit p_limit" in page and "offset p_offset" in page
    assert "join public.properties p on p.id = page.pid" in SQL
    assert SQL.rstrip().endswith("order by page.k_county, page.k_case, page.pid;\n$function$;")


def test_signature_volatility_and_security_unchanged():
    assert "create or replace function public.get_properties(" in SQL
    assert "p_limit integer default 20000" in SQL and "p_offset integer default 0" in SQL
    assert "\nstable\n" in SQL and "set search_path to 'public'" in SQL
    assert "security definer" not in SQL.lower()                    # RLS still applies (invoker)
    assert not re.search(r"\b(grant|revoke|drop|alter|delete|update|insert)\b", SQL.split("as $function$")[0].split("\n-- ")[-1], re.I)
