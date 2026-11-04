-- Scratch fixture for migration 026 (tests/python/test_migration_026_properties_rls_initplan.py).
-- The live `properties` column list, indexes, policy and the byte-for-byte
-- production definitions of auth.uid() and is_approved() (read 2026-10-04),
-- with SYNTHETIC rows. Followed by migration 025's get_properties().

do $$ begin
  if not exists (select 1 from pg_roles where rolname='anon') then create role anon nologin; end if;
  if not exists (select 1 from pg_roles where rolname='authenticated') then create role authenticated nologin; end if;
  if not exists (select 1 from pg_roles where rolname='service_role') then create role service_role nologin bypassrls; end if;
end $$;
grant usage on schema public to anon, authenticated, service_role;
create schema if not exists auth;
grant usage on schema auth to anon, authenticated, service_role;
create or replace function auth.uid() returns uuid language sql stable as $function$
  select
  coalesce(
    nullif(current_setting('request.jwt.claim.sub', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
  )::uuid
$function$;
create table public.profiles (id uuid primary key, approved boolean not null default false, is_admin boolean not null default false);
alter table public.profiles enable row level security;
-- byte-for-byte production definition (VOLATILE, SECURITY DEFINER)
create or replace function public.is_approved() returns boolean language sql security definer set search_path to 'public'
as $function$
  select coalesce((select approved from public.profiles where id = auth.uid()), false);
$function$;
insert into public.profiles values
 ('11111111-1111-1111-1111-111111111111', true, true),   -- approved admin
 ('22222222-2222-2222-2222-222222222222', true, false),  -- approved customer
 ('33333333-3333-3333-3333-333333333333', false, false); -- pending
create table public.properties (
id uuid primary key default gen_random_uuid(),
source text,
county text,
case_no text,
parcel text,
owner_name text,
address text,
bid numeric,
assessed numeric,
market numeric,
status text,
lien_level text,
lien_note text,
prop_type text,
sale_date date,
homestead boolean,
url_streetview text,
url_appraiser text,
url_zillow text,
url_taxcoll text,
url_auction text,
url_title text,
updated_at timestamp with time zone,
gone_since timestamp with time zone,
interest_rate numeric,
certificate_no text,
tax_year text,
issued_date date,
expiration_date date,
latitude double precision,
longitude double precision,
year_built integer,
living_area integer,
lot_sqft integer,
land_value numeric,
legal_desc text,
last_sale_price numeric,
last_sale_year integer,
value_year integer,
num_buildings integer,
fdor_enriched_at timestamp with time zone,
state text,
tx_category text,
redemption_period_months integer,
redemption_expiration_date date,
max_statutory_return_usd numeric,
min_bid numeric,
ledger_type text,
harvester_source text,
dor_use_code text,
photo_url text,
taxable_value numeric,
improvement_value numeric,
land_use text,
acreage numeric,
field_provenance jsonb,
last_sale_month smallint,
last_sale_qual_code text,
last_sale_vi_code text,
last_sale_or_book text,
last_sale_or_page text,
last_sale_clerk_no text,
prior_sale_price numeric,
prior_sale_year integer,
prior_sale_month smallint,
prior_sale_qual_code text,
effective_year_built integer,
num_res_units integer,
fdor_alt_key text,
flood_zone text,
flood_checked_at timestamp with time zone,
flood_zone_subtype text,
flood_sfha boolean,
flood_bfe numeric,
flood_firm_id text,
photo_source text,
photo_captured_year integer,
photo_checked_at timestamp with time zone,
url_auction_kind text,
tx_sale_status text,
inventory_type text,
source_authority text,
source_id text,
list_url text,
document_url text,
purchase_url text,
purchase_url_kind text,
purchase_amount numeric,
purchase_amount_kind text,
first_seen_at timestamp with time zone,
last_seen_at timestamp with time zone,
delisted_at timestamp with time zone,
source_published_at timestamp with time zone,
list_as_of date,
source_document_sha256 text,
source_etag text,
source_last_modified text,
otc_provenance jsonb,
escheatment_date date,
available_date date,
inventory_status text,
inventory_status_raw text,
inventory_status_basis text,
inventory_status_observed_at timestamp with time zone,
publication_status text,
purchase_path_type text,
purchase_path_scope text,
purchase_path_evidence text,
purchase_path_observed_on date,
result_amount numeric,
result_date date,
result_party text
);
alter table public.properties enable row level security;
create policy "properties: approved only" on public.properties as permissive for all to public
  using (is_approved()) with check (is_approved());
grant select, insert, update, delete on public.properties to authenticated, anon, service_role;
-- production indexes (pg_indexes, 2026-10-04)
create index idx_properties_state_county on public.properties (state, county);
create index idx_properties_state_ledger_saledate on public.properties (state, ledger_type, sale_date);
create index properties_county_idx on public.properties (county);
create index properties_publication_status_idx on public.properties (state, source, publication_status);
create index properties_purchase_path_type_idx on public.properties (state, source, purchase_path_type);
create index properties_saledate_idx on public.properties (sale_date);
create index properties_source_idx on public.properties (source);
create unique index properties_state_source_county_case_no_key on public.properties (state, source, county, case_no);
create index properties_status_idx on public.properties (status);
-- production-SHAPED rows (smaller counts so the test is quick; MI and LA still page past offset 1000)
insert into public.properties (source, ledger_type, state, county, case_no, parcel, address, status, legal_desc,
  field_provenance, otc_provenance, publication_status, sale_date, updated_at)
select s.source, s.ledger, s.state, s.county, s.prefix || lpad(g::text, 8, '0'), s.prefix || g, g || ' SYNTHETIC ST', 'active',
  repeat('LOT ' || g || ' BLOCK SYNTHETIC ', 4),
  jsonb_build_object('address', jsonb_build_object('source','county_list','evidence', repeat('e', 40))),
  jsonb_build_object('note', repeat('p', 50)), s.pub, null, now()
from (values
  ('laft','buy','MI','Wayne','W',3250,'UNREVIEWED'),
  ('laft','buy','MI','Oceana','O',5,'UNREVIEWED'),
  ('auction','auctions','MI','Lenawee','L',43,'APPROVED'),
  ('laft','buy','LA','East Baton Rouge','E',1100,'APPROVED'),
  ('auction','auctions','SC','York','Y',853,'APPROVED'),
  ('certificate','lien','CO','Douglas','D',146,'APPROVED'),
  ('auction','auctions','WY','Albany','A',253,'APPROVED'),
  ('laft','buy','TX','Harris','H',421,'APPROVED_GRANDFATHERED'),
  ('auction','auctions','TX','Harris','HA',122,null)
) s(source, ledger, state, county, prefix, n, pub), generate_series(1, s.n) g;
insert into public.properties (source, ledger_type, state, county, case_no, parcel, address, status, legal_desc,
  field_provenance, otc_provenance, publication_status, sale_date, updated_at)
select src, led, 'FL', 'County' || (g % 67), 'F' || src || lpad(g::text, 7, '0'), 'P' || g, g || ' FL ST', 'active',
  repeat('FL LEGAL ', 60), jsonb_build_object('a', repeat('x', 300)), jsonb_build_object('b', repeat('y', 300)),
  case when src = 'laft' then 'APPROVED_GRANDFATHERED' end, current_date + 30, now()
from (values ('auction','auctions',300), ('laft','buy',40), ('certificate','lien',200)) t(src, led, n), generate_series(1, t.n) g;
-- duplicate (county, case_no) pairs inside one ledger are impossible (unique key); ties on county+case_no
-- across sources are exercised by the id tie-break in get_properties.
vacuum analyze public.properties;
