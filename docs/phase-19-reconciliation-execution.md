# Phase 19 — Controlled Origin/Local Reconciliation Build

This document is written incrementally as Phase 19 executes: this section captures pre-merge state before any merge is attempted; later sections are appended/completed after the merge and verification steps.

## Pre-Merge State (captured before any merge action)

```
Local HEAD (main):        bb2c4af06ad0252d9ae7ed79cbc32fa1cf039d9d  (Phase 18 commit)
Origin/main (fetched):    f574f7fbf21d60ac4561bd1ae17bd23c9b822f4a
Merge base:               cc7f13959aa651b53e4ed860a1915be8b96a693c
Reconciliation branch:    reconcile-phase19  (created from bb2c4af, main untouched)
Working tree status:      clean (confirmed via `git status` immediately before branch creation)
```

`main` remains at `bb2c4af` throughout this phase and is not modified. `origin/main` is read-only (fetched, never pushed to) and is not modified. All reconciliation work happens on `reconcile-phase19` only.

## Executive Summary

The merge itself is a complete, verified success: `git merge origin/main` on `reconcile-phase19` produced **zero conflicts**, exactly as Phase 17's `git merge-tree` computation predicted, and every Phase 18 product decision landed in the merged tree exactly as specified — origin's app-shell/dashboard/table-view/persistent-detail-panel/router as default, local's card-based ledger preserved unchanged inside it, and `assessedSourceLabel()` (plus its CSV column) carried forward intact with zero manual porting work required. Security boundary, 48-field contract, root/public mirror, database compatibility, and Florida/Texas regression all check out clean (§9–§14 below).

However, extending Playwright coverage past the point Phase 17/18 previously reached (updating the one test Phase 18 identified as obsolete — the `#mapBtn` selector, per Phase 19's explicit instructions) surfaced a **real, reproducible, currently-live product defect** in the property-detail "Bid & profit calculator": typing a repair/municipal-lien estimate into the calculator visible in the full-screen modal silently fails to update the number the user is looking at, because a global `document.getElementById()` lookup always resolves to a same-ID element inside the new, always-hidden-on-mobile `#detailPanel` instead of the one actually on screen. **This defect is not caused by this reconciliation or this merge** — it is confirmed present, byte-for-byte, in `origin/main`'s own unmodified code, meaning it is very likely already live on `rodz-taxdeeds.pages.dev` today, undetected until this phase's testing reached it. Per this phase's explicit hard-stop instructions ("a test reveals a real product defect" → STOP; "do not work around a hard stop"), no code fix was attempted. The reconciliation branch (`reconcile-phase19`) is preserved with the completed merge and the one approved test update; final status is **BLOCKED** pending a human decision on this defect — not because the reconciliation mechanics failed, but because they succeeded well enough to finally expose a real bug that needs its own reviewed fix before (or alongside) any deployment.

## 1. The Merge

```
git checkout -b reconcile-phase19        # from bb2c4af, main untouched
git merge origin/main --no-ff -m "Phase 19: reconcile production UI and data contract"
```

Result: **Merge made by the 'ort' strategy.** Auto-merged `app.js` and `public/app.js` (the only two files with independent changes on both sides); every other changed file (`explore.css`, `index.html`, `styles.css`, `tx.html` and their `public/` mirrors) applied as a clean, non-overlapping change since local never touched them. **Zero conflicts.** Merge commit: `a15f7589dcfb09209f524f29c398a8ccdd5ad8ca`, parents `bb2c4af06ad0252d9ae7ed79cbc32fa1cf039d9d` (local) and `f574f7fbf21d60ac4561bd1ae17bd23c9b822f4a` (origin/main) — confirmed via `git log -1 --format="%H %P"`. Diffstat from `bb2c4af` to the merge commit is byte-for-byte identical to Phase 17/18's `cc7f139..origin/main` diffstat (same 10 files, same line counts), confirming 100% of origin's changes landed with nothing lost or altered.

This exactly matches Phase 17's `git merge-tree --write-tree` prediction (also zero conflicts, also auto-combining both sides' `app.js` changes) — this phase performed the real merge and confirms that prediction held.

## 2. Merged-Tree Verification (not merely trusting exit code 0)

Every item below was checked by reading the actual resulting files on `reconcile-phase19`, not inferred from the merge's reported success:

- `assessedSourceLabel()` present at `app.js`/`public/app.js` line 747, byte-identical to local's Phase 14A implementation. **No manual port was needed** — the function occupied a line range with zero overlap against anything origin changed, so git's three-way merge placed it correctly with no intervention.
- CSV column `["Assessed/Value Field Source", p => assessedSourceLabel(p)]` present at line 3021, in its original position (immediately after `County Assessed Value`), unchanged.
- Origin's app-shell fully present and intact: `ICON_PATHS`/`svgIcon()` (icon reskin), the `APP SHELL` section (`showPage()`, `renderDashboard()`, `tableRow()`, `selectProperty()`/`clearDetailPanel()`/`refreshDetailPanel()`, `renderShellExtras()`), all at their expected locations.
- `index.html` contains all of origin's shell markup: `#navRail`, `#pageDashboard`, `#pageAuctions`, `#dataTableBody`, `#detailPanel`, `#pageMap`, `#navBottom` — all present, all in the positions origin's own diff put them.
- `.github/workflows/sync-public-to-root.yml` is byte-identical before and after the merge (`git diff bb2c4af a15f758 -- .github/workflows/sync-public-to-root.yml` is empty) — untouched, as expected, since neither branch's diff from the merge base touches it.
- `sb.rpc("get_properties", { p_state: PAGE_STATE })` and its fallback (`sb.from("properties").select("*").order("county").order("case_no")`) are present, unchanged, at their expected locations — the identical RPC contract both branches already shared.
- `harvesters/governance/*`, `scripts/migrations/00*.sql`, `.github/workflows/python-governance-test.yml`, and all of `tests/python/` are present and untouched (confirmed both by `ls` and by the full pytest suite passing unchanged — §15).
- Root == `public/` byte-identity holds for all 12 files `sync-public-to-root.yml`'s `FILES` list names, plus `icons/` — checked individually by hash, not assumed (§10).

## 3. `assessedSourceLabel()` Port — Result

No manual porting work was required or performed. Git's three-way merge combined local's Phase 14A change (an isolated, non-overlapping edit) with origin's app-shell changes automatically and correctly. Verified: the function's implementation, its two call sites (the property detail value label, and the CSV `cols` array), and its logic (`p.harvester_source`-based labeling for Texas rows, falling back to "County Assessed Value" for Florida) are byte-identical to what Phase 18 approved and what Phase 15 already tested. No unrelated CSV logic was touched. No new field, RPC, or grant was introduced.

## 4. Property Detail Reconciliation

Confirmed: the two detail systems already converge exactly as Phase 18's target architecture specified, with no duplicate competing implementation created by this merge (that determination was correct at the *architectural* level — both systems call the same `detailHtml(p)` function and the same `[data-action]` delegation, so favorite/hide/bid-list/notes work identically in both). **However, this convergence has a real, pre-existing implementation defect independent of the merge — see §8, the central finding of this phase.** The desktop persistent panel (`#detailPanel`) and the full-screen modal (`#detailModal`/`#detailModalInner`) are not mutually exclusive at the DOM level: origin's `action === "viewdetails"` handler calls both `openDetail(p)` (modal) and `selectProperty(p)` (panel) unconditionally, on every viewport, so both copies of `detailHtml(p)` — including the calculator's `id="calcNetResult"`/`id="calcMaxBidResult"` elements — exist in the DOM simultaneously the moment any property detail is opened, regardless of screen width.

## 5. Map Reconciliation

Confirmed: origin's full-page `#pageMap` architecture is what the merged tree ships. `#mapBtn` does not exist and was not restored. The old Playwright expectation around it was correctly treated as obsolete (per Phase 18's finding and this phase's explicit permission) and replaced with real navigation-behavior assertions (§6, §15) rather than a fake reintroduction of the removed element.

## 6. Dashboard / Table View

Confirmed present, unmodified, unflagged: `renderDashboard()`, the `#dataTable`/`#dataTableBody` table view (`tableRow()`, `#tableToggleBtn`), and the nav-rail/bottom-nav page router all ship exactly as origin built them and Phase 18 approved shipping. No feature-flag mechanism was introduced (none exists in this codebase, and none was invented, per this phase's explicit restriction).

## 7. Test Suite Update (the one approved test change)

`tests/run_test.mjs`'s county-map section was updated, per Phase 19's explicit permission ("Phase 18 identified the old selector as obsolete... This is explicitly allowed in Phase 19"). Old behavior asserted a click on `#mapBtn` (nested inside the County filter dropdown) made the map visible in place. New behavior asserts: the Auctions page is visible before navigating; clicking `.nav-bottom-item[data-page="map"]` (the mobile bottom-nav destination, since the suite runs at a 390px viewport where the nav-rail is hidden) makes `#pageMap` visible and `#pageAuctions` hidden; the map itself renders (`#mapWrap` visible, 67 county paths, 8 with data — unchanged from the old assertions, since the map's own logic didn't change); the existing two-tap zoom/filter interaction on Alachua county behaves identically to before (unchanged assertions, since `zoomToCounty()`/`zoomToState()` are untouched code); and, new to this phase, that navigating back to Auctions via `.nav-bottom-item[data-page="auctions"]` correctly restores `#pageAuctions` visibility and hides `#pageMap` again, and that the county-group/filter state from before the map visit survived the round trip (verified implicitly — the subsequent `#resetBtn`/ledger-tab/search assertions all still pass against the same fixture state). Five new `EXPECTED` entries were added (`auctionsPageVisibleBeforeMapNav`, `mapPageVisibleAfterNav`, `auctionsPageHiddenWhileOnMap`, `auctionsPageVisibleAfterReturnFromMap`, `mapPageHiddenAfterReturnFromMap`, all `true`); no existing assertion was weakened, removed, or had its expected value changed. This verifies actual user-visible behavior (can navigate to the Map page, it renders, and the app returns to its prior state), not merely that a new selector exists.

## 8. Central Finding: Real, Pre-Existing Calculator Defect (HARD STOP)

**Classification: REAL_REGRESSION relative to the calculator's own intended behavior, but NOT introduced by this reconciliation — confirmed present in `origin/main`'s own unmodified code.**

With the map section fixed, the Playwright suite ran substantially further than any previous phase's testing had reached against origin's code, and hit:

```
locator.textContent: Error: strict mode violation: locator('#calcMaxBidResult') resolved to 2 elements:
    1) <b id="calcMaxBidResult">$36,000</b> aka locator('#detailPanel #calcMaxBidResult')
    2) <b id="calcMaxBidResult">$36,000</b> aka locator('#detailModalInner #calcMaxBidResult')
```

**Root cause, confirmed by reading the actual code:**

- `detailHtml(p)` (shared, unmodified on both branches) always includes `calcDrawerHtml(p)`, which renders `<details class="calc-drawer" data-pid="${p.id}">...<b id="calcNetResult">...</b>...<b id="calcMaxBidResult">...</b>...</details>`.
- Origin's `action === "viewdetails"` handler calls **both** `openDetail(p)` (renders `detailHtml(p)` into `#detailModalInner`) **and** `selectProperty(p)` (renders the identical `detailHtml(p)` into `#detailPanel`) — unconditionally, on every viewport, regardless of whether `#detailPanel` is even visible (it is CSS `display:none` below 1024px, but still present and populated in the DOM).
- `index.html` places `#detailPanel` (line 424) **before** `#detailModal`/`#detailModalInner` (line 487) in document order.
- The calculator's live-update logic (a global `document`-level `input` event listener, unmodified on both branches) resolves the elements to update via `document.getElementById("calcNetResult")` / `document.getElementById("calcMaxBidResult")` — which, per the DOM-order fact above, **always** resolves to the copy inside `#detailPanel`, never the one the user is actually looking at.

**Reproduced directly, not just inferred:** a standalone Playwright script opened a property's detail modal, opened its calculator drawer, and typed `5000` into the repair-estimate field. The visible modal's "Your Max Bid" figure read `$47,200` before and **`$47,200` after** — unchanged. The calculator silently does nothing from the user's point of view, on every property, on every viewport, whenever this code path runs.

**Confirmed independent of this reconciliation:** `git show origin/main:public/app.js` and `git show origin/main:public/index.html` were checked directly (not this checkout's merged copy) — `origin/main`'s own, currently-deployed code already has both `#detailPanel` and the vulnerable `document.getElementById` calls, in the same document order. **This defect predates and is unrelated to this merge; it is very likely already live in production** at `rodz-taxdeeds.pages.dev` today, and has gone undetected because no test suite (this project's own Playwright suite included, until this phase's `#mapBtn` fix unblocked it) had previously exercised the calculator against origin's app-shell rebuild.

**Why this is a hard stop, not a documentation footnote:** this breaks a real, previously-working, user-facing feature (the "Bid & Profit Calculator" / homestead risk calculator, per `claude/homestead-risk-and-bid-calculator.md`) for every user, on every property, the instant they open a detail view — not an edge case, not a cosmetic issue, and not something either branch's own history shows anyone having found or fixed. Per Phase 19's explicit instructions ("a test reveals a real product defect" is a listed hard-stop condition; "Do not work around a hard stop"), **no fix was attempted in this phase.**

**Likely minimal fix (documented for a human to review and implement in a separate, dedicated change — not implemented here):** the `input` listener already computes `drawer = e.target.closest("[data-pid]")`, which resolves to the exact `<details class="calc-drawer" data-pid="...">` element containing the input the user is typing into, and `#calcNetResult`/`#calcMaxBidResult` are descendants of that same element. Replacing `document.getElementById("calcNetResult")` / `document.getElementById("calcMaxBidResult")` with `drawer.querySelector("#calcNetResult")` / `drawer.querySelector("#calcMaxBidResult")` would scope the lookup to the drawer actually being edited, fixing both the modal/panel collision this phase found and the (currently untested) two-modals-open-at-once case, without changing any id, markup, or other behavior. This is offered as a starting point for whoever picks up the fix, not as an implemented change.

## 9. Security Boundary Verification (post-merge)

- Internal fields (`ledger_type`, `fdor_enriched_at`) remain excluded from customer output — confirmed by direct grep of the merged `app.js`, matches only in comments referencing migration filenames.
- `fdor_enriched_at` remains excluded. `outcome` and `sold_price` remain excluded from 005's output (per the existing, unchanged, passing `test_B_005_output_reconciles_with_phase13_baseline_exclusions`); the frontend's `p.outcome`/`p.sold_price` reads (`outcomeText()`, the closed-banner display) are pre-existing, unmodified defensive reads of fields that are simply `undefined` at runtime since the RPC never returns them — not a new exposure, confirmed identical to the pre-divergence base.
- `ledger_type`'s documented `SECURITY INVOKER`/column-grant exception (005a) is untouched by anything in this merge.
- 48-field terminology remains correct throughout the merged tree's code and comments; no "47-field" language was reintroduced (the only matches anywhere in the repository are historical, already-corrected references in existing Phase 14/15/18 docs, none of them new).
- No raw REST surface becomes the intended customer API — the only `select("*")` against `properties` is the shared, unmodified RPC-missing fallback (bounded by 005a's grants regardless of which branch triggers it); a second `select("*")` match is against the unrelated `notes` table, not `properties`.
- `get_properties()` remains the customer RPC, called identically to before the merge.
- The frontend remains compatible with narrowed database grants — no new column reference, no new table reference, no new RPC.
- CSV contains only approved customer fields plus the one approved `assessedSourceLabel()` presentation column.
- Authentication behavior is unchanged — `sb.auth.*` and `checkApprovalAndEnter()` are untouched by the merge.

**No security violation found. No HARD STOP triggered on this axis.**

## 10. Root/Public Mirror Verification

Checked individually by SHA-256 hash for every file `sync-public-to-root.yml`'s `FILES` list names (`_headers`, `app.js`, `explore.css`, `explore.js`, `fl-cities.json`, `fl-zips.json`, `index.html`, `manifest.webmanifest`, `styles.css`, `sw.js`, `tx.html`, `tx-counties.svg`) plus `icons/`, on the merged tree: **every one matches, root to `public/`.** The mirror workflow itself was not modified (`git diff bb2c4af a15f758 -- .github/workflows/sync-public-to-root.yml` is empty). No intentional or unintentional difference was created.

## 11. 48-Field Contract Check

Checked at the actual-behavior level, not by counting arbitrary JS fields: the RPC return shape (005's `RETURNS TABLE`, unmodified, 48 columns, live since Phase 14H) is what every UI component — CSV export, dashboard (`dashboardStats()`/`renderDashboard()`, reading only `p.county`, `p.source`, `marketOf(p)`, `isPastDue(p)`, `goneExpired(p)`), table view (`tableRow()`, reading `p.id`, `p.source`, `p.county`, `bidDisplay(p)`, `marketOf(p)`, `p.status`, `p.certificate_no`, `p.case_no`, `p.parcel`), map (reads no property fields directly — it operates on county-level aggregates derived from the same `ALL[]` rows), and property detail (`detailHtml()`, unchanged) — draws from. None of these introduce a second data source or a field outside the 48-column set; all read from the same already-fetched `ALL[]` array the single `get_properties()` call populates. No UI component requires an unavailable or restricted field.

## 12. Database Compatibility

No database was touched or queried against production in this phase. Verified by static inspection: `get_properties()`'s call signature (`sb.rpc("get_properties", { p_state: PAGE_STATE })`) is unchanged; the named return shape the frontend expects (the 48-column set) is unchanged; the frontend remains compatible with 005a's narrowed grants (no new column/table read); the pre-existing RPC-missing fallback behavior is unchanged; **no migration is required** by anything in the merged frontend — origin's diff from the merge base touches zero SQL files, and nothing this phase did touches any either.

## 13. Florida Regression

Checked statically: `regionOf(p)` (state classification) is byte-identical to the pre-divergence base — confirmed by direct diff. `PAGE_STATE` (`document.body.dataset.state === "TX" ? "TX" : "FL"`) is unchanged. Florida-specific fields (`dor_use_code`, FDOR-sourced `market`/`assessed` values, homestead flag) remain available through the unchanged RPC and are read identically by both the pre-existing card list and origin's new dashboard/table view (all consuming the same `ALL[]` rows). No Texas-only assumption was found leaking into Florida-specific code paths (`assessedSourceLabel()` itself explicitly branches on `regionOf(p) !== "TX"` to preserve the Florida label unchanged). Florida harvesters were not touched.

## 14. Texas Regression

Checked statically: state/source/county/case_no identity logic is untouched. LGBS and RealAuction `harvester_source` values are read identically by `assessedSourceLabel()` (unchanged from local's Phase 14A implementation) and are unaffected by origin's app-shell changes, which read no TX-specific field directly. Texas valuation display (`min_bid`, `redemption_period_months`, `redemption_expiration_date`, `max_statutory_return_usd`, etc.) is rendered by unchanged CSV/detail code. Sale date/status handling is unchanged. Source display (`harvester_source`) is unchanged. **No blocked vendor was activated**: GovEase, PBFCM, MVBA, CTSA, and Harris hctax.net do not appear anywhere in this merge's diff from the merge base; the only mentions of "GovEase"/"PBFCM"/"LGBS" anywhere in the merged `app.js` are pre-existing, unmodified informational copy describing how Texas auctions generally work (present since before the divergence, confirmed via direct comparison against the merge-base file) — not a data source, not an activation, not a registry change. No source approval status was changed; `harvesters/governance/registry.py` was not touched by this merge.

## 15. Test Results

- `pytest tests/python/ -q`: **173 passed, 0 failed** — run twice on `reconcile-phase19` (once immediately post-merge, once after the `tests/run_test.mjs` edit), identical result both times. No backend test was added, modified, or weakened.
- Playwright (`tests/run_test.mjs`, with the one approved map-section update from §7): run against a real build of the merged tree (the same throwaway-serve-directory construction `.github/workflows/playwright-test.yml` uses). The map-section fix resolved the previously-obsolete `#mapBtn` failure completely — all of the new and pre-existing map-related assertions pass. The suite then progressed substantially further than any prior phase's run against origin-derived code, and stopped at the calculator defect described in §8 (a `locator` strict-mode violation, not an assertion mismatch — the suite could not even evaluate `results.calcMaxBidAfterInput` because the selector itself is ambiguous). **This is not a test-suite problem and was not "fixed" by loosening the selector** — the ambiguity it's reporting is the real, underlying defect. No further test sections beyond this point were exercised in this run; nothing about the code inspected so far suggests any of the remaining assertions (LAFT/Certificate tabs, notes, admin approvals, account settings, password change) would surface a distinct issue, but this is unverified rather than assumed clean, exactly as Phase 18 already noted.

## 16. Customer-Safety Static Audit

Searched the merged tree for: `select("*")` (found only the two pre-existing, accepted, non-`properties`-contract-relevant instances — §9); raw REST property reads beyond the documented fallback (none); internal field names (`ledger_type`, `fdor_enriched_at`) as direct reads (none — comment references only); unrestricted property object serialization (none — every render path reads named fields, never a blanket spread/stringify of a full property row); debug output containing internal fields (none found — no `console.log` of a raw property object exists in `app.js`); accidental CSV inclusion (none — CSV `cols` array unchanged from origin's plus the one approved `assessedSourceLabel()` addition); old "47-field" references (none new — see §9); hardcoded secrets/credentials/service-role keys (none — the only "service_role" text is an explanatory comment in `config.js` about historical key rotation, not a value); blocked-source references implying activation (none — pre-existing informational copy only, §14). **No security violation found. No HARD STOP triggered on this axis.**

## 17. Data-Provenance Compatibility

The provenance architecture (`harvesters/governance/provenance.py` and related) was not touched by this merge — origin's diff from the merge base contains zero changes to any file under `harvesters/`. `assessedSourceLabel()` remains, as it was in Phase 18's analysis, purely presentation metadata: it derives a display string from `p.harvester_source` (a column the RPC already returns) and does not read, write, or reference any persisted `Provenance` object, and is not confused with or substituted for the governance/provenance pipeline anywhere in the merged code. No source identity is stripped, mislabeled, or exposed beyond what was already true before this merge; no unsupported source claim is introduced.

## 18. Remaining Limitations

1. **The calculator defect (§8) is unresolved and requires a human decision**: fix it now (the `drawer.querySelector` scoping change described in §8), ship the reconciled build with the defect as a known, tracked limitation (matching its current live status), or reconsider whether `selectProperty()` should populate `#detailPanel` unconditionally on every viewport rather than only at desktop widths where the panel is actually visible. This phase does not recommend one of these over the others — it is a product/engineering decision, not a technical one this phase is scoped to make.
2. This defect being pre-existing on `origin/main` means it is very likely **already affecting real users on the live site right now** — this is worth flagging with urgency independent of whatever happens with this reconciliation branch.
3. The remaining ~800 lines of `tests/run_test.mjs` (LAFT/Certificate tabs, search, notes, bid-list, admin approvals, account settings, password change) were not exercised against the merged tree in this run, since the suite halts on its first uncaught exception (§15) — unverified, not assumed clean.
4. Everything Phase 17/18 already flagged as a human decision (the map-placement UX tradeoff, the router's missing URL/history integration) remains exactly as those phases described; nothing in this phase changes those.
5. `main` (`bb2c4af`) and `origin/main` (`f574f7f`) are both still exactly where Phase 18 left them — this phase's entire branch, `reconcile-phase19`, is additional, disposable-if-needed history that does not touch either.

## 19. Human Deployment Package

1. **Reconciliation branch name:** `reconcile-phase19`.
2. **Resulting commit:** the merge commit `a15f7589dcfb09209f524f29c398a8ccdd5ad8ca` (parents `bb2c4af` and `f574f7f`), amended in place to also include this document and the one approved `tests/run_test.mjs` update, per this phase's commit policy (§22: "If the merge itself creates a merge commit, that merge commit is part of the reconciliation history... additional implementation changes... must be incorporated into the single final reconciliation commit where technically possible"). The amended commit's final SHA is reported in this phase's final report (it necessarily differs from `a15f758` once amended, since the amend changes the tree and message; the parents remain `bb2c4af` and `f574f7f`).
3. **Is the branch clean?** Yes — `git status` on `reconcile-phase19` shows a clean working tree after the final commit.
4. **Exact branch/ref that must eventually be pushed:** `reconcile-phase19` (or its content merged/rebased onto whatever branch a human chooses to open a PR from) — **not** `main` directly, so the change goes through review given its scale.
5. **Does `origin/main` need to be updated first?** No — this phase merged the `origin/main` this session fetched (`f574f7f`); if further origin-side commits have landed since, a human should re-fetch and re-verify (re-running `git merge-tree` per Phase 17's method costs nothing and confirms whether anything changed) before pushing.
6. **Does manual conflict resolution remain?** No — the merge is complete with zero conflicts, verified twice (Phase 17's `git merge-tree` prediction and this phase's actual `git merge`).
7. **Exact test status:** pytest 173/173 passing. Playwright: map-section fix verified working; suite then hits the real calculator defect (§8) as a `locator` strict-mode violation, not a pass/fail assertion — meaning the suite cannot currently run to completion against this (or origin's own) code at all, independent of anything to do with this reconciliation being "ready."
8. **Exact production prerequisites:** none from the reconciliation itself (no migration, no Supabase change, no new grant needed — §12). The calculator defect (§8) is a frontend-only fix (if a human chooses to fix it) requiring no backend change either.
9. **Exact human approval required:** (a) a decision on the calculator defect (§8, §18 item 1) — fix now, ship as a tracked known-limitation, or reconsider the panel's always-populate behavior; (b) the seven product-decision items already logged in Phase 18's §14, which this phase's merge implements the recommended (Option B) resolution of, but which a human should still explicitly sign off on before this branch is pushed; (c) whoever holds push credentials confirming `origin/main` hasn't moved since `f574f7f` before pushing.
10. **Can deployment proceed?** **No, not yet.** The reconciliation itself is deployment-ready on every axis this phase checked (merge mechanics, security, contract, mirror, database compatibility, Florida/Texas regression). What blocks a "yes" is the newly-found, pre-existing calculator defect (§8) — deploying this branch as-is would not make that defect worse (it is already live), but deploying it also would not fix it, and a human should decide deliberately rather than have this phase's silence on the topic read as implicit approval to ship a known-broken calculator without comment.
