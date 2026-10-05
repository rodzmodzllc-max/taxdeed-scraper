// supabase/functions/billing-portal/index.ts
//
// Paid beta (2026-10-05): opens Stripe's customer billing portal (update
// card, view invoices, cancel) for the signed-in account's own Stripe
// customer and returns its URL. The portal is configured in the Stripe
// dashboard. The account comes from the caller's JWT (deploy WITH JWT
// verification); a caller with no Stripe customer gets 404.
//
// Secrets: STRIPE_SECRET_KEY, optional APP_URL.
import { portalSessionParams } from "../_shared/billing_core.js";
import { ALLOWED_ORIGIN, appUrl, caller, cors, reply, serviceClient, stripe } from "../_shared/billing_http.ts";

Deno.serve(async (req) => {
  const origin = req.headers.get("origin");
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors(origin) });
  if (req.method !== "POST") return reply(405, { error: "method_not_allowed" }, origin);
  if (!origin || !ALLOWED_ORIGIN.test(origin)) return reply(403, { error: "origin_not_allowed" }, origin);
  if (!Deno.env.get("STRIPE_SECRET_KEY")) return reply(503, { error: "billing_not_configured" }, origin);
  const user = await caller(req);
  if (!user) return reply(401, { error: "not_signed_in" }, origin);
  const { data: link } = await serviceClient().from("billing_customers").select("stripe_customer_id").eq("user_id", user.id).maybeSingle();
  if (!link) return reply(404, { error: "no_billing_account", message: "There is no billing account for this sign-in yet." }, origin);
  try {
    const session = await stripe("billing_portal/sessions", portalSessionParams({ customerId: link.stripe_customer_id, appUrl: appUrl(origin) }));
    return reply(200, { url: session.url }, origin);
  } catch (e) {
    console.error("portal failed:", String((e as Error).message || e));
    return reply(502, { error: "portal_failed", message: "The billing portal could not be opened. Please try again or contact support." }, origin);
  }
});
