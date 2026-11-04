// Admin area (/admin) - 2026-09-30.
//
// WHO MAY SEE THIS PAGE IS DECIDED BY THE SERVER, NOT BY THIS FILE.
// Authentication is the app's existing Supabase Auth (email + password,
// checked and hashed by Supabase - this file never sees or compares a
// password). The ADMIN ROLE is the existing server-side one: the
// `profiles.is_admin` column, read here through PostgREST under row-level
// security ("profiles: read own row" - a user can read only their own row,
// and only an existing admin can write any row, via public.is_admin()). The
// session token is Supabase's signed JWT; editing localStorage /
// sessionStorage / window state cannot make the database return
// is_admin = true for an account that is not an admin.
//
// Pending sign-ups: the SAME approval mechanism the application's own admin
// panel uses (app.js refreshAdminApprovals) - list profiles with
// approved = false, and approve one by setting approved = true +
// approved_at. Both the read of other users' rows and the write are allowed
// by the server only for an admin ("profiles: admin full access", on
// public.is_admin()); a non-admin's request returns nothing / changes
// nothing whatever this page does. There is no reject: an account that is
// not approved stays pending. Source publication reviews stay in the
// application's admin panel.
//
// Flow: no session -> the normal sign-in (index.html). Session but the
// server says not an admin -> the normal application (index.html). Admin ->
// the shell, identified only as "Admin" (no e-mail address shown).
import { loadCreateClient } from "./supabase-loader.js";
// esm.sh first, this site's own copy if that fails or hangs (supabase-loader.js).
const createClient = await loadCreateClient();

const cfg = window.TDW_CONFIG || {};
const APP_URL = "index.html";

function leave() {
  // replace(): /admin never stays in the history of someone it refused.
  location.replace(APP_URL);
}

const sb = cfg.supabaseUrl && cfg.supabasePublishableKey
  ? createClient(cfg.supabaseUrl, cfg.supabasePublishableKey, {
      auth: { storage: window.sessionStorage, persistSession: true, autoRefreshToken: true, detectSessionInUrl: false }
    })
  : null;

// The server's answer for the signed-in user, or false on any doubt
// (no session, no profile row, a query error): fail closed.
async function serverSaysAdmin() {
  if (!sb) return { user: null, admin: false };
  const { data: sess } = await sb.auth.getSession();
  const user = sess && sess.session && sess.session.user;
  if (!user) return { user: null, admin: false };
  const { data, error } = await sb.from("profiles").select("is_admin").eq("id", user.id).maybeSingle();
  return { user, admin: !error && !!(data && data.is_admin === true) };
}

async function gate() {
  const { user, admin } = await serverSaysAdmin();
  if (!user || !admin) { leave(); return; }
  document.getElementById("adminIdentity").textContent = "Admin";
  document.getElementById("adminShell").hidden = false;
  document.body.dataset.admin = "verified";
  sendApprovalNotifications();          // sweep: send any approval e-mail whose retry is due
  const attention = refreshAttention().catch(e => {
    const st = document.getElementById("adminAttentionStatus");
    if (st) st.textContent = "Could not build the Needs attention list: " + (e && e.message ? e.message : e);
  });
  await refreshPending();
  await refreshCustomers();
  await refreshUsage();
  await refreshSources();
  await refreshFreshness();
  initInventory();
  await attention;
}

// Product usage (migration 024's product_usage_summary(), admin-only on the
// server: is_admin() inside a SECURITY DEFINER function). Without 024 the
// card says so instead of showing zeros.
const USAGE_LABELS = {
  session_start: "Sessions", search_performed: "Searches / filter changes", property_viewed: "Property pages viewed",
  property_saved: "Favorites added", property_watched: "Watchlist adds", acquisition_source_opened: "Acquisition source links opened",
  acquisition_instructions_opened: "Acquisition instructions opened", application_opened: "Application documents opened",
  official_source_opened: "Official source links opened", export_performed: "Exports", alert_created: "Alerts set up",
  alert_opened: "Alerts opened", saved_search_created: "Saved searches created", saved_search_opened: "Saved searches opened"
};
async function refreshUsage() {
  const status = document.getElementById("adminUsageStatus");
  const list = document.getElementById("adminUsageList");
  if (!status || !list) return;
  const { data, error } = await sb.rpc("product_usage_summary", { p_days: 30 });
  if (error) {
    const missing = error.code === "PGRST202" || /could not find the function/i.test(error.message || "");
    status.textContent = missing ? "Usage analytics are not enabled on this deployment yet (migration 024 has not been applied)." : "Could not load usage: " + error.message;
    list.innerHTML = "";
    return;
  }
  const rows = data || [];
  status.textContent = rows.length ? "" : "No usage recorded in the last 30 days.";
  list.innerHTML = rows.length ? `<table class="admin-usage-table"><thead><tr><th>Action</th><th>Count</th><th>Accounts</th></tr></thead><tbody>${rows.map(r =>
    `<tr data-event="${esc(r.event)}"><td>${esc(USAGE_LABELS[r.event] || r.event)}</td><td>${esc(r.events)}</td><td>${esc(r.users)}</td></tr>`).join("")}</tbody></table>` : "";
}

// Sources (all-sources enrichment engine, 2026-10-01): the unified source
// inventory (public/source-inventory.json, generated from the repository by
// scripts/build_source_inventory.py - value-free) joined with the registry's
// live per-unit freshness (migration 021 columns, approved-read RLS). A source
// the registry does not track shows "not tracked", never a guessed date.
let SOURCES = null;
let FRESHNESS = new Map();
let REGISTRY_UNITS = null;   // every county_source_registry row with its freshness columns (null = the columns are not live)
const TYPE_LABELS = { GOVERNMENT: "Government", DOCUMENT: "PDF / document", GIS: "GIS / parcel", COURT_PUBLIC_RECORD: "Court / public record",
  PUBLIC_NOTICE: "Public notice", AUCTION_VENDOR: "Auction vendor", THIRD_PARTY: "Third party", FEDERAL_DATASET: "Federal dataset" };
async function refreshSources() {
  const status = document.getElementById("adminSourcesStatus");
  if (!status) return;
  try {
    const resp = await fetch("source-inventory.json", { cache: "no-store" });
    SOURCES = resp.ok ? await resp.json() : null;
  } catch { SOURCES = null; }
  if (!SOURCES) { status.textContent = "The source inventory could not be loaded."; return; }
  const { data, error } = await sb.from("county_source_registry")
    .select("state,county,source_id,ledgers,last_attempt_at,last_attempt_status,last_success_at,last_success_row_count,consecutive_failures,last_error_category");
  REGISTRY_UNITS = error ? null : (data || []);
  FRESHNESS = new Map((REGISTRY_UNITS || []).map(r => [`${r.state}:${r.county}:${r.source_id || "unharvested_list"}`, r]));
  const stSel = document.getElementById("adminSourcesState");
  const tySel = document.getElementById("adminSourcesType");
  if (stSel.options.length === 1) {
    [...new Set(SOURCES.sources.map(s => s.state))].sort().forEach(st => stSel.add(new Option(st, st)));
    Object.entries(TYPE_LABELS).forEach(([k, v]) => tySel.add(new Option(v, k)));
    ["adminSourcesState", "adminSourcesGov", "adminSourcesType"].forEach(id => document.getElementById(id).addEventListener("change", renderSources));
  }
  renderSources();
}
function sourceDate(iso) {
  const d = iso ? new Date(iso) : null;
  return d && !isNaN(d) ? d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }) : "";
}
function renderSources() {
  const status = document.getElementById("adminSourcesStatus");
  const list = document.getElementById("adminSourcesList");
  const st = document.getElementById("adminSourcesState").value;
  const gov = document.getElementById("adminSourcesGov").value;
  const ty = document.getElementById("adminSourcesType").value;
  const rows = SOURCES.sources.filter(s => (!st || s.state === st) && (!gov || s.governance === gov) && (!ty || s.source_type === ty));
  const counts = { APPROVED: 0, REVIEW_REQUIRED: 0, HARD_BLOCKED: 0 };
  rows.forEach(s => { counts[s.governance] += 1; });
  status.textContent = `${rows.length} source(s): ${counts.APPROVED} approved, ${counts.REVIEW_REQUIRED} review required, ${counts.HARD_BLOCKED} hard blocked.`;
  list.innerHTML = rows.length ? `<table class="admin-usage-table admin-sources-table"><thead><tr><th>State</th><th>County</th><th>Source</th><th>Type</th><th>Governance</th><th>Access</th><th>Last checked</th><th>Last successful read</th><th>Last failure</th><th>Next action</th></tr></thead><tbody>${rows.map(s => {
    const f = FRESHNESS.get(s.source_id);
    const lastOk = f ? (sourceDate(f.last_success_at) || "never") : "not tracked";
    const failure = f && Number(f.consecutive_failures) > 0 ? `${esc(f.last_attempt_status || "FAILED")} (${esc(f.last_error_category || "error")}) ×${esc(f.consecutive_failures)}` : (f ? "none" : "not tracked");
    const link = s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.name)}</a>` : esc(s.name);
    return `<tr data-source="${esc(s.source_id)}" data-governance="${esc(s.governance)}"><td>${esc(s.state)}</td><td>${esc(s.county)}</td>
      <td>${link}<br><span class="admin-note">${esc(s.publisher)} · ${esc((s.roles || []).join(", "))}</span></td>
      <td>${esc(TYPE_LABELS[s.source_type] || s.source_type)}</td>
      <td><span class="gov-${esc(s.governance.toLowerCase())}">${esc(s.governance)}</span>${s.governance_reason ? `<br><span class="admin-note">${esc(s.governance_reason)}</span>` : ""}</td>
      <td>${esc(s.access)}${s.access_note ? `<br><span class="admin-note">${esc(s.access_note)}</span>` : ""}</td>
      <td>${esc(s.last_checked || "")}</td><td>${esc(lastOk)}</td><td>${failure}</td><td>${esc(s.next_action || "")}</td></tr>`;
  }).join("")}</tbody></table>` : "";
}

function esc(v) {
  return String(v == null ? "" : v).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function requestedOn(iso) {
  const d = iso ? new Date(iso) : null;
  return d && !isNaN(d) ? d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }) : "date not recorded";
}

// Approval e-mail (migration 030 + supabase/functions/notify-approval): the
// approval queued one notification in the same transaction; this asks the
// server to send what is due (fire-and-forget, never blocks the approval).
// Opening this page also sweeps any notification whose retry is due.
function sendApprovalNotifications() {
  try { sb.functions.invoke("notify-approval", { body: {} }).catch(() => {}); } catch (e) { /* never blocks approval */ }
}

// Notification health for administrators (counts only, never an address).
// The outbox holds two kinds; each is counted on its own.
async function approvalNotificationStatus() {
  const { data, error } = await sb.from("account_notifications").select("status,kind");
  if (error || !data) return "";
  const line = (kind, one, many) => {
    const rows = data.filter(r => (r.kind || "account_approved") === kind);
    const n = (st) => rows.filter(r => r.status === st).length;
    const waiting = n("pending") + n("sending") + n("failed");
    return waiting ? ` ${waiting} ${waiting === 1 ? one + " is" : many + " are"} waiting to be sent or retried${n("failed") ? " (" + n("failed") + " failed so far)" : ""}.` : "";
  };
  return line("account_approved", "approval e-mail", "approval e-mails") + line("admin_new_signup", "new sign-up alert", "new sign-up alerts");
}

async function refreshPending() {
  const status = document.getElementById("adminPendingStatus");
  const list = document.getElementById("adminPendingList");
  const { data, error } = await sb.from("profiles").select("id,email,requested_at").eq("approved", false).order("requested_at");
  if (error) { status.textContent = "Could not load pending accounts: " + error.message; list.innerHTML = ""; return; }
  const rows = data || [];
  status.textContent = (rows.length ? rows.length + (rows.length === 1 ? " account is" : " accounts are") + " waiting for approval." : "No accounts are waiting for approval.")
    + await approvalNotificationStatus();
  list.innerHTML = rows.map(p => `
    <span class="admin-approval-row" data-id="${esc(p.id)}">
      <span class="admin-approval-info"><span class="admin-approval-name">${esc(p.email || p.id)}</span></span>
      <span class="admin-approval-when">requested ${esc(requestedOn(p.requested_at))}</span>
      <button class="mini-btn admin-approve-btn" type="button" data-id="${esc(p.id)}">Approve</button>
    </span>`).join("");
  list.querySelectorAll(".admin-approve-btn").forEach(btn => btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "Approving";
    const { error: updErr } = await sb.from("profiles")
      .update({ approved: true, approved_at: new Date().toISOString() })
      .eq("id", btn.dataset.id);
    if (updErr) { btn.disabled = false; btn.textContent = "Approve"; status.textContent = "Could not approve: " + updErr.message; return; }
    sendApprovalNotifications();
    await refreshPending();
  }));
}

// Customers & access (paid beta, migration 027): admin_billing_overview()
// is admin-only on the server (it raises for anyone else) and returns the
// SAME entitlement decision the app enforces. Before 027 is applied, access
// is approval only - the card says so and lists accounts from profiles.
const ROLE_LABELS = { admin: "Administrator", tester: "Tester (beta)", customer: "Customer", inactive: "No access" };
const STATE_LABELS = {
  admin_override: "Administrator", tester_beta: "Approved tester", manual_customer: "Granted by an administrator",
  active: "Paid - active", trial: "Paid - trial", cancelling: "Paid - cancellation scheduled",
  payment_failed_grace: "Payment failed - in grace period", payment_failed: "Payment failed - access paused",
  cancelled: "Cancelled", inactive: "Pending / no subscription"
};
// One date format across admin ("Oct 23, 2026", UTC), matching the other admin
// date helpers. Previously this alone printed ISO dates (2026-10-23).
function dateOnly(v) { const t = v ? Date.parse(v) : NaN; return Number.isNaN(t) ? "" : new Date(t).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" }); }
async function refreshCustomers() {
  const status = document.getElementById("adminCustomersStatus");
  const list = document.getElementById("adminCustomersList");
  if (!status || !list) return;
  const { data, error } = await sb.rpc("admin_billing_overview");
  if (error) {
    const missing = error.code === "PGRST202" || error.code === "42883" || /could not find the function/i.test(error.message || "");
    if (!missing) { status.textContent = "Could not load accounts: " + error.message; list.innerHTML = ""; return; }
    const { data: profs, error: pErr } = await sb.from("profiles").select("email,approved,is_admin,requested_at").order("requested_at");
    if (pErr) { status.textContent = "Could not load accounts: " + pErr.message; list.innerHTML = ""; return; }
    const rows = (profs || []).map(p => ({ email: p.email, role: p.is_admin ? "admin" : p.approved ? "tester" : "inactive",
      state: p.is_admin ? "admin_override" : p.approved ? "tester_beta" : "inactive", access: !!(p.is_admin || p.approved),
      reason: p.is_admin ? "Administrator" : p.approved ? "Approved by an administrator" : "Waiting for approval" }));
    const c = rows.reduce((m, r) => { m[r.role] = (m[r.role] || 0) + 1; return m; }, {});
    status.textContent = "Billing is not installed yet (migration 027 is not applied): access comes from approval only. " +
      ["admin", "tester", "inactive"].map(k => `${c[k] || 0} ${ROLE_LABELS[k].toLowerCase()}`).join(" · ") + ".";
    revealable(list, () => customersTable(rows, false));
    return;
  }
  const rows = data || [];
  const counts = rows.reduce((m, r) => { m[r.role] = (m[r.role] || 0) + 1; return m; }, {});
  status.textContent = `${rows.length} account${rows.length === 1 ? "" : "s"}: ` +
    ["admin", "tester", "customer", "inactive"].map(k => `${counts[k] || 0} ${ROLE_LABELS[k].toLowerCase()}`).join(" · ") + ".";
  revealable(list, () => customersTable(rows, true));
}
// Account e-mail addresses are not on screen until asked for: this page shows
// no e-mail by default (screen sharing, shoulder surfing).
function revealable(list, render) {
  list.innerHTML = `<button class="admin-btn admin-btn-quiet" type="button" id="adminCustomersShow">Show accounts</button>`;
  document.getElementById("adminCustomersShow").addEventListener("click", () => { list.innerHTML = render(); });
}
function customersTable(rows, billing) {
  if (!rows.length) return "";
  const head = `<tr><th>Account</th><th>Access</th><th>Why</th>${billing ? "<th>Subscription</th><th>Period end</th><th>Problem</th>" : ""}</tr>`;
  const body = rows.map(r => {
    const problem = r.state === "payment_failed" || r.state === "payment_failed_grace" ? "Payment failed" + (r.payment_failed_at ? " " + dateOnly(r.payment_failed_at) : "")
      : r.cancel_at_period_end ? "Cancels at period end" : r.last_payment_status === "failed" ? "Last payment failed" : "";
    return `<tr data-role="${esc(r.role)}" data-state="${esc(r.state)}">
      <td>${esc(r.email || r.user_id || "")}</td>
      <td><b>${esc(ROLE_LABELS[r.role] || r.role)}</b>${r.access ? "" : " (no access)"}<br><span class="admin-sub">${esc(STATE_LABELS[r.state] || r.state || "")}</span></td>
      <td>${esc(r.reason || "")}</td>
      ${billing ? `<td>${esc(r.subscription_status || "None")}${r.stripe_subscription_id ? `<br><span class="admin-sub">${esc(r.stripe_subscription_id)}</span>` : ""}</td>
      <td>${esc(dateOnly(r.current_period_end))}</td><td>${esc(problem)}</td>` : ""}
    </tr>`;
  }).join("");
  return `<table class="admin-usage-table admin-customers-table"><thead>${head}</thead><tbody>${body}</tbody></table>`;
}

// ---- Operator diagnostics (moved here from the customer Dashboard, 2026-10-10) ----
// Dataset health is DERIVED at read time from public.source_health and must
// stay in step with scripts/source_health.py derive_health() and with the
// customer page's healthOf() in app.js (the customer page shows one plain
// status per source; this page shows the operator detail behind it).
const HEALTH_STALE_MULTIPLIER = 2;
const HEALTH_TEXT = { HEALTHY: "Healthy", INCOMPLETE: "Incomplete", FAILED: "Failed", STALE: "Stale", NOT_RUN: "Not run" };
function healthOf(rec, now) {
  const t = now || Date.now();
  if (!rec || !rec.last_attempt_at) return "NOT_RUN";
  if (rec.last_attempt_status === "FAILED") return "FAILED";
  if (rec.completeness === "INCOMPLETE") return "INCOMPLETE";
  if (rec.mode === "scheduled" && rec.cadence_hours) {
    if (!rec.last_success_at) return "FAILED";
    const age = (t - Date.parse(rec.last_success_at)) / 3600000;
    if (age > rec.cadence_hours * HEALTH_STALE_MULTIPLIER) return "STALE";
  }
  return "HEALTHY";
}
function relativeTime(iso) {
  if (!iso) return "never";
  const t = Date.parse(iso);
  if (isNaN(t)) return "unknown";
  const h = Math.round((Date.now() - t) / 3600000);
  if (h < 1) return "under an hour ago";
  if (h < 48) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}
// One row per dataset with the operator detail (cadence, last success, last
// attempt and its status, row count, completeness, incomplete units, error).
function healthRowHtml(rec) {
  const health = healthOf(rec);
  const units = rec.units_total !== null && rec.units_total !== undefined
    ? `${rec.units_complete}/${rec.units_total} units complete` : "completeness not gated";
  const bits = [
    rec.mode === "manual" ? "manual runs, no schedule" : (rec.cadence_hours ? `every ${rec.cadence_hours}h` : "scheduled"),
    `last success ${relativeTime(rec.last_success_at)}`,
    `last attempt ${relativeTime(rec.last_attempt_at)} (${String(rec.last_attempt_status || "?").toLowerCase()})`,
    rec.row_count !== null && rec.row_count !== undefined ? `${rec.row_count} rows` : "row count unknown",
    units
  ];
  const inc = (rec.incomplete_units || []).slice(0, 4);
  const detail = inc.length ? ` · incomplete: ${inc.join(", ")}${(rec.incomplete_units || []).length > 4 ? ", …" : ""}` : (rec.error && health === "FAILED" ? ` · ${rec.error}` : "");
  return `<tr class="health-row" data-source="${esc(rec.source)}" data-health="${esc(health)}" data-state="${esc(rec.state || "")}"><td>${esc(rec.state || "")}</td><td>${esc(rec.label || rec.source)}</td><td><span class="health-badge ${esc(health.toLowerCase())}">${esc(HEALTH_TEXT[health] || health)}</span></td><td>${esc(bits.join(" · "))}${esc(detail)}</td></tr>`;
}
// One row per (county, source) unit: last read / last complete read / rows at
// that read / consecutive failures, plus the three operator states the
// customer page only summarises (source unavailable, no complete read in 36h,
// back-off hold - scripts/unit_freshness.py).
function unitRowHtml(u) {
  const last = u.last_attempt_status ? String(u.last_attempt_status).toLowerCase() : "?";
  const ok = u.last_attempt_status === "COMPLETE" || u.last_attempt_status === "EMPTY";
  const bits = [
    `last read ${relativeTime(u.last_attempt_at)} (${last})`,
    u.last_success_at ? `last complete read ${relativeTime(u.last_success_at)}` : "no complete read recorded",
    u.last_success_row_count !== null && u.last_success_row_count !== undefined ? `${u.last_success_row_count} rows at that read` : "row count unknown"
  ];
  if (Number(u.consecutive_failures) > 0) bits.push(`${u.consecutive_failures} consecutive failed attempt${Number(u.consecutive_failures) === 1 ? "" : "s"}`);
  const unavailable = u.last_attempt_status === "SOURCE_UNAVAILABLE" || /^(TRANSPORT_|PROXY_|ACCESS_)/.test(String(u.last_error_category || ""));
  if (unavailable) bits.push("source unavailable at the last attempt - inventory kept, nothing closed");
  const sinceSuccess = u.last_success_at ? (Date.now() - Date.parse(u.last_success_at)) / 3600000 : null;
  if (sinceSuccess === null || isNaN(sinceSuccess) || sinceSuccess > 36) bits.push("no complete read in the last 36 hours");
  if (Number(u.consecutive_failures) >= 3) bits.push("back-off: attempted at most once per 48 hours until a read succeeds");
  return `<tr class="unit-row" data-state="${esc(u.state)}" data-county="${esc(u.county)}" data-source="${esc(u.source_id || "")}" data-fresh="${ok ? "current" : "stale"}" data-unavailable="${unavailable ? "1" : "0"}"><td>${esc(u.state)}</td><td>${esc(u.county)}</td><td class="admin-sub">${esc(u.source_id || "")}${u.ledgers ? ` · ${esc(u.ledgers)}` : ""}</td><td><span class="health-badge ${ok ? "healthy" : "stale"}">${ok ? "Current" : "Stale"}</span></td><td>${esc(bits.join(" · "))}</td></tr>`;
}
let HEALTH_ROWS = null;
async function refreshFreshness() {
  const status = document.getElementById("adminFreshnessStatus");
  if (!status) return;
  const { data, error } = await sb.from("source_health").select("*").order("source");
  HEALTH_ROWS = error ? null : (data || []);
  const sel = document.getElementById("adminFreshnessState");
  if (sel && sel.options.length === 1) {
    const states = new Set();
    (HEALTH_ROWS || []).forEach(r => { if (r.state && r.state !== "ALL") states.add(r.state); });
    (REGISTRY_UNITS || []).forEach(r => { if (r.state) states.add(r.state); });
    [...states].sort().forEach(st => sel.add(new Option(st, st)));
    sel.addEventListener("change", renderFreshness);
  }
  renderFreshness();
}
function renderFreshness() {
  const status = document.getElementById("adminFreshnessStatus");
  const list = document.getElementById("adminFreshnessList");
  const units = document.getElementById("adminUnitList");
  if (!status || !list || !units) return;
  const st = (document.getElementById("adminFreshnessState") || {}).value || "";
  const health = HEALTH_ROWS === null ? null : HEALTH_ROWS.filter(r => !st || r.state === st || r.state === "ALL");
  const reg = REGISTRY_UNITS === null ? null : REGISTRY_UNITS.filter(u => u.last_attempt_at && (!st || u.state === st))
    .sort((a, b) => String(a.state).localeCompare(String(b.state)) || String(a.county).localeCompare(String(b.county)) || String(a.source_id || "").localeCompare(String(b.source_id || "")));
  const parts = [];
  // Two different records: the dataset-health table (one row per dataset run)
  // and the county read status (one row per source unit). "Not recorded" in one
  // says nothing about the other, so each is labelled by its own name.
  if (health === null) parts.push("Dataset health (source_health table): not recorded on this deployment (migration 016 not live). This is not a failed read.");
  else parts.push(`Dataset health (source_health): ${health.length} dataset${health.length === 1 ? "" : "s"} with a recorded run.`);
  if (reg === null) parts.push("County read status (unit_freshness): not recorded on this deployment (migration 021 not live).");
  else parts.push(`County read status (unit_freshness): ${reg.length} source unit${reg.length === 1 ? "" : "s"} with a recorded read. Each unit's CURRENT or STALE label is its own last read, not the dataset health above.`);
  status.textContent = parts.join(" ");
  list.innerHTML = health && health.length ? `<table class="admin-usage-table admin-sources-table admin-health-table"><thead><tr><th>State</th><th>Dataset</th><th>Health</th><th>Operator detail</th></tr></thead><tbody>${health.map(healthRowHtml).join("")}</tbody></table>` : "";
  // Up to 50 units at once; the rest sit in a disclosure labelled with their count
  // (the list was 360 rows on one screen).
  const unitTable = rows => `<table class="admin-usage-table admin-sources-table admin-units-table"><thead><tr><th>State</th><th>County</th><th>Source</th><th>Read</th><th>Operator detail</th></tr></thead><tbody>${rows.map(unitRowHtml).join("")}</tbody></table>`;
  const UNIT_FIRST = 50;
  units.innerHTML = reg && reg.length
    ? unitTable(reg.slice(0, UNIT_FIRST)) + (reg.length > UNIT_FIRST ? `<details class="admin-more-units"><summary>Show the other ${reg.length - UNIT_FIRST} county source units</summary>${unitTable(reg.slice(UNIT_FIRST))}</details>` : "")
    : "";
}

// Needs attention (2026-10-29). One list of every place a person has to act,
// so the owner is never the one who finds a dead source first (the Hendry
// FL Lands Available record: its list file 404'd, the county's read had
// failed 33 times and the record was already withheld - but each fact sat in
// a different view). One row per unit (state, county, source); every reason
// comes from a recorded field:
//   * county_source_registry: last read status, failure streak, last complete
//     read and last_error_category (scripts/unit_freshness.py). A unit is
//     listed when its last read is FAILED / INCOMPLETE / SOURCE_UNAVAILABLE,
//     its last complete read is older than ATTENTION_STALE_DAYS, or it is a
//     production source with no read on record;
//   * source_link_checks (migration 036): a link BROKEN on 2+ separate daily
//     checks, tied to its unit through the registry row or the active
//     properties rows that carry it, else acquisition-evidence.json;
//   * properties: Available rows withheld as unconfirmed (last_seen_at NULL or
//     older than 7 days - app.js unconfirmedAvailable), counted per unit.
// Nothing here guesses a cause: a failure with no recorded category reads
// "reason not recorded". Counts and place names only - no parcel, address or
// owner is read or shown.
const ATTENTION_STALE_DAYS = 2;
const ATTENTION_UNCONFIRMED_DAYS = 7;   // app.js UNCONFIRMED_DAYS
const ATTENTION_LEDGER_NAMES = { AUCTIONS: "Auctions", AVAILABLE: "Available", LIENS_CERTIFICATES: "Liens & Certificates", auction: "Auctions", laft: "Available", certificate: "Liens & Certificates" };
// last_error_category -> [what happened, what is needed]. Keys cover
// scripts/laft_status.py ERROR_CATEGORIES plus the categories the Texas and
// expansion harvesters write (tests/python/test_needs_attention.py pins it).
const ATTENTION_READ_REASONS = {
  TRANSPORT_HTTP_403_BLOCKED: ["site blocks automated reads (HTTP 403 / Cloudflare challenge)", "a decision on how to read it: a recorded permission, a proxy route, or a manual capture"],
  TRANSPORT_HTTP_404: ["list file / page moved (HTTP 404)", "the current link to the county's list"],
  TRANSPORT_HTTP_4XX: ["site refused the request (HTTP 4xx)", "a look at the source page to see what it now requires"],
  TRANSPORT_HTTP_5XX: ["source site returned a server error (HTTP 5xx)", "nothing if it clears on the next run; a look at the site if it persists"],
  TRANSPORT_TIMEOUT: ["site did not answer in time", "nothing if it clears on the next run; a look at the site if it persists"],
  TRANSPORT_CONNECTION: ["site could not be reached (connection refused or address does not resolve)", "check the site still exists at this address"],
  TRANSPORT_REQUEST_FAILED: ["the request to the site failed", "check the latest job log for the failed request"],
  TRANSPORT_PAGE_FAILED: ["a page of the feed failed after its retries", "nothing if it clears on the next run; a look at the feed if it persists"],
  TRANSPORT: ["the site could not be read", "check the latest job log for the failed request"],
  PROXY_FAILURE: ["site blocks automated reads and the fallback proxy also failed", "a check of the proxy account"],
  PROXY_NOT_CONFIGURED: ["site blocks automated reads and no proxy key is set", "a proxy key, or another recorded way to read it"],
  ACCESS_DENIED: ["a login or disclaimer gate was not passed", "check whether the list now sits behind a login or a click-through"],
  PLACEHOLDER_TENANT: ["the platform shows a test placeholder, not the county's list", "the county's real list address"],
  PARSE_NO_TABLE: ["no list found on the page and no 'none available' statement", "a look at the page: the list may have moved or changed format"],
  PARSE_FORMAT_CHANGE: ["list format changed", "a parser update for the new format"],
  PARSE_COUNT_MISMATCH: ["rows read do not match the count the source shows", "a parser check"],
  PARSE_TRUNCATED: ["source says more rows exist than were read", "a parser check of the paging"],
  PARSE_UNREADABLE_DOCUMENT: ["the list file could not be read (unreadable document)", "a look at the file: it may be a scan or a different format"],
  UNCONFIRMED_EMPTY: ["list could not be confirmed (zero rows and no 'none available' statement)", "check whether the county really lists nothing today"],
  SOURCE_LINK_MISSING: ["the page no longer links to the list file", "the current link to the county's list"],
  PERMISSION_DENIED: ["no recorded permission to read this source, so nothing was requested", "a permission record in data/source_permissions.csv"],
  UNKNOWN: ["unexpected error", "check the latest job log"]
};
const ATTENTION_LINK_DETAIL = {
  HTTP_404: "HTTP 404", HTTP_410: "HTTP 410 - removed", SOFT_404: "page reads 'not found'", DNS: "site address no longer resolves"
};
// referenced_by (check_source_links.py) -> what the link is, most specific first.
const ATTENTION_LINK_ROLES = [
  ["registry.document_url", "list file link"], ["properties.document_url", "list file link"], ["properties.otc_provenance.document", "list file link"],
  ["properties.list_url", "list page link"], ["properties.otc_provenance.list", "list page link"], ["registry.canonical_url", "source page link"],
  ["registry.purchase_url", "purchase page link"], ["properties.purchase_url", "purchase page link"], ["properties.url_auction", "auction site link"],
  ["properties.otc_provenance.application", "application form link"], ["acquisition-evidence", "acquisition instructions link"],
  ["properties.otc_provenance.evidence", "acquisition instructions link"]
];
function attentionDate(iso) {
  const t = iso ? Date.parse(iso) : NaN;
  return isNaN(t) ? "" : new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}
function attentionLinkRole(refs) {
  const list = Array.isArray(refs) ? refs.map(String) : String(refs || "").replace(/^\{|\}$/g, "").split(",");
  const hit = ATTENTION_LINK_ROLES.find(([k]) => list.includes(k));
  return hit ? hit[1] : "source link";
}
function attentionLinkNeed(detail) {
  if (detail === "DNS") return "the site's current address (the domain no longer resolves)";
  return "the current link (the page or file moved)";
}
// The read problem of one registry unit, or null when it reads fine.
function attentionReadProblem(u, now) {
  const t = now || Date.now();
  const st = String(u.last_attempt_status || "");
  const success = u.last_success_at ? Date.parse(u.last_success_at) : NaN;
  const staleMs = ATTENTION_STALE_DAYS * 86400000;
  const lastGood = isNaN(success) ? "no complete read on record" : `last complete read ${attentionDate(u.last_success_at)}`;
  if (!u.last_attempt_at) {
    if (u.verification_status !== "PRODUCTION_VERIFIED") return null;   // a candidate is never harvested
    return { kind: "read", start: null, text: "No read recorded for this source in this county", need: "check that the job reading this source records its reads" };
  }
  const failing = st === "FAILED" || st === "INCOMPLETE" || st === "SOURCE_UNAVAILABLE";
  if (failing) {
    const cat = String(u.last_error_category || "");
    const known = ATTENTION_READ_REASONS[cat]
      || (cat.startsWith("TRANSPORT_") ? ATTENTION_READ_REASONS.TRANSPORT : null)
      || (cat.startsWith("PARSE_") ? ["the list could not be read as expected (" + cat + ")", "a parser check"] : null);
    let reason = known ? known[0] : (cat ? `reason code ${cat}` : "reason not recorded");
    let need = known ? known[1] : "check the latest job log";
    if (!cat && st === "SOURCE_UNAVAILABLE") { reason = "source could not be reached"; need = "a look at the site if it persists"; }
    const word = st === "INCOMPLETE" ? "List read incomplete" : "List read failing";
    const streak = Number(u.consecutive_failures) > 0 ? `${u.consecutive_failures} failed read${Number(u.consecutive_failures) === 1 ? "" : "s"} in a row` : "";
    return { kind: "read", start: isNaN(success) ? null : success, text: [`${word}: ${reason}`, streak, lastGood].filter(Boolean).join(" · "), need };
  }
  if (isNaN(success) || t - success > staleMs) {
    const days = isNaN(success) ? null : Math.floor((t - success) / 86400000);
    return { kind: "read", start: isNaN(success) ? null : success,
      text: days === null ? "No complete read on record" : `No complete read in ${days} days (${lastGood})`,
      need: "check the scheduled job is still reading this source" };
  }
  return null;
}
async function attentionRegistry() {
  const { data, error } = await sb.from("county_source_registry")
    .select("state,county,source_id,ledgers,inventory_type,verification_status,canonical_url,document_url,purchase_url,last_attempt_at,last_attempt_status,last_success_at,consecutive_failures,last_error_category");
  if (error) throw new Error("the county read status (" + (error.message || error.code) + ")");
  return data || [];
}
async function attentionBrokenLinks() {
  const out = [];
  let after = null;
  for (let i = 0; i < 50; i++) {
    let q = sb.from("source_link_checks").select("url,host,status,http_code,detail,first_failed_at,checked_at,consecutive_failures,referenced_by")
      .eq("status", "BROKEN").gte("consecutive_failures", 2).order("url").limit(1000);
    if (after !== null) q = q.gt("url", after);
    const { data, error } = await q;
    if (error) {
      if (/PGRST205|42P01/.test(String(error.code || ""))) return null;   // migration 036 not on this deployment
      throw new Error("the link checks (" + (error.message || error.code) + ")");
    }
    (data || []).forEach(r => { if (r && r.url && Number(r.consecutive_failures) >= 2) out.push(r); });
    if (!data || data.length < 1000) break;
    after = data[data.length - 1].url;
  }
  return out;
}
// The active rows that carry one of `urls` in a link column: which units a
// dead link belongs to. Units only - no row identity is kept.
async function attentionLinkOwners(urls) {
  const owners = new Map();   // url -> Map(unitKey -> unit)
  const add = (url, unit) => { if (!owners.has(url)) owners.set(url, new Map()); owners.get(url).set(unit.key, unit); };
  for (const col of ["document_url", "list_url", "purchase_url", "url_auction"]) {
    for (let i = 0; i < urls.length; i += 20) {
      const chunk = urls.slice(i, i + 20);
      const { data, error } = await sb.from("properties").select(`state,county,source,source_id,harvester_source,${col}`)
        .in(col, chunk).in("status", ["active", "available"]).limit(1000);
      if (error) throw new Error("the properties carrying a broken link (" + (error.message || error.code) + ")");
      (data || []).forEach(p => add(p[col], attentionUnit(p.state || "FL", p.county, p.source_id || p.harvester_source, p.source)));
    }
  }
  return owners;
}
async function attentionUnconfirmed() {
  const cutoff = new Date(Date.now() - ATTENTION_UNCONFIRMED_DAYS * 86400000).toISOString();
  const rows = [];
  let after = null;
  for (let i = 0; i < 200; i++) {
    let q = sb.from("properties").select("id,state,county,source,source_id,harvester_source,last_seen_at")
      .eq("source", "laft").in("status", ["active", "available"])
      .or(`last_seen_at.is.null,last_seen_at.lt.${cutoff}`).order("id").limit(1000);
    if (after !== null) q = q.gt("id", after);
    const { data, error } = await q;
    if (error) throw new Error("the unconfirmed Available records (" + (error.message || error.code) + ")");
    rows.push(...(data || []));
    if (!data || data.length < 1000) break;
    after = data[data.length - 1].id;
  }
  return rows;
}
async function attentionEvidence() {
  try {
    const resp = await fetch("acquisition-evidence.json", { cache: "no-store" });
    return resp.ok ? await resp.json() : null;
  } catch { return null; }
}
function attentionUnit(state, county, sourceId, ledger) {
  const st = String(state || ""), co = String(county || ""), src = String(sourceId || "");
  return { key: `${st}|${co}|${src}`, state: st, county: co, source_id: src, ledger: ledger || null, problems: [] };
}
function attentionLedgerLabel(u) {
  const name = ATTENTION_LEDGER_NAMES[u.ledger] || "";
  if (name === "Available" && u.state === "FL") return "Lands Available";
  return name;
}
// The whole panel from the four reads. `now` is injectable for determinism.
function attentionModel({ registry, links, owners, unconfirmed, evidence }, now) {
  const units = new Map();
  const unitFor = (state, county, src, ledger) => {
    const u = attentionUnit(state, county, src, ledger);
    if (!units.has(u.key)) units.set(u.key, u);
    const cur = units.get(u.key);
    if (!cur.ledger && ledger) cur.ledger = ledger;
    return cur;
  };
  const regLedger = r => r.ledgers ? String(r.ledgers).split("|")[0] : (r.inventory_type ? "AVAILABLE" : null);
  (registry || []).forEach(r => {
    const p = attentionReadProblem(r, now);
    if (p) unitFor(r.state, r.county, r.source_id || "", regLedger(r)).problems.push(p);
  });
  (links || []).forEach(l => {
    const detail = ATTENTION_LINK_DETAIL[l.detail] || (l.http_code ? `HTTP ${l.http_code}` : String(l.detail || "broken"));
    const since = attentionDate(l.first_failed_at);
    const problem = { kind: "link", start: l.first_failed_at ? Date.parse(l.first_failed_at) : null,
      text: `${attentionLinkRole(l.referenced_by)} is dead (${detail}${since ? " since " + since : ""}): ${l.url}`, need: attentionLinkNeed(l.detail), url: l.url };
    const homes = new Map();
    (registry || []).forEach(r => {
      if ([r.canonical_url, r.document_url, r.purchase_url].includes(l.url)) homes.set(`${r.state}|${r.county}|${r.source_id || ""}`, [r.state, r.county, r.source_id || "", regLedger(r)]);
    });
    const carried = owners && owners.get(l.url);
    if (carried) carried.forEach(u => { if (!homes.has(u.key)) homes.set(u.key, [u.state, u.county, u.source_id, u.ledger]); });
    if (!homes.size && evidence) {
      const hit = rec => JSON.stringify(rec).includes(JSON.stringify(l.url));
      (evidence.records || []).concat(evidence.status || []).forEach(rec => {
        if (rec && hit(rec)) homes.set(`${rec.state}|${rec.county}|${rec.source_id || ""}`, [rec.state, rec.county, rec.source_id || "", "AVAILABLE"]);
      });
    }
    if (!homes.size) homes.set(`||${l.host || ""}`, ["", "", l.host || "", null]);
    homes.forEach(([st, co, src, ledger]) => unitFor(st, co, src, ledger).problems.push(problem));
  });
  const byUnit = new Map();
  (unconfirmed || []).forEach(p => {
    const k = `${p.state || "FL"}|${p.county || ""}|${p.source_id || p.harvester_source || ""}`;
    const e = byUnit.get(k) || { state: p.state || "FL", county: p.county || "", src: p.source_id || p.harvester_source || "", n: 0, never: 0, newest: null };
    e.n++;
    if (!p.last_seen_at) e.never++;
    else if (!e.newest || p.last_seen_at > e.newest) e.newest = p.last_seen_at;
    byUnit.set(k, e);
  });
  byUnit.forEach(e => {
    const u = unitFor(e.state, e.county, e.src, "laft");
    const when = e.newest ? `not confirmed by the source since ${attentionDate(e.newest)}` : "never confirmed by the source";
    const mixed = e.newest && e.never ? ` (${e.never} never confirmed)` : "";
    u.problems.push({ kind: "unconfirmed", start: e.newest ? Date.parse(e.newest) + ATTENTION_UNCONFIRMED_DAYS * 86400000 : null,
      text: `${e.n} Available record${e.n === 1 ? "" : "s"} withheld from customers: ${when}${mixed}`,
      need: u.problems.some(p => p.kind === "read") ? "a successful read of this county's list (see above)" : "a read of this county's list that includes them, or confirmation they left the list" });
  });
  const list = [...units.values()].filter(u => u.problems.length);
  list.forEach(u => {
    const starts = u.problems.map(p => p.start).filter(x => typeof x === "number" && !isNaN(x));
    u.newest = starts.length ? Math.max(...starts) : null;
    u.problems.sort((a, b) => ["read", "link", "unconfirmed"].indexOf(a.kind) - ["read", "link", "unconfirmed"].indexOf(b.kind));
  });
  const newestFirst = (a, b) => (b.newest === null ? -Infinity : b.newest) - (a.newest === null ? -Infinity : a.newest)
    || a.county.localeCompare(b.county) || a.source_id.localeCompare(b.source_id);
  const states = new Map();
  list.forEach(u => { const k = u.state || ""; if (!states.has(k)) states.set(k, []); states.get(k).push(u); });
  const groups = [...states.entries()].map(([state, rows]) => {
    rows.sort(newestFirst);
    return { state, units: rows, newest: rows.reduce((m, u) => (u.newest !== null && (m === null || u.newest > m) ? u.newest : m), null) };
  });
  groups.sort((a, b) => (!a.state) - (!b.state) || (b.newest === null ? -Infinity : b.newest) - (a.newest === null ? -Infinity : a.newest) || a.state.localeCompare(b.state));
  return { total: list.length, groups };
}
function attentionRowHtml(u) {
  const where = u.county ? `${u.county}, ${u.state}` : (u.state ? u.state : "Not tied to a county");
  const head = [where, attentionLedgerLabel(u), u.source_id].filter(Boolean).join(" · ");
  const kinds = [...new Set(u.problems.map(p => p.kind))].join(",");
  return `<li class="attn-row" data-state="${esc(u.state)}" data-county="${esc(u.county)}" data-source="${esc(u.source_id)}" data-kinds="${esc(kinds)}">`
    + `<p class="attn-where">${esc(head)}</p><ul class="attn-problems">${u.problems.map(p =>
      `<li class="attn-problem" data-kind="${esc(p.kind)}">${esc(p.text)} <span class="attn-need">· what's needed: ${esc(p.need)}</span></li>`).join("")}</ul></li>`;
}
function renderAttention(model, gaps) {
  const head = document.getElementById("adminAttentionLabel");
  const status = document.getElementById("adminAttentionStatus");
  const list = document.getElementById("adminAttentionList");
  if (!head || !status || !list) return;
  head.textContent = `Needs attention (${model.total})`;
  const gapText = gaps.length ? `Could not check ${gaps.join("; ")} - this list may be missing items.` : "";
  status.textContent = model.total ? gapText : (gapText || "Nothing needs attention.");
  list.innerHTML = model.groups.map(g => `<section class="attn-state" data-state="${esc(g.state)}"><p class="attn-state-head">${esc(g.state || "Links not tied to a county")} (${g.units.length})</p><ul class="attn-list">${g.units.map(attentionRowHtml).join("")}</ul></section>`).join("");
  document.getElementById("attention").dataset.count = String(model.total);
}
async function refreshAttention() {
  const status = document.getElementById("adminAttentionStatus");
  if (!status) return;
  const gaps = [];
  const safe = async (fn, fallback) => { try { return await fn(); } catch (e) { gaps.push(e && e.message ? e.message : String(e)); return fallback; } };
  const [registry, links, unconfirmed, evidence] = await Promise.all([
    safe(attentionRegistry, []), safe(attentionBrokenLinks, []), safe(attentionUnconfirmed, []), attentionEvidence()
  ]);
  if (links === null) gaps.push("the link checks (migration 036 is not on this deployment)");
  const linkList = links || [];
  const owners = linkList.length ? await safe(() => attentionLinkOwners([...new Set(linkList.map(l => l.url))]), new Map()) : new Map();
  const model = attentionModel({ registry, links: linkList, owners, unconfirmed, evidence });
  renderAttention(model, gaps);
}

// Collected inventory by source: what is collected in a state against what a
// customer sees. The Detroit customer subset rule is the same deterministic
// rule the customer page applies (app.js detroitSubsetStatus /
// harvesters/otc/detroit_subset.py; tests pin the constants equal).
const DETROIT_SOURCE_IDS = ["mi_detroit_landbank_lots", "mi_detroit_landbank_programs"];
const DETROIT_STRUCTURE_SOURCE_ID = "mi_detroit_landbank_lots";
const DETROIT_STRUCTURE_STATUSES = ["Marketed Structure For Sale"];
const DETROIT_SUBSET_PERCENT = 50;
function fnv1a32(text) {
  let h = 0x811c9dc5;
  for (const b of new TextEncoder().encode(String(text))) { h ^= b; h = Math.imul(h, 0x01000193) >>> 0; }
  return h >>> 0;
}
function detroitSubsetStatus(p) {
  if (!p || !DETROIT_SOURCE_IDS.includes(p.source_id)) return null;
  if (p.source_id !== DETROIT_STRUCTURE_SOURCE_ID || !DETROIT_STRUCTURE_STATUSES.includes(String(p.inventory_status_raw || "").trim())) return "not_structure";
  const parcel = String(p.parcel || p.case_no || "").trim();
  return fnv1a32(`${p.source_id}|${parcel}`) % 100 < DETROIT_SUBSET_PERCENT ? "in_subset" : "not_selected";
}
const REVIEW_LABELS = { APPROVED: "Approved", APPROVED_GRANDFATHERED: "Approved (grandfathered)", UNREVIEWED: "Unreviewed", RESTRICTED: "Review required", BLOCKED: "Blocked" };
const LEDGER_NAMES = { auction: "Auctions", laft: "Available", certificate: "Liens & Certificates" };
function customerPublishable(status) { return !status || status === "APPROVED" || status === "APPROVED_GRANDFATHERED"; }
function isGoneRow(p) { return p.status && p.status !== "active" && p.status !== "available"; }
const INVENTORY_PAGE = 1000;
const INVENTORY_COLUMNS = "id,source,source_id,harvester_source,county,status,publication_status,last_seen_at,inventory_status_raw,parcel,case_no";
function initInventory() {
  const sel = document.getElementById("adminInventoryState");
  const btn = document.getElementById("adminInventoryLoad");
  const mode = document.getElementById("adminInventoryMode");
  if (!sel || !btn) return;
  const states = new Set((SOURCES && SOURCES.sources ? SOURCES.sources.map(s => s.state) : []).filter(Boolean));
  (REGISTRY_UNITS || []).forEach(r => { if (r.state) states.add(r.state); });
  if (!states.size) ["FL", "TX"].forEach(st => states.add(st));
  if (!sel.options.length) [...states].sort().forEach(st => sel.add(new Option(st, st)));
  if (mode) mode.textContent = String(cfg.publicationMode || "enforced") === "preview"
    ? "Preview mode (config.js publicationMode = preview): customers see rows from every source except BLOCKED sources, labelled by review status; rows the publication and acquisition-path gates withhold stay hidden from customers. Administrators see every collected row."
    : "Customer mode: customers see only approved sources, plus rows that pass the publication and acquisition-path gates. Unreviewed and blocked sources are withheld. Administrators see every collected row, labelled.";
  btn.addEventListener("click", () => loadInventory(sel.value));
}
async function loadInventory(st) {
  const status = document.getElementById("adminInventoryStatus");
  const list = document.getElementById("adminInventoryList");
  const btn = document.getElementById("adminInventoryLoad");
  if (!status || !list || !st) return;
  btn.disabled = true;
  list.innerHTML = "";
  const rows = [];
  try {
    for (let off = 0; ; off += INVENTORY_PAGE) {
      status.textContent = `Loading ${st}: ${rows.length.toLocaleString("en-US")} rows read so far`;
      const { data, error } = await sb.from("properties").select(INVENTORY_COLUMNS).eq("state", st).order("id").range(off, off + INVENTORY_PAGE - 1);
      if (error) { status.textContent = `Could not read ${st}: ${error.message}`; btn.disabled = false; return; }
      const page = data || [];
      rows.push(...page);
      if (page.length < INVENTORY_PAGE) break;
    }
  } catch (e) { status.textContent = `Could not read ${st}: ${e && e.message ? e.message : e}`; btn.disabled = false; return; }
  btn.disabled = false;
  const by = new Map();
  rows.forEach(p => {
    const key = p.source_id || p.harvester_source || "(no source id)";
    const e = by.get(key) || { source: key, ledger: p.source, status: p.publication_status || null, rows: 0, active: 0, customer: 0, counties: new Set(), lastSeen: null,
      detroit: DETROIT_SOURCE_IDS.includes(key), structure: 0, subset: 0 };
    e.rows++;
    if (!isGoneRow(p)) e.active++;
    const det = detroitSubsetStatus(p);
    if (customerPublishable(p.publication_status) && (det === null || det === "in_subset")) e.customer++;
    if (det && det !== "not_structure") e.structure++;
    if (det === "in_subset") e.subset++;
    e.counties.add(p.county || "Unknown");
    if (p.last_seen_at && (!e.lastSeen || p.last_seen_at > e.lastSeen)) e.lastSeen = p.last_seen_at;
    by.set(key, e);
  });
  const summary = [...by.values()].sort((x, y) => (customerPublishable(x.status) - customerPublishable(y.status)) || y.rows - x.rows);
  const pending = summary.filter(e => !customerPublishable(e.status));
  status.textContent = `${st}: ${rows.length.toLocaleString("en-US")} collected row${rows.length === 1 ? "" : "s"} across ${summary.length} source${summary.length === 1 ? "" : "s"}; ${pending.length} source${pending.length === 1 ? "" : "s"} awaiting customer-publication review.`;
  list.innerHTML = summary.length ? `<table class="admin-usage-table admin-sources-table admin-inventory-table"><thead><tr><th>Source</th><th>Ledger</th><th>Source review</th><th>Collected</th><th>Active</th><th>Counties</th><th>Customer-visible</th><th>Detroit subset</th><th>Last read</th></tr></thead><tbody>${summary.map(e =>
    `<tr data-source-id="${esc(e.source)}"><td>${esc(e.source)}</td><td>${esc(LEDGER_NAMES[e.ledger] || e.ledger)}</td><td>${esc(e.status ? (REVIEW_LABELS[e.status] || e.status) : "Not classified")}</td><td>${e.rows}</td><td>${e.active}</td><td>${e.counties.size}</td><td>${e.customer}</td><td>${e.detroit ? `${e.subset} of ${e.structure} with a verified structure` : ""}</td><td>${e.lastSeen ? esc(dateOnly(e.lastSeen)) : "not recorded"}</td></tr>`).join("")}</tbody></table>` : "";
}

document.getElementById("adminSignOut").addEventListener("click", async () => {
  if (sb) await sb.auth.signOut();
  leave();
});

if (sb) {
  sb.auth.onAuthStateChange(event => {
    if (event === "SIGNED_OUT") leave();
  });
}

gate().catch(() => leave());
