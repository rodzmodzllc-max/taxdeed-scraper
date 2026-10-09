-- 030_account_approval_notifications.sql
--
-- Durable, idempotent "your account is approved" e-mails (2026-10-09).
-- WRITTEN, NOT APPLIED. Applying it is an owner decision.
--
-- Why a table: approval is a plain admin UPDATE of public.profiles
-- (approved -> true, approved_at; app.js / admin.js, RLS "profiles: admin
-- full access"). Before this migration nothing recorded whether the
-- approved person was told, so a provider outage lost the e-mail silently
-- and nothing prevented a second one. This outbox gives:
--   * enqueue in the SAME transaction as the approval (trigger below): no
--     approval -> no row; a failed e-mail never undoes an approval;
--   * one notification per account and kind for ever (unique key): editing
--     an approved account, re-approving it, or two admins clicking at once
--     never queues a second e-mail;
--   * claim with FOR UPDATE SKIP LOCKED + a lease: two senders running at
--     once never pick the same row;
--   * retry with back-off and a capped number of attempts; failures keep a
--     short error CODE (never an address or a message body).
-- Existing approved accounts get NO row: nobody is e-mailed retroactively.
-- The sender (supabase/functions/notify-approval) also passes a provider
-- idempotency key per row, so a retry after a lost response is not a
-- second delivery.

begin;

create table if not exists public.account_notifications (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid not null references public.profiles(id) on delete cascade,
  kind                text not null check (kind in ('account_approved')),
  status              text not null default 'pending' check (status in ('pending', 'sending', 'sent', 'failed', 'skipped')),
  attempts            integer not null default 0 check (attempts >= 0),
  next_attempt_at     timestamptz not null default now(),
  locked_until        timestamptz,
  provider_message_id text,
  last_error          text check (last_error is null or length(last_error) <= 80),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  sent_at             timestamptz,
  unique (user_id, kind)
);

create index if not exists account_notifications_due_idx
  on public.account_notifications (next_attempt_at) where status in ('pending', 'failed', 'sending');

-- Not readable or writable by customers; admins may read (monitoring).
alter table public.account_notifications enable row level security;
revoke all on public.account_notifications from public, anon, authenticated;
grant select on public.account_notifications to authenticated;
drop policy if exists "account_notifications: admin read" on public.account_notifications;
create policy "account_notifications: admin read" on public.account_notifications
  as permissive for select to authenticated using ((select public.is_admin()));
grant all on public.account_notifications to service_role;

-- Enqueue on the false -> true transition only, inside the approving UPDATE.
create or replace function public.enqueue_account_approved_notification() returns trigger
language plpgsql security definer
set search_path to 'public'
as $$
begin
  if new.approved is true and coalesce(old.approved, false) is false then
    insert into public.account_notifications (user_id, kind) values (new.id, 'account_approved')
    on conflict (user_id, kind) do nothing;
  end if;
  return new;
end
$$;
revoke all on function public.enqueue_account_approved_notification() from public, anon, authenticated;

drop trigger if exists profiles_enqueue_approval_notification on public.profiles;
create trigger profiles_enqueue_approval_notification
  after update of approved on public.profiles
  for each row
  when (new.approved is true and old.approved is distinct from true)
  execute function public.enqueue_account_approved_notification();

-- Claim due rows for sending (service_role only). A row is due when it is
-- pending, or failed with attempts left and its back-off elapsed, or stuck
-- in 'sending' past its lease. Returns the CURRENT address and approval
-- flag from profiles - never a value supplied by a caller.
create or replace function public.claim_account_notifications(p_limit integer default 10, p_lease_seconds integer default 300)
returns table (id uuid, kind text, attempt integer, email text, approved boolean)
language plpgsql security definer
set search_path to 'public'
as $$
begin
  return query
  with due as (
    select n.id from public.account_notifications n
    where n.attempts < 8
      and ((n.status in ('pending', 'failed') and n.next_attempt_at <= now())
           or (n.status = 'sending' and n.locked_until < now()))
    order by n.created_at
    for update skip locked
    limit greatest(1, least(coalesce(p_limit, 10), 50))
  ), claimed as (
    update public.account_notifications n
       set status = 'sending', attempts = n.attempts + 1,
           locked_until = now() + make_interval(secs => greatest(30, least(coalesce(p_lease_seconds, 300), 3600))),
           updated_at = now()
      from due where n.id = due.id
    returning n.id, n.kind, n.attempts, n.user_id
  )
  select c.id, c.kind, c.attempts, p.email, p.approved
    from claimed c join public.profiles p on p.id = c.user_id;
end
$$;

-- Record the outcome of ONE claimed attempt. Ignored unless the row is still
-- in that attempt (a stale sender whose lease expired cannot overwrite a
-- newer attempt). p_outcome: 'sent' | 'failed' | 'skipped'.
create or replace function public.finish_account_notification(p_id uuid, p_attempt integer, p_outcome text,
                                                               p_message_id text default null, p_error text default null,
                                                               p_retry_seconds integer default 300)
returns boolean
language plpgsql security definer
set search_path to 'public'
as $$
declare n integer;
begin
  if p_outcome not in ('sent', 'failed', 'skipped') then
    raise exception 'unknown outcome';
  end if;
  update public.account_notifications
     set status = p_outcome,
         provider_message_id = case when p_outcome = 'sent' then left(p_message_id, 120) else provider_message_id end,
         sent_at = case when p_outcome = 'sent' then now() else sent_at end,
         last_error = case when p_outcome = 'sent' then null else left(p_error, 80) end,
         next_attempt_at = case when p_outcome = 'failed'
                                then now() + make_interval(secs => greatest(60, least(coalesce(p_retry_seconds, 300), 86400)))
                                else next_attempt_at end,
         locked_until = null, updated_at = now()
   where id = p_id and status = 'sending' and attempts = p_attempt;
  get diagnostics n = row_count;
  return n = 1;
end
$$;

-- Admin retry: a failed (or exhausted) notification goes back to pending
-- with a fresh attempt budget. A sent one is never re-queued.
create or replace function public.requeue_account_notification(p_id uuid) returns boolean
language plpgsql security definer
set search_path to 'public'
as $$
declare n integer;
begin
  if not coalesce(public.is_admin(), false) then
    raise exception 'admin only';
  end if;
  update public.account_notifications
     set status = 'pending', attempts = 0, next_attempt_at = now(), locked_until = null, updated_at = now()
   where id = p_id and status = 'failed';
  get diagnostics n = row_count;
  return n = 1;
end
$$;

revoke all on function public.claim_account_notifications(integer, integer) from public, anon, authenticated;
revoke all on function public.finish_account_notification(uuid, integer, text, text, text, integer) from public, anon, authenticated;
revoke all on function public.requeue_account_notification(uuid) from public, anon;
grant execute on function public.claim_account_notifications(integer, integer) to service_role;
grant execute on function public.finish_account_notification(uuid, integer, text, text, text, integer) to service_role;
grant execute on function public.requeue_account_notification(uuid) to authenticated;

commit;
