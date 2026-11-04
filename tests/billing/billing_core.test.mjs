// Billing core tests (node --test tests/billing/). No network, no Stripe
// account: events are built here and signed with a test secret exactly the
// way Stripe signs them (HMAC-SHA256 over "<t>.<raw body>").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  entitlementFor, verifyStripeSignature, hmacSha256Hex, processWebhook, planEvent, subscriptionRow,
  checkoutSessionParams, portalSessionParams, plansFromEnv, STATES, ROLES,
} from "../../supabase/functions/_shared/billing_core.js";

const SECRET = "whsec_test_only_not_a_real_secret";
const PLANS = { monthly: "price_monthly_test" };
const USER = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const NOW = 1791201600; // 2026-10-05T12:00:00Z

async function signed(event, { secret = SECRET, t = NOW } = {}) {
  const raw = typeof event === "string" ? event : JSON.stringify(event);
  return { raw, header: `t=${t},v1=${await hmacSha256Hex(secret, `${t}.${raw}`)}` };
}

function memoryStore() {
  const s = { events: new Map(), customers: new Map(), subs: new Map(), log: [] };
  return Object.assign(s, {
    async claimEvent(id, type) {
      const e = s.events.get(id);
      if (e && (e.outcome === "processed" || e.outcome === "ignored")) return "duplicate";
      s.events.set(id, { type, outcome: "received" });
      return e ? "retry" : "new";
    },
    async finishEvent(id, outcome, error) { s.events.get(id).outcome = outcome; s.events.get(id).error = error; },
    async linkCustomer(u, c) { s.customers.set(c, u); },
    async userIdForCustomer(c) { return s.customers.get(c) || null; },
    async getSubscription(id) { return s.subs.get(id) || null; },
    async upsertSubscription(row) { s.subs.set(row.stripe_subscription_id, { ...(s.subs.get(row.stripe_subscription_id) || {}), ...row }); s.log.push("upsert"); },
    async recordPayment(id, outcome, at) {
      const r = s.subs.get(id);
      r.last_payment_status = outcome;
      r.payment_failed_at = outcome === "failed" ? (r.payment_failed_at || at) : null;
    },
  });
}

function subEvent(type, { id = "evt_" + Math.random().toString(36).slice(2), created = NOW, status = "active", cancel = false, user = USER, price = PLANS.monthly, periodEnd = NOW + 30 * 86400 } = {}) {
  return {
    id, type, created, livemode: false,
    data: { object: {
      id: "sub_1", object: "subscription", customer: "cus_1", status, cancel_at_period_end: cancel,
      metadata: user ? { user_id: user } : {},
      items: { data: [{ price: { id: price, product: "prod_1" }, current_period_start: NOW - 86400, current_period_end: periodEnd }] },
    } },
  };
}

async function deliver(store, event, opts) {
  const { raw, header } = await signed(event, opts);
  return processWebhook({ rawBody: raw, signatureHeader: header, secret: SECRET, store, plans: PLANS, nowSec: NOW });
}

const ent = (store, nowSec = NOW, profile = { approved: false, is_admin: false, access_grant: "tester" }) =>
  entitlementFor({ profile, subscriptions: [...store.subs.values()].filter((r) => r.user_id === USER), nowMs: nowSec * 1000 });

// ---------- entitlement vectors (shared with the SQL mirror) ----------
const vectors = JSON.parse(readFileSync(new URL("./fixtures/entitlement_cases.json", import.meta.url), "utf8"));
for (const c of vectors.cases) {
  test(`entitlement: ${c.name}`, () => {
    const e = entitlementFor({ profile: c.profile, subscriptions: c.subscriptions, nowMs: Date.parse(vectors.now) });
    for (const [k, v] of Object.entries(c.expect)) assert.equal(e[k], v, `${c.name}.${k}`);
  });
}

// ---------- signature ----------
test("valid signature verifies", async () => {
  const { raw, header } = await signed({ id: "evt_a", type: "ping", data: { object: {} } });
  assert.deepEqual(await verifyStripeSignature(raw, header, SECRET, { nowSec: NOW }), { ok: true });
});
test("invalid signature is refused and nothing is recorded", async () => {
  const store = memoryStore();
  const { raw } = await signed(subEvent("customer.subscription.created"));
  const forged = await signed(subEvent("customer.subscription.created"), { secret: "whsec_attacker" });
  const r = await processWebhook({ rawBody: raw, signatureHeader: forged.header, secret: SECRET, store, plans: PLANS, nowSec: NOW });
  assert.equal(r.status, 400);
  assert.equal(r.body.error, "invalid_signature");
  assert.equal(store.events.size, 0);
  assert.equal(store.subs.size, 0);
});
test("tampered body fails verification", async () => {
  const { raw, header } = await signed(subEvent("customer.subscription.created"));
  const r = await verifyStripeSignature(raw.replace('"active"', '"trialing"'), header, SECRET, { nowSec: NOW });
  assert.equal(r.ok, false);
});
test("stale timestamp (replay) is refused", async () => {
  const { raw, header } = await signed(subEvent("customer.subscription.created"), { t: NOW - 3600 });
  assert.equal((await verifyStripeSignature(raw, header, SECRET, { nowSec: NOW })).reason, "timestamp_outside_tolerance");
});
test("missing secret refuses every event", async () => {
  const { raw, header } = await signed(subEvent("customer.subscription.created"));
  const r = await processWebhook({ rawBody: raw, signatureHeader: header, secret: "", store: memoryStore(), plans: PLANS, nowSec: NOW });
  assert.equal(r.status, 500);
});
test("missing / malformed signature header is refused", async () => {
  assert.equal((await verifyStripeSignature("{}", "", SECRET, { nowSec: NOW })).reason, "malformed_header");
  assert.equal((await verifyStripeSignature("{}", "t=abc,v1=zz", SECRET, { nowSec: NOW })).reason, "malformed_header");
});

// ---------- lifecycle ----------
test("subscription activation grants paid access", async () => {
  const store = memoryStore();
  const r = await deliver(store, subEvent("customer.subscription.created"));
  assert.equal(r.status, 200);
  const e = ent(store);
  assert.equal(e.role, ROLES.CUSTOMER);
  assert.equal(e.state, STATES.ACTIVE);
  assert.equal(e.scope, "approved");
});
test("checkout.session.completed links the customer but grants nothing on its own", async () => {
  const store = memoryStore();
  const r = await deliver(store, { id: "evt_cs", type: "checkout.session.completed", created: NOW,
    data: { object: { mode: "subscription", client_reference_id: USER, customer: "cus_9", subscription: "sub_9", payment_status: "paid" } } });
  assert.equal(r.status, 200);
  assert.equal(store.customers.get("cus_9"), USER);
  assert.equal(store.subs.size, 0);
  assert.equal(ent(store).access, false);
});
test("subscription without metadata resolves the account through the linked customer", async () => {
  const store = memoryStore();
  await deliver(store, { id: "evt_cs2", type: "checkout.session.completed", created: NOW, data: { object: { mode: "subscription", client_reference_id: USER, customer: "cus_1" } } });
  const r = await deliver(store, subEvent("customer.subscription.created", { user: null }));
  assert.equal(r.status, 200);
  assert.equal(store.subs.get("sub_1").user_id, USER);
});
test("subscription for an unknown customer fails (Stripe retries) and grants nothing", async () => {
  const store = memoryStore();
  const r = await deliver(store, subEvent("customer.subscription.created", { id: "evt_unk", user: null }));
  assert.equal(r.status, 500);
  assert.equal(store.events.get("evt_unk").outcome, "failed");
  assert.equal(store.subs.size, 0);
});
test("a failed event is retried and applied on redelivery", async () => {
  const store = memoryStore();
  const ev = subEvent("customer.subscription.created", { id: "evt_retry", user: null });
  assert.equal((await deliver(store, ev)).status, 500);
  await store.linkCustomer(USER, "cus_1");
  assert.equal((await deliver(store, ev)).status, 200);
  assert.equal(store.subs.get("sub_1").user_id, USER);
});
test("duplicate webhook is acknowledged and not applied twice", async () => {
  const store = memoryStore();
  const ev = subEvent("customer.subscription.created", { id: "evt_dup" });
  await deliver(store, ev);
  const second = await deliver(store, ev);
  assert.equal(second.status, 200);
  assert.equal(second.body.duplicate, true);
  assert.equal(store.log.filter((x) => x === "upsert").length, 1);
});
test("payment failure: grace first, then restricted", async () => {
  const store = memoryStore();
  await deliver(store, subEvent("customer.subscription.created", { id: "e1" }));
  await deliver(store, { id: "e2", type: "invoice.payment_failed", created: NOW + 10, data: { object: { subscription: "sub_1", customer: "cus_1" } } });
  await deliver(store, subEvent("customer.subscription.updated", { id: "e3", created: NOW + 20, status: "past_due" }));
  assert.equal(store.subs.get("sub_1").last_payment_status, "failed");
  assert.equal(ent(store, NOW + 86400).state, STATES.PAYMENT_FAILED_GRACE);
  assert.equal(ent(store, NOW + 86400).access, true);
  assert.equal(ent(store, NOW + 8 * 86400).state, STATES.PAYMENT_FAILED);
  assert.equal(ent(store, NOW + 8 * 86400).access, false);
});
test("payment recovered clears the failure", async () => {
  const store = memoryStore();
  await deliver(store, subEvent("customer.subscription.created", { id: "p1" }));
  await deliver(store, { id: "p2", type: "invoice.payment_failed", created: NOW + 10, data: { object: { subscription: "sub_1" } } });
  await deliver(store, { id: "p3", type: "invoice.paid", created: NOW + 20, data: { object: { parent: { subscription_details: { subscription: "sub_1" } } } } });
  assert.equal(store.subs.get("sub_1").last_payment_status, "paid");
  assert.equal(store.subs.get("sub_1").payment_failed_at, null);
});
test("cancellation at period end keeps access until the period ends", async () => {
  const store = memoryStore();
  await deliver(store, subEvent("customer.subscription.created", { id: "c1" }));
  await deliver(store, subEvent("customer.subscription.updated", { id: "c2", created: NOW + 5, cancel: true }));
  assert.equal(ent(store).state, STATES.CANCELLING);
  assert.equal(ent(store).access, true);
  assert.equal(ent(store, NOW + 31 * 86400).access, false);
});
test("subscription expiration (deleted) removes access", async () => {
  const store = memoryStore();
  await deliver(store, subEvent("customer.subscription.created", { id: "x1" }));
  await deliver(store, subEvent("customer.subscription.deleted", { id: "x2", created: NOW + 5, status: "canceled" }));
  assert.equal(ent(store).state, STATES.CANCELLED);
  assert.equal(ent(store).access, false);
});
test("an older event never overwrites a newer state", async () => {
  const store = memoryStore();
  await deliver(store, subEvent("customer.subscription.deleted", { id: "o2", created: NOW + 100, status: "canceled" }));
  const r = await deliver(store, subEvent("customer.subscription.updated", { id: "o1", created: NOW + 1, status: "active" }));
  assert.deepEqual(r.body.applied, ["stale"]);
  assert.equal(store.subs.get("sub_1").status, "canceled");
});
test("a subscription cannot move to another account", async () => {
  const store = memoryStore();
  await deliver(store, subEvent("customer.subscription.created", { id: "m1" }));
  const r = await deliver(store, subEvent("customer.subscription.updated", { id: "m2", created: NOW + 5, user: OTHER }));
  assert.equal(r.status, 500);
  assert.equal(store.subs.get("sub_1").user_id, USER);
});
test("a subscription on another price is recorded but grants nothing", async () => {
  const store = memoryStore();
  await deliver(store, subEvent("customer.subscription.created", { id: "pp", price: "price_other_product" }));
  assert.equal(store.subs.get("sub_1").plan_key, null);
  assert.equal(ent(store).access, false);
});
test("unknown event type is acknowledged and ignored", async () => {
  const store = memoryStore();
  const r = await deliver(store, { id: "evt_u", type: "customer.created", created: NOW, data: { object: { id: "cus_1" } } });
  assert.equal(r.status, 200);
  assert.equal(r.body.outcome, "ignored");
  assert.equal(store.events.get("evt_u").outcome, "ignored");
});
test("malformed events are refused", async () => {
  const store = memoryStore();
  const notJson = await signed("{not json");
  assert.equal((await processWebhook({ rawBody: notJson.raw, signatureHeader: notJson.header, secret: SECRET, store, plans: PLANS, nowSec: NOW })).status, 400);
  const noObject = await signed({ id: "evt_m", type: "customer.subscription.updated", data: {} });
  assert.equal((await processWebhook({ rawBody: noObject.raw, signatureHeader: noObject.header, secret: SECRET, store, plans: PLANS, nowSec: NOW })).status, 400);
  const badStatus = await signed(subEvent("customer.subscription.updated", { id: "evt_bs", status: "made_up" }));
  const r = await processWebhook({ rawBody: badStatus.raw, signatureHeader: badStatus.header, secret: SECRET, store, plans: PLANS, nowSec: NOW });
  assert.equal(r.status, 400);
  assert.equal(store.subs.size, 0);
});
test("planEvent ignores non-subscription checkouts", () => {
  assert.equal(planEvent({ type: "checkout.session.completed", data: { object: { mode: "payment" } } }, PLANS)[0].op, "ignore");
});
test("subscriptionRow reads the period from the subscription item (newer API) or the subscription (older)", () => {
  const ev = subEvent("customer.subscription.updated");
  assert.ok(subscriptionRow(ev.data.object, NOW, PLANS).current_period_end);
  const old = { ...ev.data.object, items: { data: [{ price: { id: PLANS.monthly, product: "prod_1" } }] }, current_period_end: NOW + 100 };
  assert.equal(subscriptionRow(old, NOW, PLANS).current_period_end, new Date((NOW + 100) * 1000).toISOString());
});

// ---------- checkout / portal ----------
test("checkout session: one monthly price, the account on every reference, no access in the redirect", () => {
  const p = checkoutSessionParams({ priceId: "price_monthly_test", customerId: "cus_1", userId: USER, appUrl: "https://example.test/index.html#/list" });
  assert.equal(p.get("mode"), "subscription");
  assert.equal(p.get("line_items[0][price]"), "price_monthly_test");
  assert.equal(p.get("client_reference_id"), USER);
  assert.equal(p.get("subscription_data[metadata][user_id]"), USER);
  assert.equal(p.get("success_url"), "https://example.test/index.html#/billing?checkout=success");
  assert.equal(p.get("cancel_url"), "https://example.test/index.html#/billing?checkout=cancelled");
  assert.throws(() => checkoutSessionParams({ priceId: "", userId: USER, appUrl: "x" }));
  assert.throws(() => checkoutSessionParams({ priceId: "p", userId: "not-a-uuid", appUrl: "x" }));
});
test("billing portal session returns to the billing view", () => {
  const p = portalSessionParams({ customerId: "cus_1", appUrl: "https://example.test/" });
  assert.equal(p.get("customer"), "cus_1");
  assert.equal(p.get("return_url"), "https://example.test/#/billing");
  assert.throws(() => portalSessionParams({ customerId: "", appUrl: "x" }));
});
test("plans come only from configuration", () => {
  assert.deepEqual(plansFromEnv(() => ""), {});
  assert.deepEqual(plansFromEnv((k) => (k === "STRIPE_PRICE_ID" ? " price_x " : "")), { monthly: "price_x" });
});
