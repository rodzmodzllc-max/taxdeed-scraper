-- Minimal stand-in for the parts of the production database that migration
-- 014 depends on, so the migration file can be applied VERBATIM to an
-- isolated scratch database (a local PostgreSQL cluster, never the Supabase
-- project) and its behaviour checked for real. Only what 014 references is
-- reproduced: the three API roles, auth.uid(), profiles/is_approved(),
-- touch_updated_at(), and a `properties` table with its real primary key.
-- Nothing here is ever run against production.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    -- Supabase's service_role bypasses RLS; reproduced so the "future writer
    -- can write, clients cannot" check is meaningful.
    create role service_role nologin bypassrls;
  end if;
end $$;

grant usage on schema public to anon, authenticated, service_role;

create schema if not exists auth;
-- Same signature and claim source as Supabase's own auth.uid().
create or replace function auth.uid() returns uuid
language sql stable
as $$
  select (nullif(current_setting('request.jwt.claims', true), '')::json ->> 'sub')::uuid
$$;

create table public.profiles (
  id       uuid primary key,
  approved boolean not null default false
);

-- Byte-for-byte the production definition (read from pg_get_functiondef on
-- 2026-09-25).
create or replace function public.is_approved() returns boolean
language sql security definer
set search_path to 'public'
as $$ select coalesce((select approved from public.profiles where id = auth.uid()), false) $$;

create or replace function public.touch_updated_at() returns trigger
language plpgsql
as $$ begin new.updated_at = now(); return new; end $$;

-- The columns 014 denormalizes from, plus the real primary key and natural
-- key. Other production columns are irrelevant to 014 and omitted.
create table public.properties (
  id               uuid primary key default gen_random_uuid(),
  state            text,
  source           text not null,
  county           text not null,
  case_no          text not null,
  harvester_source text,
  ledger_type      text,
  sale_date        date,
  bid              numeric,
  url_auction      text,
  url_auction_kind text,
  updated_at       timestamptz not null default now(),
  constraint properties_state_source_county_case_no_key unique (state, source, county, case_no)
);
alter table public.properties enable row level security;
create policy "properties: approved only" on public.properties
  as permissive for all to public using (public.is_approved()) with check (public.is_approved());
grant select on public.properties to authenticated;
grant all on public.properties to service_role;
