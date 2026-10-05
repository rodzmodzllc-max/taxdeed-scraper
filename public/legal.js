// Legal pages: fill the business details from config.js (TDW_CONFIG.legal,
// supportEmail, billing.priceDisplay). Nothing is invented: a value that is
// not configured is shown as "not configured" and listed in the notice at
// the top of the page, so an incomplete document never reads as complete.
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
  var labels = {
    operatorName: "the operator's legal business name (legal.operatorName)",
    governingLaw: "the governing law / jurisdiction (legal.governingLaw)",
    effectiveDate: "the effective date (legal.effectiveDate)",
    contactEmail: "a contact e-mail address (legal.contactEmail or supportEmail)",
    priceDisplay: "the subscription price (billing.priceDisplay)"
  };
  var missing = {};
  var nodes = document.querySelectorAll("[data-legal]");
  for (var i = 0; i < nodes.length; i++) {
    var key = nodes[i].getAttribute("data-legal");
    var v = values[key];
    if (v) {
      if (key === "contactEmail") { nodes[i].innerHTML = ""; var a = document.createElement("a"); a.href = "mailto:" + v; a.textContent = v; nodes[i].appendChild(a); }
      else nodes[i].textContent = v;
    } else {
      nodes[i].textContent = "[not configured]";
      nodes[i].className += " legal-missing";
      missing[key] = true;
    }
  }
  var keys = Object.keys(missing);
  var box = document.getElementById("legalUnconfigured");
  if (box && keys.length) {
    box.hidden = false;
    box.textContent = "This document is not complete for this deployment. Not yet configured: " + keys.map(function (k) { return labels[k]; }).join("; ") + ".";
  }
  document.documentElement.setAttribute("data-legal-missing", keys.join(","));
})();
