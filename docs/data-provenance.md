# Data provenance

**Status:** Phase 10A (Commercial Source Governance Infrastructure), 2026-09-14. Companion to `docs/data-licensing.md` (restriction enforcement) — this page is about lineage: for a given value, where did it come from, and what has happened to it since.

## Repository audit finding (Phase 10A Step 1)

Before this phase, this project had **no field/data provenance system**. `TexasSaleRow` (and the Florida equivalent, the `properties` row shape written by the PowerShell harvesters) carries the harvested *values* but nothing about their lineage beyond the single `harvester_source` string (added 2026-09-08, `003_ledger_type_and_state_isolation.sql`) — which vendor produced a row, but not when it was retrieved, what pipeline stage it's at, or what restrictions apply to it. `enrich_property_details_tx.py`/`enrich_property_details.py` and `tx_yield_calc.py` already compute enrichment/derived fields (HCAD/TAD lookups, yield calculations) but track no lineage for them either — an enriched or derived value looks identical, in the database, to a directly-harvested one.

This phase did not change that database shape (see [What this phase did NOT do](#what-this-phase-did-not-do) below) — it built a lineage model that CAN be attached to values, proved it works with real tests, and used it for exactly one new purpose (Harris County reconnaissance's own restriction-propagation question), without retrofitting it onto every existing field.

## The pipeline model

`harvesters/governance/provenance.py` implements the exact seven stages Phase 10A Step 5 specifies:

```
SOURCE -> RAW -> NORMALIZED -> ENRICHED -> DERIVED -> CUSTOMER -> EXPORT/API
```

- **SOURCE** — the originating source itself, before any retrieval (conceptual; not typically instantiated as a `Provenance` record on its own).
- **RAW** — a value exactly as retrieved from the source, before any transformation. This is the stage a harvester would attach when it first parses a page/API response.
- **NORMALIZED** — currency/date parsing, address formatting, county-name casing (matching this project's existing normalization steps, e.g. `_lgbs_normalize_county()`, `_realauction_to_float()`).
- **ENRICHED** — a value augmented from a second source (e.g. HCAD/TAD lookups in `enrich_property_details_tx.py`).
- **DERIVED** — a value computed FROM one or more other tracked values (e.g. a yield calculation) rather than retrieved or enriched directly — see `derive()`.
- **CUSTOMER** — the value as it would be shown inside the product to a paying subscriber.
- **EXPORT_API** — the value as it would leave the product entirely, through a customer-facing export or API.

## What a `Provenance` record actually carries

```python
@dataclass(frozen=True)
class Provenance:
    source_id: str            # e.g. "tx_lgbs" - matches SourceRecord.source_id
    source_url: str
    source_field: str | None  # the field name/label as the source itself presents it
    retrieved_at: str         # ISO 8601 - set once, at RAW, never updated by advance()/derive()
    stage: PipelineStage
    classification: FieldClassification
    restrictions: tuple[Restriction, ...]
    is_source_provided: bool  # True = came directly from the source; False = this project computed it
    derived_from: tuple["Provenance", ...]  # parent records, for a DERIVED value
```

Two functions move a record through the pipeline:

- **`advance(provenance, *, stage, classification=None, additional_restrictions=())`** — moves a record forward (never backward — `_assert_forward_or_same()` raises if you try to move `ENRICHED` back to `RAW`, catching what would be a programming error in a future caller). `source_id`/`source_url`/`source_field`/`retrieved_at`/`is_source_provided`/`derived_from` are always carried forward unchanged. Restrictions only grow (see `docs/data-licensing.md`'s "no laundering" section).
- **`derive(parents, *, source_field=None, classification=DERIVED)`** — builds a new `DERIVED`-stage record from one or more parents, unioning their restrictions and recording them all in `derived_from` so `origin_source_ids()` can recover the full lineage later.

## Field classification (Phase 10A Step 6)

`FieldClassification` (in `provenance.py`, alongside `PipelineStage` — kept in the same module since both describe "what a value IS," as opposed to `restrictions.py`, which describes "what you may DO with it"):

`PUBLIC`, `PUBLIC_RESTRICTED`, `PERSONAL`, `CONFIDENTIAL`, `SENSITIVE`, `LICENSE_RESTRICTED`, `DERIVED`.

A classification is carried on the same `Provenance` record as its restrictions and follows the value downstream via `advance()`/`derive()`, the same as restrictions do — a value classified `LICENSE_RESTRICTED` at `RAW` doesn't quietly become `PUBLIC` by the time it reaches `CUSTOMER` just because nothing explicitly re-checked it; `advance()`'s default behavior is to **keep the existing classification unless the caller explicitly passes a new one**, so silence preserves the classification rather than resetting it.

Every field this project has harvested to date (LGBS, RealAuction) would classify as `PUBLIC` — genuinely public tax-sale information with no source-side access restriction encountered. The richer classifications (`LICENSE_RESTRICTED` in particular) exist for the day a source like Harris County resolves to `APPROVED_WITH_RESTRICTIONS` with real conditions attached.

## Lineage for derived values

Phase 9.5's own reconnaissance (`claude/harris-hctax-legal-commercial-gate.md`, Section 10) raised, and explicitly declined to resolve, the question of whether a derived metric (e.g. a bid-to-value ratio, mirroring this project's existing `tx_yield_calc.py` pattern) counts as "the source's data" or "this project's own analysis" for rights purposes. `origin_source_ids(provenance)` makes that question checkable rather than requiring someone to trace code history: it walks `derived_from` recursively and returns every source_id a value ultimately traces back to — including through a derive-of-a-derive chain (tested: `test_derive_of_a_derive_still_traces_to_original_sources`, combining `tx_lgbs` + `tx_realauction` into an intermediate value, then combining that with `tx_hctax` into a final one, and confirming all three original sources are still recoverable).

## What this phase did NOT do

- **No change to `TexasSaleRow`.** Provenance is a separate, additive model — it is not a new field bolted onto the production dataclass, and nothing about `harvest_lgbs()`/`harvest_realauction()`'s actual output shape changed.
- **No change to the `properties` table or any migration.** Provenance records are not written to Supabase anywhere in this phase. `out/harvest_texas.json`'s shape is unchanged; the sync script's payload to `properties` is unchanged (aside from the Phase 10A gate check itself — see `docs/data-licensing.md`).
- **No retrofit of provenance onto Florida's existing harvested fields, or onto every existing Texas field.** The model exists and is tested; wiring it into every harvest_*() call to attach a real `Provenance` record per field is future work, not done speculatively here (Phase 10A Step 5's own "do not over-engineer" instruction).

## Remaining risks

1. **No production code path actually constructs a `Provenance` record yet.** The model is built, tested, and ready, but `harvest_lgbs()`/`harvest_realauction()` don't call `advance()`/`derive()` on their output today — provenance tracking exists as infrastructure, not yet as an active per-row/per-field practice. This is an honest gap: building the model without wiring it into production everywhere avoids overreach, but it also means "lineage survives normalization" is proven in tests, not yet observed on a real harvested row.
2. **No persistence layer for provenance exists.** Even once a harvester starts constructing real `Provenance` records, there's nowhere in `properties` (or elsewhere) to store them today — see `docs/source-registry.md`'s migration-considerations section for the same category of gap on the registry side. A `source_url`/`acquisition_timestamp` gap on `TexasSaleRow` was already flagged, independently, by `claude/harris-hctax-implementation-readiness.md` Section 16/17 as a pre-existing issue affecting every TX harvester, not something unique to provenance — this phase doesn't close it, only reconfirms it's still open.
3. **Tests are not wired into CI** — see `docs/commercial-data-inventory.md`.
