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

## Added in the final UX/UI pass

Before = `main` at 77688dc. After = branch head with this pass. Each pair is the same page and
viewport, captured with the test stub (no live data).

- `before-signin-<w>.jpg` / `after-signin-<w>.jpg`: signed-out sign-in page. After shows the
  illustrative preview on desktop and the form alone on phones.
- `before-detail-<w>.jpg` / `after-detail-<w>.jpg`: an Available property (`#/lands/p15`). Desktop
  (1280px and up) shows the side panel; narrower widths show the full-page detail.
- `before-states-<w>.jpg` / `after-states-<w>.jpg`: the header state selector, focused, on the
  Available page. Before has a separate States button; after has the state selector only.

Widths: 1400, 1280, 1024, 768 and 390px.
