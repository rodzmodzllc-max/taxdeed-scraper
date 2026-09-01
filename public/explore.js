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
    computeCentroids(canvas);
    draw();
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

      layer.appendChild(g);
    });

  if (refocusCounty) {
    const again = layer.querySelector(
      `.cluster-bubble[data-county="${window.CSS && CSS.escape ? CSS.escape(refocusCounty) : refocusCounty}"]`);
    if (again) again.focus();
  }

  updateSummary(byCounty, max);
}

function updateSummary(byCounty) {
  const countEl = $("exploreMapCount");
  if (countEl) {
    countEl.innerHTML = byCounty.size
      ? `<b>${rows.length}</b> shown across <b>${byCounty.size}</b> ${byCounty.size === 1 ? "county" : "counties"}`
      : "Nothing matches the current filters";
  }
  const resetBtn = $("exploreMapReset");
  if (resetBtn) resetBtn.hidden = !selectedCounty;
  const hint = $("exploreMapHint");
  if (hint) {
    hint.textContent = selectedCounty
      ? `Filtered to ${selectedCounty} - tap it again to clear`
      : "Tap a county to filter the list to it";
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
  draw();
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
    if (e.key !== "Enter" && e.key !== " " && e.key !== "Spacebar") return;
    const bubble = e.target.closest && e.target.closest(".cluster-bubble");
    if (!bubble) return;
    e.preventDefault();
    applyCounty(bubble.dataset.county);
  });

  canvas.addEventListener("click", e => {
    const bubble = e.target.closest(".cluster-bubble");
    if (bubble) { applyCounty(bubble.dataset.county); return; }
    const path = e.target.closest("path[data-county]");
    // Tapping the county shape itself works too, but only where there's
    // something to filter to - otherwise it reads as a dead tap.
    if (path && rows.some(p => p.county === path.dataset.county)) applyCounty(path.dataset.county);
  });

  canvas.addEventListener("mousemove", e => {
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
  if (svgLoaded) draw();
}

window.addEventListener("tdw:rendered", e => absorb(e.detail));

bindViewToggle();
bindMapInteraction();
bindListHover();
bindReset();
watchForVisibility();

// Pick up a render that already happened before this module finished loading
// (see the header note) - without this the map would stay empty until the
// next filter change.
if (window.__tdwLastRender) absorb(window.__tdwLastRender);
