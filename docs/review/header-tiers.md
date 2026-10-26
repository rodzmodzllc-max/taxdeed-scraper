# Header, filters and essentials-first tiers (2026-10-25)

The owner's brief: one header with nothing repeated, cleaner filters, no
Active / Inactive chips, no repeated county counts, never "available" on the
Available ledger, essentials-first cards so a new investor is not drowned,
the research data grouped and tiered, and the Merged look (Tactile objects
and stamps with the Terrain sale-day strip). During testing nothing is hidden
by acquisition path (`config.js availableGate: "off"`).

## What changed

- **Header** (`installShellV3()` in app.js): brand = Home, the three ledgers
  (one count each) and Map in `#hdrNav`, a compact search (behind a button on
  phones), state, the Look button and ONE account menu that carries Saved
  searches, My Research, Watchlist, County Intelligence and About. Elements
  move rather than being copied, so every id and listener is unchanged.
- **List toolbar** (`installListToolbarV3()`): County, Filters, Sort. Table
  view and Export sit inside Filters; Expand / Collapse all is gone (every
  county opens); the status chip row is gone. Administrators pick another
  listing view inside Filters (`#statusViewSelect`).
- **Default view is current listings** (`statusView: "live"`,
  `isCurrentListing()`): a row that left its list, or an auction the county's
  latest sale-list read no longer carries, is not counted or shown by
  default. Administrators can still show them.
- **Cards** (`card()`, `certCard()`): picture, ONE stamp (`cardStamp()` - a
  fact the record or a verified source states), address, county, ONE labelled
  figure, the way in, Watchlist. Identifiers, the facts row, favourite and
  hide move into "Record details".
- **Property page**: How to acquire, Financial position and the decision
  stay on the first screen; flood, liens, owner, values, property facts,
  history, location, sources, provenance and due diligence are grouped in ONE
  "Research" disclosure, closed until opened (the free tier). A section-nav
  jump into it opens it. Nothing is removed.
- **Ledger head**: the facts line, the colour legend, the per-county
  "x/y active" counts and the customer "N withheld" paragraphs are gone; the
  ledger status strip keeps "Withheld from customers", and administrators get
  one line (`adminWithheldLineHtml`).
- Florida's group line reads "Lands Available list - over the counter" (no
  "available now").
- Fixes found while testing: the new filter styles showed `[hidden]` filter
  rows and fields (the administrator-only listing view among them);
  `[hidden]` now wins there.

## Re-pinned checks (tests/run_test.mjs, marked "header/tiers revision")

Each was re-read from the suite's own dump; every change follows from the
list above:

| Check(s) | Why |
|---|---|
| gateCustomer, gateAdmin, devVis*, tnVisibility (withheld), ledgerWithheldText, gateEnforced* | customer "N withheld" paragraphs removed; the strip and the zero case still say it |
| tnVisibility (tabs), ledgerTabCounts | Available is listed first |
| scaleListInitial, brevardGroupCount, everyLedgerHasFactsLine, legendSwatchCount | repeated counts, facts line and legend removed |
| countyGroupOpenOnLoad, countyGroupsClosedAfterReset, duvalGroupClosedBeforeSearch, expandAll* | every county opens; no Expand / Collapse all |
| goneChipOn, offListCards | status chips removed; off-list auctions are not in the default view |
| navRailItems, rdNav*, rdListHead, rdPhoneSearchVisible, accountGotoPhone, govMenu | header revision (Map in the header, one title line per ledger, search behind a button on phones, the account menu at every width, About replaces the help item) |
| desktop*Column | compact cards sit two-up in a county group |
| laftGroupMeta, flLandsGroupMetaText | "available now" removed |
| certCardStatCount, laftCtaText, bidBtnIcon*, txStruckOffLink, txFutureSaleLink | essentials-first cards |

Checks whose selectors moved rather than whose values changed:
`nav*Lit` (the ledger entries live in `#hdrNav`), `gsPhone.headerCompact`
(one row on a phone), `identityViewports` (the masthead is the top bar). New:
`researchGroup_*`, `researchGroupJumpOpens_*`.
