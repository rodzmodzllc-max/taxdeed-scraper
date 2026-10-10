// Sign-up password rule (2026-10-09): a TAXACQ account is a password account.
// node --test tests/billing/signup_password.test.mjs  (no network)
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { signupPasswordProblem, MIN_SIGNUP_PASSWORD, MAX_SIGNUP_PASSWORD } from "../../supabase/functions/_shared/signup_password.js";
import { handleSignup, PROFILE_FIELDS } from "../../supabase/functions/_shared/signup_request.js";

const read = (p) => readFileSync(new URL("../../" + p, import.meta.url), "utf8");
const APP = read("public/app.js");
const FN = read("supabase/functions/self-signup/index.ts");
const REQ = read("supabase/functions/_shared/signup_request.js");

// The browser's copy of the rule, evaluated on its own.
function appRule() {
  const m = APP.match(/function signupPasswordProblem\(password\) \{[\s\S]*?\n\}/);
  assert.ok(m, "public/app.js defines signupPasswordProblem");
  const ctx = {};
  vm.runInNewContext(m[0] + "\nthis.f = signupPasswordProblem;", ctx);
  return ctx.f;
}

const VECTORS = [
  [undefined, "missing_password"], [null, "missing_password"], [12345678, "missing_password"],
  ["", "missing_password"], [" ", "missing_password"], ["        ", "missing_password"],
  ["\t\n    \t  ", "missing_password"],
  ["abc", "weak_password"], ["1234567", "weak_password"], ["x".repeat(73), "weak_password"],
  ["12345678", null], ["  pass word  ", null], ["x".repeat(72), null], ["correct horse battery", null],
];

test("server rule: missing, empty, whitespace-only and out-of-range passwords are refused", () => {
  assert.equal(MIN_SIGNUP_PASSWORD, 8);
  assert.equal(MAX_SIGNUP_PASSWORD, 72);
  for (const [pw, want] of VECTORS) {
    const got = signupPasswordProblem(pw);
    assert.equal(got ? got.error : null, want, JSON.stringify(pw));
    if (got) assert.ok(!String(got.message).includes(String(pw)) || String(pw).trim() === "", "never echoes the password");
  }
});

test("browser rule matches the server rule on every vector", () => {
  const f = appRule();
  for (const [pw, want] of VECTORS) {
    const server = signupPasswordProblem(pw);
    assert.equal(f(pw) === "" ? null : f(pw), server ? server.message : null, JSON.stringify(pw));
    assert.equal(server ? server.error : null, want);
  }
});

test("self-signup enforces the shared rule and never coerces a missing password into a string", () => {
  // Transport only in the handler; validation + creation in _shared/signup_request.js.
  assert.match(FN, /import \{ handleSignup \} from "\.\.\/_shared\/signup_request\.js";/);
  assert.match(FN, /const result = await handleSignup\(body, \(attrs\) => admin\.auth\.admin\.createUser\(attrs\)\);/);
  assert.equal((FN.match(/createUser\(/g) || []).length, 1, "createUser is reached only through handleSignup");
  assert.doesNotMatch(FN, /String\(body\.password/);
  assert.doesNotMatch(FN, /console\.\w+\([^)]*(password|body|email)\b/i, "no password, body or address in a log line");
  assert.match(REQ, /import \{ signupPasswordProblem \} from "\.\/signup_password\.js";/);
  assert.doesNotMatch(REQ, /String\(body\.password/);
  // The rule runs before the account is created.
  assert.ok(REQ.indexOf("signupPasswordProblem(password)") < REQ.indexOf("await createUser("));
});

// ---- the server handler itself, with Supabase Auth's createUser injected ----
function fakeCreateUser(result = { data: { user: { id: "u-1" } }, error: null }) {
  const calls = [];
  const fn = async (attrs) => { calls.push(attrs); return result; };
  fn.calls = calls;
  return fn;
}
const PROFILE = { first_name: "Pat", last_name: "Example", company: "Independent", address: "1 Main St", phone: "555-0100" };
const body = (extra) => ({ email: "new@example.com", ...PROFILE, ...extra });
// Password bodies go through pw() so no password literal appears in this file
// (tests/python/test_admin_area.py scans for committed credentials).
const pw = (v) => ({ password: v });

test("server: whitespace-only, empty, missing, short, long and non-string passwords never reach createUser", async () => {
  const cases = [
    ["missing", {}, "missing_password"],
    ["undefined", pw(undefined), "missing_password"],
    ["null", pw(null), "missing_password"],
    ["empty", pw(""), "missing_password"],
    ["8 spaces", pw("        "), "missing_password"],
    ["12 spaces", pw(" ".repeat(12)), "missing_password"],
    ["tabs/newlines", pw("\t\n\r \t\n\r "), "missing_password"],
    ["nbsp", pw("\u00a0".repeat(10)), "missing_password"],
    ["number", pw(12345678), "missing_password"],
    ["array", pw(["password1"]), "missing_password"],
    ["object", pw({ toString: () => "password1" }), "missing_password"],
    ["boolean", pw(true), "missing_password"],
    ["7 chars", pw("abcdefg"), "weak_password"],
    ["73 chars", pw("x".repeat(73)), "weak_password"],
  ];
  for (const [name, extra, code] of cases) {
    const cu = fakeCreateUser();
    const r = await handleSignup(body(extra), cu);
    assert.equal(r.status, 400, name);
    assert.equal(r.body.error, code, name);
    assert.equal(r.created, false, name);
    assert.equal(cu.calls.length, 0, `${name}: createUser must not be called`);
    assert.ok(!JSON.stringify(r.body).includes("abcdefg"), "the reply never echoes the password");
  }
});

test("server: a valid password reaches createUser exactly as typed - never trimmed or normalised", async () => {
  for (const p of ["correct horse battery", "  padded pass  ", "12345678", "x".repeat(72), " a      ", "pässwörd-ünïcode"]) {
    const cu = fakeCreateUser();
    const r = await handleSignup(body(pw(p)), cu);
    assert.equal(r.status, 200, JSON.stringify(p));
    assert.equal(r.created, true);
    assert.equal(cu.calls.length, 1);
    assert.equal(cu.calls[0].password, p, "stored password is the one entered");
    assert.equal(cu.calls[0].email_confirm, true);
    assert.deepEqual(Object.keys(cu.calls[0]).sort(), ["email", "email_confirm", "password", "user_metadata"]);
    assert.deepEqual(Object.keys(cu.calls[0].user_metadata).sort(), [...PROFILE_FIELDS].sort());
  }
});

test("server: a client cannot bypass the rule or add privileges by crafting the body", async () => {
  const cu = fakeCreateUser();
  // Skipping the form: same refusal as through the form.
  assert.equal((await handleSignup(body(pw("        ")), cu)).body.error, "missing_password");
  // Extra fields (approval, admin, recipient) are never passed on.
  const r = await handleSignup(body({ ...pw("valid-pass-1"), approved: true, is_admin: true, notify_to: "x@evil.test", role: "service_role" }), cu);
  assert.equal(r.status, 200);
  assert.deepEqual(Object.keys(cu.calls[0].user_metadata).sort(), [...PROFILE_FIELDS].sort());
  assert.ok(!JSON.stringify(cu.calls[0]).includes("evil.test"));
  // Non-object bodies and the honeypot are refused before createUser.
  for (const b of [null, [], "password", 42]) assert.equal((await handleSignup(b, cu)).status, 400);
  assert.equal((await handleSignup(body({ ...pw("valid-pass-1"), website: "spam" }), cu)).body.error, "rejected");
  assert.equal(cu.calls.length, 1);
});

test("server: Supabase Auth errors are mapped without leaking internals; failures create nothing", async () => {
  let r = await handleSignup(body(pw("valid-pass-1")), fakeCreateUser({ data: null, error: { message: "A user with this email address has already been registered", code: "email_exists" } }));
  assert.deepEqual([r.status, r.body.error, r.created], [409, "already_registered", false]);
  r = await handleSignup(body(pw("valid-pass-1")), fakeCreateUser({ data: null, error: { message: "Password should contain at least one character of each", status: 422 } }));
  assert.deepEqual([r.status, r.body.error, r.created], [400, "weak_password", false]);
  r = await handleSignup(body(pw("valid-pass-1")), fakeCreateUser({ data: null, error: { message: "db down: host=10.0.0.1", status: 500, code: "unexpected_failure" } }));
  assert.deepEqual([r.status, r.body.error, r.created], [500, "create_failed", false]);
  assert.ok(!JSON.stringify(r.body).includes("10.0.0.1"));
  assert.deepEqual(r.failure, { status: 500, code: "unexpected_failure" });
});

test("the sign-up handler refuses before any request, and the app has no passwordless sign-in", () => {
  const i = APP.indexOf('if (authMode === "signup") {');
  const check = APP.indexOf("signupPasswordProblem(password)", i);
  const firstRequest = Math.min(APP.indexOf("serverSignUp(email, password, profile)", i), APP.indexOf("sb.auth.signUp(", i));
  assert.ok(i > 0 && check > i && check < firstRequest, "password check precedes self-signup and auth.signUp");
  // The fallback still sends the password and keeps the confirmation e-mail.
  assert.match(APP, /sb\.auth\.signUp\(\{\s*email,\s*password,\s*options: \{ data: profile, emailRedirectTo:/);
  for (const m of ["signInWithOtp", "signInWithIdToken", "signInWithSSO", "signInAnonymously", "inviteUserByEmail", "magiclink"]) {
    assert.ok(!APP.includes(m), `app.js must not use ${m}`);
  }
  // Provider sign-in (Google / Apple / Microsoft, 2026-10-10) is the one
  // intentional exception: a single call, inside startOAuth(), reached only
  // from buttons for providers config.js oauthProviders lists (none by
  // default). Those accounts still wait for approval like any other.
  assert.equal(APP.split("signInWithOAuth(").length - 1, 1, "exactly one signInWithOAuth call");
  const oauthFn = APP.indexOf("async function startOAuth(");
  const oauthCall = APP.indexOf("signInWithOAuth(");
  assert.ok(oauthFn > 0 && oauthCall > oauthFn && oauthCall < APP.indexOf("\n}", oauthFn), "signInWithOAuth only inside startOAuth()");
  assert.match(APP, /const list = \(window\.TDW_CONFIG \|\| \{\}\)\.oauthProviders;/);
  // Recovery stays available; nothing logs a password.
  assert.match(APP, /resetPasswordForEmail\(/);
  assert.doesNotMatch(APP, /console\.\w+\([^)]*password/i);
});
