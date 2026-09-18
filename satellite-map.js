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
// sent his Mapbox token back. So the toggle is now three-way: the same-
// origin outline map (default, no third party), Google, and Mapbox - each
// independent, each off/inert until its own key/token is present, neither
// one replacing the other. This file now owns two provider implementations
// side by side rather than picking one; see the "GOOGLE PROVIDER" and
// "MAPBOX PROVIDER" sections below. Kept as one file rather than split into
// three (a Google-only and Mapbox-only version were each their own file at
// different points in this project's history) because the two providers
// share most of their surrounding logic (county grouping, centroids,
// zoomed-vs-statewide detection, the toolbar contract) and a single toggle
// dispatch is simpler to reason about than cross-module wiring for what's
// still, at heart, one feature with two swappable backends.
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
// Google needs an API key (window.TDW_CONFIG.googleMapsApiKey) and Mapbox
// needs an access token (window.TDW_CONFIG.mapboxToken) - each only Marc can
// obtain/manage, see config.js's comments. This file never injects either
// provider's loader script or fetches a single tile for a provider unless
// BOTH (a) that provider's key/token is non-empty AND (b) the user has
// actually clicked that provider's button at least once. Clicking a
// provider's button with no key/token just swaps in a plain-language setup
// message naming that provider - no different from any other empty state in
// this app, and it never touches the other provider's state.
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
const CANVAS_ID = "satelliteMapCanvas";
const PAGE_STATE = document.body.dataset.state === "TX" ? "TX" : "FL";

// Roughly centers each state in frame at a zoom that shows the whole thing
// without excess ocean/neighbor-state padding. Not derived from data (there's
// no "centroid of all counties" reason to prefer over a plain eyeballed
// state center) - just a sane initial camera, same spirit as the outline
// map's own fixed viewBox. Shared by both providers; Google and Mapbox each
// convert the [lng, lat] tuple into their own center-object shape.
const STATEWIDE_VIEW = {
  FL: { center: [-81.6, 28.1], zoom: 5.6 },
  TX: { center: [-99.3, 31.4], zoom: 5.1 }
};

let rows = [];
let ledger = "all";
let openDetail = null;

let activeStyle = "outline"; // "outline" | "google" | "mapbox" - which canvas shows

function googleMapsApiKey() {
  const k = (window.TDW_CONFIG || {}).googleMapsApiKey;
  return typeof k === "string" ? k.trim() : "";
}

function mapboxToken() {
  const t = (window.TDW_CONFIG || {}).mapboxToken;
  return typeof t === "string" ? t.trim() : "";
}

// ---------------------------------------------------------------------------
// style toggle - three-way: outline (default, no third party) / google / mapbox
// ---------------------------------------------------------------------------
function bindStyleToggle() {
  const outlineBtn = $("mapStyleOutline");
  const googleBtn = $("mapStyleGoogle");
  const mapboxBtn = $("mapStyleMapbox");
  if (!outlineBtn) return;
  outlineBtn.addEventListener("click", () => setStyle("outline"));
  if (googleBtn) googleBtn.addEventListener("click", () => setStyle("google"));
  if (mapboxBtn) mapboxBtn.addEventListener("click", () => setStyle("mapbox"));
}

function setStyle(style) {
  if (style === activeStyle) return;
  activeStyle = style;
  const outlineBtn = $("mapStyleOutline");
  const googleBtn = $("mapStyleGoogle");
  const mapboxBtn = $("mapStyleMapbox");
  const outlineCanvas = $("exploreMapCanvas");
  const satCanvas = $(CANVAS_ID);
  if (outlineBtn) outlineBtn.classList.toggle("on", style === "outline");
  if (googleBtn) googleBtn.classList.toggle("on", style === "google");
  if (mapboxBtn) mapboxBtn.classList.toggle("on", style === "mapbox");
  if (outlineCanvas) outlineCanvas.hidden = style !== "outline";
  if (satCanvas) satCanvas.hidden = style === "outline";
  // The outline map's own centroids/geometry stay correct while hidden (see
  // this file's header note on why - explore.js only measures once and
  // caches it), so nothing needs to be told to redraw on switching back to it.
  if (style === "google") {
    ensureGoogleMap();
    if (googleState.map && window.google && window.google.maps && window.google.maps.event) {
      requestAnimationFrame(() => window.google.maps.event.trigger(googleState.map, "resize"));
    }
    renderGoogle();
  } else if (style === "mapbox") {
    ensureMapboxMap();
    if (mapboxState.map) requestAnimationFrame(() => mapboxState.map.resize());
    renderMapbox();
  }
}

function setupMessage(html) {
  const canvas = $(CANVAS_ID);
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

function radiusPx(count, max) {
  const MIN_R = 15, MAX_R = 34;
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
// Mapbox style URL was.
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
      `<b>Google satellite view isn't set up yet</b>` +
      `<span>Add a Google Maps API key as <code>googleMapsApiKey</code> in ` +
      `<code>config.js</code>, then reload. The outline map on the left ` +
      `still works fully without one.</span>`
    );
    return;
  }
  googleState.loadState = "loading";
  setupMessage(`<b>Loading Google satellite map…</b>`);
  try {
    installGoogleMapsBootstrap(key);
    const { Map, InfoWindow } = await google.maps.importLibrary("maps");
    ({ AdvancedMarkerElement: googleState.AdvancedMarkerElement } = await google.maps.importLibrary("marker"));
    const canvas = $(CANVAS_ID);
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
      `<b>Google satellite map couldn't load</b>` +
      `<span>Check your connection and reload. The outline map still ` +
      `works offline - switch back with the Map button above.</span>`
    );
  }
}

function clearGoogleMarkers() {
  googleState.markers.forEach(m => { m.map = null; });
  googleState.markers = [];
}

async function renderGoogle() {
  if (activeStyle !== "google" || googleState.loadState !== "ready" || !googleState.map) return;
  const map = googleState.map;
  const AdvancedMarkerElement = googleState.AdvancedMarkerElement;
  const canvas = $(CANVAS_ID);
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
// MAPBOX PROVIDER
// ============================================================================
const MAPBOX_GL_VERSION = "v3.30.0"; // bump alongside a check of
  // https://docs.mapbox.com/mapbox-gl-js/guides/install/ for a newer stable

const mapboxState = {
  gl: null,          // the mapboxgl module, once loaded
  map: null,          // the mapboxgl.Map instance, once created
  loadState: "idle",  // "idle" | "loading" | "ready" | "unconfigured" | "error"
  markers: [],
  popup: null,
  lastZoomedCounty: null
};

function loadMapboxGl() {
  if (window.mapboxgl) return Promise.resolve(window.mapboxgl);
  if (loadMapboxGl._p) return loadMapboxGl._p;
  loadMapboxGl._p = new Promise((resolve, reject) => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `https://api.mapbox.com/mapbox-gl-js/${MAPBOX_GL_VERSION}/mapbox-gl.css`;
    document.head.appendChild(link);

    const script = document.createElement("script");
    script.src = `https://api.mapbox.com/mapbox-gl-js/${MAPBOX_GL_VERSION}/mapbox-gl.js`;
    script.onload = () => resolve(window.mapboxgl);
    script.onerror = () => reject(new Error("Mapbox GL JS failed to load"));
    document.head.appendChild(script);
  });
  return loadMapboxGl._p;
}

async function ensureMapboxMap() {
  if (mapboxState.loadState === "ready" || mapboxState.loadState === "loading") return;
  const token = mapboxToken();
  if (!token) {
    mapboxState.loadState = "unconfigured";
    setupMessage(
      `<b>Mapbox satellite view isn't set up yet</b>` +
      `<span>Add a free Mapbox token as <code>mapboxToken</code> in ` +
      `<code>config.js</code>, then reload. The outline map on the left ` +
      `still works fully without one.</span>`
    );
    return;
  }
  mapboxState.loadState = "loading";
  setupMessage(`<b>Loading Mapbox satellite map…</b>`);
  try {
    mapboxState.gl = await loadMapboxGl();
    mapboxState.gl.accessToken = token;
    const canvas = $(CANVAS_ID);
    canvas.innerHTML = "";
    const view = STATEWIDE_VIEW[PAGE_STATE] || STATEWIDE_VIEW.FL;
    mapboxState.map = new mapboxState.gl.Map({
      container: canvas,
      style: "mapbox://styles/mapbox/satellite-streets-v12",
      center: view.center,
      zoom: view.zoom,
      attributionControl: true
    });
    mapboxState.map.addControl(new mapboxState.gl.NavigationControl({ showCompass: false }), "top-right");
    mapboxState.popup = new mapboxState.gl.Popup({ closeButton: true, closeOnClick: false, offset: 14 });
    mapboxState.map.on("load", () => {
      mapboxState.loadState = "ready";
      renderMapbox();
    });
  } catch (err) {
    mapboxState.loadState = "error";
    setupMessage(
      `<b>Mapbox satellite map couldn't load</b>` +
      `<span>Check your connection and reload. The outline map still ` +
      `works offline - switch back with the Map button above.</span>`
    );
  }
}

function clearMapboxMarkers() {
  mapboxState.markers.forEach(m => m.remove());
  mapboxState.markers = [];
}

async function renderMapbox() {
  if (activeStyle !== "mapbox" || mapboxState.loadState !== "ready" || !mapboxState.map) return;
  const gl = mapboxState.gl;
  const map = mapboxState.map;
  const canvas = $(CANVAS_ID);
  if (canvas) canvas.dataset.ledger = ledger;

  const byCounty = groupByCounty();
  const selectedCounty = ($("mapCountySelect") || {}).value || "ALL";
  const zoomed = selectedCounty !== "ALL" && byCounty.has(selectedCounty);

  clearMapboxMarkers();

  if (zoomed) {
    const list = byCounty.get(selectedCounty) || [];
    const cc = await loadCentroids();
    const center = cc[selectedCounty];
    if (center && mapboxState.lastZoomedCounty !== selectedCounty) {
      map.flyTo({ center: [center.lng, center.lat], zoom: 10, essential: true });
      mapboxState.lastZoomedCounty = selectedCounty;
    }
    list.filter(hasPin).forEach(p => {
      const el = document.createElement("div");
      el.className = "sat-pin";
      el.setAttribute("role", "button");
      el.setAttribute("tabindex", "0");
      el.setAttribute("aria-label", pinLabel(p) + " - view details");
      el.addEventListener("click", () => showMapboxPopup(p, [p.longitude, p.latitude]));
      const m = new gl.Marker({ element: el, anchor: "bottom" })
        .setLngLat([p.longitude, p.latitude])
        .addTo(map);
      mapboxState.markers.push(m);
    });
    return;
  }

  mapboxState.lastZoomedCounty = null;
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
      mapboxState.markers.push(m);
    });
}

function showMapboxPopup(p, lngLat) {
  if (!mapboxState.popup || !mapboxState.map) return;
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
  mapboxState.popup.setLngLat(lngLat).setDOMContent(el).addTo(mapboxState.map);
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
  renderMapbox();
}

window.addEventListener("tdw:maprendered", e => absorb(e.detail));
if (window.__tdwMapLastRender) absorb(window.__tdwMapLastRender);

bindStyleToggle();
