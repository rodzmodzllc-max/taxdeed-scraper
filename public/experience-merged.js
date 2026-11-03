// Merged List experience - 2026-10-25 (owner's brief: "merge both versions").
//
// Since 2026-10-27 the Merged look draws Available with Terrain's module and
// Auctions with Tactile's (app.js MERGED_ENGINES); this module draws only
//   LIENS      certificate slips bundled by tax year (or county); the newest
//              bundle is fanned out as a side-by-side scroll-snap row (every
//              slip readable, its Watch strip reachable); a lifted slip
//              rises in place and its full facts sit in the tray below.
// The List title count is the only "certificates in view" number; the
// sub-line names the number of bundles only when there is more than one.
//
// Stamps are pressed onto a slip only from what the record or its source
// says (app.js cardStamp): Redeemed / Expired / Assigned for a certificate,
// "No longer listed" for a row that left its list. A stamp presses in once
// per object, when it first comes into view.
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
const PAGE = 48;            // bundles built at a time; "Show more" adds PAGE more
const FAN = 5;              // slips fanned out at once
const OPEN_DELAY = 260;     // ms of opening animation before the property page

const S = {
  ledger: null,             // ledger last drawn: a change replays the entrance
  limit: { certificate: PAGE },
  bundleBy: "year",
  fan: undefined,           // undefined = not chosen yet: the newest bundle opens
  fanStart: 0,
  slip: null,
  pressed: null,
  stamped: new Set(),       // "<id>|<stamp>" already pressed in
  dealt: null,              // the bundle whose fan-out has already played
  trayShown: null,          // the slip whose tray has already risen
  last: null
};

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
  const ledger = "certificate";
  // Only Liens & Certificates is drawn here (Available and Auctions belong
  // to Terrain / Tactile under Merged); any other ledger leaves the stage
  // empty and the classic list shows.
  if (!rows.length || detail.ledger !== "certificate") {
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
  }

  const ae = document.activeElement;
  const focusKey = ae && stage.contains(ae) ? ae.getAttribute("data-k")
    : (!ae || ae === document.body) ? S.pressed : null;
  S.pressed = null;

  const keep = {};
  stage.querySelectorAll("[data-keep]").forEach(el => { keep[el.dataset.keep] = el.scrollLeft; });

  const html = liensHtml(rows, api);

  stage.dataset.xp = NAME;
  stage.innerHTML = `<div class="xpm xpm-${ledger}${enter ? " xpm-enter" : ""}" data-ledger="${ledger}">${html}</div>`;
  stage.querySelectorAll("[data-keep]").forEach(el => { if (keep[el.dataset.keep] !== undefined) el.scrollLeft = keep[el.dataset.keep]; });
  try { api.hydrateVisuals(stage); } catch {}
  document.documentElement.dataset.experienceReady = NAME;
  watchStamps(stage);

  if (focusKey) {
    const el = stage.querySelector(`[data-k="${keyEsc(focusKey)}"]`);
    if (el) { try { el.focus({ preventScroll: true }); } catch {} }
  }
}

function redraw() { if (S.last) draw(S.last); }

// ------------------------------------------------------------------ stamps

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
  // Fallback for an app.js without cardStamp: the certificate rules only.
  if (api.isGone(p)) return { k: "closed", key: "gone", t: "No longer listed" };
  if (p.source === "certificate") {
    const s = p.inventory_status;
    if (s === "certificate_redeemed") return { k: "redeemed", key: "redeemed", t: "Redeemed" };
    if (s === "certificate_expired") return { k: "closed", key: "expired", t: "Expired" };
    if (s === "certificate_assigned") return { k: "closed", key: "assigned", t: "Assigned" };
    return null;
  }
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

function whereText(p, api) { return `${p.county} ${api.unitWord()}, ${api.stateCode()}`; }

// "County" -> "counties", "Parish" -> "parishes" (never "countys").
function unitPlural(api) {
  const w = String(api.unitWord() || "County").toLowerCase();
  if (/[^aeiou]y$/.test(w)) return w.slice(0, -1) + "ies";
  if (/(s|sh|ch|x|z)$/.test(w)) return w + "es";
  return w + "s";
}

function factRows(rows, api) {
  return rows.map(r => `<div class="fact"><span class="k">${api.esc(r[0])}</span><span class="v">${api.esc(r[1])}</span></div>`).join("");
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
      ${keys.length > 1 ? `<p class="xpm-line"><span class="xpm-mono">${n(keys.length)}</span> bundles</p>` : ""}
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
  const sub = by === "year" ? `${other} ${other === 1 ? api.unitWord().toLowerCase() : unitPlural(api)}` : `${other} tax year${other === 1 ? "" : "s"}`;
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
    // Every slip shows its own number, county and amount and keeps its own
    // Watch strip; the lifted one is raised (translateY only) and its facts
    // also sit in the tray below. Slips sit side by side in a scroll-snap
    // row, so none covers a neighbour's text or Watch strip (audit F8).
    const pf = api.previewFacts(p);
    const a = api.amountShort(p);
    const amt = pf.bid || a.text;   // the exact published figure, under amountShort's label
    return `<div class="fslip${lifted ? " lifted" : ""}" style="--off:${i - mid};--fd:${i * 45}ms">
      <button type="button" class="fb xpm-slip xpm-obj" data-xa="slip" data-pid="${api.esc(id)}" data-k="slip-${api.esc(id)}" aria-pressed="${lifted}"
        aria-label="${api.esc(slipLabel(p, api, lifted))}">
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
      <div class="fan-stage${deal ? " deal" : ""}" data-keep="fan-${api.esc(k)}" role="group" aria-label="${api.esc(`${L.caps} ${L.title}, ${list.length} ${list.length === 1 ? "certificate" : "certificates"}, fanned out`)}">
        <div class="fan-band" aria-hidden="true">${api.esc(L.title)}</div>
        ${slips}
      </div>
      ${pager}
      ${trayHtml(sel, api)}
      <button type="button" class="fold-back" data-xa="fan" data-key="${api.esc(k)}" data-k="fan-${api.esc(k)}" aria-expanded="true">Bundle ${api.esc(L.title)} back up</button>
    </div>
  </div>`;
}

function slipLabel(p, api, lifted) {
  const pf = api.previewFacts(p);
  const a = api.amountShort(p);
  const amt = a.state === "not_published" ? "not published" : (pf.bid || a.text);
  return `Certificate ${certNo(p) || "number not published"}, ${p.county} ${api.unitWord()}. ${a.label}: ${amt}. ${lifted ? "Lifted, its facts are shown below." : "Lift this slip."}`;
}

function trayHtml(p, api) {
  const id = idOf(p);
  const anim = S.trayShown !== id;
  S.trayShown = id;
  return `<div class="tray xpm-obj${anim ? " anim" : ""}" aria-live="polite">${trayInner(p, api)}</div>`;
}

// The tray's content for a slip (no wrapper): a slip change swaps only this,
// in place (liftInPlace).
function trayInner(p, api) {
  const pf = api.previewFacts(p);
  const a = api.amountShort(p);
  const facts = [["Status", api.officialStatusText(p)]];
  if (pf.parcel) facts.push([pf.parcelLabel, pf.parcel]);
  const more = new Map(pf.more || []);
  for (const k of ["Interest rate", "Tax year", "Issued"]) facts.push([k, more.get(k) || "Not published"]);
  for (const r of pf.more || []) if (!["Interest rate", "Tax year", "Issued"].includes(r[0])) facts.push(r);
  if (pf.source) facts.push(["Source", pf.source]);
  const id = idOf(p);
  return `
    <div class="tray-head"><div><div class="tray-cert xpm-mono">Cert ${api.esc(certNo(p) || "number not published")}</div>
      <div class="xpm-small">${api.esc(whereText(p, api))}</div></div>${stampHtml(p, api, "inline")}</div>
    <div class="tray-fig"><span class="xpm-caps">${api.esc(a.label)}</span>${a.state === "not_published" ? missing("Not published", api) : `<span class="fig-xl">${api.esc(pf.bid || a.text)}</span>`}</div>
    <div class="facts">${factRows(facts, api)}</div>
    <div class="tray-acts">
      <button type="button" class="xpm-cta plum" data-xa="open" data-pid="${api.esc(id)}" data-k="open-${api.esc(id)}">Open full record</button>
      ${watchBtn(p, api, "xpm-watch").replace(`data-k="w-`, `data-k="tw-`)}
    </div>
    ${linkHtml(pf.link, api, "xpm-link plum")}`;
}

// Lift another slip without rebuilding the stage (audit F45): the slips move
// by their own transition and the tray keeps its element, swapping only its
// content. Falls back to a redraw when the fan is not on screen.
function liftInPlace(pid) {
  const stage = stageEl();
  const api = apiOf(S.last);
  const p = rowById(pid);
  const fan = stage && stage.querySelector(".xpm-bundle.fanned");
  const tray = fan && fan.querySelector(".tray");
  const target = fan && fan.querySelector(`.fslip .fb[data-pid="${keyEsc(pid)}"]`);
  if (!api || !p || !tray || !target) { redraw(); return; }
  fan.querySelectorAll(".fslip").forEach(s => {
    const fb = s.querySelector(".fb");
    const on = fb === target;
    s.classList.toggle("lifted", on);
    fb.setAttribute("aria-pressed", String(on));
    const row = rowById(fb.dataset.pid);
    if (row) fb.setAttribute("aria-label", slipLabel(row, api, on));
  });
  S.pressed = null;
  tray.classList.remove("anim", "opening");
  tray.innerHTML = trayInner(p, api);
  S.trayShown = pid;
  try { api.hydrateVisuals(tray); } catch {}
  watchStamps(stage);
}

// Keep the bundle the reader tapped where it was on screen (audit F9):
// folding the fan above it would otherwise pull the page up under it.
function redrawKeeping(key, fromEl) {
  const stage = stageEl();
  const b = fromEl && fromEl.closest(".xpm-bundle");
  const before = b ? b.getBoundingClientRect().top : null;
  redraw();
  if (before === null || !stage) return;
  const k = stage.querySelector(`[data-k="fan-${keyEsc(key)}"]`);
  const nb = k && k.closest(".xpm-bundle");
  if (!nb) return;
  const d = nb.getBoundingClientRect().top - before;
  if (Math.abs(d) > 1) window.scrollBy(0, d);
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
  const obj = fromEl && fromEl.closest(".tray");
  if (obj && !reduced()) {
    obj.classList.add("opening");
    setTimeout(() => { obj.classList.remove("opening"); api.openDetail(p); }, OPEN_DELAY);
  } else api.openDetail(p);
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
    case "open": openRecord(pid, el); break;
    case "bundleby":
      if (S.bundleBy !== el.dataset.by) { S.bundleBy = el.dataset.by; S.fan = undefined; S.slip = null; S.fanStart = 0; S.limit.certificate = PAGE; redraw(); }
      break;
    case "fan": {
      const k = el.dataset.key;
      S.fan = S.fan === k ? null : k;
      S.fanStart = 0; S.slip = null; S.dealt = null; S.trayShown = null;
      redrawKeeping(k, el);
      break;
    }
    case "fanprev": S.fanStart = Math.max(0, S.fanStart - FAN); S.slip = null; redraw(); break;
    case "fannext": S.fanStart += FAN; S.slip = null; redraw(); break;
    case "slip":
      if (S.slip !== pid) { S.slip = pid; liftInPlace(pid); }
      break;
  }
}

function onKey(e) {
  const stage = stageEl();
  if (!stage || stage.dataset.xp !== NAME || !isActive()) return;
  if (!stage.contains(document.activeElement)) return;
  if (e.key === "Escape") {
    if (S.fan !== null && S.fan !== undefined) { const k = S.fan; S.fan = null; redraw(); const b = stage.querySelector(`[data-k="fan-${keyEsc(k)}"]`); if (b) b.focus(); }
    return;
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
window.addEventListener("tdw:rendered", e => draw(e.detail));
window.addEventListener("tdw:experience", () => { if (isActive()) { S.ledger = null; if (window.__tdwLastRender) draw(window.__tdwLastRender); } else deactivate(); });
if (isActive() && window.__tdwLastRender) draw(window.__tdwLastRender);
else if (!isActive()) deactivate();
