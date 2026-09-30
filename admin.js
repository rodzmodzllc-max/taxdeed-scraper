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
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

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
