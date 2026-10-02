-- 024_customer_monitoring_foundation.sql
-- Customer-value sprint (2026-10-01): the monitoring foundation for the
-- DISCOVER -> EVALUATE -> VERIFY -> ACQUIRE -> WATCH -> RECEIVE CHANGES workflow.
--
-- Additive only. No existing column, policy or row changes meaning:
--   * get_properties(): identical columns; the ORDER BY gains `id` as a
--     tie-break so the frontend can page past PostgREST's max-rows (1,000)
--     deterministically. Before this, one call returned at most 1,000 rows and
--     every state larger than that (FL 4,036, LA 10,334) was silently truncated.
--   * count_properties(): row count for a state (+ ledger), for parallel paging.
--   * property_change_snapshots / property_change_events: deterministic,
--     server-detected changes (scripts/detect_property_changes.py). Approved
--     users read events; snapshots are service-role only.
--   * source_observation_runs: per-source rows observed / added / changed /
--     closed for each detection run (freshness and data-quality visibility).
--   * saved_searches / alert_preferences / user_alerts: per-user, own rows only.
--   * product_events: per-user product analytics (insert own; admins read).
--
-- RLS pattern (CLAUDE.md, "the RESTRICTIVE/PERMISSIVE lesson"): every customer
-- table gets a PERMISSIVE own-row policy AND a RESTRICTIVE is_approved()
-- policy layered on top - never a RESTRICTIVE policy alone.

-- ---------------------------------------------------------------------------
-- 1. Deterministic paging for get_properties() + a matching count
-- ---------------------------------------------------------------------------
do $$
declare def text;
begin
  def := pg_get_functiondef('public.get_properties(text,text,text,integer,integer)'::regprocedure);
  if position('order by county, case_no, id' in def) = 0 then
    def := regexp_replace(def, 'order by county, case_no(\s)', 'order by county, case_no, id\1');
    if position('order by county, case_no, id' in def) = 0 then
      raise exception 'get_properties ORDER BY not found - refusing to guess';
    end if;
    execute def;
  end if;
end $$;

create or replace function public.count_properties(p_state text, p_ledger_type text default null)
returns bigint
language sql stable
set search_path = public
as $$
  select count(*) from public.properties
  where state = p_state and (p_ledger_type is null or ledger_type = p_ledger_type);
$$;
revoke all on function public.count_properties(text, text) from public, anon;
grant execute on function public.count_properties(text, text) to authenticated;

create index if not exists properties_state_county_case_id_idx on public.properties (state, county, case_no, id);
create index if not exists properties_state_ledger_idx on public.properties (state, ledger_type);

-- ---------------------------------------------------------------------------
-- 2. Server-detected property changes
-- ---------------------------------------------------------------------------
create table if not exists public.property_change_snapshots (
  property_id uuid primary key references public.properties(id) on delete cascade,
  state text not null,
  snapshot jsonb not null,
  taken_at timestamptz not null default now()
);
alter table public.property_change_snapshots enable row level security;
-- No client policy: service role only (RLS on + zero policies = no client access).
revoke all on public.property_change_snapshots from anon, authenticated;

create table if not exists public.property_change_events (
  id bigserial primary key,
  property_id uuid not null references public.properties(id) on delete cascade,
  state text not null,
  county text,
  source text,                 -- auction | laft | certificate (the ledger)
  source_id text,
  kind text not null check (kind in (
    'new_listing', 'removed', 'reactivated', 'status_changed', 'sale_date_changed', 'opening_bid_changed',
    'acquisition_path_changed', 'acquisition_evidence_changed', 'source_changed', 'field_changed', 'result_published')),
  field text,
  old_value text,
  new_value text,
  observed_at timestamptz not null default now(),
  run_id text
);
create index if not exists property_change_events_property_idx on public.property_change_events (property_id, observed_at desc);
create index if not exists property_change_events_state_time_idx on public.property_change_events (state, observed_at desc);
alter table public.property_change_events enable row level security;
drop policy if exists "property_change_events: approved read" on public.property_change_events;
create policy "property_change_events: approved read" on public.property_change_events
  as permissive for select to authenticated using (public.is_approved());
revoke all on public.property_change_events from anon, authenticated;
grant select on public.property_change_events to authenticated;

create table if not exists public.source_observation_runs (
  id bigserial primary key,
  state text not null,
  source_id text not null,
  ledger text,
  run_at timestamptz not null default now(),
  run_id text,
  rows_observed integer not null default 0,
  rows_added integer not null default 0,
  rows_changed integer not null default 0,
  rows_closed integer not null default 0,
  rows_reactivated integer not null default 0
);
create index if not exists source_observation_runs_idx on public.source_observation_runs (state, source_id, run_at desc);
alter table public.source_observation_runs enable row level security;
drop policy if exists "source_observation_runs: approved read" on public.source_observation_runs;
create policy "source_observation_runs: approved read" on public.source_observation_runs
  as permissive for select to authenticated using (public.is_approved());
revoke all on public.source_observation_runs from anon, authenticated;
grant select on public.source_observation_runs to authenticated;

-- ---------------------------------------------------------------------------
-- 3. Saved searches, alert preferences, alerts (own rows only)
-- ---------------------------------------------------------------------------
create table if not exists public.saved_searches (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  name text not null check (length(name) between 1 and 80),
  state text not null,
  criteria jsonb not null default '{}'::jsonb,
  alerts_enabled boolean not null default true,
  last_viewed_at timestamptz,
  last_match_ids uuid[] not null default '{}',
  created_at timestamptz not null default now()
);
create index if not exists saved_searches_user_idx on public.saved_searches (user_id);
alter table public.saved_searches enable row level security;

create table if not exists public.alert_preferences (
  user_id uuid primary key default auth.uid() references auth.users(id) on delete cascade,
  watch_changes boolean not null default true,
  saved_search_matches boolean not null default true,
  email_enabled boolean not null default false,
  updated_at timestamptz not null default now()
);
alter table public.alert_preferences enable row level security;

create table if not exists public.user_alerts (
  id bigserial primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  kind text not null check (kind in ('watched_status', 'watched_acquisition', 'watched_source', 'watched_auction',
                                      'watched_field', 'saved_search_new_match')),
  property_id uuid references public.properties(id) on delete cascade,
  saved_search_id uuid references public.saved_searches(id) on delete cascade,
  change_event_id bigint references public.property_change_events(id) on delete cascade,
  title text not null,
  detail text,
  created_at timestamptz not null default now(),
  read_at timestamptz,
  unique (user_id, change_event_id, saved_search_id)
);
create index if not exists user_alerts_user_idx on public.user_alerts (user_id, created_at desc);
alter table public.user_alerts enable row level security;

do $$
declare t text;
begin
  foreach t in array array['saved_searches', 'alert_preferences', 'user_alerts'] loop
    execute format('drop policy if exists %I on public.%I', t || ': own rows', t);
    execute format('drop policy if exists %I on public.%I', t || ': approved only', t);
    execute format('create policy %I on public.%I as permissive for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid())',
                   t || ': own rows', t);
    execute format('create policy %I on public.%I as restrictive for all to public using (public.is_approved()) with check (public.is_approved())',
                   t || ': approved only', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
  end loop;
end $$;
grant select, insert, update, delete on public.saved_searches to authenticated;
grant select, insert, update on public.alert_preferences to authenticated;
-- Alerts are written by the service role; a customer reads and marks them read
-- (Supabase's default privileges grant ALL on new tables - revoked above, so
-- a customer can never insert or edit an alert, only set read_at).
grant select, update (read_at) on public.user_alerts to authenticated;
grant usage, select on sequence public.user_alerts_id_seq to authenticated;

-- ---------------------------------------------------------------------------
-- 4. Product analytics (no free text, no PII beyond the user id)
-- ---------------------------------------------------------------------------
create table if not exists public.product_events (
  id bigserial primary key,
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  event text not null check (event in (
    'session_start', 'search_performed', 'property_viewed', 'property_saved', 'property_watched',
    'acquisition_source_opened', 'acquisition_instructions_opened', 'application_opened', 'official_source_opened',
    'export_performed', 'alert_created', 'alert_opened', 'saved_search_created', 'saved_search_opened')),
  state text,
  ledger text,
  property_id uuid,
  props jsonb not null default '{}'::jsonb check (pg_column_size(props) < 2048),
  created_at timestamptz not null default now()
);
create index if not exists product_events_event_time_idx on public.product_events (event, created_at desc);
create index if not exists product_events_user_time_idx on public.product_events (user_id, created_at desc);
alter table public.product_events enable row level security;
drop policy if exists "product_events: insert own" on public.product_events;
drop policy if exists "product_events: admin read" on public.product_events;
drop policy if exists "product_events: approved only" on public.product_events;
create policy "product_events: insert own" on public.product_events
  as permissive for insert to authenticated with check (user_id = auth.uid());
create policy "product_events: admin read" on public.product_events
  as permissive for select to authenticated using (public.is_admin());
create policy "product_events: approved only" on public.product_events
  as restrictive for all to public using (public.is_approved()) with check (public.is_approved());
revoke all on public.product_events from anon, authenticated;
grant insert, select on public.product_events to authenticated;
grant usage, select on sequence public.product_events_id_seq to authenticated;

-- Admin-only aggregate: counts per event and distinct users, last 30 days.
create or replace function public.product_usage_summary(p_days integer default 30)
returns table(event text, events bigint, users bigint, first_at timestamptz, last_at timestamptz)
language sql stable security definer
set search_path = public
as $$
  select e.event, count(*), count(distinct e.user_id), min(e.created_at), max(e.created_at)
  from public.product_events e
  where public.is_admin() and e.created_at > now() - make_interval(days => greatest(1, least(p_days, 365)))
  group by e.event order by e.event;
$$;
revoke all on function public.product_usage_summary(integer) from public, anon;
grant execute on function public.product_usage_summary(integer) to authenticated;
