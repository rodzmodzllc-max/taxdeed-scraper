# Navigation model (unified, 2026-09-30)

Four primary destinations, three ledgers inside them. Frontend only; the
backend ledger classification (`harvesters/ledgers`, `properties.source`)
is the one definition the List and the Map both read.

## Destinations

| Destination | Hash | What it is |
|---|---|---|
| Dashboard | `#/dashboard` | the operating view (`renderDashboard()` / `dashboardOps()`) |
| List | `#/auctions`, `#/lands`, `#/certificates` (`#/list` = current ledger); `#/<slug>/<pid>` reopens a property | the property workspace; the ledger selector is `#ledgerTabs`, the state selector `#regionTabs` |
| Map | `#/map[?ledger=..&county=..&q=..&watch=1]`; legacy `#map` is rewritten to `#/map` | the geographic workspace; state select, ledger pills (`All Ledgers` + the three ledgers), county select scoped to state + ledger |
| Watchlist | `#/watchlist` | the watchlist layer over whichever page is open |

The rail (`.nav-list`) and the phone bottom bar (`#navBottom`) carry exactly
these four entries (`data-page`), identical on `index.html` and `tx.html`.
`showPage()` routes them; `routeFromHash()` reads a hash; `syncPageHash()`
writes the current page's hash with `replaceState` only (page moves never
enter the Android-back stack, `BACK_LAYERS`). A self-initiated back (closing
a layer with its own ✕) restores the URL the layer was opened over; the
hashchange that traversal fires is skipped (`suppressHashRoute`) and the
page that is showing rewrites its own hash.

## State

The state is the page (`index.html` = FL, `tx.html` = TX), never a hash
parameter: each page loads only its own state's rows through the
state-scoped `get_properties()` RPC. `STATE_META` in `app.js` is the one
table of states with a page, a basemap and production data; a Python test
pins its keys to `harvesters/governance/states.PRODUCTION_STATES`, so a
state appears in the Map's `#mapStateSelect` only once it is activated on
the backend. Switching state navigates to the other page carrying the hash
along (`syncStateLinks()` for the List's FL/TX links, the select's own
handler for the Map), so ledger, county and search survive the switch when
they remain valid (a county with no rows in the new state falls back to
"All Counties").

## Ledger

One selector per workspace: `#ledgerTabs` on the List (`setLedger()`), the
`#mapLedgerPills` on the Map (`mapFilter.ledger`). `All Ledgers` on the Map
is a real aggregation (`computeMapRows()` filters `ALL` by `p.source`, the
backend column, and "all" keeps every ledger); the counts on the bubbles,
in the county select and in the side panel are the selected ledger's. The
county select lists only counties with inventory in the selected state and
ledger, with that ledger's count (`mapCountyCandidates()`). Texas's third
slot keeps its existing name (Redeemable Deeds, `ledgerCopy()`); no Texas
certificate ledger is invented.

## Dashboard

Tiles: one per ledger (active count, counties; opens the List on that
ledger) plus counties with inventory. Panels: Needs attention (auctions in
the next 7 days, watchlist rows no longer listed, Available rows not read
in 14+ days, sources unavailable / in back-off), Recent (first-recorded and
read-from-source counts per ledger, "not tracked" where the pipeline holds
no such date), Verified purchase paths (typed from evidence vs not yet
verified, by type), By County, By Ledger, Upcoming Auctions, Data sources,
per-county freshness, Watchlist changes. Every figure is a count over data
the app already loaded; no score, trend or estimate.

## Watchlist

`openBidList()` is the destination: its nav entry is lit while open, the
hash is `#/watchlist`, and the same parcel watched in two ledgers renders
one card with the other ledger's record folded underneath
(`relatedRecordsFor()`, exact state / county / parcel match).

## Compatibility

`#map`, `#/auctions`, `#/lands`, `#/certificates`, `#/<slug>/<pid>` all
keep working; `showPage("auctions")` is accepted as `list`. `#pageAuctions`
was renamed `#pageList`.
