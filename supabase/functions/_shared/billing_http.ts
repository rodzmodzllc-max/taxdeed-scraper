// supabase/functions/_shared/billing_http.ts
// Shared plumbing for billing-checkout and billing-portal: CORS / origin
// allowlist (same rule as self-signup), the signed-in caller (verified by
// Supabase from the request's JWT - deploy WITH JWT verification), and a
// form-encoded call to Stripe's REST API with the secret key.
import { createClient } from "npm:@supabase/supabase-js@2";

export const ALLOWED_ORIGIN = /^(https:\/\/([a-z0-9-]+\.)?rodz-taxdeeds\.pages\.dev|http:\/\/localhost(:\d+)?|http:\/\/127\.0\.0\.1(:\d+)?)$/;

export function cors(origin: string | null): Record<string, string> {
  const h: Record<string, string> = {
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
    "Vary": "Origin",
  };
  if (origin && ALLOWED_ORIGIN.test(origin)) h["Access-Control-Allow-Origin"] = origin;
  return h;
}

export function reply(status: number, body: Record<string, unknown>, origin: string | null) {
  return new Response(JSON.stringify(body), { status, headers: { ...cors(origin), "Content-Type": "application/json" } });
}

export function serviceClient() {
  return createClient(Deno.env.get("SUPABASE_URL") ?? "", Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
    { auth: { persistSession: false, autoRefreshToken: false } });
}

// The caller, from the Authorization header. Never from the request body.
export async function caller(req: Request) {
  const auth = req.headers.get("authorization") ?? "";
  const jwt = auth.replace(/^Bearer\s+/i, "");
  if (!jwt) return null;
  const { data, error } = await serviceClient().auth.getUser(jwt);
  return error || !data.user ? null : data.user;
}

export async function stripe(path: string, params: URLSearchParams) {
  const key = Deno.env.get("STRIPE_SECRET_KEY") ?? "";
  const r = await fetch(`https://api.stripe.com/v1/${path}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/x-www-form-urlencoded" },
    body: params.toString(),
  });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(`stripe ${path} ${r.status}: ${(body && body.error && body.error.type) || "error"}`);
  return body;
}

// The page the customer returns to: APP_URL when set, else the request's own
// allowlisted origin + "/index.html".
export function appUrl(origin: string | null) {
  const configured = (Deno.env.get("APP_URL") ?? "").trim();
  if (configured) return configured;
  return origin && ALLOWED_ORIGIN.test(origin) ? `${origin}/index.html` : "";
}
