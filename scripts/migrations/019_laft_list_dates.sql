-- Migration 019: the two inventory dates a Florida Lands Available list
-- publishes about a parcel's availability - escheatment_date and
-- available_date.
--
-- STATUS: PROPOSED, NOT APPLIED. Applied by hand by the project owner after
-- review, like every file in this directory. Must be applied AFTER 017 (it
-- re-creates get_properties() from 017's exact signature and column list
-- with the two new columns appended). Independent of 015/016/018.
--
-- WHY (enrichment phase, 2026-09-29)
--
-- The LAFT harvesters already read these two columns off the county lists
-- (HEADER_MAP "escheatment date" / "expiration date" in the PDF and HTML
-- harvesters; Putnam's "Available for Purchase:" card field; Leon's JSON)
-- and have written them into the harvest artifact since 2026-08, but the
-- properties table had nowhere to put them, so every run dropped them.
-- They are inventory facts, not property characteristics:
--
--   escheatment_date   the date the county's list says the parcel escheats
--                      to the county if unsold (F.S. 197.502(8): three
--                      years after the day it was offered for sale). A
--                      buyer's deadline. NULL = the list did not publish one.
--   available_date     the date the list says the parcel became / becomes
--                      available for purchase. NULL = not published.
--
-- Both are written ONLY by scripts/laft_source_fields.py (inside
-- scripts/laft_lifecycle.py), fill-blank, from the county's own cell,
-- with a field_provenance entry, and only after this migration exists
-- (the script probes for the columns and skips them otherwise). Nothing
-- is derived: no date is ever computed from a sale date, and the absence
-- of a value is never turned into one.
--
-- Same shape as 017: columns, comments, grant, then get_properties()
-- re-created with the two columns appended, search_path re-pinned,
-- execute re-granted. No backfill (there is nothing to backfill from -
-- the values arrive with the next laft run).

begin;

-- ---------------------------------------------------------------------------
-- 1. Columns (nullable; nothing existing is renamed, dropped or re-typed).
-- ---------------------------------------------------------------------------
alter table public.properties
  add column if not exists escheatment_date date,
  add column if not exists available_date date;

comment on column public.properties.escheatment_date is
  'From the county Lands Available list: the date the parcel escheats to the county if unsold (F.S. 197.502(8)). NULL = the list published none. Never computed.';
comment on column public.properties.available_date is
  'From the county Lands Available list: the date the parcel became / becomes available for purchase. NULL = the list published none. Never computed.';

-- ---------------------------------------------------------------------------
-- 2. Grants first (additive).
-- ---------------------------------------------------------------------------
grant select (escheatment_date, available_date) on public.properties to authenticated;

-- ---------------------------------------------------------------------------
-- 3. get_properties(): drop the exact live (017) signature, re-create with
--    the two columns appended. Everything before them is byte-for-byte
--    017's list; WHERE/ORDER/LIMIT/OFFSET unchanged.
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
  photo_url text, photo_source text, photo_captured_year integer,
  flood_zone text, flood_zone_subtype text, flood_sfha boolean,
  flood_bfe numeric, flood_firm_id text, flood_checked_at timestamptz,
  taxable_value numeric, improvement_value numeric, acreage numeric,
  land_use text, effective_year_built integer, num_res_units integer,
  last_sale_month smallint, last_sale_qual_code text, last_sale_vi_code text,
  last_sale_or_book text, last_sale_or_page text, last_sale_clerk_no text,
  prior_sale_price numeric, prior_sale_year integer,
  prior_sale_month smallint, prior_sale_qual_code text,
  url_auction_kind text, tx_sale_status text,
  -- 017: inventory classification, source authority, provenance URLs,
  -- honest amount semantics, currentness
  inventory_type text, source_authority text, source_id text,
  list_url text, document_url text, purchase_url text, purchase_url_kind text,
  purchase_amount numeric, purchase_amount_kind text,
  first_seen_at timestamptz, last_seen_at timestamptz, delisted_at timestamptz,
  source_published_at timestamptz, list_as_of date,
  -- 019: list-published inventory dates
  escheatment_date date, available_date date
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
    prior_sale_price, prior_sale_year, prior_sale_month, prior_sale_qual_code,
    url_auction_kind, tx_sale_status,
    inventory_type, source_authority, source_id,
    list_url, document_url, purchase_url, purchase_url_kind,
    purchase_amount, purchase_amount_kind,
    first_seen_at, last_seen_at, delisted_at,
    source_published_at, list_as_of,
    escheatment_date, available_date
  from public.properties
  where state = p_state
    and (p_ledger_type is null or ledger_type = p_ledger_type)
    and (p_status is null or status = p_status)
  order by county, case_no
  limit p_limit
  offset p_offset;
$function$;

-- 015 pins search_path on this function; re-pin here so the order of 015
-- and 019 does not matter.
alter function public.get_properties(text, text, text, integer, integer) set search_path = public;

grant execute on function public.get_properties(text, text, text, integer, integer)
  to anon, authenticated, service_role;

commit;

-- ---------------------------------------------------------------------------
-- Rollback (by hand, if ever needed): re-run 017's section 3 to restore its
-- get_properties() projection, then
--   alter table public.properties
--     drop column if exists escheatment_date, drop column if exists available_date;
-- ---------------------------------------------------------------------------
