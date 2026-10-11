# PR #137 before / after screenshots

One sheet per width (1400, 1280, 1024, 768, 390px). Left column: `main` at
77688dc (the PR base) served with the test fixture; right column: this PR's
head served the same way. Rows: Home (`#/dashboard`), List (`#/lands`), Map
(`#/map`), Watchlist (`#/watchlist`, seeded with `?bidlist=p1,p3,p15`).

What to look for:
- Home: the duplicate stat tiles and counts subtitle are gone; per-ledger
  cards carry the counts and withheld / pending-verification notes.
- List / Map: the county select on either page is the same selection
  (`state.counties`); the Filters chips follow it.
- Watchlist: a page with its own heading and "Back to …" instead of a modal
  over the List; the browser Back button returns to the previous page.

Captured by a Playwright script against the fixture stub (no production
data); the sheets are JPEG at reduced scale for repository size.
