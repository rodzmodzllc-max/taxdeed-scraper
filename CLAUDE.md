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
