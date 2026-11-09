// Buyer's Guide (2026-10-29, owner's request; destination redesign 2026-11-09):
// the questions a buyer asks before acting, per state, ledger and county, read
// as a journey - Find > Check > Buy > After > Risks - each answered from an
// official source or plainly marked "Not yet confirmed" with where to look.
//
// Data: public/buyers-guide.json (backend-generated; contract in
// docs/buyers-guide-contract.md). Until that file exists the guide is built
// from public/state-rules.json - the verified rules and county procedures
// already on file - mapped onto the same questions by rule topic. Nothing here
// invents an answer: a question with no recorded answer says so, and the
// meter is a count of answered questions, never a score.
//
// Loaded on demand by app.js (showPage("guide") -> import("./buyers-guide.js")).
// app.js passes everything page-specific through `ctx`; this module reads no
// app.js globals and makes no request other than the two JSON files. app.js
// re-renders the whole section on every ledger / county change, so this module
// keeps the reader's own state (open questions, search text, the county
// callout, the control that was used) and restores it after each render.

const LEDGER_NAMES = { AVAILABLE: "Available", AUCTIONS: "Auctions", LIENS_CERTIFICATES: "Liens & Certificates" };
const LEDGER_SHORT = { AVAILABLE: "Available", AUCTIONS: "Auctions", LIENS_CERTIFICATES: "Liens" };
const LEDGER_HERO = { AVAILABLE: "Available property", AUCTIONS: "Auctions", LIENS_CERTIFICATES: "Liens & Certificates" };
// One status vocabulary for the whole guide (chips, counts, tests).
export const STATUS_LABELS = { VERIFIED: "Answered", PARTIALLY_VERIFIED: "Partly answered", NOT_VERIFIED: "Not yet confirmed", SOURCE_RESTRICTED: "Official page blocked" };
const ANSWERED = new Set(["VERIFIED", "PARTIALLY_VERIFIED"]);

// The journey (pinned equal to buyers-guide.json "journey" by
// tests/python/test_buyers_guide.py); used when the file carries none.
const DEFAULT_JOURNEY = {"steps":[{"id":"find","label":"Find","title":"Find the sale or list"},{"id":"check","label":"Check","title":"Check before you commit"},{"id":"buy","label":"Buy","title":"How to buy"},{"id":"after","label":"After","title":"After you buy"},{"id":"risks","label":"Risks","title":"Risks to weigh"}],"ledger_order":["AVAILABLE","AUCTIONS","LIENS_CERTIFICATES"],"map":{"AVAILABLE":{"office":"find","what_is_list":"find","timeline":"find","price":"check","inspect":"check","due_diligence":"check","how_to_buy":"buy","application":"buy","pay":"buy","extra_costs":"buy","what_you_get":"after","refunds":"after","liens_survive":"risks","title":"risks"},"AUCTIONS":{"office":"find","how_it_works":"find","schedule":"find","where_when":"find","opening_bid":"check","due_diligence":"check","occupied":"check","register":"buy","deposit":"buy","pay_after_win":"buy","extra_costs":"buy","what_you_get":"after","redemption_after_sale":"after","unsold":"after","surplus":"after","liens_survive":"risks","title":"risks"},"LIENS_CERTIFICATES":{"office":"find","what_is_it":"find","interest_return":"check","redemption_period":"check","due_diligence":"check","how_to_buy":"buy","assignment":"buy","costs":"buy","if_not_redeemed":"after","expiry":"after","risks":"risks"}}};
const MORE_STEP = { id: "more", label: "More", title: "More questions" };

// Default catalog - used when the backend file has none (fallback mode).
// `topics` are state-rules.json topics that answer the question.
const DEFAULT_QUESTIONS = {
  AUCTIONS: [
    { id: "how_it_works", group: "The sale", question: "How does the sale work?", topics: ["tax_sale_model", "tax_deed_law", "tax_sale_law", "auction_source", "tax_forfeit_sale", "tax_forfeit_law"], where: "The county's tax-sale page and the state's tax-sale statute." },
    { id: "register", group: "Before the sale", question: "How do I register and pay the deposit?", topics: ["registration_deposit", "acquisition_procedure_auctions", "acquisition_procedure_auctions_available"], where: "The county's auction site states its registration and deposit rules." },
    { id: "opening_bid", group: "The money", question: "What is the opening bid made of?", topics: ["opening_bid"], where: "The county's sale terms or the state's tax-sale statute." },
    { id: "extra_costs", group: "The money", question: "What costs are added after I win?", topics: ["purchaser_costs"], where: "The county's sale terms (recording fees, stamps and other charges)." },
    { id: "redemption_after_sale", group: "After the sale", question: "Can the owner still redeem after the sale?", topics: ["redemption", "redemption_law"], where: "The state's redemption statute and the county's sale terms." },
    { id: "what_you_get", group: "After the sale", question: "What do I receive, and is the title clear?", topics: ["forfeited_land_deed"], where: "The county's sale terms; a title company can say whether the deed is insurable." },
    { id: "unsold", group: "After the sale", question: "What happens to property nobody bids on?", topics: ["available_after_sale", "available_escheat"], where: "The state's tax-sale statute." },
  ],
  AVAILABLE: [
    { id: "what_is_list", group: "The list", question: "What is this list?", topics: ["available_after_sale", "available_escheat", "land_bank_inventory", "land_bank_law", "adjudicated_property_law", "county_owned_sale", "repository_sale", "repository_law", "tax_forfeit_sale", "tax_forfeit_law", "source_dated_list"], where: "The office that publishes the list explains what it is." },
    { id: "how_to_buy", group: "Buying", question: "How do I buy a property on it?", topics: ["acquisition_procedure_available", "acquisition_process", "acquisition_procedure_auctions_available"], where: "The office that publishes the list (its process page or application)." },
    { id: "price", group: "The money", question: "What does the listed figure mean, and what is added?", topics: ["opening_bid", "purchaser_costs"], where: "Ask the office for the current amount due; listed figures may exclude fees." },
    { id: "what_you_get", group: "After buying", question: "What do I receive, and is the title clear?", topics: ["forfeited_land_deed"], where: "The office's sale terms; a title company can say whether the deed is insurable." },
  ],
  LIENS_CERTIFICATES: [
    { id: "what_is_it", group: "The certificate", question: "What am I buying?", topics: ["certificate_instrument", "tax_lien_law", "tax_sale_model"], where: "The state's tax-lien statute and the county treasurer or tax collector." },
    { id: "how_to_buy", group: "Buying", question: "How do I buy one?", topics: ["acquisition_procedure_liens_certificates"], where: "The county treasurer's or tax collector's certificate page." },
    { id: "redemption_period", group: "Holding it", question: "How long until it can be redeemed or turned into a deed?", topics: ["certificate_term", "redemption", "redemption_law"], where: "The state's tax-lien statute." },
  ],
};

let GUIDE_PROMISE = null, GUIDE_DATA = null;
function loadGuide() {
  if (!GUIDE_PROMISE) {
    const get = u => fetch(u, { cache: "no-cache" }).then(r => (r.ok ? r.json() : null)).catch(() => null);
    GUIDE_PROMISE = Promise.all([get("buyers-guide.json"), get("state-rules.json")]).then(([guide, rules]) => (GUIDE_DATA = { guide, rules }));
  }
  return GUIDE_PROMISE;
}

function ensureCss() {
  if (document.getElementById("bgCss")) return;
  const l = document.createElement("link");
  l.id = "bgCss"; l.rel = "stylesheet"; l.href = "buyers-guide.css";
  document.head.appendChild(l);
}

const has = (o, k) => !!o && Object.prototype.hasOwnProperty.call(o, k);
const isHttps = u => typeof u === "string" && /^https:\/\//.test(u);
const reduceMotion = () => !(window.matchMedia && window.matchMedia("(prefers-reduced-motion: no-preference)").matches);

// The reader's own state, kept across app.js re-renders.
const UI = { open: new Map(), search: "", callout: false, trigger: null, lastLedger: null };
function openSet(key) { if (!UI.open.has(key)) UI.open.set(key, new Set()); return UI.open.get(key); }

// ---------------------------------------------------------------- model
// One shape for both data sources: { questions: [...], answer(q, county), countyAnswers(q) }.
function ledgerModel(data, st, ledger) {
  const g = data.guide;
  if (g && g.states && has(g.states, st)) {
    const s = g.states[st];
    const qs = (g.questions && g.questions[ledger]) || [];
    const base = ((s.ledgers || {})[ledger] || {});
    const statewide = new Map((base.answers || []).map(a => [a.q, a]));
    const countyAns = (county, id) => {
      const c = county && s.counties && s.counties[county] && s.counties[county][ledger];
      return c && (c.answers || []).find(a => a.q === id);
    };
    return {
      mode: "guide",
      summary: base.summary || null,
      offered: base.offered || null,
      questions: qs.map(q => ({ id: q.id, group: q.group || "", question: q.question, where: q.where_to_look || q.where || "" })),
      counties: Object.keys(s.counties || {}).filter(c => has(s.counties[c], ledger)).sort(),
      answer(q, county) {
        const ca = countyAns(county, q.id);
        if (ca) return Object.assign({ scope: "county" }, ca);
        const a = statewide.get(q.id);
        return a ? Object.assign({ scope: "state" }, a) : null;
      },
      // Counties whose own page answers this question.
      countyAnswers(q) {
        return Object.keys(s.counties || {}).filter(c => { const a = countyAns(c, q.id); return a && ANSWERED.has(a.status); }).sort();
      },
    };
  }
  // Fallback: state-rules.json mapped by topic.
  const rs = data.rules && data.rules.states && data.rules.states[st];
  const rules = rs ? (rs.rules || []).concat(rs.county_rules || []) : [];
  const procs = rs ? (rs.county_procedures || []) : [];
  const inLedger = r => { const l = String(r.ledger || "ALL"); return l === "ALL" || l.split("|").includes(ledger); };
  const procLedger = p => { const id = String(p.source_id || ""); return ledger === "AVAILABLE" ? !/auction|lien|certificate/.test(id) : ledger === "AUCTIONS" ? /auction|tax_sale|treasurer_sale/.test(id) : /lien|certificate/.test(id); };
  const qs = DEFAULT_QUESTIONS[ledger] || [];
  const answer = (q, county) => {
    // A county's own verified procedure answers "how to buy / register".
    if (county && /how_to_buy|register/.test(q.id)) {
      const p = procs.find(x => x.county === county && procLedger(x));
      if (p) return { scope: "county", status: "VERIFIED", answer: p.instructions || "", steps: String(p.steps || "").split("|").map(s => s.trim()).filter(Boolean), source_url: p.evidence_url, source_title: p.source_title, office: p.office, verified_on: p.observed_on };
    }
    const pick = list => list.find(r => (q.topics || []).includes(r.topic) && inLedger(r) && r.status === "VERIFIED") || list.find(r => (q.topics || []).includes(r.topic) && inLedger(r));
    const own = county ? pick(rules.filter(r => r.county === county)) : null;
    const r = own || pick(rules.filter(r => !r.county));
    if (!r) return null;
    return { scope: r.county ? "county" : "state", status: r.status, answer: r.statement, source_url: r.source_url, source_title: r.source_title, citation: r.citation, office: r.office, verified_on: r.status === "VERIFIED" ? r.verified_on : null, where_to_look: r.ambiguity || "" };
  };
  const counties = Array.from(new Set(rules.filter(r => r.county && inLedger(r)).map(r => r.county).concat(procs.filter(procLedger).map(p => p.county)))).filter(Boolean).sort();
  return {
    mode: "rules", summary: null, offered: null, questions: qs, counties, answer,
    countyAnswers(q) { return counties.filter(c => { const a = answer(q, c); return a && a.scope === "county" && ANSWERED.has(a.status) && a.answer; }); },
  };
}

const answered = a => !!(a && a.answer && ANSWERED.has(a.status));

// ---------------------------------------------------------------- render parts
function placeName(county, unit) { return / City$/.test(county) ? county : `${county} ${unit}`; }

function linksOf(a) {
  const list = Array.isArray(a && a.links) ? a.links.filter(l => l && isHttps(l.url)) : [];
  if (!list.length && a && isHttps(a.source_url)) list.push({ title: a.source_title || "Official page", url: a.source_url });
  return list;
}

function linkHtml(l, e) { return `<a href="${e(l.url)}" target="_blank" rel="noopener">${e(l.title || "Official page")} →</a>`; }

// "Where to look: <link>. Remaining sentence." - the link title is shown once,
// as the link, when the sentence starts with it.
function whereHtml(q, a, e) {
  const where = (a && a.where_to_look) || q.where || "Ask the office that runs the sale.";
  const links = linksOf(a);
  let body = e(where), rest = links;
  if (links.length) {
    const lead = `See ${links[0].title}.`;
    if (where.startsWith(lead)) { body = linkHtml(links[0], e) + e(where.slice(lead.length)); rest = links.slice(1); }
  }
  const more = rest.length ? `<span class="bg-where-links">${rest.map(l => linkHtml(l, e)).join("")}</span>` : "";
  return `<p class="bg-where"><span class="bg-where-l">Where to look:</span> ${body}${more}</p>`;
}

function mostlyCaps(t) {
  const letters = String(t || "").replace(/[^A-Za-z]/g, "");
  if (letters.length < 20) return false;
  return letters.replace(/[^A-Z]/g, "").length / letters.length > 0.6;
}

function scopeChip(a, ctx) {
  if (a.scope === "county") return `${ctx.unit} rule`;
  if (a.citation) return `State law · ${a.citation}`;
  return "Statewide";
}

function chipHtml(status, e) {
  const cls = status === "VERIFIED" ? "ok" : status === "PARTIALLY_VERIFIED" ? "part" : status === "SOURCE_RESTRICTED" ? "blocked" : "open";
  return `<span class="bg-chip bg-chip-${cls}">${e(STATUS_LABELS[status] || STATUS_LABELS.NOT_VERIFIED)}</span>`;
}

function answeredRowHtml(q, a, ctx, isOpen) {
  const e = ctx.esc;
  const steps = Array.isArray(a.steps) && a.steps.length ? `<ol class="bg-steps">${a.steps.map(s => `<li>${e(s)}</li>`).join("")}</ol>` : "";
  const quote = a.quote ? `<details class="bg-src"><summary>Official wording</summary><blockquote class="bg-quote${mostlyCaps(a.quote) ? " bg-caps" : ""}">${e(a.quote)}</blockquote></details>` : "";
  const link = isHttps(a.source_url) ? `<span>${linkHtml({ url: a.source_url, title: a.source_title || "Official source" }, e)}</span>` : "";
  const meta = [`<span class="bg-scope">${e(scopeChip(a, ctx))}</span>`, link,
    a.office ? `<span>${e(a.office)}</span>` : "",
    a.verified_on ? `<span>Checked ${e(ctx.fmtDate(a.verified_on))}</span>` : ""].filter(Boolean).join("");
  const verified = a.status === "VERIFIED";
  return `<details class="bg-q bg-q-ok${verified ? " bg-q-verified" : ""}" data-bg-q="${e(q.id)}" data-bg-status="${e(a.status)}"${verified ? ' data-bg-verified="1"' : ""}${isOpen ? " open" : ""}>
    <summary><span class="bg-q-text">${e(q.question)}</span>${chipHtml(a.status, e)}</summary>
    <div class="bg-a"><p class="bg-answer">${e(a.answer)}</p>${steps}${quote}<p class="bg-meta">${meta}</p></div></details>`;
}

function openRowHtml(q, a, ctx) {
  const e = ctx.esc;
  const status = a && a.status === "SOURCE_RESTRICTED" ? "SOURCE_RESTRICTED" : "NOT_VERIFIED";
  return `<div class="bg-q bg-q-open" data-bg-q="${e(q.id)}" data-bg-status="${status}">
    <p class="bg-q-line"><span class="bg-q-text">${e(q.question)}</span>${chipHtml(status, e)}</p>${whereHtml(q, a, e)}</div>`;
}

function stepHtml(step, n, items, ctx, opened) {
  const e = ctx.esc;
  const done = items.filter(x => answered(x.a));
  const todo = items.filter(x => !answered(x.a));
  return `<section class="bg-step" id="bgStep-${e(step.id)}" data-bg-step="${e(step.id)}" aria-labelledby="bgStepH-${e(step.id)}">
    <header class="bg-step-head"><span class="bg-step-n" aria-hidden="true">${n}</span>
      <div class="bg-step-hd"><p class="bg-step-k">Step ${n} · ${e(step.label)}</p><h2 class="bg-step-h" id="bgStepH-${e(step.id)}">${e(step.title)}</h2></div>
      <span class="bg-step-c">${done.length}/${items.length} answered</span></header>
    ${done.length ? `<div class="bg-list">${done.map(x => answeredRowHtml(x.q, x.a, ctx, opened.has(x.q.id))).join("")}</div>` : ""}
    ${todo.length ? `<div class="bg-todo"><h3 class="bg-todo-h">Still to confirm (${todo.length})</h3>${todo.map(x => openRowHtml(x.q, x.a, ctx)).join("")}</div>` : ""}
  </section>`;
}

function calloutHtml(moved, ctx, model) {
  const e = ctx.esc;
  if (!moved.length) return "";
  const unit = ctx.unit.toLowerCase();
  const all = Array.from(new Set(moved.flatMap(x => x.counties))).sort();
  const opts = `<option value="">Choose a ${e(unit)}</option>` + all.map(c => `<option value="${e(c)}">${e(placeName(c, ctx.unit))}</option>`).join("");
  return `<aside class="bg-callout" data-bg-callout><details${UI.callout ? " open" : ""}><summary><span class="bg-callout-t">${moved.length} ${moved.length === 1 ? "question is" : "questions are"} answered ${e(unit)} by ${e(unit)}</span></summary>
    <p class="bg-callout-p">No statewide source answers ${moved.length === 1 ? "it" : "these"}; each ${e(unit)}'s own official page does. Pick a ${e(unit)} to read its answers.</p>
    <ul class="bg-callout-list">${moved.map(x => `<li><span>${e(x.q.question)}</span><span class="bg-callout-n">${x.counties.length} ${x.counties.length === 1 ? e(unit) : (unit === "parish" ? "parishes" : "counties")}</span></li>`).join("")}</ul>
    <label class="bg-callout-pick"><span>${e(ctx.unit)}</span><select data-bg-callout-county aria-label="Open the guide for a ${e(unit)}">${opts}</select></label></details></aside>`;
}

function ledgerTabsHtml(order, ledger, ctx) {
  const e = ctx.esc;
  const idx = order.indexOf(ledger);
  const from = UI.lastLedger && order.includes(UI.lastLedger) ? order.indexOf(UI.lastLedger) : idx;
  return `<div class="bg-seg" role="group" aria-label="Ledger" style="--n:${order.length};--i:${from}" data-bg-to="${idx}">
    <span class="bg-seg-thumb" aria-hidden="true"></span>
    ${order.map(k => `<button type="button" class="bg-tab${k === ledger ? " on" : ""}" data-bg-ledger="${k}" data-tab-ledger="${k}" aria-pressed="${k === ledger}" aria-label="${e(LEDGER_NAMES[k])}"><span class="bg-tab-long">${e(LEDGER_NAMES[k])}</span><span class="bg-tab-short" aria-hidden="true">${e(LEDGER_SHORT[k])}</span></button>`).join("")}
  </div>`;
}

// ---------------------------------------------------------------- render
export function render(root, ctx) {
  ensureCss();
  if (GUIDE_DATA) return Promise.resolve(draw(root, ctx, GUIDE_DATA));
  root.innerHTML = `<div class="bg-page"><p class="bg-loading" role="status">Loading the buyer's guide…</p></div>`;
  return loadGuide().then(data => draw(root, ctx, data));
}

function draw(root, ctx, data) {
  const e = ctx.esc;
  const journey = (data.guide && data.guide.journey && Array.isArray(data.guide.journey.steps)) ? data.guide.journey : DEFAULT_JOURNEY;
  const order = (journey.ledger_order || DEFAULT_JOURNEY.ledger_order).filter(k => LEDGER_NAMES[k]);
  const ledger = order.includes(ctx.ledger) ? ctx.ledger : order[0];
  const model = ledgerModel(data, ctx.state, ledger);
  const counties = Array.from(new Set(model.counties.concat(ctx.counties || []))).sort();
  const county = ctx.county && counties.includes(ctx.county) ? ctx.county : null;
  const c2 = Object.assign({}, ctx, { county });
  const map = (journey.map && journey.map[ledger]) || {};
  const all = model.questions.map(q => ({ q, a: model.answer(q, county) }));

  // Statewide view: questions only counties answer move into one callout.
  const moved = [];
  const shown = county ? all : all.filter(x => {
    if (answered(x.a)) return true;
    const cs = model.countyAnswers(x.q);
    if (!cs.length) return true;
    moved.push({ q: x.q, counties: cs });
    return false;
  });
  const steps = journey.steps.map(s => ({ step: s, items: shown.filter(x => map[x.q.id] === s.id) })).filter(s => s.items.length);
  const unmapped = shown.filter(x => !journey.steps.some(s => s.id === map[x.q.id]));
  if (unmapped.length) steps.push({ step: MORE_STEP, items: unmapped });

  const verifiedN = all.filter(x => x.a && x.a.status === "VERIFIED").length;
  const meterN = shown.filter(x => x.a && x.a.status === "VERIFIED").length;
  const meterM = shown.length;
  const place = county ? placeName(county, ctx.unit) : ctx.stateName;
  const key = `${ctx.state}|${ledger}`;
  const opened = openSet(key);
  const lede = model.summary || "The questions to settle before you act, each answered from an official page or marked not yet confirmed with where to look.";
  const opts = `<option value="">Statewide</option>` + counties.map(c => `<option value="${e(c)}"${c === county ? " selected" : ""}>${e(placeName(c, ctx.unit))}</option>`).join("");
  const rail = steps.map((s, i) => {
    const d = s.items.filter(x => answered(x.a)).length;
    return `<li><button type="button" class="bg-jump" data-bg-jump="${e(s.step.id)}"><span class="bg-jump-n" aria-hidden="true">${i + 1}</span><span class="bg-jump-l">${e(s.step.label)}</span><span class="bg-jump-c">${d}/${s.items.length}</span></button></li>`;
  }).join("");

  root.innerHTML = `<div class="bg-page" data-ledger="${ledger}" data-bg-mode="${model.mode}">
    <header class="bg-hero">
      <p class="bg-eyebrow">Buyer's Guide · ${e(ctx.stateName)}</p>
      <h1 class="bg-title">${e(LEDGER_HERO[ledger])} in ${e(place)}</h1>
      <p class="bg-lede">${e(lede)}</p>
      <div class="bg-meter"><p class="bg-meter-t"><strong>${meterN}</strong> of ${meterM} answered from official pages${county ? "" : " statewide"}</p>
        <span class="bg-meter-bar" aria-hidden="true"><span style="--f:${meterM ? (meterN / meterM).toFixed(3) : 0}"></span></span></div>
      <p class="bg-legal">Answers describe the public process, not any one property. Not legal advice - confirm with the office before you pay.${model.mode === "rules" ? " The full guide is being prepared; these answers come from the verified rules on file." : ""}</p>
    </header>
    <div class="bg-controls">
      ${ledgerTabsHtml(order, ledger, ctx)}
      <label class="bg-county"><span class="bg-county-l">Showing:</span><select data-bg-county aria-label="Showing: ${e(ctx.unit)} or statewide">${opts}</select></label>
      <div class="bg-search-wrap"><input class="bg-search" type="search" placeholder="Search questions" aria-label="Search questions" data-bg-search autocomplete="off"></div>
    </div>
    <p class="bg-count" role="status" aria-live="polite"></p>
    ${county ? "" : calloutHtml(moved, c2, model)}
    <div class="bg-body">
      <nav class="bg-rail" aria-label="Journey steps"><ol>${rail}</ol></nav>
      <div class="bg-main">
        ${steps.map((s, i) => stepHtml(s.step, i + 1, s.items, c2, opened)).join("")}
        <div class="bg-empty" hidden><p>No question matches <span class="bg-empty-q"></span>.</p><button type="button" class="bg-clear" data-bg-clear>Clear search</button></div>
      </div>
    </div>
  </div>`;

  wire(root, ctx, { ledger, county, key, total: shown.length, stepsN: steps.length });
  const tb = document.querySelector('html[data-shell="v3"] .topbar');
  root.style.setProperty("--bg-top", (tb ? Math.round(tb.getBoundingClientRect().height) : 0) + "px");
  UI.lastLedger = ledger;
  return { mode: model.mode, verified: verifiedN, total: all.length, shown: shown.length, countyOnly: moved.length, steps: steps.map(s => s.step.id) };
}

function wire(root, ctx, s) {
  const page = root.querySelector(".bg-page");
  const remember = sel => { UI.trigger = sel; };
  const go = (next, sel) => { remember(sel); ctx.navigate(next); };
  root.querySelectorAll("[data-bg-ledger]").forEach(b => b.addEventListener("click", () => {
    if (b.dataset.bgLedger !== s.ledger) go({ ledger: b.dataset.bgLedger, county: s.county }, `[data-bg-ledger="${b.dataset.bgLedger}"]`);
  }));
  const sel = root.querySelector("[data-bg-county]");
  if (sel) sel.addEventListener("change", () => go({ ledger: s.ledger, county: sel.value || null }, "[data-bg-county]"));
  const csel = root.querySelector("[data-bg-callout-county]");
  if (csel) csel.addEventListener("change", () => { if (csel.value) go({ ledger: s.ledger, county: csel.value }, "[data-bg-county]"); });
  const callout = root.querySelector("[data-bg-callout] details");
  if (callout) callout.addEventListener("toggle", () => { UI.callout = callout.open; });
  const opened = openSet(s.key);
  root.querySelectorAll("details.bg-q").forEach(d => d.addEventListener("toggle", () => {
    if (d.dataset.bgAuto) return;
    if (d.open) opened.add(d.dataset.bgQ); else opened.delete(d.dataset.bgQ);
  }));
  root.querySelectorAll("[data-bg-jump]").forEach(b => b.addEventListener("click", () => {
    const t = root.querySelector(`#bgStep-${b.dataset.bgJump}`);
    if (!t) return;
    t.scrollIntoView({ behavior: reduceMotion() ? "auto" : "smooth", block: "start" });
    const h = t.querySelector(".bg-step-h"); if (h) { h.setAttribute("tabindex", "-1"); h.focus({ preventScroll: true }); }
  }));

  // Search: filters rows, keeps its text across re-renders, Escape clears.
  const search = root.querySelector("[data-bg-search]");
  const count = root.querySelector(".bg-count");
  const empty = root.querySelector(".bg-empty");
  const apply = () => {
    const t = search.value.trim().toLowerCase();
    UI.search = search.value;
    let n = 0;
    root.querySelectorAll(".bg-q").forEach(d => {
      const hit = !t || d.textContent.toLowerCase().includes(t);
      d.hidden = !hit;
      if (hit) n++;
      if (d.tagName === "DETAILS") {
        if (t && hit && !d.open) { d.dataset.bgAuto = "1"; d.open = true; }
        else if (!t && d.dataset.bgAuto) { d.open = opened.has(d.dataset.bgQ); }
        if (!t) setTimeout(() => { delete d.dataset.bgAuto; }, 0);
      }
    });
    root.querySelectorAll(".bg-step").forEach(sec => { sec.hidden = !sec.querySelector(".bg-q:not([hidden])"); });
    root.querySelectorAll(".bg-todo").forEach(g => { g.hidden = !g.querySelector(".bg-q:not([hidden])"); });
    root.querySelectorAll("[data-bg-jump]").forEach(b => { const sec = root.querySelector(`#bgStep-${b.dataset.bgJump}`); b.classList.toggle("dim", !!(sec && sec.hidden)); });
    if (empty) { empty.hidden = !t || n > 0; const q = empty.querySelector(".bg-empty-q"); if (q) q.textContent = `“${search.value.trim()}”`; }
    count.textContent = t ? (n ? `${n} ${n === 1 ? "question matches" : "questions match"} “${search.value.trim()}”.` : `No question matches “${search.value.trim()}”. Press Escape to clear.`)
      : `${s.total} questions in ${s.stepsN} steps.`;
  };
  search.value = UI.search || "";
  search.addEventListener("input", apply);
  search.addEventListener("keydown", ev => { if (ev.key === "Escape" && search.value) { ev.preventDefault(); ev.stopPropagation(); search.value = ""; apply(); } });
  const clear = root.querySelector("[data-bg-clear]");
  if (clear) clear.addEventListener("click", () => { search.value = ""; apply(); search.focus(); });
  apply();

  // Sliding thumb: drawn at the previous ledger, then moved to this one.
  const seg = root.querySelector(".bg-seg");
  if (seg) {
    const to = seg.dataset.bgTo;
    if (reduceMotion()) seg.style.setProperty("--i", to);
    else requestAnimationFrame(() => requestAnimationFrame(() => seg.style.setProperty("--i", to)));
  }
  // Focus returns to the control that caused the re-render.
  if (UI.trigger) {
    const t = root.querySelector(UI.trigger);
    UI.trigger = null;
    if (t) t.focus({ preventScroll: true });
  }
  if (page && !reduceMotion()) page.classList.add("bg-anim");
}
