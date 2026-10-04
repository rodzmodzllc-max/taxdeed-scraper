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
  await refreshPending();
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

async function refreshPending() {
  const status = document.getElementById("adminPendingStatus");
  const list = document.getElementById("adminPendingList");
  const { data, error } = await sb.from("profiles").select("id,email,requested_at").eq("approved", false).order("requested_at");
  if (error) { status.textContent = "Could not load pending accounts: " + error.message; list.innerHTML = ""; return; }
  const rows = data || [];
  status.textContent = rows.length ? rows.length + (rows.length === 1 ? " account is" : " accounts are") + " waiting for approval." : "No accounts are waiting for approval.";
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
    await refreshPending();
  }));
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
