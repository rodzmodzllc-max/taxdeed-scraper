"""Tests for Phase 58 - exposing already-collected enrichment through the API.

The data was correct, stored, and unreachable: get_properties() still
projected the pre-Phase-52 column set, so 500 FEMA results, 300 NAIP images
and the Phase 52 FDOR fields existed in Supabase and were invisible to the
product.

The trap this file mostly guards is the SECOND half of that fix.
get_properties() is deliberately NOT security definer (RLS must apply to the
caller), and migration 005a revoked blanket SELECT and granted `authenticated`
column-level SELECT on an explicit list. A column added to the projection but
not to that grant does not merely fail to appear - every call raises
`permission denied for column` and the whole API goes down. Both halves have
to be in the same migration.

No network and no database.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
MIGRATION = REPO / "scripts" / "migrations" / "012_expose_enrichment_in_get_properties.sql"
APP_JS = REPO / "public" / "app.js"

SQL = MIGRATION.read_text(encoding="utf-8")


def sql_only() -> str:
    """Strip comments - this migration's comments legitimately name fields it
    deliberately does NOT expose, and a naive substring check would read those
    as exposure."""
    return "\n".join(
        l for l in SQL.splitlines() if not l.strip().startswith("--")
    )


# The pre-existing contract, read from the live function before the change.
PRE_EXISTING = [
    "id", "state", "county", "source", "harvester_source", "address", "parcel",
    "case_no", "owner_name", "status", "prop_type", "dor_use_code",
    "tx_category", "lien_level", "lien_note", "homestead", "bid", "assessed",
    "market", "value_year", "min_bid", "redemption_period_months",
    "redemption_expiration_date", "max_statutory_return_usd", "year_built",
    "living_area", "lot_sqft", "num_buildings", "land_value", "legal_desc",
    "last_sale_price", "last_sale_year", "sale_date", "certificate_no",
    "tax_year", "issued_date", "expiration_date", "interest_rate", "latitude",
    "longitude", "url_appraiser", "url_auction", "url_taxcoll", "url_title",
    "url_streetview", "url_zillow", "gone_since", "updated_at",
]

NEWLY_EXPOSED = [
    "photo_url", "photo_source", "photo_captured_year",
    "flood_zone", "flood_zone_subtype", "flood_sfha", "flood_bfe",
    "flood_firm_id", "flood_checked_at",
    "taxable_value", "improvement_value", "acreage", "land_use",
    "effective_year_built", "num_res_units",
    "last_sale_month", "last_sale_qual_code", "last_sale_vi_code",
    "last_sale_or_book", "last_sale_or_page", "last_sale_clerk_no",
    "prior_sale_price", "prior_sale_year", "prior_sale_month",
    "prior_sale_qual_code",
]

WITHHELD = ["fdor_alt_key", "field_provenance", "photo_checked_at"]


# ---------------------------------------------------------------------------
# 1. The grant, which is the half that takes the API down if forgotten
# ---------------------------------------------------------------------------

def test_p58_01_every_newly_projected_column_is_also_granted():
    body = sql_only()
    grant = body[body.index("grant select ("):body.index(") on public.properties")]
    for col in NEWLY_EXPOSED:
        assert col in grant, f"{col} is projected but not granted - API would 500"


def test_p58_02_grant_is_additive_and_revokes_nothing():
    assert "revoke" not in sql_only().lower()


def test_p58_03_grant_targets_authenticated():
    assert "to authenticated" in sql_only()


# ---------------------------------------------------------------------------
# 2. The existing contract is preserved
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("col", PRE_EXISTING)
def test_p58_04_pre_existing_column_still_returned(col):
    body = sql_only()
    returns = body[body.index("returns table ("):body.index("language sql")]
    assert re.search(rf"\b{col}\b", returns), f"{col} disappeared from the projection"


def test_p58_05_where_clause_is_unchanged():
    """An added nullable column must never filter a record out. The row count
    before and after this migration is identical, and this pins the reason."""
    body = sql_only()
    assert "where state = p_state" in body
    assert "(p_ledger_type is null or ledger_type = p_ledger_type)" in body
    assert "(p_status is null or status = p_status)" in body


def test_p58_06_ordering_is_unchanged():
    assert "order by county, case_no" in sql_only()


def test_p58_07_function_stays_security_invoker():
    """Not security definer: RLS has to apply to the caller. 005/005a's whole
    design rests on this."""
    assert "security definer" not in sql_only().lower()


def test_p58_08_return_type_change_drops_before_creating():
    """CREATE OR REPLACE cannot change a return type - migration 005 learned
    this the hard way."""
    body = sql_only()
    assert "drop function if exists public.get_properties(text, text, text, integer, integer)" in body
    assert body.index("drop function") < body.index("create function")


def test_p58_09_execute_grant_is_restored_after_the_drop():
    """DROP takes the old EXECUTE grants with it; without this the API is
    dead for every role."""
    body = sql_only()
    assert "grant execute on function public.get_properties" in body
    for role in ("anon", "authenticated", "service_role"):
        assert role in body[body.index("grant execute"):]


# ---------------------------------------------------------------------------
# 3. What is deliberately withheld
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("col", WITHHELD)
def test_p58_10_withheld_column_is_not_projected(col):
    body = sql_only()
    returns = body[body.index("returns table ("):body.index("language sql")]
    assert not re.search(rf"\b{col}\b", returns), f"{col} should not be on the customer API"


def test_p58_11_alt_key_reason_is_recorded():
    """It is withheld because its tax-collector reading is an unvalidated
    hypothesis, not because it was forgotten."""
    assert "fdor_alt_key" in SQL
    assert "UNVALIDATED" in SQL or "unvalidated" in SQL


def test_p58_12_no_owner_mailing_address_is_exposed():
    """Never collected, and deliberately so - but a future field list should
    not quietly acquire it either."""
    body = sql_only()
    for col in ("own_addr", "owner_address", "mail_addr", "mailing_address"):
        assert col not in body.lower()


# ---------------------------------------------------------------------------
# 4. Migration hygiene
# ---------------------------------------------------------------------------

def test_p58_13_migration_is_transactional():
    body = "\n".join(l for l in SQL.splitlines() if not l.strip().startswith("--")).strip()
    assert body.startswith("begin;") and body.rstrip().endswith("commit;")


def test_p58_14_migration_has_no_destructive_table_statement():
    body = sql_only().lower()
    for bad in ("drop table", "drop column", "delete from", "truncate"):
        assert bad not in body


# ---------------------------------------------------------------------------
# 5. The frontend renders it honestly
# ---------------------------------------------------------------------------

def test_p58_15_unmapped_never_renders_as_low_risk():
    """'FEMA does not map this parcel' is not 'FEMA found minimal hazard'."""
    js = APP_JS.read_text(encoding="utf-8")
    assert "UNMAPPED" in js
    assert "Not mapped by FEMA" in js
    block = js[js.index("function floodRowHtml"):js.index("function riskLegalCardHtml")]
    unmapped = block[block.index('p.flood_zone === "UNMAPPED"'):]
    assert "not the same as low risk" in unmapped


def test_p58_16_never_checked_is_distinct_from_checked():
    js = APP_JS.read_text(encoding="utf-8")
    block = js[js.index("function floodRowHtml"):js.index("function riskLegalCardHtml")]
    assert "Not checked" in block
    assert "flood_checked_at" in block


def test_p58_17_sfha_is_tri_state_not_truthy():
    """`false` is a positive claim that the parcel is NOT in a hazard area;
    null is unknown. A truthy check would collapse them."""
    js = APP_JS.read_text(encoding="utf-8")
    block = js[js.index("function floodRowHtml"):js.index("function riskLegalCardHtml")]
    assert "p.flood_sfha === true" in block
    assert "p.flood_sfha === false" in block


def test_p58_18_the_other_risk_rows_stay_not_tracked():
    """Only flood gained a real source. Liens, judgments, foreclosure and code
    violations still have zero real data anywhere in the pipeline."""
    js = APP_JS.read_text(encoding="utf-8")
    block = js[js.index("function riskLegalCardHtml"):]
    block = block[:block.index("\nfunction ", 5)]
    assert "Not tracked" in block
    for row in ("Liens", "Judgments", "Foreclosure", "Code Violations"):
        assert row in block


def test_p58_19_residential_units_are_not_labelled_bedrooms():
    """FDOR NO_RES_UNT is dwelling units. The NAL layout has no bedroom field
    at all, and mislabelling it would invent one."""
    js = APP_JS.read_text(encoding="utf-8")
    assert "Residential Units" in js
    assert '"Bedrooms"' not in js


def test_p58_20_taxable_value_is_shown_beside_assessed_not_instead_of_it():
    js = APP_JS.read_text(encoding="utf-8")
    assert "Taxable Value" in js
    assert "p.taxable_value" in js
