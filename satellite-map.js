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
// views, switchable, neither one replacing the other. That's what this file
// builds. See CLAUDE.md's Phase 55 section for the full exchange.
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
// Mapbox GL JS needs an access token only Marc can obtain (a free Mapbox
// account - see config.js's mapboxToken comment for the exact steps). This
// file never fetches Mapbox's script, CSS, or a single tile unless BOTH (a)
// window.TDW_CONFIG.mapboxToken is non-empty AND (b) the user has actually
// clicked "Satellite" at least once. Until then the toggle button is fully
// visible (so the feature is discoverable) but inert as far as network
// traffic goes - clicking it with no token just swaps in a plain-language
// setup message, no different from any other empty state in this app.
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
// map's own fixed viewBox.
const STATEWIDE_VIEW = {
  FL: { center: [-81.6, 28.1], zoom: 5.6 },
  TX: { center: [-99.3, 31.4], zoom: 5.1 }
};

const MAPBOX_GL_VERSION = "v3.30.0"; // bump alongside a check of
  // https://docs.mapbox.com/mapbox-gl-js/guides/install/ for a newer stable

let rows = [];
let ledger = "all";
let openDetail = null;

let activeStyle = "outline";   // "outline" | "satellite" - which canvas shows
let gl = null;                 // the mapboxgl module, once loaded
let map = null;                // the mapboxgl.Map instance, once created
let loadState = "idle";        // "idle" | "loading" | "ready" | "unconfigured" | "error"
let markers = [];              // live mapboxgl.Marker instances, cleared each redraw
let popup = null;
let lastZoomedCounty = null;   // county last flown to, so redraws don't re-fly
                               // the camera on every unrelated toolbar change

function mapboxToken() {
  const t = (window.TDW_CONFIG || {}).mapboxToken;
  return typeof t === "string" ? t.trim() : "";
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
    // Container was just un-hidden; Mapbox measured it at whatever size it
    // had (possibly 0x0) if init happened earlier while hidden. resize() is
    // a no-op if nothing changed, so it's safe to always call.
    if (map) requestAnimationFrame(() => map.resize());
    renderSatellite();
  }
}

// ---------------------------------------------------------------------------
// lazy Mapbox GL load + map init
// ---------------------------------------------------------------------------
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

function setupMessage(html) {
  const canvas = $(CANVAS_ID);
  if (!canvas) return;
  canvas.innerHTML = `<div class="satellite-map-setup">${html}</div>`;
}

async function ensureSatelliteMap() {
  if (loadState === "ready" || loadState === "loading") return;
  const token = mapboxToken();
  if (!token) {
    loadState = "unconfigured";
    setupMessage(
      `<b>Satellite view isn't set up yet</b>` +
      `<span>Add a free Mapbox token as <code>mapboxToken</code> in ` +
      `<code>config.js</code>, then reload. The outline map on the left ` +
      `still works fully without one.</span>`
    );
    return;
  }
  loadState = "loading";
  setupMessage(`<b>Loading satellite map…</b>`);
  try {
    gl = await loadMapboxGl();
    gl.accessToken = token;
    const canvas = $(CANVAS_ID);
    canvas.innerHTML = "";
    const view = STATEWIDE_VIEW[PAGE_STATE] || STATEWIDE_VIEW.FL;
    map = new gl.Map({
      container: canvas,
      style: "mapbox://styles/mapbox/satellite-streets-v12",
      center: view.center,
      zoom: view.zoom,
      attributionControl: true
    });
    map.addControl(new gl.NavigationControl({ showCompass: false }), "top-right");
    popup = new gl.Popup({ closeButton: true, closeOnClick: false, offset: 14 });
    map.on("load", () => {
      loadState = "ready";
      renderSatellite();
    });
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
  markers.forEach(m => m.remove());
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
      map.flyTo({ center: [center.lng, center.lat], zoom: 10, essential: true });
      lastZoomedCounty = selectedCounty;
    }
    list.filter(hasPin).forEach(p => {
      const el = document.createElement("div");
      el.className = "sat-pin";
      el.setAttribute("role", "button");
      el.setAttribute("tabindex", "0");
      el.setAttribute("aria-label", pinLabel(p) + " - view details");
      el.addEventListener("click", () => showPropertyPopup(p, [p.longitude, p.latitude]));
      const m = new gl.Marker({ element: el, anchor: "bottom" })
        .setLngLat([p.longitude, p.latitude])
        .addTo(map);
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
      const m = new gl.Marker({ element: el, anchor: "center" })
        .setLngLat([center.lng, center.lat])
        .addTo(map);
      markers.push(m);
    });
}

function showPropertyPopup(p, lngLat) {
  if (!popup || !map) return;
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
  popup.setLngLat(lngLat).setDOMContent(el).addTo(map);
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
