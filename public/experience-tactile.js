// Tactile ("Pocket Objects") List experience - 2026-10-25 trial look.
//
// Every record is a paper object you handle:
//   AUCTIONS   lot placards in a deck per sale day; tap a placard to flip it
//              and read its back; "Open full record" opens the property page.
//   AVAILABLE  deed folders with coloured tabs in a drawer; tap a folder and
//              it opens on its hinge while its "How to acquire" sheet slides
//              out (acquisitionOf / previewFacts).
//   LIENS      certificate slips bundled by tax year (or county) under a paper
//              band; tap a bundle to fan it out, tap a slip to lift it.
//
// Contract (app.js "Look switch"): draws only while
// window.__tdwExperience.name === "tactile", from the tdw:rendered payload
// (the List's own filtered, publication-gated rows plus `api`, the card's own
// label / display helpers). Every figure is shown under the label the api
// gives; nothing is scored, estimated or computed. Opening a record always
// goes through api.openDetail(p) - there is no second property page. The
// watchlist buttons are data-action="bidlist" and are handled by app.js's
// document-level action handler.
//
// No imports; no network requests of its own.

const NAME = "tactile";
const CPAGE = 8;            // Available folders per county drawer before its own "Show more"
const PAGE = 48;            // objects built at a time; "Show more" adds PAGE more
const FAN = 5;              // slips fanned out at once
const OPEN_DELAY = 260;     // ms of opening animation before the property page

const S = {
  ledger: null,
  key: "",
  limit: { auction: PAGE, laft: PAGE, certificate: PAGE },
  flipped: new Set(),
  day: null,
  deckId: null,
  deckAnim: null,           // { id, cls } one-shot animation on the next draw
  folder: null,
  cLim: new Map(),          // Available: folders shown per county drawer
  seg: "all",
  bundleBy: "year",
  fan: null,
  fanStart: 0,
  slip: null,
  pressed: null,
  last: null
};

const ACQ_CACHE = new WeakMap();

const isActive = () => !!(window.__tdwExperience && window.__tdwExperience.name === NAME);
const reduced = () => { try { return matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; } };
const stageEl = () => document.getElementById("xpStage");
const safeUrl = u => (u && /^https?:\/\//i.test(String(u).trim()) ? String(u).trim() : "");
const idOf = p => String(p.id);

function apiOf(detail) {
  return (detail && detail.api) || (window.__tdwExperience && window.__tdwExperience.api) || null;
}

// ---------------------------------------------------------------- lifecycle

function deactivate() {
  const stage = stageEl();
  if (stage && stage.dataset.xp === NAME) { stage.innerHTML = ""; delete stage.dataset.xp; }
  if (document.documentElement.dataset.experienceReady === NAME) delete document.documentElement.dataset.experienceReady;
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
    // Let the classic list say which zero this is (its zero-state copy is
    // the honest one); the stage stays empty.
    if (stage.dataset.xp === NAME) { stage.innerHTML = ""; delete stage.dataset.xp; }
    if (document.documentElement.dataset.experienceReady === NAME) delete document.documentElement.dataset.experienceReady;
    S.key = "";
    return;
  }
  if (ledger !== S.ledger) {
    S.ledger = ledger;
    S.limit[ledger] = PAGE;
    S.cLim.clear();
  }
  // The entrance animation plays once per ledger (2026-10-28): rows arrive a
  // page at a time while a ledger loads, and keying it on the row count
  // replayed it on every page - the deck jumped several times on load.
  const key = ledger;
  const enter = key !== S.key;
  S.key = key;

  // Keep keyboard focus across a redraw: the focused control, or the one just
  // pressed when app.js disabled it mid-action (the watchlist button).
  const ae = document.activeElement;
  const focusKey = ae && stage.contains(ae) ? ae.getAttribute("data-k")
    : (!ae || ae === document.body) ? S.pressed : null;
  S.pressed = null;

  let html;
  if (ledger === "auction") html = auctionsHtml(rows, api);
  else if (ledger === "laft") html = availableHtml(rows, api);
  else html = liensHtml(rows, api);

  // A redraw keeps the sale-day rail and lot grid where the reader left them.
  const keepScroll = {};
  [".xpt-days", ".xpt-lot-grid"].forEach(sel => { const el = stage.querySelector(sel); if (el) keepScroll[sel] = el.scrollLeft; });
  stage.dataset.xp = NAME;
  stage.innerHTML = `<div class="xpt xpt-${ledger}${enter ? " xpt-enter" : ""}" data-ledger="${ledger}">${html}</div>`;
  Object.keys(keepScroll).forEach(sel => { const el = stage.querySelector(sel); if (el) el.scrollLeft = keepScroll[sel]; });
  try { api.hydrateVisuals(stage); } catch {}
  // The shared "Now showing" county bar (app.js). Called on every ledger so a
  // bar left from Available is cleared: it hides itself with fewer than two
  // [data-county-head] elements, which only the Available drawers carry.
  if (typeof api.installCountyNowBar === "function") { try { api.installCountyNowBar(stage); } catch {} }
  document.documentElement.dataset.experienceReady = NAME;

  if (focusKey) {
    const el = stage.querySelector(`[data-k="${focusKey.replace(/["\\]/g, "")}"]`);
    if (el) { try { el.focus({ preventScroll: true }); } catch {} }
  }
  S.deckAnim = null;
}

function redraw() { if (S.last) draw(S.last); }

// Moving through the deck (next / previous / a swipe / a lot picked from the
// grid) replaces only the top placard, the pager and the grid's highlight
// (2026-10-28). Redrawing the whole stage reloaded every picture, reset the
// rail's scroll position and flashed the page - the "glitchy" deck.
function updateDeck() {
  const stage = stageEl();
  const api = apiOf(S.last);
  const col = stage && stage.querySelector(".xpt-deck-col");
  if (!col || !api || S.ledger !== "auction") { redraw(); return; }
  const tmp = document.createElement("div");
  tmp.innerHTML = auctionsHtml(S.last.rows || [], api);
  const oldDeck = col.querySelector(".xpt-deck"), newDeck = tmp.querySelector(".xpt-deck");
  const oldCtl = col.querySelector(".xpt-deck-ctl"), newCtl = tmp.querySelector(".xpt-deck-ctl");
  if (!oldDeck || !newDeck || !oldCtl || !newCtl) { redraw(); return; }
  oldDeck.replaceWith(newDeck);
  oldCtl.replaceWith(newCtl);
  const grid = stage.querySelector(".xpt-lot-grid"), newGrid = tmp.querySelector(".xpt-lot-grid");
  if (grid && newGrid && grid.children.length !== newGrid.children.length) grid.replaceWith(newGrid);
  else if (grid) grid.querySelectorAll(".xpt-mini").forEach(m => { const on = m.dataset.pid === S.deckId; m.classList.toggle("on", on); m.setAttribute("aria-current", String(on)); });
  const more = stage.querySelector(".xpt-lots .xpt-more"), newMore = tmp.querySelector(".xpt-lots .xpt-more");
  if (more && newMore) more.replaceWith(newMore); else if (more && !newMore) more.remove();
  try { api.hydrateVisuals(newDeck); } catch {}
  S.deckAnim = null;
}

// --------------------------------------------------------------- shared bits

function watchBtn(p, api, cls) {
  const on = api.isWatched(p.id);
  return `<button type="button" class="${cls}${on ? " on" : ""}" data-action="bidlist" data-pid="${api.esc(p.id)}" data-k="w-${api.esc(p.id)}" aria-pressed="${on}" aria-label="${on ? "On your watchlist - tap to remove" : "Add to watchlist"}">` +
    `<svg width="18" height="18" viewBox="0 0 24 24" fill="${on ? "currentColor" : "none"}" stroke="currentColor" stroke-width="1.75" stroke-linejoin="round" aria-hidden="true"><path d="M6 3h12v18l-6-4.5L6 21z"/></svg>` +
    `<span>${on ? "On Watchlist" : "Add to Watchlist"}</span></button>`;
}

function missing(text, api) { return `<span class="xpt-missing">${api.esc(text)}</span>`; }

function titleHtml(p, api) {
  const street = api.realAddress(p);
  return street ? { html: api.esc(street), parcel: false } : { html: api.lotTitle(p), parcel: true };   // lotTitle is already escaped
}

function linkHtml(link, api, cls) {
  const href = link ? safeUrl(link.href) : "";
  if (!href) return link && link.label ? missing(link.label, api) : "";
  return `<a class="${cls}" href="${api.esc(href)}" target="_blank" rel="noopener"${link.note ? ` title="${api.esc(link.note)}"` : ""}>${api.esc(link.label)}` +
    `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 17L17 7M9 7h8v8"/></svg></a>`;
}

function moreButton(ledger, shown, total) {
  if (shown >= total) return "";
  const next = Math.min(PAGE, total - shown);
  return `<div class="xpt-more-wrap"><button type="button" class="xpt-more" data-xa="more" data-ledger="${ledger}" data-k="more-${ledger}">Show ${next} more <span class="xpt-mono">${shown} of ${total}</span></button></div>`;
}

const todayIso = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
function daysBetween(iso) {
  const a = new Date(todayIso() + "T00:00:00"), b = new Date(iso + "T00:00:00");
  if (isNaN(b)) return null;
  return Math.round((b - a) / 86400000);
}

// ---------------------------------------------------------------- AUCTIONS

function saleDay(p) { const d = p.sale_date ? String(p.sale_date).slice(0, 10) : ""; return /^\d{4}-\d{2}-\d{2}$/.test(d) ? d : ""; }

function groupDays(rows) {
  const m = new Map();
  for (const p of rows) {
    const d = saleDay(p);
    let g = m.get(d);
    if (!g) { g = []; m.set(d, g); }
    g.push(p);
  }
  const t = todayIso();
  const keys = Array.from(m.keys()).sort((a, b) => {
    const ra = a === "" ? 2 : a >= t ? 0 : 1, rb = b === "" ? 2 : b >= t ? 0 : 1;
    if (ra !== rb) return ra - rb;
    return ra === 0 ? (a < b ? -1 : a > b ? 1 : 0) : (a < b ? 1 : a > b ? -1 : 0);
  });
  return keys.map(k => ({ day: k, rows: m.get(k) }));
}

function stepCls(days) {
  if (days === null) return "none";
  if (days < 0) return "past";
  return days === 0 ? "today" : days <= 3 ? "warm" : days <= 14 ? "mid" : "soft";
}
function countdown(days) {
  if (days === null) return "Sale date not scheduled";
  if (days < 0) return "Sale date passed";
  if (days === 0) return "Sale day is today";
  return `in ${days} day${days === 1 ? "" : "s"}`;
}

function auctionsHtml(rows, api) {
  const groups = groupDays(rows);
  if (!groups.some(g => g.day === S.day)) { S.day = groups[0].day; S.deckId = null; }
  const g = groups.find(x => x.day === S.day);
  const lots = g.rows;
  let idx = lots.findIndex(p => idOf(p) === S.deckId);
  if (idx < 0) { idx = 0; S.deckId = idOf(lots[0]); }
  const counties = new Set(lots.map(p => p.county));
  // One county on the day: the banner chip names it and the placards do not.
  const oneCounty = counties.size === 1 ? (Array.from(counties)[0] || "") : "";
  const days = g.day ? daysBetween(g.day) : null;
  const top = lots[idx];
  const topFacts = api.previewFacts(top);
  const procRow = (topFacts.more || []).find(r => r[0] === "Sale process");
  const proc = procRow && procRow[1] && procRow[1] !== "Not yet verified" ? procRow[1] : "";

  const rail = groups.map((x, i) => {
    const dd = x.day ? daysBetween(x.day) : null;
    const on = x.day === S.day;
    let dow = "", num = "—", mon = "No date";
    if (x.day) {
      const dt = new Date(x.day + "T00:00:00");
      dow = dt.toLocaleDateString("en-US", { weekday: "short" }).toUpperCase();
      num = String(dt.getDate());
      mon = dt.toLocaleDateString("en-US", { month: "short" }).toUpperCase();
    }
    const n = x.rows.length;
    return `<button type="button" class="xpt-day s-${stepCls(dd)}${on ? " on" : ""}" data-xa="day" data-day="${x.day}" data-k="day-${x.day || "none"}" aria-pressed="${on}" style="--rd:${Math.min(i, 12) * 40 + 140}ms" ` +
      `aria-label="${api.esc((x.day ? api.fmtDateLong(x.day) : "Sale date not scheduled") + ", " + n + (n === 1 ? " lot" : " lots") + ", " + countdown(dd))}">` +
      `<span class="dw">${dow}</span><span class="dn">${num}</span><span class="dm">${mon}</span>` +
      `<span class="dc xpt-mono">${n}</span></button>`;
  }).join("");

  const banner = `<section class="xpt-banner" aria-label="Sale day">
    <h2 class="xpt-dm">${g.day ? api.esc(api.fmtDateLong(g.day)) : "Sale date not scheduled"}</h2>
    <div class="xpt-chips">
      <span class="xpt-chip cd s-${stepCls(days)}">${api.esc(countdown(days))}</span>
      ${oneCounty ? `<span class="xpt-chip fmt">${api.esc(oneCounty + " " + api.unitWord())}</span>` : ""}
    </div>
    <ol class="xpt-miles" aria-label="Sale milestones">
      <li class="mile ${proc ? "fill" : "hatch"}" style="--md:120ms"><span class="node" aria-hidden="true"></span><span class="xpt-caps">Sale process</span><span class="mv">${proc ? api.esc(proc) : "Not yet verified"}</span></li>
      <li class="mile fill" style="--md:180ms"><span class="node" aria-hidden="true"></span><span class="xpt-caps">Sale day</span><span class="mv">${g.day ? "Scheduled" : "Not scheduled"}</span></li>
      <li class="mile ${days !== null && days < 0 ? "hatch" : "outline"}" style="--md:240ms"><span class="node" aria-hidden="true"></span><span class="xpt-caps">Result</span><span class="mv">${days !== null && days < 0 ? "Sale date passed - see each lot" : "Sale not yet held"}</span></li>
      <li aria-hidden="true" class="miles-line"></li>
    </ol>
  </section>`;

  // The deck: the top placard in full, two blank papers under it.
  const under = [];
  for (let k = 1; k <= 2 && k < lots.length; k++) under.push(`<div class="xpt-under u${k}" aria-hidden="true"><span class="band"></span></div>`);
  const deck = `<div class="xpt-deck" role="group" aria-roledescription="deck" aria-label="Placard deck, ${lots.length} ${lots.length === 1 ? "lot" : "lots"}">
    ${under.reverse().join("")}
    ${placardHtml(top, idx, lots.length, api, topFacts, !!oneCounty)}
  </div>
  <div class="xpt-deck-ctl">
    <button type="button" class="xpt-round" data-xa="prev" data-k="deck-prev" aria-label="Previous lot"${lots.length < 2 ? " disabled" : ""}><span><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg></span></button>
    <span class="xpt-pager" aria-live="polite">Lot <b class="xpt-mono">${idx + 1}</b> of <span class="xpt-mono">${lots.length}</span></span>
    <button type="button" class="xpt-round" data-xa="next" data-k="deck-next" aria-label="Next lot"${lots.length < 2 ? " disabled" : ""}><span><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg></span></button>
  </div>`;

  const lim = Math.min(S.limit.auction, lots.length);
  const minis = lots.slice(0, lim).map((p, i) => miniPlacardHtml(p, i, api, i === idx)).join("");

  // The List title carries the lot count; the rail label carries the number
  // of sale days; each day badge carries that day's lots.
  const lotsGrid = lots.length > 1 ? `<section class="xpt-lots" aria-label="Every lot on this sale day">
        <h3 class="xpt-caps xpt-lots-h">All lots this sale day</h3>
        <div class="xpt-lot-grid">${minis}</div>
        ${moreButton("auction", lim, lots.length)}
      </section>` : "";
  return `<div class="xpt-rail"><span class="xpt-caps xpt-rail-label"><span class="xpt-mono">${groups.length}</span> sale ${groups.length === 1 ? "day" : "days"}</span><div class="xpt-days" role="group" aria-label="Sale days">${rail}</div></div>
    <div class="xpt-auction-body${lotsGrid ? "" : " xpt-one-lot"}">
      <div class="xpt-deck-col">${banner}${deck}
        <p class="xpt-note">Tap a placard to flip it. Every figure sits under the source's own label.</p>
      </div>
      ${lotsGrid}
    </div>`;
}

function placardHtml(p, idx, n, api, pf, countyInBanner) {
  const id = idOf(p);
  const flipped = S.flipped.has(id);
  const t = titleHtml(p, api);
  const caseText = api.caseIdentText(p);
  const value = pf.value ? `<span class="fig-m">${api.esc(pf.value)}</span>` : missing(api.dataGaps(p).includes("No county value on file") ? "No county value on file" : "Not published", api);
  const off = api.offCurrentSaleList(p);
  const foot = off
    ? `<span class="xpt-offlist">Not on the county's current sale list${p.sale_date ? " · was scheduled " + api.esc(api.fmtDateLong(saleDay(p))) : ""} · no result published</span>`
    : placardFoot(p, api);
  // "Sale process" is the banner's milestone; a flood gap goes to the
  // "Not on file" line, never a second "Not checked" row.
  const facts = (pf.more || []).filter(r => r[0] !== "Legal" && r[0] !== "Sale process").slice(0, 7);
  const floodGap = !pf.flood || pf.flood.cls === "muted";
  if (!floodGap) facts.push(["Flood", pf.flood.text]);
  const legalRow = (pf.more || []).find(r => r[0] === "Legal");
  const allGaps = api.dataGaps(p);
  const gaps = allGaps.slice(0, 4);
  const fg = allGaps.find(t => /^Flood zone/.test(t)) || (floodGap ? "Flood zone not checked" : "");
  if (fg && !gaps.includes(fg)) { if (gaps.length >= 4) gaps.pop(); gaps.push(fg); }
  const anim = S.deckAnim && S.deckAnim.id === id ? " " + S.deckAnim.cls : "";
  return `<div class="xpt-placard${flipped ? " flipped" : ""}${anim}" data-pid="${api.esc(id)}">
    <div class="xpt-flip">
      <button type="button" class="face front xpt-obj" data-xa="flip" data-pid="${api.esc(id)}" data-k="flip-${api.esc(id)}" aria-pressed="${flipped}" ${flipped ? 'tabindex="-1" aria-hidden="true"' : ""}
        aria-label="${api.esc(`Lot ${idx + 1} of ${n}. ${pf.bidLabel}: ${pf.bid || "Not published"}. Tap to flip and read the back.`)}">
        <span class="band" aria-hidden="true"></span><span class="punch l" aria-hidden="true"></span><span class="punch r" aria-hidden="true"></span>
        <span class="flip-hint" aria-hidden="true">${flipIcon()}Flip</span>
        <span class="lotrow"><span class="lotnum"><span class="xpt-caps">Lot</span><span class="numeral">${idx + 1}</span></span>
          <span class="xpt-mono-s">${api.esc(caseText)}</span></span>
        <span class="ctitle${t.parcel ? " parcel" : ""}">${t.html}</span>
        <span class="ids xpt-mono-s">${pf.parcel ? api.esc(pf.parcelLabel + " " + pf.parcel) : "Parcel # not published"}${countyInBanner ? "" : " · " + api.esc(p.county + " " + api.unitWord())}</span>
        <span class="plate"><span class="plate-in">${api.propertyVisual(p, "prop-card-photo xpt-vis", countyInBanner ? { omitCounty: true } : undefined)}</span></span>
        <span class="figs">
          <span class="figure"><span class="xpt-caps">${api.esc(pf.bidLabel)}</span>${pf.bid ? `<span class="fig-xl">${api.esc(pf.bid)}</span>` : missing("Not published", api)}</span>
          <span class="figure"><span class="xpt-caps">${api.esc(pf.valueLabel || "County value")}</span>${value}<span class="ctx">county value, not a price</span></span>
        </span>
        ${foot}
      </button>
      <div class="face back xpt-obj"${flipped ? "" : ' aria-hidden="true"'}>
        <span class="band" aria-hidden="true"></span>
        <button type="button" class="back-head" data-xa="flip" data-pid="${api.esc(id)}" data-k="back-${api.esc(id)}" ${flipped ? "" : 'tabindex="-1"'} aria-label="Flip back to the front of lot ${idx + 1}">
          <span class="xpt-caps">Lot ${idx + 1} · Facts on file</span><span class="flip-hint static">${flipIcon()}Front</span></button>
        <div class="back-scroll">
          <div class="facts">${facts.map(r => `<div class="fact"><span class="k">${api.esc(r[0])}</span><span class="v">${api.esc(r[1])}</span></div>`).join("")}</div>
          ${legalRow ? `<p class="legal">${api.esc(legalRow[1])}</p>` : ""}
          ${gaps.length ? `<p class="gaps"><span class="xpt-caps">Not on file</span> ${api.esc(gaps.join(" · "))}</p>` : ""}
          <p class="src">${api.esc(pf.source || api.sourceNameFor(p) || "")}</p>
        </div>
        ${backActs(`<div class="acts">
          ${linkHtml(pf.link, api, "xpt-link")}
          <div class="acts-row">
            <button type="button" class="xpt-cta rust" data-xa="open" data-pid="${api.esc(id)}" data-k="open-${api.esc(id)}">Open full record</button>
            ${watchBtn(p, api, "xpt-watch")}
          </div>
        </div>`, flipped)}
      </div>
    </div>
  </div>`;
}

// The placard foot: the record's status without the ledger word, and only
// when it says more than "sale scheduled" (the banner's milestone says that).
// "no sale date on file", a passed date and a published result all show.
function placardFoot(p, api) {
  const t = String(api.officialStatusText(p, { omitLedger: true }) || "");
  const plain = t.replace(/^[^·]*·\s*/, "");
  if (/^sale scheduled\b/i.test(plain)) return "";
  return `<span class="xpt-cfoot"><i aria-hidden="true"></i>${api.esc(plain.charAt(0).toUpperCase() + plain.slice(1))}</span>`;
}

// The back of an unflipped placard is out of the tab order.
function backActs(html, flipped) { return flipped ? html : html.replace(/<(a|button) /g, '<$1 tabindex="-1" '); }

function flipIcon() {
  return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/></svg>`;
}

function miniPlacardHtml(p, i, api, on) {
  const id = idOf(p);
  const t = titleHtml(p, api);
  const a = api.amountShort(p);
  const watched = api.isWatched(p.id);
  return `<button type="button" class="xpt-mini xpt-obj${on ? " on" : ""}" data-xa="pick" data-pid="${api.esc(id)}" data-k="pick-${api.esc(id)}" style="--i:${Math.min(i, 16)}" aria-current="${on}"
      aria-label="${api.esc(`Lot ${i + 1}. ${a.label}: ${a.text}. Show this placard on top of the deck.`)}">
    <span class="band" aria-hidden="true"></span>
    <span class="mini-top"><span class="numeral-s">${i + 1}</span>${watched ? `<span class="rib" aria-label="On your watchlist"><svg width="12" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M6 3h12v18l-6-4.5L6 21z"/></svg></span>` : ""}</span>
    <span class="mini-title${t.parcel ? " parcel" : ""}">${t.html}</span>
    <span class="mini-fig"><span class="xpt-caps">${api.esc(a.label)}</span><span class="${a.state === "not_published" ? "nf" : "f"}">${api.esc(a.text)}</span></span>
  </button>`;
}

// --------------------------------------------------------------- AVAILABLE

function acqOf(p, api) {
  let a = ACQ_CACHE.get(p);
  if (!a) { a = api.acquisitionOf(p); ACQ_CACHE.set(p, a); }
  return a;
}

function availableHtml(rows, api) {
  let verified = 0;
  for (const p of rows) if (acqOf(p, api).verified) verified++;
  const counts = { all: rows.length, verified, unverified: rows.length - verified };
  if (!counts[S.seg] && S.seg !== "all") S.seg = "all";
  const list = S.seg === "all" ? rows : rows.filter(p => (S.seg === "verified") === acqOf(p, api).verified);
  const segs = [["all", "All"], ["verified", "Verified path"], ["unverified", "Not yet verified"]];
  const si = segs.findIndex(s => s[0] === S.seg);
  // One drawer per county, in the order the List sorted the rows. Every
  // county gets its head at once (so the shared "Now showing" bar can reach
  // any county); each drawer opens with CPAGE folders and its own "Show more
  // in <County>". The county head carries the name only: the List title is
  // the one count, and the bar's county list is the one place per-county
  // counts appear.
  const byCounty = new Map();
  for (const p of list) {
    const c = p.county || "";
    let g = byCounty.get(c);
    if (!g) { g = []; byCounty.set(c, g); }
    g.push(p);
  }
  const shownIds = new Set();
  byCounty.forEach((ps, c) => { ps.slice(0, S.cLim.get(c) || CPAGE).forEach(p => shownIds.add(idOf(p))); });
  if (S.folder && !shownIds.has(S.folder)) S.folder = null;
  let fi = 0;
  const drawers = Array.from(byCounty, ([c, ps]) => {
    const name = c ? c + " " + api.unitWord() : api.unitWord() + " not published";
    const lim = Math.min(S.cLim.get(c) || CPAGE, ps.length);
    const more = lim < ps.length
      ? `<div class="xpt-more-wrap"><button type="button" class="xpt-more" data-xa="cmore" data-county="${api.esc(c)}" data-k="cmore-${api.esc(c)}">Show more in ${api.esc(name)}</button></div>`
      : "";
    return `<section class="xpt-cgroup" aria-label="${api.esc(name)}">
      <h2 class="xpt-chead"${c ? ` data-county-head="${api.esc(c)}"` : ""}>${api.esc(name)}</h2>
      <div class="xpt-drawer">${ps.slice(0, lim).map(p => folderHtml(p, fi++, api)).join("")}</div>
      ${more}
    </section>`;
  }).join("");
  return `<div class="xpt-seg" role="group" aria-label="Acquisition path" style="--si:${si}">
      <span class="seg-tile" aria-hidden="true"></span>
      ${segs.map(s => `<button type="button" class="seg-btn${S.seg === s[0] ? " on" : ""}" data-xa="seg" data-seg="${s[0]}" data-k="seg-${s[0]}" aria-pressed="${S.seg === s[0]}"${s[0] !== "all" && !counts[s[0]] ? " disabled" : ""}>${s[1]}${s[0] === "all" ? "" : ` <span class="n">${counts[s[0]]}</span>`}</button>`).join("")}
    </div>
    ${drawers || `<div class="xpt-drawer"><p class="xpt-note">No folders match this switch.</p></div>`}
    <p class="xpt-note">Tap a folder to open it. Being on a list is not a promise that a parcel is still offered.</p>`;
}

const TAB_X = ["14px", "34%", "62%"];

function folderHtml(p, i, api) {
  const id = idOf(p);
  const open = S.folder === id;
  const a = acqOf(p, api);
  const amt = api.amountInfo(p);
  const has = amt.value !== null && amt.value !== undefined;
  const fig = has ? api.amountShort(p).text : (amt.display || "Not published");
  const t = titleHtml(p, api);
  const pf = open ? api.previewFacts(p) : null;
  const tabCls = a.verified ? "ok" : a.mode === "none" ? "none" : "wait";
  // The tab says the path state once; the chip under the figure says the
  // verified method (or nothing - the tab already says it is not verified).
  const tabText = a.verified ? "Verified path" : a.mode === "none" ? "No purchase path published" : "Path not yet verified";
  const chip = a.verified
    ? `<span class="xpt-chip vchip">${checkIcon()}${api.esc(a.label)}${a.steps.length ? ` · ${a.steps.length} step${a.steps.length === 1 ? "" : "s"}` : ""}</span>`
    : "";
  const face = `<span class="ftab ${tabCls}" style="left:${TAB_X[i % 3]}">${api.esc(tabText)}</span>
      <span class="face-row"><span class="face-title${t.parcel ? " parcel" : ""}">${t.html}</span>${api.isWatched(p.id) ? `<span class="rib" aria-label="On your watchlist"><svg width="14" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M6 3h12v18l-6-4.5L6 21z"/></svg></span>` : ""}</span>
      <span class="fline">${has ? `<span class="xpt-caps">${api.esc(amt.label)}</span><span class="val">${api.esc(fig)}</span>` : `<span class="xpt-caps">${api.esc(amt.label)}</span>${missing(fig, api)}`}</span>
      ${chip ? `<span class="face-chip">${chip}</span>` : ""}
      <span class="face-more">
        ${faceIdent(p, t, api)}
        <span class="xpt-small">${api.esc(api.officialStatusText(p, { omitLedger: true }))}</span>
      </span>`;
  if (!open) {
    return `<div class="xpt-fold" style="--i:${Math.min(i, 14)};--r0:${(i % 3) - 1}deg">
      <button type="button" class="fold-btn" data-xa="folder" data-pid="${api.esc(id)}" data-k="fold-${api.esc(id)}" aria-expanded="false"
        aria-label="${api.esc(`${p.county} ${api.unitWord()}. ${amt.label}: ${fig}. ${a.verified ? "Verified acquisition path." : "Acquisition path not yet verified."} Open folder.`)}">
        <span class="face xpt-obj tab-${tabCls}">${face}</span>
      </button>
    </div>`;
  }
  return `<div class="xpt-fold open" style="--i:0">
    <div class="hinge">
      <div class="inside xpt-obj">
        <span class="ftab ${tabCls}" style="left:16px">${api.esc(tabText)}</span>
        <button type="button" class="close-fold" data-xa="folder" data-pid="${api.esc(id)}" data-k="fold-${api.esc(id)}" aria-expanded="true" aria-label="Close folder and put it back">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg></button>
        <h3 class="in-title${t.parcel ? " parcel" : ""}">${t.html}</h3>
        <div class="xpt-mono-s">${api.esc([pf.parcel ? pf.parcelLabel + " " + pf.parcel : "Parcel # not published", api.caseIdentText(p)].filter(Boolean).join(" · "))}</div>
        <div class="in-fig"><span class="xpt-caps">${api.esc(amt.label)}</span>${has ? `<span class="fig-xxl">${api.esc(api.fmtMoney(amt.value))}</span>` : missing(fig, api)}</div>
        ${amt.note ? `<p class="xpt-small">${api.esc(amt.note)}</p>` : ""}
        <p class="xpt-small status"><i aria-hidden="true"></i>${api.esc(api.officialStatusText(p, { omitLedger: true }))}</p>
      </div>
      <div class="cover" aria-hidden="true"><span class="xpt-caps">Deed folder</span></div>
    </div>
    ${acquireSheetHtml(p, a, pf, api)}
  </div>`;
}

// The folder face's identifier line: the parcel when the title is a street
// address; the case when the title already is the parcel. Never the county
// (the drawer's head names it).
function faceIdent(p, t, api) {
  const text = t.parcel ? api.caseIdentText(p) : (api.parcelOf(p) ? "Parcel " + api.parcelOf(p) : "Parcel # not published");
  return text ? `<span class="xpt-mono-s">${api.esc(text)}</span>` : "";
}

function acquireSheetHtml(p, a, pf, api) {
  const id = idOf(p);
  let how;
  if (a.verified) {
    const steps = a.steps.length
      ? a.steps.map((s, i) => `<div class="insert xpt-obj" style="--id:${420 + i * 70}ms"><span class="num">${i + 1}</span><span>${api.esc(s)}</span></div>`).join("")
      : (a.instructions ? `<div class="insert xpt-obj" style="--id:420ms"><span class="num">i</span><span>${api.esc(a.instructions)}</span></div>` : "");
    const contact = [["Office", a.office], ["Phone", a.phone], ["E-mail", a.email], ["Address (in person)", a.address], ["Mailing address", a.mailing], ["Payment", a.payment]]
      .map(([k, v]) => `<div class="kv"><span class="xpt-caps">${k}</span>${v ? `<span>${api.esc(v)}</span>` : `<span>${missing("Not published", api)}</span>`}</div>`).join("");
    const docs = [];
    const appUrl = safeUrl(a.applicationUrl), pathUrl = safeUrl(a.url);
    if (appUrl) docs.push(`<a class="link-row" href="${api.esc(appUrl)}" target="_blank" rel="noopener"><span>Application / instructions document</span><span class="xpt-caps">Form</span></a>`);
    if (pathUrl && pathUrl !== appUrl) docs.push(`<a class="link-row" href="${api.esc(pathUrl)}" target="_blank" rel="noopener"><span>${api.esc(a.typeLabel || "Official page")}</span><span class="xpt-caps">Source</span></a>`);
    how = `<div class="vwrap"><span class="vstamp" aria-label="Verified official process">${checkIcon(14)}VERIFIED OFFICIAL PROCESS</span>${steps}</div>
      <div class="kvs">${contact}</div>${docs.join("")}
      ${a.mode !== "online" ? `<p class="xpt-small">No online purchase link on file.</p>` : ""}
      <p class="xpt-small">${api.esc(`Acquisition process last verified ${a.observedOn ? String(a.observedOn).slice(0, 10) : "(date not recorded)"}`)}</p>`;
  } else {
    how = `<div class="insert-blank"><span class="xpt-caps">${a.mode === "none" ? "No purchase path - the source states there is none" : "Acquisition path not yet verified"}</span>
      <span class="xpt-small">Official source: ${api.esc(pf.source || api.sourceNameFor(p) || "")}</span>
      ${linkHtml(pf.link, api, "xpt-link sage")}</div>`;
  }
  const moreRows = (pf.more || []).filter(r => !["How to acquire", "Legal"].includes(r[0])).slice(0, 8);
  return `<section class="xpt-sheet" aria-label="How to acquire">
    <div class="sec-h"><h3 class="xpt-dm">How to acquire</h3><span class="xpt-chip mode">${api.esc(a.verified ? a.label : "Not yet verified")}</span></div>
    ${how}
    <h3 class="xpt-dm sec2">On file</h3>
    <div class="facts3">${moreRows.map(r => `<div class="fact"><span class="xpt-caps">${api.esc(r[0])}</span><span class="v">${api.esc(r[1])}</span></div>`).join("")}
      <div class="fact"><span class="xpt-caps">Flood</span><span class="v">${api.esc(pf.flood ? pf.flood.text : "Not checked")}</span></div></div>
    <div class="sheet-acts">
      <button type="button" class="xpt-cta sage" data-xa="open" data-pid="${api.esc(id)}" data-k="open-${api.esc(id)}">Open full record</button>
      ${watchBtn(p, api, "xpt-watch")}
    </div>
  </section>`;
}

function checkIcon(size) {
  const s = size || 12;
  return `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>`;
}

// ------------------------------------------------------------------- LIENS

function bundleKey(p, by) {
  if (by === "county") return p.county || "";
  return p.tax_year ? String(p.tax_year) : "";
}

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
  if (S.fan !== null && !keys.slice(0, lim).includes(S.fan)) S.fan = null;
  const bundles = keys.slice(0, lim).map((k, i) => (S.fan === k ? fanHtml(k, m.get(k), api) : pileHtml(k, m.get(k), i, api))).join("");
  const sorts = [["year", "By tax year"], ["county", "By " + api.unitWord().toLowerCase()]];
  // No module header: the List title carries the certificate count and the
  // bundle labels carry the bundles.
  return `<div class="xpt-sorts" role="group" aria-label="Bundle the slips">
      ${sorts.map(s => `<button type="button" class="sort${by === s[0] ? " on" : ""}" data-xa="bundleby" data-by="${s[0]}" data-k="by-${s[0]}" aria-pressed="${by === s[0]}"><span class="xpt-chip">${api.esc(s[1])}</span></button>`).join("")}
    </div>
    <section class="xpt-shelf" aria-label="Certificate bundles">${bundles}</section>
    ${moreButton("certificate", lim, keys.length)}
    <section class="xpt-notes xpt-obj" aria-label="How to read these slips">
      <span class="xpt-caps">Reading a slip</span>
      <p class="xpt-small">A certificate is a lien on the property, not the land. Every figure sits under the source's own label; interest rate, tax year and issue date appear only when the source publishes them. Nothing here works out interest or an expiry.</p>
      <p class="xpt-small">A certificate that leaves the county list never reads as sold, redeemed or assigned unless the source says so.</p>
    </section>`;
}

function certNo(p) { return p.certificate_no ? String(p.certificate_no) : ""; }

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
  const a = api.amountShort(top);
  const edges = Math.min(3, list.length - 1);
  let edgeHtml = "";
  for (let e = edges; e >= 1; e--) edgeHtml += `<span class="edge xpt-slip" style="transform:translate(${e * 3}px,${e * 4}px) rotate(${(e % 2 ? 1 : -1) * (e * 1.1)}deg)" aria-hidden="true"></span>`;
  return `<div class="xpt-bundle" style="--i:${Math.min(i, 12)};--r0:${(i % 2 ? 1 : -1) * 2}deg">
    <button type="button" class="pile" data-xa="fan" data-key="${api.esc(k)}" data-k="fan-${api.esc(k)}" aria-expanded="false"
      aria-label="${api.esc(`${L.caps} ${L.title}: ${list.length} ${list.length === 1 ? "slip" : "slips"}. Fan the bundle out.`)}">
      ${edgeHtml}
      <span class="pile-top xpt-slip xpt-obj">
        <span class="pile-left"><span><span class="xpt-caps">Top slip</span><span class="xpt-mono-s tr">${api.esc(certNo(top) || "Certificate # not published")}</span></span>
          ${S.bundleBy === "county" ? "" : `<span class="pile-county tr">${api.esc(top.county)}</span>`}</span>
        <span class="band"><span class="xpt-caps">${api.esc(L.caps)}</span><span class="band-title">${api.esc(L.title)}</span><span class="band-count">${list.length} ${list.length === 1 ? "slip" : "slips"}</span><span class="band-sub">${api.esc(L.sub)}</span></span>
        <span class="pile-right"><span class="xpt-caps">${api.esc(a.label)}</span><span class="${a.state === "not_published" ? "nf" : "f"}">${api.esc(a.text)}</span></span>
        <span class="stub" aria-hidden="true"></span>
      </span>
    </button>
  </div>`;
}


function fanHtml(k, list, api) {
  const L = bundleLabels(k, list, api);
  const start = Math.max(0, Math.min(S.fanStart, Math.max(0, list.length - 1)));
  const win = list.slice(start, start + FAN);
  if (!win.some(p => idOf(p) === S.slip)) S.slip = idOf(win[0]);
  const n = win.length, mid = (n - 1) / 2;
  const slips = win.map((p, i) => {
    const id = idOf(p);
    const lifted = id === S.slip;
    const off = i - mid;
    const a = api.amountShort(p);
    return `<button type="button" class="fslip${lifted ? " lifted" : ""}" data-xa="slip" data-pid="${api.esc(id)}" data-k="slip-${api.esc(id)}" aria-pressed="${lifted}"
        style="--off:${off};--fd:${(i * 45)}ms;z-index:${lifted ? 30 : 10 + i}"
        aria-label="${api.esc(`Certificate ${certNo(p) || "number not published"}, ${p.county} ${api.unitWord()}. ${a.label}: ${a.text}. Lift this slip.`)}">
      <span class="fb xpt-slip xpt-obj">
        <span class="xpt-caps">Cert</span><span class="xpt-mono-s ink tr">${api.esc(certNo(p) || "Not published")}</span>
        ${S.bundleBy === "county" ? "" : `<span class="slip-county tr">${api.esc(p.county)}</span>`}
        <span class="xpt-caps lab">${api.esc(a.label)}</span><span class="${a.state === "not_published" ? "nf" : "f"}">${api.esc(a.text)}</span>
      </span>
      <span class="fs xpt-obj" aria-hidden="true"></span>
    </button>`;
  }).join("");
  const sel = win.find(p => idOf(p) === S.slip) || win[0];
  const pager = list.length > FAN ? `<div class="fan-pager">
      <button type="button" class="xpt-round sm" data-xa="fanprev" data-k="fanprev" aria-label="Previous slips"${start === 0 ? " disabled" : ""}><span><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6"/></svg></span></button>
      <span class="xpt-pager">Slips <span class="xpt-mono">${start + 1}–${start + n}</span> of <span class="xpt-mono">${list.length}</span></span>
      <button type="button" class="xpt-round sm" data-xa="fannext" data-k="fannext" aria-label="Next slips"${start + FAN >= list.length ? " disabled" : ""}><span><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg></span></button>
    </div>` : "";
  return `<div class="xpt-bundle fanned">
    <div class="fan-wrap">
      <div class="fan-stage" role="group" aria-label="${api.esc(`${L.caps} ${L.title}, fanned out`)}">
        <button type="button" class="fan-collapse" data-xa="fan" data-key="${api.esc(k)}" tabindex="-1" aria-hidden="true"></button>
        <div class="fan-band" aria-hidden="true">${api.esc(L.title)}</div>
        ${slips}
      </div>
      ${pager}
      ${trayHtml(sel, api)}
      <button type="button" class="fold-back" data-xa="fan" data-key="${api.esc(k)}" data-k="fan-${api.esc(k)}" aria-expanded="true">Bundle these slips back up</button>
    </div>
  </div>`;
}

function trayHtml(p, api) {
  const pf = api.previewFacts(p);
  const a = api.amountShort(p);
  const more = new Map(pf.more || []);
  // The bundle label already names the tax year (by year) or the county (by
  // county); the tray does not repeat it.
  const facts = [["Interest rate", more.get("Interest rate")], ...(S.bundleBy === "year" ? [] : [["Tax year", more.get("Tax year")]]), ["Issued", more.get("Issued")]];
  const extra = [];
  if (pf.parcel) extra.push([pf.parcelLabel, pf.parcel]);
  if (more.get("Listing status")) extra.push(["Listing status", more.get("Listing status")]);
  const id = idOf(p);
  return `<div class="tray xpt-obj" aria-live="polite">
    <div class="tray-head"><div><div class="tray-cert xpt-mono">Cert ${api.esc(certNo(p) || "number not published")}</div>
      <div class="xpt-small">${api.esc((S.bundleBy === "county" ? "" : p.county + " " + api.unitWord() + " · ") + api.officialStatusText(p, { omitLedger: true }))}</div></div>
      ${watchBtn(p, api, "xpt-watch ribbon")}</div>
    <div class="tray-fig"><span class="xpt-caps">${api.esc(a.label)}</span><span class="${a.state === "not_published" ? "nf" : "fig-xl"}">${api.esc(a.text)}</span></div>
    <div class="facts3">${facts.map(([k, v]) => `<div class="fact"><span class="xpt-caps">${k}</span>${v ? `<span class="v xpt-mono">${api.esc(v)}</span>` : missing("Not published", api)}</div>`).join("")}</div>
    ${extra.length ? `<div class="tray-extra">${extra.map(([k, v]) => `<span><span class="xpt-caps">${api.esc(k)}</span> ${api.esc(v)}</span>`).join("")}</div>` : ""}
    <div class="tray-acts">
      <button type="button" class="xpt-cta plum" data-xa="open" data-pid="${api.esc(id)}" data-k="open-${api.esc(id)}">${tearIcon()}Tear off &amp; open</button>
      ${linkHtml(pf.link, api, "xpt-link plum")}
    </div>
  </div>`;
}

function tearIcon() {
  return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 4h16v16H4z" stroke-dasharray="3 2"/><path d="M9 12h6M12 9v6"/></svg>`;
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
  const obj = fromEl && fromEl.closest(".xpt-placard, .xpt-fold, .fslip, .tray, .xpt-mini");
  if (obj && !reduced()) {
    obj.classList.add("xpt-opening");
    setTimeout(() => { obj.classList.remove("xpt-opening"); api.openDetail(p); }, OPEN_DELAY);
  } else api.openDetail(p);
}

function deckStep(dir, thrown) {
  const rows = S.last && S.last.rows ? S.last.rows : [];
  const lots = rows.filter(p => saleDay(p) === (S.day || ""));
  if (lots.length < 2) return;
  let idx = lots.findIndex(p => idOf(p) === S.deckId);
  if (idx < 0) idx = 0;
  const next = (idx + dir + lots.length) % lots.length;
  const go = () => {
    S.deckId = idOf(lots[next]);
    S.deckAnim = { id: S.deckId, cls: dir > 0 ? "landing" : "returning" };
    if (S.limit.auction <= next) S.limit.auction = Math.ceil((next + 1) / PAGE) * PAGE;
    updateDeck();
    const t = stageEl() && stageEl().querySelector(".xpt-mini.on");
    if (t && t.scrollIntoView) { try { t.scrollIntoView({ block: "nearest", inline: "nearest" }); } catch {} }
  };
  const top = stageEl() && stageEl().querySelector(".xpt-deck .xpt-placard");
  if (thrown) go();
  else if (top && !reduced()) {
    top.classList.add(dir > 0 ? "thrown" : "thrown-back");
    setTimeout(go, 240);
  } else go();
}

function onClick(e) {
  const stage = stageEl();
  if (!stage || stage.dataset.xp !== NAME || !isActive()) return;
  const el = e.target.closest("[data-xa]");
  if (!el || !stage.contains(el)) return;
  const xa = el.dataset.xa, pid = el.dataset.pid;
  switch (xa) {
    case "cmore": {
      const c = el.dataset.county || "";
      S.cLim.set(c, (S.cLim.get(c) || CPAGE) + PAGE);
      redraw();
      break;
    }
    case "more": {
      const k = el.dataset.ledger;
      if (S.limit[k]) S.limit[k] += PAGE;
      redraw();
      break;
    }
    case "day":
      if (S.day !== el.dataset.day) { S.day = el.dataset.day; S.deckId = null; S.limit.auction = PAGE; S.deckAnim = null; redraw(); }
      break;
    case "flip": {
      const card = el.closest(".xpt-placard");
      if (S.flipped.has(pid)) S.flipped.delete(pid); else S.flipped.add(pid);
      if (card) {
        // Animate in place, then let the next draw keep the state.
        card.classList.toggle("flipped", S.flipped.has(pid));
        card.classList.remove("lift-a", "lift-b");
        void card.offsetWidth;
        card.classList.add(S.flipped.has(pid) ? "lift-a" : "lift-b");
        const front = card.querySelector(".face.front"), back = card.querySelector(".face.back");
        const fl = S.flipped.has(pid);
        if (front) { front.setAttribute("aria-pressed", String(fl)); if (fl) { front.setAttribute("tabindex", "-1"); front.setAttribute("aria-hidden", "true"); } else { front.removeAttribute("tabindex"); front.removeAttribute("aria-hidden"); } }
        if (back) {
          if (fl) back.removeAttribute("aria-hidden"); else back.setAttribute("aria-hidden", "true");
          back.querySelectorAll("button, a").forEach(b => { if (fl) b.removeAttribute("tabindex"); else b.setAttribute("tabindex", "-1"); });
        }
        const focusTo = fl ? card.querySelector(".back-head") : front;
        if (focusTo) setTimeout(() => { try { focusTo.focus({ preventScroll: true }); } catch {} }, reduced() ? 0 : 320);
      } else redraw();
      break;
    }
    case "prev": deckStep(-1); break;
    case "next": deckStep(1); break;
    case "pick":
      if (S.deckId === pid) break;
      S.deckId = pid;
      S.deckAnim = { id: pid, cls: "landing" };
      updateDeck();
      {
        const deck = stage.querySelector(".xpt-deck");
        if (deck && deck.getBoundingClientRect().top < 0 && deck.scrollIntoView) { try { deck.scrollIntoView({ block: "start", behavior: reduced() ? "auto" : "smooth" }); } catch {} }
      }
      break;
    case "open": openRecord(pid, el); break;
    case "seg":
      if (S.seg !== el.dataset.seg) { S.seg = el.dataset.seg; S.limit.laft = PAGE; S.cLim.clear(); S.folder = null; redraw(); }
      break;
    case "folder":
      S.folder = S.folder === pid ? null : pid;
      redraw();
      if (S.folder) {
        const f = stage.querySelector(".xpt-fold.open");
        if (f && f.scrollIntoView) { try { f.scrollIntoView({ block: "nearest", behavior: reduced() ? "auto" : "smooth" }); } catch {} }
        const c = stage.querySelector(".xpt-fold.open .close-fold");
        if (c) { try { c.focus({ preventScroll: true }); } catch {} }
      }
      break;
    case "bundleby":
      if (S.bundleBy !== el.dataset.by) { S.bundleBy = el.dataset.by; S.fan = null; S.slip = null; S.fanStart = 0; S.limit.certificate = PAGE; redraw(); }
      break;
    case "fan": {
      const k = el.dataset.key;
      S.fan = S.fan === k ? null : k;
      S.fanStart = 0; S.slip = null;
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
  if (e.key !== "Escape") return;
  const stage = stageEl();
  if (!stage || stage.dataset.xp !== NAME || !isActive()) return;
  if (!stage.contains(document.activeElement)) return;
  if (S.folder) { const id = S.folder; S.folder = null; redraw(); const b = stage.querySelector(`[data-k="fold-${id.replace(/["\\]/g, "")}"]`); if (b) b.focus(); }
  else if (S.fan !== null) { const k = S.fan; S.fan = null; redraw(); const b = stage.querySelector(`[data-k="fan-${String(k).replace(/["\\]/g, "")}"]`); if (b) b.focus(); }
}

// ------------------------------------------------------------------ wiring

document.addEventListener("click", e => {
  const stage = stageEl();
  const k = stage && stage.dataset.xp === NAME && e.target.closest ? e.target.closest("[data-k]") : null;
  S.pressed = k && stage.contains(k) ? k.getAttribute("data-k") : null;
}, true);
document.addEventListener("click", onClick);

// Swipe the top placard left / right to move through the deck (2026-10-28).
// The placard follows the finger; past SWIPE_PX it is thrown off and the next
// lot lands, otherwise it springs back. A vertical drag still scrolls the page
// (touch-action: pan-y on the deck), and the click a drag ends with is not
// taken as a flip.
const SWIPE_PX = 64;
const DRAG = { id: null, x: 0, y: 0, dx: 0, on: false, card: null, suppressClick: false };
document.addEventListener("pointerdown", e => {
  const stage = stageEl();
  if (!stage || stage.dataset.xp !== NAME || !isActive() || S.ledger !== "auction") return;
  if (e.pointerType === "mouse" && e.button !== 0) return;
  const card = e.target.closest && e.target.closest(".xpt-deck .xpt-placard");
  if (!card || !stage.contains(card) || e.target.closest(".back-scroll, .acts, a")) return;
  DRAG.id = e.pointerId; DRAG.x = e.clientX; DRAG.y = e.clientY; DRAG.dx = 0; DRAG.on = false; DRAG.card = card;
});
document.addEventListener("pointermove", e => {
  if (DRAG.id !== e.pointerId || !DRAG.card) return;
  const dx = e.clientX - DRAG.x, dy = e.clientY - DRAG.y;
  if (!DRAG.on) {
    if (Math.abs(dx) < 10 || Math.abs(dx) < Math.abs(dy) * 1.2) { if (Math.abs(dy) > 12) DRAG.id = null; return; }
    DRAG.on = true;
    DRAG.card.classList.add("dragging");
  }
  DRAG.dx = dx;
  DRAG.card.style.transform = `translateX(${dx}px) rotate(${Math.max(-12, Math.min(12, dx / 18))}deg)`;
});
function endDrag(e) {
  if (DRAG.id !== e.pointerId) return;
  const card = DRAG.card, dx = DRAG.dx, was = DRAG.on;
  DRAG.id = null; DRAG.card = null; DRAG.on = false;
  if (!card || !was) return;
  DRAG.suppressClick = true;
  setTimeout(() => { DRAG.suppressClick = false; }, 0);
  card.classList.remove("dragging");
  const lots = (S.last && S.last.rows ? S.last.rows : []).filter(p => saleDay(p) === (S.day || ""));
  if (Math.abs(dx) >= SWIPE_PX && lots.length > 1) {
    const dir = dx < 0 ? 1 : -1;
    if (reduced()) { card.style.transform = ""; deckStep(dir, true); return; }
    card.style.transition = "transform 200ms ease-in, opacity 200ms ease-in";
    card.style.transform = `translateX(${dx < 0 ? -460 : 460}px) rotate(${dx < 0 ? -14 : 14}deg)`;
    card.style.opacity = "0";
    setTimeout(() => deckStep(dir, true), 190);
  } else {
    card.style.transition = "transform 260ms cubic-bezier(.2,.9,.3,1.2)";
    card.style.transform = "";
    setTimeout(() => { card.style.transition = ""; }, 280);
  }
}
document.addEventListener("pointerup", endDrag);
document.addEventListener("pointercancel", endDrag);
// The click that ends a swipe is not a flip.
document.addEventListener("click", e => {
  if (DRAG.suppressClick && e.target.closest && e.target.closest(".xpt-deck")) { e.stopImmediatePropagation(); e.preventDefault(); DRAG.suppressClick = false; }
}, true);
document.addEventListener("keydown", onKey);
window.addEventListener("tdw:rendered", e => draw(e.detail));
window.addEventListener("tdw:experience", () => { if (isActive()) { if (window.__tdwLastRender) draw(window.__tdwLastRender); } else deactivate(); });
if (isActive() && window.__tdwLastRender) draw(window.__tdwLastRender);
else if (!isActive()) deactivate();
