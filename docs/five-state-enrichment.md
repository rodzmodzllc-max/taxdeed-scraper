# Five-state enrichment sprint: MI, WY, SC, CO, WI (2026-10-01)

Branch `feat/five-state-enrichment`, starting from main `aba5c68` (PR #57 and
PR #58 merged).

This sprint builds on the five states PR #57 activated. It covers lifecycle,
freshness, provenance, acquisition evidence and new sources, all checked
against the repository's publication gate.

**What this sprint does not do:**
- No migration.
- No source is approved by assumption.
- No row is written for a source without an APPROVED publication decision.

## 1. What #57 shipped, measured before this sprint

The rows below were checked in production on 2026-10-01, before any write.

| | MI | WY | SC | CO | WI |
|---|---|---|---|---|---|
| Sources | Eaton, Lenawee layers | Albany layer | York layer | Morgan certificate page | Green tax-deed page |
| Rows (active / closed) | 38 / 5 | 253 / 0 | 853 / 0 | 3 / 0 | 0 / 9 |
| `last_seen_at` set | 0 | 0 | 0 | 0 | 0 |
| `inventory_status` set | 0 | 0 | 0 | 0 | 0 |
| `field_provenance` set | 0 | 0 | 0 | 3 (statewide parcels) | 0 |
| `sale_date` set | 0 | 0 | 0 | n/a | 9 |
| Verified acquisition path | 0 | 0 | 0 | 3 | 0 |

**Gaps this exposed:**
- **No freshness or lifecycle:** the sync never stamped `last_seen_at`, and nothing wrote `inventory_status` or observation history for adapter rows.
- **List values were unprovenanced.**
- **Enriched values could be nulled:** the sync's bulk upsert sent every key in the batch, so it could null a value the enrichment factory had filled.
- **Albany WY's list was for a sale that has already happened.** Live evidence shows the county's pages now name the next sale (August 13, 2027), but its rows still read "Listed".
- **No verified purchase path for MI, WY or SC.**

## 2. How sources were found and verified

1. Five discovery agents ran web searches, one per state. Their results were search-index evidence only; no state host was reachable from the sandbox.
2. Every candidate was then read live, value-free, by the manual evidence job (`harvest-and-sync.yml`, `job=evidence`):

| Pass | `evidence_scope` | Run | What it reads |
|---|---|---|---|
| 1 | `five_state` | 36793062673 | process pages, ArcGIS layers, service directories, catalog items and searches |
| 2 | `five_state_pass2` | 36793611223 | PDFs as process text, identifier SHAPES and category value counts under a WHERE clause, parcel services |
| 3 | `five_state_pass3` | 36793980491 | Douglas CO licence text and lien types, Wisconsin parcel licence, York SC |

What the capture keeps (`scripts/capture_state_sources.py`):
- **Process text** keeps dates, times, amounts and office phone numbers.
- **Masked:** any token that could be a parcel, account, case or certificate number.
- **Category fields** (a sale flag, a tax year, a lien type) are counted. An owner, address or amount never is.

## 3. Source matrix (investigated sources only)

### Michigan

| Category | Source | Verified | Publication | Status |
|---|---|---|---|---|
| A auction | Eaton "For Sale 2026" layer; Lenawee "2026 Tax Sale" layer | #57 + probe: Eaton 8 rows, Sold Yes 5 / No 3 | owner 2026-09-30 | production (unchanged) |
| L acquisition | Eaton "2026 Foreclosure Sale" page: last 2026 auction, in person, **Oct 22, 2026, 6:00 p.m.**, Eaton County Governmental Complex, 1045 Independence Blvd, Charlotte | pass 2 | n/a (process text) | **verified path, applied to active Eaton rows** |
| L acquisition | Lenawee "Tax Sale" page: online scavenger sale Oct 6, 2026 on a vendor site the county names; minimum-bid auction; pay by Oct 8, 11:30 AM; cash, money order, cashier's check | pass 1 | n/a | **verified county instructions** (the vendor site is not linked) |
| B available | Genesee County Land Bank inventory (HTML table, paginated) | pass 1-2 | **Terms forbid it:** "You will not modify, publish, transmit ... GCLBA content is not for resale ... solely for your personal use" | **not implemented** |
| B available | Lenawee Landbank page (2 rows, "Last Updated 7/22/2026", no parcel numbers) | pass 1 | no licence | not implemented (2 address-only rows, no deterministic identity) |
| D-K enrichment | Eaton Parcels_AGO, Lenawee_Parcels_Public layers (no values) | pass 2 | no licence | not implemented (no values to add) |
| | Michigan statewide parcel / value layer | - | - | none exists publicly |

### Wyoming

| Category | Source | Verified | Publication | Status |
|---|---|---|---|---|
| A auction | Albany 2026 1st-list layer | probe: 253 rows, all tax year 2026; the county's pages now name the next sale, **Aug 13, 2027** | owner 2026-09-30 | production; **marked superseded** (status "Not published", never "Listed") |
| A auction | Albany `2026TAXSALEPROP_1STC` layer (139 rows, edited on sale day) | pass 2 | - | not used: the county publishes no meaning for it |
| A auction | Lincoln, Sweetwater, Niobrara, Laramie and other county pages | pass 1 | - | not implemented: the lists are PDF or newspaper only |
| D-K enrichment | WY DEQ `WY_PRIVATE_PARCELS` (no layers served); Sheridan parcels (no Sheridan inventory) | pass 1 | - | not implemented |

### South Carolina

| Category | Source | Verified | Publication | Status |
|---|---|---|---|---|
| A auction | York "Tax Sale Properties" layer | #57 | owner 2026-09-30 | production (unchanged) |
| L acquisition | York "Tax Sale Fact Sheet and Disclaimer" (PDF) + Tax Collection phones | pass 2-3 | n/a | **verified in-person path** (opening bid makeup, same-day payment, 12-month redemption at 12%) |
| A auction | **Oconee "Delinquent Tax Sale List"** (HTML table; today only "The 2026 Tax Sale is scheduled for Monday, November 9, 2026.") | pass 1 | no licence | **implemented, UNREVIEWED** (no request, no row) |
| B available | Forfeited Land Commission lists (Lexington, Lancaster, Horry, Richland, Georgetown, Berkeley, Spartanburg ...) | pass 1 | - | not implemented: PDF / XLSX or by request; Richland and Berkeley returned 403 |

### Colorado

| Category | Source | Verified | Publication | Status |
|---|---|---|---|---|
| C certificates | Morgan county-held certificate page | #57; contact (phone, P.O. box) pass 1-2 | owner 2026-09-30 | production; evidence row upgraded |
| C certificates | **Douglas County "Tax Liens" open data**, filtered to county-held (`type = 'CHL'`, re-checked per row) | pass 3: licence, 808 rows, lien types CHL / L | **CC BY-SA 4.0** stated on the item + Open Data Guidelines | **production** |
| A auction | **Douglas "Tax Sale List Locations"**, with a cycle guard (Tax_Year 2025 -> the Nov 5, 2026 sale) | pass 2-3: every row today is Tax_Year 2024 | **CC BY-SA 4.0** | **production, EMPTY today** (`past_cycle`); the 2026 list flows in once posted |
| A auction | **Morgan "Treasurer's Deed Option Auctions"** (105 rows: deed #, auction date, account, certificate #) | pass 1 | no licence (the owner's 2026-09-30 approval covered the certificate page only) | **implemented, UNREVIEWED** |
| L acquisition | Douglas "Request for Assignment of County-Held Tax Lien" (PDF) | pass 3 | n/a | **verified application path** |
| D-K enrichment | Colorado Public Parcels (OIT), matched on (countyName, account) | #57 | owner 2026-09-30 | now also enriches **Douglas** rows |
| | Mesa, Kiowa, Adams, El Paso, Weld, Larimer county-held lists | pass 1 | - | not implemented: PDF / Excel, posted in office, or a vendor site |

### Wisconsin

| Category | Source | Verified | Publication | Status |
|---|---|---|---|---|
| A auction | Green tax-deed page | #57; clerk address and phone from the bid form (pass 2) | owner 2026-09-30 | production; evidence row upgraded |
| A auction | **Dane "Tax Deed Auction"**: `tblAuction` (20 available: Bid Due, Minimum Bid, per-parcel Bid Form) and `tblAuctionSold` (132: "$bid SOLD - $price") | pass 1 | no licence ("Copyright County of Dane") | **implemented, UNREVIEWED** |
| D-K enrichment | **Wisconsin V12 statewide parcels** (3,574,646): assessed land / improvement / total value, fair market estimate, acres, owner, site address; Green PARCELID 13 digits, Dane 12, matching each county's published numbers digit for digit | pass 1-3 | "free for public consumption" / "provided free of charge"; **no explicit reuse grant** | **implemented, UNREVIEWED** (`enrichment_allowed()` refuses) |
| | St. Croix, Wood, Sauk, Pierce, Juneau, Lincoln | pass 1 | - | not implemented: listings are text blocks or documents; Lincoln returned 403 |

## 4. Architecture added (shared, not per state)

### Lifecycle and freshness
`harvesters/governance/inventory_status.adapter_record_status`. It applies to any row written by the shared ArcGIS or table adapters; there is no per-state code.

| Row | Status | Basis |
|---|---|---|
| Auction, sale date ahead | upcoming | `SCHEDULED_DATE` |
| Auction, sale date passed | unknown | `SCHEDULED_DATE` |
| Auction, no sale date published | active | `LIST_PRESENCE` |
| List superseded by a later county sale (Albany) | unknown | the county's own words |
| Off the list, with the source's own sold flag or a published sale price | sold | `SOURCE_STATUS` |
| Off the list otherwise | closed | `LIST_PRESENCE` (never sold) |
| Certificate on the list | certificate_listed | `LIST_PRESENCE` |
| Certificate off the list | closed | `LIST_PRESENCE` |

The expansion job now runs `inventory_status_writer.py` per state, and every change writes an observation row.

`sync_state_inventory.py` changes:
- stamps `last_seen_at` on every row read;
- stamps `delisted_at` on close-out;
- merges `field_provenance`: list values are recorded as `county_list`, and enrichment entries are kept;
- aligns keys **per source**, so a column a source never publishes is never sent and never nulls an enriched value.

### Publication, review-aware
`scripts/source_publication.py` decides what a source may do:
- **Decision:** the registry CSV, plus the latest valid admin review (`source_publication_reviews`), validated by the same `apply_reviews` that `publication_gate.py` uses.
- **Harvest:** `harvest_expansion.py` requests only APPROVED* sources. UNREVIEWED ones log `GATED` and make zero requests.
- **Sync:** `sync_state_inventory.py` writes no row of a source that is not publishable (`withheld_not_publishable`), and closes out only publishable sources' rows.
- **Approval:** approving a source in the admin panel turns it on; no code change is needed.

### Adapters
**Table adapter:**
- `table_id`;
- `amount_sold_pattern`: "$bid SOLD - $price" becomes a published result;
- per-row links on the source's own host (`row_links`);
- date and time cells;
- `empty_patterns`.

**ArcGIS adapter:**
- certificate number and `issued_date`;
- the **sale-cycle guard** (`cycle_field` / `cycles` / `past_cycle`);
- `superseded`;
- `require`: a server-side filter re-checked on every feature, so an unfiltered response is FAILED.

### Acquisition
- `purchase_path_engine.resolve`: a row's own verified link, such as Dane's per-parcel bid form, keeps its property scope and takes the source's verified steps and contacts.
- New evidence rows in `data/purchase_path_evidence_expansion.csv`:
  - Eaton, Lenawee, York and Douglas;
  - Dane and Morgan deed auctions, dormant until their sources are approved;
  - Morgan certificates and Green, upgraded with contact details.

### Enrichment
- `harvesters/enrichment/sources.py` gains `wi_sco_v12_parcels` (UNREVIEWED).
- Douglas rows are enriched by the existing Colorado statewide parcel configuration, keyed on the assessor account.

## 5. Not done, and why
- **No AVAILABLE inventory in any of the five states.**
  - The only government-held "available now" lists found are Genesee Land Bank, whose terms forbid publication, and Lenawee Landbank, two address-only rows.
  - South Carolina's Forfeited Land Commission lists are PDF or XLSX; Wisconsin's over-the-counter lists are text blocks or documents.
  - None is turned into AVAILABLE inventory by inference.
- **No new imagery.** No legally usable per-parcel imagery source was verified, and Google Street View is excluded. The existing county-context mini-map remains.
- **Three sources and one parcel layer await a publication decision:** Dane WI, Morgan CO deed auctions, Oconee SC, and the WI V12 parcels. They are listed in the admin publication panel.

## 6. Production after this sprint

This section describes production run
[36795385054](https://github.com/rodzmodzllc-max/taxdeed-scraper/actions/runs/36795385054)
(`job=expansion` on `88edd37`). Every count below was read from `properties`
after the run.

The previous attempt, run 36794968470, wrote nothing. Every upsert was
rejected by `properties_seen_order_check` (`last_seen_at >= first_seen_at`):
new rows took `first_seen_at = now()` at insert time, which is later than the
run's `last_seen_at`. The sync now sends `first_seen_at` with every row:
- a stored row keeps its stored value;
- a new row is first seen at the run's observed time.

Test: `test_y01b_first_seen_never_follows_last_seen`.

| | MI | WY | SC | CO | WI |
|---|---|---|---|---|---|
| Rows active / closed | 38 / 5 | 253 / 0 | 853 / 0 | 146 / 0 | 0 / 9 |
| Ledger | Auctions | Auctions | Auctions | Liens & Certificates | Auctions |
| Counties | 2 | 1 | 1 | 2 (Morgan 3, Douglas 143) | 1 |
| `last_seen_at` within 36 h | 43 / 43 | 253 / 253 | 853 / 853 | 146 / 146 | 9 / 9 |
| `inventory_status` | active 38, sold 5 (Eaton's own flag) | unknown 253 (superseded list) | active 853 | certificate_listed 146 | sold 8 (published price), closed 1 |
| `field_provenance` | 43 / 43 | 253 / 253 | 853 / 853 | 146 / 146 | 9 / 9 |
| Statewide parcel enrichment | n/a (no source) | n/a | n/a | 119 / 146 matched, 116 written, 27 unmatched, 0 ambiguous | 0 (V12 UNREVIEWED) |
| Coordinates | 43 / 43 | 253 / 253 | 853 / 853 | 119 / 146 | 0 / 9 |
| Imagery | 0 | 0 | 0 | 0 | 0 |
| Verified acquisition path | 38 / 38 active | 0 / 253 (sale over; next Aug 13, 2027) | 853 / 853 | 146 / 146 | 0 (no active rows) |
| Published results | 0 | 0 | 0 | 0 | 8 (county Sale Price) |

**Douglas County tax sale list:** read COMPLETE. It is tax year 2024, so it is
EMPTY with signal `past_cycle`, and 0 rows are written.

**Sources gated before any request:** Dane WI, Morgan CO deed auctions and
Oconee SC (`GATED publication=UNREVIEWED - 0 requests`).

**Florida and Texas after the run:**

| State / ledger | Active | Total |
|---|---|---|
| FL auction | 1,077 | 2,038 |
| FL certificate | 1,611 | 1,667 |
| FL laft | 157 | 167 |
| TX auction | 122 | 122 |
| TX laft | 421 | 421 |

The expansion job reads and writes only its own matrix state.
