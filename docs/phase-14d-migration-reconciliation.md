# Phase 14D: Migration Reconciliation & Pre-Execution Re-Gate

**Status:** Phase 14D, 2026-09-14. Design/reconciliation only — **no production SQL was executed, no Supabase object was created or altered, no workflow was dispatched.** Companion to `docs/phase-14c-production-migration-verification.md` (Phase 14C — live preflight, Gate A BLOCKED), `docs/phase-14b-database-api-boundary-readiness.md` (Phase 14B — designed migrations 005/005a), and `docs/phase-14a-customer-safety-hardening.md` (Phase 14A). This document is the Phase 14D deliverable: it reconciles the tracked migration chain with the actual production schema and produces a corrected, internally consistent migration package plus a new pre-execution checklist for the fresh Gate A that must follow this phase.

This phase is repository-only. It re-reads the repository directly (per its own Gate 1 instruction: "use the actual repo as authority") and reuses Phase 14C's already-captured live-schema snapshot rather than re-querying production — no Supabase MCP tool was called this phase.

## 1. Phase 14C failure summary

Phase 14C ran a live preflight against production project `cqnnnvpbocafuvpzfbzu` and reached **Gate A: BLOCKED**. The blocker: migrations `005_customer_safe_properties_projection.sql` and `005a_close_direct_properties_grant.sql`, as committed through Phase 14B, both named three columns — `outcome`, `sold_price`, `dor_use_code` — in their `RETURNS TABLE` / `SELECT` / `GRANT SELECT (...)` lists that do not exist on the live `public.properties` table. Confirmed by a direct, targeted `information_schema.columns` query (`column_name in ('outcome','sold_price','dor_use_code','geom','geometry')` → zero rows), not inferred by omission from the broader column list. Had either migration been executed as written, Postgres would have rejected it outright (`column "outcome" does not exist`, or equivalent) — `CREATE OR REPLACE FUNCTION` would fail to compile, and `GRANT SELECT (...)` would fail to resolve the column list. Per the phase's own hard rule against improvising production SQL mid-verification, Phase 14C did not edit or execute either file; Gate B was never reached. Every other precondition Phase 14C checked (row count 3,929, zero identity duplicates on `(state, source, county, case_no)`, the unique constraint intact, `get_properties()`'s live definition matching tracked migration 003 exactly, the 005→005a ordering already documented, the `harvester_source` inclusion, `service_role` non-interference) passed.

## 2. Production vs repository schema drift

Two distinct kinds of drift were in play, and Phase 14D's job was to tell them apart rather than treat all three blocked columns identically:

- **`outcome` / `sold_price`** — drift with no tracked-migration side at all. Searched across every `.sql` file this repository's git history contains (`schema*.sql` at repo root, every `scripts/migrations/*.sql` file): the *only* two files anywhere in this repository that have ever named these columns are `005` and `005a` themselves — no earlier or later migration, tracked or otherwise, ever proposed adding them to `public.properties`. Phase 13's original field inventory (which Phase 14A/14B's classification work inherited) listed them as real, customer-visible columns without that inventory itself having been checked against either a tracked migration or a live schema query — it was built partly from `public/app.js`'s own defensive read code, which is exactly the trap Gate 1's own instruction ("do not infer that a field should exist merely because app.js references it") warns against.
- **`dor_use_code`** — drift on the execution side only, not the tracking side. A real, tracked, purely-additive migration exists for it (`schema-v9-dor-use-code.sql`, committed 2026-09-08) and a real, currently-functioning writer exists for it (`scripts/enrich_property_details.py`, populating it on its normal per-county schedule since 2026-09-02, per that script's own docstring). The migration was simply never run against this particular Supabase project — the same "tracked-but-never-executed" failure pattern `CLAUDE.md` already documents for `schema-v4`/`v5`/`v7`/`v8` (each committed, none confirmed run, until checked live).

Additionally, while transcribing Phase 14C's live-schema snapshot for this phase's compatibility tests (`tests/python/test_phase14d_migration_reconciliation.py`), a small, pre-existing inconsistency was found *inside* Phase 14C's own documentation: `docs/phase-14c-production-migration-verification.md` Section 2 says "47 columns" in prose, but the literal column-name list in that same section contains 49 distinct, non-duplicated names. This does not affect anything either phase concluded — `outcome`, `sold_price`, and `dor_use_code` are absent from that list under either count — but it is flagged here (and appended to that document's own Section 13) as a documentation-only drift item a future live Gate A should resolve with a fresh, single authoritative count. Phase 14D did not re-query production to settle which number is correct; see Section 13 (Known unresolved limitations) below.

## 3. Three-column analysis (Gate 1 / Gate 2)

For each column: production existence, tracked migration existence, writers, readers, customer/API visibility, FL/TX dependency, customer-safe-projection impact, and whether its absence can safely remain.

### `outcome`

- **Production existence:** absent (Phase 14C, live-verified).
- **Tracked migration:** none, anywhere in this repository, other than 005/005a's own (now-corrected) column lists.
- **Writers:** none. Searched `scripts/*.py`, `scripts/*.ps1`, `harvesters/**/*.py` — zero matches for any assignment/write of `outcome` as a `properties` field (confirmed again this phase, and guarded going forward by `test_outcome_and_sold_price_have_no_writer_anywhere_in_the_repo`).
- **Readers:** `public/app.js`'s `outcomeText(p)` reads `p.outcome` defensively (`app.js` — `OUTCOME_LABEL` mapping plus a fallback to `status` when `outcome` is falsy). Not read anywhere else.
- **Customer/API visibility:** shown on property cards via `outcomeText()`, but **not** a CSV export column (confirmed: `const cols = [...]` in `app.js` has no entry reading `p.outcome`).
- **FL/TX dependency:** the field spec (`claude/closed-outcome-and-map-cities.md`, this project's claude.ai Project) is state-agnostic — intended for any closed auction row, FL or TX.
- **Customer-safe-projection impact:** none — omitting it from 005/005a changes nothing observable, since the frontend already tolerates its absence (that was the explicit design intent when the frontend code was written ahead of the backend).
- **Safe to remain absent:** yes. This is a deliberately-deferred, never-completed feature, not an accidental gap. `claude/closed-outcome-and-map-cities.md` and `claude/header-account-terms-and-the-deploy-mirror-gap.md` (both read via the claude.ai Project this phase) confirm the frontend half was built intentionally ahead of the backend, with the explicit expectation that "it starts working the day the pipeline fills them in, with no further frontend change," and that the backend/harvester capture work was "Handed to the backend chat (not mine to build)" — work no session since has completed.
- **Classification: SHOULD BE REMOVED FROM 005/005a.**

### `sold_price`

- **Production existence:** absent (Phase 14C, live-verified).
- **Tracked migration:** none, anywhere in this repository, other than 005/005a's own (now-corrected) column lists.
- **Writers:** none (same repo-wide search as `outcome`, same zero-match result).
- **Readers:** `public/app.js`'s `outcomeText(p)` reads `p.sold_price` (used only when `outcome` resolves to `"Sold"`, to append the winning-bid amount).
- **Customer/API visibility:** shown on property cards only when `outcome === "Sold"` and `sold_price > 0`; **not** a CSV export column (same check as `outcome`).
- **FL/TX dependency:** state-agnostic, same as `outcome`; the field spec explicitly documents it as "the winning bid, not the opening bid."
- **Customer-safe-projection impact:** none, same reasoning as `outcome`.
- **Safe to remain absent:** yes, same reasoning and same source documents as `outcome` — it is the companion field to `outcome` in the same deferred feature, never built on the backend side.
- **Classification: SHOULD BE REMOVED FROM 005/005a.**

### `dor_use_code`

- **Production existence:** absent as of the Phase 14C snapshot (2026-09-14) — the tracked migration for it has simply never been run.
- **Tracked migration:** `schema-v9-dor-use-code.sql`, committed 2026-09-08. Purely additive (`alter table public.properties add column if not exists dor_use_code text;` plus a `comment on column`), explicitly documented in its own header as needing no RLS change and self-backfilling on `enrich_property_details.py`'s normal schedule — no separate backfill script required.
- **Writers:** `scripts/enrich_property_details.py` — a real, currently-functioning writer (line ~760: `("dor_use_code", dor_use_code_str(attrs.get("DOR_UC")))`), fetching the raw 2-digit Florida DOR property-use code from the FDOR Statewide Cadastral layer for every matched parcel since 2026-09-02, per that script's own docstring.
- **Readers:** `public/app.js` reads `p.dor_use_code` (property-detail rendering) and it is a literal CSV export column (`["DOR Use Code", p => p.dor_use_code || ""]`).
- **Customer/API visibility:** yes — both card-level and CSV-export-level, already assumed live by the frontend.
- **FL/TX dependency:** Florida-specific (the FDOR Statewide Cadastral layer is a Florida data source; Texas rows have no equivalent field and are unaffected either way).
- **Customer-safe-projection impact:** if 005/005a run without `dor_use_code` existing first, both fail outright (Phase 14C's actual finding). If `schema-v9-dor-use-code.sql` runs first, both migrations work exactly as designed and the column becomes available exactly where the frontend already expects it.
- **Safe to remain absent:** no — unlike `outcome`/`sold_price`, this is a genuinely intended, already-half-deployed part of the customer contract (real migration + real writer + real, currently-live-but-blank frontend read paths), not a speculative one. Simply omitting it from 005/005a (treating it the same as `outcome`/`sold_price`) would be a mismatch with actual repo intent — the fields are not in the same category.
- **Classification: REQUIRED BEFORE 005** (via its own already-existing, already-tracked, purely-additive migration).

## 4. Correct migration dependency graph

```
schema-v9-dor-use-code.sql   (adds dor_use_code; additive, self-backfilling)
            │
            ▼
005_customer_safe_properties_projection.sql   (get_properties() column projection)
            │
            ▼
005a_close_direct_properties_grant.sql   (column-level GRANT/REVOKE on the base table)
```

This ordering was previously **entirely undocumented** — neither `schema-v9-dor-use-code.sql`'s own header nor 005/005a's original headers ever stated that 005 depends on `schema-v9` having already run. That silence is a direct contributor to how the Phase 14C blocker went undetected until live verification: nothing in the repository asserted the dependency, so nothing could check it ahead of time. All three files now document this ordering explicitly in their own headers (see Sections 5/6 below and each file's own "CORRECTION, Phase 14D" / "DEPENDENCY (added Phase 14D)" comment), and `tests/python/test_phase14d_migration_reconciliation.py` asserts the documentation is present (`test_schema_v9_documents_the_005_ordering_dependency`, `test_005_documents_the_schema_v9_prerequisite`, `test_005a_documents_the_schema_v9_prerequisite`) so it cannot silently regress.

005a's existing, already-documented dependency on 005 (005a must never run without 005 already applied — see 005a's own "VERIFICATION REQUIRED" Section 4, unchanged from Phase 14B) remains in force and is unaffected by this phase's changes.

**Update (Phase 14F, same day): this file's own `CREATE OR REPLACE FUNCTION` statement, while column-correct, was found live to be DDL-invalid.** Postgres rejects it with `ERROR: 42P13: cannot change return type of existing function` — `get_properties()` is currently `RETURNS SETOF properties`, and 005 declares `RETURNS TABLE (...)`; that is a return-type-shape change, which `CREATE OR REPLACE FUNCTION` cannot perform (`DROP FUNCTION` first is required). This is a defect in 005 itself, independent of and in addition to the column-reconciliation work this document describes — the column list below is still correct, but the statement shape needs a `DROP FUNCTION` step added before it can run. See `docs/phase-14f-production-migration-execution-attempt.md` for the full account (schema-v9 succeeded and is now live; 005 failed with this error before any of the column corrections below were tested against production; 005a was never attempted).

**Update (Phase 14G, same day): fixed.** 005 now wraps an explicit `drop function if exists ...` and the `create or replace function` in one transaction, and re-grants `EXECUTE` to the exact live role set instead of narrowing to `authenticated` alone (avoiding a silent privilege loss `DROP FUNCTION` would otherwise cause). That analysis also found `get_properties()`'s `WHERE` clause reads `ledger_type` internally under `SECURITY INVOKER`, so 005a had to be corrected too - it now grants `ledger_type` for that reason alone, while `get_properties()` still never returns it. Full account: `docs/phase-14g-corrective-migration-function-contract.md`.

## 5. Corrected 005 design (`scripts/migrations/005_customer_safe_properties_projection.sql`)

Chosen option (Gate 8, matching the terms that phase's own instructions posed): a hybrid of **Option C** for `dor_use_code` (established via its own already-existing dedicated migration, run first, rather than folded into 005 or omitted) and **Option B** for `outcome`/`sold_price` (simply omitted, since neither is currently deployed and neither has any migration to run). This is the option the repo's actual dependency evidence supports, per Section 3 above — not chosen for convenience; the alternative (Option B for all three, deferring `dor_use_code` too) was rejected specifically because `dor_use_code` already has a real writer and a real migration, unlike the other two, and would leave the CSV export's existing `["DOR Use Code", ...]` column meaningfully worse off than it needs to be once schema-v9 does run.

Changes made this phase:
- `outcome text, sold_price numeric,` removed from the `RETURNS TABLE (...)` clause.
- `outcome, sold_price,` removed from the function body's `SELECT` list.
- `dor_use_code` kept, unchanged, in both places.
- A new "CORRECTION, Phase 14D" header comment added, documenting the removal reasoning and the new `schema-v9-dor-use-code.sql` prerequisite, immediately after the existing "CORRECTION, Phase 14B" comment (`harvester_source`'s own re-inclusion) — following this file's own established pattern of appending a dated correction rather than silently rewriting prior reasoning.
- No other line changed: the function signature (`p_state, p_ledger_type, p_status, p_limit, p_offset`), `security invoker`, the `grant execute ... to authenticated` statement, and the rollback block are all untouched.

The migration remains non-destructive (`CREATE OR REPLACE FUNCTION` only), idempotent (re-running it is a no-op change), and free of `DROP COLUMN`/`DELETE`/`TRUNCATE`/data rewrites (verified by `test_no_migration_file_contains_drop_column_delete_or_truncate`).

**005 customer-safe column buckets** (reconciled against the corrected column list):

- **CUSTOMER-SAFE COLUMNS** (returned by `get_properties()`): `id, state, county, source, harvester_source, address, parcel, case_no, owner_name, status, prop_type, dor_use_code, tx_category, lien_level, lien_note, homestead, bid, assessed, market, value_year, min_bid, redemption_period_months, redemption_expiration_date, max_statutory_return_usd, year_built, living_area, lot_sqft, num_buildings, land_value, legal_desc, last_sale_price, last_sale_year, sale_date, certificate_no, tax_year, issued_date, expiration_date, interest_rate, latitude, longitude, url_appraiser, url_auction, url_taxcoll, url_title, url_streetview, url_zillow, gone_since, updated_at` (47 columns — `dor_use_code` included on the strength of its own prerequisite migration, per Section 3).
- **INTERNAL COLUMNS** (deliberately excluded, unchanged from Phase 14A/14B): `ledger_type`, `fdor_enriched_at`.
- **SYSTEM-METADATA COLUMNS**: `id` (real join key, kept — required by `notes`/`favorites`/`hidden`/`bid_list` — but never a standalone CSV export column, per the existing Phase 14B regression test).
- **RESTRICTED-UNKNOWN COLUMNS** (fail-closed — never named in either migration because this repository cannot confirm what they are): the still-unidentified geometry-related surface (`properties_sync_geom()` exists but is orphaned and targets no real column — see Section 8) and any future column this repository's tracked history does not yet know about. `outcome`/`sold_price` move into this document's own history as "deferred, no longer speculatively included" rather than restricted-unknown — they are fully understood, just not yet backed by real data.

## 6. Corrected 005a design (`scripts/migrations/005a_close_direct_properties_grant.sql`)

Mirrors 005 exactly, since `test_A_005_and_005a_column_lists_are_identical` (Phase 14B) requires the two files to never drift apart:
- `outcome, sold_price,` removed from the `GRANT SELECT (...)` column list.
- `dor_use_code` kept.
- A new "CORRECTION, Phase 14D" header comment added, cross-referencing 005's own correction and restating the corrected three-step execution order.

Reconciled against Phase 14C's live access-model findings (`anon`/`authenticated` currently hold table-level `SELECT`/`INSERT`/`UPDATE`/`DELETE` on `properties`; `get_properties()` `EXECUTE` is granted to `service_role`, `authenticated`, `anon`, `postgres`, and `PUBLIC`; RLS controls rows only, via one PERMISSIVE policy, `"properties: approved only"`, `qual`/`with_check` both `is_approved()`): 005a's actual mechanism — revoke blanket `SELECT` from `anon`/`authenticated`, then grant a narrowed, named-column `SELECT` back to `authenticated` only — is unchanged by this phase and remains correct against that live picture. No RLS policy is created, dropped, or altered by this file (`test_H_neither_migration_creates_or_alters_an_rls_policy`, Phase 14B, still passes unchanged). No `service_role` grant is touched (`test_H_005a_never_touches_service_role`, unchanged). `INSERT`/`UPDATE`/`DELETE` privileges on `properties` are **not** addressed by 005a and remain out of scope for this phase — Phase 14C's finding that `anon`/`authenticated` also hold those was recorded as a live fact, not something this phase's hard rules ("do not change RLS policies," "do not improvise production SQL") authorize touching; a future phase should decide, with its own explicit review, whether write-side grants need the same narrowing treatment.

- **Customer-facing reads:** `authenticated` role, narrowed `SELECT` — this file's entire purpose.
- **Authenticated application reads:** identical to the above (this app has no separate "application" role from the signed-in user's own role).
- **Internal service writes:** `service_role` — untouched, unaffected by any `REVOKE`/`GRANT` targeting `anon`/`authenticated` specifically.
- **Admin-internal reads:** also `service_role` (no separate admin DB role exists in this project's model).
- **RPC execution:** `get_properties()` `EXECUTE` grants are untouched by 005a (that's 005's own `grant execute` statement, unchanged this phase).
- **Direct REST table access:** exactly what 005a exists to narrow — `anon` loses `SELECT` entirely (RLS already blocked it from seeing real rows; this makes the grant match that reality), `authenticated` keeps `SELECT` but only on the corrected column list above.

## 7. `digest_candidates()` drift (Gate 6)

No new investigation was needed or performed this phase — Phase 14C already established the relevant facts live. `schema-v5-digest.sql` is tracked in this repository (root-level, part of the auction-closing-soon email digest feature) but `digest_candidates()` does not exist in production at all — confirmed in Phase 14C via a `pg_proc`/`pg_namespace` search that matched only pgcrypto's unrelated `digest()` function. Nothing in `public/app.js` or any send-digest code path calls it from a location this phase found reason to re-check. Its absence has no bearing on the Phase 14 customer-data boundary (005/005a never reference it, and it is not part of `public.properties` at all). Per this phase's own Gate 6 instruction ("do NOT create or execute the function unless absolutely necessary for the current migration dependency"), it was not created, run, or otherwise touched — it remains a separate, pre-existing, tracked-but-never-run drift item, orthogonal to this phase's scope, same as `schema-v7-bidlist.sql`'s `bid_list` table gap documented in `CLAUDE.md`.

## 8. Geometry/orphan function finding (Gate 7)

**RESOLVED / NON-BLOCKING**, unchanged from Phase 14C — no new evidence surfaced this phase. `properties_sync_geom()` is a real, live `plpgsql` trigger function (`if new.latitude is not null and new.longitude is not null then new.geom := ST_SetSRID(ST_MakePoint(new.longitude, new.latitude), 4326)::geography; end if; return new;`), but it is attached to no trigger on `public.properties` (only four unrelated triggers exist there: `properties_gone_since`, `properties_gone_since_ins`, `properties_touch`, `trg_sync_ledger_type_from_source`), and `properties` has no `geom`/`geometry`-typed column for it to write to even if it were triggered. Neither 005 nor 005a names any geometry-related column (`test_C_no_geometry_column_name_appears_in_either_grant_list`, Phase 14B, still passes unchanged). Per this phase's own instruction, it was not deleted or modified.

## 9. Customer boundary summary

The Phase 14A/14B customer-safe/internal boundary (RPC-level via 005, base-table-level via 005a) is preserved exactly, with the corrected column set from Sections 5/6: 47 customer-safe columns (once `dor_use_code`'s own prerequisite is satisfied), 2 internal columns (`ledger_type`, `fdor_enriched_at`) permanently excluded, and 2 previously-speculative columns (`outcome`, `sold_price`) removed from the active contract pending a real backend implementation. No RLS policy is touched by any file this phase edited. `service_role` is unaffected throughout.

## 10. Pre-execution checklist (for the fresh Gate A this phase's own hard rules require before any of the three files run)

A future Gate A must re-verify every item below live — nothing in this list is assumed to still hold from Phase 14C's snapshot without a fresh check, since time has passed and this repository's own history shows tracked state and live state can diverge silently:

1. Confirm `schema-v9-dor-use-code.sql` has not already been run (if it has, its own migration is a no-op via `add column if not exists` — safe either way, but the checklist should record which is true).
2. Confirm the live `public.properties` column list, in full, via `information_schema.columns` — do not reuse Phase 14C's snapshot uncritically, given the "47 vs 49" inconsistency found this phase (Section 2 above); record a fresh, single authoritative count.
3. Confirm the live RLS policy set on `properties` is still exactly what Phase 14C found (one PERMISSIVE `"properties: approved only"` policy, `qual`/`with_check` both `is_approved()`) — do not assume it is unchanged.
4. Confirm the live grants on `properties` for `anon`/`authenticated` are still what Phase 14C found (table-level `SELECT`/`INSERT`/`UPDATE`/`DELETE` for both).
5. Confirm `get_properties()`'s live definition is still exactly Phase 14C's finding (matches tracked migration 003, `security invoker`) — i.e., no other session has already changed it.
6. Re-run the row-count and identity-duplicate checks (Phase 14C's Section 10 pattern) to get a current baseline before any change.
7. Confirm this repository's `git log` HEAD matches the commit this checklist expects (this phase's own commit, or later) — i.e., 005/005a are the corrected versions, not the pre-14D ones.
8. Re-run `tests/python/` in full and confirm all pass (this phase leaves it at 151/151 — see Section 12).

## 11. Exact production execution order

1. **`schema-v9-dor-use-code.sql`** — `alter table public.properties add column if not exists dor_use_code text;` plus its `comment on column` statement. Additive, non-destructive, no RLS change, self-backfilling.
2. **`scripts/migrations/005_customer_safe_properties_projection.sql`** — `create or replace function public.get_properties(...)`. Requires step 1 already complete (fails otherwise — `dor_use_code` would not exist).
3. **`scripts/migrations/005a_close_direct_properties_grant.sql`** — the `REVOKE`/`GRANT SELECT (...)` statements. Requires step 2 already complete and confirmed working (per that file's own, unchanged, Phase 14B "VERIFICATION REQUIRED item 4" reasoning: applying 005a while `get_properties()` still selects `*` would break the RPC for every caller).

No step in this order is reversible-by-accident-proof — each has its own documented rollback (schema-v9: none needed, it's additive-only and harmless to leave in place; 005: revert to the pre-005 `select *` body, reproduced in that file's own rollback comment; 005a: re-grant blanket `SELECT`, reproduced in that file's own rollback comment) but this phase does not execute any of them.

## 12. Exact post-execution verification requirements

After step 1 (schema-v9): confirm `dor_use_code` appears in `information_schema.columns` for `public.properties`; confirm `enrich_property_details.py`'s next scheduled run begins populating it (no manual backfill required, per that migration's own header).

After step 2 (005): confirm `get_properties(p_state)` still returns every field `public/app.js` reads (cross-check against the CUSTOMER-SAFE COLUMNS list in Section 5); confirm a raw REST call to the RPC no longer includes `ledger_type`/`fdor_enriched_at`; confirm the frontend's card rendering, CSV export, and every filter behave identically to before (Playwright regression, `tests/run_test.mjs`, per 005's own existing test plan).

After step 3 (005a): confirm a raw authenticated REST call to `/rest/v1/properties?select=harvester_source` now returns an empty column set or a permission error; confirm `/rest/v1/properties?select=*` now returns only the corrected customer-safe column list; confirm the frontend still loads and renders identically (same Playwright check); confirm `service_role`-driven harvester/sync writes are unaffected.

After all three: re-run the full `tests/python/` suite (expect 151/151, unchanged by execution since these are static repository tests); re-run the row-count/identity-duplicate checks and confirm no row was modified, added, or deleted by any of the three steps (all are schema/function/grant changes only).

## 13. Known unresolved limitations

- This phase performed no live verification of any kind — every finding above is either carried forward from Phase 14C's snapshot (dated, not re-confirmed) or derived from static repository inspection. A fresh Gate A (Section 10's checklist) is required, and is explicitly the only thing recommended to follow this phase — not Phase 15, and not execution.
  - **Update (same day):** that fresh Gate A was performed — see `docs/phase-14e-gate-a-execution-attempt.md` and `docs/phase-14c-production-migration-verification.md` Section 14. Result: **GREEN**, every item in Section 10's checklist independently re-confirmed live. Execution (Gate B) was then attempted and stopped by a tool-access denial in that session before any SQL reached production — the corrected package here remains unexecuted and ready.
- The Phase 14C documentation's own "47 columns" (prose) vs. 49-name (literal list) inconsistency (Section 2) was found but not resolved — this phase deliberately did not re-query production to settle it, consistent with its own repository-only scope. A future Gate A should record one authoritative, freshly-queried figure.
  - **Update (same day):** resolved by the fresh Gate A above — the live column count is **49**, matching the literal list; "47" was simply a prose error.
- Whether `outcome`/`sold_price` should ever be built (a real harvester-side outcome-capture pipeline, per `claude/closed-outcome-and-map-cities.md`'s already-written field spec) is a real, separate product decision this phase does not make — it only resolves the narrower question of whether 005/005a should reference them *today* (no).
- The write-side grants (`INSERT`/`UPDATE`/`DELETE` on `properties` for `anon`/`authenticated`, confirmed present live by Phase 14C) remain untouched and unreviewed by any phase to date — named here, as Phase 14C also named it, as a real gap for a future phase's own explicit review, not something this phase's hard rules permit deciding now.
- The raw-REST-path closure options 005's own header names as its "TARGET ARCHITECTURE" (revoke-and-force-through-RPC, or a narrower view) remain undesigned beyond 005a's grant-based approach — unchanged from Phase 14B/14C, not a new limitation this phase introduces.
