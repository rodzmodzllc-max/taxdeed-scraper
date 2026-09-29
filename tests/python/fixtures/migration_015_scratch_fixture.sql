-- Stand-in for the parts of the production database migration 015 touches,
-- so the migration file can be applied VERBATIM to an isolated scratch
-- database (a local PostgreSQL cluster, never the Supabase project) and its
-- behaviour checked for real. Policies, grants, foreign keys and function
-- signatures reproduce what pg_policies / information_schema /
-- pg_get_functiondef showed on the live project on 2026-09-29. Nothing here
-- is ever run against production.

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

-- Supabase's default privileges: every new table, sequence and function in
-- public is granted to the three API roles at creation. Reproduced so the
-- migration's explicit REVOKEs are actually exercised.
alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;
alter default privileges in schema public grant execute on functions to anon, authenticated, service_role;

-- ---- auth ----
create schema if not exists auth;
grant usage on schema auth to anon, authenticated, service_role;
create table auth.users (
  id    uuid primary key,
  email text
);
-- Same signature and claim source as Supabase's own auth.uid().
create or replace function auth.uid() returns uuid
language sql stable
as $$
  select (nullif(current_setting('request.jwt.claims', true), '')::json ->> 'sub')::uuid
$$;
-- Stand-ins for the auth tables that cascade from auth.users in production
-- (identities, sessions, ...), so the deletion test proves the cascade shape.
create table auth.identities (
  id      uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade
);
create table auth.sessions (
  id      uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade
);

-- ---- profiles + gate functions (byte-for-byte live definitions) ----
create table public.profiles (
  id           uuid primary key references auth.users(id) on delete cascade,
  email        text,
  approved     boolean not null default false,
  is_admin     boolean not null default false,
  requested_at timestamptz not null default now(),
  approved_at  timestamptz
);
alter table public.profiles enable row level security;

create or replace function public.is_approved() returns boolean
language sql security definer
set search_path to 'public'
as $$ select coalesce((select approved from public.profiles where id = auth.uid()), false) $$;

create or replace function public.is_admin() returns boolean
language sql stable security definer
set search_path to 'public'
as $$ select coalesce((select is_admin from public.profiles where id = auth.uid()), false) $$;

create or replace function public.handle_new_user() returns trigger
language plpgsql security definer
set search_path to 'public'
as $$
begin
  insert into public.profiles (id, email) values (new.id, new.email) on conflict (id) do nothing;
  return new;
end $$;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- Policies are created after the functions they call exist (Postgres
-- resolves a policy expression at creation time).
create policy "profiles: admin full access" on public.profiles
  as permissive for all to public using (public.is_admin()) with check (public.is_admin());
create policy "profiles: read own row" on public.profiles
  as permissive for select to public using (auth.uid() = id);

-- ---- the eight advisor-flagged functions (live bodies; properties_sync_geom
-- is a stand-in body because the scratch cluster has no PostGIS - the
-- migration only ALTERs its search_path, never its body) ----
create or replace function public.touch_updated_at() returns trigger
language plpgsql as $$ begin new.updated_at = now(); return new; end $$;
create or replace function public.set_updated_at() returns trigger
language plpgsql as $$ begin new.updated_at = now(); return new; end $$;
create or replace function public.update_modified_column() returns trigger
language plpgsql as $$ begin new.updated_at = now(); return new; end $$;
create or replace function public.sync_ledger_type_from_source() returns trigger
language plpgsql as $$
begin
  new.ledger_type := case new.source when 'auction' then 'auctions' when 'laft' then 'buy' when 'certificate' then 'lien' else new.ledger_type end;
  return new;
end $$;
create or replace function public.track_gone_since() returns trigger
language plpgsql as $$
declare
  gone_now boolean := new.status in ('dropped','sold','notfound','closed');
  gone_was boolean := coalesce(old.status,'') in ('dropped','sold','notfound','closed');
begin
  if gone_now and not gone_was then new.gone_since := now();
  elsif not gone_now then new.gone_since := null;
  else new.gone_since := old.gone_since; end if;
  return new;
end $$;
create or replace function public.track_gone_since_insert() returns trigger
language plpgsql as $$
begin
  if new.status in ('dropped','sold','notfound','closed') and new.gone_since is null then new.gone_since := now(); end if;
  return new;
end $$;
create or replace function public.properties_sync_geom() returns trigger
language plpgsql as $$ begin return new; end $$;

-- ---- properties (subset of columns; live policy + live grant shape) ----
create table public.properties (
  id               uuid primary key default gen_random_uuid(),
  state            text,
  source           text not null,
  county           text not null,
  case_no          text not null,
  ledger_type      text,
  status           text,
  sale_date        date,
  bid              numeric,
  gone_since       timestamptz,
  updated_at       timestamptz not null default now(),
  constraint properties_state_source_county_case_no_key unique (state, source, county, case_no)
);
alter table public.properties enable row level security;
create policy "properties: approved only" on public.properties
  as permissive for all to public using (public.is_approved()) with check (public.is_approved());
-- 005a: anon has no SELECT; authenticated's SELECT is column-level.
revoke select on public.properties from anon, authenticated;
grant select (id, state, county, source, case_no, status, sale_date, bid, gone_since, updated_at, ledger_type)
  on public.properties to authenticated;
create trigger properties_touch before update on public.properties for each row execute function public.touch_updated_at();
create trigger properties_gone_since before update on public.properties for each row execute function public.track_gone_since();
create trigger properties_gone_since_ins before insert on public.properties for each row execute function public.track_gone_since_insert();
create trigger trg_sync_ledger_type_from_source before insert or update on public.properties for each row execute function public.sync_ledger_type_from_source();

-- Same signature as the live 013 projection; body reduced to the scratch columns.
create function public.get_properties(
  p_state text default null, p_ledger_type text default null, p_status text default null,
  p_limit integer default 5000, p_offset integer default 0)
returns table (id uuid, state text, county text, source text, case_no text, status text, sale_date date, bid numeric)
language sql stable security invoker
as $$
  select id, state, county, source, case_no, status, sale_date, bid
  from public.properties
  where (p_state is null or state = p_state)
    and (p_ledger_type is null or ledger_type = p_ledger_type)
    and (p_status is null or status = p_status)
  order by county, case_no limit p_limit offset p_offset
$$;

-- ---- county_calendar (live policy shape) ----
create table public.county_calendar (
  county     text not null,
  sale_date  date not null,
  host       text,
  updated_at timestamptz not null default now(),
  primary key (county, sale_date)
);
alter table public.county_calendar enable row level security;
create policy "county_calendar: approved only" on public.county_calendar
  as permissive for all to public using (public.is_approved()) with check (public.is_approved());

-- ---- customer-owned tables (live policies, live cascades) ----
create table public.notes (
  id           uuid primary key default gen_random_uuid(),
  property_id  uuid not null,
  author_id    uuid not null references auth.users(id) on delete cascade,
  author_email text,
  stage        text,
  body         text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  unique (property_id, author_id)
);
alter table public.notes enable row level security;
create policy "notes: approved only" on public.notes
  as restrictive for all to public using (public.is_approved()) with check (public.is_approved());
create policy "notes: read if approved" on public.notes
  as permissive for select to public using (public.is_approved());
create policy "insert own note" on public.notes
  as permissive for insert to authenticated with check (author_id = auth.uid());
create policy "update own note" on public.notes
  as permissive for update to authenticated using (author_id = auth.uid());
create policy "delete own note" on public.notes
  as permissive for delete to authenticated using (author_id = auth.uid());

create table public.favorites (
  user_id     uuid not null references auth.users(id) on delete cascade,
  property_id uuid not null,
  created_at  timestamptz not null default now(),
  primary key (user_id, property_id)
);
alter table public.favorites enable row level security;
create policy "favorites: approved only" on public.favorites
  as restrictive for all to public using (public.is_approved()) with check (public.is_approved());
create policy "own favorites" on public.favorites
  as permissive for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

create table public.hidden (
  user_id     uuid not null references auth.users(id) on delete cascade,
  property_id uuid not null,
  created_at  timestamptz not null default now(),
  primary key (user_id, property_id)
);
alter table public.hidden enable row level security;
create policy "hidden: approved only" on public.hidden
  as restrictive for all to public using (public.is_approved()) with check (public.is_approved());
create policy "own hidden" on public.hidden
  as permissive for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

create table public.bid_list (
  user_id     uuid not null references auth.users(id) on delete cascade,
  property_id uuid not null references public.properties(id) on delete cascade,
  added_at    timestamptz not null default now(),
  primary key (user_id, property_id)
);
alter table public.bid_list enable row level security;
create policy "bid_list: approved only" on public.bid_list
  as restrictive for all to public using (public.is_approved()) with check (public.is_approved());
create policy "own bid_list" on public.bid_list
  as permissive for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

create or replace function public.enforce_bid_list_limit() returns trigger
language plpgsql security definer
set search_path to 'public'
as $$
begin
  if (select count(*) from public.bid_list where user_id = new.user_id) >= 10 then
    raise exception 'Bid list is full (10 max) - remove one before adding another.';
  end if;
  return new;
end $$;
create trigger bid_list_limit_check before insert on public.bid_list
  for each row execute function public.enforce_bid_list_limit();

-- ---- legacy tables the app never reads ----
create table public.auction_records (id serial primary key, note text);
create table public.auctions (id serial primary key, note text);
create table public.tax_auctions (id serial primary key, note text);
create table public.tax_deeds (id serial primary key, note text);
create table public.tax_liens (id serial primary key, note text);
create table public.scrape_review_queue (id serial primary key, note text);
create table public.scraper_review_queue (id serial primary key, note text);
create table public.scraping_logs (id serial primary key, note text);
create table public.states (code text primary key, name text not null);
alter table public.tax_auctions enable row level security;
create policy "Allow public read access" on public.tax_auctions for select to public using (true);
alter table public.states enable row level security;
create policy "Allow public read access to states" on public.states for select to public using (true);

-- ---- seed: two approved customers, one pending, shared rows ----
insert into auth.users (id, email) values
  ('11111111-1111-1111-1111-111111111111', 'a@example.com'),
  ('22222222-2222-2222-2222-222222222222', 'b@example.com'),
  ('33333333-3333-3333-3333-333333333333', 'pending@example.com');
update public.profiles set approved = true where id in
  ('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222');
insert into auth.identities (user_id) values
  ('11111111-1111-1111-1111-111111111111'), ('22222222-2222-2222-2222-222222222222');
insert into auth.sessions (user_id) values ('11111111-1111-1111-1111-111111111111');

insert into public.properties (id, state, source, county, case_no, status, sale_date, bid) values
  ('aaaaaaaa-0000-0000-0000-000000000001', 'FL', 'auction', 'Alachua', 'A-1', 'active', '2030-01-01', 5000),
  ('aaaaaaaa-0000-0000-0000-000000000002', 'FL', 'auction', 'Baker',   'B-1', 'active', '2030-01-02', 6000),
  ('aaaaaaaa-0000-0000-0000-000000000003', 'FL', 'laft',    'Bay',     'C-1', 'available', null, 2000);
insert into public.county_calendar (county, sale_date) values ('Alachua', '2030-01-01');

insert into public.notes (property_id, author_id, author_email, body) values
  ('aaaaaaaa-0000-0000-0000-000000000001', '11111111-1111-1111-1111-111111111111', 'a@example.com', 'note by a'),
  ('aaaaaaaa-0000-0000-0000-000000000001', '22222222-2222-2222-2222-222222222222', 'b@example.com', 'note by b');
insert into public.favorites (user_id, property_id) values
  ('11111111-1111-1111-1111-111111111111', 'aaaaaaaa-0000-0000-0000-000000000001'),
  ('22222222-2222-2222-2222-222222222222', 'aaaaaaaa-0000-0000-0000-000000000002');
insert into public.hidden (user_id, property_id) values
  ('11111111-1111-1111-1111-111111111111', 'aaaaaaaa-0000-0000-0000-000000000002');
insert into public.bid_list (user_id, property_id) values
  ('11111111-1111-1111-1111-111111111111', 'aaaaaaaa-0000-0000-0000-000000000001'),
  ('22222222-2222-2222-2222-222222222222', 'aaaaaaaa-0000-0000-0000-000000000001');
