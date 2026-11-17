"""Migration 042 (2026-11-17, owner): in-app willingness-to-pay answers.
Customers insert their own rows and read none; admins read all."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL = (ROOT / "scripts" / "migrations" / "042_pricing_feedback.sql").read_text(encoding="utf-8")
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")


def code(sql: str) -> str:
    return re.sub(r"\s+", " ", " ".join(ln.split("--", 1)[0] for ln in sql.splitlines())).lower().strip()


C = code(SQL)


def test_table_and_bounds():
    assert "create table if not exists public.pricing_feedback" in C
    assert "user_id uuid not null default auth.uid()" in C
    for col in ("too_cheap", "bargain", "getting_expensive", "too_expensive"):
        assert f"{col} numeric check ({col} is null or ({col} >= 0 and {col} <= 10000))" in C
    assert "char_length(comment) <= 1000" in C


def test_privileges_and_policies():
    assert "alter table public.pricing_feedback enable row level security" in C
    assert "revoke all on table public.pricing_feedback from anon, authenticated" in C
    # customers can never choose user_id or created_at
    grant = C[C.index("grant insert ("):]
    grant = grant[:grant.index(")")]
    assert "user_id" not in grant and "created_at" not in grant
    assert "as permissive for insert to authenticated with check (user_id = (select auth.uid()))" in C
    assert "as permissive for select to authenticated using ((select public.is_admin()))" in C
    assert "as restrictive for all to authenticated using ((select public.is_approved()))" in C
    assert "for update" not in C and "for delete" not in C


def test_app_no_longer_offers_the_survey():
    # Owner, 2026-11-17: pricing is researched privately, not asked in the app.
    # The table (042, applied) stays; nothing in the app writes to it.
    assert "pricing_feedback" not in APP and "openPricingSurvey" not in APP
