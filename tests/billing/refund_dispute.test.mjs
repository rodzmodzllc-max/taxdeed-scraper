// Refund, dispute, duplicate, out-of-order, failure and grace-period tests for
// the paid-beta webhook (decided 2026-10-13; see docs/billing-refund-dispute.md).
// No network: events are built here and signed the way Stripe signs them.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  entitlementFor, hmacSha256Hex, processWebhook, planEvent, mergeCharge, accessHolds,
  stripeDisputeStatus, STATES, ROLES,
} from "../../supabase/functions/_shared/billing_core.js";

const SECRET = "whsec_test_only_not_a_real_secret";
const PLANS = { monthly: "price_monthly_test" };
const USER = "11111111-1111-4111-8111-111111111111";
const NOW = 1791201600; // 2026-10-05T12:00:00Z
const DAY = 86400;
const AMOUNT = 2900;

async function signed(event, t = NOW) {
  const raw = typeof event === "string" ? event : JSON.stringify(event);
  return { raw, header: `t=${t},v1=${await hmacSha256Hex(SECRET, `${t}.${raw}`)}` };
}

// In-memory store with the same contract as stripe-webhook/index.ts.
function memoryStore() {
  const s = { events: new Map(), customers: new Map(), subs: new Map(), charges: new Map(), log: [], fail: null };
  const guard = (name) => { if (s.fail && s.fail(name)) throw new Error(`simulated ${name} failure`); };
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
    async getSubscription(id) { guard("getSubscription"); return s.subs.get(id) || null; },
    async upsertSubscription(row) { guard("upsertSubscription"); s.subs.set(row.stripe_subscription_id, { ...(s.subs.get(row.stripe_subscription_id) || {}), ...row }); s.log.push("upsert"); },
    async recordPayment(id, outcome, at) {
      guard("recordPayment");
      const r = s.subs.get(id);
      r.last_payment_status = outcome;
      r.payment_failed_at = outcome === "failed" ? (r.payment_failed_at || at) : null;
      r.last_payment_event_at = at;
      s.log.push(`payment_${outcome}`);
    },
    async getCharge(id) { guard("getCharge"); return s.charges.get(id) || null; },
    async saveCharge(row) { guard("saveCharge"); s.charges.set(row.charge_id, { ...row }); s.log.push(`charge_${row.refund_state}_${row.dispute_status}`); },
  });
}

function subEvent(type, { id = "evt_" + Math.random().toString(36).slice(2), created = NOW, status = "active", cancel = false, periodEnd = NOW + 30 * DAY } = {}) {
  return {
    id, type, created, livemode: false,
    data: { object: {
      id: "sub_1", object: "subscription", customer: "cus_1", status, cancel_at_period_end: cancel,
      metadata: { user_id: USER },
      items: { data: [{ price: { id: PLANS.monthly, product: "prod_1" }, current_period_start: NOW - DAY, current_period_end: periodEnd }] },
    } },
  };
}
const invoiceEvent = (type, { id, created = NOW + 1, charge = "ch_1" } = {}) => ({
  id, type, created, livemode: false,
  data: { object: { id: "in_1", object: "invoice", customer: "cus_1", subscription: "sub_1", charge } },
});
const chargeEvent = (type, { id, created = NOW + 5, amount = AMOUNT, amountRefunded = 0, chargeId = "ch_1" } = {}) => ({
  id, type, created, livemode: false,
  data: { object: { id: chargeId, object: "charge", amount, amount_refunded: amountRefunded, refunded: amountRefunded >= amount, invoice: "in_1", customer: "cus_1" } },
});
const disputeEvent = (type, { id, created = NOW + 6, status = "needs_response", chargeId = "ch_1", disputeId = "dp_1" } = {}) => ({
  id, type, created, livemode: false,
  data: { object: { id: disputeId, object: "dispute", charge: chargeId, amount: AMOUNT, status, reason: "fraudulent" } },
});

async function deliver(store, event, { t = NOW } = {}) {
  const { raw, header } = await signed(event, t);
  return processWebhook({ rawBody: raw, signatureHeader: header, secret: SECRET, store, plans: PLANS, nowSec: NOW });
}

// A paying customer: subscription active, invoice linked to its charge.
async function paidAccount(store, extra = {}) {
  await deliver(store, subEvent("customer.subscription.created", { id: "s_create" }));
  await deliver(store, invoiceEvent("invoice.paid", { id: "e_paid" }));
  return store;
}

const ent = (store, { nowSec = NOW, profile = { approved: false, is_admin: false, access_grant: "tester" } } = {}) =>
  entitlementFor({
    profile,
    subscriptions: [...store.subs.values()].filter((r) => r.user_id === USER),
    charges: [...store.charges.values()],
    nowMs: nowSec * 1000,
  });

// ---------- full and partial refunds ----------
test("a full refund ends paid access", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, chargeEvent("charge.refunded", { id: "e_ref", amountRefunded: AMOUNT }));
  const e = ent(store);
  assert.equal(e.access, false);
  assert.equal(e.state, STATES.REFUNDED);
  assert.equal(e.subscription_status, "active", "Stripe still reports the subscription active; our hold decides access");
});

test("a partial refund keeps paid access", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, chargeEvent("charge.refunded", { id: "e_part", amountRefunded: 1000 }));
  const e = ent(store);
  assert.equal(store.charges.get("ch_1").refund_state, "partial");
  assert.equal(e.access, true);
  assert.equal(e.state, STATES.ACTIVE);
});

test("a second, smaller refund report never reduces the refunded amount", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, chargeEvent("charge.refunded", { id: "e_r1", amountRefunded: AMOUNT }));
  await deliver(store, chargeEvent("charge.refunded", { id: "e_r2", amountRefunded: 500, created: NOW + 2 }));
  assert.equal(store.charges.get("ch_1").amount_refunded, AMOUNT);
  assert.equal(ent(store).access, false);
});

test("a partial refund that later becomes full revokes access", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, chargeEvent("charge.refunded", { id: "e_p", amountRefunded: 1000 }));
  assert.equal(ent(store).access, true);
  await deliver(store, chargeEvent("charge.refunded", { id: "e_f", amountRefunded: AMOUNT, created: NOW + 9 }));
  assert.equal(ent(store).access, false);
});

test("a full refund revokes access even during the seven-day payment grace period", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, invoiceEvent("invoice.payment_failed", { id: "e_fail", created: NOW + 2 }));
  await deliver(store, subEvent("customer.subscription.updated", { id: "e_pd", created: NOW + 3, status: "past_due" }));
  assert.equal(ent(store, { nowSec: NOW + DAY }).state, STATES.PAYMENT_FAILED_GRACE);
  await deliver(store, chargeEvent("charge.refunded", { id: "e_gr", amountRefunded: AMOUNT }));
  assert.equal(ent(store, { nowSec: NOW + DAY }).access, false);
  assert.equal(ent(store, { nowSec: NOW + DAY }).state, STATES.REFUNDED);
});

test("a full refund does not change cancellation-at-period-end state beyond ending access", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, subEvent("customer.subscription.updated", { id: "e_cx", created: NOW + 2, cancel: true }));
  assert.equal(ent(store).state, STATES.CANCELLING);
  await deliver(store, chargeEvent("charge.refunded", { id: "e_cr", amountRefunded: AMOUNT }));
  assert.equal(ent(store).access, false);
  assert.equal(ent(store).state, STATES.REFUNDED);
});

// ---------- disputes ----------
test("an opened dispute is recorded and keeps access; it is not assumed won or lost", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, disputeEvent("charge.dispute.created", { id: "e_dc" }));
  const e = ent(store);
  assert.equal(store.charges.get("ch_1").dispute_status, "needs_response");
  assert.equal(e.access, true);
  assert.equal(e.disputed, true);
  assert.equal(e.state, STATES.ACTIVE);
});

test("a dispute under review is still open and keeps access", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, disputeEvent("charge.dispute.updated", { id: "e_du", status: "under_review" }));
  assert.equal(ent(store).access, true);
  assert.equal(ent(store).disputed, true);
});

test("a lost dispute ends paid access", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, disputeEvent("charge.dispute.created", { id: "e_dc2" }));
  await deliver(store, disputeEvent("charge.dispute.closed", { id: "e_dl", created: NOW + 50, status: "lost" }));
  const e = ent(store);
  assert.equal(e.access, false);
  assert.equal(e.state, STATES.DISPUTE_LOST);
  assert.equal(e.disputed, false);
});

test("a won dispute ends nothing: access continues", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, disputeEvent("charge.dispute.created", { id: "e_dc3" }));
  await deliver(store, disputeEvent("charge.dispute.closed", { id: "e_dw", created: NOW + 50, status: "won" }));
  assert.equal(ent(store).access, true);
  assert.equal(ent(store).disputed, false);
});

test("an inquiry closed without a chargeback (warning_closed) counts as won", () => {
  assert.equal(stripeDisputeStatus("warning_closed"), "won");
  assert.equal(stripeDisputeStatus("warning_needs_response"), "needs_response");
  assert.throws(() => stripeDisputeStatus("made_up"), /unknown dispute status/);
});

test("out of order: a closed (won) event arriving before the created event never regresses", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, disputeEvent("charge.dispute.closed", { id: "e_ow", created: NOW + 50, status: "won" }));
  const r = await deliver(store, disputeEvent("charge.dispute.created", { id: "e_oc", created: NOW + 6, status: "needs_response" }));
  assert.equal(r.status, 200);
  assert.equal(store.charges.get("ch_1").dispute_status, "won");
  assert.equal(ent(store).disputed, false);
});

test("out of order: a lost dispute is never undone by a later 'created' or 'updated' event", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, disputeEvent("charge.dispute.closed", { id: "e_lx", created: NOW + 50, status: "lost" }));
  await deliver(store, disputeEvent("charge.dispute.updated", { id: "e_lu", created: NOW + 60, status: "under_review" }));
  assert.equal(ent(store).access, false);
  assert.equal(ent(store).state, STATES.DISPUTE_LOST);
});

test("a dispute that arrives before the charge link is held until the link arrives", async () => {
  const store = memoryStore();
  await deliver(store, subEvent("customer.subscription.created", { id: "s_c2" }));
  await deliver(store, chargeEvent("charge.refunded", { id: "e_orf", amountRefunded: AMOUNT }));
  // Unattributed until the charge is linked to its subscription, so it cannot revoke yet.
  assert.equal(ent(store).access, true);
  await deliver(store, invoiceEvent("invoice.paid", { id: "e_olink" }));
  assert.equal(store.charges.get("ch_1").stripe_subscription_id, "sub_1");
  assert.equal(ent(store).access, false, "the refund applies once the charge is linked");
  assert.equal(ent(store).state, STATES.REFUNDED);
});

test("a second dispute on the same charge is refused and recorded as failed, not merged", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, disputeEvent("charge.dispute.created", { id: "e_d1", disputeId: "dp_1" }));
  const r = await deliver(store, disputeEvent("charge.dispute.created", { id: "e_d2", disputeId: "dp_2", created: NOW + 7 }));
  assert.equal(r.status, 500);
  assert.equal(store.events.get("e_d2").outcome, "failed");
  assert.equal(store.charges.get("ch_1").dispute_id, "dp_1");
});

// ---------- duplicates ----------
test("a duplicate refund event is acknowledged and not applied twice", async () => {
  const store = await paidAccount(memoryStore());
  const ev = chargeEvent("charge.refunded", { id: "e_dup_r", amountRefunded: AMOUNT });
  await deliver(store, ev);
  const again = await deliver(store, ev);
  assert.equal(again.body.duplicate, true);
  assert.equal(store.log.filter((x) => x.startsWith("charge_full")).length, 1);
});

test("a duplicate dispute event is acknowledged and not applied twice", async () => {
  const store = await paidAccount(memoryStore());
  const ev = disputeEvent("charge.dispute.closed", { id: "e_dup_d", created: NOW + 50, status: "lost" });
  await deliver(store, ev);
  const again = await deliver(store, ev);
  assert.equal(again.body.duplicate, true);
  assert.equal(store.charges.get("ch_1").dispute_status, "lost");
});

// ---------- out-of-order payments ----------
test("out of order: a payment failure older than a payment success never overwrites it", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, invoiceEvent("invoice.payment_failed", { id: "e_pf_old", created: NOW + 100 }));
  const late = await deliver(store, invoiceEvent("invoice.paid", { id: "e_pp_new", created: NOW + 200 }));
  assert.equal(late.status, 200);
  const stale = await deliver(store, invoiceEvent("invoice.payment_failed", { id: "e_pf_late", created: NOW + 150 }));
  assert.deepEqual(stale.body.applied, ["payment_stale", "charge_linked"]);
  assert.equal(store.subs.get("sub_1").last_payment_status, "paid");
  assert.equal(store.subs.get("sub_1").payment_failed_at, null);
});

test("out of order: a payment before its subscription fails so Stripe redelivers it, and is then applied", async () => {
  const store = memoryStore();
  const pay = invoiceEvent("invoice.payment_failed", { id: "e_early", created: NOW + 3, charge: null });
  const first = await deliver(store, pay);
  assert.equal(first.status, 500);
  assert.equal(store.events.get("e_early").outcome, "failed");
  await deliver(store, subEvent("customer.subscription.created", { id: "s_later" }));
  await deliver(store, invoiceEvent("invoice.payment_failed", { id: "e_early", created: NOW + 3, charge: null }));
  assert.equal(store.events.get("e_early").outcome, "processed");
  assert.equal(store.subs.get("sub_1").last_payment_status, "failed");
});

// ---------- failed processing: observable and recoverable ----------
test("a failed charge write is recorded as failed, answers 500, and is applied on redelivery", async () => {
  const store = await paidAccount(memoryStore());
  let broken = true;
  store.fail = (name) => broken && name === "saveCharge";
  const ev = chargeEvent("charge.refunded", { id: "e_fail_save", amountRefunded: AMOUNT });
  const first = await deliver(store, ev);
  assert.equal(first.status, 500);
  assert.equal(first.body.error, "processing_failed");
  assert.equal(store.events.get("e_fail_save").outcome, "failed");
  assert.match(store.events.get("e_fail_save").error, /simulated saveCharge failure/);
  assert.equal(ent(store).access, true, "nothing is granted or revoked on a failed event");
  broken = false;
  const retry = await deliver(store, ev);
  assert.equal(retry.status, 200);
  assert.equal(store.events.get("e_fail_save").outcome, "processed");
  assert.equal(ent(store).access, false);
});

test("a missing billing_charges table (migration 033 not applied) fails the event visibly, not silently", async () => {
  const store = await paidAccount(memoryStore());
  store.fail = (name) => name === "getCharge";
  const r = await deliver(store, chargeEvent("charge.refunded", { id: "e_nomig", amountRefunded: AMOUNT }));
  assert.equal(r.status, 500);
  assert.equal(store.events.get("e_nomig").outcome, "failed");
  assert.equal(ent(store).access, true);
});

test("a refund or dispute event with a bad signature is refused and nothing is recorded", async () => {
  const store = await paidAccount(memoryStore());
  const ev = chargeEvent("charge.refunded", { id: "e_sig", amountRefunded: AMOUNT });
  const { raw } = await signed(ev);
  const r = await processWebhook({ rawBody: raw, signatureHeader: `t=${NOW},v1=00`, secret: SECRET, store, plans: PLANS, nowSec: NOW });
  assert.equal(r.status, 400);
  assert.equal(store.charges.get("ch_1").refund_state, "none");
  assert.equal(ent(store).access, true);
});

test("a refund event without amounts is refused as malformed (failed row, no state change)", async () => {
  const store = await paidAccount(memoryStore());
  const bad = { id: "e_noamt", type: "charge.refunded", created: NOW, data: { object: { id: "ch_1" } } };
  const r = await deliver(store, bad);
  assert.equal(r.status, 400);
  assert.equal(store.charges.get("ch_1").refund_state, "none");
});

// ---------- support exception and other account types ----------
test("a manual customer grant keeps access after a full refund (the documented support exception)", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, chargeEvent("charge.refunded", { id: "e_sup", amountRefunded: AMOUNT }));
  const e = ent(store, { profile: { approved: true, is_admin: false, access_grant: "customer" } });
  assert.equal(e.state, STATES.MANUAL_CUSTOMER);
  assert.equal(e.access, true);
});

test("a tester keeps tester access regardless of refunds or disputes", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, chargeEvent("charge.refunded", { id: "e_t1", amountRefunded: AMOUNT }));
  await deliver(store, disputeEvent("charge.dispute.closed", { id: "e_t2", created: NOW + 50, status: "lost" }));
  const e = ent(store, { profile: { approved: true, is_admin: false, access_grant: "tester" } });
  assert.equal(e.role, ROLES.TESTER);
  assert.equal(e.access, true);
});

test("an admin is never affected by a hold", async () => {
  const store = await paidAccount(memoryStore());
  await deliver(store, disputeEvent("charge.dispute.closed", { id: "e_a1", created: NOW + 50, status: "lost" }));
  assert.equal(ent(store, { profile: { approved: true, is_admin: true } }).role, ROLES.ADMIN);
});

test("a refund or dispute on a subscription for another price grants nothing either way", async () => {
  const store = memoryStore();
  await deliver(store, { ...subEvent("customer.subscription.created", { id: "s_other" }), data: { object: { ...subEvent("x").data.object, items: { data: [{ price: { id: "price_other", product: "prod_x" }, current_period_end: NOW + DAY * 30 }] } } } });
  await deliver(store, invoiceEvent("invoice.paid", { id: "e_ol" }));
  await deliver(store, chargeEvent("charge.refunded", { id: "e_or", amountRefunded: AMOUNT }));
  assert.equal(ent(store).access, false, "a subscription on an unconfigured price grants nothing, even after a refund");
  assert.equal(ent(store, { profile: { approved: true, is_admin: false, access_grant: "customer" } }).state, STATES.MANUAL_CUSTOMER,
    "a manual grant is the only other way in, and it is unaffected");
});

// ---------- pure helpers ----------
test("mergeCharge: amounts are monotone, the first subscription link wins, and a second dispute id is refused", () => {
  let row = mergeCharge(null, { charge_id: "ch_x", amount: 100, amount_refunded: 60 });
  assert.equal(row.refund_state, "partial");
  row = mergeCharge(row, { charge_id: "ch_x", amount_refunded: 30 });
  assert.equal(row.amount_refunded, 60);
  row = mergeCharge(row, { charge_id: "ch_x", amount_refunded: 100 });
  assert.equal(row.refund_state, "full");
  row = mergeCharge(row, { charge_id: "ch_x", stripe_subscription_id: "sub_a" });
  row = mergeCharge(row, { charge_id: "ch_x", stripe_subscription_id: "sub_b" });
  assert.equal(row.stripe_subscription_id, "sub_a");
  assert.throws(() => mergeCharge(null, {}), /no charge id/);
});

test("accessHolds reads only the given subscription's charges", () => {
  const charges = [
    { stripe_subscription_id: "sub_a", refund_state: "full", dispute_status: "none" },
    { stripe_subscription_id: "sub_b", refund_state: "none", dispute_status: "lost" },
  ];
  assert.deepEqual(accessHolds(charges, "sub_a"), { refunded: true, dispute_lost: false, dispute_open: false });
  assert.deepEqual(accessHolds(charges, "sub_b"), { refunded: false, dispute_lost: true, dispute_open: false });
  assert.deepEqual(accessHolds(charges, null), { refunded: false, dispute_lost: false, dispute_open: false });
});

test("planEvent: a payment invoice that carries its charge also links the charge to the subscription", () => {
  const ops = planEvent(invoiceEvent("invoice.paid", { id: "p" }), PLANS);
  assert.deepEqual(ops.map((o) => o.op), ["payment", "charge"]);
  assert.equal(ops[1].charge.stripe_subscription_id, "sub_1");
});
