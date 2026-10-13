-- 033_billing_refunds_disputes.sql
--
-- DRAFT - NOT APPLIED. Requires the owner's explicit approval before anything
-- runs against production (see docs/billing-refund-dispute.md, section 6).
-- Apply ONLY AFTER 027 (billing tables) and BEFORE the stripe-webhook function
-- that reads last_payment_event_at / writes billing_charges is redeployed.
--
-- Adds what the webhook needs to record refunds and disputes per charge, and
-- to order payment events. Nothing here grants or revokes access by itself:
-- the entitlement mirror (public.entitlement_for, migration 027) must be
-- updated to honour billing_charges BEFORE billing is enabled. That change is
-- listed as a blocker in docs/billing-refund-dispute.md and is not in this file.

-- 1. Payment ordering: the newest invoice event applied to this subscription.
alter table public.subscriptions add column if not exists last_payment_event_at timestamptz;

-- 2. One row per Stripe charge. A refund or dispute arrives per charge; the
--    charge is attributed to a subscription when its invoice is paid. Both
--    orders are allowed: stripe_subscription_id stays null until linked.
create table if not exists public.billing_charges (
  charge_id             text primary key,
  stripe_subscription_id text,                       -- null until the invoice links it
  amount                integer,
  amount_refunded       integer not null default 0 check (amount_refunded >= 0),
  refund_state          text not null default 'none' check (refund_state in ('none', 'partial', 'full')),
  dispute_id            text,
  dispute_status        text not null default 'none' check (dispute_status in ('none', 'needs_response', 'under_review', 'won', 'lost')),
  updated_at            timestamptz not null default now()
);
create index if not exists billing_charges_subscription_idx on public.billing_charges (stripe_subscription_id);

-- Same privilege pattern as the other billing tables: no client writes, admin
-- read only, service_role writes from the webhook.
revoke all on public.billing_charges from anon, authenticated;
grant select on public.billing_charges to authenticated;
grant all on public.billing_charges to service_role;
alter table public.billing_charges enable row level security;

drop policy if exists "billing_charges: admin read" on public.billing_charges;
create policy "billing_charges: admin read" on public.billing_charges
  as permissive for select to authenticated using ((select public.is_admin()));
