# Thin-states enrichment (2026-10-27)

The owner asked to enrich every property ("All"). This sprint works through the measured gaps in the thin
states. It works under the standing decisions of 2026-10-25 and 2026-10-26: collect every source now, with
legal review to follow. Those decisions are recorded as INTERIM `INTERNAL_RISK_ACCEPTANCE` permission
records, which are never permission.

No login, CAPTCHA, click-through, paywall or IP block was worked around.

Every number below is a count. No parcel id, address, owner or value was printed anywhere.

## How the numbers were measured

Measurements were taken from the development sandbox on 2026-10-27 in two ways:

- **Layer fields and fill.** Each candidate layer's own field list was read live, and its fill was counted
  on a sample.
- **Dry run.** The real adapters (`harvest_expansion.py`, `harvest_state_inventory.py`) were run with no
  database credential, producing today's list rows. The real factory then ran over those rows:
  `enrich_statewide_parcels.run_all_layers`, in dry-run, with live layer queries.

So "expected fills" means what the code would write over today's lists, minus nothing already in production.
The production gap counts in the table come from a read-only count query.

## What was added

### Factory: `harvesters/enrichment/parcels.py`

- **`composite_map`**: a text column the source publishes in parts. The parts are joined as published. A
  blank first part (the house number) means no value.
- **`no_value_patterns`**: values that mean "not published". Examples are `0 UNKNOWN <city>`, and a situs
  with no house number.
- **Shared counties**: two county layers may serve one county only when they write different columns
  (`sources.register`, `written_columns()`).

### Runner: `scripts/enrich_statewide_parcels.py --all-layers`

- It runs every cleared layer of the state, county-scoped first, over every active row of every ledger.
- `--limit N` caps the rows per layer per run. A checkpoint in `out/.harvest_cache`, cached by the job, lets
  the next run resume where this one stopped (`enrichment_queue.take_after`).
- `--dry-run` writes nothing and advances no checkpoint.
- A patch is sent only when it changes the row (`write_diff.unchanged`).
- A `Parcel <id>` placeholder counts as a missing address.

### Sync guard: `sync_state_inventory.keep_enriched_values`

This fixes a real write loop. A list column the list leaves blank, or fills with its placeholder, no longer
erases a value that another source filled. Production on 2026-10-27 had 55 Colorado rows whose
`statewide_parcel` address had been overwritten by `Parcel <id>` on every sync.

### New and extended layers (`harvesters/enrichment/sources.py`)

Every layer below matches on the row's own identifier only.

| Source id | Layer | Columns |
|---|---|---|
| `sc_horry_assessor_parcels` (new) | Horry public GIS MapServer 24, numeric PIN | acreage, legal description, assessed / market / land / improvement / taxable value |
| `sc_horry_address_points` (new) | Horry open-data AddressPoints, PIN | address (a PIN with two or more points is AMBIGUOUS) |
| `co_douglas_property_locations` (new) | Douglas County OpenData layer 5, ACCOUNT_NO, CC BY-SA 4.0 | address (from its parts), acreage, legal description |
| `co_douglas_property_improvements` (new) | Douglas County OpenData layer 8, ACCOUNT_NO, CC BY-SA 4.0 | year built (multi-building accounts are AMBIGUOUS) |
| `ok_oklahoma_county_parcels` (extended) | `location` (situs) | address; `0 UNKNOWN …` is never stored |
| `la_ebr_tax_parcels` (extended) | `physical_address`, `sum_improvement_value` (from the dataset's column definitions) | address, improvement value |
| `la_ebr_tax_roll` (extended) | `parcel_address`, tax year 2023 (blank on every record from 2024) | address |

The PR also carries PR #178, the five 2026-10-25 county layers, because they had already run in production.

## Result per gap

| Gap (production, active) | Source | Expected rows filled (dry run) | Why not more |
|---|---|---|---|
| SC Horry FLC (51 Available) | Horry assessor + address points | values on 31-32 (assessed 31, market 32, taxable 32, land 30), acreage 12, address 7 (coordinates already 32) | 19 PINs are `998…` mobile-home accounts with no parcel; most FLC parcels have no address point |
| SC Horry delinquent tax sale (2,342 auction rows, synced by the next expansion run) | same | coordinates 2,333, values 2,113, improvement 1,396, land 1,565, address 1,273, acreage 795 | 121 PINs with several address points stay AMBIGUOUS |
| SC Georgetown (1) | none | 0 | one row; no Georgetown layer configured |
| CO Douglas county-held liens (138) | Douglas locations | address 53 (the addresses the sync had erased come back and now stay), acreage / legal on the 24 OIT did not match | 85 accounts publish no house number; improvements match 0 (no buildings) |
| CO Morgan (3) | OIT (existing) | address 2 (kept by the sync guard) | |
| CO Saguache (906 auction rows) | none | 0 | the statewide OIT layer matches none of Saguache's account numbers |
| OK Oklahoma County (195) | county tax parcels `location` | address 4 | 349 of 586 county-owned parcels read `0 UNKNOWN`; values are 0 on exempt parcels and are never stored; the layer has no land-use field |
| PA Fayette (247) | none | 0 | the PASDA layer carries geometry only; address points have no parcel id (a spatial join is not an identifier match); the county's assessment site sits behind a click-through disclaimer (not bypassed) |
| LA East Baton Rouge (4,520) | tax parcels + tax roll | address 6, land use about +470, taxable about +485, legal description about +280 (existing mappings, rows not yet enriched) | parcels without an address on the adjudicated list have none on the roll either (2023 reads `N/A`); 1,231 roll records are AMBIGUOUS; no EBR dataset publishes acreage (`units` counts structures) |
| MO St. Louis (9,778) | Assessor layer 11 (existing) | none new | `LandArea` / `SQFT` have no published definition; `AprExemptLand` overlaps `AprLand` on 9,572 parcels, so its meaning is not established |
| TN Shelby (1,784) lot size | none | 0 | the portal publishes only `parcelLength` × `parcelWidth` (an area is not derived); the Assessor's GIS host answers 403; the statewide TN layer excludes Shelby |
| MI Detroit (30,560) year built | Detroit assessor (existing) | none new | 22,652 rows are vacant land; the assessor already fills every year built it publishes (1,244) |
| FL auctions / certificates | FDOR NAL (existing) | none new | `ACT_YR_BLT` → year_built, `TOT_LVG_AR` → living_area, `PA_UC` → land_use and `DOR_UC` → dor_use_code / prop_type are all mapped. The gap is identifier matching (75 of 1,611 certificates carry FDOR provenance), which open PR #180 addresses |

## Applying it after merge (writes; owner-authorized runs only)

- **Daily, automatically.** Each `expansion` leg (MI, WY, SC, CO, WI, MO, OK, PA, MN, TN) now runs
  `enrich_statewide_parcels.py --all-layers --limit 500` after its sync. The new SC and CO layers and the OK
  address fill in on the next scheduled run.
- **Backlog, parcels only.** Dispatch `job=enrich`, `enrich_kinds=parcels`, `enrich_states=SC,CO,OK,LA`.
  Optionally set `enrich_limit=<N>` for bounded overnight batches; the checkpoint resumes the next run.
- **Louisiana.** Use `job=available`, `available_mode=apply` (AVAILABLE rows; it also runs the acquisition
  and flood steps), or the `job=enrich` dispatch above with `LA`.
