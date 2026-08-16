import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const cfg = window.TDW_CONFIG || {};
if (!cfg.supabaseUrl || cfg.supabaseUrl.includes("YOUR-PROJECT-REF")) {
  document.body.innerHTML = '<div style="padding:2rem;font-family:sans-serif">' +
    '<h2>Not configured</h2><p>Edit <code>config.js</code> with your Supabase project URL and publishable key, then redeploy.</p></div>';
  throw new Error("config.js not filled in");
}

// supabasePublishableKey replaces the old supabaseAnonKey - same client-side
// role (safe to expose, RLS still gates every table), new sb_publishable_...
// format instead of the legacy long-lived JWT anon token.
const sb = createClient(cfg.supabaseUrl, cfg.supabasePublishableKey, {
  auth: {
    storage: window.sessionStorage,
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: false
  }
});

const BUILD = "v6 - 2026-08-06";
const IDLE_MINUTES = 5;

const DOC_STAMP_RATE = 0.007;
const RECORDING_FEE = 30;
const QUIET_TITLE_EST = 3000;
const TOP_PICK_RATIO = 12;
const SOON_DAYS = 14;

const GONE_HOURS_DEFAULT = 24;
const GONE_HOURS_FLAGGED = 48;
const GONE_STATUSES = ["dropped", "sold", "notfound"];
const isGone = p => GONE_STATUSES.includes(p.status);

const TYPE_ORDER = ["House", "Condo", "Townhome", "Mobile/Manuf.", "Vacant Lot", "Commercial", "Unknown"];
const LIEN_ORDER = ["clean", "flag", "serious", "unscreened"];
const LIEN_LABEL = { clean: "Clear", flag: "Flag", serious: "Serious", unscreened: "Unscreened" };
const STAGES = ["", "researched", "drove by", "called clerk", "bidding", "won", "passed"];

const COUNTY_INFO = {
  "Brevard":{fmt:"Online",note:"Deposit required in advance via the auction site."},
  "Indian River":{fmt:"Online",note:"Deposit required in advance via the auction site."},
  "Osceola":{fmt:"Online",note:"Deposit required in advance via the auction site."},
  "Seminole":{fmt:"Online",note:"Deposit required in advance via the auction site."},
  "Pasco":{fmt:"Online",note:"Deposit required in advance via the auction site."},
  "Polk":{fmt:"Online",note:"Deposit required in advance via the auction site."},
  "Lee":{fmt:"Online",note:"Deposit required in advance via the auction site."},
  "Charlotte":{fmt:"Shared site with foreclosure sales - confirm you are on a TAXDEED auction."},
  "Orange":{fmt:"Online",note:"Deposit required in advance via the auction site."},
  "Palm Beach":{fmt:"Three sale dates in play - check each property's own date."},
  "DeSoto":{fmt:"In person",note:"11:00am, DeSoto County Courthouse, 115 E Oak St, Arcadia. Register by 10:30am with 5% of your highest bid."},
  "Collier":{fmt:"In person",note:"1:00pm, Collier County Courthouse, 1st floor. Arrive 15 min early."},
  "Hendry":{fmt:"In person",note:"Not on Realauction - Clerk runs the sale from a PDF notice. (863) 675-5217."},
  "Hillsborough":{fmt:"Fixed price",note:"Lands Available parcels only - bought directly from the Clerk."},
  "Glades":{fmt:"In person",note:"No sale currently scheduled."}
};

let ALL = [], CALENDAR = {}, NOTES = {}, FAVS = new Set(), HIDDEN = new Set(), ME = null;

const LEDGERS = {
  auction: { title: "Auctions & Bidding", sub: "Open to competitive bidding." },
  laft: { title: "Lands Available", sub: "Fixed price from Clerk." },
  certificate: { title: "Tax Certificates", sub: "County-held liens available for direct purchase - not property." }
};

const state = {
  bidMin: null, bidMax: null, assessedMin: null,
  sortBy: "county", favoritesOnly: false, topPicksOnly: false, soonOnly: false,
  includeQT: false, maxBidPct: 40,
  statusView: "all",
  ledger: "auction",
  counties: new Set(), types: new Set(TYPE_ORDER), liens: new Set(LIEN_ORDER)
};

function goneExpired(p) {
  if (!isGone(p) || !p.gone_since) return false;
  const flagged = FAVS.has(p.id) || (NOTES[p.id] || []).some(n => n.body || n.stage);
  const hours = flagged ? GONE_HOURS_FLAGGED : GONE_HOURS_DEFAULT;
  return (Date.now() - Date.parse(p.gone_since)) > hours * 3600 * 1000;
}

const fmtMoney = n => "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtShort = n => "$" + Math.round(Number(n)).toLocaleString("en-US");
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function propType(p) {
  const s = (p.prop_type || "").toLowerCase();
  if (!s || s.includes("unknown")) return "Unknown";
  if (s.includes("vacant")) return "Vacant Lot";
  if (s.includes("mobile") || s.includes("manuf") || /\bmh\b/.test(s)) return "Mobile/Manuf.";
  if (s.includes("townhome")) return "Townhome";
  if (s.includes("condo")) return "Condo";
  if (s.includes("store") || s.includes("office") || s.includes("comm")) return "Commercial";
  if (s.includes("sfr") || s.includes("duplex") || /\d\s*\/\s*\d/.test(s)) return "House";
  return "Unknown";
}

const marketOf = p => Number(p.market || p.assessed || 0);
const valueRatio = p => (Number(p.bid) > 0 ? marketOf(p) / Number(p.bid) : 0);
const isTopPick = p => p.lien_level === "clean" && valueRatio(p) >= TOP_PICK_RATIO;
const homesteadSurcharge = p => (p.homestead ? Number(p.assessed || 0) / 2 : 0);
function trueCost(p) {
  const base = Number(p.bid) + homesteadSurcharge(p);
  return base + base * DOC_STAMP_RATE + RECORDING_FEE + (state.includeQT ? QUIET_TITLE_EST : 0);
}
const maxBid = p => marketOf(p) * (state.maxBidPct / 100);
function daysUntil(p) {
  if (!p.sale_date) return null;
  const d = new Date(p.sale_date + "T00:00:00");
  return Math.ceil((d - new Date().setHours(0, 0, 0, 0)) / 86400000);
}
function saleTime(p) {
  if (!p.sale_date) return Infinity;
  const t = Date.parse(p.sale_date);
  return isNaN(t) ? Infinity : t;
}
const countyNames = () => Array.from(new Set(ALL.map(p => p.county)));
const fmtDate = d => new Date(d + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

const gate = document.getElementById("authGate");
const app = document.getElementById("app");
const authMsg = document.getElementById("authMsg");

const authForm = document.getElementById("authForm");
if (authForm) {
  authForm.addEventListener("submit", async e => {
    e.preventDefault();
    const btn = document.getElementById("signInBtn");
    if (btn) btn.disabled = true;
    if (authMsg) {
      authMsg.className = "auth-msg";
      authMsg.textContent = "Signing in";
    }
    const { error } = await sb.auth.signInWithPassword({
      email: document.getElementById("email").value.trim(),
      password: document.getElementById("password").value
    });
    if (btn) btn.disabled = false;
    if (error && authMsg) {
      authMsg.className = "auth-msg err";
      authMsg.textContent = error.message;
    }
  });
}

const signOutBtn = document.getElementById("signOutBtn");
if (signOutBtn) {
  signOutBtn.addEventListener("click", () => doSignOut(null));
}

async function doSignOut(reason) {
  stopIdleWatch();
  if (reason) sessionStorage.setItem("tdw_signout_reason", reason);
  await sb.auth.signOut();
  location.reload();
}

let lastActivity = Date.now();
let tick = null;
function markActive() { lastActivity = Date.now(); }
function stopIdleWatch() { if (tick) { clearInterval(tick); tick = null; } }
function startIdleWatch() {
  stopIdleWatch();
  markActive();
  tick = setInterval(() => { if (!ME) return; if (Date.now() - lastActivity >= IDLE_MINUTES * 60 * 1000) doSignOut("idle"); }, 5000);
}

["mousemove", "mousedown", "keydown", "touchstart", "wheel", "scroll"].forEach(ev => window.addEventListener(ev, markActive, { passive: true, capture: true }));
document.addEventListener("visibilitychange", () => { if (!document.hidden) markActive(); });

sb.auth.onAuthStateChange((_e, session) => {
  if (session && session.user) { ME = session.user; showApp(); }
  else if (gate && app) { gate.hidden = false; app.hidden = true; }
});

(async () => {
  const { data } = await sb.auth.getSession();
  if (data.session) { ME = data.session.user; showApp(); }
  else if (gate) {
    gate.hidden = false;
    const why = sessionStorage.getItem("tdw_signout_reason");
    if (why === "idle" && authMsg) { authMsg.textContent = `Signed out after ${IDLE_MINUTES} minutes of inactivity.`; sessionStorage.removeItem("tdw_signout_reason"); }
  }
})();

async function showApp() {
  if (gate) gate.hidden = true;
  if (app) app.hidden = false;
  const genEl = document.getElementById("generatedAt");
  if (genEl) genEl.textContent = "Loading";
  await loadAll();
  state.counties = new Set(countyNames());
  buildAllChips();
  updateBadge();
  render();
  startIdleWatch();
}

async function loadAll() {
  const today = new Date().toISOString().slice(0, 10);
  const [props, notes, favs, hid, cal] = await Promise.all([
    sb.from("properties").select("*").order("county").order("case_no"),
    sb.from("notes").select("*"),
    sb.from("favorites").select("property_id"),
    sb.from("hidden").select("property_id"),
    sb.from("county_calendar").select("county,sale_date").gte("sale_date", today).order("sale_date")
  ]);
  if (props.error) { 
    const genEl = document.getElementById("generatedAt");
    if (genEl) genEl.textContent = "Error: " + props.error.message; 
    return; 
  }
  ALL = props.data || [];
  NOTES = {}; (notes.data || []).forEach(n => { (NOTES[n.property_id] = NOTES[n.property_id] || []).push(n); });
  FAVS = new Set((favs.data || []).map(r => r.property_id));
  HIDDEN = new Set((hid.data || []).map(r => r.property_id));
  CALENDAR = {}; if (!cal.error) { (cal.data || []).forEach(r => { (CALENDAR[r.county] = CALENDAR[r.county] || []).push(r.sale_date); }); }
  const newest = ALL.reduce((a, p) => (p.updated_at > a ? p.updated_at : a), "");
  const genEl = document.getElementById("generatedAt");
  const eyeEl = document.getElementById("eyebrow");
  if (genEl) genEl.textContent = newest ? "Data updated " + new Date(newest).toLocaleString() : "No data yet.";
  if (eyeEl) eyeEl.textContent = "Field Ledger - " + countyNames().length + " Counties - " + BUILD;
}

// County chips and the county map (below) both drive state.counties, so a
// click on either one has to keep the other in sync - route both through
// this single toggle instead of mutating the set in two places.
function toggleCounty(name) {
  if (state.counties.has(name)) state.counties.delete(name); else state.counties.add(name);
  const on = state.counties.has(name);
  document.querySelectorAll('#countyChips .chipx').forEach(c => { if (c.dataset.value === name) c.classList.toggle("on", on); });
  if (mapLoaded) document.querySelectorAll('#mapHost path[data-county]').forEach(p => { if (p.dataset.county === name) p.classList.toggle("sel", on); });
  updateBadge();
  render();
}

function buildChips(id, values, set, labelFn, classFn) {
  const el = document.getElementById(id); if (!el) return; el.innerHTML = "";
  values.forEach(v => {
    const c = document.createElement("span");
    c.className = "chipx" + (set.has(v) ? " on" : "") + (classFn ? " " + classFn(v) : "");
    c.textContent = labelFn ? labelFn(v) : v; c.dataset.value = v;
    c.addEventListener("click", () => {
      if (id === "countyChips") { toggleCounty(v); return; }
      set.has(v) ? set.delete(v) : set.add(v);
      c.classList.toggle("on");
      updateBadge(); render();
    });
    el.appendChild(c);
  });
}

// County chips carry a "(n)" count and sort busiest-first, so the picker
// itself answers "how many properties does this county have" instead of
// just being an alphabetical toggle list.
function countyCounts() {
  const m = new Map();
  ALL.forEach(p => m.set(p.county, (m.get(p.county) || 0) + 1));
  return m;
}
function countyNamesByCount() {
  const counts = countyCounts();
  return countyNames().slice().sort((a, b) => (counts.get(b) || 0) - (counts.get(a) || 0) || a.localeCompare(b));
}
function buildAllChips() {
  const counts = countyCounts();
  buildChips("countyChips", countyNamesByCount(), state.counties, v => `${v} (${counts.get(v) || 0})`);
  buildChips("typeChips", TYPE_ORDER, state.types);
  buildChips("lienChips", LIEN_ORDER, state.liens, v => LIEN_LABEL[v], v => "lien-" + v);
}

function passes(p) {
  if (HIDDEN.has(p.id) || goneExpired(p)) return false;
  if (state.statusView === "gone" && !isGone(p)) return false;
  if (state.statusView === "live" && isGone(p)) return false;
  if (state.favoritesOnly && !FAVS.has(p.id)) return false;
  if (state.topPicksOnly && !isTopPick(p)) return false;
  if (state.soonOnly) { const d = daysUntil(p); if (d === null || d < 0 || d > SOON_DAYS) return false; }
  if (!state.counties.has(p.county)) return false;
  // Certificates aren't screened for title and don't have a property type -
  // the type/lien chip filters only make sense for deed/LAFT rows.
  if (p.source !== "certificate" && (!state.types.has(propType(p)) || !state.liens.has(p.lien_level))) return false;
  if ((state.bidMin !== null && Number(p.bid) < state.bidMin) || (state.bidMax !== null && Number(p.bid) > state.bidMax)) return false;
  if (p.source !== "certificate" && state.assessedMin !== null && Number(p.assessed || 0) < state.assessedMin) return false;
  return true;
}

function noteHtml(p) {
  const rows = (NOTES[p.id] || []).slice().sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
  const mine = ME ? rows.find(n => n.author_id === ME.id) : null;
  const others = ME ? rows.filter(n => n.author_id !== ME.id) : rows;
  const list = others.map(n => `<div class="note-item"><span class="note-author">${esc((n.author_email || "teammate").split("@")[0])}</span>${n.stage ? `<span class="note-stage-tag">${esc(n.stage)}</span>` : ""}<br>${esc(n.body || "")}</div>`).join("");
  return `
  <div class="notes-block">
    <div class="notes-head"><span>Team notes${rows.length ? " (" + rows.length + ")" : ""}</span></div>
    ${list}
    <div class="note-editor">
      <select data-role="stage" data-pid="${p.id}">${STAGES.map(s => `<option value="${s}"${mine && mine.stage === s ? " selected" : ""}>${s === "" ? " - stage - " : s}</option>`).join("")}</select>
      <textarea data-role="body" data-pid="${p.id}" rows="2" placeholder="Your note">${esc(mine ? mine.body : "")}</textarea>
      <button class="note-save" data-action="savenote" data-pid="${p.id}" type="button">Save note</button>
    </div>
  </div>`;
}

function card(p, showCounty) {
  const el = document.createElement("div");
  const fav = FAVS.has(p.id), top = isTopPick(p);
  el.className = "prop-card" + (fav ? " favorited" : "") + (top ? " toppick" : "");
  const d = daysUntil(p);
  let cd = "";
  if (d !== null && d >= 0) { const cls = d <= 3 ? "urgent" : d <= SOON_DAYS ? "soon" : ""; cd = `<span class="countdown ${cls}">${d === 0 ? "TODAY" : d + "d"}</span>`; }
  const tag = showCounty ? `<div class="prop-county-tag">${esc(p.county)}${p.sale_date ? " - " + fmtDate(p.sale_date) : ""}</div>` : (p.sale_date ? `<div class="prop-county-tag">Sale ${new Date(p.sale_date + "T00:00:00").toLocaleDateString("en-US", { month: "short", day: "numeric" })}</div>` : "");

  const hasAddress = p.address && p.address.trim();
  const titleLine = hasAddress ? esc(p.address) : `Parcel #${esc(p.parcel || "Unknown")} (${esc(p.county)} County Lot)`;
  const hasBid = p.bid !== null && p.bid !== undefined;

  el.innerHTML = `
    ${top ? `<div class="toppick-banner"> Top pick <span class="ratio-pill">${valueRatio(p).toFixed(1)}- market vs bid</span></div>` : ""}
    ${tag}
    <div class="prop-top">
      <div class="prop-address">${titleLine}</div>
      <div class="prop-top-actions">
        <button class="icon-btn heart-btn${fav ? " on" : ""}" data-action="fav" data-pid="${p.id}" type="button" title="Favorite">${fav ? "♥" : "♡"}</button>
        <button class="icon-btn remove-btn" data-action="hide" data-pid="${p.id}" type="button" title="Hide">✕</button>
        ${cd}
        <span class="pill ${esc(p.status)}">${esc(p.status)}</span>
      </div>
    </div>
    <div class="prop-meta">
      <span>Parcel #${esc(p.parcel || "Unknown")}</span>
      <span class="meta-bid">Bid ${hasBid ? fmtMoney(p.bid) : "N/A"}</span>
      <span class="meta-assessed">Assessed ${p.assessed ? fmtShort(p.assessed) : "N/A"}</span>
      <span class="meta-market">Market ${p.market ? fmtShort(p.market) : "N/A"}</span>
    </div>
    ${hasBid ? `
    <div class="cost-row">
      <span class="cost-item"><span class="cost-tag">True cost</span> <b>${fmtShort(trueCost(p))}</b></span>
      <span class="cost-item ${Number(p.bid) > maxBid(p) ? "over" : "under"}"><span class="cost-tag">Walk away above</span> <b>${fmtShort(maxBid(p))}</b></span>
    </div>` : ""}
    <div class="lien-banner ${esc(p.lien_level)}">
      <div class="lien-toprow"><span class="lien-label">Title: ${LIEN_LABEL[p.lien_level] || p.lien_level}</span><span class="type-badge">${esc(p.prop_type || "Type: Unknown")}</span></div>
      <span class="lien-text">${esc(p.lien_note || "")}</span>
    </div>
    <div class="copy-row">
      <button class="copy-btn owner-tag${p.owner_name ? "" : " unknown"}" ${p.owner_name ? `data-action="copy" data-copy="${esc(p.owner_name)}"` : ""} type="button"><span class="copy-tag">Owner</span><span class="copy-val">${esc(p.owner_name || "Unknown")}</span></button>
      ${p.parcel ? `<button class="copy-btn" data-action="copy" data-copy="${esc(p.parcel)}" type="button"><span class="copy-tag">Parcel</span><span class="copy-val">${esc(p.parcel)}</span></button>` : ""}
    </div>
    <div class="prop-links">
      ${p.url_streetview ? `<a href="${esc(p.url_streetview)}" target="_blank" rel="noopener">Street View</a>` : ''}
      ${p.url_appraiser ? `<a href="${esc(p.url_appraiser)}" target="_blank" rel="noopener">Appraiser</a>` : ''}
      ${p.url_zillow ? `<a href="${esc(p.url_zillow)}" target="_blank" rel="noopener">Zillow</a>` : ''}
      ${p.url_taxcoll ? `<a href="${esc(p.url_taxcoll)}" target="_blank" rel="noopener">Collector</a>` : ''}
      ${p.url_auction ? `<a href="${esc(p.url_auction)}" target="_blank" rel="noopener">${p.source === "laft" ? "LAFT" : "Auction"}</a>` : ''}
      ${p.url_title ? `<a href="${esc(p.url_title)}" target="_blank" rel="noopener">Title Search</a>` : ''}
    </div>
    ${p.url_auction ? `<a class="cta-btn" href="${esc(p.url_auction)}" target="_blank" rel="noopener">${p.source === "laft" ? "View Lands Available Listing" : "Bid on County Auction Site"}</a>` : ''}
    ${noteHtml(p)}`;
  return el;
}

const CERT_SOON_DAYS = 90;
function certDaysUntil(dateStr) {
  if (!dateStr) return null;
  const d = new Date(dateStr + "T00:00:00");
  if (isNaN(d)) return null;
  return Math.ceil((d - new Date().setHours(0, 0, 0, 0)) / 86400000);
}

// Certificates are liens, not property - no address/owner/assessed/lien
// screening the way deed and LAFT rows have, but they do have a redemption
// clock (expiration_date) that matters more than anything else on the card.
function certCard(p, showCounty) {
  const el = document.createElement("div");
  const fav = FAVS.has(p.id);
  el.className = "prop-card cert-card" + (fav ? " favorited" : "");
  const tag = showCounty ? `<div class="prop-county-tag">${esc(p.county)} County - Certificate</div>` : "";
  const expDays = certDaysUntil(p.expiration_date);
  let cd = "";
  if (expDays !== null && expDays >= 0) {
    const cls = expDays <= 30 ? "urgent" : expDays <= CERT_SOON_DAYS ? "soon" : "";
    cd = `<span class="countdown ${cls}">${expDays === 0 ? "TODAY" : expDays + "d to expire"}</span>`;
  }

  el.innerHTML = `
    ${tag}
    <div class="prop-top">
      <div class="prop-address">Certificate #${esc(p.certificate_no || "Unknown")}</div>
      <div class="prop-top-actions">
        <button class="icon-btn heart-btn${fav ? " on" : ""}" data-action="fav" data-pid="${p.id}" type="button" title="Favorite">${fav ? "♥" : "♡"}</button>
        <button class="icon-btn remove-btn" data-action="hide" data-pid="${p.id}" type="button" title="Hide">✕</button>
        ${cd}
      </div>
    </div>
    <div class="prop-meta">
      <span>Account #${esc(p.case_no || "Unknown")}</span>
      <span>Tax year ${esc(p.tax_year || "N/A")}</span>
      <span class="meta-bid">Amount ${p.bid ? fmtMoney(p.bid) : "N/A"}</span>
      ${p.interest_rate ? `<span>Rate ${esc(p.interest_rate)}%</span>` : ""}
    </div>
    <div class="prop-meta">
      <span>Issued ${p.issued_date ? fmtDate(p.issued_date) : "N/A"}</span>
      <span>Expires ${p.expiration_date ? fmtDate(p.expiration_date) : "N/A"}</span>
    </div>
    <div class="copy-row">
      <button class="copy-btn" data-action="copy" data-copy="${esc(p.case_no || "")}" type="button"><span class="copy-tag">Account</span><span class="copy-val">${esc(p.case_no || "Unknown")}</span></button>
    </div>
    ${p.url_auction ? `<a class="cta-btn" href="${esc(p.url_auction)}" target="_blank" rel="noopener">View on County-Held Liens List</a>` : ''}
    ${noteHtml(p)}`;
  return el;
}

// Card-level actions: favorite, hide, copy-to-clipboard, save note. Nothing
// wired these up before, so the buttons on the card were dead clicks.
document.addEventListener("click", async e => {
  const btn = e.target.closest("[data-action]");
  if (!btn) return;
  const action = btn.dataset.action;
  const pid = btn.dataset.pid;

  if (action === "fav") {
    if (!ME || !pid) return;
    btn.disabled = true;
    if (FAVS.has(pid)) {
      const { error } = await sb.from("favorites").delete().eq("user_id", ME.id).eq("property_id", pid);
      if (!error) FAVS.delete(pid);
    } else {
      const { error } = await sb.from("favorites").insert({ user_id: ME.id, property_id: pid });
      if (!error) FAVS.add(pid);
    }
    render();
  } else if (action === "hide") {
    if (!ME || !pid) return;
    btn.disabled = true;
    const { error } = await sb.from("hidden").insert({ user_id: ME.id, property_id: pid });
    if (!error) { HIDDEN.add(pid); render(); } else { btn.disabled = false; }
  } else if (action === "copy") {
    const val = btn.dataset.copy;
    if (!val) return;
    try {
      await navigator.clipboard.writeText(val);
      btn.classList.add("copied");
      setTimeout(() => btn.classList.remove("copied"), 1200);
    } catch { /* clipboard permission denied - fail quietly */ }
  } else if (action === "savenote") {
    if (!ME || !pid) return;
    const cardEl = btn.closest(".prop-card");
    if (!cardEl) return;
    const stageEl = cardEl.querySelector(`[data-role="stage"][data-pid="${pid}"]`);
    const bodyEl = cardEl.querySelector(`[data-role="body"][data-pid="${pid}"]`);
    const stage = stageEl ? stageEl.value : "";
    const body = bodyEl ? bodyEl.value.trim() : "";
    btn.disabled = true;
    const { error } = await sb.from("notes").upsert(
      { property_id: pid, author_id: ME.id, author_email: ME.email, stage, body },
      { onConflict: "property_id,author_id" }
    );
    if (error) { btn.disabled = false; return; }
    const rows = NOTES[pid] || (NOTES[pid] = []);
    const mine = rows.find(n => n.author_id === ME.id);
    const now = new Date().toISOString();
    if (mine) { mine.stage = stage; mine.body = body; mine.updated_at = now; }
    else rows.push({ property_id: pid, author_id: ME.id, author_email: ME.email, stage, body, updated_at: now });
    btn.textContent = "Saved ✓";
    btn.classList.add("saved");
    setTimeout(render, 700);
  }
});

// Three separate ledgers (Auctions, Lands Available, Certificates), one
// visible at a time via the tab bar - not one long page where Lands
// Available sat under 300+ auction cards and read as "not populated"
// because nobody scrolled that far to find it.
function render() {
  const main = document.getElementById("main"); if (!main) return; main.innerHTML = "";
  if (!LEDGERS[state.ledger]) state.ledger = "auction";
  const activeLedger = state.ledger;
  const cfg = LEDGERS[activeLedger];
  const inLedger = p => p.source === activeLedger;
  section(main, cfg.title, cfg.sub, ALL.filter(inLedger), activeLedger);

  const tabCounts = { auction: 0, laft: 0, certificate: 0 };
  ALL.forEach(p => { if (p.source in tabCounts) tabCounts[p.source]++; });
  document.querySelectorAll("#ledgerTabs .ledger-tab").forEach(btn => {
    const src = btn.dataset.ledger;
    btn.classList.toggle("on", src === activeLedger);
    const countEl = document.getElementById("tabCount" + src[0].toUpperCase() + src.slice(1));
    if (countEl) countEl.textContent = tabCounts[src] || 0;
  });

  const pool = ALL.filter(inLedger).filter(passes);

  const chipTotal = document.getElementById("chipTotal");
  if (chipTotal) chipTotal.textContent = pool.length;

  // Active/Gone counts ignore the current statusView (and are scoped to the
  // active ledger, same as Shown) so both chips stay meaningful no matter
  // which one is currently selected.
  const savedView = state.statusView;
  state.statusView = "live";
  const activeCount = ALL.filter(inLedger).filter(passes).length;
  state.statusView = "gone";
  const goneCount = ALL.filter(inLedger).filter(passes).length;
  state.statusView = savedView;
  const chipActive = document.getElementById("chipActive");
  if (chipActive) chipActive.textContent = activeCount;
  const chipGone = document.getElementById("chipGone");
  if (chipGone) chipGone.textContent = goneCount;
  document.querySelectorAll(".summary-strip .chip[data-status]").forEach(c => c.classList.toggle("on", c.dataset.status === state.statusView));

  const hiddenInfo = document.getElementById("hiddenInfo");
  if (hiddenInfo) hiddenInfo.hidden = HIDDEN.size === 0;

  const hiddenCount = document.getElementById("hiddenCount");
  if (hiddenCount) hiddenCount.textContent = HIDDEN.size;
}

function sortRows(rows) {
  const cmp = {
    dateAsc: (a, b) => saleTime(a) - saleTime(b),
    dateDesc: (a, b) => saleTime(b) - saleTime(a),
    bidAsc: (a, b) => Number(a.bid || 0) - Number(b.bid || 0),
    bidDesc: (a, b) => Number(b.bid || 0) - Number(a.bid || 0),
    assessedAsc: (a, b) => Number(a.assessed || 0) - Number(b.assessed || 0),
    assessedDesc: (a, b) => Number(b.assessed || 0) - Number(a.assessed || 0),
    spreadDesc: (a, b) => valueRatio(b) - valueRatio(a),
    address: (a, b) => (a.address || "").localeCompare(b.address || "")
  }[state.sortBy];
  // "county" (default) keeps the query's own county/case_no order - no sort.
  return cmp ? rows.slice().sort(cmp) : rows;
}

function section(container, title, sub, rows, kind) {
  const sec = document.createElement("section"); sec.className = "mega-section";
  sec.innerHTML = `<div class="mega-head"><h2>${title}</h2><p class="mega-sub">${sub}</p></div>`;
  const shown = sortRows(rows.filter(passes));
  if (!shown.length) { const e = document.createElement("div"); e.className = "empty-state"; e.textContent = "Nothing found."; sec.appendChild(e); container.appendChild(sec); return []; }
  const list = document.createElement("div"); list.className = "prop-list flat";
  const renderCard = kind === "certificate" ? certCard : card;
  shown.forEach(p => list.appendChild(renderCard(p, true)));
  sec.appendChild(list); container.appendChild(sec); return shown;
}

function updateBadge() {
  let n = 0;
  if (state.bidMin || state.bidMax || state.assessedMin) n++;
  if (state.sortBy !== "county") n++;
  if (state.favoritesOnly || state.topPicksOnly || state.soonOnly) n++;
  if (state.statusView !== "all") n++;
  if (state.maxBidPct !== 40) n++;
  if (state.counties.size !== countyNames().length) n++;
  if (state.types.size !== TYPE_ORDER.length) n++;
  if (state.liens.size !== LIEN_ORDER.length) n++;
  const b = document.getElementById("filtersBadge");
  if (b) { b.textContent = n; b.hidden = n === 0; }
}

// ==================== filters panel wiring ====================
// None of this existed before: the whole panel (toggle, inputs, sort,
// checkboxes, reset, status chips, hidden-restore, group buttons, theme,
// install, and the county map) rendered but did nothing on click/change.

let mapLoaded = false;

// ---- ledger tabs (Auctions / Lands Available / Certificates) ----
document.querySelectorAll("#ledgerTabs .ledger-tab[data-ledger]").forEach(btn => {
  btn.addEventListener("click", () => {
    if (state.ledger === btn.dataset.ledger) return;
    state.ledger = btn.dataset.ledger;
    render();
  });
});

// ---- open/close ----
const filtersToggleBtn = document.getElementById("filtersToggle");
const filtersPanelEl = document.getElementById("filtersPanel");
if (filtersToggleBtn && filtersPanelEl) {
  filtersToggleBtn.addEventListener("click", () => {
    filtersPanelEl.classList.toggle("open");
    filtersToggleBtn.classList.toggle("open");
  });
}

// ---- number inputs ----
function bindNumber(id, key, fallback) {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener("input", () => {
    const v = el.value.trim();
    state[key] = v === "" ? (fallback === undefined ? null : fallback) : Number(v);
    updateBadge();
    render();
  });
}
bindNumber("bidMin", "bidMin");
bindNumber("bidMax", "bidMax");
bindNumber("assessedMin", "assessedMin");
bindNumber("maxBidPct", "maxBidPct", 40);

// ---- sort ----
const sortByEl = document.getElementById("sortBy");
if (sortByEl) sortByEl.addEventListener("change", () => { state.sortBy = sortByEl.value; updateBadge(); render(); });

// ---- checkboxes ----
function bindCheckbox(id, key) {
  const el = document.getElementById(id);
  if (!el) return;
  el.addEventListener("change", () => { state[key] = el.checked; updateBadge(); render(); });
}
bindCheckbox("favOnly", "favoritesOnly");
bindCheckbox("topOnly", "topPicksOnly");
bindCheckbox("soonOnly", "soonOnly");
bindCheckbox("qtToggle", "includeQT");

// ---- reset ----
const resetBtn = document.getElementById("resetBtn");
if (resetBtn) resetBtn.addEventListener("click", () => {
  state.bidMin = null; state.bidMax = null; state.assessedMin = null;
  state.sortBy = "county"; state.favoritesOnly = false; state.topPicksOnly = false;
  state.soonOnly = false; state.includeQT = false; state.maxBidPct = 40;
  state.statusView = "all";
  state.counties = new Set(countyNames()); state.types = new Set(TYPE_ORDER); state.liens = new Set(LIEN_ORDER);

  ["bidMin", "bidMax", "assessedMin"].forEach(id => { const el = document.getElementById(id); if (el) el.value = ""; });
  const maxBidEl = document.getElementById("maxBidPct"); if (maxBidEl) maxBidEl.value = "40";
  const sortEl = document.getElementById("sortBy"); if (sortEl) sortEl.value = "county";
  ["favOnly", "topOnly", "soonOnly", "qtToggle"].forEach(id => { const el = document.getElementById(id); if (el) el.checked = false; });

  buildAllChips();
  if (mapLoaded) refreshMapPaths();
  updateBadge();
  render();
});

// ---- status summary chips (Shown / Active / Gone) ----
document.querySelectorAll(".summary-strip .chip[data-status]").forEach(c => {
  c.addEventListener("click", () => { state.statusView = c.dataset.status; render(); });
});

// ---- restore hidden ----
const restoreHiddenBtn = document.getElementById("restoreHiddenBtn");
if (restoreHiddenBtn) restoreHiddenBtn.addEventListener("click", async () => {
  if (!ME) return;
  restoreHiddenBtn.disabled = true;
  const { error } = await sb.from("hidden").delete().eq("user_id", ME.id);
  restoreHiddenBtn.disabled = false;
  if (!error) { HIDDEN.clear(); render(); }
});

// ---- group all/none mini-buttons (types / liens / counties) ----
document.querySelectorAll(".mini-btn[data-group]").forEach(btn => {
  btn.addEventListener("click", () => {
    const group = btn.dataset.group, mode = btn.dataset.mode;
    const setRef = group === "types" ? state.types : group === "liens" ? state.liens : state.counties;
    const values = group === "types" ? TYPE_ORDER : group === "liens" ? LIEN_ORDER : countyNames();
    setRef.clear();
    if (mode === "all") values.forEach(v => setRef.add(v));
    buildAllChips();
    if (group === "counties" && mapLoaded) refreshMapPaths();
    updateBadge();
    render();
  });
});

// ---- Florida county map ----
const mapBtnEl = document.getElementById("mapBtn");
const mapWrapEl = document.getElementById("mapWrap");
const mapHostEl = document.getElementById("mapHost");
function refreshMapPaths() {
  if (!mapHostEl) return;
  const withData = new Set(countyNames());
  mapHostEl.querySelectorAll("path[data-county]").forEach(p => {
    const name = p.dataset.county;
    p.classList.toggle("has-data", withData.has(name));
    p.classList.toggle("sel", state.counties.has(name));
  });
}
async function ensureMapLoaded() {
  if (mapLoaded || !mapHostEl) return;
  try {
    const res = await fetch("fl-counties.svg");
    mapHostEl.innerHTML = await res.text();
    mapLoaded = true;
    refreshMapPaths();
    mapHostEl.addEventListener("click", e => {
      const path = e.target.closest("path[data-county]");
      if (!path || !path.classList.contains("has-data")) return;
      toggleCounty(path.dataset.county);
    });
  } catch { /* offline or fetch blocked - map picker just stays closed */ }
}
if (mapBtnEl && mapWrapEl) {
  mapBtnEl.addEventListener("click", async () => {
    mapWrapEl.hidden = !mapWrapEl.hidden;
    if (!mapWrapEl.hidden) { await ensureMapLoaded(); refreshMapPaths(); }
  });
}

// ---- theme (auto -> light -> dark, persisted) ----
const THEME_KEY = "tdw_theme";
const THEME_CYCLE = ["auto", "light", "dark"];
const THEME_ICON = { auto: "☼", light: "☀", dark: "☾" };
const THEME_LABEL = { auto: "Auto", light: "Light", dark: "Dark" };
function applyTheme(mode) {
  if (mode === "light" || mode === "dark") document.documentElement.setAttribute("data-theme", mode);
  else document.documentElement.removeAttribute("data-theme");
  const icon = document.getElementById("themeIcon"); if (icon) icon.textContent = THEME_ICON[mode] || THEME_ICON.auto;
  const label = document.getElementById("themeLabel"); if (label) label.textContent = THEME_LABEL[mode] || THEME_LABEL.auto;
}
let themeMode = "auto";
try { themeMode = localStorage.getItem(THEME_KEY) || "auto"; } catch { /* private mode - fall back to auto */ }
applyTheme(themeMode);
const themeBtnEl = document.getElementById("themeBtn");
if (themeBtnEl) themeBtnEl.addEventListener("click", () => {
  themeMode = THEME_CYCLE[(THEME_CYCLE.indexOf(themeMode) + 1) % THEME_CYCLE.length];
  try { localStorage.setItem(THEME_KEY, themeMode); } catch { /* private mode - just won't persist */ }
  applyTheme(themeMode);
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  });
}

// ---- install button ----
// installBtn exists in the HTML (starts hidden) but nothing ever showed it
// or handled a click - the captured beforeinstallprompt event just sat
// unused. Now it un-hides the button and the click actually triggers it.
let deferredInstallPrompt = null;
const installBtnEl = document.getElementById("installBtn");
window.addEventListener("beforeinstallprompt", e => {
  e.preventDefault();
  deferredInstallPrompt = e;
  if (installBtnEl) installBtnEl.hidden = false;
});
if (installBtnEl) installBtnEl.addEventListener("click", async () => {
  if (!deferredInstallPrompt) return;
  installBtnEl.hidden = true;
  deferredInstallPrompt.prompt();
  await deferredInstallPrompt.userChoice;
  deferredInstallPrompt = null;
});
window.addEventListener("appinstalled", () => {
  if (installBtnEl) installBtnEl.hidden = true;
  deferredInstallPrompt = null;
});