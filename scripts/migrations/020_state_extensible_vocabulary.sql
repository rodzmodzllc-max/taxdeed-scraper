-- Migration 020: the vocabulary and registry columns a third state needs
-- (Alabama onboarding foundation, 2026-09-29).
--
-- STATUS: PROPOSED, NOT APPLIED. Applied by hand by the project owner after
-- review, like every file in this directory. Must be applied AFTER 017 and
-- 018 (it replaces their check constraints and adds columns to 018's
-- table). Independent of 015/016/019.
--
-- WHAT IT CHANGES, AND WHAT IT DOES NOT
--
-- 1. public.properties: the inventory-type and purchase-amount-kind check
--    constraints are WIDENED with the values the code has carried since
--    the framework generalization (POST_SALE, STATE_HELD_TAX_LAND,
--    ADJUDICATED_PROPERTY; QUOTED_ON_APPLICATION). The amount-semantics
--    constraint learns that QUOTED_ON_APPLICATION, like NOT_PUBLISHED,
--    carries NO amount. Every existing FL/TX row satisfies the new
--    constraints unchanged (they only add allowed values).
-- 2. public.county_source_registry: the FL/TX-only state check becomes
--    "two capital letters" (the registered-state rule lives in code,
--    harvesters/governance/states.py); the inventory-type check is widened
--    the same way; five columns are added - publishing_unit (default
--    COUNTY), publishing_unit_name, amount_kind, update_frequency,
--    source_terminology - matching data/county_source_registry.csv's
--    EXTENDED_COLUMNS.
-- 3. NOTHING is inserted, updated or backfilled. No Alabama row exists in
--    either table after this migration; activation is a separate, explicit
--    decision (docs/alabama-onboarding.md).
--
-- Rollback (by hand): re-run 017 section 3 constraints for properties;
-- for the registry, drop the five columns and re-create the 018 checks.

begin;

-- ---------------------------------------------------------------------------
-- 1. properties: widened vocabulary
-- ---------------------------------------------------------------------------
alter table public.properties drop constraint if exists properties_inventory_type_check;
alter table public.properties add constraint properties_inventory_type_check
  check (inventory_type is null or inventory_type in (
    'POST_SALE_FIXED_PRICE', 'STRUCK_OFF_HELD_IN_TRUST', 'FUTURE_RESALE',
    'POST_SALE', 'STATE_HELD_TAX_LAND', 'ADJUDICATED_PROPERTY'));

alter table public.properties drop constraint if exists properties_purchase_amount_kind_check;
alter table public.properties add constraint properties_purchase_amount_kind_check
  check (purchase_amount_kind is null or purchase_amount_kind in (
    'MINIMUM_PURCHASE_AMOUNT', 'OPENING_BID', 'ORIGINAL_OPENING_BID', 'FIXED_PURCHASE_PRICE',
    'ESTIMATED_PURCHASE_PRICE', 'PUBLISHED_AMOUNT_KIND_UNSPECIFIED', 'NOT_PUBLISHED',
    'QUOTED_ON_APPLICATION'));

-- "Not published" and "quoted on application" are NULL + their kind, never
-- 0; any other kind always carries an amount.
alter table public.properties drop constraint if exists properties_purchase_amount_semantics_check;
alter table public.properties add constraint properties_purchase_amount_semantics_check
  check (
    (purchase_amount is null and (purchase_amount_kind is null or purchase_amount_kind in ('NOT_PUBLISHED', 'QUOTED_ON_APPLICATION')))
    or (purchase_amount is not null and purchase_amount_kind is not null
        and purchase_amount_kind not in ('NOT_PUBLISHED', 'QUOTED_ON_APPLICATION'))
  );

comment on column public.properties.inventory_type is
  'POST_SALE_FIXED_PRICE (FL Lands Available: purchasable now at a set price) | STRUCK_OFF_HELD_IN_TRUST (TX: struck off to the taxing units, held in trust) | FUTURE_RESALE (TX: awaiting a future resale) | POST_SALE (post-sale inventory without a published fixed price / process) | STATE_HELD_TAX_LAND (forfeited to and sold by a state agency) | ADJUDICATED_PROPERTY (adjudicated to a parish / municipality). NULL = not classified; never assume.';
comment on column public.properties.purchase_amount_kind is
  'What purchase_amount IS, from the source''s own label. NOT_PUBLISHED and QUOTED_ON_APPLICATION (the price is quoted to an applicant) carry no amount.';

-- ---------------------------------------------------------------------------
-- 2. county_source_registry: any registered state, wider inventory types,
--    publishing-unit and semantics columns
-- ---------------------------------------------------------------------------
alter table public.county_source_registry drop constraint if exists county_source_registry_state_check;
alter table public.county_source_registry add constraint county_source_registry_state_check
  check (state ~ '^[A-Z]{2}$');

alter table public.county_source_registry drop constraint if exists county_source_registry_inventory_type_check;
alter table public.county_source_registry add constraint county_source_registry_inventory_type_check
  check (inventory_type is null or inventory_type in (
    'POST_SALE_FIXED_PRICE', 'STRUCK_OFF_HELD_IN_TRUST', 'FUTURE_RESALE',
    'POST_SALE', 'STATE_HELD_TAX_LAND', 'ADJUDICATED_PROPERTY'));

alter table public.county_source_registry
  add column if not exists publishing_unit text not null default 'COUNTY',
  add column if not exists publishing_unit_name text,
  add column if not exists amount_kind text,
  add column if not exists update_frequency text,
  add column if not exists source_terminology text;

alter table public.county_source_registry drop constraint if exists county_source_registry_publishing_unit_check;
alter table public.county_source_registry add constraint county_source_registry_publishing_unit_check
  check (publishing_unit in ('COUNTY', 'PARISH', 'BOROUGH', 'MUNICIPALITY', 'STATE'));

-- A statewide publisher has no county: the row says STATEWIDE and names the agency.
alter table public.county_source_registry drop constraint if exists county_source_registry_statewide_check;
alter table public.county_source_registry add constraint county_source_registry_statewide_check
  check ((publishing_unit = 'STATE') = (county = 'STATEWIDE'));
alter table public.county_source_registry drop constraint if exists county_source_registry_state_unit_named_check;
alter table public.county_source_registry add constraint county_source_registry_state_unit_named_check
  check (publishing_unit <> 'STATE' or publishing_unit_name is not null);

alter table public.county_source_registry drop constraint if exists county_source_registry_amount_kind_check;
alter table public.county_source_registry add constraint county_source_registry_amount_kind_check
  check (amount_kind is null or amount_kind in (
    'MINIMUM_PURCHASE_AMOUNT', 'OPENING_BID', 'ORIGINAL_OPENING_BID', 'FIXED_PURCHASE_PRICE',
    'ESTIMATED_PURCHASE_PRICE', 'PUBLISHED_AMOUNT_KIND_UNSPECIFIED', 'NOT_PUBLISHED',
    'QUOTED_ON_APPLICATION'));

comment on column public.county_source_registry.publishing_unit is
  'The kind of government unit this row describes: COUNTY (FL, TX), PARISH, BOROUGH, MUNICIPALITY or STATE (county = STATEWIDE, publishing_unit_name = the agency).';
comment on column public.county_source_registry.publishing_unit_name is
  'The publisher a non-county unit names (e.g. a state agency). NULL for a county row.';
comment on column public.county_source_registry.amount_kind is
  'What a figure this source publishes IS (the purchase_amount_kind vocabulary); NULL = not established.';
comment on column public.county_source_registry.update_frequency is
  'The source''s own stated update cadence, when established from the source itself. NULL = not established.';
comment on column public.county_source_registry.source_terminology is
  'The source''s own words for the inventory, kept beside the normalized inventory_type.';

commit;
