# Phase 14F: Production Migration Execution Attempt (schema-v9 applied, 005 failed)

**Status:** 2026-09-14, same day as Phase 14E. **Migration 1 (`schema-v9-dor-use-code.sql`): SUCCEEDED, live in production.** **Migration 2 (`005_customer_safe_properties_projection.sql`): FAILED**, exact Postgres error below — a real, previously-undiscovered defect in 005's own design, not a live-state or access problem. Migration 3 (`005a`) was correctly never attempted per the absolute ordering rule. **Gate B was not reached.** No data was lost, corrupted, or rewritten; no RLS/grant change occurred; the customer-data boundary is unchanged from its pre-Phase-14 state (still open — this migration attempt did not close it, and did not regress it either).

Companion to `docs/phase-14e-gate-a-execution-attempt.md` (the fresh Gate A that authorized this attempt) and `docs/phase-14d-migration-reconciliation.md` (the migration package executed here).

## 1. Pre-migration baseline (re-verified live, this session)

Confirmed identical to Phase 14E's Gate A snapshot before any statement executed: 49 columns, row count 3,929, 0 identity duplicates, `properties_state_source_county_case_no_key` intact, RLS enabled/not forced with one PERMISSIVE `"properties: approved only"` policy (`is_approved()`), grants unchanged (`anon`/`authenticated`/`service_role` all hold blanket `SELECT`/`INSERT`/`UPDATE`/`DELETE`/`REFERENCES`/`TRIGGER`/`TRUNCATE`), `get_properties()` unchanged (`select *`, security invoker), `outcome`/`sold_price`/`dor_use_code` all absent. No drift from Gate A — migration execution began from exactly the state that gate verified.

## 2. Migration 1: `schema-v9-dor-use-code.sql` — SUCCESS

Applied via `mcp__Supabase__apply_migration` (`alter table public.properties add column if not exists dor_use_code text;` plus its `comment on column`). Result: `{"success":true}`.

**Verification (immediate, live):**
- `dor_use_code` now exists: `text`, nullable, no default — exactly as the migration file specifies.
- Row count unchanged: 3,929. All 3,929 rows currently have `dor_use_code IS NULL` (expected — this migration is additive-only and does not backfill; `scripts/enrich_property_details.py` will populate it incrementally on its normal per-county schedule, per that migration's own header, unchanged this phase).
- Column count: 50 (49 + 1), no other column added or changed.
- Unique constraint `properties_state_source_county_case_no_key` intact.
- RLS unchanged (`relrowsecurity=true`, `relforcerowsecurity=false`).
- `outcome`/`sold_price` still absent.

**This is now a durable, live production change.** `dor_use_code` exists in `public.properties` starting this session and will begin filling in as the normal FDOR enrichment schedule runs — no further action needed for that half of the feature. Re-running `schema-v9-dor-use-code.sql` again in the future is a safe no-op (`add column if not exists`), but should not be necessary.

## 3. Migration 2: `005_customer_safe_properties_projection.sql` — FAILED

Before executing, the actual repository file was re-confirmed to be the corrected Phase 14D version: `md5sum` of the working-tree file matched `git show eec477b:scripts/migrations/005_customer_safe_properties_projection.sql` exactly, and a direct grep confirmed `outcome`/`sold_price` appear only inside comments (never in executable SQL) while `dor_use_code`/`harvester_source` appear in the executable `RETURNS TABLE`/`SELECT` lists, per Section 5/6 of `docs/phase-14d-migration-reconciliation.md`.

The operative SQL (the `CREATE OR REPLACE FUNCTION ... ; grant execute ...` block, extracted verbatim from the file, comments excluded) was applied via `mcp__Supabase__apply_migration`. It failed:

```
ERROR:  42P13: cannot change return type of existing function
HINT:  Use DROP FUNCTION get_properties(text,text,text,integer,integer) first.
```

**Root cause (not fixed this phase — this phase's own hard rules forbid improvising a fix mid-execution):** the live `get_properties()` is declared `RETURNS SETOF properties` (a whole-row reference type). 005's replacement declares `RETURNS TABLE (id uuid, state text, ...)` (an anonymous composite/table type). Postgres treats these as different return-type *shapes*, not merely a body change — `CREATE OR REPLACE FUNCTION` can change a function's body freely but cannot change its return type; that requires dropping the function first. This is a genuine defect in migration 005's own design, present since Phase 14A first wrote it and never caught by any of Phases 14A/14B/14C/14D/14E's own extensive review — every one of those reviews was static (reading the SQL text, reasoning about columns, checking live schema/grants/RLS) and 005's own "TEST PLAN" section anticipated only a smoke test "against a non-production project (or a Supabase branch, if available)" — no such branch/non-production project was ever actually used by any phase to dry-run the statement itself, only to reason about it. This phase is the first time `CREATE OR REPLACE FUNCTION` was actually attempted against the live function, and it is what surfaced the defect.

**Verification of production state immediately after the failure (live, this session):**
- `get_properties()` is **completely unchanged** — `pg_get_functiondef()` shows the exact same pre-migration definition (`RETURNS SETOF properties`, `select *`, `security invoker`). The failed `apply_migration` call did not partially apply; Postgres's own DDL transaction semantics rolled it back entirely.
- Row count unchanged: 3,929.
- `dor_use_code` still present (Migration 1's effect persists — that was a separate, already-committed statement).
- `get_properties()` grants unchanged (`service_role`, `authenticated`, `anon`, `postgres`, `PUBLIC` all still hold `EXECUTE`).
- RLS unchanged.

**A genuinely positive, unplanned side effect**: because `get_properties()` still does `select * from public.properties`, it now transparently returns `dor_use_code` too (it did not before this session, since the column didn't exist). `public/app.js` already reads `p.dor_use_code` defensively (card rendering, CSV export). No frontend deploy or further migration is needed for `dor_use_code` values to start appearing in the app as the enrichment pipeline backfills them — this one piece of the intended outcome is already live and working, independent of whether 005/005a ever run.

## 4. Migration 3: `005a_close_direct_properties_grant.sql` — NOT ATTEMPTED

Per the absolute ordering rule ("Never execute 005a before 005 succeeds") and the hard-stop rule ("If 005 fails: STOP... Do not continue to the next migration"), 005a was not attempted. The base-table column-level grant narrowing it would apply remains undone; `anon`/`authenticated` retain full, unnarrowed table access exactly as before this session.

## 5. Gate B: NOT REACHED

Gate B requires all three migrations to succeed first. It was not entered.

## 6. Customer data boundary decision

**NOT CLOSED.** This is not a regression — the boundary was never closed to begin with (Phase 14A through 14F, inclusive, have designed, corrected, and now partially executed the closure, but the RPC projection and the base-table grant narrowing — the two mechanisms that actually close it — have not yet both succeeded). Direct `select * from public.properties` (whether via the RPC, which still does exactly that, or via the raw REST fallback `sb.from("properties").select("*")` app.js already has) continues to return every column, including `ledger_type` and `fdor_enriched_at`, to any `authenticated` (or, per the grant audit, even `anon`) caller. This matches this session's own pre-migration baseline exactly — no new exposure was introduced, but none was closed either.

## 7. What this phase did and did not do

**Did:** re-verified the pre-migration baseline live; executed `schema-v9-dor-use-code.sql` (succeeded, now live); attempted `005_customer_safe_properties_projection.sql` (failed with a specific, reproducible Postgres error); verified production state immediately after the failure; stopped before 005a and before Gate B, per the phase's own hard rules; documented the root cause and the now-live `dor_use_code` column.

**Did not do:** modify migration 005's SQL to work around the failure; attempt `DROP FUNCTION` or any other corrective statement; execute 005a; run any Gate B check (moot — the migrations it verifies did not complete); change any RLS policy, grant, or the `TRUNCATE`/write-grant item (explicitly out of scope, unchanged); expand Texas counties; change any source's legal status; dispatch any workflow; push to origin; weaken or delete any test.

## 8. Recommended next action

Not Phase 15, and not a retry of 005 as currently written — it will fail identically every time until it is corrected. The concrete next step is a new corrective revision of `scripts/migrations/005_customer_safe_properties_projection.sql` (and, since 005a's own grant statement depends on 005 already existing with the new shape, a re-review of whether 005a needs any change too, which is expected to be none): the function must be dropped before being recreated with a different return-type shape, e.g. `drop function if exists public.get_properties(text, text, text, int, int); create function public.get_properties(...) returns table (...) ...` as one migration, ideally inside an explicit transaction so the function is never briefly absent for a caller mid-migration (a `DROP` immediately followed by `CREATE` in the same statement batch is very low-risk in practice, but this is a genuine design decision a future phase should make deliberately, with its own test plan that actually dry-runs the statement rather than only reasoning about it statically — this phase's own experience is the concrete argument for that). `dor_use_code` is already live and does not need to be revisited. A fresh Gate A is not strictly required before that narrow fix (nothing about live state changed in a way that affects 005's design, only the discovery that its DDL shape is invalid), but re-confirming the corrected file's `CREATE OR REPLACE FUNCTION` statement is valid should include an actual dry-run this time, not static review alone.

**Update (Phase 14G, same day): done, and this paragraph's own guess about 005a was wrong in one respect - worth recording rather than quietly fixing.** 005 was corrected exactly as described above (drop-then-create in an explicit transaction). But 005a *did* need a change, not the "expected to be none" this paragraph predicted: the same analysis found `get_properties()`'s `WHERE` clause reads `ledger_type` internally under `SECURITY INVOKER`, so 005a's grant list had to add `ledger_type` (for that internal use only - `get_properties()` still never returns it) or every authenticated call to the function would have failed once 005a's narrowed grant took effect. Full account: `docs/phase-14g-corrective-migration-function-contract.md`.

**Update (Phase 14H, same day): the retry succeeded.** Both corrected migrations were re-attempted against production and both succeeded this time, verified live (not just by re-reading the SQL): `get_properties()` now has the named-columns `RETURNS TABLE` shape with the full live EXECUTE grant set preserved, and 005a's REVOKE/GRANT narrowed `authenticated`'s column access exactly as designed, including the `ledger_type` exception, with `anon` losing SELECT entirely. Gate B (all 16 items) passed; full test suite (162/162) passed; a fresh security-advisor check found no new finding. Customer data boundary decision: **CLOSED_WITH_LIMITATIONS** (the accepted `ledger_type` raw-REST exception is the one named limitation). Full account: `docs/phase-14h-production-retry-success.md`.
