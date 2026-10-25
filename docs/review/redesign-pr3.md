# Redesign PR 3 - Home, map preview, table mode

Branch `redesign/3-home-map-table` (base `redesign/2-cards-list-head`).
Direction A of the 2026-10-24 design panel, PR 3 section of
`scratchpad/mockups/PLAN.md`. Frontend only: `public/app.js`, `public/explore.js`,
`public/identity.css`, `public/admin.html` / `public/admin.js`,
`public/index.html` / `tx.html` / `la.html` (by hand) and the ten generated state
pages (`scripts/build_state_page.py`, `--check` passes), `public/sw.js` (v140) and
their root mirrors, `tests/run_test.mjs`, five Python tests (six service-worker
pins plus four string pins), and the `sw.js ->` line in CLAUDE.md. No data,
label, estimate or score was added.

## What changed

### Home (`renderHome()` / `renderHomeDesk()`)

Before: about 5,500px on a 390px phone - the ledger cards, Available now, upcoming
auctions, county intelligence, saved counts, recent changes, and then the
"Operating view" (Needs attention, Verified purchase paths, Data sources (all
states) with per-county rows, change-detection runs, Watchlist changes).

After (`home-390.png`, about 1,900px with every fold closed):

| Block | What it shows | Where it comes from |
|---|---|---|
| Hero | unchanged search, title and "Change state" (strings pinned by the branding checks and `homeGuide`) | as before |
| Ledger lines (`#homeLedgers`) | one ruled line per ledger: name, one fact (the existing unit line - "upcoming sales across 6 counties", "properties across 2 counties · 1 withheld"), the count, an arrow; "Browse by state" stays as the fourth line because `#homeStatesCard` is the one control that opens the state picker | `homeLedgerCardHtml()` - same counts, same ids; the ledger blurb is shown only for the "Loading…" and "None listed" states |
| Next sales (`#homeUpcomingSales`) | the first three `upcomingAuctionRows()` events. One property: its address and its figure named by `auctionBidLabel(p)` ("Opening bid $11,000"), or "not published". Several: "N of M with a published opening bid" - never a sum or range | `homeNextSalesHtml()` |
| Your work (`#homeSaved`) | three closed folds with their counts: Watchlist `n / 10` (and "· N changed" when the change snapshot has items) with the watchlist changes (`#dashWatchChanges`, same wording) inside; Saved searches `n`; My research `n`, with "Kept in this browser only." when research lives in this browser (migration 029 absent) | `homePersonalHtml()`; open state survives re-renders |
| Data read (`#homeDataRead`) | one line per ledger: the status in `CUSTOMER_HEALTH_TEXT`'s words and "Last updated <date>" (or "No successful update recorded"; "Status not recorded" when nothing is on file). No county names, counts, source ids or "blocked" | `ledgerReadStatus()`: the dataset-health rows that feed the ledger (`SOURCE_HEALTH_LEDGERS`: fl_deeds → Auctions, fl_laft → Available, fl_certificates → Liens & Certificates, tx_sales → Auctions + Available), the worst `healthOf()` wins; with no dataset row, the ledger's county reads (all complete → Current / Not recently updated after 7 days, some → Partly updated, none → Update unsuccessful, on-request sources → Updated on request) |
| Recently observed | the existing `first_seen_at` list, now a closed fold with its count | `#homeRecentSection` |

Operator panels stop rendering on Home. Where each one lives now:

- Dataset health and per-county read status: admin.html "Source freshness and
  health" (already there; `adminFreshness*` checks).
- Change-detection runs: a new admin.html card, "Change-detection runs"
  (`refreshRuns()` in admin.js; every state, latest run per source and ledger;
  "not reported on this deployment" without migration 024). The customer page no
  longer reads `source_observation_runs`.
- "Needs attention" and "Verified purchase paths (Available)": not ported. Their
  customer facts are on Home already (sales in the next days are the Next sales;
  watched properties that left a list are in the Watchlist fold's changes) or on
  each record (the verified acquisition path); the remaining counts (stale
  Available rows, sources awaiting retry) are operator detail the admin
  freshness card states per source. Recorded here so the removal is deliberate.

`dashboardOps()`, `dashRow()`, `unitFreshnessRowsHtml()`, `ledgerFreshnessSummary()`,
`observationRunsHtml()` / `renderRunRows()` are deleted (no remaining caller).
TDZ: `HEALTH_STALE_MULTIPLIER`, `MANUAL_ONLY_SOURCE_IDS`, `LEDGER_KEY_BY_NAME`,
`SOURCE_ID_LEDGERS` became `var` (render() reaches them through Home during
module init); the two Python tests that pinned `const` read `var` now.

### Map preview (`explore.js showPreview()`)

- The preview is the card's money block: the headline figure in display type,
  labelled as its source labels it, the value on file beside it at body size with
  its own label (`.pv-head-fig` / `.pv-ctx`; same classes `.pv-money` / `.pv-stat`
  / `.pv-val.bid` the suite reads). An auction figure is formatted as its card
  formats it (`bidDisplayCard()`, whole dollars) with the exact amount in the
  title.
- Under it, the card's provenance line (`provenanceLineText(p)`, passed through
  `previewFacts()`), then the actions: the Watchlist button (app.js's own
  `bidListBtnHtml(p, false)`; after a toggle `refreshPreviewWatch()` swaps its new
  state in), "Details" on phones, and "Open record →" (was "Full property page →").
- The ids list drops its "Source" row - the provenance line carries the source once.
- The strip card of the property open in the preview is a marker only: its title
  and "Open in the preview · tap to close" (`.strip-card.sel.in-preview`), no
  second date or figure. It keeps `.sel` and the tap-to-close toggle, so the
  `tdw:mapselection` / strip↔pin `.sel` / `.hover` contract is unchanged.
- Phone sheet: still under half the stage when collapsed (210px of 437px at
  360×780); the actions sit on one line.

### Map toolbar at phone width (< 768px)

`ensureMapFiltersToggle()` (app.js, injected, so no shell change): a "Filters"
button after the county select; "Watchlist only" and "Same filters as the List"
move into `#mapMoreFilters` behind it. The button's badge counts how many of the
two narrow the map now (List filters only while the List has a filter set).
Row 1: county + Filters; row 2: ledger pills (scrolling) + the basemap toggle; the
"Map" title is visually hidden (still the page's h1). `#mapStyleOutline/Google/Maptiler`
keep their ids; the Phase 61 Google → MapTiler → Google sequence is checked at
390px. At 768px and wider the toolbar is unchanged.

### Table mode (graft B)

Opt-in as before (`#tableToggleBtn`, desktop). Columns: Sale (the kicker's phase -
"Sale Oct 28, 2026", "Fixed price · available now", "Expires …"), County, Address,
Parcel, Case (the Texas cause through `caseIdentText()`), Published figure (with
its label: `auctionBidLabel(p)` / `amountShort(p)` / "Amount"), Value on file (with
`valueLabel(p)` / `assessedSourceLabel(p)`, or "No county value on file"), Status,
actions. No ratio column. Divider rows (`tr.dt-divider`): by sale date when sorted
by sale date, by county in the default county order, none for other sorts. The
header is written by `tableHeadHtml()` and matches the static `<thead>` in the
shells. The card list stays the default.

## Checks re-pinned

All new values were read from `DUMP_RESULTS` runs against the served build of
this branch.

| Check | Old | New | Why the new value is correct |
|---|---|---|---|
| `brandSwReload.cache` | `tdw-shell-v139` | `tdw-shell-v140` | PR3's service-worker bump. |
| `brandShell.dataSourcesHead` | `true` | `false` | The every-state "Data sources (all states)" panel left the customer page; admin.html's freshness card lists every state. |
| `previewBid` | `$8,000.00` | `$8,000` | The preview formats an auction figure as its card does; the exact amount is in the title (`pr3Preview.bidTitle`). |
| `navDashAttention` | four attention rows | `[]` (ids of operator panels still present) | No operator panel remains on Home. |
| `navDashPaths` | verified-path counts | the three Next sales lines | The verified-path panel left Home; the check now reads Home's next sales and their labelled bids (sale dates are relative in the fixture, so only county and text are pinned). |
| `navDashSubtitle` | the operating-view subtitle | `0` (element count) | The subtitle went with the operating view. |
| `dashHealthRows` | five dataset rows | `auction:HEALTHY, laft:FAILED, certificate:INCOMPLETE` | One Data read line per ledger from the same dataset health. |
| `dashHealthBadgeTexas` (reader) | tx_sales row on Florida Home | the Auctions line on tx.html Home | Texas is read on its own page; value stays `true` ("Partly updated"). |
| `dashHealthIncompleteNames` (reader) | certificate badge text | certificate line reads "Partly updated" and the block names no county, count or source id | Value stays `true`. |
| `dashUnitRows` | four county rows | `{ unitRows: 0, countyNames: false }` | No county rows or names on Home (admin `adminFreshnessUnitDetail` still covers Bay). |
| `dashUnitMissingColumns` | `true` ("not reported yet") | three ledger lines from dataset health | Without the registry columns the dataset health still decides each ledger. |
| `dashHealthMissingTable` | `true` | `Status not recorded / Partly updated / Status not recorded` | Without dataset health, Available falls back to its county reads (Bay unavailable → Partly updated); the other ledgers have no read on file. |
| `monNoneRuns`, `monDashRuns` (readers) | Home `#dashRunsUnavailable` / `#dashRunRows` | admin.html `#adminRunsUnavailable` / `#adminRunsList` | Values unchanged (`1`; the same two run lines); the runs are an admin card now. |
| `tableHeaderValue` (reader + value) | 4th header, `County value` | 7th header, `Value on file` | Figure columns; the column holds the value under its own label. |
| `scaleListInitial.tableRows` (reader) | `tr:not(.table-more-row)` | `tr[data-pid]` | Divider rows are not property rows; value stays `200`. |
| identity sweep `homeDesk` (reader) | Available now / Upcoming / County intelligence / Saved | Next sales / Your work / Data read | The new Home blocks. |

Removed as obsolete (the per-county rows are no longer on Home; admin.html
covers them): `dashUnitBayUnavailable`, `dashUnitLedgerHeads`,
`dashUnitRowsUnderAvailable`, `dashUnitEmptyGroups`, `dashUnitStaleText`,
`dashUnitCurrentText`, `dashUnitMissingColumnsNoRows`.

Added: `monNoneHomeNoRuns` (Home never shows run rows), `pr3Home`,
`pr3MapToolbar`, `pr3Preview`, `pr3Table` (see the PR3 block at the end of the
suite).

Python: `test_n08` now pins "no operator panel on Home, one customer-worded Data
read block, runs in admin"; `test_multistate_branding` pins that the dataset panel
is off the customer pages; `test_front_end_coherence` no longer pins the deleted
verified-path count line (`hasVerifiedPath` itself stays pinned).

## Not done (deliberately)

- Certificate cards (`certCard()`) still carry their PR2 layout; the PR2 review's
  C5 (provenance line + Watchlist / Open record row, "Est. Accrued Interest" off
  the card face) is outside the plan's PR3 section and stays open.
- No compact-row density toggle for large counties (the verdict's open item).

## Screenshots

Taken against the served build of the branch head, signed in through the stub,
in `docs/review/redesign-pr3/`:

- `home-390.png` / `home-1280.png` - Home with the folds closed.
- `home-folds-390.png` - the three "Your work" folds open (watchlist changes inside).
- `map-390.png` / `map-1280.png` - the Map toolbar (phone: county + Filters, pills + basemap).
- `map-filters-390.png` - Filters open: Watchlist only / List filters.
- `map-sel-390.png` / `map-sel-1280.png` - Charlotte's p5 selected: money block, provenance line, Watchlist / Open record; the strip marker on desktop.
- `table-1280.png` / `table-date-1280.png` - table mode in county order and in sale-date order.

## Verification

On the branch head (served build of the commit that adds this file):

```
Browser: PASS: all 1269 checks matched, 8 console error(s) all allowlisted.
Python:  3018 passed, 129 skipped, 1639 warnings
```

1269 = 1271 (PR2) - 7 obsolete per-county Home checks + 5 added. Root mirror
identical to `public/`; `scripts/build_state_page.py --check` passes. The first
run (11 mismatches) also caught one real regression, fixed before the second:
the phone preview sheet covered more than half the map stage
(`mobilePreviewCoversLessThanHalfStage`) once the provenance line and actions
were added - the actions now sit on one line and the collapsed sheet's spacing
is tighter (228px → 210px of a 437px stage at 360×780).
