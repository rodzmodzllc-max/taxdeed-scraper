# Verified auction outcomes (2026-09-30)

Every customer-visible auction outcome is backed by the source's own published
wording, read from a property-specific item, matched by exact case number, and
recorded with where and when it was read. Anything else stays explicitly
unknown.

## 1. What the approved source publishes (measured, not assumed)

The earlier evidence sprint concluded that RealAuction past-sale pages are a
"login wall". That test fetched only the sale-day page **shell**
(`zmethod=PREVIEW`), which always carries the site's login form in its header
and never contains items: the items arrive by AJAX. The FL deed harvester has
always read those items anonymously (`AREA=W`, "Auctions Waiting").

Capture runs 36728042223, 36728924465, 36729310846, 36729752890, 36730690353,
36731088178 and 36731266591 (`job=evidence`, `evidence_scope=auction_results`,
value-free, manual only) read the same anonymous endpoints for past sale days:

| Surface | Anonymous? | What it carries |
|---|---|---|
| `AREA=C` "Auctions Closed or Canceled" (same `FNC=LOAD` call the harvester uses for `AREA=W`) | yes, no login form | one item per property: `Case #`, `Parcel ID`, `Certificate #`, `Opening Bid`, address; the status box is empty in the HTML |
| `FNC=UPDATE&ref=<item ids>` - the status refresh the sale-day page itself calls to fill each item's status box | yes | per item: `A`, `B`, `C`, `D`, `SL`, `ST` status lines |

Wordings observed over 21 counties x 6 past sale days (2026-09-16..09-29):

| Wording (verbatim) | Items | Layout | Mapped to |
|---|---|---|---|
| Auction Sold | 65 | `A`; `B` = time; `C` = "Amount", `D` = money; `SL` = "Sold To", `ST` = purchaser **category** | sold (+ published amount) |
| Redeemed | 126 | `A` = one-letter code, `B` = wording | redeemed |
| Redeemed After Sale | 1 | same | redeemed |
| Canceled per County | 5 | same | cancelled |
| Canceled per Bankruptcy | 1 | same | cancelled |
| Bidder Walked Away | 4 | same | **not mapped** - a default, not a final result |
| Auction to be rescheduled / Rescheduled | 6 | same | **not mapped** - a postponement |

No "struck off" or "withdrawn" wording appeared on any sale day read, so no
row exists for either. The reviewed table is
`data/auction_outcome_wordings.csv` (each row cites the capture run); the
unmapped wordings and why are in `data/auction_outcome_wordings_unmapped.md`.

The purchaser (`ST`: "3rd Party Bidder" or another category) is never
stored. No bidder count or bidder identity is published or written.

## 2. The model (migration 014, no new migration)

| Customer state | Stored as |
|---|---|
| Scheduled | sale date not passed |
| Outcome not yet verified | past sale date, and no closed-listing observation - or one whose wording is not a reviewed row (the wording is quoted) |
| Outcome not published | the latest `feed='closed'` observation has no status wording |
| Sold - verified | `auction_events.outcome='sold'`, `outcome_raw`, `outcome_observed_at`, `winning_bid` only when printed beside "Amount" |
| Redeemed - verified | `outcome='redeemed'`, `lifecycle='cancelled'`, `outcome_raw` |
| Cancelled - verified | `lifecycle='cancelled'`, `outcome_raw` |
| Withdrawn / Unsold - struck off / No sale - verified | `lifecycle='withdrawn'` / `outcome='struck_off'` / `outcome='no_sale'` with `outcome_raw` (no wording observed yet) |
| Source unavailable | a failed read: nothing written; counted in the run report |

Every result also appends an `auction_event_observations` row
(`feed='closed'`, `raw_status` = the wording, `evidence_url` = the sale-day
page, `observed_at`, `harvest_run_id`). History is append-only.

## 3. The pipeline

`scripts/realauction_results.py` - the anonymous read (calendar, sale-day
page, `AREA=C` pages, status refresh), the item parser, and the value-free
summaries the capture prints (every attribute value and digit masked).

`scripts/auction_outcomes.py` - for FL events whose sale date is within the
last 21 days: reads each (county, sale day) once, joins items to status lines
by the site's own item id (a count mismatch makes the day unreadable), matches
each item to exactly one event by exact case number (a published parcel must
agree), and maps the wording only through the reviewed table. It writes:

- a verified result: one observation + one event patch;
- "checked, no wording": one observation, only when it changed, never over a
  verified result;
- a failed read: nothing.

It never writes `properties`, never infers from absence, a passed date, a bid
or a value, and never touches Available or certificate rows. It runs after
the Phase B event writer in every `deeds` job (allowed to error) and on its
own as the manual `job=outcomes`.

## 4. Customer surfaces

- **Auction decision block, "Is an explicit auction result available?"**: the
  state, and for a verified or checked outcome the provenance - source and
  host with a link to the sale-day page, evidence type ("Auctions Closed or
  Canceled" listing, property-specific), the matching case number, the source
  wording, the observation date, the amount only when published, and
  "Purchaser identity and bidder count are not recorded".
- **Sale event history**: the same state per event.
- **Card kicker**: a past sale shows the verified outcome, or "Past sale date
  · Outcome not yet verified / not published".
- **Relationship**: "Previously auctioned - verified unsold / struck off ·
  Currently Available - independently verified" appears only when BOTH the
  auction's own unsold / struck-off result AND a current, publishable
  Available record for the same state, county and parcel exist. A failed
  auction alone never makes a property "available", and an Available record
  never manufactures a failed auction.
- **Auction export**: Auction Outcome, Outcome Source Wording, Outcome
  Observed, Outcome Evidence URL, Published Sale Amount. No governance field,
  no purchaser, no bidder count.

## 5. Known limits

- The closed listing pages at ten items and the site's pager could not be
  driven anonymously (`PageDir=1&doR=0` returned the same ten). On a sale day
  with more than ten closed items the rest stay "Outcome not yet verified".
- Event history starts with the auction-event writer; earlier sales have no
  event row and are not reconstructed.
- Okaloosa (Bid4Assets) and Texas have no outcome adapter; their outcomes
  stay unknown. LGBS, GovEase and blocked vendors are untouched.

## 6. Public logs

Capture output is printed to public GitHub Actions logs. Run 36717720575
(acquisition sprint) printed Putnam per-parcel account-number links; run
36728924465 (this sprint, before the fix) printed three appraiser links
carrying parcel keys. Neither was ever committed to this repository (`out/`
is gitignored). The capture now masks every attribute value and every digit
in anything it prints (`realauction_results.mask_text`, tested by
`tests/python/test_auction_outcomes.py::test_26_*`), and the acquisition
capture drops any link with a 7+ digit run. Deleting those two runs' logs is
a GitHub action for the repository owner.
