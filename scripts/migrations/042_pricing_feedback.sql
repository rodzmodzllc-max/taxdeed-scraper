-- 042 (2026-11-17, owner): "I want the users to tell me how much they would
-- pay." A short willingness-to-pay survey (Van Westendorp's four price
-- questions plus plan, use and a comment) answered inside the app.
--
-- One row per answer; a person may answer again later (their latest counts).
-- Customers insert their own rows only and cannot read anyone's; admins read
-- all. Trial accounts may answer: is_approved() admits a trial (041).

create table if not exists public.pricing_feedback (
  id bigserial primary key,
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  too_cheap numeric check (too_cheap is null or (too_cheap >= 0 and too_cheap <= 10000)),
  bargain numeric check (bargain is null or (bargain >= 0 and bargain <= 10000)),
  getting_expensive numeric check (getting_expensive is null or (getting_expensive >= 0 and getting_expensive <= 10000)),
  too_expensive numeric check (too_expensive is null or (too_expensive >= 0 and too_expensive <= 10000)),
  plan text check (plan is null or plan in ('one_state', 'few_states', 'all_states', 'pay_per_list', 'would_not_pay')),
  buys text[] check (buys is null or buys <@ array['auctions', 'available', 'liens', 'learning']::text[]),
  comment text check (comment is null or char_length(comment) <= 1000),
  access_role text check (access_role is null or char_length(access_role) <= 20),
  created_at timestamptz not null default now()
);
create index if not exists pricing_feedback_user_time_idx on public.pricing_feedback (user_id, created_at desc);

alter table public.pricing_feedback enable row level security;
revoke all on table public.pricing_feedback from anon, authenticated;
grant insert (too_cheap, bargain, getting_expensive, too_expensive, plan, buys, comment, access_role)
  on table public.pricing_feedback to authenticated;
grant select on table public.pricing_feedback to authenticated;
grant usage, select on sequence public.pricing_feedback_id_seq to authenticated;
grant all on table public.pricing_feedback to service_role;

drop policy if exists "pricing_feedback: insert own" on public.pricing_feedback;
drop policy if exists "pricing_feedback: admin read" on public.pricing_feedback;
drop policy if exists "pricing_feedback: approved only" on public.pricing_feedback;
create policy "pricing_feedback: insert own" on public.pricing_feedback
  as permissive for insert to authenticated with check (user_id = (select auth.uid()));
create policy "pricing_feedback: admin read" on public.pricing_feedback
  as permissive for select to authenticated using ((select public.is_admin()));
create policy "pricing_feedback: approved only" on public.pricing_feedback
  as restrictive for all to authenticated using ((select public.is_approved())) with check ((select public.is_approved()));

comment on table public.pricing_feedback is
  '042: in-app willingness-to-pay answers (monthly USD). Insert own, admin read.';
