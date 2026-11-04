# Shell redesign (2026-10-04)

Frontend only (`public/` + mirrored root copies, `tests/`). No migration, no
backend, no data, no workflow change. `get_properties()` and every publication
gate are unchanged; the shell only reads the rows `loadAll()` already admitted
for this viewer.

## What changed

| Area | Where | Notes |
|---|---|---|
| Sidebar | `index.html` / `tx.html` / `la.html` (generated pages from `tx.html`) | "TaxDeed-Scraper / Public Property Intelligence"; Home (`data-page="dashboard"`), Search (`data-page="list"`), one entry per ledger (`data-nav-ledger`, label from `ledgerCopy(k).nav`, count = that ledger's tab count), Saved Searches, Watchlist, Map, States & Counties, About; Admin (hidden unless `IS_ADMIN`) and Account at the foot. |
| Global search | top bar, `#globalSearchInput` | Searches the loaded rows of the selected state with the List's own `textMatches()` (address, parcel, case and certificate number, county). Up to 8 results with ledger badges; arrow keys + Enter; Enter with no selection opens the List filtered (on a ledger that has matches). Loading and no-match states say so. |
| Home | `#pageDashboard` top: `renderHome()` | Hero + search, ledger cards (Available first; counts = active rows, same exclusions as the tabs), Browse by state (opens the picker), Recently added (rows with `first_seen_at`, newest first; says so when none is recorded). The operating view below is unchanged. |
| State picker | `#statePicker` sheet, `openStatePicker()` | Every `STATE_META` state, searchable. Current state: real counts per ledger. Other states: which ledgers have at least one row this viewer may see (one `limit 1` probe per state × ledger, two at a time, cached per tab; customers probe customer-published rows only). A badge links to that ledger on that state's page; the state name opens it on its landing ledger. A failed probe reads "Couldn't check", never "no properties". |
| List head | `#listHead`, `#filterChips` | "Available Properties" etc. + "N shown of M in <state>"; one removable chip per active filter (read from the controls, removed through each control's own handler); Clear all = Reset. |
| List layout | `styles.css` | ≥1280px: filters left (always open), list centre, right column = county panel (state outline shaded by the rows on screen; click filters to that county) until a property is selected, then the property page. 1024-1279: filters behind the toggle. <1024: the panel opens in place with its own close header. |
| Cards | `cardAcqBadgeHtml()` | Available cards carry the acquisition mode from `acquisitionOf()`: "Acquisition path not yet verified" (amber), "Bid application required …", "Download the county application" + "No online purchase link on file", or "Purchase or apply online" only for the `online` mode. |
| Property page | `detailCrumbsHtml()`, `whySeeingHtml()` | Breadcrumb Home / ledger / property; the section nav reads as tabs (Acquisition, Overview, …, Map, Source, Provenance - only sections that rendered); "Why am I seeing this?" built from the row's ledger, source, source wording, dated-list / no-longer-listed state, last read, publication review status and the active search. No score. |
| Phone | bottom bar | Home, Search, Map, Saved (watchlist), Account (account menu). |
| Tablet | 768-1023px | The 680px phone column is lifted; county groups lay cards two-up. |

`sw.js` → `tdw-shell-v77`.

## Not built, and why

- **No "All States" mode.** Each state is its own page and `get_properties()` is
  state-scoped; an all-states list would need the cross-state query the
  per-state pages exist to avoid.
- **No per-state counts for states other than the open one.** The customer
  inventory rules applied in the browser (the Detroit customer subset) cannot be
  applied to a server count, so a count there could overstate what the viewer
  would see. The picker shows which ledgers have rows instead.
- **No owner search wording.** The List's existing search matches owner names;
  the new search fields do not advertise it.
- **No price-meaning filter rename.** The existing amount filters keep their
  labels (Purchase path / Amount / Bid range); the amount-kind semantics are
  shown on the card and the property page as before.
- **Map page unchanged.** The List's county panel is a density view built from
  the state outline; the full map (clusters, pins, preview) stays on the Map
  page.
