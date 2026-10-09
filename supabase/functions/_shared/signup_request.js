// supabase/functions/_shared/signup_request.js
//
// The self-signup request, from a parsed JSON body to a created account -
// pure JS with the account creator injected, so node --test can prove what
// reaches Supabase Auth (tests/billing/signup_password.test.mjs). The Deno
// handler (self-signup/index.ts) keeps transport concerns only: origin
// allowlist, rate limit, body size, JSON parsing.
//
// Password rule: _shared/signup_password.js (missing / empty / whitespace-only
// / outside 8..72 refused - the sign-up form applies the same rule). The
// password that passes is handed to createUser EXACTLY as received: never
// trimmed or normalised, so the stored password is the one the person typed.
import { signupPasswordProblem } from "./signup_password.js";

const EMAIL_RE = /^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,63}$/;
export const PROFILE_FIELDS = Object.freeze(["first_name", "last_name", "company", "address", "phone"]);

// -> { ok: true, email, password, meta } | { ok: false, status, body }
export function validateSignupBody(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return { ok: false, status: 400, body: { error: "bad_json" } };
  if (typeof body.website === "string" && body.website.trim()) return { ok: false, status: 400, body: { error: "rejected" } };   // honeypot
  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  if (!EMAIL_RE.test(email) || email.length > 254) {
    return { ok: false, status: 400, body: { error: "invalid_email", message: "That email address doesn't look valid. Please check it and try again." } };
  }
  // A missing or non-string password stays missing - never String(undefined).
  const password = typeof body.password !== "string" ? "" : body.password;
  const problem = signupPasswordProblem(password);
  if (problem) return { ok: false, status: 400, body: problem };
  const meta = {};
  for (const f of PROFILE_FIELDS) {
    const v = typeof body[f] === "string" ? body[f].trim() : "";
    if (!v || v.length > 200) return { ok: false, status: 400, body: { error: "missing_fields", message: "Please fill in all fields. No company? Enter \"Independent\"." } };
    meta[f] = v;
  }
  return { ok: true, email, password, meta };
}

// createUser(attrs) -> { data, error } (supabase-js admin.auth.admin.createUser).
// -> { status, body, created }   created = true only when an account exists now.
export async function handleSignup(body, createUser) {
  const v = validateSignupBody(body);
  if (!v.ok) return { status: v.status, body: v.body, created: false };
  const { data, error } = await createUser({ email: v.email, password: v.password, email_confirm: true, user_metadata: v.meta });
  if (error) {
    const msg = String(error.message || "");
    if (/already.*registered|already been registered|already exists/i.test(msg) || error.code === "email_exists") {
      return { status: 409, created: false, body: { error: "already_registered", message: "An account with this email already exists. Choose “Already have an account? Sign in”, or “Forgot password?” to set a new password." } };
    }
    // Supabase Auth's own password policy: its wording is safe to show.
    if (/password/i.test(msg)) return { status: 400, created: false, body: { error: "weak_password", message: msg } };
    return { status: 500, created: false, failure: { status: error.status ?? null, code: error.code ?? null },
             body: { error: "create_failed", message: "Could not create the account. Please try again." } };
  }
  return { status: 200, created: true, body: { ok: true, user_id: data?.user?.id ?? null } };
}
