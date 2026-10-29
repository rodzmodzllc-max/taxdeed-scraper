# Phase 65: Enrichment Diagnostics & Probe Execution Framework

**Status:** Diagnostic and probe infrastructure complete. Baseline measured and probes executed 2026-09-18 (push-triggered on a probe branch; see Evidence below).

**Scope:** Enrichment coverage audit, read-only evidence probe for blocked enrichment routes, and setup for targeted enrichment improvements.

## Problem Statement

Enrichment coverage for auction + LAFT/OTC rows is stuck at **57.7%** (1,440 / 2,494 rows enriched). The blocking issues are:

1. **Florida (3 counties, 201 rows):** Identifier mismatch
   - Hillsborough: 132 unenriched rows
   - Brevard: 49 unenriched rows
   - Suwannee: 20 unenriched rows
   - **Issue:** We store county account numbers; FDOR FeatureServer is keyed on PARCEL_ID
   - **Possible fix:** FDOR layer also returns ALT_KEY; if ALT_KEY equals our stored account number for these counties, we can enrich via ALT_KEY → PARCEL_ID mapping

2. **Texas (Galveston, 203 rows):** No enrichment implemented
   - Galveston's esearch portal disallows `/Search/` and `/Property/` via robots.txt
   - CAD publishes a Parcel DBF export with unknown field richness
   - **Possible fix:** Parse published Parcel DBF to extract appraisal attributes

3. **Other counties:** Enrichment script not yet run in production workflow
   - Harris County (HCAD): Working enrichment code verified
   - Tarrant County (TAD): Working enrichment code verified
   - Bexar County (BCAD): Code pending one verification step
   - Dallas County (DCAD): Needs two-source join investigation
   - Travis County (TCAD): Needs different source investigation

## New Tools Created

### 1. Enrichment Coverage Audit (`scripts/audit_enrichment_coverage.py`)

**Purpose:** Establish baseline measurements of enrichment coverage.

**What it does:**
- Fetches all properties from the database (read-only)
- Computes enrichment statistics by source, state, and county
- Reports field-level population percentages
- Generates JSON and markdown reports

**Outputs:**
- `out/enrichment_audit.json` - machine-readable statistics
- `out/enrichment-audit.md` - human-readable summary with visualizations

**Run via:** Manual workflow dispatch on `audit-enrichment-coverage.yml`
(its own workflow, deliberately NOT a job inside `harvest-and-sync.yml` -
that workflow's `workflow_dispatch` runs every harvest job under one
concurrency group, so "take a baseline" would also mean "run the whole
production harvest").

**Metrics reported:**
- Headline: `fdor_enriched_at` coverage across `auction` + `laft` only
  (certificates are a lien instrument, not a parcel - reported separately,
  excluded from the headline)
- By source (auction/laft/certificate): count, % enriched, and per-field
  population within that source
- By state (FL/TX): coverage statistics
- By county, keyed `state/source/county` so "Harris" TX auction and
  "Harris" TX laft are two rows, not one: unenriched counts (priority
  targets)
- By field: % population (market, assessed, owner_name, etc.). `''` is
  treated as empty - this matters for `photo_url`, whose `''` means
  "checked, no Street View coverage" (see CLAUDE.md), not "has a photo".

**Tests:** `tests/python/test_enrichment_coverage_audit.py` (no network, no
database) - pins the headline's source scope, the `''`-is-empty rule, the
per-state/source county keying, the REST paging loop, and that the workflow
stays manual-only with `contents: read`.

### 2. Enrichment Source Probe (`scripts/probe_enrichment_sources.py`)

**Purpose:** Gather evidence on whether blocked enrichment routes are viable.

**Read-only by construction:**
- Only GET requests (no POST/PATCH/PUT/DELETE)
- No schema access, no writes to properties table
- Single source reference is a `?select=parcel` read scoped to `source in (auction,laft)`

**What it tests:**

#### Florida - ALT_KEY Mapping (Hillsborough, Brevard, Suwannee)
- Fetches PARCEL_ID + ALT_KEY from FDOR published dataset for each county
- Tests whether ALT_KEY values match our stored account numbers
- Measures join determinism (1:1 vs 1:many)
- Reports exact match rate and ambiguity count

#### Texas - Galveston Parcel DBF
- Downloads published Parcel DBF from Galveston CAD's GIS page
- Parses DBF header to report actual field list
- Identifies presence/absence of appraisal attributes (value, year built, owner, etc.)

**Outputs:**
- `out/probe_enrichment_sources.json` - machine-readable evidence
- `out/probe-evidence.md` - human-readable verdict on each blocked route

**Run via:** Manual workflow dispatch on `probe-enrichment-sources.yml`

**Guarantees:**
- 100% read-only by construction, not convention
- Safe to run against production database
- No secrets or credentials exposed
- Fails safely if credentials are missing

## Workflow Updates

Two new standalone workflows, both `workflow_dispatch` only (no schedule),
both `permissions: contents: read`, neither touching `harvest-and-sync.yml`:

### `audit-enrichment-coverage.yml`
- Runs `scripts/audit_enrichment_coverage.py`
- Produces baseline statistics, echoed to the run's step summary
- Uploads artifact: `enrichment-audit-{run_id}` (30-day retention)

### `probe-enrichment-sources.yml`
- Runs `scripts/probe_enrichment_sources.py`
- Gathers evidence on blocked routes, echoed to the run's step summary
- Uploads artifact: `enrichment-source-evidence` (30-day retention)

## Next Steps (in Priority Order)

### Immediate (Once Measurements Are Gathered)

1. **Run the audit** to see current baseline
   - GitHub Actions → "Audit enrichment coverage (READ-ONLY)" → Run workflow
   - Review `enrichment-audit.md` to identify which counties/fields have highest impact

2. **Run the probe** to verify ALT_KEY and Galveston viability
   - GitHub Actions → probe-enrichment-sources workflow → workflow_dispatch
   - If ALT_KEY is 1:1 match, implement targeted enrichment for 3 FL counties
   - If Galveston DBF has appraisal fields, parse and enrich

### Phase 66+ (Likely Implementation)

- **If ALT_KEY probe succeeds:** Implement supplementary enrichment for Hillsborough/Brevard/Suwannee via ALT_KEY lookup
- **If Galveston DBF is viable:** Implement Texas enrichment for Galveston as a proof-of-concept
- **Activate existing code:** Wire up HCAD/TAD enrichment in production workflow (already verified live)
- **Investigate Dallas/Travis:** Run targeted research on per-CAD enrichment strategy

## Schema Dependencies

All enrichment improvements depend on these existing migrations:
- `schema-v8-geocoding.sql` - latitude/longitude fields
- `schema-v9-dor-use-code.sql` - dor_use_code field
- `scripts/migrations/009_fdor_verified_field_expansion.sql` - fdor_alt_key + sale/owner fields
- `scripts/migrations/010_flood_hazard.sql` - flood_zone/flood_sfha fields
- `scripts/migrations/011_property_photos_naip.sql` - photo URLs (aerial)

No new migrations are needed for this phase - only diagnostic/evidence gathering.

## Guarantees & Limitations

### What Works Today
- Florida FDOR enrichment for ~58% of auction/LAFT rows
- Santa Rosa and Flagler county-specific fallbacks
- US Census Bureau geocoding for any parcel with an address
- FEMA flood zone lookup via lat/lon
- USDA NAIP aerial imagery caching
- Harris/Tarrant County (TX) enrichment code (verified, not yet in workflow)

### What's Blocked
- Florida account-number counties (Hillsborough/Brevard/Suwannee) - waiting on probe results
- Texas enrichment beyond Harris/Tarrant - waiting on CAD research
- Property photos (Street View) - waiting for Google Maps API key
- Tax amounts, liens, judgments - no source discovered yet
- Bedrooms, bathrooms, zoning - not available in FDOR NAL

## Measurement Plan

**Baseline (Once Audit Runs):**
- Overall % enriched (target: improve from 57.7%)
- Field-by-field coverage (which enrichment fields are most/least populated)
- County-by-county unenriched count (identifies priority targets)
- Source-specific coverage (auction vs LAFT vs certificate)

**After-Fix Measurement (Once Probe + Implementation Complete):**
- Rerun audit to measure improvement
- Expected gains if ALT_KEY succeeds: +201 rows from 3 FL counties
- Expected gains if Galveston succeeds: +203 TX rows (if DBF has appraisal fields)

## Documentation References

- `docs/fdor-field-provenance.md` - authoritative source of each FDOR field meaning
- `claude/parcel-enrichment-and-gis-plan.md` - overall enrichment architecture
- Phase 51-62 sections in `CLAUDE.md` - frontend redesign context (photos, coordinates, property details)


## Evidence (2026-09-18, Actions runs 35404152650 / 35405458491)

All read-only. Artifacts: `enrichment-evidence-branch` on those runs.

### Coverage baseline

- Audit script output matched the direct SQL baseline exactly: **1,458 / 2,500
  auction+LAFT rows enriched (58.3%)** before the LAFT junk-row cleanup;
  **1,458 / 2,495 (58.4%)** after it (5 parser-artifact rows removed, see
  `scripts/migrations/013_remove_laft_header_rows.sql`).
- By source: auction 1,325/1,921 (69.0%), LAFT 133/574 (23.2%), certificate
  658/1,667 (39.5%, reported, not in the headline). TX: 0/531.

### FL account-number counties (Hillsborough 132, Brevard 49, Suwannee 20) - FDOR query behaviour

- County-wide pulls from the FDOR FeatureServer are not a route: `returnIdsOnly`
  and `resultOffset` paging return HTTP 400 for Hillsborough, Suwannee, Citrus
  and Hernando; Brevard paged to 26,000 records and then 400.
- Inside that Brevard slice, **6 of 6 reachable stored accounts matched
  `ALT_KEY` 1:1** (`2102746 -> 21 3507-01-3-12`, `2103356 -> 21 3517-00-315`,
  ...). Brevard's stored "parcel" is therefore FDOR's `ALT_KEY`.
- Direct per-key lookup is refused: `ALT_KEY` is `esriFieldTypeString` and both
  `ALT_KEY=2102746` and `ALT_KEY='2102746'` return HTTP 400 even for that
  proven key. The FeatureServer only answers exact `PARCEL_ID` filters.
- **Classification:** FDOR identifier mismatch (we hold the account/ALT_KEY,
  the layer is keyed on PARCEL_ID) + FDOR query behaviour (no ALT_KEY filter,
  no county scan). Not fixable in `enrich_property_details.py`. The route
  that remains is the same agency's bulk tax-roll download (FDOR NAL files,
  which carry both `PARCEL_ID` and `ALT_KEY`), a new source that the
  governance framework requires a human to promote (`docs/provider-authorization.md`).

### Citrus (25) and Hernando (25) - no parcel published, appraiser key captured

- Live RealAuction blocks (run 35402576827) show no `Parcel ID` field on either
  skin: Citrus publishes `Alternate Key` (e.g. 1028868, linking to
  citruspa.org `pin=1028868`), Hernando `Parcel Key` (e.g. 00190947, linking to
  propsearch.hernandocountypa-florida.us/parcel/00190947). PR #18 captures the
  appraiser link into `url_appraiser` (0 -> 50 rows on the next deeds sync)
  and the key as `alt_key` in the harvest artifact, never as a parcel.
- Those keys do not resolve through FDOR either (same ALT_KEY refusal above):
  10/10 live keys per county, 0 hits. **Classification:** source limitation
  (no parcel number on the listing) + FDOR query behaviour. Parcel stays
  empty; the card keeps saying "parcel # not published".

### TX Galveston (183 LAFT + 20 auction) - viable on data, gated on governance

- Galveston CAD publishes `parcels.zip` (47.6 MB, 190,731 records, 26 fields)
  with `GEOID`, `PID`, `NAME`, `SITUS`, `LEGAL`, `ACRES`, `LANDUSE`, `EXEMPT` and
  `VAL26LAND` / `VAL26IMP` / `VAL26TOT`. The first probe run's `NOT_VIABLE`
  verdict was a keyword-heuristic false negative (fixed).
- Our stored Galveston `case_no` (the CAD account from LGBS / RealAuction) is
  the Geo ID without dashes: **195 of 203 stored accounts match a DBF `GEOID`
  digits-only** (2 ambiguous, 8 unmatched), e.g. `000200320000000 ->
  0002-0032-0000-000`, PID 131618, 810 WESTWARD AVE LA MARQUE, land/imp/total
  24,910 / 233,250 / 258,160.
- **Not implemented.** `data/tx_county_coverage_matrix.csv` records Galveston
  CAD as DISCOVERED with no Terms-of-Use/robots review and "automated
  ingestion not authorized by this entry", and `harvesters/governance` denies
  every production use for a discovery-only source by construction. Promoting
  it is a human-reviewed registry change. What the evidence supports, once
  authorized: a fill-blanks-only enrichment (market = VAL26TOT, land_value,
  improvement_value, value_year 2026, acreage, lot_sqft, legal_desc, land_use,
  owner_name) keyed on GEOID digits, stamped with its own `*_enriched_at`
  column and `field_provenance` entries naming the CAD file and vintage.
- Liberty (113) and Leon TX (84): same LGBS account-number identity; no CAD
  publication checked yet - same governance path applies before any check
  becomes a pipeline.

### FL counties with the same parcel shape as their matched rows - per-county classification

`scripts/probe_fl_parcel_formats.py` (probe branch, Actions runs 35406185583 and
35407266083) asked the layer, for live unenriched parcels: exact match with the
production candidate rules, `LIKE` on the value itself, and `LIKE` on a short
prefix to reveal the county's real `PARCEL_ID` shape.

| County | Unenriched rows | Finding | Classification | Action |
|---|---:|---|---|---|
| Lake | 10 | layer holds `01-19-26-1000-00C-01900`; we store `01-19-26-100000C00600` (4-3-5 tail) | parcel normalization | rule added, **6/6 exact hits** |
| Leon | 31 | layer holds `411137  C0050` (13-wide, tail right-aligned); we store `411137C0180` | parcel normalization | rule added, **8/8 exact hits** incl. `110250 CD0150` |
| Citrus (LAFT) | 5 | layer holds `19E17S25      3B000 0320` (section block ljust 8); we store `19E17S35 2B0E0 0330` | parcel normalization | rule added, **5/5 exact hits** |
| Escambia | 21 | 5/5 sampled rows hit exactly with existing rules | backlog (per-run quota) | none needed |
| Volusia (auction) | 43 | 6/6 sampled auction rows hit exactly; LAFT samples have no block neighbours | backlog; a few LAFT parcels absent from the layer | none needed |
| Miami-Dade | 43 | misses' subdivision blocks contain exactly one layer parcel ending `-0001` (condo master); unit folios absent; dash-stripped form still hits non-condo rows | source limitation (cadastral polygon layer omits condo units) | none possible via this layer |
| Pasco | 8 | 19-char dashless values (`16263101100060000A0`); the 2-2-2-4-5-4 re-dashing that matches its 41 enriched rows gives 0/6 hits | unresolved (identifier shape) | rule tried and removed |
| Lee | 59 | STRAPs with numeric area codes (`14-44-27-12-…`) have no layer rows under `14442712%`; alnum-area STRAPs (`07-45-27-L1-…`) hit | unresolved (layer encodes numeric-area STRAPs differently or omits them) | needs one more targeted query |
| Pinellas | 11 | no layer rows under any section/township/range order, dashed or not | unresolved (layer shape unknown) | needs a contains-LIKE on the subdivision number |
| Hillsborough / Brevard / Suwannee | 201 | stored value is the appraiser account (= FDOR `ALT_KEY`, proven for Brevard); layer refuses ALT_KEY filters and county scans | FDOR identifier mismatch + query behaviour | bulk NAL route, governance-gated |
| Citrus / Hernando (auction) | 50 | no parcel published on the listing; appraiser key captured (PR #18) | source limitation | parcel stays empty, appraiser link added |
