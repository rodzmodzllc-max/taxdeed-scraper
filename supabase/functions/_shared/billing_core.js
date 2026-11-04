// supabase/functions/_shared/billing_core.js
//
// Paid-beta billing core (2026-10-05). Plain JavaScript with no Deno, Node or
// Stripe-SDK dependency, so the SAME file runs inside the Edge Functions
// (stripe-webhook, billing-checkout, billing-portal) and under `node --test`
// (tests/billing/). Everything that decides access lives here or in its SQL
// mirror (scripts/migrations/027_commercial_billing_entitlements.sql,
// public.entitlement_for()); tests/billing/fixtures/entitlement_cases.json
// pins both to the same answers.
//
// Rules this file enforces:
//  - Stripe is the authority for a paid subscription. Access is granted only
//    from a webhook whose signature verifies against STRIPE_WEBHOOK_SECRET -
//    never from a browser redirect, a query string or anything a client sends.
//  - Webhook processing is idempotent: one row per Stripe event id; an event
//    already processed is acknowledged and not applied again; an older event
//    never overwrites a newer subscription state (stripe_event_created).
//  - Only the configured plan price(s) grant entitlement (plan_key). Another
//    product in the same Stripe account is recorded but grants nothing.
//  - Admin, tester and manually-granted access never depend on Stripe.

export const SUBSCRIPTION_STATUSES = Object.freeze([
  "incomplete", "incomplete_expired", "trialing", "active", "past_due", "canceled", "unpaid", "paused",
]);

// Who the account is, for access purposes. One vocabulary, used by the SQL
// mirror, the frontend (ACCESS.role) and the admin view.
export const ROLES = Object.freeze({ ADMIN: "admin", TESTER: "tester", CUSTOMER: "customer", INACTIVE: "inactive" });

// Why. Exactly one per account at a time.
export const STATES = Object.freeze({
  ADMIN_OVERRIDE: "admin_override",         // is_admin - never needs a subscription
  TESTER_BETA: "tester_beta",               // approved by an admin, access_grant = tester
  MANUAL_CUSTOMER: "manual_customer",       // approved by an admin, access_grant = customer (no Stripe)
  ACTIVE: "active",                         // Stripe status active
  TRIAL: "trial",                           // Stripe status trialing (not yet paid)
  CANCELLING: "cancelling",                 // active, cancel_at_period_end, period not over
  PAYMENT_FAILED_GRACE: "payment_failed_grace", // past_due, still inside the grace window
  PAYMENT_FAILED: "payment_failed",         // past_due beyond grace, or unpaid
  CANCELLED: "cancelled",                   // canceled, or cancel_at_period_end and the period is over
  INACTIVE: "inactive",                     // no access at all
});

// What inventory the account may see (the frontend and the RESTRICTIVE
// properties policy enforce the same three scopes).
//   all      - every collected row, labelled (admins)
//   preview  - tester inventory: customer rows + sources under review, labelled
//   approved - paid-beta inventory: rows whose source is explicitly APPROVED
//   none     - nothing
export const SCOPES = Object.freeze({ ALL: "all", PREVIEW: "preview", APPROVED: "approved", NONE: "none" });

export const DEFAULT_GRACE_DAYS = 7;
const DAY_MS = 86400000;

function ms(v) {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number") return v < 1e12 ? v * 1000 : v;   // Stripe sends seconds
  const t = Date.parse(v);
  return Number.isNaN(t) ? null : t;
}

// One subscription row -> its own entitlement, ignoring admin / approval.
export function subscriptionEntitlement(sub, nowMs, graceDays = DEFAULT_GRACE_DAYS) {
  if (!sub || !sub.plan_key) return { state: STATES.INACTIVE, access: false, reason: sub ? "Subscription is not for a configured plan" : "No subscription" };
  const end = ms(sub.current_period_end);
  switch (sub.status) {
    case "active":
      if (sub.cancel_at_period_end) {
        return end !== null && end > nowMs
          ? { state: STATES.CANCELLING, access: true, reason: "Cancellation scheduled - access until the end of the paid period" }
          : { state: STATES.CANCELLED, access: false, reason: "Cancelled - the paid period has ended" };
      }
      return { state: STATES.ACTIVE, access: true, reason: "Active subscription" };
    case "trialing":
      return { state: STATES.TRIAL, access: true, reason: "Trial period" };
    case "past_due": {
      const since = ms(sub.payment_failed_at) ?? end ?? nowMs;
      return nowMs < since + graceDays * DAY_MS
        ? { state: STATES.PAYMENT_FAILED_GRACE, access: true, reason: `Payment failed - access continues during the ${graceDays}-day grace period` }
        : { state: STATES.PAYMENT_FAILED, access: false, reason: "Payment failed - the grace period has ended" };
    }
    case "unpaid":
      return { state: STATES.PAYMENT_FAILED, access: false, reason: "Payment failed - subscription unpaid" };
    case "canceled":
      return { state: STATES.CANCELLED, access: false, reason: "Subscription cancelled" };
    default:   // incomplete, incomplete_expired, paused, anything unknown
      return { state: STATES.INACTIVE, access: false, reason: `Subscription ${sub.status || "not active"}` };
  }
}

// Several subscriptions (re-subscribed after a cancel): the one that grants
// access wins; otherwise the most recently changed one explains the state.
export function bestSubscription(subs, nowMs, graceDays = DEFAULT_GRACE_DAYS) {
  const list = (subs || []).filter(Boolean);
  if (!list.length) return null;
  const rank = (s) => {
    const e = subscriptionEntitlement(s, nowMs, graceDays);
    return (e.access ? 2 : 0) + (s.plan_key ? 1 : 0);
  };
  return list.slice().sort((a, b) => rank(b) - rank(a) ||
    (ms(b.stripe_event_created) ?? ms(b.updated_at) ?? 0) - (ms(a.stripe_event_created) ?? ms(a.updated_at) ?? 0))[0];
}

// THE access decision. profile = {approved, is_admin, access_grant}; subs =
// the account's subscription rows. Precedence: admin > tester > customer
// (manual or paid) > inactive. A tester who also pays keeps tester access
// (the larger, labelled inventory) and their subscription is still reported.
export function entitlementFor({ profile, subscriptions, nowMs, graceDays = DEFAULT_GRACE_DAYS }) {
  const now = nowMs ?? Date.now();
  const sub = bestSubscription(subscriptions, now, graceDays);
  const subEnt = subscriptionEntitlement(sub, now, graceDays);
  const base = { subscription_state: sub ? subEnt.state : null, subscription_status: sub ? sub.status : null };
  if (profile && profile.is_admin) return { role: ROLES.ADMIN, state: STATES.ADMIN_OVERRIDE, access: true, scope: SCOPES.ALL, reason: "Administrator", ...base };
  if (profile && profile.approved && (profile.access_grant || "tester") === "tester") {
    return { role: ROLES.TESTER, state: STATES.TESTER_BETA, access: true, scope: SCOPES.PREVIEW, reason: "Approved tester (beta) - no subscription needed", ...base };
  }
  if (subEnt.access) return { role: ROLES.CUSTOMER, state: subEnt.state, access: true, scope: SCOPES.APPROVED, reason: subEnt.reason, ...base };
  if (profile && profile.approved && profile.access_grant === "customer") {
    return { role: ROLES.CUSTOMER, state: STATES.MANUAL_CUSTOMER, access: true, scope: SCOPES.APPROVED, reason: "Customer access granted by an administrator", ...base };
  }
  return { role: ROLES.INACTIVE, state: sub ? subEnt.state : STATES.INACTIVE, access: false, scope: SCOPES.NONE,
    reason: sub ? subEnt.reason : "No approval and no active subscription", ...base };
}

// ==================== Stripe webhook signature ====================
// Stripe-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of "t.payload">[,v1=...]
export function parseSignatureHeader(header) {
  const out = { t: null, v1: [] };
  if (typeof header !== "string" || !header) return out;
  for (const part of header.split(",")) {
    const i = part.indexOf("=");
    if (i < 1) continue;
    const k = part.slice(0, i).trim(), v = part.slice(i + 1).trim();
    if (k === "t" && /^\d+$/.test(v)) out.t = Number(v);
    else if (k === "v1" && /^[0-9a-f]{64}$/i.test(v)) out.v1.push(v.toLowerCase());
  }
  return out;
}

export async function hmacSha256Hex(secret, message) {
  const enc = new TextEncoder();
  const key = await globalThis.crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await globalThis.crypto.subtle.sign("HMAC", key, enc.encode(message)));
  return Array.from(sig, (b) => b.toString(16).padStart(2, "0")).join("");
}

function timingSafeEqualHex(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function verifyStripeSignature(payload, header, secret, { toleranceSec = 300, nowSec } = {}) {
  if (!secret) return { ok: false, reason: "no_secret" };
  const { t, v1 } = parseSignatureHeader(header);
  if (t === null || !v1.length) return { ok: false, reason: "malformed_header" };
  const now = nowSec ?? Math.floor(Date.now() / 1000);
  if (Math.abs(now - t) > toleranceSec) return { ok: false, reason: "timestamp_outside_tolerance" };
  const expected = await hmacSha256Hex(secret, `${t}.${payload}`);
  return v1.some((s) => timingSafeEqualHex(s, expected)) ? { ok: true } : { ok: false, reason: "signature_mismatch" };
}

// ==================== Stripe object -> local rows ====================
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const idOf = (v) => (typeof v === "string" ? v : v && typeof v.id === "string" ? v.id : null);
const iso = (sec) => (typeof sec === "number" && Number.isFinite(sec) ? new Date(sec * 1000).toISOString() : null);

// plans: { <plan_key>: <price id> } - e.g. { monthly: env STRIPE_PRICE_ID }.
export function planKeyFor(priceId, plans) {
  for (const [k, v] of Object.entries(plans || {})) if (v && v === priceId) return k;
  return null;
}

export function subscriptionRow(sub, eventCreatedSec, plans) {
  if (!sub || typeof sub.id !== "string" || !sub.id) throw new Error("subscription object has no id");
  if (!SUBSCRIPTION_STATUSES.includes(sub.status)) throw new Error(`unknown subscription status: ${String(sub.status)}`);
  const item = sub.items && Array.isArray(sub.items.data) ? sub.items.data[0] : null;
  const price = (item && item.price) || sub.plan || null;
  const priceId = idOf(price);
  // Newer Stripe API versions moved the period onto the subscription item.
  const start = sub.current_period_start ?? (item && item.current_period_start);
  const end = sub.current_period_end ?? (item && item.current_period_end);
  const metaUser = sub.metadata && typeof sub.metadata.user_id === "string" && UUID_RE.test(sub.metadata.user_id) ? sub.metadata.user_id : null;
  return {
    stripe_subscription_id: sub.id,
    stripe_customer_id: idOf(sub.customer),
    status: sub.status,
    price_id: priceId,
    product_id: price ? idOf(price.product) : null,
    plan_key: planKeyFor(priceId, plans),
    current_period_start: iso(start),
    current_period_end: iso(end),
    cancel_at_period_end: !!sub.cancel_at_period_end,
    cancel_at: iso(sub.cancel_at),
    canceled_at: iso(sub.canceled_at),
    ended_at: iso(sub.ended_at),
    stripe_event_created: iso(eventCreatedSec),
    metadata_user_id: metaUser,
  };
}

function invoiceSubscriptionId(inv) {
  return idOf(inv.subscription) ||
    idOf(inv.parent && inv.parent.subscription_details && inv.parent.subscription_details.subscription) || null;
}

// The ordered operations one verified event asks for. Pure: no I/O.
export function planEvent(event, plans) {
  const obj = event && event.data && event.data.object;
  if (!obj || typeof obj !== "object") throw new Error("event has no data.object");
  switch (event.type) {
    case "checkout.session.completed": {
      if (obj.mode !== "subscription") return [{ op: "ignore", reason: "checkout not in subscription mode" }];
      const userId = [obj.client_reference_id, obj.metadata && obj.metadata.user_id].find((v) => typeof v === "string" && UUID_RE.test(v));
      const customer = idOf(obj.customer);
      if (!userId || !customer) return [{ op: "ignore", reason: "checkout session without a user / customer" }];
      // Links the account to its Stripe customer. Grants NOTHING by itself:
      // access comes from the subscription events below.
      return [{ op: "link_customer", user_id: userId, stripe_customer_id: customer }];
    }
    case "customer.subscription.created":
    case "customer.subscription.updated":
    case "customer.subscription.deleted":
    case "customer.subscription.paused":
    case "customer.subscription.resumed":
      return [{ op: "upsert_subscription", row: subscriptionRow(obj, event.created, plans) }];
    case "invoice.payment_failed":
    case "invoice.paid":
    case "invoice.payment_succeeded": {
      const subId = invoiceSubscriptionId(obj);
      if (!subId) return [{ op: "ignore", reason: "invoice without a subscription" }];
      return [{ op: "payment", stripe_subscription_id: subId, outcome: event.type === "invoice.payment_failed" ? "failed" : "paid", at: iso(event.created) }];
    }
    default:
      return [{ op: "ignore", reason: "event type not used" }];
  }
}

// ==================== webhook processor ====================
// store: { claimEvent(id, type, livemode) -> "new" | "retry" | "duplicate",
//          finishEvent(id, outcome, error), linkCustomer(userId, customerId),
//          userIdForCustomer(customerId), getSubscription(subId),
//          upsertSubscription(row), recordPayment(subId, outcome, atIso) }
export async function processWebhook({ rawBody, signatureHeader, secret, store, plans, nowSec, toleranceSec }) {
  if (!secret) return { status: 500, body: { error: "webhook_not_configured" } };
  const sig = await verifyStripeSignature(rawBody, signatureHeader, secret, { nowSec, toleranceSec });
  if (!sig.ok) return { status: 400, body: { error: "invalid_signature", reason: sig.reason } };
  let event;
  try { event = JSON.parse(rawBody); } catch { return { status: 400, body: { error: "malformed_event" } }; }
  if (!event || typeof event.id !== "string" || typeof event.type !== "string" || !event.data || typeof event.data.object !== "object") {
    return { status: 400, body: { error: "malformed_event" } };
  }
  const claim = await store.claimEvent(event.id, event.type, !!event.livemode);
  if (claim === "duplicate") return { status: 200, body: { received: true, duplicate: true } };
  let ops;
  try { ops = planEvent(event, plans); } catch (e) {
    await store.finishEvent(event.id, "failed", String(e && e.message || e));
    return { status: 400, body: { error: "malformed_event" } };
  }
  try {
    const applied = [];
    for (const op of ops) {
      if (op.op === "ignore") { applied.push("ignored"); continue; }
      if (op.op === "link_customer") { await store.linkCustomer(op.user_id, op.stripe_customer_id); applied.push("linked"); continue; }
      if (op.op === "upsert_subscription") {
        const row = { ...op.row };
        const userId = row.metadata_user_id || (row.stripe_customer_id ? await store.userIdForCustomer(row.stripe_customer_id) : null);
        delete row.metadata_user_id;
        // Not known yet (the checkout event links the customer): fail so
        // Stripe retries; nothing is granted meanwhile.
        if (!userId) throw new Error("subscription for a customer not linked to any account yet");
        const existing = await store.getSubscription(row.stripe_subscription_id);
        if (existing && ms(existing.stripe_event_created) !== null && ms(row.stripe_event_created) !== null &&
            ms(existing.stripe_event_created) > ms(row.stripe_event_created)) { applied.push("stale"); continue; }
        if (existing && existing.user_id && existing.user_id !== userId) throw new Error("subscription already belongs to another account");
        await store.upsertSubscription({ ...row, user_id: userId });
        applied.push("subscription");
        continue;
      }
      if (op.op === "payment") {
        const existing = await store.getSubscription(op.stripe_subscription_id);
        if (!existing) { applied.push("payment_for_unknown_subscription"); continue; }
        await store.recordPayment(op.stripe_subscription_id, op.outcome, op.at);
        applied.push(`payment_${op.outcome}`);
      }
    }
    const outcome = applied.every((a) => a === "ignored") ? "ignored" : "processed";
    await store.finishEvent(event.id, outcome, null);
    return { status: 200, body: { received: true, outcome, applied } };
  } catch (e) {
    await store.finishEvent(event.id, "failed", String(e && e.message || e));
    return { status: 500, body: { error: "processing_failed" } };
  }
}

// ==================== checkout / portal request bodies ====================
// Form-encoded bodies for Stripe's REST API (no SDK). The success URL never
// carries anything that grants access - the page only re-reads the server's
// entitlement, which only the verified webhook changes.
export function checkoutSessionParams({ priceId, customerId, userId, appUrl }) {
  if (!priceId) throw new Error("no price configured");
  if (!UUID_RE.test(String(userId || ""))) throw new Error("bad user id");
  const base = String(appUrl || "").replace(/[#?].*$/, "");
  const p = new URLSearchParams();
  p.set("mode", "subscription");
  p.set("line_items[0][price]", priceId);
  p.set("line_items[0][quantity]", "1");
  p.set("client_reference_id", userId);
  p.set("metadata[user_id]", userId);
  p.set("subscription_data[metadata][user_id]", userId);
  if (customerId) p.set("customer", customerId);
  p.set("success_url", `${base}#/billing?checkout=success`);
  p.set("cancel_url", `${base}#/billing?checkout=cancelled`);
  p.set("allow_promotion_codes", "false");
  return p;
}

export function portalSessionParams({ customerId, appUrl }) {
  if (!customerId) throw new Error("no customer");
  const p = new URLSearchParams();
  p.set("customer", customerId);
  p.set("return_url", `${String(appUrl || "").replace(/[#?].*$/, "")}#/billing`);
  return p;
}

// Plans from the environment: STRIPE_PRICE_ID is the one monthly plan.
export function plansFromEnv(get) {
  const monthly = (get("STRIPE_PRICE_ID") || "").trim();
  return monthly ? { monthly } : {};
}
