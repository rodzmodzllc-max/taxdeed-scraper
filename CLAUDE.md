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

**Correction, 2026-09-29 (SaaS hardening):** the section below describes the
Street View design. In production every stored `photo_url` today carries
`photo_source = 'usda_naip'` (an overhead USDA aerial from
`scripts/enrich_naip_imagery.py` / migration 011), and none is a Street View
still. The frontend labels imagery from `photo_source` (`PHOTO_SOURCE_LABELS`
in `app.js`) and never as "Street View" unless that column says so; `''`
means "checked, no stored image", not specifically "no Street View coverage".
Read the paragraphs below as the design of the Street View path, not as a
description of what the live images are.

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

## Property intelligence: at-a-glance summary, section nav, show-on-map (Phase 66, done)

Stacked on Phase 65 (branch `feat/property-intelligence`, PR based on
`feat/frontend-terminal-polish`, so its diff is only this work). Frontend
only; `sw.js` → `tdw-shell-v34`.

- **"At a glance" block** (`opportunitySummaryHtml()`), first section of the
  full property page for deed/LAFT rows: What (ledger + state, and the
  harvester source), Where (address or "No street address in listing",
  county/state, parcel, case), When (sale date + "in Nd" / today / past /
  LAFT "Available now" / closed outcome, coloured by urgency), Minimum bid
  (or "Not published"; the value ÷ bid ratio is labelled "screening ratio,
  not a return"), Value on file (just value + assessed, assessed alone, or
  "No county value on file"), Missing (`dataGaps()`). **No score, no
  estimate, no recommendation** - every cell is a field the row carries.
- **`dataGaps(p)`** - the honest list of what a row does NOT have, each
  wording tied to a backend-distinguishable state: parcel-only listing,
  parcel # not published, bid/price not published, no county value, sale
  date not scheduled (auction only), photo not checked (NULL) vs no Street
  View coverage (''), not yet geocoded, flood not checked vs not mapped by
  FEMA. Do not add a gap whose cause the backend cannot actually tell.
- **Section nav** (`detailNavHtml()`): sticky jump pills (Summary /
  Financial / Property / History / Risk & Legal / Map / Sources / Data)
  built by scanning the rendered body for `data-section` anchors, so only
  sections that exist get a pill. `detailSectionHtml()` grew an `id`
  parameter; the `jump` click action scrolls within the modal or the
  desktop side panel (both are their own scroll boxes). Gotcha: the modal
  body is a flex column with a max-height - a child with `overflow:auto`
  gets `min-height:0` there and was squeezed to a few pixels until
  `flex-shrink:0` was set on `.detail-nav` (and `.detail-hero-photo`).
  The nav sticks at `top:-1rem` with matching padding so scrolled content
  can't show through the scroll box's own top padding.
- **Show on the Map page** (`showOnMap()` in app.js, `data-action=
  "showonmap"` from the GIS card): closes the modal, clears the Map page's
  search/watchlist/ledger filters, sets `mapFilter.county`, stashes the id
  in `window.__tdwMapSelectPid` + dispatches `tdw:mapselect`, then
  `showPage("map")`. explore.js parks it in `pendingSelectPid` and
  `drawPins()` consumes it (`applyPendingSelect()`) once the county is
  zoomed and the strip exists - so the strip card, preview and (when
  geocoded) pin all select together. A stale id for a row not in the
  zoomed county is ignored, never mis-selected. Google/MapTiler untouched:
  they still zoom to the county via the same select change.
- **Selected pin halo** (`.pin-halo`, drawn in `drawPins()` only for
  `activeProp`).
- **Cards**: county + state now lead the kicker on every card
  (`Alachua, FL · Auction · Sale …`); last sale + legal description fold
  behind a `<details class="card-more">` ("More · last sale, legal
  description") - the `.prop-legal` element and its `title` stay in the
  DOM, so the one-line/clamp tests still pass; photo banner is 21:9 capped
  at 170px with a "Street View" caption (it IS a Street View still, per the
  photo pipeline); placeholder wording now distinguishes `photo_url` NULL
  ("Photo not checked yet") from '' ("No Street View coverage at this
  address") - text only, same bar, per the field's documented contract.
  `.icon-btn` gets a 32px hit area, `.prop-links a` / `.detail-btn` 36px.
- **Fixture** (`tests/vendor/supabase-stub.js`): p3 carries `photo_url: ""`,
  p6 carries a data-URI SVG placard labelled "FIXTURE PHOTO" (not a real
  property image) so the photo layout can be exercised and screenshotted.
- `tests/run_test.mjs`: 289 → **316 checks**.

## Map workspace: large stage, side intelligence panel, one selection across three basemaps, imagery ladder (Phase 67, done)

Stacked on Phase 66 (branch `feat/map-workspace`, PR based on
`feat/property-intelligence`). Frontend only; `sw.js` → `tdw-shell-v35`.

### The three basemaps, audited (all kept; none behave identically)

| | Outline (`explore.js`) | Google (`satellite-map.js`) | MapTiler (`satellite-map.js`) |
|---|---|---|---|
| Library | own SVG (`fl-counties.svg`/`tx-counties.svg`), same-origin | Google Maps JavaScript API (weekly), `AdvancedMarkerElement` | MapLibre GL JS 4.7.1 (unpkg) + MapTiler styles |
| Container | `#exploreMapCanvas` | `#satelliteMapCanvasGoogle` | `#satelliteMapCanvasMaptiler` |
| Size before / after | svg capped `min(76vh, 100vh-17rem)`, letterboxed in a card / fills the stage: `100vh - 8.6rem` desktop, 56-58vh phone | `aspect-ratio` box, `max-height:64vh` / fills the stage | same as Google |
| Default view | home viewBox; county = viewBox tween to county bbox | center FL/TX, zoom 5.6/5.1; county = `panTo` + zoom 10 | same numbers via `flyTo` |
| Markers | SVG bubbles statewide, teardrop pins zoomed | HTML bubbles/pins as marker content | HTML bubbles/pins as `maplibregl.Marker` |
| Clustering | one bubble per county (count), never per-parcel statewide | same | same |
| Selection before / after | `.sel` + halo (Phase 66) / same, plus it announces `tdw:mapselection` | none (InfoWindow popup on pin) / `.sat-pin.sel` + pan/zoom to ≥16 on the active basemap | none (Popup) / same as Google via `easeTo` |
| Satellite | no | `hybrid`; Streets = `roadmap` (imagery toggle) | `hybrid`; Streets = `streets-v2` |
| Static image API | no (own county-context mini-map instead) | Maps Static API (`maps/api/staticmap`) - REQUIRES that API enabled on the key's project; the Demo Key is testing-only | Static Maps API (`maps/{style}/static/{lon},{lat},{z}/{w}x{h}.png`) - on the free plan |
| Parcel / GIS layers | none (no parcel geometry in the backend) | none for US parcels | none (MapTiler cadastre does not cover the US) |
| Key | none | `googleMapsApiKey` | `maptilerKey` (origin-restricted) |
| Attribution | none required (own data) | rendered by the JS API / baked into static images (must not be hidden) | MapLibre `AttributionControl` on / baked into static images ("© MapTiler © OpenStreetMap contributors") |

No basemap can draw a parcel boundary, so no "parcel" toggle exists and
none is faked. Live tiles/static imagery could not be rendered in this
sandbox (egress blocked, fixture ships no keys) - Google/MapTiler were
verified to the "not set up yet" state and by code; first real check is on
the deployed site with the live keys.

### What changed
- **Workspace** (`index.html`/`tx.html` `#pageMap`): one toolbar row
  (title, search, county, ledger pills, watchlist, and the basemap toggle
  moved out of the old card head), then `#mapWorkspace` = `#mapStage`
  (`.explore-map.map-page-map`, the three canvases, an imagery toggle
  overlay, the hint/reset strip as a bottom-left overlay) beside
  `#mapSidePanel` (`.map-side-head` title/count, `#mapSideBody` with the
  county rail, legend, note, and the preview + strip injected by
  explore.js). `.map-page-head` and `.explore-map-head` are gone. Desktop
  is a `1fr | 380px` grid (420px ≥1600px) at `calc(100vh - 8.6rem)`; below
  1024px the panel flows under a 56-58vh stage.
- **Preview** (`showPreview()` rewrite): kicker / address / county-state,
  optional imagery, minimum bid + value on file, parcel/case/source,
  location (coords + "Center on map", or "Not yet geocoded"), flood, a
  `<details>` for the rest, "Full property page". Labels come from
  app.js's `previewFacts(p)` (passed on `tdw:maprendered` with
  `propertyVisual`/`hydrateVisuals`), so explore.js holds no label rules.
  Phone: the node is re-homed into the stage as a bottom sheet (collapsed
  = header + money + Details; `.expanded` = the rest). It was first built
  as a viewport-fixed sheet and covered the property list under the map -
  hence the re-homing (`previewHost()`).
- **One selection**: explore.js owns it. Google/MapTiler pins dispatch
  `tdw:pinselect` → `showPreview()`; every selection change dispatches
  `tdw:mapselection {pid, lat, lng, focus}` (+ `__tdwMapSelection` stash)
  → satellite-map.js marks `.sat-pin.sel` and, on the active basemap,
  pans (zoom raised to `SELECT_ZOOM` 16 only if lower). Provider popups
  (`showGooglePopup`/`showMaptilerPopup`) retained but unwired. Strip and
  pins now live in different columns, so delegated listeners and
  pin↔card lookups scope to `workspaceEl()` (`#mapWorkspace`), not
  `.explore-map` - the first cut selected nothing because of exactly that.
- **County zoom on a hidden outline map**: `countyViewBox()` used
  `getBBox()`, which is 0×0 while the SVG is `display:none` (Google or
  MapTiler showing) - so the strip/preview never appeared on those
  basemaps. `computeCentroids()` now caches `countyBoxes` and
  `countyViewBox()` falls back to them.
- **Imagery ladder** (`propertyVisual(p, cls)` in app.js, used by cards,
  the full page hero and the preview): 1 Street View still (`photo_url`)
  → 2 static satellite centred on the row's coordinates
  (`staticImageUrl()`: MapTiler first, Google second, only with coords AND
  a key; `loading="lazy"`; captioned "Satellite · <provider>"; an `error`
  steps down a rung) → 3 county context from the app's own basemap
  (`renderMinimapInto()`, IntersectionObserver-hydrated, county tinted,
  neighbours in frame, one dot; "Location in <county> County") → 4 the
  two-part placeholder ("Photo not checked yet · Not yet geocoded"). The
  preview skips rungs 3-4 (the map is the context there). Privacy: rung 2
  sends a row's coordinates to the provider per card in view - the same
  trade-off Marc accepted for the basemaps, now per card, default on when
  a key exists.
- **Fixture**: p5 (Charlotte) and p12 (Brevard) carry coordinates.
- `tests/run_test.mjs`: 316 → **368 checks**.

## Known landmines / do-not-repeat mistakes

- Miami-Dade is the only county with a hyphen in `data/realauction_counties.csv` — a blanket `-replace '-',' '` once silently renamed it to "Miami Dade", which didn't match the frontend's canonical `"Miami-Dade"` and hid 33 live listings. Fixed; don't reintroduce a blanket hyphen transform.
- `scraper.js` no longer exists (removed 2026-09-01, repo debris cleanup). Historical note: it used to be a disabled, non-functional 50-state simulated scraper (`Math.sin()`-based fake data, writing to a `tax_auctions` table the frontend never read), kept `workflow_dispatch`-only so it couldn't burn CI minutes doing nothing. It, its package.json/package-lock.json, and its `.github/workflows/scrape.yml` workflow were all removed together. It was never the real pipeline.
- Root `config.js` (not under `public/` — see the note near the top of this file) intentionally ships a public Supabase **publishable** key client-side — this is expected and safe (RLS enforces everything). The **service_role** key must never appear in this repo or in client-side code, only in `sync-config.local.json` (gitignored) and GitHub Actions secrets.
- There was an earlier leaked-key incident (see comments in root `config.js`) that prompted migrating from the legacy long-lived `anon`/`service_role` JWTs to the new revocable `sb_publishable_...`/`sb_secret_...` key format. Legacy key revocation was still pending user action as of the last audit — check current status before assuming it's done.
- The "every write action fails silently" bug (favorite/hide/restore/bid-list/notes) that earlier audits in this project flagged **was fixed 2026-08-24** (commit `a732779`, "Surface write errors instead of failing silently") — a shared `showErrorToast()` helper now surfaces every one of those errors. Don't re-flag it without checking the current file first.
- Bid-on-auction links in `app.js` are **entirely data-driven** from `p.url_auction` (populated by the harvesters) and conditionally rendered — `${p.url_auction ? '<a ...>Bid on County Auction Site</a>' : ''}`. There is no frontend-constructed URL, so a "broken bid link" cannot render; the only failure mode is an absent bid button on a property the harvester didn't attach a URL to. Confirmed by code inspection 2026-08-25.
- This sandbox has no git push access to `taxdeed-scraper` (git proxy reports the repo isn't in this session's authorized set) and no `gh`/git-clone credentials for it either — reach it through the authenticated Chrome browser tab (GitHub web UI for edits/uploads, raw file view or `document.body.innerText` via `javascript_tool` for reading — `get_page_text` truncates large files at ~50KB, so `app.js` needs the `innerText` approach or a range-limited fetch).

## FL LAFT reliability + TX OTC foundation (2026-09-29)

Implemented from the master LAFT / OTC / struck-off audit of the same day.
Full description: `docs/otc-inventory-model.md`. The stable facts:
- **Every LAFT harvester writes `out/harvest_laft_status.json`** via
  `scripts/laft_status.py` (COMPLETE / EMPTY / INCOMPLETE / FAILED per
  county; STALE / NOT_RUN are reader-side). A zero is EMPTY only with an
  explicit signal; otherwise INCOMPLETE. Brevard's procedural PDF and a
  realTDM zero (no empty phrase captured yet) read INCOMPLETE by design.
- **`scripts/laft_lifecycle.py`** (last `laft` job step) sets `last_seen_at`
  for rows actually read, closes rows absent from a COMPLETE / EMPTY county
  only, reactivates re-listed rows; the sync also sends `status='active'`.
  `sanity_check_laft.ps1` is `state=eq.FL` now.
- **Migrations 017 (OTC columns on `properties`, get_properties re-created
  from 013's list) and 018 (`county_source_registry` table) exist and are
  NOT applied.** The lifecycle script probes for 017 and degrades honestly.
- **`data/county_source_registry.csv`** is generated by
  `scripts/build_county_source_registry.py` (run it after editing a
  harvester CSV; a test pins the output). Candidates are never runnable;
  `harvesters/otc/gate.py` refuses everything not PRODUCTION_VERIFIED and
  the blocked vendors by name. No live Texas government adapter exists.
- `bid` still carries the legacy 0 sentinel; `purchase_amount` +
  `purchase_amount_kind` are the honest columns and `hasPublishedBid()`
  reads the kind first.

## State-extensible OTC framework (2026-09-29, code foundation only)

`harvesters/governance/states.py` is the one place a state is declared
(FL and TX; nothing else). `OtcRecord.validate()`, the registry validator,
`scripts/laft_lifecycle.py` (`--state`, default FL) and
`scripts/sanity_check_laft.ps1` (`$env:LAFT_STATE`, default FL) read it
instead of FL/TX literals; the frontend's three modules read one
state→assets table each instead of ternaries. `InventoryType` /
`AmountKind` carry values (POST_SALE, STATE_HELD_TAX_LAND,
ADJUDICATED_PROPERTY, QUOTED_ON_APPLICATION) that migration 017's
constraints do NOT allow - `DB_SUPPORTED_*` pins what is storable and
`to_properties_row()` / the lifecycle / the registry refuse the rest until
a future migration widens them. A generic, unconfigured ArcGIS layer
adapter exists (`harvesters/otc/adapters/arcgis.py`). No state beyond
FL/TX is registered, no registry row was added, no migration applied.
Full description: `docs/otc-inventory-model.md` section 11.

## Alabama onboarding foundation (2026-09-29, no state activated)

`harvesters/governance/states.py` registers **AL as a NON-production
state** (representable, never runnable) and defines the ten
`ACTIVATION_REQUIREMENTS`; `is_activated()` is what `otc.gate`,
`CountySourceRow.runnable` and `scripts/laft_lifecycle.py` consult, so a
registered-but-inactive state is refused before any request.
`data/county_source_registry.csv` carries five extra columns
(`publishing_unit`, `publishing_unit_name`, `amount_kind`,
`update_frequency`, `source_terminology`) and ONE Alabama row
(SEARCH_EVIDENCE_ONLY, TERMS_NOT_VERIFIED). Migration
`020_state_extensible_vocabulary.sql` is written and NOT applied.

## Alabama source implementation (2026-09-30, gated, not activated)

`harvesters/otc/adapters/alabama.py` is a real adapter for the Alabama
Department of Revenue source, configured from `ADOR_EVIDENCE`: the
agency's own page titles, URLs, query-parameter names and snippets as a
web search indexed them (the search page
`/property-tax/delinquent-search/`, the detail page's
`?ador-view-application=<CS number>`, the process page, two FAQs). That is
**still search-index evidence** - `revenue.alabama.gov` is egress-blocked
from the sandbox AND from the assistant's fetch tool, so no page was ever
read; every fixture under `tests/python/fixtures/alabama/` is SYNTHETIC.
Stable facts: identifier = the **CS Number** as published (leading zeros
kept; `identifier_shape()` counts, never rewrites); parcel separate; owner
name = the name assessed at sale to the State; amount always None +
`QUOTED_ON_APPLICATION` (the FAQ's own "price quote ... by application");
the CS Number cell's own link -> per-property `application_form`, else the
process page -> `purchase_instructions`, never a constructed URL;
`classify_outcome()` reports **nothing COMPLETE or EMPTY until
`parser_fixture_validated`**; `harvest()` refuses before the first request
unless `can_run()` (state activated AND source enabled/verified) allows.
`scripts/harvest_alabama_state_land.py` has a `--fixture` mode (no
network) and a live mode that exits 2 with zero requests today; it writes
its OWN status file (`out/harvest_alabama_status.json` - county names
repeat across states) and is wired into no workflow. `OtcRecord` gained
`owner_name`; `laft_lifecycle.py`'s gates and harvest-row reader are
state-scoped (`county_gates(state=...)`) and `amount_of()` keeps
`QUOTED_ON_APPLICATION` only once storable. Full ledger, what is not
verified, and the first live step: `docs/alabama-onboarding.md`.

## Arkansas and Louisiana adapters (2026-09-30, PR open, not activated)

Branch `feat/states-ar-la` (stacked on the production-readiness PR). Full
description: `docs/arkansas-louisiana-onboarding.md`. `AR` (Commissioner
of State Lands Post Auction Sales List - STATE publisher, county per
`?county=<NAME>` in the one observed shape, `POST_SALE`, tax due as
`OPENING_BID`, buyer page as `purchase_instructions`) and `LA` (East Baton
Rouge adjudicated-property open-data CSV - PARISH publisher,
`ADJUDICATED_PROPERTY`, no price, no purchase link, tax-roll values and
coordinates from the row) are registered NON-production states; both
adapters are search-index-evidence configurations with SYNTHETIC fixtures,
gated by `harvesters/otc/adapters/common.can_run` (state activation
first) and report nothing COMPLETE/EMPTY until fixture-validated.
`scripts/harvest_state_inventory.py --state AR|LA` runs fixtures; live
exits 2. `MachineFormat.CSV` (migration 020, unapplied). Registry: 112
rows (109 FL/TX unchanged + AL, AR, LA candidates).

## Production-readiness pass 1 (2026-09-30, PR open, migration 021 unapplied)

Branch `feat/production-readiness-1` (stacked on the Alabama adapter PR).
Full description: `docs/otc-inventory-model.md` section 16. Stable facts:
- `harvesters/governance/inventory_status.py` is the ONE lifecycle
  vocabulary (12 statuses, 4 bases); a result status is refused unless
  its basis is the source's own published wording. `scripts/
  inventory_status_writer.py` writes `properties.inventory_status*` and
  the append-only `inventory_status_observations` (migration 021, NOT
  applied; probed). The FL HTML/PDF harvesters write the lists' own
  'Sold To' rows as identities to `out/harvest_laft_sold*.json`.
- `scripts/laft_purchase_paths.py` + `data/laft_purchase_link_rules.csv`:
  the HTML harvester keeps each row's published links; a link becomes a
  purchase path only through an enabled, verified rule (none enabled).
  Evidence: `out/public/laft-link-evidence.json` (value-free).
- `scripts/auction_events_writer.py`: source-published outcomes via
  `SOURCE_OUTCOME_MAP` (empty; add a wording only after observing it on the
  source); winning bid / bidder / count stay forbidden.
- `scripts/unit_freshness.py`: per-county last attempt / last complete
  read / failure streak, back-off after 3 blocked failures (HTML harvester
  consults it), registry PATCH once 021 exists, Dashboard rows.
- `get_properties()` (021) appends the four status columns plus
  `field_provenance` and `otc_provenance`; the frontend renders them only
  when projected. `harvest_cache.PARSER_VERSION` -> 3. `sw.js` -> v46.

## SaaS launch-readiness hardening (2026-09-29, PR open, not merged)

Branch `feat/saas-readiness-hardening`. What it adds, and where to look:
- **Migrations, not yet applied:** `scripts/migrations/015_customer_write_privileges_and_account_deletion.sql`
  (customers read shared `properties`/`county_calendar` but can no longer
  write them; anon closed out of every customer and legacy table; trigger
  functions not callable by clients; `search_path` pinned; `delete_my_account()`)
  and `016_source_health.sql` (per-dataset health table). Both have static +
  live-Postgres tests (`tests/python/test_migration_015_*.py`, `..._016_*.py`)
  that apply the files verbatim to a scratch cluster when one is reachable.
- **Artifacts are evidence-only now:** every workflow uploads only
  `out/public/` (an `*-evidence.json` with hashes/counts/field names, never a
  row) and `out/private/` (OpenPGP-encrypted raw files, only when the
  `ARTIFACT_PUBLIC_KEY` repository variable is set). Without that variable
  no raw harvest and no restorable backup is retained anywhere - a launch
  dependency. `scripts/artifact_evidence.py`; `tests/python/test_artifact_privacy.py`.
- **Account lifecycle:** forgot-password (`resetPasswordForEmail`, needs the
  Supabase Redirect URLs allowlist), `PASSWORD_RECOVERY` handler, self-service
  deletion via the RPC, support/help modals (`supportEmail` in `config.js`,
  blank on purpose), "Sale event history" card from the Phase B tables
  (outcome always "Not tracked"), Dashboard "Data sources" and "Watchlist
  changes" panels (per-browser localStorage snapshot, no notifications).
- **Everything a person must set outside the repo** is in
  `docs/production-configuration.md`.

## OTC/LAFT enrichment foundation (2026-09-29, PR after #37)

Goal: raise the share of active FL/TX OTC-LAFT rows with source-supported
enrichment without inventing anything. Everything is a reusable pipeline
step; nothing ran against production in the PR. Full design in
`docs/otc-inventory-model.md` section 10.

- **`scripts/laft_source_fields.py`** (inside `laft_lifecycle.py`, every
  laft job): carries the list-published columns the PowerShell sync drops -
  `legal_desc`, `owner_name`, `assessed`, `certificate_no`, `homestead`
  (yes -> true only) and, once migration 019 exists, `escheatment_date` /
  `available_date` - onto the OBSERVED rows (COMPLETE/INCOMPLETE county
  only), matched by the sync's own `(state, source, county, case_no)`
  identity, fill-blank, one PATCH per row, counts-only logging.
- **`scripts/field_provenance.py`**: `properties.field_provenance`
  (migration 009, never written before) now holds one entry per column
  with the source and its evidence. Precedence: a blank takes any source;
  a stored value is replaced only by a strictly higher rank
  (`hand_research` > `county_list` = `fdor_nal` = `county_gis` >
  `vendor_listing`); equal rank never overwrites. `enrich_property_details.py`
  reads it, withholds accordingly and writes its own entries.
- **Identifier plausibility gate** (`laft_status.plausible_identifier`) in
  the PDF/HTML parsers: a parcel/case with no digit, over 40/60 chars or
  spanning a line break is not a property (the five junk rows in
  production: Volusia x3, Pasco x1, Escambia x1). Rejected rows are
  counted; a document whose every row is rejected is INCOMPLETE /
  PARSE_FORMAT_CHANGE, never EMPTY. `harvest_cache.PARSER_VERSION` -> 2.
- **`list_as_of`** read off the PDF text / filename
  (`laft_status.extract_list_as_of`), `source_published_at` from the
  document's Last-Modified - both written by the lifecycle's provenance
  PATCH; never the retrieval time.
- **FDOR enricher**: Hendry list-form normalization (verified production
  pair), ambiguous multi-feature matches skipped (`resultRecordCount=2`),
  parcel numbers redacted from public CI logs, summary counters
  (matched/written/unmatched/ambiguous/errored/withheld).
- **Migration `019_laft_list_dates.sql`** (NOT applied): `escheatment_date`,
  `available_date` + `get_properties()` recreated with them. The lifecycle
  probes for the columns and skips them until then.
- **Frontend**: "Inventory & Purchase" card on the full property page for
  every `laft` row (`inventoryCardHtml()` in `app.js`): inventory type,
  amount with its source label, certificate number, the 019 dates (only
  when the API projects them), source list / source document / purchase
  links kept distinct ("No online purchase link on file - the county list
  page is not a purchase mechanism"), publisher, last-read / list-as-of /
  document-dated lines. `dataGaps()` names a missing purchase link. No
  score, no badge, no estimate. `sw.js` -> `tdw-shell-v43`.
- **Not done, on purpose**: no LGBS retry, no blocked vendor, no TX CAD
  adapters (no verified government source for the 8 LGBS counties), TX
  `purchase_amount` stays NULL (017's rule), no purchase URL for any county
  (none verified), no FDOR rule for Citrus / Hillsborough / Indian River
  (unverifiable from this sandbox). Production backfill (the five junk
  rows, the first carry run) needs explicit authorization; the next
  scheduled laft/deeds runs perform the carry and the gate on their own.

## Three customer ledgers: Auctions / Available / Liens & Certificates (2026-09-30, PR open, migrations 020/021 unapplied)

Full description: `docs/three-ledgers.md`. The stable facts:
- **`harvesters/ledgers/__init__.py`** is the one mapping between
  `properties.source` (auction / laft / certificate), `ledger_type`
  (auctions / buy / lien), the harvest-side source ids (`SOURCE_LEDGERS`)
  and the customer names (Auctions / Available / Liens & Certificates).
  `harvesters/ledgers/domains.py` names each ledger's harvesters, status
  files, harvest files, syncs, lifecycle and close-out gate;
  `assert_isolated()` proves no file is shared between ledgers.
- **The registry carries every ledger's production sources** now (216 rows:
  the 109 FL/TX AVAILABLE rows unchanged + 47 FL auction, 32 FL LienHub
  certificate and 24 TX RealAuction sources, generated from the harvesters'
  own CSVs) with a `ledgers` column. `expected_harvest_units()` is scoped
  per ledger (default AVAILABLE); tests that count "FL production rows"
  must scope to a ledger.
- **`SOURCE_UNAVAILABLE`** is a reader-side laft_status state (FAILED with a
  TRANSPORT_/PROXY_/ACCESS_ error category); it closes nothing.
- **Certificate statuses** (`certificate_listed` from list presence;
  `certificate_redeemed` / `_assigned` / `_expired` only from a source
  column) live in `inventory_status.py`; a certificate that left the list
  is `closed`, never a result. `INVENTORY_STATUS_LABELS` in app.js carries
  the same keys (a test pins them equal).
- **Frontend**: nav entries per ledger (`data-page="auctions"` +
  `data-ledger`, lit by `syncLedgerNav()`), certificate status lines
  (`certStatusLinesHtml`), same-parcel records across ledgers
  (`relatedRecordsFor` - exact state/county/parcel match only), per-ledger
  freshness on the Dashboard (`ledgerFreshnessSummary`, grouped
  `unitFreshnessRowsHtml`). `sw.js` -> `tdw-shell-v47`.
- **Arizona** (`harvesters/otc/adapters/arizona.py`, Maricopa State CP
  liens) is registered, fixture-driven, gated, not activated - the first
  LIENS & CERTIFICATES source outside FL. No TX certificate ledger exists or
  was invented; MS / WV have no adapter.

## AVAILABLE commercialization (2026-09-30, PR open, migration 022 unapplied)

Full description: `docs/available-ledger.md`. The stable facts:
- **Source-level publication gate** (`harvesters/governance/publication.py`):
  one decision per registry source - APPROVED / APPROVED_GRANDFATHERED /
  UNREVIEWED / RESTRICTED / BLOCKED - validated against governance
  (APPROVED* needs governance ok AND production-verified; legal review is
  at most RESTRICTED; blocked vendors are BLOCKED; a government website is
  never automatic permission). Registry columns `publication_status`,
  `restrictions`, `purchase_path_mode`, `purchase_path_evidence`.
  `scripts/publication_gate.py` (laft job, non-blocking) writes
  `out/public/publication-gate.json` (decisions + the AVAILABLE measurement:
  observed / publishable / restricted / unreviewed / blocked / unclassified /
  unavailable-source / with-without purchase path / stale) and, once
  migration 022 exists, propagates `properties.publication_status`. The
  frontend withholds non-APPROVED rows from list, counts, map and export
  and prints "N records withheld" (`WITHHELD`, `isPublishable`); NULL keeps
  today's behaviour.
- **Migration 022** (`022_available_publication_gate.sql`, NOT applied):
  registry publication columns + `last_error_category`,
  `properties.publication_status`, `inventory_status_observations.transition`,
  `get_properties()` re-created from 021's list with `publication_status`
  APPENDED. It is the only new functionality that needs a production step.
- **Purchase-path modes** (`laft_purchase_paths.PURCHASE_PATH_MODES`) and
  URL trust (`untrusted_reason`: http, homepage, list/document page, search
  engines, blocked vendor domains, search-results pages). Every FL
  production source carries mode `unknown` (blank) - nothing verified, no
  page read; the lifecycle propagates a registry-stated non-URL mode into
  `otc_provenance.purchase_path_mode`.
- **Lifecycle transitions** (`inventory_status_writer.plan`): newly_observed /
  status_changed / removed / result_published; sent to the history table
  only once 022's column exists. Absence is `removed` → closed, never sold.
- **Enrichment**: `fetch_county_batch` fills a county's slice from Available
  rows first, then the rest, deduplicated, capped. **Freshness**:
  `unit_freshness.public_report` adds `backoff`, `stale` (36 h),
  `source_unavailable` per unit and per ledger.
- **Frontend**: Available-only filter row (`#availableFilters`: purchase
  path, amount kind, availability status, acreage min, read in the last 14
  days), availability-evidence block + published / derived / not-published
  legend on the provenance card, Available facts in the Map preview,
  freshness bits (source unavailable / no complete read in 36 h / back-off).
  `sw.js` -> `tdw-shell-v48`.

## AVAILABLE commercial release (2026-09-30, migrations 021/022/023 APPLIED)

Full description: `docs/available-ledger.md` section 8. The stable facts:
- **Production state changed this sprint, with the owner's explicit
  authorization**: migrations 021, 022 and 023 are applied
  (`021_inventory_status_provenance_freshness`,
  `022_available_publication_gate`, `023_available_commercial_release` in
  Supabase's migration list); 020 is still NOT applied. `get_properties()`
  now ends `... publication_status, purchase_path_type, purchase_path_scope,
  purchase_path_evidence, purchase_path_observed_on, result_amount,
  result_date, result_party`. `properties.publication_status` is
  APPROVED_GRANDFATHERED on every FL / TX laft row of a production source
  (propagated from the registry; unknown sources stay NULL, never
  approved by omission). `public.source_publication_reviews` exists
  (admin read / insert, service_role read).
- **`harvest-and-sync.yml` has a `job` selector** on manual dispatch (all /
  deeds / certificates / laft / texas / backup). Dispatch `job=laft` for the
  normal AVAILABLE path; never dispatch `all` or `texas` unless LGBS is
  meant to run. Schedules unchanged; texas is never scheduled.
- **`scripts/purchase_path_engine.py`** is the only writer of
  `purchase_path_type` / `_scope` / `_evidence` / `_observed_on` (ten
  types; refusals for search engines, homepages, guessed patterns,
  blocked vendors, unverified third parties, list / document pages).
  Evidence tables `data/purchase_path_evidence.csv` and
  `data/outcome_column_rules.csv` ship EMPTY - no county page has been
  read from this repository, so every FL production row stays "not yet
  evaluated". Do not add a row without a verified observation.
- **`scripts/outcome_ingest.py`**: result date / amount / party only
  through an enabled rule; party only when `party_permitted`. Absence is
  never a result. `inventory_status_writer` names `reactivated` (023 only)
  and carries result fields once 023 is probed.
- **Admin publication panel** (`refreshAdminPublication`, `#adminPublication`)
  writes append-only reviews; `publication_gate.py` applies the latest
  VALID one per source (`apply_reviews`, validated by
  `publication_problems`) and writes it back to the registry table.
- **Frontend**: `availableDecisionHtml` (eleven questions, section id
  `decision`), `inventoryHistoryHtml` / `hydrateInventoryHistory`, typed
  path labels `PURCHASE_PATH_TYPE_LABELS`, filters `availLandUse` /
  `availGeocoded` / `availValues`, published-fields Available export
  (`availableCols`). Fixture p15 (Citrus) is the typed-path row; p3 stays
  untyped. `sw.js` -> `tdw-shell-v49`. `tests/run_test.mjs` supports
  `DUMP_RESULTS=<path>` to read a new check's real value before pinning.

## Customer value / evidence acquisition (2026-09-30, PR open)

Full description: `docs/available-ledger.md` section 10. The stable facts:
- **`scripts/capture_purchase_evidence.py`** runs as the manual-only
  `evidence` job of `harvest-and-sync.yml` (`job=evidence`): a value-free
  capture (titles, headings, vocab links, digit-free sentences, phones,
  e-mails, HTTP status) of every FL AVAILABLE production source, printed
  as a digest into the job log. It never writes to the database. Artifact
  downloads are blocked from the sandbox - read the digest from the log.
- **`data/purchase_path_evidence.csv` carries fifteen verified FL rows**
  (Brevard, Calhoun, Citrus, Clay, Dixie, Franklin, Hernando, Leon, Levy,
  Madison, Orange, Pasco, Sumter, Taylor, Volusia), every one quoting the
  source's own page / document with `evidence_url`, `source_title`,
  `instructions`, `review_state=verified`, observed 2026-09-30. Add a row
  only from a capture you have read; a row without a verified review
  state and an https evidence page is never applied
  (`EvidenceRow.applicable`). Path provenance
  (`purchase_evidence_url/_type/_title`, `purchase_instructions`,
  `purchase_path_observed_on`) rides in `otc_provenance`.
- ~~RealAuction past-sale pages are a login wall~~ - **corrected
  2026-09-30**: that test read only the page shell (which always carries a
  login form); the results are served anonymously by AJAX. See "Verified
  auction outcomes" below.
- Frontend: Available thirteen questions, Auction seven, Certificate six
  (`auctionDecisionHtml` / `certificateDecisionHtml`), cross-ledger
  current / previous (`relatedWhen`, `crossLedgerSummary`), DOR use-code
  land-use fallback, per-ledger exports (`certificateCols`). `sw.js` ->
  `tdw-shell-v50`. `tests/run_test.mjs`: 645 checks; Python: 1354.

## Unified navigation: Dashboard | List | Map | Watchlist (2026-09-30, PR open)

Full description: `docs/navigation.md`. The stable facts:
- **Exactly four primary destinations** in the rail and the phone bottom
  bar (`data-page` dashboard / list / map / watchlist, identical on both
  pages); the three ledgers are picked INSIDE the List (`#ledgerTabs`) and
  the Map (`#mapLedgerPills`, "All Ledgers" + the three), never in the
  primary nav. `SHELL_PAGES` = dashboard / list / map; `#pageAuctions` is
  now `#pageList`; `showPage("auctions")` still works.
- **Hash routes** (`routeFromHash()` / `syncPageHash()`, replaceState only):
  `#/dashboard`, the ledger slugs (`#/auctions|lands|certificates[/pid]`,
  the List's own routes, unchanged), `#/list`, `#/map?ledger=&county=&q=&watch=1`
  (context, not routes per combination), `#/watchlist`; legacy `#map` is
  rewritten to `#/map`. A self-back's hashchange is skipped
  (`suppressHashRoute`) - see the popstate comment before touching this.
- **State is the page**, never a hash parameter: `STATE_META` (FL, TX;
  keys pinned to `states.PRODUCTION_STATES` by
  `tests/python/test_unified_navigation.py`) feeds the ONE state control,
  the header's `#stateSelect` beside the account badge (global state
  context, 2026-09-30 - the List's FL/TX tabs and the Map's state select are
  gone). A switch navigates to that state's page carrying the route, minus
  a property id (`stateSwitchHref()`). Do not hard-code Florida anywhere.
- **Map county select is scoped to state + ledger** with that ledger's
  counts (`mapCountyCandidates()`); the context line `#mapContext` reads
  "State: · Ledger: · County:" from `renderMapContext()`.
- **Dashboard is an operating view** (`dashboardOps()`): per-ledger tiles,
  Needs attention, Recent ("not tracked" where no date exists), Verified
  purchase paths, counties, ledgers, upcoming, freshness, watchlist
  changes. No value-sum tile, no score.
- Watchlist folds the same parcel across ledgers into one card. `sw.js` ->
  `tdw-shell-v51`. `tests/run_test.mjs`: 713 checks; Python: 1364.

## Acquisition path (2026-09-30, PR open)

Full description: `docs/available-ledger.md` section 11. The stable facts:
- **Evidence record v3** (`purchase_path_engine.EVIDENCE_COLUMNS`, 25
  columns): office, address, phone, email, mailing_address, steps
  (" | "-separated), application_url, payment - all quoted from the
  evidence page, blank when not published. `acquisition_mode()` /
  `PurchasePath.channels` / `PurchasePath.acquisition()` →
  `otc_provenance.acquisition`; `laft_lifecycle.source_match_of()` →
  `otc_provenance.source_match` (case_no else parcel, the harvester's own
  read). No schema change.
- **The customer page answers "how do I acquire it" with the mode, the
  numbered steps, the documents and the contact block**; an offline process
  is a complete path. The gap wording is "Acquisition path not yet
  verified", never "no online link". `ACQUISITION_MODE_LABELS` in app.js
  mirrors the engine (a test pins them equal).
- **Headline metric** is `% of AVAILABLE rows with a verified actionable
  acquisition path` (`purchase_path_engine.measure()`), not URL coverage.
- `sw.js` -> `tdw-shell-v51`. `tests/run_test.mjs`: 661 checks; Python:
  `tests/python/test_acquisition_path.py`.

## Acquisition coverage (2026-09-30, PR open)

Full description: `docs/available-ledger.md` section 12. Stable facts:
- `capture_purchase_evidence.py --follow`: one hop to tax-deed links
  present on the source page (no search / social / vendor hosts, max 6);
  per-parcel links (7+ digit runs) are never captured.
- `laft_lifecycle.carry_plan()`: rows not read this run keep and receive
  their verified evidence and deterministic match; a failed read never
  erases anything. The lifecycle reads every county with active rows.
- `data/purchase_path_evidence.csv`: 16 rows (Marion added,
  `amount_plus_costs`, no phone - the page does not attribute one).
- `measure()`: `with_complete_record` is the commercial headline; a typed
  mode alone is not complete. `sw.js` -> `tdw-shell-v52`.

## Verified auction outcomes (2026-09-30, PR open, no migration)

Full description: `docs/auction-outcomes.md`. Stable facts:
- **RealAuction is NOT a login wall for results.** The sale-day page shell
  carries a login form; the items arrive by AJAX. `AREA=C` ("Auctions Closed
  or Canceled") and the page's own status refresh (`FNC=UPDATE&ref=<ids>`)
  are served to the same anonymous session the harvester uses
  (`scripts/realauction_results.py`).
- **`data/auction_outcome_wordings.csv`** is the only path from a published
  wording to a result (Auction Sold / Redeemed / Redeemed After Sale /
  Canceled per County / Canceled per Bankruptcy, each citing a capture run).
  Unmapped wordings stay "Outcome not yet verified" with the wording quoted.
- **`scripts/auction_outcomes.py`** (deeds job step + manual `job=outcomes`):
  exact case-number match (published parcel must agree), migration-014
  columns only, append-only `feed='closed'` observations, a failed read
  writes nothing, never touches `properties`. Purchaser, bidder count and
  bidder identity are never stored; `winning_bid` only beside "Amount".
- Frontend: `auctionOutcomeState` / `eventOutcomeState` / `outcomeProvenanceText`
  / `auctionAvailableRelation` in app.js; `sw.js` -> `tdw-shell-v53`.
- Capture logs are public: every attribute value and digit is masked before
  printing (`mask_text`); never print a raw href from a county page.

## State expansion: Louisiana activated (2026-09-30, PR open)

Full description: `docs/state-expansion.md`. Stable facts:
- **Production states are FL, TX, LA** (`states.PRODUCTION_STATES`). LA's one
  source is East Baton Rouge Parish's open-data "Adjudicated Property" list
  (Public Domain), approved by the owner **as a dated list only**: every
  row's `list_as_of` is the dataset's own `rowsUpdatedAt` (2024-02-27 when
  approved) and the frontend never calls an `ADJUDICATED_PROPERTY` row
  "available now" (`isDatedList()` in app.js). The harvest refuses a run
  whose metadata licence is no longer PUBLIC_DOMAIN.
- **Migration 020 is APPLIED** (2026-09-30): POST_SALE / STATE_HELD_TAX_LAND /
  ADJUDICATED_PROPERTY and QUOTED_ON_APPLICATION are storable; the storable
  sets in model.py / county_source_registry.py / laft_status.py include them.
- Adapter records reach `properties` through `scripts/sync_state_inventory.py`
  (activated state + production, approved source + a COMPLETE/INCOMPLETE
  read, or nothing). Louisiana runs as four `continue-on-error` steps at the
  end of the `laft` job; no schedule changed.
- A third state page is: `<state>.html` (data-state), a basemap SVG with
  `data-county` names, rows in `STATE_META` / `MINIMAP_PROJ` (app.js),
  `STATE_ASSETS` / `PROJ` (explore.js), `STATEWIDE_VIEW` (satellite-map.js),
  `county-centroids.json`, `sw.js` SHELL + navigate fallback, the mirror
  `FILES` list and the CI importmap injection (playwright-test.yml); the
  header `#stateSelect` lists it automatically from `STATE_META`.
  `STATE_META[...].unit` ("Parish") drives `UNIT_WORD`. `sw.js` ->
  `tdw-shell-v56` (combined with the global state header).
- AL / AR / AZ stay gated (source moved / no table / CSV host unresolvable,
  and no reviewed reuse permission); MN county ArcGIS layers were found but
  not approved. `scripts/capture_state_sources.py` is the value-free live
  capture for candidate sources (manual `job=evidence`,
  `evidence_scope=state_sources`).

## Six-state expansion: MI, WY, SC, CO, WI (2026-09-30, PR open)

Full description: `docs/six-state-expansion.md`. Stable facts:
- **Production states are FL, TX, LA, MI, WY, SC, CO, WI.** WV and UT are
  registered and gated: WV's inventory is behind a client-script flow and the
  Auditor's terms grant no reuse right; UT has no inventory until May 2027.
  The new states' county sources publish no explicit reuse licence. The
  owner approved each for publication on 2026-09-30, recorded in the
  registry `restrictions` column and `states.EXPANSION_EVIDENCE`.
- **Configuration only: `harvesters/otc/adapters/expansion.py`.** The shared
  adapters run everything. `arcgis.py` gained the property fields a layer
  publishes, `land_value` / `improvement_value`, a published sold flag, and
  an opt-in `centroid` derived from the layer's own polygon. `tabular.py`
  gained label → several fields, required / forbidden headers, the source's
  empty statement, "N/A" cells treated as no value, and `past_listing`.
- **Runner and sync:** `scripts/harvest_expansion.py` is one runner for every
  state (gate → COMPLETE / EMPTY / FAILED per county → de-dup →
  purchase-path engine on active rows only). It reads county pages with
  browser headers. `sync_state_inventory.py --close-absent` sets `closed`
  only after a COMPLETE or EMPTY read; absence never means sold.
- **Amounts:** an auction amount of unstated kind (Albany WY `TOTAL`) is
  never `min_bid`. It keeps `purchase_amount` + `PUBLISHED_AMOUNT_KIND_UNSPECIFIED`,
  and app.js labels it via `amountWord()`. Eaton MI's own "Has Been Sold"
  flag closes a row. Green WI's Previous Sales rows are closed, with a
  result only where the county published a Sale Price.
- **Field mappings follow MEASURED fill rates, not metadata.** Run
  `scripts/probe_field_fill.py`, the manual `job=evidence` with
  `evidence_scope=field_fill`: per field, the filled count out of a sample,
  never a value. York SC's older attributes (OWNNAME, LOCDESC, lat/lng) are
  empty; its CAMA block is full.
- **Statewide enrichment factory:** `harvesters/enrichment/`, run by
  `scripts/enrich_statewide_parcels.py`. Deterministic (county, identifier)
  match only. Provenance source `statewide_parcel` (rank 2).
  - `co_oit_public_parcels`, matched on account. Morgan County's features
    carry only owner, situs, subdivision and zoning; its values are empty.
    The State says resale is forbidden, and the owner approved display.
  - `ut_ugrc_lir_saltlake`, CC BY 4.0, registered; the state is not
    activated.
- **Acquisition evidence** for these states lives in
  `data/purchase_path_evidence_expansion.csv`, never mixed into Florida's
  table. It has two rows: Morgan CO (`quoted_amount`) and Green WI (bid
  form, `application_download`).
- **Frontend:**
  - `scripts/build_state_basemap.py` builds the county SVG and centroids
    from us-atlas and prints the exact projection.
  - `scripts/build_state_page.py` builds `<st>.html` from tx.html (use
    `--check` to confirm the pages are current).
  - Each state gets one row per state table, and per-state ledger copy lives
    in `EXPANSION_LEDGER_COPY`. `STATE_META.marketLabel` / `.assessedLabel`
    name values as the source does.
  - The sw.js offline fallback serves any precached state page.
    `sw.js` → `tdw-shell-v57`.
- **Workflow:** the `expansion` job is a matrix over MI, WY, SC, CO and WI in
  the existing 12:00 UTC slot, or dispatched with `job=expansion`.

## Five-state enrichment: MI, WY, SC, CO, WI (2026-10-01, PR open, no migration)

Full description: `docs/five-state-enrichment.md`. Stable facts:
- **Sync stamps freshness and provenance.** `sync_state_inventory.py` sends:
  - `last_seen_at`;
  - `first_seen_at`: stored for existing rows, the run's time for new ones. It must be sent, because `properties_seen_order_check` rejects an insert whose `now()` default lands after `last_seen_at`;
  - list `field_provenance` (`county_list`), which keeps `statewide_parcel` entries.

  Keys are aligned per source, so another source never nulls an enriched column. Close-out sets `delisted_at`.
- **Inventory status:** `inventory_status.adapter_record_status` covers ArcGIS and tabular adapter rows.
  - Sold comes only from the source's own flag or a published price; absence means closed.
  - A superseded list is `unknown`.
  - The expansion job runs `inventory_status_writer.py` per state.
- **Publication is review-aware** (`scripts/source_publication.py`).
  - The harvest requests only APPROVED sources. Others print `GATED ... 0 requests`.
  - The sync writes only publishable rows.
  - Douglas CO (CC BY-SA 4.0) is APPROVED.
  - Dane WI, Morgan CO deed auctions, Oconee SC and the WI V12 statewide parcels are UNREVIEWED: implemented, never requested.
- **ArcGIS cycle guard:** with `cycle_field` + `cycles`, a list for a past tax year reads EMPTY with signal `past_cycle` (Douglas tax sale list, tax year 2024).
- **Evidence capture:** `capture_state_sources.py --five-state*` is a value-free capture. Run it with `job=evidence` and `evidence_scope=five_state*`.

## Property-enrichment sprint (2026-10-01, PR open, no migration)

Full description: `docs/property-enrichment.md`. Stable facts:

- **Units are (state, county)** for the flood and NAIP backfills
  (`scripts/enrichment_units.py`, `ENRICH_STATE`).
- **Manual `job=enrich`** (input `enrich_states`) runs the flood / imagery /
  parcels backfill with larger budgets.
- **Storage is the binding constraint.** The free plan allows 1 GB, and
  `property-photos` held 967 MB. `enrich_property_photos_naip.py` refuses to
  upload past `NAIP_STORAGE_BUDGET_MB` (950), or when the total is unknown.
  Raising the quota or changing how imagery is stored is the owner's
  decision.
- **Factory additions** (`harvesters/enrichment/parcels.py`):
  - `row_id_column` (`parcel` / `case_no` / `certificate_no`);
  - `alt_id_fields`;
  - `transport="socrata"`;
  - `id_rule="numeric"`;
  - `latest_field`.

  One key that hits two different features is AMBIGUOUS, and nothing is
  written.
- **LA:**
  - `la_ebr_tax_parcels` (Socrata ei2c-krsr, Public Domain, exact
    `assessment_num` match).
  - The Parish Attorney's process is a verified evidence row; no vendor link
    is used.
  - The Louisiana lifecycle step needs a long budget: the laft job has 75
    minutes, and the step itself 45.
- **FL freshness:** `scripts/stamp_seen.py` stamps `last_seen_at` on
  auction and certificate rows read this run, after each PowerShell sync.
- **Not configured, and why:**
  - TxGIO StratMap: unreachable from the runners, and the land-parcel
    licence is unsettled.
  - Wyoming statewide parcels: disclaimer only.
  - Michigan county parcels: disclaimer / click-through licence.
  - York SC sale date: the source document returned 404.

## AVAILABLE acquisition paths as enrichment (2026-10-01, PR open, no migration)

Full description: `docs/available-ledger.md` section 13. Stable facts:
- **Publication = the source decision (`publication_status`) only. The
  acquisition path is ENRICHMENT** - never gate, withhold or hide a
  legitimate Available row because its process is not captured; show
  "Not yet verified" + the official availability source instead.
  `acquisition_gaps()` / `acquisition_state()` (`purchase_path_engine.py`,
  mirrored by `acquisitionGaps()` in app.js) MEASURE coverage;
  `publication_gate.py` reports `acquisition_coverage` separately from
  publication.
- **Texas has no lifecycle read** (LGBS is manual-only and never retried):
  `scripts/apply_acquisition_paths.py --state TX --source-id tx_lgbs`
  (laft job, no source request) writes the registry listing, the identity
  match and the verified county-level evidence row; a county without one
  gets listing + match only. `lgbs.com` is an untrusted purchase host - it
  is the listing, never the acquisition page.
- **Finding a county's process:** add official pages to
  `data/acquisition_candidate_pages.csv`, dispatch `job=evidence`,
  `evidence_scope=acquisition_candidates` (optionally `evidence_counties`),
  read the digest in the job log, then record a `verified` evidence row.
  A candidate is never a path.
- The lifecycle never writes NULL `list_as_of` / `source_published_at`.
- Frontend: `acquireBlockHtml()` (first section of an Available page;
  complete / partial / not-yet-verified), truthful CTA labels from
  `acquisitionCta()`. `sw.js` -> `tdw-shell-v62`.

## Customer monitoring (2026-10-01, PR open, migration 024 NOT applied)

Full description: `docs/customer-monitoring.md`. Stable facts:
- **Paged loading:** `fetchProperties()` pages `get_properties()` per ledger
  (`p_ledger_type` / `p_limit` / `p_offset`, 1,000 per call). PostgREST's
  max-rows applies to RPCs; before this, FL and LA were truncated at 1,000
  rows in the browser. The stub enforces the cap (`?maxrows=N`).
- **Migration 024** (`024_customer_monitoring_foundation.sql`) is written and
  live-tested. Applying it to production was declined this sprint.
  - It adds: change snapshots / events, `source_observation_runs`,
    `saved_searches`, `alert_preferences`, `user_alerts`, `product_events`,
    `count_properties()`, and an `id` tie-break in `get_properties()`.
  - New tables must `revoke all ... from anon, authenticated` before their
    explicit grants. Supabase's default privileges grant ALL otherwise; the
    live test caught customers able to write alerts.
  - Every frontend feature feature-detects these tables (`MONITOR.tables`).
- **`scripts/detect_property_changes.py`** runs after every sync step. Its
  first run is a baseline. Leaving a list is `removed`, never a sale. Without
  024 it keeps snapshots in the job cache and writes no database rows.
- **`scripts/saved_search_match.py`** and app.js `savedSearchMatches()` are one
  vocabulary in two implementations. `tests/python/fixtures/saved_search_cases.json`
  pins both; change them together.
- **Imagery priority:** Available, then active auctions, then closed auctions.
  Certificates get none. Deferred rows stay unchecked; the storage budget
  fails closed.
- **`scripts/state_launch_check.py`** (`--state XX` / `--all`) is the
  repository-only READY/BLOCKED launch check; `docs/state-launch-playbook.md`
  is the procedure.
- `sw.js` -> `tdw-shell-v63`.

## Image storage optimization (2026-10-01, PR open, no migration)

Full description: `docs/image-storage.md`. Stable facts:
- **Encoding:** stored NAIP imagery is same-size (600 × 450) WebP, quality 82
  (`scripts/image_storage.py`). An image is never replaced by a larger,
  undecodable or different-size file.
- **New images:** stored at `naip/v2/<sha256 of source>.webp`. Exact duplicates
  reuse one object.
- **Existing images:** re-encoded IN PLACE by `scripts/optimize_stored_images.py`
  (manual `job=storage`, `storage_mode` analyze / apply / apply_consolidate).
  - No `properties` row is written, because every UPDATE bumps `updated_at`
    (the app's "Last synced") through `touch_updated_at`.
  - Consolidating duplicates repoints rows, so it is opt-in.
- **Priority:** imagery goes to Available first, then active auctions. Closed
  auctions are deferred by policy. Certificates are never requested.
- **Budget and failures:** the 950 MB budget fails closed. Both NAIP steps are
  `continue-on-error`.

## Data-quality fixes before merge (2026-10-01, PR open, no migration)

- **Every whole-population REST read pages by id.** PostgREST's max-rows
  (1,000) caps any `limit`, so `scripts/laft_lifecycle.py` reads through
  `Api.get_all()` (`order=id.asc&limit=1000&offset`). Its old `limit=10000`
  read had matched only 1,000 of Louisiana's 10,334 rows. Never write a
  single read with a limit above 1,000.
- **FL certificate `last_seen_at`:** `stamp_seen.py --status` stamps only
  counties the harvester's status file marks COMPLETE / EMPTY. A missing
  status file stamps nothing. A one-object JSON (PowerShell's single-element
  array) is read as one row. The NULLs on 2026-10-01 were correct: LienHub
  returned 403 for all 32 counties on the only run since stamping shipped.
- **Texas is manual-only by design** (the `texas` job is dispatch-only; LGBS
  and TX RealAuction run nowhere else). `unit_freshness.MANUAL_ONLY_SOURCES`
  marks those units `manual_only` and never ages them by the clock. Their
  last read is never advanced. A test pins that set to the job's trigger.

## All-sources AVAILABLE enrichment engine (2026-10-01, PR open, no migration)

Full description: `docs/available-enrichment-engine.md`. Stable facts:
- **One source model:** `harvesters/sources` (`UnifiedSource`, `build_inventory()`)
  holds every source of all 13 registered states. Governance is APPROVED /
  REVIEW_REQUIRED / HARD_BLOCKED:
  - APPROVED writes customer fields;
  - REVIEW_REQUIRED is read for discovery only, never written from;
  - HARD_BLOCKED is never requested.

  `tx_lgbs` and `tx_realauction` are REVIEW_REQUIRED by their own rights
  audits; the registry's publication decision is unchanged. Known unused
  sources live in `data/enrichment_source_catalog.csv`.
  `public/source-inventory.json` is generated
  (`scripts/build_source_inventory.py`, test-pinned) and feeds the admin.html
  Sources panel.
- **Documents:** `harvesters/documents/extract.py`. It reads PDF text and
  tables, uses OCR only when tesseract exists, and reports `OCR_UNAVAILABLE`
  otherwise. Identifier matching is whole-token. Acquisition facts and
  notices come with page numbers.
- **Engine:** `scripts/enrich_available.py`, run as the manual `job=available`
  with `available_mode` plan / discover / apply. It covers every active
  AVAILABLE row and fourteen dimensions, and gives each gap one outcome:
  SOURCE_FOUND, SOURCE_REVIEW_REQUIRED, NO_SOURCE_FOUND, and so on. It builds
  the state × county coverage matrix. It never closes, hides or republishes a
  row.
- `ParcelSourceConfig.counties` scopes a layer to counties, and
  `sources.for_county()` returns the layers for one county.
  `enrich_statewide_parcels.run(..., cfg=, outcomes=)`.
- **Execution priority:** AVAILABLE customer value first, imagery last.
  - `available_mode=apply` runs the parcel / tax-roll layers and flood only,
    never NAIP.
  - Imagery is its own bounded `available_mode=imagery` slice (600 rows,
    about 40 minutes).
  - Never queue a long imagery run ahead of priority 1-2 work: the workflow
    has one concurrency slot and keeps only one pending run.
- `sw.js` -> `tdw-shell-v64`.

## AVAILABLE execution sprint (2026-10-01 / 02, PR #65, no migration)

Full description: `docs/available-enrichment-engine.md` section 9.

**Rule: map a column from the source's own definition.** Read it with
`available_mode=metadata` (`discover_sources.py --metadata`) before mapping.
The EBR Tax Roll's `units` counts structures; it is not acreage.

**`la_ebr_tax_roll`** (Public Domain, county-scoped):
- land use, taxable value and legal description;
- multi-year, so it uses the latest year only, with `latest_min` 2024;
- land use comes from 2023 through `column_year_floor`, because `structure_use` is blank from 2024 on;
- two different records in the year are AMBIGUOUS, and nothing is written for them.

**Parcel factory additions:**
- `conditional_map`, `no_value`, `provenance_attrs`, `latest_min`, `column_year_floor`;
- `enrich_statewide_parcels.run` updates the in-memory row after each write, so there is no stale-snapshot rewrite.

**`scripts/lgbs_available_refresh.py`** (apply mode):
- reads LGBS only, through the ingestion gate, and touches only TX laft rows;
- writes `last_seen_at` and `vendor_listing` attestations;
- never closes a row;
- `enrich_available.availability()` reports such rows as `OBSERVED_REVIEW_REQUIRED`, never as verified.

**Engine dimensions:** a `taxable` dimension was added. `acquisition_contact` now means phone, e-mail or an address; an office name alone does not count.

**Louisiana evidence row:** Parish Attorney office phone, P.O. Box, the Request to Purchase form and the memorandum's steps (capture run 36940992329). Staff e-mails are deliberately not recorded.

`sw.js` → `tdw-shell-v65`.

## Multi-state product branding (2026-10-02)

- **The product is never one state.** On every page, the sign-in / sign-up /
  reset screen reads "Tax Sale Property Intelligence" plus "Tax-sale,
  available-property, and lien/certificate research across supported states".
  The static `<title>` is "Tax Acquisitions — Tax Sale Property Intelligence".
  app.js names the selected state in the tab title only after sign-in.
- **State wording belongs to that state's own context**: ledger copy, the
  fees / statute copy on the FL page, and source names.
  - "Data sources (all states)" lists every state's datasets.
  - A registered state with no rows reads "No properties currently available
    for this state." It is never called unsupported.
- **Generated pages:** `scripts/build_state_page.py` no longer writes a
  per-state title or tagline.
- **A repository fix is not a deployed fix.** Cloudflare serves `main`.
  - `scripts/check_deployed_branding.py` reads what a signed-out visitor is
    actually served.
  - It runs as the `deployed-login` job of `playwright-test.yml`: the branch
    preview on a PR, and production (waiting for the build) on a push to
    main.
  - The sandbox cannot reach `*.pages.dev`; the job can.

## AVAILABLE multistate discovery (2026-10-02, PR open, no migration)

Full description: `docs/available-discovery.md`. Stable facts:
- **AVAILABLE comes only from a source that itself states availability**:
  - a lands-available list;
  - a Forfeited Land Commission list;
  - an over-the-counter list;
  - a land bank's inventory.

  Never from an auction row's absence, a passed date, or an unsold or
  unknown outcome. Auction and lien registry sources never count as
  AVAILABLE sources (`available_coverage.production_available_sources`
  requires ledger AVAILABLE).
- **Discovered candidates** live in `data/available_discovery_pages.csv` and
  `data/enrichment_source_catalog.csv` (REVIEW_REQUIRED / NOT_CHECKED, shown
  in the Admin Sources panel). They are NOT registry rows, and no harvester
  reads them.
- **Capturing them:** `job=evidence`, `evidence_scope=available_discovery`
  (value-free, no database).
- **Coverage file:** `harvesters/sources/available_coverage.py` →
  `public/available-coverage.json` (`scripts/build_available_coverage.py`,
  `--check` pinned by a test, mirrored to root). Rebuild it, and
  `build_source_inventory.py`, after editing the catalog, the discovery list,
  `data/available_state_research.csv` or the registry.
- **Frontend:** an empty Available ledger adds "Why this list is empty"
  (`availableCoverageHtml`, `AVAILABLE_COVERAGE_LABELS` pinned to `STATUSES`).
- **Service worker:** `sw.js` → `tdw-shell-v69` (v68 is held by PR #66).
- **First read (run 37010171899):** `data/available_discovery_evidence.csv`
  records each page's finding (CURRENT_INVENTORY / EMPTY / UNAVAILABLE /
  SEASONAL_NOT_POSTED / NOT_ESTABLISHED / AUCTION_ONLY / HISTORICAL), validated
  by `available_coverage.problems()`. Current lists: Georgetown and Spartanburg
  SC (identifier published), Lenawee MI (no identifier). AUCTION_ONLY pages
  (Aiken, Fairfield) lose the `availability` role. No adapter yet: no
  publication review. `--discovery` never prints a row-like line.

## SC AVAILABLE: Georgetown / Spartanburg FLC lists (2026-10-02, PR open, no migration)

Full description: `docs/sc-available-inventory.md`. Stable facts:
- **`harvesters/otc/adapters/sc_flc.py`** parses the live FLC PDFs, configured
  from read-only evidence runs 37033274319 (structure) and 37035908843
  (parser validation).
  - Georgetown: only a LAND row past SC's twelve-month redemption period is
    AVAILABLE (1 on the live list). MOBILE HOMES rows are personal property.
  - Spartanburg's list is a redemption-period bid ASSIGNMENT, so it is never
    AVAILABLE.
  - Identifier = TMS # / MAP NUMBER with whitespace removed, nothing else.
  - `harvest()` refuses before any request unless publication is APPROVED.
- **Publication reviews:** `data/available_publication_reviews.csv` (both
  sources REVIEW_REQUIRED) must agree with the catalog's governance.
  `available_coverage.problems()` enforces this, and APPROVED needs a
  published grant or recorded permission.
- **Evidence capture:** `job=evidence`, `evidence_scope=sc_available`
  (`scripts/capture_sc_available.py`). Structure and counts only; a privacy
  test feeds it PII and proves none reaches its output.

## AVAILABLE inventory sprint + collection vs customer publication (2026-10-02, PR #70, no migration)

Full description: `docs/available-inventory.md`. Stable facts:
- **Publication review is a customer release control, not a collection gate.**
  `source_publication.collectable(row, record_source)`: APPROVED* sources and
  AVAILABLE (laft) sources awaiting review are collected and synced, with their
  `publication_status` on every row; BLOCKED is never requested. Auction /
  lien sources keep the publishable-only rule.
- **Frontend:**
  - `isCustomerPublishable()` is the customer rule.
  - `isPublishable()` decides what this session shows: admins see everything (labelled), as does everyone when `config.js` `publicationMode: "preview"`; BLOCKED is never shown.
  - Source review status is labelled apart from availability (`sourceLineHtml`, `sourceReviewBannerHtml`, `sourceReviewHtml`).
  - Admin Dashboard panel: `#dashSourceReview`.
- **Five AVAILABLE sources, all UNREVIEWED:**
  - Detroit Land Bank lots;
  - Detroit Land Bank programs (Auction excluded);
  - Oceana MI Land Bank;
  - Horry SC FLC yearly workbooks;
  - Georgetown SC FLC PDF.

  The source's own program wording rides in `inventory_status_raw` for laft rows.
- **Horry redemption rule:** `sc_flc.list_year_past_redemption`. A year's list counts only from Jan 1 of year + 2. A PIN must match `id_pattern`.
- **Large counties:**
  - List groups page 50 cards (`LIST_PAGE`) and the table pages 200 (`TABLE_PAGE`). Both are declared at the top of app.js because of the TDZ.
  - Zoomed-county pins cluster above 250 in view (explore.js `PIN_CLUSTER_MIN`; satellite-map.js `clusterPins`), and the strip pages 100.
  - The stub's `?bigcounty=N` is the regression fixture.
  - The expansion job's timeout is 45 minutes.
- **Candidate pages:** `data/available_source_candidates.csv`, captured with `evidence_scope=available_sources`. `available_validate` runs the real MI/SC harvest with no credentials.

## Detroit customer subset + Available as the default ledger (2026-10-03, PR open, no migration)

Full description: `docs/detroit-customer-subset.md`. Stable facts:
- **A view stage, never a data change:**
  - collection -> admin (everything) -> verified structure -> deterministic ~50% -> publication gate -> customer.
  - Only the two Detroit Land Bank sources are in scope; every other source is never capped.
- **Verified structure:** only the source's own status "Marketed Structure For Sale"
  (`expansion.DLBA_STRUCTURE_STATUSES`, now read alongside the four lot statuses). The lot statuses are vacant land; the
  programs layer has no structure field.
- **Selection:** 32-bit FNV-1a of `"<source_id>|<parcel>"`, in the subset when `% 100 < 50`.
  - Python: `harvesters/otc/detroit_subset.py`. JS: `detroitSubsetStatus` in `app.js`.
  - Shared vectors in `tests/python/fixtures/detroit_subset_cases.json`.
- **Who sees what:**
  - Admins see every row, labelled "Not included in current Detroit customer subset" when outside it.
  - Preview and customers see only the subset, which still passes the publication gate.
- **Default ledger:** with no ledger in the URL, the List lands on Available when the state has Available rows; otherwise Auctions.
- **Registry:** the row is byte-identical. Its notes text still says "four lot statuses", unchanged on purpose.
## Acquisition-path semantics: offline forms are never "online" (2026-10-03, PR open, no migration)

Full description: `docs/available-publication-evidence.md`. Stable facts:
- A downloadable form is `application_download` at **source** scope, whatever
  its `purchase_url_kind`. That covers a PDF / Word / Excel file or a CivicPlus
  `DocumentCenter` item (`laft_purchase_paths.is_document_url`). It is never a
  `direct_property_url` and never a per-parcel link
  (`purchase_path_engine.type_and_scope`).
- Acquisition mode `bid` ("Bid application required - purchase process not
  online") applies to `bid_form` / `offer_form`. A document is `application`.
  `online` applies only to a real web page or checkout. The registry builder
  and validator use `mode_for_kind(kind, url)`.
- The frontend mirrors this:
  - `purchasePathOf()` shows a property-action kind at source scope, or a
    document, as the county's process;
  - `acquisitionOf()`'s type-only fallback follows the same rule;
  - `isDocumentUrl` is a hoisted function declaration (TDZ-safe).
- Path types stay the 023 CHECK set. Horry SC's county-wide FLC bid form is the
  regression case (`tests/python/test_acquisition_path_semantics.py`,
  `acqPathHorryDetail`).
- The five 2026-10-02 AVAILABLE sources stay UNREVIEWED. The doc records
  what is verified (the DLBA Vacant Land Policy) and what is search-index
  only.

## Boot resilience (2026-10-03, PR open, no migration)

After PR #72 deployed, production showed a black page, and no browser request
reached Supabase after 02:29 UTC. The deployed files run cleanly against the
stub, so the app module itself never started. The static
`import ... from "https://esm.sh/@supabase/supabase-js@2"` was a single point
of failure. If it fails or hangs, `#authGate` / `#pendingGate` / `#app` all
stay `hidden`, and the visitor sees an empty dark page.

- **`public/supabase-loader.js`** (app.js and admin.js use it, with top-level
  await):
  - esm.sh first, bounded by 8 s;
  - on failure, `supabase-js.umd.js`: the npm package's own 2.117.2 UMD
    build, unmodified, served same-origin (CSP `'self'`);
  - failures are pushed to `window.__tdwBootErrors`;
  - the test importmap still maps the esm.sh specifier to the stub.
- **`public/boot.js`:**
  - a classic script after `config.js` on every page (generated pages via
    `build_state_page.py`);
  - collects load and runtime errors;
  - after 15 s (`window.__tdwBootTimeoutMs` in tests), if no screen is
    visible, shows `#bootFailure` with Reload / "Reset app cache and reload"
    (unregisters the SW, clears caches).
- **Load order:** app.js is now an async module, so explore.js /
  satellite-map.js can run first. They already handle either order through
  the `__tdw*` stashes.
- **Workflow:** new top-level files must go in the mirror `FILES` list and in
  `DEPLOYED_BUNDLE_FILES`.
- `sw.js` -> `tdw-shell-v74`.

## get_properties narrow sort (2026-10-04, migration 025 written, NOT applied)

On 2026-10-04, Michigan (30,801 Available rows) and Louisiana (10,334) showed
"Couldn't load property data right now": every `get_properties()` page sorted
the state's FULL rows (~47 MB) before LIMIT/OFFSET, which took 2.76 s per
Michigan page and spilled ~95 MB to disk. With ~8 pages in parallel, the
pages hit the statement timeout.

`scripts/migrations/025_get_properties_narrow_sort.sql` sorts only
`(county, case_no, id)` in a CTE, then joins the page's full rows by id. In
production, read-only, that took 0.59 s. Signature, columns, STABLE,
`search_path`, grants and RLS are unchanged. Migration 024's DO block
recognises the definition and leaves it alone.

Rule: never ORDER BY full rows in a paged RPC over a large state; sort the
keys, then fetch.

## AVAILABLE expansion: MO, OK, PA, MN (2026-10-04, PR open, no migration)

Full description: `docs/available-expansion-2026-10.md`.

**Sources** (all UNREVIEWED: collected for admins, never customer-published until an admin review approves them):

| State | Source | Rows read live |
|---|---|---|
| MO | St. Louis LRA CSV (`Parcel_Status = Available` only) | 9,758 |
| OK | Oklahoma County county-owned list (suggested bid = `PUBLISHED_AMOUNT_KIND_UNSPECIFIED`; offline bid form) | 195 |
| PA | Fayette repository PDF (`Bid Received` excluded; dated 2025-10-07) | 376 |
| MN | Ramsey tax-forfeited layer (`Available for purchase` only) | 2 |

**Shared adapter additions** (`tabular.py`):
- `status_include` / `status_exclude`;
- `ColumnMap.land_use`;
- `parse_rows` / `pdf_table_rows`;
- `header_required` and the status column are enforced on every input path;
- runner kinds `csv` / `pdf_table` in `harvest_expansion.py`.

**Names and rules:**
- "St. Louis City" names the independent city apart from St. Louis County (`build_state_basemap.py --rename`).
- Owner columns are never mapped.
- Mississippi is deferred: no public source of record; the only GIS layer is a City of Jackson blight-project snapshot.
- `sw.js` → `tdw-shell-v75`.

## Shell redesign (2026-10-04, PR open, frontend only)

Full description: `docs/ui-redesign.md`. Stable facts:
- **Sidebar** (identical markup on every page): Home = `data-page="dashboard"`,
  Search = `data-page="list"`, one entry per ledger with `data-nav-ledger`
  (never `data-page` + `data-ledger`), Saved Searches / States & Counties /
  About as `data-nav` actions, Watchlist and Map as pages. On the List page the
  rail lights the ledger entry, not Search (`syncLedgerNav()`).
- **Global search** (`#globalSearchInput`) and Home search use the List's own
  `textMatches()` over the loaded, already-gated rows; Enter opens the List.
- **State picker** (`#statePicker`): counts only for the open state; other
  states get a `limit 1` existence probe per ledger (customers: customer-
  published rows only). Never a cross-state count - the Detroit subset is a
  browser-side rule a server count cannot apply.
- **TDZ:** render() runs during module init, so anything it reaches in the
  redesign section is a function declaration (e.g. `chipControlIds()`), never
  a top-level `const` - a `const` there aborted the whole module.
- The filters panel lives in `.auctions-body` (left column at >=1280px).
- `sw.js` -> `tdw-shell-v77`.
## Migration 026: properties access rule once per statement + page index (2026-10-04, APPLIED as version 20261004180726)

`scripts/migrations/026_properties_rls_initplan_and_page_index.sql`. Production's
only policy on `properties` ("properties: approved only", PERMISSIVE, ALL,
PUBLIC) called `is_approved()` per row; that function is VOLATILE +
SECURITY DEFINER, so it re-ran a profiles lookup and re-parsed the JWT claims
for every row a scan touched (production plan: `Filter: is_approved()` plus a
full sort). One deep Michigan page took 4.6 s; parallel pages crossed the 8 s
timeout.

026 does two things:
- `ALTER POLICY ... using ((select public.is_approved())) with check (...)`.
  This is an InitPlan, evaluated once per statement. The policy is never
  dropped, and its name, type, command and role are unchanged.
- An index on `(state, ledger_type, county, case_no, id)`, which is
  `get_properties()`'s page order.

Measured on a production-shaped local bench (PG16, production `auth.uid()` /
`is_approved()`): deep MI page 465 ms -> 44 ms; 8 concurrent deep pages
1,148 ms -> 213 ms. The authorization fingerprint for every role is
identical before and after.

Rule: wrap per-user helper calls in RLS policies as `(select fn())`.

Applied to production 2026-10-04 (version `20261004180726`, executable SQL
identical to this file). Measured in production as an approved customer:
deep MI page 4,494 ms -> 106 ms; every MI / LA page read back in the same
order with no row missing or repeated.


## Grouped search, cross-links, parcel timeline (2026-10-06, PR open, no migration)

Full description: `docs/search-crosslinks-timeline.md`. Stable facts:
- **Global search groups** (`gsGroups()`): States (another registered
  state → its page), Counties (open state's county → county page), My
  research (list name / saved property → My Research). Deterministic word
  matching; a digit-led query never routes to a state or county. Group rows
  are `.gs-row` options with sequential `gsOpt<n>` ids.
- **Parcel timeline** (`parcelTimelineFor`, section `timeline`): every
  dated fact for the record and the same parcel in other ledgers. A result
  only from `auctionOutcomeState().verified`; leaving a list is never a sale.
- `openDetail()` writes the hash with the property's OWN ledger slug.
- `sw.js` -> `tdw-shell-v104` (v103 is skipped - it was reserved for PR #112, which carries its own later version; v104 adds the phone Account sheet "Go to" group).

## Phone in "Desktop site" mode (2026-10-06, PR open, no migration)

A production phone screenshot showed the whole app laid out ~980px wide and
shrunk: unreadable text, the desktop toolbar on one row. The viewport meta is
correct on every page; Chrome's / Samsung Internet's "Desktop site" setting
(which an installed app inherits) ignores it, and no CSS can undo that.
`public/boot.js` detects exactly that case - `(pointer: coarse)` with no fine
pointer, a screen no wider than 600px, and the page laid out at least 1.6x
wider - and shows `#desktopSiteNotice` with how to turn the setting off, in
type scaled for the shrunken page; dismissal is per browser
(`tdw_desktop_site_notice_hidden_v1`). Real phones and desktops never see it
(Playwright block "Phone in Desktop site mode"). `sw.js` -> `tdw-shell-v105` (above the stack's v104; v103 is skipped).

**Imagery without coordinates (same PR).** A record with no stored image and
no coordinates used to show only the slim "Image not checked yet · Not yet
geocoded" bar (production FL on 2026-10-06: 21 active Available rows, e.g.
Escambia; MO / OK / PA / SC carry no coordinates at all). `propertyVisual()`
now draws that row's county from the app's own basemap behind the same two
lines (`.minimap-county`, `renderMinimapInto()` county-only: tinted, never a
dot). No request leaves the site. A real image for those rows still needs
coordinates (an authorized geocode / enrichment run). Playwright block
"Imagery without coordinates".

## Where to look for more

- `claude/improvement-roadmap.md` in the "tax florida app" claude.ai Project — the full dated log of every fix, audit finding, and open decision. This is where new findings should be appended, not here.
- This file (`CLAUDE.md`) should stay a **stable architecture map** — update it when the architecture, data model, or a hard-won lesson changes, not for routine status updates. Verify claims here still hold before trusting them blindly — this file itself was wrong about the repo count until 2026-08-25, and wrong about local-PC involvement until 2026-08-25.

## Available amount semantics (2026-10-05, PR #82, no migration)

Full description: `docs/available-amount-semantics.md`. Stable facts:
- **`amountInfo(p)` in app.js is the one description of an Available figure**
  (card, Home, Map strip / preview / popups, summary, decision, inventory,
  stats, table, export). States: official_current / official_expired / price /
  base / estimate / partial / vendor / unspecified / quoted / not_published.
  An opening bid / minimum is never "Purchase price"; RealTDM's figure is a
  "Base purchase price"; Texas LGBS is "Minimum bid (vendor listing)".
- **No tax amount owed is stored anywhere.** assessed / market /
  taxable_value are values; never derive a tax from them.
- **Florida opening bid (F.S. 197.502(6), 2026 text) already includes**
  certificates, delinquent / omitted / current taxes then due, interest,
  costs - and half the assessed value on homestead. Lands Available adds only
  interest, later years' taxes, doc stamps, recording (`FL_LAFT_ADDITIONS`).
  No "two years of taxes" rule exists in the statute or the clerks' pages.
- `fees()` no longer adds the homestead half (it was a double count) and
  returns null for Available rows.
- A clerk statement lives in `otc_provenance.purchase_statement` (total_due,
  valid_through, document_url, observed_on, publisher, components) with
  earlier ones in `purchase_statement_history`; past valid_through = Expired,
  never current. None is stored yet; the Pioneer statements are scanned
  images (OCR) with unestablished reuse permission.
- **Every state is source-aware** through `data/available_financial_terms.csv`
  (`harvesters/sources/available_terms.py` validates; `scripts/build_available_terms.py`
  renders `public/available-terms.json`, mirrored, `--check` pinned). app.js
  `termsFor(p)` picks the most specific row (state + source + county + status).
  Basis vocabulary: OFFICIAL_PRICE / PROGRAM_PRICE / OFFICIAL_TOTAL_DUE /
  OPENING_BID_PLUS_ADDITIONS / BASE_PRICE_PLUS_ADDITIONS / ESTIMATE /
  MINIMUM_BID / BID_SUBMISSION / OFFER_NEGOTIATED / PROPOSAL /
  QUOTED_ON_REQUEST / NOT_PUBLISHED. Application costs and deposits are never
  added to a price. Add a row only from a source actually read (quote +
  evidence + observed_on); rebuild the JSON after editing the CSV.

## Controlled paid beta: commercial layer (2026-10-05, PR open, migration 027 NOT applied)

Full description: `docs/commercial-layer.md`. Stable facts:
- **One access decision**: `entitlementFor()` (`supabase/functions/_shared/billing_core.js`)
  = `public.entitlement_for()` (migration 027); shared vectors in
  `tests/billing/fixtures/entitlement_cases.json`. Roles admin / tester /
  customer / inactive; precedence admin > tester > customer. Existing approved
  accounts are testers (`profiles.access_grant` default `tester`).
- **Frontend**: `ACCESS` + `viewerScope()` (`all` / `preview` / `enforced` / `paid`)
  in app.js (declared with `var` - TDZ). Without 027, `my_entitlement()` is
  missing and the approval record decides exactly as before. A customer never
  gets the tester preview: `isPaidBetaPublishable()` = APPROVED + in
  `commercial-scope.json`'s paid-beta set (fails closed).
- **Paid-beta scope is NOT the tester preview**: `data/paid_beta_sources.csv`
  -> `harvesters/governance/commercial_scope.py` -> `public/commercial-scope.json`
  (`scripts/build_commercial_scope.py --check`), seeded into
  `commercial_source_scope` by 027 (test-pinned equal). Paid beta = explicit
  APPROVED + provenance / lifecycle / financial / acquisition ok. Initially:
  la_ebr_adjudicated, sc_york_tax_sale, mi_lenawee_tax_sale,
  mi_eaton_treasurer_sale, wi_green_tax_deed_sales. Never approve a source to
  grow this set.
- **Stripe**: `stripe-webhook` (verify signature, idempotent per event id,
  stale-event guard; deploy `--no-verify-jwt`) is the only writer of
  `subscriptions`; `billing-checkout` / `billing-portal` take price and account
  from the server. A checkout redirect never grants access.
- **Billing ships off** (`config.js billing.enabled: false`); legal pages read
  `config.js legal.*` and show "not configured" for anything missing. Admin
  "Customers & access" shows e-mails only after "Show accounts".
- `sw.js` -> `tdw-shell-v81`.


## Investor beta (2026-10-05, PR open, no migration)

Full description: `docs/investor-beta.md`. Stable facts:
- **`public/acquisition-evidence.json`** (`scripts/build_acquisition_evidence.py --check`, mirrored) holds the county-level verified acquisition records from both evidence tables, built by the engine's own `resolve()`. Rebuild it after editing either evidence CSV.
- app.js `acquisitionProvenance(p)` fills a row's lost acquisition record from that file, only for the same state + source + county + path type; the row's own keys win. Every acquisition reader goes through it. Root cause fixed 2026-10-05 (see Investor conversion below).
- Usage events: `state_selected`, `county_selected`, `map_used`, `acquisition_section_viewed` and classified acquisition / form / source link opens go through `track()`. They are added to migration 024's CHECK list (024 is still NOT applied), and nothing is recorded until it is. `ACQ_VIEWED` is a `var` (TDZ).
- `sw.js` -> `tdw-shell-v82`.

## Investor conversion: Available (2026-10-05, PR open, no migration)

Full description: `docs/investor-conversion.md`. Stable facts:
- **`sync_state_inventory.py` merges `otc_provenance`.** PostgREST merge-duplicates replaces a jsonb column, so the sync reads back the stored dict and path columns (`stored_rows`). `merge_acquisition()` keeps verified acquisition evidence as a unit unless the new read is equal-or-richer for the same path type. It never uses another source's row and never mixes path types. An active row stating no path keeps the stored path columns. Pinned by `tests/python/test_acquisition_persistence.py`.
- **"How to acquire"** (`acquireBlockHtml`) is the Available page's first section and answers seven questions in order. Every answer comes only from the verified record or the row; otherwise "Not yet verified" or "not published". When no online path exists it says "No online purchase link on file".
- **Saved properties:** the existing watchlist renders `savedAcquisitionHtml()` under each Available card (method, amount, form, official links, plus `data-action="openacq"`). There is no second list.
- **Links carry `data-acq-link`** (form / instructions / source) for the funnel events. Every visible Available source must have a terms row (test-pinned).
- `sw.js` -> `tdw-shell-v83`.

## Independent ledger loading + list payload (2026-10-05, PR open, migration 028 NOT applied)

Full description: `docs/property-list-performance.md`. Stable facts:
- **The List paints from the active ledger's first page.**
  `fetchProperties(activeKey, onUpdate)` returns `{ready, done}`, and
  `loadAll()` awaits `ready` plus the small per-user reads only. Other
  ledgers, the auction-outcome index and the watchlist diff arrive in the
  background (`scheduleLedgerUpdate`, coalesced; counts-only while another
  ledger is on screen).
- **Per-ledger load state:** `LEDGER_LOAD[k]` moves idle / loading / partial
  / done / error.
  - A ledger still loading is never called empty. It shows `…` counts and
    `data-ledger-loading`.
  - A settled empty one starts with `LEDGER_EMPTY_HEAD`
    (`data-ledger-empty`).
  - "No properties currently available for this state" appears only when
    every ledger is settled.
- **List payload:** the List reads `get_properties_list()` (migration 028)
  and falls back to `get_properties()` on PGRST202.
  - List rows carry `provenance_scope: 'list'`.
  - `field_provenance` is reduced to the review markers.
  - `otc_provenance` drops only `purchase_instructions` and the ArcGIS
    internals; `acquisitionProvenance()` refills the instructions from the
    identical county record.
  - `openDetail` / `selectProperty` call `ensureFullProvenance(p)`
    (`get_property_provenance`, once per property).
- **Shared lists:** the stub's `LIST_OTC_DROPPED_KEYS` /
  `LIST_REVIEW_SOURCE_IDS` must equal the SQL (a test pins them). Never read
  a dropped key on a list surface.
- **Stub knobs:**
  - `?ledgerdelay=buy:ms` delays every page of that ledger;
  - `?tabledelay=table:ms` delays one table read;
  - `?nolistrpc=1` simulates 028 not being applied;
  - `window.__stubRpcLog` and `__stubProvenanceCalls` count the calls.
- `sw.js` -> `tdw-shell-v84`.

## Saved searches, saved properties, per-state county filter (2026-10-05, PR open, stacked on the performance PR)

Full description: `docs/saved-searches-and-properties.md`. Stable facts:
- **County universe:** `ALL_COUNTIES` is Florida's list only on the FL page.
  Elsewhere it is filled by `extendCountyUniverse()` from the loaded rows. A
  county filter is active whenever `state.counties.size < ALL_COUNTIES.length`,
  in every state.
- **Source filter:** `#sourceFilter` (`state.sourceId`) drives a new
  saved-search key, `source_ids`, matched on `source_id` else
  `harvester_source`. It is implemented in both app.js `savedSearchMatches`
  and `scripts/saved_search_match.py`; the shared cases pin both.
- **Saved searches:** rename and "Replace with current filters" record
  `saved_search_updated` (in 024's CHECK list; 024 still unapplied).
- **Watchlist:**
  - a status line per saved card (`savedStatusHtml`);
  - the watch snapshot keeps missing entries (`missing: true`), and the
    modal names them under `#savedMissing`, never removing them silently.
- `sw.js` -> `tdw-shell-v85`.

## First-run guide, touch targets, search while loading (2026-10-05, PR open, stacked on the saved-searches PR)

Full description: `docs/onboarding-mobile-search.md`. Stable facts:
- **Home guide:** `#homeGuide` (`homeGuideHtml` / `renderHomeGuide`) is five
  steps, every line built from loaded data; there are no scores or sample
  figures. It is hidden per browser by `tdw_home_guide_hidden_v1`.
- **Touch targets:** at ≤768px or on a coarse pointer, primary controls are
  ≥44px (end of `explore.css`). The Playwright `viewportSweep` checks:
  - no horizontal overflow at 390 / 768 / 1024 / 1280 / 1440 / 1920px;
  - those 44px targets at 390px.
- **Global search:** says "Still loading … results may grow" while a ledger
  is loading, or "may be incomplete" after a failed one. It refreshes from
  `scheduleLedgerUpdate`.
- `sw.js` -> `tdw-shell-v86`.

## Financial honesty across states (2026-10-05, PR open, stacked on the first-run guide PR)

Full description: `docs/financial-honesty-across-states.md`. Stable facts:
- **No-figure rows:** when a row has no figure but the source terms state
  the process, the display reads "Application required" / "Bid required" /
  "Quoted on request" (`NO_FIGURE_DISPLAY`). The state stays
  `not_published`.
- **One auction bid label:** `auctionBidLabel(p)` serves every surface.
  "Minimum bid" is used only for `MINIMUM_BID_SOURCES` (tx_lgbs, whose own
  field is `minimum_bid`); every other source reads "Opening bid". Michigan's
  list column is an opening bid, even though it is stored in `min_bid`.
- **"Just Value" is Florida-only** in `valueLabel()`.
- `sw.js` -> `tdw-shell-v87`.

## Acquisition checklist, source truth, county intelligence (2026-10-05, PR open, no migration)

Full description: `docs/county-intelligence.md`. Stable facts:
- **Acquisition checklist:** `acquireChecklist(p)` in app.js is fourteen items
  (`ACQUIRE_CHECKLIST_KEYS`). Each item is `known` / `not_published` /
  `not_verified`; item 14 lists the gaps. No default, no score.
- **Source health:** app.js `sourceHealthState()` is the same function as
  `unit_freshness.customer_health()`, pinned by
  `tests/python/fixtures/source_health_cases.json`.
  - States: CURRENT / RECENT / STALE / SOURCE_UNAVAILABLE / PARTIAL /
    NEEDS_REVIEW / MANUAL / NOT_RECORDED.
  - `checked_zero` (a complete read listing nothing) is never shown like an
    unreachable source.
  - The registry select now reads `last_error_category`.
- **County intelligence:** `harvesters/sources/county_intel.py` →
  `public/county-intelligence.json` (`scripts/build_county_intelligence.py
  --check`, mirrored). Rebuild it after editing the registry, either evidence
  table, the financial terms or a candidate file.
  - Coverage per ledger and the county state come from repository records.
  - SOURCE_UNAVAILABLE is only a runtime overlay in app.js (`countyIntelFor`).
  - Customers see unreviewed sources counted, never named.
- **Where it shows:** "Source truth" (`sourceTruthHtml`, section id `truth`) on
  every property page; the dossier modal `#countyModal` on every page (la.html
  hand-edited, the others generated from tx.html); a county-group link
  `.county-intel-row`.
- `sw.js` → `tdw-shell-v88`.

## Understood search, research queue, coverage explorer (2026-10-05, PR open, no migration)

Full description: `docs/investor-workflow.md`. Stable facts:
- **`parseNaturalQuery()`** maps the global search to the List's own filters
  (ledger, county, bid range, `acqState`). It uses rules only, no model.
  - A query starting with a digit stays a plain text search.
  - An understood reading with no matches falls back to the plain text.
- Every `track()` event must be in migration 024's CHECK list. A test pins
  this: an unknown event would switch tracking off for the session. New
  events: `search_interpreted`, `county_dossier_opened`.
- **Watchlist:** saved searches have Duplicate; the watchlist has a research
  queue (`researchQueueHtml`, never ranked).
- **State picker:** a coverage explorer (`coverageExplorerHtml`).
- **About:** "Why TaxDeed-Scraper" (`#whyList`). No competitor is named.
- **Layers:** a layer opened right after closing another uses
  `afterSelfBack()`, so the two `history.back()` calls cannot race.
- `sw.js` → `tdw-shell-v89`.

## TaxDeed-Scraper identity redesign (2026-10-05, PR open, frontend only)

Full description: `docs/identity-redesign.md`. Stable facts:
- **`public/identity.css` is loaded last** on index / tx / la and the
  generated state pages. It holds the design language: stone, charcoal and
  copper, with sage / rust / plum per ledger, serif display type, thin rules
  and squared tags. It is precached and in the mirror lists. Never
  reintroduce navy chrome or pill / card stacks: the test block
  "Identity redesign" checks for them.
- **Desktop navigation is a masthead:** `.nav-primary` (Home, Search, the
  three ledgers, Map) and `.nav-secondary` (Saved Searches, Watchlist,
  County Intelligence, About) inside `#navRail`. The ids and data
  attributes are unchanged.
- **Product name:** TaxDeed-Scraper. The tagline is "Public Property
  Acquisition Intelligence" (the `check_deployed_branding.py` TAGLINE).
  The legal pages and admin.html still say "Tax Acquisitions"; renaming them
  is the owner's decision.
- **Pages:**
  - Home has `#homeDesk` (`renderHomeDesk()`).
  - The auction ledger head has `upcomingSalesHtml()`.
  - On the property page, Source truth comes after the map.
- `sw.js` → `tdw-shell-v90`.

## Opportunity finder + auction command center (2026-10-05, PR open, no migration)

Full description: `docs/opportunity-finder.md`. Stable facts:
- **Evidence-first sorts** (`pathFirst`, `amountFirst`, `readRecent` in
  `SORT_COMPARATORS`, options in `#sortBy` / `#sortSecondary`): one criterion
  each, never a score. Keys cached per `sortRows()` call in `SORT_KEY_CACHE`
  (a `var` - TDZ).
- **Record badges** (`recordBadges(p)`): path / official / amount (Available
  only) / fresh (≤ 7 days) / dated. A fact or nothing; no weighting.
- **Auction command center** (`auctionCommandRows`, `upcomingSalesHtml`): next
  45 days of the filtered rows, per sale date + county; links only from
  `auctionLinkInfo()`; no deposit / registration / bidder terms (none stored).
- `sw.js` -> `tdw-shell-v91`.

## Final visual refinement (2026-10-05, PR open, frontend only)

Full description: `docs/final-visual-refinement.md`. Stable facts:
- **Ledger questions:** `LEDGERS[...].question` is shown in each ledger head,
  in the ledger's colour. The List page hides the repeated section `h2`
  visually only; it stays readable by screen readers.
- **Property page order:** identity → `detailStatusHtml()` (ledger / status /
  last read) → How to acquire → … → Risk & Legal (the FL lien-notes banner
  lives here now) → Map → Source truth → documents. Sections are numbered by
  a CSS counter.
- **Source truth rows** (fixed order): Source record, Last read, Source date,
  Publication status, Source health, Acquisition path / Sale process, Price /
  bid / Certificate amount, Official listing, County intelligence. Never add a
  score or a confidence.
- `sw.js` → `tdw-shell-v92`.

## AVAILABLE financial position + documents & links (2026-10-05, PR open, no migration)

Full description: `docs/available-financial-position.md`. Stable facts:
- **Financial position** (`harvesters/sources/financial_position.py` =
  app.js `financialPositionCore()`, shared vectors
  `tests/python/fixtures/financial_position_cases.json`). Parts: current
  acquisition amount, known tax obligation, known fees, other published
  amounts, application costs / deposit (always separate), and the total.
  A total is never computed: it is the source's current statement or
  "Not published". A value column is never a tax (a test greps for it).
- **Documents & links** (`harvesters/sources/acquisition_documents.py` = app.js
  `classifyAcquisitionLink()`, vectors `acquisition_documents_cases.json`):
  PURCHASE_LINK / FORM / INSTRUCTIONS / DOCUMENT / SOURCE_PAGE. A PDF is never
  a purchase link, and a non-https link is never shown.
- **Property page:** `data-section` `money` sits right after `acquire`, and
  `documents` sits right after `truth`.
- `sw.js` -> `tdw-shell-v93`.

## AVAILABLE imagery: rights, deterministic match, live NAIP (2026-10-05, PR open, no migration)

Full description: `docs/available-imagery.md`. Stable facts:
- **`harvesters/imagery`** is the one imagery decision. It holds:
  - the sources with `terms_status`: usda_naip APPROVED; MapTiler / Google static PROVIDER_DISPLAY; county orthoimagery REVIEW_REQUIRED; Street View BLOCKED;
  - the match method from `field_provenance.latitude.source` (never "nearby");
  - `naip_export_url()`;
  - the imagery priority, a coverage queue and never a score;
  - `coverage()`.

  app.js mirrors the constants (`naipExportUrl`, `IMAGERY_MATCH_LABELS`), pinned by `tests/python/fixtures/imagery_cases.json`.
- **Live NAIP rung** (`propertyVisual`, after a stored photo). It applies to a record with coordinates and `photo_url` not `''`:
  - the image is a USGS exportImage of a 0.0012° box centered on the record;
  - 400×300 on cards, 800×600 on the property page;
  - the request waits until the image is in view (`data-naip-src` plus `hydrateNaip`; native lazy loading never fired in this layout);
  - a failure is remembered per session and steps down a rung;
  - `config.js naipLiveImagery: false` switches it off, and the fixture is off;
  - CSP: `img-src https://imagery.nationalmap.gov`.
- **Source truth** has an "Imagery" row (`imageryTruthHtml`).
- `enrich_property_photos_naip.py` runs customer-visible counties first.
- `scripts/available_quality_report.py`: a counts-only quality and imagery report per state / source.
- `sw.js` -> `tdw-shell-v94`.

## Shared List / Map filters + acquisition method (2026-10-05, PR open, frontend only)

Full description: `docs/available-workflow-map.md`. Stable facts:
- **Shared filters:** `computeMapRows()` also requires `passes(p)` while
  `mapFilter.listFilters` is on (the default).
  - The toggle is `#mapListFilters`, injected beside the watchlist pill, with
    `lf=0` in the map hash when off.
  - The List's archive view is never applied to the Map.
  - `showOnMap()` turns the toggle off for a property the List's filters
    would hide.
- **`controlActive()`** ignores `[hidden].page` ancestors, so List filters
  count while the List is off screen.
- **Acquisition method filter:** `state.acqMode` / `#acqModeFilter`, read
  from `acquisitionOf(p)`. Available rows only. It is not in the saved-search
  vocabulary.
- `sw.js` -> `tdw-shell-v95`.

## Acquisition evidence status (2026-10-06, PR open, no migration)

Full description: `docs/acquisition-evidence-status.md`. Stable facts:
- **One status per AVAILABLE unit:** `harvesters/sources/acquisition_evidence_status.py`
  gives each (state, source, county) VERIFIED / NEEDS_REVIEW / UNAVAILABLE /
  NOT_FOUND, generated into `public/acquisition-evidence.json` `"status"`.
- **Where VERIFIED comes from:** only the evidence tables or a
  PRODUCTION_VERIFIED registry purchase document. Outcomes
  (`data/acquisition_evidence_outcomes.csv`) can never say VERIFIED, and a
  capture outcome must cite its run id.
- **Candidate pages:** `data/acquisition_candidate_pages.csv` gained
  `source_id` / `doc_kind`. After editing it, rebuild county-intelligence /
  source-inventory / acquisition-evidence.
- **Frontend:** `acquisitionEvidenceStatus(p)`. The labels
  (`ACQ_EVIDENCE_STATUS_LABELS`, `ACQ_DOC_KIND_LABELS`) are pinned to Python.
  Candidate links carry `data-acq-link="candidate"` and are always marked
  "not yet verified".
- `sw.js` -> `tdw-shell-v96`.

## Authoritative coordinates (2026-10-06, PR open, no migration)

Full description: `docs/authoritative-coordinates.md`. Stable facts:
- **Coordinate provenance.** `harvesters/sources/coordinates.py`
  `coordinate_provenance()` returns the method (PARCEL_GIS / TAX_ROLL /
  LAND_BANK_GIS / OFFICIAL_ADDRESS / OTHER_REVIEWED / VENDOR_LISTING /
  DETERMINISTIC_GEOCODE / UNRECORDED) and the geometry (POINT /
  PARCEL_CENTROID). app.js `coordinateProvenance()` mirrors it, pinned by
  `coordinate_cases.json`.
- **Matching and replacement.** Coordinates come only from a deterministic
  match (`accept_match`), never from a nearby feature. `should_replace()`
  never goes down the ranking or from authoritative to non-authoritative.
  `field_provenance.RANK["census_geocoder"] = 0`.
- **Geocoder.** `geocode_properties.py`: independent cities match only on
  the Census NAME. `GEOCODE_SOURCE_ID` makes a run strict (house number +
  street word, provenance written, counts-only log).
- **Parcel coordinate layers.** These are inert configs
  (`mo_stl_parcels_coordinates`) and `DEEP_TARGETS` with
  `"purpose": "coordinates"` (MO / OK / PA / SC). Probe before use.
- `sw.js` -> `tdw-shell-v97`.

## Current acquisition amounts (2026-10-06, PR open, no migration)

Full description: `docs/current-acquisition-amounts.md`. Stable facts:
- `harvesters/sources/amount_semantics.py` = app.js `amountSemanticType()` /
  `amountTemporal()` (vectors `tests/python/fixtures/amount_semantics_cases.json`).
  Twelve semantic types; time status CURRENT / HISTORICAL / EXPIRED / UNKNOWN
  (list read within 14 days and dated within 365 for CURRENT). A minimum-named
  source column makes an opening bid a MINIMUM_BID.
- `parse_statement_text()` validates a statement: one total, OCR-garbled
  figures refused, components must reconcile, rights not PERMITTED =
  not displayable. No statement is stored anywhere yet.
- Property page shows Amount type / Amount status / Valid through (`.fp-meta`).
  `sw.js` -> `tdw-shell-v98`.

## County Intelligence page (2026-10-06, PR open, no migration)

Full description: `docs/county-intelligence-page.md`. Stable facts:
- `#/counties` (index) and `#/county/<name>` (page), rendered into
  `#pageCounty`, which `ensureCountySection()` creates (no HTML change).
  `SHELL_PAGES.county`; the nav "County Intelligence" entry opens the index;
  the state picker stays on the header "States" button.
- Research ladder: `harvesters/sources/county_research.py` = app.js
  `countyResearchStatus()` (vectors `county_research_cases.json`). Six steps,
  VERIFIED / PARTIAL / NOT_VERIFIED / NOT_APPLICABLE, reached = last step
  with no earlier gap. Rows on file never verify a county; no score.
- Sections: Available, Auctions (calendar, platform, bid range as published,
  registration only as published steps, verified outcomes only), Liens
  (only with certificate inventory/source), Property intelligence (X of N),
  Source truth, Research gaps. Customers see unreviewed sources counted only.
- Section code is `var` / function declarations (TDZ). `sw.js` -> `tdw-shell-v99`.

## My Research: research lists + customer workflow state (2026-10-06, PR open, migration 029 NOT applied)

Full description: `docs/research-workspace.md`. Stable facts:
- `#/research` (`#pageResearch`, created at runtime) + a "My research" section
  on every property page + the "My Research" nav entry (injected by
  `syncResearchNav()`) + Home "In my research".
- Customer research state (DISCOVERED / RESEARCHING / DUE_DILIGENCE /
  ACQUISITION_READY / PASSED / ACQUIRED, `RESEARCH_STATES`) is NEVER a source
  status: shown beside `officialStatusText(p)`, refused outside the six
  values before any request, never written to `properties`.
- Migration 029 (`research_lists`, `research_items`; own-row PERMISSIVE +
  RESTRICTIVE `is_approved()`, InitPlans, grants revoked first) is written and
  live-tested, NOT applied. Without it the workspace lives in localStorage
  (`tdw_research_v1:<user>`), labelled "Kept in this browser only".
- Stub: `?research=none` simulates 029 absent; `__stubResearchDb()` reads it.
  `sw.js` -> `tdw-shell-v100`.

## Due diligence (2026-10-06, PR open, no new migration - uses 029)

Full description: `docs/due-diligence.md`. Stable facts:
- `harvesters/sources/due_diligence.checklist(facts)` = app.js
  `diligenceChecklistFromFacts()` (vectors `due_diligence_cases.json`);
  `diligenceFacts(p)` derives the facts from the existing evidence functions.
- States VERIFIED / NOT_VERIFIED / NOT_PUBLISHED / NOT_APPLICABLE /
  SOURCE_UNAVAILABLE. A populated field without a recorded origin (or a read
  of its source) is NOT_VERIFIED - never verified because it is filled.
- "Due diligence" section (`data-section="diligence"`) on every property;
  customer review marks / notes live in `research_items.diligence` and never
  change a state. `sw.js` -> `tdw-shell-v101`.


## Enrichment priority + authoritative geocoding (2026-10-06, PR open, no migration)

Full description: `docs/enrichment-geocoding.md`. Stable facts:
- **`harvesters/enrichment/priority.py`**: explicit rules, no score:
  - P1 / P2 / P3: customer-visible Available / Auction / Lien;
  - P4: a county with a verified acquisition path;
  - P5: a market-test county (`data/market_test_counties.csv`);
  - P6: strong identity with gaps;
  - P7: the rest.

  Order is rule, then state, county, id. Inactive rows are never enriched.
- **`harvesters/enrichment/geocode.py`**: coordinate sources are only
  - FDOR cadastral (TAX_ROLL);
  - Santa Rosa parcels;
  - every `centroid=True` parcel config (PARCEL_GIS);

  all as PARCEL_CENTROID, and queried only when APPROVED and verified.
  - **Matching:** exactly one feature on the record's own identifier; no
    address / fuzzy / nearest match.
  - **Points:** a point outside the state is a PARSER_FAILURE.
  - **Replacement:** `coordinates.should_replace` decides. Stored coordinates
    with a weaker or unrecorded origin are replaced only with `--allow-upgrade`.
- **`scripts/geocode_authoritative.py`** (manual `job=geocode`):
  - `geocode_mode` plan (default) / dry-run / apply;
  - apply also needs `--confirm-apply`, which the workflow passes only in apply
    mode;
  - output is counts only.

  **`scripts/enrichment_audit.py`** writes the counts-only state × county ×
  ledger audit.
- Nothing has been dispatched. The first run needs the owner's authorization.
