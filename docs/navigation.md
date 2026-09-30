# Navigation model (unified, 2026-09-30)

Four primary destinations, three ledgers inside them. Frontend only; the
backend ledger classification (`harvesters/ledgers`, `properties.source`)
is the one definition the List and the Map both read.

## Destinations

| Destination | Hash | What it is |
|---|---|---|
| Dashboard | `#/dashboard` | the operating view (`renderDashboard()` / `dashboardOps()`) |
| List | `#/auctions`, `#/lands`, `#/certificates` (`#/list` = current ledger); `#/<slug>/<pid>` reopens a property | the property workspace; the ledger selector is `#ledgerTabs` (the state is the header's `#stateSelect`) |
| Map | `#/map[?ledger=..&county=..&q=..&watch=1]`; legacy `#map` is rewritten to `#/map` | the geographic workspace; ledger pills (`All Ledgers` + the three ledgers), county select scoped to state + ledger |
| Watchlist | `#/watchlist` | the watchlist layer over whichever page is open |

The rail (`.nav-list`) and the phone bottom bar (`#navBottom`) carry exactly
these four entries (`data-page`), identical on `index.html` and `tx.html`.
`showPage()` routes them; `routeFromHash()` reads a hash; `syncPageHash()`
writes the current page's hash with `replaceState` only (page moves never
enter the Android-back stack, `BACK_LAYERS`). A self-initiated back (closing
a layer with its own ✕) restores the URL the layer was opened over; the
hashchange that traversal fires is skipped (`suppressHashRoute`) and the
page that is showing rewrites its own hash.

## State (global context)

There is one state selector: `#stateSelect`, in the shared header beside the account badge. It is on every destination and on the phone as well as the desktop. It is not a bottom-bar item.

- Its options are `STATE_META` in `app.js`, the one table of states that have a page, a basemap and production data. A Python test pins its keys to `harvesters/governance/states.PRODUCTION_STATES`, so a state appears only once it is activated on the backend.
- **The selected state is the page:** `index.html` is FL and `tx.html` is TX.
  - Its value is `PAGE_STATE`, the one state variable the whole app reads.
  - Each page loads only its own state's rows through `get_properties(p_state: PAGE_STATE)`. Dashboard, List, Map and Watchlist therefore all show the selected state's data, not a relabelled copy.
  - The state is in the URL, so a refresh or a shared link keeps it, and nothing else stores a second copy.
- **Choosing a state** navigates to that state's page and carries the current route along (`stateSwitchHref()`):
  - page, ledger, and the map's ledger / county / search all come along;
  - a county the new state lacks falls back to "All Counties";
  - a property id is dropped, because a property belongs to one state. A property deep link (`tx.html#/auctions/<id>`) opens in its own state's context.
- The List's former FL/TX tabs, the Map's state select and the Map context line's "State:" badge were removed. State shown as property metadata (cards, sources) is unchanged.
- The watchlist is one list per account. It shows the selected state's items and names how many saved items are elsewhere; switching state never removes anything.

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
