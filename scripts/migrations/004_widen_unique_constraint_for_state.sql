-- Widens properties' unique constraint to include `state`, closing a
-- cross-state collision risk that 002_add_texas_support.sql introduced but
-- did not itself fix.
--
-- The problem: `properties` has been unique on (source, county, case_no)
-- since the original schema, back when every row was implicitly Florida.
-- 002_add_texas_support.sql added a `state` column (default 'FL') but left
-- that constraint untouched. Florida and Texas both have counties that
-- share a name - Orange County, Jefferson County, Madison County, Lake
-- County, and more - and a county's tax-sale case numbering is set by that
-- county/vendor, not by this app, so two genuinely different properties
-- (one in FL Orange County, one in TX Orange County) can land on the exact
-- same (source, county, case_no) key. Today that's a silent upsert
-- collision: the second state's harvest would overwrite the first's row
-- instead of creating its own, because Postgres has no way to know they're
-- different properties without `state` in the key.
--
-- The fix: drop the narrow constraint and replace it with one that also
-- includes `state`. This is a REPLACE, not an addition - Postgres enforces
-- every unique constraint on a table independently and simultaneously, so
-- leaving the old narrow one in place would keep blocking the exact
-- cross-state pairs this migration exists to allow. Dropping it is safe:
-- every row satisfying the old (source, county, case_no) uniqueness
-- trivially satisfies the new, wider (state, source, county, case_no)
-- uniqueness too, so no existing data can violate the replacement.
--
-- Ordering: run this after 002_add_texas_support.sql (needs the `state`
-- column to exist) and after 003_ledger_type_and_state_isolation.sql (no
-- hard dependency, but that's the migration that made state-scoping visible
-- at the API layer via get_properties() - this one is the matching fix at
-- the write path). Safe to run before Texas harvesting actually starts;
-- it's a no-op risk-wise for FL-only data since state is uniformly 'FL'
-- today.
--
-- Deployment-ordering note (see CLAUDE.md - migrations in this repo
-- routinely get committed well before they're actually run against
-- production): the three FL sync scripts
-- (sync-harvest-to-supabase.ps1, sync-certificates-to-supabase.ps1,
-- sync-laft-to-supabase.ps1) are updated in the same commit as this file to
-- target the new `on_conflict=state,source,county,case_no`, WITH a runtime
-- fallback to the old `on_conflict=source,county,case_no` target if
-- Postgres/PostgREST reports error 42P10 ("no unique or exclusion
-- constraint matching the ON CONFLICT specification") - i.e. if this
-- migration hasn't been run yet against the Supabase project those scripts
-- are pointed at. That means the sync jobs keep working whether this file
-- has been run or not; running it just turns on the wider, collision-safe
-- key.
--
-- NOT YET RUN against production as of this commit - paste into the
-- Supabase SQL Editor and run by hand (see CLAUDE.md: raw DDL can't be
-- typed into that editor via browser automation).

alter table public.properties
  drop constraint if exists properties_source_county_case_no_key;

alter table public.properties
  add constraint properties_state_source_county_case_no_key
  unique (state, source, county, case_no);

comment on constraint properties_state_source_county_case_no_key on public.properties is
  'Replaces the old (source, county, case_no) uniqueness (dropped by this same migration) so that two different states'' same-named counties (e.g. FL Orange County vs TX Orange County) can never collide on one upserted row.';
