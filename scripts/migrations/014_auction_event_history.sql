-- Phase A of the auction-event history plan: the schema foundation, and
-- nothing else.
--
-- WHY THIS EXISTS
--
-- `properties` holds one row per (state, source, county, case_no) and every
-- sync upserts into that same row, so a property re-offered under a new sale
-- date overwrites the previous listing and its status. The 2026-09-25
-- read-only audit measured the consequence: 876 Florida auction rows have a
-- sale date in the past and not one of them carries an observed outcome.
-- `status='closed'` means only "no longer on the county's waiting feed after
-- its sale date"; it cannot tell sold from redeemed from cancelled, and 17
-- rows that were re-listed under a later date are still marked closed.
--
-- This migration adds two tables that let a future writer keep each
-- scheduled sale as its own record and keep what the source showed each time
-- it was looked at. It ADDS ONLY. It does not alter `properties`, any
-- existing column, constraint, trigger, index, policy or function, and it
-- does not alter or call `get_properties()`. It inserts nothing: both tables
-- are created empty and stay empty until a separately authorized phase adds
-- writers.
--
-- WHAT IS NOT HERE, DELIBERATELY
--
--   - No writers, no seed from `properties`, no backfill.
--   - No outcomes table, no bids table, no bidder-participation table, no raw
--     JSON snapshots. `auction_event_observations` is the append-only record
--     of what a source showed; that is the only history kept in this phase.
--   - No winner, purchaser or bidder identity. `winning_bidder_ref` exists as
--     a nullable column so the shape is settled, and must stay NULL until the
--     data-handling review recorded in docs/production-data-contract.md
--     Section 26 has cleared what may be stored in it.
--   - No analytics function. Rates that depend on outcome coverage are not
--     computable from empty tables and no RPC is created to suggest they are.
--
-- IDENTITY
--
--   Property identity stays `properties.id` (natural key (state, source,
--   county, case_no), unchanged). Event identity is (property_id,
--   scheduled_sale_date): every source that has an event keys it by a sale
--   date (RealAuction calendar day, LGBS sale_date_only) and none publishes a
--   per-property auction id. A re-listing under a new date is therefore a new
--   event row, never an overwrite. The URL, the county spelling, the
--   case-number formatting and the parcel are NOT identity - each has changed
--   shape in this project's history and none is unique per sale.
--
-- VOCABULARIES (normalized; the raw source string is kept beside them)
--
--   lifecycle: scheduled | completed | cancelled | withdrawn | stayed |
--              pending_result | superseded | unknown
--   outcome:   sold | redeemed | struck_off | future_sale | no_sale | unknown
--
--   "closed", "active" and "left the feed" are property-status words, not
--   outcomes, and are not in either list. A listing that disappears from a
--   feed after its sale date is lifecycle 'completed' with outcome 'unknown'
--   until a source actually says what happened. 'unknown' stays 'unknown'.
--
-- ACCESS
--
--   Same posture as every ledger table: RLS enabled, and exactly one
--   PERMISSIVE policy per table, for SELECT, to `authenticated`, gated on
--   public.is_approved(). No INSERT/UPDATE/DELETE policy exists, so no client
--   role can write through the API at all; the future writers run as
--   service_role (which bypasses RLS), the same way every sync script already
--   writes `properties`. The policies are PERMISSIVE on purpose - a table
--   whose only policy is RESTRICTIVE returns nothing to anyone (the 2026-08-24
--   outage, see CLAUDE.md).
--
--   Grants are stated explicitly rather than inherited from the project's
--   default privileges, so what each role can do is exactly what this file
--   says: anon nothing, authenticated SELECT only, service_role full DML.
--
-- REVERSIBILITY
--
--   Dropping `auction_event_observations` then `auction_events` (in that
--   order, because of the FK) restores the previous schema exactly; nothing
--   else in the database references either table. No separate rollback file
--   is kept - this repository's convention (see 006, 012, 013) is a single
--   forward migration.

begin;

-- ---------------------------------------------------------------------------
-- 1. auction_events - one row per scheduled sale of one property.
-- ---------------------------------------------------------------------------
create table public.auction_events (
  id                     uuid        primary key default gen_random_uuid(),
  -- The property this sale is of. RESTRICT: a property with recorded sale
  -- history must not be silently deleted; the history is the point.
  property_id            uuid        not null references public.properties(id) on delete restrict,
  -- Denormalized from properties at event creation so analytics group
  -- without a join and so a later rename of the property row cannot rewrite
  -- history. Immutable once written.
  state                  text        not null,
  source                 text        not null,
  harvester_source       text,
  county                 text        not null,
  case_no                text        not null,
  ledger_type            text,
  -- The event key (with property_id). The date the source scheduled the
  -- sale for. Immutable: a changed date is a new event, and the old one is
  -- marked lifecycle 'superseded'.
  scheduled_sale_date    date        not null,
  -- Where the event was observed and what that page is. Same vocabulary as
  -- properties.url_auction_kind (migration 013) but a separate, event-level
  -- value: the property's current link and the page a past sale was read
  -- from are different facts.
  event_url              text,
  event_url_kind         text,
  -- The opening / minimum bid at first observation. A snapshot, not a live
  -- mirror of properties.bid, so a later re-listing cannot change the
  -- denominator of a premium computed for this event.
  opening_bid            numeric,
  -- Normalized current state of the event, derived from observations.
  lifecycle              text        not null default 'scheduled',
  outcome                text        not null default 'unknown',
  -- The source's own status string, verbatim, for the observation that set
  -- the current outcome. Normalization can be re-derived from it.
  outcome_raw            text,
  -- When this pipeline saw the resolution, and the date the source says it
  -- took effect if the source publishes one. Both null until observed.
  outcome_observed_at    timestamptz,
  outcome_effective_date date,
  -- Economics. Null until a source provides them; no source in this
  -- pipeline does today.
  winning_bid            numeric,
  bid_count              integer,
  -- Reserved. Must remain NULL in this phase (see header).
  winning_bidder_ref     text,
  -- The provider's own event identifier when one exists. None of the current
  -- sources publishes one; null is the honest value, never a composed string.
  source_event_ref       text,
  -- Feed-presence window: first and most recent sighting on the source.
  first_seen_at          timestamptz not null default now(),
  last_seen_at           timestamptz not null default now(),
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),

  constraint auction_events_property_sale_date_key
    unique (property_id, scheduled_sale_date),
  constraint auction_events_lifecycle_check
    check (lifecycle in ('scheduled', 'completed', 'cancelled', 'withdrawn', 'stayed', 'pending_result', 'superseded', 'unknown')),
  constraint auction_events_outcome_check
    check (outcome in ('sold', 'redeemed', 'struck_off', 'future_sale', 'no_sale', 'unknown')),
  constraint auction_events_event_url_kind_check
    check (event_url_kind is null or event_url_kind in ('property', 'sale', 'county', 'info')),
  constraint auction_events_bid_count_check
    check (bid_count is null or bid_count >= 0),
  constraint auction_events_seen_window_check
    check (last_seen_at >= first_seen_at)
);

comment on table public.auction_events is
  'One row per scheduled sale of one property (identity: property_id + scheduled_sale_date). Written only by service_role pipelines in a later phase; empty until then. lifecycle/outcome are normalized from auction_event_observations; outcome_raw keeps the source wording. An event that left its feed is completed/unknown, never sold.';
comment on column public.auction_events.scheduled_sale_date is
  'Event key with property_id. Immutable; a changed date is a new event and the prior one becomes lifecycle superseded.';
comment on column public.auction_events.lifecycle is
  'scheduled | completed | cancelled | withdrawn | stayed | pending_result | superseded | unknown';
comment on column public.auction_events.outcome is
  'sold | redeemed | struck_off | future_sale | no_sale | unknown. Defaults to unknown and stays unknown until a source states the result.';
comment on column public.auction_events.event_url_kind is
  'property | sale | county | info - what event_url opens (same vocabulary as properties.url_auction_kind, migration 013), or null.';
comment on column public.auction_events.winning_bidder_ref is
  'Reserved for a future phase. Must stay NULL until the data-handling review in docs/production-data-contract.md Section 26 clears what may be stored here.';
comment on column public.auction_events.opening_bid is
  'Opening/minimum bid at first observation of this event - a snapshot, not a mirror of properties.bid.';

-- Keep updated_at honest on the mutable event row, the same way
-- properties_touch does for properties, reusing the existing function.
-- No trigger of any kind is placed on auction_event_observations.
create trigger auction_events_touch
  before update on public.auction_events
  for each row execute function public.touch_updated_at();

-- ---------------------------------------------------------------------------
-- 2. auction_event_observations - append-only: what a source showed for an
--    event at one moment. Never updated, never deleted by application code.
-- ---------------------------------------------------------------------------
create table public.auction_event_observations (
  id              bigint      generated always as identity primary key,
  -- RESTRICT: an event with observations cannot be deleted out from under
  -- its history.
  event_id        uuid        not null references public.auction_events(id) on delete restrict,
  -- When the pipeline observed this. With event_id it is the row's identity:
  -- one observation per event per instant. timestamptz carries microsecond
  -- precision, so two sightings in one run collide only if a writer reuses
  -- one timestamp for the same event twice, which is exactly the duplicate
  -- this constraint is meant to reject.
  observed_at     timestamptz not null default now(),
  -- The pipeline run that produced it (e.g. the GitHub Actions run id), so a
  -- run's observations can be audited or removed as a unit.
  harvest_run_id  text,
  -- Which surface of the source was read. Vocabulary is documented, not
  -- CHECK-constrained, because the closed-section and list feeds are not yet
  -- harvested and their exact names are settled when their writers land:
  -- expected values are 'waiting' (RealAuction Auctions Waiting), 'closed'
  -- (RealAuction Closed/Canceled), 'api' (LGBS), 'list' (LAFT/LienHub).
  feed            text        not null,
  -- The source's own words, verbatim.
  raw_status      text,
  -- The normalization applied to raw_status at observation time, with the
  -- same vocabularies as auction_events.
  lifecycle       text        not null,
  outcome         text        not null default 'unknown',
  -- Figures as shown at this observation.
  opening_bid     numeric,
  winning_bid     numeric,
  bid_count       integer,
  -- The page or API URL the observation was read from.
  evidence_url    text,
  created_at      timestamptz not null default now(),

  constraint auction_event_observations_event_observed_key
    unique (event_id, observed_at),
  constraint auction_event_observations_lifecycle_check
    check (lifecycle in ('scheduled', 'completed', 'cancelled', 'withdrawn', 'stayed', 'pending_result', 'superseded', 'unknown')),
  constraint auction_event_observations_outcome_check
    check (outcome in ('sold', 'redeemed', 'struck_off', 'future_sale', 'no_sale', 'unknown')),
  constraint auction_event_observations_bid_count_check
    check (bid_count is null or bid_count >= 0)
);

comment on table public.auction_event_observations is
  'Append-only log of what a source showed for an auction event at one observation. One row per (event_id, observed_at). Application code inserts only; it never updates or deletes rows here. Written only by service_role pipelines in a later phase; empty until then.';
comment on column public.auction_event_observations.feed is
  'Source surface read: waiting | closed | api | list (documented vocabulary; not CHECK-constrained until those writers exist).';
comment on column public.auction_event_observations.raw_status is
  'The source status string verbatim (e.g. an LGBS status, a RealAuction auction status). Never normalized in place.';

-- ---------------------------------------------------------------------------
-- 3. Indexes. Each one is for a query the plan actually needs; nothing
--    speculative.
-- ---------------------------------------------------------------------------
-- (property_id, scheduled_sale_date) is already the unique key, and its
-- leading column serves "events for this property", so no separate
-- property_id index is created.

-- County-level trends: "events in this state and county between two dates".
create index auction_events_state_county_date_idx
  on public.auction_events (state, county, scheduled_sale_date);

-- Provider-level trends: "events from this source between two dates".
create index auction_events_source_date_idx
  on public.auction_events (source, scheduled_sale_date);

-- The writer's own work queue in the outcome-capture phase: events whose
-- sale date has passed and whose outcome is still unknown. Partial, because
-- the resolved majority never needs to be scanned for this. A plain index on
-- outcome or lifecycle alone is not created: both are low-cardinality and
-- every analytics query that filters on them also filters on state/county or
-- source and a date range, which the two composite indexes above serve.
create index auction_events_unresolved_idx
  on public.auction_events (scheduled_sale_date)
  where outcome = 'unknown';

-- (event_id, observed_at) is the unique key and serves "observations for
-- this event, in order", so no separate event_id index is created.

-- Time-window reads of the log ("what did we observe between these times").
create index auction_event_observations_observed_at_idx
  on public.auction_event_observations (observed_at);

-- Run-scoped audit and rollback ("every observation this run wrote").
-- Partial: rows without a run id cannot be selected by run anyway.
create index auction_event_observations_run_idx
  on public.auction_event_observations (harvest_run_id)
  where harvest_run_id is not null;

-- ---------------------------------------------------------------------------
-- 4. Access: RLS on, one PERMISSIVE SELECT policy per table for approved
--    users, explicit grants. No client write path exists.
-- ---------------------------------------------------------------------------
alter table public.auction_events enable row level security;
alter table public.auction_event_observations enable row level security;

create policy "auction_events: approved read"
  on public.auction_events
  as permissive
  for select
  to authenticated
  using (public.is_approved());

create policy "auction_event_observations: approved read"
  on public.auction_event_observations
  as permissive
  for select
  to authenticated
  using (public.is_approved());

-- State the grants rather than inherit the project's default privileges.
revoke all on table public.auction_events from public, anon, authenticated;
revoke all on table public.auction_event_observations from public, anon, authenticated;
grant select on table public.auction_events to authenticated;
grant select on table public.auction_event_observations to authenticated;
grant select, insert, update, delete on table public.auction_events to service_role;
grant select, insert, update, delete on table public.auction_event_observations to service_role;
-- The identity column's sequence. The project's default privileges grant
-- every new sequence in public to anon/authenticated as well (confirmed on
-- pg_default_acl, 2026-09-25), which would let a client advance or reset the
-- observation id counter even though it cannot insert. Revoke first, then
-- grant only the future service_role writer what an identity insert needs.
revoke all on sequence public.auction_event_observations_id_seq from public, anon, authenticated;
grant usage, select on sequence public.auction_event_observations_id_seq to service_role;

commit;
