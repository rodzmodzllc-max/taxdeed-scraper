-- Migration 021: customer-facing lifecycle status, provenance exposure and
-- per-unit source freshness (production-readiness program, 2026-09-30).
--
-- STATUS: PROPOSED, NOT APPLIED. Applied by hand by the project owner after
-- review, like every file in this directory. Must be applied AFTER 019 (it
-- re-creates get_properties() from 019's exact signature and column list
-- with new columns APPENDED) and AFTER 018 (it adds columns to
-- county_source_registry). Independent of 015 / 016 / 020.
--
-- WHAT IT ADDS (nothing existing is renamed, dropped, re-typed or backfilled)
--
-- 1. public.properties - the normalized inventory / lifecycle status:
--      inventory_status              one of harvesters/governance/inventory_status.py's
--                                    vocabulary (check constraint below)
--      inventory_status_raw          the source's own status wording, verbatim
--      inventory_status_basis        "SOURCE_STATUS: ..." / "LIST_PRESENCE: ..." /
--                                    "SCHEDULED_DATE: ..." / "NOT_PUBLISHED: ..." -
--                                    what kind of evidence produced the status
--      inventory_status_observed_at  when the pipeline observed it
--    Written ONLY by scripts/inventory_status_writer.py (which probes for
--    these columns and skips until they exist). A result status (sold,
--    redeemed, withdrawn, cancelled, struck_off) is written only from the
--    source's own published status; a row that merely left a list is
--    `closed`, and a past-dated auction with no published result is
--    `unknown` - the same rule the writer enforces in code.
-- 2. public.inventory_status_observations - append-only history of those
--    observations (one row per property per change), so the newest state
--    never overwrites what was observed before. Approved read; no client
--    write path (same access shape as migration 014's tables).
-- 3. public.county_source_registry - per-unit freshness written by
--    scripts/unit_freshness.py after each harvest: last_attempt_at /
--    last_attempt_status / last_success_at / last_success_row_count /
--    consecutive_failures. The table already has an approved-read policy
--    (018), so the Dashboard can show per-county freshness.
-- 4. get_properties(): 019's list with SIX columns appended -
--    inventory_status, inventory_status_raw, inventory_status_basis,
--    inventory_status_observed_at, field_provenance (migration 009's
--    per-field origin, never projected before) and otc_provenance
--    (migration 017's). Existing columns keep their order and semantics;
--    search_path re-pinned; execute re-granted.
--
-- Rollback (by hand): re-run 019 section 3 for get_properties(); then
--   alter table public.properties drop column if exists inventory_status,
--     drop column if exists inventory_status_raw, drop column if exists inventory_status_basis,
--     drop column if exists inventory_status_observed_at;
--   drop table if exists public.inventory_status_observations;
--   alter table public.county_source_registry drop column if exists last_attempt_at,
--     drop column if exists last_attempt_status, drop column if exists last_success_at,
--     drop column if exists last_success_row_count, drop column if exists consecutive_failures;

begin;

-- ---------------------------------------------------------------------------
-- 1. properties: normalized inventory / lifecycle status
-- ---------------------------------------------------------------------------
alter table public.properties
  add column if not exists inventory_status text,
  add column if not exists inventory_status_raw text,
  add column if not exists inventory_status_basis text,
  add column if not exists inventory_status_observed_at timestamptz;

alter table public.properties drop constraint if exists properties_inventory_status_check;
alter table public.properties add constraint properties_inventory_status_check
  check (inventory_status is null or inventory_status in (
    'upcoming', 'active', 'sold', 'redeemed', 'withdrawn', 'cancelled', 'struck_off',
    'state_held', 'resale_inventory', 'available_otc', 'closed', 'unknown'));

comment on column public.properties.inventory_status is
  'Normalized lifecycle state (harvesters/governance/inventory_status.py). sold / redeemed / withdrawn / cancelled / struck_off only from the source''s own published status; closed = left the list or feed; unknown = not published. NULL = not yet observed.';
comment on column public.properties.inventory_status_raw is
  'The source''s own status wording, verbatim, that produced inventory_status. NULL when the status came from list presence or a date.';
comment on column public.properties.inventory_status_basis is
  'What kind of evidence produced inventory_status: SOURCE_STATUS / LIST_PRESENCE / SCHEDULED_DATE / NOT_PUBLISHED, with a one-line reason.';
comment on column public.properties.inventory_status_observed_at is
  'When the pipeline observed the current inventory_status.';

grant select (inventory_status, inventory_status_raw, inventory_status_basis, inventory_status_observed_at,
              field_provenance, otc_provenance)
  on public.properties to authenticated;

-- ---------------------------------------------------------------------------
-- 2. inventory_status_observations: append-only history
-- ---------------------------------------------------------------------------
create table if not exists public.inventory_status_observations (
  id               bigint      generated always as identity primary key,
  property_id      uuid        not null references public.properties(id) on delete cascade,
  observed_at      timestamptz not null default now(),
  harvest_run_id   text,
  source_id        text,
  raw_status       text,
  inventory_status text        not null,
  basis            text        not null,
  evidence_url     text,
  created_at       timestamptz not null default now(),
  constraint inventory_status_observations_status_check
    check (inventory_status in (
      'upcoming', 'active', 'sold', 'redeemed', 'withdrawn', 'cancelled', 'struck_off',
      'state_held', 'resale_inventory', 'available_otc', 'closed', 'unknown')),
  constraint inventory_status_observations_one_per_run unique (property_id, observed_at)
);
create index if not exists inventory_status_observations_property_idx
  on public.inventory_status_observations (property_id, observed_at desc);

comment on table public.inventory_status_observations is
  'Append-only: every change of a property''s inventory_status, with the source wording and basis. Written by scripts/inventory_status_writer.py; never edited.';

alter table public.inventory_status_observations enable row level security;
drop policy if exists "inventory_status_observations: approved read" on public.inventory_status_observations;
create policy "inventory_status_observations: approved read"
  on public.inventory_status_observations
  as permissive
  for select
  to authenticated
  using (public.is_approved());

revoke all on table public.inventory_status_observations from public, anon, authenticated;
grant select on table public.inventory_status_observations to authenticated;
grant select, insert on table public.inventory_status_observations to service_role;
revoke all on sequence public.inventory_status_observations_id_seq from public, anon, authenticated;
grant usage, select on sequence public.inventory_status_observations_id_seq to service_role;

-- ---------------------------------------------------------------------------
-- 3. county_source_registry: per-unit freshness
-- ---------------------------------------------------------------------------
alter table public.county_source_registry
  add column if not exists last_attempt_at timestamptz,
  add column if not exists last_attempt_status text,
  add column if not exists last_success_at timestamptz,
  add column if not exists last_success_row_count integer,
  add column if not exists consecutive_failures integer not null default 0;

alter table public.county_source_registry drop constraint if exists county_source_registry_last_attempt_status_check;
alter table public.county_source_registry add constraint county_source_registry_last_attempt_status_check
  check (last_attempt_status is null or last_attempt_status in ('COMPLETE', 'EMPTY', 'INCOMPLETE', 'FAILED'));
alter table public.county_source_registry drop constraint if exists county_source_registry_consecutive_failures_check;
alter table public.county_source_registry add constraint county_source_registry_consecutive_failures_check
  check (consecutive_failures >= 0);

comment on column public.county_source_registry.last_attempt_at is
  'When a harvester last attempted this unit (scripts/unit_freshness.py). NULL = never attempted since this column existed.';
comment on column public.county_source_registry.last_attempt_status is
  'The harvester''s own status for the last attempt: COMPLETE / EMPTY (an authoritative read), INCOMPLETE (read, not trusted as a whole list), FAILED (no observation).';
comment on column public.county_source_registry.last_success_at is
  'The last COMPLETE or EMPTY read - the last-known-good observation. Never advanced by a FAILED or INCOMPLETE attempt.';
comment on column public.county_source_registry.last_success_row_count is
  'Row count at last_success_at.';
comment on column public.county_source_registry.consecutive_failures is
  'FAILED attempts in a row since the last non-failed one; drives the harvesters'' back-off so a blocked source is not hammered.';

-- ---------------------------------------------------------------------------
-- 4. get_properties(): drop the exact live (019) signature, re-create with
--    six columns appended. Everything before them is byte-for-byte 019's
--    list; WHERE/ORDER/LIMIT/OFFSET unchanged.
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
  field_provenance jsonb, otc_provenance jsonb
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
    field_provenance, otc_provenance
  from public.properties
  where state = p_state
    and (p_ledger_type is null or ledger_type = p_ledger_type)
    and (p_status is null or status = p_status)
  order by county, case_no
  limit p_limit
  offset p_offset;
$function$;

-- 015 pins search_path on this function; re-pin here so the order of 015
-- and 021 does not matter.
alter function public.get_properties(text, text, text, integer, integer) set search_path = public;

grant execute on function public.get_properties(text, text, text, integer, integer)
  to anon, authenticated, service_role;

commit;
