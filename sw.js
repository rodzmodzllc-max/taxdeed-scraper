// Service worker: makes the app installable and keeps it usable on a weak
// signal at a courthouse.
//
// Strategy is deliberately split:
//   * App shell (html/css/js/icons) - cache-first, so it launches instantly.
//   * Everything else, including all Supabase traffic - network-only.
//     Property data, notes and auth must never be served stale, and caching
//     authenticated API responses on disk would be a privacy problem.

// Bump this on every deploy that changes the shell, otherwise returning users
// keep the old CSS/JS from cache and your fix appears not to have shipped.
const CACHE = "tdw-shell-v7";
const SHELL = [
  "/",
  "/index.html",
  "/styles.css",
  "/app.js",
  "/config.js",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png"
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

  // Icons never change without a filename change - cache-first is safe.
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