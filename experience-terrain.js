// ==================== Terrain look: living map & time (2026-10-25) ====================
// One of the two trial List experiences behind the header "Look" switch
// (app.js installLookSwitch). It draws the rows the List just filtered (the
// tdw:rendered payload) into #xpStage as a light survey sheet:
//   AUCTIONS     - driven by TIME: a sale-day scrubber (next 45 days, rings
//                  sized by how many lots sell that day, earlier / later /
//                  undated at the ends). A day drops its lots as pins on a
//                  decorative plat and as cards. A pin is placed only from a
//                  row's own latitude / longitude; a lot without them says
//                  "Not yet geocoded" and gets no pin.
//   AVAILABLE    - about PLACE: one story per county (its count, its cards
//                  in a snapping rail), each card with the app's own imagery
//                  ladder and the acquisition path as a trail of waypoints
//                  (verified steps only; otherwise "Not yet verified").
//   LIENS        - no map (a certificate is not land): tax years as strata;
//                  a stratum opens to survey tags that flip to the facts the
//                  source published.
// Every label and figure comes from the app's own helpers (detail.api), so
// nothing here names or computes a figure. Opening a record always calls the
// app's real property page (api.openDetail).
// No imports, same-origin only. Draws only while
// window.__tdwExperience.name === "terrain".

const NAME = "terrain";
const PAGE = 48;            // auction lots per day, first draw / per "Show more"
const STORY_PAGE = 6;       // county stories per draw step
const STORY_CARDS = 8;      // cards per story at first (6 x 8 = 48)
const STORY_MORE = 16;
const TAG_PAGE = 24;        // certificate tags per open stratum
const WINDOW_DAYS = 45;

const S = {
  scene: "",
  auction: { day: null, sel: null, limit: {}, dayKey: "" },
  laft: { storyLimit: STORY_PAGE, cards: {} },
  certificate: { open: new Set(), flipped: new Set(), limit: {}, justOpened: null, inited: false }
};
let LAST = null;            // last payload drawn
let BY_ID = new Map();      // id -> row, for the rows on screen
let BOUND = false;

const reduced = () => { try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; } };
const isNum = v => v !== null && v !== undefined && v !== "" && Number.isFinite(Number(v));
const hasCoords = p => isNum(p.latitude) && isNum(p.longitude) && !(Number(p.latitude) === 0 && Number(p.longitude) === 0);
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WK = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const WEEKDAY = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

function todayUTC() { const t = new Date(); return Date.UTC(t.getFullYear(), t.getMonth(), t.getDate()); }
function saleDayOffset(p) {
  const s = String(p.sale_date || "").slice(0, 10);
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
  if (!m) return null;
  return Math.round((Date.UTC(+m[1], +m[2] - 1, +m[3]) - todayUTC()) / 86400000);
}
function bucketOf(p) {
  const d = saleDayOffset(p);
  if (d === null) return "undated";
  if (d < 0) return "past";
  if (d >= WINDOW_DAYS) return "later";
  return "d" + d;
}
function dayDate(i) { return new Date(todayUTC() + i * 86400000); }
function urgency(i) { return i === 0 ? "u-today" : i <= 3 ? "u-near" : i <= 14 ? "u-mid" : "u-far"; }

// ---------- stage lifecycle ----------
function stageEl() { return document.getElementById("xpStage"); }
function active() { const x = window.__tdwExperience; return !!(x && x.name === NAME); }
function teardown() {
  const stage = stageEl();
  if (stage && stage.dataset.xp === NAME) { stage.innerHTML = ""; delete stage.dataset.xp; }
  if (document.documentElement.dataset.experienceReady === NAME) delete document.documentElement.dataset.experienceReady;
}

function draw(detail, opts) {
  if (!active()) { teardown(); return; }
  const d = detail || window.__tdwLastRender;
  const stage = stageEl();
  if (!d || !stage) return;
  const api = d.api || (window.__tdwExperience && window.__tdwExperience.api);
  if (!api) return;
  LAST = d;
  S.width = stage.clientWidth || 0;
  const rows = Array.isArray(d.rows) ? d.rows : [];
  if (!rows.length) {
    // Nothing to draw: give the List back its own empty state, which says
    // WHICH zero this is (loading, withheld, no inventory, failed read).
    teardown();
    return;
  }
  const ledger = d.ledger === "laft" || d.ledger === "certificate" ? d.ledger : "auction";
  const enter = S.scene !== ledger;
  S.scene = ledger;
  BY_ID = new Map();

  // Keep horizontal scroll positions across a redraw.
  const keep = {};
  stage.querySelectorAll("[data-xt-keep]").forEach(el => { keep[el.dataset.xtKeep] = el.scrollLeft; });

  let html;
  if (ledger === "auction") html = auctionView(rows, api, enter, opts);
  else if (ledger === "laft") html = availableView(rows, api, enter);
  else html = liensView(rows, api, enter);

  stage.dataset.xp = NAME;
  stage.innerHTML = html;
  stage.querySelectorAll("[data-xt-keep]").forEach(el => {
    if (keep[el.dataset.xtKeep] !== undefined) el.scrollLeft = keep[el.dataset.xtKeep];
  });
  if (ledger === "auction" && (enter || (opts && opts.centerDay))) centerSelectedDay(stage);
  try { api.hydrateVisuals(stage); } catch {}
  bind(stage);
  document.documentElement.dataset.experienceReady = NAME;
}

// ---------- shared bits ----------
function stakeSvg() {
  return `<svg class="xt-stake" viewBox="0 0 16 26" aria-hidden="true"><rect x="1" y="2" width="3.5" height="23" rx="1.5" fill="#A4512A"/><path d="M4.5 3h10l-3 4 3 4h-10z" fill="#7E3B1C"/></svg>`;
}
function watchBtn(p, api) {
  const on = !!api.isWatched(p.id);
  return `<button type="button" class="xt-btn xt-btn-quiet${on ? " on" : ""}" data-action="bidlist" data-pid="${api.esc(p.id)}" aria-pressed="${on}">` +
    `<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4z" fill="${on ? "currentColor" : "none"}" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>` +
    `${on ? "On watchlist" : "Watch"}</button>`;
}
function openBtn(p, api, cls) {
  return `<button type="button" class="xt-btn ${cls || "xt-btn-primary"}" data-xt="open" data-pid="${api.esc(p.id)}">Open record<span aria-hidden="true">→</span></button>`;
}
function titleHtml(p, api) {
  const a = api.realAddress(p);
  return a ? api.esc(a) : api.lotTitle(p); // lotTitle() returns escaped HTML
}
function idRow(p, api) {
  const parts = [];
  const parcel = api.parcelOf(p);
  if (parcel && String(parcel).trim()) parts.push(`Parcel # ${api.esc(parcel)}`);
  const c = api.caseIdentText(p);
  if (c) parts.push(api.esc(c));
  return parts.join(" · ");
}
function heads(api, ledger, title, sub, extra) {
  const st = api.stateCode ? api.stateCode() : "";
  return `<header class="xt-head xt-glass">
    <div class="xt-head-k"><span class="xt-ledger-dot"></span>${api.esc(api.ledgerTitle(ledger))}${st ? ` · ${api.esc(st)}` : ""}</div>
    <h2 class="xt-h1">${title}</h2>
    ${sub ? `<p class="xt-sub">${sub}</p>` : ""}
    ${extra || ""}
  </header>`;
}
function n(x) { return Number(x).toLocaleString("en-US"); }

// Decorative plat: blocks, lots, roads, water, contours. Drawn once and
// cached; it is the ground under the pins, never a map of where they are.
let PLAT_SVG = "";
function platSvg() {
  if (PLAT_SVG) return PLAT_SVG;
  let seed = 7;
  const rnd = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
  const W = 1000, H = 800;
  let blocks = "";
  for (let gy = 0; gy < 7; gy++) {
    for (let gx = 0; gx < 9; gx++) {
      if (rnd() < 0.16) continue;
      const x = 18 + gx * 112 + (gy % 2 ? 20 : 0), y = 14 + gy * 116;
      const w = 84 + rnd() * 12, h = 88 + rnd() * 10;
      const lots = 3 + Math.floor(rnd() * 3);
      let l = "";
      for (let k = 1; k < lots; k++) l += `<line x1="${(x + (w * k) / lots).toFixed(1)}" y1="${y}" x2="${(x + (w * k) / lots).toFixed(1)}" y2="${(y + h).toFixed(1)}"/>`;
      l += `<line x1="${x}" y1="${(y + h / 2).toFixed(1)}" x2="${(x + w).toFixed(1)}" y2="${(y + h / 2).toFixed(1)}"/>`;
      const rot = gx > 5 && gy < 3 ? ` transform="rotate(-9 ${x + w / 2} ${y + h / 2})"` : "";
      blocks += `<g class="xt-blk" style="--b:${(gx + gy) * 28}ms"${rot}><rect x="${x}" y="${y}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="2"/>${l}</g>`;
    }
  }
  let contours = "";
  for (let i = 0; i < 6; i++) {
    const cy = 120 + i * 120, a = 26 + rnd() * 30;
    contours += `<path class="xt-draw" pathLength="1" d="M-20 ${cy} C 180 ${(cy - a).toFixed(0)}, 330 ${(cy + a).toFixed(0)}, 520 ${cy} S 860 ${(cy - a).toFixed(0)}, 1030 ${(cy + 10).toFixed(0)}" style="--dl:${200 + i * 70}ms"/>`;
  }
  PLAT_SVG = `<svg class="xt-plat-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
    <defs><pattern id="xtWet" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="7" height="7" fill="#E4ECE6"/><line x1="0" y1="0" x2="0" y2="7" stroke="#CFDDD3" stroke-width="2.2"/></pattern></defs>
    <rect width="${W}" height="${H}" fill="#F1ECE2"/>
    <g class="xt-contours">${contours}</g>
    <g class="xt-blocks">${blocks}</g>
    <path class="xt-water" d="M760 520 C 820 470, 940 480, 980 540 S 960 690, 860 700 S 700 640, 760 520 Z" fill="url(#xtWet)" stroke="#B9CDBF" stroke-width="1.5"/>
    <path class="xt-river xt-draw" pathLength="1" d="M-10 690 C 160 640, 260 720, 420 660 S 640 560, 770 600" style="--dl:120ms"/>
    <g class="xt-roads">
      <path class="xt-draw" pathLength="1" d="M0 360 C 240 330, 520 400, 1000 340" style="--dl:60ms"/>
      <path class="xt-draw" pathLength="1" d="M430 0 C 410 260, 470 520, 440 800" style="--dl:160ms"/>
      <path class="xt-draw" pathLength="1" d="M0 120 L 1000 170" style="--dl:260ms"/>
    </g>
    <text class="xt-plat-lbl" x="130" y="350">sale-day plat</text>
    <text class="xt-plat-lbl xt-plat-w" x="808" y="610">lake</text>
  </svg>`;
  return PLAT_SVG;
}

// ---------- AUCTIONS: time ----------
function auctionView(rows, api, enter, opts) {
  const A = S.auction;
  const buckets = new Map();
  for (const p of rows) {
    const k = bucketOf(p);
    let b = buckets.get(k);
    if (!b) { b = []; buckets.set(k, b); }
    b.push(p);
  }
  // Keep the selected day when it still has lots; otherwise the first day
  // with sales from today on, then later / undated / earlier.
  if (!A.day || !buckets.has(A.day)) {
    let pick = null;
    for (let i = 0; i < WINDOW_DAYS && !pick; i++) if (buckets.has("d" + i)) pick = "d" + i;
    pick = pick || ["later", "undated", "past"].find(k => buckets.has(k)) || "d0";
    A.day = pick; A.sel = null;
  }
  const dayEnter = enter || A.dayKey !== A.day;
  A.dayKey = A.day;

  let max = 1;
  buckets.forEach((v, k) => { if (k.charAt(0) === "d") max = Math.max(max, v.length); });
  let inWindow = 0;
  for (let i = 0; i < WINDOW_DAYS; i++) inWindow += (buckets.get("d" + i) || []).length;

  const cols = [];
  const endCol = (k, label, sub) => {
    const c = (buckets.get(k) || []).length;
    const on = A.day === k;
    return `<button type="button" class="xt-col xt-col-end${on ? " on" : ""}${c ? "" : " empty"}" data-xt="day" data-day="${k}" aria-pressed="${on}" aria-label="${api.esc(label + ", " + c + (c === 1 ? " lot" : " lots"))}"${c ? "" : " disabled"}>
      ${on ? `<span class="xt-handle"></span>${stakeSvg()}` : ""}<span class="xt-end-n">${n(c)}</span><span class="xt-colwk">${api.esc(label)}</span><span class="xt-end-sub">${api.esc(sub)}</span></button>`;
  };
  cols.push(endCol("past", "Earlier", "past dates"));
  for (let i = 0; i < WINDOW_DAYS; i++) {
    const dt = dayDate(i), k = "d" + i, c = (buckets.get(k) || []).length, on = A.day === k;
    const size = c ? Math.round(12 + 22 * Math.sqrt(c / max)) : 0;
    const monthStart = dt.getUTCDate() === 1 || i === 0;
    cols.push(`<button type="button" class="xt-col ${urgency(i)}${on ? " on" : ""}${c ? " has" : ""}" data-xt="day" data-day="${k}" aria-pressed="${on}" aria-label="${api.esc(MON[dt.getUTCMonth()] + " " + dt.getUTCDate() + (i === 0 ? ", today" : "") + ", " + (c ? c + (c === 1 ? " lot" : " lots") : "no sales"))}" style="--i:${i}">
      ${monthStart ? `<span class="xt-month">${i === 0 ? "Today" : MON[dt.getUTCMonth()]}</span>` : ""}
      ${on ? `<span class="xt-handle"></span>${stakeSvg()}` : ""}
      ${c ? `<span class="xt-ring" style="--s:${size}px"></span>` : `<span class="xt-tick"></span>`}
      <span class="xt-colnum">${dt.getUTCDate()}</span><span class="xt-colwk">${WK[dt.getUTCDay()]}</span></button>`);
  }
  cols.push(endCol("later", "Later", "after 45 days"));
  cols.push(endCol("undated", "No date", "not scheduled"));

  // Banner for the chosen day.
  const list = buckets.get(A.day) || [];
  let big, sub;
  if (A.day.charAt(0) === "d") {
    const i = Number(A.day.slice(1)), dt = dayDate(i);
    big = `${MON[dt.getUTCMonth()]} ${dt.getUTCDate()}`;
    sub = `${WEEKDAY[dt.getUTCDay()]} · ${i === 0 ? "today" : i === 1 ? "tomorrow" : "in " + i + " days"}`;
  } else if (A.day === "past") { big = "Earlier"; sub = "Sale dates that have passed · results only as published"; }
  else if (A.day === "later") { big = "Later"; sub = "Sales more than 45 days out"; }
  else { big = "No date"; sub = "Sale date not scheduled by the source"; }

  const limit = A.limit[A.day] || PAGE;
  const shown = list.slice(0, limit);
  shown.forEach(p => BY_ID.set(String(p.id), p));

  // Pins: real coordinates only, fitted into the plat box.
  const wide = S.width >= 760; // the CSS switches to two columns at the same container width
  const ar = wide ? 1.05 : 1.3; // width / height, matches the CSS aspect-ratio
  const geo = shown.filter(hasCoords);
  let pins = "";
  if (geo.length) {
    const lat0 = geo.reduce((a, p) => a + Number(p.latitude), 0) / geo.length;
    const k = Math.cos((lat0 * Math.PI) / 180);
    const xs = geo.map(p => Number(p.longitude) * k), ys = geo.map(p => -Number(p.latitude));
    let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const minSpan = 0.04;
    if (x1 - x0 < minSpan) { const c = (x0 + x1) / 2; x0 = c - minSpan / 2; x1 = c + minSpan / 2; }
    if (y1 - y0 < minSpan) { const c = (y0 + y1) / 2; y0 = c - minSpan / 2; y1 = c + minSpan / 2; }
    const W = ar * 100, H = 100, pad = 0.14;
    const sc = Math.min((W * (1 - 2 * pad)) / (x1 - x0), (H * (1 - 2 * pad)) / (y1 - y0));
    const ox = (W - (x1 - x0) * sc) / 2, oy = (H - (y1 - y0) * sc) / 2;
    const urg = A.day.charAt(0) === "d" ? urgency(Number(A.day.slice(1))) : "u-far";
    const caps = geo.length <= 5;
    pins = geo.map((p, idx) => {
      const left = ((ox + (xs[idx] - x0) * sc) / W) * 100;
      const top = ((oy + (ys[idx] - y0) * sc) / H) * 100;
      const amt = api.amountShort(p);
      const sel = A.sel === String(p.id);
      return `<button type="button" class="xt-pin ${urg}${sel ? " sel" : ""}${caps ? " cap" : ""}" data-xt="pin" data-pid="${api.esc(p.id)}" style="left:${left.toFixed(2)}%;top:${top.toFixed(2)}%;--k:${Math.min(idx, 12)}" aria-label="${api.esc(p.county + ", " + (api.realAddress(p) || "parcel " + (api.parcelOf(p) || "not published")) + ", " + amt.label + " " + amt.text)}">
        <span class="xt-pin-pulse"></span><span class="xt-pin-body"><span class="xt-drop"></span><span class="xt-drop-dot"></span></span>
        <span class="xt-cap"><span class="k">${api.esc(amt.label)}</span><span class="v">${api.esc(amt.text)}</span></span></button>`;
    }).join("");
  }
  const noGeo = shown.length - geo.length;
  const platNote = geo.length
    ? `${n(geo.length)} of ${n(shown.length)} lot${shown.length === 1 ? "" : "s"} pinned from ${geo.length === 1 ? "its" : "their"} published coordinates${noGeo ? ` · ${n(noGeo)} not yet geocoded, no pin drawn` : ""}. The plat underneath is decoration, not a map.`
    : `None of these lots is geocoded yet, so no pins are drawn. The plat is decoration, not a map.`;

  const cards = shown.map((p, i) => auctionCard(p, api, i)).join("");
  const more = list.length > shown.length
    ? `<button type="button" class="xt-more" data-xt="more-day">Show ${n(Math.min(PAGE, list.length - shown.length))} more · ${n(list.length - shown.length)} left this day</button>` : "";

  return `<div class="xp-terrain xt-auction${enter ? " xt-enter" : ""}" data-ledger="auction">
    <div class="xt-grain" aria-hidden="true"></div>
    ${heads(api, "auction", `<span class="xt-banner${dayEnter ? " xt-swap" : ""}"><span class="xt-date">${api.esc(big)}</span><span class="xt-date-sub">${api.esc(sub)}</span></span>`, "", `<div class="xt-count${dayEnter ? " xt-swap" : ""}"><span class="xt-count-n">${n(list.length)}</span><span class="xt-count-l">${list.length === 1 ? "lot" : "lots"}</span></div>`)}
    <section class="xt-scrub xt-glass" aria-label="Sale days">
      <div class="xt-scrub-top"><span class="xt-scrub-k">${stakeSvg()}Next 45 days</span><span class="xt-scrub-total">${n(inWindow)} of ${n(rows.length)} in window</span></div>
      <div class="xt-ruler" data-xt-keep="ruler" role="group" aria-label="Pick a sale day">${cols.join("")}</div>
    </section>
    <div class="xt-day${dayEnter ? " xt-day-enter" : ""}">
      <div class="xt-plat-wrap xt-glass" data-xt-ping>
        <div class="xt-plat" style="--ar:${ar}">${platSvg()}<div class="xt-pins">${pins}</div>
          ${geo.length ? "" : `<div class="xt-plat-empty"><span>Not yet geocoded</span></div>`}
        </div>
        <p class="xt-plat-note">${api.esc(platNote)}</p>
      </div>
      <div class="xt-lots-col">
        <ol class="xt-lots" aria-label="Lots on this day">${cards}</ol>
        ${more}
      </div>
    </div>
  </div>`;
}

function auctionCard(p, api, i) {
  const pf = api.previewFacts(p);
  const amt = api.amountShort(p);
  const sel = S.auction.sel === String(p.id);
  const gaps = (api.dataGaps(p) || []).slice(0, 3);
  const flood = pf.flood ? pf.flood.text : null;
  return `<li class="xt-lot${sel ? " sel" : ""}" data-xt="lot" data-pid="${api.esc(p.id)}" data-xt-ping style="--r:${Math.min(i, 10)}">
    <div class="xt-lot-k">${api.cardKickerHtml(p)}</div>
    <h3 class="xt-lot-t">${titleHtml(p, api)}</h3>
    <div class="xt-ids">${idRow(p, api)}</div>
    <div class="xt-figs">
      <div class="xt-fig xt-fig-main"><span class="xt-lbl">${api.esc(amt.label)}</span><span class="xt-num${amt.state === "not_published" ? " np" : ""}">${api.esc(amt.text)}</span></div>
      <div class="xt-fig"><span class="xt-lbl">${api.esc(pf.valueLabel || "County value")}</span><span class="xt-num xt-num-s${pf.value ? "" : " np"}">${api.esc(pf.value || "Not published")}</span>${pf.value ? `<span class="xt-fig-note">Not a sale price</span>` : ""}</div>
    </div>
    <div class="xt-facts">
      <span class="xt-fact${hasCoords(p) ? " on" : ""}"><i></i>${hasCoords(p) ? "Pinned on the plat" : "Not yet geocoded"}</span>
      ${flood ? `<span class="xt-fact"><b>Flood</b> ${api.esc(flood)}</span>` : ""}
    </div>
    ${gaps.length ? `<p class="xt-gaps"><b>Not on file:</b> ${gaps.map(g => api.esc(g)).join(" · ")}</p>` : ""}
    <div class="xt-actions">${openBtn(p, api)}${watchBtn(p, api)}</div>
  </li>`;
}

function centerSelectedDay(stage) {
  const ruler = stage.querySelector(".xt-ruler");
  const on = ruler && ruler.querySelector(".xt-col.on");
  if (!ruler || !on) return;
  requestAnimationFrame(() => {
    const target = on.offsetLeft - ruler.clientWidth / 2 + on.offsetWidth / 2;
    ruler.scrollLeft = Math.max(0, target);
  });
}

// ---------- AVAILABLE: place ----------
function availableView(rows, api, enter) {
  const L = S.laft;
  const groups = [];
  const index = new Map();
  for (const p of rows) {
    const key = String(p.county || "");
    let g = index.get(key);
    if (!g) { g = { county: key, rows: [] }; index.set(key, g); groups.push(g); }
    g.rows.push(p);
  }
  const unit = api.unitWord ? api.unitWord() : "County";
  const st = api.stateCode ? api.stateCode() : "";
  const storyCount = Math.min(groups.length, L.storyLimit);
  const chips = groups.slice(0, 120).map((g, i) =>
    `<button type="button" class="xt-chip" data-xt="jump" data-story="${i}"><span>${api.esc(g.county)}</span><b>${n(g.rows.length)}</b></button>`).join("");

  const stories = groups.slice(0, storyCount).map((g, si) => {
    const lim = L.cards[g.county] || STORY_CARDS;
    const shown = g.rows.slice(0, lim);
    shown.forEach(p => BY_ID.set(String(p.id), p));
    const cards = shown.map((p, i) => availableCard(p, api, i)).join("");
    const left = g.rows.length - shown.length;
    const more = left > 0 ? `<button type="button" class="xt-rail-more" data-xt="more-story" data-county="${api.esc(g.county)}"><span class="xt-rail-more-n">+${n(Math.min(STORY_MORE, left))}</span><span>Show more in ${api.esc(g.county)}</span><span class="xt-rail-more-s">${n(left)} not drawn yet</span></button>` : "";
    return `<section class="xt-story" id="xtStory${si}" style="--s:${Math.min(si, 6)}" aria-label="${api.esc(g.county + " " + unit + ", " + g.rows.length + " properties")}">
      <div class="xt-story-head xt-glass">
        <svg class="xt-story-contour" viewBox="0 0 400 160" preserveAspectRatio="none" aria-hidden="true">
          <path class="xt-draw" pathLength="1" d="M-10 130 C 80 90, 160 150, 260 100 S 380 40, 420 70"/>
          <path class="xt-draw" pathLength="1" d="M-10 100 C 90 60, 170 120, 270 70 S 380 10, 420 40" style="--dl:120ms"/>
          <path class="xt-draw" pathLength="1" d="M-10 70 C 100 30, 180 90, 280 40 S 380 -10, 420 10" style="--dl:240ms"/>
        </svg>
        <span class="xt-flag" aria-hidden="true"><i class="pole"></i><i class="pf"></i><i class="base"></i></span>
        <div class="xt-story-k">${api.esc(unit)} story${st ? ` · ${api.esc(st)}` : ""}</div>
        <h3 class="xt-story-t">${api.esc(g.county)} ${api.esc(unit)}</h3>
        <div class="xt-story-cnt"><span class="xt-story-n">${n(g.rows.length)}</span><span class="xt-story-l">${g.rows.length === 1 ? "property" : "properties"} on the source's list${shown.length < g.rows.length ? ` · ${n(shown.length)} drawn` : ""}</span></div>
      </div>
      <div class="xt-rail" data-xt-keep="rail-${api.esc(g.county)}" role="list">${cards}${more}</div>
    </section>`;
  }).join("");
  const moreStories = groups.length > storyCount
    ? `<button type="button" class="xt-more" data-xt="more-stories">Show ${n(Math.min(STORY_PAGE, groups.length - storyCount))} more ${api.esc(unit === "Parish" ? "parishes" : "counties")} · ${n(groups.length - storyCount)} left</button>` : "";

  return `<div class="xp-terrain xt-laft${enter ? " xt-enter" : ""}" data-ledger="laft">
    <div class="xt-grain" aria-hidden="true"></div>
    ${heads(api, "laft", `${n(rows.length)} ${rows.length === 1 ? "property" : "properties"} across ${n(groups.length)} ${api.esc(groups.length === 1 ? unit.toLowerCase() : (unit === "Parish" ? "parishes" : "counties"))}`,
      "Each story is a place. Swipe its cards; each card lays out how to acquire it as a trail - verified steps only.")}
    <nav class="xt-chips" data-xt-keep="chips" aria-label="Jump to a ${api.esc(unit.toLowerCase())}">${chips}</nav>
    <div class="xt-stories">${stories}</div>
    ${moreStories}
  </div>`;
}

function availableCard(p, api, i) {
  const pf = api.previewFacts(p);
  const amt = api.amountShort(p);
  let note = "";
  try { note = api.amountInfo(p).note || ""; } catch {}
  const visual = api.propertyVisual(p, "prop-card-photo xt-visual");
  return `<article class="xt-acard" role="listitem" data-xt="acard" data-pid="${api.esc(p.id)}" data-xt-ping style="--r:${Math.min(i, 8)}">
    <div class="xt-acard-vis">${visual}</div>
    <div class="xt-acard-body">
      <div class="xt-lot-k">${api.cardKickerHtml(p)}</div>
      <h4 class="xt-lot-t">${titleHtml(p, api)}</h4>
      <div class="xt-ids">${idRow(p, api)}</div>
      <div class="xt-figs">
        <div class="xt-fig xt-fig-main"><span class="xt-lbl">${api.esc(amt.label)}</span><span class="xt-num${amt.state === "not_published" ? " np" : ""}">${api.esc(amt.text)}</span></div>
        <div class="xt-fig"><span class="xt-lbl">${api.esc(pf.valueLabel || "County value")}</span><span class="xt-num xt-num-s${pf.value ? "" : " np"}">${api.esc(pf.value || "Not published")}</span></div>
      </div>
      ${note ? `<p class="xt-amt-note">${api.esc(note)}</p>` : ""}
      ${trailHtml(p, api)}
      <div class="xt-actions">${openBtn(p, api, "xt-btn-primary xt-sage")}${watchBtn(p, api)}</div>
    </div>
  </article>`;
}

function trailHtml(p, api) {
  const a = api.acquisitionOf(p) || { verified: false, label: "Not yet verified", steps: [] };
  if (!a.verified) {
    const none = a.mode === "none";
    return `<div class="xt-trail unverified" aria-label="How to acquire: ${api.esc(none ? "no purchase path stated by the source" : "not yet verified")}">
      <div class="xt-trail-k">How to acquire</div>
      <ol>
        <li class="wp done"><span class="wp-n">1</span><span class="wp-t">On the source's list</span></li>
        <li class="wp q"><span class="wp-n">?</span><span class="wp-t">${api.esc(none ? "No purchase path (stated by the source)" : "Not yet verified")}</span></li>
      </ol>
    </div>`;
  }
  const steps = (a.steps || []).filter(Boolean);
  const nodes = [];
  if (steps.length) {
    steps.slice(0, 4).forEach((s, i) => nodes.push(`<li class="wp"><span class="wp-n">${i + 1}</span><span class="wp-t">${api.esc(s)}</span></li>`));
    if (steps.length > 4) nodes.push(`<li class="wp more"><span class="wp-n">+${steps.length - 4}</span><span class="wp-t">more step${steps.length - 4 === 1 ? "" : "s"} on the record</span></li>`);
  } else {
    nodes.push(`<li class="wp"><span class="wp-n">1</span><span class="wp-t">${api.esc(a.label || "")}${a.typeLabel ? ` · ${api.esc(a.typeLabel)}` : ""}</span></li>`);
  }
  if (a.office) nodes.push(`<li class="wp office"><span class="wp-n" aria-hidden="true">⚑</span><span class="wp-t"><b>Office</b> ${api.esc(a.office)}</span></li>`);
  const obs = a.observedOn && /^\d{4}-\d{2}-\d{2}/.test(String(a.observedOn)) ? String(a.observedOn).slice(0, 10) : "";
  let obsText = "";
  if (obs) { try { obsText = api.fmtDateLong(obs); } catch { obsText = obs; } }
  return `<div class="xt-trail verified">
    <div class="xt-trail-k">How to acquire · <span>${api.esc(a.label || "")}</span></div>
    <ol>${nodes.join("")}</ol>
    <div class="xt-trail-f">${a.scope === "property" ? "Published for this parcel" : "County process, not an approval for this parcel"}${obsText ? ` · last verified ${api.esc(obsText)}` : ""}</div>
  </div>`;
}

// ---------- LIENS: strata ----------
function liensView(rows, api, enter) {
  const C = S.certificate;
  const groups = new Map();
  for (const p of rows) {
    let key, label, title, sort;
    if (isNum(p.tax_year)) { key = "t" + p.tax_year; title = String(p.tax_year); label = "Tax year"; sort = Number(p.tax_year); }
    else if (/^\d{4}/.test(String(p.issued_date || ""))) { const y = String(p.issued_date).slice(0, 4); key = "i" + y; title = y; label = "Issued (tax year not published)"; sort = Number(y) - 0.5; }
    else { key = "none"; title = "Year not published"; label = "Neither tax year nor issue date published"; sort = -Infinity; }
    let g = groups.get(key);
    if (!g) { g = { key, title, label, sort, rows: [], counties: new Set() }; groups.set(key, g); }
    g.rows.push(p); g.counties.add(p.county);
  }
  const bands = [...groups.values()].sort((a, b) => b.sort - a.sort);
  if (!C.inited && bands.length) { C.open.add(bands[0].key); C.inited = true; }
  const justOpened = C.justOpened; C.justOpened = null;
  const unit = api.unitWord ? api.unitWord() : "County";

  const html = bands.map((b, bi) => {
    const open = C.open.has(b.key);
    const cs = [...b.counties].filter(Boolean);
    const countiesTxt = cs.length <= 3 ? cs.join(", ") : `${cs.slice(0, 2).join(", ")} and ${cs.length - 2} more`;
    let body = "";
    if (open) {
      const lim = C.limit[b.key] || TAG_PAGE;
      const shown = b.rows.slice(0, lim);
      shown.forEach(p => BY_ID.set(String(p.id), p));
      const tags = shown.map((p, i) => tagHtml(p, api, i)).join("");
      const left = b.rows.length - shown.length;
      body = `<div class="xt-band-in${justOpened === b.key ? " xt-unclip" : ""}">
        <div class="xt-tagrow" data-xt-keep="tags-${api.esc(b.key)}">${tags}</div>
        ${left > 0 ? `<button type="button" class="xt-more xt-more-plum" data-xt="more-band" data-band="${api.esc(b.key)}">Show ${n(Math.min(TAG_PAGE, left))} more · ${n(left)} left in this layer</button>` : ""}
        <p class="xt-band-hint">Tap a tag to turn it over to the facts the source published.</p>
      </div>`;
    }
    const sil = Math.min(b.rows.length, 4);
    return `<section class="xt-band${open ? " open" : ""}" style="--d:${bi};--rd:${Math.min(bi, 8) * 70}ms" aria-label="${api.esc(b.title + ", " + b.rows.length + " certificates")}" data-xt-ping>
      <svg class="xt-wave" viewBox="0 0 400 16" preserveAspectRatio="none" aria-hidden="true"><path class="xt-draw" pathLength="1" d="M0 9 C 40 2, 80 14, 130 8 S 220 1, 270 8 S 360 15, 400 6" style="--dl:${200 + Math.min(bi, 8) * 70}ms"/></svg>
      <button type="button" class="xt-band-hd" data-xt="band" data-band="${api.esc(b.key)}" aria-expanded="${open}">
        <span class="xt-band-txt"><span class="xt-yr${b.key === "none" ? " ital" : ""}">${api.esc(b.title)}</span>
          <span class="xt-band-lbl">${api.esc(b.label)} · ${n(b.rows.length)} certificate${b.rows.length === 1 ? "" : "s"}${countiesTxt ? ` · ${api.esc(countiesTxt)}` : ""}</span></span>
        <span class="xt-sil" aria-hidden="true">${"<i></i>".repeat(sil)}<span class="xt-chev">⌄</span></span>
      </button>
      ${body}
    </section>`;
  }).join("");

  return `<div class="xp-terrain xt-liens${enter ? " xt-enter" : ""}" data-ledger="certificate">
    <div class="xt-grain" aria-hidden="true"></div>
    ${heads(api, "certificate", `${n(rows.length)} certificate${rows.length === 1 ? "" : "s"} in ${n(bands.length)} layer${bands.length === 1 ? "" : "s"}`,
      `A certificate is a lien, not land - so no map here. Layers are tax years, newest on top; ${api.esc(unit.toLowerCase())} is on each tag.`)}
    <div class="xt-strata">${html}</div>
    <section class="xt-bedrock" aria-label="About these records">
      <div class="xt-ruleline"></div>
      <span class="xt-lbl">Bedrock · what this ledger never shows</span>
      <p>No accrued interest, value, returns or computed expiry. An expiry appears only when the source publishes it. A certificate that leaves a list is never called sold: redeemed, assigned or expired is shown only when the source says so.</p>
    </section>
  </div>`;
}

function tagHtml(p, api, i) {
  const pf = api.previewFacts(p);
  const amt = api.amountShort(p);
  const flipped = S.certificate.flipped.has(String(p.id));
  const rot = ((i * 37) % 7 - 3) * 0.6;
  let expiry = "Expiry not published";
  if (p.expiration_date && /^\d{4}-\d{2}-\d{2}/.test(String(p.expiration_date))) {
    try { expiry = "Expires " + api.fmtDateLong(String(p.expiration_date).slice(0, 10)).replace(/^[A-Za-z]+, /, ""); } catch { expiry = "Expires " + String(p.expiration_date).slice(0, 10); }
  }
  const certNo = p.certificate_no ? String(p.certificate_no) : "";
  // The exact published figure, as the classic certificate card shows it
  // (fmtMoney); amountShort() rounds to whole dollars, which a lien amount
  // must not be. Its label stays amountShort()'s.
  const amtText = pf.bid || amt.text;
  const facts = [[pf.parcelLabel || "Account", pf.parcel || "Not published"]]
    .concat(Array.isArray(pf.more) ? pf.more : []);
  const srcName = pf.source || api.sourceNameFor(p);
  if (srcName) facts.push(["Source", srcName]); // an unnamed source is not "not published" by the source
  facts.push(["Status", api.officialStatusText(p)]);
  const back = facts.map(([k, v]) => `<span class="xt-bk-row"><span class="xt-lbl">${api.esc(k)}</span><span class="xt-bk-v">${api.esc(v)}</span></span>`).join("");
  return `<div class="xt-tag${flipped ? " flipped" : ""}" style="--rot:${rot.toFixed(1)}deg;--t:${Math.min(i, 10) * 45}ms">
    <button type="button" class="xt-tag-flip" data-xt="flip" data-pid="${api.esc(p.id)}" aria-pressed="${flipped}" data-label="${api.esc("Certificate " + (certNo || "number not published") + ", " + p.county + ", " + amt.label + " " + amtText + ". ")}" aria-label="${api.esc("Certificate " + (certNo || "number not published") + ", " + p.county + ", " + amt.label + " " + amtText + ". " + (flipped ? "Showing published facts; tap to turn back" : "Tap to show published facts"))}">
      <svg class="xt-string" viewBox="0 0 20 34" aria-hidden="true"><path d="M10 0 C 4 10, 16 18, 10 30" fill="none" stroke="#B9A7BA" stroke-width="1.4"/></svg>
      <span class="xt-tag-inner">
        <span class="xt-face front">
          <span class="xt-hole"></span>
          <span class="xt-lbl">Cert</span>
          <span class="xt-tag-id${certNo ? "" : " np"}">${api.esc(certNo || "Not published")}</span>
          <span class="xt-lbl xt-mt">${api.esc(amt.label)}</span>
          <span class="xt-tag-amt${amt.state === "not_published" ? " np" : ""}">${api.esc(amtText)}</span>
          <span class="xt-tag-county">${api.esc(p.county)}</span>
          <span class="xt-tag-exp${p.expiration_date ? "" : " np"}">${api.esc(expiry)}</span>
        </span>
        <span class="xt-face back"><span class="xt-slip">Published facts</span>${back}</span>
      </span>
    </button>
    <div class="xt-tag-actions">${openBtn(p, api, "xt-btn-primary xt-plum xt-btn-s")}${watchBtn(p, api)}</div>
  </div>`;
}

// ---------- interaction ----------
function ping(host, e) {
  if (reduced() || !host || !e || typeof e.clientX !== "number") return;
  const r = host.getBoundingClientRect();
  const s = document.createElement("span");
  s.className = "xt-ping";
  s.style.left = (e.clientX - r.left) + "px";
  s.style.top = (e.clientY - r.top) + "px";
  s.innerHTML = "<i></i><i></i>";
  host.appendChild(s);
  setTimeout(() => s.remove(), 700);
}

function selectLot(stage, pid, fromPin) {
  S.auction.sel = pid;
  stage.querySelectorAll(".xt-pin.sel,.xt-lot.sel").forEach(el => el.classList.remove("sel"));
  const esc = window.CSS && CSS.escape ? CSS.escape(pid) : pid.replace(/"/g, '\\"');
  const pin = stage.querySelector(`.xt-pin[data-pid="${esc}"]`);
  const card = stage.querySelector(`.xt-lot[data-pid="${esc}"]`);
  if (pin) pin.classList.add("sel");
  if (card) {
    card.classList.add("sel");
    if (fromPin) card.scrollIntoView({ behavior: reduced() ? "auto" : "smooth", block: "nearest" });
  }
}

function openRecord(stage, pid) {
  const p = BY_ID.get(pid);
  const api = (LAST && LAST.api) || (window.__tdwExperience && window.__tdwExperience.api);
  if (!p || !api) return;
  const esc = window.CSS && CSS.escape ? CSS.escape(pid) : pid;
  const card = stage.querySelector(`[data-pid="${esc}"].xt-lot, [data-pid="${esc}"].xt-acard`) ||
    (stage.querySelector(`.xt-tag-flip[data-pid="${esc}"]`) || {}).parentElement;
  if (card && card.classList && !reduced()) {
    card.classList.add("xt-opening");
    setTimeout(() => { card.classList.remove("xt-opening"); api.openDetail(p); }, 260);
  } else api.openDetail(p);
}

function bind(stage) {
  if (BOUND) return;
  BOUND = true;
  stage.addEventListener("pointerdown", e => {
    if (stage.dataset.xp !== NAME) return;
    const host = e.target.closest("[data-xt-ping]");
    if (host && stage.contains(host)) ping(host, e);
  });
  stage.addEventListener("click", e => {
    if (stage.dataset.xp !== NAME) return;
    const t = e.target.closest("[data-xt]");
    if (!t || !stage.contains(t)) return;
    const kind = t.dataset.xt;
    // A click on an inner button / link of a card is that control's, not the card's.
    if ((kind === "lot" || kind === "acard") && e.target.closest("button, a")) return;
    const pid = t.dataset.pid ? String(t.dataset.pid) : "";
    if (kind === "day") {
      if (S.auction.day === t.dataset.day) return;
      S.auction.day = t.dataset.day; S.auction.sel = null;
      draw(LAST, { centerDay: false });
    } else if (kind === "pin") {
      selectLot(stage, pid, true);
    } else if (kind === "lot") {
      selectLot(stage, pid, false);
    } else if (kind === "open") {
      openRecord(stage, pid);
    } else if (kind === "acard") {
      // whole-card tap is decoration only; the Open record button opens it
    } else if (kind === "more-day") {
      S.auction.limit[S.auction.day] = (S.auction.limit[S.auction.day] || PAGE) + PAGE;
      draw(LAST);
    } else if (kind === "jump") {
      const i = Number(t.dataset.story);
      const go = () => {
        const el = document.getElementById("xtStory" + i);
        if (el) el.scrollIntoView({ behavior: reduced() ? "auto" : "smooth", block: "start" });
      };
      if (i >= S.laft.storyLimit) { S.laft.storyLimit = i + 1; draw(LAST); requestAnimationFrame(go); } else go();
    } else if (kind === "more-story") {
      const c = t.dataset.county;
      S.laft.cards[c] = (S.laft.cards[c] || STORY_CARDS) + STORY_MORE;
      draw(LAST);
    } else if (kind === "more-stories") {
      S.laft.storyLimit += STORY_PAGE;
      draw(LAST);
    } else if (kind === "band") {
      const k = t.dataset.band;
      if (S.certificate.open.has(k)) S.certificate.open.delete(k);
      else { S.certificate.open.add(k); S.certificate.justOpened = k; }
      draw(LAST);
    } else if (kind === "more-band") {
      const k = t.dataset.band;
      S.certificate.limit[k] = (S.certificate.limit[k] || TAG_PAGE) + TAG_PAGE;
      draw(LAST);
    } else if (kind === "flip") {
      const tag = t.closest(".xt-tag");
      const on = !S.certificate.flipped.has(pid);
      if (on) S.certificate.flipped.add(pid); else S.certificate.flipped.delete(pid);
      if (tag) tag.classList.toggle("flipped", on);
      t.setAttribute("aria-pressed", String(on));
      if (t.dataset.label) t.setAttribute("aria-label", t.dataset.label + (on ? "Showing published facts; tap to turn back" : "Tap to show published facts"));
    }
  });
}

// ---------- wiring ----------
window.addEventListener("tdw:rendered", e => {
  if (!active()) { teardown(); return; }
  // Drop flipped / selected ids that are no longer in the rows.
  const rows = e.detail && Array.isArray(e.detail.rows) ? e.detail.rows : null;
  if (rows && (S.certificate.flipped.size || S.auction.sel)) {
    const ids = new Set(rows.map(r => String(r.id)));
    S.certificate.flipped.forEach(id => { if (!ids.has(id)) S.certificate.flipped.delete(id); });
    if (S.auction.sel && !ids.has(S.auction.sel)) S.auction.sel = null;
  }
  draw(e.detail);
});
window.addEventListener("tdw:experience", () => {
  if (!active()) { teardown(); return; }
  S.scene = "";
  draw(window.__tdwLastRender);
});
if (active() && window.__tdwLastRender) draw(window.__tdwLastRender);
