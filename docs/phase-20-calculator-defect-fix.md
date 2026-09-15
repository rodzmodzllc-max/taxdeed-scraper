# Phase 20 — Bid & Profit Calculator Defect Fix + Regression Gate

Status: **READY_WITH_LIMITATIONS** (see §11). Scope: a single, surgical,
scoped-lookup fix for the calculator defect Phase 19 discovered and
deliberately did not fix, plus the regression coverage and test-infrastructure
updates needed to prove it. No merge/reset/rebase/push/deploy/Supabase/schema/
source-registry/legal-status/48-field-contract/router/panel/modal redesign
work was performed — those remain exactly as Phase 19 left them.

## 1. The original defect (as found and left unfixed in Phase 19)

Phase 19's reconciliation merge brought origin/main's app-shell rebuild into
this branch. That rebuild renders the same property-detail markup
(`detailHtml(p)`, which includes the "Bid & profit calculator" `<details
class="calc-drawer">` block from `calcDrawerHtml(p)`) into **two** places at
once for whichever property is currently open or selected:

- `#detailModalInner` — the full-screen modal (`openDetail(p)`), used on
  every viewport, and the only surface on mobile.
- `#detailPanel` — the persistent desktop detail panel (`selectProperty(p)`),
  visible at >=1024px widths, but still populated (just CSS-hidden) below
  that width.

Both copies carry their own `id="calcNetResult"` and `id="calcMaxBidResult"`
elements. The calculator's `input` event listener updated those results with
a bare `document.getElementById("calcNetResult")` /
`document.getElementById("calcMaxBidResult")` — which always resolves to the
**first** matching element in document order, regardless of which drawer the
user is actually typing into. `#detailPanel` precedes `#detailModal` in
`public/index.html`, so that lookup always grabbed the panel's copy.

Net effect: typing a repair estimate or lien buffer into the calculator
never visibly updated the number the user was looking at, in the modal (the
only surface mobile users have, and the surface most desktop users interact
with when opening a property from a list). Phase 19 proved this directly
with a throwaway Playwright script (repair estimate of $5,000 entered; "Your
Max Bid" stayed at $47,200 before and after) and confirmed via `git show
origin/main:public/app.js` that the same code, with the same bug, was
**already present in origin/main's own code before this branch ever merged
it** — this was not something the merge introduced.

## 2. Affected surfaces

- **Full-screen modal (`#detailModalInner`)** — broken. This is the surface
  every mobile user sees, and the surface any desktop user sees when they
  click "View full property page →" from a card.
- **Desktop persistent panel (`#detailPanel`)** — NOT broken. Because the
  buggy lookup always resolved to the panel's own elements (document order),
  the panel's calculator was, by coincidence, always displaying correct,
  live-updating numbers. Confirmed directly in §6 below: re-running the new
  regression test against the pre-fix code shows the panel's own calculator
  assertions passing unchanged, while the modal's fail exactly as expected.

## 3. Root cause

A single un-scoped DOM lookup (`document.getElementById`) used inside a
listener that has to work correctly no matter which of two simultaneously-
rendered copies of the same template the user is interacting with. The
listener already computes exactly the right scope and just wasn't using it:

```js
const drawer = e.target.closest("[data-pid]");
```

`drawer` is the specific `<details class="calc-drawer" data-pid="...">`
element containing the `<input>` the user just typed into — by construction
it is *never* ambiguous between the modal and the panel, because it's
derived from the actual event target, not a global document query.

## 4. The fix

`public/app.js` and `app.js` (root mirror), inside the global
`document.addEventListener("input", ...)` handler:

```diff
-  const netEl = document.getElementById("calcNetResult");
-  const maxEl = document.getElementById("calcMaxBidResult");
+  const netEl = drawer.querySelector("#calcNetResult");
+  const maxEl = drawer.querySelector("#calcMaxBidResult");
```

(plus an explanatory comment left in place in both files). That is the
entire product-code change for this phase. No formula changed — `grossSpread`,
`netSpread`, `yourMaxBid` and the fee/max-bid math are byte-identical to
before; only *which DOM node* the result gets written into changed.

### Why a scoped lookup is safe here, and why it's the *minimal* fix

- `drawer` was already correctly scoped and already in scope at the point
  of use — no new state, no new element references, no new way for the
  panel and modal to interfere with each other.
- It does not require unique IDs. Two elements can still legally share
  `id="calcNetResult"`/`id="calcMaxBidResult"` (see §5) because every read
  and write in the app now goes through `drawer.querySelector(...)`, which
  only ever looks inside the one drawer the interaction is happening in -
  document-wide ID uniqueness stops being load-bearing for this feature.
- It doesn't touch `calcDrawerHtml(p)`, `detailHtml(p)`, `openDetail`,
  `closeDetail`, `selectProperty`, or any panel/modal/router code - exactly
  as instructed. The panel and modal remain two independent, full copies of
  the same template; this fix just makes the one shared listener correctly
  address whichever copy is actually being edited.

## 5. DOM-ID safety: duplicate IDs deliberately still exist

`id="calcNetResult"` and `id="calcMaxBidResult"` **still appear twice** in
the DOM at once whenever a property has ever been viewed (once inside
`#detailModalInner`, once inside `#detailPanel`) — this phase did **not**
rename either ID, and did not perform a broader DOM-ID refactor, per the
explicit instruction to prefer a scoped lookup over any ID-uniqueness
change. This is safe now because:

1. The only code that ever read or wrote those IDs globally
   (`document.getElementById`) has been changed to a scoped lookup
   (`drawer.querySelector`) that can't cross between the two copies.
2. Every other place these IDs are referenced in the codebase was already
   scoped - `calcDrawerHtml(p)` itself only ever produces the IDs inside a
   `<details data-pid="...">` it controls; nothing else in `app.js` queries
   `#calcNetResult`/`#calcMaxBidResult` globally.
3. It keeps the change surgical: renaming IDs would have meant editing the
   template function, the CSS (if any selectors target those IDs), and every
   test locator that references them - a much larger blast radius for no
   behavioral gain over the listener-side scoping fix.

If a future phase wants full DOM-ID uniqueness (e.g. because some other new
code starts using a bare `getElementById` against these IDs again), that's a
deliberate, separately-scoped follow-up, not something this phase silently
assumed.

## 6. Regression test added

`tests/run_test.mjs` already contained a calculator test block (added in an
earlier phase, before the app-shell merge) that opens the first property,
opens its calculator drawer, records the initial "Net Profit Estimate" /
"Your Max Bid" figures, types a $5,000 repair estimate and $1,000 lien
buffer, and re-reads both figures - which is exactly the flow needed to
catch this defect. It just hadn't been run to completion since the Phase 19
merge: the bare, unscoped `#calcNetResult`/`#calcMaxBidResult` locators it
used threw a Playwright strict-mode violation (`locator resolved to 2
elements`) the moment `#detailPanel` started carrying its own copy of those
IDs too - this is the exact crash Phase 19 reproduced and reported
(`tests/run_test.mjs:641:70` in that phase's line numbering).

This phase:

- **Scoped the existing block's locators** to `#detailModalInner` (the
  modal is the surface being exercised there), so they resolve
  unambiguously to the visible copy instead of throwing:
  `calcInitialMaxBid`, `calcInitialNet`, the two `page.fill(...)` calls,
  `calcNetAfterInput`, `calcMaxBidAfterInput`, and
  `calcInputPersistsAfterReopen`.
- **Added an explicit no-leakage check** (`calcInputNoLeakToOtherProperty`):
  close the first property, open a *different* property, open its
  calculator, and confirm its repair-estimate input is empty rather than
  inheriting the first property's $5,000. Calc inputs are already
  per-property (`calcInputsFor(p.id)` / `saveCalcInput(pid, ...)`, a
  per-`pid` localStorage key), so this was expected to already hold; it's
  now an explicit, checked assertion instead of an unverified assumption.
- **Added a symmetric desktop-panel check** in the existing 1280x900
  desktop-viewport block: after the pre-existing `desktopAuctionModalDocksRight`
  check, the modal is closed (it's a full-screen overlay and was blocking
  clicks on the panel underneath - see the in-code comment), then the SAME
  property's `#detailPanel` copy of the calculator is opened, given its own
  $5,000/$1,000 input, and its own result elements are checked
  (`detailPanelCalcDrawerPresent`, `detailPanelCalcInitialMaxBid`,
  `detailPanelCalcInitialNet`, `detailPanelCalcNetAfterInput`,
  `detailPanelCalcMaxBidAfterInput`) - proving the fix holds for the panel
  surface too, independent of the modal.
- **Scoped one incidental, pre-existing ambiguous selector** this work
  exposed: `[data-action="closedetail"]` (the "✕" button, itself part of
  `detailHtml(p)` and thus also duplicated between the modal and panel) and
  `.info-tip` (also inside `detailHtml(p)`) were bare, document-wide
  selectors elsewhere in the file, unreachable until the calculator crash
  above them was fixed. Once reachable, they hung (closedetail - Playwright
  picked the CSS-hidden panel copy and waited forever for it to become
  visible) or silently double-counted (`infoTipCount`: 8 instead of 4 - the
  panel's and modal's copies both counted). Both are scoped to
  `#detailModalInner` now, for the identical reason and in the identical
  style as the pre-existing `detailModalHasLinks` locator two lines above
  the first of them. **These are test-file-only changes** - no app.js code
  beyond the one calculator fix in §4 was touched, and no assertion's
  *expected value* changed because of them (`infoTipCount: 4` was already
  correct; the fix makes the test measure it correctly instead of an
  inflated double-count).

### Fails against the defective code, passes against the fixed code

Both required by the phase instructions - verified directly, not assumed:

- **Against `origin/main`'s pre-fix `app.js`** (this branch's HEAD,
  unchanged) with this phase's finalized `tests/run_test.mjs`:
  `calcNetAfterInput` and `calcMaxBidAfterInput` mismatch (`+$84,935` /
  `$36,000` - i.e. unchanged from before the input, reproducing the exact
  defect), while `calcInputNoLeakToOtherProperty` and every
  `detailPanelCalc*` assertion pass. This is the expected shape of the
  failure: the bug only ever broke the modal, never the panel, because the
  old unscoped lookup happened to always land on the panel's elements.
- **Against this phase's fixed `app.js`**: all calculator, no-leakage, and
  desktop-panel assertions pass.

## 7. Playwright results

Run via the same throwaway-serve-directory process
`.github/workflows/playwright-test.yml` uses (`public/` + `tests/vendor/
supabase-stub.js` + `tests/config.js` + `fl-counties.svg`, importmap
redirecting `@supabase/supabase-js` to the local stub, served over
`python3 -m http.server`), against the fixed build:

```
FAIL: regression test found 6 problem(s)

Value mismatches:
  ledgerTabCounts: expected ["⚖️Auctions 9","🏞️Lands Available 1","📜Certificates 1"], got ["Auctions 9","Lands Available 1","Certificates 1"]
  desktopLaftListIsMultiColumn: expected true, got false
  watchlistChipLabel: expected "⚑ Watchlist 0/10", got "Watchlist 0/10"
  ledgerTitles: expected [...FL Tax Deed Watchlist...], got [...Tax Acquisitions — Florida...]
  csvDownloadFilename: expected /^taxdeed-auction-\d{4}-\d{2}-\d{2}\.csv$/, got "taxdeed-fl-auction-2026-09-15.csv"
  detailModalHasLinks: expected 6, got 5
```

**Map navigation** (Phase 19's `#mapBtn` → router-navigation fix): not in
this list - still passing, not reverted.

**Calculator regression** (this phase's whole purpose): not in this list -
`calcInitialMaxBid`, `calcInitialNet`, `calcNetAfterInput`,
`calcMaxBidAfterInput`, `calcInputPersistsAfterReopen`,
`calcInputNoLeakToOtherProperty`, `detailPanelCalcDrawerPresent`,
`detailPanelCalcInitialMaxBid`, `detailPanelCalcInitialNet`,
`detailPanelCalcNetAfterInput`, `detailPanelCalcMaxBidAfterInput` all pass.

**The six remaining mismatches are classified `EXPECTED_ARCHITECTURAL_CHANGE`
/ `TEST_OBSOLETE`, not `REAL_REGRESSION` or `NEW_DEFECT`**, for the following
reasons:

- They are **provably independent of this phase's changes**. Five of the six
  (`ledgerTabCounts`, `csvDownloadFilename`, `detailModalHasLinks`,
  `watchlistChipLabel`, `ledgerTitles`) are computed by lines of
  `tests/run_test.mjs` that execute *before* this phase's first edit (the
  earliest is line 67, the latest line 940; this phase's edits start at line
  ~635). The sixth (`desktopLaftListIsMultiColumn`) executes after this
  phase's new desktop-panel block, but by direct code review nothing in that
  block touches viewport size, navigation, or any element the LAFT ledger's
  grid layout could depend on - it only reads text and fills two number
  inputs inside `#detailPanel`.
- Re-running the identical (finalized) test file against the **pre-fix**
  `app.js` (§6) reproduces the exact same six mismatches, byte-for-byte
  identical values, confirming they have nothing to do with the calculator
  code this phase touched in either direction.
- Every one of them reads as a genuine, intentional product/branding change
  from origin's app-shell + FL/TX region-switcher rebuild that Phase 19
  merged in (new page title "Tax Acquisitions — Florida" replacing "FL Tax
  Deed Watchlist"; CSV filenames gaining an `fl-` region prefix; tab/chip
  labels apparently no longer carrying a literal emoji character in their
  text content; a changed LAFT grid column count; one fewer link rendered in
  the detail view) - not corruption, not a crash, not something the
  calculator fix could plausibly cause.
- They were **never previously observable**. Every prior run of this suite,
  since the Phase 19 merge, crashed on the calculator's strict-mode
  violation before ever reaching the final `EXPECTED` comparison at the end
  of the file - this is the first time the suite has run start-to-finish
  since that merge. The `EXPECTED` object was captured before the merge and
  has simply never been refreshed against origin's actual current output.

Per the phase's explicit hard boundary (no redesigning panel/modal/router,
no altering unrelated UI) and its explicit instruction not to suppress
failures, **these six are left exactly as found, not fixed, and reported
here** rather than silently patched or worked around. They represent a
distinct, bounded follow-up: a full `EXPECTED` snapshot refresh against
origin's app-shell + region-switcher rebuild, unrelated to the calculator.
The regression test's own exit code is non-zero because of them (`FAIL: ...
6 problem(s)`) - that is the accurate, honest state of the suite today, not
a Phase 20 regression.

## 8. Pytest results

```
$ python3 -m pytest tests/python/ -q
173 passed in 0.42s
```

Matches the expected baseline exactly. No backend/Python files were touched
this phase, so this was expected and confirms no backend regression.

## 9. Build / syntax

- `node --check app.js` → OK
- `node --check public/app.js` → OK
- `diff app.js public/app.js` → IDENTICAL
- No new imports, no new external dependencies, no router changes, no
  console errors observed during the Playwright run beyond the reported
  value mismatches (which are assertion-level, not runtime exceptions).

## 10. Security regression check

- `git diff public/app.js` contains no matches for `supabase`, `auth`,
  `rest`, `field`, `select(`, `rpc(`, or `csv` (checked directly, case-
  insensitive, against the diff) - the only change is the two-line DOM
  lookup described in §4.
- The 48-field customer-safe contract, internal-field exclusion, CSV export
  logic, Supabase client calls, authentication flow, and raw REST behavior
  are all untouched by this phase - confirmed by the diff being limited to
  the calculator's `input` listener plus explanatory comments.

## 11. Mirror verification

All 12 files the `Auto-sync: mirror public/ to repo root` workflow tracks
(`_headers`, `app.js`, `explore.css`, `explore.js`, `fl-cities.json`,
`fl-zips.json`, `index.html`, `manifest.webmanifest`, `styles.css`, `sw.js`,
`tx.html`, `tx-counties.svg`) plus `icons/` were verified byte-identical
between root and `public/` via SHA-256 comparison after this phase's edit.
`app.js`/`public/app.js` SHA-256:
`264b68f361a0fb01e577b611671b8b2217214a6c66b7ccb862f993c3d4f7cd7a`.

## 12. Remaining limitations

- The six pre-existing, unrelated `EXPECTED` mismatches documented in §7
  remain unresolved. They predate this phase, are provably unrelated to it,
  and fixing them would mean editing branding text, CSS grid rules, CSV
  naming, and detail-view link rendering - all outside this phase's
  explicit "calculator defect only" mandate and its "do not alter unrelated
  UI" hard boundary. They should be picked up as a dedicated follow-up (an
  `EXPECTED` snapshot refresh against origin's app-shell + FL/TX
  region-switcher rebuild), not folded into this fix.
- Duplicate DOM IDs (`calcNetResult`/`calcMaxBidResult`, and, incidentally,
  `data-action="closedetail"` / `.info-tip` elements) remain in the DOM by
  design - see §5. Safe under every current code path, but a future change
  that reintroduces a bare `document.getElementById`/`querySelector`
  against either calculator ID (or a bare selector against the close button
  or info-tip elements) would reintroduce the same class of bug.
- This phase did not investigate whether the dead-looking "✕" close button
  inside `#detailPanel` (harmless - `closeDetail()` only ever touches
  `#detailModal`, so clicking it there is an inert no-op) is worth removing
  or repurposing in the panel context. Out of scope; noted for awareness
  only, not treated as a defect.
