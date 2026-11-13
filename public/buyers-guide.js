// Buyer's Guide (2026-10-29, owner's request; destination redesign 2026-11-09;
// "up to a 10" sprint 2026-11-12): the questions a buyer asks before acting, per
// state, ledger and county, read as a guide - a short version at the top, then
// Find > Check > Buy > After > Risks with the answers open, then the next step
// back to the properties. Each answer comes from an official source (its title,
// link and the date it was read; the source's own wording folded beneath) or is
// plainly marked "Not yet confirmed" with where to look.
//
// Data: public/buyers-guide.json (backend-generated; contract in
// docs/buyers-guide-contract.md). Until that file exists the guide is built
// from public/state-rules.json - the verified rules and county procedures
// already on file - mapped onto the same questions by rule topic. Nothing here
// invents an answer: the short version quotes the first sentence of an answer
// (or the ledger's own summary) from the file, a question with no recorded
// answer says so, and no count or score is shown (2026-11-12: the "N of M
// answered" meter and the per-row "Answered" badges read as coverage
// bookkeeping to a customer and were removed).
//
// Loaded on demand by app.js (showPage("guide") -> import("./buyers-guide.js")).
// app.js passes everything page-specific through `ctx`; this module reads no
// app.js globals and makes no request other than the two JSON files. app.js
// re-renders the whole section on every ledger / county change, so this module
// keeps the reader's own state (questions they closed, search text, the
// control that was used) and restores it after each render.

const LEDGER_NAMES = { AVAILABLE: "Available", AUCTIONS: "Auctions", LIENS_CERTIFICATES: "Liens & Certificates" };
const LEDGER_SHORT = { AVAILABLE: "Available", AUCTIONS: "Auctions", LIENS_CERTIFICATES: "Liens" };
const LEDGER_HERO = { AVAILABLE: "Available property", AUCTIONS: "Auctions", LIENS_CERTIFICATES: "Liens & Certificates" };
// The listing noun of the next-step link: [one, many].
const LEDGER_NOUN = { AVAILABLE: ["Available property", "Available properties"], AUCTIONS: ["property at auction", "properties at auction"], LIENS_CERTIFICATES: ["lien or certificate", "liens and certificates"] };
// One status vocabulary for the whole guide (chips, tests). Since 2026-11-12 an
// answered row carries no chip; "Answered" stays here as the status's name.
export const STATUS_LABELS = { VERIFIED: "Answered", PARTIALLY_VERIFIED: "Partly answered", NOT_VERIFIED: "Not yet confirmed", SOURCE_RESTRICTED: "Official page blocked" };
const ANSWERED = new Set(["VERIFIED", "PARTIALLY_VERIFIED"]);
// "The short version": which question answers each of the three lines, per
// ledger. Only an answer already in the file is shown (its first sentence, word
// for word); the "what" line prefers the ledger's own summary sentence.
export const SHORT_VERSION = {
  AVAILABLE: [["what", "What it is", "what_is_list"], ["cost", "What it costs", "price"], ["buy", "How to buy", "how_to_buy"]],
  AUCTIONS: [["what", "What it is", "how_it_works"], ["cost", "What it costs", "opening_bid"], ["buy", "How to buy", "register"]],
  LIENS_CERTIFICATES: [["what", "What it is", "what_is_it"], ["cost", "What it costs", "costs"], ["buy", "How to buy", "how_to_buy"]],
};

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

// The reader's own state, kept across app.js re-renders. Answers are open by
// default (2026-11-12); `closed` remembers the ones the reader folded.
const UI = { closed: new Map(), search: "", trigger: null, lastLedger: null };
function closedSet(key) { if (!UI.closed.has(key)) UI.closed.set(key, new Set()); return UI.closed.get(key); }

// ---------------------------------------------------------------- model
// One shape for both data sources: { questions: [...], answer(q, county), countyAnswers(q) }.
const answered = a => !!(a && a.answer && ANSWERED.has(a.status));
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
      // A county's answered row replaces the statewide one in that county; the
      // statewide answer stays readable beneath it (`statewide`). A county row
      // that is still open does not hide an answered statewide one: the state
      // answer is shown and the county's own "where to look" travels with it
      // (`countyOpen`) - the statewide rule still applies in that county.
      answer(q, county) {
        const ca = countyAns(county, q.id);
        const a = statewide.get(q.id);
        const sa = a ? Object.assign({ scope: "state" }, a) : null;
        if (ca && answered(ca)) return Object.assign({ scope: "county", statewide: answered(sa) ? sa : null }, ca);
        if (ca && answered(sa)) return Object.assign({}, sa, { countyOpen: ca });
        if (ca) return Object.assign({ scope: "county" }, ca);
        return sa;
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

// The opening of an answer, word for word (never rewritten): whole sentences
// until about 120 characters, so a short first sentence ("For the first 90 days
// only the county may buy...") is not left without the one that completes it.
// A full stop followed by a capital letter ends a sentence; "s. 197.552" does not.
export function firstSentence(t) {
  const s = String(t || "").trim();
  const parts = s.split(/(?<=[.!?])\s+(?=[A-Z"“(])/);
  let out = "";
  for (const p of parts) { out = out ? out + " " + p : p; if (out.length >= 120) break; }
  return out;
}

// ---------------------------------------------------------------- render parts
function placeName(county, unit) { return / City$/.test(county) ? county : `${county} ${unit}`; }

function linksOf(a) {
  const list = Array.isArray(a && a.links) ? a.links.filter(l => l && isHttps(l.url)) : [];
  if (!list.length && a && isHttps(a.source_url)) list.push({ title: a.source_title || "Official page", url: a.source_url });
  return list;
}

function linkHtml(l, e) { return `<a href="${e(l.url)}" target="_blank" rel="noopener">${e(l.title || "Official page")} <span aria-hidden="true">↗</span></a>`; }

// "Where to look: <link>. Remaining sentence." - the link title is shown once,
// as the link, when the sentence starts with it.
function whereHtml(q, a, e, lead) {
  const where = (a && a.where_to_look) || q.where || "Ask the office that runs the sale.";
  const links = linksOf(a);
  let body = e(where), rest = links;
  if (links.length) {
    const start = `See ${links[0].title}.`;
    if (where.startsWith(start)) { body = linkHtml(links[0], e) + e(where.slice(start.length)); rest = links.slice(1); }
  }
  const more = rest.length ? `<span class="bg-where-links">${rest.map(l => linkHtml(l, e)).join("")}</span>` : "";
  return `<p class="bg-where">${lead ? `<span class="bg-where-for">${e(lead)}</span> ` : ""}<span class="bg-where-l">Where to look:</span> ${body}${more}</p>`;
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

// Provenance, compact: scope · source title (link) · checked <date> · office,
// with the source's own wording folded beneath. Never dropped.
function provenanceHtml(a, ctx) {
  const e = ctx.esc;
  const link = isHttps(a.source_url) ? `<span class="bg-meta-src">${linkHtml({ url: a.source_url, title: a.source_title || "Official source" }, e)}</span>` : "";
  const meta = [`<span class="bg-scope">${e(scopeChip(a, ctx))}</span>`, link,
    a.verified_on ? `<span class="bg-meta-date">checked ${e(ctx.fmtDate(a.verified_on))}</span>` : "",
    a.office ? `<span>${e(a.office)}</span>` : ""].filter(Boolean).join("");
  const quote = a.quote ? `<details class="bg-src"><summary>Official wording</summary><blockquote class="bg-quote${mostlyCaps(a.quote) ? " bg-caps" : ""}">${e(a.quote)}</blockquote></details>` : "";
  return `<p class="bg-meta">${meta}</p>${quote}`;
}

function answerBodyHtml(a, ctx) {
  const e = ctx.esc;
  const steps = Array.isArray(a.steps) && a.steps.length ? `<ol class="bg-steps">${a.steps.map(s => `<li>${e(s)}</li>`).join("")}</ol>` : "";
  return `<p class="bg-answer">${e(a.answer)}</p>${steps}${provenanceHtml(a, ctx)}`;
}

function answeredRowHtml(q, a, ctx, isOpen) {
  const e = ctx.esc;
  const verified = a.status === "VERIFIED";
  // Under a county answer, the statewide rule for the same question.
  const also = a.statewide ? `<div class="bg-also"><p class="bg-also-k">Statewide</p>${answerBodyHtml(a.statewide, ctx)}</div>` : "";
  // A county page not yet read for a question the state answers.
  const countyOpen = a.countyOpen && ctx.county ? whereHtml(q, a.countyOpen, e, `${placeName(ctx.county, ctx.unit)}: not yet confirmed.`) : "";
  return `<details class="bg-q bg-q-ok${verified ? " bg-q-verified" : ""}" data-bg-q="${e(q.id)}" data-bg-status="${e(a.status)}" data-bg-scope="${e(a.scope || "state")}"${verified ? ' data-bg-verified="1"' : ""}${isOpen ? " open" : ""}>
    <summary><span class="bg-q-text">${e(q.question)}</span>${a.status === "PARTIALLY_VERIFIED" ? chipHtml(a.status, e) : ""}</summary>
    <div class="bg-a">${answerBodyHtml(a, ctx)}${also}${countyOpen}</div></details>`;
}

function openRowHtml(q, a, ctx) {
  const e = ctx.esc;
  const status = a && a.status === "SOURCE_RESTRICTED" ? "SOURCE_RESTRICTED" : "NOT_VERIFIED";
  return `<div class="bg-q bg-q-open" data-bg-q="${e(q.id)}" data-bg-status="${status}">
    <p class="bg-q-line"><span class="bg-q-text">${e(q.question)}</span>${chipHtml(status, e)}</p>${whereHtml(q, a, e)}</div>`;
}

function stepHtml(step, n, items, ctx, closed) {
  const e = ctx.esc;
  const done = items.filter(x => answered(x.a));
  const todo = items.filter(x => !answered(x.a));
  return `<section class="bg-step" id="bgStep-${e(step.id)}" data-bg-step="${e(step.id)}" aria-labelledby="bgStepH-${e(step.id)}">
    <header class="bg-step-head"><span class="bg-step-n" aria-hidden="true">${n}</span>
      <div class="bg-step-hd"><p class="bg-step-k">Step ${n} · ${e(step.label)}</p><h2 class="bg-step-h" id="bgStepH-${e(step.id)}">${e(step.title)}</h2></div></header>
    ${done.length ? `<div class="bg-list">${done.map(x => answeredRowHtml(x.q, x.a, ctx, !closed.has(x.q.id))).join("")}</div>` : ""}
    ${todo.length ? `<div class="bg-todo"><h3 class="bg-todo-h">Still to confirm (${todo.length})</h3>${todo.map(x => openRowHtml(x.q, x.a, ctx)).join("")}</div>` : ""}
  </section>`;
}

// "The short version": three lines, each the first sentence of an answer in the
// file (the "what" line: the ledger's summary sentence when there is one), with
// a link to the full answer below. An unanswered line says "Not yet confirmed".
function shortVersionHtml(ledger, model, county, ctx, stepOf) {
  const e = ctx.esc;
  const rows = (SHORT_VERSION[ledger] || []).map(([key, label, qid]) => {
    const q = model.questions.find(x => x.id === qid);
    const a = q ? model.answer(q, county) : null;
    const own = answered(a) && a.scope === "county" && county;
    let from, text = "", src = "";
    if (key === "what" && model.summary && !own) { from = "summary"; text = model.summary; }
    else if (answered(a)) {
      from = a.scope === "county" ? "county" : "answer"; text = firstSentence(a.answer);
      src = [isHttps(a.source_url) ? linkHtml({ url: a.source_url, title: a.source_title || "Official source" }, e) : "", a.verified_on ? `checked ${e(ctx.fmtDate(a.verified_on))}` : ""].filter(Boolean).join(" · ");
    } else from = "missing";
    const target = q && stepOf(qid) ? qid : null;
    const more = target ? `<button type="button" class="bg-short-more" data-bg-goto="${e(target)}">${from === "missing" ? "Where to look" : "Full answer"} <span aria-hidden="true">↓</span></button>` : "";
    const body = from === "missing"
      ? `<span class="bg-short-none">Not yet confirmed.</span>${target ? "" : " Ask the office that runs the sale before you pay."}`
      : `<span class="bg-short-t">${e(text)}</span>`;
    return `<div class="bg-short-row" data-bg-short="${key}" data-bg-short-from="${from}"${q ? ` data-bg-short-q="${e(qid)}"` : ""}>
      <dt>${e(label)}${from === "county" ? ` <span class="bg-short-scope">${e(placeName(county, ctx.unit))}</span>` : ""}</dt>
      <dd>${body} ${more}${src ? `<span class="bg-short-src">${src}</span>` : ""}</dd></div>`;
  }).join("");
  return `<section class="bg-short" aria-labelledby="bgShortH"><h2 class="bg-short-h" id="bgShortH">The short version</h2><dl class="bg-short-list">${rows}</dl></section>`;
}

// Statewide view: the questions whose answers differ by county, with the county
// picker in plain sight (it used to sit behind a collapsed bar).
function calloutHtml(moved, counties, ctx) {
  const e = ctx.esc;
  if (!moved.length) return "";
  const unit = ctx.unit.toLowerCase();
  const plural = unit === "parish" ? "parishes" : "counties";
  const all = Array.from(new Set(moved.flatMap(x => x.counties).concat(counties))).sort();
  const opts = `<option value="">Choose a ${e(unit)}</option>` + all.map(c => `<option value="${e(c)}">${e(placeName(c, ctx.unit))}</option>`).join("");
  return `<aside class="bg-callout" data-bg-callout aria-labelledby="bgCalloutH">
    <h2 class="bg-callout-t" id="bgCalloutH">Pick your ${e(unit)} for its own answers</h2>
    <p class="bg-callout-p">${moved.length === 1 ? "This question is" : "These questions are"} answered by each ${e(unit)}'s own official page, not statewide. The statewide answers stay shown under the ${e(unit)}'s.</p>
    <label class="bg-callout-pick"><span>${e(ctx.unit)}</span><select data-bg-callout-county aria-label="Open the guide for a ${e(unit)}">${opts}</select></label>
    <ul class="bg-callout-list">${moved.map(x => `<li><span>${e(x.q.question)}</span><span class="bg-callout-n">${x.counties.length} ${x.counties.length === 1 ? e(unit) : plural}</span></li>`).join("")}</ul></aside>`;
}

function ledgerTabsHtml(order, ledger, ctx) {
  const e = ctx.esc;
  const idx = order.indexOf(ledger);
  const from = UI.lastLedger && order.includes(UI.lastLedger) ? order.indexOf(UI.lastLedger) : idx;
  return `<div class="bg-seg" role="group" aria-label="Ledger" style="--bg-n:${order.length};--bg-i:${from}" data-bg-to="${idx}">
    <span class="bg-seg-thumb" aria-hidden="true"></span>
    ${order.map(k => `<button type="button" class="bg-tab${k === ledger ? " on" : ""}" data-bg-ledger="${k}" data-tab-ledger="${k}" aria-pressed="${k === ledger}" aria-label="${e(LEDGER_NAMES[k])}"><span class="bg-tab-long">${e(LEDGER_NAMES[k])}</span><span class="bg-tab-short" aria-hidden="true">${e(LEDGER_SHORT[k])}</span></button>`).join("")}
  </div>`;
}

// The next step: back to this ledger's properties (with the count the app
// already has; no count is shown when it has none), and the other two guides.
function nextStepHtml(order, ledger, county, ctx) {
  const e = ctx.esc;
  let where = county, n = typeof ctx.count === "function" ? ctx.count(ledger, county) : null;
  // A county with none listed: the state's list instead, never "See the 0 ...".
  if (county && n === 0) { where = null; n = typeof ctx.count === "function" ? ctx.count(ledger, null) : null; }
  const place = where ? placeName(where, ctx.unit) : ctx.stateName;
  const noun = LEDGER_NOUN[ledger] || ["property", "properties"];
  const label = typeof n === "number" && n > 0 ? `See the ${n.toLocaleString("en-US")} ${n === 1 ? noun[0] : noun[1]} in ${place}` : `See the ${noun[1]} in ${place}`;
  const list = typeof ctx.openList === "function"
    ? `<button type="button" class="bg-next-go" data-bg-list="${e(ledger)}"${where ? ` data-bg-list-county="${e(where)}"` : ""}${typeof n === "number" ? ` data-bg-count="${n}"` : ""}>${e(label)} <span aria-hidden="true">→</span></button>` : "";
  const others = order.filter(k => k !== ledger).map(k => `<li><button type="button" class="bg-next-guide" data-bg-ledger-go="${e(k)}">Buyer's Guide: ${e(LEDGER_NAMES[k])} <span aria-hidden="true">→</span></button></li>`).join("");
  return `<section class="bg-next" aria-labelledby="bgNextH"><h2 class="bg-next-h" id="bgNextH">Next step</h2>
    ${list}<p class="bg-next-p">Or read how the other sales work:</p><ul class="bg-next-list">${others}</ul></section>`;
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
  const stepOf = id => (steps.find(s => s.items.some(x => x.q.id === id)) || {}).step || null;

  const verifiedN = all.filter(x => x.a && x.a.status === "VERIFIED").length;
  const place = county ? placeName(county, ctx.unit) : ctx.stateName;
  const key = `${ctx.state}|${ledger}|${county || ""}`;
  const closed = closedSet(key);
  const opts = `<option value="">All of ${e(ctx.stateName)} (statewide)</option>` + counties.map(c => `<option value="${e(c)}"${c === county ? " selected" : ""}>${e(placeName(c, ctx.unit))}</option>`).join("");
  const rail = steps.map((s, i) => `<li><button type="button" class="bg-jump" data-bg-jump="${e(s.step.id)}"><span class="bg-jump-n" aria-hidden="true">${i + 1}</span><span class="bg-jump-l">${e(s.step.title)}</span></button></li>`).join("");
  const anyAnswered = shown.some(x => answered(x.a));

  root.innerHTML = `<div class="bg-page" data-ledger="${ledger}" data-bg-mode="${model.mode}"${county ? ` data-bg-county-on="${e(county)}"` : ""}>
    <header class="bg-hero">
      <p class="bg-eyebrow">Buyer's Guide · ${e(ctx.stateName)}</p>
      <h1 class="bg-title">${e(LEDGER_HERO[ledger])} in ${e(place)}</h1>
      <p class="bg-lede">How it works, what it costs and how to buy - each answer from an official page, with its source and the date it was checked.</p>
      <p class="bg-legal">Answers describe the public process, not any one property. Not legal advice - confirm with the office before you pay.${model.mode === "rules" ? " The full guide is being prepared; these answers come from the verified rules on file." : ""}</p>
    </header>
    <div class="bg-controls">
      ${ledgerTabsHtml(order, ledger, ctx)}
      <label class="bg-county"><span class="bg-county-l">Showing:</span><select data-bg-county aria-label="Showing: ${e(ctx.unit)} or statewide">${opts}</select></label>
    </div>
    ${shortVersionHtml(ledger, model, county, c2, stepOf)}
    ${county ? "" : calloutHtml(moved, counties, c2)}
    ${county && ledger === "AVAILABLE" && typeof ctx.countyProcessHtml === "function" ? (ctx.countyProcessHtml(county) || "") : ""}
    <div class="bg-body">
      <nav class="bg-rail" aria-label="On this page"><p class="bg-rail-h" aria-hidden="true">On this page</p><ol>${rail}<li><button type="button" class="bg-jump bg-jump-next" data-bg-jump="next"><span class="bg-jump-n" aria-hidden="true">→</span><span class="bg-jump-l">Next step</span></button></li></ol></nav>
      <div class="bg-main" id="bgMain">
        <div class="bg-tools">
          <div class="bg-search-wrap"><input class="bg-search" type="search" placeholder="Search the guide" aria-label="Search the guide" data-bg-search autocomplete="off"></div>
          ${anyAnswered ? `<button type="button" class="bg-expand" data-bg-expand aria-controls="bgMain" aria-expanded="true">Collapse all</button>` : ""}
        </div>
        <p class="bg-count" role="status" aria-live="polite"></p>
        ${steps.map((s, i) => stepHtml(s.step, i + 1, s.items, c2, closed)).join("")}
        <div class="bg-empty" hidden><p>No question matches <span class="bg-empty-q"></span>.</p><button type="button" class="bg-clear" data-bg-clear>Clear search</button></div>
      </div>
    </div>
    ${nextStepHtml(order, ledger, county, c2)}
  </div>`;

  wire(root, ctx, { ledger, county, key, total: shown.length, stepsN: steps.length, stepOf });
  const tb = document.querySelector('html[data-shell="v3"] .topbar');
  root.style.setProperty("--bg-top", (tb ? Math.round(tb.getBoundingClientRect().height) : 0) + "px");
  UI.lastLedger = ledger;
  return { mode: model.mode, verified: verifiedN, total: all.length, shown: shown.length, countyOnly: moved.length, steps: steps.map(s => s.step.id), county };
}

function wire(root, ctx, s) {
  const page = root.querySelector(".bg-page");
  const remember = sel => { UI.trigger = sel; };
  const go = (next, sel) => { remember(sel); ctx.navigate(next); };
  const smooth = () => (reduceMotion() ? "auto" : "smooth");
  root.querySelectorAll("[data-bg-ledger]").forEach(b => b.addEventListener("click", () => {
    if (b.dataset.bgLedger !== s.ledger) go({ ledger: b.dataset.bgLedger, county: s.county }, `[data-bg-ledger="${b.dataset.bgLedger}"]`);
  }));
  // The other guides, from the bottom of the page: open at the top.
  root.querySelectorAll("[data-bg-ledger-go]").forEach(b => b.addEventListener("click", () => {
    go({ ledger: b.dataset.bgLedgerGo, county: s.county }, `[data-bg-ledger="${b.dataset.bgLedgerGo}"]`);
    window.scrollTo({ top: 0, behavior: "auto" });
  }));
  const sel = root.querySelector("[data-bg-county]");
  if (sel) sel.addEventListener("change", () => go({ ledger: s.ledger, county: sel.value || null }, "[data-bg-county]"));
  const csel = root.querySelector("[data-bg-callout-county]");
  if (csel) csel.addEventListener("change", () => { if (csel.value) go({ ledger: s.ledger, county: csel.value }, "[data-bg-county]"); });
  const listBtn = root.querySelector("[data-bg-list]");
  if (listBtn && typeof ctx.openList === "function") listBtn.addEventListener("click", () => ctx.openList(listBtn.dataset.bgList, listBtn.dataset.bgListCounty || null));

  const closed = closedSet(s.key);
  const rows = () => Array.from(root.querySelectorAll("details.bg-q"));
  const expand = root.querySelector("[data-bg-expand]");
  const syncExpand = () => {
    if (!expand) return;
    const allOpen = rows().filter(d => !d.hidden).every(d => d.open);
    expand.textContent = allOpen ? "Collapse all" : "Expand all";
    expand.setAttribute("aria-expanded", allOpen ? "true" : "false");
  };
  rows().forEach(d => d.addEventListener("toggle", () => {
    if (!d.dataset.bgAuto) { if (d.open) closed.delete(d.dataset.bgQ); else closed.add(d.dataset.bgQ); }
    syncExpand();
  }));
  if (expand) expand.addEventListener("click", () => {
    const open = expand.getAttribute("aria-expanded") !== "true";
    rows().forEach(d => { delete d.dataset.bgAuto; d.open = open; if (open) closed.delete(d.dataset.bgQ); else closed.add(d.dataset.bgQ); });
    syncExpand();
  });
  const focusHeading = t => { const h = t.querySelector(".bg-step-h, .bg-next-h"); if (h) { h.setAttribute("tabindex", "-1"); h.focus({ preventScroll: true }); } };
  root.querySelectorAll("[data-bg-jump]").forEach(b => b.addEventListener("click", () => {
    const t = b.dataset.bgJump === "next" ? root.querySelector(".bg-next") : root.querySelector(`#bgStep-${b.dataset.bgJump}`);
    if (!t) return;
    t.scrollIntoView({ behavior: smooth(), block: "start" });
    focusHeading(t);
  }));
  // The short version's "Full answer" / "Where to look": open that question and go to it.
  root.querySelectorAll("[data-bg-goto]").forEach(b => b.addEventListener("click", () => {
    const t = root.querySelector(`.bg-q[data-bg-q="${b.dataset.bgGoto}"]`);
    if (!t) return;
    if (t.hidden && search.value) { search.value = ""; apply(); }
    if (t.tagName === "DETAILS" && !t.open) t.open = true;
    t.scrollIntoView({ behavior: smooth(), block: "start" });
    const f = t.querySelector("summary") || t.querySelector("a");
    if (f) f.focus({ preventScroll: true });
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
        else if (!t && d.dataset.bgAuto) { d.open = !closed.has(d.dataset.bgQ); }
        if (!t) setTimeout(() => { delete d.dataset.bgAuto; }, 0);
      }
    });
    root.querySelectorAll(".bg-step").forEach(sec => { sec.hidden = !sec.querySelector(".bg-q:not([hidden])"); });
    root.querySelectorAll(".bg-todo").forEach(g => { g.hidden = !g.querySelector(".bg-q:not([hidden])"); });
    root.querySelectorAll(".bg-jump[data-bg-jump]").forEach(b => { const sec = root.querySelector(`#bgStep-${b.dataset.bgJump}`); b.classList.toggle("dim", !!(sec && sec.hidden)); });
    if (empty) { empty.hidden = !t || n > 0; const q = empty.querySelector(".bg-empty-q"); if (q) q.textContent = `“${search.value.trim()}”`; }
    // Only a search result is announced; the plain page needs no count line.
    count.textContent = t ? (n ? `${n} ${n === 1 ? "question matches" : "questions match"} “${search.value.trim()}”.` : `No question matches “${search.value.trim()}”. Press Escape to clear.`) : "";
    // The empty box below says the same sentence on screen; the status line
    // stays for the screen-reader announcement only, so it is not read twice.
    count.classList.toggle("bg-sr", !!(empty && !empty.hidden));
    syncExpand();
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
    if (reduceMotion()) seg.style.setProperty("--bg-i", to);
    else requestAnimationFrame(() => requestAnimationFrame(() => seg.style.setProperty("--bg-i", to)));
  }
  // Focus returns to the control that caused the re-render.
  if (UI.trigger) {
    const t = root.querySelector(UI.trigger);
    UI.trigger = null;
    if (t) t.focus({ preventScroll: true });
  }
  if (page && !reduceMotion()) page.classList.add("bg-anim");
}
