-- FL Tax Deed Watchlist — approval-gated sign-up
-- Run this once in the Supabase SQL Editor (Dashboard -> SQL Editor -> New
-- query), AFTER schema.sql / schema-v2/v3/v4/v5 have already been applied.
--
-- What this changes: self-serve sign-up (public/app.js) already lets anyone
-- create a Supabase Auth account. Until now that account got ledger access
-- immediately. This migration adds a `profiles` table with an `approved`
-- flag (false by default for every new sign-up) and an extra RESTRICTIVE
-- policy on every ledger table requiring approved=true - so a brand new
-- account can sign in, but sees a "pending approval" screen and can't read
-- or write properties/notes/favorites/hidden/county_calendar until you flip
-- it to true (from the in-app admin panel, or the last UPDATE below).
--
-- Nothing existing is touched or dropped - this only adds a table, a
-- trigger, two helper functions, and RESTRICTIVE policies (which can only
-- narrow access further, never widen it, so they're safe to layer on top of
-- whatever SELECT/INSERT/UPDATE/DELETE policies those tables already have).

-- 1. One row per auth user, tracking approval state.
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  approved boolean not null default false,
  is_admin boolean not null default false,
  requested_at timestamptz not null default now(),
  approved_at timestamptz
);

alter table public.profiles enable row level security;

drop policy if exists "profiles: read own row" on public.profiles;
create policy "profiles: read own row"
  on public.profiles for select
  using (auth.uid() = id);

-- 2. Auto-create a profile row the instant someone signs up, so there's
-- never a signed-in account with no profiles row for the app to check.
-- SECURITY DEFINER so it can insert regardless of the caller's own RLS.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email)
  values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- 3. Helper functions - SECURITY DEFINER so they can read profiles.approved
-- / profiles.is_admin for the CURRENT caller without recursing through
-- profiles' own RLS (a plain policy calling back into the same table it
-- protects is a classic infinite-recursion foot-gun; this sidesteps it).
create or replace function public.is_approved()
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select coalesce((select approved from public.profiles where id = auth.uid()), false);
$$;

create or replace function public.is_admin()
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select coalesce((select is_admin from public.profiles where id = auth.uid()), false);
$$;

-- Admins (you) can see and act on every profiles row, to review and
-- approve pending sign-ups - both from the in-app admin panel and directly
-- in the Supabase table editor.
drop policy if exists "profiles: admin full access" on public.profiles;
create policy "profiles: admin full access"
  on public.profiles for all
  using (public.is_admin())
  with check (public.is_admin());

-- 4. The actual gate. RESTRICTIVE policies AND with whatever permissive
-- policies each table already has - they only narrow, so this is additive
-- and safe without needing to know those tables' existing policy text.
alter table public.properties enable row level security;
alter table public.notes enable row level security;
alter table public.favorites enable row level security;
alter table public.hidden enable row level security;
alter table public.county_calendar enable row level security;

drop policy if exists "properties: approved only" on public.properties;
create policy "properties: approved only" on public.properties as restrictive for all using (public.is_approved()) with check (public.is_approved());

drop policy if exists "notes: approved only" on public.notes;
create policy "notes: approved only" on public.notes as restrictive for all using (public.is_approved()) with check (public.is_approved());

drop policy if exists "favorites: approved only" on public.favorites;
create policy "favorites: approved only" on public.favorites as restrictive for all using (public.is_approved()) with check (public.is_approved());

drop policy if exists "hidden: approved only" on public.hidden;
create policy "hidden: approved only" on public.hidden as restrictive for all using (public.is_approved()) with check (public.is_approved());

drop policy if exists "county_calendar: approved only" on public.county_calendar;
create policy "county_calendar: approved only" on public.county_calendar as restrictive for all using (public.is_approved()) with check (public.is_approved());

-- 5. Bootstrap: your own existing account predates this migration (the
-- trigger above only fires on NEW sign-ups), so without this you'd lock
-- yourself out along with everyone else. This backfills your profile row
-- (or creates it if missing) and marks it approved + admin.
insert into public.profiles (id, email, approved, is_admin, approved_at)
select id, email, true, true, now()
from auth.users
where email = 'rodzmodzllc@gmail.com'
on conflict (id) do update set approved = true, is_admin = true, approved_at = now();

-- Approving anyone else later, without the in-app admin panel or the
-- notify-signup email (see supabase/functions/notify-signup/README.md):
--   update public.profiles set approved = true, approved_at = now() where email = 'them@example.com';
