-- 029_research_workspace.sql
-- Research workflow layer (2026-10-06): a customer's own research lists, the
-- properties saved into them, the customer's own workflow state for each, and
-- the customer's own due-diligence review notes.
--
-- WRITTEN AND TESTED, NOT APPLIED. Applying it is a separate, explicit
-- production step. Until it is applied the frontend feature-detects the two
-- tables and keeps research lists in the browser only (labelled as such).
--
-- Additive only:
--   * research_lists  - one row per list a customer names ("October Florida
--                        Auction", "Due Diligence", ...). Own rows only.
--   * research_items  - one row per (list, property). research_state is the
--                        CUSTOMER's workflow state (DISCOVERED / RESEARCHING /
--                        DUE_DILIGENCE / ACQUISITION_READY / PASSED / ACQUIRED).
--                        It is never a government or source status and is
--                        never written to public.properties: the official
--                        ledger status and the source's own status stay on the
--                        property row, untouched.
--                        `diligence` holds only the customer's own review marks
--                        and notes per checklist item. Evidence states are
--                        computed from the property's records by the app and
--                        are never stored here - a customer note cannot make an
--                        item "verified".
-- Nothing else changes: no existing table, column, policy or function is
-- altered. public.properties is not touched.
--
-- RLS (CLAUDE.md, "the RESTRICTIVE/PERMISSIVE lesson"): each table gets a
-- PERMISSIVE own-row policy AND a RESTRICTIVE is_approved() policy layered on
-- top - never a RESTRICTIVE policy alone. Helper calls are wrapped as
-- (select fn()) so they run once per statement (migration 026's rule).
-- Supabase's default privileges grant ALL on new tables, so every grant is
-- revoked first and only the four row verbs are granted back to customers.

create table if not exists public.research_lists (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  name text not null check (length(btrim(name)) between 1 and 80),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists research_lists_user_idx on public.research_lists (user_id, created_at);

create table if not exists public.research_items (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  list_id uuid not null references public.research_lists(id) on delete cascade,
  property_id uuid not null references public.properties(id) on delete cascade,
  research_state text not null default 'DISCOVERED'
    check (research_state in ('DISCOVERED', 'RESEARCHING', 'DUE_DILIGENCE', 'ACQUISITION_READY', 'PASSED', 'ACQUIRED')),
  note text check (note is null or length(note) <= 2000),
  diligence jsonb not null default '{}'::jsonb
    check (jsonb_typeof(diligence) = 'object' and pg_column_size(diligence) < 16384),
  saved_at timestamptz not null default now(),
  state_changed_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (list_id, property_id)
);
create index if not exists research_items_user_idx on public.research_items (user_id, saved_at desc);
create index if not exists research_items_list_idx on public.research_items (list_id);
create index if not exists research_items_property_idx on public.research_items (property_id);

-- An item can only live in a list its own user owns.
create or replace function public.research_items_same_owner()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if not exists (select 1 from public.research_lists l where l.id = new.list_id and l.user_id = new.user_id) then
    raise exception 'research list not found' using errcode = '23503';
  end if;
  if tg_op = 'UPDATE' and new.research_state is distinct from old.research_state then
    new.state_changed_at := now();
  end if;
  new.updated_at := now();
  return new;
end $$;
revoke all on function public.research_items_same_owner() from public, anon, authenticated;
drop trigger if exists research_items_same_owner on public.research_items;
create trigger research_items_same_owner before insert or update on public.research_items
  for each row execute function public.research_items_same_owner();

-- A modest ceiling per customer: 50 lists, 2,000 saved properties.
create or replace function public.research_limits()
returns trigger
language plpgsql
set search_path = public
as $$
begin
  if tg_table_name = 'research_lists' and (select count(*) from public.research_lists where user_id = new.user_id) >= 50 then
    raise exception 'research list limit reached (50)' using errcode = '23514';
  end if;
  if tg_table_name = 'research_items' and (select count(*) from public.research_items where user_id = new.user_id) >= 2000 then
    raise exception 'research item limit reached (2000)' using errcode = '23514';
  end if;
  return new;
end $$;
revoke all on function public.research_limits() from public, anon, authenticated;
drop trigger if exists research_lists_limit on public.research_lists;
create trigger research_lists_limit before insert on public.research_lists
  for each row execute function public.research_limits();
drop trigger if exists research_items_limit on public.research_items;
create trigger research_items_limit before insert on public.research_items
  for each row execute function public.research_limits();

alter table public.research_lists enable row level security;
alter table public.research_items enable row level security;

do $$
declare t text;
begin
  foreach t in array array['research_lists', 'research_items'] loop
    execute format('drop policy if exists %I on public.%I', t || ': own rows', t);
    execute format('drop policy if exists %I on public.%I', t || ': approved only', t);
    execute format('create policy %I on public.%I as permissive for all to authenticated using (user_id = (select auth.uid())) with check (user_id = (select auth.uid()))',
                   t || ': own rows', t);
    execute format('create policy %I on public.%I as restrictive for all to public using ((select public.is_approved())) with check ((select public.is_approved()))',
                   t || ': approved only', t);
    execute format('revoke all on public.%I from anon, authenticated', t);
  end loop;
end $$;
grant select, insert, update, delete on public.research_lists to authenticated;
grant select, insert, update, delete on public.research_items to authenticated;
