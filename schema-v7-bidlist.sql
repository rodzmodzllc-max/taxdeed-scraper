-- FL Tax Deed Watchlist — "My Bid List"
-- Run this once in the Supabase SQL Editor (Dashboard -> SQL Editor -> New
-- query), after schema.sql. If you've also run schema-v6-approvals.sql
-- (sign-up approval), it doesn't matter which order you run this one in -
-- see the bottom section, which detects whether that migration is present.
--
-- What this adds: a small, separate shortlist from Favorites - "My Bid
-- List" - capped at 10 properties, for the handful someone's actually
-- planning to show up and bid on. Same shape/privacy as favorites/hidden:
-- one row per (user, property), fully private to that user.
--
-- Nothing existing is touched or dropped - this only adds one new table,
-- its own RLS policies, and a limit-enforcing trigger.

create table if not exists public.bid_list (
  user_id     uuid not null references auth.users(id) on delete cascade,
  property_id uuid not null references public.properties(id) on delete cascade,
  added_at    timestamptz not null default now(),
  primary key (user_id, property_id)
);

alter table public.bid_list enable row level security;

drop policy if exists "own bid_list" on public.bid_list;
create policy "own bid_list" on public.bid_list
  for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Server-side backstop for the 10-item cap. The app already checks this and
-- blocks the request before it's ever sent - this just makes sure the cap
-- holds even under a race (two tabs both adding a 10th/11th item at once)
-- or a client that skips the check entirely.
create or replace function public.enforce_bid_list_limit()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if (select count(*) from public.bid_list where user_id = new.user_id) >= 10 then
    raise exception 'Bid list is full (10 max) - remove one before adding another.';
  end if;
  return new;
end;
$$;

drop trigger if exists bid_list_limit_check on public.bid_list;
create trigger bid_list_limit_check
  before insert on public.bid_list
  for each row execute function public.enforce_bid_list_limit();

-- Only takes effect if schema-v6-approvals.sql has already been run (its
-- is_approved() helper has to exist first) - narrows bid_list to approved
-- accounts only, same restriction every other ledger table already has.
-- Safe either way: if you haven't set up approval-gated sign-up, this block
-- just does nothing.
do $$
begin
  if exists (select 1 from pg_proc where proname = 'is_approved') then
    execute 'drop policy if exists "bid_list: approved only" on public.bid_list';
    execute 'create policy "bid_list: approved only" on public.bid_list as restrictive for all using (public.is_approved()) with check (public.is_approved())';
  end if;
end $$;
