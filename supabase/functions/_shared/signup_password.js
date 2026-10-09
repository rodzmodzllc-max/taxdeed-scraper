// supabase/functions/_shared/signup_password.js
//
// The sign-up password rule, in one place (2026-10-09). TAXACQ accounts are
// password accounts: the self-signup function creates them with the admin API
// and the browser signs in with that same password right away. A missing,
// empty or whitespace-only password is refused, as is anything outside
// Supabase Auth's 8..72 character window. public/app.js applies the same
// rule before any request (signupPasswordProblem); this module is what the
// server enforces, so a request that skips the form is refused too.
//
// Returns null when the password is acceptable, else { error, message }.
// Never echoes the password.
export const MIN_SIGNUP_PASSWORD = 8;
export const MAX_SIGNUP_PASSWORD = 72;

export function signupPasswordProblem(password) {
  if (typeof password !== "string" || password.trim() === "") {
    return { error: "missing_password", message: "Enter a password for your new account." };
  }
  if (password.length < MIN_SIGNUP_PASSWORD) {
    return { error: "weak_password", message: "Please choose a password of at least 8 characters." };
  }
  if (password.length > MAX_SIGNUP_PASSWORD) {
    return { error: "weak_password", message: "Please choose a password of at most 72 characters." };
  }
  return null;
}
