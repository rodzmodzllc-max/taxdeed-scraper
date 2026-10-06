# Opportunity finder and auction command center (2026-10-05)

Frontend only. No migration, no data change, no new source. Every badge and
every ordering below comes from a field the row already carries.

## Evidence-first sorts

`#sortBy` and `#sortSecondary` gain three orderings (`SORT_COMPARATORS` in
`app.js`):

| Value | Puts first |
|---|---|
| `pathFirst` | rows with a verified acquisition path (Available) or a verified county sale process (Auctions), from `acquisitionOf()` |
| `amountFirst` | rows with an amount the source published (Available: `amountInfo()` returned a figure that is not an expired statement; other ledgers: a published bid) |
| `readRecent` | rows read from the source most recently (`last_seen_at`); never-read rows last |

Each is one visible criterion. There is no total and no weighting. Ties keep
the query's own order or fall to the "Then by" sort, so criteria combine only
in the order a user chooses. Sort keys are cached per `sortRows()` call
(`SORT_KEY_CACHE`, a `var` because `render()` runs during module init), so a
30,000-row state is not re-evaluated per comparison. Sorting applies within
each county group, as every existing sort does.

## Record badges

`recordBadges(p)` / `recordBadgesHtml(p)` add a row of squared tags under the
kicker on property and certificate cards. A badge is either on the record or
it is not; its tooltip says exactly what it means.

| Key | Label | When |
|---|---|---|
| `path` | Verified acquisition path / Verified sale process | `acquisitionOf(p).verified` and the mode is not "none" |
| `official` | Official total due | a clerk statement that has not expired |
| `amount` | Amount published | Available only: the source published a figure |
| `fresh` | Read ≤ 7 days ago | `last_seen_at` within 7 days |
| `dated` | Dated list | `isDatedList(p)` - never "available now" |

No amount badge appears on auctions or certificates: nearly every such row
publishes its bid, so the badge would say nothing.

## Auction command center

The auction ledger head's "Upcoming sales" timeline becomes the command
center (`auctionCommandRows()`, `upcomingSalesHtml()`). It covers the next 45
days of the rows on screen, so the current filters apply. Each sale date and
county gets one line:

- the number of properties, and how many are on your watchlist or favorites;
- how many have a published bid;
- whether the county's sale process is verified;
- the sale listing or county auction-site link the rows themselves publish
  (`auctionLinkInfo()`), never a constructed URL;
- "County process", which opens the county dossier. Clicking the event
  filters the List to that county.

Deposit, registration deadline and bidder rules are not shown: none is stored
per sale. The dossier is where the county's process lives. Up to 8 events are
listed on desktop and 4 on phones, with a count of the rest.

## Tests

- `tests/run_test.mjs`: `finderSortOptions`, `finderBadges`, `finderSortPath`,
  `finderReadRecent`, `commandCenter`, `commandCenterDossier`,
  `commandCenterMobile` (no overflow at 390px, 44px tap targets).
- `tests/python/test_opportunity_finder.py`: options on every page, the cache
  is a `var` and reset per sort, badges carry no score wording, and the
  command center uses only row fields.
- `sw.js` → `tdw-shell-v91` (v92 after the final visual refinement).
