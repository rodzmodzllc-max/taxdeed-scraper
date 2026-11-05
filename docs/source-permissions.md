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
| `scripts/laft_lifecycle.py` (`apply_store_permission`, per county) | the county's LAFT source (`fl_laft_*`, `la_ebr_adjudicated`) | store - a denied county is withdrawn: nothing observed, reactivated, closed or carried from its list |
| `scripts/stamp_seen.py` | `fl_realauction` + `fl_bid4assets_okaloosa` (auction); `fl_lienhub_certificates` (certificate); any other ledger refused | store |
| `scripts/auction_events_writer.py` (not in `--dry-run`) | `fl_realauction` + `fl_bid4assets_okaloosa` (fl); `tx_realauction` + `tx_lgbs` (tx) | store |
| `scripts/apply_acquisition_paths.py` (per row's source) | the row's `source_id` / `harvester_source` | store |
| `enrich_property_details.lookup_fdor` / `lookup_santa_rosa_gis` / `lookup_flagler_gis` (inside the functions) | `fl_fdor_cadastral` (both datasets), Santa Rosa, Palm Coast | fetch, enrich - raises `SourceNotPermitted` before any request, whoever calls it |
| `scripts/backfill_fdor_phase52_fields.py` | `fl_fdor_cadastral` (both datasets); each fallback individually | fetch, enrich |
| `scripts/enrich_property_details_tx.py` `_fetch_hcad` / `_fetch_tad` (draft, unscheduled) | `tx_cad_harris`, `tx_cad_tarrant` (no record: denied) | fetch, enrich |
| `scripts/harvest_alabama_state_land.py` live mode (after activation) | `al_ador_state_land` (UNKNOWN: denied) | fetch, parse |

**How the PowerShell guard fails closed.**

- It is the first statement after `$ErrorActionPreference`.
- It calls the CLI with named sources, operations and state.
- It exits 3 if Python is missing or the check fails, before any `Invoke-*` or `curl` call.
- `tests/python/ps1_permission_guard.py` pins all of the above.

**Discovery, evidence capture and probes** (`capture_*`, `discover_sources.py`, `probe_*`; wired 2026-10-13).
Each script's `main()` first calls `permission_gate.install_discovery_guard(label)`
(`harvesters/governance/discovery_guard.py`). From then on every outbound request of the process
(`requests` and `urllib`) is checked before a connection is opened:

- The URL is matched to its source(s) from the repository's own records: the registry, the enrichment
  catalog, the candidate and evidence tables, and the expansion and parcel-layer configs. The longest path
  prefix on the same host wins; a shared host with no path match counts every source on it.
- Every matched source needs an in-date **`discover`** permission. A fetch / store / display permission
  does not cover discovery, and a working public URL is never permission.
- No match, a row without a source id, a denial, an expired or not-yet-effective record, or an unreadable
  permission file refuses the request (`DiscoveryDenied`, a transport error, so the script records the page
  as failed and carries on). The project's own database host (`SUPABASE_URL`) is not a source.
- At exit: one log line and `out/public/discovery-permission-<label>.json`, counts, hosts, reason codes and
  source ids only - never a path, query, credential or row value.

**Today no source holds a `discover` permission** (the only `discover` records are the four BLOCKED
vendors), so every one of these scripts refuses every source request until the owner records a `discover`
permission, with its evidence, for each source they are to read. Offline / fixture modes are unaffected.
Pinned by `tests/python/test_discovery_guard.py`.

**Not wired, and why.** (Re-checked 2026-10-13 after the entry points above were closed.)

- **Writers of derived state only** (`inventory_status_writer.py`, `publication_gate.py`, `publication_state_writer.py`, `detect_property_changes.py`, `unit_freshness.py`, `export_backup.py`, `optimize_stored_images.py`). They read and write the project's own rows; they request nothing from a source. Customer display is gated separately by `display` in `publishable()` / `publication_state.decide()`.
- **The browser.** `public/app.js` shows what the database returns; the `display` decision is made server-side by the writers above (and by migration 031 once applied).
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

## Office replies (2026-11-04, second round 2026-11-05)

Replies from county offices are listed in `data/office_replies.csv`, each with the question it actually
answered (`ROUTING_ONLY`, `TECHNICAL_ONLY` or `COMMERCIAL_USE`) and what it said about commercial use
(`PERMITTED`, `PROHIBITED_WITHOUT_WRITTEN_AUTHORIZATION` or `NOT_ANSWERED`). Two rules follow from them, and
`office_replies.problems()` enforces both (`tests/python/test_office_replies.py`):

- **A link, or permission to link, is not permission to reuse.** Neither is a routing answer or a statement
  of what is technically acceptable. A reply that did not permit commercial use can never back a documented
  fetch, parse, store, display, enrich or redistribute record.
- **A written prohibition is recorded as one.** When an office prohibits collection or commercial
  incorporation without prior written authorization, those operations are `RESTRICTED` on
  `PROHIBITION_FOUND`. Its rows are withheld from every customer view, the tester preview included:
  `publication.row_publication()` gives them `BLOCKED`, and `commercial_scope` marks the source `BLOCKED`.
  Stored rows are never deleted, and admins still see them.

The two replies on file:

| Office | Source | Answered | Recorded |
|---|---|---|---|
| Orange County Comptroller | `fl_laft_orange` | Commercial use: prohibited without prior written authorization. Links and individual record viewing permitted. | `link` APPROVED (written permission). `fetch` / `parse` / `store` / `display` RESTRICTED. Removed from the daily job and from the Lands Available sync guard, so it can never block the other counties. |
| Palm Beach County Clerk | `fl_laft_pioneer` (Palm Beach only) | Technical only. Direct links to Official Records, limited factual display and retention of published outcomes are technically acceptable. Court-case deep links are restricted, and the site is intended for human interaction. Commercial use was not answered. | `FL:Palm Beach` `link` LINK_ONLY on `TECHNICAL_SIGNAL_ONLY`. Every other operation keeps its existing interim record. Court-case deep links are refused as customer links (`restricted_link_patterns`, checked by `laft_purchase_paths.untrusted_reason`). |

Neither reply covers the RealAuction auction sites (`fl_realauction`) or LienHub (`fl_lienhub_certificates`)
for the same counties. Those are separate sources with their own terms. The original e-mails are not in this
repository, and their received dates were not supplied, so neither is recorded.

### Second round (recorded 2026-11-05)

The owner's reply register (read-only review of the outreach mailbox, 2026-11-05) added the replies below. No
person's name, e-mail address or phone number is recorded; office names, dates, request numbers and short quotes
of policy wording are. Four columns were added to `data/office_replies.csv`:

| Column | Meaning |
|---|---|
| `received_on` | The reply date(s), `|`-separated; blank when not supplied. |
| `automated_collection` | `PERMITTED_WITH_LIMITS`, `PROHIBITED` or `NOT_ANSWERED`: what the reply said about automated reading, kept apart from commercial use. |
| `collection_limits` | `host=...;max_per_day=N;min_interval_s=N` when automation is allowed under limits. `scripts/host_limits.py` applies them before every request. |
| `owner_decision` | Blank, or `PENDING`. A prohibition is enforced on the permission records (`RESTRICTED`) unless the owner's decision on it is `PENDING`. A `PENDING` prohibition keeps the existing interim records, can never back a documented record, withholds nothing by itself (`prohibits_reuse()` is false) and must be listed below. |

`authorization_id` is now optional. A reply recorded without one grants nothing, so its sources may carry no
documented reuse record (`problems()` checks this).

| Office | Source | Answered | Recorded |
|---|---|---|---|
| RealAuction.com (vendor), ticket 914220, 2026-10-21 | `fl_realauction`, `fl_laft_realtdm` (FL), `tx_realauction` (TX) | Automated collection refused: "will not be providing any form of written permission to use automated means for scanning or crawling our auction sites". There is no API. Display and links were not addressed. | Two rows (FL, TX): `COMMERCIAL_USE`, commercial use `NOT_ANSWERED` (the reply only addresses crawling), automated collection `PROHIBITED`, owner decision `PENDING`. Fetch / parse records are unchanged (interim). |
| Volusia County Clerk of the Circuit Court, 2026-10-21 and 2026-10-30 | `fl_laft_pdfs` (Volusia) | The website disclaimer applies to all its data: "expressly prohibited from reproducing, publishing online, selling, reselling, or otherwise disseminating data ... except as permitted by law". Deep linking is not allowed; links must go where its own links go (`https://app02.clerk.org/or_td/` or `/or_m/`). Its bulk Official Records product excludes the Tax Deeds data. | `PROHIBITED_WITHOUT_WRITTEN_AUTHORIZATION`, owner decision `PENDING`. Deep links are refused (`restricted_link_patterns` with the two entry pages marked `!`), and every customer link to `app02.clerk.org` other than the entry pages becomes `https://app02.clerk.org/or_td/` (`app.js` `officeEntryLink()`, applied by `customerPageUrl()` and to every rendered anchor). |
| Indian River County Clerk of Court & Comptroller, 2026-10-21 / 22 / 26 | `fl_laft_html` (Indian River) | "we do not grant permission for any commercial activities". The data can be used like any member of the public; a paid data-vendor agreement covers court and Official Records data and does not name tax-deed data. The 2026-10-26 follow-up said a data contract is not required for the Tax Deed website, and did not answer permitted uses. | `PROHIBITED_WITHOUT_WRITTEN_AUTHORIZATION`, owner decision `PENDING`. Records unchanged. |
| Oklahoma Office of Geographic Information (Oklahoma Conservation Commission), 2026-10-14 and 2026-10-26 | none (OKMaps parcel dataset, unused) | Linking to the parcel layer on the OKMaps search page is permitted with the credit "OKMaps and iProplogic". Downloading the dataset is not allowed by its vendor agreement; a licence would come from iProplogic. | `PROHIBITED_WITHOUT_WRITTEN_AUTHORIZATION` (the dataset). The app links OKMaps nowhere today; a test requires any future `okmaps.org` link to carry the credit. |
| Citrus County Clerk of the Circuit Court & Comptroller, JustFOIA CLKPRR-2026-684, 2026-10-29 | `fl_laft_pioneer` (Citrus) | Technical: no API or export; automation allowed at "no more than 2,000 requests per day, with at least 60 seconds between requests". Commercial use not answered. | `TECHNICAL_ONLY`, `NOT_ANSWERED`, automated collection `PERMITTED_WITH_LIMITS` with `host=search.citrusclerk.org;max_per_day=2000;min_interval_s=60`. `harvest_laft_pioneer.py` calls `host_limits.HostLimiter` before every request to that host, retries included (the per-day count is shared through `out/.harvest_cache/host_request_counts.json`). |
| Wisconsin State Cartographer's Office (V12 statewide parcels), ticket 112196, 2026-10-26 | `wi_sco_v12_parcels` | Public domain: "There are no use restrictions"; attribution recommended, not required; no county terms. | `COMMERCIAL_USE`, `PERMITTED`, no authorization record. Permission records unchanged (`UNKNOWN`): the reply is recorded, nothing is approved on it yet. |
| Tennessee Comptroller of the Treasury, Division of Property Assessments (GIS), 2026-11-04 | none | Shapefile data may be used "for any use case, including consumption in a commercial application/software or for historical purposes"; no retention policy; no automated or recurring downloads (requests are filled out by hand); boundaries are approximate; nine counties, Shelby among them, are not maintained by the Comptroller. | `COMMERCIAL_USE`, `PERMITTED`, no source and no permission record. |

Florida DOR Property Tax Oversight and Utah UGRC replies are already recorded in `data/source_approvals.csv` and
are not repeated here.

The routing and technical answers are rows too, each `NOT_ANSWERED` with no source: the Okaloosa Tax Collector
and Clerk, the Escambia, DeSoto, Lee, Seminole, Broward, Miami-Dade, Marion, Duval, Pasco, Liberty, Gulf, Madison,
Lafayette, Putnam, Brevard, Orange and Franklin Clerks, Miami-Dade ITD, the Manatee, Volusia, Flagler and Taylor Tax
Collectors, Albany WY, Wood WI, Kaufman, Tarrant, Harris, Floyd, Collin, Dallas, Angelina and Hidalgo TX, the
Texas Comptroller, Maricopa AZ, the Minnesota Department of Revenue, Sherburne MN and Los Angeles County CA.
Automatic acknowledgements with no substance are not recorded.

### Open owner decisions

Each `PENDING` row is a written prohibition the permission records do not yet enforce. The owner decides whether
to stop the collection (records `RESTRICTED`, as for the Orange County Comptroller), seek written authorization or
a public-records route, or keep the interim risk acceptance:

- **RealAuction.com (vendor)**: automated collection refused in writing. Every RealAuction-hosted source is
  affected: the Florida deed auctions (`harvest_all_counties.ps1`, `fl_realauction`), realTDM Lands Available
  (`fl_laft_realtdm`), the outcome reads (`auction_outcomes.py`) and the Texas sheriff / constable sales
  (`tx_realauction`, the Dallas sheriff site among them). Nothing was turned off; the 2026-10-26 owner decision
  accepted this risk on interim records. A second RealAuction ticket (914757) waits for a reply naming state,
  county and product.
- **Volusia County Clerk of the Circuit Court**: online republication prohibited "except as permitted by law"
  under its website disclaimer. The Volusia Lands Available PDF (`fl_laft_pdfs`) is still read; a Chapter 119
  records request is the route the reply leaves open. Deep links are already refused.
- **Indian River County Clerk of Court & Comptroller**: no permission for commercial activities. The Indian
  River Lands Available page (`fl_laft_html`) is still read.

Add a new reply as a row in `data/office_replies.csv`. A reply that grants something also needs a record in
`harvesters/governance/authorization.py` and the matching permission rows. Then run
`tests/python/test_office_replies.py`.

## FDOR and Santa Rosa

`harvesters/enrichment/geocode.py` used to mark both sources `publication_status="APPROVED"` with no licence cited. Both now read `APPROVED_GRANDFATHERED`, which is still usable, so production is unchanged. `usable()` now also requires the recorded interim permission.

For FDOR (`fl_fdor_cadastral`), the records name what the scheduled deeds job actually does:

- `parcel_attributes`: fetch and enrich;
- `parcel_centroid`: fetch and enrich (one point derived from the polygon; the polygon is never stored).

Every other operation has no allowance and is denied. That covers display, redistribution, polygon storage, and the NAL bulk files (`fl_dor_statewide`).

## Interim allowances: inventory and expiry

`docs/interim-permissions.md` (with `data/current_state/interim-permissions.json`) lists every interim allowance. It is generated by `scripts/build_interim_permissions.py` (`--check` is test-pinned) from `harvesters/governance/interim_permissions.py`. Each entry gives the source, dataset, jurisdiction, operation, conditions, evidence, reviewer and dates, plus the code that enforces it. The call sites are read from the code: files that name the source next to a permission check, and the shared class gates (`source_publication.py` / `publication_state.py` for registry sources, `laft_lifecycle.py` for Lands Available, `parcels.py` for parcel layers, `geocode.py` for coordinate sources).

As of this file, there are 133 interim records across 36 sources, and every one expires on 2027-04-12. 77 of them carry a reviewer column reading "no reviewer decision on file" (finding `REVIEWER_IS_NOT_A_DECISION`): those allowances rest on recorded practice, not on a reviewer's decision. No record lacks a call site.

Expiry is enforced in `authorize()` on every call, never cached:

- denied before `effective_on` (`NOT_YET_EFFECTIVE`);
- allowed through `expires_on`, inclusive;
- denied from the day after (`EXPIRED`).

There is no fallback. An expired county record is not replaced by an in-date state record, and an expired state record is not replaced by a national one. A met condition never revives an expired record. A missing or malformed date, an expiry not after the effective date, a missing reviewer, or an interim window longer than `INTERIM_MAX_DAYS` (210 days, the length of the current window 2026-09-14 .. 2027-04-12) makes the file invalid, and every request is then denied (`CONFIG_INVALID`). Renewal is a new, dated record from a fresh review, never an extended date. `tests/python/test_interim_expiry.py` covers each boundary.

## Changing a record

1. Read the evidence and cite it (`evidence_ref`, `evidence_date`).
2. Edit the row, or add one. A documented status needs documented evidence. A `WRITTEN_PERMISSION` row also needs a granted `ProviderAuthorization` in `harvesters/governance/authorization.py`.
3. Run `python3 -m pytest tests/python/test_source_permissions.py`.
4. Never extend `expires_on` without re-reading the evidence and updating `last_verified_on`.
