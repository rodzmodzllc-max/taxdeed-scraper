# Florida source coverage — 67 counties

**Status:** Phase 33, 2026-09-15. Machine-readable matrix: `data/fl_county_coverage_matrix.csv` (67 rows, one per county, built programmatically from the CSVs this project's own harvesters already use — `data/realauction_counties.csv`, `data/florida_certificate_sale_platforms.csv`, `data/laft_pdf_sources.csv`, `data/laft_html_sources.csv`, `data/laft_pioneer_counties.csv`, `data/laft_realtdm_counties.csv` — not re-researched by hand, so every cell traces to a CSV row this project already verified live in a prior phase). This page is the narrative summary; the CSV is the source of truth for per-county detail.

## Real counts (from the matrix, not estimated)

- **67/67 Florida counties** have a row in the matrix (every county represented; `UNKNOWN` is an explicit value, never a blank cell, per Phase 33 Section 53).
- **66/67 counties** have at least one known category source (auction, tax-certificate, or LAFT). Only **DeSoto** has zero known sources — its LAFT PDF went dead when the county migrated off PDF publishing (`claude/laft-pdf-harvester-audit.md`); no replacement source has been found.
- **46/67 counties** have a known auction (tax deed sale) source — `fl_realauction`, per `data/realauction_counties.csv`.
- **66/67 counties** have a known tax-certificate-sale source — `fl_lienhub_certificates`/other platforms, per `data/florida_certificate_sale_platforms.csv`.
- **47/67 counties** have a known LAFT (Lands Available for Taxes) source, across four distinct platform families (static PDF, native HTML, Pioneer TaxSmart, realTDM) — see `docs/auction-source-policy.md` and the four `data/laft_*.csv` files.
- **All 67 counties** are covered by one statewide GIS/parcel source, `fl_dor_statewide`'s sibling dataset the FDOR Statewide Cadastral FeatureServer (`claude/parcel-enrichment-and-gis-plan.md`) — one source, not 67 separate ones, per Phase 33 Section 23's coverage-representation rule.

## Legal status of what's covered

Every one of the sources above is registered in `harvesters/governance/registry.py`. Three (`fl_realauction`, `fl_lienhub_certificates`, `fl_laft_pdfs`) are `APPROVED` but **grandfathered** — long-standing production sources that predate the governance framework and have never had a Phase-9.5-style formal rights audit performed on them specifically. This is Florida's real, honestly-flagged gap: technical coverage is excellent, but *none* of the three production-driving Florida sources has the kind of terms-of-use/robots.txt review Phase 10B gave `tx_lgbs` and `tx_realauction`, or Phase 8/9/9.5 gave Harris County. The fourth Florida source, `fl_dor_statewide` (new this phase), got that review immediately upon being registered and sits honestly at `LEGAL_REVIEW_REQUIRED` — free, official, no restriction found, but no permission found either.

## What's not covered (recorded_document_source, public_record_request_source columns; property_appraiser now partially covered)

**Updated Phase 35 (2026-09-15):** the `property_appraiser_name`/`property_appraiser_url` columns are no longer blanket-`UNKNOWN` — 12 of 67 counties (the highest-population ones: Miami-Dade, Broward, Palm Beach, Duval, Hillsborough, Orange, Pinellas, Lee, Polk, Brevard, Volusia, Pasco) now carry an individually verified official Property Appraiser website, and the remaining 55 carry `MECHANISM_CONFIRMED_NOT_EXTRACTED` — Florida DOR's `LocalOfficials.aspx` statewide directory was confirmed live to cover all 67 counties via dropdown menus, just not extracted per-county this phase. The recorded-document/Clerk source and public-records-request columns remain entirely `UNKNOWN` — Florida Court Clerks & Comptrollers' own directory (`flclerks.com`) was located but not extracted this phase either. See `docs/data-completeness.md` for the full, current numbers and `claude/phase-35-county-source-of-truth-catalog.md` for the complete Phase 35 findings. See [Gap analysis](#gap-analysis-carried-into-the-phase-33-report) below for what was originally found in Phase 33.

## Gap analysis (carried into the Phase 33 report)

1. **No formal rights audit exists for any of the three grandfathered Florida production sources.** This is the single largest Florida-specific finding of this phase.
2. **DeSoto County has no known live source in any category.**
3. **21 of 67 counties have no known auction source**; 20 of 67 have no known LAFT source. Whether that reflects "no source exists" or "no one has looked yet" is itself unknown per-county — Phase 33 does not collapse those into one bucket (Section 25: `NOT_AVAILABLE` vs. `SOURCE_NOT_FOUND` vs. `UNKNOWN` remain distinct).
4. **Property Appraiser / Clerk / public-records-request sources are entirely unmapped** at the individual-county level.
