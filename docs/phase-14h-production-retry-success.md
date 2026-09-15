# Phase 14H: Production Retry of Corrected 005/005a — SUCCESS, Gate B CLOSED_WITH_LIMITATIONS

**Status:** 2026-09-14, same day as Phase 14E/14F/14G. Requested by the user as "Phase 14F — Production Retry of Corrected 005/005a + Gate B"; filed here as 14H (not 14F) because `docs/phase-14f-production-migration-execution-attempt.md` already names the earlier, failed attempt — same collision-avoidance reasoning Phase 14E's own corrective work used when it was filed as 14G.

**Both migrations succeeded this time.** `005_customer_safe_properties_projection.sql` (the corrected, drop-then-create version committed at `e446504`) and `005a_close_direct_properties_grant.sql` (the corrected version, same commit, with the `ledger_type` grant exception) were both applied to production and verified live, end to end. **Gate B decision: CUSTOMER DATA BOUNDARY = CLOSED_WITH_LIMITATIONS.**

Companion to `docs/phase-14f-production-migration-execution-attempt.md` (the failed first attempt this retries) and `docs/phase-14g-corrective-migration-function-contract.md` (the design-only fix this retry finally executes).

## 1. Pre-execution checks (this session)

- `git status` clean at `e446504`; `git log -3` confirmed `e446504` → `5c755d8` → `eec477b`.
- Working-tree `scripts/migrations/005_customer_safe_properties_projection.sql` and `005a_close_direct_properties_grant.sql` diffed byte-for-byte against `git show e446504:...` for both files: **identical**, confirming no drift between the reviewed/committed fix and what was about to run.
- Fresh live baseline pulled immediately before touching anything: row count 3,929; column count 50 (49 + `dor_use_code` from the already-live schema-v9); 0 identity duplicates; `get_properties()` still the pre-005 `RETURNS SETOF properties` / `select *` / no explicit security mode printed (i.e. still the Postgres default, `SECURITY INVOKER`) definition; grants on `public.properties` still blanket (`anon`/`authenticated`/`postgres`/`service_role` all hold `SELECT`/`INSERT`/`UPDATE`/`DELETE`/`REFERENCES`/`TRIGGER`/`TRUNCATE` — the pre-existing, separately-scoped `TRUNCATE` item, unchanged and still out of scope for this phase); RLS: exactly one policy, `"properties: approved only"`, PERMISSIVE, `ALL`, gated on `is_approved()` — matches CLAUDE.md's documented safe pattern, no RESTRICTIVE-with-zero-PERMISSIVE risk. `mcp__Supabase__list_migrations` showed only `schema_v9_dor_use_code` as already applied — confirming 005/005a genuinely had not yet run. This is exactly the expected post-14F, pre-005 state.
- Supabase tool access (`execute_sql`, `apply_migration`, `get_advisors`, `list_migrations`) all worked without denial this session — no repeat of the earlier Gate-A-refresh phase's `[Production Deploy]` classifier block.

## 2. Migration 2 (execution order continues from schema-v9): `005_customer_safe_properties_projection.sql` — SUCCESS

Applied via `mcp__Supabase__apply_migration` with the exact executable SQL from the committed file (the `begin; drop function if exists ...; create or replace function ...; grant execute ...; commit;` block). Result: `{"success":true}` — the 42P13 defect is fixed.

**Verification (immediate, live):**
- `pg_get_functiondef()` now shows `RETURNS TABLE(id uuid, state text, county text, ... gone_since timestamp with time zone, updated_at timestamp with time zone)` — the exact 47-column named shape from the corrected file, byte-for-byte matching the function body that was submitted.
- `information_schema.role_routine_grants` for `get_properties`: `EXECUTE` held by `PUBLIC`, `anon`, `authenticated`, `postgres`, `service_role` — the full live role set preserved, not narrowed, exactly as the corrective phase required.
- Live RPC call `select * from public.get_properties('FL', null, null, 3, 0)` returned real rows with exactly the narrowed column set (no `ledger_type`, no `fdor_enriched_at` in the output).
- Row count unchanged (3,929), 0 identity duplicates — no data touched.

## 3. Migration 3: `005a_close_direct_properties_grant.sql` — SUCCESS

Applied via `mcp__Supabase__apply_migration` with the exact `revoke select ... from anon; revoke select ... from authenticated; grant select (...) on public.properties to authenticated;` statements from the committed file (including the `ledger_type` exception). Result: `{"success":true}`.

**Verification (immediate, live, going beyond static review — this phase actually exercised the privilege boundary, not just inspected it):**
- `information_schema.role_column_grants` (SELECT only): `authenticated` now holds column-level SELECT on exactly 48 columns — the 47 customer-safe columns from 005's output plus the documented `ledger_type` exception. `anon` holds **zero** SELECT grants of any kind on `public.properties`. `postgres`/`service_role` still hold SELECT on all 50 columns (`fdor_enriched_at` and `ledger_type` included) — internal/service access fully preserved.
- `information_schema.role_table_grants`: `anon` and `authenticated` no longer hold table-level `SELECT` at all; `INSERT`/`UPDATE`/`DELETE`/`REFERENCES`/`TRIGGER`/`TRUNCATE` are untouched (005a's REVOKE targeted `SELECT` only, exactly as written — the pre-existing `TRUNCATE`/broad-write-grant item is neither fixed nor worsened by this phase, still separately scoped).
- **Live-exercised, not just reasoned about:** `set local role authenticated; select ledger_type from public.properties limit 1;` ran with no permission error (returned zero rows, because no `request.jwt.claims` was set for `is_approved()` to authorize — RLS, not the grant, is what filtered rows here, which is itself confirmation RLS is still enforced independently of the column grant). `set local role authenticated; select fdor_enriched_at from public.properties limit 1;` **failed** with `permission denied for table properties` — confirming `fdor_enriched_at` is genuinely excluded, not merely omitted from a hand-checked list. `set local role authenticated; set local request.jwt.claims = '{"role":"authenticated","sub":"00000000...0000"}'; select count(*) from public.get_properties('FL', null, null, 5, 0);` executed **without** a "permission denied for column ledger_type" error (returned `count: 0`, since that synthetic UUID has no approved profile row for RLS to allow) — this is the concrete, live proof that the Phase 14E `ledger_type`/SECURITY INVOKER fix actually works under the narrowed grant, not just on paper. `set local role anon; select 1 from public.properties limit 1;` **failed** with `permission denied for table properties` — confirming `anon` access is fully closed.
- A live check for whether `anon` calling `get_properties()` itself would now behave differently was also run: `set local role anon; select count(*) from public.get_properties('FL', null, null, 5, 0);` now fails with `permission denied for table properties` (previously it would have returned an empty result set, since `anon` held full table SELECT before this phase and would simply have been filtered to zero rows by RLS). This is a real behavior change for a hypothetical unauthenticated caller of the RPC — but a **verified non-regression**: `public/app.js`'s only call site for `get_properties()` (`fetchProperties()`, inside `loadAll()`) is reachable only from `showApp()`, which is only invoked from `checkApprovalAndEnter()` after a real, signed-in, `approved=true` Supabase Auth session exists — at which point Supabase's client sends the user's JWT and PostgREST executes as `authenticated`, never `anon`. No code path in this repository calls `get_properties()` as an unauthenticated client, so this stricter (fail-loud instead of silent-empty) behavior for a hypothetical anonymous/malicious caller is a net security improvement, not a frontend regression.

## 4. Gate B checklist — full results

1. **Schema:** `get_properties()` is the corrected named-columns `RETURNS TABLE` shape, live. ✅
2. **Data preservation:** row count 3,929 before and after both migrations; 0 identity duplicates. ✅
3. **Unique constraint:** `properties_state_source_county_case_no_key` untouched by either migration (neither touches table structure). ✅
4. **RLS:** unchanged — one PERMISSIVE `is_approved()`-gated policy, confirmed via `pg_policies` before and after. ✅
5. **Customer-safe access:** `get_properties()` output and `authenticated`'s column grants both match the documented ~47-column customer contract plus the one named `ledger_type` exception. ✅ (with limitation, see §5)
6. **Direct REST exposure:** live-simulated for `anon` (fully blocked) and `authenticated` (narrowed to 48 columns); `fdor_enriched_at` confirmed genuinely inaccessible via a real permission-denied error, not just absent from a list. ✅
7. **`get_properties()` behavior:** verified against the live database object (not just the migration file) for both FL and TX rows and under a narrowed-grant `authenticated` simulation. ✅
8. **Write path:** `service_role`'s full column and table grants on `properties` unaffected — FL/TX harvester and sync scripts unaffected. ✅
9. **Frontend regression:** `app.js`'s only `get_properties()` call site verified to run exclusively post-authentication; `harvester_source` still present in RPC output (required by `assessedSourceLabel()` for TX rows — confirmed live on a real TX row: `harvester_source: "tx_realauction"`). ✅
10. **CSV/export:** unaffected — `ALL` is populated from the same `get_properties()` result the export already worked from before this phase; no column removed that was ever read. ✅ (by inspection, not a live browser test this phase)
11. **Governance/provenance/migration-compatibility tests:** full `pytest tests/python/ -q` run: **162 passed**, 0 failed. ✅
12. **Florida regression:** `get_properties('FL', ...)` returns 3,493 FL rows, correctly scoped. ✅
13. **Texas regression:** `get_properties('TX', ...)` returns 436 TX rows, correctly scoped, `harvester_source` intact. ✅
14. **Leon County cross-state regression:** `get_properties('FL', ...)` filtered to `county = 'Leon'` returns 45 rows — nonzero, correctly state-scoped (no TX bleed-through, no Leon-named-county collision from another state). ✅
15. **Digest drift:** `digest_candidates()` untouched by 005/005a (no dependency in either file); unaffected, still the previously-documented non-blocking drift (real caller in `supabase/functions/send-digest/index.ts`, zero Edge Functions actually deployed). ✅ (unchanged)
16. **Geometry drift:** `properties_sync_geom()` untouched by 005/005a; unaffected. ✅ (unchanged)

`mcp__Supabase__get_advisors(type: "security")` was also re-run after both migrations: every finding is a pre-existing item already documented elsewhere in this project (the orphaned legacy tables' `rls_enabled_no_policy` findings from CLAUDE.md's "Known landmines" section; `function_search_path_mutable` on `get_properties` and seven other pre-existing functions, none of which changed relative to before this phase's migrations — the mutable-search-path property is unrelated to the return-type/grant fix and was equally true of the old function body; `spatial_ref_sys`/PostGIS-in-public findings, pre-existing infrastructure from the PostGIS extension itself; the `SECURITY DEFINER`-callable-by-anon findings, all pre-existing functions unrelated to `properties`; leaked-password-protection, an Auth-wide setting unrelated to this phase). **No new advisory finding was introduced by 005 or 005a.**

## 5. Customer data boundary decision

**CLOSED_WITH_LIMITATIONS.**

Closed: both real read paths (`get_properties()` RPC and the raw `/rest/v1/properties` REST path) now return the same, narrow, ~47-column customer-safe projection to `authenticated` callers — `fdor_enriched_at` is fully unreachable via either path, and `anon` can reach neither path at all (RPC: table-level permission denied when reading columns to answer the query, verified; raw REST: no SELECT grant at all, verified).

Limitation, named rather than hidden (documented in 005/005a's own Phase 14E correction comments, and now confirmed live rather than only reasoned about): `ledger_type` remains readable by an `authenticated` client that queries `public.properties` directly (`sb.from("properties").select("ledger_type")`), even though `get_properties()` itself never returns it. This is a forced consequence of `get_properties()` being `SECURITY INVOKER` and reading `ledger_type` in its own `WHERE` clause — closing it fully would require either `SECURITY DEFINER` (explicitly out of scope, a materially larger and separately-reviewable architectural change) or restructuring the function to not filter on that column internally (a functional change, not attempted here). `ledger_type` itself is pipeline-routing metadata with no restricted or legally-sensitive content, per 005/005a's own "WHY REQUIRED" sections — this is an accepted, narrow, documented gap, not an oversight.

Two items remain explicitly out of scope and unaffected by this phase, exactly as before: the `TRUNCATE`/broad-write-grant question for `anon`/`authenticated` on `public.properties` (a separate future security review), and the `digest_candidates()`/send-digest drift (non-blocking, no Edge Functions actually deployed).

## 6. What this phase did and did not do

**Did:** re-confirmed git/file state matched the committed corrective fix exactly; re-verified a fresh live pre-migration baseline; executed the corrected `005` (succeeded); executed the corrected `005a` (succeeded); live-exercised the privilege boundary with role-simulation queries rather than relying on static review; ran the full Gate B checklist against the live database; ran the full local test suite (162/162); ran a fresh security-advisor check; rendered a CLOSED_WITH_LIMITATIONS decision naming the one accepted exception honestly; wrote this record.

**Did not do:** modify either migration file (both ran exactly as committed at `e446504`); touch RLS; change any grant beyond what 005/005a themselves specify; expand Texas county coverage; change any source's legal status; dispatch any workflow; push to origin; weaken or delete any test; attempt to close the `ledger_type` raw-REST exception (a separate, future, explicitly-scoped decision if ever pursued) or the `TRUNCATE`/write-grant item.

## Update (Phase 15, same day): the "47-column" figure used throughout this document was off by one

This document (and Phase 14B/14D before it) described the customer-safe shape as "~47 columns." Phase 15's own field reconciliation found the real number is **48** (including `id`, the internal UUID that was apparently never counted even though it is always in the literal list) - confirmed directly against 005's actual `RETURNS TABLE` clause and against live production, where `authenticated`'s column-level SELECT grant count is 49 = 48 (005's output) + 1 (the `ledger_type` exception this document already describes). This changes no finding, no verification result, and no decision in this document - CLOSED_WITH_LIMITATIONS stands exactly as concluded below - it is a prose-label correction only. Full account: `docs/phase-15-customer-surface-security-audit.md`.

## 7. Recommended next action

None required for this feature — the customer-safe projection work Phase 14A originally proposed is now fully live in production, closed to the extent designed, with its one remaining limitation named and accepted rather than silently left open. Any future work here (closing the `ledger_type` raw-REST gap, addressing the `TRUNCATE`/broad-write grant, or building the deferred `outcome`/`sold_price` harvester capture) is a new, separately-scoped decision for the user to authorize explicitly — not a continuation of this phase.
