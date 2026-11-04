// Buyer's Guide (2026-10-29, owner's request): the questions a buyer asks
// before acting, per state, ledger and county, each answered from an official
// source or plainly marked "Not yet verified" with where to look.
//
// Data: public/buyers-guide.json (backend-generated; contract in
// docs/buyers-guide-contract.md). Until that file exists the guide is built
// from public/state-rules.json - the verified rules and county procedures
// already on file - mapped onto the same questions by rule topic. Nothing here
// invents an answer: a question with no recorded answer says so.
//
// Loaded on demand by app.js (showPage("guide") -> import("./buyers-guide.js")).
// app.js passes everything page-specific through `ctx`; this module reads no
// app.js globals and makes no request other than the two JSON files.

const LEDGERS = [["AVAILABLE", "Available"], ["AUCTIONS", "Auctions"], ["LIENS_CERTIFICATES", "Liens & Certificates"]];
const STATUS_LABELS = { VERIFIED: "Verified", PARTIALLY_VERIFIED: "Partly verified", NOT_VERIFIED: "Not yet verified", SOURCE_RESTRICTED: "Source restricted" };

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

let GUIDE_PROMISE = null;
function loadGuide() {
  if (!GUIDE_PROMISE) {
    const get = u => fetch(u, { cache: "no-cache" }).then(r => (r.ok ? r.json() : null)).catch(() => null);
    GUIDE_PROMISE = Promise.all([get("buyers-guide.json"), get("state-rules.json")]).then(([guide, rules]) => ({ guide, rules }));
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

// ---------------------------------------------------------------- model
// One shape for both data sources: { questions: [...], answersFor(county) }.
function ledgerModel(data, st, ledger) {
  const g = data.guide;
  if (g && g.states && has(g.states, st)) {
    const s = g.states[st];
    const qs = (g.questions && g.questions[ledger]) || [];
    const base = ((s.ledgers || {})[ledger] || {});
    const statewide = new Map((base.answers || []).map(a => [a.q, a]));
    return {
      mode: "guide",
      summary: base.summary || null,
      offered: base.offered || null,
      questions: qs.map(q => ({ id: q.id, group: q.group || "", question: q.question, where: q.where_to_look || q.where || "" })),
      counties: Object.keys(s.counties || {}).filter(c => has(s.counties[c], ledger)).sort(),
      answer(q, county) {
        const c = county && s.counties && s.counties[county] && s.counties[county][ledger];
        const ca = c && (c.answers || []).find(a => a.q === q.id);
        if (ca) return Object.assign({ scope: "county" }, ca);
        const a = statewide.get(q.id);
        return a ? Object.assign({ scope: "state" }, a) : null;
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
  return {
    mode: "rules",
    summary: null, offered: null,
    questions: qs,
    counties: Array.from(new Set(rules.filter(r => r.county && inLedger(r)).map(r => r.county).concat(procs.filter(procLedger).map(p => p.county)))).filter(Boolean).sort(),
    answer(q, county) {
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
    },
  };
}

// ---------------------------------------------------------------- render
function answerHtml(q, a, ctx) {
  const e = ctx.esc;
  if (!a || !a.answer) {
    return `<div class="bg-a bg-a-open"><span class="bg-status muted">Not yet verified</span><p class="bg-where">${e((a && a.where_to_look) || q.where || "Ask the office that runs the sale.")}</p></div>`;
  }
  const status = STATUS_LABELS[a.status] || a.status || "";
  const verified = a.status === "VERIFIED";
  const steps = Array.isArray(a.steps) && a.steps.length ? `<ol class="bg-steps">${a.steps.map(s => `<li>${e(s)}</li>`).join("")}</ol>` : "";
  const link = a.source_url && /^https:\/\//.test(a.source_url) ? `<a href="${e(a.source_url)}" target="_blank" rel="noopener">${e(a.source_title || "Official source")} →</a>` : "";
  const meta = [a.citation ? e(a.citation) : "", a.office ? e(a.office) : "", verified && a.verified_on ? "Checked " + e(ctx.fmtDate(a.verified_on)) : "", a.scope === "county" ? `${e(ctx.county || "")} ${e(ctx.unit)} only` : "Statewide"].filter(Boolean);
  return `<div class="bg-a">${verified ? "" : `<span class="bg-status muted">${e(status)}</span>`}
    <p class="bg-answer">${e(a.answer)}</p>${steps}
    ${a.quote ? `<blockquote class="bg-quote">${e(a.quote)}</blockquote>` : ""}
    ${!verified && a.where_to_look ? `<p class="bg-where">${e(a.where_to_look)}</p>` : ""}
    <p class="bg-meta">${link ? `<span>${link}</span>` : ""}${meta.map(m => `<span>${m}</span>`).join("")}</p></div>`;
}

export function render(root, ctx) {
  ensureCss();
  const e = ctx.esc;
  root.innerHTML = `<div class="bg-page"><p class="bg-loading">Loading the buyer's guide…</p></div>`;
  return loadGuide().then(data => {
    const ledger = LEDGERS.some(l => l[0] === ctx.ledger) ? ctx.ledger : "AVAILABLE";
    const model = ledgerModel(data, ctx.state, ledger);
    const counties = Array.from(new Set(model.counties.concat(ctx.counties || []))).sort();
    const county = ctx.county && counties.includes(ctx.county) ? ctx.county : null;
    const c2 = Object.assign({}, ctx, { county });
    const answered = model.questions.map(q => ({ q, a: model.answer(q, county) }));
    const verifiedN = answered.filter(x => x.a && x.a.status === "VERIFIED").length;
    const groups = [];
    answered.forEach(x => { const g = x.q.group || ""; let grp = groups.find(y => y.name === g); if (!grp) groups.push(grp = { name: g, items: [] }); grp.items.push(x); });
    const tabs = LEDGERS.map(([k, label]) => `<button type="button" class="bg-tab${k === ledger ? " on" : ""}" data-bg-ledger="${k}" aria-pressed="${k === ledger}">${e(label)}</button>`).join("");
    const opts = `<option value="">Statewide</option>` + counties.map(c => `<option value="${e(c)}"${c === county ? " selected" : ""}>${e(c)} ${e(ctx.unit)}</option>`).join("");
    root.innerHTML = `<div class="bg-page">
      <header class="bg-head">
        <p class="bg-eyebrow">Buyer's Guide · ${e(ctx.stateName)}</p>
        <h1 class="bg-title">${county ? `${e(county)} ${e(ctx.unit)}` : e(ctx.stateName)}</h1>
        <p class="bg-lede">The questions to answer before you act - each from an official source, or marked not yet verified with where to look. Not legal advice.</p>
      </header>
      <div class="bg-controls">
        <div class="bg-tabs" role="group" aria-label="Ledger">${tabs}</div>
        <label class="bg-county"><span>${e(ctx.unit)}</span><select data-bg-county aria-label="${e(ctx.unit)}">${opts}</select></label>
        <input class="bg-search" type="search" placeholder="Search questions" aria-label="Search questions" data-bg-search>
      </div>
      ${model.summary ? `<p class="bg-summary">${e(model.summary)}</p>` : ""}
      <p class="bg-count">${verifiedN} of ${model.questions.length} questions answered from an official source${county ? ` for ${e(county)} ${e(ctx.unit)}` : " statewide"}.${model.mode === "rules" ? " The full guide is being prepared; these answers come from the verified rules on file." : ""}</p>
      ${groups.map(g => `<section class="bg-group">${g.name ? `<h2 class="bg-group-h">${e(g.name)}</h2>` : ""}
        ${g.items.map(({ q, a }) => `<details class="bg-q" data-bg-q="${e(q.id)}"${a && a.status === "VERIFIED" ? ' data-bg-verified="1"' : ""}><summary><span class="bg-q-text">${e(q.question)}</span><span class="bg-q-badge ${a && a.status === "VERIFIED" ? "ok" : "muted"}">${a && a.answer ? e(STATUS_LABELS[a.status] || "") : "Open"}</span></summary>${answerHtml(q, a, c2)}</details>`).join("")}
      </section>`).join("")}
      <p class="bg-foot">Answers describe the public process, not any one property. Confirm with the office before you pay.</p>
    </div>`;
    root.querySelectorAll("[data-bg-ledger]").forEach(b => b.addEventListener("click", () => ctx.navigate({ ledger: b.dataset.bgLedger, county })));
    const sel = root.querySelector("[data-bg-county]");
    if (sel) sel.addEventListener("change", () => ctx.navigate({ ledger, county: sel.value || null }));
    const search = root.querySelector("[data-bg-search]");
    if (search) search.addEventListener("input", () => {
      const t = search.value.trim().toLowerCase();
      root.querySelectorAll(".bg-q").forEach(d => { d.hidden = !!t && !d.textContent.toLowerCase().includes(t); if (t && !d.hidden) d.open = true; });
      root.querySelectorAll(".bg-group").forEach(s => { s.hidden = !s.querySelector(".bg-q:not([hidden])"); });
    });
    return { mode: model.mode, verified: verifiedN, total: model.questions.length };
  });
}
