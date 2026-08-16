-- FL Tax Deed Watchlist — "auctions closing soon" email digest
-- Run this once in the Supabase SQL Editor (Dashboard -> SQL Editor -> New query),
-- AFTER schema.sql / schema-v2/v3/v4 have already been applied.
--
-- This adds one function, digest_candidates(), that the send-digest Edge
-- Function (see supabase/functions/send-digest/) calls to find, per user,
-- which of their FAVORITED auctions have a sale_date coming up in the next
-- N days. It does not touch any existing table.
--
-- Locked to service_role only (same pattern as the sync script's writes to
-- `properties`) - no anon/authenticated client should ever call this
-- directly, since it returns other users' favorite lists.

create or replace function public.digest_candidates(days_ahead int default 7)
returns table (
  user_id      uuid,
  property_id  uuid,
  county       text,
  address      text,
  case_no      text,
  bid          numeric,
  market       numeric,
  sale_date    date,
  url_auction  text,
  days_out     int
)
language sql
security definer
set search_path = public
as $$
  select
    f.user_id,
    p.id,
    p.county,
    p.address,
    p.case_no,
    p.bid,
    p.market,
    p.sale_date,
    p.url_auction,
    (p.sale_date - current_date)::int as days_out
  from public.favorites f
  join public.properties p on p.id = f.property_id
  where p.source = 'auction'
    and p.status = 'active'
    and p.sale_date is not null
    and p.sale_date >= current_date
    and p.sale_date <= current_date + days_ahead
  order by f.user_id, p.sale_date asc;
$$;

revoke all on function public.digest_candidates(int) from public, anon, authenticated;
grant execute on function public.digest_candidates(int) to service_role;
