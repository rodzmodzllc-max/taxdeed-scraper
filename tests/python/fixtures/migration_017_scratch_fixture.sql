-- Stand-in for the parts of the production database migrations 017 and 018
-- touch, so both files can be applied VERBATIM to an isolated scratch
-- database (a local PostgreSQL cluster, never the Supabase project) and
-- their behaviour checked for real. The properties table carries every
-- column migration 013's get_properties() projects (017 re-creates that
-- function from 013's exact list, so the columns must exist), the live
-- trigger shapes for updated_at / gone_since / ledger_type, the 013
-- get_properties() signature, and the is_approved() gate. Nothing here is
-- ever run against production.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin bypassrls;
  end if;
end $$;

grant usage on schema public to anon, authenticated, service_role;
alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;
alter default privileges in schema public grant execute on functions to anon, authenticated, service_role;

-- ---- auth ----
create schema if not exists auth;
grant usage on schema auth to anon, authenticated, service_role;
create table auth.users (id uuid primary key, email text);
create or replace function auth.uid() returns uuid
language sql stable
as $$
  select (nullif(current_setting('request.jwt.claims', true), '')::json ->> 'sub')::uuid
$$;

-- ---- profiles + gate ----
create table public.profiles (
  id        uuid primary key references auth.users(id) on delete cascade,
  approved  boolean not null default false,
  is_admin  boolean not null default false
);
create or replace function public.is_approved() returns boolean
language sql stable security definer
set search_path to 'public'
as $$
  select coalesce((select approved from public.profiles where id = auth.uid()), false)
$$;

create or replace function public.touch_updated_at() returns trigger
language plpgsql as $$ begin new.updated_at := now(); return new; end $$;
create or replace function public.track_gone_since() returns trigger
language plpgsql as $$
begin
  if new.status in ('dropped','sold','notfound','closed') and (old.status is null or old.status not in ('dropped','sold','notfound','closed')) then
    new.gone_since := now();
  elsif new.status not in ('dropped','sold','notfound','closed') then
    new.gone_since := null;
  end if;
  return new;
end $$;
create or replace function public.sync_ledger_type_from_source() returns trigger
language plpgsql as $$
begin
  new.ledger_type := case new.source when 'auction' then 'auctions' when 'laft' then 'buy' when 'certificate' then 'certificates' else new.ledger_type end;
  return new;
end $$;

-- ---- properties: every column 013's projection names, live trigger shape ----
create table public.properties (
  id uuid primary key default gen_random_uuid(),
  state text, county text not null, source text not null, harvester_source text,
  address text not null default '', parcel text, case_no text not null, owner_name text,
  status text not null default 'active', prop_type text, dor_use_code text, tx_category text,
  lien_level text, lien_note text, homestead boolean, bid numeric not null default 0, assessed numeric,
  market numeric, value_year integer, min_bid numeric, redemption_period_months integer,
  redemption_expiration_date date, max_statutory_return_usd numeric, year_built integer,
  living_area integer, lot_sqft integer, num_buildings integer, land_value numeric,
  legal_desc text, last_sale_price numeric, last_sale_year integer, sale_date date,
  certificate_no text, tax_year text, issued_date date, expiration_date date,
  interest_rate numeric, latitude double precision, longitude double precision,
  url_appraiser text, url_auction text, url_taxcoll text, url_title text, url_streetview text,
  url_zillow text, gone_since timestamptz, updated_at timestamptz not null default now(),
  photo_url text, photo_source text, photo_captured_year integer, flood_zone text,
  flood_zone_subtype text, flood_sfha boolean, flood_bfe numeric, flood_firm_id text,
  flood_checked_at timestamptz, taxable_value numeric, improvement_value numeric,
  acreage numeric, land_use text, effective_year_built integer, num_res_units integer,
  -- 009: internal per-column provenance (written since the 2026-09-29 enrichment phase)
  field_provenance jsonb,
  last_sale_month smallint, last_sale_qual_code text, last_sale_vi_code text,
  last_sale_or_book text, last_sale_or_page text, last_sale_clerk_no text,
  prior_sale_price numeric, prior_sale_year integer, prior_sale_month smallint,
  prior_sale_qual_code text, url_auction_kind text, tx_sale_status text, ledger_type text,
  constraint properties_state_source_county_case_no_key unique (state, source, county, case_no),
  constraint properties_url_auction_kind_check check (url_auction_kind is null or url_auction_kind in ('property', 'sale', 'county', 'info'))
);
alter table public.properties enable row level security;
create policy "properties: approved only" on public.properties
  as permissive for select to authenticated using (public.is_approved());
-- 005a: anon has no SELECT; authenticated's SELECT is column-level, on the
-- explicit list every projected column belongs to (013 added its two).
revoke select on public.properties from anon, authenticated;
grant select (id, state, county, source, harvester_source, address, parcel, case_no, owner_name, status,
              prop_type, dor_use_code, tx_category, lien_level, lien_note, homestead, bid, assessed, market,
              value_year, min_bid, redemption_period_months, redemption_expiration_date, max_statutory_return_usd,
              year_built, living_area, lot_sqft, num_buildings, land_value, legal_desc, last_sale_price,
              last_sale_year, sale_date, certificate_no, tax_year, issued_date, expiration_date, interest_rate,
              latitude, longitude, url_appraiser, url_auction, url_taxcoll, url_title, url_streetview, url_zillow,
              gone_since, updated_at, photo_url, photo_source, photo_captured_year, flood_zone, flood_zone_subtype,
              flood_sfha, flood_bfe, flood_firm_id, flood_checked_at, taxable_value, improvement_value, acreage,
              land_use, effective_year_built, num_res_units, last_sale_month, last_sale_qual_code, last_sale_vi_code,
              last_sale_or_book, last_sale_or_page, last_sale_clerk_no, prior_sale_price, prior_sale_year,
              prior_sale_month, prior_sale_qual_code, url_auction_kind, tx_sale_status, ledger_type)
  on public.properties to authenticated;
create trigger properties_touch before update on public.properties for each row execute function public.touch_updated_at();
create trigger properties_gone_since before insert or update on public.properties for each row execute function public.track_gone_since();
create trigger trg_sync_ledger_type_from_source before insert or update on public.properties for each row execute function public.sync_ledger_type_from_source();

-- 013's exact live signature (body reduced to a few columns; 017 replaces it wholesale).
create function public.get_properties(
  p_state text, p_ledger_type text default null, p_status text default null,
  p_limit integer default 20000, p_offset integer default 0)
returns table (id uuid, state text, county text, source text, case_no text, status text, bid numeric)
language sql stable
as $$
  select id, state, county, source, case_no, status, bid from public.properties
  where state = p_state and (p_ledger_type is null or ledger_type = p_ledger_type)
    and (p_status is null or status = p_status)
  order by county, case_no limit p_limit offset p_offset
$$;
grant execute on function public.get_properties(text, text, text, integer, integer) to anon, authenticated, service_role;

-- ---- seed: one approved customer, one pending ----
insert into auth.users (id, email) values
  ('11111111-1111-1111-1111-111111111111', 'a@example.com'),
  ('33333333-3333-3333-3333-333333333333', 'pending@example.com');
insert into public.profiles (id, approved) values
  ('11111111-1111-1111-1111-111111111111', true),
  ('33333333-3333-3333-3333-333333333333', false);

-- Rows shaped like the writers actually write them (2026-09-29 state):
--   FL laft, bid sentinel 0 (Marion publishes no price); FL laft with a price;
--   FL laft in a county no registry row covers; TX LGBS laft with raw status,
--   TX LGBS laft without (pre-013 row, the 421 case); TX RealAuction auction;
--   TX LGBS auction; FL auction; FL certificate.
insert into public.properties (id, state, source, county, case_no, address, bid, status, url_auction, url_auction_kind, harvester_source, tx_sale_status, min_bid) values
  ('aaaaaaaa-0000-0000-0000-000000000001', 'FL', 'laft', 'Marion', '2026-011', 'Parcel 1', 0, 'active', 'https://www.marioncountyclerk.org/uploads/2026/07/LAT-List-updated3.13.2026-1.pdf', 'county', null, null, null),
  ('aaaaaaaa-0000-0000-0000-000000000002', 'FL', 'laft', 'Putnam', 'TD-9', 'Lot 9', 1234.56, 'active', 'https://apps.putnam-fl.com/coc/taxdeeds/public/public_LAFT.php', 'county', null, null, null),
  ('aaaaaaaa-0000-0000-0000-000000000003', 'FL', 'laft', 'Nowhere', 'X-1', 'Lot X', 0, 'available', null, null, null, null, null),
  ('aaaaaaaa-0000-0000-0000-000000000004', 'TX', 'laft', 'Galveston', '129500040015000', 'VACANT LOT', 4451.95, 'active', null, null, 'tx_lgbs', 'Struck off to Jurisdiction', 4451.95),
  ('aaaaaaaa-0000-0000-0000-000000000005', 'TX', 'laft', 'Liberty', '000016000361003', 'TRACT 3', 900, 'active', null, null, 'tx_lgbs', null, 900),
  ('aaaaaaaa-0000-0000-0000-000000000006', 'TX', 'laft', 'Hardin', 'H-1', 'TRACT H', 500, 'active', null, null, 'tx_lgbs', 'Available for Future Sale', 500),
  ('aaaaaaaa-0000-0000-0000-000000000007', 'TX', 'auction', 'Dallas', 'D-1', '1 Main', 7000, 'active', 'https://dallas.texas.sheriffsaleauctions.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=10/07/2026', 'sale', 'tx_realauction', null, 7000),
  ('aaaaaaaa-0000-0000-0000-000000000008', 'TX', 'auction', 'Concho', 'C-1', '2 Main', 100, 'active', null, null, 'tx_lgbs', 'Scheduled for Auction', 100),
  ('aaaaaaaa-0000-0000-0000-000000000009', 'FL', 'auction', 'Alachua', 'A-1', '3 Main', 5000, 'active', 'https://alachua.realforeclose.com/index.cfm?zaction=AUCTION&zmethod=PREVIEW&AuctionDate=10/07/2026', 'sale', null, null, null),
  ('aaaaaaaa-0000-0000-0000-000000000010', 'FL', 'certificate', 'Bay', 'CERT-1', 'Account CERT-1', 250, 'active', 'https://lienhub.com/county/bay', 'county', null, null, null);
