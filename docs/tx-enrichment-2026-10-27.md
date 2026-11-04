# Texas enrichment: property facts and how to buy (2026-10-27)

Owner request 2026-10-27: enrich every property. Owner decision on record (2026-10-26): collect every
source now, legal review later, recorded as INTERIM `INTERNAL_RISK_ACCEPTANCE` permission records.

Production before this change (read-only, counts only, 2026-10-27): 4,184 active TX rows (tx_lgbs
3,635 Available + 354 Auctions, tx_realauction 195 Auctions). Land use, lot size and year built were
0% filled; a recorded acquisition path existed on 4% of Available rows (Galveston only) and 0% of
Auction rows. PBFCM / MVBA / GovEase / county-list rows were not yet in production.

## 1. Property facts

### Sources

| Source id | What | Counties | Permission |
|---|---|---|---|
| `tx_txgio_stratmap_parcels` | TxGIO StratMap Land Parcels 2026, one zipped shapefile per county (S3, `county_file` transport) | 83 | interim (discover, fetch, parse, store, enrich) |
| `tx_hcad_parcels` | Harris Central Appraisal District parcel layer (gis.hctx.net, ArcGIS) | Harris | interim (same) |

TxGIO StratMap was "unreachable from runners" in the 2026-10-01 sprint. On 2026-10-27 the map
service answered but refused every query ("Requested operation is not supported by this service"),
so the county shapefiles in TxGIO's public data warehouse are read instead. A first runner read
happens on the first `job=enrich` dispatch.

### Field definitions read

The TxGIO Land Parcel Schema (Appendix A, `https://geographic.texas.gov/_uploads/TxGIO-land-parcel-schema.pdf`).
Mapped (fill-blank only): `STAT_LAND_` (state land-use code) → `land_use`; `LEGAL_AREA` → `acreage`
only when `LGL_AREA_U` is ACRE / ACRES / AC; `LAND_VALUE`, `IMP_VALUE`, `MKT_VALUE` → `land_value`,
`improvement_value`, `market`; `TAX_YEAR` → `value_year`; `YEAR_BUILT` → `year_built` (a single year
only); the polygon centroid → `latitude` / `longitude` (the files' `.prj` is geographic WGS 84).
Never mapped: `SITUS_ADDR` and `LEGAL_DESC` (the Texas syncs write address / legal_desc themselves and
would take turns with this source), owner and mailing columns, `LOC_LAND_USE` (no legend), `GIS_AREA`.
The schema has no building-area column, so building area stays unfilled.

HCAD's layer publishes no field definitions. Only self-describing columns are mapped: `state_class`,
`land_value`, `impr_value`, `total_market_val`, `acreage_1`, `tax_year`.

### Matching

Exact CAD account only. `case_no` holds the account for the vendor listings (`tx_lgbs`,
`tx_realauction`, `tx_pbfcm`, `tx_mvba`, `tx_govease`); rows of other sources are never matched.
Each appraisal district fills a different identifier column, so the column and rule are measured per
county: a sample of each county's accounts was matched against its 2026 file, and a county is
configured only when at least half matched exactly one record. Two records for one key are AMBIGUOUS
and nothing is written. A failed county read writes nothing.

Excluded for no or too few matches: Tarrant (its StratMap `PROP_ID` is TAD's lot/block key; the
county's TCProperty layer returns a small subset; TAD's own service carries no account), Hunt,
Matagorda, Smith, Grayson, Hardin, Red River, Travis, Anderson, Erath, Franklin, Goliad, Panola.

Expected: the 83 counties hold 3,608 of the 4,184 rows; from the measured sample rates, about 3,150
rows should match. Harris: HCAD matched 7 of 10 sampled accounts (about 230 of 327 rows).

## 2. How to buy

Captured value-free by `job=evidence`, `evidence_scope=acquisition_candidates`, run 40430155571
(2026-10-27), from official county pages added to `data/acquisition_candidate_pages.csv` under the
discovery-only id `tx_county_sale_process`. Rows recorded in `data/purchase_path_evidence.csv` quote
the digest.

`data/acquisition_evidence_ledgers.csv` names the ledger each process applies to. A row without an
entry is an AVAILABLE process, as before. `scripts/apply_acquisition_paths.py --ledgers laft,auction`
applies each row only to its ledgers. A source whose single listing serves every county (LGBS) now
reaches counties missing from the 8-county registry roster. A per-county source (RealAuction) never
borrows another county's page.

| County | Source | Ledgers | Office page | Active rows (2026-10-27) |
|---|---|---|---|---|
| Galveston | tx_lgbs / tx_realauction | Auctions + Available | Sheriff's procedures PDF (run 36858070184) | 200 |
| Dallas | tx_lgbs | Available | Property Division resale FAQ (sealed bids) | 482 |
| Harris | tx_lgbs | Auctions + Available | Tax Office "Harris County Tax Sales" | 327 |
| Jefferson | tx_lgbs | Auctions + Available | Tax Office delinquent tax sale guidelines | 253 |
| Orange | tx_lgbs (Available) / tx_realauction (Auctions) | split | Trust Property bid document / Tax Sale FAQs | 209 |
| Bexar | tx_lgbs | Available | Struck Off Properties general information | 60 |
| Tarrant | tx_lgbs | Auctions | Constable Precinct 3 delinquent tax sales | 40 |
| Fort Bend | tx_lgbs | Auctions | Constable Precinct 2 property sales | 13 |

About 1,584 rows in all: roughly 1,405 of 3,635 Available rows and about 179 of 549 Auction rows.

Not recorded:
- Montgomery: both Tax Office pages returned HTTP 403 to the runner.
- Dallas: the Property Division page was refused by the discovery guard, because its host is also a
  registry row without a source id. The FAQ PDF was read instead.
- Tom Green: refused by the discovery guard for the same reason.
- Montague: the page only points to the delinquent-tax attorney.
- Every other county: no official process page was found.

## Applying it (after merge)

1. Property facts: run `job=enrich` with `enrich_states=TX` and `enrich_kinds=parcels`. Optionally add
   `enrich_limit=N` to cap the rows per layer; the checkpoint resumes where the last run stopped.
   - That leg runs `enrich_statewide_parcels.py --all-layers` (#220). For TX, every cleared layer means
     `tx_txgio_stratmap_parcels` and `tx_hcad_parcels`. Jim Wells' CAD layer stays UNREVIEWED and is refused.
   - `--limit` bounds the rows per layer. A county_file layer downloads only the county files of the rows in that
     batch.
   - Without a limit, all 83 county files are read, roughly 3-4 GB, which fits the leg's 150-minute budget.
   - By hand, the same script also takes `--source-id a,b`, `--ledgers laft,auction`, `--counties` and
     `--max-counties`. Add `--dry-run` for a read-only plan.
2. How to buy: run `job=available` with `available_mode=acquisition`. The step runs with
   `--ledgers laft,auction` and also runs inside the scheduled `laft` job.

## 3. Coordinates for the listings that arrived after the first measurement (2026-10-28)

Production (read-only, counts only, 2026-10-28): the active TX rows without coordinates were mostly
PBFCM / MVBA / GovEase listings and two county lists that joined after the 2026-10-27 measurement.
Census address matching had already failed for them (most rows publish no house number). Causes:

| County | Rows without coordinates | Cause | Fix | Sample matched (one record) |
|---|---|---|---|---|
| Trinity | 343 (`tx_trinity_cad_resale`) | county not configured AND source not served | PROP_ID, alnum; source served | 20/20 |
| San Jacinto | 96 (PBFCM) | not configured; accounts written `R` + digits | PROP_ID, `r_account` | 20/20 |
| Bell | 53 (MVBA) | not configured | PROP_ID, alnum | 20/20 |
| Dimmit | 42 (PBFCM) | not configured | PROP_ID, alnum | 16/20 |
| Uvalde | 40 (PBFCM) | not configured | PROP_ID, alnum | 20/20 |
| Matagorda | 40 (PBFCM) | the 2026 file leaves PROP_ID empty; its GEO_ID is a map number | **none** (no deterministic key) | 0/20 |
| Hill | 38 (PBFCM) | not configured | PROP_ID, alnum | 20/20 |
| Bastrop | 37 (MVBA) | not configured | PROP_ID, alnum | 18/20 (2 manufactured homes only) |
| Waller | 37 (PBFCM) | not configured; `R` parcels and `N` mineral leases | PROP_ID, `r_account` | 12/20 (6 `N` leases never match) |
| Val Verde | 28 (MVBA) | configured on GEO_ID (LGBS's 12 digits); MVBA writes PROP_ID | GEO_ID + PROP_ID, alnum | 20/20 |
| Brown | 24 (MVBA) | not configured | PROP_ID, alnum | 20/20 |
| Brewster | 20 (PBFCM) | not configured; `R` prefix | PROP_ID, `r_account` | 20/20 |
| Chambers / Walker / Palo Pinto / Panola / Knox / Newton / Wichita / Nacogdoches / Milam / Washington / Throckmorton / Runnels | 1-19 each | not configured | measured column + rule | 8/12, 11/12, 9/10, 7/9, 7/7, 4/5, 4/4, 2/2, 1/1, 1/1, 1/1, 1/1 |
| Reeves | 9 (PBFCM) | configured on GEO_ID (LGBS); PBFCM writes PROP_ID | GEO_ID + PROP_ID, alnum | 8/9 |
| Randall | 3 (`tx_randall_trustee_property`) | not configured, source not served | PROP_ID, alnum; source served | 3/3 |
| Bexar / Jefferson / Orange | 14 / 6 / 4 (county lists) | source not served (the configured GEO_ID already matches) | source served | 12/12, 6/6, 4/4 |

Not changed: Hays (3 PBFCM `R` rows) and Jasper (6) - their LGBS rows key on GEO_ID with another rule, and
one county takes one rule; Hunt (the file has no PROP_ID); Matagorda; single rows in large configured
counties (Galveston, Fort Bend, Montgomery, McLennan, Maverick, Zavala, Austin) whose one sampled account
did not match.

Method: each county's 2026 StratMap zip was downloaded from the public warehouse (reachable from the
sandbox); up to 20 production accounts of rows WITHOUT coordinates per county were normalized by each rule
and counted against PROP_ID / GEO_ID (counts only, nothing committed). For Bastrop, Brewster, Brown, Dimmit,
San Jacinto, Trinity, Val Verde and Waller the matched record's legal description was compared by hand
with the row's own: every compared pair named the same lot or tract. Where a county serves two columns
(Val Verde, Reeves) the two columns' normalized values never coincide in the 2026 file (0 overlaps), and a
key reaching two different records through them is still AMBIGUOUS.

- New identifier rule `r_account` (`parcels.ID_RULES`): digits, optionally after the district's `R`
  (real property) prefix, leading zeros dropped; any other shape (`N`, `P`, separators) is no identifier.
- `sources.TX_COUNTY_LIST_ACCOUNT_SOURCES` (Harris, Bexar, Jefferson, Orange, Trinity, Randall lists -
  `case_no` is the CAD account per `harvest_tx_county_sales.to_properties_row`) joins the vendor listings
  in `TX_CAD_ACCOUNT_ROW_SOURCES`, served by both StratMap and HCAD. Montgomery's and Hood's lists are left
  out until measured.
- Writes stay fill-blank only: stored coordinates (any origin) are never replaced.

Apply after merge: dispatch `harvest-and-sync.yml` with `job=enrich`, `enrich_states=TX`,
`enrich_kinds=parcels` (optionally `enrich_limit`).
