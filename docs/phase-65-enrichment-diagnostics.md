# Phase 65: Enrichment Diagnostics & Probe Execution Framework

**Status:** Diagnostic and probe infrastructure complete. Baseline measurements pending.

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
