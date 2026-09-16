# Florida acquisition

**Status:** Phase 39, 2026-09-16. Companion to `docs/florida-data-map.md` (Phase 37/38's source map) and `docs/acquisition-status.md`.

## 1. The statewide mechanism, verified and implemented

Phase 37/38 recommended `fl_dor_statewide` as Florida's highest-leverage target: one source covering all 67 counties instead of 55 individual Property Appraiser integrations. Phase 39 verified it live and built the adapter.

**What was verified, 2026-09-16**, through this session's sanctioned web-fetch path:

- `services9.arcgis.com/.../Florida_Statewide_Cadastral/FeatureServer/0` answers. Layer name **"FDOR Cadastral 2025"**, **124 fields**.
- Every field the existing production enrichment script reads is present: `PARCEL_ID`, `CO_NO`, `ASMNT_YR`, `JV`, `AV_NSD`, `LND_VAL`, `DOR_UC`, `PHY_ADDR1`, `OWN_NAME`.
- A real **county-scoped query** (`CO_NO=11`, Alachua) returned parcels with `JV`, `AV_NSD` and `DOR_UC` populated.

**What was built:** `ArcGisAdapter` with `FDOR_LAYER` configuration and an `acquire_county()` path that scopes by FDOR county code. All 67 counties now have an implemented adapter in `data/fl_acquisition_map.csv` — up from zero before this phase.

**What was preserved:** the adapter reuses `enrich_property_details.py`'s documented field mapping (`JV` → `market`, `AV_NSD` → `assessed`, `ASMNT_YR` → `value_year`) and its 0-as-no-data sentinel rule. Two tests assert agreement against that script's own source text, including the full 67-entry county-code table, so the adapter and the production script cannot drift apart silently.

### A correction worth recording

`SOURCE_REGISTRY`'s `fl_dor_statewide` entry records the source URL as `floridarevenue.com/dataPortal/Pages/default.aspx`. **That page no longer lists any datasets** — fetched 2026-09-16, it now returns general program descriptions only. The real Property Tax Data Portal is at `floridarevenue.com/property/dataportal/Pages/default.aspx` (NAL-DBF tax-roll folders, per-year user guides).

The registry entry was **not** edited this phase — changing a source record is a governance action, and nothing about this finding changes that source's `LEGAL_REVIEW_REQUIRED` status. It is recorded here and in the Phase 39 report as a concrete, cheap correction for a future governance pass.

## 2. Authorization remains exactly where Phase 37/38 left it

Nothing in this phase changed any Florida source's legal status.

| Source | Technical state after Phase 39 | `CUSTOMER_DISPLAY` production status |
|---|---|---|
| `fl_dor_statewide` | `TECHNICAL_ACQUISITION_READY` (adapter built, contract verified) | **Denied** — `LEGAL_REVIEW_REQUIRED` |
| `fl_realauction` | `TECHNICAL_ACQUISITION_SUCCESS` (existing production harvester) | **Denied** — every one of its ~46 counties |
| `fl_lienhub_certificates` | `TECHNICAL_ACQUISITION_SUCCESS` (existing production harvester) | **Denied** — provider-wide record, `LEGAL_REVIEW_REQUIRED` |
| `fl_laft_pdfs` | `TECHNICAL_ACQUISITION_SUCCESS` (existing production harvester) | **Allowed** — no authorization record, pre-existing no-op path |

`fl_dor_statewide` is the clearest illustration of the five-layer model working: this phase moved it from `NOT_ACQUIRED` to `TECHNICAL_ACQUISITION_READY` — real engineering progress, a real adapter, a real verified contract — and its production status did not move an inch. Internal technical testing against it is permitted (no prohibition has been found; the open question is commercial); production acquisition is refused.

## 3. Mechanisms across the 67 counties

| Mechanism | County-source rows | Adapter implemented |
|---|---|---|
| `ARCGIS_REST` (FDOR statewide) | 67 | **Yes** |
| `HTML_PUBLIC_SEARCH` (RealAuction, LienHub) | 112 | No — blocker is legal, not technical |
| `DOCUMENT_PDF` (LAFT) | 47 | No — working production harvester already exists |

## 4. Remaining Florida gaps

Unchanged from Phase 37/38 except where noted:

- **35 of 67 counties have no LAFT harvester coverage.** Unchanged.
- **55 of 67 counties have no individually-verified Property Appraiser page.** The FDOR adapter is the intended answer to this — it supplies assessment data for all 67 counties from one layer — but it cannot be used for production until its authorization question is resolved.
- **No auction-event history model** exists in the schema; a postponed or re-offered sale still overwrites the prior row. Unchanged, and out of scope this phase (no schema changes).
- **The FDOR bulk-download path** (NAL/NAP/SDF files) remains unverified. The ArcGIS path to the same source was verified and implemented instead; the bulk path would give history and full-roll access the query API does not, and is worth a future pass now that the correct portal URL is known.

## 5. What a production Florida acquisition run would need

1. An environment with outbound access — GitHub Actions, where the Florida harvesters already run.
2. Resolution of `fl_dor_statewide`'s authorization question, or an explicit decision to run it under `INTERNAL_TECHNICAL_TESTING` for internal verification only, with results kept out of the customer-facing tables.
3. A decision about pagination volume: the layer holds every parcel in Florida, so a full-state pull is a materially larger job than the per-parcel enrichment `enrich_property_details.py` does today. The adapter emits resumable checkpoints (`county` + `offset`) for exactly this reason.
