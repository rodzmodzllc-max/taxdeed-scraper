# Source permissions: per-operation, dated, expiring, fail closed

**Status:** 2026-10-12. Code: `harvesters/governance/permissions.py`. Records: `data/source_permissions.csv`. CLI: `scripts/source_permission_check.py`. Tests: `tests/python/test_source_permissions.py`.

Being able to reach a source is not permission to use it. Neither is a working endpoint, a county linking to a vendor, an earlier harvest, or an `APPROVED` value in a config file. A source may be used for an operation only when a record says so, and only for that operation, jurisdiction, dataset and date range.

## The record

Each row of `data/source_permissions.csv` covers one combination of source, dataset, jurisdiction and operation.

| Column | Meaning |
|---|---|
| `source_id` | Registry / code id of the source. |
| `provider`, `publisher` | The platform or host, and the government body the data comes from. They are often different. |
| `dataset` | `*` for every dataset of the source, or a named dataset (`sale_calendar`, `closed_results`, `parcel_centroid`, ...). A caller that names a dataset matches only that dataset or `*`. A caller that names none matches only `*`. |
| `jurisdiction` | `US`, `XX` (a state) or `XX:County`. A county row beats the state row for that county only. |
| `operation` | `discover`, `fetch`, `fetch_via_proxy`, `parse`, `store`, `enrich`, `display`, `redistribute` or `link`. |
| `status` | `APPROVED`, `APPROVED_WITH_CONDITIONS`, `LINK_ONLY`, `LEGAL_REVIEW_REQUIRED`, `OWNER_PERMISSION_REQUIRED`, `RESTRICTED`, `BLOCKED` or `UNKNOWN`. |
| `evidence_type` | `PUBLISHED_LICENSE`, `WRITTEN_PERMISSION`, `INTERNAL_RISK_ACCEPTANCE`, `GRANDFATHERED_PRACTICE`, `PROHIBITION_FOUND`, `TECHNICAL_SIGNAL_ONLY`, `TERMS_SILENT` or `NO_EVIDENCE`. |
| `evidence_ref`, `evidence_date`, `reviewer` | Where the evidence is, when it was read or decided, and who recorded the decision. |
| `effective_on`, `expires_on` | The allowance's window. A record that can allow must have both. |
| `conditions` | Named conditions, `|`-separated. The engine checks each one itself; a caller cannot assert them. |
| `attribution` | Attribution text, where a licence requires one. |
| `last_verified_on`, `reason` | When the record was last checked against its evidence, and why it says what it says. |

How the operations map onto `authorization.py`'s `AuthorizationScope` dimensions (`OPERATION_SCOPE_DIMENSIONS`):

| Operation | Scope dimension(s) |
|---|---|
| `fetch`, `discover`, `fetch_via_proxy` | `automated_access` |
| `parse` | `normalization` |
| `store` | `storage` |
| `enrich` | `derived_data` |
| `display` | `customer_display` |
| `redistribute` | `customer_export` and `api_redistribution` |

A `WRITTEN_PERMISSION` row must match a granted `ProviderAuthorization` covering that dimension, or the file is invalid.

## The decision

`permissions.authorize(source_id, operation, state=, county=, dataset=)` never raises. It returns a `PermissionDecision`, which `as_dict()` turns into a machine-readable record.

**It allows only when exactly one applicable record exists and that record is in effect today.** The record must also be one of three kinds:

- **APPROVED or APPROVED_WITH_CONDITIONS on documented evidence** (a published licence or written permission). Basis `DOCUMENTED`.
- **An open status with an interim allowance.** The status is `LEGAL_REVIEW_REQUIRED`, `OWNER_PERMISSION_REQUIRED` or `UNKNOWN`, carrying an explicit, dated, expiring interim allowance (internal risk acceptance or grandfathered practice, with who recorded it). Basis `INTERIM`.
- **LINK_ONLY, for the `link` operation only.**

Every condition the record names must also be satisfied.

**Everything else denies, with a reason code:**

| Code | Cause |
|---|---|
| `NO_RECORD` | No record for this operation, jurisdiction or dataset. |
| `UNKNOWN_SOURCE` | The source has no records at all. |
| `EXPIRED` / `NOT_YET_EFFECTIVE` | Outside the record's window. |
| `CONFLICT` | More than one record applies. |
| `BLOCKED` / `RESTRICTED` | The record's own status forbids the operation. |
| `LINK_ONLY` | Any operation other than `link` on a link-only source. |
| `NOT_PERMITTED` | An open status with no interim allowance. |
| `CONDITION_UNMET` / `UNKNOWN_CONDITION` / `CONDITION_UNCHECKABLE` | A named condition fails, has no checker, or its checker errors. |
| `HARD_BLOCKED` | A blocked vendor (see below). |
| `CONFIG_INVALID` | The file is missing, unreadable or invalid. This denies every operation of every source. |
| `EVALUATION_ERROR` | Any unexpected error. |

**`INTERIM` is never permission.** `decision.documented` is `False` for it, and its reason says "not a grant". Validation refuses an `APPROVED` row on internal-acceptance or grandfathered evidence. So an internal decision cannot become documented permission by editing a status word.

**Hard blocks.** `tx_pbfcm`, `tx_mvba`, `tx_govease` and `tx_ctsa` are denied in code, whatever the file says. A file that records anything but `BLOCKED` for one of them is invalid. Lifting such a block takes three coordinated changes: the code (`permissions.HARD_BLOCKED_SOURCE_IDS` and `county_source_registry.BLOCKED_SOURCE_IDS`), the record, and the tests.

**Conditions.** Each condition is evaluated over repository records:

- `excluded_from_paid_tier`: the source is not in `data/paid_beta_sources.csv`'s paid tier.
- `dated_list_only`: the registry records the owner's dated-list decision.
- `attribution_text_recorded`: the record carries the attribution text.

**Expiry.** Interim allowances recorded on 2026-10-12 expire on **2027-04-12**. Documented licences are re-read by **2027-10-12**. An expired record denies. Production collection therefore stops on that date unless each record is reviewed and re-dated. To list what is due, run:

```
python3 scripts/source_permission_check.py --due 60
```

## Where it is enforced

Every listed point checks before its first request or write.

| Entry point | Source(s) | Operation(s) |
|---|---|---|
| `scripts/harvest_all_counties.ps1` (guard at the top) | `fl_realauction` / `sale_calendar` | fetch, parse |
| `scripts/harvest_okaloosa_bid4assets.ps1` | `fl_bid4assets_okaloosa` | fetch, parse |
| `scripts/harvest_lienhub_certificates.ps1` | `fl_lienhub_certificates` | fetch, parse |
| `scripts/sync-harvest-to-supabase.ps1` | `fl_realauction`, `fl_bid4assets_okaloosa` | store |
| `scripts/sync-certificates-to-supabase.ps1` | `fl_lienhub_certificates` | store |
| `scripts/sync-laft-to-supabase.ps1` | the nine `fl_laft_*` sources | store |
| `scripts/harvest_laft_*.py` (nine harvesters, `laft_status.permission_gate`) | `fl_laft_*` | fetch, parse |
| `scripts/harvest_laft_pdfs.py`, per county | `fl_laft_pdfs` (e.g. Volusia's own record) | fetch |
| `scripts/harvest_laft_html.py` proxy fallback | `fl_laft_html` | fetch_via_proxy |
| `scripts/auction_outcomes.py` | `fl_realauction` / `closed_results` | fetch, store |
| `harvesters/texas_harvester.py` main loop | `tx_lgbs`, `tx_realauction`, every TX vendor | fetch |
| `scripts/sync-texas-to-supabase.py` (per row) | TX sources | store |
| `scripts/lgbs_available_refresh.py` | `tx_lgbs` | fetch; store (apply) |
| `scripts/harvest_state_inventory.py` | `la_ebr_adjudicated` (and AL / AR when activated) | fetch |
| `scripts/source_publication.py` `collectable()`, used by `harvest_expansion.py` | expansion sources | fetch |
| the same, used by `sync_state_inventory.py` (incl. close-out) | expansion sources | store |
| `source_publication.publishable()` and `publication_state.decide()` | every source | display |
| `harvesters/enrichment/parcels.enrichment_allowed()` | statewide parcel layers | fetch, enrich |
| `harvesters/enrichment/geocode.CoordinateSource.usable()` | FDOR, Santa Rosa, parcel layers | fetch, enrich |
| `scripts/enrich_property_details.py` | `fl_fdor_cadastral` (both datasets), Santa Rosa, Palm Coast | fetch, enrich |
| `scripts/geocode_properties.py` | `census_geocoder` | fetch, enrich |
| `scripts/enrich_flood_zone.py` | `fema_nfhl` | fetch, enrich |
| `scripts/enrich_property_photos_naip.py` | `usda_naip` | fetch, store |
| `scripts/fetch_property_photos.py` | `google_street_view` (BLOCKED) | fetch, store |

**How the PowerShell guard fails closed.**

- It is the first statement after `$ErrorActionPreference`.
- It calls the CLI with named sources, operations and state.
- It exits 3 if Python is missing or the check fails, before any `Invoke-*` or `curl` call.
- `tests/python/ps1_permission_guard.py` pins all of the above.

**Not wired, and why.**

- **The manual, value-free evidence-capture scripts** (`capture_*`, `discover_sources.py`, `probe_*`). They read candidate pages to learn what exists, write nothing to the database and never run on a schedule. They are the next candidates for a `discover` record.
- **Parcel polygon storage and display.** These are governed separately by PR #144's boundary permission matrix, and nothing here grants a geometry operation.

## What the records say today

Every operation production performed on 2026-10-12 is allowed, on the basis it actually has. The parity tests pin this.

**Documented** (a published licence):

- East Baton Rouge: the adjudicated list, the Tax Parcels and the Tax Roll, all Public Domain.
- Douglas County, CO: CC BY-SA 4.0.
- USDA NAIP: public domain.
- UGRC: CC BY 4.0. Utah is not activated.

**Interim, grandfathered practice:**

- RealAuction (Florida and Texas), Bid4Assets, LienHub, LGBS.
- The nine Florida LAFT sources and the ScraperAPI proxy path.
- FDOR cadastral attributes and centroid point, Santa Rosa, Palm Coast.
- The Census geocoder and FEMA NFHL.

**Interim, the owner's internal risk acceptance:**

- The six county sources published since 2026-09-30.
- The ten admin-only AVAILABLE sources, for collection only. These have no `display` record.
- The Colorado OIT parcels, kept out of the paid tier.

**Denied** (no allowance):

- The four hard-blocked vendors.
- Street View stills.
- Harris County, except as a link.
- Dane WI and Oconee SC.
- AL / AR / AZ.
- WI SCO V12, Jim Wells CAD, St. Louis parcels.
- FDOR redistribution and the FDOR NAL bulk files.

## FDOR and Santa Rosa

`harvesters/enrichment/geocode.py` used to mark both sources `publication_status="APPROVED"` with no licence cited. Both now read `APPROVED_GRANDFATHERED`, which is still usable, so production is unchanged. `usable()` now also requires the recorded interim permission.

For FDOR (`fl_fdor_cadastral`), the records name what the scheduled deeds job actually does:

- `parcel_attributes`: fetch and enrich;
- `parcel_centroid`: fetch and enrich (one point derived from the polygon; the polygon is never stored).

Every other operation has no allowance and is denied. That covers display, redistribution, polygon storage, and the NAL bulk files (`fl_dor_statewide`).

## Changing a record

1. Read the evidence and cite it (`evidence_ref`, `evidence_date`).
2. Edit the row, or add one. A documented status needs documented evidence. A `WRITTEN_PERMISSION` row also needs a granted `ProviderAuthorization` in `harvesters/governance/authorization.py`.
3. Run `python3 -m pytest tests/python/test_source_permissions.py`.
4. Never extend `expires_on` without re-reading the evidence and updating `last_verified_on`.
