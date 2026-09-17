-- Phase 50 design gap: the backend columns, tables and index the new
-- RODZ TAXDEEDS screens need, which `properties` does not have today.
--
-- Scope of this file: schema only. It adds nothing to the customer-facing
-- projection by itself - get_properties() is widened separately in
-- 008_get_properties_design_fields.sql so the API boundary change is
-- reviewable on its own.
--
-- ============================================================================
-- THE ONE DESIGN DECISION THAT MATTERS MOST
-- ============================================================================
-- The property-detail mockup renders a "Risk & Legal" panel reading:
--
--     Liens            None found
--     Judgments        None found
--     Foreclosure      No
--     Code Violations  None found
--     Flood Zone       X (No risk)
--
-- We have never checked any of those things for any property. Rendering
-- "None found" from a NULL column would tell someone about to bid real money
-- that a property is clear of liens when the truth is that nobody looked.
-- That is the "confident wrong answer" failure this project has guarded
-- against since the harvester lessons in the roadmap - and it is far more
-- dangerous here than a wrong address, because the user acts on it with cash.
--
-- So every risk field is modelled as a PAIR:
--
--     <risk>_checked_at   NULL  -> never checked        -> UI: "Not checked"
--                         set   -> a check really ran   -> UI: "None found as of <date>"
--     <risk>_count        NULL  -> unknown
--                         0     -> checked, none found
--                         n     -> n found
--
-- A NULL `liens_checked_at` must never render as "None found". The count
-- alone is not enough information to draw that panel honestly.
--
-- The same rule is why `flood_zone` gets `flood_checked_at`: an unknown flood
-- zone and a zone-X flood zone are opposite facts for a bidder.
-- ============================================================================

begin;

-- ---------------------------------------------------------------------------
-- 1. Value fields the detail panels show and `properties` lacks
-- ---------------------------------------------------------------------------
-- taxable_value is NOT assessed: Florida's assessed value is pre-exemption,
-- taxable is post-exemption, and the homestead difference between them is
-- exactly what the existing homestead-risk feature is about. Storing one and
-- labelling it the other would corrupt that calculation.
alter table public.properties add column if not exists taxable_value      numeric;
alter table public.properties add column if not exists improvement_value  numeric;
alter table public.properties add column if not exists annual_tax         numeric;
alter table public.properties add column if not exists delinquent_tax     numeric;
alter table public.properties add column if not exists acreage            numeric;
alter table public.properties add column if not exists beds               smallint;
alter table public.properties add column if not exists baths              numeric;
alter table public.properties add column if not exists land_use           text;

-- ---------------------------------------------------------------------------
-- 2. GIS & Location panel
-- ---------------------------------------------------------------------------
alter table public.properties add column if not exists zoning        text;
alter table public.properties add column if not exists municipality  text;
alter table public.properties add column if not exists subdivision   text;

-- ---------------------------------------------------------------------------
-- 3. Risk & Legal - value + proof-of-check, per the note above
-- ---------------------------------------------------------------------------
alter table public.properties add column if not exists liens_count               integer;
alter table public.properties add column if not exists liens_checked_at          timestamptz;
alter table public.properties add column if not exists judgments_count           integer;
alter table public.properties add column if not exists judgments_checked_at      timestamptz;
alter table public.properties add column if not exists code_violations_count     integer;
alter table public.properties add column if not exists code_violations_checked_at timestamptz;
alter table public.properties add column if not exists foreclosure_status        text;
alter table public.properties add column if not exists foreclosure_checked_at    timestamptz;
alter table public.properties add column if not exists flood_zone                text;
alter table public.properties add column if not exists flood_checked_at          timestamptz;

-- A count without a check date is not interpretable, so forbid the pair that
-- would let a UI render "None found" off a check that never happened.
alter table public.properties drop constraint if exists properties_risk_counts_need_a_check;
alter table public.properties add constraint properties_risk_counts_need_a_check check (
      (liens_count           is null or liens_checked_at           is not null)
  and (judgments_count       is null or judgments_checked_at       is not null)
  and (code_violations_count is null or code_violations_checked_at is not null)
  and (foreclosure_status    is null or foreclosure_checked_at     is not null)
  and (flood_zone            is null or flood_checked_at           is not null)
);

-- Counts are counts.
alter table public.properties drop constraint if exists properties_risk_counts_non_negative;
alter table public.properties add constraint properties_risk_counts_non_negative check (
      coalesce(liens_count, 0)           >= 0
  and coalesce(judgments_count, 0)       >= 0
  and coalesce(code_violations_count, 0) >= 0
);

-- ---------------------------------------------------------------------------
-- 4. Field-level provenance
-- ---------------------------------------------------------------------------
-- The detail screen's "Data Quality / Provenance" strip names a source per
-- property, but the fields on that page come from DIFFERENT sources - the bid
-- from the auction site, the values from the tax roll, the coordinates from
-- the parcel layer. One `harvester_source` per row cannot express that.
--
-- JSONB rather than a column per field: the set of enriched fields changes
-- every phase, and a provenance table would need a row per field per property
-- (~50k rows today) to carry three scalars.
--
--   { "market": {"source":"fl_dor_cadastral","source_record_id":"...",
--                "retrieved_at":"2026-09-17T..."}, ... }
alter table public.properties add column if not exists field_provenance jsonb;
alter table public.properties drop constraint if exists properties_field_provenance_is_object;
alter table public.properties add constraint properties_field_provenance_is_object check (
  field_provenance is null or jsonb_typeof(field_provenance) = 'object'
);

-- ---------------------------------------------------------------------------
-- 5. History timeline -> its own table
-- ---------------------------------------------------------------------------
-- The mockup's History panel is a sequence (auction scheduled 2026, transfer
-- 2024, previous sale 2021, recorded deed 2019). `last_sale_price` /
-- `last_sale_year` hold exactly ONE point and are overwritten by each new
-- harvest, so history cannot live on the property row without destroying
-- itself.
create table if not exists public.property_events (
  id               uuid primary key default gen_random_uuid(),
  property_id      uuid not null references public.properties(id) on delete cascade,
  event_date       date not null,
  event_type       text not null check (event_type in (
                     'AUCTION_SCHEDULED','AUCTION_RESULT','SALE','TRANSFER',
                     'DEED_RECORDED','TAX_EVENT','VALUE_CHANGE','LIEN','PERMIT',
                     'CODE_ENFORCEMENT','REDEMPTION','STATUS_CHANGE')),
  description      text,
  amount           numeric,
  -- Provenance is mandatory on an event. An undated, unsourced entry on a
  -- bidder's timeline is worse than an absent one.
  source           text not null,
  source_record_id text,
  retrieved_at     timestamptz not null default now(),
  created_at       timestamptz not null default now(),
  -- Re-harvesting the same event must update it, not stack duplicates on the
  -- timeline.
  unique (property_id, event_type, event_date, coalesce(source_record_id, ''))
);
create index if not exists property_events_property_date_idx
  on public.property_events (property_id, event_date desc);
create index if not exists property_events_type_idx
  on public.property_events (event_type);

-- ---------------------------------------------------------------------------
-- 6. Watchlist pipeline
-- ---------------------------------------------------------------------------
-- The watchlist screen is a pipeline - Watchlist -> Research -> Due Diligence
-- -> Auction -> Won/Lost -> Post-Auction - with Active / Auction Soon /
-- Researching / Completed tabs over it. `favorites` is currently just
-- (user_id, property_id, created_at) and cannot express a stage.
--
-- 'AUCTION_SOON' is deliberately NOT a stage: the mockup's "Auction Soon" tab
-- is a date filter over sale_date, not a state a user puts a property into.
-- Making it a stage would let it disagree with the calendar.
alter table public.favorites add column if not exists stage text
  not null default 'WATCHLIST';
alter table public.favorites add column if not exists stage_updated_at timestamptz
  not null default now();
alter table public.favorites drop constraint if exists favorites_stage_valid;
alter table public.favorites add constraint favorites_stage_valid check (
  stage in ('WATCHLIST','RESEARCH','DUE_DILIGENCE','AUCTION','WON','LOST','POST_AUCTION')
);

-- ---------------------------------------------------------------------------
-- 7. Geometry, so "Distance" and "Search this area" are indexable
-- ---------------------------------------------------------------------------
-- PostGIS 3.3.7 is already installed and a `properties_sync_geom()` trigger
-- function already exists, but the column it was written for does not - so
-- there is no geometry and no spatial index today. A map that filters by
-- viewport, or a list that sorts by distance, would otherwise scan the table.
--
-- geography(Point,4326) rather than geometry: ST_Distance on geography
-- returns metres on the spheroid, which is what a "2.4 mi" column needs,
-- without picking a projection per state. Generated, so it can never drift
-- from latitude/longitude.
alter table public.properties add column if not exists geog geography(Point, 4326)
  generated always as (
    case when latitude is not null and longitude is not null
         then st_setsrid(st_makepoint(longitude, latitude), 4326)::geography
    end
  ) stored;
create index if not exists properties_geog_gix on public.properties using gist (geog);

-- ---------------------------------------------------------------------------
-- 8. Dashboard trend deltas
-- ---------------------------------------------------------------------------
-- The dashboard tiles read "+12% vs last 30 days". That comparison needs
-- yesterday's numbers, which nothing records - `properties` holds only the
-- current state. One small row per metric per day.
create table if not exists public.daily_metrics (
  metric_date  date not null,
  state        text not null,
  metric       text not null,
  value        numeric not null,
  captured_at  timestamptz not null default now(),
  primary key (metric_date, state, metric)
);

commit;
