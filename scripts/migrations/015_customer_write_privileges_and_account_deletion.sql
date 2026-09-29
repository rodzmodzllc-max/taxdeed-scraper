-- Migration 015: customers read shared property intelligence, they never
-- write it; and a customer can delete their own account.
--
-- STATUS: PROPOSED, NOT APPLIED. Written for the SaaS launch-readiness
-- hardening PR (2026-09-29). Like every migration in this directory it is
-- applied by hand, by the project owner, after review - never by CI, never
-- by the assistant session that wrote it. See "HOW TO APPLY" at the bottom.
--
-- ============================================================
-- WHY (facts read live from pg_policies / information_schema, 2026-09-29)
-- ============================================================
--
-- 1. `properties` is the shared property-intelligence table every customer
--    reads. Its ONLY policy today is
--
--        "properties: approved only"  PERMISSIVE  FOR ALL  TO public
--            USING (is_approved())  WITH CHECK (is_approved())
--
--    and the `authenticated` role holds table-level INSERT, UPDATE, DELETE,
--    TRUNCATE, REFERENCES and TRIGGER on it (SELECT is column-level, from
--    005a). Put together: any APPROVED customer can insert, update or delete
--    ANY row of the shared dataset through the REST API - the RLS policy
--    passes for every row once is_approved() is true. The frontend never
--    does this (public/app.js reads via get_properties() and a SELECT
--    fallback only - see the "app query inspection" note below), so nothing
--    a customer can click exercises it, but the privilege is real and a
--    PostgREST call needs no click. `anon` holds the same six write
--    privileges (no SELECT) - RLS blocks anon at the row level, but the
--    grant is a door that only RLS is holding shut.
--
-- 2. `county_calendar` has the identical shape ("county_calendar: approved
--    only", FOR ALL, plus full DML grants to anon/authenticated). The app
--    only ever SELECTs it (app.js:1837).
--
-- 3. `notes`, `favorites`, `hidden`, `bid_list`, `profiles`: RLS is correct
--    (own-row PERMISSIVE + approved-only RESTRICTIVE; profiles: read-own +
--    admin-all), but `anon` holds full DML grants it can never legitimately
--    use, and `authenticated` holds TRUNCATE/REFERENCES/TRIGGER. TRUNCATE is
--    NOT subject to row-level security - it is a table privilege, and a
--    role that holds it can empty the table regardless of policies.
--
-- 4. Nine legacy tables the frontend has never referenced (`auction_records`,
--    `auctions`, `tax_auctions`, `tax_deeds`, `tax_liens`,
--    `scrape_review_queue`, `scraper_review_queue`, `scraping_logs`,
--    `states` - see CLAUDE.md "Data model", the remains of the removed
--    scraper.js subsystem) still grant anon/authenticated full DML.
--    `tax_auctions` and `states` even carry a `USING (true)` public-read
--    policy. tests/python/test_migration_015_customer_privileges.py
--    asserts, from the frontend source, that none of these names is read
--    by the app - this is a grep-backed revoke, not a blind one.
--
-- 5. Supabase's security advisor flags two SECURITY DEFINER trigger
--    functions (`handle_new_user`, `enforce_bid_list_limit`) as executable
--    by anon/authenticated, and eight functions with a mutable search_path
--    (`get_properties`, `properties_sync_geom`, `set_updated_at`,
--    `sync_ledger_type_from_source`, `touch_updated_at`, `track_gone_since`,
--    `track_gone_since_insert`, `update_modified_column`). Trigger functions
--    are only ever invoked by their trigger (EXECUTE is checked when the
--    trigger is created, not when it fires - verified in the live test layer
--    below by inserting into bid_list as `authenticated` after the revoke),
--    so no client role needs EXECUTE on them.
--
-- 6. There is no way for a customer to delete their own account. The
--    browser client has no service role (correctly), and Supabase's
--    supported pattern for self-service deletion is a SECURITY DEFINER
--    function that deletes the caller's own `auth.users` row; every
--    customer-owned table already cascades from auth.users (notes.author_id,
--    favorites/hidden/bid_list.user_id, profiles.id - all ON DELETE CASCADE,
--    read live). `auth.identities`, `auth.sessions`, `auth.mfa_factors`,
--    `auth.one_time_tokens` etc. also cascade from auth.users. The `postgres`
--    role that owns this function holds DELETE on auth.users (verified via
--    has_table_privilege, live).
--
-- App query inspection (the "do not blindly revoke" check): every
-- `sb.from(...)` and `sb.rpc(...)` in public/app.js, explore.js and
-- satellite-map.js was enumerated before writing this file. `properties`:
-- rpc get_properties + `.select("*")` fallback only. `county_calendar`:
-- `.select(...)` only. `profiles`: select own / admin update (approve,
-- revoke) - unchanged here. `notes`/`favorites`/`hidden`/`bid_list`: own-row
-- insert/upsert/update/delete - unchanged here. Nothing else. The harvest,
-- sync, geocode, photo, flood, FDOR and Phase B writers all use
-- SUPABASE_SERVICE_KEY (service_role), which this file does not touch.
--
-- ============================================================
-- WHAT THIS DOES NOT DO
-- ============================================================
--   - Does not change get_properties() (013 stays the current projection),
--     any customer-safe column list, or 005a's column-level SELECT grant.
--   - Does not change the notes visibility model: notes stay readable by
--     every approved member ("notes: read if approved"). The UI labels this
--     (see the same PR); the policy is not touched.
--   - Does not touch service_role, any harvester, sync or backup path.
--   - Does not delete, alter or backfill any row.
--   - Does not touch PostGIS-owned objects (spatial_ref_sys,
--     geometry_columns, geography_columns): they are owned by
--     supabase_admin, so `postgres` cannot REVOKE on them. Documented in
--     docs/production-configuration.md as a known, accepted advisor item.
--   - Does not enable leaked-password protection or any other Auth
--     dashboard setting - those are not SQL. See docs/production-
--     configuration.md.
--
-- ============================================================
-- ROLLBACK (metadata only; nothing here touches data)
-- ============================================================
--   drop policy "properties: approved read" on public.properties;
--   create policy "properties: approved only" on public.properties
--     as permissive for all to public
--     using (public.is_approved()) with check (public.is_approved());
--   grant insert, update, delete, truncate, references, trigger
--     on public.properties to anon, authenticated;
--   -- county_calendar: same three statements with its own names.
--   grant all on public.notes, public.favorites, public.hidden,
--     public.bid_list, public.profiles to anon;
--   grant truncate, references, trigger on public.notes, public.favorites,
--     public.hidden, public.bid_list, public.profiles to authenticated;
--   grant all on <each legacy table> to anon, authenticated;
--   grant execute on function public.handle_new_user(),
--     public.enforce_bid_list_limit() to anon, authenticated, public;
--   alter function <each of the eight> reset search_path;
--   drop function public.delete_my_account();
--
-- ============================================================
-- HOW TO APPLY
-- ============================================================
--   1. Read pg_policies for `properties` and `county_calendar` and confirm
--      each still has exactly the one FOR ALL policy named above. If a
--      second PERMISSIVE policy has appeared since 2026-09-29, re-read the
--      RESTRICTIVE/PERMISSIVE lesson in CLAUDE.md before continuing.
--   2. Run this file in one transaction (it is wrapped in begin/commit).
--      The new SELECT policy is created BEFORE the FOR ALL policy is
--      dropped, so at no point does `properties` have zero permissive
--      policies - the exact outage CLAUDE.md records from 2026-08-24.
--   3. Smoke test, as an approved customer: the app loads and renders
--      cards; `POST /rest/v1/properties` returns 42501 (permission denied);
--      favorites/hidden/bid list/notes still add and remove; an admin can
--      still approve a pending profile. As service_role: the next scheduled
--      harvest sync upserts normally.
--   4. Deploy the frontend from the same PR (it calls delete_my_account()
--      and shows the account-deletion control). Deploying the frontend
--      first is harmless: the control reports "not available yet" when the
--      RPC is missing.

begin;

-- ------------------------------------------------------------
-- 1. properties: approved customers read; nobody but service_role writes
-- ------------------------------------------------------------
create policy "properties: approved read" on public.properties
  as permissive for select to authenticated
  using (public.is_approved());

drop policy "properties: approved only" on public.properties;

revoke insert, update, delete, truncate, references, trigger
  on public.properties from anon, authenticated;

-- ------------------------------------------------------------
-- 2. county_calendar: same posture
-- ------------------------------------------------------------
create policy "county_calendar: approved read" on public.county_calendar
  as permissive for select to authenticated
  using (public.is_approved());

drop policy "county_calendar: approved only" on public.county_calendar;

revoke insert, update, delete, truncate, references, trigger
  on public.county_calendar from anon, authenticated;
revoke select on public.county_calendar from anon;

-- ------------------------------------------------------------
-- 3. customer-owned tables: anon gets nothing; authenticated keeps DML only
--    (row-level policies - unchanged - decide which rows)
-- ------------------------------------------------------------
revoke all on public.notes, public.favorites, public.hidden,
  public.bid_list, public.profiles from anon;

revoke truncate, references, trigger
  on public.notes, public.favorites, public.hidden,
  public.bid_list, public.profiles from authenticated;

-- ------------------------------------------------------------
-- 4. legacy tables the app never reads: closed to both client roles
-- ------------------------------------------------------------
revoke all on public.auction_records, public.auctions, public.tax_auctions,
  public.tax_deeds, public.tax_liens, public.scrape_review_queue,
  public.scraper_review_queue, public.scraping_logs, public.states
  from anon, authenticated;

-- ------------------------------------------------------------
-- 5. trigger functions are not an API; pin every mutable search_path
-- ------------------------------------------------------------
revoke execute on function public.handle_new_user() from public, anon, authenticated;
revoke execute on function public.enforce_bid_list_limit() from public, anon, authenticated;

alter function public.get_properties(text, text, text, integer, integer) set search_path = public;
alter function public.properties_sync_geom() set search_path = public;
alter function public.set_updated_at() set search_path = public;
alter function public.sync_ledger_type_from_source() set search_path = public;
alter function public.touch_updated_at() set search_path = public;
alter function public.track_gone_since() set search_path = public;
alter function public.track_gone_since_insert() set search_path = public;
alter function public.update_modified_column() set search_path = public;

-- ------------------------------------------------------------
-- 6. self-service account deletion
-- ------------------------------------------------------------
-- Deletes the CALLER's account and nothing else. The explicit deletes of
-- the customer-owned rows are redundant with the ON DELETE CASCADE
-- constraints (all verified live) and are kept so the function states, in
-- one place, exactly which tables hold customer-owned data. Shared property
-- intelligence (`properties`, `county_calendar`, `auction_events`,
-- `auction_event_observations`) is never touched: none of it is keyed by a
-- user, and this function names none of it.
create function public.delete_my_account()
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  uid uuid := auth.uid();
begin
  if uid is null then
    raise exception 'delete_my_account: no signed-in user' using errcode = '28000';
  end if;
  delete from public.notes     where author_id = uid;
  delete from public.favorites where user_id  = uid;
  delete from public.hidden    where user_id  = uid;
  delete from public.bid_list  where user_id  = uid;
  delete from public.profiles  where id       = uid;
  delete from auth.users       where id       = uid;
end;
$$;

revoke execute on function public.delete_my_account() from public, anon;
grant execute on function public.delete_my_account() to authenticated;

commit;
