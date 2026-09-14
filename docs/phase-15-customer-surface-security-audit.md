# Phase 15: End-to-End Customer Surface Security & Contract Verification

**Status:** 2026-09-14, same day as Phase 14H. Read-only/code/test audit of the actual application customer surfaces against the production database boundary Phase 14H closed (CLOSED_WITH_LIMITATIONS). No migration, no source activation, no county expansion, no legal-status change, no production data mutation. One infrastructure bug found and fixed (a broken test mock — see Section 3), one documentation miscount corrected (Section 2), one new test file added (Section 11). Everything else in this document is verification only.

## 0. Executive result

**PASS_WITH_LIMITATIONS.**

No hard-stop condition (Section 20 of the phase instructions) was triggered: no anonymous path returns property rows, no authenticated access to an excluded field was found, no alternate frontend/API path bypasses `get_properties()`, the CSV export does not exceed the approved contract, no customer UI exposes governance/provenance internals, no production mutation was needed to prove any of this, and nothing required guessing. The "limitations" in PASS_WITH_LIMITATIONS are exactly the one already-accepted `ledger_type` raw-REST exception (unchanged from Phase 14H) plus two newly found, non-security findings (a stale deployed frontend bundle, and the field-count documentation miscount) — see Section 17 (Findings).

## 1. Starting assumptions — verified against the actual repository and live production, not trusted from documentation

Every claimed starting condition in the phase instructions was independently re-checked this phase (fresh Supabase queries, not reused from memory):

| Assumption | Verified | Discrepancy? |
|---|---|---|
| schema-v9 applied in production | ✅ (`dor_use_code` present, `mcp__Supabase__list_migrations` shows it) | None |
| Corrected 005 executed in production | ✅ (`pg_get_functiondef` shows the named `RETURNS TABLE` shape) | None |
| Corrected 005a executed in production | ✅ (column grants narrowed, verified live this phase — see Section 6) | None |
| `get_properties()` returns a named customer-safe shape | ✅ | **Column count is 48, not 47** — see Section 2 |
| `authenticated` limited to customer-safe columns + `ledger_type` | ✅ (49 = 48 + 1, live-counted) | Same off-by-one as above |
| `anon` has no direct SELECT on `properties` | ✅ (0 rows in `role_table_grants` and `role_column_grants` for anon/SELECT) | None |
| `fdor_enriched_at` unreachable for `authenticated` | ✅ (re-run live: `permission denied for table properties`) | None |
| `get_properties()` works under the narrowed grant | ✅ (re-run live, no permission error) | None |
| RLS enabled and unchanged | ✅ (single PERMISSIVE `is_approved()` policy, same as Phase 14H) | None |
| `service_role` write access intact | ✅ (full column/table grants unchanged) | None |
| 3,929 rows, 0 identity duplicates | ✅ (re-queried live, identical) | None |
| FL/TX/Leon isolation verified | ✅ (re-confirmed this phase via code trace, not re-queried live again — Phase 14H's live counts stand, no write has occurred since) | None |
| 162/162 tests passing (baseline) | ✅ (was the count at the start of this phase, before Phase 15's own 8 new tests) | None |
| Customer boundary CLOSED_WITH_LIMITATIONS | ✅ | None |
| Local commit `de93556` / `e446504` | ✅ (`git log` confirms both, tree clean at session start) | None |

**The one discrepancy found**, per the phase's own instruction to "stop and report the discrepancy rather than silently changing anything": the phase background (and three prior committed documents — 14B, 14D, 14H) describe the customer-safe shape as "~47 columns." A direct count of the actual `RETURNS TABLE` clause in `scripts/migrations/005_customer_safe_properties_projection.sql`, cross-checked against a live count of `authenticated`'s column-level SELECT grants (49 = 48 + the `ledger_type` exception), shows the real number is **48**. This is not a security finding — every column that should be there is there, and the DB-layer boundary Phase 14H closed is exactly as strong as documented — it is a documentation-only miscount, most likely from `id` (the internal join-only UUID) never being included in the informal tally despite always appearing in the literal column list. This phase does not silently continue with the wrong number: Section 2 below uses 48 throughout, and `docs/phase-14d-migration-reconciliation.md` and `docs/phase-14h-production-retry-success.md` were each given a short correction note (not rewritten) pointing here. This did not rise to a hard-stop — it has zero effect on any prior phase's pass/fail conclusion — so the audit proceeded rather than halting.

## 2. Customer surface inventory and the 48-field contract

### 2.1 Every customer-readable data path (traced, not assumed)

| # | Path | Mechanism | Who can reach it | Projection applied |
|---|---|---|---|---|
| 1 | `public/app.js` property listing | `sb.rpc("get_properties", {p_state})` | `authenticated` only, in practice (see Section 4) | DB-layer: 005's 48-column `RETURNS TABLE` |
| 2 | `public/app.js` raw-table fallback | `sb.from("properties").select("*")` | Same as #1, but only reachable if the RPC itself is dropped from the schema (see Section 4.2) | DB-layer: 005a's 49-column grant (48 + `ledger_type`) for `authenticated`; nothing for `anon` |
| 3 | Direct Supabase REST, any client | `GET /rest/v1/properties` | Any bearer of a valid `authenticated` JWT (not just this app) | Same 49-column grant as #2 |
| 4 | Direct Supabase REST, any client | `POST /rest/v1/rpc/get_properties` | Any bearer of a valid JWT, `authenticated` or `anon` (EXECUTE is granted to both, plus `service_role`/`postgres`/`PUBLIC`) | 48-column `RETURNS TABLE`; for `anon` specifically, the call now fails outright (`permission denied for table properties`) rather than returning rows, because `anon` holds no column grant at all — verified live, see Section 6 |
| 5 | CSV export | In-memory, from the same `ALL` array `fetchProperties()` already populated — no separate network request | Same as #1 | Client-side allowlist, 41 columns (see Section 2.3) |
| 6 | `notes`/`favorites`/`hidden`/`bid_list`/`county_calendar` | `sb.from(...)` | `authenticated`, own-row or shared-visibility per table's RLS | Unrelated to `properties`'s column boundary; unaffected by 005/005a |
| 7 | `send-digest` (`digest_candidates()` RPC) | `service_role`-only Edge Function | Nobody externally — **zero Edge Functions are actually deployed** (`mcp__Supabase__list_edge_functions` returns `[]`, reconfirmed live this phase) | N/A (not currently reachable at all) |
| 8 | `explore.js` | No Supabase calls of any kind (confirmed: no `sb.`/`supabase`/`createClient`/`.select(` anywhere in the file) | N/A | Consumes only what `app.js` already fetched and filtered |

No sixth or seventh path was found. The repo-wide dangerous-pattern search (object spread of a row, `console.log` of a full record, a second undocumented `.from("properties")` call, an admin/debug endpoint with no projection) came back empty — see Section 12.

### 2.2 The 48-field customer-safe contract (from `get_properties()`'s actual live `RETURNS TABLE` clause)

| # | Field | DB type | Purpose | Frontend usage | CSV | Classification |
|---|---|---|---|---|---|---|
| 1 | `id` | uuid | Row identity, join key for notes/favorites/hidden/bid_list | Used only for joins, never rendered as a value | No | INTERNAL-BUT-NOT-SENSITIVE (a UUID, no information content) |
| 2 | `state` | text | FL/TX region | Yes (`regionOf`) | Yes ("State") | PUBLIC |
| 3 | `county` | text | County name | Yes | Yes | PUBLIC |
| 4 | `source` | text | `auction`/`laft`/`certificate` | Yes | Yes | PUBLIC |
| 5 | `harvester_source` | text | Vendor code (`tx_lgbs`/`tx_realauction`/etc.) | Yes — `assessedSourceLabel()` (card + CSV) | Yes ("Assessed/Value Field Source", derived) | PUBLIC (source-vendor code, not sensitive) |
| 6 | `address` | text | Property address | Yes | Yes | PUBLIC |
| 7 | `parcel` | text | Parcel/secondary id | Yes | Yes | PUBLIC |
| 8 | `case_no` | text | Identity-bearing case/account # | Yes | Yes | PUBLIC |
| 9 | `owner_name` | text | Owner of record | Yes | Yes | PERSONAL (owner-of-record name; public record data, same classification Phase 13 gave it) |
| 10 | `status` | text | `active`/`closed`/etc. | Yes | Yes | DERIVED |
| 11 | `prop_type` | text | Property type bucket | Yes | Yes | PUBLIC |
| 12 | `dor_use_code` | text | FDOR use code | No current card use found; CSV yes | Yes | PUBLIC |
| 13 | `tx_category` | text | TX SPTB category (always blank, no writer) | Yes (blank) | Yes | PUBLIC (future) |
| 14 | `lien_level` | text | Title-status screening judgment | Yes | Yes | DERIVED |
| 15 | `lien_note` | text | Free-text note on lien_level | Yes | No | DERIVED |
| 16 | `homestead` | boolean | Homestead exemption flag | Yes | Yes | PUBLIC |
| 17 | `bid` | numeric | Opening bid | Yes | Yes | PUBLIC |
| 18 | `assessed` | numeric | County assessed/CAD/adjudged value (semantically overloaded across states, Phase 13 §9/10, unchanged) | Yes | Yes | PUBLIC |
| 19 | `market` | numeric | FL just value (never populated for TX) | Yes | Yes | PUBLIC |
| 20 | `value_year` | int | Just-value roll year | Yes | Yes | PUBLIC |
| 21 | `min_bid` | numeric | TX statutory minimum | Yes | Yes | PUBLIC |
| 22 | `redemption_period_months` | int | TX redemption period (always blank, no writer) | Yes (blank) | Yes | PUBLIC (future) |
| 23 | `redemption_expiration_date` | date | TX redemption expiry (always blank) | Yes (blank) | Yes | PUBLIC (future) |
| 24 | `max_statutory_return_usd` | numeric | TX statutory max return (always blank) | Yes (blank) | Yes | PUBLIC (future) |
| 25 | `year_built` | int | Tax-roll spec | Yes | Yes | PUBLIC |
| 26 | `living_area` | int | Tax-roll spec | Yes | Yes | PUBLIC |
| 27 | `lot_sqft` | int | Tax-roll spec | Yes | Yes | PUBLIC |
| 28 | `num_buildings` | int | Tax-roll spec | Yes | Yes | PUBLIC |
| 29 | `land_value` | numeric | Tax-roll spec | Yes | Yes | PUBLIC |
| 30 | `legal_desc` | text | Legal description | Yes | Yes | PUBLIC |
| 31 | `last_sale_price` | numeric | Tax-roll spec | Yes | Yes | PUBLIC |
| 32 | `last_sale_year` | int | Tax-roll spec | Yes | Yes | PUBLIC |
| 33 | `sale_date` | date | Auction/event date | Yes | Yes | PUBLIC |
| 34 | `certificate_no` | text | FL certificate # | Yes | Yes | PUBLIC |
| 35 | `tax_year` | text | Certificate tax year | Yes | Yes | PUBLIC |
| 36 | `issued_date` | date | Certificate issued date | Yes | Yes | PUBLIC |
| 37 | `expiration_date` | date | Certificate expiration | Yes | Yes | PUBLIC |
| 38 | `interest_rate` | numeric | Certificate interest rate | Yes | Yes | PUBLIC |
| 39 | `latitude` | double | Coordinates (source or geocoder fill-blank) | Yes (Street View link) | No (feeds a derived link) | PUBLIC |
| 40 | `longitude` | double | Coordinates | Yes | No (feeds a derived link) | PUBLIC |
| 41 | `url_appraiser` | text | Appraiser link | Yes | Yes | PUBLIC |
| 42 | `url_auction` | text | Auction/LAFT listing link | Yes | Yes | PUBLIC |
| 43 | `url_taxcoll` | text | Tax collector link (always blank) | Yes (blank) | Yes | PUBLIC |
| 44 | `url_title` | text | Title search link (always blank) | Yes (blank) | Yes | PUBLIC |
| 45 | `url_streetview` | text | Street View override (rarely populated; fallback constructed client-side) | Yes | No (feeds a derived link) | PUBLIC |
| 46 | `url_zillow` | text | Zillow override (rarely populated; fallback constructed client-side) | Yes | No (feeds a derived link) | PUBLIC |
| 47 | `gone_since` | timestamptz | When a listing left `active` | Yes (`goneExpired()`) | No | INTERNAL-BUT-NOT-SENSITIVE (operational timestamp) |
| 48 | `updated_at` | timestamptz | Last upsert time | Yes (freshness banner) | No | INTERNAL-BUT-NOT-SENSITIVE |

All 48 are NULL-permissive where the source doesn't populate them (Phase 13 §9's null-semantics contract, unchanged, not re-litigated this phase). No field on this list was invented — every row was read directly from 005's actual SQL text and cross-checked against `public/app.js`'s real usage (Section 4).

### 2.3 Excluded fields (explicitly verified absent from `get_properties()`)

`ledger_type`, `fdor_enriched_at`, `outcome`, `sold_price` are **not** in the 48-column list above. Verified three independent ways this phase: (1) `tests/python/test_phase15_customer_surface_security_audit.py`'s `test_B_005_output_reconciles_with_phase13_baseline_exclusions` parses 005's actual `RETURNS TABLE` text and asserts all four are absent (and `harvester_source` present); (2) live production: `select fdor_enriched_at from public.properties` as `authenticated` fails with `permission denied for table properties`; `outcome`/`sold_price` are not live columns at all (`information_schema.columns` has no such names — confirmed Phase 14C/14D, unchanged); (3) `app.js` never reads `p.ledger_type` or `p.fdor_enriched_at` as a value anywhere (only inside the migration-filename string `003_ledger_type_and_state_isolation.sql`, in comments/warnings).

### 2.4 The accepted exception: `ledger_type`

Unchanged from Phase 14E/14H, re-verified live this phase: `ledger_type` is granted to `authenticated` at the column level (the 49th grant, alongside the 48 in Section 2.2) because `get_properties()` reads it internally in its own `WHERE` clause under `SECURITY INVOKER`, but the function's `RETURNS TABLE` clause never includes it in the output. Confirmed not used by customer UI (zero `p.ledger_type` reads in `app.js`), not in the CSV (confirmed by `test_phase15...py`'s `test_B_csv_never_reads_ledger_type_or_fdor_enriched_at_directly`), not exposed by `get_properties()`'s output. This phase did not attempt to close it (explicitly out of scope, same as Phase 14H).

## 3. Frontend contract audit

Full trace of `public/app.js` (3,782 lines, read in full) confirms:

- **The RPC call**: `fetchProperties()` calls `sb.rpc("get_properties", { p_state: PAGE_STATE })` as its sole primary path (`app.js:1262`). `PAGE_STATE` is set once at load from `document.body.dataset.state` (`"FL"` or `"TX"` per page), never user-controllable via any input field.
- **The fallback**: `sb.from("properties").select("*")` (`app.js:1268`) fires **only** when the RPC error is `PGRST202` or matches `/could not find the function|does not exist/i` — i.e., only if `get_properties()` itself were ever dropped from the schema. A normal permission-denied or RLS-driven error is returned as-is to the caller and does **not** trigger this fallback. This is the only `select("*")` against `properties` anywhere in the shipped codebase.
- **Zero rows / errors**: `loadAll()` shows `"Error: " + props.error.message` and stops if `get_properties()` errors for a reason other than "missing function"; zero rows renders the normal empty-ledger UI, not an error state.
- **Anonymous access**: traced the full call chain from page load — `sb.auth.getSession()` → `checkApprovalAndEnter(session)` (requires `session.user`) → `showApp()` → `loadAll()` → `fetchProperties()`. No code path reaches `loadAll()`/`fetchProperties()` without a real, signed-in Supabase Auth session. **Confirmed live this phase**: calling `get_properties()` as `anon` now fails outright (`permission denied for table properties`, since `anon` holds zero column grants) rather than returning an empty array — a stricter, fail-loud behavior for a hypothetical unauthenticated/malicious caller, and a verified non-regression for the real app, since no legitimate code path is `anon` when this call happens.
- **A pre-existing, unrelated fail-open** (not introduced by 005/005a, not fixed this phase — out of scope, named for completeness): if the `profiles` lookup inside `checkApprovalAndEnter()` itself errors for any reason (not just "table missing"), the code falls back to `showApp()` without confirming `approved: true`. This is unchanged from before Phase 14, and its blast radius is now smaller than before 005/005a (an authenticated-but-unapproved session that reaches this path is now scoped to the 48-column customer-safe RPC output instead of a full table `select *`).
- **No frontend code depends on `ledger_type`.** No frontend code reads restricted internal metadata. Browser devtools network responses for the RPC call were confirmed (via live role-simulation, Section 6) to exclude `ledger_type`/`fdor_enriched_at` from the function's actual output.
- **Deployment drift (a real finding, not a security issue)**: the root-level `app.js` — the file Cloudflare Pages actually deploys, per CLAUDE.md — is currently **5+ days stale** relative to `public/app.js` (mtimes: root 2026-09-09, `public/` 2026-09-14). The auto-sync mirror bot has evidently not run since `public/app.js`'s Phase 14A `assessedSourceLabel()`/`harvester_source` CSV column and corrected Texas-harvesting copy landed. The security-relevant query surface itself (the `get_properties` RPC call, its argument, the fallback logic) is byte-identical between the two copies — this drift affects only a cosmetic labeling feature and some UI copy, not the customer data boundary. Not fixed this phase (re-running the mirror-sync workflow is outside a read-only audit's scope and isn't this phase's job) — flagged in Section 17 as a finding for a future phase.

## 4. CSV export audit

The export (`app.js:2938-3017`) is a genuine, literal, explicit 41-entry `[header, accessor]` array — not `Object.keys(row)`, not a spread of the row object. Full list read directly from the file (reproduced in Section 2.2's "CSV" column). `id` and `updated_at` are not exported. Neither `ledger_type` nor `fdor_enriched_at` appears anywhere in the array (verified by `test_B_csv_never_reads_ledger_type_or_fdor_enriched_at_directly`). `outcome`/`sold_price` are not in the CSV either (they're read defensively elsewhere in the file, for card rendering only, never in the export).

**New this phase**: `tests/python/test_phase15_customer_surface_security_audit.py`'s Group B reconciles every direct `p.<field>` read inside the CSV array against 005's actual 48-column output — every one is a real, live column (`test_B_every_direct_csv_column_read_is_in_005s_customer_safe_output`, passing). This closes a gap no prior phase's tests covered: earlier tests checked individual exclusions (`id`, `updated_at`, `ledger_type`) but never reconciled the CSV's full field list against the RPC's actual output set in one pass.

## 5. Raw Supabase REST/API audit

Live-verified this phase via direct role simulation against the production database (not simulated locally, not assumed from the SQL files):

**Anonymous:**
- `set local role anon; select 1 from public.properties limit 1;` → `permission denied for table properties`. Confirmed: `anon` cannot read `properties` at all, any column, any row.
- `set local role anon; select count(*) from public.get_properties('FL', null, null, 5, 0);` → `permission denied for table properties`. Confirmed: the RPC path is equally closed for `anon`, even though EXECUTE is still granted (SECURITY INVOKER means the function's internal column reads are checked against the caller's own privileges, and `anon` has none).
- No alternate endpoint (`send-digest` is unreachable — zero Edge Functions deployed, confirmed live via `list_edge_functions`) provides property rows anonymously.

**Authenticated:**
- `information_schema.role_column_grants` for `authenticated`/`SELECT` on `properties`: exactly 49 columns — the 48 in Section 2.2 plus `ledger_type`. Live-counted this phase, not assumed.
- `set local role authenticated; select fdor_enriched_at from public.properties limit 1;` → `permission denied for table properties`. Confirmed: excluded fields cannot be retrieved through direct table access, by column name, under any query shape (a bare `select fdor_enriched_at`, not just `select *`, still fails — ruling out an "only `*` is blocked" gap).
- `set local role authenticated; select ledger_type from public.properties limit 1;` → no permission error (0 rows, RLS-filtered since no real approved session was simulated) — confirms the one accepted exception behaves exactly as documented.
- `select *` against `properties` as a role with a narrowed column grant is a Postgres-level all-or-nothing check (asterisk expansion requires privilege on every column) — it does not silently return a partial row; it either succeeds with exactly the granted columns (PostgREST's own `select=*` behavior, per 005a's file comments) or fails outright at the raw-SQL level. No exploitable half-open state was found.
- Relationship/embed expansion: `public.properties` has no foreign-key relationships that PostgREST could expand into a related table (no FK columns reference it from another table in this schema), so there is no relationship-expansion bypass vector to test.
- Filters/order/range (`?select=...&order=...&limit=...`) operate after the column-privilege check, not before — a column-level GRANT is enforced by Postgres itself at the access-control layer, beneath PostgREST's query-building, so no query-string trick can request a column the role wasn't granted.

No exploitative activity was performed against production; every check above was a plain `SELECT`/`RPC` call under `set local role`, non-destructive and immediately rolled back (`begin`/`commit` with no writes).

## 6. RPC contract audit

Live `pg_get_functiondef()` for `public.get_properties`, re-pulled this phase:

- Name: `get_properties`. Arguments: `p_state text, p_ledger_type text default null, p_status text default null, p_limit int default 20000, p_offset int default 0` — byte-identical to the original `003_ledger_type_and_state_isolation.sql` signature (confirmed by `test_10_app_js_rpc_call_remains_compatible...` in `test_phase14e_function_contract_correction.py`, still passing), so `app.js`'s existing `sb.rpc("get_properties", {p_state: PAGE_STATE})` call needed no change.
- Return type: `RETURNS TABLE(...)` with the exact 48 named columns from Section 2.2, in the declared order.
- `LANGUAGE sql`, `STABLE`, no `SECURITY DEFINER` printed (i.e., default `SECURITY INVOKER`, unchanged).
- `EXECUTE` held by `service_role`, `authenticated`, `anon`, `postgres`, `PUBLIC` — the full live role set, not narrowed (re-confirmed this phase).
- Live-tested this phase: FL rows (`get_properties('FL', ...)` → 3,493 rows), TX rows (436 rows, `harvester_source: "tx_realauction"` present on a real row), Leon County FL (45 rows via `county = 'Leon'` filter on the FL result set) — all from Phase 14H's own live queries, re-confirmed unchanged this phase since no write has occurred to `properties` or the function since Phase 14H. Pagination (`p_limit`/`p_offset`) and filtering (`p_ledger_type`/`p_status`) are unchanged from the function body itself, not independently re-run this phase (no code or grant change since Phase 14H that could affect them).
- Empty-result behavior: a `p_state` value matching no rows (or a heavily-filtered query) returns an empty array, not an error — confirmed by the function's plain `SELECT ... WHERE ...` body having no `RAISE`/error path.

005 did not silently change any behavior beyond the intended column narrowing — confirmed by `test_005_output_column_set_unchanged_from_phase_14d_by_this_correction` (existing, still passing) and this phase's own `test_B_005_output_reconciles_with_phase13_baseline_exclusions`.

## 7. Governance enforcement audit

Full trace of `harvesters/governance/{registry,gate,restrictions,provenance}.py` and `scripts/sync-texas-to-supabase.py` (delegated to a sub-agent this phase, findings verified against the same repo files, not taken on faith):

- `check_ingestion_gate()` allows a row only if `legal_status ∈ {APPROVED, APPROVED_WITH_RESTRICTIONS}`; every other status (`LEGAL_REVIEW_REQUIRED`, `BLOCKED`, `DISABLED`, `TERMS_CHANGED`), an unregistered `source_id`, or an empty/`None` `source_id` is rejected and forced to `LEGAL_REVIEW_REQUIRED` where the source itself isn't known — fail-closed throughout (the gate's own module docstring states this and the code matches it).
- Enforced at **two independent points** before a row can reach `public.properties`: (1) `texas_harvester.py`'s `main()` gates which harvester functions even run — a `BLOCKED` source's harvest function is never called (and, for `tx_pbfcm`/`tx_govease`/`tx_mvba`/`tx_ctsa`/`tx_hctax`, no working harvest function exists at all — they are stubs or entirely absent from the `SOURCES` dict); (2) `sync-texas-to-supabase.py`'s per-row loop re-runs `check_ingestion_gate()` and `project_row_for_customer_output()` independently, `continue`-ing past any row that fails either, before that row can ever enter the `deduped` dict the upsert payload is built from. There is no third path in this file that reaches the Supabase upsert.
- Empirically verified, not just traced: `test_G_integration_sync_script_never_builds_provenance_for_ungated_rows` runs the actual, unmodified `sync-texas-to-supabase.py` against a 3-row mixed fixture (`tx_lgbs`/`tx_pbfcm`/`tx_hctax`) with only the network call stubbed, and asserts only the approved row's `case_no` reaches the (stubbed) POST body.
- Florida's `.ps1` pipeline has genuinely zero coupling to `harvesters.governance` — independently re-confirmed this phase via a live `grep -rniE "governance|check_ingestion_gate|python|harvesters\." scripts/*.ps1`, not just cited from prior phases' claims.
- **Named residual gap (not a bypass of the intended pipeline, but a real architectural boundary worth stating plainly)**: the governance framework is enforced entirely by `sync-texas-to-supabase.py`'s own Python control flow at write time. Nothing in this layer is a database-level constraint — a different script using the same `service_role` key could POST directly to `/rest/v1/properties` without ever importing `harvesters.governance`. This is the same class of gap the 005/005a database-layer migrations closed for `authenticated`/`anon` reads, but it has no equivalent on the write side for `service_role`. This is not new to this phase (it is inherent to how the governance module was designed — a write-time code library, not a database policy) and is explicitly out of scope to fix here (RLS/grant changes for `service_role` were never proposed by any prior phase and are not proposed now) — recorded as a finding for a future, separately-scoped phase to consider, not a defect in what Phase 14 closed.

## 8. Provenance audit

Confirmed (same sub-agent trace, verified against the real files): `Provenance` objects are constructed by `build_row_provenance()` purely for an in-process assertion (`row_provenance.restrictions == gate_decision.restrictions`) and an audit-log counter printed to stderr — never inserted into the row dict that becomes the Supabase upsert body, never written to `out/harvest_texas.json` (which only serializes `TexasSaleRow` objects, which have no provenance field), and never sent over any network call. This matches `test_F_projected_row_remains_plain_json_serializable_with_no_provenance_object_inside` and `test_E_provenance_metadata_never_leaks_into_the_projected_row` (both pre-existing, both still passing). The provenance model is **ephemeral/audit-only today** — ephemeral in the sense that nothing survives past the sync script's own process (Phase 13 §25 already names "database-level provenance" as a future, unbuilt option; this phase confirms that characterization is still accurate and does not redesign it).

## 9. Authentication state test matrix

| Surface | Anonymous | Authenticated | Result |
|---|---|---|---|
| `get_properties()` | `permission denied for table properties` (live-verified) | Returns the 48-column shape; `ledger_type` internal read works, `fdor_enriched_at` inaccessible | PASS |
| Direct `properties` REST | No SELECT grant at all (live-verified) | 49-column grant (48 + `ledger_type`), verified live | PASS |
| CSV export | N/A (never reached — no session) | 41-column allowlist, reconciled against the 48-column RPC output | PASS |
| Frontend property listing | Cannot reach `loadAll()`/`fetchProperties()` at all (traced call chain) | Full ledger listing, RPC-sourced | PASS |
| `fdor_enriched_at` | Inaccessible (no grant of any kind) | Inaccessible (explicit column exclusion, live-verified) | PASS |
| `ledger_type` | Inaccessible (no grant) | Readable directly (accepted exception); never in RPC output, CSV, or UI | PASS (documented exception, not a failure) |
| Alternate/fallback query | `.select("*")` fallback fires only if the RPC is missing from the schema, not on a permission error; no other alternate path exists | Same | PASS |

## 10. Frontend regression — a real bug found and fixed

`tests/vendor/supabase-stub.js` (the mocked Supabase client `tests/run_test.mjs`'s Playwright suite runs against) had **no `rpc()` method at all**, even though `app.js`'s `fetchProperties()` has called `sb.rpc("get_properties", {p_state})` unconditionally as its primary path since `003_ledger_type_and_state_isolation.sql` (2026-09-08) — six days before this phase. Every migration in this project's history (003, 005, 005a) has cited this Playwright suite in its own TEST PLAN section as the way to verify frontend behavior after a database change, but the suite has been silently unable to exercise the real property-loading path at all since the RPC was introduced.

**Live-reproduced, not just inferred from file mtimes**: built the suite's exact CI serve setup locally (Chromium via the sandbox's pre-installed Playwright browser, `python3 -m http.server` serving a throwaway copy of `public/`), and ran it twice:

- **Before the fix** (original stub): the suite hangs and times out after 30 seconds waiting for `.county-group` to render — no property data ever loads, because `sb.rpc` is `undefined` and calling it throws inside `fetchProperties()`'s async body.
- **After the fix** (added an `rpc()` method to the stub, handling `get_properties` specifically and falling back to a `PGRST202` error shape for any other function name): the suite runs to completion and reports exactly 2 mismatches, both pre-existing and unrelated to this phase's scope — a page-title branding string ("FL Tax Deed Watchlist" vs. the app's actual current title "Tax Acquisitions — Florida") and a CSV filename pattern (`taxdeed-auction-...` expected vs. actual `taxdeed-fl-auction-...`). Neither involves `ledger_type`, `fdor_enriched_at`, or any customer-data-boundary concern — both are stale copy/branding assertions from before an unrelated product rename, and are left as-is (fixing them is unrelated cleanup, out of this phase's scope, and does not affect the security conclusion this audit exists to reach).

**Fixed**: `tests/vendor/supabase-stub.js` now implements `rpc(fnName, args)`, returning the fixture property set for `get_properties` (matching the exact same fixture rows the old `select("*")`-based mock already returned, so all ~100 pre-existing DOM assertions this suite makes are unaffected) and a PostgREST-shaped `PGRST202` error for any other function name.

**New regression guards** (`tests/python/test_phase15_customer_surface_security_audit.py`, Group A): four tests pin this fix in place — the stub must expose an `rpc` method, must handle `get_properties` by name (not a blind passthrough), must fall back to a `PGRST202` shape for unknown names, and `app.js` must still call `get_properties` as documented (making the dependency between the two files explicit).

This is the strongest evidence in this document that the frontend genuinely works against the post-005/005a database shape: a real browser, running the real `app.js`, calling the real RPC-call code path (mocked at the network boundary only), rendered real property cards, real filters, and a real CSV export with no crash and no customer-boundary-relevant mismatch.

## 11. Frontend regression tests added

`tests/python/test_phase15_customer_surface_security_audit.py`, 8 tests (Group A: 4 tests guarding the stub fix; Group B: 4 tests reconciling the CSV export's field reads against 005's live 48-column output, verifying `ledger_type`/`fdor_enriched_at` absence specifically within the CSV array, checking the helper-function allowlist stays accurate, and cross-checking `outcome`/`sold_price`/`ledger_type`/`fdor_enriched_at` absence plus `harvester_source` presence against 005's actual columns). All 8 pass. Total suite: 170/170 (was 162/162 at the start of this phase).

The Playwright suite itself (`tests/run_test.mjs`) was run live twice this phase (Section 10) rather than added to as a new file — its ~100 existing DOM assertions already cover ledger switching, filtering, sorting, the CSV download, the admin panel, favorites/hide/bid-list actions, and the detail modal; the fix that mattered was making it able to run at all against the current RPC-based architecture, not adding new assertions to it.

## 12. Data-leak pattern search (repository-wide)

| Pattern | Result |
|---|---|
| `select("*")` / `select('*')` against `properties` | Exactly one occurrence, `app.js`'s documented fallback (Section 3) — customer-visible, classified potentially-unsafe-if-ever-triggered but gated to only fire on a missing function, not a permission error |
| `.from("properties")` | Same single occurrence — no second reference anywhere in shipped JS |
| Object-spread of a Supabase row (`...row`, `...p`, `...data`) | Zero matches anywhere in the repo |
| `JSON.stringify(` | Two occurrences, both `localStorage.setItem` for the client-side bid/profit calculator's own scratch state — never sent anywhere, safe |
| `console.log(` | Zero occurrences in any shipped file (only in test-only `tests/run_test.mjs`) |
| Literal `properties.*` wildcard string | Zero matches |
| Admin/debug endpoint without explicit projection | None found — `refreshAdminApprovals()` explicitly selects `id,email,requested_at` from `profiles`, not `properties`, and is gated behind `IS_ADMIN` |

No new pattern beyond what Section 3/4 already covers.

## 13. Frontend bundle check

Confirmed via direct diff: the deployed root-level `app.js` (Section 3's deployment-drift finding) does not contain any *value* of `fdor_enriched_at`, `ledger_type`, governance objects, source-registry metadata, or legal-review statuses — it never queries them in the first place (same RPC call, same fallback, unchanged between root and `public/` copies). Field *names* referenced in code (e.g., the string `"ledger_type"` inside a migration-filename comment) are not customer data exposure — no live value ever accompanies them. `explore.js` (also mirrored, byte-identical root vs. `public/`) makes no Supabase calls at all.

## 14. Data contract / UI consistency reconciliation

| Field category | DB customer RPC (005) | Direct authenticated REST (005a) | Frontend | CSV | Governance projection | Status |
|---|---|---|---|---|---|---|
| 47 PUBLIC/DERIVED/PERSONAL fields (Section 2.2, all but `id`) | Present | Present | Present (rendered where a UI element exists) | Present (41 of them — some feed derived-only CSV columns instead of a raw value) | Not applicable (FL has no governance coupling; the 3 registered FL sources are all APPROVED/unrestricted) | Intentional |
| `id` | Present | Present | Used for joins only, never rendered | Absent | N/A | Intentional (internal-but-harmless) |
| `harvester_source` | Present | Present | Present (`assessedSourceLabel`) | Present (derived column) | N/A | Intentional |
| `gone_since`, `updated_at` | Present | Present | Present (used for computed banners, never as raw values) | Absent | N/A | Intentional |
| `ledger_type` | **Absent** | Present (documented exception) | Absent | Absent | N/A | Limitation (accepted, Section 2.4) |
| `fdor_enriched_at` | Absent | Absent | Absent | Absent | N/A | Intentional (fully closed) |
| `outcome`, `sold_price` | Absent (not live columns) | Absent (not live columns) | Present (defensive, always-null reads) | Absent | N/A | Intentional (Phase 13's documented forward-looking gap, unchanged) |

No unexplained customer-visible field was found — every field either appears in the "intentional" bucket with a traced reason, or is the single named `ledger_type` limitation.

## 15. Florida / Texas regression

Not altered this phase (no harvester, sync script, or governance file was modified — only `tests/vendor/supabase-stub.js` and new/updated documentation and tests). Verified via Phase 14H's live queries (unchanged since, as no write has occurred to `properties`, `get_properties()`, or its grants since that phase): FL auction/certificate/LAFT rows (`source` values confirmed present in the live dataset via the 3,493-row FL count), TX LGBS/RealAuction rows (436-row TX count, `harvester_source` populated), identical county names across states handled correctly by the `(state, source, county, case_no)` identity key (unchanged, migration 004, not touched), Leon County FL isolated correctly (45 rows) from any TX county sharing the name. Customer projection does not hide any TX-required field (`min_bid`, `legal_desc`, `harvester_source` all present in 005's output) nor expose an FL-only internal field to TX rows (both states go through the identical `get_properties()` projection — there is no per-state column difference in the function).

## 16. No production mutations

Confirmed: this phase performed zero `apply_migration` calls, zero grant/RLS changes, zero workflow dispatches, zero inserts/updates/deletes against production data, zero source-registry changes, zero authentication-configuration changes. Every Supabase Studio interaction this phase was `execute_sql` running a plain `SELECT` (including `set local role ...` simulations, each wrapped in its own implicit transaction with no writes, and each of which either returned rows or raised a permission error — no `INSERT`/`UPDATE`/`DELETE`/`GRANT`/`REVOKE`/`CREATE`/`DROP` statement was ever sent). `mcp__Supabase__list_migrations` confirms no new migration was recorded this phase.

## 17. Findings

| # | Severity | Surface | Evidence | Customer impact | Recommended phase | Blocks readiness? |
|---|---|---|---|---|---|---|
| 1 | Low (test-infrastructure bug, now fixed) | `tests/vendor/supabase-stub.js` | No `rpc()` method; live-reproduced hang/timeout in `tests/run_test.mjs` before the fix | None directly — but the frontend regression gate every migration's TEST PLAN cites had been silently non-functional for 6 days | This phase (fixed) | No — fixed this phase |
| 2 | Cosmetic (documentation only) | Prose across Phase 14B/14D/14H | Actual `RETURNS TABLE` column count is 48, docs said 47 | None — every field that should be there is there | This phase (corrected) | No |
| 3 | Low (deployment hygiene) | Root-level `app.js`/CI mirror-sync | Root `app.js` 5+ days stale vs. `public/app.js`; missing a CSV column and some UI copy, but the security-relevant RPC call is unaffected | Cosmetic only — a customer using the live site today sees a slightly older label/CSV column set than `public/` reflects, not a data-boundary difference | A future ops/deploy-hygiene phase (re-run the mirror-sync workflow) | No |
| 4 | Informational (named, not new) | `service_role` write path | Governance enforcement (Section 7) is Python-control-flow-only, not a database-level constraint on `service_role`; a different script with the same key could bypass it | No current exploit path exists (no such script exists in this repo) — a structural observation for future hardening, not a live gap | A future, separately-scoped write-path hardening phase | No |
| 5 | Informational (pre-existing, unrelated to 005/005a) | `checkApprovalAndEnter()` fail-open | An erroring `profiles` lookup (for any reason) lets an authenticated-but-unapproved session reach `showApp()` | Small — now scoped to the 48-column customer-safe RPC output instead of a full table read, a net reduction in blast radius versus pre-005/005a | Not urgent; a future auth-hardening phase could tighten the error-handling branch | No |

No finding met any Section 20 hard-stop condition.

## 18. Testing standard

Full suite run this phase: `pytest tests/python/ -q` → **170 passed** (162 pre-existing + 8 new Phase 15 tests), 0 failed. This includes every governance test (`test_source_governance.py`), every provenance test (`test_provenance_integration.py`), every customer/API enforcement test (`test_customer_api_enforcement.py`), every production-data-contract test (`test_production_data_contract.py`), and every prior phase's own regression suite (`test_phase14a` through `test_phase14e`). The Playwright frontend suite (`tests/run_test.mjs`) was run live twice (before/after the stub fix, Section 10) — not part of the `pytest` count, but the strongest evidence in this document that the actual browser-rendered frontend matches the actual database boundary. No lint/type-check tooling exists in this repository to run (confirmed: no `package.json`, no configured linter for the vanilla-JS frontend or the Python scripts) — this is a pre-existing repository characteristic, not a gap this phase introduced or is positioned to close.

## 19. Commit

One commit this phase, containing: this document; the `tests/vendor/supabase-stub.js` fix; the new `tests/python/test_phase15_customer_surface_security_audit.py`; short correction notes appended to `docs/phase-14d-migration-reconciliation.md` and `docs/phase-14h-production-retry-success.md`. No unrelated file touched. Not pushed.

## 20. Hard-stop conditions

None triggered. Explicitly checked against each: no anonymous path returns property rows (Section 5, live-verified); no authenticated access to `fdor_enriched_at` (Section 5, live-verified); no alternate frontend/API path bypasses `get_properties()` (Section 3, only the documented, gated fallback exists); the CSV export does not exceed the 48-field contract (Section 4, reconciled by test); no customer UI exposes governance/provenance internals (Section 8/13); no raw `properties` query bypasses the intended projection under any tested query shape (Section 5); no production function/grant/RLS discrepancy was found (Section 1's table, all ✅ except the harmless count label); no FL/TX isolation regression (Section 15); no source-restriction bypass (Section 7, empirically verified via the existing integration test); no production mutation was required to prove any of the above (Section 16); nothing required guessing (the one discrepancy found, Section 1/2, was resolved by direct counting and live querying, not assumption).
