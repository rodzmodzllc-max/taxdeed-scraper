-- PROPOSED, NOT YET RUN. Written and reviewed as part of Phase 14A
-- (Production Customer-Safety Hardening), 2026-09-14 - matching this
-- repo's own long-standing convention (see CLAUDE.md, and every prior
-- migration file's own header) of writing a migration well before it is
-- actually run against production, by hand, in the Supabase SQL Editor.
--
-- Phase 14A's own hard rules for this session explicitly forbid applying
-- any Supabase schema/RLS/RPC change this phase ("default assumption is
-- NO schema migration in Phase 14A" / "Do not create RLS policies
-- speculatively" / "STOP before applying" any fix that needs one). This
-- file is the Step 20 deliverable for that rule: WHY REQUIRED / CURRENT
-- LIMITATION / TARGET ARCHITECTURE / MIGRATION STEPS / ROLLBACK STRATEGY /
-- DATA-SAFETY CONSIDERATIONS / TEST PLAN, all below, plus the actual SQL a
-- human would run once they decide to. It is committed so the exact
-- proposal is reviewable in this session's Phase 14A commit - it is NOT
-- executed by this session, and this session has no credentials that
-- could execute it even if that rule did not exist.
--
-- ============================================================
-- WHY REQUIRED
-- ============================================================
-- docs/production-data-contract.md (Phase 13) and
-- docs/phase-14a-customer-safety-hardening.md (this phase) both confirm,
-- by tracing the actual code (not assuming): get_properties()
-- (003_ledger_type_and_state_isolation.sql) is defined as
-- `returns setof public.properties` with a body of `select * from
-- properties where ...` - every column on the table, with no projection
-- of any kind. The same is true of the unscoped fallback path
-- (`sb.from("properties").select("*")`) public/app.js's fetchProperties()
-- uses if the RPC is ever missing. Postgres RLS (is_approved(), etc.)
-- restricts which ROWS an approved user can read - it has no mechanism to
-- restrict which COLUMNS of an allowed row are returned. This means
-- `harvester_source`, `ledger_type`, and `fdor_enriched_at` (Phase 13's
-- "internal, code-convention-only" fields - see that doc's Section 6) are
-- transmitted to every approved browser session today, in full. "The
-- frontend doesn't display it" is not access control on its own - a
-- different client calling the same authenticated Supabase REST/RPC
-- endpoint would see them without needing to bypass anything - and, per
-- the Phase 14B correction just above, `harvester_source` specifically
-- is NOT one this migration can safely omit: app.js's own
-- assessedSourceLabel() now legitimately reads it. `ledger_type`/
-- `fdor_enriched_at` remain genuinely internal and are what this
-- migration actually closes.
--
-- ============================================================
-- CURRENT LIMITATION
-- ============================================================
-- No production code path in this repository has ever restricted
-- `properties` at the column level. `filter_rows_for_customer_output()` /
-- `project_row_for_customer_output()` (harvesters/governance/gate.py,
-- Phase 10A/11) run entirely on the WRITE path, inside
-- scripts/sync-texas-to-supabase.py, before a row ever reaches Supabase -
-- they have no read-path counterpart and cannot have one without a
-- database object (function/view) that actually performs a column
-- projection, which is exactly what this migration proposes.
--
-- The three fields identified above carry no restricted/legally-sensitive
-- content today (they are pipeline bookkeeping: which vendor produced a
-- row, which of the three ledgers it's canonically mapped to, and when
-- FDOR enrichment last touched it) - so this is not, today, a governance
-- violation or a customer-data leak of anything sensitive. It is a real
-- architectural gap that would become a genuine risk the moment a future
-- field legitimately needs to be internal-only for a real reason (a
-- vendor contract term, an internal QA flag, a future raw-payload
-- reference) - Phase 13 and this phase both flag it now, before that
-- day, rather than after.
--
-- ============================================================
-- TARGET ARCHITECTURE
-- ============================================================
-- Replace get_properties()'s body so it returns an explicit, named column
-- list (the same ~46-field customer-visible inventory
-- docs/production-data-contract.md Section 5 already documents as
-- authoritative, mapped back from CSV-export labels to real DB column
-- names) instead of `select *`. Because public/app.js's fetchProperties()
-- already only ever reads known field names off whatever get_properties()
-- returns (confirmed this phase - zero references to harvester_source,
-- ledger_type, or fdor_enriched_at anywhere in app.js), this is a
-- backward-compatible, drop-in replacement: the RPC's name and parameter
-- signature (p_state, p_ledger_type, p_status, p_limit, p_offset) do not
-- change, so no frontend deploy is required alongside it.
--
-- This migration closes the RPC path. It deliberately does NOT close the
-- second path (unscoped `sb.from("properties").select("*")`, and any
-- other authenticated client hitting `/rest/v1/properties` directly) -
-- that would require either (a) revoking SELECT on the base table from
-- the `authenticated`/`anon` roles entirely (forcing every reader through
-- a function/view), or (b) replacing the table's default PostgREST
-- exposure with a narrower VIEW and adjusting grants so the raw table is
-- no longer part of the exposed API surface. Both are materially larger,
-- riskier changes (they affect every existing authenticated query against
-- `properties`, including the fallback path app.js itself still relies on
-- for resilience against a not-yet-migrated project - see
-- fetchProperties()'s own comment) and are explicitly NOT proposed for
-- execution in this file. They are named here as the honest, full target
-- architecture; a future phase should design and test that change on its
-- own, with its own rollback plan, once get_properties() is confirmed
-- deployed and stable everywhere it's needed.
--
-- ============================================================
-- MIGRATION STEPS (for a human to run by hand, per this repo's own
-- established process - see CLAUDE.md on why raw DDL can't be typed into
-- the Supabase SQL Editor via browser automation)
-- ============================================================
-- 1. Confirm, live, the exact current column list of public.properties
--    (this file's SELECT list below was built from every migration file
--    and every sync/enrichment script this repository's git history
--    contains - see docs/production-data-contract.md Section 5/24 for the
--    honest caveat that this repo's history does not itself contain a
--    schema.sql/v2/v3, so information_schema is the only full source of
--    truth for whether a column this file assumes exists actually does).
-- 2. Run the CREATE OR REPLACE FUNCTION statement below.
-- 3. Confirm get_properties(p_state) still returns every field
--    public/app.js currently reads (the full list is in
--    docs/production-data-contract.md Section 5/18) - a smoke test against
--    a non-production project (or a Supabase branch, if available) is the
--    right way to verify this before running it against the real project.
-- 4. Confirm the CSV export and every card still render identically (no
--    visual/behavioral diff expected, since every dropped column was
--    already unused by the frontend).
-- 5. Separately, and NOT part of this file, decide on the raw-REST-path
--    closure (see TARGET ARCHITECTURE above) as its own future migration.
--
-- ============================================================
-- ROLLBACK STRATEGY
-- ============================================================
-- `CREATE OR REPLACE FUNCTION` is not destructive to data - rolling back
-- is re-running the CURRENT (pre-this-migration) function body, i.e.
-- `returns setof public.properties` / `select * from properties where
-- ...`, exactly as 003_ledger_type_and_state_isolation.sql defined it.
-- Keep that original definition (reproduced in this file's own comment
-- block, Step 6 area, unchanged from that file) so a rollback is a single
-- copy-paste, not a re-derivation. No column, table, or row is ever
-- dropped or altered by this migration - purely a function-body swap.
--
-- ============================================================
-- DATA-SAFETY CONSIDERATIONS
-- ============================================================
-- - No existing row is modified, added, or deleted by this migration.
-- - No RLS policy changes - `security invoker` is preserved exactly as
--   003_ledger_type_and_state_isolation.sql already set it, so the exact
--   same is_approved()-gated row-level access applies before and after.
-- - No grant changes - `grant execute ... to authenticated` stays as-is.
-- - The only behavior change is which COLUMNS come back from this one
--   function - confirmed harmless to the current frontend by the same
--   "zero references anywhere in app.js" check this phase's own tests
--   (Section below) perform against the *current* function definition's
--   column list, which this proposal preserves entirely (adds no new
--   customer-visible column, removes only the three internal ones).
--
-- ============================================================
-- TEST PLAN
-- ============================================================
-- - Before running: confirm (via information_schema, live) that every
--   column named in the SELECT list below actually exists on the live
--   `properties` table - a column present in this repo's own migration
--   files but never actually run against this particular Supabase
--   project (the exact failure mode CLAUDE.md warns about for
--   schema-v4/v7/v8) would make this function fail outright rather than
--   silently return fewer columns, which is the correct fail-closed
--   behavior but should be caught before relying on it in production.
-- - After running: re-run this repo's existing Playwright frontend
--   regression (tests/run_test.mjs) against a page pointed at the
--   updated function, confirming card rendering, CSV export, and every
--   filter still work identically.
-- - After running: confirm directly (a raw REST call, or the SQL Editor)
--   that `select harvester_source from properties limit 1` via the
--   `get_properties` RPC's result no longer includes that key, while a
--   direct `select * from properties` (service_role or an admin session)
--   still can, for whoever legitimately needs it internally.
--
-- ============================================================
-- THE PROPOSED FUNCTION (NOT EXECUTED BY THIS SESSION)
-- ============================================================
-- `ledger_type` and `fdor_enriched_at` are deliberately absent from the
-- RETURNS TABLE column list below - not renamed, not nulled-out, simply
-- not selected. `ledger_type` is pipeline-routing metadata derived from
-- `source` by sync_ledger_type_from_source(); the frontend already
-- re-derives everything it needs from `source`/PAGE_STATE and never reads
-- ledger_type directly (confirmed - zero references anywhere in
-- public/app.js, re-confirmed again Phase 14B). `fdor_enriched_at` is
-- pipeline bookkeeping with the same "never read by app.js" confirmation.
--
-- CORRECTION, Phase 14B: `harvester_source` was originally on this
-- deliberately-absent list too (Phase 14A's own reasoning at the time was
-- correct - as of Phase 13, app.js truly never read it). That stopped
-- being true within Phase 14A itself: the same phase's own
-- `assessedSourceLabel(p)` fix (public/app.js) reads `p.harvester_source`
-- directly to tell tx_lgbs rows from tx_realauction rows apart, so a
-- Texas row's assessed-value label is CORRECT today only because
-- `harvester_source` is still available on the row. Phase 14B's own fresh
-- test suite (tests/python/test_phase14b_database_api_boundary.py, group
-- J) caught this drift by re-checking app.js directly rather than trusting
-- this file's own prior claim. `harvester_source` therefore moved back
-- into the returned/selected column list below - it is a source-vendor
-- code (e.g. "tx_lgbs"), not sensitive data, and the frontend now has a
-- real, legitimate, load-bearing reason to read it. Omitting `ledger_type`
-- and `fdor_enriched_at` remains the point of this migration for those two
-- - returning either of them under a different name or a nulled
-- placeholder would not close the exposure this file exists to close for
-- them.
--
-- CORRECTION, Phase 14D (Migration Reconciliation & Pre-Execution Re-Gate):
-- Phase 14C's live preflight (docs/phase-14c-production-migration-
-- verification.md) found this file, as written through Phase 14B, named
-- three columns - `outcome`, `sold_price`, `dor_use_code` - that do not
-- exist on the live `public.properties` table (confirmed via a direct
-- information_schema.columns query against production: exactly 47 real
-- columns, none of the three among them). Running this migration as-is
-- would fail outright with a Postgres "column does not exist" error. Phase
-- 14D's own repo-only reconciliation (docs/phase-14d-migration-
-- reconciliation.md has the full analysis) found the three columns are NOT
-- symmetric and resolved them differently:
--
--   * `outcome` and `sold_price` are REMOVED from the RETURNS TABLE/SELECT
--     lists below. Neither has a writer anywhere in this repository
--     (scripts/*.py, scripts/*.ps1, harvesters/*.py all confirmed to have
--     zero references) and neither has ever had a tracked migration
--     proposing to add them to `public.properties` - the only two places
--     in this repo's entire git history that ever named them are this file
--     and 005a, both written by Phase 14A/14B from Phase 13's field
--     inventory without verifying a migration or live column actually
--     backed them. The claude.ai Project's own historical docs
--     (claude/closed-outcome-and-map-cities.md,
--     claude/header-account-terms-and-the-deploy-mirror-gap.md) confirm
--     `outcome`/`sold_price` are a deliberately-built-ahead-of-schedule
--     frontend feature: public/app.js's `outcomeText()` and `OUTCOME_LABEL`
--     already read `p.outcome`/`p.sold_price` defensively and fall back to
--     today's `status`-only behavior, specifically so "it starts working
--     the day the pipeline fills them in, with no further frontend
--     change" - the backend/harvester half of that work was explicitly
--     handed off and was never built by any session since. Omitting them
--     here changes nothing observable (the frontend already tolerates
--     their absence); a future phase that actually builds the outcome-
--     capture harvester work should add them back via their own dedicated,
--     tracked migration at that time - not by reintroducing them here
--     speculatively.
--   * `dor_use_code` is KEPT in both lists below, unlike the two above -
--     unlike `outcome`/`sold_price`, it already has a real, tracked,
--     purely-additive migration (schema-v9-dor-use-code.sql, committed
--     2026-09-08) and a real, currently-functioning writer
--     (scripts/enrich_property_details.py, which has populated it on its
--     normal per-county schedule since 2026-09-02) - it is a genuinely
--     intended, already-half-deployed part of the customer contract that
--     simply never had its own migration run against this particular
--     Supabase project (the same "tracked-but-never-run" failure pattern
--     CLAUDE.md already documents for schema-v4/v5/v7/v8). Because this
--     migration will fail if `dor_use_code` does not exist yet,
--     schema-v9-dor-use-code.sql is now a formal, documented prerequisite
--     of this file: THIS MIGRATION MUST NOT BE RUN UNTIL
--     schema-v9-dor-use-code.sql HAS BEEN RUN AND CONFIRMED LIVE. See
--     docs/phase-14d-migration-reconciliation.md for the full corrected
--     execution order and the pre-execution checklist that must be re-run
--     (a fresh Gate A) before either file is applied.
--
-- CORRECTION, Phase 14E (Corrective Migration 005 / get_properties()
-- Function Contract). Phase 14C's execution attempt applied schema-v9
-- successfully, then this file FAILED against live production with:
--
--   ERROR:  42P13: cannot change return type of existing function
--   HINT:  Use DROP FUNCTION get_properties(text,text,text,integer,integer)
--          first.
--
-- Root cause: the live function is `returns setof public.properties`
-- (003_ledger_type_and_state_isolation.sql's original shape); this file
-- replaces it with an explicit, named TABLE-of-columns return clause
-- below. Postgres treats a `SETOF <table>` result and a named-columns
-- TABLE result as different return-type shapes - `CREATE OR REPLACE
-- FUNCTION` can change a function's body freely but never its return
-- type; that requires dropping the function first. This was a genuine
-- defect in this file's own design, present
-- since Phase 14A first wrote it and never caught by any of Phases
-- 14A/14B/14C/14D/14E's own review - every one of those reviews was
-- static (reading SQL text, reasoning about columns/grants/RLS); this is
-- the first phase to actually attempt the statement against the live
-- function, which is what surfaced it. Full account:
-- docs/phase-14f-production-migration-execution-attempt.md.
--
-- Fix: an explicit `drop function if exists ...` immediately before the
-- (unchanged) `create or replace function`, both inside one transaction
-- so no caller ever observes the function absent - Postgres DDL is
-- already transactional and an uncommitted DROP is invisible to other
-- sessions, but the transaction is made explicit here for clarity and so
-- this file does not depend on the calling tool's own default behavior.
-- `drop function if exists` (not a bare `drop function`) so this file
-- stays idempotent if re-run after a partial/aborted attempt.
--
-- EXECUTE grant, corrected to avoid a silent privilege loss: this file
-- previously granted EXECUTE to `authenticated` only (matching
-- 003_ledger_type_and_state_isolation.sql's own original grant exactly).
-- Phase 14C/14E's live audit found the *actual* live grant is broader -
-- `service_role`, `authenticated`, `anon`, `postgres`, and `PUBLIC` all
-- currently hold EXECUTE (PUBLIC alone already implies the other four;
-- the live state lists them individually too, most likely from Supabase's
-- own default project-template grants predating this project's own
-- migrations, not anything 003 itself granted). Because `DROP FUNCTION`
-- discards every grant the dropped function held, and this phase's own
-- hard rule is "do not silently lose EXECUTE privileges," the grant
-- statement below reproduces the exact live set rather than narrowing to
-- just `authenticated` - narrowing this (a real, separate security
-- decision, the same class of question as the TRUNCATE/write-grant item)
-- is explicitly left to a future, separately-scoped phase, not decided
-- here as a side effect of fixing the return-type defect.
--
-- CRITICAL FINDING, also Phase 14E: this function's own WHERE clause
-- reads `ledger_type` (`... and (p_ledger_type is null or ledger_type =
-- p_ledger_type) ...`) even though `ledger_type` is deliberately never
-- part of this function's RETURNS TABLE/SELECT output (it is one of the
-- two genuinely-internal fields this migration exists to stop exposing).
-- Under `security invoker`, every column a function's body references -
-- in a WHERE clause or ORDER BY, not only the SELECT list - is checked
-- against the CALLING role's own column-level privileges. 005a (see that
-- file's own corrected grant list) must therefore still grant
-- `authenticated` SELECT on `ledger_type`, even though this function
-- never returns it - otherwise every authenticated call to
-- get_properties() would fail with "permission denied for column
-- ledger_type" once 005a's narrowed grant took effect. `fdor_enriched_at`
-- has no such dependency (never referenced anywhere in this function's
-- body) and remains fully excludable from both the output and the grant.
-- This does mean 005a cannot fully close the raw-table (`sb.from(
-- "properties").select("ledger_type")`) path for `ledger_type`
-- specifically - a client with direct table access can still read it,
-- even though get_properties() itself never returns it. This is a named,
-- accepted, narrow exception (ledger_type is pipeline-routing metadata,
-- not restricted/legally-sensitive content, per this file's own WHY
-- REQUIRED section above), not an oversight - see 005a's own corrected
-- header for the full reasoning.
begin;

drop function if exists public.get_properties(text, text, text, int, int);

create or replace function public.get_properties(
  p_state text,
  p_ledger_type text default null,
  p_status text default null,
  p_limit int default 20000,
  p_offset int default 0
)
returns table (
  id uuid, state text, county text, source text, harvester_source text,
  address text, parcel text, case_no text, owner_name text, status text,
  prop_type text, dor_use_code text, tx_category text, lien_level text,
  lien_note text, homestead boolean, bid numeric, assessed numeric,
  market numeric, value_year int, min_bid numeric,
  redemption_period_months int, redemption_expiration_date date,
  max_statutory_return_usd numeric, year_built int, living_area int,
  lot_sqft int, num_buildings int, land_value numeric, legal_desc text,
  last_sale_price numeric, last_sale_year int, sale_date date,
  certificate_no text, tax_year text, issued_date date,
  expiration_date date, interest_rate numeric, latitude double precision,
  longitude double precision, url_appraiser text, url_auction text,
  url_taxcoll text, url_title text, url_streetview text, url_zillow text,
  gone_since timestamptz, updated_at timestamptz
)
language sql
stable
security invoker
as $$
  select
    id, state, county, source, harvester_source, address, parcel, case_no,
    owner_name, status, prop_type, dor_use_code, tx_category, lien_level,
    lien_note, homestead, bid, assessed, market, value_year, min_bid,
    redemption_period_months, redemption_expiration_date,
    max_statutory_return_usd, year_built, living_area, lot_sqft,
    num_buildings, land_value, legal_desc, last_sale_price,
    last_sale_year, sale_date, certificate_no, tax_year, issued_date,
    expiration_date, interest_rate, latitude, longitude, url_appraiser,
    url_auction, url_taxcoll, url_title, url_streetview, url_zillow,
    gone_since, updated_at
  from public.properties
  where state = p_state
    and (p_ledger_type is null or ledger_type = p_ledger_type)
    and (p_status is null or status = p_status)
  order by county, case_no
  limit p_limit
  offset p_offset;
$$;

grant execute on function public.get_properties(text, text, text, int, int)
  to service_role, authenticated, anon, postgres, public;

commit;

-- Rollback (the exact original 003_ledger_type_and_state_isolation.sql
-- definition, reproduced here so a revert never needs to be re-derived -
-- corrected, Phase 14E, to also DROP FUNCTION first: reverting FROM this
-- migration's named-columns TABLE return shape BACK TO `returns setof
-- public.properties` is exactly the same return-type-change problem in
-- reverse, so a rollback needs the same drop-then-create shape, not a
-- bare CREATE OR REPLACE):
--
-- begin;
--
-- drop function if exists public.get_properties(text, text, text, int, int);
--
-- create or replace function public.get_properties(
--   p_state text,
--   p_ledger_type text default null,
--   p_status text default null,
--   p_limit int default 20000,
--   p_offset int default 0
-- )
-- returns setof public.properties
-- language sql
-- stable
-- security invoker
-- as $$
--   select *
--   from public.properties
--   where state = p_state
--     and (p_ledger_type is null or ledger_type = p_ledger_type)
--     and (p_status is null or status = p_status)
--   order by county, case_no
--   limit p_limit
--   offset p_offset;
-- $$;
--
-- grant execute on function public.get_properties(text, text, text, int, int)
--   to service_role, authenticated, anon, postgres, public;
--
-- commit;
