# Data completeness — Florida and Texas county coverage

**Status:** Phase 35 (County Source-of-Truth Catalog), 2026-09-15. The current, authoritative completeness statement for both states' county-source catalogs. Numbers below are computed live by `harvesters.governance.source_catalog.gap_analysis()` against the real CSVs (`data/fl_county_coverage_matrix.csv`, `data/tx_county_coverage_matrix.csv`) — not estimated, and re-checked by `tests/python/test_source_catalog.py::test_gap_analysis_counts_are_internally_consistent` on every test run so this page cannot silently drift from the data.

## Florida (67/67 counties represented)

| Metric | Count | Source |
|---|---|---|
| Counties with a row in the matrix | 67 / 67 | Phase 33 |
| Counties with a known auction (tax deed sale) source | 46 / 67 | Phase 33 (`fl_realauction`) |
| Counties with a known tax-certificate-sale source | 66 / 67 | Phase 33 (`fl_lienhub_certificates`/other) |
| Counties with a known LAFT source | 47 / 67 | Phase 33 |
| Counties with an individually verified Property Appraiser website | 12 / 67 | **Phase 35** (Miami-Dade, Broward, Palm Beach, Duval, Hillsborough, Orange, Pinellas, Lee, Polk, Brevard, Volusia, Pasco) |
| Counties with zero known source in any category | 1 / 67 | Phase 33 (DeSoto) |

**What Phase 35 changed for Florida:** before this phase, `property_appraiser_source`/`recorded_document_source`/`public_record_request_source` were `UNKNOWN` for all 67 counties, with no lead at all. Phase 35 (1) individually verified the Property Appraiser website for the 12 highest-population counties via live web research, and (2) confirmed that Florida DOR's `floridarevenue.com/property/Pages/LocalOfficials.aspx` is a real, existing statewide directory covering Property Appraiser/Tax Collector/Value Adjustment Board links for all 67 counties — but implemented as dropdown menus, not a bulk-listable static page, so the remaining 55 counties' specific destination URLs were not extracted this phase (recorded as `MECHANISM_CONFIRMED_NOT_EXTRACTED`, never left as a bare, lead-less `UNKNOWN`). The Clerk of Court / recorded-document and public-record-request columns remain fully unmapped at the individual-county level — Florida Court Clerks & Comptrollers' own directory (`flclerks.com`) was located but not extracted this phase either, for the same reason (interactive lookup, not a bulk list).

## Texas (254/254 counties represented)

| Metric | Count | Source |
|---|---|---|
| Counties with a row in the matrix | 254 / 254 | Phase 33 |
| Counties with a known auction/tax-sale source of any kind | 42 / 254 | Phase 33 (RealAuction 24, LGBS-named 8, GovEase 4, MVBA 9, with overlaps) |
| Counties with a generated, verified Texas Comptroller county-directory URL | 254 / 254 | **Phase 35** (deterministic URL pattern, live-verified against 3 test cases before generating the rest) |
| Counties with an individually verified Appraisal District + Tax Assessor-Collector website | 42 / 254 | **Phase 35** (every county already referenced by this project's existing RealAuction/LGBS/GovEase/MVBA data) |
| Counties with zero known source in any category | 212 / 254 | Phase 33/35 (unchanged — Phase 35 did not newly discover an auction source for any additional county) |

**What Phase 35 changed for Texas:** before this phase, `tx_comptroller_directory` was `DISCOVERED` as a mechanism only — 0 of 254 counties had an actual extracted URL. Phase 35 (1) confirmed the exact, deterministic slug formula the Comptroller's site uses (lowercase county name, spaces and punctuation removed — verified live against Harris, El Paso, and Fort Bend before being applied to the other 251), so every one of the 254 counties now has a real, generated (not fabricated — pattern-verified) directory-page URL, and (2) individually fetched and verified the actual Appraisal District and Tax Assessor-Collector website for the 42 counties this project's own existing vendor data (RealAuction, LGBS, GovEase, MVBA) already names. The other 212 counties' actual appraisal-district/tax-office destination websites were not individually extracted this phase — the directory *mechanism* to find each is confirmed and generated, but the specific destination link behind each was not fetched.

## What "verified" means here, precisely

A cell marked `VERIFIED_PHASE35` means a live fetch or search was performed this phase against the actual government source and the resulting name/URL was transcribed directly from that response — not inferred, not guessed from a naming convention, and not copied from a third-party aggregator. Every Texas Comptroller fetch this phase used the real `comptroller.texas.gov` domain directly; every Florida property-appraiser lookup was checked against multiple search results to avoid the SEO-clone sites (e.g. `*propertyappraiser.org`/`*propertyappraisers.us` domains that mimic a county's real name but are not government-run) that appeared alongside genuine results for several counties during this phase's own research — a real, concrete instance of exactly the risk Phase 35 Section 6's "do not invent URLs" instruction exists to prevent, and a reason the unverified 55 Florida / 212 Texas counties were left `UNKNOWN`/`MECHANISM_CONFIRMED_NOT_EXTRACTED` rather than filled in from a guessed domain pattern.

**"Verified" here means "we found the right website." It does not mean "we reviewed its Terms of Use" and it does not mean any use of that source is authorized.** No cell this phase populated carries any status beyond `DISCOVERED`/`MECHANISM_CONFIRMED_NOT_EXTRACTED` — none is `LEGAL_REVIEW_REQUIRED` (that would imply a terms review actually happened) and none is `APPROVED`/`APPROVED_WITH_RESTRICTIONS`. See `docs/state-onboarding.md` for what a real promotion past this stage requires.

## Category coverage gaps (Phase 35 Section 14)

No source discovered this phase was assumed to provide every category it might plausibly touch. A Texas Appraisal District website provides parcel/APN, address, legal description, acreage, and assessed/market value; it does not provide auction date, opening bid, case number, or sale status (those live with the county's separate tax-sale/foreclosure process, which for most of the 212 not-yet-mapped counties is entirely unknown). A Florida Property Appraiser site provides the same assessment-side categories; it does not provide tax-certificate or tax-deed-auction data (those are `fl_lienhub_certificates`/`fl_realauction`'s domain, already tracked separately). This distinction is preserved in the matrix by keeping `property_appraiser_*`/`appraisal_district_*` as separate columns from `auction_source`/`tax_certificate_source`, never merged into one "does this county have data" flag.

## What Phase 35 explicitly did not attempt

- Extracting the true LGBS county roster beyond the 8 already named in prior reconnaissance, the PBFCM 11-county list, or GIS/recorded-document/public-record-request sources for any county.
- Any Terms-of-Use or robots.txt review for any of the 54 newly-identified sources (12 Florida + 42 Texas) — every one of them sits at `DISCOVERED`, not `LEGAL_REVIEW_REQUIRED`, precisely because that review has not happened.
- Extracting the remaining 55 Florida / 212 Texas counties' destination URLs — the mechanism to find each is now confirmed and (for Texas) generated; the individual fetch was not performed for time/scope reasons this phase, not because the mechanism doesn't exist.
- Any automated access, harvesting, or scraping of anything catalogued here (Phase 35 Section 19's explicit prohibition).

See `claude/phase-35-county-source-of-truth-catalog.md` for the full phase report and Section 17/Section 22's exact recommended next phase.
