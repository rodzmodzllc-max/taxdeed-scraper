// Legal pages: fill the business details from config.js (TDW_CONFIG.legal,
// supportEmail, billing.priceDisplay). Nothing is invented. A value that is
// not configured is never shown to a customer as a placeholder or as setup
// text (audit F66 / F103): the clause that needs it is left out instead
// (elements marked data-legal-needs="<key>"), or a span carrying
// data-legal-fallback gets that neutral, true wording. Which values are
// missing stays readable for the operator on <html data-legal-missing> and
// in the console - never on the page.
(function () {
  var cfg = window.TDW_CONFIG || {};
  var legal = cfg.legal || {};
  var billing = cfg.billing || {};
  var values = {
    operatorName: String(legal.operatorName || "").trim(),
    governingLaw: String(legal.governingLaw || "").trim(),
    effectiveDate: String(legal.effectiveDate || "").trim(),
    contactEmail: String(legal.contactEmail || cfg.supportEmail || "").trim(),
    priceDisplay: String(billing.priceDisplay || "").trim()
  };
  var missing = {};
  var keys = [];
  function note(key) { if (!missing[key]) { missing[key] = true; keys.push(key); } }
  var nodes = document.querySelectorAll("[data-legal]");
  for (var i = 0; i < nodes.length; i++) {
    var key = nodes[i].getAttribute("data-legal");
    var v = values[key];
    if (v) {
      if (key === "contactEmail") { nodes[i].innerHTML = ""; var a = document.createElement("a"); a.href = "mailto:" + v; a.textContent = v; nodes[i].appendChild(a); }
      else nodes[i].textContent = v;
      continue;
    }
    note(key);
    var fallback = nodes[i].getAttribute("data-legal-fallback");
    if (fallback) nodes[i].textContent = fallback;
    else { nodes[i].textContent = ""; nodes[i].hidden = true; }
  }
  // Leave out every clause whose value is not configured.
  var clauses = document.querySelectorAll("[data-legal-needs]");
  for (var j = 0; j < clauses.length; j++) {
    var needs = clauses[j].getAttribute("data-legal-needs").split(/\s+/);
    for (var k = 0; k < needs.length; k++) {
      if (needs[k] && !values[needs[k]]) { note(needs[k]); clauses[j].hidden = true; break; }
    }
  }
  // The "Operator · Effective" line: a separator only between two shown
  // parts, and no line at all when neither is configured.
  var metas = document.querySelectorAll(".legal-meta");
  for (var m = 0; m < metas.length; m++) {
    var parts = metas[m].querySelectorAll("[data-legal-needs]");
    var shown = 0;
    for (var p = 0; p < parts.length; p++) if (!parts[p].hidden) shown++;
    var seps = metas[m].querySelectorAll("[data-legal-sep]");
    for (var s = 0; s < seps.length; s++) seps[s].hidden = shown < 2;
    if (parts.length && !shown) metas[m].hidden = true;
  }
  document.documentElement.setAttribute("data-legal-missing", keys.join(","));
  if (keys.length && window.console && console.info) console.info("Legal page: not configured in config.js: " + keys.join(", "));
})();
