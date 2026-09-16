# Texas data map (254 counties)

**Status:** Phase 37/38, 2026-09-16. Computed directly from `data/tx_county_coverage_matrix.csv` (Phase 33/35) and `harvesters/governance/verification.py`/`data/tx_verification_map.csv` (this phase). See `docs/two-state-data-architecture.md` for the five-state vocabulary.

## 1. County readiness (Section 22 vocabulary), all 254/254 counties

| Readiness state | Count |
|---|---|
| `SOURCE_DISCOVERED` | 212 |
| `PRODUCTION_READY` (real, currently-allowed `tx_lgbs`/`tx_realauction` `CUSTOMER_DISPLAY` decision) | 29 |
| `PARTIALLY_COVERED` | 13 |
| `NO_SOURCE_IDENTIFIED` | 0 |

**Texas's heterogeneity (Section 9), stated numerically**: 212 of 254 counties have ONLY the Comptroller's directory-mechanism entry (a real, live, per-county URL pattern - `SOURCE_DISCOVERED` under this document's vocabulary, since the mechanism is confirmed but no per-county appraisal-district/tax-assessor page has actually been extracted or reviewed) and no named auction source at all. This is the expected shape for Texas, explicitly warned against being treated as uniform (Section 9's own tree-diagram illustration) - unlike Florida's single dominant vendor pattern, most Texas counties genuinely have no auction-source finding on file yet.

## 2. Source coverage by category (existing Phase 35 `gap_analysis()`, unchanged this phase)

| Category | Counties with a known source |
|---|---|
| Auction (`tx_lgbs`/`tx_realauction`/named third parties) | 42 / 254 |
| Appraisal district (individually verified via Comptroller directory) | 42 / 254 |
| Comptroller directory URL generated (mechanism only, every county) | 254 / 254 |
| No known source in any category beyond the directory mechanism | 212 / 254 |

## 3. Production status of Texas's two registered, ingesting sources, today

| Source | Verification | Technical acquisition | Authorization records | `CUSTOMER_DISPLAY` production status |
|---|---|---|---|---|
| `tx_lgbs` | `CONTENT_VERIFIED` | `ACQUIRED` (production, manual `workflow_dispatch` only - no cron schedule, `docs/production-data-contract.md` Section 20) | None | **Allowed** (unmodified no-op path) |
| `tx_realauction` | `CONTENT_VERIFIED` | `ACQUIRED` (same freshness caveat) | None | **Allowed** (unmodified no-op path) |

Neither Texas source has a `ProviderAuthorization` record on file - both remain on Phase 37's existing, unmodified no-op production path, exactly as before this phase. **This phase changed neither Texas source's status or behavior.**

## 4. Blocked/unresolved Texas sources - preserved exactly, re-verified not re-decided (Section 10/38)

| Source | Registry status | Technical state (this phase's re-inspection) |
|---|---|---|
| `tx_hctax` (Harris County) | `LEGAL_REVIEW_REQUIRED` | Technically ready (single-GET HTML page); no `harvest_hctax()` exists |
| `tx_pbfcm` | `BLOCKED` | `harvest_pbfcm()` remains an architectural stub |
| `tx_mvba` | `BLOCKED` | No harvester exists |
| `tx_ctsa` | `BLOCKED` | Paywalled; republishes `tx_hctax`'s own data |
| `tx_govease` | `BLOCKED` | **Re-confirmed this phase, by direct source read**: `harvest_govease()` at `harvesters/texas_harvester.py` line 973 still raises `NotImplementedError` - the county-slug/ID enumeration and rendered-HTML-vs-JSON-API questions are still open, exactly as `registry.py`'s own notes already stated. (This phase's inspection resolved a genuine open question from the prior session about whether this note had gone stale - it had not.) |

None of these five statuses were changed. No new harvester was written for any of them.

## 5. Preserved existing implementations (Section 10, verified by direct re-read this phase)

- `harvest_lgbs()` - confirmed still a real, live integration against `taxsales.lgbs.com/api/property_sales/`. Not reverted, not modified.
- `harvest_realauction()` - confirmed still real, covering 24 TX county deployments. Not modified.
- `scripts/enrich_property_details_tx.py` - re-read in full this phase. **More real than its own top-of-file "non-working stub" framing in `docs/production-data-contract.md` suggests**: it contains genuine, live-confirmed per-CAD fetchers for Harris County (HCAD, an unauthenticated ArcGIS REST endpoint) and Tarrant County (TAD, richer than HCAD's), plus partially-verified paths for Bexar (valuation-rich, classification fields unsampled) and known dead ends for Dallas (no single rich source; a two-source join would be needed) and Travis (geometry-only, no valuation). This project's own file already documents this per-CAD variance honestly; this phase changes nothing in it, only surfaces the finding here so it is not lost in a script comment.

## 6. Known Texas gaps (none newly invented this phase)

- 212 of 254 counties have no auction source of any kind on file.
- No confirmed statewide CAD-equivalent to Florida's FDOR exists - `enrich_property_details_tx.py`'s own header documents this as the single biggest open architectural question for Texas enrichment.
- Both production Texas sources run on manual `workflow_dispatch` only, not a schedule - a materially different freshness guarantee than any Florida source.
- `tx_comptroller_directory`'s 254-row per-county extraction (appraisal district name/URL/tax assessor-collector name/URL) is only 42/254 complete (Phase 35, unchanged).

See `data/tx_verification_map.csv` for the full 765-row machine-readable detail this document summarizes.
