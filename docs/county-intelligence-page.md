# County Intelligence page (2026-10-06)

A county is now a first-class research page:

- `#/counties` lists the state's counties with a research status.
- `#/county/<name>` opens one county's dossier.

Both sit above the quick dossier modal (`docs/county-intelligence.md`), which keeps working and now links to the full page.

## Where it is reached

- **Navigation:** the "County Intelligence" entry (`#navStatesBtn`) opens the index. The state picker and coverage explorer stay on the header's "States" button and the index's "Other states & coverage" link.
- **Property page:** the Source truth "County intelligence" row carries a second link. It reads "Full county page", or "County auction intelligence" on an auction.
- **Dossier modal:** "Open the full … page".
- **County page → List:** the ledger counts and "Open in the List (N)" open the List filtered to the county and ledger (`dossierlist`).
- **County page → Map:** "Show on the Map" (`countymap`).

## What the page shows

Every value comes from records the app already holds:

- `county-intelligence.json`: sources per ledger, publication and verification;
- `acquisition-evidence.json`: status per Available unit and the verified county records;
- the registry read health (`UNIT_FRESHNESS`);
- the rows this viewer can already see (`ALL`, gated at load).

Nothing new is fetched beyond `county-centroids.json`, which is loaded only for "Show every county".

| Section | Content |
|---|---|
| Research status | The six-step ladder below. |
| Available | Properties on file, published figures grouped by semantic type (range as published, or "No amount published"), each source with publisher, publication and last read. Per source unit: the evidence status, authority, acquisition method, application document, official process page with its verified date, the county's steps, and candidate pages (marked not yet verified). |
| Auctions | Upcoming count, next sale date, platform (registry source), opening/minimum bid range as published (never a price), registration and deposit only as the county's own published steps, sale calendar with official sale-day links, watched properties, and historical results. |
| Liens & Certificates | Shown only when the county has certificate rows or a production certificate source. Covers certificate amounts (a lien, not a property price), interest rate, issue dates and redemption / expiration dates as published. |
| Property intelligence | "X of N" for the parcel identifier, assessed, taxable, acreage / lot size, land use, homestead recorded, authoritative versus other coordinates, stored imagery, legal description and FDOR enrichment. |
| Source truth | A table of every source: ledger, official source, source type, publication, last read and health. Deadlines are stated as never inferred. |
| Research gaps | What is not known: amounts not published, purchase path not yet verified, coordinates missing or not official, auction process not verified, no past auction or no published result, winning bid not published, publication review pending, source unavailable, no source recorded. |

**Historical results:** only verified outcomes count, by label. Everything else is counted as "Result not published or not yet verified". Bidder identity and bidder count are never recorded.

Customers see sources awaiting publication review only as a count, never by name, which is the dossier's existing rule.

## Research status ladder

`harvesters/sources/county_research.py` and app.js `countyResearchStatus()` implement the same rule, pinned by `tests/python/fixtures/county_research_cases.json`.

| Step | Verified when |
|---|---|
| Discovered | a source, candidate page or finding names the county |
| Source verified | at least one production-verified, unblocked source |
| Inventory verified | every production source has a recorded complete read (some = partly) |
| Acquisition path verified | every Available unit has VERIFIED evidence and an Auctions ledger has a verified county sale process |
| Property data verified | every non-certificate row has a parcel id **and** authoritative coordinates |
| Outcome data verified | every past auction on file has a source-published outcome |

- Each step is VERIFIED, PARTIAL, NOT_VERIFIED or NOT_APPLICABLE.
- The reached step is the last one with every earlier step VERIFIED or NOT_APPLICABLE. A county is never shown as researched further than its weakest earlier step.
- Rows on file alone never verify a county.
- There is no score.

## Implementation notes

- **TDZ:** the section in app.js uses only `var` and function declarations, because a `#/county` deep link reaches `showPage()` during module init.
- **No HTML change:** `#pageCounty` is created by `ensureCountySection()`, so no state page changed.
- **Routes:** `routeFromHash()` handles `counties` / `county`, and `pageHash("county")` maps back. Both the boot path and `hashchange` route to the page.
- `sw.js` → `tdw-shell-v99`.
