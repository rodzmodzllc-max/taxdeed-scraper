# AVAILABLE workflow: one set of filters for List and Map, acquisition method

2026-10-05. Frontend only, no migration.

## Map uses the List's filters

The Map applies its own toolbar (state, ledger pills, county, search,
watchlist) **and**, by default, the List's filters: `passes()`, the same
function the List uses. That covers county chips, amount range, the Available
filters, acquisition path and method, source, imagery, freshness, and sale
dates. What the List shows is what the Map shows.

- **Toggle:** "Same filters as the List (N)" (`#mapListFilters`) sits beside
  "Watchlist only". N is the number of active List filters. The toggle is
  injected by `ensureMapListFiltersToggle()`, so every state page (static and
  generated) gets it without markup changes.
- **Hash:** turning the toggle off writes `lf=0` into `#/map?...`. A cold
  load of that hash restores the toggle in the off state.
- **Archive view:** the List's archive view (past sales only) has no map
  equivalent and is not applied.
- **"Show on the Map page":** when the List's filters would hide the
  requested property, the toggle switches off, because the request is for
  that property.
- **Counting filters while the List is off screen:** `controlActive()`
  ignores a hidden page section (`[hidden]:not(.page)`), so the Map counts
  the List's filters correctly. A hidden ledger-specific filter row is still
  inactive.

## Acquisition method filter

"Acquisition method" (`#acqModeFilter`, `state.acqMode`) is a filter in the
monitoring row. It applies to Available rows only:

- the options are online, application form, bid application, county
  instructions, mail, in person, e-mail, phone, contact for the amount,
  multi-step, or "Not yet verified";
- the value is read from `acquisitionOf(p)`, the same record "How to acquire"
  shows;
- a mode only matches a verified record;
- choosing it shows a filter chip.

It is not part of the saved-search vocabulary (`scripts/saved_search_match.py`
is unchanged).

## Performance

There is no new request. The Map filters the rows already in memory. The
toggle count reuses `filterChipList()`, and imagery stays lazy (PR #101).
