"""Tests for the Phase 50 design-gap backend (migrations 007 + 008).

These parse the migration SQL rather than talking to a database - the files
have not been applied to production, and a test that needs production to pass
is not a test. What they defend is the reasoning, because the reasoning is the
part that gets lost:

  * A risk count must never reach the UI without the timestamp proving a check
    actually ran. "Liens: None found" on a property nobody checked is a
    confident wrong answer someone bids money on.
  * The customer projection must not acquire `outcome` or `sold_price`.
  * The projection must stay non-SECURITY-DEFINER, so RLS still applies.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
M007 = REPO / "scripts" / "migrations" / "007_design_gap_property_intelligence.sql"
M008 = REPO / "scripts" / "migrations" / "008_get_properties_design_fields.sql"

SQL007 = M007.read_text(encoding="utf-8")
SQL008 = M008.read_text(encoding="utf-8")

RISKS = ["liens", "judgments", "code_violations"]


def sql_only(text: str) -> str:
    """The SQL with `--` comments removed. These migrations carry long
    explanatory headers that quote the very strings some assertions forbid -
    checking the prose instead of the statements is how a test passes for the
    wrong reason."""
    return "\n".join(re.sub(r"--.*$", "", line) for line in text.splitlines())


BODY007 = sql_only(SQL007)
BODY008 = sql_only(SQL008)
MIGRATIONS = [("007", SQL007, BODY007), ("008", SQL008, BODY008)]


# ===========================================================================
# The honesty model
# ===========================================================================

@pytest.mark.parametrize("risk", RISKS)
def test_p50d_01_every_risk_count_has_a_checked_at(risk):
    assert f"{risk}_count" in SQL007
    assert f"{risk}_checked_at" in SQL007


@pytest.mark.parametrize("risk", RISKS + ["foreclosure", "flood"])
def test_p50d_02_constraint_forbids_a_value_without_a_check(risk):
    """The database itself must refuse the row shape that would let the UI
    render "None found" off a check that never happened."""
    m = re.search(r"properties_risk_counts_need_a_check\s+check\s*\((.*?)\);",
                  BODY007, re.S)
    assert m, "the check constraint is gone"
    body = m.group(1)
    assert f"{risk}_checked_at" in body, f"{risk} is not covered by the constraint"


def test_p50d_03_constraint_pairs_each_value_with_its_own_check():
    m = re.search(r"properties_risk_counts_need_a_check\s+check\s*\((.*?)\);", BODY007, re.S)
    body = m.group(1)
    for value_col, check_col in (
        ("liens_count", "liens_checked_at"),
        ("judgments_count", "judgments_checked_at"),
        ("code_violations_count", "code_violations_checked_at"),
        ("foreclosure_status", "foreclosure_checked_at"),
        ("flood_zone", "flood_checked_at"),
    ):
        pat = rf"{value_col}\s+is null or {check_col}\s+is not null"
        assert re.search(pat, body), f"{value_col} is not paired with {check_col}"


def test_p50d_04_counts_cannot_be_negative():
    assert "properties_risk_counts_non_negative" in SQL007
    for risk in RISKS:
        assert re.search(rf"coalesce\({risk}_count,\s*0\)\s*>=\s*0", SQL007)


@pytest.mark.parametrize("risk", RISKS + ["foreclosure", "flood"])
def test_p50d_05_projection_exposes_the_check_alongside_the_value(risk):
    """Shipping the count without the timestamp is the whole bug."""
    assert f"{risk}_checked_at" in SQL008, f"{risk}_checked_at is not exposed"


def test_p50d_06_no_default_backfills_a_risk_as_clear():
    """A `default 0` on a count would silently mark every existing row as
    checked-and-clear the moment the migration runs."""
    for risk in RISKS:
        assert not re.search(rf"{risk}_count\s+integer\s+default", SQL007, re.I)
        assert not re.search(rf"{risk}_count\s+integer\s+not null", SQL007, re.I)


# ===========================================================================
# The customer API boundary
# ===========================================================================

def test_p50d_07_projection_still_excludes_the_deferred_fields():
    assert "outcome" not in BODY008
    assert "sold_price" not in BODY008


def test_p50d_08_projection_is_not_security_definer():
    """Not SECURITY DEFINER means it runs as the caller and RLS still applies.
    Turning it into a definer function would quietly bypass every policy."""
    body = BODY008.lower()
    assert "security definer" not in body
    assert re.search(r"language sql\s+stable", body)


def test_p50d_09_projection_keeps_its_argument_list():
    for arg in ("p_state", "p_ledger_type", "p_status", "p_limit", "p_offset"):
        assert arg in SQL008


def test_p50d_10_projection_keeps_its_filters_and_ordering():
    for clause in ("where state = p_state",
                   "p_ledger_type is null or ledger_type = p_ledger_type",
                   "p_status is null or status = p_status",
                   "order by county, case_no"):
        assert clause in SQL008, clause


def test_p50d_11_every_new_property_column_reaches_the_projection():
    """Scoped to columns added to `properties`. A column on `favorites` is
    the watchlist's own state and has no business in a property projection -
    an earlier version of this test conflated the two."""
    new_cols = set(re.findall(
        r"alter table public\.properties add column if not exists\s+(\w+)", SQL007))
    assert len(new_cols) > 15, "the properties ALTERs stopped being detected"
    # geog is spatial plumbing the map queries by, not a field the detail
    # screen prints.
    display = new_cols - {"geog"}
    missing = sorted(c for c in display if c not in BODY008)
    assert not missing, f"added to properties but never exposed: {missing}"


def test_p50d_11b_watchlist_state_stays_out_of_the_property_projection():
    fav_cols = set(re.findall(
        r"alter table public\.favorites add column if not exists\s+(\w+)", SQL007))
    assert fav_cols == {"stage", "stage_updated_at"}
    for col in fav_cols:
        assert col not in BODY008, f"{col} is per-user watchlist state, not property data"


# ===========================================================================
# History belongs in its own table
# ===========================================================================

def test_p50d_12_property_events_table_exists_with_provenance():
    assert "create table if not exists public.property_events" in SQL007
    for col in ("property_id", "event_date", "event_type", "source", "retrieved_at"):
        assert col in SQL007


def test_p50d_13_an_event_cannot_be_recorded_without_a_source():
    m = re.search(r"create table if not exists public\.property_events\s*\((.*?)\n\);",
                  BODY007, re.S)
    assert m
    body = m.group(1)
    assert re.search(r"source\s+text\s+not null", body), "source must be mandatory"
    assert re.search(r"event_date\s+date\s+not null", body)


def test_p50d_14_reharvesting_an_event_updates_rather_than_duplicates():
    assert re.search(r"unique \(property_id, event_type, event_date", SQL007)


def test_p50d_15_events_cascade_with_their_property():
    assert "references public.properties(id) on delete cascade" in SQL007


def test_p50d_16_event_types_are_constrained():
    m = re.search(r"event_type\s+text not null check \(event_type in \((.*?)\)\)",
                  BODY007, re.S)
    assert m, "event_type is no longer constrained to a known set"
    allowed = m.group(1)
    for t in ("AUCTION_SCHEDULED", "SALE", "TRANSFER", "DEED_RECORDED"):
        assert t in allowed


# ===========================================================================
# Watchlist pipeline
# ===========================================================================

def test_p50d_17_favorites_gains_a_constrained_stage():
    assert "alter table public.favorites add column if not exists stage" in SQL007
    m = re.search(r"favorites_stage_valid check \(\s*stage in \((.*?)\)", BODY007, re.S)
    assert m
    for stage in ("WATCHLIST", "RESEARCH", "DUE_DILIGENCE", "AUCTION", "WON", "LOST", "POST_AUCTION"):
        assert f"'{stage}'" in m.group(1)


def test_p50d_18_auction_soon_is_not_a_stage():
    """It is a date filter over sale_date. As a stage it could disagree with
    the calendar."""
    m = re.search(r"favorites_stage_valid check \(\s*stage in \((.*?)\)", BODY007, re.S)
    assert "AUCTION_SOON" not in m.group(1)


def test_p50d_19_existing_favorites_keep_working():
    """The new column must not make old rows invalid."""
    assert re.search(r"add column if not exists stage text\s*\n?\s*not null default 'WATCHLIST'", SQL007)


# ===========================================================================
# Geometry and metrics
# ===========================================================================

def test_p50d_20_geography_is_generated_not_hand_maintained():
    assert "geography(Point, 4326)" in SQL007
    assert "generated always as" in SQL007
    assert "stored" in SQL007


def test_p50d_21_spatial_index_exists():
    assert re.search(r"create index if not exists properties_geog_gix .*using gist \(geog\)", SQL007)


def test_p50d_22_daily_metrics_supports_the_dashboard_deltas():
    assert "create table if not exists public.daily_metrics" in SQL007
    assert "primary key (metric_date, state, metric)" in SQL007


# ===========================================================================
# Migration hygiene
# ===========================================================================

@pytest.mark.parametrize("name", ["007", "008"])
def test_p50d_23_migration_is_transactional(name):
    body = dict((n, b) for n, _, b in MIGRATIONS)[name].strip().lower()
    assert body.startswith("begin;"), f"{name} does not open a transaction"
    assert body.endswith("commit;"), f"{name} does not commit"


@pytest.mark.parametrize("name", ["007", "008"])
def test_p50d_24_migration_is_rerunnable(name):
    """Every create/alter is guarded, so a partially-applied migration can be
    re-run rather than needing hand repair."""
    body = dict((n, b) for n, _, b in MIGRATIONS)[name]
    for stmt in re.findall(r"^[^\n]*\b(?:create table|create index|add column)\b[^\n]*",
                           body, re.I | re.M):
        assert "if not exists" in stmt.lower(), f"{name}: unguarded -> {stmt.strip()[:70]}"


@pytest.mark.parametrize("name", ["007", "008"])
def test_p50d_25_migration_is_non_destructive(name):
    """No data-losing statement. Dropping a CONSTRAINT before re-adding it is
    how these stay idempotent and is not data loss."""
    lowered = dict((n, b) for n, _, b in MIGRATIONS)[name].lower()
    for verb in ("drop table", "drop column", "truncate", "delete from"):
        assert verb not in lowered, f"{name} contains {verb!r}"
    for hit in re.findall(r"drop\s+(\w+)", lowered):
        assert hit == "constraint", f"{name} drops a {hit}"


def test_p50d_26_taxable_value_is_its_own_column():
    """Florida assessed is pre-exemption and taxable is post-exemption; the
    homestead feature depends on the difference. Reusing `assessed` for both
    would corrupt it."""
    assert "taxable_value" in SQL007
    assert "improvement_value" in SQL007
