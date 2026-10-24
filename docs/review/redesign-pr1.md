# Redesign PR 1 - property page first fold

Branch `redesign/1-property-first-fold` (base `fix/at-a-glance-duplicate-shell-cache`).
Direction A of the 2026-10-24 design panel, with the C and D grafts the plan
names (`scratchpad/mockups/PLAN.md`, PR 1 section). Frontend only: `public/app.js`,
`public/identity.css`, `public/sw.js` (v138) and their root mirrors,
`tests/run_test.mjs`, the Python tests that pin the service-worker version and
one source-order pin.

## What changed

**The first fold (390px).** The title block is followed by a four-fact row
(`detailStatusHtml()`, still the `.dossier-status` dl, now `.dossier-status.facts`):

| Cell | Auction | Available | Certificate |
|---|---|---|---|
| 1 | **Sale** - date, "in Nd" / "today" / "Nd ago (past sale date)", then `auctionOutcomeState()` ("Scheduled · no result yet", or the verified / not-published outcome); the record kind and the source's own `tx_sale_status` wording as sub-lines; "Not scheduled"; the gone outcome | **Availability** - the kicker phase (`kickerParts()`), record kind | **Status** - expiry |
| 2 | `auctionBidLabel(p)` (Opening bid / Minimum bid / Published amount (kind not stated)) - `bidDisplay(p)` or "Not published" | `amountInfo(p).label` - the figure, its note when it is not an official current total, "Expired", or "Not published" / "Quoted on application" | Certificate amount - "Not a property price" |
| 3 | **Value on file** - `valueLabel(p)` figure + assessed, or assessed alone, or "No county value on file" | same | **Interest rate** as published, or "Not published" |
| 4 | **Source · last read** - `provenanceLineText(p)` | same | same |

`provenanceLineText(p)` (graft D) is the one provenance wording:
`Read from <sourceNameFor(p) || "Source not recorded"> · last synced <date> (<n> days ago)[ · may be stale] · last read <date | not recorded>`.
Never a relative time without its date, never a source name the row does not carry.

Under it, one `.unknown` line: `Not known from the record: <dataGaps(p) joined by " · ">. Nothing here is estimated.`
(or "nothing missing from the fields this page checks").

**Acquire comes next.** Auctions get a new first section, "Sale & bidding
process" (`auctionAcquireHtml()`, `data-section="acquire"`, the same
`.acquire-card` sheet as Available): the one link `auctionLinkInfo(p)` allows
(with its scope note, or the "no longer current" / "not published" reason), and
"How do I register and bid?" - `auctionProcessHtml()` when the county's own
rules were read, otherwise `Verified: Not yet · the county's registration,
deposit and payment rules for this sale have not been captured from its own
page`. The "Sale result and bidding process ↓" link moved from the status band
into this sheet; it opens the decision fold under it. Available's existing
`acquireBlockHtml()` now leads with its verification state and its CTA
(`acquisitionCta()`), above the 14-item checklist.

The decision Q&A (`auctionDecisionHtml()` / `availableDecisionHtml()`,
`data-section="decision"`) is unchanged and sits in a
`<details class="detail-more decision-fold">` directly under the Acquire sheet.

**Section order.** Acquire · Money (Financial position, Financial stats,
Inventory & Purchase, the FL calculator) stay open. Then six
`<details class="detail-more detail-group">` groups, open on desktop and closed
on phones by the existing `collapseSecondaryOnPhone()`: Property & history
(Property Details, History, legal description, identifier copy row - a Florida
row's name is labelled "Name in which assessed"), Risk & legal (manual lien
notes banner, Risk & Legal card), Map & location (the imagery ladder hero,
GIS & Location), Same parcel & timeline (related records, parcel timeline,
sale event history), Source (Source truth, Data Quality & Provenance,
Documents & links, Research & Sources, the Available list link, "Why am I
seeing this?"), Mine (the research cell, My research, Due diligence,
Watch & changes, notes). Every `data-section` id survives; the certificate
page keeps its flat layout and gains the facts row and the action bar only.

**Contents list (graft D).** `detailNavHtml(bodyHtml, p)` renders
`.detail-nav.detail-toc`: one numbered `<button data-action="jump">` per group
that rendered, with the group's honest state from `detailGroupStatus()`
(acquisitionOf / value fields / tax-roll facts / floodShort / coordinates /
relatedRecordsFor + auctionOutcomeState / sourceNameFor + last_seen_at /
research state + diligence counts). It follows the facts row, is sticky in the
modal, static in the narrow side panel (container query) and hidden on phones.
The `jump` action (and `openacq`) now opens every `<details>` ancestor of the
target before scrolling (`openDetailFolds()`).

**Bottom action bar (graft C).** `detailActionBarHtml()`: Favorite · Watchlist
· Acquire (`data-action="jump" data-target="acquire"`; "Decision" on a
certificate), `position:sticky; bottom:0; flex-shrink:0`, 44px targets, hidden
from 1024px and in `#detailPanel`. The buttons carry the same `data-action`
and `data-pid` as the top row, so the existing handlers serve both.

**Deliberately not changed.** No data, label or estimate was added. Cards,
the Map preview and Home are PR 2 / PR 3. The decision Q&A keeps its own gap
list (the full-page sections keep theirs; only the first fold states each gap
once).

## Checks re-pinned

All values below were read from `DUMP_RESULTS` runs against the served build
of this branch, never guessed. "Why correct" says what the new value shows.

RE_PIN_TABLE

## New checks

- `firstFoldAuction` (p5 at 390x844): the four dt labels; the sale cell is a
  date; "$8,000.00" and "$95,000" and the Acquire CTA all end inside the first
  844px of `#detailModalInner`; the gaps line text; the figure, the value and
  the date each appear once in the rendered first fold; the groups and the
  decision fold start closed; the contents list is hidden; the action bar is
  on screen with 44px targets; the section ids.
- `firstFoldJumpOpensDecision`: the "Sale result and bidding process" link
  opens the closed decision fold and scrolls.
- `firstFoldActbarFav`: the bar's Favorite toggles the same favorite the top
  row shows.
- `firstFoldAvailable` (p15): the "Download application" CTA inside the first
  fold, "Price · Not published", the gaps line.
- `firstFoldUnverifiedAvailable` (p3): "Verified: Not yet" leads the sheet, no
  CTA.
- `detailContents` / `detailContentsJumpOpensGroup` (p1 at 1280, side panel):
  the contents list follows the facts row, its eight entries with their
  statuses, no score words, groups open on desktop, the bar hidden; a jump to
  Source truth opens a closed Source group and marks the entry.

## Screenshots

Taken from the served build, signed in through the stub, in this folder
(`docs/review/redesign-pr1/`):

- `property-auction-390-first-fold.png`, `property-auction-390-scrolled.png`
- `property-available-390-first-fold.png`
- `property-certificate-390.png`
- `property-auction-1280-panel.png`, `property-auction-1280-panel-scrolled.png`
- `property-available-1280-panel.png`

## Suites

SUITES_LINE
