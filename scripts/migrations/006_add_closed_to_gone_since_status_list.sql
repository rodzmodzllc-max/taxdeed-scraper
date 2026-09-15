-- Adds 'closed' to the status list the gone_since trigger pair treats as
-- "gone" - closing the mismatch Phase 29/30 found between the trigger's
-- vocabulary and the application's.
--
-- Background: `properties_gone_since` (BEFORE UPDATE -> track_gone_since())
-- and `properties_gone_since_ins` (BEFORE INSERT -> track_gone_since_insert())
-- are live, verified-in-production triggers that stamp `gone_since` the
-- moment `status` transitions into a "gone" set, and clear it if a row ever
-- transitions back out. Both functions currently define that set as
-- ('dropped','sold','notfound') only. Live status-vocabulary verification
-- this phase (see claude/phase-29-30-backend-audit-and-readiness-gate.md,
-- Area 7/8) found FL auction rows actually use 'closed' as a real, live
-- status - not 'sold', which has never been observed - and app.js's own
-- GONE_STATUSES constant is `["dropped","sold","notfound","closed"]`,
-- explicitly expecting `closed` to be tracked the same way. Without this
-- fix, an FL auction property transitioning to 'closed' (exactly the
-- transition sync-harvest-to-supabase.ps1's stale-property closeout
-- performs - see 30B's changes to that script) never gets `gone_since`
-- stamped, and the UPDATE trigger's `elsif not gone_now` branch actively
-- NULLs it if the row had one from an earlier transition, since 'closed'
-- wasn't in the recognized set.
--
-- Fix: CREATE OR REPLACE both function bodies with 'closed' added to the
-- IN (...) list. This is not a trigger redesign - the trigger definitions
-- themselves (`properties_gone_since` / `properties_gone_since_ins`, i.e.
-- the actual CREATE-TRIGGER-time bindings of function to table/event) are
-- untouched, same function names, same firing timing, same columns.
-- 'sold' is left in place even though nothing currently writes it - removing
-- it isn't this migration's job, and there's no correctness reason to.
--
-- Schema-management note (Phase 30B, Part 4): this repo's own CLAUDE.md and
-- prior audits (Phase 26, Phase 29 Area 1) reference `schema-v2-gone-tracking.sql`
-- as the trigger pair's origin, but that file - along with schema.sql/v1
-- and schema-v3-calendar.sql - does not exist anywhere in this repository's
-- tracked history (confirmed this phase: absent from the working tree AND
-- from `git log --all` across every branch/commit). The
-- trigger pair was evidently applied by hand directly against Supabase at
-- some point and was never captured as a tracked migration at all. Given
-- that, and given no schema-v2 file exists to "correct", this fix follows
-- the newer, actually-used `scripts/migrations/NNN_*.sql` numbered series
-- (002-005a) instead of inventing a conflicting schema-v* convention that
-- has no real precedent in this repo to build on.
--
-- NOT YET RUN against production as of this commit - paste into the
-- Supabase SQL Editor and run by hand (see CLAUDE.md: raw DDL can't be
-- typed into that editor via browser automation), same deployment-ordering
-- note as every other file in this directory.

create or replace function public.track_gone_since()
returns trigger
language plpgsql
as $function$
declare
  gone_now  boolean := new.status in ('dropped','sold','notfound','closed');
  gone_was  boolean := coalesce(old.status,'') in ('dropped','sold','notfound','closed');
begin
  if gone_now and not gone_was then
    new.gone_since := now();          -- just went away: start the clock
  elsif not gone_now then
    new.gone_since := null;           -- came back (redemption reversed): clear it
  else
    new.gone_since := old.gone_since; -- still gone: keep the original timestamp
  end if;
  return new;
end
$function$;

create or replace function public.track_gone_since_insert()
returns trigger
language plpgsql
as $function$
begin
  if new.status in ('dropped','sold','notfound','closed') and new.gone_since is null then
    new.gone_since := now();
  end if;
  return new;
end
$function$;

comment on function public.track_gone_since() is
  'BEFORE UPDATE trigger function for properties_gone_since. Stamps/clears gone_since on transitions into or out of the gone-status set (dropped, sold, notfound, closed - closed added by 006_add_closed_to_gone_since_status_list.sql). No source/state filter - applies project-wide.';

comment on function public.track_gone_since_insert() is
  'BEFORE INSERT trigger function for properties_gone_since_ins. Stamps gone_since on insert when a row arrives already in the gone-status set (dropped, sold, notfound, closed - closed added by 006_add_closed_to_gone_since_status_list.sql) with no gone_since already supplied.';
