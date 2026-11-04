// supabase/functions/billing-checkout/index.ts
//
// Paid beta (2026-10-05): starts a Stripe Checkout session for the ONE
// monthly plan and returns its URL. Grants nothing - the subscription only
// counts once stripe-webhook has recorded it from a verified Stripe event.
// The account comes from the caller's JWT (deploy WITH JWT verification);
// the price comes from STRIPE_PRICE_ID, never from the browser.
//
// Secrets: STRIPE_SECRET_KEY, STRIPE_PRICE_ID, optional APP_URL.
import { checkoutSessionParams } from "../_shared/billing_core.js";
import { ALLOWED_ORIGIN, appUrl, caller, cors, reply, serviceClient, stripe } from "../_shared/billing_http.ts";

Deno.serve(async (req) => {
  const origin = req.headers.get("origin");
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors(origin) });
  if (req.method !== "POST") return reply(405, { error: "method_not_allowed" }, origin);
  if (!origin || !ALLOWED_ORIGIN.test(origin)) return reply(403, { error: "origin_not_allowed" }, origin);
  const priceId = (Deno.env.get("STRIPE_PRICE_ID") ?? "").trim();
  if (!Deno.env.get("STRIPE_SECRET_KEY") || !priceId) return reply(503, { error: "billing_not_configured", message: "Subscriptions are not open yet." }, origin);
  const user = await caller(req);
  if (!user) return reply(401, { error: "not_signed_in" }, origin);

  const db = serviceClient();
  try {
    const { data: link } = await db.from("billing_customers").select("stripe_customer_id").eq("user_id", user.id).maybeSingle();
    let customerId = link ? link.stripe_customer_id : null;
    if (!customerId) {
      const p = new URLSearchParams();
      if (user.email) p.set("email", user.email);
      p.set("metadata[user_id]", user.id);
      const customer = await stripe("customers", p);
      customerId = customer.id;
      const { error } = await db.from("billing_customers").insert({ user_id: user.id, stripe_customer_id: customerId });
      if (error) throw error;
    }
    const session = await stripe("checkout/sessions", checkoutSessionParams({ priceId, customerId, userId: user.id, appUrl: appUrl(origin) }));
    return reply(200, { url: session.url }, origin);
  } catch (e) {
    console.error("checkout failed:", String((e as Error).message || e));
    return reply(502, { error: "checkout_failed", message: "Checkout could not be started. Please try again or contact support." }, origin);
  }
});
