// Sign-up password rule (2026-10-09): a TAXACQ account is a password account.
// node --test tests/billing/signup_password.test.mjs  (no network)
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import { signupPasswordProblem, MIN_SIGNUP_PASSWORD, MAX_SIGNUP_PASSWORD } from "../../supabase/functions/_shared/signup_password.js";

const read = (p) => readFileSync(new URL("../../" + p, import.meta.url), "utf8");
const APP = read("public/app.js");
const FN = read("supabase/functions/self-signup/index.ts");

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
  assert.match(FN, /import \{ signupPasswordProblem \} from "\.\.\/_shared\/signup_password\.js";/);
  assert.match(FN, /const pwProblem = signupPasswordProblem\(password\);\s*\n\s*if \(pwProblem\) return reply\(400, pwProblem, origin\);/);
  assert.doesNotMatch(FN, /String\(body\.password/);
  // Order: the rule runs before the account is created.
  assert.ok(FN.indexOf("signupPasswordProblem(password)") < FN.indexOf("auth.admin.createUser"));
  // The account is a password account; the caller cannot set approval.
  assert.match(FN, /createUser\(\{ email, password, email_confirm: true, user_metadata: meta \}\)/);
});

test("the sign-up handler refuses before any request, and the app has no passwordless sign-in", () => {
  const i = APP.indexOf('if (authMode === "signup") {');
  const check = APP.indexOf("signupPasswordProblem(password)", i);
  const firstRequest = Math.min(APP.indexOf("serverSignUp(email, password, profile)", i), APP.indexOf("sb.auth.signUp(", i));
  assert.ok(i > 0 && check > i && check < firstRequest, "password check precedes self-signup and auth.signUp");
  // The fallback still sends the password and keeps the confirmation e-mail.
  assert.match(APP, /sb\.auth\.signUp\(\{\s*email,\s*password,\s*options: \{ data: profile, emailRedirectTo:/);
  for (const m of ["signInWithOtp", "signInWithOAuth", "signInWithIdToken", "signInWithSSO", "signInAnonymously", "inviteUserByEmail", "magiclink"]) {
    assert.ok(!APP.includes(m), `app.js must not use ${m}`);
  }
  // Recovery stays available; nothing logs a password.
  assert.match(APP, /resetPasswordForEmail\(/);
  assert.doesNotMatch(APP, /console\.\w+\([^)]*password/i);
});
