// Map 3D / GIS (2026-11-10): map-3d.js's pure helpers (bbox, camera fit,
// layer specs - the parcel is never extruded), the no-key fallback (no
// MapLibre / MapTiler / Google request, the setup message shown), and the
// MapTiler selection flow against a FAKE MapLibre (window.maplibregl) - the
// sandbox cannot load real MapTiler / Google tiles, so real rendering is
// unverified until the deployed preview. Also: the admin-only Street View
// button, the outline-map pin touch target and the legend colour.
import { chromium } from 'playwright';
import fs from 'fs';
const BASE = process.env.BASE_URL || 'http://localhost:9201/index.html';
const exe = '/opt/pw-browsers/chromium';
const b = await chromium.launch(fs.existsSync(exe) ? { executablePath: exe } : {});
let fail = 0;
const check = (name, ok, got) => { console.log((ok ? 'PASS ' : 'FAIL ') + name + (ok ? '' : ' -> ' + JSON.stringify(got))); if (!ok) fail++; };
const THIRD_PARTY = /unpkg\.com|maptiler\.com|googleapis\.com|gstatic\.com|ggpht\.com|googleusercontent\.com/;
// Not map requests: the page's web fonts, and app.js's own static-image rung
// (a MapTiler snapshot for a row with coordinates when a key exists).
const NOT_MAP = /fonts\.googleapis\.com|fonts\.gstatic\.com|api\.maptiler\.com\/maps\/[^/]+\/static\//;

async function page(opts) {
  const o = opts || {};
  // Service workers blocked: the shell's worker would serve config.js on a
  // reload without the route's test key.
  const ctx = await b.newContext({ viewport: o.vp || { width: 1440, height: 900 }, serviceWorkers: 'block' });
  const pg = await ctx.newPage();
  const errs = [], third = [];
  pg.on('pageerror', e => errs.push(e.message));
  await pg.route('**/*', r => {
    const u = r.request().url();
    if (THIRD_PARTY.test(u)) { if (!NOT_MAP.test(u)) third.push(u); return r.abort(); }
    return r.continue();
  });
  if (o.keys) {
    await pg.route('**/config.js', async r => {
      const res = await r.fetch();
      const body = await res.text();
      return r.fulfill({ response: res, body: body + `\nwindow.TDW_CONFIG.maptilerKey = ${JSON.stringify(o.keys.maptiler || '')};\nwindow.TDW_CONFIG.googleMapsApiKey = ${JSON.stringify(o.keys.google || '')};\n` });
    });
  }
  if (o.init) await pg.addInitScript(o.init);
  const q = o.query ? (BASE.includes('?') ? '&' : '?') + o.query : '';
  await pg.goto(BASE + q + '#/map', { waitUntil: 'networkidle' });
  await pg.waitForTimeout(800);
  return { pg, errs, third };
}

// ---- 1. Pure helpers, imported in the page ----
{
  const { pg, errs } = await page();
  const r = await pg.evaluate(async () => {
    const m = await import('./map-3d.js');
    const sq = [[-81, 27], [-80.999, 27], [-80.999, 27.001], [-81, 27.001], [-81, 27]];
    const big = [[-81, 27], [-80.99, 27], [-80.99, 27.01], [-81, 27.01], [-81, 27]];
    const out = {};
    out.bboxPoly = m.bboxOfGeoJSON({ type: 'Polygon', coordinates: [sq] });
    out.bboxMulti = m.bboxOfGeoJSON({ type: 'MultiPolygon', coordinates: [[sq], [[[-82, 26], [-81.9, 26], [-81.9, 26.1], [-82, 26]]]] });
    out.bboxFc = m.bboxOfGeoJSON({ type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: [sq] } }] });
    out.bboxNone = m.bboxOfGeoJSON({ type: 'Point', coordinates: [0, 0] });
    const specs = m.parcelLayerSpecs(m.ledgerColor('auction'));
    out.types = specs.map(s => s.type);
    out.sources = specs.map(s => s.source);
    out.fillOpacity = specs[0].paint['fill-opacity'];
    out.fillColor = specs[0].paint['fill-color'];
    out.noExtrusionKey = JSON.stringify(specs).includes('extrusion');
    const fc = m.boundaryFeatureCollection({ polygons: [[sq]], bbox: m.bboxOfPolygons([[sq]]) }, 'laft');
    out.fcProps = fc.features[0].properties;
    out.fcHasHeight = JSON.stringify(fc).includes('height');
    const bb = m.bboxOfPolygons([[sq]]), bbBig = m.bboxOfPolygons([[big]]);
    const pad = { top: 0, right: 0, bottom: 0, left: 380 };
    out.cam = m.cameraForBbox(bb, { width: 1060, height: 760, padding: pad });
    out.camBig = m.cameraForBbox(bbBig, { width: 1060, height: 760, padding: pad });
    out.camTiny = m.cameraForBbox({ minX: -81, minY: 27, maxX: -81 + 1e-7, maxY: 27 + 1e-7 }, { width: 1060, height: 760 });
    // The fitted box must fit in the clear area: its ground width in pixels.
    const [x0] = m.mercNorm(bb.minX, bb.minY), [x1] = m.mercNorm(bb.maxX, bb.maxY);
    out.boxPx = (x1 - x0) * 512 * Math.pow(2, out.cam.zoom);
    const bl = m.findBuildingLayer([{ id: 'p', type: 'fill', source: m.PARCEL_SOURCE_ID, 'source-layer': 'building' }, { id: 'b', type: 'fill', source: 'maptiler_planet', 'source-layer': 'building' }]);
    out.buildingSrc = bl && bl.source;
    out.extrusion = bl && m.buildingExtrusionSpec(bl);
    out.noBuildingOnParcel = m.findBuildingLayer([{ id: 'p', type: 'fill', source: m.PARCEL_SOURCE_ID, 'source-layer': 'building' }]);
    out.capBoth = m.depthCaption({ terrain: true, buildings: true });
    out.capTerrain = m.depthCaption({ terrain: true, buildings: false });
    out.capOff = m.depthCaption({ terrain: false, buildings: false });
    out.hN = Math.round(m.headingTo(27, -81, 27.001, -81));
    out.hE = Math.round(m.headingTo(27, -81, 27, -80.999));
    out.terrainUrl = m.terrainTilesUrl('K');
    out.credit = m.boundaryCreditHtml({ credit: 'C', changeNotice: 'N', licenseName: 'CC BY 4.0', licenseUrl: 'https://x.org/l', metadataUrl: 'https://x.org/m' });
    out.creditMissing = m.boundaryCreditHtml({ credit: 'C' });
    return out;
  });
  check('bboxPolygon', JSON.stringify(r.bboxPoly) === JSON.stringify({ minX: -81, minY: 27, maxX: -80.999, maxY: 27.001 }), r.bboxPoly);
  check('bboxMultiPolygon', r.bboxMulti && r.bboxMulti.minX === -82 && r.bboxMulti.maxY === 27.001, r.bboxMulti);
  check('bboxFeatureCollection', r.bboxFc && r.bboxFc.maxX === -80.999, r.bboxFc);
  check('bboxNonPolygonNull', r.bboxNone === null, r.bboxNone);
  check('parcelLayersFlatFillHaloLine', JSON.stringify(r.types) === JSON.stringify(['fill', 'line', 'line']), r.types);
  check('parcelLayersNeverExtruded', !r.noExtrusionKey && !r.types.includes('fill-extrusion'), r.types);
  check('parcelLayersOneSource', r.sources.every(s => s === 'tdw-parcel'), r.sources);
  check('parcelFillLedgerColour018', r.fillOpacity === 0.18 && r.fillColor === '#A4512A', [r.fillOpacity, r.fillColor]);
  check('parcelFeatureCarriesNoHeight', !r.fcHasHeight && r.fcProps.ledger === 'laft', r.fcProps);
  check('cameraPitch55Bearing-18', r.cam.pitch === 55 && r.cam.bearing === -18, r.cam);
  check('cameraCentredOnBbox', Math.abs(r.cam.center[0] + 80.9995) < 1e-9 && Math.abs(r.cam.center[1] - 27.0005) < 1e-9, r.cam.center);
  check('cameraKeepsCardPadding', r.cam.padding.left === 380, r.cam.padding);
  check('cameraFitsClearArea', r.boxPx > 120 && r.boxPx <= 1060 - 380, r.boxPx);
  check('cameraBiggerParcelLowerZoom', r.camBig.zoom < r.cam.zoom, [r.cam.zoom, r.camBig.zoom]);
  check('cameraZoomCapped19', r.camTiny.zoom === 19, r.camTiny.zoom);
  check('buildingsFromStyleNotParcel', r.buildingSrc === 'maptiler_planet' && r.extrusion.type === 'fill-extrusion' && r.extrusion.source !== 'tdw-parcel', r.extrusion);
  check('buildingHeightsFromStyleAttributes', JSON.stringify(r.extrusion.paint['fill-extrusion-height']).includes('render_height'), r.extrusion.paint);
  check('noBuildingLayerFromParcelSource', r.noBuildingOnParcel === null, r.noBuildingOnParcel);
  check('depthCaptions', r.capBoth === 'Terrain and buildings: MapTiler / OpenStreetMap' && r.capTerrain === 'Terrain: MapTiler' && r.capOff === '', [r.capBoth, r.capTerrain, r.capOff]);
  check('headingNorthEast', r.hN === 0 && r.hE === 90, [r.hN, r.hE]);
  check('terrainSourceIsTerrainRgbV2', r.terrainUrl === 'https://api.maptiler.com/tiles/terrain-rgb-v2/tiles.json?key=K', r.terrainUrl);
  check('creditHasLicenceAndChange', /Parcel outline: C/.test(r.credit) && /Changes: N/.test(r.credit) && /href="https:\/\/x\.org\/l"/.test(r.credit), r.credit);
  check('creditRefusedWithoutChangeNotice', r.creditMissing === '', r.creditMissing);
  check('pureNoErrors', errs.length === 0, errs);
  await pg.close();
}

// ---- 2. No keys (tests/config.js ships none): nothing third-party ----
{
  const { pg, errs, third } = await page({ query: 'profile=admin' });
  await pg.click('#mapStyleMaptiler');
  await pg.waitForTimeout(600);
  check('noKeySetupMessage', /isn't set up yet/.test(await pg.locator('#satelliteMapCanvasMaptiler .satellite-map-setup').textContent()), null);
  check('noKeyNoMapLibre', await pg.evaluate(() => typeof window.maplibregl === 'undefined'), null);
  check('noKeyDepthToggleHidden', await pg.evaluate(() => { const t = document.getElementById('mapDepthToggle'); return !!t && t.hidden; }), null);
  await pg.click('#mapStyleOutline');
  await pg.selectOption('#mapCountySelect', 'Charlotte');
  await pg.waitForTimeout(800);
  await pg.locator('#exploreMapCanvas .map-pin[data-pid="p5"]').click({ force: true });
  await pg.waitForTimeout(800);
  check('noGoogleKeyNoStreetViewEvenForAdmin', (await pg.locator('#explorePreview .mp-sv').count()) === 0, null);
  const gis = await pg.evaluate(async () => {
    const m = await import('./map-3d.js');
    const el = document.createElement('div'); el.innerHTML = '<p>today</p>'; document.body.appendChild(el);
    const a = await m.mountGisMap(el, { lat: 26.9, lng: -82.0, propertyId: 'p5' });
    const c = await m.mountGisMap(el, { lat: null, lng: null, propertyId: 'p5' });
    const sv = await m.mountStreetView(el, { lat: 26.9, lng: -82.0 });
    return { a: a.status, c: c.status, sv: sv.status, html: el.innerHTML };
  });
  check('miniMapUnconfiguredLeavesElement', gis.a === 'unconfigured' && gis.html === '<p>today</p>', gis);
  check('miniMapNoCoords', gis.c === 'no_coords', gis);
  check('streetViewUnconfigured', gis.sv === 'unconfigured', gis);
  check('noKeyNoThirdPartyRequest', third.length === 0, third);
  check('noKeyNoErrors', errs.length === 0, errs);
  await pg.close();
}

// ---- 3. Outline map: pin touch target, legend colour ----
{
  const { pg } = await page();
  const legend = await pg.evaluate(() => {
    const dot = document.querySelector('#exploreMapLegend .map-legend-dot');
    const bub = document.querySelector('#exploreMapCanvas .cluster-bubble circle:not(.bubble-hit)');
    return dot && bub ? { dot: getComputedStyle(dot).backgroundColor, bub: getComputedStyle(bub).fill } : null;
  });
  check('legendDotMatchesBubble', legend && legend.dot === legend.bub, legend);
  await pg.selectOption('#mapCountySelect', 'Charlotte');
  await pg.waitForTimeout(900);
  const hit = await pg.evaluate(() => { const c = document.querySelector('#exploreMapCanvas .map-pin[data-pid="p5"] .pin-hit'); if (!c) return null; const r = c.getBoundingClientRect(); return { w: r.width, h: r.height, pe: getComputedStyle(c).pointerEvents, fill: getComputedStyle(c).fill }; });
  check('pinHitArea44px', hit && hit.w >= 43 && hit.h >= 43 && hit.pe === 'all', hit);
  check('pinHitInvisible', hit && /rgba\(0, 0, 0, 0\)|transparent/.test(hit.fill), hit);
  await pg.close();
}

// ---- 4. MapTiler selection against a fake MapLibre ----
const FAKE_GL = () => {
  const log = window.__gl = { calls: [], maps: [] };
  class Evented { constructor() { this._h = {}; } on(t, f) { (this._h[t] = this._h[t] || []).push(f); return this; } once(t, f) { const g = (...a) => { this.off(t, g); f(...a); }; return this.on(t, g); } off(t, f) { this._h[t] = (this._h[t] || []).filter(x => x !== f); return this; } fire(t, e) { (this._h[t] || []).slice().forEach(f => f(e || {})); } }
  class Map extends Evented {
    constructor(o) { super(); this.o = o; this.c = o.container; this.center = { lng: o.center[0], lat: o.center[1] }; this.zoom = o.zoom; this.pitch = o.pitch || 0; this.bearing = o.bearing || 0;
      this.sources = {}; this.layers = []; this.terrain = null; log.maps.push(this);
      this.styleLayers = [{ id: 'building', type: 'fill', source: 'maptiler_planet', 'source-layer': 'building' }];
      setTimeout(() => { this._loaded = true; this.fire('style.load'); this.fire('load'); }, 30); }
    getContainer() { return this.c; } getZoom() { return this.zoom; } getCenter() { return this.center; } getPitch() { return this.pitch; } getBearing() { return this.bearing; }
    getBounds() { const d = 0.5; return { getSouth: () => this.center.lat - d, getNorth: () => this.center.lat + d, getWest: () => this.center.lng - d, getEast: () => this.center.lng + d }; }
    loaded() { return !!this._loaded; } addControl() { return this; } resize() {} setPadding() {} remove() { log.calls.push(['remove']); }
    _cam(k, o) { log.calls.push([k, JSON.parse(JSON.stringify(o))]); if (o.center) this.center = Array.isArray(o.center) ? { lng: o.center[0], lat: o.center[1] } : o.center; if (o.zoom != null) this.zoom = o.zoom; if (o.pitch != null) this.pitch = o.pitch; if (o.bearing != null) this.bearing = o.bearing; }
    easeTo(o) { this._cam('easeTo', o); } flyTo(o) { this._cam('flyTo', o); } jumpTo(o) { this._cam('jumpTo', o); } fitBounds() {}
    setStyle(u) { log.calls.push(['setStyle', u]); this.sources = {}; this.layers = []; setTimeout(() => this.fire('style.load'), 20); }
    getStyle() { return { layers: this.styleLayers.concat(this.layers) }; }
    addSource(id, s) { if (this.sources[id]) throw new Error('dup source'); this.sources[id] = s; log.calls.push(['addSource', id, s.type, s.url || '']); }
    getSource(id) { return this.sources[id]; } removeSource(id) { delete this.sources[id]; log.calls.push(['removeSource', id]); }
    addLayer(l, before) { if (this.layers.some(x => x.id === l.id)) throw new Error('dup layer'); const i = before ? this.layers.findIndex(x => x.id === before) : -1; if (i >= 0) this.layers.splice(i, 0, l); else this.layers.push(l); log.calls.push(['addLayer', l.id, l.type, l.source, before || '']); }
    getLayer(id) { return this.layers.find(l => l.id === id); } removeLayer(id) { this.layers = this.layers.filter(l => l.id !== id); log.calls.push(['removeLayer', id]); }
    setTerrain(t) { this.terrain = t; log.calls.push(['setTerrain', t]); }
  }
  class Marker { constructor(o) { this.el = o.element; } setLngLat(ll) { this.ll = ll; return this; } addTo(m) { this.el.style.position = 'absolute'; this.el.style.left = '400px'; this.el.style.top = '300px'; m.c.appendChild(this.el); return this; } remove() { this.el.remove(); } }
  class NavigationControl {}
  window.maplibregl = { Map, Marker, NavigationControl };
  // The outline comes from app.js's own boundary reader (renderMapPage's
  // payload carries boundaryFor), answered by the stub's ?boundary=ok fixture.
};
{
  const { pg, errs, third } = await page({ keys: { maptiler: 'FAKEKEY' }, init: FAKE_GL, query: 'boundary=ok' });
  await pg.evaluate(() => { try { sessionStorage.removeItem('tdw_map_depth_v1'); } catch {} });
  // A customer opens MapTiler first when it is configured; click to be sure.
  await pg.click('#mapStyleMaptiler');
  await pg.waitForTimeout(500);
  check('fakeMapCreatedWithHybrid', await pg.evaluate(() => window.__gl.maps.length === 1 && /maps\/hybrid\/style\.json\?key=FAKEKEY/.test(window.__gl.maps[0].o.style)), null);
  check('depthToggleShownOnMaptiler', await pg.locator('#mapDepthToggle').isVisible(), null);
  await pg.selectOption('#mapCountySelect', 'Charlotte');
  await pg.waitForTimeout(700);
  check('countyViewFlat', await pg.evaluate(() => window.__gl.maps[0].pitch === 0), null);
  await pg.locator('#satelliteMapCanvasMaptiler .sat-pin[data-pid="p5"]').click({ force: true });
  await pg.waitForTimeout(800);
  const sel = await pg.evaluate(() => {
    const m = window.__gl.maps[0];
    const ease = window.__gl.calls.filter(c => c[0] === 'easeTo').map(c => c[1]);
    return { layers: m.layers.map(l => [l.id, l.type, l.source]), src: m.sources['tdw-parcel'] && m.sources['tdw-parcel'].type, last: ease[ease.length - 1] };
  });
  check('selectionAddsParcelSource', sel.src === 'geojson', sel);
  check('selectionAddsFillHaloLine', JSON.stringify(sel.layers.map(l => l[1])) === JSON.stringify(['fill', 'line', 'line']), sel.layers);
  check('selectionParcelNotExtruded', sel.layers.every(l => l[1] !== 'fill-extrusion'), sel.layers);
  check('selectionEasesTo55Minus18', sel.last && sel.last.pitch === 55 && sel.last.bearing === -18, sel.last);
  const p5 = await pg.evaluate(() => { const r = window.__tdwMapLastRender.rows.find(x => x.id === 'p5'); return [r.longitude, r.latitude]; });
  check('selectionFramedOnParcel', sel.last && Math.abs(sel.last.center[0] - p5[0]) < 1e-6 && Math.abs(sel.last.center[1] - p5[1]) < 1e-6 && sel.last.zoom > 15 && sel.last.zoom <= 19, { last: sel.last, p5 });
  check('selectionPaddingAvoidsCard', sel.last && sel.last.padding && sel.last.padding.left > 300, sel.last && sel.last.padding);
  check('outlineCreditShown', /Parcel outline: FIXTURE Utah Geospatial Resource Center/.test(await pg.locator('#mapParcelCredit').textContent()), null);
  check('outlineCreditKeepsLicenceAndChanges', await pg.evaluate(() => { const d = document.getElementById('mapParcelCredit'); return !!d.querySelector('a[href="https://creativecommons.org/licenses/by/4.0/"]') && /Changes: FIXTURE: boundaries reprojected and simplified/.test(d.textContent); }), null);
  // 3D toggle: terrain + the style's buildings; never the parcel.
  await pg.click('#mapDepthBtn');
  await pg.waitForTimeout(300);
  const d3 = await pg.evaluate(() => {
    const m = window.__gl.maps[0];
    return { terrain: m.terrain, dem: m.sources['tdw-terrain'], ext: m.layers.filter(l => l.type === 'fill-extrusion').map(l => [l.id, l.source]), cap: document.getElementById('mapDepthCaption').textContent, pressed: document.getElementById('mapDepthBtn').getAttribute('aria-pressed'), stored: sessionStorage.getItem('tdw_map_depth_v1'),
      order: m.layers.map(l => l.id) };
  });
  check('depthTerrainExaggeration12', d3.terrain && d3.terrain.source === 'tdw-terrain' && d3.terrain.exaggeration === 1.2, d3.terrain);
  check('depthTerrainRgbV2', d3.dem && d3.dem.type === 'raster-dem' && /terrain-rgb-v2/.test(d3.dem.url), d3.dem);
  check('depthExtrudesStyleBuildingsOnly', d3.ext.length === 1 && d3.ext[0][1] === 'maptiler_planet', d3.ext);
  check('depthBuildingsBelowParcel', d3.order.indexOf('tdw-buildings-3d') < d3.order.indexOf('tdw-parcel-fill'), d3.order);
  check('depthCaption', d3.cap === 'Terrain and buildings: MapTiler / OpenStreetMap', d3.cap);
  check('depthPressedAndPersisted', d3.pressed === 'true' && d3.stored === '1', d3);
  // Imagery swap drops GL layers; outline and depth come back.
  await pg.click('#mapImageryStreets');
  await pg.waitForTimeout(400);
  const back = await pg.evaluate(() => { const m = window.__gl.maps[0]; return { ids: m.layers.map(l => l.id), terrain: !!m.terrain }; });
  check('styleSwapRestoresParcelAndDepth', back.ids.includes('tdw-parcel-line') && back.ids.includes('tdw-buildings-3d') && back.terrain, back);
  // Closing the card removes the outline and flattens the camera.
  await pg.click('#explorePreview [data-act="close"]');
  await pg.waitForTimeout(400);
  const cleared = await pg.evaluate(() => { const m = window.__gl.maps[0]; return { ids: m.layers.map(l => l.id), pitch: m.pitch, bearing: m.bearing, credit: !!document.getElementById('mapParcelCredit') }; });
  check('clearRemovesParcelLayers', !cleared.ids.some(id => id.startsWith('tdw-parcel')), cleared.ids);
  check('clearEasesBackFlat', cleared.pitch === 0 && cleared.bearing === 0, cleared);
  check('clearRemovesCredit', !cleared.credit, cleared);
  // Statewide stays flat.
  await pg.selectOption('#mapCountySelect', 'ALL');
  await pg.waitForTimeout(500);
  check('statewideFlat', await pg.evaluate(() => window.__gl.maps[0].pitch === 0 && window.__gl.maps[0].bearing === 0), null);
  // Session persistence: a reload keeps 3D on.
  await pg.reload({ waitUntil: 'networkidle' });
  await pg.waitForTimeout(800);
  await pg.click('#mapStyleMaptiler').catch(() => {});
  await pg.waitForTimeout(500);
  const rl = await pg.evaluate(() => { const m = window.__gl.maps[window.__gl.maps.length - 1]; return { maps: window.__gl.maps.length, terrain: !!(m && m.terrain), pressed: (document.getElementById('mapDepthBtn') || {}).getAttribute ? document.getElementById('mapDepthBtn').getAttribute('aria-pressed') : null, on: document.getElementById('mapStyleMaptiler').className, stored: sessionStorage.getItem('tdw_map_depth_v1') }; });
  check('depthRestoredAfterReload', rl.maps >= 1 && rl.terrain && rl.pressed === 'true', rl);
  check('fakeFlowNoThirdParty', third.length === 0, third);
  check('fakeFlowNoErrors', errs.length === 0, errs);
  await pg.close();
}

// ---- 5. Street View: admins only, Google stubbed (no imagery here) ----
const FAKE_GOOGLE = () => {
  window.__svCalls = [];
  window.google = { maps: { importLibrary: async lib => {
    window.__svCalls.push(lib);
    if (lib === 'streetView') return { StreetViewService: class { async getPanorama() { throw new Error('ZERO_RESULTS'); } }, StreetViewPanorama: class {}, StreetViewSource: { OUTDOOR: 'outdoor' } };
    throw new Error('not stubbed');
  } } };
};
for (const [who, query, want] of [['customer', '', false], ['admin', 'profile=admin', true]]) {
  const { pg, errs } = await page({ keys: { google: 'FAKEGOOGLE' }, init: FAKE_GOOGLE, query });
  await pg.click('#mapStyleOutline').catch(() => {});
  await pg.selectOption('#mapCountySelect', 'Charlotte');
  await pg.waitForTimeout(800);
  await pg.locator('#exploreMapCanvas .map-pin[data-pid="p5"]').click({ force: true });
  await pg.waitForTimeout(800);
  const n = await pg.locator('#explorePreview .mp-sv').count();
  check(`streetViewButton_${who}`, (n === 1) === want, n);
  if (want) {
    await pg.click('#explorePreview .mp-sv');
    await pg.waitForTimeout(500);
    check('streetViewPanelNoImageryMessage', /no Street View imagery within 50 m/.test(await pg.locator('#mapStreetView').textContent()), null);
    check('streetViewPanelSaysWhatItIsNot', /does not show the parcel's boundary/.test(await pg.locator('#mapStreetView .map-sv-note').textContent()), null);
    check('streetViewAskedGoogleStreetViewOnly', await pg.evaluate(() => JSON.stringify(window.__svCalls) === '["streetView"]'), null);
    await pg.click('#mapStreetView .map-sv-close');
    check('streetViewCloses', (await pg.locator('#mapStreetView').count()) === 0, null);
  } else {
    check('customerNeverCallsGoogle', await pg.evaluate(() => window.__svCalls.length === 0), null);
  }
  check(`streetViewNoErrors_${who}`, errs.length === 0, errs);
  await pg.close();
}

await b.close();
console.log(fail ? `${fail} FAILED` : 'ALL PASSED');
process.exit(fail ? 1 : 0);
