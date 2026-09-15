# Phase 18 — UI Product Reconciliation & Ship Decision Gate

Analytical/product-decision phase only. No merge, push, reset, rebase, cherry-pick, production change, migration, source-approval change, or feature-flag system was created. The only repository change in this phase is this document.

## 1. Objective (restated)

Determine, from the actual files and actual running behavior of both frontends (not commit messages), what should survive the eventual reconciliation between this checkout's local history (Phase 10–17) and `origin/main` (currently deployed at `rodz-taxdeeds.pages.dev`), and give one concrete recommended product direction.

## 2. The Two Frontend Baselines

Both frontends were extracted and inspected directly: this checkout's `public/app.js`/`index.html`/`tx.html`/`styles.css`/`explore.css` at `HEAD` (`6d1ea27`), and the same files fetched fresh from `origin/main` (`f574f7f`). `explore.js` (the list/split/map view-toggle engine) and `config.js` are byte-identical on both branches — neither history touches them.

**LOCAL UI** (this checkout):
- Layout: single-page, mobile-first. `#app` holds the topbar, region tabs (FL/TX), ledger tabs (Auctions/LAFT/Certificates), a summary-strip of status chips, quick controls (search + county quick-select), a filter-dropdown panel (Property Type / County multi-select, with the county map embedded as a collapsible sub-panel inside the County dropdown), and the ledger content itself.
- Navigation: tab-based (ledger tabs switch content in place); the county map is reached by opening the County filter dropdown and tapping a "🗺 Map" mini-button inside it.
- Responsive behavior: `explore.js`'s list/split/map view-toggle (`#viewToggle`) already adapts columns by width; "Split" is CSS-hidden below 900px. No dedicated desktop-only chrome beyond that.
- Ledger/table presentation: card-based (`.prop-card`/`.cert-card`), grouped by county+date into collapsible `<details class="county-group">` groups.
- Filters/search: instant text search, county quick-select, multi-select Property Type/County/Lien-level chips, bid-amount range, sort dropdown with a tiebreaker.
- Map: an inline SVG choropleth of FL counties, embedded inside the County filter dropdown, two-tap interaction (tap to zoom+name, tap again to filter).
- Property detail: full-screen modal (`#detailModal`) reusing `detailHtml(p)`; on the LAFT/County-Held-Liens/Auction link row, the auction/LAFT/lien link previously sat as one tile among equals with Street View/Zillow/Tax Collector.
- Dashboard: none — there is no portfolio-level summary view.
- Mobile behavior: this is the native, only mode. No degraded phone experience — it *is* the phone experience.
- Desktop behavior: the same single-column-to-multi-column card layout, just wider; no distinct desktop-only feature set.
- Authentication: unchanged since the merge base — `sb.auth.signUp/signInWithPassword/signOut/onAuthStateChange`, `checkApprovalAndEnter()` gating on `profiles.approved`.
- Loading/error states: skeleton cards (`.skel`) while loading; `showErrorToast()` surfaces write failures (fav/hide/bid-list/notes).
- CSV export: a `cols` array of `[header, accessor]` pairs, including `assessedSourceLabel()` (Phase 14A) as one additional column, `Assessed/Value Field Source`.
- Customer-safe field handling: unchanged, verified in Phase 15 — reads only fields within 005's 48-column customer-safe RPC output.

**ORIGIN UI** (`origin/main`):
- Layout: the exact same topbar/region-tabs/ledger-tabs/summary-strip/quick-controls/filter-dropdown/card-list structure as local, **preserved verbatim and unremoved**, now nested one level deeper inside a new `<section class="page" id="pageAuctions">`. This is additive wrapping, not a replacement — confirmed by a full line-by-line diff of `index.html`, not inferred from the commit message.
- Navigation: adds a desktop `nav-rail` (left sidebar: Dashboard / Auctions / Map / Watchlist, plus a live portfolio-stats mini-panel) and a mobile `nav-bottom` (the same four destinations as a bottom tab bar). Both drive a small client-side page router (`showPage(name)`) that toggles `hidden` on three `<section class="page">` containers: `#pageDashboard`, `#pageAuctions` (the pre-existing ledger UI), `#pageMap` (the county map, promoted from a buried filter-dropdown toggle to its own full destination).
- Responsive behavior: the nav-rail/dashboard/table-view/persistent-detail-panel are explicitly gated to `min-width:1024px`; the bottom nav is gated to `max-width:1023.98px`. Below 1024px, the experience is the identical mobile ledger UI local has, plus the bottom nav and the Map/Dashboard pages now reachable as first-class destinations instead of a buried toggle.
- Ledger/table presentation: the existing card-based list is unchanged and remains the *only* list mode below 1024px. At 1024px+, a new opt-in dense sortable `<table class="data-table">` (toggled via `#tableToggleBtn`) is added alongside it — never replacing the cards, switchable via `[data-listmode="table"]`.
- Filters/search: identical to local — same search box, chips, dropdowns, sort — verified byte-identical except for icon markup (emoji → inline SVG).
- Map: promoted from an inline panel embedded in the County filter dropdown to a dedicated full-page destination (`#pageMap`), reachable from nav-rail/bottom-nav. Loses the "adjust county filters and see the map at the same time" one-panel convenience local had; gains a full-width, unhurried map view and a persistent nav entry point.
- Property detail: same `detailHtml(p)` function, plus (a) the county/clerk auction link is pulled out of the equal-weight reference-link row into its own prominent `.detail-cta` button, and (b) at desktop widths, the detail view is also renderable in a persistent, always-visible `#detailPanel` beside the list/table (in addition to, not instead of, the existing full-screen modal, which remains the only detail view on mobile).
- Dashboard: new. `renderDashboard()` computes stat tiles (Total Properties, Active, Est. Total Value, Counties) and two ranked panels (By County, By Ledger) entirely from the client's already-loaded `ALL[]` array — no new network call, no new field.
- Mobile behavior: identical ledger/filter/search/sort/CSV/detail-modal behavior to local, plus the bottom nav and full-page Map/Dashboard destinations.
- Desktop behavior: everything mobile has, plus the nav-rail, dashboard, opt-in table view, and persistent detail panel.
- Authentication: byte-identical to local (confirmed: same line content for every `sb.auth.*` call and `checkApprovalAndEnter()`, only line numbers shift due to unrelated insertions above).
- Loading/error states: identical (`showErrorToast()`, skeleton cards) — untouched by origin's diff.
- CSV export: identical to local's, **minus** the one `assessedSourceLabel()` column — everything else, in the same order, with the same accessor logic (confirmed Phase 17, re-confirmed here).
- Customer-safe field handling: identical RPC call (`sb.rpc("get_properties", {p_state: PAGE_STATE})`), identical fallback, no new field read anywhere in the diff from the merge base.
- Visual identity: switches the font stack from Inter to IBM Plex Sans/Mono (a deliberate "terminal-style" reskin, per its own commit message), tightens border radii, and replaces every emoji icon with an inline SVG line-icon set (`ICON_PATHS`/`svgIcon()`). The underlying "institutional slate/navy + emerald" color palette and CSS custom-property structure are **unchanged** — this is a typography/iconography change, not a color or design-system rewrite.

## 3. Feature Matrix

| Feature | Local implementation | Origin implementation | Which is stronger | Compatibility risk | Security/data-contract risk | Recommendation |
|---|---|---|---|---|---|---|
| Application shell | Single-page, no chrome beyond the topbar | `.app-shell` grid: nav-rail (desktop) / nav-bottom (mobile) + a 3-page router, wrapping the existing content unchanged | Origin — adds real navigational structure without removing anything | None (git-merges cleanly, confirmed Phase 17) | None | Origin's shell |
| Navigation | Ledger tabs only; Map buried in a filter dropdown | Nav-rail/bottom-nav with Dashboard/Auctions/Map/Watchlist as peers | Origin — Map and a portfolio view become discoverable destinations instead of one buried toggle | Low — this is what broke the old `#mapBtn` Playwright assertion (§6, §12) | None | Origin's navigation model |
| Dashboard | None | New: stat tiles + By-County/By-Ledger panels, computed entirely client-side from `ALL[]` | Origin (net-new capability; nothing to compare against) | None — reads no new field, adds one DOM section | None — no new column, no new RPC | Ship (see §8) |
| Property ledger/table (cards) | Card-based, grouped by county+date | Identical, unmodified, still the only list mode on mobile | Tie — origin preserves local's implementation exactly | None | None | Keep as-is (shared) |
| Desktop table view | Not present | New: dense sortable `<table>`, opt-in via toggle, 1024px+ only | Origin (net-new, additive, doesn't touch the card list) | Low — genuinely new code, needs test coverage (§12) | None — reads the same client-side rows the cards already render | Ship (see §8) |
| Mobile responsiveness | Native mode; this is the whole app | Preserves local's mobile experience exactly, adds bottom nav + full-page Map/Dashboard | Origin — strictly additive on mobile | None | None | Origin's mobile treatment |
| Desktop responsiveness | Same card layout, just wider; no desktop-specific value-add | Nav-rail, dashboard, table view, persistent detail panel, all 1024px+-gated | Origin — meaningfully upgrades the desktop experience, a segment the mobile-first design underserved | Low | None | Origin's desktop layer |
| Search | Instant text search over case #/parcel/owner/county | Identical | Tie | None | None | Keep (shared) |
| Filtering | Multi-select Property Type/County/Lien chips, bid range | Identical | Tie | None | None | Keep (shared) |
| Sorting | Sort dropdown + tiebreaker | Identical | Tie | None | None | Keep (shared) |
| Map | Inline panel inside the County filter dropdown, two-tap zoom/filter interaction preserved | Same interaction logic, promoted to a dedicated full-page destination | Origin, with one real tradeoff: filtering counties and viewing the map side-by-side is no longer possible in one screen | Low | None | Origin's placement, see §6 for the tradeoff called out explicitly |
| Property detail | Full-screen modal only | Same modal (mobile), plus an always-visible desktop `#detailPanel`; auction/LAFT link promoted to its own CTA button | Origin — additive, no functional change to the modal itself | None | None | Origin's addition, keep the modal as the mobile/only-option fallback |
| Status indicators | Status pills, countdown badges, homestead/lien pills | Identical (unmodified in the diff) | Tie | None | None | Keep (shared) |
| Auction information | Opening bid, county just value, fees, equity spread | Identical | Tie | None | None | Keep (shared) |
| Valuation display | `County Assessed Value` label, generic across states | Identical label and value | Tie (both branches inherited this from the base — Phase 14A's improvement is local-only, see next row) | None | None | Keep (shared) |
| Source display | `harvester_source` shown via card/detail text | Identical | Tie | None | None | Keep (shared) |
| Assessed-source labeling | `assessedSourceLabel()` — per-row honest label for TX value provenance (CAD vs. adjudged value), plus a matching CSV column | Not present | **Local** | None — pure function, no DOM dependency | None — reads `harvester_source`, already in the 48-field contract | Port to origin (see §7) |
| CSV export | 48-columns-worth of fields plus `assessedSourceLabel()`'s column | Identical minus that one column | Local, by exactly one column | None | None — both are within contract | Merge: origin + the one ported column (see §7) |
| Authentication | Sign-up/approval-gate flow, unchanged since merge base | Byte-identical | Tie | None | None | Keep (shared, no change needed) |
| Customer-safe field handling | Verified (Phase 15) to read only the 48-field contract | Identical RPC/fallback, subset CSV field list — verified here directly against origin's actual `app.js` | Tie | None | None — both compliant | No action needed |
| Error handling | `showErrorToast()` on every write action | Identical | Tie | None | None | Keep (shared) |
| Loading states | Skeleton cards | Identical | Tie | None | None | Keep (shared) |
| Empty states | Per-ledger empty-state copy (Phase 14A corrected the Texas ones) | Same structure; inherits local's Phase 14A copy fix automatically once merged (origin never touched these strings, so it still has the older, now-corrected-in-local wording) | Local (has the corrected copy) | None | None | Port via merge (already resolved by §7's ported change, since it's the same file region) |
| Pagination | None — all rows loaded client-side | None — identical | Tie (neither implements it; a pre-existing, unaffected limitation) | N/A | N/A | Out of scope for this reconciliation |
| Routing | Tab-switch only, no page concept | Client-side page router (`showPage()`) across 3 sections, no URL/history integration (no deep-linking, no back-button support) | Origin, with a real gap: no browser history integration | Low-medium — acceptable for a first cut, worth a follow-up item, not a blocker | None | Ship as-is; note the missing deep-link/back-button support as a known limitation (§8) |
| Responsive breakpoints | 900px (list/split toggle only) | 900px (unchanged) + 1024px (new shell breakpoint) + 1280px (wider detail-panel column) | Origin — more deliberate breakpoint design | None | None | Origin's breakpoints |
| Accessibility | Emoji icons (no semantic markup beyond default), `aria-label` on a few landmark elements | SVG icons consistently marked `aria-hidden="true"` (correctly treated as decorative, since every icon has adjacent text), `aria-label="Main"` on both new nav elements | Origin — modest, real improvement | None | None | Origin's icon/aria treatment |
| Visual consistency | Inter font, "institutional slate/navy + emerald" palette | IBM Plex Sans/Mono font, same color palette and CSS custom-property structure, tighter radii | Neither objectively — a genuine identity/taste decision, not a technical improvement | None (both are internally consistent) | None | Human decision (§13/§14) |
| Performance | All client-side; no new heavy dependency | Same — dashboard/table view compute from the already-loaded `ALL[]`, no new fetch, no new library | Tie | None | None | No action needed |
| Existing Playwright coverage | Full suite passes except 2 known cosmetic mismatches | One assertion (`#mapBtn`) fails because that element was deliberately removed; ~50 preceding assertions (property load, filters, sort, gone-status, theme, type chips) ran without error | Local (suite matches its DOM) | Medium — the suite needs a real update before it can gate a merged/shipped build (§12) | None — this is test-suite staleness, not a runtime defect | Update the suite as part of reconciliation, not before |

## 4. Product Center of Gravity

The application is, by every implemented feature on both branches, **(A) a property-sale intelligence ledger with (C) a light analytics layer added on top** — not a dashboard/analytics application in its own right. The evidence: the overwhelming majority of the codebase (harvesters, governance, provenance, the 48-field customer contract, the entire card-list/filter/sort/search/CSV/detail-modal system) exists to get individual property listings — with their auction mechanics, valuation, title risk, and source provenance — in front of a bidder who needs to act on one property at a time. Origin's dashboard is real but thin by design (four stat tiles and two ranked panels, all derived from data the ledger already loaded, with an explicit comment ruling out fabricated trend lines) — it is a summary view *of* the ledger, not a parallel product.

- **Which UI better supports the core product?** Neither alone — local has zero portfolio-level view; origin has the identical, fully-preserved ledger *plus* a summary view and a denser desktop option. Origin strictly dominates for this determination, because it does not trade away any of the ledger functionality to add the dashboard.
- **Which UI should be the default shell?** Origin's app-shell (nav-rail/bottom-nav + page router), because it's additive to the same underlying ledger and improves discoverability of the Map (previously a buried toggle) without cost.
- **Which capabilities from the other side should survive?** From local: `assessedSourceLabel()` and its CSV column (§7) — a genuine data-honesty fix with no origin equivalent. From origin: everything (dashboard, table view, detail panel, nav shell, icon/typography reskin) — nothing here duplicates or degrades an existing local capability.
- **Which capabilities should NOT survive?** None identified as harmful. The one real tradeoff — losing the single-screen "adjust county filter + watch the map" interaction when Map became a full page — is a UX regression worth naming (§6), not a capability to discard; it's a candidate for a future improvement (e.g., a map preview inline in the filter dropdown that deep-links to the full page), not a reason to revert the page-based Map.

This determination is based on actually reading what each branch implements, not on which commit is newer — origin happens to be newer, but the recommendation above would be identical if the timestamps were reversed, because it rests on origin's changes being strictly additive to local's ledger, not competitive with it.

## 5. Mobile-First Ledger Analysis (local)

**What it does better than origin:** nothing structurally — origin preserves it byte-for-byte in the diff from the merge base except icon markup. The one thing local has that origin lacks is `assessedSourceLabel()` (§7), which is orthogonal to the mobile-first design itself.

**What it does worse:** no portfolio summary, no dense-view option for a user managing dozens of active properties on a desktop monitor, and the Map is one extra tap deeper (open County dropdown, then tap the map mini-button) than it needs to be given how central geography is to this product.

**Is it still useful on desktop?** Yes — its card-based list is the *only* list mode on mobile and remains available at every width on origin's branch too (the table view is opt-in, not a replacement). Its information density (address, parcel, 2-box headline stat grid, status/lien pills) is appropriate for a "browse and decide" task; the new table view serves a different task (scan/sort many rows at once) without displacing it.

**Should its navigation model (ledger tabs) survive?** Yes, unchanged — it's what both branches use inside `#pageAuctions`.

**Should its ledger/table interaction model (cards, expand/collapse county groups, two-tap map) survive?** Yes, unchanged — origin never touches this logic.

Recommendation per major component:
- Card-based property list: **KEEP** (unmodified on both branches already).
- Ledger tabs (Auctions/LAFT/Certificates): **KEEP** (unmodified).
- County map's two-tap zoom/filter interaction: **KEEP** the interaction logic; **MODIFY** only its placement (see §6 — this is already what origin did).
- Single-page-only navigation (no nav-rail/bottom-nav/dashboard): **REPLACE** with origin's shell, since it adds structure without removing anything local has.

## 6. Origin Desktop App-Shell Analysis

**What it adds:** a nav-rail (desktop) / bottom-nav (mobile) page router across three destinations (Dashboard, Auctions, Map), plus, at 1024px+, an opt-in dense table view and a persistent detail panel beside the list.

**Are those additions actually useful?** Yes, on the evidence of what each does: the dashboard answers "how is my whole portfolio doing" in one glance, which nothing in local answers at all; the table view answers "let me scan/sort 50 rows at once," a real desktop-only task the card list is not well-suited to; the persistent detail panel removes the friction of a full-screen modal stealing the list from view while cross-referencing rows, a genuinely desktop-shaped convenience.

**Do they overlap with existing ledger functionality?** No — confirmed by reading the code, not assumed: the dashboard reads `ALL[]` read-only and writes to its own DOM nodes; the table view and detail panel are alternate renderings of the same rows the card list already computes (`renderShellExtras(shown, activeLedger)` receives exactly the `shown` array `render()` just drew), never a second source of truth.

**Does routing introduce regression risk?** Some, but bounded: `showPage()` is a simple `hidden`-toggle router with no URL/history integration — there is no deep link to `#pageMap` or `#pageDashboard`, and the browser back button does not move between pages. This is a real, worth-naming limitation, not a blocker; nothing depends on deep-linking today (no shared "map view" links exist anywhere in the product), so it is a future-improvement item, not a regression against anything currently shipped.

**Should dashboard/table-view be part of the default product, feature-gated, or removed?** Part of the default — see §8's per-feature classification.

**The `#mapBtn` Playwright difference — is it architectural, test-only, a regression, or a combination?** **A combination, weighted almost entirely toward intentional architectural improvement, with a real (and currently uncovered) side effect.** The `#mapBtn` mini-button inside the County filter dropdown was deliberately removed — origin's `index.html` diff shows the entire `<div class="map-wrap" id="mapWrap">...</div>` block (including that button) deleted from inside the County-filter markup and re-created, unchanged in its internal structure, as the content of the new `#pageMap` section. This is not decay or an accidental DOM rename; it's a considered relocation, confirmed by the surrounding CSS (§2/§3) being purpose-built for a full-page map layout. The side effect — losing the "watch the map while adjusting county filters in the same screen" interaction — is real and is the one thing local's placement did better (§5); it is not, however, a defect in origin's map itself, which is functionally identical (verified: `zoomToCounty()`/`zoomToState()` and the two-tap interaction are untouched code). The test failure is squarely `tests/run_test.mjs` being written against a DOM structure origin deliberately changed — **TEST_OBSOLETE**, not a product defect (see §12's formal classification).

## 7. `assessedSourceLabel()` Decision

- **Where it exists:** local only (`public/app.js`, Phase 14A, ~line 693–718 in this checkout). Origin has no equivalent.
- **What user problem it solves:** the existing "County Assessed Value" label implies a Florida-style statutory appraisal figure. For Texas rows, the underlying number is never that — it's either LGBS's raw CAD-listed value or RealAuction's court-set adjudged value, neither of which is a county assessor's appraisal. Without this function, every Texas row with no `market` value (all of them, since `market` is Florida-enrichment-only) displayed a label that overclaimed what the figure actually was.
- **Does it change the 48-field customer contract?** No. It reads `p.harvester_source` and `p.market`/`regionOf(p)`, all already inside the 48-column customer-safe RPC output; it introduces no new column, no new RPC, no new grant.
- **Does it change CSV semantics?** It adds one column (`Assessed/Value Field Source`) without renaming or removing the existing `County Assessed Value` column, so a consumer reading by header name sees only an addition; a consumer reading by fixed column position would see everything shift by one position after that column.
- **Is it merely presentation metadata?** Functionally yes — it is a derived label, not a stored fact, and does not change any value the app already displays elsewhere.
- **Would removing it reduce clarity?** Yes, measurably: without it, Texas users see a demonstrably false implication (a Florida statutory concept applied to a Texas court-sale or CAD figure) that Phase 14A's own audit documented as a real correctness problem, not a cosmetic one.
- **Would keeping it create unnecessary contract complexity?** No — it adds one presentation-layer function and one CSV column, with no schema, RPC, or grant surface at all.

**Recommendation: KEEP.** This is a real correctness fix with zero cost to the security boundary or the 48-field contract, and no equivalent exists on origin to conflict with it. It should be ported into the merged frontend exactly as local implements it (confirmed mechanically compatible with origin's file via Phase 17's `git merge-tree` result, which combined both without conflict). No reframing is needed — the label wording already states the real source system by name rather than a borrowed Florida term, which is the entire point of the fix.

## 8. Dashboard / Table-View Decision

| Feature | User value | Implementation maturity | Backend dependency | Unavailable-field dependency | Security implications | Mobile implications | Desktop implications | Test coverage | Classification |
|---|---|---|---|---|---|---|---|---|---|
| Dashboard (stat tiles + By County/By Ledger panels) | Real — answers a "how's my portfolio" question nothing else in the product answers | Mature for its scope: explicitly declines to fabricate a trend figure it can't compute honestly (no historical snapshots exist) | None — reads only `ALL[]`, already-fetched client-side rows | None | None — no new column/RPC | Full — reachable via bottom nav, renders at any width | Enhanced layout at 1024px+ (wider grid) | None yet (new surface; the existing suite never reaches `#pageDashboard`) | **SHIP** |
| Desktop table view | Real — a genuine desktop-scan/sort task the card list doesn't serve well | Functional; reuses `cardStatus()`/`bidDisplay()`/`FAVS`/watchlist logic already proven correct by the card list | None — renders the identical `shown` rows the card list computes | None | None | Hidden below 1024px by design (`.data-table-wrap{display:none}` unconditionally, then shown only via `[data-listmode="table"]` inside the 1024px+ media query) — no mobile exposure at all | Opt-in via toggle, does not replace the card list | None yet | **SHIP** (already correctly desktop-gated; no additional gating needed) |
| Persistent detail panel | Real — removes the modal-stealing-focus friction on a desktop monitor with room to spare | Functional; reuses `detailHtml()` and the same `[data-action]` delegation the modal already uses, so fav/hide/bid-list/notes work identically inside it | None | None | None | Hidden below 1024px (`display:none` outside the same media query); mobile keeps the existing full-screen modal exclusively | 1024px+ only | None yet | **SHIP** |
| Nav-rail / bottom-nav page router | Real — makes Map and (new) Dashboard first-class destinations | Functional but missing URL/history integration (§6) | None | None | None | Bottom-nav present at all widths below 1024px | Nav-rail present at 1024px+ | Partially exercised (the suite reaches several `#pageAuctions`-internal assertions; `#pageDashboard`/`#pageMap` navigation itself is untested) | **SHIP**, with the missing deep-link/back-button support logged as a **DEFER**red follow-up item, not a blocker |

No feature here should be REMOVEd — none introduces a security, contract, or mobile-experience cost, and all four are already correctly scoped (three of the four are hard-gated to desktop widths by CSS that predates this phase, not something this phase needs to add). No feature needs SHIP BEHIND FEATURE FLAG: this codebase has no feature-flag system today (confirmed — no gating mechanism beyond CSS breakpoints and the existing `is_admin`/`approved` account flags exists anywhere in the codebase), and per this phase's explicit restriction, one must not be invented here. If a human decides gating is wanted later (e.g., to A/B the dashboard), the natural boundary to gate on is the existing `profiles` row (the same table `is_admin`/`approved` already live on) — documented as a recommendation, not implemented.

## 9. Security Boundary Verification

Reconfirmed directly against origin's actual `app.js` content (not assumed from Phase 17's summary):

- Internal fields are not rendered to customers on either branch — `ledger_type` and `fdor_enriched_at` appear in origin's `app.js` only inside comments referencing migration filenames, never as a `p.<field>` read.
- Internal fields do not appear in either branch's customer CSV — origin's CSV `cols` array reads a strict subset of local's, both fully within the 48-field contract.
- Authenticated users receive the identical customer-safe contract on both branches — both call the identical `get_properties()` RPC with the identical argument.
- `get_properties()` remains the customer RPC on both branches — no new RPC name, no direct-table query introduced by either branch's diff from the merge base.
- Raw REST (`sb.from("properties").select("*")`) exists identically on both branches only as the pre-existing, unmodified "RPC not found" fallback (predates the divergence entirely) — not the intended customer data surface on either branch, and not a new risk introduced by this reconciliation.
- `ledger_type`'s documented `SECURITY INVOKER`/column-grant exception (005a) remains understood and is not touched by anything in either frontend's diff.
- `fdor_enriched_at` remains excluded from both.
- `outcome` remains excluded from both (confirmed absent from both `005`'s output and both branches' CSV/detail code).
- `sold_price` remains excluded from both (same confirmation).
- 48-field contract terminology remains correct throughout this document and the underlying code comments on both branches (no "47-field" language reintroduced anywhere).

**No BLOCKED condition found on either branch.**

## 10. Frontend Data Contract Compatibility

Every field either frontend reads was checked against 005's live 48-column customer-safe output:

- **Local:** already fully reconciled and tested in Phase 15 (`test_phase15_customer_surface_security_audit.py`, Group B) — every direct `p.<field>` read in the CSV `cols` array is a column 005 returns; `ledger_type`/`fdor_enriched_at` never appear.
- **Origin:** its CSV field set is a strict subset of local's (§2, §3), so it is automatically covered by the same reconciliation — no field origin reads falls outside what local's test already verified.
- **`select("*")`:** present only in the shared, unmodified RPC-fallback function on both branches (§9) — not a violation, since it is bounded by 005a's grants regardless of which branch triggers it, and is not new to this reconciliation.
- **Raw REST reads / unapproved RPCs:** none found on either branch beyond the documented, unmodified fallback and the pre-existing `profiles`/`notes`/`favorites`/`hidden`/`county_calendar`/`bid_list` table reads that predate the divergence and are identical on both branches.
- **Hidden internal fields:** none found.
- **Accidental CSV additions:** none — origin's CSV is a subset, not a superset, of local's; the one field local adds (`assessedSourceLabel()`'s derived label) is derived from an already-contract-safe column.
- **47-vs-48 assumption:** neither branch's code or comments assume 47 fields; the correction Phase 15 made stands unchallenged by anything in origin's diff.

**No BLOCKER found in either implementation.**

## 11. Root/Public Mirror Safety

Re-confirmed for this phase (values match Phase 17's, since `origin/main` has not moved): root and `public/` copies of every deployed-bundle file (`app.js`, `explore.css`, `index.html`, `styles.css`, `tx.html`, plus `_headers`, `explore.js`, `fl-cities.json`, `fl-zips.json`, `manifest.webmanifest`, `sw.js`, `tx-counties.svg`, and `icons/`) are byte-identical on `origin/main`, on this checkout, and in the hypothetical merged tree Phase 17 computed. The eventual reconciliation must preserve this invariant for exactly this file list — the same `FILES` list `.github/workflows/sync-public-to-root.yml` already enforces in CI, and the same list `tests/python/test_phase16_deployment_mirror_sync.py` guards locally. Nothing in this phase's analysis requires touching the mirror mechanism itself.

## 12. Playwright Analysis

Both frontends were built into the exact throwaway serve directory `.github/workflows/playwright-test.yml` constructs (public/ + `tests/vendor` stub + `tests/config.js` + `fl-counties.svg` + an injected importmap pointing `@supabase/supabase-js` at the local stub) and run against `tests/run_test.mjs` unmodified.

- **Local build:** `FAIL: regression test found 2 problem(s)` — `ledgerTitles` (branding string mismatch: `"FL Tax Deed Watchlist"` vs. the app's current `"Tax Acquisitions — Florida"` title) and `csvDownloadFilename` (expects `taxdeed-auction-...` vs. actual `taxdeed-fl-auction-...`). Both are the same two pre-existing, known cosmetic mismatches documented since Phase 15/16 — classification: **TEST_OBSOLETE** (the test's frozen expected strings predate a later, intentional rename; not a runtime defect).
- **Origin build:** the suite runs cleanly through roughly 50 assertions — page load and visibility, filter-dropdown/county-group collapsed-by-default state, expand-all, county banner pills, bid-amount filtering, sort-by-bid-descending and the interest/expiring-soon sort options, the "gone" status chip, favorite heart-icon toggling, account panel/theme toggle, property-type filter chips (none/all) — before throwing on `page.click('#mapBtn')` (a 30-second timeout, since the element no longer exists). Classification: **TEST_OBSOLETE**, per §6's finding that this is a deliberate, considered relocation of the map to its own page, not decay or an accidental rename. It is not **REAL_REGRESSION** (the map itself works identically — same zoom/filter logic, just reached differently) and not **NEW_DEFECT** (nothing crashes; the test's own assumption about *where* the map lives is simply out of date). No classification of **UNKNOWN** was needed — the cause was fully determined by reading the actual `index.html` diff (§2), not guessed at.

No test was rewritten in this phase. The exact test that should eventually be updated during reconciliation is `tests/run_test.mjs`'s map section (currently `#mapBtn` at line 200, followed by the `#mapWrap`/`#mapHost`/`#mapZoomBanner` assertions through roughly line 230) — it needs to navigate to `#pageMap` via the nav-rail/bottom-nav router first, rather than opening the County filter dropdown and clicking a now-nonexistent mini-button. The suite's remaining ~800+ lines (LAFT/Certificate tabs, search, CSV export, notes, bid-list, admin approvals, account settings, password change) were not exercised against origin's build in this run because the suite halts on its first uncaught exception; nothing in the structural diff (§2, §3) suggests any of them would fail for a reason other than the same `#pageAuctions`-wrapping change, but this is noted as unverified rather than assumed clean.

## 13. Product Recommendation

**A. LOCAL UI AS DEFAULT + selectively port origin features** — rejected. This would mean shipping without the dashboard, table view, detail panel, and nav-rail/bottom-nav, all of which are real, additive, non-conflicting improvements (§3, §8).

**B. ORIGIN UI AS DEFAULT + selectively port local features** — **this is the recommendation.** Origin's app-shell should become the default, with exactly one local feature ported into it: `assessedSourceLabel()` and its CSV column (§7). Everything else origin has is additive and should ship as-is; everything else local has is already preserved unchanged inside origin's `#pageAuctions`.

**C. HYBRID RECONCILIATION** — this is, in substance, what option B already describes (origin's shell plus one ported local function) rather than a distinct third option; naming it separately would only obscure that the actual reconciliation work is a single, small, well-scoped port, not a broader hybrid design exercise.

**D. DEFER PRODUCT DECISION** — rejected. The evidence in this document (a conflict-free `git merge-tree` result from Phase 17, a fully additive relationship between the two branches' feature sets, and exactly one small, well-understood function to port) does not support deferring; deferring would only delay shipping origin's already-built, already-live improvements without changing what the eventual decision will be.

**Proposed target architecture:**

```
SHELL:            origin's .app-shell (nav-rail desktop / nav-bottom mobile / 3-page router)
NAVIGATION:       origin's nav-rail + nav-bottom, Dashboard/Auctions/Map/Watchlist
DASHBOARD:        origin's renderDashboard() (stat tiles + By County/By Ledger panels), unmodified
LEDGER:           local's card-based ledger/filter/search/sort system (byte-identical on both
                   branches already), unmodified, living inside origin's #pageAuctions
MAP:              origin's #pageMap placement (full-page destination) with local's unmodified
                   zoomToCounty()/zoomToState() two-tap interaction logic
PROPERTY DETAIL:  local's detailHtml()/full-screen modal (the only detail view on mobile) +
                   origin's persistent #detailPanel (desktop-only) + origin's promoted
                   auction/LAFT .detail-cta button, with local's assessedSourceLabel() ported
                   into the value-label call site
FILTERS:          shared, unmodified on both branches
MOBILE:           origin's nav-bottom + local's unmodified card list/filters/modal (identical
                   to what mobile users have today on either branch)
DESKTOP:          origin's nav-rail + dashboard + opt-in table view + persistent detail panel,
                   layered on the same ledger
CSV:              origin's export logic + the one ported assessedSourceLabel() column (local's
                   CSV, effectively)
AUTH:             unchanged (identical on both branches already)
ROUTING:          origin's showPage() page router, with the missing URL/history (deep-link,
                   back-button) integration logged as a follow-up item, not a blocker
```

## 14. Human Decision Register

| # | Decision | Claude recommendation | Options | Impact | Human approval required? |
|---|---|---|---|---|---|
| 1 | Default UI direction | Origin's app-shell as default, with `assessedSourceLabel()` ported in (Option B, §13) | A / B / C / D (§13) | Determines what every user sees on next deploy | **Yes** |
| 2 | `assessedSourceLabel()` | KEEP, port unchanged into the merged frontend (§7) | KEEP / REMOVE / KEEP BUT REFRAME | One extra CSV column; corrects a real Texas-labeling inaccuracy | **Yes** (small, but changes the shipped CSV contract by one column) |
| 3 | Dashboard / table-view / detail-panel | SHIP all three as origin already built them (§8) | SHIP / SHIP BEHIND FLAG / DEFER / REMOVE (no flag system exists — would need to be built if chosen) | New always-on desktop capability; net-new mobile bottom-nav entries (Dashboard) | **Yes** (a visible product surface, even though technically low-risk) |
| 4 | Map: router page vs. inline filter-dropdown panel | Keep origin's full-page placement; note the lost "filter + view map together" convenience as a future improvement, not a revert (§6) | Keep origin's placement / Revert to local's inline placement / Build both (inline preview + full page) | Affects one specific workflow (adjusting county filters while watching the map) | **Yes** (a genuine, named UX tradeoff, not a technical call) |
| 5 | Mobile-first behavior | Keep local's mobile experience exactly as-is (already what both branches converge on) | N/A — both branches already agree | None — no change either way | No (already settled by both branches independently) |
| 6 | Desktop shell adoption | Adopt origin's nav-rail/dashboard/table/detail-panel for desktop widths (§8) | Adopt / Adopt partially (e.g., dashboard only) / Reject entirely | Meaningfully changes the desktop experience only; zero effect on mobile | **Yes** |
| 7 | Router URL/history integration (deep links, back button) | DEFER — ship the router as-is now, track the gap as follow-up work | Ship as-is now / Block the merge on adding it first | No current feature depends on deep-linking; adding it is a self-contained future improvement | **Yes** (to confirm deferring is acceptable, not to design the fix now) |

## 15. Merge Readiness

**READY_WITH_PRODUCT_DECISIONS.** Technical merge blockers remain absent, exactly as Phase 17 found (re-confirmed here at the feature/behavior level, not just the file/git level): no security-boundary violation, no data-contract violation, no mirror-invariant violation, and no unmergeable file conflict on either branch. What remains is the human decision register in §14 — none of which is a technical blocker, all of which are product/UX calls this phase is explicitly scoped not to make unilaterally in code.

## 16. Tests

- `pytest tests/python/ -q`: **173 passed**, 0 failed. Unchanged from Phase 17; no test was added, modified, or weakened this phase.
- Playwright suite (`tests/run_test.mjs`, unmodified) run against this checkout's build: same 2 pre-existing cosmetic mismatches as Phases 15–17 (`ledgerTitles`, `csvDownloadFilename`) — no new failures.
- Playwright suite run against a freshly-built copy of `origin/main`'s actual frontend: progressed through roughly 50 real assertions before failing on `page.click('#mapBtn')` — classified **TEST_OBSOLETE** (§12), the exact same finding as Phase 17, independently reconfirmed in this session rather than assumed carried-forward.
- No coverage was reduced. No test was rewritten to force a pass.

## 17. Implementation Restrictions — compliance confirmation

No merge, push, reset, rebase, or cherry-pick was performed. No production, Supabase, or migration change was made. No source approval state or vendor activation status was changed. The 48-field contract was not altered. No security control was weakened. No feature-flag system was invented — §8 explicitly declines to invent one and instead names the existing `profiles` table as the natural future gating boundary, without implementing anything against it. No irreversible product decision was made in code — every recommendation above is documentation, pending the human decisions in §14.

## 18. Commit

This document is the only repository change in Phase 18. No test file was added — the existing suite already provides everything this phase needed to classify origin's one real DOM difference (§12), so no "tiny regression guard" was necessary.

---

PHASE 18 RESULT

STATUS: READY_WITH_PRODUCT_DECISIONS
DEPLOYMENT: NOT_SYNCHRONIZED (unchanged — origin/main remains what's live; this phase made no deployment action)
LOCAL HEAD: 6d1ea27be142668548c3fdf17560b1b09adac380
ORIGIN/MAIN: f574f7fbf21d60ac4561bd1ae17bd23c9b822f4a
MERGE BASE: cc7f13959aa651b53e4ed860a1915be8b96a693c

DEFAULT UI RECOMMENDATION: ORIGIN (Option B: origin as default, port one local feature in — see §13)

SHELL: Origin's app-shell (nav-rail desktop / nav-bottom mobile / 3-page router)
LEDGER: Local's card-based ledger (already byte-identical on both branches — no change needed)
DASHBOARD: Ship origin's dashboard as built (§8)
MAP: Origin's full-page placement; note the lost inline filter+map convenience as a named future improvement, not a defect (§6, §14 item 4)
PROPERTY DETAIL: Local's modal (mobile) + origin's persistent detail panel (desktop) + local's assessedSourceLabel() ported into the value label
MOBILE: Unchanged — both branches already converge on the identical mobile experience
DESKTOP: Adopt origin's nav-rail/dashboard/table-view/detail-panel layer
ROUTING: Ship origin's page router as-is; defer URL/history integration as follow-up work (§14 item 7)
CSV: Origin's export + the one ported assessedSourceLabel() column
ASSESSED SOURCE LABEL: KEEP, port unchanged (§7)

SECURITY: PRESERVED on both branches — no BLOCKED condition found (§9)
48-FIELD CONTRACT: PRESERVED on both branches (§10)
MIRROR: INTACT on both branches and in the Phase-17-computed merged tree (§11)
DATABASE COMPATIBILITY: COMPATIBLE — both branches call the identical, unmodified get_properties() RPC (§9, §10)

PLAYWRIGHT: local build 2/2 known pre-existing cosmetic mismatches, no new failures; origin build reaches ~50 assertions then hits one TEST_OBSOLETE failure (#mapBtn, deliberately relocated to #pageMap) — classified, not treated as a defect (§12)
PYTEST: 173/173

TECHNICAL BLOCKERS: NONE
PRODUCT DECISIONS: 7 items in the human decision register (§14) — default UI direction, assessedSourceLabel(), dashboard/table-view/detail-panel shipping, map placement tradeoff, mobile behavior (already settled), desktop shell adoption, router URL/history integration timing

RECOMMENDED NEXT PHASE: Once the human decisions in §14 are made (expected: approve Option B as recommended), the next phase should be the actual reconciliation execution — performed by a human with real push credentials per Phase 17's deployment plan (§14 there), including the tests/run_test.mjs update this phase identified (§12) as a precondition for trusting the suite against the merged/shipped result. No further automated analysis phase is needed before that human action.

COMMIT: (this phase's commit — see below)
PUSHED: NO

HARD STOP
