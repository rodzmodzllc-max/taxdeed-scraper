// ============================================================================
// Satellite/terrain basemaps for the Map page - OPTIONAL second/third views,
// toggled against explore.js's own same-origin outline map via
// #mapStyleToggle (see index.html/tx.html's "Where these are" card head).
//
// WHY THIS EXISTS (Phase 55):
// Phase 54 rebuilt Map into its own page but kept the honest same-origin
// outline map from Phase 53 - deliberately, since only ~2% of rows are
// geocoded and a third-party tile provider would leak which parcels a
// signed-in user is browsing to that provider (see explore.js's own header
// comment). Marc watched a screen recording of the (then still pre-Phase-54)
// live site and asked for "the actual 3d map like the mockup" - a real
// satellite/terrain basemap, Google-Maps-style. That's a genuine trade-off,
// not a styling gap: it needs a third party. Asked directly, Marc chose
// "real satellite/terrain WITH A TOGGLE to our current style map" - both
// views, switchable, neither one replacing the other. See CLAUDE.md's Phase
// 55 section for the full exchange.
//
// PHASE 56: MAPBOX -> GOOGLE MAPS
// Marc then got a real Google Maps API key and, asked directly, chose to
// switch providers outright - this file briefly supported Google only.
//
// PHASE 57: BOTH PROVIDERS, USER'S CHOICE
// After seeing Google Maps working live, Marc asked to have Mapbox back too
// - "as a backup, or even just a map toggle to have all three options" - and
// sent his Mapbox token back. So the toggle became three-way: the same-
// origin outline map (default, no third party), Google, and Mapbox - each
// independent, each off/inert until its own key/token is present, neither
// one replacing the other.
//
// PHASE 60: MAPBOX -> MAPTILER
// The Mapbox token Marc provided kept getting flagged by GitHub's push-
// protection secret scanner as a "Mapbox Secret Access Token," and Mapbox's
// dashboard requires a payment method on file to create a fresh, narrowly-
// scoped replacement token - a real paywall, not just friction. Rather than
// have Marc hand over a card for a bonus third map view, this file now uses
// MapTiler instead of Mapbox: a free tier that needs no payment method at
// all (5,000 map sessions/month, confirmed via MapTiler's own pricing page),
// using MapLibre GL JS - an open-source fork of Mapbox GL JS with the same
// API - so the provider swap below is close to a 1:1 rename rather than a
// rewrite. This file now owns two provider implementations side by side
// rather than picking one; see the "GOOGLE PROVIDER" and "MAPTILER
// PROVIDER" sections below. Kept as one file rather than split into three
// because the two providers share most of their surrounding logic (county
// grouping, centroids, zoomed-vs-statewide detection, the toolbar contract)
// and a single toggle dispatch is simpler to reason about than cross-module
// wiring for what's still, at heart, one feature with two swappable
// backends.
//
// PHASE 61: SEPARATE CANVASES PER PROVIDER (bug fix)
// Phases 56/57/60 had Google and the GL-based provider (Mapbox, then
// MapTiler) share ONE DOM node (#satelliteMapCanvas), on the theory that
// "never both at once - only the active one is un-hidden" (see explore.css's
// old comment) was enough. It wasn't: each provider's ensure*Map() claims
// that shared node by wiping it with canvas.innerHTML = "" the FIRST time
// it initializes, then never touches it again (ensure*Map() early-returns
// once that provider's own loadState is "ready"). So whichever provider is
// activated SECOND wipes out the first provider's live map/markers when it
// takes the node over - and because the first provider's ensure*Map() never
// re-runs, clicking back to it just calls its render*() against a map
// object whose container div no longer has that map's content, or was
// deleted from under it. This was never caught because tests/config.js
// ships neither key (see the test file's own comment on that block), so
// the suite only ever exercises the "not configured" path for both
// providers - each stays "idle", so the fixture never triggers the actual
// hand-off. It surfaced only once Marc had BOTH a real Google key and a
// real MapTiler key live at once and clicked both buttons in one session
// (Phase 60's own header already flagged that the "both configured, tiles
// really render" path was never live-verified in the sandbox - this is
// exactly the gap that note was warning about).
// Fix: give each provider its own permanent canvas
// (#satelliteMapCanvasGoogle / #satelliteMapCanvasMaptiler) instead of
// sharing one - switching styles now only ever toggles which of the two
// (already-initialized, independent) DOM nodes is hidden, the same way the
// outline map and the satellite group have always coexisted. Neither
// provider's ensure*Map() needs to reclaim anything from the other anymore.
//
// WHY A SEPARATE MODULE, not code inside explore.js:
// Same reasoning explore.js's own header gives for being separate from
// app.js - this draws a second, independent view of the same data, so it
// takes app.js's data over the same one-way event explore.js already
// listens for (window.addEventListener("tdw:maprendered", ...) -> { rows,
// ledger, openDetail }) rather than reaching into explore.js's internals.
// The two modules don't know about each other; #mapStyleToggle's own click
// handlers (bound in this file) just show one canvas and hide the other.
//
// WHY EACH PROVIDER IS OFF BY DEFAULT AND SAFE WHEN UNCONFIGURED:
// Google needs an API key (window.TDW_CONFIG.googleMapsApiKey) and MapTiler
// needs an API key (window.TDW_CONFIG.maptilerKey) - each only Marc can
// obtain/manage, see config.js's comments. This file never injects either
// provider's loader script or fetches a single tile for a provider unless
// BOTH (a) that provider's key is non-empty AND (b) the user has actually
// clicked that provider's button at least once. Clicking a provider's
// button with no key just swaps in a plain-language setup message naming
// that provider - no different from any other empty state in this app, and
// it never touches the other provider's state.
//
// WHAT'S DELIBERATELY THE SAME AS THE OUTLINE MAP, AND WHY:
// Statewide, each provider draws one bubble per county (sized by count,
// coloured by the active ledger pill - same palette as .cluster-bubble,
// reused via CSS custom properties rather than a second hard-coded one).
// Clicking a bubble sets #mapCountySelect to that county exactly the way
// explore.js's own applyCounty() does (set .value, dispatch a bubbling
// "change") - all three maps share the same toolbar and the same filter,
// they just draw it different ways. Once a single county is selected, rows
// narrows to that county alone (computeMapRows() in app.js already does
// this - see its own comment), and the active provider switches from
// bubbles to real geocoded pins for that county and flies the camera in -
// the same statewide-bubbles / zoomed-pins split explore.js's
// draw()/drawPins() use, for the same honesty reason (a pin is a claim of a
// real coordinate; a bubble is a count).
// ============================================================================

const $ = id => document.getElementById(id);
// Phase 61: each provider gets its own permanent canvas - see this file's
// header note on why sharing one node between two map libraries was buggy.
const GOOGLE_CANVAS_ID = "satelliteMapCanvasGoogle";
const MAPTILER_CANVAS_ID = "satelliteMapCanvasMaptiler";
const PAGE_STATE = document.body.dataset.state === "TX" ? "TX" : "FL";

// Roughly centers each state in frame at a zoom that shows the whole thing
// without excess ocean/neighbor-state padding. Not derived from data (there's
// no "centroid of all counties" reason to prefer over a plain eyeballed
// state center) - just a sane initial camera, same spirit as the outline
// map's own fixed viewBox. Shared by both providers; Google and MapTiler
// each convert the [lng, lat] tuple into their own center-object shape.
const STATEWIDE_VIEW = {
  FL: { center: [-81.6, 28.1], zoom: 5.6 },
  TX: { center: [-99.3, 31.4], zoom: 5.1 }
};

let rows = [];
let ledger = "all";
let openDetail = null;

let activeStyle = "outline"; // "outline" | "google" | "maptiler" - which canvas shows

function googleMapsApiKey() {
  const k = (window.TDW_CONFIG || {}).googleMapsApiKey;
  return typeof k === "string" ? k.trim() : "";
}

function maptilerKey() {
  const k = (window.TDW_CONFIG || {}).maptilerKey;
  return typeof k === "string" ? k.trim() : "";
}

// ---------------------------------------------------------------------------
// style toggle - three-way: outline (default, no third party) / google / maptiler
// ---------------------------------------------------------------------------
function bindStyleToggle() {
  const outlineBtn = $("mapStyleOutline");
  const googleBtn = $("mapStyleGoogle");
  const maptilerBtn = $("mapStyleMaptiler");
  if (!outlineBtn) return;
  outlineBtn.addEventListener("click", () => setStyle("outline"));
  if (googleBtn) googleBtn.addEventListener("click", () => setStyle("google"));
  if (maptilerBtn) maptilerBtn.addEventListener("click", () => setStyle("maptiler"));
}

function setStyle(style) {
  if (style === activeStyle) return;
  activeStyle = style;
  const outlineBtn = $("mapStyleOutline");
  const googleBtn = $("mapStyleGoogle");
  const maptilerBtn = $("mapStyleMaptiler");
  const outlineCanvas = $("exploreMapCanvas");
  const googleCanvas = $(GOOGLE_CANVAS_ID);
  const maptilerCanvas = $(MAPTILER_CANVAS_ID);
  if (outlineBtn) outlineBtn.classList.toggle("on", style === "outline");
  if (googleBtn) googleBtn.classList.toggle("on", style === "google");
  if (maptilerBtn) maptilerBtn.classList.toggle("on", style === "maptiler");
  if (outlineCanvas) outlineCanvas.hidden = style !== "outline";
  // Phase 61: each provider owns its own canvas now, so switching styles is
  // just independent show/hide per node - no shared element to hand off.
  if (googleCanvas) googleCanvas.hidden = style !== "google";
  if (maptilerCanvas) maptilerCanvas.hidden = style !== "maptiler";
  // The outline map's own centroids/geometry stay correct while hidden (see
  // this file's header note on why - explore.js only measures once and
  // caches it), so nothing needs to be told to redraw on switching back to it.
  if (style === "google") {
    ensureGoogleMap();
    if (googleState.map && window.google && window.google.maps && window.google.maps.event) {
      requestAnimationFrame(() => window.google.maps.event.trigger(googleState.map, "resize"));
    }
    renderGoogle();
  } else if (style === "maptiler") {
    ensureMaptilerMap();
    if (maptilerState.map) requestAnimationFrame(() => maptilerState.map.resize());
    renderMaptiler();
  }
}

function setupMessage(canvasId, html) {
  const canvas = $(canvasId);
  if (!canvas) return;
  canvas.innerHTML = `<div class="satellite-map-setup">${html}</div>`;
}

// ---------------------------------------------------------------------------
// shared helpers - provider-agnostic, used by both renderers below
// ---------------------------------------------------------------------------
let centroids = null; // { fips, lat, lng } per county name, this state only
let centroidsPromise = null;

function loadCentroids() {
  if (centroids) return Promise.resolve(centroids);
  if (centroidsPromise) return centroidsPromise;
  centroidsPromise = fetch("county-centroids.json")
    .then(res => { if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
    .then(data => { centroids = (data && data[PAGE_STATE]) || {}; return centroids; })
    .catch(() => { centroids = {}; return centroids; });
  return centroidsPromise;
}

function hasPin(p) {
  return typeof p.latitude === "number" && typeof p.longitude === "number" &&
         isFinite(p.latitude) && isFinite(p.longitude);
}

// Phase 62: these bubbles sit at REAL county centroids on a real geographic
// map, unlike explore.js's own radiusFor() (13-38 units), which places
// bubbles on an abstract, hand-drawn SVG shape with room deliberately built
// in between counties. Florida's actual geography doesn't have that room -
// several of its most active counties (Hillsborough/Pinellas/Pasco/Polk,
// Orange/Seminole/Osceola) sit genuinely close together on a real map, so
// the old 30-68px-diameter range (MIN_R 15 / MAX_R 34) overlapped into an
// unreadable stack of circles at statewide zoom, worst on a narrow phone
// screen - confirmed directly from Marc's own screenshot (both Google and
// MapTiler showing five-plus bubbles piled on each other around Tampa/
// Orlando). Cut roughly in half; still sqrt-scaled so area (not radius)
// tracks count, just sized for real-world density instead of a friendlier
// abstract layout.
function radiusPx(count, max) {
  const MIN_R = 8, MAX_R = 18;
  if (max <= 1) return MIN_R;
  return MIN_R + (MAX_R - MIN_R) * Math.sqrt(count / max);
}

function pinLabel(p) {
  const a = (p.address || "").trim();
  if (a && !/^parcel\b/i.test(a)) return a;
  if (p.certificate_no) return "Certificate #" + p.certificate_no;
  return "Parcel " + (p.parcel || "unknown");
}

// Same select-and-dispatch as explore.js's applyCounty(), so all three
// basemaps drive the one toolbar the same way - see that function's own
// comment for why a plain "change" event (not a direct app.js call) is the
// contract.
function selectCounty(county) {
  const select = $("mapCountySelect");
  if (!select) return;
  if (county !== "ALL" && !Array.from(select.options).some(o => o.value === county)) return;
  select.value = county;
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function priceLineFor(p) {
  const bids = Number(p.bid);
  return bids > 0
    ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(bids)
    : "no published price";
}

function groupByCounty() {
  const byCounty = new Map();
  rows.forEach(p => {
    if (!byCounty.has(p.county)) byCounty.set(p.county, []);
    byCounty.get(p.county).push(p);
  });
  return byCounty;
}

// ============================================================================
// GOOGLE PROVIDER
// ============================================================================
// Google's own placeholder Map ID, meant exactly for this situation - trying
// out Advanced Markers without first creating a real Map ID in Cloud Console.
// Fine for Marc's demo key; swap for a real Map ID (Google Cloud Console ->
// Maps Management -> Map IDs) if/when this moves off the demo key. A Map ID
// is required for AdvancedMarkerElement - it isn't optional the way a
// MapTiler style URL was.
const GOOGLE_MAP_ID = "DEMO_MAP_ID";

const googleState = {
  map: null,
  AdvancedMarkerElement: null,
  infoWindow: null,
  loadState: "idle", // "idle" | "loading" | "ready" | "unconfigured" | "error"
  markers: [],
  lastZoomedCounty: null
};

// Google's own official dynamic-library-loader bootstrap (see
// https://developers.google.com/maps/documentation/javascript/load-maps-js-api),
// reproduced verbatim from Google's docs and installed inline here instead of
// as a separate <script> tag in index.html/tx.html - identical behavior:
// after this runs once, google.maps.importLibrary(...) is defined and the
// rest of this section uses it to pull in the "maps" and "marker" libraries
// on demand, only when a key is configured and the user has clicked Google.
function installGoogleMapsBootstrap(apiKey) {
  if (window.google && window.google.maps && window.google.maps.importLibrary) return;
  (g => {
    let h, a, k;
    const p = "The Google Maps JavaScript API", c = "google", l = "importLibrary", q = "__ib__";
    const m = document, b = window;
    b[c] = b[c] || {};
    const d = b[c].maps || (b[c].maps = {});
    const r = new Set(), e = new URLSearchParams();
    const u = () => h || (h = new Promise(async (f, n) => {
      a = m.createElement("script");
      e.set("libraries", [...r] + "");
      for (k in g) e.set(k.replace(/[A-Z]/g, t => "_" + t[0].toLowerCase()), g[k]);
      e.set("callback", c + ".maps." + q);
      a.src = `https://maps.${c}apis.com/maps/api/js?` + e;
      d[q] = f;
      a.onerror = () => { h = null; n(new Error(p + " could not load.")); };
      a.nonce = m.querySelector("script[nonce]")?.nonce || "";
      m.head.append(a);
    }));
    d[l] ? console.warn(p + " only loads once. Ignoring:", g) : d[l] = (f, ...n) => r.add(f) && u().then(() => d[l](f, ...n));
  })({ key: apiKey, v: "weekly" });
}

async function ensureGoogleMap() {
  if (googleState.loadState === "ready" || googleState.loadState === "loading") return;
  const key = googleMapsApiKey();
  if (!key) {
    googleState.loadState = "unconfigured";
    setupMessage(
      GOOGLE_CANVAS_ID,
      `<b>Google satellite view isn't set up yet</b>` +
      `<span>Add a Google Maps API key as <code>googleMapsApiKey</code> in ` +
      `<code>config.js</code>, then reload. The outline map on the left ` +
      `still works fully without one.</span>`
    );
    return;
  }
  googleState.loadState = "loading";
  setupMessage(GOOGLE_CANVAS_ID, `<b>Loading Google satellite map…</b>`);
  try {
    installGoogleMapsBootstrap(key);
    const { Map, InfoWindow } = await google.maps.importLibrary("maps");
    ({ AdvancedMarkerElement: googleState.AdvancedMarkerElement } = await google.maps.importLibrary("marker"));
    const canvas = $(GOOGLE_CANVAS_ID);
    canvas.innerHTML = "";
    const view = STATEWIDE_VIEW[PAGE_STATE] || STATEWIDE_VIEW.FL;
    googleState.map = new Map(canvas, {
      center: { lat: view.center[1], lng: view.center[0] },
      zoom: view.zoom,
      mapId: GOOGLE_MAP_ID,
      mapTypeId: "hybrid", // satellite imagery + labels - closest match to the reference mockup
      streetViewControl: false,
      fullscreenControl: false,
      mapTypeControl: false
    });
    googleState.infoWindow = new InfoWindow();
    googleState.loadState = "ready";
    renderGoogle();
  } catch (err) {
    googleState.loadState = "error";
    setupMessage(
      GOOGLE_CANVAS_ID,
      `<b>Google satellite map couldn't load</b>` +
      `<span>Check your connection and reload. The outline map still ` +
      `works offline - switch back with the Map button above.</span>`
    );
  }
}

function clearGoogleMarkers() {
  googleState.markers.forEach(m => { m.map = null; });
  googleState.markers = [];
  // Phase 62: an InfoWindow is its own object, not a marker - clearing
  // markers never touched it, so a popup opened from one ledger/county
  // stayed pinned on screen after switching to another (Auctions -> Lands
  // Available, or a different county), showing a property that ledger no
  // longer even includes. Confirmed live via Marc's own screenshot: a
  // Broward "Lands Available" filter with zero matches ("Nothing matches
  // the current filters") still showed an open popup for an Auctions-ledger
  // parcel from before the switch. Every re-render must close it too.
  if (googleState.infoWindow) googleState.infoWindow.close();
}

async function renderGoogle() {
  if (activeStyle !== "google" || googleState.loadState !== "ready" || !googleState.map) return;
  const map = googleState.map;
  const AdvancedMarkerElement = googleState.AdvancedMarkerElement;
  const canvas = $(GOOGLE_CANVAS_ID);
  if (canvas) canvas.dataset.ledger = ledger;

  const byCounty = groupByCounty();
  const selectedCounty = ($("mapCountySelect") || {}).value || "ALL";
  const zoomed = selectedCounty !== "ALL" && byCounty.has(selectedCounty);

  clearGoogleMarkers();

  if (zoomed) {
    const list = byCounty.get(selectedCounty) || [];
    const cc = await loadCentroids();
    const center = cc[selectedCounty];
    if (center && googleState.lastZoomedCounty !== selectedCounty) {
      map.panTo({ lat: center.lat, lng: center.lng });
      map.setZoom(10);
      googleState.lastZoomedCounty = selectedCounty;
    }
    list.filter(hasPin).forEach(p => {
      const el = document.createElement("div");
      el.className = "sat-pin";
      el.setAttribute("role", "button");
      el.setAttribute("tabindex", "0");
      el.setAttribute("aria-label", pinLabel(p) + " - view details");
      const position = { lat: p.latitude, lng: p.longitude };
      el.addEventListener("click", () => showGooglePopup(p, position));
      const m = new AdvancedMarkerElement({ map, position, content: el });
      googleState.markers.push(m);
    });
    return;
  }

  googleState.lastZoomedCounty = null;
  if (STATEWIDE_VIEW[PAGE_STATE]) {
    const v = STATEWIDE_VIEW[PAGE_STATE];
    const c = map.getCenter();
    if (Math.abs(c.lng() - v.center[0]) > 4 || Math.abs(c.lat() - v.center[1]) > 4) {
      map.setCenter({ lat: v.center[1], lng: v.center[0] });
      map.setZoom(v.zoom);
    }
  }

  const cc = await loadCentroids();
  const counts = Array.from(byCounty.values(), r => r.length);
  const max = counts.length ? Math.max(...counts) : 0;

  Array.from(byCounty.entries())
    .sort((a, b) => b[1].length - a[1].length)
    .forEach(([county, list]) => {
      const center = cc[county];
      if (!center) return;
      const r = radiusPx(list.length, max);
      const el = document.createElement("div");
      el.className = "sat-county-bubble";
      el.style.width = el.style.height = (r * 2) + "px";
      el.style.fontSize = Math.max(11, Math.min(18, r * 0.62)) + "px";
      el.textContent = String(list.length);
      el.setAttribute("role", "button");
      el.setAttribute("tabindex", "0");
      el.setAttribute("aria-label",
        `${county} County, ${list.length} ${list.length === 1 ? "property" : "properties"} - activate to filter the list`);
      el.addEventListener("click", () => selectCounty(county));
      el.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectCounty(county); }
      });
      const m = new AdvancedMarkerElement({ map, position: { lat: center.lat, lng: center.lng }, content: el });
      googleState.markers.push(m);
    });
}

function showGooglePopup(p, position) {
  if (!googleState.infoWindow || !googleState.map) return;
  const el = document.createElement("div");
  el.innerHTML =
    `<p class="sat-popup-addr">${escapeHtml(pinLabel(p))}</p>` +
    `<p class="sat-popup-meta">${escapeHtml(p.county || "")} County - ${escapeHtml(priceLineFor(p))}</p>`;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "sat-popup-open";
  btn.textContent = "View details";
  btn.addEventListener("click", () => { if (openDetail) openDetail(p); });
  el.appendChild(btn);
  googleState.infoWindow.setPosition(position);
  googleState.infoWindow.setContent(el);
  googleState.infoWindow.open(googleState.map);
}

// ============================================================================
// MAPTILER PROVIDER
// ============================================================================
// MapLibre GL JS - an open-source, API-compatible fork of Mapbox GL JS (see
// this file's header, Phase 60). Loaded from a CDN rather than a provider's
// own host, since MapTiler doesn't host the library itself the way Mapbox
// does at api.mapbox.com; unpkg mirrors the published npm package verbatim.
const MAPLIBRE_GL_VERSION = "4.7.1"; // bump alongside a check of
  // https://www.npmjs.com/package/maplibre-gl for a newer stable

const maptilerState = {
  gl: null,          // the maplibregl module, once loaded
  map: null,          // the maplibregl.Map instance, once created
  loadState: "idle",  // "idle" | "loading" | "ready" | "unconfigured" | "error"
  markers: [],
  popup: null,
  lastZoomedCounty: null
};

function loadMapLibreGl() {
  if (window.maplibregl) return Promise.resolve(window.maplibregl);
  if (loadMapLibreGl._p) return loadMapLibreGl._p;
  loadMapLibreGl._p = new Promise((resolve, reject) => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `https://unpkg.com/maplibre-gl@${MAPLIBRE_GL_VERSION}/dist/maplibre-gl.css`;
    document.head.appendChild(link);

    const script = document.createElement("script");
    script.src = `https://unpkg.com/maplibre-gl@${MAPLIBRE_GL_VERSION}/dist/maplibre-gl.js`;
    script.onload = () => resolve(window.maplibregl);
    script.onerror = () => reject(new Error("MapLibre GL JS failed to load"));
    document.head.appendChild(script);
  });
  return loadMapLibreGl._p;
}

async function ensureMaptilerMap() {
  if (maptilerState.loadState === "ready" || maptilerState.loadState === "loading") return;
  const key = maptilerKey();
  if (!key) {
    maptilerState.loadState = "unconfigured";
    setupMessage(
      MAPTILER_CANVAS_ID,
      `<b>MapTiler satellite view isn't set up yet</b>` +
      `<span>Add a free MapTiler key as <code>maptilerKey</code> in ` +
      `<code>config.js</code>, then reload. The outline map on the left ` +
      `still works fully without one.</span>`
    );
    return;
  }
  maptilerState.loadState = "loading";
  setupMessage(MAPTILER_CANVAS_ID, `<b>Loading MapTiler satellite map…</b>`);
  try {
    maptilerState.gl = await loadMapLibreGl();
    const canvas = $(MAPTILER_CANVAS_ID);
    canvas.innerHTML = "";
    const view = STATEWIDE_VIEW[PAGE_STATE] || STATEWIDE_VIEW.FL;
    maptilerState.map = new maptilerState.gl.Map({
      container: canvas,
      // "hybrid" = satellite imagery + labels, MapTiler's closest match to
      // Mapbox's old satellite-streets-v12 style this replaced.
      style: `https://api.maptiler.com/maps/hybrid/style.json?key=${key}`,
      center: view.center,
      zoom: view.zoom,
      attributionControl: true
    });
    maptilerState.map.addControl(new maptilerState.gl.NavigationControl({ showCompass: false }), "top-right");
    maptilerState.popup = new maptilerState.gl.Popup({ closeButton: true, closeOnClick: false, offset: 14 });
    maptilerState.map.on("load", () => {
      maptilerState.loadState = "ready";
      renderMaptiler();
    });
  } catch (err) {
    maptilerState.loadState = "error";
    setupMessage(
      MAPTILER_CANVAS_ID,
      `<b>MapTiler satellite map couldn't load</b>` +
      `<span>Check your connection and reload. The outline map still ` +
      `works offline - switch back with the Map button above.</span>`
    );
  }
}

function clearMaptilerMarkers() {
  maptilerState.markers.forEach(m => m.remove());
  maptilerState.markers = [];
  // Phase 62: same fix as clearGoogleMarkers() above, for the MapLibre
  // Popup, which is likewise its own object clearing markers never reached.
  if (maptilerState.popup) maptilerState.popup.remove();
}

async function renderMaptiler() {
  if (activeStyle !== "maptiler" || maptilerState.loadState !== "ready" || !maptilerState.map) return;
  const gl = maptilerState.gl;
  const map = maptilerState.map;
  const canvas = $(MAPTILER_CANVAS_ID);
  if (canvas) canvas.dataset.ledger = ledger;

  const byCounty = groupByCounty();
  const selectedCounty = ($("mapCountySelect") || {}).value || "ALL";
  const zoomed = selectedCounty !== "ALL" && byCounty.has(selectedCounty);

  clearMaptilerMarkers();

  if (zoomed) {
    const list = byCounty.get(selectedCounty) || [];
    const cc = await loadCentroids();
    const center = cc[selectedCounty];
    if (center && maptilerState.lastZoomedCounty !== selectedCounty) {
      map.flyTo({ center: [center.lng, center.lat], zoom: 10, essential: true });
      maptilerState.lastZoomedCounty = selectedCounty;
    }
    list.filter(hasPin).forEach(p => {
      const el = document.createElement("div");
      el.className = "sat-pin";
      el.setAttribute("role", "button");
      el.setAttribute("tabindex", "0");
      el.setAttribute("aria-label", pinLabel(p) + " - view details");
      el.addEventListener("click", () => showMaptilerPopup(p, [p.longitude, p.latitude]));
      const m = new gl.Marker({ element: el, anchor: "bottom" })
        .setLngLat([p.longitude, p.latitude])
        .addTo(map);
      maptilerState.markers.push(m);
    });
    return;
  }

  maptilerState.lastZoomedCounty = null;
  if (STATEWIDE_VIEW[PAGE_STATE]) {
    const v = STATEWIDE_VIEW[PAGE_STATE];
    const c = map.getCenter();
    if (Math.abs(c.lng - v.center[0]) > 4 || Math.abs(c.lat - v.center[1]) > 4) {
      map.jumpTo({ center: v.center, zoom: v.zoom });
    }
  }

  const cc = await loadCentroids();
  const counts = Array.from(byCounty.values(), r => r.length);
  const max = counts.length ? Math.max(...counts) : 0;

  Array.from(byCounty.entries())
    .sort((a, b) => b[1].length - a[1].length)
    .forEach(([county, list]) => {
      const center = cc[county];
      if (!center) return;
      const r = radiusPx(list.length, max);
      const el = document.createElement("div");
      el.className = "sat-county-bubble";
      el.style.width = el.style.height = (r * 2) + "px";
      el.style.fontSize = Math.max(11, Math.min(18, r * 0.62)) + "px";
      el.textContent = String(list.length);
      el.setAttribute("role", "button");
      el.setAttribute("tabindex", "0");
      el.setAttribute("aria-label",
        `${county} County, ${list.length} ${list.length === 1 ? "property" : "properties"} - activate to filter the list`);
      el.addEventListener("click", () => selectCounty(county));
      el.addEventListener("keydown", e => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectCounty(county); }
      });
      const m = new gl.Marker({ element: el, anchor: "center" })
        .setLngLat([center.lng, center.lat])
        .addTo(map);
      maptilerState.markers.push(m);
    });
}

function showMaptilerPopup(p, lngLat) {
  if (!maptilerState.popup || !maptilerState.map) return;
  const el = document.createElement("div");
  el.innerHTML =
    `<p class="sat-popup-addr">${escapeHtml(pinLabel(p))}</p>` +
    `<p class="sat-popup-meta">${escapeHtml(p.county || "")} County - ${escapeHtml(priceLineFor(p))}</p>`;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "sat-popup-open";
  btn.textContent = "View details";
  btn.addEventListener("click", () => { if (openDetail) openDetail(p); });
  el.appendChild(btn);
  maptilerState.popup.setLngLat(lngLat).setDOMContent(el).addTo(maptilerState.map);
}

// ---------------------------------------------------------------------------
// wiring - same contract explore.js uses, listened to independently (see
// this file's header for why the two modules don't reach into each other)
// ---------------------------------------------------------------------------
function absorb(detail) {
  const d = detail || {};
  rows = Array.isArray(d.rows) ? d.rows : [];
  ledger = d.ledger || ledger;
  openDetail = d.openDetail || openDetail;
  renderGoogle();
  renderMaptiler();
}

window.addEventListener("tdw:maprendered", e => absorb(e.detail));
if (window.__tdwMapLastRender) absorb(window.__tdwMapLastRender);

bindStyleToggle();
