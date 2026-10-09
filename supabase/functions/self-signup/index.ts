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
// Edge Function by Supabase; nothing to set. The service key never leaves
// this function.

import { createClient } from "npm:@supabase/supabase-js@2";
import { signupPasswordProblem } from "../_shared/signup_password.js";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

// Origins: the Pages project (production + branch previews), the custom domain
// taxacq.com and its www host (exact hosts only, https only), local dev.
const ALLOWED_ORIGIN = /^(https:\/\/([a-z0-9-]+\.)?rodz-taxdeeds\.pages\.dev|https:\/\/(www\.)?taxacq\.com|http:\/\/localhost(:\d+)?|http:\/\/127\.0\.0\.1(:\d+)?)$/;
const EMAIL_RE = /^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,63}$/;
const FIELDS = ["first_name", "last_name", "company", "address", "phone"] as const;
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

  if (typeof body.website === "string" && body.website.trim()) return reply(400, { error: "rejected" }, origin);   // honeypot

  const email = String(body.email ?? "").trim().toLowerCase();
  // A missing password stays missing (never the string "undefined").
  const password = typeof body.password !== "string" ? "" : body.password;
  if (!EMAIL_RE.test(email) || email.length > 254) {
    return reply(400, { error: "invalid_email", message: "That email address doesn't look valid. Please check it and try again." }, origin);
  }
  // Missing / empty / whitespace-only / outside 8..72 (_shared/signup_password.js).
  const pwProblem = signupPasswordProblem(password);
  if (pwProblem) return reply(400, pwProblem, origin);
  const meta: Record<string, string> = {};
  for (const f of FIELDS) {
    const v = String(body[f] ?? "").trim();
    if (!v || v.length > 200) return reply(400, { error: "missing_fields", message: "Please fill in all fields. No company? Enter \"Independent\"." }, origin);
    meta[f] = v;
  }

  const admin = createClient(SUPABASE_URL, SERVICE_KEY, { auth: { persistSession: false, autoRefreshToken: false } });
  const { data, error } = await admin.auth.admin.createUser({ email, password, email_confirm: true, user_metadata: meta });
  if (error) {
    const msg = String(error.message || "");
    if (/already.*registered|already been registered|already exists/i.test(msg) || (error as { code?: string }).code === "email_exists") {
      return reply(409, { error: "already_registered", message: "An account with this email already exists. Choose “Already have an account? Sign in”, or “Forgot password?” to set a new password." }, origin);
    }
    if (/password/i.test(msg)) return reply(400, { error: "weak_password", message: msg }, origin);
    console.error("self-signup createUser failed:", (error as { status?: number }).status, (error as { code?: string }).code);
    return reply(500, { error: "create_failed", message: "Could not create the account. Please try again." }, origin);
  }
  return reply(200, { ok: true, user_id: data.user?.id ?? null }, origin);
});
