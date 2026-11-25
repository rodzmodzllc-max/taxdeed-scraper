-- 043 (2026-11-22, owner): "take off the approval for the time being. I'm
-- not charging for this." While TAXACQ is free, every signed-in account reads
-- what an approved account reads, with no approval wait and no trial end.
--
-- How: one server-side switch, public.app_settings('open_access'). While it is
-- on, is_approved() answers true for any signed-in account. Turning it off
-- (update the row to false) restores 041's rule exactly: approved, or inside a
-- 7-day trial. Nothing else changes:
--   * is_member() (approved members and admins) is untouched, so the
--     RESTRICTIVE "notes: trial reads own only" policy still keeps a
--     non-member to its own notes - the team's notes and their authors'
--     e-mails stay private.
--   * anon is never admitted: auth.uid() is null for anon, and the switch is
--     only consulted for a signed-in account.
--   * Customers cannot read or change the switch: app_settings has RLS on and
--     no customer policy; open_access() exposes only the one boolean.

create table if not exists public.app_settings (
  key        text primary key,
  value      jsonb not null,
  updated_at timestamptz not null default now()
);
alter table public.app_settings enable row level security;
revoke all on table public.app_settings from anon, authenticated;
grant select, insert, update, delete on table public.app_settings to service_role;

comment on table public.app_settings is
  '043: server-side product switches. No customer policy; read through dedicated functions only.';

insert into public.app_settings (key, value)
values ('open_access', '{"enabled": true, "reason": "Free period, owner 2026-11-22"}'::jsonb)
on conflict (key) do nothing;

-- The one boolean the app needs (so it can show the Guided view instead of
-- the trial-ended screen). Signed-in accounts only.
create or replace function public.open_access()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select auth.uid() is not null
     and coalesce((select (value->>'enabled')::boolean from public.app_settings where key = 'open_access'), false);
$$;
revoke all on function public.open_access() from public, anon;
grant execute on function public.open_access() to authenticated, service_role;

create or replace function public.is_approved()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select coalesce((select approved
                          or (trial_ends_at is not null and trial_ends_at > now())
                     from public.profiles where id = auth.uid()), false)
      or public.open_access();
$$;

comment on function public.is_approved() is
  'Approved account, one inside its 7-day trial (041), or any signed-in account while app_settings.open_access is on (043). Every ledger policy asks this.';
