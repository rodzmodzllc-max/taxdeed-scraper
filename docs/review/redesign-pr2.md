# Redesign PR 2 - cards and the list head

Branch `redesign/2-cards-list-head` (base `redesign/1-property-first-fold`).
Direction A of the 2026-10-24 design panel, PR 2 section of
`scratchpad/mockups/PLAN.md`. Frontend only: `public/app.js`,
`public/identity.css`, `public/index.html` / `tx.html` / `la.html` (by hand) and
the ten generated state pages (`scripts/build_state_page.py`, `--check` passes),
`public/sw.js` (v139) and their root mirrors, `tests/run_test.mjs`, the six
Python tests that pin the service-worker version, and the `sw.js ->` line in
CLAUDE.md. No data, label, estimate or score was added.

## What changed

**The card (`card()`).** Top to bottom:

| Row | What it shows | Where the text comes from |
|---|---|---|
| Photo | unchanged: `propertyVisual()`, the county / ledger / lot chips, the info bubble, the parcel outline for cards in `BOUNDARY_IDS` | as before |
| Kicker | `<county>, <state> · Auction / Available · <sale or phase>` | `cardKickerHtml()` / `kickerParts()`, unchanged |
| Address + actions | address, Favorite, Hide, the countdown badge | unchanged (the compact watchlist icon moved to the actions row) |
| Identity line | `Parcel # 111 · Case A-1 · House` - parcel (or "Parcel # not published"), case, property type as published | `cardIdentityHtml()`; `.prop-parcel-line` / `.prop-case-line` text unchanged (pinned) |
| Money | ONE headline figure labelled as the source labels it (`auctionBidLabel(p, true)` / `amountInfo(p)`, "Not published" when none) with the county value on file as its right-hand context: `valueLabel(p)` + the market figure, else the assessed figure under `assessedSourceLabel(p)`, else "No county value on file" | `cardMoneyHtml()`; `.card-price` stays the headline's wrapper. The value ÷ bid ratio is not on the card. |
| Off-list note | unchanged | `offCurrentSaleList()` |
| Provenance | `Read from <source> · last synced <date> (<n> days ago)[ · may be stale] · last read <date \| not recorded>` | `provenanceLineText()` - the same wording as the property page's fourth cell; not italic (the usability judge) |
| More (closed `<details class="card-more">`) | the four tax-roll size facts (`cardStatsHtml()`), Location / Flood (/ Acquire on Available) (`cardFactsHtml()`), Last sale and the legal description only when the row carries them, and the county's own listing link (`auctionLinkHtml()` - a stored URL by its kind, or "Auction link not published") | `cardMoreHtml()` |
| Actions | `⚐ Add to Watchlist` (`bidListBtnHtml(p, false)`) and `Open record →` (`.detail-btn`, same `data-action="viewdetails"`) | - |

Nothing on the face is derived; no fact appears twice on it (the county is in the
kicker and on the photo chip only; the sale date in the kicker only). Certificate
cards (`certCard()`) are unchanged.

**The list head (`section()` and the shells).**

- The head is the ledger's name, its live fact line and the "Source status and
  coverage" fold (`ledgerStatusHtml()` - the eligibility / zero-case strip stays in
  the head, as `docs/ledger-eligibility.md` requires).
- The 45-day calendar (`upcomingSalesHtml()`, `#upcomingSales`, `.upcoming-fold`) and
  the ledger explainer (the ledger's question as the summary, the same `.mega-sub`
  / `.ledger-how` copy the head's info bubble held, the card-edge `.ledger-legend`)
  are two closed `<details class="ledger-foot">` under the cards
  (`ledgerFootHtml()`), on the empty-state path too.
- The status chips (Shown / Active / No longer listed - same ids, same handlers)
  moved from the strip above the toolbar into the Filters panel's first section
  ("Search & status"); a status view other than "all" already counts in
  `#filtersBadge` (`updateBadge()`).
- The toolbar row is the county select and Filters & Sort; Table / Expand all /
  Export CSV and the Watchlist chip (`#bidListToggle`) form `.qc-tools`, a quiet
  line that is one horizontally scrolling row on a phone (the export label is
  per-ledger and pinned, so it is not shortened).
- There is one search box. The 2026-10-10 remediation removed the List's
  `#searchInput` on purpose (`test_removed_duplicate_controls_stay_removed` pins
  that), so the plan's "the List has its own search" is satisfied by re-homing
  the one `#globalSearch` element into the Filters panel (`#listSearchHost`) on
  the List below 768px (`homeGlobalSearch()`, on `showPage()` and on the media
  query change) - never a clone, so its id, handlers and results list are the
  same object in both homes. At every wider width, and on every other page, it
  sits in the header as before. `showPage()` also writes
  `document.documentElement.dataset.page`.

**Service worker** `tdw-shell-v139` (sw.js + root, `brandSwReload`, the six
Python pins, CLAUDE.md).

**Deliberately not changed.** County groups still open by default only when
there are three or fewer (so a six-county list shows group headers first, as
before); the card photo keeps its 4:3 height; Home, the Map preview and table
mode are PR 3.

## Suite changes

- `ensureFiltersOpenOn(pg)` (top of the file): the status chips and, at phone
  width on the List, the search box live inside Filters, so the steps that click
  a chip (`.chip[data-status=…]`, three sites) or fill `#globalSearchInput` on
  the phone page's List (the "Searchable" step, the `?an=1` analytics step) open
  the panel first - by asking its state, since a bare `#filtersToggle` click
  would close an already-open panel.

## Checks re-pinned

All values below were read from `DUMP_RESULTS` runs against the served build
of this branch, never guessed. "Why correct" says what the new value shows.

| Check | Old | New | Why the new value is correct |
|---|---|---|---|
| `brandSwReload.cache` | `tdw-shell-v138` | `tdw-shell-v139` | PR2's own service-worker bump. |
| `cardStatLabelsFirst` | `['Opening Bid']` | `['Opening Bid', '2025 County Just Value']` | The card's money block is the headline figure plus the county value on file as context (plan item 1), labelled by `valueLabel(p)` - the source's own roll year and name. |
| `bidBtnIconBefore` / `bidBtnIconAfterAdd` | `⚐` / `⚑` | `⚐ Add to Watchlist` / `⚑ On Watchlist` | The card's Watchlist action is the full-label button in the actions row (`bidListBtnHtml(p, false)`); the compact icon is gone from the top-right row. The handler and the count chip are unchanged (`bidListChipTextAfterAdd` still `1/10`). |
| `xsMiCard.sev` | `false` | `true` | pmi1 carries an assessed figure and no market figure, so the context cell shows it under its own source label, `State Equalized Value (county list)` (`assessedSourceLabel`); `noJustValue` stays true - no Florida wording. |
| `laCardValueLabel` | `false` | `true` | pla1's context cell reads `2023 Fair Market Value (tax roll)` - the Parish's own label from `valueLabel(p)` - and never "Just Value". |
| `rdPhoneSearchVisible` | `true` | `false` | On the List at phone width the one search box sits inside the (closed) Filters panel (plan item 2). New check `rdPhoneSearchHost` = `listSearchHost` pins where it sits; it is the same `#globalSearch` element, not a second box. |
| `refineLedgerQuestions` (reader) | `[data-ledger-question]` textContent | the fold's `<summary>` textContent; values unchanged (`What can I acquire now?` …) | The question is now the summary of the explainer fold under the cards; the body carries the ledger copy. |
| `gsPhone.headerCompact` (reader) | required the search box on a second header row | the second-row check applies only while `#globalSearch` is inside `.topbar`; value stays `true` | On `tx.html#/list` at 360px the search is re-homed into Filters, so the header is one 63px row - more compact, not less. |

## Screenshots

Taken with `pr2_shots.mjs` against the served build of the branch head, signed
in through the Playwright stub (`tests/vendor/supabase-stub.js`), saved in
`docs/review/redesign-pr2/`:

- `list-auctions-390.png` / `list-auctions-1280.png` - the Auctions list head: title, toolbar (county + Filters; tools line), the ledger fact and status fold, then the county groups.
- `card-auction-390.png` / `card-auction-1280.png` - the Alachua card (p1) with "More" open: identity line, money block, provenance line, size facts, location / flood, last sale, legal description, the county listing link, Watchlist + Open record.
- `list-filters-open-390.png` - the Filters panel on a phone: the re-homed search box and the Shown / Active / No longer listed chips in its first section.
- `list-foot-folds-390.png` - the two folds under the cards (the 45-day calendar, the ledger explainer with its legend) opened.
- `list-available-390.png` / `list-available-1280.png` - the Available list (Bay, p3): `Opening bid` headline with its "About this price" bubble and the county value beside it.
- `list-certificates-390.png` - the certificate list, unchanged cards.

## Verification

On head `d6e2817` (before review):

```
Browser: PASS: all 1270 checks matched, 8 console error(s) all allowlisted.
Python:  3018 passed, 129 skipped
```

Root mirror identical to `public/`; `scripts/build_state_page.py --check` passes.
