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
const CACHE = "tdw-shell-v18";
const SHELL = [
  "/",
  "/index.html",
  "/styles.css",
  "/explore.css",
  "/app.js",
  "/explore.js",
  "/config.js",
  "/fl-counties.svg",
  "/fl-cities.json",
  "/fl-zips.json",
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
  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req).catch(() => caches.match("/index.html").then(r => r || Response.error()))
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
