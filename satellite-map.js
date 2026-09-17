// ============================================================================
// Satellite/terrain basemap for the Map page - an OPTIONAL second view,
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
// Phase 55 shipped on Mapbox GL JS. Marc then got a real Google Maps API key
// ("google gave me a demo api to test") and, asked directly how he wanted it
// wired in, chose "Switch to Google Maps" - a full replacement, not a second
// provider option. This file now uses the Google Maps JavaScript API
// exclusively: same toggle, same bubbles-then-pins model, same event
// contract, different renderer underneath. See config.js's
// googleMapsApiKey comment and CLAUDE.md's Phase 56 section for the CSP
// trade-off that came with this switch (materially larger than Mapbox's).
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
// WHY THIS IS OFF BY DEFAULT AND SAFE WHEN UNCONFIGURED:
// The Google Maps JS API needs an API key only Marc can obtain/manage - see
// config.js's googleMapsApiKey comment. This file never injects Google's
// loader script or fetches a single tile unless BOTH (a)
// window.TDW_CONFIG.googleMapsApiKey is non-empty AND (b) the user has
// actually clicked "Satellite" at least once. Until then the toggle button
// is fully visible (so the feature is discoverable) but inert as far as
// network traffic goes - clicking it with no key just swaps in a
// plain-language setup message, no different from any other empty state in
// this app.
//
// WHAT'S DELIBERATELY THE SAME AS THE OUTLINE MAP, AND WHY:
// Statewide, this draws one bubble per county (sized by count, coloured by
// the active ledger pill - same palette as .cluster-bubble, reused via CSS
// custom properties rather than a second hard-coded one). Clicking a bubble
// sets #mapCountySelect to that county exactly the way explore.js's own
// applyCounty() does (set .value, dispatch a bubbling "change") - the two
// maps share the same toolbar and the same filter, they just draw it two
// different ways. Once a single county is selected, rows narrows to that
// county alone (computeMapRows() in app.js already does this - see its own
// comment), and this module switches from bubbles to real geocoded pins for
// that county and flies the camera in - the same statewide-bubbles / zoomed-
// pins split explore.js's draw()/drawPins() use, for the same honesty reason
// (a pin is a claim of a real coordinate; a bubble is a count).
// ============================================================================

const $ = id => document.getElementById(id);
const CANVAS_ID = "satelliteMapCanvas";
const PAGE_STATE = document.body.dataset.state === "TX" ? "TX" : "FL";

// Roughly centers each state in frame at a zoom that shows the whole thing
// without excess ocean/neighbor-state padding. Not derived from data (there's
// no "centroid of all counties" reason to prefer over a plain eyeballed
// state center) - just a sane initial camera, same spirit as the outline
// map's own fixed viewBox. [lng, lat] kept as the tuple shape (matches
// county-centroids.json / the properties table's lng-then-lat convention);
// converted to Google's {lat, lng} object shape at each call site.
const STATEWIDE_VIEW = {
  FL: { center: [-81.6, 28.1], zoom: 6 },
  TX: { center: [-99.3, 31.4], zoom: 5.4 }
};

// Google's own placeholder Map ID, meant exactly for this situation - trying
// out Advanced Markers without first creating a real Map ID in Cloud Console.
// Fine for Marc's "demo api to test" key; swap for a real Map ID (Google
// Cloud Console -> Maps Management -> Map IDs) if/when this moves off the
// demo key. A Map ID is required for AdvancedMarkerElement - it isn't
// optional the way a Mapbox style URL was.
const GOOGLE_MAP_ID = "DEMO_MAP_ID";

let rows = [];
let ledger = "all";
let openDetail = null;

let activeStyle = "outline";      // "outline" | "satellite" - which canvas shows
let map = null;                   // the google.maps.Map instance, once created
let AdvancedMarkerElement = null; // class ref, once the "marker" library loads
let infoWindow = null;            // shared google.maps.InfoWindow
let loadState = "idle";           // "idle" | "loading" | "ready" | "unconfigured" | "error"
let markers = [];                 // live AdvancedMarkerElement instances, cleared each redraw
let lastZoomedCounty = null;      // county last flown to, so redraws don't re-fly
                                   // the camera on every unrelated toolbar change

function googleMapsApiKey() {
  const k = (window.TDW_CONFIG || {}).googleMapsApiKey;
  return typeof k === "string" ? k.trim() : "";
}

// ---------------------------------------------------------------------------
// style toggle
// ---------------------------------------------------------------------------
function bindStyleToggle() {
  const outlineBtn = $("mapStyleOutline");
  const satBtn = $("mapStyleSatellite");
  if (!outlineBtn || !satBtn) return;
  outlineBtn.addEventListener("click", () => setStyle("outline"));
  satBtn.addEventListener("click", () => setStyle("satellite"));
}

function setStyle(style) {
  if (style === activeStyle) return;
  activeStyle = style;
  const outlineBtn = $("mapStyleOutline");
  const satBtn = $("mapStyleSatellite");
  const outlineCanvas = $("exploreMapCanvas");
  const satCanvas = $(CANVAS_ID);
  if (outlineBtn) outlineBtn.classList.toggle("on", style === "outline");
  if (satBtn) satBtn.classList.toggle("on", style === "satellite");
  if (outlineCanvas) outlineCanvas.hidden = style !== "outline";
  if (satCanvas) satCanvas.hidden = style !== "satellite";
  // The outline map's own centroids/geometry stay correct while hidden (see
  // this file's header note on why - explore.js only measures once and
  // caches it), so nothing needs to be told to redraw on switching back to it.
  if (style === "satellite") {
    ensureSatelliteMap();
    // Container was just un-hidden; if init happened earlier while hidden,
    // Google may have measured a 0x0 box. Google Maps doesn't expose a
    // Mapbox-style resize() - the documented way to make it re-measure is
    // firing its own "resize" event through google.maps.event.
    if (map && window.google && window.google.maps && window.google.maps.event) {
      requestAnimationFrame(() => window.google.maps.event.trigger(map, "resize"));
    }
    renderSatellite();
  }
}

// ---------------------------------------------------------------------------
// lazy Google Maps JS API load + map init
// ---------------------------------------------------------------------------
// Google's own official dynamic-library-loader bootstrap (see
// https://developers.google.com/maps/documentation/javascript/load-maps-js-api),
// reproduced verbatim from Google's docs and installed inline here instead of
// as a separate <script> tag in index.html/tx.html - identical behavior:
// after this runs once, google.maps.importLibrary(...) is defined and the
// rest of this file uses it to pull in the "maps" and "marker" libraries on
// demand, only when a key is configured and the user has clicked Satellite.
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

function setupMessage(html) {
  const canvas = $(CANVAS_ID);
  if (!canvas) return;
  canvas.innerHTML = `<div class="satellite-map-setup">${html}</div>`;
}

async function ensureSatelliteMap() {
  if (loadState === "ready" || loadState === "loading") return;
  const key = googleMapsApiKey();
  if (!key) {
    loadState = "unconfigured";
    setupMessage(
      `<b>Satellite view isn't set up yet</b>` +
      `<span>Add a Google Maps API key as <code>googleMapsApiKey</code> in ` +
      `<code>config.js</code>, then reload. The outline map on the left ` +
      `still works fully without one.</span>`
    );
    return;
  }
  loadState = "loading";
  setupMessage(`<b>Loading satellite map…</b>`);
  try {
    installGoogleMapsBootstrap(key);
    const { Map, InfoWindow } = await google.maps.importLibrary("maps");
    ({ AdvancedMarkerElement } = await google.maps.importLibrary("marker"));
    const canvas = $(CANVAS_ID);
    canvas.innerHTML = "";
    const view = STATEWIDE_VIEW[PAGE_STATE] || STATEWIDE_VIEW.FL;
    map = new Map(canvas, {
      center: { lat: view.center[1], lng: view.center[0] },
      zoom: view.zoom,
      mapId: GOOGLE_MAP_ID,
      mapTypeId: "hybrid", // satellite imagery + labels - closest match to the reference mockup
      streetViewControl: false,
      fullscreenControl: false,
      mapTypeControl: false
    });
    infoWindow = new InfoWindow();
    loadState = "ready";
    renderSatellite();
  } catch (err) {
    loadState = "error";
    setupMessage(
      `<b>Satellite map couldn't load</b>` +
      `<span>Check your connection and reload. The outline map still ` +
      `works offline - switch back with the Map button above.</span>`
    );
  }
}

// ---------------------------------------------------------------------------
// county centroids (Census-derived - see county-centroids.json's own
// generation notes in CLAUDE.md's Phase 55 section)
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

function clearMarkers() {
  markers.forEach(m => { m.map = null; });
  markers = [];
}

// Same select-and-dispatch as explore.js's applyCounty(), so both basemaps
// drive the one toolbar the same way - see that function's own comment for
// why a plain "change" event (not a direct app.js call) is the contract.
function selectCounty(county) {
  const select = $("mapCountySelect");
  if (!select) return;
  if (county !== "ALL" && !Array.from(select.options).some(o => o.value === county)) return;
  select.value = county;
  select.dispatchEvent(new Event("change", { bubbles: true }));
}

async function renderSatellite() {
  if (activeStyle !== "satellite" || loadState !== "ready" || !map) return;
  const canvas = $(CANVAS_ID);
  if (canvas) canvas.dataset.ledger = ledger;

  const byCounty = new Map();
  rows.forEach(p => {
    if (!byCounty.has(p.county)) byCounty.set(p.county, []);
    byCounty.get(p.county).push(p);
  });

  const selectedCounty = ($("mapCountySelect") || {}).value || "ALL";
  const zoomed = selectedCounty !== "ALL" && byCounty.has(selectedCounty);

  clearMarkers();

  if (zoomed) {
    const list = byCounty.get(selectedCounty) || [];
    const cc = await loadCentroids();
    const center = cc[selectedCounty];
    if (center && lastZoomedCounty !== selectedCounty) {
      map.panTo({ lat: center.lat, lng: center.lng });
      map.setZoom(10);
      lastZoomedCounty = selectedCounty;
    }
    list.filter(hasPin).forEach(p => {
      const el = document.createElement("div");
      el.className = "sat-pin";
      el.setAttribute("role", "button");
      el.setAttribute("tabindex", "0");
      el.setAttribute("aria-label", pinLabel(p) + " - view details");
      const position = { lat: p.latitude, lng: p.longitude };
      el.addEventListener("click", () => showPropertyPopup(p, position));
      const m = new AdvancedMarkerElement({
        map,
        position,
        content: el,
        anchor: undefined // AdvancedMarkerElement anchors bottom-center by default, matching the pin's own drop-shape origin
      });
      markers.push(m);
    });
    return;
  }

  lastZoomedCounty = null;
  if (STATEWIDE_VIEW[PAGE_STATE]) {
    const v = STATEWIDE_VIEW[PAGE_STATE];
    // Only recenter statewide if we're not already roughly there - avoids
    // yanking the camera back every render while the user is panning around.
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
      if (!center) return; // not in county-centroids.json - shouldn't happen,
                            // names are 1:1 with ALL_COUNTIES, but don't crash
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
      const m = new AdvancedMarkerElement({
        map,
        position: { lat: center.lat, lng: center.lng },
        content: el
      });
      markers.push(m);
    });
}

function showPropertyPopup(p, position) {
  if (!infoWindow || !map) return;
  const bids = Number(p.bid);
  const priceLine = bids > 0
    ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(bids)
    : "no published price";
  const el = document.createElement("div");
  el.innerHTML =
    `<p class="sat-popup-addr">${escapeHtml(pinLabel(p))}</p>` +
    `<p class="sat-popup-meta">${escapeHtml(p.county || "")} County - ${escapeHtml(priceLine)}</p>`;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "sat-popup-open";
  btn.textContent = "View details";
  btn.addEventListener("click", () => { if (openDetail) openDetail(p); });
  el.appendChild(btn);
  infoWindow.setPosition(position);
  infoWindow.setContent(el);
  infoWindow.open(map);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
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
  renderSatellite();
}

window.addEventListener("tdw:maprendered", e => absorb(e.detail));
if (window.__tdwMapLastRender) absorb(window.__tdwMapLastRender);

bindStyleToggle();
