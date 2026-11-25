"""Migration 043 (2026-11-22, owner): free period - every signed-in account
reads what an approved account reads, behind one server-side switch."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL = (ROOT / "scripts" / "migrations" / "043_open_access_free_period.sql").read_text(encoding="utf-8")
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")


def code(sql: str) -> str:
    return re.sub(r"\s+", " ", " ".join(ln.split("--", 1)[0] for ln in sql.splitlines())).lower().strip()


C = code(SQL)


def test_switch_table_is_server_only():
    assert "create table if not exists public.app_settings" in C
    assert "alter table public.app_settings enable row level security" in C
    assert "revoke all on table public.app_settings from anon, authenticated" in C
    assert "create policy" not in C          # no customer policy at all
    assert "('open_access', '{\"enabled\": true" in C


def test_open_access_is_signed_in_only_and_read_only():
    assert "select auth.uid() is not null and coalesce((select (value->>'enabled')::boolean from public.app_settings where key = 'open_access'), false)" in C
    assert "revoke all on function public.open_access() from public, anon" in C
    assert "grant execute on function public.open_access() to authenticated, service_role" in C


def test_is_approved_keeps_041_and_adds_the_switch():
    body = C[C.index("create or replace function public.is_approved()"):]
    assert "approved or (trial_ends_at is not null and trial_ends_at > now())" in body
    assert "or public.open_access()" in body
    # is_member() (team notes) is not widened.
    assert "function public.is_member()" not in C


def test_app_lands_everyone_on_guided():
    assert 'await sb.rpc("open_access")' in APP
    assert "if (approved || onTrial || OPEN_ACCESS) {" in APP
    assert 'var PAGE_TIER_KEY = "tdw_page_tier_v2";' in APP
    assert 'if (allowed.includes("beginner")) return "beginner";' in APP
