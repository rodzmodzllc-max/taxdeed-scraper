# Phase 14G: Corrective Migration 005 / get_properties() Function Contract

**Status:** 2026-09-14, design-only - **no production SQL executed this phase.** Requested as "PHASE 14E — Corrective Migration 005 / get_properties() Function Contract"; filed here as **14G** in this repository's own doc sequence (not 14E) because `docs/phase-14e-gate-a-execution-attempt.md` already exists, from an earlier same-day phase this repository's history calls 14E (the fresh Gate A re-verification) - the request's own "14E" label collides with that existing, committed document. Nothing else about the request's numbering or scope is reinterpreted; this is a filename disambiguation only, noted here so the mapping is traceable.

Companion to `docs/phase-14f-production-migration-execution-attempt.md` (the failed execution this phase corrects) and `docs/phase-14d-migration-reconciliation.md` (the migration package this phase further corrects).

## 1. Why 005 failed

```
ERROR:  42P13: cannot change return type of existing function
HINT:  Use DROP FUNCTION get_properties(text,text,text,integer,integer) first.
```

The live `get_properties(text,text,text,integer,integer)` is `RETURNS SETOF properties` (a whole-row reference type, `003_ledger_type_and_state_isolation.sql`'s original shape). The corrected-through-Phase-14D 005 declared `RETURNS TABLE (id uuid, state text, ...)` (an anonymous named-columns composite type). Postgres treats these as different return-type *shapes* - `CREATE OR REPLACE FUNCTION` can change a function's body, arguments, and volatility freely, but never its return type; changing that requires dropping the function first (Postgres's own error and HINT say exactly this). There was no way to make 005's actual goal (narrow which columns the RPC returns) work with `RETURNS SETOF properties` at all - that return type mandates every column of the table, by definition, so *some* return-type change was unavoidable the moment this migration pair's goal was "return fewer columns." The defect was never in the goal, only in not accounting for what changing the return type requires.

This was a genuine defect in 005's own design, present since Phase 14A first wrote it and never caught by any of Phases 14A/14B/14C/14D/14E's own review - every one of those reviews was static (reading SQL text, reasoning about columns/grants/RLS/row counts). Phase 14C/14F's session was the first to actually attempt the statement against the live function, which is what surfaced it.

## 2. The existing (live) function signature

```sql
create or replace function public.get_properties(
  p_state text,
  p_ledger_type text default null,
  p_status text default null,
  p_limit int default 20000,
  p_offset int default 0
)
returns setof public.properties
language sql
stable
security invoker
as $$
  select *
  from public.properties
  where state = p_state
    and (p_ledger_type is null or ledger_type = p_ledger_type)
    and (p_status is null or status = p_status)
  order by county, case_no
  limit p_limit
  offset p_offset;
$$;
```

Grants: `EXECUTE` currently held by `service_role`, `authenticated`, `anon`, `postgres`, and `PUBLIC` (broader than `003`'s own tracked grant, which names only `authenticated` - the extra grantees are most likely Supabase's own default project-template grants, not anything this project's migrations added). `prosecdef = false` - `SECURITY INVOKER`.

## 3. Why CREATE OR REPLACE was insufficient (and why DROP FUNCTION → CREATE FUNCTION is the correct strategy, not merely convenient)

The request posed three strategies:

- **(A) DROP FUNCTION → CREATE FUNCTION.**
- **(B) preserve the existing signature via another safe migration strategy.**
- **(C) introduce a new customer-safe function, keep the old one temporarily, controlled transition.**

There is no Postgres mechanism to narrow a `SETOF <table>`-returning function's output columns without changing its return type to something other than `SETOF <table>` - that return type is defined as "every column of the referenced table," so option (B) does not exist as a distinct alternative; any strategy that actually achieves 005's goal necessarily changes the return type, and any return-type change on an existing function necessarily requires a drop first. Option (A) is therefore not chosen for convenience - it is the only mechanism available that achieves the goal at all.

Option (C) (a new function name, old one kept temporarily, phased transition) was considered and rejected for this specific migration: it would require a frontend deploy to call the new name (defeating 005's own long-standing design goal, stated in its header since Phase 14A, of a drop-in replacement needing "no frontend deploy... alongside it," since `public/app.js` already calls the RPC by the fixed name `"get_properties"`), and it would leave two functions live simultaneously with diverging behavior for an unspecified transition window, which is more operational complexity than this narrow defect warrants. Nothing about the actual dependency evidence (a single, simple RPC caller in `app.js`, no other database object depending on `get_properties()` - see Section 4) supports the extra machinery a phased transition exists to manage. Option (A), reproducing the exact same function name and argument signature, is the option the repository's actual dependencies support.

## 4. Dependency inventory (before choosing DROP FUNCTION)

Full-repository search for `get_properties` (`.py`, `.sql`, `.js`, `.ts`): the only references are `public/app.js` (the one real RPC caller, `fetchProperties()`), `app.js` (the repo-root mirror copy, identical content), the migration files themselves (`003`, `004`'s own comment, `005`, `005a`), `scripts/sync-texas-to-supabase.py` (a comment describing the read-path architecture, not a caller), and the test suite. No other SQL object - no view, no other function, no trigger - is defined anywhere in this repository's tracked SQL files as depending on `get_properties()`; it is a leaf RPC, called only from application code via PostgREST, never referenced by another database object. This conclusion is repository-based (this phase's own scope is design-only, no production SQL/live `pg_depend` query was run - see Section 8) but is corroborated by every one of Phase 14C/14E/14F's own live audits, none of which found any view, trigger, or other function referencing it.

**Permission loss**: DROP FUNCTION discards every grant the dropped function held. Addressed in Section 5 - the corrected 005 explicitly re-grants the exact live `EXECUTE` set, not a narrowed one.

**Ownership / search_path**: `get_properties()` is `language sql`, fully qualifies its one table reference (`public.properties`), and has never had an explicit owner or `search_path` set by any tracked migration. Recreating it via the same tool/credentials this repository's migrations have always used (the Supabase SQL Editor, by hand, per this project's own established convention) will recreate it owned by the same connecting role, with no `search_path` dependency to lose (it never had one).

**API behavior change**: none, by design (Section 3's rejection of option C exists specifically to avoid one) - same function name, same argument names/types/order/defaults (verified byte-for-byte identical to `003`'s original parameter block by `tests/python/test_phase14e_function_contract_correction.py::test_10_...`), same `SECURITY INVOKER`, only the column shape of what is returned changes (fewer columns) - exactly 005's original, unchanged goal.

## 5. The corrected 005: exact strategy, signature, return columns, security mode, grants

`scripts/migrations/005_customer_safe_properties_projection.sql`'s forward migration is now:

```sql
begin;

drop function if exists public.get_properties(text, text, text, int, int);

create or replace function public.get_properties(
  p_state text,
  p_ledger_type text default null,
  p_status text default null,
  p_limit int default 20000,
  p_offset int default 0
)
returns table ( ... 48 named columns, unchanged from Phase 14D's corrected list ... )
language sql
stable
security invoker
as $$
  select ...
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
```

- **`DROP FUNCTION IF EXISTS`** (not a bare `DROP FUNCTION`) targets the exact signature Postgres's own error named, so this file stays idempotent if re-run after a partial or aborted attempt.
- **Explicit `BEGIN`/`COMMIT`**: Postgres DDL is already transactional, so an uncommitted DROP is invisible to other sessions regardless - but the transaction is made explicit so this file does not depend on the calling tool's own default behavior, and so no caller can ever observe the function absent mid-migration. A nested `BEGIN` inside a tool that already wraps the submitted SQL in its own transaction is harmless in Postgres (a warning, not an error - the statements simply continue in the already-open transaction).
- **Function signature**: byte-for-byte identical to the live/tracked one (`p_state text, p_ledger_type text default null, p_status text default null, p_limit int default 20000, p_offset int default 0`) - unchanged, so `app.js`'s existing `sb.rpc("get_properties", { p_state: PAGE_STATE })` call keeps resolving to this function with no frontend deploy required.
- **Return columns**: unchanged from Phase 14D's own corrected list (48 columns - `outcome`/`sold_price` excluded, `dor_use_code`/`harvester_source` included, `ledger_type`/`fdor_enriched_at` excluded). This phase's fix is entirely about the DDL *shape*, not the column *list* - Section 6 covers the one place those two questions actually interact.
- **Security mode**: `SECURITY INVOKER`, unchanged - **not** changed to `SECURITY DEFINER`. This phase's own hard rule forbids that change without a separate, documented architectural review, and no such review was performed or is warranted here - `SECURITY DEFINER` would be a materially larger, riskier change (bypassing RLS/column privileges more broadly than this narrow gap requires) being proposed as a workaround for a permissions detail, exactly what the hard rule exists to prevent.
- **Grants**: `EXECUTE` re-granted explicitly to `service_role, authenticated, anon, postgres, public` - the exact live set (Section 2), not narrowed to `authenticated` alone (003's original, and this file's own pre-14E draft). `DROP FUNCTION` would otherwise silently discard the broader live grant; narrowing it is a real, separate security decision (the same class of question as the deferred `TRUNCATE`/write-grant item) left to a future, explicitly-scoped phase, not decided here as a side effect of fixing the return-type defect.

## 6. The critical finding: 005a's interaction with get_properties() under SECURITY INVOKER

Proven from Postgres privilege semantics and the actual function body, not assumed: under `SECURITY INVOKER`, every column a function's body references - in a `WHERE` clause or `ORDER BY`, not only the `SELECT`/output list - is checked against the **calling role's own** column-level privileges at execution time. `get_properties()`'s `WHERE` clause reads `ledger_type` (`... and (p_ledger_type is null or ledger_type = p_ledger_type) ...`) to implement the `p_ledger_type` filter parameter - but `ledger_type` is one of the two fields (with `fdor_enriched_at`) this whole migration pair exists to keep out of the customer-visible output, and was therefore excluded from 005a's grant list in every version of that file through Phase 14D.

**If 005a had been left as Phase 14D wrote it, applying it after the corrected 005 would have broken every authenticated call to `get_properties()`** - not with the column silently omitted, but with a hard `permission denied for column ledger_type` error, since the function's own WHERE clause would still try to read a column `authenticated` no longer had SELECT on. This would not have shown up in any static review of either file in isolation - it only surfaces by tracing `get_properties()`'s actual function body against 005a's actual grant list together, which is exactly what this phase did.

**Fix**: `005a_close_direct_properties_grant.sql`'s grant list now includes `ledger_type`, on its own trailing line, explicitly separated from and commented apart from the genuinely customer-safe columns above it - granted *only* because `get_properties()` needs to read it internally to filter, never because it is meant to be customer-visible. `get_properties()` itself still never returns `ledger_type` in its output (unchanged from Phase 14D), and `public/app.js` still never reads `p.ledger_type` anywhere (re-confirmed by `tests/python/test_phase14b_database_api_boundary.py`'s updated group B).

`fdor_enriched_at` has no equivalent dependency - it is never referenced anywhere in `get_properties()`'s function body (not the `WHERE` clause, not `ORDER BY`, not the `SELECT` list) - so it remains the one field genuinely, fully absent from both 005's output and 005a's grant, with no exception.

**Named, not hidden, consequence**: this means 005a can no longer claim to fully close the raw-table path for `ledger_type` specifically - a client with direct table access (`sb.from("properties").select("ledger_type")`) can still read it after 005a runs, even though `get_properties()` itself never returns it to any caller. This is an accepted, narrow, documented exception forced by the `SECURITY INVOKER` + column-grant mechanism, not an oversight: `ledger_type` is pipeline-routing metadata, and 005's own "WHY REQUIRED" section (unchanged since Phase 14A) already characterizes it and `fdor_enriched_at` together as carrying "no restricted/legally-sensitive content." The alternative that would close this specific gap - `SECURITY DEFINER` - is explicitly rejected (Section 5) as a disproportionate response to it.

The invariant `tests/python/test_phase14b_database_api_boundary.py` and `tests/python/test_phase14d_migration_reconciliation.py` enforced since Phase 14B/14D ("005's output columns and 005a's grant columns are identical") is corrected accordingly to: **005a's grant columns = 005's output columns ∪ {`ledger_type`}, exactly** - both test files' relevant tests are updated to check this, not weakened or deleted; `tests/python/test_phase14e_function_contract_correction.py` adds targeted regression coverage for the underlying WHERE-clause/grant relationship itself, not just the resulting set arithmetic.

## 7. Production state assumption (unchanged by this phase)

Production remains exactly where Phase 14F left it:

- `schema-v9-dor-use-code.sql`: **APPLIED.** `dor_use_code` is live.
- `005`: **NOT APPLIED** (the version that failed is not the version now in the repository).
- `005a`: **NOT APPLIED.**
- Gate B: **NOT REACHED.**

No rollback for schema-v9 was created or is warranted - it succeeded cleanly and is additive-only. `dor_use_code` was not touched.

## 8. What this phase did and did not do

**Did:** inspected the actual repository (005, 005a, schema-v9, `003`, `004`, `public/app.js`, `scripts/sync-texas-to-supabase.py`, `scripts/enrich_property_details.py`, every test referencing `get_properties`) rather than assuming the prior failure report was sufficient; determined the exact live function signature and the exact fix (DROP FUNCTION → CREATE FUNCTION, wrapped in a transaction); found and fixed the EXECUTE-grant-loss risk; found and fixed the `ledger_type` WHERE-clause/column-grant conflict in 005a; updated the affected existing tests (not weakened - genuinely corrected to the new, proven-correct invariant) and added new tests covering all 15 items this phase's own instructions listed; ran the complete test suite (162/162, up from 151).

**Did not do:** execute any production SQL (no Supabase tool was called this phase - this was code/design-only work, per this phase's own framing); execute 005 or 005a; modify RLS; modify write grants; touch the deferred `TRUNCATE` item; modify source registry approvals; activate any blocked vendor; dispatch any workflow; modify harvesters; modify Texas source coverage; implement `outcome`/`sold_price`; touch the geometry drift item; implement `digest_candidates()`; change `get_properties()` to `SECURITY DEFINER`; proceed to Phase 15.

## 9. Recommended next action

Not Phase 15. The corrected 005/005a package (this document, and the files themselves) is ready for a fresh production attempt: a fresh Gate A re-verification (the same discipline Phase 14C/14E established - query live rather than trust this document's own snapshot) followed by executing the corrected `005` (this time an actual DROP-then-CREATE, expected to succeed where the prior attempt failed at the DDL-shape level) and then `005a` (now correctly including the `ledger_type` grant exception), then Gate B. `schema-v9-dor-use-code.sql` does not need to be re-run (Section 7).
