# Source adapters

**Status:** Phase 40, 2026-09-16 (supersedes the Phase 39 revision). Inventory of implemented acquisition mechanisms. See `docs/acquisition-engine.md` for the contract they implement.

## 1. The anti-321-scrapers rule, measured

Section 5 of Phase 39's brief prohibits building one scraper per county. The measured outcome, computed live from `harvesters/acquisition/config.py`:

| State | County-source config rows | Distinct counties | Rows served by an implemented adapter | Adapters needed |
|---|---|---|---|---|
| Florida | 226 | 67 | 67 | 1 (`ArcGisAdapter`) |
| Texas | 277 | 254 | **95** | 1 (`LgbsAdapter`) |

Two adapters cover every county-source pair that has an implemented mechanism today. Adding a county to either is a configuration entry, not a module.

## 2. `ArcGisAdapter` — unauthenticated ArcGIS REST

The highest-leverage adapter in the engine, because ArcGIS REST is the mechanism behind Florida's statewide cadastral layer, most Texas CADs, and most county GIS portals in both states.

| Layer | `cad_id` | Jurisdiction | Live-verified | Notes |
|---|---|---|---|---|
| FDOR Statewide Cadastral | `fl_fdor_statewide_cadastral` | FL, all 67 counties | 2026-09-16 | Layer "FDOR Cadastral 2025", 124 fields. County-scoped query by `CO_NO` confirmed against Alachua (code 11), returning parcels with `JV`/`AV_NSD`/`DOR_UC` populated. |
| HCAD Parcels | `tx_cad_harris_hcad` | TX, Harris | 2026-09-16 | Layer "HCAD Parcels". A real single-parcel query returned attribute values matching the 2026-09-08 sample in `_fetch_hcad()`'s comment block **exactly**. |
| Tarrant County Parcel | `tx_cad_tarrant_tad` | TX, Tarrant | 2026-09-16 | All 16 expected fields confirmed, including `EXEMPTION_` and `LIVING_ARE`, both confirmed absent from HCAD's layer. |

**A note on what "verified" means here.** These checks confirm the layer answers and carries the expected fields. They were performed through this session's sanctioned web-fetch path, because the sandbox's own sockets are egress-blocked (see `docs/acquisition-engine.md` §2). They are a genuine live contract check; they are **not** a statement that a full acquisition run has been performed, and no coverage figure anywhere in this phase is derived from them.

Adding a fourth layer is a `CadLayerConfig` entry in `harvesters/acquisition/adapters/arcgis.py`. Bexar (BCAD) is the obvious next one: a real endpoint was found in earlier research but its classification field names have never been sampled.

### Florida statewide, worked

`fl_dor_statewide` covers all 67 Florida counties from one layer — Section 46's statewide-over-per-county preference, realized. The adapter's `acquire_county()` scopes by county code and refuses a county it has no code for, rather than silently issuing an unscoped query that would pull a neighbouring county's parcels.

The FDOR normalization preserves that source's documented **0-as-no-data sentinel** rule (`enrich_property_details.py::_num`): a real $0 just value does not occur, so `0` becomes `None` rather than a misleading zero. `JV` is the county property appraiser's statutory just-value estimate and must never be presented as a live/AVM estimate; `value_year` carries `ASMNT_YR` so the UI can say whose number it is and for which tax year.

## 3. `LgbsAdapter` / `JsonApiAdapter` — paginated JSON REST

`tx_lgbs`, `taxsales.lgbs.com/api/property_sales/`. Live re-verified 2026-09-16: DRF `count`/`next`/`previous`/`results` envelope unchanged, **count = 6,309** rows for `area=TX`, all 29 result fields present including every field `harvest_lgbs()` reads.

Three source semantics are preserved deliberately and would be wrong to "simplify":

1. **`area=TX` is not a strict state filter.** A live sample previously returned Philadelphia County, PA rows interleaved with Texas ones, so every row's own `state` field is checked. Skipping that filter would silently import Pennsylvania properties into the Texas ledger.
2. **Ledger classification keys off `status`, never `sale_type`.** A `sale_type=SALE` row can carry status "Cancelled", "Sold" or "Struck off to Jurisdiction".
3. **`next` links come back as plain `http://`** and are upgraded before being followed, so every request after the first stays encrypted.

The adapter does not reimplement any of this — it calls `_lgbs_normalize_county`, `_lgbs_to_float`, `_lgbs_compose_address` and `LGBS_STATUS_TO_LEDGER` from `harvesters/texas_harvester.py`. There is one implementation of each rule.

### One finding worth recording

The `/api/sale_status/` endpoint referenced in `texas_harvester.py`'s own comments — the source of the documented 8-value status enum — **returned HTTP 404**, confirmed twice (Phase 39 and Phase 40).

Phase 40 extended the finding: the API root at `/api/` advertises ten endpoints, and **every one tested besides `property_sales` returns 404** (`sale_counties`, `sale_status`, `filter_bar`, `counties`, `venues`). So the 404 is not evidence that the status vocabulary changed — it is a whole class of advertised-but-unserved routes. `LGBS_STATUS_TO_LEDGER` is unchanged and pinned by a test.

### Coverage, measured (Phase 40)

The caveat recorded here in Phase 39 — that the configuration attributed `tx_lgbs` to only 8 counties while the API's 6,309 rows spanned many more — has been resolved by measurement.

**95 Texas counties**, measured county-by-county from the API's own authoritative `count`. The adapter serves all 95 unchanged, because the API is statewide and the roster is configuration rather than code. See `claude/phase-40-lgbs-roster.md` and `data/tx_lgbs_observed_county_roster.csv`.

Two further findings from that measurement bear on this adapter:

- **`area=TX` carries 2,104 Philadelphia, PA records** (33.4% of 6,309). The `state`-field check preserved from `harvest_lgbs()` is doing a third of the work of keeping the Texas ledger clean.
- **The API silently ignores unknown query parameters.** `county__icontains=` and `search=` both returned the full unfiltered count rather than erroring. Any future filter added to this adapter must be validated against a known-bad value before its results are trusted.

## 4. Mechanisms configured but not implemented

Each has a real reason, not a stub left lying around:

| Mechanism | Counties | Why not this phase |
|---|---|---|
| `HTML_PUBLIC_SEARCH` | 112 FL, 24 TX | `fl_realauction`, `fl_lienhub_certificates`, `tx_realauction`, `tx_hctax`. All either `LEGAL_REVIEW_REQUIRED` or already served by working production harvesters. The blocker is legal, not technical. |
| `DOCUMENT_PDF` | 47 FL | `fl_laft_pdfs` has a working production implementation. Re-implementing it behind this contract buys nothing and violates the no-gratuitous-rewrite rule. |
| `BULK_DOWNLOAD` | — | FDOR's Data Portal NAL/NAP/SDF files. Not implemented because the portal URL recorded in the registry was found stale this phase (see `docs/florida-acquisition.md`); the ArcGIS path to the same source was verified and implemented instead. |
| `NONE` | 158 TX | Genuinely no identified acquisition mechanism. Recording that honestly is the point. (Was 225 before Phase 40's roster measurement.) |
