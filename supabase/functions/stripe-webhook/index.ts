// supabase/functions/stripe-webhook/index.ts
//
// Paid beta (2026-10-05). Receives Stripe's subscription / invoice events and
// keeps public.subscriptions in step with Stripe. The ONLY writer of billing
// state: access for a paying customer comes from here, never from a browser
// redirect. All decisions live in ../_shared/billing_core.js (node-tested):
//   - the Stripe-Signature header is verified against STRIPE_WEBHOOK_SECRET
//     (HMAC-SHA256, 5-minute tolerance) before anything is read;
//   - each event id is recorded once in public.billing_events; an event
//     already processed is acknowledged and not applied again;
//   - an older event never overwrites a newer subscription state;
//   - only STRIPE_PRICE_ID (the one monthly plan) grants entitlement.
//
// Deploy with JWT verification OFF (Stripe does not send a Supabase JWT):
//   supabase functions deploy stripe-webhook --no-verify-jwt
// Secrets (set by the owner, never in the repository):
//   STRIPE_WEBHOOK_SECRET   whsec_... from the Stripe webhook endpoint
//   STRIPE_PRICE_ID         price_... of the monthly plan
// SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are provided by Supabase.

import { createClient } from "npm:@supabase/supabase-js@2";
import { processWebhook, plansFromEnv } from "../_shared/billing_core.js";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const WEBHOOK_SECRET = Deno.env.get("STRIPE_WEBHOOK_SECRET") ?? "";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function store(db: ReturnType<typeof createClient>) {
  return {
    async claimEvent(id: string, type: string, livemode: boolean) {
      const ins = await db.from("billing_events").insert({ stripe_event_id: id, type, livemode }).select("stripe_event_id");
      if (!ins.error) return "new";
      if (ins.error.code !== "23505") throw ins.error;
      const { data, error } = await db.from("billing_events").select("outcome").eq("stripe_event_id", id).maybeSingle();
      if (error) throw error;
      if (data && (data.outcome === "processed" || data.outcome === "ignored")) return "duplicate";
      await db.from("billing_events").update({ outcome: "received", error: null }).eq("stripe_event_id", id);
      return "retry";
    },
    async finishEvent(id: string, outcome: string, err: string | null) {
      await db.from("billing_events").update({ outcome, error: err, processed_at: new Date().toISOString() }).eq("stripe_event_id", id);
    },
    async linkCustomer(userId: string, customerId: string) {
      const { error } = await db.from("billing_customers").upsert({ user_id: userId, stripe_customer_id: customerId }, { onConflict: "user_id" });
      if (error) throw error;
    },
    async userIdForCustomer(customerId: string) {
      const { data, error } = await db.from("billing_customers").select("user_id").eq("stripe_customer_id", customerId).maybeSingle();
      if (error) throw error;
      return data ? data.user_id : null;
    },
    async getSubscription(id: string) {
      const { data, error } = await db.from("subscriptions").select("user_id, stripe_event_created").eq("stripe_subscription_id", id).maybeSingle();
      if (error) throw error;
      return data;
    },
    async upsertSubscription(row: Record<string, unknown>) {
      const { error } = await db.from("subscriptions").upsert({ ...row, updated_at: new Date().toISOString() }, { onConflict: "stripe_subscription_id" });
      if (error) throw error;
    },
    async recordPayment(id: string, outcome: "paid" | "failed", at: string | null) {
      if (outcome === "failed") {
        const { data } = await db.from("subscriptions").select("payment_failed_at").eq("stripe_subscription_id", id).maybeSingle();
        const { error } = await db.from("subscriptions").update({ last_payment_status: "failed", payment_failed_at: (data && data.payment_failed_at) || at, updated_at: new Date().toISOString() }).eq("stripe_subscription_id", id);
        if (error) throw error;
      } else {
        const { error } = await db.from("subscriptions").update({ last_payment_status: "paid", payment_failed_at: null, updated_at: new Date().toISOString() }).eq("stripe_subscription_id", id);
        if (error) throw error;
      }
    },
  };
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return json(405, { error: "method_not_allowed" });
  if (!SUPABASE_URL || !SERVICE_KEY) return json(503, { error: "not_configured" });
  const raw = await req.text();
  if (raw.length > 512_000) return json(413, { error: "too_large" });
  const db = createClient(SUPABASE_URL, SERVICE_KEY, { auth: { persistSession: false, autoRefreshToken: false } });
  const result = await processWebhook({
    rawBody: raw,
    signatureHeader: req.headers.get("stripe-signature") ?? "",
    secret: WEBHOOK_SECRET,
    store: store(db),
    plans: plansFromEnv((k: string) => Deno.env.get(k) ?? ""),
  });
  return json(result.status, result.body);
});
