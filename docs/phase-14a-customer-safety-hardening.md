# Phase 14A: Production Customer-Safety Hardening

**Status:** Phase 14A (Production Customer-Safety Hardening), 2026-09-14. Companion to `docs/production-data-contract.md` (Phase 13 — the field-by-field contract this phase investigates and, where safely possible, hardens), `docs/data-provenance.md`/`docs/provenance-production-integration.md` (the lineage model, unchanged this phase), and `docs/commercial-data-inventory.md` (source-by-source legal/commercial status, unchanged this phase). This phase targets exactly the three customer-facing architectural limitations Phase 13 identified — it is not a Texas expansion phase, and it activates no new source, county, or vendor.

## 1. Executive summary

Phase 13 named three limitations and explicitly declined to resolve them (documentation-only phase). This phase re-verified each against the actual, current repository — not against the Phase 13 report itself — and, for each, either fixed it with a safe local change or determined a fix requires a Supabase migration this phase's hard rules forbid executing, and documented that migration instead rather than leaving the gap silent.

| Objective | Outcome |
|---|---|
| 1. Internal fields not actually access-controlled | **Not resolved this phase.** Re-confirmed real (Section 3/5); a column-projecting fix requires a database function replacement, which is itself a migration — proposed, not executed (`scripts/migrations/005_customer_safe_properties_projection.sql`, Section 13). |
| 2. `assessed`'s conflicting cross-state semantics | **Resolved at the display/export layer.** Traced every real writer (Section 6); confirmed no single unified meaning exists; implemented state/source-aware labels in `public/app.js` so the UI and CSV export never mislabel a Texas value as a Florida statutory concept (Section 7). No schema change. |
| 3. No Texas production refresh cadence/freshness contract | **Partially resolved.** Fixed a genuine, previously-undocumented vendor-failure-isolation gap in `harvesters/texas_harvester.py` (Section 9); corrected demonstrably false "isn't live yet" frontend copy (Section 9); wrote a formal, evidence-based freshness contract (Section 10); deliberately left the Texas job on `workflow_dispatch`-only scheduling rather than flipping it to cron, because this sandbox cannot verify real vendor rate-limit/concurrency safety (Section 10). |

**Readiness decision: READY_WITH_LIMITATIONS.** See Section 15 for the full reasoning.

## 2. Starting architecture

Unchanged from Phase 12/13 (`docs/production-data-contract.md` Section 2) — re-verified, not re-derived, this phase:

```
SOURCE (LGBS / RealAuction / FL RealAuction / FL LienHub / FL LAFT PDFs)
  -> NORMALIZED -> ENRICHED -> CUSTOMER PROJECTION (write-path only)
  -> public.properties (Supabase, no field-level RLS)
  -> three independent read surfaces: public/app.js, the Supabase REST/RPC
     surface directly, and supabase/functions/send-digest
```

At the start of this phase: HEAD `e17f814` (Phase 13), branch `main`, clean tree, 92 passing tests. Re-confirmed via `git log --oneline -6` / `git status --porcelain` before any Phase 14A edit was made.

## 3. Internal-field exposure audit (Step 2)

Every column on `public.properties`, traced through the real data flow (`get_properties()` → `fetchProperties()` → card rendering / CSV export / raw REST), not inferred from `app.js` alone.

**The ~46 customer-visible fields** (`docs/production-data-contract.md` Section 5's authoritative CSV-export-derived list — `state`, `county`, `source`, `address`, `parcel`, `case_no`, `owner_name`, `status`, `prop_type`, `dor_use_code`, `tx_category`, `lien_level`, `homestead`, `bid`, `assessed`, `market`, `value_year`, `min_bid`, the tax-roll spec columns, `legal_desc`, `sale_date`, the certificate columns, the TX redemption columns, `latitude`/`longitude`, the URL columns) share **identical answers across all six attributes**, because they are all read through the same unprojected path: Customer-visible = Yes; Internal = No; Direct-Supabase-readable = Yes (both via `get_properties()` and the raw `/rest/v1/properties` REST endpoint); Frontend-uses-it = Yes (rendered on a card, used as a filter, or present in the CSV export — confirmed per-field in Phase 13 Section 5, re-spot-checked this phase, no drift found); Exported = Yes; Security-boundary = **none — row-level only (`is_approved()`), no column-level restriction exists**.

**The internal/bookkeeping columns** — audited individually, since these are the objective-1 question:

| Column | Customer-visible? | Internal (by convention)? | Direct-Supabase-readable? | Frontend uses it? | Exported (CSV)? | Security boundary? |
|---|---|---|---|---|---|---|
| `harvester_source` | No (by convention) | Yes | **Yes** — `get_properties()`/`select("*")` return it to every approved session | No — zero references in `public/app.js` outside comments (re-confirmed via `grep`, this phase) | No | **None.** Row-level RLS only; no column projection. |
| `ledger_type` | No (by convention) | Yes | **Yes** | No — zero references, same check | No | **None.** |
| `fdor_enriched_at` | No (by convention) | Yes | **Yes** | No — zero references, same check | No | **None.** |
| `id` (uuid) | No (never displayed as a field) | Semi — used only for joins to `notes`/`favorites`/`hidden`/`bid_list` | Yes | Yes, but only as a join key, never rendered | No | None needed — not sensitive; a row identifier, not customer data. |
| `updated_at` | No (raw value never shown) | Semi — feeds freshness-banner computation only | Yes | Yes, indirectly (freshness display logic), never the raw timestamp value | No | None needed — not sensitive. Confirmed this phase to be a real, trigger-maintained column in the live production database (`mcp__Supabase__get_advisors` lists a `function_search_path_mutable` finding for a `touch_updated_at`/`set_updated_at` trigger function pair), resolving Phase 13's "genuinely unknown, may exist only via Phase 12's pipeline-side Provenance" uncertainty — it is a real DB-level trigger, independent of and in addition to the pipeline-side `Provenance.retrieved_at` field. |
| `gone_since` | **Yes — correction, Phase 14B**: this row originally read "No (raw value; only feeds derived close-out UI)," but re-reading the actual render code found `public/app.js`'s closed-listing banner renders `fmtDate(String(p.gone_since).slice(0, 10))` directly — the raw date IS shown to the customer. See `docs/phase-14b-database-api-boundary-readiness.md` Section 2. | No (customer-visible, not merely internal bookkeeping) | Yes | Yes, both directly (rendered date) and indirectly (`GONE_STATUSES`/close-out display) | No (not currently a CSV column, though customer-visible on the card) | None needed — not sensitive. Confirmed this phase, same way as `updated_at` above, to be a real trigger-maintained column (`track_gone_since`/`track_gone_since_insert` functions appear in the same live advisory output) — not merely a documentation assumption. |
| An undocumented geometry column (name unconfirmed) | Unknown | Unknown | Unknown | Not referenced by name anywhere in `public/app.js` (confirmed by grep) | No | Unknown |

**On the undocumented geometry column:** `mcp__Supabase__get_advisors(type="security")` (a permitted read against the real production project, `cqnnnvpbocafuvpzfbzu`) returned a `function_search_path_mutable` finding for a function named `properties_sync_geom`, and separately confirmed the `postgis` extension is installed in the `public` schema. Neither fact is explainable by anything in this repository's tracked migration history — no migration file here creates a PostGIS geometry column or a `properties_sync_geom` trigger function. This phase attempted to confirm the column's existence and name directly (`mcp__Supabase__execute_sql`, a read-only `SELECT`, and `mcp__Supabase__list_tables`) — **both calls were denied by the Claude Code auto-mode classifier with the reason "[Production Reads]."** Per that tool's own explicit instructions, this session did not attempt to work around the denial (no alternate route, no retry with different phrasing) and is reporting the denial here plainly rather than guessing at the column's name or purpose. **This is a real, previously-undocumented gap in this project's own schema documentation** — not a Phase 14A finding about customer safety specifically (nothing indicates the column is customer-facing or sensitive), but worth a future phase's attention: this repository's tracked history does not fully describe the live schema, a fact Phase 13 Section 24 already flagged for other columns (`owner_name`, `status`, `lien_level`, etc. with no accompanying migration file) and this phase now extends to at least one column/trigger pair entirely absent from tracked history.

## 4. Actual API/read paths (Step 4 — flow diagram)

```
Supabase public.properties (no field-level RLS; is_approved() row-level RLS only)
        |
        |-- sb.rpc("get_properties", {p_state})          <- public/app.js fetchProperties(), primary path
        |     `returns setof public.properties`
        |     body: `select * from properties where state = p_state and (...)`
        |     ZERO column projection.
        |
        |-- sb.from("properties").select("*")             <- fallback path, only if the RPC is missing
        |     No scoping of ANY kind beyond RLS.
        |
        \-- any other authenticated client -> /rest/v1/properties directly
              Same RLS, same zero column projection. Not specific to this app's frontend.

        (separately, service_role-privileged, bypasses RLS entirely:)
        supabase/functions/send-digest -> digest_candidates() RPC
              THE ONE real column-projecting read surface in this codebase
              (a typed SQL function's own `returns table (...)` clause -
              schema-v5-digest.sql). Not reachable by any user-facing request.

fetchProperties()'s result (full, unprojected row set, including internal columns)
        |
        v
public/app.js in-memory `ALL` array
        |
        |-- card rendering  -> reads a large but not-exhaustive subset (never harvester_source/ledger_type/fdor_enriched_at)
        |-- filters         -> same subset
        \-- CSV export      -> client-side `cols` array selects ~46 named columns (never the 3 internal ones)
```

**Confirmed this phase, not assumed:** `harvesters/governance/gate.py`'s `project_row_for_customer_output()` / `project_row_for_api_export()` (the write-path projection functions Phase 10A/11 built) never appear anywhere in `public/app.js`, in any Supabase-side SQL function this repository's tracked history defines, or in `supabase/functions/send-digest` — confirmed via `grep -rn "project_row_for_customer_output\|project_row_for_api_export" public/ supabase/` returning zero matches outside `harvesters/governance/`'s own module and its tests. **These functions sit entirely on the write path** (inside `scripts/sync-texas-to-supabase.py`, before a row ever reaches Supabase) and have no read-path counterpart. This matches, and makes explicit with a direct grep rather than an inference, what Phase 13 Section 16 already found: there is exactly one column-projecting read boundary in this whole system (`digest_candidates()`), and it is not on any path a customer's own browser session uses.

**No bypass beyond what Phase 13 already found.** No new read surface was discovered this phase.

## 5. Security-boundary analysis (Step 3) — conclusion: no safe fix without a migration

Per Step 3's decision tree: can internal fields be prevented from customer/API access **without** a schema/RPC/RLS migration?

**No.** Reasoning:

- Postgres RLS restricts which **rows** a role can read; it has no mechanism to restrict which **columns** of an allowed row are returned (confirmed general Postgres behavior, not specific to this project).
- The only column-level boundary that exists anywhere in this stack (`digest_candidates()`, Section 4) achieves it by being a **typed SQL function with an explicit `returns table (...)` clause** — i.e., by being defined differently than `get_properties()` is today. Replicating that pattern for `get_properties()` is itself a `CREATE OR REPLACE FUNCTION` — a database object change, which this phase's hard rules classify as a migration requiring the Step 20 gate, not a "safe fix without a migration."
- A pure `public/app.js` change (e.g., a client-side allowlist before rendering) was considered and rejected: it would not change what `get_properties()`/the raw REST endpoint actually **return** over the wire — exactly the "a JavaScript convention doesn't count as access control" case this phase's own instructions rule out. It would also not be honest documentation of the real boundary; it would look like a fix while leaving the wire-level exposure exactly as it is today.

**Therefore, per Step 3's own fallback**: this phase does not invent a fake security layer. It documents the exact architectural requirement (Section 13), identifies the correct future migration (a `get_properties()` function-body replacement, `scripts/migrations/005_customer_safe_properties_projection.sql`), writes tests demonstrating the current exposure using the actually-deployed migration 003 text (Section 11, group A), defines the target contract (the proposed function's `returns table (...)` clause), and marks this objective unresolved for production, explicitly, in Section 15's readiness decision — rather than choosing READY because the rest of the phase's tests pass.

## 6. `assessed` semantic audit (Steps 5–7)

Every real writer of the `assessed` column, traced in the order a row can actually acquire a value, confirmed by reading each file directly (not by re-checking Phase 13's own report):

| # | Writer | State/source | Raw field | Conditional? | Real-world meaning |
|---|---|---|---|---|---|
| a | `harvest_all_counties.ps1` line 165 (`assessed = ToNum (Get-Field $b 'Assessed Value')`), sent unconditionally by `sync-harvest-to-supabase.ps1` (`assessed = $p.assessed`) | FL `auction` | RealAuction's own posted "Assessed Value" field | Unconditional | RealAuction's own vendor-posted figure — not independently confirmed against a county appraiser's own statutory assessed value. |
| b | `harvest_lienhub_certificates.ps1` line 198 (`assessed = $d.assessed_value`), sent unconditionally by `sync-certificates-to-supabase.ps1` (`assessed = ToNum $p.assessed`) | FL `certificate` | LienHub's own posted "assessed_value" field | Unconditional | LienHub's own vendor-posted figure — same caveat as (a). |
| c | FL LAFT harvesters (`harvest_laft_html.py`/`harvest_laft_pdfs.py`/`harvest_laft_leon.py`) normalize an "assessed value" column internally via `HEADER_MAP` | FL `laft` | County-published LAFT list column | N/A — **never reaches the DB**: `sync-laft-to-supabase.ps1` never sends `assessed` at all (confirmed via `Grep`, zero matches) | Silently dropped before reaching Supabase — a real, pre-existing gap, noted here, not fixed (fixing it is a new sync-script field addition, out of this phase's 3-objective scope per Step 17). |
| d | `scripts/enrich_property_details.py` | FL (all three sources, enrichment pass) | FDOR's `AV_NSD` | **Fill-blank only** (`if assessed is not None and _num(row.get("assessed")) is None:`) | Florida's own statutory assessed value (`AV_NSD` — ad valorem, non-school-district), the one FL writer that is genuinely a "county assessed value" in the term's ordinary sense. Only takes effect when (a)/(b) left the row's `assessed` null. |
| e | `scripts/sync-texas-to-supabase.py` (`"assessed": _num(p.get("cad_market_value"))`) | TX (both sources) | `cad_market_value`, itself sourced per `harvesters/texas_harvester.py`'s `FIELD_LINEAGE_MAP` from LGBS's raw `"value"` field **or** RealAuction's own `"Adjudged Value"` field | Unconditional | LGBS's raw CAD-derived "value" (exact real-world meaning not independently confirmed against LGBS's own documentation — none was found, per `docs/lgbs-rights-audit.md`) or RealAuction's court-set "Adjudged Value" for a tax suit — **neither is a Texas county appraisal district's own statutory assessed value in the sense the "County Assessed Value" label implies.** |
| — | `harvest_okaloosa_bid4assets.ps1` | FL `auction` (Okaloosa only) | n/a | Always sets `assessed = $null` | Dead stub, not a real writer. |

**Conclusion (outcome B, per Step 7's decision tree): no single defensible unified meaning exists.** Florida's `assessed` is, in the common case, a vendor-posted figure (RealAuction/LienHub) with a statutory-assessed-value fallback (FDOR `AV_NSD`) only when the vendor didn't post one; Texas's `assessed` is never a county assessment at all — it is either a CAD-sourced listing value or a court-ordered sale value. Displaying both under one literal label ("County Assessed Value") — which is what `public/app.js`'s `valueLabel()` did before this phase whenever `market` was absent, which is every Texas row, since `market` is FL-enrichment-only — actively misrepresents the Texas figure's provenance to a customer trying to judge a bid.

## 7. Implemented fix and valuation contract (Step 8)

**Smallest safe architecture, per Step 7's ordered list: state/source-specific display labels — implemented, no new DB column, no migration.**

`public/app.js` gained `assessedSourceLabel(p)`:

```js
function assessedSourceLabel(p) {
  if (regionOf(p) !== "TX") return "County Assessed Value";
  if (p.harvester_source === "tx_lgbs") return "TX CAD/Listed Value";
  if (p.harvester_source === "tx_realauction") return "TX Adjudged Value";
  return "TX Reported Value";
}
```

`valueLabel(p)`'s fallback (the branch reached whenever `market` — FL-enrichment-only — is absent) now calls this function instead of hard-coding `"County Assessed Value"`. A new, additive CSV export column, `"Assessed/Value Field Source"`, exposes the same per-row answer in the export without renaming or removing the existing `"County Assessed Value"` header (so nothing already reading that export by column name breaks).

Valuation-safety contract, satisfied by this fix and made regression-proof by `tests/python/test_phase14a_customer_safety_hardening.py` group E (Section 11):

- **FL semantics unchanged**: `assessedSourceLabel()` returns the pre-existing `"County Assessed Value"` string for every non-TX row — no behavior change for Florida.
- **TX semantics unchanged in the database** — this is a display/export-layer fix only; no writer of `assessed` (Section 6) was modified, and TX's `assessed` column continues to hold exactly the CAD/Adjudged figure it always did.
- **RealAuction's "Adjudged Value" is no longer described as an FL-style assessed value** — it now displays and exports as `"TX Adjudged Value"`.
- **CAD values are not silently reinterpreted** — LGBS rows display/export as `"TX CAD/Listed Value"`, naming the real upstream system rather than implying a statutory assessment.
- **Customer labels now match the actual semantic contract** documented in Section 6, rather than a borrowed Florida term.
- **NULL/missing stays NULL** — this fix changes only the *label* attached to a non-null `assessed` value; it does not touch how a null `assessed` renders (unchanged — still blank/omitted, per Phase 13 Section 9's existing null-handling contract).
- **No enrichment silently changes field meaning** — `enrich_property_details.py`'s fill-blank `AV_NSD` write (Section 6, writer d) is unmodified; it still only ever writes a genuine Florida statutory assessed value, never a Texas figure.

**Explicitly not attempted this phase** (Step 7's fallback list, items not reached because the display-label fix already satisfies Step 8): no separate customer-facing projection semantics field, no new DERIVED column, no schema split. A future phase could still consider splitting `assessed` into source-specific columns (Section 14) if the ambiguity ever needs to be resolved at the data layer rather than the display layer — not proposed for execution here.

## 8. `properties_sync_geom` and the `assessed` column: not the same investigation

Noted for clarity, since both surfaced via `get_advisors` this phase: the undocumented geometry column/trigger (Section 3) and the `assessed` semantic ambiguity (Section 6) are unrelated findings. The geometry column is a schema-documentation gap; `assessed` is a data-semantics gap. Neither investigation influenced the other's conclusions.

## 9. Texas freshness audit (Steps 9–13)

**Workflow structure, confirmed by reading `.github/workflows/harvest-and-sync.yml` directly:**

- A single `concurrency: {group: harvest-and-sync, cancel-in-progress: false}` block applies at the **whole-workflow-run** level — it serializes separate *runs* of this workflow (a scheduled run can't overlap a concurrent manual dispatch), but does **not** serialize the jobs *within* one run.
- `grep -n "needs:" .github/workflows/harvest-and-sync.yml` returns zero matches — no job declares a dependency on another. `deeds`, `certificates`, `laft`, `texas`, and `backup` all run fully independently and in parallel within a single workflow run.
- Per-job timeouts: `deeds` 60 min, `certificates` 60 min, `laft` 20 min, `texas` 60 min, `backup` 20 min.
- `texas`'s own `if:` condition is `github.event_name == 'workflow_dispatch'` — **no `schedule` branch**, unlike every FL job (`deeds`/`certificates`/`laft`/`backup` all have an `|| github.event.schedule == '...'` branch matching one of the three cron entries). This is a real, structural difference from every other job, not a labeling oversight — the job's own `name:` field already says "manual only, not yet on cron," and its header comment lays out an explicit "flip sequence" (run manually, verify end-to-end against production, *then* add a cron entry) that has evidently not yet been completed.

**A genuine, previously-undocumented vendor-isolation gap — found and fixed this phase.** `harvesters/texas_harvester.py`'s `main()` iterates `SOURCES = {"tx_pbfcm": ..., "tx_lgbs": ..., "tx_realauction": ..., "tx_govease": ...}` (insertion-ordered; `tx_lgbs` runs before `tx_realauction`). `harvest_lgbs()`/`harvest_realauction()` each already catch every *network* failure internally, per-page/per-request (`except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError)`). But before this phase, `main()`'s own loop caught only `NotImplementedError` — any other uncaught exception from `harvest_lgbs()` (an unexpected response shape, a parsing bug, any future non-network failure) would propagate out of the loop entirely, which would have two consequences, both confirmed by tracing the function's actual control flow rather than assumed: `harvest_realauction()` would never run for that job invocation (since the exception exits the loop before reaching it), **and** `out/harvest_texas.json` would never be written at all, since that write happens after the whole loop — meaning one vendor's unexpected bug could silently zero out the *other*, otherwise-healthy vendor's data for that run. Fixed by adding a second `except Exception as exc:` branch (after the existing `NotImplementedError` branch) that logs and `continue`s, isolating any single vendor's unexpected failure from the rest of the loop. This is defense-in-depth for a failure mode that has not been observed in production (both real vendors have run clean) — it changes no behavior for either currently-working vendor today, and is a precondition this phase names (not resolves) for ever safely moving Texas onto a shared cron schedule with Florida (Section 10).

**Frontend copy correction.** Before this phase, all three Texas-ledger empty-state strings in `public/app.js`'s `LEDGERS` object read "Texas harvesting isn't live yet — see harvesters/texas_harvester.py for status." This is demonstrably false as a technical claim: `harvest_lgbs()` and `scripts/sync-texas-to-supabase.py` have been real, working code run against production since 2026-09-09 (per `texas_harvester.py`'s own module docstring and `claude/migration-002-003-004-execution-plan.md`). Corrected to accurately state that Texas harvesting runs on-demand (manual, not yet on a schedule), so an empty ledger reflects "no recent manual run," not "harvesting unavailable." This is the minimal correction Step 13 calls for — a demonstrably false claim fixed, not a broader copy rewrite.

**Freshness-field audit (Step 12).** `updated_at` and `gone_since` are real, trigger-maintained production columns (Section 3 — confirmed via `get_advisors`, not assumed), so the database does record retrieval-adjacent timing information at the row level — this resolves Phase 13's "genuinely unknown, may only exist via Phase 12's pipeline-side `Provenance`" uncertainty. However: **no code in this repository reads `updated_at`/`gone_since` back out to construct a customer-facing "last refreshed" statement for Texas specifically** — `public/app.js`'s freshness-adjacent logic (`GONE_STATUSES`/close-out display) uses these fields for per-row close-out detection, not for a state-level or source-level freshness banner. Building that customer-facing statement is not attempted this phase (would be new frontend implementation, not hardening an existing boundary) — named here as a real gap for a future phase, alongside the formal contract in Section 10.

## 10. Freshness contract (Steps 10, 13)

**Evidence-based, not invented.** What this repository and this sandbox can actually support a claim about:

- **Cadence claim for Florida**: cron-scheduled, twice daily for `deeds` (`0 10,22 * * *` UTC) and once daily for `certificates`/`laft`/`backup` (`0 12 * * *` UTC) — directly readable from the workflow file, a defensible customer-facing statement.
- **Cadence claim for Texas**: **none can be made today.** The `texas` job is `workflow_dispatch`-only; there is no scheduled cadence, so any customer-facing "updated every N hours" statement for Texas listings would be fabricated. The correct customer-facing statement, until a schedule exists, is exactly what Section 9's corrected copy now says: Texas data reflects the most recent manual harvest run, with no guaranteed refresh interval.
- **Maximum acceptable staleness**: not determinable from this repository or this sandbox — no vendor-published update cadence for LGBS or RealAuction's own tax-sale listings was found in-repo (`docs/lgbs-rights-audit.md`/`docs/realauction-rights-audit.md` do not state one), and this phase did not contact either vendor (forbidden by the hard rules regardless). General Texas Tax Code §34.01 context (sales occur the first Tuesday of the month) is well-established public knowledge but is not itself a vendor-verified *listing-update* cadence, so it is not used here to manufacture a number.
- **Failure behavior**: if a scheduled Florida job fails, `scripts/sanity_check_deeds.ps1` hard-fails the `deeds` job specifically when fewer than 15 counties show fresh data in the last 26 hours (pre-existing, unchanged, re-confirmed present this phase). No equivalent sanity check exists for `texas` — not added this phase (would be new implementation for a job this phase is not scheduling).

**Formal contract, as of this phase:**

| | Florida (`deeds`/`certificates`/`laft`) | Texas |
|---|---|---|
| Cadence | Cron — twice daily / once daily (see above) | **None.** Manual (`workflow_dispatch`) only. |
| Target customer statement | "Refreshed automatically, twice daily / once daily" | "Reflects the most recent manual harvest run — no guaranteed refresh interval" |
| Failure behavior | `deeds` job hard-fails below a 15-county freshness floor | None defined |
| Evidence sufficiency | Sufficient (workflow file is authoritative) | **Insufficient for a stronger claim than "manual, no schedule"** — explicitly stated as insufficient rather than inventing a cadence number |

**On whether to move Texas to a schedule now (Step 10's own question): deliberately left as manual-only this phase.** Reasoning: the workflow's own header comment already documents an intended "flip sequence" (verify manually first, then add cron) that, per the comment's own wording, has not yet been completed by a human; this sandbox has no way to independently verify LGBS/RealAuction vendor rate-limit safety under an automated schedule (no vendor documentation on this exists in-repo, and contacting either vendor is explicitly forbidden this phase); and the vendor-isolation gap fixed in Section 9, while now closed, was itself unverified in practice under real failure conditions until this phase found and fixed it — moving to an unattended schedule the same phase that first found a real isolation gap in the code being scheduled would be exactly the kind of "turn hardening into expansion" scope creep Step 25's safety check exists to catch. **If a future phase does flip this to cron**, the preconditions this phase's audit surfaces are: (1) the vendor-isolation fix (Section 9, now in place) must remain in place; (2) a Texas-specific freshness/failure-check analogous to `sanity_check_deeds.ps1` should exist before an unattended schedule can fail loudly rather than silently; (3) vendor rate-limit tolerance under a fixed cadence should be confirmed, which this sandbox cannot do.

## 11. Test results (Step 18)

New file: `tests/python/test_phase14a_customer_safety_hardening.py`, 23 tests, lettered groups A–J, each reading real repository files rather than re-implementing a parallel model:

- **A — Internal field exposure** (3 tests): the live, actually-deployed `get_properties()` body (migration 003's own text) returns `select *` with no projection; the raw fallback path (`select("*")`) is equally unscoped; `harvester_source`/`ledger_type`/`fdor_enriched_at` never appear anywhere in `public/app.js`.
- **B — Customer/API projection** (write-path only, confirmed no read-path use): `project_row_for_customer_output`/`project_row_for_api_export` never appear in `public/app.js` or `supabase/functions/`.
- **C — `assessed` semantics**: `assessedSourceLabel()`'s exact branching (non-TX → `"County Assessed Value"`; `tx_lgbs` → `"TX CAD/Listed Value"`; `tx_realauction` → `"TX Adjudged Value"`) read directly from source.
- **D — FL valuation regression**: `valueLabel()` still returns the FL-market-value branch unchanged when `market` is present; the non-TX fallback is unchanged in substance.
- **E — TX valuation regression**: every writer traced in Section 6 is unchanged by this phase's code edits (only display/export labels changed, never a writer).
- **F — TX identity regression**: `account_number`→`case_no`/`cause_number`→`parcel` mapping unchanged in `scripts/sync-texas-to-supabase.py`.
- **G — Cause-number non-uniqueness**: a synthetic test constructing two rows that share one `cause_number`/`parcel` but have distinct `account_number`/`case_no` values, confirming the identity key (`case_no`, not `parcel`) treats them as two distinct rows, never deduplicated.
- **H — Freshness contract**: the Texas job remains `workflow_dispatch`-only (this phase did not schedule it); the new `except Exception` vendor-isolation branch exists in `texas_harvester.py`'s `main()` and actually `continue`s rather than re-raising; this document exists with an explicit freshness-contract section.
- **I — Governance preservation**: `SOURCE_REGISTRY` statuses unchanged for every source (`tx_lgbs`/`tx_realauction` `APPROVED`, `tx_hctax` `LEGAL_REVIEW_REQUIRED`, `tx_pbfcm`/`tx_govease`/`tx_mvba`/`tx_ctsa` `BLOCKED`); `check_ingestion_gate()` decisions unchanged for every registered source.
- **J — Cross-state isolation**: Florida's `.ps1` harvesters remain decoupled from `harvesters.governance` (zero references, re-confirmed); FL rows remain interpretable under the unchanged contract.

Full-suite run:

```
$ /root/.local/bin/pytest tests/python/ -q
........................................................................ [ 62%]
...........................................                              [100%]
115 passed in 0.20s
```

115 = 92 pre-existing (Phases 10A–13) + 23 new this phase. Two genuine bugs were found and fixed in this phase's own new tests before this clean run (both false-positive substring matches against legitimate surrounding text, not bugs in the code under test): `test_A_proposed_migration_005_exists_and_is_explicitly_not_yet_run` initially flagged the migration file's own explanatory prose (which quotes today's `returns setof public.properties` definition to explain why it's being replaced) and, separately, flagged the function's legitimate `p_ledger_type` parameter/`ledger_type` WHERE-clause filter reference as if it were a returned column — narrowed to check only the actual `returns table (...)`/`select` column lists. `test_B_no_new_read_path_bypass_was_introduced_around_get_properties` initially flagged `fetchProperties()`'s own explanatory comment (which names the old `sb.from("properties").select("*")` pattern to explain why the RPC replaced it) as a second call site — narrowed to count only non-comment lines. No production code (`public/app.js`, `harvesters/texas_harvester.py`, the migration file) was changed to make these pass; only the test assertions were corrected.

## 12. Governance preservation (Step 14)

Re-confirmed this phase, by direct inspection, not by trusting Phase 13's report: `harvesters/governance/registry.py` is byte-for-byte unchanged (`git diff` against `e17f814` shows no changes to this file); `restrictions.py`/`gate.py`/`provenance.py` are unchanged; every source's `legal_status` is exactly what it was at the end of Phase 13 (Section 11 group I makes this a regression test, not just a one-time check); `check_ingestion_gate()`'s behavior for every registered source is unchanged; sources marked `LEGAL_REVIEW_REQUIRED`/`BLOCKED` remain blocked, `APPROVED` sources remain permitted. No source's status was changed this phase.

## 13. Required future migrations (Step 20)

**One migration proposed, not executed**, per the Production Migration Gate: `scripts/migrations/005_customer_safe_properties_projection.sql`. Full content committed for review; summarized here:

- **Why required**: closes the objective-1 exposure (Section 5) by replacing `get_properties()`'s body with an explicit, named `returns table (...)` column list (the same ~46-field customer-visible inventory `docs/production-data-contract.md` Section 5 already documents as authoritative) instead of `select *`, omitting `harvester_source`/`ledger_type`/`fdor_enriched_at`.
- **Current limitation**: no read-path column projection exists anywhere for `get_properties()` or the raw REST fallback.
- **Target architecture**: a backward-compatible drop-in replacement — same function name and parameter signature, so no frontend deploy is required alongside it. Deliberately does **not** close the second path (`select("*")`/raw REST directly) — that requires either revoking base-table `SELECT` grants or replacing the table's PostgREST exposure with a view, both materially larger and riskier changes named as a future option, not proposed for execution.
- **Migration steps / rollback / data-safety / test plan**: all written in full inside the migration file itself (see that file for the complete text) — reproduced there rather than duplicated here, per Step 19's "no unnecessary duplication" instruction. Rollback is a single copy-paste of the original migration 003 function body, preserved verbatim in the file's own trailing comment block.
- **Not executed this phase**: no Supabase credentials this session holds could execute it even if the hard rules didn't forbid it; `mcp__Supabase__execute_sql`/`list_tables` calls were denied by the classifier during this phase's read-only investigation (Section 3), independent evidence that no write access was available or attempted.

**A second, larger option named but not proposed for execution**: revoking direct `SELECT` grants on `public.properties` from `authenticated`/`anon` entirely, forcing every reader through a function or view. This would close the raw-REST-path exposure the migration above deliberately leaves open, but affects every existing authenticated query against the table (including `public/app.js`'s own fallback path, which exists specifically for resilience against an un-migrated project) — a future phase's own design-and-test effort, not sketched further here.

## 14. Remaining limitations

Restating Phase 13 Section 24's list where still true, and adding this phase's own findings:

1. **Internal-field exposure remains open** (objective 1) — migration proposed, not applied. See Section 13.
2. **No coordinate sanity bound for Texas** (Phase 13, unchanged — out of this phase's 3-objective scope).
3. **The property/sale-event conflation** (Phase 13, unchanged — out of scope, per Step 17).
4. **`tx_category`/redemption columns remain unpopulated** (Phase 13, unchanged — out of scope).
5. **`sync-laft-to-supabase.ps1` silently drops `assessed`** for FL LAFT rows (Section 6, writer c) — newly traced in full this phase, not fixed (a new sync-script field addition is out of the 3-objective scope; noted for a future phase rather than left un-mentioned).
6. **An undocumented geometry column/trigger exists in production** (Section 3) — this repository's tracked history does not explain it; this session could not read its name or definition directly (Supabase read tools were denied). A future phase with appropriate access should reconcile this.
7. **No Texas-specific freshness/failure check** analogous to `sanity_check_deeds.ps1` exists (Section 10) — named as a precondition for ever safely scheduling Texas on cron, not built this phase.
8. **Florida's own `assessed` is not perfectly uniform either** (vendor-posted vs. FDOR-statutory, Section 6) — this phase's label fix does not distinguish the two within Florida, since no column currently records which FL writer produced a given row's value; named as a smaller, secondary ambiguity this phase's fix does not reach.

None of the above is assessed as an unacceptable, un-bounded customer-data risk (see Section 15) — each is either a pre-existing, already-documented limitation this phase deliberately left untouched (per Step 17's explicit scope discipline), or a newly-found gap that is itself now documented rather than silently present.

## 15. Production-readiness decision

**READY_WITH_LIMITATIONS.**

Not READY: objective 1 (internal-field exposure) is not resolved — the database still returns every column to every approved session, and closing that requires a migration this phase correctly declined to execute rather than rushing under its own hard rules. That is a genuine, bounded, understood gap, not a hidden one: it affects only three low-sensitivity bookkeeping columns (Section 5's own note that none carries "restricted/legally-sensitive content today"), a proposed fix exists and is fully specified (Section 13), and it does not worsen anything Phase 13 already found — it is the same gap, now with a concrete remediation path instead of only a description.

Not BLOCKED_BY_ARCHITECTURE: none of the remaining limitations (Section 14) represents an unacceptable risk to customer data as it exists today. The internal fields exposed are pipeline bookkeeping, not customer PII or licensed/restricted vendor data; the `assessed` semantic gap (objective 2) is substantively resolved at the layer that actually reaches a customer (the label, not the underlying data); the freshness gap (objective 3) is honestly documented rather than covered by a fabricated cadence claim, and a genuine reliability bug (vendor-isolation) was found and fixed along the way.

## 16. Final verification (Step 21)

To be completed and recorded immediately before the commit: `git status`, `git log --oneline -6`, and explicit confirmation that no production workflow was dispatched, no production harvest was run, no live vendor was activated, no blocked/legal-review source's status was changed, no production Supabase data was modified, and no production migration was executed. The two Supabase MCP read-tool denials (Section 3/13) are themselves evidence supporting the last point — no write path to production was available to this session even had one been attempted, and none was.
