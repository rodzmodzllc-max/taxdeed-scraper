-- 039_preview_listings.sql
-- New-customer preview (2026-11-12, owner: "if it's free, you should
-- automatically be able to see blurred out items and not have the links").
-- NOT applied to production by this change - applying it needs the owner's
-- approval.
--
-- Why a SECURITY DEFINER function: an account waiting for approval reads no
-- listing at all (the properties policy requires is_approved(), and
-- get_properties / get_properties_list / get_property_provenance /
-- count_properties are SECURITY INVOKER). The app shows such an account a
-- Free preview of the real lists; this function is the ONLY thing it reads,
-- and it returns only fields that identify nothing:
--
--   preview_id    md5 of the row id with a fixed prefix - opaque, never the
--                 property's uuid, so it opens nothing anywhere else
--   state, county, source, source_id (names the kind of sale /
--                 list, e.g. "Tax lien sale"; no link, no identifier of a
--                 property)
--   land_use      the published property type / land use text
--   dor_use_code  the published use classification code
--   acreage       rounded to 2 decimals
--   lot_sqft      rounded to the nearest 100 square feet
--   sale_month    auctions only: the sale date truncated to its month
--
-- Never returned: address, parcel, case or certificate number, owner, any
-- amount (bid, minimum bid, purchase amount, assessed / market / land
-- values, last sale price), coordinates, photo, any url, document, the
-- acquisition record, provenance, publication internals.
--
-- Which rows: only rows a customer could see once approved, mirroring the
-- app's customer rules (app.js isPublishable) and, where unsure, stricter:
--   - signed-in callers only (auth.uid() is not null);
--   - status 'active' and not delisted;
--   - the source's publication decision is APPROVED, APPROVED_GRANDFATHERED
--     or not recorded (NULL) - the same rule the app applies to approved
--     customers (isPublishable: NULL keeps the row). Integrator's change
--     2026-11-12: production carries no decision on any Florida auction
--     (1,848 rows) or Florida lien (1,750 rows), so excluding NULL left a
--     waiting Florida customer with empty Auctions and Liens previews.
--     BLOCKED / UNREVIEWED / RESTRICTED are never returned;
--   - migration 031's per-row decision when that column exists: only
--     CUSTOMER_PUBLISHED (read through to_jsonb so this function works with
--     or without 031; once 031 is applied, NULL is never shown);
--   - the two Detroit Land Bank sources are left out entirely (the app shows
--     customers a deterministic subset of them; leaving them out is stricter);
--   - Available rows confirmed by their source in the last 7 days (the app's
--     unconfirmed-Available rule, UNCONFIRMED_DAYS);
--   - auctions with a sale date today or later (a passed sale is not open).
--
-- At most 60 rows per call (p_limit is capped), ordered deterministically.
-- EXECUTE: authenticated (and service_role) only - never anon or public.

create or replace function public.get_preview_listings(
  p_state text,
  p_ledger_type text default null,
  p_limit integer default 60,
  p_offset integer default 0)
returns table(
  preview_id text,
  state text,
  county text,
  source text,
  source_id text,
  land_use text,
  dor_use_code text,
  acreage numeric,
  lot_sqft integer,
  sale_month date
)
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select
    md5('tdw-preview:' || p.id::text) as preview_id,
    p.state,
    p.county,
    p.source,
    p.source_id,
    coalesce(nullif(btrim(p.prop_type), ''), nullif(btrim(p.land_use), '')) as land_use,
    nullif(btrim(p.dor_use_code), '') as dor_use_code,
    case when p.acreage > 0 then round(p.acreage, 2) end as acreage,
    case when p.lot_sqft > 0 then (round(p.lot_sqft / 100.0) * 100)::integer end as lot_sqft,
    case when p.source = 'auction' and p.sale_date is not null
         then date_trunc('month', p.sale_date)::date end as sale_month
  from public.properties p
  where auth.uid() is not null
    and p.state = p_state
    and (p_ledger_type is null or p.ledger_type = p_ledger_type)
    and p.status = 'active'
    and p.delisted_at is null
    and (p.publication_status is null or p.publication_status in ('APPROVED', 'APPROVED_GRANDFATHERED'))
    and coalesce(p.source_id, '') not in ('mi_detroit_landbank_lots', 'mi_detroit_landbank_programs')
    and (p.source <> 'laft' or p.last_seen_at >= now() - interval '7 days')
    and (p.source <> 'auction' or p.sale_date >= current_date)
    -- Whether 031's column exists is looked up once per call (an InitPlan);
    -- only then is a row read through to_jsonb. Testing every row with
    -- to_jsonb(p) ? ... cost 2.6 s on Missouri's list against 0.1 s this way
    -- (measured read-only on production, 2026-11-13).
    and (not exists (select 1 from pg_catalog.pg_attribute a
                     where a.attrelid = 'public.properties'::regclass
                       and a.attname = 'publication_state'
                       and a.attnum > 0 and not a.attisdropped)
         or to_jsonb(p) ->> 'publication_state' = 'CUSTOMER_PUBLISHED')
  order by p.county, p.source, p.id
  limit least(greatest(coalesce(p_limit, 60), 0), 60)
  offset greatest(coalesce(p_offset, 0), 0);
$$;

comment on function public.get_preview_listings(text, text, integer, integer) is
  'Free preview for accounts awaiting approval (2026-11-12): safe fields only (opaque id, state, county, source, land use, rounded size, auction sale month) of customer-publishable rows; max 60 per call.';

revoke all on function public.get_preview_listings(text, text, integer, integer) from public, anon;
grant execute on function public.get_preview_listings(text, text, integer, integer) to authenticated, service_role;
