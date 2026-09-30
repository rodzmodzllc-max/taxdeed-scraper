-- Migration 023: purchase-path evidence, source-published results, the
-- reactivation transition and admin publication reviews (AVAILABLE
-- commercial release, 2026-09-30).
--
-- STATUS: PROPOSED, NOT APPLIED by this file alone. Applied to production
-- by the project owner (or with the owner's explicit authorization) after
-- review, like every file in this directory. Must be applied AFTER 022 (it
-- re-creates get_properties() from 022's exact signature and column list
-- with SEVEN columns APPENDED, and widens 022's transition check) and AFTER
-- 021 (it adds columns to inventory_status_observations). Independent of
-- 015 / 016 / 020.
--
-- WHAT IT ADDS (nothing existing is renamed, dropped, re-typed or backfilled)
--
-- 1. public.properties - the purchase path as EVIDENCE, not a guess
--      purchase_path_type          one of the ten path types
--                                  scripts/purchase_path_engine.py can
--                                  establish (direct_property_url,
--                                  county_instructions, application_page,
--                                  application_download, in_person,
--                                  phone_mail, quoted_amount, amount_plus_costs,
--                                  amount_on_application, none_published).
--                                  NULL = not yet evaluated.
--      purchase_path_scope         'property' (a link the source published for
--                                  THIS parcel) or 'source' (the source's own
--                                  process, page or wording, the same for
--                                  every parcel it lists).
--      purchase_path_evidence      the source wording / rule / registry
--                                  evidence the type rests on (never blank
--                                  when the type is set).
--      purchase_path_observed_on   the date that evidence was observed
--                                  (a rule's verified_on, a registry row's
--                                  last_checked, or the harvest date for a
--                                  link read off the list row).
--    The URL itself stays in 017's purchase_url / purchase_url_kind; a
--    non-URL type carries none. The engine refuses search engines,
--    homepages, guessed URL patterns, blocked-vendor hosts, unverified
--    third-party hosts and the list / document page itself.
--
-- 2. public.properties - a RESULT the source itself published
--      result_amount / result_date / result_party
--    Written only by scripts/outcome_ingest.py from an enabled, verified
--    column rule (data/outcome_column_rules.csv - none enabled today) or a
--    source status the writer already maps; never from absence, a date, a
--    bid or a count. result_party is written only where the source
--    publishes it AND the rule says the publication is permitted.
--
-- 3. public.inventory_status_observations
--      result_amount / result_date / result_party   the same three, on the
--                                                   history row that recorded
--                                                   the result
--      transition                                   + 'reactivated' (a row
--                                                   that had left the list and
--                                                   is on it again)
--
-- 4. public.source_publication_reviews - the admin publication governance
--    record: one row per decision (append-only), per (state, source_id):
--    publication_status, restrictions, decision_note, evidence, notes,
--    decided_by (auth.uid()), decided_at, next_review. Admins (is_admin())
--    read and insert through the app; service_role reads (the publication
--    gate applies the latest valid decision per source, validated against
--    the registry's governance state - a blocked vendor or a source under
--    legal review can never be approved by a review row); customers have
--    no access at all.
--
-- 5. get_properties(): 022's list with SEVEN columns appended -
--    purchase_path_type, purchase_path_scope, purchase_path_evidence,
--    purchase_path_observed_on, result_amount, result_date, result_party.
--    Everything before them is byte-for-byte 022's list; WHERE/ORDER/LIMIT/
--    OFFSET unchanged; search_path re-pinned; grants restated.
--
-- WHAT IT DOES NOT DO: RLS on properties is unchanged; no row is withheld
-- by the database; nothing is backfilled - the next laft run's lifecycle
-- and writer steps populate the new columns from evidence, and a row whose
-- source publishes no path reads none_published with that wording.
--
-- Rollback (by hand): re-run 022 section 4 for get_properties(); then
--   drop table if exists public.source_publication_reviews;
--   alter table public.inventory_status_observations drop column if exists result_amount, drop column if exists result_date, drop column if exists result_party;
--   alter table public.inventory_status_observations drop constraint if exists inventory_status_observations_transition_check;
--   alter table public.inventory_status_observations add constraint inventory_status_observations_transition_check check (transition is null or transition in ('newly_observed', 'status_changed', 'removed', 'result_published'));
--   alter table public.properties drop column if exists purchase_path_type, drop column if exists purchase_path_scope, drop column if exists purchase_path_evidence, drop column if exists purchase_path_observed_on, drop column if exists result_amount, drop column if exists result_date, drop column if exists result_party;

begin;

-- ---------------------------------------------------------------------------
-- 1 + 2. properties: purchase-path evidence and source-published results
-- ---------------------------------------------------------------------------
alter table public.properties
  add column if not exists purchase_path_type text,
  add column if not exists purchase_path_scope text,
  add column if not exists purchase_path_evidence text,
  add column if not exists purchase_path_observed_on date,
  add column if not exists result_amount numeric,
  add column if not exists result_date date,
  add column if not exists result_party text;

alter table public.properties drop constraint if exists properties_purchase_path_type_check;
alter table public.properties add constraint properties_purchase_path_type_check
  check (purchase_path_type is null or purchase_path_type in (
    'direct_property_url', 'county_instructions', 'application_page', 'application_download',
    'in_person', 'phone_mail', 'quoted_amount', 'amount_plus_costs', 'amount_on_application', 'none_published'));

alter table public.properties drop constraint if exists properties_purchase_path_scope_check;
alter table public.properties add constraint properties_purchase_path_scope_check
  check (purchase_path_scope is null or purchase_path_scope in ('property', 'source'));

-- A stored path type always names its evidence; a type is never a bare label.
alter table public.properties drop constraint if exists properties_purchase_path_evidence_check;
alter table public.properties add constraint properties_purchase_path_evidence_check
  check (purchase_path_type is null or (purchase_path_evidence is not null and length(purchase_path_evidence) > 0 and purchase_path_scope is not null));

-- The three URL-bearing types carry 017's purchase_url; the seven others never do.
alter table public.properties drop constraint if exists properties_purchase_path_url_check;
alter table public.properties add constraint properties_purchase_path_url_check
  check (purchase_path_type is null
         or (purchase_path_type in ('direct_property_url', 'county_instructions', 'application_page', 'application_download') and purchase_url is not null)
         or (purchase_path_type not in ('direct_property_url', 'county_instructions', 'application_page', 'application_download') and purchase_url is null));

alter table public.properties drop constraint if exists properties_result_amount_check;
alter table public.properties add constraint properties_result_amount_check
  check (result_amount is null or result_amount >= 0);

comment on column public.properties.purchase_path_type is
  'How a buyer acts on this row, as scripts/purchase_path_engine.py established it from evidence (a verified rule, the registry, or the source''s own wording). NULL = not yet evaluated; none_published = the source publishes no path. Never inferred from a list page, a homepage or a URL pattern.';
comment on column public.properties.purchase_path_scope is
  'property = a link the source published for this parcel; source = the source''s process / page / wording, the same for every parcel it lists.';
comment on column public.properties.purchase_path_evidence is
  'The evidence the path type rests on: the rule and its verification date, the registry evidence, or the source wording.';
comment on column public.properties.purchase_path_observed_on is
  'The date the purchase-path evidence was observed (never the retrieval time of the row).';
comment on column public.properties.result_amount is
  'A sale / purchase result amount the SOURCE published (scripts/outcome_ingest.py, from an enabled verified column rule). Never a bid, a minimum or an estimate.';
comment on column public.properties.result_date is
  'The date of the source-published result.';
comment on column public.properties.result_party is
  'The buyer / bidder as the source published it, written only where the rule says publishing it is permitted.';

create index if not exists properties_purchase_path_type_idx
  on public.properties (state, source, purchase_path_type);

-- Customers may read the columns (015's column grant lists are additive).
grant select (purchase_path_type, purchase_path_scope, purchase_path_evidence, purchase_path_observed_on,
              result_amount, result_date, result_party) on public.properties to authenticated;

-- ---------------------------------------------------------------------------
-- 3. inventory_status_observations: results on the history row; reactivation
-- ---------------------------------------------------------------------------
alter table public.inventory_status_observations
  add column if not exists result_amount numeric,
  add column if not exists result_date date,
  add column if not exists result_party text;

alter table public.inventory_status_observations drop constraint if exists inventory_status_observations_transition_check;
alter table public.inventory_status_observations add constraint inventory_status_observations_transition_check
  check (transition is null or transition in ('newly_observed', 'status_changed', 'removed', 'result_published', 'reactivated'));

alter table public.inventory_status_observations drop constraint if exists inventory_status_observations_result_amount_check;
alter table public.inventory_status_observations add constraint inventory_status_observations_result_amount_check
  check (result_amount is null or result_amount >= 0);

comment on column public.inventory_status_observations.transition is
  'newly_observed (first status for the row) / status_changed / removed (left the list, closed) / result_published (a result the source itself published) / reactivated (back on the list after a removal). Never derived from absence: a removed row is closed, not sold. "Continued" observations are not stored per run - properties.last_seen_at carries the last read.';

grant select (result_amount, result_date, result_party) on public.inventory_status_observations to authenticated;

-- ---------------------------------------------------------------------------
-- 4. source_publication_reviews: the admin governance record
-- ---------------------------------------------------------------------------
create table if not exists public.source_publication_reviews (
  id                 bigint      generated always as identity primary key,
  state              text        not null check (state ~ '^[A-Z]{2}$'),
  source_id          text        not null,
  publication_status text        not null
                     check (publication_status in ('APPROVED', 'APPROVED_GRANDFATHERED', 'UNREVIEWED', 'RESTRICTED', 'BLOCKED')),
  restrictions       text,
  decision_note      text,
  evidence           text,
  notes              text,
  decided_by         uuid        not null default auth.uid(),
  decided_at         timestamptz not null default now(),
  next_review        date,
  created_at         timestamptz not null default now(),
  constraint source_publication_reviews_restricted_reason_check
    check (publication_status <> 'RESTRICTED' or (restrictions is not null and length(restrictions) > 0)),
  constraint source_publication_reviews_evidence_check
    check (publication_status not in ('APPROVED', 'APPROVED_GRANDFATHERED') or (evidence is not null and length(evidence) > 0))
);
create index if not exists source_publication_reviews_source_idx
  on public.source_publication_reviews (state, source_id, decided_at desc);

comment on table public.source_publication_reviews is
  'Append-only admin decisions on whether a SOURCE may be published to customers. The latest row per (state, source_id) is applied by scripts/publication_gate.py after validation against the registry''s governance state (a blocked vendor or a source under legal review is never approved by a review row). Not visible to customers.';

alter table public.source_publication_reviews enable row level security;
drop policy if exists "source_publication_reviews: admin read" on public.source_publication_reviews;
create policy "source_publication_reviews: admin read"
  on public.source_publication_reviews
  as permissive
  for select
  to authenticated
  using (public.is_admin());
drop policy if exists "source_publication_reviews: admin insert" on public.source_publication_reviews;
create policy "source_publication_reviews: admin insert"
  on public.source_publication_reviews
  as permissive
  for insert
  to authenticated
  with check (public.is_admin() and decided_by = auth.uid());

revoke all on table public.source_publication_reviews from public, anon, authenticated;
grant select, insert on table public.source_publication_reviews to authenticated;
grant select on table public.source_publication_reviews to service_role;
revoke all on sequence public.source_publication_reviews_id_seq from public, anon, authenticated;
grant usage, select on sequence public.source_publication_reviews_id_seq to authenticated, service_role;

-- ---------------------------------------------------------------------------
-- 5. get_properties(): drop the exact live (022) signature, re-create with
--    SEVEN columns appended. Everything before them is byte-for-byte 022's
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
  field_provenance jsonb, otc_provenance jsonb,
  -- 022: the source's customer-publication decision
  publication_status text,
  -- 023: purchase-path evidence and source-published results
  purchase_path_type text, purchase_path_scope text, purchase_path_evidence text,
  purchase_path_observed_on date,
  result_amount numeric, result_date date, result_party text
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
    publication_status,
    purchase_path_type, purchase_path_scope, purchase_path_evidence,
    purchase_path_observed_on,
    result_amount, result_date, result_party
  from public.properties
  where state = p_state
    and (p_ledger_type is null or ledger_type = p_ledger_type)
    and (p_status is null or status = p_status)
  order by county, case_no
  limit p_limit
  offset p_offset;
$function$;

-- 015 pins search_path on this function; re-pin here so the order of 015
-- and 023 does not matter.
alter function public.get_properties(text, text, text, integer, integer) set search_path = public;

grant execute on function public.get_properties(text, text, text, integer, integer)
  to anon, authenticated, service_role;

commit;
