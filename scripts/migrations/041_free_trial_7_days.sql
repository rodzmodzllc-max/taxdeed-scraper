-- 041 (2026-11-17, owner): a new account no longer waits for approval. It
-- gets a 7-day trial of the Guided (beginner) view straight away; when the
-- trial ends it drops back to the Free preview until an administrator
-- approves it (or, once billing ships, it subscribes).
--
-- How: profiles.trial_ends_at (set by the server, never by the customer -
-- profiles has no customer UPDATE/INSERT policy, only "read own row" and
-- admin access) and is_approved() answering true while that date is in the
-- future. Every ledger policy already asks is_approved(), so the trial reads
-- exactly what an approved account reads - nothing else is widened.
--
-- One exception: notes are shared between approved members and carry the
-- author's e-mail. A trial account must not read the team's notes, so a
-- RESTRICTIVE policy keeps a trial account to its own notes. (RESTRICTIVE is
-- AND-ed on top of the existing PERMISSIVE "notes: read if approved"; it
-- narrows and never grants - see CLAUDE.md before touching RLS.)

alter table public.profiles add column if not exists trial_ends_at timestamptz;
-- New rows (handle_new_user inserts id + email only) start a 7-day trial.
alter table public.profiles alter column trial_ends_at set default (now() + interval '7 days');
-- Accounts already waiting for approval start their 7 days now.
update public.profiles set trial_ends_at = now() + interval '7 days'
 where not approved and trial_ends_at is null;

comment on column public.profiles.trial_ends_at is
  '041: end of the 7-day Guided trial. Set by the server at sign-up; while in the future, is_approved() admits the account. Ignored once approved.';

-- An approved member (or an admin): the old meaning of is_approved().
create or replace function public.is_member()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select coalesce((select approved or is_admin from public.profiles where id = auth.uid()), false);
$$;

create or replace function public.is_approved()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select coalesce((select approved
                          or (trial_ends_at is not null and trial_ends_at > now())
                     from public.profiles where id = auth.uid()), false);
$$;

comment on function public.is_approved() is
  'Approved account, or one inside its 7-day trial (041). Every ledger policy asks this.';

revoke all on function public.is_member() from public, anon;
grant execute on function public.is_member() to authenticated, service_role;

drop policy if exists "notes: trial reads own only" on public.notes;
create policy "notes: trial reads own only" on public.notes
  as restrictive for all to authenticated
  using ((select public.is_member()) or author_id = (select auth.uid()))
  with check ((select public.is_member()) or author_id = (select auth.uid()));
