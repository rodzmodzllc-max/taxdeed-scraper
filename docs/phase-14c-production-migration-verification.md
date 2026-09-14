# Phase 14C: Production Customer-Boundary Migration & Verification Gate

**Status:** Phase 14C, 2026-09-14. **Gate A: BLOCKED.** No migration was executed. Companion to `docs/phase-14b-database-api-boundary-readiness.md` (Phase 14B — designed migrations 005/005a) and `docs/phase-14a-customer-safety-hardening.md` (Phase 14A). This document records the live-database preflight this phase performed and the exact reason execution did not proceed.

## 1. Preflight state (starting point)

HEAD at start: `b743f28` (Phase 14B), clean tree, branch `main`. `mcp__Supabase__list_tables` and `mcp__Supabase__execute_sql` — both denied in Phase 14A and Phase 14B — succeeded this phase against project `cqnnnvpbocafuvpzfbzu` ("taxdeed", production). This is recorded as a fact about this session's tool access, not assumed to hold in any future session.

## 2. Live schema findings (Gate A1)

`public.properties` has **47 columns**, read directly via `information_schema.columns` (not `list_tables`'s summary alone — cross-checked against both):

```
id, source, county, case_no, parcel, owner_name, address, bid, assessed,
market, status, lien_level, lien_note, prop_type, sale_date, homestead,
url_streetview, url_appraiser, url_zillow, url_taxcoll, url_auction,
url_title, updated_at, gone_since, interest_rate, certificate_no, tax_year,
issued_date, expiration_date, latitude, longitude, year_built, living_area,
lot_sqft, land_value, legal_desc, last_sale_price, last_sale_year,
value_year, num_buildings, fdor_enriched_at, state, tx_category,
redemption_period_months, redemption_expiration_date,
max_statutory_return_usd, min_bid, ledger_type, harvester_source
```

Types/nullability/defaults recorded in full (see the raw query result in this phase's session — representative examples: `state text not null default 'FL'`, `status text not null default 'active'`, `lien_level text not null default 'unscreened'`, `homestead boolean not null default false`, `updated_at timestamptz not null default now()`, `id uuid not null default gen_random_uuid()`).

**Constraints** (`pg_constraint`): `properties_pkey` (PRIMARY KEY on `id`), `properties_state_source_county_case_no_key` (UNIQUE on `(state, source, county, case_no)` — confirmed present, unaltered), `properties_source_check` (`source` ∈ `auction`/`laft`/`certificate`), `properties_lien_level_check` (`lien_level` ∈ `clean`/`flag`/`serious`/`unscreened`), `properties_ledger_type_check` (`ledger_type` ∈ `auctions`/`buy`/`lien`, marked **`NOT VALID`** — the constraint exists but was never validated against pre-existing rows; noted, not this phase's concern, not touched).

**Indexes** (`pg_indexes`): `properties_pkey`, `properties_county_idx`, `properties_saledate_idx`, `properties_status_idx`, `properties_state_source_county_case_no_key` (the unique constraint's backing index), `idx_properties_state_county`, `idx_properties_tx_category` (partial, `where tx_category is not null`), `properties_source_idx`, `properties_fdor_enriched_at_idx` (partial, `where fdor_enriched_at is null`), `idx_properties_state_ledger_saledate`. No spatial/geometry index of any kind.

**Triggers** (`pg_trigger`, non-internal, on `properties`): `properties_gone_since` (`track_gone_since()`, BEFORE UPDATE), `properties_gone_since_ins` (`track_gone_since_insert()`, BEFORE INSERT), `properties_touch` (`touch_updated_at()`, BEFORE UPDATE), `trg_sync_ledger_type_from_source` (`sync_ledger_type_from_source()`, BEFORE INSERT OR UPDATE OF source). **No geometry-sync trigger is attached to `properties`.**

**Two columns migrations 005/005a assume exist do not exist live**: `outcome`, `sold_price`. **One column a tracked migration (`schema-v9-dor-use-code.sql`) was supposed to add does not exist live either**: `dor_use_code`. Confirmed by a direct, targeted query (`select column_name from information_schema.columns where ... and column_name in ('outcome','sold_price','dor_use_code','geom','geometry')` → zero rows), not inferred from the broader column list by omission. This is the Section 4 blocker.

## 3. Geometry finding (Gate A1, `properties_sync_geom`)

**Resolved, not blocking.** `public.properties` has **no geometry-typed column** (confirmed by the full `information_schema.columns` listing above, and by the targeted `geom`/`geometry` check in Section 2 returning zero rows) and **no trigger on `properties` calls `properties_sync_geom`** (confirmed by the full trigger listing — only the four triggers named above exist). `properties_sync_geom()`'s own definition, read directly:

```sql
CREATE OR REPLACE FUNCTION public.properties_sync_geom()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
begin
  if new.latitude is not null and new.longitude is not null then
    new.geom := ST_SetSRID(ST_MakePoint(new.longitude, new.latitude), 4326)::geography;
  end if;
  return new;
end;
$function$
```

This function references `new.geom` — a column that would need to exist on whatever table it's attached to. It is currently **orphaned**: defined, but not wired to any trigger on `properties`, and `properties` has no `geom` column for it to write to even if it were wired up. This is most plausibly a leftover from an earlier, abandoned, or not-yet-completed PostGIS integration attempt (consistent with `postgis` being installed in the `public` schema per Phase 14A/14B's `get_advisors` findings) — not an active customer-data exposure of any kind, since no geometry data flows through `properties` today. **Neither migration 005 nor 005a needs to account for a geometry column, because none exists.** This closes the Phase 13/14A/14B "unidentified geometry column" open item definitively, in the direction of "nothing to protect," not "something was missed."

## 4. The Gate A blocker

**Migrations 005 and 005a, as committed in Phase 14B (and amended once within Phase 14B itself), reference three columns that do not exist on the live `public.properties` table: `outcome`, `sold_price`, and `dor_use_code`.**

Both files' `returns table (...)` / `select ...` / `grant select (...)` lists name all three. If either migration were executed as written, Postgres would reject it outright with a hard error (`column "outcome" does not exist`, or equivalent) — `get_properties()`'s `CREATE OR REPLACE FUNCTION` would fail to compile, and 005a's `GRANT SELECT (...)` would fail to resolve the column list. Neither migration would silently succeed with a narrower result; both would simply fail.

This is not a hypothetical risk — it was verified directly against the live table's actual column set (Section 2), not inferred from Phase 13/14A/14B's own prior documentation (which listed `outcome`/`sold_price` as real, customer-visible columns, and `dor_use_code` as added by a real, tracked migration). All three were wrong about live reality. `public/app.js` itself already reads all three defensively (`p.outcome`, `p.sold_price`, `p.dor_use_code`, each handled with a null-safe fallback — confirmed by direct inspection this phase, Section 6) — meaning the frontend has silently tolerated their absence in production this whole time, which is exactly why no prior phase's own testing (all of it against repository files, never live data) caught this: a Python test reading `public/app.js`'s source text has no way to know whether `p.dor_use_code` resolves to a real value or `undefined` at runtime.

**Per this phase's own explicit rule ("If either migration differs materially from the Phase 14B design: STOP. Do not improvise" and "Do not manually edit SQL during execution unless a clearly documented, non-semantic formatting issue prevents execution") — a three-column mismatch between a proposed migration and the live schema is not a formatting issue. It is a semantic difference this phase does not have standing authorization to resolve by editing and immediately running corrected SQL.** Gate A therefore blocks before any migration is executed.

## 5. Live grants (Gate A5)

`information_schema.role_table_grants` for `public.properties`: `anon` and `authenticated` each currently hold `SELECT`, `INSERT`, `UPDATE`, `DELETE` (table-level, no column restriction) — broader than this phase's own focus (SELECT-only) anticipated, though consistent with 005a's own stated assumption that both roles hold blanket `SELECT`. `postgres` holds full grantable privileges (table owner). `service_role` shows no explicit grant rows in this view — consistent with Supabase's standard configuration where `service_role` bypasses grants/RLS entirely at a higher level rather than being enumerated here.

`information_schema.role_routine_grants` for `get_properties()`: `EXECUTE` is granted to `service_role`, `authenticated`, `anon`, `postgres`, **and `PUBLIC`** — broader than migration 003's own tracked text (`grant execute ... to authenticated` only). `PUBLIC`-level execute on a Postgres function is a common default for newly created SQL functions unless explicitly revoked; RLS (`is_approved()`) still gates which rows an unapproved caller actually gets back, so this is not itself a customer-data exposure, but it is a second live-vs-tracked divergence worth naming for completeness (not something 005/005a were designed to change, and not changed by this phase).

**`digest_candidates()` does not exist in the live database at all.** A search for any function whose name contains "digest" in any schema returns only pgcrypto's unrelated `digest()` (in the `extensions` schema). `schema-v5-digest.sql` — like `schema-v9-dor-use-code.sql` — was written and committed but, per this project's own long-documented pattern (`CLAUDE.md`: "a migration gets written and committed well before anyone actually runs it against Supabase," previously confirmed for `bid_list`/certificates), never actually run against this production project. This means the `send-digest` Edge Function, if ever invoked on a schedule, would currently fail calling a function that doesn't exist. This is a pre-existing condition, unrelated to and unaffected by migrations 005/005a (neither touches `digest_candidates()`), named here because Gate A4 explicitly asked this phase to inspect and record it, not because this phase is fixing it.

## 6. Live RLS (Gate A6)

`pg_policies` for `public.properties` shows exactly one policy: **`"properties: approved only"`, `PERMISSIVE`, roles `{public}`, `cmd ALL`, `qual is_approved()`, `with_check is_approved()`.**

**This resolves a real, open question from Phase 14B's own audit.** `schema-v6-approvals.sql`'s tracked text defines this same policy `AS RESTRICTIVE`, and Phase 14B's own read of the tracked migration history found no accompanying PERMISSIVE policy anywhere — flagged then as a genuine gap this repository's history couldn't explain (a RESTRICTIVE-only table with zero PERMISSIVE policies returns empty results for everyone, per `CLAUDE.md`'s own documented 2026-08-24 outage lesson, yet the app demonstrably works). The live database now shows the actual answer: **the deployed policy is PERMISSIVE, not RESTRICTIVE** — someone changed it at some point after `schema-v6-approvals.sql` was written (an `ALTER POLICY` cannot change RESTRICTIVE↔PERMISSIVE, per `CLAUDE.md`'s own note, so this was necessarily a `DROP POLICY` + `CREATE POLICY`, not a simple edit — plausibly the actual fix applied during or after the outage `CLAUDE.md` describes, converting the table's only policy from RESTRICTIVE to PERMISSIVE so it alone could grant access rather than needing a separate PERMISSIVE policy underneath it). This repository's tracked `.sql` files describe a state the live database has since diverged from — consistent with, and now a second concrete instance of, the same "tracked history isn't the live source of truth" pattern already found for RLS policy existence (Phase 14B), several columns (Phase 13), and now table columns/functions (Section 2/5 above) in this very phase.

`relrowsecurity = true`, `relforcerowsecurity = false` for `public.properties` — standard configuration, RLS enabled and not forced (force-RLS only matters for table-owner bypass, not relevant to this table's access model).

**Per this phase's own hard rule ("RLS controls rows. It does NOT by itself provide column-level protection. Do not treat 'RLS enabled' as proof that the customer boundary is safe."): this finding does not change the Section 4 blocker or the fundamental column-exposure gap 005/005a exist to close.** It only replaces an open, undocumented-live-state question with a confirmed, live-verified answer — good news for understanding the system, orthogonal to the migrations' current inability to execute.

## 7. Frontend read path (Gate A7 — re-audited this phase, not assumed)

Re-confirmed directly against the current `public/app.js`, not against Phase 14A/14B's own summaries:

- `fetchProperties()` calls `sb.rpc("get_properties", { p_state: PAGE_STATE })` as its primary path (`app.js:1262`), falling back to `sb.from("properties").select("*")` (`app.js:1268`) if the RPC is missing.
- `p.harvester_source` is read in exactly two places (`app.js:715-716`), both inside `assessedSourceLabel(p)`, to distinguish `tx_lgbs` from `tx_realauction` rows for value labeling — unchanged since Phase 14B, confirmed no drift.
- No real property-access reference to `ledger_type` or `fdor_enriched_at` exists anywhere in `app.js` (the only matches are `003_ledger_type_and_state_isolation.sql` filename mentions in comments/a console.warn string).
- **New finding this phase**: `app.js` reads `p.outcome` (`app.js:103`), `p.sold_price` (`app.js:106`, `1606`), and `p.dor_use_code` (`app.js:571-573`, `2956`) — all three null-safely, and all three currently always resolve to `undefined` in production since none of the three columns exists on the live table (Section 2). This is the frontend-side mirror of the Section 4 blocker: these three fields are part of the *declared* customer contract (Phase 13 Section 5 already listed `dor_use_code`/`outcome`/`sold_price` as "customer-visible … always blank today" for the redemption/TX-category fields' sibling case) but not part of the *live* schema at all for these three specifically.

## 8. Migration compatibility (Gate A8)

`scripts/migrations/005_customer_safe_properties_projection.sql` and `scripts/migrations/005a_close_direct_properties_grant.sql`, re-inspected this phase:

- 005 **does** include `harvester_source` (the Phase 14B correction) — confirmed present in both the `returns table` clause and the `select` list.
- 005a **does** include the intended `revoke select ... from anon; revoke select ... from authenticated;` followed by a matching `grant select (...) ... to authenticated`.
- 005a is documented to require 005 applied first — confirmed present in 005a's own header text.
- **Both files list `outcome`, `sold_price`, `dor_use_code` — columns that do not exist live (Section 2/4).** This is the one, sufficient reason this phase does not proceed past Gate A. No other defect was found in either file's design (the `security invoker` reasoning, the ordering dependency, the `service_role` non-interference, and the `harvester_source` inclusion all check out against live reality — Sections 5-7 above independently corroborate each of those design assumptions was correct).

## 9. Gate A decision

```
[x] live properties schema identified            - Section 2 (47 columns, live, via information_schema)
[x] geometry column identified                    - Section 3 (none exists; properties_sync_geom is orphaned)
[x] current row count recorded                     - Section 10 (3,929)
[x] identity uniqueness verified                    - Section 10 (0 duplicates on state,source,county,case_no)
[x] unique constraint verified                      - Section 2 (properties_state_source_county_case_no_key present)
[x] get_properties() inspected                      - Section 5 (matches tracked migration 003 exactly, security invoker)
[x] digest_candidates() inspected                   - Section 5 (does not exist live - pre-existing, unrelated gap)
[x] current grants inspected                        - Section 5
[x] current RLS inspected                           - Section 6 (one PERMISSIVE policy, live text differs from tracked file)
[x] frontend read paths inspected                   - Section 7
[x] 005 inspected                                   - Section 8
[x] 005a inspected                                  - Section 8
[x] 005 includes harvester_source                   - Section 8 (yes)
[x] migration order confirmed 005 -> 005a            - Section 8 (documented in 005a's own header)
[ ] no unresolved permission dependency              - N/A, not reached (see below)
[x] no unresolved geometry dependency                - Section 3 (resolved: no column exists)
[ ] no unexplained production state                  - FAILS: outcome/sold_price/dor_use_code referenced by both
                                                        migrations do not exist on the live table (Section 2/4)
```

**GATE A = BLOCKED.**

The blocker is narrow and precisely identified, not a general uncertainty: migrations 005 and 005a both reference three columns (`outcome`, `sold_price`, `dor_use_code`) that do not exist on the live `public.properties` table. Every other precondition this phase checked — row count, identity/uniqueness, the unique constraint, `get_properties()`'s actual definition, current grants, current RLS, the frontend's actual read paths, the `harvester_source` inclusion, the 005→005a ordering — passed, and several genuinely uncertain items from Phase 14B (the live RLS permissive/restrictive question, the geometry column's existence) were resolved favorably. This phase does not execute either migration.

## 10. Preflight data snapshot (for the record, pre-migration — nothing below this line was ever compared against a "post" state, since no migration ran)

- **Row count**: `select count(*) from public.properties` → **3,929**. (The prior verification's cited baseline of 3,366 is stale — the live number is recorded as-is, not reconciled against that figure, since this phase's job is to record the actual current count, not explain its growth since a prior, unspecified checkpoint.)
- **Identity duplicates**: `group by state, source, county, case_no having count(*) > 1` → **0 rows**.
- **Unique constraint**: `properties_state_source_county_case_no_key`, `UNIQUE (state, source, county, case_no)` — present, unaltered.

## 11. What this phase did not do

Per the hard rules and the Gate A block: no migration was executed (neither 005 nor 005a); no production data was modified, deleted, or rewritten; no RLS policy was created or altered; no grant was changed; no Texas county was added; no source was activated or had its legal status changed; no GitHub Actions workflow was dispatched; no push to origin occurred. `harvesters/governance/registry.py` was not touched (re-confirmed via `git diff` — empty). No new tests were added this phase: the blocker is a live-infrastructure fact, not a repository-internal one, and the existing 139 repository-level tests remain accurate descriptions of the repository's own (unmodified) contents — adding a test that encodes today's live column snapshot was considered and deliberately not done, since a static test cannot detect future live-schema drift any more reliably than this phase's own direct live query just did, and a stale hardcoded snapshot risks being trusted over a future live check the same way Phase 13/14A/14B's own prior documentation was.

## 12. Recommended next action

Not Phase 15. The concrete, narrow next step is a corrective revision of migrations 005 and 005a: drop `outcome`, `sold_price`, and `dor_use_code` from both files' column lists (they cannot be granted or projected — they don't exist), leaving every other column unchanged, and re-run this same Gate A preflight against the corrected files before ever attempting Gate B. Whether `dor_use_code` should instead be added to the live schema first (since a tracked migration for it already exists, `schema-v9-dor-use-code.sql`, and `app.js`/the CSV export already assume it) — as opposed to simply omitting it from 005/005a until it exists — is a real product/scope decision this phase does not make unilaterally; it is named here as the decision a corrective phase should resolve explicitly, not default into either direction silently. `outcome`/`sold_price` have no tracked migration at all (Phase 13 Section 24 already flagged this) and are a separate, smaller decision (populate them via a new migration, or drop the frontend's dead reads to them, or leave both untouched and simply exclude them from 005/005a going forward).

## 13. Phase 14D outcome (update)

Phase 14D (Migration Reconciliation & Pre-Execution Re-Gate) performed exactly the corrective revision this section recommended, and resolved the "real product/scope decision" this section deliberately declined to make unilaterally: see `docs/phase-14d-migration-reconciliation.md` for the full analysis. Summary: `outcome`/`sold_price` are removed from both 005 and 005a (no writer anywhere in the repository, no tracked migration ever proposed either); `dor_use_code` is kept in both, but `schema-v9-dor-use-code.sql` is now a formally documented prerequisite that must run first (it already has a real, tracked, additive migration and a real, currently-functioning writer — a materially different situation from `outcome`/`sold_price`). Corrected execution order: `schema-v9-dor-use-code.sql` → 005 → 005a. Phase 14D did not execute any of the three against production; a fresh Gate A preflight (re-verifying this section's own findings, since none of them are assumed to still hold without re-checking) is still required before Gate B.

**Documentation correction found while building Phase 14D's compatibility tests:** this section's own Section 2 says "47 columns" in prose, but the literal column-name list in that same section actually contains 49 distinct names. This is a pre-existing inconsistency within this document, not a re-verified live fact either way — Phase 14D did not re-query production (by design; see that phase's own doc). It does not affect this document's Section 4 blocker or Phase 14D's fix: `outcome`, `sold_price`, and `dor_use_code` are absent from that column-name list under either count. A future live Gate A should record a fresh, single authoritative column count rather than relying on this section's prose figure.
