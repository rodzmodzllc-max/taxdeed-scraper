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
`Read from <sourceNameFor(p)> · last synced <date> (<n> days ago)[ · may be stale] · last read <date | not recorded>`;
when the row carries no source name the line starts `Source not recorded · …` (a source is never
"read from" a placeholder - review H6).
Never a relative time without its date, never a source name the row does not carry.

Under it, one `.record-gaps` line (the class was `.unknown` until review PR1-04 found it
colliding with `.copy-btn.unknown` / `.ledger-badge.unknown`): `Not known from the record: <dataGaps(p) joined by " · ">. Nothing here is estimated.`
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
sale event history), Source (Source truth, Documents & links,
Data Quality & Provenance, Research & Sources, the Available list link, "Why am I
seeing this?"), Mine (the research cell, My research, Due diligence,
Watch & changes, notes). Every `data-section` id survives. The certificate page is grouped the same
way (review H9): Decision (certificate decision + stat tiles) and the facts row
open, then Property & history, Same parcel & timeline, Source and Mine folds.

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

## Review fixes

Two reviewers returned 18 findings (H1-H9, PR1-01..09) against `5f6fc2a`. Each was
checked against the code before acting; all 18 were confirmed and fixed - none
rejected. The code half landed as `a310a42` (WIP) and this commit; the pins, the
Python anchor and this document are in this commit.

| Finding | What was wrong | Fix |
|---|---|---|
| H1 (major) | A row that left the county feed before its sale date read "sale date … has passed" and "after the sale the county publishes results there" - a sale the record never recorded. | `auctionLinkInfo()`: only a date behind us "has passed"; a future one reads "was scheduled for <date>". `auctionAcquireHtml()`: a gone row with a future or no date reads `outcomeText(p)` + "why (redeemed, cancelled, postponed, sold) is not recorded; check the county record." |
| H2 (major) | Contents entry "sale scheduled, no result yet" on a row whose facts row says "No longer listed". | `detailGroupStatus("related")` prints `outcomeText(p)` for a gone auction row before consulting `auctionOutcomeState()`. |
| H3 (major) | Risk & legal status always "liens not tracked" and lower-cased FEMA's zone label. | FL rows: `Manual lien notes: ${LIEN_LABEL[p.lien_level] \|\| "Not reviewed"}` (the banner's own fields); other states keep "liens not tracked"; `floodShort(p).text` as returned. |
| H4 (major) | "assessed" hard-coded in the Money status and the Value sub-line. | `assessedSourceLabel(p)` in both places (MI: "State Equalized Value (county list)", TX: the CAD label). |
| H5 (major) | "the official listing is the source's own statement" on vendor-listed rows (TX LGBS). | "official" dropped: "the listing is the source's own statement of availability." |
| H6 (minor) | "Read from Source not recorded · …". | `provenanceLineText()` starts "Source not recorded · …" when `sourceNameFor(p)` is null; the first-fold check accepts either prefix (`provPrefix`). |
| H7 (minor) | Ledger / program / sale date each stated twice in the first fold. | The record-kind sub-line renders only outside Florida (where it adds a fact the kicker lacks: struck-off, dated Parish list, a non-FL program); the Acquire CTA reads "View sale listing" (the Sale cell carries the date); `firstFoldAuction.cta` is now the full label, so a date in it would be counted. |
| H8 (minor) | "Property & history" rendered but was missing from the contents list; list numbers (01..08) disagreed with the CSS counter on the page (01..06). | `detailGroupEntries()`: a rendered `data-group` with no named section is listed with the group as target (the `jump` action resolves `details.detail-group[data-group]`); `detailHtml()` writes the list's number into each summary (`data-n`), the `dgroup` counter is gone. |
| H9 (minor) | The certificate page kept a flat layout the plan does not exempt. | Grouped: Decision + facts open; Property & history, Same parcel & timeline, Source, Mine as `details.detail-group`. |
| PR1-01 (blocker) | The seven new checks had no EXPECTED entry, so they could never fail. | Pinned from the dump (`firstFoldAuction`, `firstFoldJumpOpensDecision`, `firstFoldActbarFav`, `firstFoldAvailable`, `firstFoldUnverifiedAvailable`, `detailContents`, `detailContentsJumpOpensGroup`) - see "Checks re-pinned". |
| PR1-02 (blocker) | Stale pins the suite fails on (`refineDossier`, `detailNavLabels`, `rdDetail.tabs`, `offListDetail`, `researchCell*`, `flInventoryNavHasInventory`, `decNavHasDecision`, `eventNavPill`, `monDetailNavPill`, the timeline `navPill`, `ledgerRecordBand`). | Readers retargeted at the groups where the old pill is gone; values re-pinned from the dump. Table below. |
| PR1-03 (blocker) | Placeholders in this document. | Filled from the final dump. |
| PR1-04 (major) | `.unknown` collided with `.copy-btn.unknown` / `.ledger-badge.unknown` (identity.css loads last). | Class renamed `.record-gaps` (app.js, identity.css, the test selector). |
| PR1-05 (major) | Favorite / Watchlist from the bottom bar re-rendered the page and closed every fold. | `refreshOpenDetail()` records each `details` open state and `scrollTop` before `openDetail()` and restores them. |
| PR1-06 (minor) | Mine entry stuck on "Loading your research…". | `researchAfterOpen()` rewrites `.detail-toc button[data-group="mine"] .toc-s` once research has loaded. |
| PR1-07 (minor) | The band no longer named the record's ledger. | `.dossier-sub.ledger-name` ("<ledger> ledger") in cell 1 whenever `ledgerRecordView(p).ledger_name` differs from this state's list title; `ledgerRecordBand` reads that class. |
| PR1-08 (minor) | `.toc-n` / `.toc-s` / `.dossier-research-band dt` below 12px. | All three at `.75rem`. |
| PR1-09 (minor) | `refineDossier.lastRead` reader kept the "last read " prefix. | Reader strips it; the pin stays the date. |

Also found while finishing: the root mirror of `app.js` and the Python anchor
`test_detail_page_places_money_after_acquire_and_documents_after_source_truth`
still carried the Source-group order "truth, provenance, documents"; the browser
check `order.indexOf('documents') === order.indexOf('truth') + 1` (and CLAUDE.md:
"`documents` sits right after `truth`") requires documents directly after truth,
which `public/app.js` already did. Mirror and anchor now follow the code.

## Checks re-pinned

All values below were read from `DUMP_RESULTS` runs against the served build
of this branch, never guessed. "Why correct" says what the new value shows.

| Check | Old | New | Why the new value is correct |
|---|---|---|---|
| `brandSwReload.cache` | `tdw-shell-v137` | `tdw-shell-v138` | PR1's own service-worker bump. |
| `refineDossier.status` | `["Ledger","Status","Last read","Your research (…)"]` | `["Availability","Price","Value on file","Source · last read"]` | The band is the four-fact row (plan item 1); the research cell moved to Mine. |
| `refineDossier.lastRead` (reader) | read `dd[2]` | reads the last segment of the provenance cell (`dd[3]`), `last read ` stripped; value stays `Sep 20, 2026` | The last-read date now lives in the provenance line (graft D). |
| `detailNavLabels` | 15 pill labels (`Decision`, `Tax & Value`, …) | 8 entries `01 Acquire Registration not yet verified` … `08 Mine On your account · Not saved · 7 of 15 verified` | The numbered contents list with each group's honest status (plan item 6); every status is an existing helper's output. |
| `rdDetail.tabs` | 17 pill labels | 8 entries for p3 (`03 Property & history Vacant Lot`, `07 Source FL LAFT Html · last read Sep 20, 2026`, …) | Same list on the Available page; `why` / `acquire` unchanged. |
| `txRaDetailLinkText` | `/^View sale listing for <date>$/` | `/^View sale listing$/` | Review H7: the Sale cell carries the date; the Acquire sheet's CTA does not repeat it. The card's link (`txRaCardLinkText`) keeps the date. |
| `researchCellBefore` / `After.besideOfficial` | `4` | `1` | The research cell is its own `.dossier-research-band` dl in Mine (one child), no longer beside the three official cells; `own` (the "not an official status" label) still true. |
| `acqPathHorryDetail.pdfLinks` | `Bid form →` first | `Download bid form` first | The acquisition CTA leads the Acquire sheet, above the checklist (plan item 3); the same seven links, one order change. |
| `offListDetail` (reader) | `dd.warn` | `dd.warn, dd .warn` | The off-list warning is a `.dossier-sub.warn` inside the Sale cell; the text check is unchanged. |
| `eventNavPill` (reader) | `[data-target="events"]` | `[data-group="related"]` | Sale events sit in the Same parcel & timeline group; value 1. |
| `monDetailNavPill` (reader) | `[data-target="monitor"]` | `[data-group="mine"]` | Watch & changes sits in Mine; value 1. |
| `decNavHasDecision` (reader) | `[data-target="decision"]` | `[data-group="acquire"]` | The decision fold is under Acquire; value 1. The result-jump link still targets `decision` (`firstFoldJumpOpensDecision`). |
| `flInventoryNavHasInventory` (reader) | a pill labelled `Inventory` | Money entry present and `[data-section="inventory"]` rendered | Inventory & Purchase sits in the Money group; value true. |
| timeline `navPill` (reader, `parcelTimeline*`) | button text `Timeline` | `data-group === 'related'` | Same group move. |
| `ledgerRecordBand` (reader) | first `.dossier-sub` | `.dossier-sub.ledger-name` | PR1-07: the ledger name is its own sub-line, shown only when it differs from the state's list title; on the FL page all three stay `null`. |
| Financial-position `order` (reader) | `money === acquire + 1` | allows the `decision` fold between them | The decision fold sits between Acquire and Money; `documents === truth + 1` unchanged. |
| `countyOnlyImagery` (reader) | hero at the top of the page | opens the Map fold and scrolls the hero into view before waiting | The mini-map hydrates from an IntersectionObserver; the value (`drawn: true`) is unchanged. |
| Python `test_detail_page_places_money_after_acquire_and_documents_after_source_truth` | `${acquireBlockHtml(p)}\n${financialPositionHtml(p)}` / truth then documents | the sheet + decision fold + financial position / truth, documents, provenance | Anchors follow the new source order; the rule (money after acquire, documents right after truth) is the same. |
| Python sw pins (six tests) | v137 | v138 | Service-worker bump. |

New pins (`firstFoldAuction`, `firstFoldJumpOpensDecision`, `firstFoldActbarFav`,
`firstFoldAvailable`, `firstFoldUnverifiedAvailable`, `detailContents`,
`detailContentsJumpOpensGroup`) were taken verbatim from `dump-r1.json` after the
review fixes; each value was read before pinning (the gaps line names only
`dataGaps(p)` items, the CTA is `View sale listing` / `Download application`, the
provenance cell starts `Source not recorded` for p5, the eight contents entries carry
their statuses, the Mine entry is not "Loading…").

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
- `firstFoldUnverifiedAvailable` (ptx6 on tx.html, a vendor-listed row): "Verified: Not yet"
  leads the sheet with no "official" wording, no CTA.
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

Against the served build of this branch head (port 8941, `build_serve_any.sh`),
after the review fixes:

- Browser: `PASS: all 1269 checks matched, 8 console error(s) all allowlisted.`
  (1262 carried over + the 7 first-fold / contents-list pins).
- Python: `3018 passed, 129 skipped` (`python3 -m pytest -q tests/python -x`).
- Root mirror byte-identical to `public/` for every tracked file.
