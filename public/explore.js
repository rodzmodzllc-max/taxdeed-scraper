// ============================================================================
// Explore view: split "card list + Florida map" layout with per-county
// cluster bubbles, plus the List / Split / Map switcher.
//
// WHY THIS IS A SEPARATE MODULE, not code inside app.js:
// app.js is ~2400 lines and owns every filter, every render path and all of
// the Supabase wiring. This file adds a second *view* of data app.js has
// already filtered, and it does that without reaching into app.js's internals
// at all. The entire contract between them is one event:
//
//     window.addEventListener("tdw:rendered", e => e.detail)
//        -> { rows, ledger, openDetail }
//
// dispatched at the end of app.js's render(). `rows` is the exact
// filtered+sorted set the list just drew, so the map can never disagree with
// the list about what's in view - no second copy of passes()/sortRows() here
// to drift out of sync. That was the specific failure mode worth designing
// out: two filter implementations that agree on day one and quietly diverge
// on day thirty.
//
// app.js also parks that same payload on window.__tdwLastRender before
// dispatching, and this module reads it on startup. Both files are
// type="module" (so both are deferred and app.js runs first), and app.js's
// first render() is behind an await on Supabase - so in practice the listener
// below is always registered in time. "In practice" is doing too much work
// there: if a render ever DOES land first, an event-only contract drops it
// silently and the map sits empty until the user happens to touch a filter.
// Caught exactly that way in the local harness, where the stand-in for app.js
// renders synchronously. One line on each side makes the ordering irrelevant.
//
// WHY COUNTY BUBBLES AND NOT PARCEL PINS:
// Measured against the live database (2026-08-31): of 2,837 properties, only
// 60 have latitude/longitude - 51 auctions, 9 certificates, and ZERO Lands
// Available. geocode_properties.py backfills a few hundred per deeds run, but
// coverage is ~2% today. A street-level pin map would therefore render an
// almost empty map and imply the other 98% don't exist. A county-level
// cluster is the honest unit at this coverage AND is the same visual idea as
// the numbered clusters on a listing-search map: one bubble per area, sized
// by how much is there, click to drill in.
//
// When geocoding coverage is high enough to be worth it, the upgrade path is
// contained: swap renderBubbles() for real pins over a tile basemap. That
// needs a CSP change too (public/_headers currently allows img-src 'self'
// data: only, so third-party map tiles are blocked by design) - deliberately
// NOT done here, since it would quietly start leaking which parcels a user is
// looking at to a tile provider.
//
// The basemap is the app's own fl-counties.svg - same-origin, already shipped,
// already cached by the service worker, and allowed by the existing CSP. No
// new dependency, no API key, and the map still works fully offline at a
// courthouse, which the PWA is explicitly built for.
// ============================================================================

const SHELL_ID = "exploreShell";
const CANVAS_ID = "exploreMapCanvas";
const MODE_KEY = "tdw_view_mode";
const MODES = ["list", "split", "map"];

// Live state, all of it derived from the last tdw:rendered event.
let rows = [];
let ledger = "auction";
let openDetail = null;
let svgLoaded = false;
let centroids = new Map();     // county -> {cx, cy} in SVG user units
let centroidsOk = false;       // false while the only measurements we have
                               // came from a hidden (unlaid-out) SVG
let pendingDraw = false;       // a draw was asked for while the panel had no
                               // geometry yet; run it once it does
let selectedCounty = null;     // county the map has filtered the list to
let zoomCounty = null;         // county the map is zoomed into, null = statewide
let homeViewBox = null;        // the SVG's own viewBox, restored on zoom out
let viewScale = 1;             // homeWidth / currentWidth - pins and labels
                               // divide by this so they keep a constant size
                               // on screen no matter how far we zoom
let activeProp = null;         // property showing in the preview card
let cities = null;             // county -> [[name, lat, lon, population], ...]
let zips = null;               // county -> [[zip, [[lon,lat], ...]], ...]
let cityTop = [];              // the statewide majors, picked once on load
let zoomAnim = null;           // in-flight viewBox tween

const $ = id => document.getElementById(id);

// ---------------------------------------------------------------------------
// view mode
// ---------------------------------------------------------------------------
function storedMode() {
  try {
    const m = localStorage.getItem(MODE_KEY);
    if (MODES.includes(m)) return m;
  } catch { /* private mode - fall through to the default */ }
  // Split is the point of the redesign, but it needs the width to make sense;
  // a phone opening straight into a half-width list would be worse than the
  // list it replaced.
  return window.matchMedia("(min-width:1024px)").matches ? "split" : "list";
}

function setMode(mode, persist) {
  if (!MODES.includes(mode)) mode = "list";
  const shell = $(SHELL_ID);
  if (shell) shell.dataset.mode = mode;
  document.querySelectorAll("#viewToggle button[data-mode]").forEach(b => {
    b.classList.toggle("on", b.dataset.mode === mode);
    b.setAttribute("aria-pressed", b.dataset.mode === mode ? "true" : "false");
  });
  if (persist) { try { localStorage.setItem(MODE_KEY, mode); } catch { /* not persisted, still applied */ } }
  // The SVG is only fetched when a map is actually going to be visible, so
  // list-only users never pay for it.
  if (mode !== "list") ensureMap();
}

function bindViewToggle() {
  const wrap = $("viewToggle");
  if (!wrap) return;
  wrap.addEventListener("click", e => {
    const btn = e.target.closest("button[data-mode]");
    if (btn) setMode(btn.dataset.mode, true);
  });
  setMode(storedMode(), false);
}

// ---------------------------------------------------------------------------
// basemap
// ---------------------------------------------------------------------------
async function ensureMap() {
  if (svgLoaded) return;
  const canvas = $(CANVAS_ID);
  if (!canvas) return;
  svgLoaded = true;                       // set first: a slow fetch must not
                                          // queue a second one behind it
  try {
    const res = await fetch("fl-counties.svg");
    if (!res.ok) throw new Error("HTTP " + res.status);
    canvas.innerHTML = await res.text();
    // Start watching now that there is a map to re-measure.
    watchCanvasResize();
    computeCentroids(canvas);
    draw();
    loadCities();
    loadZips();
  } catch {
    // Offline with a cold cache, or the file moved. The list is unaffected,
    // so degrade to a plain message instead of throwing into the console.
    svgLoaded = false;
    canvas.innerHTML = '<div class="explore-map-empty">Map unavailable offline.</div>';
  }
}

// Bounding-box centers rather than true polygon centroids: works for all 67
// shapes with no per-county tuning, and is what the filter-panel map already
// does (see computeCountyCentroids in app.js). The tradeoff is a label that
// can land slightly off inside a very concave county - Monroe's Keys chain
// being the one that actually shows it.
//
// getBBox() on an element inside a display:none subtree returns zeros (or
// throws) rather than failing loudly. This module loads while the auth gate
// is still up and #app is hidden, so the FIRST measurement is always the
// worthless one: every county comes back 0x0, every centroid lands on the
// SVG origin, and all 67 bubbles stack in the top-left corner of Florida.
// That shipped to the preview and is what this flag exists to stop - we only
// trust a measurement pass that produced at least one real box, and redraw
// once the panel is actually on screen (see watchForVisibility below).
function computeCentroids(canvas) {
  const next = new Map();
  let sawRealGeometry = false;
  canvas.querySelectorAll("path[data-county]").forEach(p => {
    try {
      const b = p.getBBox();
      if (b.width > 0 || b.height > 0) sawRealGeometry = true;
      next.set(p.dataset.county, { cx: b.x + b.width / 2, cy: b.y + b.height / 2 });
    } catch { /* not laid out yet - retried once the panel is visible */ }
  });
  // Keep the previous good values rather than overwriting them with zeros if
  // this pass happened to run while hidden again (e.g. a mode switch).
  if (sawRealGeometry) {
    centroids = next;
    centroidsOk = true;
  }
  return sawRealGeometry;
}

// Redraw as soon as the map actually has layout. Covers both paths into a
// visible panel: signing in (#app un-hidden by app.js's showApp) and any
// later size change, which is also when a stale zero-measurement would
// otherwise persist.
function watchForVisibility() {
  const canvas = $(CANVAS_ID);
  const app = document.getElementById("app");
  if (!canvas) return;

  if (typeof ResizeObserver === "function") {
    const ro = new ResizeObserver(() => {
      if (canvas.clientWidth > 0 && (!centroidsOk || pendingDraw)) {
        if (computeCentroids(canvas)) { pendingDraw = false; draw(); }
      }
    });
    ro.observe(canvas);
  }

  // ResizeObserver alone can miss the display:none -> visible flip on some
  // engines, so watch the attribute app.js actually toggles as well.
  if (app && typeof MutationObserver === "function") {
    const mo = new MutationObserver(() => {
      if (!app.hidden && svgLoaded) {
        if (computeCentroids(canvas)) { pendingDraw = false; draw(); }
      }
    });
    mo.observe(app, { attributes: true, attributeFilter: ["hidden"] });
  }
}

// ---------------------------------------------------------------------------
// projection: lat/long -> SVG user units
// ---------------------------------------------------------------------------
// fl-counties.svg is a plain equirectangular projection, which is worth
// stating precisely rather than assuming: the coefficients below are a
// least-squares affine fit of all 67 counties' SVG bounding-box centres
// against the same counties' real bounding-box centres taken from the US
// Census county polygons. Worst residual across the 67 is 0.05 SVG units,
// about 128 feet on the ground - so a pin sits on the right parcel, not just
// in the right part of the county.
//
// The two cross terms are nearly zero (the projection is essentially
// north-up, unrotated) but are kept because dropping them costs ~700 feet.
//
// The coefficients are fractions, so they need a basis to multiply by. That
// basis is the ORIGINAL 1000x960 box the fit was computed against - a fixed
// property of the fit, not of whatever viewBox the SVG happens to carry.
//
// It used to read the live viewBox, which was the same 1000x960 by
// coincidence and stopped being so the moment the basemap grew a margin for
// the Gulf, the Atlantic and the state line with Georgia. Worse, the viewBox
// is rewritten on every county zoom, so the old form was one careless read
// of the live value (rather than the cached "home" one) away from putting
// every pin in the wrong place while zoomed in. Pinning it here removes the
// coupling entirely: the basemap can be reframed without touching the
// projection, and the projection can't drift when the view moves.
const PROJ = {
  x: { lon: 0.131515586, lat: -0.000001417, c: 11.525408765 },
  y: { lon: 0.000002902, lat: -0.154887536, c: 4.801899887 },
  // The fit's own basis. Change these only by re-running the fit.
  baseW: 1000,
  baseH: 960
};

function projectLatLng(lat, lon) {
  return {
    x: (PROJ.x.lon * lon + PROJ.x.lat * lat + PROJ.x.c) * PROJ.baseW,
    y: (PROJ.y.lon * lon + PROJ.y.lat * lat + PROJ.y.c) * PROJ.baseH
  };
}

// Rows carry latitude/longitude straight from Supabase (app.js selects *),
// but only about 2% of them are geocoded today - none of the Lands Available
// rows at all. So a pin is strictly opt-in per property: everything else
// still appears in the strip of cards below the map, and the map says how
// many it could not place rather than quietly showing fewer properties than
// the list does.
function hasPin(p) {
  return typeof p.latitude === "number" && typeof p.longitude === "number" &&
         isFinite(p.latitude) && isFinite(p.longitude);
}

// ---------------------------------------------------------------------------
// city labels
// ---------------------------------------------------------------------------
// Without them the map is a blue silhouette: correct, and unreadable. Zoomed
// into a county it was worse - one flat shape with a couple of pins on it and
// nothing to say WHERE in the county they are, which is the first thing
// anyone wants to know.
//
// fl-cities.json is 472 places keyed by county, built from the US cities
// dataset with each city's ZIP-level points averaged to a single point and
// the county then re-derived by point-in-polygon against the Census county
// boundaries - the dataset's own COUNTY column assigns by ZIP area and puts
// Kissimmee in Polk. Five coastal places whose centre falls offshore (the
// Keys, Holmes Beach) are snapped to the nearest county.
//
// Failure here is silent and non-fatal: no city file, no labels, same map as
// before.
async function loadCities() {
  try {
    const res = await fetch("fl-cities.json");
    if (!res.ok) return;
    cities = await res.json();
    // Statewide we only want the handful that orient you at a glance.
    cityTop = Object.keys(cities)
      .reduce((all, c) => all.concat(cities[c]), [])
      .filter(c => c[3] > 0)
      .sort((a, b) => b[3] - a[3])
      .slice(0, 9);
    draw();
  } catch { /* map is fine without labels */ }
}

// A county drawn as one flat shape reads as a diagram, not a map - there is
// nothing to tell you which part of it you are looking at. fl-zips.json
// carries every county's ZIP areas as simplified polygons (Census ZCTAs,
// Douglas-Peucker at ~880m, 267KB raw / 73KB over the wire for the whole
// state, median 3KB per county), which is enough structure to place a
// property by eye.
//
// ZIP areas rather than city limits on purpose: incorporated places leave
// unincorporated land blank, and unincorporated land is exactly where a lot
// of tax deed inventory sits. ZIPs tile the whole county, and a bidder
// already thinks in them.
async function loadZips() {
  try {
    const res = await fetch("fl-zips.json");
    if (!res.ok) return;
    zips = await res.json();
    if (zoomCounty) draw();
  } catch { /* the map is fine without them */ }
}

// Areas containing a property we can actually place are tinted and counted;
// the rest are outline only. With geocoding at 2% most areas are outline
// only today, and that is the honest picture rather than a decorative one.
function drawZipAreas(svg, county, pins) {
  let layer = svg.querySelector(".zip-layer");
  if (!layer) {
    layer = document.createElementNS(NS, "g");
    layer.setAttribute("class", "zip-layer");
    svg.insertBefore(layer, svg.querySelector(".city-layer") || svg.querySelector(".cluster-layer") || null);
  }
  layer.innerHTML = "";
  const list = zips && county && zips[county];
  if (!list) return;

  const upp = unitsPerPixel(svg);

  const pointIn = (x, y, pts) => {
    let hit = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const xi = pts[i][0], yi = pts[i][1], xj = pts[j][0], yj = pts[j][1];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi + 1e-12) + xi) hit = !hit;
    }
    return hit;
  };

  list.forEach(([zip, ring]) => {
    const pts = ring.map(([lon, lat]) => {
      const q = projectLatLng(lat, lon);
      return [q.x, q.y];
    });
    const n = (pins || []).filter(q => pointIn(q.x, q.y, pts)).length;

    const poly = document.createElementNS(NS, "polygon");
    poly.setAttribute("points", pts.map(q => q[0].toFixed(1) + "," + q[1].toFixed(1)).join(" "));
    poly.setAttribute("class", "zip-area" + (n ? " has-rows" : ""));
    layer.appendChild(poly);

    // Label the area only when there is room for the number - a ZIP printed
    // across a sliver of coastline is noise. An area that HOLDS a property is
    // the exception and always gets its count, however small it is: that
    // label is the answer to "where are the properties", which is the whole
    // reason the areas are drawn.
    const xs = pts.map(q => q[0]), ys = pts.map(q => q[1]);
    const w = (Math.max(...xs) - Math.min(...xs)) / upp;
    const h = (Math.max(...ys) - Math.min(...ys)) / upp;
    if (!n && (w < 44 || h < 26)) return;
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", (Math.min(...xs) + Math.max(...xs)) / 2);
    t.setAttribute("y", (Math.min(...ys) + Math.max(...ys)) / 2);
    t.setAttribute("font-size", 9 * upp);
    t.setAttribute("class", "zip-label" + (n ? " has-rows" : ""));
    t.textContent = n ? `${zip} · ${n}` : zip;
    layer.appendChild(t);
  });
}

// Labels are placed largest-first and any that would collide with one already
// placed is dropped. Overlapping town names are worse than fewer of them.
function drawCities(svg, list, blockers) {
  let layer = svg.querySelector(".city-layer");
  if (!layer) {
    layer = document.createElementNS(NS, "g");
    layer.setAttribute("class", "city-layer");
    // Before the bubble/pin layer so a label can never sit over a pin.
    const clusters = svg.querySelector(".cluster-layer");
    svg.insertBefore(layer, clusters || null);
  }
  layer.innerHTML = "";
  if (!list || !list.length) return;

  const home = readHomeViewBox(svg);
  // Sized in real screen pixels so a label reads the same at any zoom.
  const upp = unitsPerPixel(svg);
  const fs = (zoomCounty ? 13 : 11) * upp;
  const r = 2.6 * upp;
  // Count bubbles and property pins are the data; a town name half-hidden
  // under one is worse than no town name, so they reserve their space first.
  const placed = (blockers || []).slice();
  const vb = (svg.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
  const bounds = vb.length === 4 && vb.every(isFinite)
    ? { x1: vb[0], y1: vb[1], x2: vb[0] + vb[2], y2: vb[1] + vb[3] } : null;

  list.forEach(([rawName, lat, lon]) => {
    // The source dataset writes "Mc David" for McDavid, "Mc Intosh" for
    // McIntosh, and so on.
    const name = rawName.replace(/^Mc\s+(\S)/, (m, c) => "Mc" + c);
    const { x, y } = projectLatLng(lat, lon);
    // Rough text box: 0.52em average glyph width is close enough for a
    // collision test and costs nothing to compute.
    // 0.52em per glyph under-measured real Inter text often enough that a
    // label the collision test believed was clear still overlapped a count
    // bubble by a few pixels on screen. The estimate is deliberately
    // generous now - reserving slightly too much space costs an occasional
    // label position, while reserving too little costs a name you cannot
    // read, and the harness checks for exactly that overlap.
    const w = name.length * fs * 0.58 + fs * 0.4, h = fs * 1.25;
    const gap = r + fs * 0.35;

    // Try the label above the dot first, then below, then out to each side.
    // Dropping a name on the first collision lost Pensacola from Escambia -
    // the county's own city, hidden because two pins happened to sit on it.
    // Moving it is almost always better than losing it.
    const cands = [
      { cx: x, ty: y - gap, anchor: "middle", x1: x - w / 2, x2: x + w / 2, y1: y - gap - h, y2: y - gap },
      { cx: x, ty: y + gap + h * 0.8, anchor: "middle", x1: x - w / 2, x2: x + w / 2, y1: y + gap, y2: y + gap + h },
      { cx: x + gap, ty: y + h * 0.3, anchor: "start", x1: x + gap, x2: x + gap + w, y1: y - h / 2, y2: y + h / 2 },
      { cx: x - gap, ty: y + h * 0.3, anchor: "end", x1: x - gap - w, x2: x - gap, y1: y - h / 2, y2: y + h / 2 }
    ];

    const pad = fs * 0.3;
    const fits = c => {
      if (bounds && (c.x1 < bounds.x1 + pad || c.x2 > bounds.x2 - pad ||
                     c.y1 < bounds.y1 + pad || c.y2 > bounds.y2 - pad)) return false;
      return !placed.some(b => !(c.x2 < b.x1 || c.x1 > b.x2 || c.y2 < b.y1 || c.y1 > b.y2));
    };
    const spot = cands.find(fits);
    if (!spot) return;
    placed.push(spot);

    const g = document.createElementNS(NS, "g");
    g.setAttribute("class", "city-marker");
    const dot = document.createElementNS(NS, "circle");
    dot.setAttribute("cx", x); dot.setAttribute("cy", y); dot.setAttribute("r", r);
    g.appendChild(dot);
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", spot.cx);
    t.setAttribute("y", spot.ty);
    t.setAttribute("text-anchor", spot.anchor);
    t.setAttribute("font-size", fs);
    t.setAttribute("stroke-width", fs * 0.28);
    t.textContent = name;
    g.appendChild(t);
    layer.appendChild(g);
  });
}

// ---------------------------------------------------------------------------
// zoom
// ---------------------------------------------------------------------------
function readHomeViewBox(svg) {
  if (homeViewBox) return homeViewBox;
  const vb = (svg.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
  homeViewBox = vb.length === 4 && vb.every(isFinite)
    ? { x: vb[0], y: vb[1], w: vb[2], h: vb[3] }
    : { x: 0, y: 0, w: 1000, h: 960 };
  return homeViewBox;
}

function setViewBox(svg, b) {
  svg.setAttribute("viewBox", `${b.x} ${b.y} ${b.w} ${b.h}`);
  viewScale = readHomeViewBox(svg).w / b.w;
}

// How many SVG user units make one CSS pixel on screen right now. Sizing pins
// and labels off the viewBox ratio alone was wrong: it holds them constant
// relative to the HOME view, not to the screen, so in a ~570px-wide panel
// showing a 1000-unit viewBox an 11-unit label rendered at about 6px and was
// unreadable. Divide by this instead and a size means what it says.
// Measured off the SVG ITSELF, not off the canvas that contains it.
//
// Those were the same number back when the SVG filled the canvas edge to
// edge. They stopped being the same once the map got capped to its own
// aspect ratio (so the element is narrower than the panel on a wide screen)
// and a county rail took a slice of the row. Reading the container meant
// every label and pin was sized against a box the map wasn't actually
// drawn in - measured live, a name asking for 11px was rendering at 18px,
// which is why the city names sat on the map like captions rather than
// belonging to it.
//
// getBoundingClientRect() on the <svg> is the real drawn width, after
// max-width, flexbox and letterboxing have all had their say.
function unitsPerPixel(svg) {
  const vb = (svg.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
  if (vb.length !== 4 || !isFinite(vb[2]) || !vb[2]) return 1;
  let w = svg.getBoundingClientRect().width;
  if (!w) {
    const canvas = $(CANVAS_ID);
    w = canvas ? canvas.clientWidth : 0;
  }
  if (!w) return 1;
  // With preserveAspectRatio the drawn scale is set by whichever axis is the
  // tighter fit, so take the larger units-per-pixel of the two. Sizing off
  // width alone overstated the scale whenever the panel was short and wide.
  const h = svg.getBoundingClientRect().height;
  const byW = vb[2] / w;
  const byH = h ? vb[3] / h : byW;
  return Math.max(byW, byH);
}

// Tween rather than jump: a viewBox that snaps from the whole state to one
// county gives no sense of WHERE that county was, which is most of the value
// of zooming on a map at all. Honoured only when the user hasn't asked for
// reduced motion.
function animateViewBox(svg, to, done) {
  if (zoomAnim) { cancelAnimationFrame(zoomAnim); zoomAnim = null; }
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion:reduce)").matches;
  const cur = (svg.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
  const from = cur.length === 4 && cur.every(isFinite)
    ? { x: cur[0], y: cur[1], w: cur[2], h: cur[3] } : to;
  if (reduce) { setViewBox(svg, to); if (done) done(); return; }
  const t0 = performance.now(), MS = 420;
  const ease = t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
  const step = now => {
    const t = Math.min(1, (now - t0) / MS), k = ease(t);
    setViewBox(svg, {
      x: from.x + (to.x - from.x) * k, y: from.y + (to.y - from.y) * k,
      w: from.w + (to.w - from.w) * k, h: from.h + (to.h - from.h) * k
    });
    if (t < 1) { zoomAnim = requestAnimationFrame(step); }
    else { zoomAnim = null; if (done) done(); }
  };
  zoomAnim = requestAnimationFrame(step);
}

// Frame one county with padding, keeping the home aspect ratio so the shape
// isn't stretched - a county box is rarely the same proportion as the panel.
function countyViewBox(svg, county) {
  const path = svg.querySelector(`path[data-county="${cssEscape(county)}"]`);
  if (!path) return null;
  let b;
  try { b = path.getBBox(); } catch { return null; }
  if (!(b.width > 0 && b.height > 0)) return null;
  // Deliberately the HOME aspect, not the panel's.
  //
  // Matching the panel was tried, to stop the county letterboxing inside a
  // wide desktop map, and it introduced a genuine ordering bug: the target
  // box is computed here, and only afterwards does the .zoomed class change
  // what the SVG is allowed to be sized to. So the aspect was measured
  // against one width and applied against another, the two disagreed, and
  // pins near the edge of the county ended up outside the drawn area - which
  // is what the harness caught. Filling the panel needs the element's size
  // to stop depending on the zoom state, not a different number here.
  const home = readHomeViewBox(svg);
  const aspect = home.w / home.h;
  const pad = Math.max(b.width, b.height) * 0.18;
  let w = b.width + pad * 2, h = b.height + pad * 2;
  if (w / h > aspect) h = w / aspect; else w = h * aspect;
  return { x: b.x + b.width / 2 - w / 2, y: b.y + b.height / 2 - h / 2, w, h };
}

function cssEscape(v) {
  return window.CSS && CSS.escape ? CSS.escape(v) : String(v).replace(/"/g, '\\"');
}

// The county zoom and the pin preview are layers a user expects Back to undo,
// same as a modal. app.js owns the stack so ordering across both modules is
// right - the preview closes before the zoom because it was opened later.
const back = {
  push: (n, f) => { if (window.tdwBack) window.tdwBack.push(n, f); },
  pop: n => { if (window.tdwBack) window.tdwBack.pop(n); }
};

function zoomTo(county) {
  const canvas = $(CANVAS_ID);
  const svg = canvas && canvas.querySelector("svg");
  if (!svg) return;
  readHomeViewBox(svg);
  const box = county && countyViewBox(svg, county);
  zoomCounty = box ? county : null;
  activeProp = null;
  if (zoomCounty) back.push("map-county", () => zoomOut());
  else back.pop("map-county");
  animateViewBox(svg, box || homeViewBox, () => draw());
  draw();
}

// ---------------------------------------------------------------------------
// drawing
// ---------------------------------------------------------------------------
const NS = "http://www.w3.org/2000/svg";
const fmtShort = n => "$" + Math.round(Number(n)).toLocaleString("en-US");

// sqrt scaling, not linear: bubble AREA should track the count, or one big
// county visually swamps a map where every other county still matters.
function radiusFor(count, max) {
  const MIN_R = 13, MAX_R = 38;
  if (max <= 1) return MIN_R;
  return MIN_R + (MAX_R - MIN_R) * Math.sqrt(count / max);
}

function draw() {
  const canvas = $(CANVAS_ID);
  const svg = canvas && canvas.querySelector("svg");
  if (!svg) return;

  canvas.dataset.ledger = ledger;
  // Never draw from measurements taken while hidden - that is what put every
  // bubble on the origin. Defer instead; watchForVisibility() re-runs this
  // the moment the panel has real geometry.
  if (!centroidsOk && !computeCentroids(canvas)) { pendingDraw = true; return; }

  // Group the rows the list is currently showing, by county.
  const byCounty = new Map();
  rows.forEach(p => {
    if (!byCounty.has(p.county)) byCounty.set(p.county, []);
    byCounty.get(p.county).push(p);
  });

  svg.querySelectorAll("path[data-county]").forEach(path => {
    const name = path.dataset.county;
    path.classList.toggle("has-rows", byCounty.has(name));
    path.classList.toggle("sel", selectedCounty === name);
  });

  let layer = svg.querySelector(".cluster-layer");
  if (!layer) {
    layer = document.createElementNS(NS, "g");
    layer.setAttribute("class", "cluster-layer");
    svg.appendChild(layer);
  }

  // Zoomed into a county: individual pins instead of one summary bubble.
  // If the filters moved on and that county no longer has rows, fall back to
  // the statewide view rather than showing an empty magnified county.
  if (zoomCounty && !byCounty.has(zoomCounty)) { zoomOut(); return; }
  if (zoomCounty) { drawPins(svg, layer, byCounty.get(zoomCounty) || []); return; }
  if (canvas) canvas.classList.remove("zoomed");
  drawZipAreas(svg, null, null);
  renderStrip(null);
  setBackVisible(false);
  showPreviewHidden();

  // Every redraw replaces all the bubble nodes. For a mouse that is
  // invisible; for the keyboard it silently drops focus to the top of the
  // document, so activating a bubble would lose your place every time -
  // caught by the harness, which pressed Enter twice and found the second
  // press went nowhere. Remember the focused county and restore it below.
  const activeEl = document.activeElement;
  const refocusCounty = activeEl && activeEl.classList &&
    activeEl.classList.contains("cluster-bubble") ? activeEl.dataset.county : null;

  layer.innerHTML = "";

  const counts = Array.from(byCounty.values(), r => r.length);
  const max = counts.length ? Math.max(...counts) : 0;
  const bubbleBoxes = [];

  // Biggest first so a small county's bubble is never buried under a large
  // neighbour's - later siblings paint on top in SVG.
  Array.from(byCounty.entries())
    .sort((a, b) => b[1].length - a[1].length)
    .forEach(([county, list]) => {
      const c = centroids.get(county);
      if (!c) return;                       // county not in the SVG (shouldn't
                                            // happen - names are 1:1 with
                                            // ALL_COUNTIES - but don't crash)
      const r = radiusFor(list.length, max);
      const g = document.createElementNS(NS, "g");
      g.setAttribute("class", "cluster-bubble" + (selectedCounty === county ? " sel" : "") +
        (selectedCounty && selectedCounty !== county ? " dim" : ""));
      g.dataset.county = county;
      // A bubble is a control, so it has to behave like one for anyone not
      // using a mouse: focusable, announced, and operable from the keyboard.
      // An SVG <g> gets none of that for free - without this the map is a
      // mouse-only feature, which is the same gap the filter chips have.
      g.setAttribute("tabindex", "0");
      g.setAttribute("role", "button");
      g.setAttribute("aria-label",
        `${county} County, ${list.length} ${list.length === 1 ? "property" : "properties"}` +
        (selectedCounty === county ? " - selected, activate to clear" : " - activate to filter the list"));
      g.setAttribute("aria-pressed", selectedCounty === county ? "true" : "false");

      const circle = document.createElementNS(NS, "circle");
      circle.setAttribute("cx", c.cx);
      circle.setAttribute("cy", c.cy);
      circle.setAttribute("r", r);
      g.appendChild(circle);

      const text = document.createElementNS(NS, "text");
      text.setAttribute("x", c.cx);
      text.setAttribute("y", c.cy);
      text.setAttribute("font-size", Math.max(13, Math.min(24, r * 0.95)));
      text.textContent = list.length;
      g.appendChild(text);

      bubbleBoxes.push({ x1: c.cx - r, y1: c.cy - r, x2: c.cx + r, y2: c.cy + r });
      layer.appendChild(g);
    });

  // After the bubbles, so their positions can reserve space.
  drawCities(svg, cityTop, bubbleBoxes);

  if (refocusCounty) {
    const again = layer.querySelector(
      `.cluster-bubble[data-county="${window.CSS && CSS.escape ? CSS.escape(refocusCounty) : refocusCounty}"]`);
    if (again) again.focus();
  }

  updateSummary(byCounty, max);
}

// ---------------------------------------------------------------------------
// county detail: pins, the card strip, and the preview card
// ---------------------------------------------------------------------------
// Pin geometry is divided by viewScale throughout. The viewBox shrinks as we
// zoom, so anything sized in user units would balloon on screen - a pin has
// to stay pin-sized however far in we are.
function drawPins(svg, layer, list) {
  svg.querySelectorAll("path[data-county]").forEach(path => {
    path.classList.toggle("zoom-focus", path.dataset.county === zoomCounty);
    path.classList.toggle("zoom-off", path.dataset.county !== zoomCounty);
  });

  const home = readHomeViewBox(svg);
  const upp = unitsPerPixel(svg);
  layer.innerHTML = "";
  const placed = list.filter(hasPin);

  const pinR = 7 * upp;
  const pinPts = placed.map(p => projectLatLng(p.latitude, p.longitude));
  drawZipAreas(svg, zoomCounty, pinPts);
  drawCities(svg, cities && cities[zoomCounty], placed.map(p => {
    const q = projectLatLng(p.latitude, p.longitude);
    return { x1: q.x - pinR, y1: q.y - pinR * 2.4, x2: q.x + pinR, y2: q.y };
  }));

  placed.forEach(p => {
    const { x, y } = projectLatLng(p.latitude, p.longitude);
    const g = document.createElementNS(NS, "g");
    g.setAttribute("class", "map-pin" + (activeProp && activeProp.id === p.id ? " sel" : ""));
    g.dataset.pid = String(p.id);
    g.setAttribute("tabindex", "0");
    g.setAttribute("role", "button");
    g.setAttribute("aria-label", `${pinLabel(p)} - activate for details`);

    const r = 7 * upp;
    // A teardrop, drawn so its POINT is the coordinate - a circle centred on
    // the spot reads as "somewhere around here", which is the opposite of
    // what a geocoded parcel deserves.
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d",
      `M ${x} ${y} l ${-r * 0.72} ${-r * 1.25} a ${r} ${r} 0 1 1 ${r * 1.44} 0 Z`);
    g.appendChild(path);
    const dot = document.createElementNS(NS, "circle");
    dot.setAttribute("cx", x); dot.setAttribute("cy", y - r * 1.25);
    dot.setAttribute("r", r * 0.32);
    dot.setAttribute("class", "pin-dot");
    g.appendChild(dot);
    layer.appendChild(g);
  });

  const canvas = $(CANVAS_ID);
  if (canvas) canvas.classList.add("zoomed");
  // Zooming destroys the bubble that was just activated. For a mouse that is
  // invisible; for the keyboard it drops focus to the top of the document, so
  // the county you just opened becomes unreachable without tabbing back
  // through the whole page. Hand focus to the back control instead - it is
  // the one thing every zoomed view has, and :focus-visible keeps a mouse
  // user from seeing a ring they did not ask for.
  const hadFocus = document.activeElement;
  const cameFromBubble = hadFocus && hadFocus.classList &&
    hadFocus.classList.contains("cluster-bubble");
  // The county tooltip is a statewide affordance. Clicking a bubble leaves it
  // on screen (the pointer never moves, so no mousemove fires to clear it),
  // where it sits over the county you just zoomed into.
  const tip = $("clusterTip");
  if (tip) tip.classList.remove("show");
  setBackVisible(true);
  if (cameFromBubble || hadFocus === document.body) {
    const back = $("exploreZoomOut");
    if (back) back.focus();
  }
  renderStrip(list, placed.length);
  updateSummary(new Map([[zoomCounty, list]]));
}

function pinLabel(p) {
  const a = (p.address || "").trim();
  if (a && !/^parcel\b/i.test(a)) return a;
  if (p.certificate_no) return "Certificate #" + p.certificate_no;
  return "Parcel " + (p.parcel || "unknown");
}

// The strip is built here rather than in index.html so the whole county-detail
// view stays inside this module - app.js and the page markup know nothing
// about it, same as the rest of the explore view.
function stripEl() {
  const map = document.querySelector(".explore-map");
  if (!map) return null;
  let strip = $("exploreStrip");
  if (!strip) {
    strip = document.createElement("div");
    strip.id = "exploreStrip";
    strip.className = "explore-strip";
    strip.hidden = true;
    const foot = map.querySelector(".explore-map-foot");
    map.insertBefore(strip, foot || null);
  }
  return strip;
}

function renderStrip(list, placedCount) {
  const strip = stripEl();
  if (!strip) return;
  if (!list) { strip.hidden = true; strip.innerHTML = ""; return; }

  const missing = list.length - (placedCount || 0);
  // Say plainly how many could not be placed. Showing 8 pins for a county of
  // 241 properties without saying so would read as "this county has 8".
  const note = !placedCount
    ? `<p class="strip-note">None of these ${list.length} have mapped coordinates yet — pick one below.</p>`
    : missing
      ? `<p class="strip-note"><b>${placedCount}</b> of ${list.length} are mapped. The rest are listed here.</p>`
      : `<p class="strip-note">All ${list.length} mapped.</p>`;

  strip.innerHTML = note + '<div class="strip-rail">' + list.map(p => `
    <button class="strip-card${hasPin(p) ? " mapped" : ""}${activeProp && activeProp.id === p.id ? " sel" : ""}"
            type="button" data-pid="${escAttr(p.id)}">
      <span class="strip-title">${escHtml(pinLabel(p))}</span>
      <span class="strip-bid">${bidText(p)}</span>
      ${hasPin(p) ? '<span class="strip-flag" aria-label="on the map">◉</span>' : ""}
    </button>`).join("") + "</div>";
  strip.hidden = false;
}

function bidText(p) {
  const n = Number(p.bid);
  return p.bid !== null && p.bid !== undefined && n > 0 ? fmtShort(n) : "Not published";
}

function escHtml(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const escAttr = escHtml;

// The preview card: enough to judge a property without leaving the map, and
// one button through to the full page that already exists in app.js.
function previewEl() {
  const map = $(CANVAS_ID);
  if (!map) return null;
  let card = $("explorePreview");
  if (!card) {
    card = document.createElement("div");
    card.id = "explorePreview";
    card.className = "explore-preview";
    card.hidden = true;
    map.appendChild(card);
    card.addEventListener("click", e => {
      if (e.target.closest("[data-act='close']")) { showPreview(null); return; }
      if (e.target.closest("[data-act='open']") && activeProp && openDetail) openDetail(activeProp);
    });
  }
  return card;
}

function showPreview(p) {
  activeProp = p;
  const card = previewEl();
  if (!card) return;
  if (!p) { card.hidden = true; back.pop("map-preview"); draw(); return; }
  back.push("map-preview", () => showPreview(null));

  const market = Number(p.market || p.assessed || 0);
  const rows2 = [
    ["Opening bid", bidText(p)],
    [p.market ? "Est. market" : "Assessed", market ? fmtShort(market) : "N/A"],
    [p.source === "certificate" ? "Expires" : "Sale date",
      (p.source === "certificate" ? p.expiration_date : p.sale_date) || "Not scheduled"]
  ];
  card.innerHTML = `
    <button class="preview-close" type="button" data-act="close" aria-label="Close preview">✕</button>
    <p class="preview-title">${escHtml(pinLabel(p))}</p>
    <p class="preview-sub">${escHtml(p.county)} County${hasPin(p) ? "" : " · location not mapped"}</p>
    <dl class="preview-stats">${rows2.map(([k, v]) =>
      `<div><dt>${escHtml(k)}</dt><dd>${escHtml(v)}</dd></div>`).join("")}</dl>
    <button class="preview-open" type="button" data-act="open">View full property page →</button>`;
  card.hidden = false;
  draw();
}

function setBackVisible(on) {
  const map = $(CANVAS_ID);
  if (!map) return;
  let btn = $("exploreZoomOut");
  if (!btn) {
    btn = document.createElement("button");
    btn.id = "exploreZoomOut";
    btn.className = "explore-zoom-out";
    btn.type = "button";
    btn.textContent = "← All counties";
    btn.addEventListener("click", () => zoomOut());
    map.appendChild(btn);
  }
  btn.hidden = !on;
}

function zoomOut() {
  const wasFiltered = selectedCounty;
  zoomCounty = null;
  activeProp = null;
  back.pop("map-preview");
  back.pop("map-county");
  showPreviewHidden();
  const canvas = $(CANVAS_ID);
  const svg = canvas && canvas.querySelector("svg");
  if (svg) {
    svg.querySelectorAll("path[data-county]").forEach(p => {
      p.classList.remove("zoom-focus", "zoom-off");
    });
    animateViewBox(svg, readHomeViewBox(svg), () => draw());
  }
  // Zooming out is also "show me everything again" - leaving the list pinned
  // to one county while the map shows the whole state is the kind of quiet
  // mismatch this view exists to avoid.
  if (wasFiltered) applyCounty(wasFiltered); else draw();
}

function showPreviewHidden() {
  const card = $("explorePreview");
  if (card) card.hidden = true;
}

// The counties in view, most first. This is the part of the map's job that
// bubbles are genuinely bad at: a 12-property county and an 8-property one
// are circles of almost the same size, and nothing on the map tells you
// which of the eight you are looking at is the biggest. A list does that in
// one glance, and it doubles as a keyboard-reachable way to pick a county -
// the bubbles are pointer targets sized by data, which is a poor tap target
// when the count is 1.
function renderCountyRail(byCounty) {
  const rail = $("exploreMapRail");
  if (!rail) return;

  // Zoomed into a county the rail would just be that one county, and the
  // strip of property cards below the map is already the better list.
  if (zoomCounty || !byCounty.size) {
    rail.hidden = true;
    rail.innerHTML = "";
    return;
  }

  const entries = [...byCounty.entries()]
    .map(([county, list]) => ({ county, n: list.length }))
    .sort((a, b) => b.n - a.n || a.county.localeCompare(b.county));
  const max = entries[0].n;

  rail.hidden = false;
  rail.innerHTML =
    '<div class="rail-head">Counties in view</div>' +
    '<ol class="rail-list">' +
    entries.map(e => `
      <li>
        <button class="rail-row${e.county === selectedCounty ? " on" : ""}" type="button"
                data-county="${escAttr(e.county)}">
          <span class="rail-name">${escHtml(e.county)}</span>
          <span class="rail-n">${e.n}</span>
          <span class="rail-bar" style="--w:${Math.round((e.n / max) * 100)}%"></span>
        </button>
      </li>`).join("") +
    '</ol>';

  rail.querySelectorAll(".rail-row").forEach(btn => {
    btn.addEventListener("click", () => applyCounty(btn.dataset.county));
  });
}

// Everything drawn in user units - city names, pins, the strip - is sized
// from the map's rendered size at draw time. Switching List -> Map, opening
// the county rail, or just resizing the window all change that size, and
// nothing redrew, so the map kept whatever scale it happened to be built
// at. One observer, debounced, fixes all three at once.
let resizeTimer = null;
function watchCanvasResize() {
  const canvas = $(CANVAS_ID);
  if (!canvas || !window.ResizeObserver || canvas.dataset.resizeWatched) return;
  canvas.dataset.resizeWatched = "1";
  new ResizeObserver(() => {
    clearTimeout(resizeTimer);
    // Long enough that a drag-resize doesn't redraw on every frame, short
    // enough that letting go feels immediate.
    resizeTimer = setTimeout(() => { if (rows && rows.length) draw(); }, 120);
  }).observe(canvas);
}

function updateSummary(byCounty) {
  renderCountyRail(byCounty);
  const titleEl = document.querySelector(".explore-map-title");
  if (titleEl) titleEl.textContent = zoomCounty ? `${zoomCounty} County` : "Where these are";
  const countEl = $("exploreMapCount");
  if (countEl) {
    const inCounty = zoomCounty ? (byCounty.get(zoomCounty) || []).length : 0;
    countEl.innerHTML = zoomCounty
      ? `<b>${inCounty}</b> ${inCounty === 1 ? "property" : "properties"}`
      : byCounty.size
        ? `<b>${rows.length}</b> shown across <b>${byCounty.size}</b> ${byCounty.size === 1 ? "county" : "counties"}`
        : "Nothing matches the current filters";
  }
  const resetBtn = $("exploreMapReset");
  if (resetBtn) resetBtn.hidden = !selectedCounty;
  // The standing footnote describes the statewide bubbles. Zoomed in there
  // are no bubbles - there are pins at real coordinates - so leaving it up
  // would be describing the wrong map.
  const note = document.querySelector(".explore-map-note");
  if (note) {
    note.textContent = zoomCounty
      ? "Pins are the geocoded parcel locations we hold. Properties without coordinates are listed above but not pinned."
      : "Bubbles are county-level counts, sized by how many properties match your filters \u2014 not exact parcel locations.";
  }
  const hint = $("exploreMapHint");
  if (hint) {
    hint.textContent = zoomCounty
      ? "Tap a pin or a card below for details"
      : selectedCounty
        ? `Filtered to ${selectedCounty} - tap it again to clear`
        : "Tap a county to zoom in and filter the list to it";
  }
}

// ---------------------------------------------------------------------------
// interaction
// ---------------------------------------------------------------------------
// Clicking a bubble drives the EXISTING county dropdown rather than reaching
// into app.js's state: #countyQuick's change handler already narrows the
// filter, expands that county's groups and re-renders. Reusing it means the
// map can't develop its own subtly different idea of what "filter to a
// county" means, and app.js needed no second edit to support this.
function applyCounty(county) {
  const select = $("countyQuick");
  if (!select) return;
  const next = selectedCounty === county ? "ALL" : county;
  // A county with no rows in this ledger isn't in the dropdown; ignore rather
  // than setting a value the select will reject and silently keep as-is.
  if (next !== "ALL" && !Array.from(select.options).some(o => o.value === next)) return;
  select.value = next;
  select.dispatchEvent(new Event("change", { bubbles: true }));
  selectedCounty = next === "ALL" ? null : next;
  // Filtering to a county and zooming into it are one gesture, not two:
  // picking a county on a map should take you there.
  if (next === "ALL") { if (zoomCounty) zoomTo(null); else draw(); }
  else zoomTo(next);
  // On a phone the list sits below the map, so a tap that changes the list
  // should actually take you to it.
  if (next !== "ALL" && !window.matchMedia("(min-width:1024px)").matches) {
    const main = document.getElementById("main");
    if (main) main.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function bindMapInteraction() {
  const canvas = $(CANVAS_ID);
  if (!canvas) return;
  const tip = $("clusterTip");

  // Enter/Space on a focused bubble does what a click does. Space is
  // preventDefault'd or the page scrolls out from under the selection.
  canvas.addEventListener("keydown", e => {
    if (e.key === "Escape" && zoomCounty) { e.preventDefault(); zoomOut(); return; }
    if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
    const pin = e.target.closest && e.target.closest(".map-pin");
    if (pin) { e.preventDefault(); showPreview(propById(pin.dataset.pid)); return; }
    const bubble = e.target.closest && e.target.closest(".cluster-bubble");
    if (!bubble) return;
    e.preventDefault();
    applyCounty(bubble.dataset.county);
  });

  canvas.addEventListener("click", e => {
    // The preview card and the back control are children of the canvas so they
    // can be positioned over the map. That puts their clicks through this
    // handler too, and the "tap empty space to dismiss" branch below was
    // closing the card the moment you pressed a button inside it.
    if (e.target.closest("#explorePreview") || e.target.closest("#exploreZoomOut")) return;
    const pin = e.target.closest(".map-pin");
    if (pin) { showPreview(propById(pin.dataset.pid)); return; }
    const bubble = e.target.closest(".cluster-bubble");
    if (bubble) { applyCounty(bubble.dataset.county); return; }
    // Zoomed in, a tap on empty space dismisses the preview rather than
    // re-filtering to the county you are already inside.
    if (zoomCounty) { if (activeProp) showPreview(null); return; }
    const path = e.target.closest("path[data-county]");
    // Tapping the county shape itself works too, but only where there's
    // something to filter to - otherwise it reads as a dead tap.
    if (path && rows.some(p => p.county === path.dataset.county)) applyCounty(path.dataset.county);
  });

  canvas.addEventListener("mousemove", e => {
    if (zoomCounty) { if (tip) tip.classList.remove("show"); return; }
    const bubble = e.target.closest(".cluster-bubble");
    if (!bubble || !tip) { if (tip) tip.classList.remove("show"); clearFocus(); return; }
    const county = bubble.dataset.county;
    const list = rows.filter(p => p.county === county);
    const bids = list.map(p => Number(p.bid)).filter(n => n > 0);
    const range = bids.length
      ? (bids.length === 1 ? fmtShort(bids[0]) : `${fmtShort(Math.min(...bids))} - ${fmtShort(Math.max(...bids))}`)
      : "no published price";
    tip.innerHTML = `<b>${county} County</b><span>${list.length} ${list.length === 1 ? "property" : "properties"} - ${range}</span>`;
    const box = canvas.getBoundingClientRect();
    // Flip the tooltip to the left of the cursor near the right edge so it
    // can't run off the panel.
    const x = e.clientX - box.left, y = e.clientY - box.top;
    tip.style.left = (x > box.width - 220 ? Math.max(4, x - 216) : x + 14) + "px";
    tip.style.top = Math.max(4, y - 12) + "px";
    tip.classList.add("show");
    focusCounty(county);
  });

  canvas.addEventListener("mouseleave", () => {
    if (tip) tip.classList.remove("show");
    clearFocus();
  });
}

// Two-way highlight: hovering a bubble outlines that county's group in the
// list, and hovering a group's header pulses its bubble. Without it the two
// panes read as unrelated widgets that happen to sit side by side.
function focusCounty(county) {
  document.querySelectorAll("#main .county-group").forEach(g => {
    g.classList.toggle("map-focus", g.dataset.county === county);
  });
}
function clearFocus() {
  document.querySelectorAll("#main .county-group.map-focus").forEach(g => g.classList.remove("map-focus"));
}

function bindListHover() {
  const main = document.getElementById("main");
  if (!main) return;
  main.addEventListener("mouseover", e => {
    const group = e.target.closest(".county-group");
    if (!group) return;
    const svg = $(CANVAS_ID);
    if (!svg) return;
    svg.querySelectorAll(".cluster-bubble").forEach(b => {
      b.classList.toggle("sel", b.dataset.county === group.dataset.county || b.dataset.county === selectedCounty);
    });
  });
  main.addEventListener("mouseleave", () => {
    const svg = $(CANVAS_ID);
    if (!svg) return;
    svg.querySelectorAll(".cluster-bubble").forEach(b => {
      b.classList.toggle("sel", b.dataset.county === selectedCounty);
    });
  });
}

function propById(id) {
  return rows.find(p => String(p.id) === String(id)) || null;
}

// Delegated on the panel, because the strip is rebuilt on every draw.
function bindStrip() {
  const map = document.querySelector(".explore-map");
  if (!map) return;
  // Escape from anywhere in the panel - a strip card, the preview, the back
  // button - is the way out of a county without reaching for the mouse.
  map.addEventListener("keydown", e => {
    if (e.key === "Escape" && zoomCounty) { e.preventDefault(); zoomOut(); }
  });
  map.addEventListener("click", e => {
    const card = e.target.closest(".strip-card");
    if (!card) return;
    const p = propById(card.dataset.pid);
    if (!p) return;
    showPreview(activeProp && activeProp.id === p.id ? null : p);
  });
}

function bindReset() {
  const btn = $("exploreMapReset");
  if (!btn) return;
  btn.addEventListener("click", () => { if (selectedCounty) applyCounty(selectedCounty); });
}

// ---------------------------------------------------------------------------
// wiring
// ---------------------------------------------------------------------------
function absorb(detail) {
  const d = detail || {};
  rows = Array.isArray(d.rows) ? d.rows : [];
  ledger = d.ledger || ledger;
  openDetail = d.openDetail || openDetail;
  // The county dropdown is the source of truth for "am I filtered to one
  // county" - the user can change it from the dropdown, the chips or the
  // filter-panel map, and the bubbles have to reflect that too.
  const select = $("countyQuick");
  selectedCounty = select && select.value !== "ALL" ? select.value : null;
  // The county can also change from the dropdown, the chips or the filter
  // panel's own map. Keep the zoom in step with whatever moved it.
  if (svgLoaded && zoomCounty && zoomCounty !== selectedCounty) { zoomTo(selectedCounty); return; }
  if (svgLoaded) draw();
}

window.addEventListener("tdw:rendered", e => absorb(e.detail));

bindViewToggle();
bindMapInteraction();
bindListHover();
bindReset();
bindStrip();
watchForVisibility();

// Pick up a render that already happened before this module finished loading
// (see the header note) - without this the map would stay empty until the
// next filter change.
if (window.__tdwLastRender) absorb(window.__tdwLastRender);
