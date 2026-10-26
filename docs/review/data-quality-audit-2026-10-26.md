# Production data-quality audit - 2026-10-26

Row-level checks on `public.properties` (project `cqnnnvpbocafuvpzfbzu`), every state and ledger, read
with SELECT-only aggregate queries on 2026-10-26 (~17:00-18:00 UTC). **Counts only**: no parcel, case number,
address or owner appears here. "Active" = `status in ('active','available')`. Counts are before the
corrections in `scripts/sql/data_fixes_2026_10_26.sql` unless marked "after".

## 1. Active rows per state x ledger x source

Source-link columns per ledger: auctions and certificates use `url_auction` (+ `document_url` for Texas
LGBS sale lists); Available uses `list_url` / `document_url` / `purchase_url`. "No link" = none of the four.

| State | Ledger | Source id | Active | Never seen | Seen > 36 h | Seen > 7 d | No parcel | No link | No coords | No source_id |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| CO | certificate | co_douglas_county_held_liens | 138 | 0 | 0 | 0 | 0 | 0 | 24 | 0 |
| CO | certificate | co_morgan_county_held_certificates | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| FL | auction | fl_realauction | 1,051 | 129 | 162 | 92 | 25 | 0 | 69 | 0 |
| FL | certificate | fl_lienhub_certificates | 1,611 | **1,611** | 0 | 0 | 0 | 0 | 721 | 0 |
| FL | laft | fl_laft_hillsborough | 3 | 0 | 0 | 0 | 0 | 0 | 3 | 0 |
| FL | laft | fl_laft_html | 59 | 0 | 1 | 1 | 1 | 0 | 3 | 0 |
| FL | laft | fl_laft_leon / orange / osceola / stlucie | 18 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| FL | laft | fl_laft_pdfs | 18 | 2 | 0 | 0 | 4 | 0 | 7 | 0 |
| FL | laft | fl_laft_pioneer | 21 | 0 | 0 | 0 | 0 | 0 | 5 | 0 |
| FL | laft | fl_laft_realtdm | 40 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| LA | laft | la_ebr_adjudicated | 4,520 | 0 | 0 | 0 | 0 | 0 | 781 | 0 |
| MI | auction | mi_eaton_treasurer_sale | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MI | auction | mi_lenawee_tax_sale | 35 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MI | laft | mi_detroit_landbank_lots | 30,537 | 0 | **13,037** | 0 | 0 | 0 | 0 | 0 |
| MI | laft | mi_detroit_landbank_programs | 12 | 0 | 12 | **12** | 0 | 0 | 0 | 0 |
| MI | laft | mi_oceana_landbank | 5 | 0 | 0 | 0 | 0 | 0 | 4 | 0 |
| MN | laft | mn_ramsey_tax_forfeit | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MO | laft | mo_stl_lra_inventory | 9,778 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| OK | laft | ok_oklahoma_county_owned | 195 | 0 | 0 | 0 | 0 | 0 | 27 | 0 |
| PA | laft | pa_fayette_repository | 247 | 0 | 0 | 0 | 0 | 0 | 82 | 0 |
| SC | auction | sc_york_tax_sale | 853 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| SC | laft | sc_georgetown_forfeited_land | 1 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| SC | laft | sc_horry_forfeited_land | 51 | 0 | 0 | 0 | 0 | 0 | 19 | 0 |
| TN | laft | tn_shelby_landbank | 1,784 | 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| TX | auction | tx_lgbs | 443 | 0 | 0 | 0 | 0 | 0 | 0 | **443** |
| TX | auction | tx_realauction | 73 | 0 | 0 | 0 | 0 | 0 | 69 | **69** |
| TX | laft | tx_lgbs | 3,637 | 0 | 0 | 0 | 0 | **3,263** | 0 | **3,263** |

Zero in every row (not repeated above): missing county, missing case_no, missing address, missing state,
NULL `inventory_status`, county names off the state's canonical basemap list (all 13 states checked against
`*-counties.svg`), negative amounts, amounts over $50M, sale dates before 2000 or more than two years out,
`purchase_amount` without `purchase_amount_kind` (or a figure-kind without an amount), year built or
acreage out of range, active rows carrying a result, sold rows without a basis, status values outside the
pipeline vocabulary (`active`, `available`, `closed`, `dropped`, `sold`, `notfound`), and duplicates of
`(state, source, county, case_no)` (case-insensitive, trimmed) or of one parcel twice within one source.
Texas shows 53 auction and 546 Available "repeated parcels": `parcel` there is the tax-suit **cause**
number, which covers several accounts by design (CLAUDE.md); not a defect.

## 2. Defects and what was done

| # | Defect (counts) | Cause | Fix | Production correction |
|---|---|---|---|---|
| D1 | TX: 3,775 active rows without `source_id`; 3,263 active LGBS Available rows with **no source link** | `sync-texas-to-supabase.py` never sent `source_id`; `apply_acquisition_paths.py` (which writes the registry listing link and the verified county record) selects `source_id=eq.tx_lgbs`, so it never reached them | sync sends `source_id = harvester_source`; the applier reads `source_id OR harvester_source` and backfills a missing `source_id` | `source_id` set from `harvester_source` on 3,775 rows. The list link arrives on the next `laft` run's apply step (not written by hand) |
| D2 | TX: 22 active LGBS rows with `min_bid = 0` (printed as a $0 bid in the "TX Min Bid" export) | sync stored the vendor's 0 verbatim | 0 or less is stored as NULL ("not published"); `bid` keeps the legacy 0 sentinel | 22 rows `min_bid` -> NULL |
| D3 | Coordinates outside the row's own state: 1 active FL auction (in Texas), 1 active TX LGBS (in Louisiana); 4 more on FL closed rows | FL: legacy geocode without provenance (today's geocoder verifies state and county); TX: vendor point accepted unchecked | Texas sync drops a vendor point outside `geocode.STATE_BOUNDS["TX"]` | 6 rows: coordinates, flood fields and the NAIP image taken at the wrong point cleared to "not checked" |
| D4 | Closed rows with no `delisted_at`: FL auction closed 1,622, dropped 8; FL certificate notfound 56 | PowerShell close-outs write `status` only | `stamp_seen.py --delisted` (both FL stamp steps) copies the trigger-stamped `gone_since` into a missing `delisted_at` for absence closes (never sold / result rows) | 1,092 rows (1,036 auction + 56 certificate). 586 closed auctions have no `gone_since` (bulk-closed 2026-09-30) and 8 `dropped` are of unknown origin: left NULL, nothing invented |
| D5 | Active row still carrying `delisted_at`: 1 (Detroit lots) | reactivation never cleared it (`sync_state_inventory.py`, `laft_lifecycle.py`, the FL deed upsert) | a listed row is written with `delisted_at = NULL` in all four writers | 1 row cleared |
| D6 | A Florida certificate marked `notfound` that LienHub lists again stayed `notfound` forever | `sync-certificates-to-supabase.ps1` never sent `status` (the deed sync fixed this in run #181) | certificate upsert sends `status = 'active'`, `delisted_at = NULL` | none needed (no measurement of re-listed certificates possible without a harvest) |
| D7 | TX LGBS row off the feed but carrying a stored "Scheduled ..." status maps to upcoming / unknown | `tx_lgbs_status` read the raw status before checking the pipeline status | a gone row is `closed` (raw kept verbatim, never a result) | none (no current row has this shape; the 165 TX closed rows with `inventory_status = unknown` were closed today after the status writer ran and become `closed` at its next run) |

Closed rows **legitimately** without `delisted_at`: MI Eaton sold 5 and WI Green 9 - closed by the
source's own sold flag / past-sales table, still on the source's page, so not delisted.

## 3. Measured, not changed here (owned elsewhere or no source data)

| Finding | Count | Why not fixed here |
|---|---:|---|
| FL certificates never seen (`last_seen_at` NULL), so `inventory_status = unknown` | 1,611 | LienHub reads not COMPLETE (run / read failures - another owner) |
| FL auctions never seen / not seen in 36 h (off the county's current sale list) | 129 / 162 | Florida page-2 paging and read failures - another owner |
| FL auctions active with a past sale date, never seen | 4 | their counties' reads are not COMPLETE, so the close-out is gated (another owner) |
| Detroit lots not seen in 36 h; Detroit programs not seen in 7 d | 13,037 / 12 | Detroit read failures / keyset fix (PR #204) - another owner |
| MI Lenawee 35, Eaton 3 active auctions past their sale date | 38 | the county list still publishes them and no result; `unknown` is the honest status |
| SC York auctions with no sale date and `bid = 0` | 853 | the sale-date document 404s (CLAUDE.md); bid 0 = not published, already read that way |
| TX closed rows with `inventory_status = unknown` | 165 | closed today after the writer ran (Texas close-out - another owner); fixed by the next writer run |
| Coordinates missing (largest: LA 781, FL certificates 721, PA 82, FL auctions 69, TX RealAuction 69) | see table | enrichment coverage, not a defect in written rows |
| FL realauction rows without `harvester_source` (source_id is set) | 1,051 | harmless: every reader uses `source_id` first |
| 586 FL closed auctions without `gone_since` | 586 | bulk close on 2026-09-30; no close time on record |

## 4. Front-end follow-ups (not edited here)

- None required for the corrections above: `hasPublishedBid()` already treats `bid = 0` as not published,
  and NULL coordinates fall back to the county mini-map.
- The "TX Min Bid" export column (`public/app.js`, `["TX Min Bid", p => p.min_bid ?? ""]`) printed 0 for the
  22 rows; it now prints blank. A label such as "Not published" would be clearer.
- `delisted_at` is now populated on Florida closed rows; the property page could show "Left the list on
  <date>" from it (the ledger record view already carries it in `freshness.delisted_at`).
