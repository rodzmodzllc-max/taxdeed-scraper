"""Migration 041 (2026-11-17, owner): new accounts get a 7-day Guided trial
instead of waiting for approval; notes stay members-only."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL = (ROOT / "scripts" / "migrations" / "041_free_trial_7_days.sql").read_text(encoding="utf-8")
APP = (ROOT / "public" / "app.js").read_text(encoding="utf-8")


def code(sql: str) -> str:
    return re.sub(r"\s+", " ", " ".join(ln.split("--", 1)[0] for ln in sql.splitlines())).lower().strip()


C = code(SQL)


def test_trial_column_and_default():
    assert "add column if not exists trial_ends_at timestamptz" in C
    assert "alter column trial_ends_at set default (now() + interval '7 days')" in C
    # only unapproved rows without a date get one
    assert "where not approved and trial_ends_at is null" in C


def test_is_approved_admits_an_unexpired_trial_only():
    body = C[C.index("create or replace function public.is_approved()"):]
    body = body[:body.index("$$;")]
    assert "security definer" in body and "set search_path = public" in body
    assert "approved or (trial_ends_at is not null and trial_ends_at > now())" in body
    assert "where id = auth.uid()" in body and "coalesce(" in body


def test_notes_restrictive_policy_keeps_trials_to_their_own():
    assert 'create policy "notes: trial reads own only" on public.notes as restrictive for all to authenticated' in C
    assert "using ((select public.is_member()) or author_id = (select auth.uid()))" in C
    assert "select coalesce((select approved or is_admin from public.profiles where id = auth.uid()), false)" in C
    assert "revoke all on function public.is_member() from public, anon" in C


def test_no_customer_write_path_to_profiles_is_added():
    assert "grant update" not in C and "grant insert" not in C
    assert "create policy" in C and C.count("create policy") == 1


def test_app_follows_the_trial():
    assert 'select("approved,is_admin,trial_ends_at")' in APP
    assert 'if (role === "trial") return "beginner";' in APP
    assert "const IDLE_MINUTES = 60;" in APP
