// Service worker: makes the app installable and keeps it usable on a weak
// signal at a courthouse.
//
// Strategy is deliberately split:
// * App shell (html/css/js/icons) - cache-first, so it launches instantly.
// * Everything else, including all Supabase traffic - network-only.
// Property data, notes and auth must never be served stale, and caching
// authenticated API responses on disk would be a privacy problem.

// Bump this on every deploy that changes the shell, otherwise returning users
// keep the old CSS/JS from cache and your fix appears not to have shipped.
// v8: icon URLs below got a ?v=2 cache-buster (see comment there) - bumping
// this too forces the old cached (pre-relogo) icons out of everyone's
// Cache Storage immediately instead of waiting on their natural expiry.
// v9: adds explore.css / explore.js (the split list+map view) and
// fl-counties.svg. That SVG is now a dependency of a primary view rather
// than of a filter-panel extra, so it belongs in the offline shell - the
// map still working without signal is half the point of shipping a PWA.
// v10: card/list changes (unpublished-bid labelling, single-tile headline,
// keyboard-operable chips, lazy county groups) touch app.js, explore.js and
// explore.css. Code is network-first so this isn't strictly load-bearing,
// but the shell precache list should not keep handing out the previous
// trio to a cold offline start.
// v11: the command-bar header - index.html moves the Filters & Sort toggle
// into the control bar, and explore.css collapses the duplicated brand block,
// stops the filters panel opening itself at >=1024px, and makes the bar
// sticky at every width. Shell HTML is precached, so a returning user needs
// this bump to see it.
// v12: county detail on the map - explore.js gains the lat/long projection,
// the zoom, pins, the card strip and the preview card; explore.css their
// styles. Code is network-first so this is not load-bearing, but the shell
// precache should not hand a cold offline start the previous pair.
// v13: search now matches case #, parcel #, certificate # (which it never
// did), owner and county, with punctuation stripped from identifiers - so
// index.html's placeholder and app.js both changed, and the shell HTML is
// precached.
// v15: three rounds in one. City labels and the closed-property outcome
// banner (fl-cities.json); ZIP areas inside a zoomed county (fl-zips.json);
// the Android back button; and the account badge, which moved theme,
// password, install and sign out out of the header and the title-search
// warning down into a Terms modal. Both data files are in the offline shell -
// a map with no labels or areas was the "looks stale" complaint, and the
// courthouse is exactly where the connection is worst.
//
// v16: each ledger became its own page - own URL (#/auctions, #/lands,
// #/certificates), own accent palette, own header. index.html, app.js and
// styles.css all changed, and a half-updated shell here would serve the new
// markup against the old stylesheet.
//
// v17: the header collapsed to one bar (logo, title, account badge) and the
// per-county freshness badge became a status colour on each card's left
// edge. The account badge MOVED in the markup, from the masthead into the
// sticky topbar - a cached index.html against a fresh app.js would leave
// #accountBtn where nothing expects it.
//
// v18: the basemap was rebuilt. fl-counties.svg grew a sea rect, three
// neighbouring states and orientation labels, and its viewBox moved - so a
// cached copy of the OLD svg against the new explore.js would put every pin
// 17% too far east, which is exactly the bug the projection change fixes.
//
// v19: the county tax-roll columns (year_built, living_area, lot_sqft,
// legal_desc, last_sale_*) now render, and the value box is relabelled from
// "Est. Market" to the county's just value for a stated roll year. app.js and
// styles.css changed together - a cached stylesheet against the new markup
// would leave the new card lines unstyled.
//
// v20: mobile legibility/zoom fix. index.html and tx.html's viewport meta
// gained maximum-scale=1, user-scalable=no, viewport-fit=cover (pinch-zoom
// was pulling the fixed .nav-bottom tab bar off-screen - browsers detach
// position:fixed elements from the visual viewport while zoomed), and
// styles.css gained a mobile html{font-size} bump so the UI is legible at
// 1x without needing to zoom in the first place. All three precached shell
// files changed together - a cached index.html serving the old
// unscalable-off meta against a fresh stylesheet (or vice versa) would
// leave the disappearing-nav bug in place for exactly the returning users
// on the courthouse wifi this cache exists to help.
//
// v21: three fixes from testing the packaged Android app (TWA). (1) dropped
// viewport-fit=cover from index.html/tx.html - it made the fixed bottom nav
// visibly shift/move once packaged as a TWA, which handles edge-to-edge
// insets differently than a plain Chrome tab; the zoom-lock from v20 stays.
// (2) real bug fix: #app (id="app" class="app-shell") stayed visible behind
// the sign-in screen because `.app-shell{display:block}` ties in specificity
// with the browser's own `[hidden]{display:none}` and, being later in the
// cascade, was winning - so scrolling past the login card on #authGate (not
// position:fixed, just min-height:100vh) reached the live ledger underneath.
// Added .app-shell[hidden]{display:none}, same fix already applied to
// #authGate/#pendingGate/.filters-row elsewhere in this file. (3) dropped
// the 1px outline from .detail-stat/.card-stat/.stat-tile - a page full of
// bordered boxes read as an itemized receipt; replaced with a soft shadow
// (detail-stat/stat-tile) or a plain background tint (card-stat, which
// already sits inside another bordered card). index.html, tx.html and
// styles.css all changed together.
// v22: nav-perfection pass on Dashboard and Map. (1) Dashboard gets a
// Settings button next to the title (id="dashSettingsBtn" in index.html and
// tx.html) that opens the exact same account menu as the header badge - see
// the new listener right after the accountBtn wiring in app.js. (2) The Map
// page gets its own FL/TX switcher (#regionTabsMap, styled by
// .map-region-tabs so it doesn't inherit #regionTabs' dark-masthead colors)
// linking to index.html#map / tx.html#map - a new location.hash === "#map"
// check near the page router in app.js opens straight to the Map tab
// instead of the default Auctions landing. Texas has no live harvester yet
// (see harvesters/texas_harvester.py) so its map is genuinely empty until
// then - same "ship the page ahead of the data" pattern as the Auctions
// region tabs already used. (3) The Map panel itself gets a proper card
// frame (background/border/radius/shadow) instead of edge-to-edge with no
// chrome at all - it was the one page in the app without one - and the
// legend swatches became round dots instead of 2px-radius squares.
// index.html, tx.html, styles.css and app.js all changed together.
// v23: Phase 51 visual rebuild pass 1 (Dashboard, property cards, and the
// full property page), moving the app toward Marc's dark-navy sidebar
// reference design using only real data - no fabricated fields, no new
// interaction model bolted on. (1) Dashboard stat tiles get an icon chip
// (renderDashboard() in app.js) and a new third panel, Upcoming Auctions -
// built from real sale_date rows only (upcomingAuctionRows()), no synthetic
// "recent activity" feed (this project has no events/audit-log table to
// source one from honestly). (2) Every property card and the full property
// page now show a photo strip - a real cached Street View image when
// properties.photo_url has one (see schema-v10-property-photos.sql /
// scripts/fetch_property_photos.py), otherwise a compact "No photo
// available" bar, never a blank photo-sized box and never a fake image
// (photoOrPlaceholder() in app.js). (3) The full property page
// (detailHtml()) is reorganized into labeled cards - Financial / Property
// Details / History (the same stats as before, just grouped), plus two new
// ones built from real fields only: GIS & Location (real latitude/
// longitude from scripts/geocode_properties.py, with a free key-less
// OpenStreetMap embed when coordinates exist) and Risk & Legal, which is
// intentionally NOT a fake "None found" - liens/judgments/foreclosure/code-
// enforcement data has zero real rows anywhere in this pipeline (see
// claude/phase-33-source-compliance-audit.md and friends), so every row
// reads "Not tracked" with a plain-language disclaimer instead. The
// existing reference links are relabeled "Research & Sources" and the
// existing provenance line becomes a "Data Quality & Provenance" card -
// same text, same tests/run_test.mjs assertions, new chrome around it.
// Certificates are untouched (no photo/GIS/Risk & Legal section - a lien
// instrument isn't a parcel the way a deed/LAFT row is). (4) The sidebar
// gets a Settings entry (navSettingsBtn) next to the existing Dashboard/
// Auctions/Map/Watchlist items, opening the same account menu as the
// header badge and the Dashboard's own Settings button - no new page.
// index.html, tx.html, styles.css and app.js all changed together.
// v24: Phase 53, one map instead of two. Marc's screen recording pointed out
// that the nav bar's Map and the Auctions view-toggle's Map opened two
// different maps for the same idea - a plain county-by-auction-format SVG
// on its own page, and explore.js's own richer "Where these are" bubble map
// (real per-county counts, one-tap zoom+filter, a floating preview card,
// real geocoded pins once zoomed in - all built from actual filtered rows).
// The second one was strictly the better map, so it's now the only one.
// (1) The standalone #pageMap section, its #regionTabsMap FL/TX switcher,
// and the Map button in #viewToggle are removed from index.html/tx.html.
// (2) app.js's showPage() routes "map" as a virtual destination instead -
// it shows the Auctions page and dispatches a new tdw:setviewmode event
// that explore.js listens for (mirroring the existing tdw:rendered/
// window.__tdwLastRender stash pattern, for the same module-load-order
// reason). The legacy #pageMap-driving JS (ensureMapLoaded, zoomToCounty,
// computeCountyCentroids, etc.) is left in app.js as documented dead code
// rather than stripped from several still-live filter-sync call sites -
// see the comment above mapBtnEl there. (3) The surviving map gets a small
// honest legend (renderBubbleLegend() in explore.js) showing what bubble
// size actually means, built from the real counts on screen - not a fixed
// key, since this map has no fixed scale. index.html, tx.html, styles.css,
// explore.css, app.js and explore.js all changed together.
// v25: Phase 54, Map is its own page again - and a fuller redesign, not
// another small adjustment. Marc's explicit feedback rejected Phase 53's
// virtual-route approach: switching to Map didn't feel like going anywhere
// (same masthead/ledger-tabs/toolbar, just the panel swapped), and Auctions
// needed to go back to being just the list. So: (1) #pageMap is a real
// <section class="page"> again in index.html/tx.html, with its own header
// ("Map" + subtitle) and its own toolbar - search, a county select, an
// All/Auctions/Lands Available/Certificates ledger-pill row, a Watchlist-
// only pill - none of it borrowed from the Auctions page's own controls.
// (2) app.js gets a small independent filter layer for it (mapFilter,
// computeMapRows(), buildMapCountySelect(), renderMapPage()) that reads
// ALL[] directly rather than the Auctions page's own state/passes()
// pipeline - the Map page shows every ledger at once and isn't scoped to
// whatever the Auctions page's filters happen to be set to, the same
// portfolio-wide philosophy dashboardStats() already uses for the
// Dashboard. (3) explore.js drops the List/Split/Map view-toggle it used
// to run entirely - MODE_KEY/MODES/storedMode()/setMode()/bindViewToggle()
// and the cross-highlight between a map bubble and an adjacent card list
// (focusCounty()/clearFocus()/bindListHover(), meaningless once the map and
// the list are different pages) are all gone - and consumes a new
// tdw:maprendered event (replacing tdw:rendered/tdw:setviewmode for this
// module) dispatched by renderMapPage(). (4) The Auctions page loses
// #viewToggle and the .explore-shell/.explore-map-panel it used to embed
// the map beside #main - Auctions is just the list now, full width.
// (5) The map itself keeps every honest-data property from Phase 53 (county
// bubbles sized by real counts, tap-to-zoom into real geocoded pins, the
// floating preview card, the bubble-size legend) - only the page's own
// chrome around it changed. index.html, tx.html, styles.css, explore.css,
// app.js and explore.js all changed together.
// v26: Phase 55, an optional satellite/terrain basemap alongside the outline
// map, not instead of it. Marc's follow-up on the Phase 54 recording ("the
// actual 3d map like the mockup") turned out to name a real trade-off: the
// mockup's Map panel is a photographic satellite/terrain basemap, which
// means a third party (asked directly, Marc chose "real satellite/terrain
// WITH A TOGGLE to our current style map" - both, switchable, see CLAUDE.md's
// Phase 55 section). New: satellite-map.js, a module independent of
// explore.js (same tdw:maprendered contract, no shared internals), and
// county-centroids.json (real Census-derived county centroids for FL/TX,
// computed via us-atlas/topojson/turf - not fabricated, not fetched
// pre-computed from a source we couldn't verify). Both ship in the shell so
// the toggle and its "not set up yet" message work offline; the actual map
// libraries (Google Maps JavaScript API and, as of Phase 60, MapLibre GL JS
// - Phase 56 briefly had Google only, Phase 57-59 had Mapbox GL JS in the
// second slot) are each only injected when that provider's own key is
// configured AND the user actually clicks that provider's button - never
// pre-cached, never fetched speculatively.
// index.html, tx.html, explore.css, _headers (CSP) and config.js changed
// alongside these two new files, and again in Phase 56 (provider swap),
// Phase 57 (both providers, three-way toggle), Phase 60 (Mapbox ->
// MapTiler) and Phase 61 (split the shared satellite canvas into one per
// provider - see CLAUDE.md's Phase 61 section for the bug this fixed).
const CACHE = "tdw-shell-v36"; // bumped for Phase 71: card headline bids always round to a whole dollar (app.js changed; v35 is reserved by the still-open map-workspace PR)
const SHELL = [
  "/",
  "/index.html",
  // Phase 63: tx.html/tx-counties.svg were never precached even though
  // tx.html is a full separate deployed page (same styles.css/app.js/
  // explore.js/satellite-map.js, different data) and app.js/explore.js both
  // fetch tx-counties.svg at runtime whenever PAGE_STATE is "TX". Without
  // these, a Texas user offline (or on a bad connection) had nothing correct
  // to fall back to - see the navigate handler below, which now picks
  // between the two shells instead of always handing back index.html.
  "/tx.html",
  "/tx-counties.svg",
  "/styles.css",
  "/explore.css",
  "/app.js",
  "/explore.js",
  "/satellite-map.js",
  "/config.js",
  "/fl-counties.svg",
  "/fl-cities.json",
  "/fl-zips.json",
  "/county-centroids.json",
  "/manifest.webmanifest",
  // Icon bytes changed (new logo) but the filenames didn't, and /icons/* is
  // served with a 7-day Cache-Control (see _headers) plus this worker's own
  // cache-first icon handling below - two layers that would otherwise keep
  // serving the old logo to anyone who'd already visited. The ?v=2 query
  // string makes this a new URL to both caches, so it's fetched fresh once,
  // then stays cache-first (fast) after that. Bump to v3/v4/etc next time
  // the icon files themselves change again.
  "/icons/icon-192.png?v=2",
  "/icons/icon-512.png?v=2"
];

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(CACHE)
      // addAll is atomic - one 404 would reject the whole install, so add
      // individually and tolerate misses.
      .then(c => Promise.all(SHELL.map(u => c.add(u).catch(() => {}))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // Never touch Supabase or any cross-origin request.
  if (url.origin !== self.location.origin) return;

  // Navigations: try network first so a redeploy is picked up immediately,
  // fall back to the cached shell when offline.
  //
  // Phase 63: this used to hardcode "/index.html" as the offline fallback
  // for EVERY navigation, regardless of which page was actually requested -
  // a Texas user cold-starting offline (or on a bad connection) at /tx got
  // served the Florida shell instead, the wrong app entirely. Pick the
  // fallback from the requested path instead; tx.html is now precached
  // above so this fallback has the right shell to hand back.
  if (req.mode === "navigate") {
    const isTx = /^\/tx(\.html)?\/?$/i.test(url.pathname);
    const fallbackPath = isTx ? "/tx.html" : "/index.html";
    e.respondWith(
      fetch(req).catch(() => caches.match(fallbackPath).then(r => r || Response.error()))
    );
    return;
  }

  // Icons never change without a filename (or ?v=) change - cache-first is safe.
  if (/\.(png|ico|svg|webmanifest)$/i.test(url.pathname)) {
    e.respondWith(
      caches.match(req).then(hit => hit || fetch(req).then(res => {
        if (res && res.ok) { const c = res.clone(); caches.open(CACHE).then(x => x.put(req, c)); }
        return res;
      }))
    );
    return;
  }

  // Code (css/js): NETWORK FIRST. Cache-first here meant a deploy silently did
  // not reach anyone who already had the app open - the cached copy just kept
  // winning. Cache is now only a fallback for being offline.
  e.respondWith(
    fetch(req)
      .then(res => {
        if (res && res.ok) { const c = res.clone(); caches.open(CACHE).then(x => x.put(req, c)); }
        return res;
      })
      .catch(() => caches.match(req))
  );
});
