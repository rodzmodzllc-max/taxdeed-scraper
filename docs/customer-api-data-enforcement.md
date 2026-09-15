# Customer/API data-restriction enforcement

**Status:** Phase 11 (Complete Customer/API Data-Restriction Enforcement), 2026-09-14. Companion to `docs/data-licensing.md` (the Phase 10A enforcement model this phase extends), `docs/data-provenance.md` (the pipeline/classification model), and `docs/source-registry.md` (per-source detail). No source's `legal_status` or `restrictions` changed this phase — this page is entirely about *how* an already-decided status/restriction set is now enforced at the customer/API boundary, not about any new permission decision.

## The gap this phase closes

Phase 10A's own report was explicit about what it left undone: `filter_rows_for_customer_output()` and `filter_rows_for_api_export()` (in `harvesters/governance/gate.py`) were "built/tested but NOT wired into frontend." This phase closes that gap — but the fix is not what "wire into frontend" might suggest, because of a hard architectural fact this phase's own audit confirmed first (see below): there is no frontend code path that can execute Python at all.

## The real architecture, confirmed by inspection before writing any code

This application has no application server. Three surfaces read customer data, and all three read `public.properties` directly:

1. **`public/app.js`** — calls `sb.rpc("get_properties", { p_state })` (falling back to `sb.from("properties").select("*")`), both via the Supabase JS SDK, running entirely in the browser.
2. **The CSV export in `public/app.js`** (`exportCsvBtn`'s click handler) — builds its CSV from the same in-memory rows `app.js` already fetched in (1). It is not a separate read path.
3. **`supabase/functions/send-digest`** — a Deno Edge Function that calls a `digest_candidates` RPC using the `service_role` key (bypassing RLS entirely) and emails the results to users who favorited a property closing soon.

None of these three can import or call `harvesters/governance/` — two run outside any Python runtime entirely (browser JS, Deno), and even if they could, `get_properties()` is a plain SQL function (`select * from public.properties where state = p_state ...`, see `scripts/migrations/003_ledger_type_and_state_isolation.sql`) with no per-row or per-field governance logic of its own. Adding governance logic to `get_properties()`, to a new field-filtering view, or to any other read-time mechanism would require a migration — and Phase 11's hard rules explicitly forbid modifying the Supabase schema or creating migrations this phase.

**The consequence, stated plainly:** the `public.properties` table has no field-level RLS (confirmed in Phase 10A already — `docs/data-licensing.md`'s "Where it's actually wired in" section says this directly), so a row that reaches that table is immediately, unfilterably visible to every approved user through all three of the surfaces above at once. There is no read-time chokepoint available to this phase. The only chokepoint that exists, that this phase can extend, and that is honest about what it actually enforces, is the same one Phase 10A already identified as "the last real chokepoint before customer output": `scripts/sync-texas-to-supabase.py`, the write-time step that builds the row before it becomes that permanently-shared representation.

This is why Phase 11's implementation lives in the sync script rather than in `public/app.js` — not a workaround, but the correct read of what "the customer/API boundary" actually is in this specific, single-tier, RLS-based architecture.

## What was built

### `harvesters/governance/restrictions.py`

- **`FIELD_SHAPE_KEYWORDS`** — a new mapping from a field-shaped `Restriction` (`NO_RAW_HTML`, `NO_IMAGES`, `NO_DOCUMENTS`) to a tuple of lowercase substrings that identify a restricted field by name (e.g. `NO_IMAGES` → `("image", "img_url", "photo_url", "photo")`). Deliberately keyword-based, not a fixed per-schema field list: neither `TexasSaleRow` (`harvesters/texas_harvester.py`) nor the row dict `scripts/sync-texas-to-supabase.py` builds contains any raw-HTML, image, or document field today — confirmed by inspection and by `test_field_shape_keywords_match_none_of_the_real_tx_row_fields` in the new test suite, which asserts this mapping is provably inert against every field the real pipeline currently produces. It activates automatically, with no further code change, the day a future harvested field's name contains one of these keywords.
- **`BLOCKS_CUSTOMER_DISPLAY`** now also includes **`FIELD_SPECIFIC_RESTRICTION`** (it did not before this phase). Reasoning, not just a broadened set: `SourceRecord.restrictions` records *that* a field-specific restriction exists but not *which* field — there is no restriction-to-field-name mapping anywhere in this codebase. A restriction this module cannot resolve to one specific field cannot be safely narrowed to "strip just that field," so the fail-closed choice (per this phase's own instruction: "unknown restriction → deny exposure") is to block the whole row until a future extension adds that mapping. Zero registry entries carry `FIELD_SPECIFIC_RESTRICTION` today, so this is a zero-behavior-change-today addition, exercised only by the new test suite's synthetic fixtures.

### `harvesters/governance/gate.py`

Two new functions, both thin extensions of the existing gate/restriction machinery (no parallel authorization system):

- **`project_row_for_customer_output(row: dict, source_id: str) -> dict | None`** — runs the same `check_ingestion_gate()` decision `filter_rows_for_customer_output()` already used, plus the same `BLOCKS_CUSTOMER_DISPLAY` check; if the row survives, returns a **new** dict (the input is never mutated) with any key matching a `FIELD_SHAPE_KEYWORDS` entry for a restriction the source actually carries removed. Everything else passes through unchanged.
- **`project_row_for_api_export(row: dict, source_id: str) -> dict | None`** — same shape, using `BLOCKS_API_EXPORT` (a strict superset of `BLOCKS_CUSTOMER_DISPLAY`), for a source that may be display-fine but export-prohibited (`NO_API_EXPORT`).

Both are exported from `harvesters/governance/__init__.py` alongside the existing whole-list functions.

### `scripts/sync-texas-to-supabase.py`

The row-building loop now calls `project_row_for_customer_output(row, harvester_source)` immediately after building `row`, before it is added to the dedup map that becomes the Supabase upsert payload. This is a **second, independent check** from the existing `check_ingestion_gate()` call earlier in the same loop: that call only looks at `legal_status` (is this source allowed to be ingested at all); this call additionally looks at `restrictions` (does this *approved* source still carry a restriction that blocks customer display, or a field that must be stripped). A row rejected at this new step is counted separately (`skipped_customer_restriction`) and logged distinctly from an ingestion-gate rejection, so the two failure modes stay distinguishable in the script's own output.

For `tx_lgbs` and `tx_realauction` — the only two sources this script actually processes in production, both `APPROVED` with `restrictions=()` — this is a verified no-op: `project_row_for_customer_output()` returns the row completely unchanged. See `test_Q_approved_texas_sources_project_unrestricted_unchanged` in the new test suite.

## Source-level gating (unchanged semantics, now doubly enforced)

| `legal_status` | Ingestion (Phase 10A, unchanged) | Customer/API projection (Phase 11, new) |
|---|---|---|
| `APPROVED`, no restrictions | Proceeds | Row passes through unchanged |
| `APPROVED_WITH_RESTRICTIONS` | Proceeds | Restricted fields stripped; whole row blocked only if a `BLOCKS_CUSTOMER_DISPLAY`-class restriction is present |
| `LEGAL_REVIEW_REQUIRED` | Rejected (row never reaches Supabase) | N/A — never reaches this step |
| `BLOCKED` | Rejected | N/A |
| `DISABLED` | Rejected | N/A |
| `TERMS_CHANGED` | Rejected | N/A |
| `DISCOVERED` / `UNDER_REVIEW` | Rejected (not in `INGESTION_ALLOWED_STATUSES`) | N/A |
| Unknown `source_id` | Rejected (fails closed) | Rejected (fails closed) |

Both layers independently fail closed. For the four statuses that already block ingestion, the new customer-projection layer is unreachable in production because the row never gets that far — but it was still tested directly (calling `project_row_for_customer_output()`/`project_row_for_api_export()` against each status) so its own fail-closed behavior doesn't depend on the ingestion gate having run correctly first.

## Field-level enforcement

Restriction handling splits into two groups, deliberately:

- **Field-shaped restrictions** (`NO_RAW_HTML`, `NO_IMAGES`, `NO_DOCUMENTS`) — enforced by removing the matching key(s) from the row. Currently inert (no matching fields exist in the real pipeline) but real, tested, and ready.
- **Whole-row-blocking restrictions** (`NO_CUSTOMER_DISPLAY`, `NO_REDISTRIBUTION`, `SOURCE_ONLY_DISPLAY`, `FIELD_SPECIFIC_RESTRICTION`) — the entire row returns `None`, not a partial projection.
- **Obligation-only restrictions** (`RATE_LIMIT`, `ATTRIBUTION_REQUIRED`, `RETENTION_PERIOD`, `OTHER_CONTRACTUAL_RESTRICTION`) — describe *how* data already permitted for display must be used (rate-limit the harvester, show an attribution line, purge after N days), not *which* field to remove. These have no field-stripping effect by design (`test_unrecognized_restriction_types_have_no_field_stripping_effect_but_do_not_crash`) and are not silently dropped either — they remain visible on `SourceRecord.restrictions` for a human/future feature (e.g. an attribution-line UI element) to read and act on. This is a documented gap, not a defect: this phase's instruction was "implement the smallest mechanism necessary," and there is no registry entry today carrying any of these four restriction types, so building UI-level attribution/rate-limit enforcement now would be speculative.

## Customer display / API / export

Because this application has one data surface, not three, "customer display," "API," and "export" all currently resolve to the same underlying data (`public.properties`) — the distinction that matters is not *which surface* reads the row, but *which projection function* was used to decide whether the row (or a field of it) should exist in that table at all:

- **Customer display** — governed by `project_row_for_customer_output()` (`BLOCKS_CUSTOMER_DISPLAY`).
- **API** — this application has no API distinct from PostgREST's auto-generated REST interface over `public.properties`/`get_properties()`, which any approved, authenticated user can call directly (with the same publishable key `app.js` uses) whether or not they go through `app.js` at all. This is normal, expected Supabase behavior, not a bypass: RLS (unchanged, untouched this phase) is what governs *who* can read the table; governance's job is deciding *what's in* the table, which it does at write time regardless of which client later reads it.
- **Export** — the CSV export in `app.js` builds its file from rows already fetched via (1) above; it is not a second query. `project_row_for_api_export()` exists (stricter than the customer-display function, via `BLOCKS_API_EXPORT`) for a future distinct export/API feature, but nothing calls it yet, because no such second surface exists to call it from. Documented here rather than wired in speculatively.

## Raw HTML / images / documents

No field of this shape currently exists anywhere in the TX harvest/sync pipeline — `TexasSaleRow` (`harvesters/texas_harvester.py`) has no such field, LGBS is a JSON API with no such payload, and RealAuction's harvester extracts already-structured values, never raw page HTML or image/document URLs. `FIELD_SHAPE_KEYWORDS` (above) is the enforcement mechanism that will apply automatically the moment such a field is added — verified inert against every field the real pipeline produces today, not merely inert by absence of a test.

## Provenance preservation

This codebase does not currently construct `Provenance` objects anywhere in the actual harvest/sync pipeline (`harvesters/governance/provenance.py` is tested in isolation but not yet integrated into `texas_harvester.py` or the sync script — an honest, pre-existing gap this phase did not need to close to satisfy its own objective, and did not attempt to, since doing so would mean restructuring `TexasSaleRow`/the sync row dict into `Provenance`-wrapped values, a materially larger change than "the smallest necessary mechanism"). What this phase *does* guarantee, and tests directly (`test_O_row_projection_does_not_mutate_the_input_row`): `project_row_for_customer_output()`/`project_row_for_api_export()` never mutate their input `row` dict — they always return a new dict. In this pipeline's actual data flow, the un-projected row (built from `out/harvest_texas.json`, which itself is `main()`'s already-ingestion-gated output) is the closest thing to an "internal record" this codebase has; the projected row handed to Supabase is the controlled, customer-facing derivative of it. `out/harvest_texas.json` is never committed to git and is not read by anything customer-facing — it exists only as a same-run intermediate file.

## Derived data

No derived field is currently computed server-side (in Python) before syncing to Supabase — any bid-to-value-style ratio is computed client-side in `app.js` from already-projected fields (`bid`, `assessed`) that already passed the same source's restriction check, so no additional enforcement is needed for that today (a ratio computed from two already-permitted numbers is not itself a new restricted value). What this phase confirms, at the layer this codebase actually has (`provenance.py`'s `derive()`): a value derived from a restricted parent correctly inherits that parent's restrictions rather than laundering them away — `test_N_derived_field_inherits_blocking_restriction_from_a_restricted_parent` checks this specifically for `NO_CUSTOMER_DISPLAY`, on top of the general lineage guarantee Phase 10A's own tests already covered. If a future feature computes a derived field server-side (in Python, before sync) from two different sources, it should build that value's restriction set via `derive()` first and treat the result as subject to the same `BLOCKS_CUSTOMER_DISPLAY`/`FIELD_SHAPE_KEYWORDS` checks as any other field — the mechanism exists; nothing calls it yet because nothing computes such a field yet.

## Fail-closed behavior

- **Unknown source** — `check_ingestion_gate()` (unchanged from Phase 10A) returns `allowed=False` for any `source_id` not in `SOURCE_REGISTRY`; `project_row_for_customer_output()`/`project_row_for_api_export()` inherit this directly, since both call it first.
- **Empty/missing source_id** — same fail-closed path, confirmed by `test_G_unknown_source_denies_exposure`.
- **Unresolvable restriction** (`FIELD_SPECIFIC_RESTRICTION` with no field mapping) — whole row blocked, per the `BLOCKS_CUSTOMER_DISPLAY` change above. `test_H_field_specific_restriction_with_no_field_mapping_fails_closed`.
- **Unrecognized-as-field-shaped restriction** (`RATE_LIMIT`, etc.) — does not crash, does not strip anything, does not block the row (these are use-obligations, not display blockers) — `test_unrecognized_restriction_types_have_no_field_stripping_effect_but_do_not_crash`.

## Bypass review (Phase 11 Step 12)

Checked specifically for:

- **Direct response construction bypassing governance helpers** — not possible for a would-be attacker within this codebase's own code (nothing else builds a `properties` row), but any approved user CAN read `public.properties` directly via PostgREST, bypassing `app.js` — see "Customer display / API / export" above for why this is expected Supabase behavior (governed by RLS, not by this Python package) and not a governance bypass, since governance controls what's *in* the table, not who can query it.
- **Bulk endpoints bypassing per-row filtering** — `filter_rows_for_api_export()` (whole-list) and `project_row_for_api_export()` applied row-by-row were checked for agreement (`test_S_bulk_export_path_enforces_same_restrictions_as_single_row`, `test_S_bulk_export_of_mixed_sources_isolates_each_rows_own_restrictions`) — no discrepancy found.
- **Alternate export endpoint** — none exists; the CSV export reads already-fetched, already-projected rows (see above).
- **Cached unrestricted representations** — no caching layer exists anywhere in this codebase's harvest/sync/customer path (confirmed by inspection); documented rather than tested against a mechanism that doesn't exist (`test_T_no_caching_layer_exists_to_bypass`).
- **Debug/admin endpoints exposing raw source payloads** — none found. `out/harvest_texas.json` (the closest thing to a raw/pre-projection artifact) is a local, gitignored, same-run file never served by any endpoint.
- **`supabase/functions/send-digest`** — reviewed directly (reads `Deno`/TypeScript source). Uses `service_role` to call a `digest_candidates` RPC and email results, bypassing RLS — but it can only ever surface data already present in `public.properties`, so it inherits whatever was (or wasn't) written at sync time; it introduces no new read of anything this phase's write-time projection didn't already decide. Texas rows currently never populate `url_auction` (not part of the sync payload), so a TX favorite in a digest email would render an empty link — not a leak, just an absent field, consistent with everywhere else this field is handled.

No genuine bypass was found. No fix was required beyond the enforcement wiring described above.

## Testing strategy

`tests/python/test_customer_api_enforcement.py` — 26 tests, one (or a small parametrized group) per letter of Phase 11 Step 9's own A–T matrix, using both real registry entries (`tx_lgbs`, `tx_realauction`, `tx_hctax`, `tx_pbfcm`) and synthetic `SourceRecord` fixtures (via `monkeypatch.setitem(SOURCE_REGISTRY, ...)`, the same pattern `test_source_governance.py` already established) for statuses/restrictions no real source currently carries. Fixtures resemble the actual `properties` row shape the sync script builds, not an invented schema. No external source was contacted or scraped to build these tests.

## CI enforcement

No change needed to `.github/workflows/python-governance-test.yml` — it already runs `pytest tests/python/ -v`, which picks up the new test file automatically. Verified locally: 51/51 tests pass (`pytest tests/python/`, ~0.1s). The workflow itself has still not executed on GitHub's runners (no push access this session, unchanged from Phase 10B).

## Examples

```python
from harvesters.governance import project_row_for_customer_output

# tx_lgbs today: APPROVED, zero restrictions - unchanged pass-through
row = {"state": "TX", "county": "Dallas", "case_no": "123", "address": "1 Main St"}
project_row_for_customer_output(row, "tx_lgbs") == row  # True

# a hypothetical future APPROVED_WITH_RESTRICTIONS source carrying NO_RAW_HTML
row2 = {"case_no": "1", "raw_html": "<div>...</div>", "address": "1 Main St"}
project_row_for_customer_output(row2, "some_future_source")
# -> {"case_no": "1", "address": "1 Main St"}   (raw_html stripped)

# tx_hctax: LEGAL_REVIEW_REQUIRED - never reachable, not that it's silently empty
project_row_for_customer_output(row, "tx_hctax") is None  # True
```

## Known limitation (stated plainly, not minimized)

Enforcement in this phase is **write-time only**, not independently enforced at read time, because this application's architecture (no server, direct Supabase reads, no field-level RLS) offers no read-time chokepoint that doesn't require a schema change — and Phase 11's hard rules forbid one this phase. This means: correctness depends entirely on every write path going through `scripts/sync-texas-to-supabase.py`'s projection step. If a row were ever written to `public.properties` through some other path (a manual `INSERT`, a different script, a future feature that writes directly), it would bypass this enforcement entirely, the same as it already bypasses Phase 10A's ingestion gate today — this is not a new risk Phase 11 introduces, but it is not fixed by Phase 11 either. The durable fix, when it's in scope, is one of: (a) a migration adding field-level RLS or a governance-aware view/RPC that itself calls a server-side (PL/pgSQL) equivalent of this projection logic, so enforcement holds even against a future non-`sync-texas-to-supabase.py` write path, or (b) introducing an actual application server between Supabase and the frontend. Both are schema/architecture changes explicitly out of scope this phase — named here as the real precondition for the day a source needs restrictions enforced independent of how it was written.
