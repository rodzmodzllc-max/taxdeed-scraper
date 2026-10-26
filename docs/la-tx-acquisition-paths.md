# Louisiana and Texas AVAILABLE: acquisition paths and list currency (2026-10-25)

This note covers the owner's rule of 2026-10-25: every property shown must have a path of acquisition, and
stale or dropped properties must not be shown. It records what was read and what changed. All figures are counts;
no row value is recorded.

## Louisiana: East Baton Rouge adjudicated (`la_ebr_adjudicated`, 10,334 active rows)

### Per-property purchase route: none published

The following were read live on 2026-10-25:

- **The Parish Attorney's Adjudicated Property page** (`www.brla.gov/455/Adjudicated-Property`). It links:
  - the Open Data list and its GIS twin;
  - the memorandum;
  - the statutes;
  - "REQUEST TO PURCHASE ADJUDICATED PROPERTY" (a Parish-wide PDF form; the buyer writes in the property ID);
  - the FAQs;
  - a dated "Adjudicated Properties for Auction October 21, 2026" ordinance list (3 pages; past);
  - CivicSource, a vendor that is not used (unchanged decision).
- **Per-property pages:** no page or link keyed by assessment number exists on any Parish page read. Neither the
  Open Data dataset nor the ArcGIS layer (`maps.brla.gov/.../Adjudicated_Parcel/MapServer/0`, the same 4,527
  features) carries a purchase column or link.

So the path stays the **official procedure**. That is the existing VERIFIED evidence row (memorandum + Request to
Purchase form, run 36940992329), applied to every row. Every one of the 10,334 rows carries it. No per-property link
was implemented, because none exists. Building one from the assessment number would be a guessed URL.

### A newer official list exists

| Dataset | Rows updated | Rows | Distinct numbers |
|---|---|---|---|
| `a4h4-zi7e` "Adjudicated Property" (in production) | 2024-02-27 | 52,056 (one per number per TAX YEAR 2012-2023) | 10,334 |
| `shrr-fsqq` "Adjudicated Parcel" | **2026-05-06** | 4,527, STATUS `AJ` on every row | 4,520 |

Both datasets are attributed to the East Baton Rouge Parish Assessor, with provenance official and licence
PUBLIC_DOMAIN. Both are updated "Annually".

**Overlap of the 10,334 production numbers with the newer list:** 3,691 are on it and **6,643 are not**. Another
829 numbers on the newer list are not in production.

**Within the old dataset:** 4,541 numbers have a TAX YEAR 2023 row (the newest roll). 3,388 of those are on the newer
list, against 303 of the 5,793 numbers whose newest row is older. The production adapter keeps every number's latest
row whatever its year, so numbers that left the adjudicated roll years ago are still active.

**What changed in code** (`harvesters/otc/adapters/louisiana.py`):

- The parser is column-driven (`ColumnLabels`). It optionally reads only the source's own status values
  (`status_include`).
- The outcome now counts `not_on_latest_tax_year` (counts only, nothing dropped).
- `EBR_PARCEL_SOURCE` reads `shrr-fsqq` (STATUS `AJ` only, assessment number as identity, same `source_id`). It is
  **live-verified and fixture-tested but NOT enabled.**
  - Enabling it moves the list date from 2024-02-27 to 2026-05-06.
  - The next COMPLETE read would then close the 6,643 numbers that are not on it.
  - That is the owner's decision: the 2026-09-30 publication approval named `a4h4-zi7e`.
  - To switch, point the harvest at `EBR_PARCEL_SOURCE`, update the registry row's `canonical_url` /
    `document_url` / notes, and rebuild the generated files.

## Texas: LGBS AVAILABLE (`tx_lgbs`, 421 active rows)

### Per-county official list / procedure (read 2026-10-25, government sites only)

| County | Rows | Official struck-off list | Official procedure | Status |
|---|---|---|---|---|
| Galveston | 183 | none (counsel's listing) | Sheriff's "Sheriff Sales Information & Procedures" (resales online, deposit, Certificate of Eligibility) | VERIFIED (existing row) |
| Liberty | 113 | none current; the Tax Office's "Tax Sale Property Listing" document (2017) says to contact the counsel or obtain a list from the Tax Office | none | NOT_FOUND |
| Leon | 84 | none; the Tax Assessor-Collector page sends buyers to the counsels' sites | none | NOT_FOUND |
| Maverick | 14 | none; the directory-listed county site returns 404 | none | NOT_FOUND |
| Jim Wells | 11 | none; the City of Alice page sends buyers to the counsel's site | none | NOT_FOUND |
| Hardin | 9 | none; the new county site's Foreclosure Sales page is empty | none (only a 2024 commissioners-court resale resolution) | NOT_FOUND |
| Van Zandt | 6 | none; taxes are collected by the appraisal district | none | NOT_FOUND |
| Goliad | 1 | none | none | NOT_FOUND |

Each of the seven counties publishes nothing on its own government site that lists struck-off property or tells a buyer
how to buy it. Three of them (Leon, Jim Wells via the City of Alice, and Liberty in 2017) point buyers to the
delinquent-tax counsel instead.

So for these counties the only list is the counsel's. No new evidence row could be verified. The outcomes table now
records the 2026-10-25 reads (basis `document_read`). Two county Tax Office pages were added as candidates (Leon,
Liberty).

**Path coverage:** 183 of the 421 rows (Galveston) have a verified path; the other 238 do not. PBFCM, MVBA, CTSA and
GovEase were not used.

### The 19 TX auction rows from `tx_lgbs` with no link

**Cause.** `harvest_lgbs()` set no URL on any LGBS record (Phase 72: "no per-property or per-sale LGBS URL is known").
`sync-texas-to-supabase.py` had no column to send one to. So `purchase_url`, `url_auction`, `document_url` and
`list_url` all stayed NULL. The AVAILABLE rows got their listing link later from `apply_acquisition_paths.py`; the
auction rows never did.

**What the feed actually publishes.** A value-free field probe was run on 2026-10-25 through the ingestion gate and
the `fetch` permission (ALLOWED_INTERIM). It read 4,203 Texas records and found two link fields per record:

- `county_sale_list`: the county's sale-list document. It is on 464 records, which is every record with a sale date,
  including all 174 "Scheduled for Auction" and all 203 "Scheduled for Online Auction" records.
- `property_loc`: the record's online sale site. It is on 260 records. Its hosts:
  - the counties' RealAuction sale sites;
  - GovEase (blocked);
  - one auction house that publishes only a bare homepage.

**Change.**

- `harvest_lgbs()` keeps `county_sale_list` as `TexasSaleRow.sale_list_url`, verbatim and https only. The sync sends
  it as `document_url`.
- It keeps `property_loc` as `auction_url` with kind `county`, verbatim. The link is refused when it is:
  - not https;
  - a bare homepage;
  - on a blocked vendor's host (GovEase, PBFCM, MVBA, CTSA).
- Nothing is composed or upgraded. A record without a link sends no key, so a stored value is never nulled.
- The 19 rows receive their links on the next `texas` harvest, if they are still listed then.

### Are the 421 rows still listed?

**Not determinable from the recent runs.**

- **The 2026-10-25 LGBS refresh** (run 40206132797, `lgbs_available_refresh.py --apply`) logged "pages 1, raw records
  0, Texas records 0, walk INCOMPLETE". Page 1 never answered after six attempts, so the feed was not read. It was not
  read empty. All 421 rows were counted `NOT_IN_FEED` and nothing was written.
- **Last reads:** 382 rows were last observed on 2026-10-02, and 39 were never observed.
- **Fix:** the script now reports such rows as `NOT_READ`. It keeps `NOT_IN_FEED` for a COMPLETE walk only, and logs
  the page it stopped at and the error class.
- **From this sandbox:** `taxsales.lgbs.com` did not answer, so the listings could not be checked independently.
- **Settling it:** a dispatch whose walk completes (the `texas` job, or the `available` job's refresh step). Nothing
  here closes or hides a row on absence.
