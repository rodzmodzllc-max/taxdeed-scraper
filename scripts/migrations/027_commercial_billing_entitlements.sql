-- 027_commercial_billing_entitlements.sql  (2026-10-05)
--
-- Controlled paid beta: Stripe-backed subscriptions, ONE entitlement
-- decision, and the paid-beta source scope - layered ON TOP of the existing
-- approval model, which is unchanged.
--
-- WRITTEN AND TESTED, NOT APPLIED. Applying it is a separate, explicitly
-- authorized production step (docs/commercial-layer.md section 6). Before
-- that, the frontend feature-detects my_entitlement() and keeps today's
-- behaviour exactly: approved accounts are testers, admins are admins.
--
-- What it adds
--   profiles.access_grant          'tester' (default - every existing approved
--                                  account stays a tester) or 'customer'
--                                  (an admin-granted customer without Stripe)
--   billing_customers              account <-> Stripe customer
--   subscriptions                  one row per Stripe subscription, written
--                                  ONLY by the stripe-webhook function
--                                  (service role); customers read their own
--   billing_events                 one row per Stripe event id (idempotency +
--                                  audit); service role writes, admins read
--   commercial_source_scope        the paid-beta source set, mirrored from
--                                  data/paid_beta_sources.csv (a test pins them)
--   entitlement_for(uuid)          THE access decision (SQL mirror of
--                                  supabase/functions/_shared/billing_core.js
--                                  entitlementFor; shared vectors pin both)
--   my_entitlement()               the caller's entitlement (the app reads it)
--   has_paid_entitlement()         used by is_approved()
--   can_read_unreleased_sources()  admin or approved tester
--   admin_billing_overview()       admins: who can use the product and why
--
-- What it changes
--   is_approved()                  now ALSO true for an account whose
--                                  subscription grants access - a paying
--                                  customer does not wait for manual approval.
--                                  Same signature, SECURITY DEFINER, search_path.
--   properties                     one RESTRICTIVE SELECT policy: a viewer who
--                                  is not an admin or approved tester sees only
--                                  rows whose publication_status is APPROVED
--                                  AND whose source is in the paid-beta scope.
--                                  The existing PERMISSIVE "properties: approved
--                                  only" policy is untouched, so the
--                                  RESTRICTIVE policy narrows, never empties
--                                  (see CLAUDE.md, RESTRICTIVE/PERMISSIVE).
--
-- What it never does: write a property row, change a publication decision,
-- touch an existing approval, or grant a client any write on billing tables.

begin;

-- ---------------------------------------------------------------- profiles
alter table public.profiles
  add column if not exists access_grant text not null default 'tester';
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'profiles_access_grant_check') then
    alter table public.profiles add constraint profiles_access_grant_check check (access_grant in ('tester', 'customer'));
  end if;
end $$;

-- ---------------------------------------------------------------- billing tables
create table if not exists public.billing_customers (
  user_id            uuid primary key references auth.users(id) on delete cascade,
  stripe_customer_id text not null unique,
  created_at         timestamptz not null default now()
);

create table if not exists public.subscriptions (
  stripe_subscription_id text primary key,
  user_id                uuid not null references auth.users(id) on delete cascade,
  stripe_customer_id     text not null,
  status                 text not null check (status in
                           ('incomplete', 'incomplete_expired', 'trialing', 'active', 'past_due', 'canceled', 'unpaid', 'paused')),
  price_id               text,
  product_id             text,
  plan_key               text,            -- 'monthly' when price_id is the configured plan price; NULL grants nothing
  current_period_start   timestamptz,
  current_period_end     timestamptz,
  cancel_at_period_end   boolean not null default false,
  cancel_at              timestamptz,
  canceled_at            timestamptz,
  ended_at               timestamptz,
  last_payment_status    text not null default 'none' check (last_payment_status in ('none', 'paid', 'failed')),
  payment_failed_at      timestamptz,
  stripe_event_created   timestamptz,     -- newest Stripe event applied; an older one never overwrites
  updated_at             timestamptz not null default now()
);
create index if not exists subscriptions_user_idx on public.subscriptions (user_id);

create table if not exists public.billing_events (
  stripe_event_id text primary key,
  type            text not null,
  livemode        boolean not null default false,
  outcome         text not null default 'received' check (outcome in ('received', 'processed', 'ignored', 'failed')),
  error           text,
  received_at     timestamptz not null default now(),
  processed_at    timestamptz
);

create table if not exists public.commercial_source_scope (
  source_id  text primary key,
  paid_beta  boolean not null,
  reason     text not null,
  decided_on date not null
);

-- Supabase's default privileges grant ALL on new tables to anon /
-- authenticated: take everything away first, then grant only reads.
revoke all on public.billing_customers, public.subscriptions, public.billing_events, public.commercial_source_scope from anon, authenticated;
grant select on public.billing_customers, public.subscriptions, public.billing_events, public.commercial_source_scope to authenticated;
grant all on public.billing_customers, public.subscriptions, public.billing_events, public.commercial_source_scope to service_role;

alter table public.billing_customers enable row level security;
alter table public.subscriptions enable row level security;
alter table public.billing_events enable row level security;
alter table public.commercial_source_scope enable row level security;

drop policy if exists "billing_customers: read own" on public.billing_customers;
create policy "billing_customers: read own" on public.billing_customers
  as permissive for select to authenticated using (user_id = auth.uid());
drop policy if exists "billing_customers: admin read" on public.billing_customers;
create policy "billing_customers: admin read" on public.billing_customers
  as permissive for select to authenticated using ((select public.is_admin()));

drop policy if exists "subscriptions: read own" on public.subscriptions;
create policy "subscriptions: read own" on public.subscriptions
  as permissive for select to authenticated using (user_id = auth.uid());
drop policy if exists "subscriptions: admin read" on public.subscriptions;
create policy "subscriptions: admin read" on public.subscriptions
  as permissive for select to authenticated using ((select public.is_admin()));

drop policy if exists "billing_events: admin read" on public.billing_events;
create policy "billing_events: admin read" on public.billing_events
  as permissive for select to authenticated using ((select public.is_admin()));

drop policy if exists "commercial_source_scope: signed-in read" on public.commercial_source_scope;
create policy "commercial_source_scope: signed-in read" on public.commercial_source_scope
  as permissive for select to authenticated using (true);

-- The paid-beta source set (mirror of data/paid_beta_sources.csv, paid_beta = yes;
-- tests/python/test_migration_027_commercial_billing.py pins them equal).
insert into public.commercial_source_scope (source_id, paid_beta, reason, decided_on) values
  ('la_ebr_adjudicated', true, 'Explicit APPROVED publication decision; provenance, lifecycle, financial and acquisition checks ok', '2026-10-05'),
  ('sc_york_tax_sale', true, 'Explicit APPROVED publication decision; provenance, lifecycle, financial and acquisition checks ok', '2026-10-05'),
  ('mi_lenawee_tax_sale', true, 'Explicit APPROVED publication decision; provenance, lifecycle, financial and acquisition checks ok', '2026-10-05'),
  ('mi_eaton_treasurer_sale', true, 'Explicit APPROVED publication decision; provenance, lifecycle, financial and acquisition checks ok', '2026-10-05'),
  ('wi_green_tax_deed_sales', true, 'Explicit APPROVED publication decision; no active rows at the decision date', '2026-10-05')
on conflict (source_id) do nothing;

-- ---------------------------------------------------------------- entitlement
-- Grace after a failed payment before paid access stops (mirror of
-- billing_core.js DEFAULT_GRACE_DAYS).
create or replace function public.billing_grace_days() returns integer
language sql immutable as $$ select 7 $$;

-- Per-subscription state (mirror of billing_core.js subscriptionEntitlement).
create or replace function public.subscription_state(s public.subscriptions, p_now timestamptz)
returns text
language sql stable
set search_path to 'public'
as $$
  select case
    when s.stripe_subscription_id is null then 'inactive'
    when s.plan_key is null then 'inactive'
    when s.status = 'active' and s.cancel_at_period_end and s.current_period_end is not null and s.current_period_end > p_now then 'cancelling'
    when s.status = 'active' and s.cancel_at_period_end then 'cancelled'
    when s.status = 'active' then 'active'
    when s.status = 'trialing' then 'trial'
    when s.status = 'past_due' and p_now < coalesce(s.payment_failed_at, s.current_period_end, p_now)
                                          + make_interval(days => public.billing_grace_days()) then 'payment_failed_grace'
    when s.status in ('past_due', 'unpaid') then 'payment_failed'
    when s.status = 'canceled' then 'cancelled'
    else 'inactive'
  end
$$;

-- THE access decision. Precedence: admin > tester > customer (paid or
-- admin-granted) > inactive. Mirror of billing_core.js entitlementFor().
create or replace function public.entitlement_for(p_uid uuid, p_now timestamptz default now())
returns jsonb
language plpgsql stable security definer
set search_path to 'public'
as $$
declare
  pr record;
  best public.subscriptions;
  st text;
  sub_access boolean;
  base jsonb;
begin
  select approved, is_admin, access_grant into pr from public.profiles where id = p_uid;

  -- the subscription that grants access, else the most recently changed one
  select s.* into best from public.subscriptions s
   where s.user_id = p_uid
   order by (public.subscription_state(s, p_now) in ('active', 'trial', 'cancelling', 'payment_failed_grace')) desc,
            (s.plan_key is not null) desc,
            coalesce(s.stripe_event_created, s.updated_at) desc
   limit 1;
  st := case when best.stripe_subscription_id is null then null else public.subscription_state(best, p_now) end;
  sub_access := coalesce(st in ('active', 'trial', 'cancelling', 'payment_failed_grace'), false);
  base := jsonb_build_object('subscription_state', st, 'subscription_status', best.status,
                             'current_period_end', best.current_period_end, 'cancel_at_period_end', best.cancel_at_period_end,
                             'plan_key', best.plan_key, 'last_payment_status', best.last_payment_status);

  if coalesce(pr.is_admin, false) then
    return base || jsonb_build_object('role', 'admin', 'state', 'admin_override', 'access', true, 'scope', 'all', 'reason', 'Administrator');
  end if;
  if coalesce(pr.approved, false) and coalesce(pr.access_grant, 'tester') = 'tester' then
    return base || jsonb_build_object('role', 'tester', 'state', 'tester_beta', 'access', true, 'scope', 'preview',
                                      'reason', 'Approved tester (beta) - no subscription needed');
  end if;
  if sub_access then
    return base || jsonb_build_object('role', 'customer', 'state', st, 'access', true, 'scope', 'approved', 'reason', 'Paid subscription');
  end if;
  if coalesce(pr.approved, false) and pr.access_grant = 'customer' then
    return base || jsonb_build_object('role', 'customer', 'state', 'manual_customer', 'access', true, 'scope', 'approved',
                                      'reason', 'Customer access granted by an administrator');
  end if;
  return base || jsonb_build_object('role', 'inactive', 'state', coalesce(st, 'inactive'), 'access', false, 'scope', 'none',
                                    'reason', case when st is null then 'No approval and no active subscription' else 'Subscription does not grant access' end);
end
$$;

create or replace function public.my_entitlement() returns jsonb
language sql stable security definer
set search_path to 'public'
as $$ select public.entitlement_for(auth.uid(), now()) $$;

create or replace function public.has_paid_entitlement() returns boolean
language sql stable security definer
set search_path to 'public'
as $$
  select exists (select 1 from public.subscriptions s
                  where s.user_id = auth.uid()
                    and public.subscription_state(s, now()) in ('active', 'trial', 'cancelling', 'payment_failed_grace'))
$$;

-- Admin, or an approved account whose grant is 'tester': may read rows of
-- sources not (yet) in the paid-beta scope. The frontend still decides
-- preview vs enforced for testers (config.js publicationMode).
create or replace function public.can_read_unreleased_sources() returns boolean
language sql stable security definer
set search_path to 'public'
as $$
  select coalesce((select is_admin or (approved and access_grant = 'tester') from public.profiles where id = auth.uid()), false)
$$;

-- Unchanged signature and attributes; now also true for a paying customer.
create or replace function public.is_approved() returns boolean
language sql security definer
set search_path to 'public'
as $$
  select coalesce((select approved from public.profiles where id = auth.uid()), false)
      or public.has_paid_entitlement()
$$;

-- Admins only: who can use the product and why. No payment details beyond
-- the Stripe object ids and states Stripe itself shows the account holder.
create or replace function public.admin_billing_overview()
returns table (user_id uuid, email text, approved boolean, is_admin boolean, access_grant text,
               role text, state text, access boolean, reason text,
               subscription_status text, stripe_subscription_id text, plan_key text,
               current_period_end timestamptz, cancel_at_period_end boolean,
               last_payment_status text, payment_failed_at timestamptz, requested_at timestamptz)
language plpgsql stable security definer
set search_path to 'public'
as $$
begin
  if not coalesce(public.is_admin(), false) then
    raise exception 'admin only' using errcode = '42501';
  end if;
  return query
    with e as (select p.*, public.entitlement_for(p.id, now()) as ent from public.profiles p)
    select e.id, e.email, e.approved, e.is_admin, e.access_grant,
           e.ent->>'role', e.ent->>'state', (e.ent->>'access')::boolean, e.ent->>'reason',
           s.status, s.stripe_subscription_id, s.plan_key, s.current_period_end, s.cancel_at_period_end,
           s.last_payment_status, s.payment_failed_at, e.requested_at
      from e
      left join lateral (select * from public.subscriptions x where x.user_id = e.id
                          order by coalesce(x.stripe_event_created, x.updated_at) desc limit 1) s on true
     order by (e.ent->>'access')::boolean desc, e.requested_at desc;
end
$$;

revoke execute on function public.entitlement_for(uuid, timestamptz) from public, anon, authenticated;
revoke execute on function public.subscription_state(public.subscriptions, timestamptz) from public, anon, authenticated;
revoke execute on function public.has_paid_entitlement(), public.can_read_unreleased_sources(), public.my_entitlement(),
                         public.admin_billing_overview(), public.billing_grace_days() from public, anon;
grant execute on function public.my_entitlement(), public.admin_billing_overview(),
                        public.has_paid_entitlement(), public.can_read_unreleased_sources() to authenticated;
grant execute on function public.entitlement_for(uuid, timestamptz), public.subscription_state(public.subscriptions, timestamptz),
                        public.billing_grace_days() to service_role;

-- ---------------------------------------------------------------- paid-beta scope on properties
-- RESTRICTIVE, SELECT only, authenticated only. The PERMISSIVE
-- "properties: approved only" policy stays the one that grants access.
drop policy if exists "properties: paid customers see paid-beta sources only" on public.properties;
create policy "properties: paid customers see paid-beta sources only" on public.properties
  as restrictive for select to authenticated
  using (
    (select public.can_read_unreleased_sources())
    or (publication_status = 'APPROVED'
        and source_id in (select c.source_id from public.commercial_source_scope c where c.paid_beta))
  );

commit;
