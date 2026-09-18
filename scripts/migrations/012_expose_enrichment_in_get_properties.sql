-- Phase 58: make the enrichment we already collected visible to the product.
--
-- As of 2026-09-18 the database holds 500 FEMA flood results (102 of them in
-- a Special Flood Hazard Area), 300 NAIP aerial images, and Phase 52 FDOR
-- fields on real rows - and the customer API could see none of it, because
-- get_properties() still projected only the pre-Phase-52 column set. The data
-- was correct, stored and unreachable.
--
-- TWO THINGS HAVE TO CHANGE TOGETHER, AND MISSING THE SECOND IS THE TRAP
--
-- get_properties() is LANGUAGE sql STABLE and deliberately NOT security
-- definer (see 005/005a - RLS must apply to the caller). Migration 005a then
-- revoked blanket SELECT on public.properties and granted `authenticated`
-- column-level SELECT on an explicit list. So a column added to the function's
-- projection but not to that grant does not merely fail to appear - it makes
-- every call raise `permission denied for column`, taking the whole API down
-- rather than degrading. Both halves are in this file for that reason.
--
-- A return-type change also cannot be done with CREATE OR REPLACE. 005 learned
-- this the hard way (see 005's own header and test_phase14e); the exact live
-- signature is dropped first, inside the same transaction.
--
-- WHAT IS DELIBERATELY NOT EXPOSED
--
--   fdor_alt_key       - FDOR's "[o]ptional alternate key identifier some
--                        counties use". Its tax-collector-account reading is
--                        an UNVALIDATED hypothesis (a 15-parcel Alachua sample
--                        found it strictly sequential in parcel order, which
--                        looks like a CAMA row index). Putting it on the API
--                        invites the UI to build a tax-collector URL out of
--                        it, which docs/fdor-field-provenance.md explicitly
--                        warns against. It stays internal until validated.
--   field_provenance   - internal jsonb audit metadata, not customer output.
--   photo_checked_at   - photo_url already carries a three-state contract
--                        (NULL = never checked, '' = checked and no coverage,
--                        value = a real image), so the timestamp adds surface
--                        without adding an answer.
--   owner mailing address - never collected. See docs/fdor-field-provenance.md.
--
-- flood_checked_at IS exposed, and it is not optional: flood_zone alone cannot
-- distinguish "never checked" from "checked", and the whole point of migration
-- 007's risk pairs is that the UI must be able to say "as of <date>" rather
-- than implying a clean result. Likewise flood_zone carries the sentinel
-- 'UNMAPPED' - FEMA publishes no map for that point - which is an absence of
-- information and must never render as low risk.

begin;

-- ---------------------------------------------------------------------------
-- 1. Grants first.
-- ---------------------------------------------------------------------------
-- Additive only: nothing already granted is revoked, so every existing field
-- keeps working exactly as before.
grant select (
  photo_url, photo_source, photo_captured_year,
  flood_zone, flood_zone_subtype, flood_sfha, flood_bfe, flood_firm_id,
  flood_checked_at,
  taxable_value, improvement_value, acreage, land_use,
  effective_year_built, num_res_units,
  last_sale_month, last_sale_qual_code, last_sale_vi_code,
  last_sale_or_book, last_sale_or_page, last_sale_clerk_no,
  prior_sale_price, prior_sale_year, prior_sale_month, prior_sale_qual_code
) on public.properties to authenticated;

-- ---------------------------------------------------------------------------
-- 2. Drop the exact live signature, then recreate.
-- ---------------------------------------------------------------------------
drop function if exists public.get_properties(text, text, text, integer, integer);

create function public.get_properties(
  p_state text,
  p_ledger_type text default null,
  p_status text default null,
  p_limit integer default 20000,
  p_offset integer default 0
)
returns table (
  -- Every pre-existing column, in its original order and type. Nothing here
  -- is renamed, retyped or removed - the frontend's existing reads and the
  -- CSV export both depend on this exact set.
  id uuid, state text, county text, source text, harvester_source text,
  address text, parcel text, case_no text, owner_name text, status text,
  prop_type text, dor_use_code text, tx_category text, lien_level text,
  lien_note text, homestead boolean, bid numeric, assessed numeric,
  market numeric, value_year integer, min_bid numeric,
  redemption_period_months integer, redemption_expiration_date date,
  max_statutory_return_usd numeric, year_built integer, living_area integer,
  lot_sqft integer, num_buildings integer, land_value numeric,
  legal_desc text, last_sale_price numeric, last_sale_year integer,
  sale_date date, certificate_no text, tax_year text, issued_date date,
  expiration_date date, interest_rate numeric, latitude double precision,
  longitude double precision, url_appraiser text, url_auction text,
  url_taxcoll text, url_title text, url_streetview text, url_zillow text,
  gone_since timestamptz, updated_at timestamptz,

  -- Phase 57 imagery. photo_source distinguishes an overhead NAIP aerial from
  -- a Street View facade; they are not interchangeable to a viewer, and the
  -- UI must not label an aerial a photograph of a building.
  photo_url text, photo_source text, photo_captured_year integer,

  -- Phase 56 flood. flood_sfha is the field that actually drives the federal
  -- mandatory flood-insurance requirement; zone letters are easy to misread.
  flood_zone text, flood_zone_subtype text, flood_sfha boolean,
  flood_bfe numeric, flood_firm_id text, flood_checked_at timestamptz,

  -- Phase 52 FDOR. taxable_value is post-exemption where `assessed` above is
  -- pre-exemption - the gap between them IS the exemption, so both are
  -- exposed rather than collapsed. improvement_value and acreage are DERIVED
  -- (JV - LND_VAL, and LND_SQFOOT / 43560); see migration 009.
  taxable_value numeric, improvement_value numeric, acreage numeric,
  land_use text, effective_year_built integer, num_res_units integer,

  -- last_sale_qual_code travels with last_sale_price on purpose. A tax roll's
  -- most recent "sale" is very often a $100 intra-family quitclaim the
  -- appraiser DISQUALIFIED precisely so it is not read as market evidence.
  -- Exposing the price without the code is how that becomes a wrong number on
  -- a bid screen.
  last_sale_month smallint, last_sale_qual_code text, last_sale_vi_code text,
  last_sale_or_book text, last_sale_or_page text, last_sale_clerk_no text,
  prior_sale_price numeric, prior_sale_year integer,
  prior_sale_month smallint, prior_sale_qual_code text
)
language sql
stable
as $function$
  select
    id, state, county, source, harvester_source, address, parcel, case_no,
    owner_name, status, prop_type, dor_use_code, tx_category, lien_level,
    lien_note, homestead, bid, assessed, market, value_year, min_bid,
    redemption_period_months, redemption_expiration_date,
    max_statutory_return_usd, year_built, living_area, lot_sqft,
    num_buildings, land_value, legal_desc, last_sale_price,
    last_sale_year, sale_date, certificate_no, tax_year, issued_date,
    expiration_date, interest_rate, latitude, longitude, url_appraiser,
    url_auction, url_taxcoll, url_title, url_streetview, url_zillow,
    gone_since, updated_at,
    photo_url, photo_source, photo_captured_year,
    flood_zone, flood_zone_subtype, flood_sfha, flood_bfe, flood_firm_id,
    flood_checked_at,
    taxable_value, improvement_value, acreage, land_use,
    effective_year_built, num_res_units,
    last_sale_month, last_sale_qual_code, last_sale_vi_code,
    last_sale_or_book, last_sale_or_page, last_sale_clerk_no,
    prior_sale_price, prior_sale_year, prior_sale_month, prior_sale_qual_code
  from public.properties
  -- WHERE clause byte-for-byte unchanged. Every added column is nullable and
  -- appears only in the projection, so row count and ordering are identical
  -- to before - an added column must never filter a record out.
  where state = p_state
    and (p_ledger_type is null or ledger_type = p_ledger_type)
    and (p_status is null or status = p_status)
  order by county, case_no
  limit p_limit
  offset p_offset;
$function$;

-- Same role set 005 granted. DROP removed the old grants with the old
-- function, so these are restored, not widened.
grant execute on function public.get_properties(text, text, text, integer, integer)
  to anon, authenticated, service_role;

commit;
