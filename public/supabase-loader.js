// Loads supabase-js for app.js and admin.js without a single point of failure
// (2026-10-03: the production app showed a black page while making no
// request at all - the static esm.sh import is the first thing a page needs,
// and if it fails or hangs the module never runs, so the sign-in / pending /
// app screens all stay hidden).
//
// 1. The esm.sh specifier, as before (the test importmap maps this exact
//    string to tests/vendor/supabase-stub.js, so the suite is unchanged),
//    bounded by a timeout so a hung CDN cannot hang the page.
// 2. On failure, the same library served from this origin
//    (supabase-js.umd.js: @supabase/supabase-js 2.117.2's own UMD build,
//    unmodified; CSP script-src 'self').
// Every failure is recorded on window.__tdwBootErrors for boot.js to show.
const REMOTE = "https://esm.sh/@supabase/supabase-js@2";
const LOCAL = "supabase-js.umd.js";
const REMOTE_TIMEOUT_MS = 8000;

function note(msg) {
  (window.__tdwBootErrors = window.__tdwBootErrors || []).push(String(msg));
}

function timeout(ms) {
  return new Promise((_, reject) => setTimeout(() => reject(new Error(`timed out after ${ms / 1000}s`)), ms));
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = resolve;
    s.onerror = () => reject(new Error(`could not load ${src}`));
    document.head.appendChild(s);
  });
}

export async function loadCreateClient() {
  try {
    const m = await Promise.race([import(REMOTE), timeout(REMOTE_TIMEOUT_MS)]);
    if (m && typeof m.createClient === "function") return m.createClient;
    throw new Error("module has no createClient");
  } catch (e) {
    note(`Supabase library from esm.sh failed (${e && e.message ? e.message : e}); using the copy on this site.`);
  }
  try {
    if (!(window.supabase && window.supabase.createClient)) await loadScript(LOCAL);
    if (window.supabase && typeof window.supabase.createClient === "function") {
      window.__tdwSupabaseSource = "local";
      return window.supabase.createClient;
    }
    throw new Error("supabase global missing");
  } catch (e) {
    note(`Supabase library from this site failed too (${e && e.message ? e.message : e}).`);
    throw e;
  }
}
