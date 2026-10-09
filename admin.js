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
  await refreshPending();
  await refreshCustomers();
  await refreshUsage();
  await refreshSources();
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
    .select("state,county,source_id,last_attempt_at,last_attempt_status,last_success_at,consecutive_failures,last_error_category");
  FRESHNESS = new Map((error ? [] : data || []).map(r => [`${r.state}:${r.county}:${r.source_id || "unharvested_list"}`, r]));
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
function dateOnly(v) { const t = v ? Date.parse(v) : NaN; return Number.isNaN(t) ? "" : new Date(t).toISOString().slice(0, 10); }
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
