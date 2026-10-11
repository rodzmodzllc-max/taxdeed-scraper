# Inventory (lifecycle) status: one rule, every ledger, every state

`properties.inventory_status` (migration 021) is the customer-facing lifecycle
state of a row, normalized across sources by one module,
`harvesters/governance/inventory_status.py`, and written by one gated script,
`scripts/inventory_status_writer.py`. This page records the rule as of
2026-10-11, the gap it closed, and what it refuses to infer.

## The gap (2026-10-11, read-only production measurement)

| Population | Rows | With a status before | After the next writer run |
|---|---|---|---|
| AVAILABLE rows outside Florida (LA, MI, MN, MO, OK, PA, SC, TN) | 53,559 | 0 | 53,559 |
| Texas rows (LGBS auction + AVAILABLE, RealAuction auction) | 543 | 0 | 543 |
| Florida (every ledger) | 4,235 | 4,235 | unchanged |

Cause: `status_for_row()` dispatched non-Florida rows to `adapter_record_status`,
which maps auction and certificate rows only; Louisiana was excluded by state;
Texas rows were matched on `harvester_source` alone (production rows carry
`source_id`). The writer never ran for Louisiana at all. A second defect:
observation rows (`inventory_status_observations`) recorded `source_id` from
`harvester_source`, which Florida rows do not carry - 4,857 observations had
none.

Counts-only replay: `docs/review/inventory-status-dryrun-2026-10-11.md`
(`scripts/inventory_status_gap_report.py --check` pins it).

## The rule for AVAILABLE rows outside Florida

`available_record_status(row, source_id=...)`, dispatched for every
`source = 'laft'` row whose state is not FL and that names a source id:

| Observation | Status | Basis |
|---|---|---|
| pipeline status closed / dropped / notfound (absent at a COMPLETE / EMPTY read) | `closed` | LIST_PRESENCE |
| the adapter's own sold flag (`otc_provenance.published_outcome = sold`) with its wording | `sold` | SOURCE_STATUS |
| `inventory_status_raw` is one of the source's published offered wordings | `available_otc` | SOURCE_STATUS |
| on the list, any other wording (e.g. a program name) | `active` | LIST_PRESENCE, wording kept verbatim |
| on the list, no wording | `active` | LIST_PRESENCE; a dated list is named |

`AVAILABLE_OFFERED_WORDINGS` is the only path to `available_otc` outside
Florida: the Detroit Land Bank statuses, St. Louis LRA "Available", Ramsey
"Available for purchase", Shelby "FOR SALE". A test pins the table to the
adapter configs that select those rows. Oklahoma, Fayette, Horry, Georgetown,
Oceana and the Louisiana adjudicated list publish no per-row availability
wording, so their rows are `active` ("Listed"), never promoted on inference.
Florida's own `available_otc` on list presence is unchanged: it rests on
F.S. 197.502(7), which no other state's list has been verified against.

The rule does not need `otc_provenance.adapter` (6,334 Louisiana rows had lost
it to a later sync); it keys on `source_id`.

## Auctions read from a sale calendar

`feed_auction_status` (Florida and Texas RealAuction): scheduled date ahead →
`upcoming`; passed → `unknown` ("the feed publishes no result"); none →
`active`; left the feed → `closed`. Texas LGBS keeps its vendor-status rule.

## What is never done

- A result (sold / redeemed / cancelled / withdrawn / struck off) only from the
  source's own status wording. Absence is `closed`.
- No row is deleted, closed or re-statused by this change itself: the status
  is derived from the pipeline status the syncs already maintain under their
  own COMPLETE / EMPTY gates, and written by the existing probed writer.
- No list is called current because it is on file: a dated list's date rides
  in the basis text.

## Where it runs

- `laft` job: Florida, then (new) `--state LA` after the Louisiana lifecycle.
- `expansion` matrix: one run per state.
- `texas` job (manual only): `--state TX`.

Writing to production happens only through those scheduled jobs after merge;
nothing in this repository change writes a row.
