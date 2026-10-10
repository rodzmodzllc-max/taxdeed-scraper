# Data-quality and enrichment sprint (2026-10-10)

Branch `claude/hopeful-feynman-ykxl7y-quality`, stacked on PR #131
(`claude/hopeful-feynman-ykxl7y`, head `666f7e1`): it uses #131's keyset
reads and per-source unit status. No migration was written or applied, no
workflow was dispatched, no production row was written, and no source was
approved. Every production figure here comes from read-only SQL (`begin read
only`) or an existing job log.

## Baseline re-verified (read-only, 2026-10-10 15:31 UTC)

| Source | Active | Bid ≠ amount (cents) | Not 2 dp | No amount | Distinct case | Parcel length 14 | No coordinates | List date | Path typed | Flood | Publication | Last read |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `sc_horry_forfeited_land` | 51 | 0 | 0 | 0 | 51 | - | 51 | 0 | 51 | 0 | UNREVIEWED | 2026-10-09 18:13 |
| `tn_shelby_landbank` | 2,038 | 0 | 0 | 1 | 2,038 | 2,038 | 1 | 0 | 0 | 0 | UNREVIEWED | 2026-10-09 18:19 |

Every Shelby row carries source status "FOR SALE" and ledger `buy` (Available).

## Tennessee source semantics: the AVAILABLE ledger, decided from the source

`harvesters/otc/adapters/expansion.TN_SHELBY_SEMANTICS` records the answers, and
`tests/python/test_tennessee_enrichment.py` pins them to the config, the ledger
map and the fixture.

| Question | Answer (evidence runs 37855584514 … 37856396525) |
|---|---|
| Publisher | Shelby County Land Bank (county government). It runs its own ePropertyPlus tenant, and the Land Bank's site sends buyers there. |
| What the records are | County-owned parcels already taken through delinquent-tax sales (`inventoryType` "County DTP" on 12,843 of 12,884). This is post-sale, government-held inventory. |
| What "FOR SALE" means | The Land Bank currently offers the parcel. The test is `currentStatus` FOR SALE **and** `available` Y, never the status string alone: SALE PENDING rows with `available` Y are excluded. |
| Transaction | An offer on the Land Bank's Offer to Purchase and Sales Agreement packet. `askingPrice` is a published amount of unspecified kind (OFFER_NEGOTIATED). |
| Auction / sale date | None. Shelby's tax-sale auctions belong to the Clerk & Master, a different source that is not built. |
| Complete for | The Land Bank's published inventory. A read counts as COMPLETE only when every page is read and the row count equals the portal's own `size`. |
| Ledger | **AVAILABLE**: unchanged, and now justified by fields. Never AUCTIONS. There is no Tennessee certificate product. |

Each row now also carries the portal's own `inventoryType` wording in its
provenance (`portal_inventory_type`).

## Enrichment throughput: the geocoder's fair, resumable queue

**Measured** (read-only, 2026-10-10). Rows without coordinates that the
geocoder can read:

- tier 1 (comma or ZIP), 248 rows: FL certificates 123, SC 51, CO 24, FL auctions 17, TX 17, FL Available 12, MI 4;
- tier 2 (bare street), 10,365 rows: MO 9,759, PA 376, OK 195, and others.

The script read 250 rows in physical order and never recorded a failed match.
So the 248 tier-1 rows, which keep failing, took 248 of the 250 slots on every
run, and Missouri got about 2 attempts a run.

**Fix** (`scripts/enrichment_queue.py`, used by `scripts/geocode_properties.py`):

| Requirement | Implementation |
|---|---|
| Configurable, validated cap | `GEOCODE_BATCH_LIMIT` (default 250, max 1,000) and `GEOCODE_PER_UNIT_LIMIT` (default 50). A non-integer or out-of-range value exits 2 before any read. Flood: `FLOOD_BATCH_LIMIT` / `FLOOD_PER_COUNTY_LIMIT` (500 / 40, max 10,000, which covers the manual `enrich` job's 9,000). |
| Why the default stays 250 | The bottleneck was the pinned order, not the budget. The Census Geocoder publishes no per-request quota for its one-line endpoint, so the default was not raised on a guess. |
| Fairness | Units are (state, county). Pass 1 gives each unit 50 rows. Pass 2 hands the leftover out round robin, 50 at a time. The unit order starts after the last unit served by the previous run. |
| Resume / checkpoint | Per unit, the cursor is the last row key processed (`<tier>:<id>`). It is written atomically after each finished row to `out/.harvest_cache/geocode_checkpoint.json`, which the deeds job's existing `actions/cache` step restores and saves. An interrupted run resumes at the unfinished row. |
| Retry | A row that does not match is retried only after its unit has been walked once (the cursor wraps). Census 5xx / timeout: 3 attempts with backoff. A 4xx or a no-match is never retried within the run. |
| Idempotency | The PATCH carries `latitude=is.null`, so a row that gained coordinates since it was read is never overwritten, and a repeated write is a no-op. |
| Concurrency | 1 (sequential), with a 0.4 s pause per request, as before. |
| Logs | Budget, pool size, units, rows planned, verified / no match / rejected / errors / skipped, per state. |

In the fixture with the production shape (248 failing tier-1 rows plus
Missouri rows), one run now writes 100 Missouri rows. Before, Missouri got
about 2 attempts.

The flood step's per-county cap gets the same two-pass plan
(`plan_slices()`, shared), so Tennessee (one county) is no longer held to
40 rows a run.

## Fix 1: the verified baselines are pinned

`data/current_state/verified-baselines-2026-10-10.json` holds counts only.

| Baseline | Evidence | Pinned figures |
|---|---|---|
| Horry SC | run 37971480332, commit 09ee30b incl. e7040d2, SC job 113958930434 | 51 active; 0 bid / amount discrepancies (was 23); 0 amounts off 2 dp; 0 missing amounts |
| Tennessee Shelby | TN job 113958930478 | portal 12,884 = 2,038 offered + 10,846 not; COMPLETE; 0 malformed / duplicate ids; 2,038 synced; 0 closed; 1 row without coordinates; 1 row NOT_PUBLISHED; all UNREVIEWED |

`tests/python/test_data_quality_sprint.py` covers:

- **Horry:**
  - bid = amount to the cent at 2 dp;
  - a blank or "N/A" cell stays NOT_PUBLISHED (the legacy `bid` 0 sentinel, never a price);
  - `to_cents` is idempotent;
  - a re-run of the same input plans identical rows with one `last_seen_at`;
  - the sync never sends an enrichment column (flood, imagery, coordinates, land use, taxable value), and it keeps their provenance entries.
- **Tennessee:**
  - only offered rows, with unique, 14-character, upper-case identifiers;
  - a whitespace-padded duplicate folds to one identity;
  - FAILED / INCOMPLETE / unread closes nothing;
  - a COMPLETE read syncs every offered row UNREVIEWED;
  - zero, blank, "N/A" and negative asking prices stay NOT_PUBLISHED;
  - (0,0), blank, out-of-range or non-numeric points keep the record without inventing coordinates.

**Defect fixed:** the ePropertyPlus adapter reported COMPLETE when an
offered row's parcel id failed the pattern. Close-out treats COMPLETE as the
whole list, so a stored row the portal still offers under a reformatted id
would have been closed. That read is now INCOMPLETE: the good rows are
refreshed and nothing is closed. Production had 0 rejected ids, so no
baseline changes.

## Fix 2: Tennessee enrichment, nothing published

| Item | Result | Why |
|---|---|---|
| A. Acquisition path | Unit `NEEDS_REVIEW`, basis `capture` (runs 37856189946 / 37856396525); candidate page `https://landbank.shelbycountytn.gov`; every row `source_list_only` | The Land Bank's Policies & Procedures page links an *Offer to Purchase and Sales Agreement Packet*. It is a scanned PDF with no text layer, so it was not read, and its address was not recorded and is not guessed. No URL is constructed. |
| | New `acquisition_evidence_status.evidence_type()` | Five types: property_specific / listing_level / application_process / source_list_only / no_verified_online_path. A type comes only from a typed, https path or a VERIFIED unit, never from a URL's existence. |
| B. `list_as_of` | Stays empty on all 2,038 rows | The portal publishes no list date. `epropertyplus.list_date()` accepts a calendar date, or an ISO datetime with its offset (the date as written, never shifted to UTC). It refuses naive datetimes, epoch numbers and malformed text. It runs only for a configured `list_as_of_field`, and none is configured. The read time is never used. |
| C. Parcel enrichment | Blocked; no request | No Tennessee parcel / assessment layer has been identified and reviewed. `enrich_statewide_parcels.py --state TN` prints `skip: TN statewide parcel source not cleared (none configured)`. A test shows an UNREVIEWED layer would be refused before any request. |
| D. Missing coordinate | Row `5ba08fb4-0d61-4b47-a118-fb0a1d34b5ea` (internal id). Unresolved by design. | No approved Tennessee coordinate layer exists (`plan_row` -> NO_SOURCE). **Defect fixed:** the deeds job's Census address geocoder reads every row without coordinates, so it would have given this row an address point beside 2,037 Land Bank GIS points. `NO_ADDRESS_GEOCODE_SOURCES` now excludes `tn_shelby_landbank`, with a NULL-safe filter so Florida rows without `harvester_source` are still geocoded. |
| E. Flood | 0 of 2,037 checked (source matrix) | **Defect fixed:** the FEMA step gave each county at most 40 rows a run and never handed the rest of its 500-row budget on, so one-county Tennessee would have taken about 51 runs (~25 days). `plan_slices()` keeps the per-county first slice, then gives leftover budget to units with a backlog. The total stays ≤ 500 and no unit gets more than its backlog. The outcomes are unchanged: unchecked (NULL), `UNMAPPED` (no FEMA polygon), a zone, or a failed request, which writes nothing and is retried. |
| F. Publication gate | Unchanged | Tests show a COMPLETE harvest plans every row `UNREVIEWED` and that no enrichment script writes `publication_status`. `config.js` keeps `publicationMode: "preview"`, and app.js keeps "Source review:" and "withheld - source not approved for customer publication". |

## Fix 3: all-state measurement

`scripts/sql/source_quality_matrix.sql` is read-only and counts only. Its
output, measured 2026-10-10 15:23 UTC, is in
`data/current_state/source-quality-2026-10-10.json`, rendered by
`scripts/source_quality_report.py` into `docs/source-quality-matrix.md`. The
report has one row per state × source × ledger and one per county. Every cell
is `n/N` over that row's active rows. A test pins the rendered file.

| Defect class (priority order) | Measured | Action |
|---|---|---|
| 1. Stale dates | 43,603 of 58,312 active rows not read within 36 h: Detroit 30,770, LA 10,334, FL certificates 1,611, TX 543, FL auctions 329, FL Available 16 | Detroit and LA are fixed by #131, not yet merged. FL certificates: LienHub read INCOMPLETE, correctly not stamped. Texas is manual-only by design. FL auctions: rows off the county's current sale list, already labelled (`offCurrentSaleList`). |
| 2. Failure treated as empty | ePropertyPlus rejected-id case | Fixed (Fix 1) |
| 3. Lifecycle | 0 rows with first_seen after last_seen; 161 active auctions with a past sale date (FL 4, MI Lenawee 35, TX 122) | Not closed on the calendar alone; `isPastDue()` already keeps them out of every count (#131 doc) |
| 4. Broken URLs | 0 non-https list / sale links. TX LGBS auctions 0/19 with any link (manual-only; last read before links were stored) | No change: a link is never constructed |
| 5. Parcel normalisation | 0 parcels without a digit. **Texas: 97 rows beyond the first share a "parcel" value: 32 LGBS causes repeated on 126 active Available rows (largest 26), plus 2 LGBS-auction and 1 RealAuction groups** | **Fixed (Fix 4).** The Texas `parcel` column holds the tax-suit cause number, not a parcel. |
| 6. Enrichment / provenance | coordinates 46,830 / 58,312; flood 14,456 / 58,312; MO / OK / PA / SC Available 0 coordinates | TN flood budget fixed; the rest needs approved sources or owner-dispatched jobs |
| 7. Duplicates | 0 duplicate identities. The repeated parcel *values* are the Texas causes above. | - |
| 8. Count mismatches | Horry 0; TN offered = synced | - |
| 9. Privacy | Every new file is counts only; the matrix test refuses any non-count field | - |

Not done, as instructed: no LGBS retry, no GovEase, no blocked vendor, no new source.

## Fix 4: customer-facing trust

**Defect fixed: Texas cause numbers were shown as parcels and used as parcel
identity.**

`harvesters/texas_harvester.py` stores the tax-suit Cause Number in
`parcel` and the CAD account in `case_no`. One cause covers several parcels.
The frontend did two things wrong with this:

- it printed the cause as "Parcel #" on cards, the property page, the
  inventory card, copy buttons and exports;
- its cross-ledger matcher (`parcelKey` → `relatedRecordsFor`, which also
  drives the watchlist fold and the "Same parcel in other ledgers" export)
  told customers that up to 26 different properties were "the same parcel".

Now:

- `parcelOf(p)` is the CAD account for `tx_lgbs` / `tx_realauction` rows, and
  the parcel for every other row;
- `causeOf(p)` is shown as "Tax suit cause #" and as "Cause …" in the
  identifier lines;
- exports add a "Tax Suit Cause" column.

Playwright `?txcause=1` loads two Galveston rows that share one cause.
Neither is related to the other, the card shows each one's own account as
its parcel, and the cause is labelled as a cause. `sw.js` → `tdw-shell-v116`
(v115 is held by #130).

The other trust items were checked against the existing suite and remain
pinned there:

- unpublished amounts are never shown as zero, and application amounts are never shown as sale prices (`amountInfo`, financial-terms tests);
- opening bids are never shown as winning bids (`auctionBidLabel`);
- unverified paths are never purchase links (`acquireBlockHtml`, the "No online purchase link on file" wording);
- unreviewed Tennessee rows are withheld (`tnVisibility`);
- missing coordinates fall back to the county view;
- a publication date is never shown as the last read;
- there are no scores or confidence meters.

## Before / after

| Metric | Before | After this branch | Evidence |
|---|---|---|---|
| Horry bid / amount discrepancies | 23 → 0 (e7040d2) | 0, pinned by tests; the check now compares at whole cents (`amounts_disagree`, SQL `round(.,2)`), so a scale-only difference can never read as a discrepancy | baseline file; re-verified 15:31 UTC |
| Geocoder Missouri attempts per run behind failing rows | ~2 | 100 (fixture with the production shape) | `test_failing_context_rows_no_longer_starve_the_second_tier` |
| TN rows a rejected-id read could wrongly close | every stored row of an affected id | 0 (INCOMPLETE read) | `test_tn_offered_row_with_an_unrecognised_id_...` |
| TN flood rows possible per run | 40 | up to 500 (the run budget) | `test_plan_slices_...`, `test_flood_run_...` |
| TN rows open to an address geocode | 1 | 0 | `test_address_geocoder_never_reads_...` |
| TN acquisition unit status | NOT_FOUND | NEEDS_REVIEW (capture) | `public/acquisition-evidence.json` |
| Texas active rows sharing a "parcel" with an unrelated property | 126 Available + 6 auction rows | 0 (matched on account) | Playwright `txCauseDetail` |
| Production row values changed | - | none | no write performed |

### Tennessee breakdown (production, read-only, 2026-10-10)

| Measure | Count |
|---|---|
| Active Shelby rows | 2,038 / 2,038 UNREVIEWED |
| Parcel (14-character) | 2,038 / 2,038 |
| Coordinates (Land Bank GIS) | 2,037 / 2,038 |
| Amount published (asking price, kind unspecified) | 2,037 / 2,038 |
| Official list link | 2,038 / 2,038 |
| `list_as_of` | 0 / 2,038 (not published by the portal) |
| Acquisition path typed | 0 / 2,038 (NEEDS_REVIEW; offer packet not read) |
| Flood checked | 0 / 2,038 (budget fix lands on the first deeds run after merge) |
| Read within 36 h | 2,038 / 2,038 (last read 2026-10-09 18:19 UTC) |

## Remaining blockers (owner decisions, not code)

- Reading the Shelby offer packet: it needs OCR of a scanned PDF and the Land Bank's reuse terms reviewed.
- A Tennessee parcel / assessment layer: none identified or reviewed.
- Approving any UNREVIEWED source for customers.
- Merging #131, then this PR. The "after" production numbers need the scheduled runs on the merged code; none were dispatched.
- Migrations 015, 016, 024, 027, 028 and 029 stay unapplied and untouched.
