# Saved searches, saved properties and per-state filters (2026-10-05)

Stacked on the large-state performance PR.

## Per-state county filter (bug fix)

The county universe (`ALL_COUNTIES`) was Florida's 67 counties on every page.
Outside Florida this had two effects:

- the County picker offered Florida's counties, all "(0)";
- `passes()` ignored the county selection (`PAGE_STATE === "FL" && ...`).

Now:

- **Florida** keeps its fixed list.
- **Every other state** builds the list from the counties its loaded rows
  name (`extendCountyUniverse`, run as each ledger's pages arrive).
- A county that first appears in a later page joins the selection when
  "All counties" was selected.
- The county filter applies in every state.
- Saved searches store and restore counties in every state.

## Source filter

The List has a **Source** filter in its monitoring filters. Its options are
every source the loaded rows were harvested from (`source_id`, else
`harvester_source`), named as the provenance card names them, with counts.

The saved-search vocabulary has a new `source_ids` key. It is added in both
implementations:

- `savedSearchMatches` in `public/app.js`;
- `scripts/saved_search_match.py`.

`tests/python/fixtures/saved_search_cases.json` gains four source cases.
Both implementations must give the same answers.

## Saved searches

The existing create, view, open ("Show in list"), mark seen, alerts toggle
and delete actions are joined by two more:

- **Rename**, an inline form.
- **Replace with current filters.** The List's current filters become the
  saved criteria. The comparison baseline restarts from what matches now,
  so nothing is reported as "new".

Both record `saved_search_updated`, with no free text. That event is added
to migration 024's `product_events` CHECK list (024 is still NOT applied;
the existing test pins every tracked event to that list).

## Saved properties (the existing watchlist, no second system)

- Every saved card gets a status line:
  - **Still listed** (with the last read from the source);
  - **Changed since your last visit** (the same signals as the change
    panel);
  - **No longer listed by the source**, which never claims a sale.
- A saved property that has left this state's data is no longer only
  counted:
  - the watch snapshot keeps its last known entry, marked `missing`;
  - the watchlist names it under "No longer in <state>'s current listings",
    with a Remove button;
  - it is never removed silently, and the change panel reports the
    departure once.
- The acquisition summary under each saved Available card is unchanged.
