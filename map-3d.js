// ============================================================================
// map-3d.js - shared map helpers for the Map page and the property page
// (2026-11-10). Lazy-imported (import("./map-3d.js")) by satellite-map.js
// and, for the property page's GIS card, by app.js. No <script> tag, no DOM
// access at import, so the pure functions below can be tested in a page or
// under Node.
//
// WHAT IT DOES
//  - loadMapLibre()          the one MapLibre GL JS loader (moved here from
//                            satellite-map.js; same pinned version, same CDN).
//  - loadGoogleMaps(key)     Google's own dynamic-library-loader bootstrap
//                            (moved here from satellite-map.js, verbatim).
//  - addParcelLayers(map, boundary, opts) / removeParcelLayers(map)
//                            the parcel outline as three FLAT GL layers: a
//                            fill (ledger colour, 0.18), a light halo and a
//                            line. The parcel is never extruded: no source
//                            publishes a height for it (see parcelLayerSpecs).
//  - cameraForBbox(bbox, view) the camera (centre, zoom, pitch, bearing,
//                            padding) that frames a parcel's bounding box in
//                            the part of the stage the peek card leaves clear.
//  - applyDepth(map, on, opts) MapTiler terrain (terrain-rgb-v2, exaggeration
//                            1.2) and, where the style has a building layer,
//                            an extrusion of THAT layer (OpenStreetMap heights
//                            as MapTiler publishes them). Returns what it
//                            actually added, so the caption never claims
//                            buildings the style does not have.
//  - mountGisMap(el, opts)   the property page's live mini-map (see contract).
//  - mountStreetView(el, opts) Google Street View panorama, ADMINS ONLY.
//
// mountGisMap CONTRACT (for the property page's GIS card, app.js)
//   const m = await import("./map-3d.js");
//   const res = await m.mountGisMap(el, {
//     lat, lng,                 // the row's own point (numbers); required
//     propertyId,               // the row id, passed to boundaryFetcher
//     row,                      // optional: the row (for the fetcher's point check)
//     ledger,                   // optional: "laft" | "auction" | "certificate"
//     boundaryFetcher           // optional: (propertyId, row) => Promise of
//                               //   parcel-boundary.js fetchPropertyBoundary's
//                               //   result ({status:"available", boundary} | ...)
//   });
//   res.status: "ready"        map drawn (with the outline when one is available)
//               "unconfigured" no maptilerKey in config.js - el untouched
//               "no_coords"    no usable lat/lng - el untouched
//               "error"        MapLibre / the style failed - el restored to
//                              exactly what it held before the call
//   res.outline: true when the outline was drawn (its credit is shown under
//                the map, never hidden - the boundary's display conditions).
//   res.destroy(): removes the map and puts el's previous content back.
//   Nothing here fetches a boundary on its own: without a boundaryFetcher (or
//   when it answers anything but "available") only the point is pinned.
//
// mountStreetView CONTRACT
//   await m.mountStreetView(el, { lat, lng }) -> { status: "ready" | "no_imagery"
//     | "not_admin" | "unconfigured" | "error", destroy() }
//   Shown only to admins (window.__tdwIsAdmin === true) and only with a
//   googleMapsApiKey; customers never get a request to Google from it.
//
// Nothing here invents data: the outline is drawn only from a boundary the
// server returned and parcel-boundary.js validated; terrain and building
// heights are MapTiler's / OpenStreetMap's own and are captioned as such.
// ============================================================================

export const MAPLIBRE_GL_VERSION = "4.7.1"; // bump alongside a check of https://www.npmjs.com/package/maplibre-gl
export const PARCEL_SOURCE_ID = "tdw-parcel";
export const PARCEL_LAYER_IDS = ["tdw-parcel-fill", "tdw-parcel-halo", "tdw-parcel-line"];
export const TERRAIN_SOURCE_ID = "tdw-terrain";
export const BUILDINGS_LAYER_ID = "tdw-buildings-3d";
export const TERRAIN_EXAGGERATION = 1.2;
export const SELECT_PITCH = 55;
export const SELECT_BEARING = -18;
export const PARCEL_MAX_ZOOM = 19;
export const PARCEL_FILL_OPACITY = 0.18;
export const GIS_TILT_PITCH = 50;            // the mini-map's first view when no outline frames it
export const GIS_PITCH_ZOOM_BACKOFF = 0.4;   // see mountGisMap
export const DEPTH_CAPTION_TERRAIN = "Terrain: MapTiler";
export const DEPTH_CAPTION_BOTH = "Terrain and buildings: MapTiler / OpenStreetMap";
// Ledger colours (CLAUDE.md "TAXACQ brand": unchanged per ledger).
export const LEDGER_COLORS = { laft: "#4E6B54", auction: "#A4512A", certificate: "#6B4A6E" };
export const DEFAULT_PARCEL_COLOR = "#1F3A2E";

const isNum = v => typeof v === "number" && Number.isFinite(v);

export function maptilerKey() {
  const k = (typeof window !== "undefined" && window.TDW_CONFIG) ? window.TDW_CONFIG.maptilerKey : "";
  return typeof k === "string" ? k.trim() : "";
}
export function googleMapsApiKey() {
  const k = (typeof window !== "undefined" && window.TDW_CONFIG) ? window.TDW_CONFIG.googleMapsApiKey : "";
  return typeof k === "string" ? k.trim() : "";
}
export function maptilerStyleUrl(imagery, key) {
  return `https://api.maptiler.com/maps/${imagery === "streets" ? "streets-v2" : "hybrid"}/style.json?key=${encodeURIComponent(key || maptilerKey())}`;
}
export function terrainTilesUrl(key) {
  return `https://api.maptiler.com/tiles/terrain-rgb-v2/tiles.json?key=${encodeURIComponent(key || maptilerKey())}`;
}
export function ledgerColor(source) {
  return LEDGER_COLORS[source] || DEFAULT_PARCEL_COLOR;
}

// ---------------------------------------------------------------------------
// pure geometry
// ---------------------------------------------------------------------------
// Bounding box of every ring of every polygon: { minX, minY, maxX, maxY } or null.
export function bboxOfPolygons(polygons) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  (polygons || []).forEach(poly => (poly || []).forEach(ring => (ring || []).forEach(pos => {
    if (!Array.isArray(pos) || !isNum(pos[0]) || !isNum(pos[1])) return;
    if (pos[0] < minX) minX = pos[0];
    if (pos[0] > maxX) maxX = pos[0];
    if (pos[1] < minY) minY = pos[1];
    if (pos[1] > maxY) maxY = pos[1];
  })));
  return minX === Infinity ? null : { minX, minY, maxX, maxY };
}
// A GeoJSON Polygon / MultiPolygon geometry, Feature or FeatureCollection.
export function bboxOfGeoJSON(geo) {
  if (!geo || typeof geo !== "object") return null;
  if (geo.type === "FeatureCollection") {
    const boxes = (geo.features || []).map(bboxOfGeoJSON).filter(Boolean);
    if (!boxes.length) return null;
    return boxes.reduce((a, b) => ({ minX: Math.min(a.minX, b.minX), minY: Math.min(a.minY, b.minY), maxX: Math.max(a.maxX, b.maxX), maxY: Math.max(a.maxY, b.maxY) }));
  }
  if (geo.type === "Feature") return bboxOfGeoJSON(geo.geometry);
  if (geo.type === "Polygon") return bboxOfPolygons([geo.coordinates]);
  if (geo.type === "MultiPolygon") return bboxOfPolygons(geo.coordinates);
  return null;
}
// The validated boundary (parcel-boundary.js: { polygons, bbox }) as GeoJSON.
// Its properties carry nothing but the ledger - never a height.
export function boundaryFeatureCollection(boundary, ledger) {
  const polygons = boundary && Array.isArray(boundary.polygons) ? boundary.polygons : [];
  return {
    type: "FeatureCollection",
    features: polygons.length ? [{ type: "Feature", properties: { ledger: ledger || "" }, geometry: { type: "MultiPolygon", coordinates: polygons } }] : []
  };
}

// Web Mercator, 512px tiles (MapLibre's zoom convention), normalised 0..1.
export function mercNorm(lng, lat) {
  const s = Math.sin((Math.max(-85.05, Math.min(85.05, lat)) * Math.PI) / 180);
  return [(lng + 180) / 360, 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)];
}

// The camera that frames `bbox` inside a `width` x `height` stage minus
// `padding` (the peek card's covered side + a margin), rotated by `bearing`.
// Pitch foreshortens the ground vertically by about cos(pitch), so the
// vertical span is scaled by that before fitting - an approximation that keeps
// the whole parcel in view at 55 degrees. Zoom is capped at `maxZoom`, so a
// tiny parcel is not blown up past imagery resolution.
export function cameraForBbox(bbox, view) {
  const v = Object.assign({ width: 800, height: 600, padding: null, pitch: SELECT_PITCH, bearing: SELECT_BEARING, maxZoom: PARCEL_MAX_ZOOM, margin: 48 }, view || {});
  const pad = Object.assign({ top: 0, right: 0, bottom: 0, left: 0 }, v.padding || {});
  // The margin shrinks with the space left between the overlays, so a small
  // band (a phone with the peek sheet up) still frames the parcel at a
  // sensible zoom instead of collapsing to the 40px floor.
  const rawW = v.width - pad.left - pad.right, rawH = v.height - pad.top - pad.bottom;
  const mW = Math.max(0, Math.min(v.margin, rawW * 0.15)), mH = Math.max(0, Math.min(v.margin, rawH * 0.15));
  const availW = Math.max(40, rawW - 2 * mW);
  const availH = Math.max(40, rawH - 2 * mH);
  const [x0, y1] = mercNorm(bbox.minX, bbox.minY);
  const [x1, y0] = mercNorm(bbox.maxX, bbox.maxY);
  const dx = Math.max(1e-12, x1 - x0), dy = Math.max(1e-12, y1 - y0);
  const b = (v.bearing * Math.PI) / 180;
  const rw = dx * Math.abs(Math.cos(b)) + dy * Math.abs(Math.sin(b));
  const rh = (dx * Math.abs(Math.sin(b)) + dy * Math.abs(Math.cos(b))) * Math.cos((v.pitch * Math.PI) / 180);
  const scale = Math.min(availW / rw, availH / Math.max(1e-12, rh));
  const zoom = Math.min(v.maxZoom, Math.log2(scale / 512));
  return {
    center: [(bbox.minX + bbox.maxX) / 2, (bbox.minY + bbox.maxY) / 2],
    zoom: Math.round(zoom * 100) / 100,
    pitch: v.pitch,
    bearing: v.bearing,
    padding: pad
  };
}

// The three FLAT layers of the parcel outline. Types are fill / line / line:
// never fill-extrusion - no source publishes the parcel's height, so drawing
// it as a block would invent one.
export function parcelLayerSpecs(color) {
  const c = color || DEFAULT_PARCEL_COLOR;
  return [
    { id: PARCEL_LAYER_IDS[0], type: "fill", source: PARCEL_SOURCE_ID, paint: { "fill-color": c, "fill-opacity": PARCEL_FILL_OPACITY } },
    { id: PARCEL_LAYER_IDS[1], type: "line", source: PARCEL_SOURCE_ID, layout: { "line-join": "round" }, paint: { "line-color": "#FFFFFF", "line-width": 6, "line-opacity": 0.75 } },
    { id: PARCEL_LAYER_IDS[2], type: "line", source: PARCEL_SOURCE_ID, layout: { "line-join": "round" }, paint: { "line-color": c, "line-width": 2.5 } }
  ];
}
// Extrusion of the STYLE's own building layer (OpenMapTiles schema:
// render_height / render_min_height). Never the parcel source.
export function buildingExtrusionSpec(styleLayer) {
  return {
    id: BUILDINGS_LAYER_ID, type: "fill-extrusion", source: styleLayer.source, "source-layer": styleLayer["source-layer"],
    minzoom: 14,
    paint: {
      "fill-extrusion-color": "#D8DED6",
      "fill-extrusion-height": ["coalesce", ["get", "render_height"], 0],
      "fill-extrusion-base": ["coalesce", ["get", "render_min_height"], 0],
      "fill-extrusion-opacity": 0.8
    }
  };
}
// The style's building layer, if it has one.
export function findBuildingLayer(styleLayers) {
  return (styleLayers || []).find(l => l && l["source-layer"] === "building" && l.source && l.source !== PARCEL_SOURCE_ID
    && (l.type === "fill" || l.type === "fill-extrusion") && l.id !== BUILDINGS_LAYER_ID) || null;
}
export function depthCaption(result) {
  if (!result || !result.terrain) return "";
  return result.buildings ? DEPTH_CAPTION_BOTH : DEPTH_CAPTION_TERRAIN;
}

// ---------------------------------------------------------------------------
// loaders
// ---------------------------------------------------------------------------
let mapLibrePromise = null;
export function loadMapLibre() {
  if (typeof window !== "undefined" && window.maplibregl) return Promise.resolve(window.maplibregl);
  if (mapLibrePromise) return mapLibrePromise;
  mapLibrePromise = new Promise((resolve, reject) => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `https://unpkg.com/maplibre-gl@${MAPLIBRE_GL_VERSION}/dist/maplibre-gl.css`;
    document.head.appendChild(link);
    const script = document.createElement("script");
    script.src = `https://unpkg.com/maplibre-gl@${MAPLIBRE_GL_VERSION}/dist/maplibre-gl.js`;
    script.onload = () => resolve(window.maplibregl);
    script.onerror = () => { mapLibrePromise = null; reject(new Error("MapLibre GL JS failed to load")); };
    document.head.appendChild(script);
  });
  return mapLibrePromise;
}

// Google's own official dynamic-library-loader bootstrap, reproduced verbatim
// from https://developers.google.com/maps/documentation/javascript/load-maps-js-api
// (moved here from satellite-map.js). After it runs once,
// google.maps.importLibrary(...) is defined.
export function loadGoogleMaps(apiKey) {
  if (window.google && window.google.maps && window.google.maps.importLibrary) return window.google.maps;
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
  return window.google.maps;
}

// ---------------------------------------------------------------------------
// MapLibre layers
// ---------------------------------------------------------------------------
export function removeParcelLayers(map) {
  if (!map || !map.getStyle) return;
  try {
    PARCEL_LAYER_IDS.forEach(id => { if (map.getLayer(id)) map.removeLayer(id); });
    if (map.getSource(PARCEL_SOURCE_ID)) map.removeSource(PARCEL_SOURCE_ID);
  } catch { /* style mid-swap: nothing to remove */ }
}
// Adds (or replaces) the outline. Returns false when the style is not ready.
export function addParcelLayers(map, boundary, opts) {
  if (!map || !boundary) return false;
  const o = opts || {};
  removeParcelLayers(map);
  try {
    map.addSource(PARCEL_SOURCE_ID, { type: "geojson", data: boundaryFeatureCollection(boundary, o.ledger) });
    parcelLayerSpecs(o.color || ledgerColor(o.ledger)).forEach(spec => map.addLayer(spec));
    return true;
  } catch {
    return false;
  }
}

// Terrain + the style's own buildings, or neither. -> { terrain, buildings }
export function applyDepth(map, on, opts) {
  const out = { terrain: false, buildings: false };
  if (!map || !map.getStyle) return out;
  const o = opts || {};
  try {
    if (!on) {
      if (map.setTerrain) map.setTerrain(null);
      if (map.getLayer(BUILDINGS_LAYER_ID)) map.removeLayer(BUILDINGS_LAYER_ID);
      return out;
    }
    if (!map.getSource(TERRAIN_SOURCE_ID)) {
      map.addSource(TERRAIN_SOURCE_ID, { type: "raster-dem", url: terrainTilesUrl(o.key), tileSize: 256 });
    }
    if (map.setTerrain) { map.setTerrain({ source: TERRAIN_SOURCE_ID, exaggeration: TERRAIN_EXAGGERATION }); out.terrain = true; }
    const style = map.getStyle();
    const bl = findBuildingLayer(style && style.layers);
    if (bl) {
      if (!map.getLayer(BUILDINGS_LAYER_ID)) {
        // Below the parcel outline, so the flat outline is never hidden.
        const before = PARCEL_LAYER_IDS.find(id => map.getLayer(id));
        map.addLayer(buildingExtrusionSpec(bl), before);
      }
      out.buildings = true;
    }
  } catch { /* style not ready: the caller re-applies on style.load */ }
  return out;
}

// ---------------------------------------------------------------------------
// boundary credit - every surface that draws an outline shows it (credit,
// licence link, change notice, freshness, disclaimer, metadata); same parts
// and wording as app.js's boundaryCreditHtml.
// ---------------------------------------------------------------------------
const escHtml = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function dateOnly(v) {
  const d = new Date(v);
  return isNaN(d) ? String(v) : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
export function boundaryCreditHtml(a) {
  if (!a || !a.credit || !a.changeNotice) return "";
  const link = (url, text) => `<a href="${escHtml(url)}" target="_blank" rel="noopener noreferrer">${escHtml(text)}</a>`;
  const parts = [`<span class="pb-credit-src">Parcel outline: ${escHtml(a.credit)}</span>`];
  if (a.licenseUrl) parts.push(`<span class="pb-credit-lic">Licence: ${link(a.licenseUrl, a.licenseName || "licence")}</span>`);
  parts.push(`<span class="pb-credit-chg">Changes: ${escHtml(a.changeNotice)}</span>`);
  parts.push(a.lastRefreshedAt
    ? `<span class="pb-credit-fresh">Source last refreshed by TAXACQ ${escHtml(dateOnly(a.lastRefreshedAt))}</span>`
    : `<span class="pb-credit-fresh">Source last refreshed by TAXACQ: not yet recorded</span>`);
  if (a.expectedCadence) parts.push(`<span class="pb-credit-cad">Source publishes: ${escHtml(a.expectedCadence)}</span>`);
  if (a.disclaimer) parts.push(`<span class="pb-credit-dis">${escHtml(a.disclaimer)}</span>`);
  if (a.disclaimerUrl) parts.push(`<span class="pb-credit-dis">${link(a.disclaimerUrl, "Source disclaimer")}</span>`);
  if (a.metadataUrl) parts.push(`<span class="pb-credit-meta">${link(a.metadataUrl, "Dataset metadata")}</span>`);
  parts.push(`<span class="pb-credit-note">Outline is for orientation; it is not a survey and does not show ownership or title.</span>`);
  return `<p class="pb-credit m3d-credit" data-pb-credit>${parts.join(" · ")}</p>`;
}

function reducedMotion() {
  return !!(typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-reduced-motion:reduce)").matches);
}

// ---------------------------------------------------------------------------
// The property page's live GIS mini-map (contract in the header).
// ---------------------------------------------------------------------------
export async function mountGisMap(el, opts) {
  const o = opts || {};
  const noop = () => {};
  const lat = Number(o.lat), lng = Number(o.lng);
  if (!el) return { status: "error", outline: false, destroy: noop };
  if (!isNum(lat) || !isNum(lng) || o.lat === null || o.lng === null || o.lat === "" || o.lng === "") return { status: "no_coords", outline: false, destroy: noop };
  const key = maptilerKey();
  if (!key) return { status: "unconfigured", outline: false, destroy: noop };
  const before = el.innerHTML;
  const restore = () => { el.innerHTML = before; el.classList.remove("m3d-gis"); };
  let map = null;
  try {
    const gl = await loadMapLibre();
    el.innerHTML = `<div class="m3d-gis-canvas" role="region" aria-label="Interactive parcel map"></div>`;
    el.classList.add("m3d-gis");
    const canvas = el.firstElementChild;
    map = new gl.Map({
      container: canvas, style: maptilerStyleUrl("satellite", key), center: [lng, lat], zoom: 17,
      pitch: 0, bearing: 0, attributionControl: false, cooperativeGestures: true
    });
    // Compact: the full attribution is one tap away and never covers the
    // parcel on a small map (it used to open across the bottom on a phone).
    map.addControl(new gl.AttributionControl({ compact: true }), "bottom-right");
    map.addControl(new gl.NavigationControl({ showCompass: true, visualizePitch: true }), "top-right");
    const pin = document.createElement("div");
    pin.className = "sat-pin sel m3d-pin";
    pin.setAttribute("aria-hidden", "true");
    pin.innerHTML = '<span class="sat-pin-mark"></span>';
    if (o.ledger) pin.dataset.ledger = o.ledger;
    new gl.Marker({ element: pin, anchor: "bottom" }).setLngLat([lng, lat]).addTo(map);
    await new Promise((resolve, reject) => {
      map.once("load", resolve);
      map.once("error", e => { if (!map.loaded()) reject(e && e.error ? e.error : new Error("style failed")); });
    });
    let outline = false;
    let creditNode = null;
    const wantTilt = o.tilt === true;
    if (typeof o.boundaryFetcher === "function" && o.propertyId != null) {
      let res = null;
      try { res = await o.boundaryFetcher(o.propertyId, o.row || { latitude: lat, longitude: lng }); } catch { res = null; }
      if (res && res.status === "available" && res.boundary && map) {
        outline = addParcelLayers(map, res.boundary, { ledger: o.ledger });
        if (outline) {
          const cam = cameraForBbox(res.boundary.bbox, { width: canvas.clientWidth || 600, height: canvas.clientHeight || 300, pitch: 45, bearing: SELECT_BEARING, margin: 24 });
          // cameraForBbox only approximates perspective: on a small pitched
          // map the near edge of the parcel is magnified and ran off the
          // bottom. Pull back a little so the whole outline stays in view.
          cam.zoom = Math.round((cam.zoom - GIS_PITCH_ZOOM_BACKOFF) * 100) / 100;
          map.easeTo(Object.assign(cam, reducedMotion() ? { duration: 0 } : { duration: 900 }));
          const credit = boundaryCreditHtml(res.boundary.attribution);
          if (credit) {
            // creditAfter: the host clips its content (the property page's
            // picture slot), so the credit goes right after it, never hidden.
            el.insertAdjacentHTML(o.creditAfter ? "afterend" : "beforeend", credit);
            creditNode = o.creditAfter ? el.nextElementSibling : el.lastElementChild;
          }
        }
      }
    }
    // tilt: the pitched view is the first view even without an outline.
    if (!outline && wantTilt && map) {
      map.easeTo({ pitch: GIS_TILT_PITCH, bearing: SELECT_BEARING, duration: reducedMotion() ? 0 : 900 });
    }
    return { status: "ready", outline, tilted: outline || wantTilt, map, destroy: () => {
      try { map.remove(); } catch { /* gone */ }
      if (creditNode && creditNode.parentNode && creditNode !== el && !el.contains(creditNode)) creditNode.remove();
      restore();
    } };
  } catch {
    try { if (map) map.remove(); } catch { /* gone */ }
    restore();
    return { status: "error", outline: false, destroy: noop };
  }
}

// ---------------------------------------------------------------------------
// Google Street View, admins only (contract in the header).
// ---------------------------------------------------------------------------
// Heading in degrees from a panorama's position toward the record's point.
export function headingTo(fromLat, fromLng, toLat, toLng) {
  const r = Math.PI / 180;
  const y = Math.sin((toLng - fromLng) * r) * Math.cos(toLat * r);
  const x = Math.cos(fromLat * r) * Math.sin(toLat * r) - Math.sin(fromLat * r) * Math.cos(toLat * r) * Math.cos((toLng - fromLng) * r);
  return ((Math.atan2(y, x) / r) + 360) % 360;
}
export const STREET_VIEW_RADIUS_M = 50;
export const STREET_VIEW_REFUSAL_WATCH_MS = 20000;
export async function mountStreetView(el, opts) {
  const noop = () => {};
  const o = opts || {};
  if (typeof window === "undefined" || window.__tdwIsAdmin !== true) return { status: "not_admin", destroy: noop };
  const key = googleMapsApiKey();
  if (!key) return { status: "unconfigured", destroy: noop };
  const lat = Number(o.lat), lng = Number(o.lng);
  if (!el || !isNum(lat) || !isNum(lng)) return { status: "error", destroy: noop };
  try {
    loadGoogleMaps(key);
    const lib = await window.google.maps.importLibrary("streetView");
    const svc = new lib.StreetViewService();
    let data = null;
    try {
      const res = await svc.getPanorama({ location: { lat, lng }, radius: STREET_VIEW_RADIUS_M, source: lib.StreetViewSource ? lib.StreetViewSource.OUTDOOR : undefined });
      data = res && res.data;
    } catch { data = null; }
    if (!data || !data.location || !data.location.pano) return { status: "no_imagery", destroy: noop };
    const at = data.location.latLng;
    const heading = at ? headingTo(at.lat(), at.lng(), lat, lng) : 0;
    el.innerHTML = "";
    const pano = new lib.StreetViewPanorama(el, {
      pano: data.location.pano, pov: { heading, pitch: 0 }, zoom: 0,
      addressControl: false, fullscreenControl: false, motionTracking: false, motionTrackingControl: false
    });
    // Google refuses Street View for a key whose project has no billing
    // (seen live 2026-11-10: "You must enable Billing"). It does not call
    // gm_authFailure for that; it draws its own "This page can't load Google
    // Maps correctly" dialog (a .dismissButton) inside the panorama. Watch
    // for that dialog and tell the caller, so the panel can say what happened
    // instead of showing Google's inverted placeholder.
    let watcher = null, watchTimer = null;
    const stopWatch = () => { if (watcher) { watcher.disconnect(); watcher = null; } if (watchTimer) { clearTimeout(watchTimer); watchTimer = null; } };
    if (typeof o.onRefused === "function" && typeof MutationObserver === "function") {
      const check = () => {
        if (!el.querySelector(".dismissButton, .gm-err-container")) return;
        stopWatch();
        try { o.onRefused(); } catch { /* caller's problem */ }
      };
      watcher = new MutationObserver(check);
      watcher.observe(el, { childList: true, subtree: true });
      watchTimer = setTimeout(stopWatch, STREET_VIEW_REFUSAL_WATCH_MS);
      check();
    }
    return { status: "ready", destroy: () => { stopWatch(); try { pano.setVisible(false); } catch { /* gone */ } el.innerHTML = ""; } };
  } catch {
    return { status: "error", destroy: noop };
  }
}
