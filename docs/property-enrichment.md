# Property-enrichment sprint (2026-10-01)

Branch `feat/property-enrichment`, stacked on PR #59 (`feat/five-state-enrichment`).

Main was still `aba5c68` when this sprint started. PR #59 is open and not
merged; its sync fixes are already what production runs.

**Production states (`states.PRODUCTION_STATES`):** FL, TX, LA, MI, WY, SC,
CO, WI. AL and AR are registered but gated. They were not activated: that
would be an unapproved state activation.

## 1. What was implemented

### Shared infrastructure

**`scripts/enrichment_units.py`.** The FEMA flood and NAIP imagery backfills
now work in (state, county) units instead of county names alone. Before,
names like York, Douglas and Albany merged several states into one capped
slice. The variable `ENRICH_STATE` narrows a run to some states.

**Manual `job=enrich` dispatch** (input `enrich_states`). A matrix over
`flood`, `imagery` and `parcels`, with larger budgets. Never scheduled and
never part of `all`.

**NAIP storage budget guard** (`NAIP_STORAGE_BUDGET_MB`, default 950).
- The project is on the free plan, whose storage quota is 1 GB.
- The `property-photos` bucket already held 3,518 images totalling 967 MB.
- The imagery step totals the bucket first. It uploads nothing when it is
  over budget, or when the total cannot be established.
- Rows stay `photo_url IS NULL` and are retried later.
- No imagery was added this sprint. That is a deliberate stop, not a
  failure. See the audit.

**Enrichment factory (`harvesters/enrichment/parcels.py`):**
- `row_id_column`: Texas rows carry the appraisal-district account in
  `case_no`.
- `alt_id_fields`: one key that hits two different features is AMBIGUOUS.
- `transport="socrata"` (SODA datasets).
- The `numeric` id rule.
- `latest_field`: the latest tax year wins, and a tie at that year is
  ambiguous.
- Duplicate features are identified by their position in the response,
  never by their values.

**`scripts/stamp_seen.py`.** Freshness for the PowerShell-synced Florida
auction and certificate ledgers:
- `last_seen_at` is stamped only on (county, case number) pairs in that
  run's harvest file.
- It runs after the upsert and the source-health step.
- It never closes a row or removes a stamp.

**Laft job.** The time budget went from 20 to 75 minutes, and the Louisiana
lifecycle step has its own 45-minute cap. The 10,334-row East Baton Rouge
lifecycle was cancelling the job.

**Evidence capture.** `capture_state_sources.py --enrich-sources[-2|-3|-4]`
(`job=evidence`, `evidence_scope=enrich_sources*`), plus `soda_probe()` for
Socrata identifier shapes.

### New sources and evidence

**Louisiana: East Baton Rouge Tax Parcel dataset** (`la_ebr_tax_parcels`,
`data.brla.gov` view ei2c-krsr).
- Licence: Socrata licenseId PUBLIC_DOMAIN.
- Matched on `assessment_num` = the row's property number, both shaped
  999-9999-9.
- Fields: land value, fair market value and assessed value. Equal-rank
  provenance never overwrites the list's own values.
- The ArcGIS service for the same parcels states "Access Constraints:
  copyright", so it is not used.

**Louisiana: acquisition path.** The Parish Attorney's adjudicated-property
process, quoted from the City-Parish FAQ and page, is now a verified row in
`data/purchase_path_evidence.csv`.
- Purchase directly through the Office of the Parish Attorney.
- The Request to Purchase form is in the Parish Attorney's Memorandum.
- Confirm with the Sheriff first that the property is still adjudicated.
- No vendor (CivicSource) link is used.
- No phone number is attributed to the process, so the record is not
  "complete".

### Frontend

**Provenance card:**
- A `statewide_parcel` entry is labelled "Government parcel / tax-roll
  record - <dataset> (<agency>)".
- The method reads "Published by the source; attached by an exact identifier
  match (parcel # | account # = <layer field>)".
- A derived centroid says so.
- A `county_list` entry on an auction or certificate row is named "County
  tax-sale list" or "County certificate / lien list", not "Lands Available".
- Value fields are named as their source names them, never Florida's "just
  value".

**Enriched certificates** now get the full provenance card. Before, they
showed only one line.

**Fixtures:**
- `pla2`: an East Baton Rouge row with the Parish Attorney path and the
  assessor's land value.
- Playwright checks: `laEnriched` and `xsCoMarketProvenance`.

**Service worker** bumped to `tdw-shell-v61`.

### Investigated and not implemented

**TxGIO StratMap statewide parcels (TX).**
- The program page says deliverables "are placed in the public domain for
  use by ... private industry and the public".
- But the land-parcel layer credits "Various Counties, Various Vendors".
- Every query from the GitHub runners returned nothing (count None, no
  features).
- Not configured: technically unreachable, and the licence for the parcel
  layer specifically is not settled.

**Wyoming statewide parcel viewer.** Only a no-warranty disclaimer was found,
with no reuse grant. The DEQ private-parcel service returned no layers.

**Michigan county parcels.**
- Lenawee publishes only a disclaimer.
- Eaton's data sits behind a click-through licence agreement that was not
  read in full.

**York SC sale date.**
- The county's "2026 Tax Sale Information" document returned 404.
- The sale date was seen only in search results, so it was not written.
- See the audit for the 2025/2026 cycle contradiction.

**Wisconsin V12 statewide parcels.** Still UNREVIEWED (no explicit reuse
grant).

## 2. Production runs

| Run | Job | What it did |
|---|---|---|
| 36832227666 | evidence `enrich_sources` | Candidate sources, licence pages, layer fields |
| 36832233772 | laft | First Louisiana sync (10,334 rows); the lifecycle hit the old 20-minute budget |
| 36832816276 | evidence `enrich_sources_2` | StratMap lowercase probes and program terms; EBR SODA fields |
| 36835470121 | evidence `enrich_sources_3` | EBR acquisition process; assessment-number shapes |
| 36835514079 | enrich (all states) | FEMA flood backfill; imagery stopped by the storage guard; parcels (CO) |
| 36835890811 | laft | Louisiana lifecycle completed: acquisition path and freshness on every row |
| 36838395456 | evidence `enrich_sources_4` | York document returned 404 |
| 36850920406 | enrich `enrich_states=LA` | EBR land values; East Baton Rouge flood backfill |

Coverage counts are in the PR description and the sprint report.
