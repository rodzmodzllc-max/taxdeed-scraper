# AVAILABLE discovery across the supported states (2026-10-02)

AVAILABLE means a source itself establishes that a property is held by a
government and offered for purchase or application: a county's
lands-available list, a struck-off list, a Forfeited Land Commission list, an
over-the-counter list of tax-deeded land, a land bank's inventory.

AVAILABLE is never inferred from any of these:

- an auction row disappearing;
- a sale date passing;
- a parcel going unsold;
- an unknown outcome.

## Where AVAILABLE stood (production, read-only count, 2026-10-02)

| State | Active AVAILABLE rows | Production AVAILABLE source |
|---|---|---|
| FL | 157 | county Lands Available lists (52 registry sources) |
| LA | 10,334 | East Baton Rouge adjudicated property (dated list) |
| TX | 421 | LGBS listing (manual-only, REVIEW_REQUIRED) |
| MI, WY, SC, CO, WI | 0 | none |

AL, AR, AZ, UT and WV are registered but not activated. They have no
AVAILABLE rows and no state page.

## What was found (web search only - no page read)

The sandbox cannot reach county hosts, and no production workflow was
dispatched for this sprint. Every candidate below is therefore search-index
evidence. Each is recorded as REVIEW_REQUIRED / NOT_CHECKED:

- in `data/enrichment_source_catalog.csv`, where it shows in the Admin
  Sources panel;
- with its page in `data/available_discovery_pages.csv`.

None is a registry source, so no harvester or sync reads it.

| State | Program | Counties |
|---|---|---|
| SC | Forfeited Land Commission: a parcel with no bid at the tax sale is struck to the county FLC, which assigns the bid during redemption and sells the land afterwards | York (posted in January per the county fact sheet), Richland, Spartanburg, Georgetown, Oconee, Jasper, Fairfield, Aiken, Lexington |
| WI | County tax-deeded land offered over the counter after a failed sale | Wood, Burnett (indexed as none available now), Marathon |
| MI | County land bank holding tax-foreclosed property | Lenawee |

`data/available_state_research.csv` records the states with no qualifying
program:

- **CO:** unsold parcels stay with the county as county-held tax liens,
  assigned on request. The Treasurer's Deed option is sold at auction.
- **WY:** counties sell liens, not property. An unsold parcel is bid in as a
  county-held certificate.

These are lien and auction instruments, so CO and WY correctly stay at 0. A
county-held lien list is a Liens & Certificates candidate, not an Available
one.

## Coverage vocabulary

`harvesters/sources/available_coverage.py` (generated into
`public/available-coverage.json`) names each state's AVAILABLE zero:

| Status | Meaning |
|---|---|
| SOURCE_TRACKED | a production AVAILABLE source is read; a zero means its last read found nothing current |
| SOURCE_EMPTY | the production source's last read was EMPTY |
| SOURCE_UNAVAILABLE | every production source's last read FAILED |
| MATCHING_FAILED | the last read could not be matched to identifiers |
| REVIEW_REQUIRED | no production source; discovered candidates await capture and review |
| HARD_BLOCKED | only blocked sources were found |
| NO_QUALIFYING_PROGRAM | researched: the post-sale instrument is a lien or an auction |
| NO_SOURCE_DISCOVERED | nothing found yet |

When the Available ledger holds no row for the page's state, its empty state
adds a "Why this list is empty" line with the status and the candidate
counties. A state with rows never shows the line.

## Next step for each candidate (owner action)

1. **Capture.** Dispatch `job=evidence` with
   `evidence_scope=available_discovery`. It runs
   `capture_purchase_evidence.py --candidates --candidates-file data/available_discovery_pages.csv --follow`.
   The capture is value-free and writes to no database.
2. **Read the digest in the job log.** Confirm that:
   - the page states current availability;
   - it carries a deterministic identifier (parcel / account / FLC number);
   - it states reuse terms.
3. **Review.** Record a publication decision. A source stays REVIEW_REQUIRED
   until then.
4. **Configure and verify.** Configure the shared adapter
   (`harvesters/otc/adapters/expansion.py`, ArcGIS or tabular) and validate it
   against a fixture from the capture. Add the registry row with ledger
   AVAILABLE.

Only then can rows reach `properties` through `sync_state_inventory.py`.
