# Understood search, saved-search duplicate, research queue, coverage explorer (2026-10-05)

Frontend only. No migration, and no production change. Two event names were
added to the CHECK list of the unapplied migration 024.

## Understood search (global search)

`parseNaturalQuery()` in `public/app.js` maps a plain-language query to the
List's own filters using fixed rules. It uses no model and makes no network
call.

It recognises:

| Phrase | Becomes |
|---|---|
| available, lands available, otc, over-the-counter, struck-off, adjudicated, land bank | the Available ledger |
| auction(s), tax deed(s), deed sale(s), sheriff sale(s) | Auctions |
| lien(s), certificate(s), tax cert(s) | Liens & Certificates |
| a county or parish of the open state, with or without "county" / "parish" (longest name first) | the county filter |
| under / below / less than / up to $X; over / above / at least $X; between X and Y (k / m suffixes) | the bid range |
| verified, with a verified acquisition path | the List's "Acquisition path: Verified" filter |

Whatever is left becomes the text search.

When to fall back to plain text search:

- A query that starts with a number (an address, a parcel or a case number) is always a plain text search. "15 Manatee Ln" is a street, not Manatee County.
- If the understood reading matches nothing but the words themselves do, the plain-text results are shown.

How the understood reading is shown and applied:

- It appears as chips under "Understood as", with **Apply as List filters**.
- Enter does the same thing.
- Applying sets the controls a customer could set by hand, so the List, the filter chips and saved searches all agree. Amount bounds use the List's bid filter: rows with no published amount stay in, and the dropdown says so.
- The usage event is `search_interpreted`. It records which parts were understood, never the query text.

## Saved searches

**Duplicate** creates a copy with the same criteria under "<name> (copy)". The
copy gets its own comparison baseline, so nothing in it reads as "new". The
existing **Show in list** runs the search now.

## Research queue (watchlist)

The watchlist opens with a "Research queue": every watched property that still
has open items.

- For an Available row, the open items are its acquisition-checklist items that are "not published" or "not yet verified".
- For other ledgers, they are the property page's data gaps.

The queue keeps the watchlist's order; nothing is ranked. Each row opens the
property page, at How to acquire for Available rows.

## Coverage explorer (States & Counties)

The state picker shows the open state's counties by intelligence state, using
`county-intelligence.json`. Counties the file does not list are counted as
"not yet researched", with the sentence that this is not a statement that
nothing is for sale. Each county opens its dossier.

Opening a dossier from the picker waits for the picker's own history entry to
pop first (`afterSelfBack`). Without that, the two backs raced and closing the
dossier left the page; this was caught by the new test.

## About: "Why TaxDeed-Scraper"

Six factual points about what the app does. It names no competitor, makes no
unsupported claim, and states plainly that nothing rates a deal or estimates
a return.
