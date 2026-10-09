// supabase/functions/self-signup/index.ts
//
// Server-side sign-up (2026-10-04). Supabase's built-in e-mail sender allows
// only a few auth e-mails per hour for the whole project, so the browser's
// auth.signUp() - which must e-mail a confirmation link - started refusing
// new clients with "429 email rate limit exceeded" and no account was
// created. The owner chose this path: the account is created with the admin
// API, already confirmed, and NO e-mail is sent, so there is no hourly cap.
//
// What it does NOT change: access. The on_auth_user_created trigger
// (handle_new_user) inserts the profiles row with approved = false and
// is_admin = false, exactly as for a browser sign-up, and row-level security
// shows no ledger data until an admin approves the account. Nothing the
// caller sends can set approved / is_admin: only the five profile fields
// below are stored, in user_metadata, as the browser sign-up already did.
//
// Trade-off (accepted by the owner): the address is not proven to belong to
// the person. Admin approval is the gate.
//
// verify_jwt is OFF: the caller is, by definition, not signed in yet. The
// function protects itself instead - an origin allowlist (CORS), strict
// input validation, a body size cap, a honeypot field and a best-effort
// per-IP limit.
//
// Secrets: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are provided to every
// Edge Function by Supabase; RESEND_API_KEY is the project secret
// notify-approval already uses (the new-sign-up alert is sent from here right
// after the account is created). None of them leaves this function.
//
// New-sign-up alert (2026-10-09): migration 030 queues one admin_new_signup
// row per created account (profiles INSERT trigger), so a failed sign-up
// queues nothing and a retried one cannot queue twice. The recipient is fixed
// in _shared/approval_notify_core.js; nothing in this request can change it.

import { createClient } from "npm:@supabase/supabase-js@2";
import { handleSignup } from "../_shared/signup_request.js";
import { processDue, sendViaResend } from "../_shared/approval_notify_core.js";
import { accountNotifyDb } from "../_shared/account_notify_db.ts";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const RESEND_API_KEY = Deno.env.get("RESEND_API_KEY") ?? "";

// Origins: the Pages project (production + branch previews), the custom domain
// taxacq.com and its www host (exact hosts only, https only), local dev.
const ALLOWED_ORIGIN = /^(https:\/\/([a-z0-9-]+\.)?rodz-taxdeeds\.pages\.dev|https:\/\/(www\.)?taxacq\.com|http:\/\/localhost(:\d+)?|http:\/\/127\.0\.0\.1(:\d+)?)$/;
const PER_IP_PER_HOUR = 8;
const hits = new Map<string, number[]>();

function cors(origin: string | null): Record<string, string> {
  const h: Record<string, string> = {
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
    "Vary": "Origin",
  };
  if (origin && ALLOWED_ORIGIN.test(origin)) h["Access-Control-Allow-Origin"] = origin;
  return h;
}
function reply(status: number, body: Record<string, unknown>, origin: string | null) {
  return new Response(JSON.stringify(body), { status, headers: { ...cors(origin), "Content-Type": "application/json" } });
}
function limited(ip: string): boolean {
  const now = Date.now();
  const recent = (hits.get(ip) || []).filter((t) => now - t < 3600_000);
  recent.push(now);
  hits.set(ip, recent);
  return recent.length > PER_IP_PER_HOUR;
}

Deno.serve(async (req) => {
  const origin = req.headers.get("origin");
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors(origin) });
  if (req.method !== "POST") return reply(405, { error: "method_not_allowed" }, origin);
  if (!origin || !ALLOWED_ORIGIN.test(origin)) return reply(403, { error: "origin_not_allowed" }, origin);
  if (!SUPABASE_URL || !SERVICE_KEY) return reply(503, { error: "not_configured" }, origin);

  const ip = (req.headers.get("x-forwarded-for") || "").split(",")[0].trim() || "unknown";
  if (limited(ip)) return reply(429, { error: "too_many_attempts", message: "Too many sign-up attempts from this connection. Please wait and try again." }, origin);

  const raw = await req.text();
  if (raw.length > 4000) return reply(413, { error: "too_large" }, origin);
  let body: Record<string, unknown>;
  try { body = JSON.parse(raw); } catch { return reply(400, { error: "bad_json" }, origin); }

  const admin = createClient(SUPABASE_URL, SERVICE_KEY, { auth: { persistSession: false, autoRefreshToken: false } });
  // Validation (password rule included) and account creation:
  // _shared/signup_request.js. createUser is only reached by a valid request.
  const result = await handleSignup(body, (attrs) => admin.auth.admin.createUser(attrs));
  if (result.failure) console.error("self-signup createUser failed:", result.failure.status, result.failure.code);
  if (result.created) {
    // The account now exists, and migration 030's trigger queued its operator
    // alert in the same transaction. Send due account e-mails without
    // delaying the response; a failure leaves the row queued for the next
    // sweep and never touches the new account. Counts only in the log.
    const work = processDue({ db: accountNotifyDb(admin), send: (m) => sendViaResend(fetch, RESEND_API_KEY, m), limit: 5 })
      .then((c) => console.log(`self-signup notifications: ${JSON.stringify(c)}`))
      .catch((e) => console.error(`self-signup notifications: ${e instanceof Error ? e.message : "error"}`));
    try { (globalThis as { EdgeRuntime?: { waitUntil(p: Promise<unknown>): void } }).EdgeRuntime?.waitUntil(work); } catch { /* best effort */ }
  }
  return reply(result.status, result.body, origin);
});
