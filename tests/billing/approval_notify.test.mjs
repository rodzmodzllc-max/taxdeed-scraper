// Account-approval e-mail core tests (node --test tests/billing/). No network,
// no Resend account: delivery is mocked, and the outbox is an in-memory model
// of migration 030's claim / finish semantics (the SQL itself is exercised
// against PostgreSQL by tests/python/test_migration_030_approval_notifications.py).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  APPROVAL_EMAIL, renderApprovalEmail, processDue, authorize, sendViaResend, validEmail, retrySeconds, esc, MAX_ATTEMPTS,
  SIGNUP_ALERT, renderSignupAlert, utcStamp,
} from "../../supabase/functions/_shared/approval_notify_core.js";

const SECRET_KEY = "re_test_only_not_a_real_key";
const SERVICE = "service-role-test-key";

// In-memory model of public.account_notifications + profiles (migration 030).
function outbox() {
  const profiles = new Map();
  const rows = new Map();
  let seq = 0, clock = 0;
  const m = {
    profiles, rows,
    tick(sec) { clock += sec; },
    addUser(id, email, approved = false) { profiles.set(id, { email, approved, created: "2026-10-09T01:29:00Z", confirmed: true }); },
    // Account creation = the profiles INSERT trigger: one admin_new_signup row
    // per account for ever; a failed creation (throws) queues nothing.
    createAccount(id, email, { confirmed = true, fail = false } = {}) {
      if (fail) throw new Error("createUser failed");
      if (profiles.has(id)) return;                                     // handle_new_user: on conflict do nothing
      profiles.set(id, { email, approved: false, created: "2026-10-09T01:29:00Z", confirmed });
      if (![...rows.values()].some(r => r.user_id === id && r.kind === "admin_new_signup")) {
        const nid = `n${++seq}`;
        rows.set(nid, { id: nid, user_id: id, kind: "admin_new_signup", status: "pending", attempts: 0, next: clock, lease: null, sent: 0, msg: null, err: null });
      }
    },
    // The trigger: false -> true only, one row per (user, kind) for ever.
    approve(id) {
      const p = profiles.get(id);
      if (!p) throw new Error("approval failed: no such profile");     // persistence failure -> nothing queued
      const was = p.approved;
      p.approved = true;
      if (!was && ![...rows.values()].some(r => r.user_id === id && r.kind === "account_approved")) {
        const nid = `n${++seq}`;
        rows.set(nid, { id: nid, user_id: id, kind: "account_approved", status: "pending", attempts: 0, next: clock, lease: null, sent: 0, msg: null, err: null });
      }
    },
    async claim(limit) {
      const out = [];
      for (const r of [...rows.values()]) {
        if (out.length >= limit) break;
        const due = r.attempts < MAX_ATTEMPTS && ((["pending", "failed"].includes(r.status) && r.next <= clock) || (r.status === "sending" && r.lease < clock));
        if (!due) continue;
        r.status = "sending"; r.attempts += 1; r.lease = clock + 300;     // row is now held: a concurrent claim skips it
        const p = profiles.get(r.user_id);
        out.push({ id: r.id, kind: r.kind, attempt: r.attempts, email: p.email, approved: p.approved, signed_up_at: p.created, email_confirmed: p.confirmed });
      }
      return out;
    },
    async finish(id, attempt, outcome, messageId, error, retry) {
      const r = rows.get(id);
      if (!r || r.status !== "sending" || r.attempts !== attempt) return false;
      r.status = outcome; r.lease = null;
      if (outcome === "sent") { r.sent += 1; r.msg = messageId; r.err = null; }
      else { r.err = error; if (outcome === "failed") r.next = clock + retry; }
      return true;
    },
  };
  return m;
}

function mailer({ fail = 0 } = {}) {
  const sent = [];
  let failures = fail;
  const keys = new Set();
  return {
    sent, keys,
    async send(msg) {
      if (failures > 0) { failures -= 1; return { ok: false, code: "HTTP_503" }; }
      // Provider idempotency: the same key is one delivery.
      if (keys.has(msg.idempotencyKey)) return { ok: true, id: "dup-" + msg.idempotencyKey };
      keys.add(msg.idempotencyKey);
      sent.push(msg);
      return { ok: true, id: "msg_" + sent.length };
    },
  };
}

test("1. pending user approved -> exactly one approval e-mail", async () => {
  const db = outbox(); const m = mailer();
  db.addUser("u1", "new.user@example.com");
  db.approve("u1");
  const c = await processDue({ db, send: m.send });
  assert.deepEqual([c.claimed, c.sent], [1, 1]);
  assert.equal(m.sent.length, 1);
  assert.equal(m.sent[0].to, "new.user@example.com");
  assert.equal(m.sent[0].from, "TAXACQ <info@taxacq.com>");
  assert.equal(m.sent[0].replyTo, "info@taxacq.com");
  assert.equal(m.sent[0].subject, "Your TAXACQ account has been approved");
  const again = await processDue({ db, send: m.send });                 // nothing left to send
  assert.equal(again.claimed, 0);
  assert.equal(m.sent.length, 1);
});

test("2/3. a user left pending or rejected (never approved) gets nothing", async () => {
  const db = outbox(); const m = mailer();
  db.addUser("u1", "pending@example.com");
  db.addUser("u2", "rejected@example.com");                                // rejection keeps approved = false (or deletes the account)
  db.profiles.delete("u2");
  const c = await processDue({ db, send: m.send });
  assert.equal(c.claimed, 0);
  assert.equal(m.sent.length, 0);
});

test("4/5. already-approved user edited / re-approved, or approved twice concurrently -> no duplicate", async () => {
  const db = outbox(); const m = mailer();
  db.addUser("u1", "a@example.com");
  db.approve("u1"); db.approve("u1");                                     // second click / concurrent request
  await Promise.all([processDue({ db, send: m.send }), processDue({ db, send: m.send })]);
  db.profiles.get("u1").approved = false; db.approve("u1");               // unapproved then re-approved
  await processDue({ db, send: m.send });
  assert.equal(m.sent.length, 1);
  assert.equal(db.rows.size, 1);
});

test("6. approval persistence fails -> no e-mail queued or sent", async () => {
  const db = outbox(); const m = mailer();
  assert.throws(() => db.approve("missing"));
  await processDue({ db, send: m.send });
  assert.equal(m.sent.length, 0);
});

test("7/8. provider failure keeps the approval, records a code, retries without a duplicate", async () => {
  const db = outbox(); const m = mailer({ fail: 2 });
  db.addUser("u1", "retry@example.com");
  db.approve("u1");
  let c = await processDue({ db, send: m.send });
  assert.equal(c.failed, 1);
  const row = [...db.rows.values()][0];
  assert.equal(row.status, "failed");
  assert.equal(row.err, "HTTP_503");                                      // a code, never a body or address
  assert.equal(db.profiles.get("u1").approved, true);                     // approval untouched
  c = await processDue({ db, send: m.send });                             // back-off not elapsed
  assert.equal(c.claimed, 0);
  db.tick(retrySeconds(1)); c = await processDue({ db, send: m.send });   // second failure
  assert.equal(c.failed, 1);
  db.tick(retrySeconds(2)); c = await processDue({ db, send: m.send });
  assert.equal(c.sent, 1);
  db.tick(100000); c = await processDue({ db, send: m.send });
  assert.equal(c.claimed, 0);
  assert.equal(m.sent.length, 1);
  assert.equal(row.sent, 1);
  assert.equal(row.attempts, 3);
});

test("8b. a retry after a lost response reuses the idempotency key (one delivery)", async () => {
  const db = outbox(); const m = mailer();
  db.addUser("u1", "lost@example.com");
  db.approve("u1");
  const rows = await db.claim(10);                                        // a sender claims, sends, then dies before recording
  await m.send({ idempotencyKey: `account_approved/${rows[0].id}`, to: "lost@example.com" });
  db.tick(301);                                                            // lease expires
  await processDue({ db, send: m.send });
  assert.equal(m.sent.length, 1);
  assert.equal([...db.rows.values()][0].status, "sent");
});

test("8c. a stale sender cannot overwrite a newer attempt", async () => {
  const db = outbox();
  db.addUser("u1", "s@example.com"); db.approve("u1");
  const [first] = await db.claim(10);
  db.tick(301);
  const [second] = await db.claim(10);
  assert.equal(second.attempt, first.attempt + 1);
  assert.equal(await db.finish(first.id, first.attempt, "failed", null, "X", 60), false);
  assert.equal(await db.finish(second.id, second.attempt, "sent", "m1", null, 60), true);
});

test("skips: approval revoked before sending, or no usable address - nothing sent", async () => {
  const db = outbox(); const m = mailer();
  db.addUser("u1", "revoked@example.com"); db.approve("u1"); db.profiles.get("u1").approved = false;
  db.addUser("u2", "not-an-address"); db.approve("u2");
  const c = await processDue({ db, send: m.send });
  assert.equal(c.skipped, 2);
  assert.equal(m.sent.length, 0);
  assert.deepEqual([...db.rows.values()].map(r => r.err).sort(), ["NOT_APPROVED", "NO_VALID_EMAIL"]);
});

test("9. unauthorized callers are refused; admins and the server are allowed", async () => {
  const isAdminForJwt = async (jwt) => jwt === "admin-jwt";
  assert.deepEqual(await authorize({ bearer: "", serviceRoleKey: SERVICE, isAdminForJwt }), { ok: false, status: 401, reason: "not_signed_in" });
  assert.deepEqual(await authorize({ bearer: "customer-jwt", serviceRoleKey: SERVICE, isAdminForJwt }), { ok: false, status: 403, reason: "admin_only" });
  assert.deepEqual(await authorize({ bearer: "anon-key", serviceRoleKey: SERVICE, isAdminForJwt: async () => { throw new Error("bad jwt"); } }),
    { ok: false, status: 403, reason: "admin_only" });
  assert.equal((await authorize({ bearer: "admin-jwt", serviceRoleKey: SERVICE, isAdminForJwt })).as, "admin");
  assert.equal((await authorize({ bearer: SERVICE, serviceRoleKey: SERVICE, isAdminForJwt })).as, "service");
  assert.equal((await authorize({ bearer: "", serviceRoleKey: "", isAdminForJwt })).ok, false);   // an unset key never matches an empty bearer
});

test("9b. the processor never takes a recipient from the caller", async () => {
  const db = outbox(); const m = mailer();
  db.addUser("u1", "owner@example.com"); db.approve("u1");
  await processDue({ db, send: m.send, to: "attacker@example.com", email: "attacker@example.com" });
  assert.deepEqual(m.sent.map(x => x.to), ["owner@example.com"]);
});

test("10. HTML and plain text carry the TAXACQ content and the https://taxacq.com destination", () => {
  const { subject, html, text } = renderApprovalEmail();
  assert.equal(subject, "Your TAXACQ account has been approved");
  for (const body of [html, text]) {
    for (const s of ["Welcome to TAXACQ.", "Your account has been approved, and you can now sign in to Tax Acquisition Intelligence.",
                     "Auctions", "Available", "Start exploring properties, review source records, examine parcel information, and organize your due diligence.",
                     "Coverage, source freshness, and available purchase information vary by state and source.",
                     "If you have trouble accessing your account, reply to this email and we will help.",
                     "Tax Acquisition Intelligence", "Find the property. Understand the record. Know how to acquire it.",
                     "info@taxacq.com", "6175 NW 167th Ave, Hialeah, FL 33015"]) {
      assert.ok(body.includes(s), `missing: ${s}`);
    }
  }
  assert.ok(text.includes("Liens & Certificates"));
  assert.ok(html.includes("Liens &amp; Certificates"));
  assert.ok(html.includes('href="https://taxacq.com"') && html.includes(">Access TAXACQ</a>"));
  assert.ok(text.includes("Access TAXACQ: https://taxacq.com"));
  assert.ok(html.includes("#0b1a2e") && html.includes("#c9a24b"));     // navy + gold
  // Approval only - never a subscription / paid / unlimited claim.
  for (const body of [html.toLowerCase(), text.toLowerCase()]) {
    for (const w of ["subscription", "premium", "unlimited", "paid plan", "full access"]) assert.ok(!body.includes(w), w);
  }
});

test("11. no secret, user id, admin identity or note reaches the e-mail; values are escaped", async () => {
  const db = outbox(); const m = mailer();
  db.addUser("11111111-2222-3333-4444-555555555555", "x@example.com"); db.approve("11111111-2222-3333-4444-555555555555");
  await processDue({ db, send: m.send });
  const msg = m.sent[0];
  for (const body of [msg.html, msg.text, msg.subject]) {
    for (const bad of [SECRET_KEY, SERVICE, "11111111-2222-3333-4444-555555555555", "is_admin", "approved_at", "x@example.com"]) {
      assert.ok(!body.includes(bad), bad);
    }
  }
  const evil = renderApprovalEmail({ ...APPROVAL_EMAIL, address: "<script>alert(1)</script>", site: "javascript:alert(1)" });
  assert.ok(!evil.html.includes("<script>alert(1)"));
  assert.ok(evil.html.includes('href="https://taxacq.com"'));            // a non-https site falls back to the real one
  assert.equal(esc(`<a href="x">'&`), "&lt;a href=&quot;x&quot;&gt;&#39;&amp;");
});

test("Resend call: headers, idempotency key, and codes instead of provider bodies", async () => {
  const calls = [];
  const ok = await sendViaResend(async (url, init) => { calls.push({ url, init }); return { ok: true, json: async () => ({ id: "re_123" }) }; },
    SECRET_KEY, { from: APPROVAL_EMAIL.from, replyTo: APPROVAL_EMAIL.replyTo, to: "t@example.com", subject: "s", html: "<p>h</p>", text: "t", idempotencyKey: "account_approved/n1" });
  assert.deepEqual(ok, { ok: true, id: "re_123" });
  assert.equal(calls[0].url, "https://api.resend.com/emails");
  assert.equal(calls[0].init.headers["Idempotency-Key"], "account_approved/n1");
  assert.equal(calls[0].init.headers.Authorization, `Bearer ${SECRET_KEY}`);
  const body = JSON.parse(calls[0].init.body);
  assert.deepEqual([body.from, body.reply_to, body.to], ["TAXACQ <info@taxacq.com>", "info@taxacq.com", ["t@example.com"]]);
  assert.ok(body.html && body.text);
  const bad = await sendViaResend(async () => ({ ok: false, status: 422, text: async () => "t@example.com is invalid" }), SECRET_KEY, { idempotencyKey: "k" });
  assert.deepEqual(bad, { ok: false, code: "HTTP_422" });
  assert.deepEqual(await sendViaResend(async () => { throw new Error("down"); }, SECRET_KEY, { idempotencyKey: "k" }), { ok: false, code: "NETWORK" });
  assert.deepEqual(await sendViaResend(async () => assert.fail("no call without a key"), "", { idempotencyKey: "k" }), { ok: false, code: "NOT_CONFIGURED" });
});

test("address validation and back-off schedule", () => {
  assert.ok(validEmail("a.b+c@example.co"));
  for (const bad of ["", "no-at", "a@b", "a b@example.com", "<a@example.com>", null, "x@example.com,y@example.com"]) assert.ok(!validEmail(bad), String(bad));
  assert.deepEqual([1, 2, 3, 4, 5, 6, 9].map(retrySeconds), [300, 900, 3600, 10800, 21600, 43200, 43200]);
});


// ===== Operator alert for every new account (kind admin_new_signup) =====

test("signup alert: a created account sends exactly one alert, to the fixed operator address only", async () => {
  const db = outbox(); const m = mailer();
  db.createAccount("s1", "Someone@Example.com");
  const c = await processDue({ db, send: m.send });
  assert.deepEqual([c.claimed, c.sent, c.failed, c.skipped], [1, 1, 0, 0]);
  assert.equal(m.sent.length, 1);
  assert.equal(m.sent[0].to, "info@taxacq.com");
  assert.equal(SIGNUP_ALERT.to, "info@taxacq.com");
  assert.equal(m.sent[0].from, "TAXACQ <info@taxacq.com>");
  assert.equal(m.sent[0].idempotencyKey.startsWith("admin_new_signup/"), true);
  assert.match(m.sent[0].text, /Account email: Someone@Example\.com/);
});

test("signup alert: a failed sign-up queues and sends nothing", async () => {
  const db = outbox(); const m = mailer();
  assert.throws(() => db.createAccount("s1", "x@example.com", { fail: true }));
  const c = await processDue({ db, send: m.send });
  assert.deepEqual([c.claimed, m.sent.length], [0, 0]);
});

test("signup alert: retries, concurrent senders and a repeated creation never duplicate it", async () => {
  const db = outbox(); const m = mailer();
  db.createAccount("s1", "a@example.com");
  db.createAccount("s1", "a@example.com");                              // retried request / concurrent insert
  assert.equal([...db.rows.values()].filter(r => r.kind === "admin_new_signup").length, 1);
  const [a, b] = await Promise.all([processDue({ db, send: m.send }), processDue({ db, send: m.send })]);
  assert.equal(a.sent + b.sent, 1);
  await processDue({ db, send: m.send });
  assert.equal(m.sent.length, 1);
});

test("signup alert: provider failure is recorded with a code and retried; the account is untouched", async () => {
  const db = outbox(); const m = mailer({ fail: 1 });
  db.createAccount("s1", "a@example.com");
  let c = await processDue({ db, send: m.send });
  assert.deepEqual([c.failed, c.sent], [1, 0]);
  const row = [...db.rows.values()][0];
  assert.deepEqual([row.status, row.err], ["failed", "HTTP_503"]);
  assert.ok(db.profiles.has("s1"), "the account still exists");
  db.tick(retrySeconds(1));
  c = await processDue({ db, send: m.send });
  assert.equal(c.sent, 1);
  assert.equal(m.sent.length, 1);
});

test("signup alert and approval e-mail are independent: separate rows, keys, recipients and templates", async () => {
  const db = outbox(); const m = mailer();
  db.createAccount("s1", "person@example.com");
  db.approve("s1");
  const c = await processDue({ db, send: m.send });
  assert.equal(c.sent, 2);
  const byTo = Object.fromEntries(m.sent.map(x => [x.to, x]));
  assert.deepEqual(Object.keys(byTo).sort(), ["info@taxacq.com", "person@example.com"]);
  assert.match(byTo["info@taxacq.com"].subject, /New TAXACQ account created/);
  assert.match(byTo["person@example.com"].subject, /approved/);
  assert.notEqual(byTo["info@taxacq.com"].idempotencyKey.split("/")[0], byTo["person@example.com"].idempotencyKey.split("/")[0]);
  // Re-approving or another sweep sends neither again.
  db.approve("s1");
  await processDue({ db, send: m.send });
  assert.equal(m.sent.length, 2);
});

test("signup alert content: time, account email, actual statuses, verified admin link; HTML and text", () => {
  const unconfirmedPending = renderSignupAlert({ email: "a@b.co", signed_up_at: "2026-10-09T01:29:30Z", email_confirmed: false, approved: false });
  for (const body of [unconfirmedPending.text, unconfirmedPending.html]) {
    assert.match(body, /2026-10-09 01:29 UTC/);
    assert.match(body, /a@b\.co/);
    assert.match(body, /Not confirmed/);
    assert.match(body, /Pending approval/);
    assert.match(body, /https:\/\/taxacq\.com\/admin\.html#pending/);
  }
  const confirmedApproved = renderSignupAlert({ email: "a@b.co", signed_up_at: "2026-10-09T01:29:30Z", email_confirmed: true, approved: true }).text;
  assert.match(confirmedApproved, /Email confirmation: Confirmed/);
  assert.match(confirmedApproved, /Approval: Approved/);
  assert.equal(utcStamp("not a date"), "Not recorded");
  assert.match(renderSignupAlert({ email: "", signed_up_at: null }).text, /Account email: Not recorded/);
  // The admin link is the real admin page's "Pending sign-ups" section.
  const adminHtml = readFileSync(new URL("../../public/admin.html", import.meta.url), "utf8");
  assert.match(adminHtml, /<section class="admin-card" id="pending" aria-labelledby="adminPendingLabel">/);
  assert.match(adminHtml, /Pending sign-ups/);
});

test("signup alert: account e-mail is escaped (user-supplied), and a caller cannot redirect the alert", async () => {
  const evil = '"><script>alert(1)</script>@x.co';
  const a = renderSignupAlert({ email: evil, signed_up_at: "2026-10-09T00:00:00Z" });
  assert.ok(!a.html.includes("<script>"));
  assert.match(a.text, /not a valid address/);
  // A row carrying some other address never changes the recipient.
  const db = outbox(); const m = mailer();
  db.createAccount("s1", "attacker-chosen@example.com");
  await processDue({ db, send: m.send });
  assert.deepEqual(m.sent.map(x => x.to), ["info@taxacq.com"]);
  // A tampered alert config with a bad link falls back to the verified one.
  assert.match(renderSignupAlert({ email: "a@b.co" }, { ...SIGNUP_ALERT, adminUrl: "javascript:alert(1)" }).text, /https:\/\/taxacq\.com\/admin\.html#pending/);
});

test("signup alert: nothing is logged by the processor (no address, body, password or key)", async () => {
  const seen = [];
  const orig = { log: console.log, error: console.error, warn: console.warn, info: console.info };
  for (const k of Object.keys(orig)) console[k] = (...a) => seen.push(a.join(" "));
  try {
    const db = outbox(); const m = mailer({ fail: 1 });
    db.createAccount("s1", "secret.person@example.com");
    await processDue({ db, send: m.send });
    await sendViaResend(async () => ({ ok: false, status: 500, json: async () => ({ message: "secret.person@example.com" }) }), SECRET_KEY,
      { to: "info@taxacq.com", idempotencyKey: "k", subject: "s", html: "h", text: "t" });
  } finally { Object.assign(console, orig); }
  assert.deepEqual(seen, []);
});
