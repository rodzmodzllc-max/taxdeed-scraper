// Merged List experience - 2026-10-25 (owner's brief: "merge both versions").
//
// Tactile's physical objects and motion, Terrain's sale-day calendar, and
// essentials first:
//   AUCTIONS   Terrain's sale-day scrubber across the top (sticky; the next
//              45 days, rings sized by the lots still on the county's sale
//              list that day; earlier / later / undated at the ends). A day
//              lays its lots out as Tactile placards that flip: the face is
//              the essentials (image, stamp, address or lot, county, the
//              bid under its own label, the sale-site link, Watchlist); the
//              back carries every other fact the record has. Lots no longer
//              on the county's current sale list sit apart at the end of the
//              day and are never counted as upcoming.
//   AVAILABLE  deed folders: the face is the essentials; opening one swings
//              the cover on its hinge and slides out "How to acquire" (the
//              verified process, contact, documents) and every fact on file.
//   LIENS      certificate slips bundled by tax year (or county); the newest
//              bundle is fanned out, a slip lifts into a tray of its facts,
//              and each slip's stub is its own Watchlist button.
//
// Stamps are pressed onto an object only from what the record or a verified
// source says: "Verified path" (acquisitionOf(p).verified), "Sale <date>"
// (a scheduled sale), Sold / Redeemed / Canceled / ... (auctionOutcomeState
// verified only), Redeemed / Expired / Assigned for a certificate (its
// source status), "No longer listed" for a row that left its list, "Dated
// list" for a dated list. A stamp presses in once per object, when it first
// comes into view.
//
// Contract (app.js "Look switch"): draws only while
// window.__tdwExperience.name === "merged", from the tdw:rendered payload
// (the List's own filtered, publication-gated rows plus `api`, the card's
// own label / display helpers). Every figure sits under the label the api
// gives; nothing is scored, estimated or computed. Opening a record always
// goes through api.openDetail(p). Watchlist buttons are data-action="bidlist"
// and are handled by app.js's document-level action handler.
//
// No imports; no network requests of its own.

const NAME = "merged";
const PAGE = 48;            // objects built at a time; "Show more" adds PAGE more
const FAN = 5;              // slips fanned out at once
const WINDOW_DAYS = 45;     // sale days on the scrubber
const OPEN_DELAY = 260;     // ms of opening animation before the property page

const S = {
  ledger: null,             // ledger last drawn: a change replays the entrance
  limit: { auction: PAGE, laft: PAGE, certificate: PAGE },
  flipped: new Set(),
  day: null,
  dayAnim: false,           // one-shot animation after the user picks a day
  folder: null,
  seg: "all",
  bundleBy: "year",
  fan: undefined,           // undefined = not chosen yet: the newest bundle opens
  fanStart: 0,
  slip: null,
  pressed: null,
  stamped: new Set(),       // "<id>|<stamp>" already pressed in
  folderShown: null,        // the open folder whose opening has already played
  dealt: null,              // the bundle whose fan-out has already played
  trayShown: null,          // the slip whose tray has already risen
  last: null
};

const ACQ_CACHE = new WeakMap();
let STAMP_IO = null;

const isActive = () => !!(window.__tdwExperience && window.__tdwExperience.name === NAME);
const reduced = () => { try { return matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; } };
const stageEl = () => document.getElementById("xpStage");
const safeUrl = u => (u && /^https:\/\//i.test(String(u).trim()) ? String(u).trim() : "");
const idOf = p => String(p.id);
const n = x => Number(x).toLocaleString("en-US");
const keyEsc = s => String(s).replace(/["\\]/g, "");

function apiOf(detail) {
  return (detail && detail.api) || (window.__tdwExperience && window.__tdwExperience.api) || null;
}

// ---------------------------------------------------------------- lifecycle

function deactivate() {
  const stage = stageEl();
  if (stage && stage.dataset.xp === NAME) { stage.innerHTML = ""; delete stage.dataset.xp; }
  if (document.documentElement.dataset.experienceReady === NAME) delete document.documentElement.dataset.experienceReady;
  if (STAMP_IO) { STAMP_IO.disconnect(); STAMP_IO = null; }
  S.ledger = null;
}

function draw(detail) {
  if (!isActive()) { deactivate(); return; }
  const stage = stageEl();
  const api = apiOf(detail);
  if (!stage || !api || !detail) return;
  S.last = detail;
  const rows = Array.isArray(detail.rows) ? detail.rows : [];
  const ledger = detail.ledger === "laft" || detail.ledger === "certificate" ? detail.ledger : "auction";
  if (!rows.length) {
    // The classic list says WHICH zero this is (loading, withheld, no
    // inventory, failed read); the stage stays empty and #main shows.
    if (stage.dataset.xp === NAME) { stage.innerHTML = ""; delete stage.dataset.xp; }
    if (document.documentElement.dataset.experienceReady === NAME) delete document.documentElement.dataset.experienceReady;
    return;
  }
  // The entrance plays once per ledger: never again while a big state
  // streams in more rows, and never on a local tap.
  const enter = ledger !== S.ledger;
  if (enter) {
    S.ledger = ledger;
    S.limit[ledger] = PAGE;
    S.flipped.clear();
    S.folder = null;
  }

  const ae = document.activeElement;
  const focusKey = ae && stage.contains(ae) ? ae.getAttribute("data-k")
    : (!ae || ae === document.body) ? S.pressed : null;
  S.pressed = null;

  const keep = {};
  stage.querySelectorAll("[data-keep]").forEach(el => { keep[el.dataset.keep] = el.scrollLeft; });

  let html;
  if (ledger === "auction") html = auctionsHtml(rows, api);
  else if (ledger === "laft") html = availableHtml(rows, api);
  else html = liensHtml(rows, api);

  stage.dataset.xp = NAME;
  stage.innerHTML = `<div class="xpm xpm-${ledger}${enter ? " xpm-enter" : ""}" data-ledger="${ledger}">${html}</div>`;
  stage.querySelectorAll("[data-keep]").forEach(el => { if (keep[el.dataset.keep] !== undefined) el.scrollLeft = keep[el.dataset.keep]; });
  if (ledger === "auction" && enter) centerDay(stage);
  try { api.hydrateVisuals(stage); } catch {}
  document.documentElement.dataset.experienceReady = NAME;
  stickyTop(stage);
  watchStamps(stage);
  S.dayAnim = false;

  if (focusKey) {
    const el = stage.querySelector(`[data-k="${keyEsc(focusKey)}"]`);
    if (el) { try { el.focus({ preventScroll: true }); } catch {} }
  }
}

function redraw() { if (S.last) draw(S.last); }

// The sale-day rail sticks under whatever header the page keeps on screen.
function stickyTop(stage) {
  let top = 0;
  document.querySelectorAll("body > header, .app-header, .topbar, .masthead, #navRail, .app-shell > header").forEach(el => {
    if (stage.contains(el)) return;
    const cs = getComputedStyle(el);
    if (cs.position !== "sticky" && cs.position !== "fixed") return;
    const r = el.getBoundingClientRect();
    if (r.height > 0 && r.height < 220 && r.top <= 1) top = Math.max(top, Math.round(r.bottom));
  });
  stage.style.setProperty("--xpm-top", top + "px");
}

// ------------------------------------------------------------------ stamps

const SHORT_DATE = d => new Date(d + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" });
const OUTCOME_STAMPS = {
  sold: "Sold", redeemed: "Redeemed", cancelled: "Cancelled", withdrawn: "Withdrawn",
  struck_off: "Unsold", no_sale: "No sale", future_sale: "Held for future sale"
};

function acqOf(p, api) {
  let a = ACQ_CACHE.get(p);
  if (!a) { a = api.acquisitionOf(p) || { verified: false, mode: null, label: "Not yet verified", steps: [], channels: [] }; ACQ_CACHE.set(p, a); }
  return a;
}

// The one status a record's own data supports, or null - the same decision
// the classic card stamps with (app.js cardStamp), so the two looks never
// disagree. Nothing is inferred from a passed date, a missing row or a figure.
const STAMP_KIND = {
  "stamp-verified": "verified", "stamp-sold": "sold", "stamp-redeemed": "redeemed",
  "stamp-soon": "soon", "stamp-date": "sale", "stamp-closed": "closed", "stamp-muted": "muted"
};
function stampOf(p, api) {
  if (typeof api.cardStamp === "function") {
    const st = api.cardStamp(p);
    return st ? { k: STAMP_KIND[st.cls] || "muted", key: st.key, t: st.label, title: st.title || "" } : null;
  }
  // Fallback for an app.js without cardStamp: the same rules, narrower.
  if (p.source === "auction") {
    const st = api.auctionOutcomeState(p);
    if (st && st.verified && OUTCOME_STAMPS[st.key]) return { k: st.key === "sold" ? "sold" : "closed", key: "result-" + st.key, t: OUTCOME_STAMPS[st.key] };
  }
  if (api.isGone(p)) return { k: "closed", key: "gone", t: "No longer listed" };
  if (p.source === "certificate") {
    const s = p.inventory_status;
    if (s === "certificate_redeemed") return { k: "redeemed", key: "redeemed", t: "Redeemed" };
    if (s === "certificate_expired") return { k: "closed", key: "expired", t: "Expired" };
    if (s === "certificate_assigned") return { k: "closed", key: "assigned", t: "Assigned" };
    return null;
  }
  if (p.source === "auction") {
    if (api.offCurrentSaleList(p)) return { k: "closed", key: "offlist", t: "Not on current list" };
    const d = saleDay(p);
    if (d && d >= todayIso()) return { k: "sale", key: "scheduled", t: "Sale " + SHORT_DATE(d) };
    return null;
  }
  if (api.isDatedList(p)) return { k: "muted", key: "dated", t: "Dated list" };
  if (acqOf(p, api).verified) return { k: "verified", key: "verified", t: "Verified path" };
  return null;
}

function stampHtml(p, api, extra) {
  const s = stampOf(p, api);
  if (!s) return "";
  const key = idOf(p) + "|" + s.key;
  const fresh = !S.stamped.has(key) && !reduced() && "IntersectionObserver" in window;
  const icon = s.k === "verified" ? checkIcon(11) : "";
  return `<span class="xpm-stamp k-${s.k}${extra ? " " + extra : ""}${fresh ? " pending" : ""}" data-stamp="${api.esc(key)}">${icon}${api.esc(s.t)}</span>`;
}

// Press each new stamp once, the first time it is on screen.
function watchStamps(stage) {
  if (STAMP_IO) { STAMP_IO.disconnect(); STAMP_IO = null; }
  const pend = stage.querySelectorAll(".xpm-stamp.pending");
  if (!pend.length) return;
  STAMP_IO = new IntersectionObserver(entries => {
    entries.forEach(en => {
      if (!en.isIntersecting) return;
      const el = en.target;
      STAMP_IO.unobserve(el);
      S.stamped.add(el.dataset.stamp);
      el.classList.remove("pending");
      el.classList.add("press");
    });
  }, { threshold: 0.6 });
  pend.forEach(el => STAMP_IO.observe(el));
}

// --------------------------------------------------------------- shared bits

function watchBtn(p, api, cls, short) {
  const on = api.isWatched(p.id);
  return `<button type="button" class="${cls}${on ? " on" : ""}" data-action="bidlist" data-pid="${api.esc(p.id)}" data-k="w-${api.esc(p.id)}" aria-pressed="${on}" aria-label="${on ? "On your watchlist - tap to remove" : "Add to watchlist"}">` +
    `<svg width="18" height="18" viewBox="0 0 24 24" fill="${on ? "currentColor" : "none"}" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M6 3h12v18l-6-4.5L6 21z"/></svg>` +
    (short ? "" : `<span>${on ? "Watching" : "Watch"}</span>`) + `</button>`;
}

function missing(text, api) { return `<span class="xpm-missing">${api.esc(text)}</span>`; }

function titleHtml(p, api) {
  const street = api.realAddress(p);
  return street ? { html: api.esc(street), parcel: false } : { html: api.lotTitle(p), parcel: true };   // lotTitle is already escaped
}

function linkHtml(link, api, cls, k) {
  const href = link ? safeUrl(link.href) : "";
  if (!href) return "";
  return `<a class="${cls}" href="${api.esc(href)}" target="_blank" rel="noopener"${k ? ` data-k="${api.esc(k)}"` : ""}${link.note ? ` title="${api.esc(link.note)}"` : ""}><span>${api.esc(link.label)}</span>` +
    `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 17L17 7M9 7h8v8"/></svg></a>`;
}

function moreButton(ledger, shown, total, what) {
  if (shown >= total) return "";
  const next = Math.min(PAGE, total - shown);
  return `<div class="xpm-more-wrap"><button type="button" class="xpm-more" data-xa="more" data-ledger="${ledger}" data-k="more-${ledger}">Show ${next} more ${what || ""}<span class="xpm-mono">${n(shown)} of ${n(total)}</span></button></div>`;
}

// Administrators also see records from a source not yet approved for
// customers; previewFacts names that, and the face repeats it.
function reviewNote(p, api) {
  const pf = api.previewFacts(p);
  const r = (pf.more || []).find(x => x[0] === "Source" && /review/i.test(String(x[1])));
  return r ? `<span class="nopath review">${api.esc("Source " + String(r[1]).charAt(0).toLowerCase() + String(r[1]).slice(1))}</span>` : "";
}

function whereText(p, api) { return `${p.county} ${api.unitWord()}, ${api.stateCode()}`; }

function factRows(rows, api) {
  return rows.map(r => `<div class="fact"><span class="k">${api.esc(r[0])}</span><span class="v">${api.esc(r[1])}</span></div>`).join("");
}

function checkIcon(size) {
  const s = size || 12;
  return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>`;
}
function flipIcon() {
  return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/></svg>`;
}

const todayIso = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
function daysBetween(iso) {
  const a = new Date(todayIso() + "T00:00:00"), b = new Date(iso + "T00:00:00");
  if (isNaN(b)) return null;
  return Math.round((b - a) / 86400000);
}

// ---------------------------------------------------------------- AUCTIONS

const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WK = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const WEEKDAY = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

function saleDay(p) { const d = p.sale_date ? String(p.sale_date).slice(0, 10) : ""; return /^\d{4}-\d{2}-\d{2}$/.test(d) ? d : ""; }
function dayDate(i) { const t = new Date(todayIso() + "T00:00:00"); t.setDate(t.getDate() + i); return t; }
function bucketOf(p) {
  const d = saleDay(p);
  if (!d) return "undated";
  const off = daysBetween(d);
  if (off === null) return "undated";
  if (off < 0) return "past";
  if (off >= WINDOW_DAYS) return "later";
  return "d" + off;
}
function urgency(i) { return i === 0 ? "u-today" : i <= 3 ? "u-near" : i <= 14 ? "u-mid" : "u-far"; }

function auctionsHtml(rows, api) {
  // Every bucket keeps its lots in two groups: still on the county's current
  // sale list (counted), and no longer on it (shown apart, never counted).
  const buckets = new Map();
  for (const p of rows) {
    const k = bucketOf(p);
    let b = buckets.get(k);
    if (!b) { b = { on: [], off: [], watched: 0 }; buckets.set(k, b); }
    (api.offCurrentSaleList(p) ? b.off : b.on).push(p);
    if (api.isWatched(p.id)) b.watched++;
  }
  if (!S.day || !buckets.has(S.day)) {
    let pick = null;
    for (let i = 0; i < WINDOW_DAYS && !pick; i++) { const b = buckets.get("d" + i); if (b && b.on.length) pick = "d" + i; }
    for (let i = 0; i < WINDOW_DAYS && !pick; i++) if (buckets.has("d" + i)) pick = "d" + i;
    S.day = pick || ["later", "undated", "past"].find(k => buckets.has(k));
    S.limit.auction = PAGE;
  }
  let max = 1, inWindow = 0, offWindow = 0;
  buckets.forEach((b, k) => { if (k.charAt(0) === "d") { max = Math.max(max, b.on.length); inWindow += b.on.length; offWindow += b.off.length; } });

  const cols = [];
  const endCol = (k, label, sub) => {
    const b = buckets.get(k);
    const c = b ? b.on.length + b.off.length : 0;
    const on = S.day === k;
    if (!c) return "";
    return `<button type="button" class="col end${on ? " on" : ""}${c ? "" : " empty"}" data-xa="day" data-day="${k}" data-k="day-${k}" aria-pressed="${on}"${c ? "" : " disabled"} aria-label="${api.esc(label + ", " + c + (c === 1 ? " lot" : " lots"))}">` +
      `<span class="end-n xpm-mono">${n(c)}</span><span class="wk">${api.esc(label)}</span><span class="end-sub">${api.esc(sub)}</span>${b && b.watched ? `<i class="wdot" aria-hidden="true"></i>` : ""}</button>`;
  };
  cols.push(endCol("past", "Earlier", "passed dates"));
  for (let i = 0; i < WINDOW_DAYS; i++) {
    const dt = dayDate(i), k = "d" + i, b = buckets.get(k), on = S.day === k;
    const c = b ? b.on.length : 0, off = b ? b.off.length : 0;
    const size = c ? Math.round(12 + 20 * Math.sqrt(c / max)) : 0;
    const monthStart = dt.getDate() === 1 || i === 0;
    const label = `${MON[dt.getMonth()]} ${dt.getDate()}${i === 0 ? ", today" : ""}, ` +
      (c ? `${c} ${c === 1 ? "lot" : "lots"} on the sale list` : "no lots on the sale list") + (off ? `, ${off} no longer on it` : "");
    cols.push(`<button type="button" class="col ${urgency(i)}${on ? " on" : ""}${c ? " has" : ""}${off && !c ? " offonly" : ""}" data-xa="day" data-day="${k}" data-k="day-${k}" aria-pressed="${on}"${c || off ? "" : " disabled"} aria-label="${api.esc(label)}" style="--i:${i}">` +
      (monthStart ? `<span class="month">${i === 0 ? "Today" : MON[dt.getMonth()]}</span>` : "") +
      (c ? `<span class="ring" style="--s:${size}px"><b class="xpm-mono">${c}</b></span>` : off ? `<span class="ring hollow" style="--s:14px"></span>` : `<span class="tick"></span>`) +
      `<span class="num xpm-mono">${dt.getDate()}</span><span class="wk">${WK[dt.getDay()]}</span>${b && b.watched ? `<i class="wdot" aria-hidden="true"></i>` : ""}</button>`);
  }
  cols.push(endCol("later", "Later", "after 45 days"));
  cols.push(endCol("undated", "No date", "not scheduled"));

  const b = buckets.get(S.day) || { on: [], off: [] };
  let big, sub;
  if (S.day && S.day.charAt(0) === "d") {
    const i = Number(S.day.slice(1)), dt = dayDate(i);
    big = `${WEEKDAY[dt.getDay()]}, ${MON[dt.getMonth()]} ${dt.getDate()}`;
    sub = i === 0 ? "Sale day is today" : i === 1 ? "Tomorrow" : `In ${i} days`;
  } else if (S.day === "past") { big = "Earlier"; sub = "Sale dates that have passed - a result shows only when the source published one"; }
  else if (S.day === "later") { big = "Later"; sub = "Sales more than 45 days out"; }
  else { big = "No sale date"; sub = "Sale date not scheduled by the source"; }

  const lim = Math.min(S.limit.auction, b.on.length);
  const cards = b.on.slice(0, lim).map((p, i) => placardHtml(p, i, api)).join("");
  const offLim = Math.max(0, Math.min(S.limit.auction - lim, b.off.length));
  const offCards = b.off.slice(0, offLim).map((p, i) => placardHtml(p, lim + i, api)).join("");
  const total = b.on.length + b.off.length, shown = lim + offLim;

  return `<section class="xpm-scrub" aria-label="Sale days">
      <div class="scrub-top"><span class="xpm-caps scrub-k">Sale days · next 45</span><span class="scrub-total xpm-mono">${n(inWindow)} ${inWindow === 1 ? "lot" : "lots"} on sale lists${offWindow ? ` · ${n(offWindow)} no longer listed` : ""}</span></div>
      <div class="ruler" data-keep="ruler" role="group" aria-label="Pick a sale day">${cols.join("")}</div>
    </section>
    <div class="xpm-dayhead${S.dayAnim ? " swap" : ""}" aria-live="polite">
      <div class="dh-text"><h2 class="xpm-dm">${api.esc(big)}</h2><p class="xpm-small">${api.esc(sub)}</p></div>
      <div class="dh-count"><span class="xpm-mono">${n(b.on.length)}</span><span class="xpm-caps">${b.on.length === 1 ? "lot" : "lots"}</span></div>
    </div>
    <div class="xpm-grid xpm-plac-grid${S.dayAnim ? " day-enter" : ""}">${cards || (b.off.length ? "" : `<p class="xpm-note">No lots on this day.</p>`)}</div>
    ${b.off.length && offLim ? `<section class="xpm-offgroup" aria-label="No longer on the county's current sale list">
      <h3 class="xpm-caps">No longer on the county's current sale list · ${n(b.off.length)}</h3>
      <p class="xpm-small">These were scheduled for this day but were not on the county's latest sale list. No result was published, so none is claimed.</p>
      <div class="xpm-grid xpm-plac-grid">${offCards}</div></section>` : ""}
    ${moreButton("auction", shown, total, "lots")}`;
}

function placardHtml(p, i, api) {
  const id = idOf(p);
  const flipped = S.flipped.has(id);
  const t = titleHtml(p, api);
  const a = api.amountShort(p);
  const pf = api.previewFacts(p);
  const acq = acqOf(p, api);
  const link = pf.link && safeUrl(pf.link.href) ? pf.link : null;
  const hid = flipped ? ' tabindex="-1" aria-hidden="true"' : "";
  const backTab = flipped ? "" : ' tabindex="-1"';
  // The back: every fact the record carries, nothing sliced off.
  const facts = [];
  facts.push(["Status", api.officialStatusText(p)]);
  if (pf.parcel) facts.push([pf.parcelLabel, pf.parcel]);
  const caseText = api.caseIdentText(p);
  if (caseText) facts.push(["Case", caseText]);
  facts.push([pf.valueLabel || "County value", pf.value ? pf.value + " (county value, not a price)" : (api.dataGaps(p).includes("No county value on file") ? "No county value on file" : "Not published")]);
  for (const r of pf.more || []) if (r[0] !== "Legal") facts.push(r);
  facts.push(["Flood", pf.flood ? pf.flood.text : "Not checked"]);
  if (pf.source) facts.push(["Source", pf.source]);
  const legal = (pf.more || []).find(r => r[0] === "Legal");
  const gaps = api.dataGaps(p) || [];
  return `<article class="xpm-plac${flipped ? " flipped" : ""}" data-pid="${api.esc(id)}" style="--i:${Math.min(i, 16)}">
    <div class="flip">
      <div class="face front xpm-obj"${flipped ? ' aria-hidden="true"' : ""}>
        <span class="band" aria-hidden="true"></span>
        <button type="button" class="hit" data-xa="flip" data-pid="${api.esc(id)}" data-k="flip-${api.esc(id)}" aria-pressed="${flipped}"${hid}
          aria-label="${api.esc(`${api.realAddress(p) || "Parcel " + (api.parcelOf(p) || "not published")}, ${whereText(p, api)}. ${a.label}: ${a.text}. Flip for the facts on file.`)}">
          <span class="plate"><span class="plate-in">${api.propertyVisual(p, "prop-card-photo xpm-vis")}</span>${stampHtml(p, api)}</span>
          <span class="ctitle${t.parcel ? " parcel" : ""}">${t.html}</span>
          <span class="where">${api.esc(whereText(p, api))}${acq.verified ? `<span class="seal">${checkIcon(10)}Sale process verified</span>` : ""}</span>
          <span class="fig"><span class="xpm-caps">${api.esc(a.label)}</span>${a.state === "not_published" ? missing(a.text, api) : `<span class="fig-xl">${api.esc(a.text)}</span>`}</span>
          ${reviewNote(p, api)}
          <span class="flip-hint" aria-hidden="true">${flipIcon()}Facts</span>
        </button>
        <div class="acts">
          ${link ? linkHtml(link, api, "xpm-cta rust", "l-" + id).replace("<a ", flipped ? '<a tabindex="-1" ' : "<a ") : `<button type="button" class="xpm-cta rust" data-xa="open" data-pid="${api.esc(id)}" data-k="open-${api.esc(id)}"${hid}>Open record</button>`}
          ${watchBtn(p, api, "xpm-watch icon", true).replace("<button ", flipped ? '<button tabindex="-1" ' : "<button ")}
        </div>
      </div>
      <div class="face back xpm-obj"${flipped ? "" : ' aria-hidden="true"'}>
        <span class="band" aria-hidden="true"></span>
        <button type="button" class="back-head" data-xa="flip" data-pid="${api.esc(id)}" data-k="back-${api.esc(id)}"${backTab} aria-label="Flip back to the front">
          <span class="xpm-caps">Facts on file</span><span class="flip-hint static">${flipIcon()}Front</span></button>
        <div class="back-scroll">
          <div class="facts">${factRows(facts, api)}</div>
          ${legal ? `<p class="legal">${api.esc(legal[1])}</p>` : ""}
          ${gaps.length ? `<p class="gaps"><span class="xpm-caps">Not on file</span> ${api.esc(gaps.join(" · "))}</p>` : ""}
        </div>
        <div class="acts">
          <button type="button" class="xpm-cta ghost" data-xa="open" data-pid="${api.esc(id)}" data-k="bopen-${api.esc(id)}"${backTab}>Open full record</button>
          ${watchBtn(p, api, "xpm-watch icon", true).replace("<button ", flipped ? "<button " : '<button tabindex="-1" ').replace(`data-k="w-`, `data-k="bw-`)}
        </div>
      </div>
    </div>
  </article>`;
}

function centerDay(stage) {
  const ruler = stage.querySelector(".xpm-scrub .ruler");
  const on = ruler && ruler.querySelector(".col.on");
  if (!ruler || !on) return;
  requestAnimationFrame(() => { ruler.scrollLeft = Math.max(0, on.offsetLeft - ruler.clientWidth / 2 + on.offsetWidth / 2); });
}

// --------------------------------------------------------------- AVAILABLE

function availableHtml(rows, api) {
  let verified = 0;
  for (const p of rows) if (acqOf(p, api).verified) verified++;
  const unverified = rows.length - verified;
  if (!unverified) S.seg = "all";
  const list = S.seg === "all" ? rows : rows.filter(p => (S.seg === "verified") === acqOf(p, api).verified);
  const lim = Math.min(S.limit.laft, list.length);
  if (S.folder && !list.slice(0, lim).some(p => idOf(p) === S.folder)) S.folder = null;
  const folders = list.slice(0, lim).map((p, i) => folderHtml(p, i, api)).join("");
  // The switch exists only when this viewer can see records without a
  // verified path (an admin); for everyone else every record has one.
  const segs = [["all", "All"], ["verified", "Verified path"], ["unverified", "Not yet verified"]];
  const counts = { all: rows.length, verified, unverified };
  const seg = unverified ? `<div class="xpm-seg" role="group" aria-label="Acquisition path" style="--si:${segs.findIndex(s => s[0] === S.seg)}">
      <span class="seg-tile" aria-hidden="true"></span>
      ${segs.map(s => `<button type="button" class="seg-btn${S.seg === s[0] ? " on" : ""}" data-xa="seg" data-seg="${s[0]}" data-k="seg-${s[0]}" aria-pressed="${S.seg === s[0]}"${s[0] !== "all" && !counts[s[0]] ? " disabled" : ""}>${s[1]} <span class="n">${n(counts[s[0]])}</span></button>`).join("")}
    </div>` : "";
  return `<p class="xpm-line"><span class="xpm-mono">${n(rows.length)}</span> ${rows.length === 1 ? "property" : "properties"}${unverified ? ` · <span class="xpm-mono">${n(verified)}</span> with a verified acquisition path` : " · each with a verified acquisition path"}</p>
    ${seg}
    <div class="xpm-drawer" aria-label="Deed folders">${folders || `<p class="xpm-note">No folders match this switch.</p>`}</div>
    ${moreButton("laft", lim, list.length, "folders")}`;
}

function folderHtml(p, i, api) {
  const id = idOf(p);
  const open = S.folder === id;
  const a = acqOf(p, api);
  const amt = api.amountShort(p);
  const t = titleHtml(p, api);
  const tabCls = a.verified ? "ok" : a.mode === "none" ? "none" : "wait";
  const face = `<span class="plate"><span class="plate-in">${api.propertyVisual(p, "prop-card-photo xpm-vis")}</span>${stampHtml(p, api)}</span>
      <span class="ctitle${t.parcel ? " parcel" : ""}">${t.html}</span>
      <span class="where">${api.esc(whereText(p, api))}</span>
      <span class="fig"><span class="xpm-caps">${api.esc(amt.label)}</span>${amt.state === "not_published" ? missing(amt.text, api) : `<span class="fig-xl">${api.esc(amt.text)}</span>`}</span>
      ${a.verified || (stampOf(p, api) || {}).key === "unverified" ? "" : `<span class="nopath">${api.esc(a.mode === "none" ? "No purchase path - the source states there is none" : "Acquisition path not yet verified")}</span>`}
      ${reviewNote(p, api)}`;
  if (!open) {
    return `<div class="xpm-fold" style="--i:${Math.min(i, 14)};--r0:${(i % 3) - 1}deg">
      <span class="ftab ${tabCls}">${api.esc(p.county)}${a.verified ? `<span class="ftab-check" aria-hidden="true">${checkIcon(9)}</span>` : ""}</span>
      <div class="face xpm-obj tab-${tabCls}">
        <button type="button" class="hit" data-xa="folder" data-pid="${api.esc(id)}" data-k="fold-${api.esc(id)}" aria-expanded="false"
          aria-label="${api.esc(`${api.realAddress(p) || "Parcel " + (api.parcelOf(p) || "not published")}, ${whereText(p, api)}. ${amt.label}: ${amt.text}. ${a.verified ? "Verified acquisition path." : "Acquisition path not yet verified."} Open the folder: how to acquire.`)}">${face}</button>
        <div class="acts">
          <button type="button" class="xpm-cta sage" data-xa="folder" data-pid="${api.esc(id)}" data-k="how-${api.esc(id)}" aria-expanded="false">${a.verified ? "How to acquire" : "Open folder"}</button>
          ${watchBtn(p, api, "xpm-watch icon", true)}
        </div>
      </div>
    </div>`;
  }
  const pf = api.previewFacts(p);
  const info = api.amountInfo(p);
  const has = info.value !== null && info.value !== undefined;
  const anim = S.folderShown !== id;
  S.folderShown = id;
  return `<div class="xpm-fold open${anim ? " anim" : ""}" style="--i:0">
    <div class="hinge">
      <div class="inside xpm-obj">
        <span class="ftab ${tabCls}">${api.esc(p.county)} ${api.esc(api.unitWord())}</span>
        <button type="button" class="close-fold" data-xa="folder" data-pid="${api.esc(id)}" data-k="fold-${api.esc(id)}" aria-expanded="true" aria-label="Close folder">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
        <div class="in-stamp">${stampHtml(p, api, "inline")}</div>
        <h2 class="in-title${t.parcel ? " parcel" : ""}">${t.html}</h2>
        <div class="xpm-mono-s">${api.esc([whereText(p, api), pf.parcel ? pf.parcelLabel + " " + pf.parcel : "Parcel # not published", api.caseIdentText(p)].filter(Boolean).join(" · "))}</div>
        <div class="in-fig"><span class="xpm-caps">${api.esc(info.label)}</span>${has ? `<span class="fig-xxl">${api.esc(api.fmtMoney(info.value))}</span>` : missing(info.display || "Not published", api)}</div>
        ${info.note ? `<p class="xpm-small">${api.esc(info.note)}</p>` : ""}
      </div>
      <div class="cover" aria-hidden="true"><span class="xpm-caps">Deed folder</span><span class="cover-title">${api.esc(p.county)} ${api.esc(api.unitWord())}</span></div>
    </div>
    ${acquireSheetHtml(p, a, pf, api)}
  </div>`;
}

function acquireSheetHtml(p, a, pf, api) {
  const id = idOf(p);
  let how;
  if (a.verified) {
    const steps = a.steps.length
      ? a.steps.map((s, i) => `<div class="insert xpm-obj" style="--id:${420 + Math.min(i, 8) * 70}ms"><span class="num">${i + 1}</span><span>${api.esc(s)}</span></div>`).join("")
      : (a.instructions ? `<div class="insert xpm-obj" style="--id:420ms"><span class="num">i</span><span>${api.esc(a.instructions)}</span></div>` : "");
    const contact = [["Office", a.office], ["Phone", a.phone], ["E-mail", a.email], ["Address (in person)", a.address], ["Mailing address", a.mailing], ["Payment", a.payment]]
      .map(([k, v]) => `<div class="kv"><span class="xpm-caps">${k}</span>${v ? `<span>${api.esc(v)}</span>` : `<span>${missing("Not published", api)}</span>`}</div>`).join("");
    const docs = [];
    const appUrl = safeUrl(a.applicationUrl), pathUrl = safeUrl(a.url);
    if (appUrl) docs.push(`<a class="link-row" href="${api.esc(appUrl)}" target="_blank" rel="noopener"><span>Application / instructions document</span><span class="xpm-caps">Form</span></a>`);
    if (pathUrl && pathUrl !== appUrl) docs.push(`<a class="link-row" href="${api.esc(pathUrl)}" target="_blank" rel="noopener"><span>${api.esc(a.typeLabel || "Official page")}</span><span class="xpm-caps">Source</span></a>`);
    how = `<div class="vwrap"><span class="vstamp">${checkIcon(14)}Verified official process</span>${steps}</div>
      <div class="kvs">${contact}</div>${docs.join("")}
      ${a.mode !== "online" ? `<p class="xpm-small">No online purchase link on file.</p>` : ""}
      <p class="xpm-small">${api.esc(a.scope === "property" ? "Published for this parcel." : "County process, not an approval for this parcel.")} ${api.esc(`Last verified ${a.observedOn ? String(a.observedOn).slice(0, 10) : "(date not recorded)"}.`)}</p>`;
  } else {
    how = `<div class="insert-blank"><span class="xpm-caps">${a.mode === "none" ? "No purchase path - the source states there is none" : "Acquisition path not yet verified"}</span>
      <span class="xpm-small">Official source: ${api.esc(pf.source || api.sourceNameFor(p) || "Not recorded")}</span>
      ${linkHtml(pf.link, api, "xpm-link sage")}</div>`;
  }
  // Every fact on file, except the two this sheet already answers and the
  // availability line when it only repeats that the record is on the list.
  const SAYS_LISTED = { active: 1, available_otc: 1 };
  const rows = (pf.more || []).filter(r => r[0] !== "How to acquire" && r[0] !== "Legal" && !(r[0] === "Availability" && SAYS_LISTED[p.inventory_status]));
  if (pf.value) rows.unshift([pf.valueLabel || "County value", pf.value + " (county value, not a price)"]);
  rows.push(["Flood", pf.flood ? pf.flood.text : "Not checked"]);
  if (pf.source) rows.push(["Source", pf.source]);
  const legal = (pf.more || []).find(r => r[0] === "Legal");
  const gaps = api.dataGaps(p) || [];
  return `<section class="xpm-sheet" aria-label="How to acquire">
    <div class="sec-h"><h3 class="xpm-dm">How to acquire</h3><span class="xpm-chip mode">${api.esc(a.verified ? a.label : "Not yet verified")}</span></div>
    ${how}
    <h3 class="xpm-dm sec2">On file</h3>
    <div class="facts3">${rows.map(r => `<div class="fact"><span class="xpm-caps">${api.esc(r[0])}</span><span class="v">${api.esc(r[1])}</span></div>`).join("")}</div>
    ${legal ? `<p class="legal">${api.esc(legal[1])}</p>` : ""}
    ${gaps.length ? `<p class="gaps"><span class="xpm-caps">Not on file</span> ${api.esc(gaps.join(" · "))}</p>` : ""}
    <div class="sheet-acts">
      <button type="button" class="xpm-cta sage" data-xa="open" data-pid="${api.esc(id)}" data-k="open-${api.esc(id)}">Open full record</button>
      ${watchBtn(p, api, "xpm-watch")}
    </div>
  </section>`;
}

// ------------------------------------------------------------------- LIENS

function bundleKey(p, by) {
  if (by === "county") return p.county || "";
  return p.tax_year ? String(p.tax_year) : "";
}
function certNo(p) { return p.certificate_no ? String(p.certificate_no) : ""; }

function liensHtml(rows, api) {
  const by = S.bundleBy;
  const m = new Map();
  for (const p of rows) {
    const k = bundleKey(p, by);
    let b = m.get(k);
    if (!b) { b = []; m.set(k, b); }
    b.push(p);
  }
  const keys = Array.from(m.keys()).sort((a, b) => {
    if (a === "" || b === "") return a === "" ? 1 : b === "" ? -1 : 0;
    return by === "year" ? (a < b ? 1 : a > b ? -1 : 0) : a.localeCompare(b);
  });
  const lim = Math.min(S.limit.certificate, keys.length);
  // The newest bundle starts fanned, so a slip is on screen at once.
  if (S.fan === undefined) S.fan = keys[0];
  if (S.fan !== null && !keys.slice(0, lim).includes(S.fan)) S.fan = keys[0];
  const bundles = keys.slice(0, lim).map((k, i) => (S.fan === k ? fanHtml(k, m.get(k), api) : pileHtml(k, m.get(k), i, api))).join("");
  const sorts = [["year", "By tax year"], ["county", "By " + api.unitWord().toLowerCase()]];
  return `<div class="xpm-lienhead">
      <p class="xpm-line"><span class="xpm-mono">${n(rows.length)}</span> ${rows.length === 1 ? "certificate" : "certificates"} · <span class="xpm-mono">${n(keys.length)}</span> ${keys.length === 1 ? "bundle" : "bundles"}</p>
      <div class="xpm-sorts" role="group" aria-label="Bundle the slips">
        ${sorts.map(s => `<button type="button" class="sort${by === s[0] ? " on" : ""}" data-xa="bundleby" data-by="${s[0]}" data-k="by-${s[0]}" aria-pressed="${by === s[0]}"><span class="xpm-chip">${api.esc(s[1])}</span></button>`).join("")}
      </div>
    </div>
    <section class="xpm-shelf" aria-label="Certificate bundles">${bundles}</section>
    ${moreButton("certificate", lim, keys.length, "bundles")}
    <p class="xpm-note">A certificate is a lien on the property, not the land. Redeemed, assigned or expired shows only when the source says so; a certificate that leaves the list is never called sold.</p>`;
}

function bundleLabels(k, list, api) {
  const by = S.bundleBy;
  const caps = by === "year" ? "Tax year" : api.unitWord();
  const title = k === "" ? (by === "year" ? "Tax year not published" : "Not published") : k;
  const other = new Set(list.map(p => (by === "year" ? p.county : (p.tax_year ? String(p.tax_year) : "")))).size;
  const sub = by === "year" ? `${other} ${api.unitWord().toLowerCase()}${other === 1 ? "" : "s"}` : `${other} tax year${other === 1 ? "" : "s"}`;
  return { caps, title, sub };
}

function pileHtml(k, list, i, api) {
  const top = list[0];
  const L = bundleLabels(k, list, api);
  const edges = Math.min(3, list.length - 1);
  let edgeHtml = "";
  for (let e = edges; e >= 1; e--) edgeHtml += `<span class="edge xpm-slip" style="transform:translate(${e * 3}px,${e * 4}px) rotate(${(e % 2 ? 1 : -1) * (e * 1.1)}deg)" aria-hidden="true"></span>`;
  return `<div class="xpm-bundle" style="--i:${Math.min(i, 12)};--r0:${(i % 2 ? 1 : -1) * 2}deg">
    <button type="button" class="pile" data-xa="fan" data-key="${api.esc(k)}" data-k="fan-${api.esc(k)}" aria-expanded="false"
      aria-label="${api.esc(`${L.caps} ${L.title}: ${list.length} ${list.length === 1 ? "certificate" : "certificates"}. Fan the bundle out.`)}">
      ${edgeHtml}
      <span class="pile-top xpm-slip xpm-obj">
        <span class="pile-left"><span class="xpm-caps">Top slip</span><span class="xpm-mono-s tr">${api.esc(certNo(top) || "Certificate # not published")}</span><span class="pile-county tr">${api.esc(top.county)}</span></span>
        <span class="band"><span class="xpm-caps">${api.esc(L.caps)}</span><span class="band-title">${api.esc(L.title)}</span><span class="band-count">${list.length} ${list.length === 1 ? "slip" : "slips"}</span><span class="band-sub">${api.esc(L.sub)}</span></span>
      </span>
    </button>
  </div>`;
}

function fanHtml(k, list, api) {
  const L = bundleLabels(k, list, api);
  const start = Math.max(0, Math.min(S.fanStart, Math.max(0, list.length - 1)));
  const win = list.slice(start, start + FAN);
  if (!win.some(p => idOf(p) === S.slip)) S.slip = idOf(win[0]);
  const cnt = win.length, mid = (cnt - 1) / 2;
  const slips = win.map((p, i) => {
    const id = idOf(p);
    const lifted = id === S.slip;
    const pf = api.previewFacts(p);
    const a = api.amountShort(p);
    const amt = pf.bid || a.text;   // the exact published figure, under amountShort's label
    return `<div class="fslip${lifted ? " lifted" : ""}" style="--off:${i - mid};--fd:${i * 45}ms;z-index:${lifted ? 30 : 10 + i}">
      <button type="button" class="fb xpm-slip xpm-obj" data-xa="slip" data-pid="${api.esc(id)}" data-k="slip-${api.esc(id)}" aria-pressed="${lifted}"
        aria-label="${api.esc(`Certificate ${certNo(p) || "number not published"}, ${p.county} ${api.unitWord()}. ${a.label}: ${amt}. Lift this slip.`)}">
        <span class="xpm-caps">Cert</span><span class="xpm-mono-s ink tr">${api.esc(certNo(p) || "Not published")}</span>
        <span class="slip-county tr">${api.esc(p.county)}</span>
        ${stampHtml(p, api, "slip")}
        <span class="xpm-caps lab">${api.esc(a.label)}</span>${a.state === "not_published" ? `<span class="nf">Not published</span>` : `<span class="f">${api.esc(amt)}</span>`}
      </button>
      ${watchBtn(p, api, "fs xpm-obj", true).replace(`aria-label="`, `aria-label="Certificate ${api.esc(certNo(p) || "")}: `).replace("</svg>", `</svg><span class="fs-t">${api.isWatched(p.id) ? "Watching" : "Watch"}</span>`)}
    </div>`;
  }).join("");
  const sel = win.find(p => idOf(p) === S.slip) || win[0];
  const dealKey = k + "|" + start;
  const deal = S.dealt !== dealKey;
  S.dealt = dealKey;
  const pager = list.length > FAN ? `<div class="fan-pager">
      <button type="button" class="xpm-round" data-xa="fanprev" data-k="fanprev" aria-label="Previous slips"${start === 0 ? " disabled" : ""}><span><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg></span></button>
      <span class="xpm-pager">Slips <span class="xpm-mono">${start + 1}–${start + cnt}</span> of <span class="xpm-mono">${list.length}</span></span>
      <button type="button" class="xpm-round" data-xa="fannext" data-k="fannext" aria-label="Next slips"${start + FAN >= list.length ? " disabled" : ""}><span><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg></span></button>
    </div>` : "";
  return `<div class="xpm-bundle fanned">
    <div class="fan-wrap">
      <div class="fan-stage${deal ? " deal" : ""}" role="group" aria-label="${api.esc(`${L.caps} ${L.title}, ${list.length} ${list.length === 1 ? "certificate" : "certificates"}, fanned out`)}">
        <div class="fan-band" aria-hidden="true">${api.esc(L.title)}</div>
        ${slips}
      </div>
      ${pager}
      ${trayHtml(sel, api)}
      <button type="button" class="fold-back" data-xa="fan" data-key="${api.esc(k)}" data-k="fan-${api.esc(k)}" aria-expanded="true">Bundle ${api.esc(L.title)} back up</button>
    </div>
  </div>`;
}

function trayHtml(p, api) {
  const pf = api.previewFacts(p);
  const a = api.amountShort(p);
  const facts = [["Status", api.officialStatusText(p)]];
  if (pf.parcel) facts.push([pf.parcelLabel, pf.parcel]);
  const more = new Map(pf.more || []);
  for (const k of ["Interest rate", "Tax year", "Issued"]) facts.push([k, more.get(k) || "Not published"]);
  for (const r of pf.more || []) if (!["Interest rate", "Tax year", "Issued"].includes(r[0])) facts.push(r);
  if (pf.source) facts.push(["Source", pf.source]);
  const id = idOf(p);
  const anim = S.trayShown !== id;
  S.trayShown = id;
  return `<div class="tray xpm-obj${anim ? " anim" : ""}" aria-live="polite">
    <div class="tray-head"><div><div class="tray-cert xpm-mono">Cert ${api.esc(certNo(p) || "number not published")}</div>
      <div class="xpm-small">${api.esc(whereText(p, api))}</div></div>${stampHtml(p, api, "inline")}</div>
    <div class="tray-fig"><span class="xpm-caps">${api.esc(a.label)}</span>${a.state === "not_published" ? missing("Not published", api) : `<span class="fig-xl">${api.esc(pf.bid || a.text)}</span>`}</div>
    <div class="facts">${factRows(facts, api)}</div>
    <div class="tray-acts">
      <button type="button" class="xpm-cta plum" data-xa="open" data-pid="${api.esc(id)}" data-k="open-${api.esc(id)}">Open full record</button>
      ${watchBtn(p, api, "xpm-watch").replace(`data-k="w-`, `data-k="tw-`)}
    </div>
    ${linkHtml(pf.link, api, "xpm-link plum")}
  </div>`;
}

// ------------------------------------------------------------- interaction

function rowById(id) {
  const rows = S.last && Array.isArray(S.last.rows) ? S.last.rows : [];
  for (const p of rows) if (idOf(p) === id) return p;
  return null;
}

function openRecord(id, fromEl) {
  const p = rowById(id);
  const api = apiOf(S.last);
  if (!p || !api) return;
  const obj = fromEl && fromEl.closest(".xpm-plac, .xpm-fold, .tray");
  if (obj && !reduced()) {
    obj.classList.add("opening");
    setTimeout(() => { obj.classList.remove("opening"); api.openDetail(p); }, OPEN_DELAY);
  } else api.openDetail(p);
}

// Flip a placard in place (no redraw: nothing else on the page moves).
function flipInPlace(card, pid) {
  const fl = S.flipped.has(pid);
  card.classList.toggle("flipped", fl);
  card.classList.remove("lift-a", "lift-b");
  void card.offsetWidth;
  card.classList.add(fl ? "lift-a" : "lift-b");
  const front = card.querySelector(".face.front"), back = card.querySelector(".face.back");
  const setTab = (root, on) => root && root.querySelectorAll("button, a").forEach(b => { if (on) b.removeAttribute("tabindex"); else b.setAttribute("tabindex", "-1"); });
  if (front) { if (fl) front.setAttribute("aria-hidden", "true"); else front.removeAttribute("aria-hidden"); setTab(front, !fl); }
  if (back) { if (fl) back.removeAttribute("aria-hidden"); else back.setAttribute("aria-hidden", "true"); setTab(back, fl); }
  const hit = card.querySelector(".hit");
  if (hit) { hit.setAttribute("aria-pressed", String(fl)); if (fl) hit.setAttribute("aria-hidden", "true"); else hit.removeAttribute("aria-hidden"); }
  const focusTo = fl ? card.querySelector(".back-head") : hit;
  if (focusTo) setTimeout(() => { try { focusTo.focus({ preventScroll: true }); } catch {} }, reduced() ? 0 : 320);
}

function onClick(e) {
  const stage = stageEl();
  if (!stage || stage.dataset.xp !== NAME || !isActive()) return;
  const el = e.target.closest("[data-xa]");
  if (!el || !stage.contains(el)) return;
  const xa = el.dataset.xa, pid = el.dataset.pid;
  switch (xa) {
    case "more": {
      const k = el.dataset.ledger;
      if (S.limit[k]) S.limit[k] += PAGE;
      redraw();
      break;
    }
    case "day":
      if (S.day !== el.dataset.day) {
        S.day = el.dataset.day; S.limit.auction = PAGE; S.dayAnim = !reduced();
        redraw();
        const on = stage.querySelector(".xpm-scrub .col.on");
        if (on && on.scrollIntoView) { try { on.scrollIntoView({ block: "nearest", inline: "nearest", behavior: reduced() ? "auto" : "smooth" }); } catch {} }
        const head = stage.querySelector(".xpm-dayhead");
        const scrub = stage.querySelector(".xpm-scrub");
        if (head && scrub && head.getBoundingClientRect().top < scrub.getBoundingClientRect().bottom) {
          try { window.scrollBy({ top: head.getBoundingClientRect().top - scrub.getBoundingClientRect().bottom - 8, behavior: reduced() ? "auto" : "smooth" }); } catch {}
        }
      }
      break;
    case "flip": {
      if (S.flipped.has(pid)) S.flipped.delete(pid); else S.flipped.add(pid);
      const card = el.closest(".xpm-plac");
      if (card) flipInPlace(card, pid); else redraw();
      break;
    }
    case "open": openRecord(pid, el); break;
    case "seg":
      if (S.seg !== el.dataset.seg) { S.seg = el.dataset.seg; S.limit.laft = PAGE; S.folder = null; redraw(); }
      break;
    case "folder":
      S.folder = S.folder === pid ? null : pid;
      S.folderShown = null;
      redraw();
      if (S.folder) {
        const f = stage.querySelector(".xpm-fold.open");
        if (f && f.scrollIntoView) { try { f.scrollIntoView({ block: "nearest", behavior: reduced() ? "auto" : "smooth" }); } catch {} }
        const c = stage.querySelector(".xpm-fold.open .close-fold");
        if (c) { try { c.focus({ preventScroll: true }); } catch {} }
      } else {
        const b = stage.querySelector(`[data-k="fold-${keyEsc(pid)}"]`);
        if (b) { try { b.focus({ preventScroll: true }); } catch {} }
      }
      break;
    case "bundleby":
      if (S.bundleBy !== el.dataset.by) { S.bundleBy = el.dataset.by; S.fan = undefined; S.slip = null; S.fanStart = 0; S.limit.certificate = PAGE; redraw(); }
      break;
    case "fan": {
      const k = el.dataset.key;
      S.fan = S.fan === k ? null : k;
      S.fanStart = 0; S.slip = null; S.dealt = null; S.trayShown = null;
      redraw();
      break;
    }
    case "fanprev": S.fanStart = Math.max(0, S.fanStart - FAN); S.slip = null; redraw(); break;
    case "fannext": S.fanStart += FAN; S.slip = null; redraw(); break;
    case "slip":
      if (S.slip !== pid) { S.slip = pid; redraw(); }
      break;
  }
}

function onKey(e) {
  const stage = stageEl();
  if (!stage || stage.dataset.xp !== NAME || !isActive()) return;
  if (!stage.contains(document.activeElement)) return;
  if (e.key === "Escape") {
    if (S.folder) { const id = S.folder; S.folder = null; redraw(); const b = stage.querySelector(`[data-k="fold-${keyEsc(id)}"]`); if (b) b.focus(); }
    else if (S.fan !== null && S.fan !== undefined) { const k = S.fan; S.fan = null; redraw(); const b = stage.querySelector(`[data-k="fan-${keyEsc(k)}"]`); if (b) b.focus(); }
    return;
  }
  // Arrow keys move along the sale days that have lots.
  const col = document.activeElement.closest && document.activeElement.closest(".xpm-scrub .col");
  if (col && (e.key === "ArrowRight" || e.key === "ArrowLeft")) {
    const all = Array.from(stage.querySelectorAll(".xpm-scrub .col:not(:disabled)"));
    const i = all.indexOf(col);
    const next = all[i + (e.key === "ArrowRight" ? 1 : -1)];
    if (next) { e.preventDefault(); next.focus(); next.click(); }
  }
}

// ------------------------------------------------------------------ wiring

document.addEventListener("click", e => {
  const stage = stageEl();
  const k = stage && stage.dataset.xp === NAME && e.target.closest ? e.target.closest("[data-k]") : null;
  S.pressed = k && stage.contains(k) ? k.getAttribute("data-k") : null;
}, true);
document.addEventListener("click", onClick);
document.addEventListener("keydown", onKey);
window.addEventListener("resize", () => { const st = stageEl(); if (st && st.dataset.xp === NAME) stickyTop(st); });
window.addEventListener("tdw:rendered", e => draw(e.detail));
window.addEventListener("tdw:experience", () => { if (isActive()) { S.ledger = null; if (window.__tdwLastRender) draw(window.__tdwLastRender); } else deactivate(); });
if (isActive() && window.__tdwLastRender) draw(window.__tdwLastRender);
else if (!isActive()) deactivate();
