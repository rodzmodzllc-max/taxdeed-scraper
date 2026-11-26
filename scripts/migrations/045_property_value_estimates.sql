-- 045: property_value_estimates - outside value estimates behind the MRV
-- (Marc Research Value), 2026-11-25.
--
-- Owner, 2026-11-25: show an "MRV" on the property card - the median of the
-- values available for a property: the county's own value (already on the
-- row) plus outside estimates from licensed APIs. Sources: RentCast's AVM
-- ('rentcast_avm', fetched by scripts/fetch_rentcast_estimates.py under the
-- owner's API key) and, once Zillow approves the owner's API application,
-- Zillow's official Zestimate API ('zillow_zestimate'). Zillow's and
-- Realtor.com's websites are never copied.
--
-- One row per (property, source): the latest estimate. The browser computes
-- the median; nothing here is a price, an appraisal or an offer.
--
-- Access (CLAUDE.md "publication gate on the side tables"): a row is readable
-- only when the same caller can read its property under the property's own
-- RLS - never on is_approved() alone. Only the service role writes.
-- Grants revoked first (Supabase's default privileges grant ALL otherwise).
-- Idempotent.

create table if not exists public.property_value_estimates (
  property_id uuid not null references public.properties(id) on delete cascade,
  source text not null check (source in ('rentcast_avm', 'zillow_zestimate')),
  value numeric not null check (value > 0),
  value_low numeric check (value_low is null or value_low > 0),
  value_high numeric check (value_high is null or value_high > 0),
  observed_at timestamptz not null default now(),
  provenance jsonb not null default '{}'::jsonb check (pg_column_size(provenance) < 2048),
  primary key (property_id, source)
);
create index if not exists property_value_estimates_observed_idx on public.property_value_estimates (observed_at);

alter table public.property_value_estimates enable row level security;
revoke all on table public.property_value_estimates from anon, authenticated;
grant select on table public.property_value_estimates to authenticated;
grant all on table public.property_value_estimates to service_role;

drop policy if exists "property_value_estimates: read where the property is readable" on public.property_value_estimates;
create policy "property_value_estimates: read where the property is readable"
  on public.property_value_estimates for select to authenticated
  using (exists (select 1 from public.properties p where p.id = property_value_estimates.property_id));
