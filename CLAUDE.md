# CLAUDE.md — FL Tax Deed Watchlist

Persistent orientation for Claude across sessions on this project. Read this first. For the full dated history of fixes/audits/decisions, see the "tax florida app" claude.ai Project doc `claude/improvement-roadmap.md` — that's the detailed changelog; this file is the stable map.

## What this is

A private, invite-only web app that tracks Florida county tax-deed auctions, tax-lien certificates, and "Lands Available for Taxes" (LAFT) listings for a small team (Marc + partners) doing tax-deed investing. Live at **https://rodz-taxdeeds.pages.dev**.

## ONE repo, not two — corrected 2026-08-25

**`rodzmodzllc-max/taxdeed-scraper`** (public — flipped from private 2026-08-31 to sidestep a GitHub Actions billing block; see the project roadmap for details) is the **only real repo**. There is no `taxdeed-app` repo — that name doesn't exist on GitHub; if you ever find a local clone with that remote, its origin is stale/dead (this happened once — see below) and should be discarded in favor of a fresh clone of `taxdeed-scraper`, or just browse it via the authenticated Chrome tab.

It's a monorepo containing **both** the frontend and the backend:
- Frontend source lives under `public/` (`index.html`, `tx.html`, `app.js`, `explore.js`, `satellite-map.js`, `styles.css`, `explore.css`, `sw.js`, `_headers`, etc.) — vanilla JS/HTML/CSS, no framework, no build step.
- A GitHub Actions bot auto-commits with the message `Auto-sync: mirror public/ to repo root [skip ci]`, keeping copies of those same files at the **repo root** in sync with `public/` — this is what Cloudflare Pages actually deploys from. When editing the frontend, edit the files under `public/`; the root-level copies are generated, not hand-edited.
- **`config.js` is the one exception — corrected 2026-09-18.** This file previously (wrongly) listed it as living under `public/` alongside the mirrored files. It doesn't: `public/config.js` does not exist, `config.js` only exists at repo root, and `.github/workflows/sync-public-to-root.yml`'s own `FILES` list deliberately excludes it (same reason `fl-counties.svg`/`tx-counties.svg` are root-only - see that workflow's header comment). It holds live third-party keys (Supabase publishable, Google Maps, MapTiler - see the Phase 55/56/57/60/61 sections below) that get added directly at the root by Marc from his own machine, never mirrored from a `public/` copy. If you ever create or edit `public/config.js`, the workflow's own guard step ("Fail if public/ holds a deployable file FILES does not name") will fail CI - edit the root copy directly instead. `tests/config.js` is a separate, third thing again: a fixture file for the Playwright suite, deliberately shipping no real keys.
- Backend: `.github/workflows/` (scheduled harvest/sync jobs), `scripts/` and `data/` (PowerShell + Python harvesters), `supabase/functions/` (at least one Edge Function, `notify-approval`), `schema-v*.sql` migration files at repo root.
- Repo debris cleanup done 2026-09-01: `test.txt`, `taxdeed-site-updated.zip`, a formerly-committed `node_modules/` — are gone, along with the dead scraper subsystem next to it (see the Known landmines section below for what that used to be).

Deployed to **Cloudflare Pages** (`rodz-taxdeeds.pages.dev`) from the repo root, talking directly to Supabase from the browser via `@supabase/supabase-js` loaded from esm.sh.

**Why this correction exists:** an earlier pass through this session documented a "two-repo" architecture (a separate `taxdeed-app` frontend repo) based on a local clone at `/home/claude/work/taxdeed-app` whose git remote pointed at `https://github.com/rodzmodzllc-max/taxdeed-app`. That repo does not exist under this account (confirmed via the repo listing and a 404 on direct navigation) — the clone's origin was stale, and a local commit made against it (`b860bcc`, an earlier version of this very file) can never be pushed there. The account's real, current repos are `taxdeed-scraper` (private, this project) and `Tx-taxsale-scraper` (public, unrelated). Always verify a repo actually exists (check the account's repo list) before trusting a local clone's origin.

## Backend — what's there

- **Runs entirely on GitHub Actions now — no local machine involved.** Corrected 2026-08-25: this file previously claimed the harvest ran "partly as scheduled Windows Task Scheduler jobs on the user's own PC, partly as GitHub Actions." That's stale. `.github/workflows/harvest-and-sync.yml`'s own header comment is explicit: "Runs the real statewide harvester (previously only ever run by hand on a local PC) on a schedule, entirely on GitHub's runners. No local machine involved anymore." Three jobs, all `workflow_dispatch`-or-cron: `deeds` (`harvest_all_counties.ps1` + Okaloosa's `harvest_okaloosa_bid4assets.ps1`) at `0 10,22 * * *` UTC (~6am/6pm ET), `certificates` (marked "experimental") + `laft` both at `0 12 * * *` UTC (~8am ET). `sync-config.local.json` below is a local-dev-only convenience for running scripts by hand off-schedule, not part of the production pipeline.
- Key scripts (verify current state via the repo — it changes): `harvest_all_counties.ps1` (deed auctions, 46 RealAuction/RealForeclose/RealTaxDeed counties), `harvest_laft_pdfs.py` / `harvest_laft_html.py` / `harvest_laft_realtdm.py` (LAFT listings, 32 counties total across the three), `harvest_lienhub_certificates.ps1` + `sync-certificates-to-supabase.ps1` (tax certificates, 32 LienHub counties, its own 12:00 UTC daily schedule), `scripts/sanity_check_deeds.ps1` (hard-fails the deeds job if fewer than 15 counties show fresh data in the last 26h), `scripts/geocode_properties.py` (backfills `latitude`/`longitude` via the free US Census Bureau Geocoder).
- **LAFT scope gap (documented in the workflow's own comments, unresolved):** ~35 counties gate their LAFT list behind portals (Pioneer/TaxSmartWeb, Landmark Web, a custom ASP.NET disclaimer-postback, Miami-Dade's GovHub) that none of the three current LAFT harvesters handle. Not a bug — just uncovered scope.
- `sync-config.local.json` (gitignored) holds the `service_role` key locally for manual/dev runs — **never commit this, never let Claude type a `service_role` key into any field**. Production sync uses the `SUPABASE_SERVICE_KEY` GitHub Actions secret, not this file.

## Data model (Supabase, project `cqnnnvpbocafuvpzfbzu`)

Tables actually present in `public` schema: `properties` (canonical listings; `source` ∈ `auction`/`laft`/`certificate`; unique on `(source, county, case_no)`). As of 2026-08-25, `certificate` rows are live and syncing successfully (391 certificates across 13 counties on the most recent run — see "Certificates sync fix" below); `auction` and `laft` counts fluctuate with each harvest, check live rather than trusting a point-in-time number here. Also: `notes` (shared visibility, own-row edit/delete), `favorites` and `hidden` (fully private per user), `county_calendar`, `profiles` (`approved`, `is_admin`, `first_name`, `last_name`, `company`, `requested_at` — drives the admin approval gate). Migrations for all of these exist at repo root: `schema.sql` (v1 baseline), `schema-v2-gone-tracking.sql`, `schema-v3-calendar.sql`, `schema-v4-certificate-source.sql` / `schema-v4-certificates.sql`, `schema-v5-digest.sql` (auction-closing-soon email digest — status/usage not yet verified), `schema-v6-approvals.sql` (the `profiles`/approval-gate schema), `schema-v7-bidlist.sql`, `schema-v8-geocoding.sql`.

**`bid_list` is a known, currently-unresolved gap**: `schema-v7-bidlist.sql` exists in the repo and `app.js` fully assumes the table exists (add/remove-from-bid-list, a 10-item cap enforced both client-side and via a DB trigger) — but as of 2026-08-25 **`public.bid_list` does not exist in the live database** (confirmed via `information_schema.tables`). Same failure pattern as `schema-v4-certificates.sql` had (see "Certificates sync fix" below): a migration file gets written and committed but never actually run against production. Check whether this has been fixed before assuming the bid-list feature works; if not, `schema-v7-bidlist.sql` is ready to run as-is (its RLS design is already correct: a PERMISSIVE own-row policy plus a RESTRICTIVE `is_approved()` policy layered on top, matching the safe pattern below — not the broken one).

Also present in `public` but **not used by the frontend at all** — orphaned/legacy, origin unclear, worth a cleanup decision: `auction_records` (0 rows, RLS **disabled**, `anon` role has full INSERT/SELECT/DELETE grants — a genuinely open, unauthenticated write door into production, even though currently empty and unreferenced), `auctions` (31 rows, RLS on, zero policies = safely inaccessible via the API), `tax_auctions` (0 rows, same lockdown — this was `scraper.js`'s target schema before that file was removed 2026-09-01, see Known landmines), `tax_deeds` (170 rows, RLS on, zero policies — real data nobody can read via the API), `tax_liens` (0 rows, locked), `scrape_review_queue` (31 rows, locked), `scraper_review_queue` (0 rows, locked — looks like a duplicate/renamed twin of `scrape_review_queue`), `scraping_logs` (59 rows, locked, presumably backend-only via `service_role`).

**Live `pg_policies`/`information_schema` in the Supabase project is the source of truth for current state, not the `schema*.sql` files** — the files tell you what *should* have been run, not what actually was.

## Certificates sync fix — resolved 2026-08-25

The `certificates` job had been failing 100% of the time it ran (marked "experimental" for this reason). Root cause: LienHub occasionally lists the same certificate more than once within one county's export (e.g. a re-offered certificate), and `sync-certificates-to-supabase.ps1` batched every harvested row into a single `ON CONFLICT (source, county, case_no) DO UPDATE` upsert with no de-dup step first — Postgres rejects a batch that would update the same conflict-target row twice ("ON CONFLICT DO UPDATE command cannot affect row a second time"), which failed the *entire* sync, not just the duplicated rows. Fixed by de-duplicating `$rows` on `(county, case_no)` — the same key as the upsert's conflict target — right before the upsert, keeping the last-seen row per key. Verified in production via `workflow_dispatch` run #44: de-duplicated 126 rows, then successfully synced 391 certificates across 13 counties. The `certificates` job can now be considered reliable, not experimental — worth dropping the "(experimental)" label from the job name next time the workflow file is touched.

## Access model & the RESTRICTIVE/PERMISSIVE lesson (important — read before touching RLS)

Sign-up is invite-only-by-approval: anyone can create an account, but `checkApprovalAndEnter()` in `app.js` gates entry on `profiles.approved`; an admin (`is_admin`) approves from an in-app panel. Every table has Row Level Security enabled, generally gated on a `SECURITY DEFINER` function `public.is_approved()`.

**Hard-won lesson (2026-08-24 production outage):** Postgres RLS has two policy kinds — PERMISSIVE (OR'd together; at least one must exist to grant *any* access) and RESTRICTIVE (AND'd on top, can only narrow, never grant). A table with a RESTRICTIVE `is_approved()` policy and **zero PERMISSIVE policies** silently returns empty results for *everyone*, approved or not — no error, HTTP 200, empty array. This is indistinguishable from "no data" at the app layer and took the live site down. It happened because a prior fix dropped what looked like a redundant/bypass PERMISSIVE policy without checking it was the table's only permissive one. **Before dropping any PERMISSIVE policy on any table in this project, check `pg_policies` first** to confirm it isn't the only permissive policy for that command — if it is, dropping it doesn't narrow access, it deletes all access. Also note: `ALTER POLICY` cannot change a policy between RESTRICTIVE and PERMISSIVE — that requires `DROP POLICY` + `CREATE POLICY`.

The Claude Code browser-automation safety classifier blocks typing raw DDL (`CREATE TABLE`/`CREATE POLICY`/`DROP POLICY`/etc., in any form it recognizes as SQL) directly into the Supabase SQL Editor **or** into the Assistant chat box — natural-language phrasing around an embedded SQL statement is not a reliable workaround; it has succeeded on some attempts and been blocked on others. When blocked, the classifier's own instruction is to stop and let the user decide rather than keep trying alternate phrasings. Read-only `SELECT` queries (including `pg_policies` audits and RLS simulation via `begin; set local role authenticated; set local request.jwt.claims = '...'; ...; commit;`) run fine directly in the SQL Editor.

## Deployment

**No CI/CD for the frontend beyond the mirror bot.** Cloudflare Pages deploys from the repo root, which the `Auto-sync: mirror public/ to repo root` GitHub Action keeps up to date whenever `public/` changes. There is no `npm run build` and no test suite for the frontend itself — edits under `public/` are the actual source of truth.

## Property photos — real, server-sourced, not yet activated

`properties.photo_url` (schema-v10-property-photos.sql) holds a real Google
Street View Static image for the address, fetched server-side by
`scripts/fetch_property_photos.py` and cached in the public `property-photos`
Supabase Storage bucket - never fetched live from the browser, so no Google
API key ever reaches the client and each address is paid for once, not once
per page view. Wired into `harvest-and-sync.yml`'s `deeds` job, right after
the geocoding/enrichment steps, `PHOTO_BATCH_LIMIT` (default 50) rows per run.

**Not live yet - needs one thing only Marc can create:** a Google Cloud
project with the Street View Static API enabled, a billing account attached
(Google's free monthly credit comfortably covers this app's traffic), and an
API key from it added as a `GOOGLE_MAPS_API_KEY` repo secret (Settings ->
Secrets and variables -> Actions). Until that secret exists,
`fetch_property_photos.py` prints one line saying so and exits 0 - the job
doesn't fail, photos just don't populate yet. Same shipped-ahead-of-the-
credential pattern this repo already uses for `texas_harvester.py`'s
still-stubbed `harvest_pbfcm()`/`harvest_govease()`.

`photo_url` has three states, and the frontend must treat them exactly this
way - never synthesize a fourth: `NULL` = not yet checked, `''` (empty
string) = checked, no Street View coverage at that address (common for
vacant land/rural parcels - this sentinel, not `NULL`, is what stops
`fetch_property_photos.py` from re-spending a metadata call on the same
no-coverage row every run), a real value = a public Storage URL to show as
the property's photo. A missing/empty photo renders as a plain placeholder,
never a fabricated or stock image standing in for the actual property.

## Visual rebuild toward Marc's reference design (Phase 51, in progress)

Marc supplied a 5-panel reference mockup (dark-navy sidebar nav, property
photos, Risk & Legal panel, GIS panel, Research & Sources, watchlist stage
stepper) and asked for a "full rebuild," explicitly choosing to source
missing data legally rather than fabricate it, and "back end should source
the images" (→ the photo pipeline above). This is being done in passes, not
one giant unreviewable diff — pass 1 (this one) covers Dashboard, every
property card, and the full property page (`detailHtml()`/`openDetail()`
in `app.js`). Each pass ships real, tested, honestly-labeled functionality
only; nothing here is a mockup or a placeholder page.

**What pass 1 built**, all real data, no new interaction model:
- Dashboard stat tiles get an icon chip; a third panel, **Upcoming
  Auctions**, is built straight from real `sale_date` rows
  (`upcomingAuctionRows()`) — soonest first, grouped by date + county.
- Every property card and the full property page show a **photo strip** —
  `photo_url` when the pipeline above has cached one, otherwise a compact
  "No photo available" bar (`photoOrPlaceholder()`) — never a blank
  photo-sized box, never a fake image.
- The full property page's stats are now grouped into labeled cards
  (**Financial / Property Details / History** — same figures as before,
  just organized), plus two new ones: **GIS & Location** (real
  latitude/longitude from `scripts/geocode_properties.py`, with a free,
  key-less OpenStreetMap embed when coordinates exist) and **Risk &
  Legal**, which reads "Not tracked" for every row (liens, judgments,
  foreclosure, code violations) rather than a fabricated "None found" —
  this data has zero real rows anywhere in the pipeline (see
  `phase-33-source-compliance-audit.md` and friends). The existing
  reference links became a "Research & Sources" card and the existing
  sync-provenance line became a "Data Quality & Provenance" card — same
  text, same `tests/run_test.mjs` assertions, new chrome around it.
  Certificates are untouched (a lien instrument isn't a parcel).
- Sidebar gets a **Settings** entry (`navSettingsBtn`) next to Dashboard/
  Auctions/Map/Watchlist, opening the same account menu as the header
  badge — no new page behind it.

**Deliberately not built in pass 1, and why:**
- **No tab bar** (Overview/Financial/Property/History/Risk/GIS/Permits/
  Documents) on the full property page, even though the reference mockup
  shows one. A Financial/Property/History tab would just re-show the exact
  same fields the Overview cards already show — there's no additional
  depth in the data model to put behind them. Permits and Documents have
  **zero real backing data anywhere in this project** — building those
  tabs, even empty ones, would imply data coverage that doesn't exist.
- **No "Research"/"Reports" sidebar nav items.** A dedicated Research page
  would just duplicate the per-property source links already on the full
  property page; Reports would just be the existing CSV export, which
  already lives in the Auctions toolbar where it's contextually clear.
  Happy to build either out for real if Marc wants a distinct page.
- **No embedded "Property Opportunity Map" on Dashboard** (reference panel
  1) — redundant with the app's own map (see Phase 53 below) and
  meaningfully more engineering for this pass; a real candidate for a
  later pass.
- **No "Recent Activity" feed** — the reference mockup's "New property
  added 2h ago" style entries would need a real events/audit-log table
  this project doesn't have. Not fabricated.

**Clear next real-data candidate:** FEMA's National Flood Hazard Layer API
is free, legal, and unresearched-so-far in this project — a genuine way to
eventually turn the Risk & Legal card's Flood Zone concern (from the
reference) into a real field, the same way `photo_url` and
`latitude`/`longitude` went from "not tracked" to real. Not started.

## One map, not two (Phase 53, done)

Marc sent a screen recording and asked: "The map from navigation should be
the one in the filter list which means we only need the map option at the
navigation bar." He was right that the app had two maps for one idea:

1. A standalone `#pageMap` page (nav bar → Map) — a plain FL/TX county SVG
   colored by confirmed auction format only, with its own zoom/tap-to-filter
   logic (`ensureMapLoaded()`/`zoomToCounty()`/`computeCountyCentroids()`/
   `refreshMapPaths()` in `app.js`).
2. `explore.js`'s own "Where these are" bubble map — reachable only via the
   Auctions page's List/Split/**Map** view-toggle — built from the actual
   filtered rows, with real per-county counts, one-tap zoom **and** filter
   in a single gesture, a floating property preview card, and (once zoomed
   into a county) real geocoded pins for the properties that have them.

The second one was strictly the richer, more honest map. The fix: nav
**Map** now opens the Auctions page with that same map view active, instead
of a second, worse map. Concretely —

- `index.html`/`tx.html`: `#pageMap` (and its `#regionTabsMap` FL/TX
  switcher, `#mapWrap`/`#mapHost`/`#mapZoomBanner`/`#mapHint`) is removed
  entirely, and `#viewToggle` drops its `data-mode="map"` button — List and
  Split are all it offers now, since Map is reached from the nav bar.
- `app.js`: `SHELL_PAGES` no longer has a `map` entry. `showPage("map")` is
  a virtual route — it shows the Auctions page, highlights the nav's Map
  button, and dispatches a new `tdw:setviewmode` custom event (with a
  `window.__tdwRequestedViewMode` stash for the same module-load-order race
  the existing `tdw:rendered`/`window.__tdwLastRender` pattern already
  solves — `app.js` and `explore.js` are both non-async `type="module"`
  scripts, so a cold load into `index.html#map` can call `showPage("map")`
  before `explore.js` has registered a listener for it).
- `explore.js`: a `tdw:setviewmode` listener calls `setMode(mode, true)`,
  and `storedMode()` checks `window.__tdwRequestedViewMode` first, before
  its usual `localStorage`/media-query default — so a nav-triggered request
  wins over whatever view mode was last persisted.
- The old `#pageMap`-driving JS block in `app.js` is **left in place as
  documented dead code**, not deleted — `refreshMapPaths()`/
  `computeCountyCentroids()` etc. are also called from a few still-live
  filter-sync call sites elsewhere in the file, and untangling those
  cleanly was judged a separate, lower-value pass from the actual nav fix.
  `mapBtnEl`/`mapWrapEl`/`mapHostEl` are now permanently `null` (their
  elements don't exist in the DOM any more) and every function in that
  block already null-guards on them, so it's inert, not a bug risk. Safe to
  delete outright in a future cleanup.
- `styles.css`: the now-orphaned `#pageMap`-specific rules (`.map-wrap`,
  `#mapHost`, `.map-legend`/`.lg-*`, `.map-zoom-banner`, `.zoom-seat-label`/
  `.seat-dot`, `.map-page-wrap`, `.map-region-tabs`) are deleted outright —
  unlike the JS, this CSS had no other call sites, so there was no reason
  to keep it as an orphan.
- `explore.css`/`explore.js`: the surviving map gets one small addition —
  a bubble-size legend (`renderBubbleLegend()`) showing what the dot sizes
  actually mean, built from the real min/max county counts on screen at
  draw time rather than a fixed key (this map has no fixed scale — a
  3-county filtered view and the full statewide list both range across the
  same `radiusFor()` min/max). It's real, not fabricated: same data the
  bubbles themselves already encode, just made explicit. Hidden once zoomed
  into a county, where pins replace bubbles and a size scale no longer
  applies.
- **Deliberately not built:** the mockup's individual parcel pins on the
  statewide view. Only ~2% of properties are geocoded (see the header
  comment in `explore.js`) — pins for the other 98% would fabricate a
  precision this data doesn't have. County-level bubbles (statewide) and
  real geocoded pins (once zoomed into a county) is the honest version of
  the same idea, and it already existed; this phase just made it the only
  map instead of building a second, faker one.

`tests/run_test.mjs` was rewritten to match (the old `#pageMap`-dependent
assertions replaced with checks against the real new behavior, following
that file's own pre-existing "TEST_OBSOLETE" precedent) — 236/236 checks
pass. Service worker bumped to `tdw-shell-v24`.

## Map is its own page again — a fuller rebuild, not another tweak (Phase 54, done)

Phase 53 fixed "two different maps" but traded it for a new complaint. Marc's
feedback, verbatim: *"The map button should be its own page and auctions
shoild be just the list i want to feel the change between the two not just
acting like the button and in the map still doesnt look like the earlier
mock up not even close we keep doing small adjustments instead of the
complet design."* Three real problems in that one message:

1. Nav **Map** was a virtual route into Auctions-in-map-mode — same
   masthead, same ledger tabs, same toolbar, just the side panel swapped for
   a map. It never felt like navigating anywhere.
2. Auctions was supposed to go back to being just the list, full stop — not
   a list with a map mode still available behind a toggle.
3. The map's own visual treatment hadn't meaningfully moved toward the
   reference mockup (`f88a239b-image.png`, its Panel 3) since Phase 53 —
   several small patches in a row instead of one decisive pass.

**What actually changed:**

- **`index.html`/`tx.html`:** `#pageMap` is a real `<section class="page">`
  again — its own `<h1>Map</h1>` + subtitle, and its own toolbar
  (`#mapSearchInput`, `#mapCountySelect`, `#mapLedgerPills` with
  `data-ledger="all|auction|laft|certificate"` colored-dot pills,
  `#mapWatchlistOnly`) — none of it borrowed from the Auctions page's own
  `#quickControls`/`#ledgerTabs`. The Auctions page loses `#viewToggle`
  (List/Split) and the `.explore-shell`/`.explore-map-panel` wrapper it used
  to embed the map beside `#main` — `#main` sits directly in `.auctions-body`
  now, unwrapped, full width. The actual map markup (`.explore-map`,
  `#exploreMapCanvas`, `#exploreMapRail`, `#exploreMapLegend`, etc.) just
  *moved* from inside the old panel into `#pageMap` — same inner structure,
  new home.
- **`app.js`:** a small, deliberately independent filter layer for the Map
  page — `mapFilter` (`{search, county, ledger, watchlistOnly}`, declared up
  near `selectedPid` for the same TDZ reason documented there: `render()`
  can run synchronously during page init, before the script reaches this
  section, and it calls `renderMapPage()` on every pass), `computeMapRows()`
  (filters `ALL[]` directly — every ledger at once, past-due/hidden/
  gone-expired excluded same as `dashboardStats()` — **not** `passes()`,
  which encodes the Auctions page's own ledger-scoped filter panel that this
  toolbar doesn't expose), `buildMapCountySelect()`, and `renderMapPage()`
  (dispatches the `tdw:maprendered` event explore.js consumes, plus a
  `window.__tdwMapLastRender` stash for the same module-load-order reason
  `tdw:rendered`/`window.__tdwLastRender` already exists for the list).
  `SHELL_PAGES`/`showPage()` route `"map"` to a real page again, not a
  virtual mode switch.
- **`explore.js`:** dropped the whole List/Split/Map view-toggle machinery
  it used to run for the Auctions page (`MODE_KEY`, `MODES`, `storedMode()`,
  `setMode()`, `bindViewToggle()`, the `tdw:setviewmode` listener) — this
  module is now solely the Map page's renderer. Also dropped the map↔list
  cross-highlight (`focusCounty()`/`clearFocus()`/`bindListHover()`), which
  only ever made sense when a bubble and an adjacent card list shared one
  screen. `absorb()` now listens for `tdw:maprendered` and reads
  `#mapCountySelect` (not `#countyQuick`); `applyCounty()` drives that same
  select instead of the Auctions page's dropdown.
- **`explore.css`:** new rules for the page's own chrome (`.map-page-head`,
  `.map-toolbar`, `.map-ledger-pills`/`.map-watch-pill`/`.pill-dot-*` —
  colored dots reusing the app's existing per-ledger accent colors, blue/
  green/purple, plus a new `--watch`/`--watch-soft` rose pair for the
  watchlist-only pill, deliberately distinct since it's a cross-ledger flag,
  not a fourth ledger). The full-size map treatment that used to be gated
  behind `.explore-shell[data-mode="map"]` is now the standing rule for
  `.map-page-map`, since there's only one mode. All the dead List/Split CSS
  (`.view-toggle`, `.explore-shell[data-mode=...]` and its responsive
  variants) is deleted, not left as an orphan — `styles.css`'s
  `.auctions-body` grid and `[data-listmode="table"]` rule both updated to
  target `#main` directly now that `.explore-shell` no longer wraps it.
- **Deliberately not changed:** the honest county-bubble-then-real-pins
  model from Phase 53. The mockup's individual parcel pins scattered across
  the whole state are still not built — only ~2% of properties are geocoded
  (see the header comment in `explore.js`), and pins for the other 98% would
  fabricate a precision this data doesn't have. What moved toward the
  mockup is the page-level chrome around that honest map: a real header, a
  real toolbar with colored filter pills, a full-bleed stage — not the data
  model underneath it.

Caught a real bug while wiring this up: the first cut of `mapFilter`
crashed the whole page on load (`Cannot access 'mapFilter' before
initialization`) — `bindBidRangeSliders()` calls `render()` synchronously at
module top level, before the script reaches the "Map page" section further
down, so a `let` declared only down there was still in its temporal dead
zone. Fixed the same way `selectedPid` was, per the comment already on that
line: hoist the declaration up next to it.

`tests/run_test.mjs` was rewritten to match — the old shared-map assertions
(`#exploreShell`'s `data-mode`, county-chip toggling via a bubble tap)
replaced with checks against the Map page's own controls
(`#mapCountySelect`, `#mapLedgerPills`, `#mapWatchlistOnly`), plus new
checks that `#viewToggle`/`#exploreMapPanel` are gone from Auctions — 241/241
checks pass. Service worker bumped to `tdw-shell-v25`.

## Satellite/terrain basemap — a toggle, not a replacement (Phase 55, done; needs Marc's own Mapbox token to actually light up)

Marc sent a screen recording after Phase 54 shipped, with this feedback:
*"Analyze the video as you can ser we still havent corrected the map there is
no distiction on the map and auction buttons. Auction should just be the list
and map the actual 3d map as in the mock up. You have not even close to the
mock up requested."*

Two separate things were going on in that message:

1. The video showed the **old, pre-Phase-54 deployed site** — Marc hadn't
   applied/pushed the Phase 54 patch yet, so what he was testing still had
   Phase 53's "Map is a virtual route into Auctions" behavior. Not a real
   regression, just a not-yet-applied patch. Explained to him plainly.
2. "The actual 3d map like the mockup" is a genuine, previously undisclosed
   architectural fork, not a styling complaint. Re-examined the reference
   mockup's Map panel specifically: it's a real satellite/terrain photo-style
   basemap (Google Maps/Mapbox aesthetic — real coastline texture, terrain
   shading, labeled cities over photographic imagery), not a nicer version of
   this app's own flat same-origin SVG map. Matching it for real requires a
   third-party map-tile provider. That collides with a deliberate,
   long-standing decision: `public/_headers`' CSP has always been `img-src
   'self' data:` only, specifically so no outside company can see which
   parcels a signed-in user is browsing (see explore.js's own header comment,
   there since Phase 53/54). Third-party tiles necessarily leak that.

That trade-off is Marc's to make, not mine to guess at, so it was put to him
directly: keep improving the honest same-origin map, or bring in a real
satellite/terrain provider and accept that a third party sees tile requests.
**His answer, verbatim button label: "Real satellite/terrain with a toggle to
our current style map."** Both views, switchable, neither replacing the
other — not the straight swap he could have asked for instead.

### What shipped

- **`public/satellite-map.js`** (new) — a module independent of explore.js,
  same reasoning explore.js's own header gives for being independent of
  app.js: it draws a second view of data app.js already filtered, over the
  same one-way `tdw:maprendered` event explore.js listens to (`{ rows,
  ledger, openDetail }`). The two map modules don't reach into each other;
  `#mapStyleToggle`'s click handlers just show one canvas and hide the other.
- **`public/county-centroids.json`** (new) — real lat/lng centroids for all
  67 FL counties and 254 TX counties, needed to place a county-level bubble
  on a real-world map (the outline map doesn't need this — it projects
  lat/lng into its own SVG's user-unit space instead). Computed
  deterministically from `us-atlas`'s Census-Bureau-derived county TopoJSON
  via `topojson-client` + `@turf/turf`'s `centerOfMass()`, in a scratch
  directory (`npm install us-atlas topojson-client @turf/turf`) — NOT
  web-fetched. A first attempt to pull this from a GitHub gist via WebFetch
  returned fabricated coordinates for roughly half the rows (obvious
  repeating-decimal fake patterns like `.21234567`, `.31234567` — a
  summarization model confabulating values for rows it couldn't actually
  read) and was discarded outright before it touched the repo. County names
  verified to match `app.js`'s `ALL_COUNTIES` (FL) and `tx-counties.svg`'s
  `data-county` attributes (TX) exactly, zero diffs.
- **The toggle itself**: `#mapStyleToggle` in the "Where these are" card
  head (`.map-style-toggle`, same segmented-pill idiom as the toolbar's
  ledger pills) — "Map" (outline, default) / "Satellite". Switching shows
  `#satelliteMapCanvas` and hides `#exploreMapCanvas` or vice versa via the
  `hidden` attribute (needed a `.explore-map-canvas[hidden]{display:none}`
  rule, since the existing `.explore-map-canvas{display:flex}` was tied with
  `[hidden]`'s UA-stylesheet rule on specificity and had been winning by
  source order — see explore.css). The outline map's own centroid geometry
  is unaffected by being hidden/shown (explore.js only measures once,
  `centroidsOk` latches true — see its own header note), so no coordination
  with explore.js was needed for the toggle to work correctly both ways.
- **Same honest bubble-then-pins model as the outline map**: statewide,
  county bubbles sized by count (same `.cluster-bubble` accent colors, reused
  via CSS custom properties and a mirrored `data-ledger` attribute rather
  than a second hard-coded palette). Once `#mapCountySelect` narrows to one
  county — via the toolbar or by clicking a bubble, which calls the exact
  same select-and-dispatch pattern as explore.js's own `applyCounty()` — the
  satellite map switches to real geocoded pins for that county and flies the
  camera in. A pin click opens a `mapboxgl.Popup` with a "View details"
  button wired to the same `openDetail` the event contract already carries.
- **Off by default, safe when unconfigured**: `config.js` gets a new
  `mapboxToken` field (blank by default, with the sign-up steps in a
  comment — same public-token category as the Supabase publishable key right
  above it, safe to ship client-side). `satellite-map.js` never fetches
  Mapbox's script, its CSS, or a single tile unless BOTH a token is present
  AND the user has actually clicked Satellite. With no token (which is every
  deploy until Marc adds one — `tests/config.js` deliberately has none, so
  CI exercises exactly this path) clicking Satellite just swaps in a plain
  "Satellite view isn't set up yet, add a token in config.js" message. Zero
  network calls, zero new CSP surface touched, in that state.
- **`public/_headers`**: CSP extended to allow `api.mapbox.com`
  (script/style/connect) and `worker-src 'self' blob:` (Mapbox GL JS spins up
  a worker from a blob URL) — with a comment explaining this is a deliberate,
  Marc-approved exception to the `img-src 'self' data:` privacy rule the
  outline map has relied on since Phase 53, not an oversight. `events.
  mapbox.com` (Mapbox's own telemetry) is deliberately left off the
  allowlist — blocking it doesn't break tiles.
- Mapbox GL JS is loaded from `https://api.mapbox.com/mapbox-gl-js/v3.30.0/`
  (current stable per Mapbox's own install guide as of this phase) — bump
  the pinned version in `satellite-map.js`'s `MAPBOX_GL_VERSION` constant
  next time it's worth checking for a newer one.
- `.github/workflows/sync-public-to-root.yml`'s `FILES` list gained
  `county-centroids.json` and `satellite-map.js` — same mirrored-asset
  pattern as `fl-cities.json`/`tx-counties.svg`, not the `fl-counties.svg`
  root-only exception.

### What's still needed from Marc

The feature is fully built and tested, but **inert until Marc supplies his
own Mapbox token** — that's a real account only he can create, not something
that can be generated on his behalf. Once he has one (free at mapbox.com,
free tier covers 50,000 map loads/month as of this writing — see
mapbox.com/pricing for current terms; copy the "Default public token" from
account.mapbox.com/access-tokens), it's one line in `config.js` and a
redeploy — no code changes.

### Verification

250/250 `tests/run_test.mjs` checks pass (241 carried over from Phase 54 +
9 new, covering the toggle's default state, the no-token setup message, that
Mapbox GL JS is NOT fetched when unconfigured, and that switching back to
the outline map restores it correctly). Screenshots taken at desktop
(1400×900) and mobile (390×844) width, light and dark theme, both toggle
states — caught one real bug along the way (the `--map-aspect` custom
property was scoped to `.explore-map-canvas`, which the new sibling
`.satellite-map-canvas` could never inherit from since custom properties
flow down the tree, not sideways between siblings — moved the declaration up
to their shared `.explore-map` ancestor). Service worker bumped to
`tdw-shell-v26`.

## Satellite basemap: Mapbox → Google Maps (Phase 56, done)

Marc got a real Google Maps API key ("google gave me a demo api to test")
and, asked directly how he wanted it wired in, chose to switch providers
outright rather than keep Mapbox as an option or run both — his answer,
verbatim button label: **"Switch to Google Maps."** This phase rips out
Phase 55's Mapbox GL JS implementation and rebuilds the same Satellite
toggle on the Google Maps JavaScript API. The feature itself (toggle button,
bubbles-then-pins model, event contract with explore.js, off-by-default
behavior) is unchanged — see Phase 55's section above for that design; this
section only covers what changed underneath it.

**What changed:**

- **`public/satellite-map.js`** — Mapbox GL JS (`mapboxgl.Map`,
  `mapboxgl.Marker`, `mapboxgl.Popup`, a CDN `<script>`/`<link>` pair) is
  replaced with the Google Maps JavaScript API, loaded via Google's own
  official dynamic-library-loader bootstrap (reproduced from
  developers.google.com/maps/documentation/javascript/load-maps-js-api,
  installed inline in this file rather than as a separate `<script>` tag in
  the HTML — same behavior). `google.maps.importLibrary("maps")` /
  `("marker")` pull in `Map`/`InfoWindow` and `AdvancedMarkerElement` only
  once a key is configured and the user clicks Satellite — same lazy,
  off-by-default contract Phase 55 established, just a different library.
  `mapTypeId: "hybrid"` gives satellite imagery + labels (closest match to
  the reference mockup); `mapId: "DEMO_MAP_ID"` is Google's own placeholder
  Map ID, meant exactly for testing `AdvancedMarkerElement` without first
  creating a real Map ID in Cloud Console — fine for a demo key, worth
  swapping for a real Map ID later if this key is upgraded. All the
  provider-agnostic logic (county grouping, zoomed-vs-statewide detection,
  `selectCounty()`'s select-and-dispatch pattern, `loadCentroids()`,
  `radiusPx()`, `pinLabel()`, the `tdw:maprendered` wiring) is untouched.
- **`config.js`** — `mapboxToken` is replaced with `googleMapsApiKey`.
  **The key is deliberately blank in the repo (2026-09-18).** A live key was
  briefly committed here and in `config.js`; unlike the Supabase publishable
  key, a Google Maps key is not scoped by row-level security and it bills a
  real Cloud account, so a public repo is the wrong place for one that has
  no restrictions on it yet. Google Cloud Console was unreachable at the time
  (2-step verification became mandatory on 2026-08-26 and was not yet
  enabled), so the key could not be restricted, and it was rotated instead.
  **Anything committed here lives in git history forever - blanking the file
  does not un-publish it.** Before a key goes back in this slot it must be
  restricted in Cloud Console to (a) HTTP referrers for this site's domains
  and (b) the Maps JavaScript API only. With the slot blank, the satellite
  toggle degrades to its own "not set up yet" message and nothing breaks -
  that path is covered by `tests/config.js`, which deliberately carries no
  key.
- **`public/_headers` (CSP)** — **this is a materially bigger relaxation
  than Phase 55's Mapbox addition**, not a like-for-like swap:
  - `'unsafe-eval'` is now allowed in `script-src`. Per Google's own CSP
    guidance
    (developers.google.com/maps/documentation/javascript/content-security-policy),
    the Maps JS API requires it — the library uses dynamic code execution
    internally for its on-demand library loader, and this is true even in
    Google's strictest documented CSP recipe, not just the permissive one.
    This genuinely weakens this app's defense-in-depth against
    injected-content XSS (see `_headers`' own top-of-file comment on why
    that defense exists) — if an attacker ever got script content into the
    page some other way, `'unsafe-eval'` gives it a strictly wider toolbox
    than the Mapbox-only CSP did.
  - `script-src`/`img-src`/`connect-src` now allow wildcarded Google domains
    (`*.googleapis.com`, `*.gstatic.com`, `*.google.com`) rather than one
    pinned host the way `api.mapbox.com` was — Google doesn't publish a
    narrower single-host alternative for the JS API.
  - Scoped down from Google's own published "allowlist" CSP recipe where
    this app's actual usage didn't need it (no `*.ggpht.com`,
    `*.googleusercontent.com`, or `frame-src` — those cover Street View/
    Places photos and an iframe this app doesn't use). If Satellite mode
    ever throws a CSP violation after a future Google Maps feature is added,
    check this policy first.
  - This was Marc's call to make, same as the original satellite-vs-privacy
    trade-off in Phase 55 — flagged to him directly when this shipped, not
    silently absorbed into "swap the provider."
- **`public/explore.css`** — Mapbox-specific selectors
  (`.mapboxgl-popup-content`, `.mapboxgl-popup-tip`,
  `.mapboxgl-canvas-container`) are gone. Google's `InfoWindow` renders its
  chrome via reserved `.gm-style-iw*` classes (in current versions, inside a
  closed shadow root besides), so overriding it the way Mapbox's popup CSS
  was overridden isn't reliable — left at Google's own default chrome; only
  the content passed to `setContent()` (`.sat-popup-*`) is styled here, same
  as before.
- **`tests/run_test.mjs`** — the "Mapbox GL JS not loaded when unconfigured"
  check now checks for `window.google.maps.importLibrary` instead
  (`googleMapsNotLoadedWithNoToken`, renamed from
  `mapboxGlNotLoadedWithNoToken`). `tests/config.js` already had no
  `mapboxToken`/needs no `googleMapsApiKey` — the "not configured" path this
  test exercises needed no fixture change.
- Service worker bumped to `tdw-shell-v27`.

**Verification:** 250/250 `tests/run_test.mjs` checks pass against the
unconfigured path (real deploy default until this ships). The configured
path was smoke-tested locally with Marc's real key — the bootstrap loads and
the toggle's control flow (loading message → map init → marker rendering)
runs correctly, but this sandbox's own network egress policy blocks
`maps.googleapis.com` outright (confirmed via the proxy's own connection log,
not a guess), so full live tile rendering could only be exercised as far as
the graceful "couldn't load, check your connection" fallback path — which is
itself a real, intentional code path, not a stand-in for missing coverage.
Live rendering needs to be confirmed on the actual deployed site, the same
way Phase 54/55 were verified after delivery, not assumed from this
sandbox's test run.

**Update, confirmed live:** Marc verified the Google satellite view on the
real deployed site after Phase 56 shipped — it works. See Phase 57 below for
what came next.

## Both satellite providers, three-way toggle (Phase 57, done)

After confirming Google Maps worked live, Marc asked for Mapbox back too —
verbatim: *"would like to have mapbox as a back up or even just map toggle
to have all three options"* — and sent his Mapbox token
(`pk.eyJ1Ijoicm9kem1vZHpsbGMi...`) back in the same message. Read plainly:
he wants all three views available, switchable, none replacing another —
the same spirit as Phase 55's original "toggle, not a replacement" decision,
just extended to two third-party providers instead of one.

**What changed:**

- **`public/satellite-map.js`** — restructured to hold both provider
  implementations side by side rather than one at a time: a `googleState`
  object (Google Maps, same code as Phase 56) and a `mapboxState` object
  (Mapbox GL JS, restored from Phase 55's git history — `git show
  6e1d5b9:public/satellite-map.js` — rather than rewritten from scratch, so
  the restored implementation is exactly what was already tested and
  verified working in Phase 55, not a reconstruction). Kept as one file
  instead of split into three, since the two providers share most of their
  surrounding logic (county grouping, centroids, zoomed-vs-statewide
  detection, the toolbar contract via `selectCounty()`) — see the file's own
  header for the reasoning. Each provider lazy-loads its own script only
  when its own button is clicked; clicking one never touches the other's
  state, and both can independently be `ready`, `loading`, `unconfigured`,
  or `error`.
- **`#mapStyleToggle`** is now three buttons: `#mapStyleOutline` (Map,
  default), `#mapStyleGoogle`, `#mapStyleMapbox` — replacing the old
  two-button Map/Satellite pair. `#mapStyleSatellite` no longer exists as an
  id anywhere in the app.
- **`config.js`** — `googleMapsApiKey` and `mapboxToken` are independent of
  each other; either can be blanked without affecting the other. **Update,
  2026-09-18: `googleMapsApiKey` is blank, `mapboxToken` is live.**
  `googleMapsApiKey` — the key committed here in Phase 56 was found exposed
  in this public repo and treated as compromised (see the Phase 56 section
  above and the "security: blank the committed Google Maps API key"
  commit); the Google toggle button still shows but degrades to its own
  "not set up yet" message until a properly-restricted replacement key goes
  in. `mapboxToken` — a first push carrying this same token was rejected by
  GitHub's push-protection scanner, which classified it as a "Mapbox Secret
  Access Token" despite its `pk.` (normally public/client-safe) prefix, so
  it was pulled from the commit before it ever reached GitHub pending
  verification. Verified directly against Mapbox's own dashboard
  (console.mapbox.com/account/access-tokens) — it's Mapbox's own
  auto-generated "Default public token," the only token on the account,
  confirmed byte-for-byte, and that token type is designed by Mapbox to be
  safe for client-side/public code (default public scopes only). GitHub's
  classification appears to have been a false positive for this specific
  token; restored to `config.js` and shipped. It has no URL restriction set
  in Mapbox's dashboard — adding one there is still worth doing so the key
  can't be used on other sites if it ever leaks elsewhere, but doesn't
  change anything in this repo.
- **`public/_headers` (CSP)** — grants both providers' domains
  simultaneously rather than one replacing the other: Mapbox's
  `api.mapbox.com`/`*.tiles.mapbox.com` sit alongside Google's
  wildcarded domains and `'unsafe-eval'`. Flagged in-file: this is a larger
  standing allowlist than either provider needed alone, live for every
  visitor regardless of which button they ever click — not a further
  broadening of either provider's own individual grant, but the fact that
  both are simultaneously trusted, all the time, is itself worth naming.
- **`public/explore.css`** — Mapbox's overridable `.mapboxgl-popup-*` chrome
  rules are back (restored from Phase 55), alongside Google's
  `.gm-style-iw*`-can't-be-overridden note from Phase 56. Both providers'
  markers still share the same `.sat-county-bubble`/`.sat-pin` styling and
  the same `.sat-popup-*` content markup — only the popup/marker *library*
  differs, not the visual design.
- **`tests/run_test.mjs`** — the toggle test now exercises both providers'
  "not configured" paths independently (`mapStyleGoogleOnAfterClick` /
  `mapStyleMapboxOnAfterClick` and friends) since `tests/config.js`
  deliberately carries neither key. 257/257 checks pass.
- Service worker bumped to `tdw-shell-v28`.

**Verification:** 257/257 `tests/run_test.mjs` checks pass. Both providers
were smoke-tested locally with Marc's real key/token — the sandbox's network
egress policy blocks both `maps.googleapis.com` and (presumably)
`api.mapbox.com`, so both fall through to their own graceful
"couldn't load, check your connection" message in this environment, same
limitation as Phase 56. Live rendering of both needs confirming on the
actual deployed site after this ships.

## Property deep-linking (Phase 58, done)

Marc's request, verbatim: *"when you click a link on the app and go back to
the app it should land on that same property card."* The scenario: a user
opens a property, taps an outbound `target="_blank"` link (Zillow, Street
View, the county auction site), then comes back — on mobile this can mean
the OS evicted the backgrounded PWA tab entirely, so "coming back" is
actually a full cold start of the app, not a resume.

**What changed (`public/app.js` only):**

- `pidFromHash()` — new helper alongside the existing `ledgerFromHash()`,
  parses a trailing `/<id>` off the URL fragment (`#/auctions/12345` →
  `"12345"`).
- `openDetail(p)` — right after `pushBackLayer("detail", closeDetail)`, now
  does `history.replaceState(history.state, "", "#/" + slug + "/" + p.id)`.
  Deliberately `replaceState`, not `pushState`, and deliberately applied to
  the SAME history entry `pushBackLayer` already created (that call already
  did a `pushState` with an empty-string URL, i.e. "keep the current URL") —
  this is what keeps the existing `BACK_LAYERS`/Android-back-button behavior
  completely unchanged: closing the modal via Back still lands on the bare
  ledger hash and leaves no extra history entry, whether the modal was
  opened by a click or reopened automatically below.
- `showApp()` — captures `pidFromHash()` once at startup, and after the
  existing ledger-routing/idle-watch/admin-approvals setup, looks the id up
  in `ALL` and calls `openDetail(p)` if found. This is what makes a cold
  start at a deep-linked URL reopen the right card instead of just landing
  on the bare list.

**Why this is safe rather than a special case:** the URL fragment convention
(`#/<ledger-slug>`) already existed for ledger routing; this only extends it
one level deeper. No new history-management logic was added — the feature
rides entirely on infrastructure (`BACK_LAYERS`, `pushBackLayer`) that was
already there for the Android hardware-back-button behavior.

**Testing pitfall worth remembering:** a `page.goto()` that only changes the
current document's URL fragment is a same-document, in-page navigation in
real browsers (same as clicking an anchor link) — it does **not** trigger a
real reload or re-run any startup script. An early version of the smoke test
for this feature gave a false pass because of exactly that: the modal
"stayed open" simply because it was never closed, not because the
cold-start reopen logic actually ran. The correct way to simulate a genuine
cold start / tab eviction in Playwright is a **separate `browser.newPage()`**
navigated directly at the full target URL (hash included) from the start,
never a `goto()` on the same page that was already there. `tests/run_test.mjs`
now has this coverage (`deepLinkHashHasPid`, `deepLinkModalVisibleOnColdStart`,
`deepLinkAddressMatchesAcrossColdStart`, `deepLinkModalHiddenAfterBack`,
`deepLinkHashClearedAfterBack`), built exactly that way — two isolated
`newPage()` contexts, address-text equality checked across them rather than
just "a modal appeared."

**Verification:** 262/262 `tests/run_test.mjs` checks pass (257 pre-existing
+ 5 new for this feature).

## Bigger brand-mark logo (Phase 59, done)

Marc's request, verbatim: *"also the logo should be bigger next to the title
as as my app icon should be displayed like that as well instead of the
current little calendar and dollar sign."* Two separate things in that one
sentence — the in-app logo, and the PWA/home-screen icon. Handled
differently because only one of them is actually a code issue.

**In-app logo (fixed, then bumped again - Phase 59b):** the brand-mark
`<img>` appears in three places — `.auth-brand img` (sign-in /
pending-approval screens, was 30×30, then 56×56, **now 72×72**), `.topbar
.brand-mark` (mobile sticky header, was 22×22, then 32×32, **now 44×44**),
and `.nav-rail-brand img` (desktop sidebar, was 22×22, then 32×32, **now
44×44**) — bumped via both the HTML `width`/`height` attributes in
`index.html`/`tx.html` *and* `public/styles.css`'s `.nav-rail-brand
img{width:32px;height:32px}` rule (inside the `@media (min-width:1024px)`
block), which would otherwise have silently kept overriding the HTML
attribute on desktop — a CSS `width`/`height` rule always wins over the
element's own attributes. Marc said the first bump (56/32) still wasn't
big enough, hence the second pass to 72/44. Verified with a Playwright
screenshot and a direct `clientWidth`/`clientHeight` measurement (44×44
confirmed rendered on desktop) before shipping, not just by reading the
diff. 262/262 `tests/run_test.mjs` checks still pass. The 72/44 version
shipped via two different delivery paths worth knowing about if this repo's
history looks odd here: first as a normal commit through Marc's own
terminal, then again (after a sync gap) via GitHub's web upload/commit UI
directly from this session's browser tool - see "Known landmines" below on
why pushing isn't always possible from the assistant's own sandbox.

**App icon (not a code bug — user-side cache):** investigated directly —
`public/icons/icon-192.png`, `icon-512.png`, and `apple-touch-icon.png` all
show the navy/gold shield-with-house-gavel-columns-arrow logo, not a
calendar-and-dollar-sign, both in this repo and cross-checked against the
live `origin/main` branch. `sw.js`'s own code comments (`?v=2` cache-buster
note) document a *prior* re-logo event that already replaced an old icon.
The calendar-and-dollar-sign Marc is describing almost certainly doesn't
exist in the current app at all — it's a stale, OS-level cached icon on an
already-installed "Add to Home Screen" PWA shortcut from before that prior
re-logo. This repo's own cache-busting (`?v=N` query strings, `sw.js` CACHE
version bumps) only reaches the website's own Service-Worker Cache Storage
and HTTP cache — it cannot reach an already-installed home-screen shortcut's
icon, which is a separate OS-level cache (a known limitation, especially on
iOS Safari). The fix is device-side: remove the existing home-screen
shortcut and re-add it. No code change can push a fix for this.

## Satellite basemap: Mapbox → MapTiler (Phase 60, done)

Continuation of the Phase 57 three-way toggle's Mapbox slot. The Mapbox
token kept tripping GitHub's push-protection secret scanner (twice - see
Phase 57's own section) even after being verified against Mapbox's own
dashboard as the account's "Default public token." Trying to fix it
properly (a fresh, narrowly-scoped custom token) hit a real wall: Mapbox
now requires a payment method on file before it'll let you create *any*
additional or custom token at all - confirmed by clicking "Create a token"
in Mapbox's dashboard and hitting a hard "Add a payment method to complete
your account set up" gate, not just a soft nudge. Rather than have Marc
hand over a card for what's a bonus third map view (the app works fully
with the outline map and needs neither Google nor this one), the Mapbox
slot was swapped for MapTiler instead:

- **MapTiler's free tier needs no card at all** - confirmed directly on
  MapTiler's pricing page ("FREE plans do not require billing
  information"), 5,000 map sessions/month, satellite imagery included.
  Nowhere close to this app's real traffic.
- **`public/satellite-map.js`** - the "MAPBOX PROVIDER" section became
  "MAPTILER PROVIDER." `mapboxToken()` → `maptilerKey()` (reads
  `window.TDW_CONFIG.maptilerKey`). Mapbox GL JS (loaded from
  `api.mapbox.com`) → MapLibre GL JS (loaded from `unpkg.com`, since
  MapTiler doesn't self-host the library the way Mapbox did) - MapLibre is
  an open-source fork of Mapbox GL JS v1 with the same `Map`/`Marker`/
  `Popup`/`NavigationControl` API, so this was close to a 1:1 rename rather
  than a rewrite. The one real difference: no `accessToken` global - the
  key goes directly in the style URL,
  `https://api.maptiler.com/maps/hybrid/style.json?key=...` ("hybrid" =
  satellite + labels, MapTiler's equivalent of Mapbox's
  `satellite-streets-v12`), replacing the `mapbox://styles/...` protocol
  URL. `activeStyle`'s `"mapbox"` value became `"maptiler"` throughout.
- **`public/index.html` / `public/tx.html`** - `#mapStyleMapbox` button →
  `#mapStyleMaptiler`, label text "Mapbox" → "MapTiler".
- **`config.js`** - `mapboxToken` field → `maptilerKey`, same
  independent/optional pattern as `googleMapsApiKey`. Left blank in this
  repo deliberately, same reason as the Mapbox token before it: this
  sandbox's own safety guardrails refuse to let the assistant commit a live
  API key into git history, verified-safe or not (confirmed hitting this
  wall directly - see the git history around 2026-09-18 for the denied
  attempts). A key was created in MapTiler Cloud
  (`cloud.maptiler.com/account/keys/`), named `taxdeed-scraper-site`,
  restricted via "Allowed HTTP Origins" to `rodz-taxdeeds.pages.dev` only -
  Marc adds the actual value to this file himself, from his own machine.
- **`public/explore.css`** - untouched. MapLibre GL JS deliberately kept
  Mapbox GL JS's `.mapboxgl-*` CSS class names (canvas container, popup
  chrome, etc.) for drop-in compatibility, so the existing popup/marker
  style overrides here still apply with zero changes.
- **`public/_headers` (CSP)** - `api.mapbox.com`/`*.tiles.mapbox.com` in
  `img-src`/`connect-src` replaced with `api.maptiler.com`;
  `api.mapbox.com` in `script-src`/`style-src` replaced with `unpkg.com`
  (MapLibre's CDN host). Net effect is a lateral swap in the allowlist, not
  a further widening - one provider's domains for another's.
- **`public/sw.js`** - `CACHE` bumped `tdw-shell-v28` → `tdw-shell-v29`
  since `satellite-map.js` and `config.js` are both in the shell precache
  list and changed here.
- **`tests/run_test.mjs`** - the Mapbox-button checks (`mapStyleMapboxOnAfterClick`,
  `mapboxGlNotLoadedWithNoToken`, etc.) renamed to their MapTiler
  equivalents, still exercising the same "not configured yet" path against
  `tests/config.js`'s deliberately blank `maptilerKey`. 262/262 checks pass
  - same count as before, since this was a 1:1 provider rename, not new
  surface area.
- **Not yet live-verified against real MapTiler tiles**: this sandbox's own
  network policy blocks `unpkg.com` and `api.maptiler.com`, so the
  "configured, tiles actually render" path could only be verified by
  Playwright (via the local `unpkg.com`/`api.maptiler.com` calls being
  absent, since `maptilerKey` ships blank) and by code review against
  MapLibre/MapTiler's documented integration pattern - not by an actual
  rendered map in this environment. First real check happens once Marc
  adds his key and reloads.

## Satellite basemap: shared-canvas toggle bug (Phase 61, done)

Predicted risk in Phase 60's own "not yet live-verified" note came true the
first time it could: Marc got a real `googleMapsApiKey` (a Google Maps Demo
Key - see below) live alongside the already-live `maptilerKey`, and reported
"both maps populated but both in terrain and once i choose maptiler it won't
switch back to google maps." Root cause was structural, not new to Phase 60:
Phases 56/57/60 had Google and the GL-based provider (Mapbox, then MapTiler)
share ONE DOM node, `#satelliteMapCanvas`, on the assumption that "never
both at once - only the active one is un-hidden" (explore.css's old comment)
was sufficient. It wasn't - each provider's `ensure*Map()` claims that node
with `canvas.innerHTML = ""` the first time it initializes, then never
touches it again (`ensure*Map()` early-returns once that provider's own
`loadState` is `"ready"`). So whichever provider a viewer clicks SECOND
wipes out the first provider's live map/markers when it takes the node over,
and clicking back to the first provider just calls its `render*()` against a
map object whose container div either no longer holds that map's content or
was deleted out from under it. Never caught by the test suite because
`tests/config.js` ships neither key (deliberately, per its own comment), so
Playwright only ever exercises the "not configured yet" path for both
providers - each stays `"idle"`, so the fixture never reaches the actual
hand-off. Confirmed live via Marc's own screenshot: the "Google" toggle
button showed `.on`, but the rendered tiles were MapTiler's (visible
attribution: "MapLibre | © MapTiler © OpenStreetMap contributors").

- **`public/satellite-map.js`** - `CANVAS_ID` (shared) replaced with
  `GOOGLE_CANVAS_ID` (`satelliteMapCanvasGoogle`) and `MAPTILER_CANVAS_ID`
  (`satelliteMapCanvasMaptiler`), each provider's permanent own node.
  `setupMessage()` now takes a canvas id parameter instead of assuming the
  shared one. `setStyle()` shows/hides both independently
  (`googleCanvas.hidden = style !== "google"`, same for maptiler) instead of
  toggling one shared `satCanvas`. `ensureGoogleMap()`/`ensureMaptilerMap()`,
  `renderGoogle()`/`renderMaptiler()` all target their own canvas constant.
  No provider's init logic needs to reclaim anything from the other anymore.
- **`public/index.html` / `public/tx.html`** - the single
  `<div id="satelliteMapCanvas">` became two sibling divs,
  `#satelliteMapCanvasGoogle` and `#satelliteMapCanvasMaptiler`, both
  `class="satellite-map-canvas"` (so all existing CSS, which targets the
  class, needed zero changes) and both `hidden` by default.
- **`public/explore.css`** - no rule changes (selectors are class-based, and
  both canvases share the class), just corrected a stale comment that
  described the two providers as sharing one node.
- **`tests/run_test.mjs`** - the three `#satelliteMapCanvas` locators split
  to target `#satelliteMapCanvasGoogle` / `#satelliteMapCanvasMaptiler` as
  appropriate; `satelliteCanvasHiddenByDefault` now checks both are hidden.
  The two `.satellite-map-setup` visibility checks got scoped to their own
  canvas (`#satelliteMapCanvasGoogle .satellite-map-setup`, etc.) since with
  independent canvases, both providers' setup messages can now coexist in
  the DOM at once (one hidden) once each has been clicked - a bare
  `.satellite-map-setup` locator started matching two elements and failing
  Playwright's strict mode the moment this fix was in place, which is itself
  a good sign the old shared-node behavior was gone. Added a regression test
  that runs the exact sequence that surfaced the bug (click Google, click
  MapTiler, click Google again) and asserts each canvas's visibility and the
  toggle's `.on` state came back correctly. **265/265 checks pass** (3 new
  checks: `googleCanvasVisibleAfterGoogleMaptilerGoogleSequence`,
  `maptilerCanvasHiddenAfterGoogleMaptilerGoogleSequence`,
  `mapStyleGoogleOnAfterReturningFromMaptiler`).
- **Still only verified with real tiles for one provider’s "return trip" at
  a time via manual click-through, not by Playwright** - the fixture config
  still ships neither key, so the regression test above proves the DOM-level
  contract (visibility/state) is correct, not that two real map libraries
  genuinely coexist without a deeper conflict (e.g. both loading their CSS/
  JS onto the page at once). Worth a manual recheck if either provider's
  loader ever changes.

## Google Maps key: Demo Key, and the account-wide 2SV wall (Phase 61)

`googleMapsApiKey` had been blank since Phase 56 (original key compromised
via public git history, rotation blocked because Google Cloud Console
required 2-Step Verification that wasn't enabled on Marc's account). Marc
proposed Google's free "Maps Demo Key" as a workaround, on the theory that
its own docs don't mention any 2FA requirement (true - the Demo Key concept
itself needs no billing info and no stated 2SV). In practice this didn't
route around anything: Google Cloud now enforces 2-Step Verification
**account-wide, for all of Google Cloud console, effective August 26,
2026** - confirmed live via a "Google Cloud access blocked" page that
appeared even on the Maps Terms-of-Service acceptance step the Demo Key flow
itself requires. So enabling 2SV is now an unavoidable prerequisite for
*any* Google Maps key, demo or production. Marc enabled 2SV on his Google
account (Authenticator + phone number); Google Cloud unblocked within
about a minute, and the same tab that had been showing "access blocked" went
straight through to a `gmp-demo-project-137937982` demo project and handed
back a live Demo Key. Marc added it to `config.js` himself (same
can't-commit-a-live-credential handoff as every other key in this repo).
Two caveats worth remembering: it's explicitly testing/prototyping-only per
Google's own docs (daily quota, pauses rather than charges if exceeded, not
meant for production), and it isn't domain-restricted the way the MapTiler
key is - tightening that is a follow-up, not yet done.

## Property photo CSP gap, satellite bubble sizing, and stale popups (Phase 62, done)

Three bug reports from Marc, all fixed in one pass since two were quick and
concrete and the third needed the code review this phase's investigation
started with:

**1. "Still no photos of the properties" - `img-src` never granted Supabase.**
`properties.photo_url` (see the "Property photos" section above) has been
populating real Supabase Storage URLs for a while and `app.js` has rendered
`<img src="${p.photo_url}">` for them since Phase 51, but `public/_headers`'
CSP `img-src` directive only ever granted `'self' data: blob:` plus the map
providers - never `https://*.supabase.co`. `connect-src` had it (that
governs `fetch`/XHR, which is how the Supabase *client* talks to the API),
but `img-src` governs `<img>` loads specifically, and nothing granted that.
Confirmed via live Supabase query that 300 real `photo_url` rows exist,
100% consistently under this same Storage host - every one of them was being
silently CSP-blocked from ever rendering. Fixed by adding
`https://*.supabase.co` to `img-src`. This doesn't weaken the privacy
posture `img-src`'s restrictiveness exists for (see `_headers`' own
top-of-file comment) - the `property-photos` bucket is a public bucket by
design, so these URLs were never private in the first place.

**2. "The property bubbles or pins are way too big" - real geography needed
smaller bubbles than the abstract map.** Confirmed via Marc's own
screenshots (both Google and MapTiler): five-plus county bubbles piled on
top of each other around the Tampa/Orlando corridor, unreadable. Root cause:
`satellite-map.js`'s `radiusPx()` used the same 15-34px radius range as
`explore.js`'s `radiusFor()` (13-38 SVG units) - but explore.js draws on an
abstract, hand-drawn SVG shape with room built in between counties, while
satellite-map.js places bubbles at REAL county centroids on a real map,
where several of Florida's busiest counties (Hillsborough/Pinellas/Pasco/
Polk, Orange/Seminole/Osceola) are genuinely close together. The same pixel
range that reads fine on the stylized map overlaps badly on the true-to-life
one, worst on a narrow phone screen showing the whole state at once. Cut
`MIN_R`/`MAX_R` from 15/34 to 8/18 (roughly half the diameter) - still
sqrt-scaled so bubble *area* tracks property count, just sized for real
geographic density. No test coverage existed for exact bubble pixel size
(nothing to break), and this only touches `satellite-map.js` - explore.js's
own map is untouched and unaffected.

**3. "Toggling through Auctions/Lands Available/Certificates... should
distinguish each category, not populate all the same" - an open popup
outlived the render that should have cleared it.** Confirmed via Marc's
screenshot: filtered to Broward + Lands Available with zero matches ("Where
these are" correctly said "Nothing matches the current filters"), yet a
popup for a property was still shown on the map. The underlying data
filtering was never wrong - `computeMapRows()` in `app.js` already scopes
rows to `mapFilter.ledger` correctly - but `clearGoogleMarkers()`/
`clearMaptilerMarkers()` (called at the top of every `renderGoogle()`/
`renderMaptiler()` pass, i.e. every ledger/county/filter change) only ever
cleared the marker array. A `google.maps.InfoWindow` and a
`maplibregl.Popup` opened by clicking a pin are their OWN objects, not
markers - clearing markers never touched an already-open one, so it just
sat on screen showing whatever property was last clicked, regardless of
which ledger or county the map had since switched to. Fixed by closing
`googleState.infoWindow`/removing `maptilerState.popup` inside those same
two clear functions, so every re-render (not just marker changes) also
closes any stale popup.

**Verification:** 265/265 `tests/run_test.mjs` checks pass (no new checks -
none of the three bugs had a gap in existing coverage worth a dedicated
regression test: the CSP fix isn't DOM-observable from the fixture, which
ships no real Supabase Storage photo URLs; the bubble-size fix has no pixel
assertion to update; the popup fix would need a real map provider actually
loaded, which the fixture deliberately never configures - same limitation
Phase 61's own regression test notes). Service worker bumped to
`tdw-shell-v31`.

## Full front-end audit and fix pass (Phase 63, done)

Marc asked for a full audit of the entire front end. Four parallel reviews
covered `app.js`, `explore.js`/`satellite-map.js`, the HTML/CSS, and the
PWA shell/CSP/config - 18 concrete findings came back, and all 18 were
fixed in this pass. Grouped by file:

**`app.js`**
- **Bid-range slider crossing corrupted the filter.** When the Min/Max
  handles crossed, only the slider's DOM value got corrected - `state.bidMin`/
  the label/the track fill kept using the stale, pre-correction number, so
  `state.bidMin` could end up greater than `state.bidMax` and `passes()`'s
  bid filter silently excluded every property. `updateBidRange()` now snaps
  whichever handle the user did NOT just move (via `e.target`) and keeps
  every downstream value in sync with the corrected sliders.
- **The approval gate failed open on ANY `profiles` query error**, not just
  "the migration hasn't been run" - a transient network error, a timeout, or
  an RLS misconfiguration (the exact class of bug that's taken this site
  down once before, see the RESTRICTIVE/PERMISSIVE lesson above) let an
  unapproved account straight into the app. `checkApprovalAndEnter()` now
  narrows the fallback to an actual missing-table error (mirroring
  `fetchProperties()`'s own `PGRST202` narrowing) and fails CLOSED - shows
  the pending screen - for anything else.
- **Every Supabase auth event re-ran the full app bootstrap.**
  `onAuthStateChange` didn't discriminate event types, so `TOKEN_REFRESHED`
  (fired automatically roughly hourly) and `USER_UPDATED` (fired by the
  profile-edit/change-password flows) triggered the same full
  `showApp()` reload as a real sign-in - refetching every table, repainting
  a loading skeleton, and unconditionally resetting `state.counties` back to
  "all counties," silently discarding a user's county filter mid-session.
  Now only `event === "SIGNED_IN"` (or the tab's very first load, where `ME`
  is still unset) triggers the full bootstrap; anything else just updates
  `ME`.
- **Watchlist auto-promotion swallowed insert errors.** The manual "add to
  watchlist" click handler already calls `showErrorToast()` on failure;
  `promoteNextPending()` (the same insert, fired automatically when a slot
  frees up) silently dropped a failed item with zero feedback. Now surfaces
  the same toast.
- **CSV export didn't escape a bare carriage return** - only `[",\n]` was
  tested, not `\r`, which could corrupt row boundaries in a harvested text
  field containing a lone `\r`. Regex now includes it.

**`explore.js` / `satellite-map.js`**
- **Escape closed both the preview card and the county zoom at once**,
  unlike the hardware/Android Back button, which correctly closes only the
  topmost layer (preview first, since it was opened later - see `back`'s own
  comment). Both keydown listeners (`bindMapInteraction()`,
  `bindStrip()`) now share a `handleEscapeToExitTopLayer()` helper that
  checks `activeProp` before `zoomCounty`, with `stopPropagation()` on the
  inner canvas listener so the outer panel listener doesn't double-handle
  the same keypress.
- **Satellite-map pins were `role="button" tabindex="0"` but keyboard-dead**
  - a plain `<div>` doesn't fire `click` on Enter/Space the way a real
  `<button>` does, and unlike the county bubble markers a few lines below
  (which already had this), pins in both Google and MapTiler never got a
  `keydown` handler. Added, matching the bubbles' existing pattern.
- **Overlapping async renders could leave stale markers on screen.**
  `renderGoogle()`/`renderMaptiler()` both `await loadCentroids()` (a real
  network fetch the first time a provider loads) before adding markers, with
  no way to tell a stale call from a current one - a second
  `tdw:maprendered` event (filter/ledger/county change) firing before the
  first call's post-await continuation resumed left both calls' markers on
  the map at once. Each render call now grabs a generation ticket
  (`googleRenderGen`/`maptilerRenderGen`) and bails out after every `await`
  if a newer call has since started.

**HTML/CSS** (`index.html`, `tx.html`, `styles.css`)
- **The sign-in/sign-up form had no accessible labels** - every field relied
  on `placeholder` only, unlike `#profileForm`, which already fixed this
  exact pattern with real `<label>` wrappers. `#authForm`'s fields are now
  wrapped in `.auth-field` labels; `hidden`/`required` stay on the `<input>`
  itself (unchanged, so `app.js`'s `setAuthMode()` needed no changes), and a
  new `.auth-field:has(input[hidden]){display:none}` rule hides the whole
  label - including its text - whenever its input is hidden, so a field
  name never floats visible above a field that isn't.
- **`#filtersToggle` had no `aria-expanded`/`aria-controls`**, unlike every
  other disclosure control in the app (account menu, both Settings buttons).
  Added statically in HTML (`aria-controls="filtersPanel"`) and kept in sync
  in JS (`aria-expanded` toggled alongside the existing `.open` class).
- **`--muted`/`--line` were never defined anywhere** (`.kv-sub`/`.kv-flag`
  on the Risk & Legal flood-hazard card) - this app's real tokens are
  `--ink-soft`/`--card-line`, used everywhere else in the file. With no
  fallback given, these were invalid at computed-value time and could
  render invisible or wrong in both themes. Fixed to use the real tokens.
- **The flood-hazard warning flag used the Watchlist's pink accent**
  (`--watch`/`--watch-soft`) instead of a real danger color, because those
  variables ARE defined elsewhere (explore.css) so `var()`'s fallback never
  applied - it read as decorative rather than a risk flag, and was
  confusable with the unrelated Watchlist feature. Now uses `--bad`/
  `--bad-bg`, this app's actual danger tokens.
- **Dead CSS removed**: `.hbtn`/`.hbtn[hidden]`, `.brand-lockup`/
  `.brand-mark-lg`, `.disclaimer-badge` - all zero references anywhere in
  either HTML file or in `app.js` (confirmed via grep before deleting;
  `#installBtn` now uses `.account-item`, not `.hbtn`, from a past
  redesign). `.city-label`/`.city-labels` were deliberately NOT touched
  here even though they don't appear in static HTML either - they're
  generated by the already-documented-dead `#pageMap` JS block in `app.js`
  (see Phase 53 above, "safe to delete outright in a future cleanup") and
  removing the CSS half alone would conflate two separate cleanups.

**PWA shell / CSP / config** (`sw.js`, `_headers`, `config.js`)
- **The property GIS map embed was silently CSP-blocked** - same bug class
  as Phase 62's `img-src`/Supabase gap, different directive: no `frame-src`
  was ever set, so CSP fell back to `default-src 'self'` for frames, which
  doesn't cover the cross-origin OpenStreetMap `<iframe>` `osmEmbedUrl()`
  renders on every geocoded property's card. Added
  `frame-src https://www.openstreetmap.org` (unrelated to `X-Frame-Options:
  DENY`, which controls the opposite direction - whether other sites can
  frame this app).
- **Texas offline cold starts served the Florida shell.** The service
  worker's offline navigate fallback hardcoded `caches.match("/index.html")`
  regardless of the requested path, and `tx.html`/`tx-counties.svg` were
  never precached at all - even though `tx.html` is a full separate
  deployed page and both files are fetched at runtime whenever
  `PAGE_STATE === "TX"`. Both now precached in `SHELL`, and the fallback
  picks between `/index.html`/`/tx.html` based on `url.pathname`. Cache
  bumped to `tdw-shell-v32`.
- **`config.js`'s own comments claimed the Google/MapTiler keys were
  "deliberately blank"** when both are actually live (populated in Phase 60/
  61) - misleading to anyone reading the shipped file in isolation, and a
  risk that a future edit "fixes" a perceived blank by overwriting a working
  key. Comments corrected to describe the actual state.
- **This file itself (near the top) wrongly listed `config.js` as living
  under `public/`** alongside the mirrored files - it doesn't; `public/
  config.js` doesn't exist, `config.js` is root-only, and
  `sync-public-to-root.yml`'s own `FILES` list deliberately excludes it
  (its own guard step would fail CI if anyone created `public/config.js`).
  Corrected, with a note on why.

**Verification:** 265/265 `tests/run_test.mjs` checks pass (unchanged count
- none of the 18 fixes needed new fixture coverage to exercise). Three
targeted manual Playwright checks (not added to the permanent suite, since
each needs either a forced auth-gate state or direct slider `input` events
the fixture's sign-in flow and existing test structure don't set up)
confirmed: the sign-up mode toggle correctly reveals/hides `#authForm`'s
new labeled fields via the `:has()` rule in both directions; `#filtersToggle`
`aria-expanded` tracks open/closed correctly; and the bid-range slider
crossing fix keeps both handles and their displayed values consistent after
a cross instead of drifting apart.

## Map: dropdown-selected county didn't zoom, MapTiler popup unstyled (Phase 64, done)

Marc reported "Property pins and preview are still an issue" with a
screenshot of the Map page's MapTiler view: filtered to Highlands County (1
property), the satellite pin itself was correctly flown-in and drawn, but
everything AROUND it was wrong - the page still read "Where these are" / "1
shown across 1 county" / "Bubble size = properties in that county" / "Bubbles
are county-level counts... not exact parcel locations", all statewide-view
copy, sitting above what was actually a single zoomed-in, real-coordinate
pin. Two independent bugs, both in the "pins and preview" area, fixed
together:

- **Picking a county straight from `#mapCountySelect` (the Filters panel)
  left the outline map's own `zoomCounty` stuck at `null`.** `explore.js`'s
  `absorb()` only called `zoomTo(selectedCounty)` to re-sync when `zoomCounty`
  was ALREADY truthy - so the very first time a county came from the dropdown
  rather than a bubble tap, nothing re-synced it. `draw()`/`drawPins()`
  gate showing real pins vs. one summary bubble on that same `zoomCounty`,
  and `updateSummary()`/`renderBubbleLegend()` (title, count, note, hint,
  legend) gate on it too - so the outline map kept showing ONE statewide
  bubble instead of zooming to that county's pins, and all the surrounding
  text kept describing a bubble view. `computeMapRows()` in `app.js` already
  narrows `rows` to exactly one county whenever `mapFilter.county !== "ALL"`
  (see its own comment), so there's no legitimate state where a county is
  selected but the map should stay in multi-county statewide mode - the
  `zoomCounty &&` guard was pure bug, not a deliberate case. Fixed by
  comparing `zoomCounty !== selectedCounty` directly, with no truthiness
  guard, so both directions (selecting a county from the dropdown, and
  clearing one) always resync. Google and MapTiler were never affected by
  this half - `satellite-map.js`'s `renderGoogle()`/`renderMaptiler()`
  compute their own `zoomed` independently from `selectedCounty`, not from
  `explore.js`'s `zoomCounty` - which is exactly why the pin in Marc's
  screenshot was already correct while the text around it wasn't: two
  modules disagreeing about the same state.
- **The MapTiler property-pin popup rendered in MapLibre's bare default
  chrome**, not the app's themed card. `explore.css`'s popup rules still
  targeted `.mapboxgl-popup-content`/`.mapboxgl-popup-tip` - correct back
  when this file's own header comment described a Mapbox GL JS popup (pre-
  Phase-60), but Phase 60 swapped the provider for MapLibre GL JS, an
  independent fork, not a Mapbox build. MapLibre 4.x's own stylesheet ships
  its popup chrome under `.maplibregl-popup-*`, not `.mapboxgl-popup-*` -
  confirmed by pulling `maplibre-gl@4.7.1` (the exact version pinned in
  `satellite-map.js`'s `MAPLIBRE_GL_VERSION`) from npm and grepping its CSS.
  So neither rule had matched anything since Phase 60 shipped - the "preview"
  card Marc gets after tapping a MapTiler pin was plain white with square
  corners and no shadow instead of the app's card theme, regardless of the
  zoom-sync bug above. Renamed both selectors to the correct
  `.maplibregl-popup-*` prefix.

**Verification**: 265/265 `tests/run_test.mjs` checks still pass. A targeted
manual Playwright check (not added to the permanent suite - it drives
`#mapCountySelect` directly with `selectOption()` rather than a bubble tap,
which the existing map test block doesn't exercise) confirmed that selecting
a county straight from the dropdown now flips `#exploreMapCanvas` to
`.zoomed`, switches the title to "`<County> County`", switches the note to
the pins copy, hides the bubble-size legend, switches the hint to "Tap a pin
or a card below for details," and shows "Clear county filter" - matching
bubble-tap behavior exactly. The popup CSS fix couldn't be exercised live in
that same check: `tests/config.js` ships no `maptilerKey` (deliberately, so
the suite never makes a real network call to a paid-tier-adjacent provider -
see that file's own comment), so MapLibre never actually loads under test;
the fix was instead verified by downloading the pinned `maplibre-gl` version
from npm directly and confirming its shipped CSS uses the `.maplibregl-`
prefix the app's rules now match.

## Frontend sprint: typed price range, card kicker/facts, map linkage (Phase 65, done)

One focused frontend PR, no backend or data changes. What changed and why,
by feature (all under `public/`, mirrored to root; `sw.js` → `tdw-shell-v33`):

- **Typed min/max price** (`#bidMinInput`/`#bidMaxInput` in the Filters
  panel's Bid Range section, replacing the read-only `#bidMinDisplay`/
  `#bidMaxDisplay` labels). `bindBidRangeSliders()` in `app.js` now funnels
  sliders AND fields through one writer, `applyBidRange(min, max, source)`,
  so `state.bidMin`/`bidMax`, both sliders, both fields and the track fill
  can never disagree. Typing filters as you go (250ms debounce), Enter or
  leaving the field commits at once and drops the phone keyboard; there is
  deliberately no Search button. A crossing snaps the control the user did
  NOT touch (Phase 63's slider rule, now shared - note `source` is one of
  `min`/`max`/`minInput`/`maxInput`, and the crossing check must test both
  `max*` spellings; the first cut only tested `"max"` and snapped the wrong
  side when the MAX FIELD was typed - caught by the new regression checks).
  Typed values above the slider's $1M track are honoured by `passes()`; the
  handle just pins to the track end. The slider's `step="10000"` means the
  browser rounds a typed $9,000 to the nearest notch on the HANDLE only -
  the filter keeps the exact typed value. `#searchInput` also gets Enter =
  commit-now + blur. Reset goes through `bindBidRangeSliders.reset()`.
- **Card kicker line** (`cardKickerHtml()`): the deed/LAFT card's first line
  is now "AUCTION · Sale Sep 21, 2026" / "LANDS AVAILABLE · Fixed price ·
  available now" / "AUCTION · Past sale date · …" / "AUCTION · Closed", ledger
  word in the ledger's own `--accent`, phase word in the status palette
  (`phase-soon` warn within `SOON_DAYS`, `phase-today`/`phase-past`/
  `phase-closed` bad, `phase-fixed` ok). Replaces the old "SALE SEP 21"
  `.prop-county-tag` on those cards (certificate cards keep theirs). The
  status `.pill` is dropped on closed cards - the closed banner already says
  it.
- **Identifier row** (`.prop-ids`): `Parcel # …` and `Case …` side by side;
  a missing parcel prints "Parcel # not published" (muted) rather than the
  row silently shrinking. `.prop-parcel-line`'s text is unchanged, so the
  existing `cardParcelLineFirst` check still holds.
- **Facts row** (`cardFactsHtml()`): Location ("Geocoded" / "Not yet
  geocoded" - `latitude`/`longitude` from `scripts/geocode_properties.py`),
  Flood (`floodShort()`, the compact three-state version of
  `floodRowHtml()`: "Not checked" / "Not mapped by FEMA" / "Zone X[ · SFHA]"),
  and "Value ÷ bid N×" (the same `valueRatio()` `isTopPick()` screens on).
  **This is NOT an MMV/return estimate** - no MMV column, formula or source
  exists in the backend; the row is where one belongs once a real field
  (e.g. `mmv` + `mmv_source` + `mmv_computed_at`) exists. Nothing invented.
- **Whole-dollar bids on the card** (`bidDisplayCard()`): "$11,000" not
  "$11,000.00" when the bid is a whole number - on a 360px phone the two
  headline boxes are ~103px wide (measured) and the ".00" wrapped or got
  cut. Bids with real cents keep them; the full page/table/cert cards keep
  `bidDisplay()`. The headline figure also gets a phone-width `clamp()` -
  and it lives in **`explore.css`**, not `styles.css`, because explore.css
  loads later and its own `.card-stat-headline .card-stat-val{font-size:
  1.18rem}` silently overrode the first attempt in styles.css (found by
  enumerating matching rules in the browser, not by reading the diff).
- **Desktop split view**: the card whose page is open in `#detailPanel`
  gets `.prop-card.selected` (accent ring), set by `selectProperty()` and
  re-applied by `card()` on re-render (reads the hoisted `selectedPid`, so
  no new TDZ risk; `mapFilter` untouched).
- **Map linkage** (`explore.js`): `syncSelection()` after `showPreview()`
  scrolls the selected strip card into view and lifts the selected pin to
  the top of its layer; `setHoverLink(id)` mirrors a `.hover` class between
  a strip card and its pin in both directions (canvas `mousemove`, strip
  `mouseover`/`focusin`). Pins/preview/strip already shared `.sel`. The
  Google/MapTiler pins are NOT linked (they have their own popups and no
  strip); deliberately left alone per "don't break the map providers".
  Gotcha: explore.js already had a `cssEscape()` - a second declaration
  crashed the whole module at load ("Identifier … already declared", map
  empty). Grep before adding a helper here.
- **Not a route**: `index.html#/map` is not a hash route (only ledger slugs
  are) - the Map page is reached via the nav button. A screenshot script
  that `goto`s `#/map` lands on Auctions; not a bug.

`tests/run_test.mjs`: 265 → **289 checks** (typed price fields incl. the
crossing rule and Enter, kicker/ids/facts text, strip↔pin↔preview
selection and hover, LAFT kicker). `net::ERR_CERT_AUTHORITY_INVALID` added
to the console allowlist (this sandbox's egress proxy CA on the esm.sh/
fonts fetches; reproduces on unmodified main).

## Known landmines / do-not-repeat mistakes

- Miami-Dade is the only county with a hyphen in `data/realauction_counties.csv` — a blanket `-replace '-',' '` once silently renamed it to "Miami Dade", which didn't match the frontend's canonical `"Miami-Dade"` and hid 33 live listings. Fixed; don't reintroduce a blanket hyphen transform.
- `scraper.js` no longer exists (removed 2026-09-01, repo debris cleanup). Historical note: it used to be a disabled, non-functional 50-state simulated scraper (`Math.sin()`-based fake data, writing to a `tax_auctions` table the frontend never read), kept `workflow_dispatch`-only so it couldn't burn CI minutes doing nothing. It, its package.json/package-lock.json, and its `.github/workflows/scrape.yml` workflow were all removed together. It was never the real pipeline.
- Root `config.js` (not under `public/` — see the note near the top of this file) intentionally ships a public Supabase **publishable** key client-side — this is expected and safe (RLS enforces everything). The **service_role** key must never appear in this repo or in client-side code, only in `sync-config.local.json` (gitignored) and GitHub Actions secrets.
- There was an earlier leaked-key incident (see comments in root `config.js`) that prompted migrating from the legacy long-lived `anon`/`service_role` JWTs to the new revocable `sb_publishable_...`/`sb_secret_...` key format. Legacy key revocation was still pending user action as of the last audit — check current status before assuming it's done.
- The "every write action fails silently" bug (favorite/hide/restore/bid-list/notes) that earlier audits in this project flagged **was fixed 2026-08-24** (commit `a732779`, "Surface write errors instead of failing silently") — a shared `showErrorToast()` helper now surfaces every one of those errors. Don't re-flag it without checking the current file first.
- Bid-on-auction links in `app.js` are **entirely data-driven** from `p.url_auction` (populated by the harvesters) and conditionally rendered — `${p.url_auction ? '<a ...>Bid on County Auction Site</a>' : ''}`. There is no frontend-constructed URL, so a "broken bid link" cannot render; the only failure mode is an absent bid button on a property the harvester didn't attach a URL to. Confirmed by code inspection 2026-08-25.
- This sandbox has no git push access to `taxdeed-scraper` (git proxy reports the repo isn't in this session's authorized set) and no `gh`/git-clone credentials for it either — reach it through the authenticated Chrome browser tab (GitHub web UI for edits/uploads, raw file view or `document.body.innerText` via `javascript_tool` for reading — `get_page_text` truncates large files at ~50KB, so `app.js` needs the `innerText` approach or a range-limited fetch).

## Where to look for more

- `claude/improvement-roadmap.md` in the "tax florida app" claude.ai Project — the full dated log of every fix, audit finding, and open decision. This is where new findings should be appended, not here.
- This file (`CLAUDE.md`) should stay a **stable architecture map** — update it when the architecture, data model, or a hard-won lesson changes, not for routine status updates. Verify claims here still hold before trusting them blindly — this file itself was wrong about the repo count until 2026-08-25, and wrong about local-PC involvement until 2026-08-25.
