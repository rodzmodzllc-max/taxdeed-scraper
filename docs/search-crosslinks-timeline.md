# Grouped search, cross-links and the parcel timeline (2026-10-06)

Frontend only (`public/app.js`, `public/identity.css`). No migration, no
database write, no new data source. Service worker `tdw-shell-v102`.

## 1. Grouped global search

The global search box (`#globalSearchInput`) still lists matching properties
exactly as before (`gsMatches()`: the natural-query reading, else plain text,
Available first). Above them it now routes a query to the product experience
the query names:

| Group | Matches | Opens |
|---|---|---|
| States | another registered state's name or two-letter code (`STATE_META`) | that state's page at `#/dashboard` |
| Counties / Parishes | a county of the open state (`ALL_COUNTIES`), exact, prefix (3+ letters) or contained as a whole word; "County" / "Parish" in the query is ignored | the county intelligence page (`openCountyPage`) |
| My research | a research list whose name contains the query, or a saved property whose record matches the query | My Research on that list (`openResearchPage`) |

Rules:

- Deterministic word matching (`gsGroups()`), no model, no score. Each group
  is ordered exact → prefix → contained, then alphabetically, with at most 3
  states, 3 counties and 4 research entries.
- A query that starts with a digit is an address, parcel or case number,
  following the natural-query rule. It never routes to a state or a county.
- The current state is never offered as a "switch".
- Every group row is a `.gs-row` option with a sequential `gsOpt<n>` id, so
  arrow keys and Enter move through counties and properties in one list.
- When no property matches but a group does, the groups still show, with
  "No … property matches “q” itself".

Test hook: `window.__tdwSearchGroups(q)`.

## 2. Cross-links

- **Same parcel → county.** The "Same parcel in other ledgers" section ends
  with a link to the county intelligence page, for every ledger.
- **Timeline → other record.** Each timeline entry from another ledger opens
  that record (`viewdetails`). For example, a certificate's timeline opens the
  auction for the same parcel.
- **Deep links use the property's own ledger.** `openDetail()` writes
  `#/<slug of p.source>/<id>`, no longer the List's current ledger. Opening an
  auction record from a certificate page used to write
  `#/certificates/<auction id>`; it now writes `#/auctions/<id>`.

## 3. Parcel timeline (outcome history across ledgers)

`parcelTimelineFor(p)` / `parcelTimelineHtml(p)` add the "Parcel timeline"
section (`data-section="timeline"`, tab "Timeline") after "Same parcel in
other ledgers". It is one chronological list of every dated fact the app
holds for the record and for the same parcel's records in the other ledgers.
Records are matched by exact state + county + parcel identity
(`relatedRecordsFor`, which never matches fuzzily).

| Kind | From | Wording |
|---|---|---|
| `first_seen` | `first_seen_at` | First observed in <ledger> |
| `cert_issued` | `issued_date` | Certificate issued (as published) |
| `cert_expiration` | `expiration_date` | Expiration date (as published); once passed: "redemption status not published" |
| `sale_scheduled` | future `sale_date`, record still listed | Sale scheduled |
| `sale_last_published` | future `sale_date`, record has left the list | Sale date last published - the record has since left the source list |
| `sale_passed` | past `sale_date`, no published result | outcome not published / not yet verified |
| `sale_result` | past `sale_date` + `auctionOutcomeState().verified` | the verified label, with the source's own wording |
| `left_list` | `delisted_at` / `gone_since` | Left the <ledger> source list - not a sale result |
| `last_read` | `last_seen_at`, still listed | Last read on <ledger> |

The timeline never says why a record moved between ledgers. A passed date or
a record leaving a list is never shown as a sale, a redemption or a
forfeiture. A purchaser, a bidder or a winning bid never appears, because
none is stored. Test hook: `window.__tdwParcelTimeline(pid)`.

## 4. Tests

`tests/run_test.mjs`, block "Grouped search, cross-links, parcel timeline":

- group vectors, including that a digit-led query routes to no county or state;
- dropdown order and option ids;
- keyboard routing to a county page, plus state and research routing;
- timeline kinds for six fixture records and the certificate → auction
  cross-link hash;
- the county link;
- no horizontal overflow at 390 / 430 / 768 / 1024 / 1440 / 1920 px.

## Verification pass (2026-10-06): one property-page order for every ledger

From top to bottom:
1. Identity
2. Status band: ledger, official status, last read, and "Your research", which carries the due-diligence count
3. How to acquire
4. Financial position
5. Property intelligence: overview, decision, inventory, tax and value, property, history, Risk & Legal, map
6. My research
7. Due diligence
8. History: same parcel in other ledgers, parcel timeline, sale events
9. Watch
10. Source truth
11. Documents

A certificate page follows the same order, with Source truth after its timeline. The timeline's cross-ledger link reads "Open the <ledger> record →".
