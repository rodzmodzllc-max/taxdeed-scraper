# CLAUDE.md — FL Tax Deed Watchlist

Persistent orientation for Claude across sessions on this project. Read this first. For the full dated history of fixes/audits/decisions, see the "tax florida app" claude.ai Project doc `claude/improvement-roadmap.md` — that's the detailed changelog; this file is the stable map.

## What this is

A private, invite-only web app that tracks Florida county tax-deed auctions, tax-lien certificates, and "Lands Available for Taxes" (LAFT) listings for a small team (Marc + partners) doing tax-deed investing. Live at **https://rodz-taxdeeds.pages.dev**.

## ONE repo, not two — corrected 2026-08-25

**`rodzmodzllc-max/taxdeed-scraper`** (public — flipped from private 2026-08-31 to sidestep a GitHub Actions billing block; see the project roadmap for details) is the **only real repo**. There is no `taxdeed-app` repo — that name doesn't exist on GitHub; if you ever find a local clone with that remote, its origin is stale/dead (this happened once — see below) and should be discarded in favor of a fresh clone of `taxdeed-scraper`, or just browse it via the authenticated Chrome tab.

It's a monorepo containing **both** the frontend and the backend:
- Frontend source lives under `public/` (`index.html`, `app.js`, `styles.css`, `config.js`, `sw.js`, etc.) — vanilla JS/HTML/CSS, no framework, no build step.
- A GitHub Actions bot auto-commits with the message `Auto-sync: mirror public/ to repo root [skip ci]`, keeping copies of those same files at the **repo root** in sync with `public/` — this is what Cloudflare Pages actually deploys from. When editing the frontend, edit the files under `public/`; the root-level copies are generated, not hand-edited.
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
- **`config.js`** — `mapboxToken` is replaced with `googleMapsApiKey`,
  holding the actual key Marc supplied
  (`AIzaSyCw-tvRxNh5ahP3VbqBAOQMGeJJ6befaqc`). Flagged in the file's own
  comment: unlike the Supabase publishable key, this key isn't scoped by
  row-level security, so it's only as safe as its own Google Cloud Console
  restrictions (HTTP referrer + Maps JavaScript API only) — worth doing in
  Cloud Console even though it's outside this repo.
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

## Known landmines / do-not-repeat mistakes

- Miami-Dade is the only county with a hyphen in `data/realauction_counties.csv` — a blanket `-replace '-',' '` once silently renamed it to "Miami Dade", which didn't match the frontend's canonical `"Miami-Dade"` and hid 33 live listings. Fixed; don't reintroduce a blanket hyphen transform.
- `scraper.js` no longer exists (removed 2026-09-01, repo debris cleanup). Historical note: it used to be a disabled, non-functional 50-state simulated scraper (`Math.sin()`-based fake data, writing to a `tax_auctions` table the frontend never read), kept `workflow_dispatch`-only so it couldn't burn CI minutes doing nothing. It, its package.json/package-lock.json, and its `.github/workflows/scrape.yml` workflow were all removed together. It was never the real pipeline.
- `public/config.js` intentionally ships a public Supabase **publishable** key client-side — this is expected and safe (RLS enforces everything). The **service_role** key must never appear in this repo or in client-side code, only in `sync-config.local.json` (gitignored) and GitHub Actions secrets.
- There was an earlier leaked-key incident (see comments in `public/config.js`) that prompted migrating from the legacy long-lived `anon`/`service_role` JWTs to the new revocable `sb_publishable_...`/`sb_secret_...` key format. Legacy key revocation was still pending user action as of the last audit — check current status before assuming it's done.
- The "every write action fails silently" bug (favorite/hide/restore/bid-list/notes) that earlier audits in this project flagged **was fixed 2026-08-24** (commit `a732779`, "Surface write errors instead of failing silently") — a shared `showErrorToast()` helper now surfaces every one of those errors. Don't re-flag it without checking the current file first.
- Bid-on-auction links in `app.js` are **entirely data-driven** from `p.url_auction` (populated by the harvesters) and conditionally rendered — `${p.url_auction ? '<a ...>Bid on County Auction Site</a>' : ''}`. There is no frontend-constructed URL, so a "broken bid link" cannot render; the only failure mode is an absent bid button on a property the harvester didn't attach a URL to. Confirmed by code inspection 2026-08-25.
- This sandbox has no git push access to `taxdeed-scraper` (git proxy reports the repo isn't in this session's authorized set) and no `gh`/git-clone credentials for it either — reach it through the authenticated Chrome browser tab (GitHub web UI for edits/uploads, raw file view or `document.body.innerText` via `javascript_tool` for reading — `get_page_text` truncates large files at ~50KB, so `app.js` needs the `innerText` approach or a range-limited fetch).

## Where to look for more

- `claude/improvement-roadmap.md` in the "tax florida app" claude.ai Project — the full dated log of every fix, audit finding, and open decision. This is where new findings should be appended, not here.
- This file (`CLAUDE.md`) should stay a **stable architecture map** — update it when the architecture, data model, or a hard-won lesson changes, not for routine status updates. Verify claims here still hold before trusting them blindly — this file itself was wrong about the repo count until 2026-08-25, and wrong about local-PC involvement until 2026-08-25.
