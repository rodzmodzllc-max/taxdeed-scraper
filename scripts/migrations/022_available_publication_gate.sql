-- Migration 022: source-level customer publication for the AVAILABLE ledger
-- and lifecycle transitions on the observation history (AVAILABLE
-- commercialization, 2026-09-30).
--
-- STATUS: PROPOSED, NOT APPLIED. Applied by hand by the project owner after
-- review, like every file in this directory. Must be applied AFTER 021 (it
-- re-creates get_properties() from 021's exact signature and column list
-- with ONE column APPENDED, and adds a column to
-- inventory_status_observations) and AFTER 018 (it adds columns to
-- county_source_registry). Independent of 015 / 016 / 020.
--
-- WHAT IT ADDS (nothing existing is renamed, dropped, re-typed or backfilled)
--
-- 1. public.county_source_registry
--      publication_status   APPROVED / APPROVED_GRANDFATHERED / UNREVIEWED /
--                           RESTRICTED / BLOCKED - whether customers may see
--                           this SOURCE's rows (harvesters/governance/publication.py;
--                           generated from data/county_source_registry.csv).
--                           Default UNREVIEWED: a source is never published
--                           by omission.
--      restrictions         why a RESTRICTED source is restricted.
--      last_error_category  the last attempt's error category (freshness).
--
-- 2. public.properties
--      publication_status   the row's SOURCE decision, propagated by
--                           scripts/publication_gate.py (never decided per
--                           row). NULL = not yet classified (written before
--                           this column, or a source the registry cannot
--                           name) - the frontend keeps today's behaviour for
--                           NULL and counts it, so the gap is measurable.
--
-- 3. public.inventory_status_observations
--      transition           what the observation was, relative to the stored
--                           status: newly_observed / status_changed /
--                           removed / result_published (scripts/inventory_status_writer.py).
--
-- 4. get_properties(): 021's list with ONE column appended - publication_status.
--    Everything before it is byte-for-byte 021's list; WHERE/ORDER/LIMIT/
--    OFFSET unchanged; search_path re-pinned; grants restated.
--
-- WHAT IT DOES NOT DO: no row is withheld by the database - RLS is
-- unchanged (customers who may read properties still may). Withholding
-- restricted inventory from the customer AVAILABLE ledger is done by the
-- frontend from publication_status, and the gate script is what writes the
-- value. A stricter, policy-level withholding is a separate, later decision.
--
-- Rollback (by hand): re-run 021 section 4 for get_properties(); then
--   alter table public.inventory_status_observations drop column if exists transition;
--   alter table public.properties drop column if exists publication_status;
--   alter table public.county_source_registry drop column if exists last_error_category, drop column if exists restrictions, drop column if exists publication_status;

begin;

-- ---------------------------------------------------------------------------
-- 1. county_source_registry: publication per source
-- ---------------------------------------------------------------------------
alter table public.county_source_registry
  add column if not exists publication_status text not null default 'UNREVIEWED',
  add column if not exists restrictions text,
  -- the last attempt's error category (scripts/unit_freshness.py), so the
  -- Dashboard can tell "source unavailable" (TRANSPORT_ / PROXY_ / ACCESS_)
  -- from a read that reached the source and failed to parse
  add column if not exists last_error_category text;

alter table public.county_source_registry drop constraint if exists county_source_registry_publication_status_check;
alter table public.county_source_registry add constraint county_source_registry_publication_status_check
  check (publication_status in ('APPROVED', 'APPROVED_GRANDFATHERED', 'UNREVIEWED', 'RESTRICTED', 'BLOCKED'));

comment on column public.county_source_registry.publication_status is
  'Whether customers may see this source''s rows: APPROVED (reviewed), APPROVED_GRANDFATHERED (already served before the gate existed), UNREVIEWED (default; not shown), RESTRICTED (reviewed, not shown - see restrictions), BLOCKED (blocked vendor). Source-level; a government site is not commercial permission.';
comment on column public.county_source_registry.restrictions is
  'Why a RESTRICTED source is restricted.';
comment on column public.county_source_registry.last_error_category is
  'scripts/laft_status.py error category of the last attempt (NULL after a successful read); a TRANSPORT_ / PROXY_ / ACCESS_ category is "source unavailable" - inventory is kept, nothing is closed.';

-- ---------------------------------------------------------------------------
-- 2. properties: the propagated source decision
-- ---------------------------------------------------------------------------
alter table public.properties
  add column if not exists publication_status text;

alter table public.properties drop constraint if exists properties_publication_status_check;
alter table public.properties add constraint properties_publication_status_check
  check (publication_status is null or publication_status in ('APPROVED', 'APPROVED_GRANDFATHERED', 'UNREVIEWED', 'RESTRICTED', 'BLOCKED'));

comment on column public.properties.publication_status is
  'The SOURCE''s customer-publication decision, propagated by scripts/publication_gate.py from county_source_registry.publication_status. NULL = not yet classified. The frontend withholds non-APPROVED rows from the customer AVAILABLE ledger.';

create index if not exists properties_publication_status_idx
  on public.properties (state, source, publication_status);

-- Customers may read the column (015's column grant lists are additive).
grant select (publication_status) on public.properties to authenticated;

-- ---------------------------------------------------------------------------
-- 3. inventory_status_observations: the transition each observation records
-- ---------------------------------------------------------------------------
alter table public.inventory_status_observations
  add column if not exists transition text;

alter table public.inventory_status_observations drop constraint if exists inventory_status_observations_transition_check;
alter table public.inventory_status_observations add constraint inventory_status_observations_transition_check
  check (transition is null or transition in ('newly_observed', 'status_changed', 'removed', 'result_published'));

comment on column public.inventory_status_observations.transition is
  'newly_observed (first status for the row) / status_changed / removed (left the list, closed) / result_published (a result the source itself published). Never derived from absence: a removed row is closed, not sold.';

-- ---------------------------------------------------------------------------
-- 4. get_properties(): drop the exact live (021) signature, re-create with
--    ONE column appended. Everything before it is byte-for-byte 021's list;
--    WHERE/ORDER/LIMIT/OFFSET unchanged.
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
  escheatment_date date, available_date date,
  -- 021: normalized lifecycle status and provenance exposure
  inventory_status text, inventory_status_raw text, inventory_status_basis text,
  inventory_status_observed_at timestamptz,
  field_provenance jsonb, otc_provenance jsonb,
  -- 022: the source's customer-publication decision
  publication_status text
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
    escheatment_date, available_date,
    inventory_status, inventory_status_raw, inventory_status_basis,
    inventory_status_observed_at,
    field_provenance, otc_provenance,
    publication_status
  from public.properties
  where state = p_state
    and (p_ledger_type is null or ledger_type = p_ledger_type)
    and (p_status is null or status = p_status)
  order by county, case_no
  limit p_limit
  offset p_offset;
$function$;

-- 015 pins search_path on this function; re-pin here so the order of 015
-- and 022 does not matter.
alter function public.get_properties(text, text, text, integer, integer) set search_path = public;

grant execute on function public.get_properties(text, text, text, integer, integer)
  to anon, authenticated, service_role;

commit;
