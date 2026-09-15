# Production provenance integration

**Status:** Phase 12 (Production Provenance & Data Lineage Integration), 2026-09-14. Companion to `docs/data-provenance.md` (the lineage model itself — `Provenance`, `PipelineStage`, `FieldClassification`, `advance()`, `derive()`), `docs/data-licensing.md` (restriction enforcement), and `docs/customer-api-data-enforcement.md` (Phase 11's customer/API boundary, which this phase builds directly on top of). No source's `legal_status` or `restrictions` changed this phase — this page is entirely about making an already-existing lineage model real in the production data flow, not about any new permission decision.

## 1. Actual production data flow

Traced directly from the code, not assumed from prior documentation:

```
SOURCE            LGBS's JSON API / RealAuction county HTML — never persisted as a
                   separate artifact (see Section 7)
  ↓
RAW                DOES NOT EXIST as a materialized stage. harvest_lgbs()/
                   harvest_realauction() (harvesters/texas_harvester.py) parse the
                   HTTP response inline, in the same function call that produces a
                   TexasSaleRow — there is no intermediate "raw record" object or
                   file anywhere in this codebase. Documented here rather than
                   inventing a stage that isn't real (Phase 12 Step 2's own
                   instruction).
  ↓
NORMALIZED         TexasSaleRow, exactly as built by harvest_lgbs()/harvest_realauction()
                   — the actual first materialized stage in this pipeline. See
                   FIELD_LINEAGE_MAP (Section 5) for the source-field → normalized-field
                   mapping.
  ↓
ENRICHED           scripts/geocode_properties.py — the ONE real, currently-running
                   enrichment step (confirmed: runs against public.properties with no
                   state filter, so it applies to TX and FL rows alike). Backfills
                   latitude/longitude ONLY where NULL — never overwrites a
                   source-provided value. scripts/enrich_property_details_tx.py
                   (CAD-based valuation enrichment) is a confirmed, documented,
                   non-working draft stub — NOT run by any workflow (see Section 6) —
                   so TX rows receive no CAD-based enrichment in production today.
  ↓
DERIVED            DOES NOT EXIST in server-side/Python code. No derived field
                   (e.g. bid-to-value) is computed before sync — public/app.js
                   computes any such ratio client-side, from fields that already
                   passed the same source's restriction check (see Section 8).
  ↓
SYNC               scripts/sync-texas-to-supabase.py — builds the Supabase upsert
                   row, re-checks the ingestion gate, applies Phase 11's
                   project_row_for_customer_output(), and (Phase 12, new) builds one
                   Provenance record per row reaching this point.
  ↓
public.properties  The single customer-facing table. No field-level RLS (see
                   docs/data-licensing.md) — this table IS the CUSTOMER stage.
  ↓
CUSTOMER/API/EXPORT public/app.js (get_properties() RPC / direct .select()), its CSV
                   export (reads the same already-fetched rows), and
                   supabase/functions/send-digest (service_role RPC) — see
                   docs/customer-api-data-enforcement.md for the full account of why
                   these three surfaces are, in this architecture, effectively one
                   surface.
```

## 2. Existing provenance architecture (unchanged this phase)

`harvesters/governance/provenance.py` — `Provenance` (frozen dataclass), `PipelineStage` (7-value enum), `FieldClassification` (7-value enum), `advance()` (forward-only, restriction-only-additive), `derive()` (unions parent restrictions, preserves lineage), `origin_source_ids()`. None of this module changed this phase — Phase 12 is entirely about calling it from real code, not about extending its shape. See `docs/data-provenance.md` for the full model reference.

## 3. Integration points

Two new pieces in `harvesters/texas_harvester.py`, both added right after the `TexasSaleRow` dataclass:

- **`FIELD_LINEAGE_MAP`** — a static, per-source dict documenting the source-field → normalized-field mapping each real harvester actually performs (read directly from `harvest_lgbs()`/`harvest_realauction()`'s own row-construction code, not invented). Data, not runtime objects — see Section 5 for why.
- **`build_row_provenance(harvester_source: str, *, retrieved_at: str) -> Provenance`** — constructs one whole-row `Provenance` record at `NORMALIZED` stage, using the SAME `check_ingestion_gate()` decision and the SAME `SOURCE_REGISTRY` entry that already govern ingestion (never a second, independently-maintained copy of that data — see Section 9).

Two real call sites:

- **`harvesters/texas_harvester.py`'s `main()`** — after writing `out/harvest_texas.json`, logs one `Provenance` summary per source actually harvested this run (not per row — see `build_row_provenance()`'s own docstring for why one-per-source is the complete, non-redundant record here).
- **`scripts/sync-texas-to-supabase.py`** — builds one `Provenance` per row that survives both governance checks (`check_ingestion_gate()` and Phase 11's `project_row_for_customer_output()`), asserts it matches the gate's own restriction decision, and logs a per-source count at the end of the run.

A third, lighter touch: **`scripts/geocode_properties.py`** logs a plain-language `ENRICHED`-stage audit line after a successful batch — not a `Provenance` object (see Section 6 for why).

## 4. Source-level lineage

Verified for both real Texas production sources:

- **`tx_lgbs`** — `build_row_provenance("tx_lgbs", ...)` returns `source_id="tx_lgbs"`, `source_url` from the registry (`https://taxsales.lgbs.com/api/property_sales/`), `restrictions=()` (matching the registry's current `APPROVED`, zero-restriction status). `test_A_lgbs_row_has_source_provenance`.
- **`tx_realauction`** — same shape, `source_url` from the registry. `test_A_realauction_row_has_source_provenance`.
- **Florida** — Florida's harvesters remain entirely PowerShell, with zero coupling to this Python package (re-confirmed this phase, same grep check every prior phase has used: no `.ps1` file references `governance`). Per Phase 12 Step 5's own instruction ("determine the cleanest shared integration point... do not introduce Texas-specific assumptions into Florida harvesting"), the answer is: the *model* (`Provenance`, generic by its own design) is directly reusable for an FL row without any FL-specific code change — proven by `test_A_florida_row_can_be_represented_by_the_same_generic_model`, which builds a real `Provenance` for `fl_realauction` using nothing but existing registry data. No FL harvester was modified, and none needed to be.

## 5. Field-level lineage

`FIELD_LINEAGE_MAP` answers "field → source → source field → transformation" directly, as data:

```python
FIELD_LINEAGE_MAP["tx_lgbs"]["min_bid"]
# -> "minimum_bid (parsed via _lgbs_to_float())"

FIELD_LINEAGE_MAP["tx_realauction"]["cause_number"]
# -> "'Cause Number' field"

FIELD_LINEAGE_MAP["tx_realauction"]["latitude"]
# -> None  (RealAuction publishes no coordinates - explicitly recorded, not omitted)
```

**Why this is a static map, not one `Provenance` object per field per row:** this pipeline harvests and normalizes a listing as a single unit — there is no point in `harvest_lgbs()`/`harvest_realauction()` where an individual field exists as a separately-tracked value before the full `TexasSaleRow` is built, and nothing downstream in this codebase reads a per-field `Provenance` object. Generating 13 of them per row, for thousands of rows, on every harvest run, for a story no code consumes, would be exactly the over-engineering Phase 12 Step 23 warns against. The map is real, checkable data pulled directly from the harvesting code (verified by `test_B_field_lineage_reflects_the_actual_source_field_names_in_the_harvester_code`) at zero per-row runtime cost — it answers the question Phase 12 Step 4 actually asks ("what source field did this normalized field come from") without building unused infrastructure.

## 6. Enrichment lineage

Two candidate enrichment steps were audited, not assumed:

- **`scripts/geocode_properties.py`** — REAL, runs in production (`.github/workflows/harvest-and-sync.yml` invokes it directly), confirmed to have no `state` filter anywhere in `_fetch()`/`fetch_ungeocoded()` — it applies to TX and FL rows alike, which is exactly the "narrowest shared boundary" Phase 12 Step 5 asks for when a mechanism is genuinely cross-state. Confirmed to only ever target `latitude IS NULL` rows (`test_C_geocoding_enrichment_only_ever_targets_null_coordinates`) — it **supplements**, never **replaces**, a source value. This phase added one audit-log line after a successful batch, documenting the `ENRICHED`/`DERIVED`/`is_source_provided=False` classification in plain language rather than as a fabricated `Provenance` object: a `Provenance.source_id` is meant to identify a `SOURCE_REGISTRY` entry (a governed, restriction-bearing commercial source), and the free Census Geocoder is neither commercial nor gated — representing it with a registry-shaped `source_id` would invent structure this enrichment doesn't actually have.
- **`scripts/enrich_property_details_tx.py`** — confirmed, by reading its own module docstring, to be an "ARCHITECTURAL DRAFT, not working code" — and confirmed, by grepping `.github/workflows/harvest-and-sync.yml`, to be mentioned only in a comment, never invoked as a `run:` step (`test_C_no_working_cad_enrichment_exists_for_texas_yet`). **No CAD-based enrichment happens for Texas in production today.** This phase did not build one — that would be expanding source coverage, explicitly out of scope (Phase 12's own hard rules).

**SOURCE value vs. ENRICHED value, kept distinct:** `geocode_properties.py`'s `latitude IS NULL` filter is itself the mechanism that keeps these distinct in this codebase — a row's originally-harvested coordinates (if LGBS published any) are never touched; only a `NULL` gets filled. There is no code path where enrichment can overwrite an already-populated source value.

## 7. Derived data lineage

No derived field is computed server-side anywhere in this pipeline (confirmed by inspection, same finding as Phase 11) — `public/app.js` computes any bid-to-value-style ratio client-side, from fields (`bid`, `assessed`) that already passed the same source's restriction check at sync time. What Phase 12 verifies, at the layer this codebase actually has (`derive()`):

- A derived value's lineage traces back to all of its real parent sources (`test_D_derived_field_inherits_parent_lineage`, using `origin_source_ids()`).
- A restriction on ANY parent survives into the derived value — never laundered away (`test_D_derived_field_restriction_inheritance_preserved_end_to_end`, `test_D_unrestricted_parents_produce_unrestricted_derived_field`).
- **The complete chain** (Phase 12 Step 17's explicit ask): a restricted parent's restriction survives `derive()` AND is independently confirmed to match what `project_row_for_customer_output()` would decide for a row from that same source — the two representations of "restricted" (the provenance model's and the governance gate's) are shown to agree, not just each individually correct in isolation.

## 8. Restriction inheritance

Verified end to end: source (registry `restrictions` tuple) → `check_ingestion_gate()`'s decision → `build_row_provenance()`'s `Provenance.restrictions` (built FROM that same decision, never a second lookup) → `derive()` (unions, never drops) → `project_row_for_customer_output()`/`project_row_for_api_export()` (block or strip accordingly, per Phase 11). `test_D_derived_field_restriction_inheritance_preserved_end_to_end` exercises this full chain in one test. No restriction was weakened anywhere in this phase — `harvesters/governance/registry.py` was not modified at all (confirmed: zero lines changed in this phase's diff).

## 9. Customer/API boundaries

Provenance is never merged into a customer-facing row. `project_row_for_customer_output()`/`project_row_for_api_export()` (Phase 11, unchanged this phase) only ever return a subset of the *input* row's own keys — there is no code path where a `Provenance` object's fields (`source_url`, `classification`, `stage`, `restrictions`, etc.) could end up as a key in the projected dict. Verified directly: `test_E_provenance_metadata_never_leaks_into_the_projected_row` and `test_F_provenance_metadata_never_leaks_into_the_exported_row` both assert a specific set of provenance/governance-shaped key names (`provenance`, `restrictions`, `classification`, `stage`, `source_url`, `is_source_provided`, `derived_from`, `legal_status`, `reviewer`, `notes`, `review_date`) never appears in a projected row. `test_F_projected_row_remains_plain_json_serializable_with_no_provenance_object_inside` additionally confirms the projected row round-trips through `json.dumps()` cleanly, with no `Provenance`/`PipelineStage` object embedded.

## 10. Internal-only metadata

Everything a `Provenance` record carries — `source_url`, `retrieved_at`, `stage`, `classification`, `restrictions`, `is_source_provided`, `derived_from` — along with everything a `SourceRecord` carries (`legal_status`, `reviewer`, `notes`, `review_date`, `commercial_use_status`, and the rest) stays inside the Python pipeline (`harvesters/texas_harvester.py`'s `main()`, `scripts/sync-texas-to-supabase.py`) and is never part of the dict handed to Supabase. None of it reaches `public/app.js`, the CSV export, or `supabase/functions/send-digest` — those three surfaces only ever see whatever ended up as an actual column value in `public.properties`, and no provenance/governance field is among those columns (confirmed: the `row` dict `sync-texas-to-supabase.py` builds has exactly the same key set it had before this phase — `state`, `source`, `county`, `case_no`, `parcel`, `address`, `bid`, `min_bid`, `assessed`, `sale_date`, `legal_desc`, `harvester_source`, and conditionally `latitude`/`longitude` — Phase 12 added no new key to it).

## 11. Cross-state isolation

`build_row_provenance()` takes a `harvester_source` string and nothing else — it has no parameter for `county`/`case_no`, and holds no module-level cache or shared mutable state keyed by either. Two rows sharing the same `(county, case_no)` from different states/sources produce fully independent `Provenance` objects and fully independent projection results, verified directly by `test_H_florida_texas_same_county_case_no_produce_independent_provenance` (re-running in both orders to rule out any hidden ordering dependency).

## 12. Idempotency behavior

`build_row_provenance()` is a pure function of its two inputs (`harvester_source`, `retrieved_at`) plus the current registry state — calling it twice with identical inputs produces two equal (by dataclass value equality) `Provenance` objects (`test_I_same_source_same_retrieval_context_produces_equivalent_lineage`). **Record identity** (which source this is — `source_id`) is explicitly distinguished from **retrieval event** (when this particular run fetched it — `retrieved_at`): two calls with the same `source_id` but different `retrieved_at` values are, correctly, two *different* `Provenance` records (`test_I_different_retrieval_timestamps_are_a_different_retrieval_event_not_a_different_record_identity`) — this is not a bug or a source of drift, it is the intended behavior: a source retrieved at two different times genuinely has two different retrieval events, even though it's "the same source."

`main()` and `sync-texas-to-supabase.py` each generate their OWN `retrieved_at` (a fresh UTC timestamp captured once per process run) rather than threading a single value through `out/harvest_texas.json` — deliberately: that file carries no retrieval-timestamp field of its own today, and adding one would be a file-shape change this phase's "smallest necessary mechanism" instruction (Step 23) doesn't justify for a value that's only ever used for an audit-log line. This means `main()`'s logged retrieval event ("when the harvester fetched from LGBS/RealAuction") and the sync script's logged retrieval event ("when this sync run processed the row") are two distinct, honestly-labeled events — not a claim that the sync script re-fetched from the vendor.

## 13. Current limitations (stated plainly)

- **Pipeline-side only, not persisted.** Every `Provenance` record this phase builds is constructed, used (logged, asserted against), and discarded within a single process run. Nothing durable remembers "this specific row's lineage" between runs — a re-sync of the same row builds a fresh `Provenance` with a fresh `retrieved_at`, not a continuation of a prior one. This is the direct, intended consequence of Phase 12's own "no schema, no migration" hard rule, not an oversight.
- **Whole-row, not per-field, at runtime.** `FIELD_LINEAGE_MAP` answers field-level lineage as static data (Section 5); the actual `Provenance` objects built and used at runtime are whole-row. A future need for genuine per-field runtime provenance (e.g. once a source enters `APPROVED_WITH_RESTRICTIONS` with a `field_specific_restriction` — see `docs/customer-api-data-enforcement.md`'s own `FIELD_SPECIFIC_RESTRICTION` handling) would need this extended; not built speculatively here.
- **`main()`'s per-source summary vs. the sync script's per-row records.** These are two different granularities logged in two different places, intentionally (see Section 3) — a reader wanting "prove every individual row's lineage" should look at the sync script's assertion (`row_provenance.restrictions == gate_decision.restrictions`, checked live for every row) and its final per-source count, not `main()`'s coarser per-source-per-run log line.
- **No CAD/valuation enrichment lineage for Texas** — because no such enrichment runs in production (Section 6). This is a pre-existing gap this phase confirmed and documented, not one it was in scope to close (would mean finishing `enrich_property_details_tx.py`, itself gated on the CAD-source-availability research question that file's own docstring describes as unresolved — out of scope for a provenance-integration phase).
- **The Census-geocoder enrichment event is logged, not modeled as a `Provenance` object** (Section 6) — a deliberate choice, not an inconsistency, but it does mean `geocode_properties.py`'s ENRICHED-stage event isn't queryable the same programmatic way `build_row_provenance()`'s NORMALIZED-stage records are.
- **A cosmetic, pre-existing, unrelated label bug was noticed but not fixed**: `geocode_properties.py`'s no-match log line always prints "County, FL" regardless of the row's actual state, even though the query itself is state-agnostic (Section 6/Section C's tests confirm the query, not the log wording). Flagged here for completeness; out of scope to fix in a provenance-integration phase per Step 24's "do not fix unrelated failures."

## 14. Future database-level provenance option (not implemented this phase)

If persistent, queryable, cross-run provenance is wanted later, the smallest schema-respecting options are:

- **A single `properties.provenance` JSONB column** — one column, additive, no new table — storing a serialized form of the `Provenance` this phase already builds (would need a `Provenance → dict` serializer, since the dataclass isn't currently JSON-serializable as-is: `PipelineStage`/`FieldClassification` are `str` enums, so `dataclasses.asdict()` plus `str()` on the enum members would round-trip cleanly). Cheapest option; loses queryability of individual lineage fields without JSONB path operators.
- **A separate `property_provenance` table**, one row per `(property_id, retrieved_at)`, foreign-keyed to `properties.id` — fully queryable, supports genuine history (multiple retrieval events per property over time, which a single JSONB column on `properties` itself would overwrite on each sync), but is a real new table + migration + RLS policy design (mirroring the same RESTRICTIVE/PERMISSIVE care `CLAUDE.md` already documents being hard-won knowledge for this project).
- **An append-only `harvest_events` log table** — one row per harvest/sync RUN (not per property), recording `(run_id, source_id, retrieved_at, rows_processed, rows_rejected_by_gate, rows_rejected_by_restriction)` — closer to what `main()`'s and the sync script's current per-run log lines already informally capture, formalized into a queryable audit trail without needing per-row granularity at all.

None of these were implemented this phase — Phase 12's hard rules explicitly forbid a migration. Named here as real options, not built speculatively (Step 23).

## 15. Future raw-data retention option (not implemented this phase)

Currently: no raw payload (LGBS's JSON response, RealAuction's HTML) is retained anywhere, for any source, approved or blocked. Per source:

| Source | Raw retained today? | Raw permitted? | Raw necessary for provenance? |
|---|---|---|---|
| `tx_lgbs` (APPROVED) | No | Unresolved — LGBS's own redistribution-prohibition scope question (`docs/lgbs-rights-audit.md`) is exactly about reproduction/retransmission of material, which raw retention would implicate directly | No — `NORMALIZED`-stage provenance (Section 4) is sufficient for today's auditability needs |
| `tx_realauction` (APPROVED) | No | Unresolved — no Terms of Use was ever found to check against (`docs/realauction-rights-audit.md`) | No |
| `tx_hctax` (LEGAL_REVIEW_REQUIRED) | No | No — no permission found | N/A — no harvester exists |
| `tx_govease` / `tx_pbfcm` / `tx_mvba` / `tx_ctsa` (all BLOCKED) | No | **No — explicit prohibitions found for each** (see each source's own reconnaissance doc) | N/A — no harvester runs |

If raw retention is ever wanted for an APPROVED source (for audit/dispute purposes, say), it would need: (a) a storage location outside `public.properties` (raw HTML/JSON doesn't belong in a relational row — object storage, e.g. a Supabase Storage bucket, would be the natural fit), (b) an explicit decision that LGBS's/RealAuction's own terms permit retention specifically (not just automated access — retention is a different question the existing audits didn't resolve), and (c) a `Restriction.NO_RAW_HTML`-aware check before ever writing raw content anywhere customer-reachable (the mechanism for this already exists — see `docs/customer-api-data-enforcement.md`'s `FIELD_SHAPE_KEYWORDS`). Not built or begun this phase, consistent with Phase 12 Step 7's explicit instruction not to start raw retention "merely for provenance."

## 16. Future audit/event architecture (not implemented this phase)

The `harvest_events` log table sketched in Section 14 is the natural seed of a fuller audit/event architecture (e.g. a per-run event stream feeding an admin dashboard of "what was harvested/rejected/enriched, when, from where"). Phase 12 Step 23 explicitly rules out building "a full event-sourcing system" or "a persistent audit-log platform" this phase — what exists today (per-run stderr log lines from `main()`, the sync script, and `geocode_properties.py`) is the honest, minimal precursor to such a system, not the system itself. If this is wanted later, the natural next step is formalizing today's log lines into structured (JSON) log output first — a much smaller change than a new table — before considering persistence at all.

## Testing strategy

`tests/python/test_provenance_integration.py` — 24 tests, one (or a small group) per letter of Phase 12 Step 20's own A–J matrix, using real registry entries (`tx_lgbs`, `tx_realauction`, `tx_hctax`, `tx_pbfcm`, `fl_realauction`) plus synthetic `SourceRecord` fixtures for restriction combinations no real source currently carries. One test (`test_G_integration_sync_script_never_builds_provenance_for_ungated_rows`) runs the REAL, unmodified `scripts/sync-texas-to-supabase.py` end to end against a synthetic mixed-source fixture, with only its one outbound network call (`urllib.request.urlopen`) stubbed — no reimplementation of its logic, no real Supabase call, no external source contacted.

## CI

No workflow change needed — `.github/workflows/python-governance-test.yml` already runs `pytest tests/python/ -v`, which picks up the new test file automatically, the same as Phase 11's test file was picked up without a workflow edit. Verified locally: 75/75 tests pass (25 Phase 10A + 26 Phase 11 + 24 Phase 12, ~0.15s). The workflow itself has still not executed on GitHub's runners (no push access, unchanged since Phase 10B).

## Regression summary

`harvesters/governance/registry.py` — untouched (zero lines changed this phase; confirmed via diff). `harvesters/governance/gate.py`, `restrictions.py`, `provenance.py`, `__init__.py` — untouched. `TexasSaleRow` — untouched (still the same 13 fields; `test_14_lgbs_and_realauction_unchanged_and_approved`'s hard-coded snapshot still passes). `SOURCES` dict — untouched. Florida — zero `.ps1` references to `governance`, re-confirmed. Phase 10A/10B/11 behavior — all 75 tests pass, including every pre-existing test from those phases, unmodified. The pre-existing, unrelated `sb.rpc is not a function` frontend-test failure was reconfirmed present (same failure signature: `.county-group` timeout) via an actual Playwright run this phase — not fixed, out of scope, exactly as documented in Phase 10B/11.
