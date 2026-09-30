# Admin area (`/admin`) - 2026-09-30

## Architecture

- **Authentication:** the app's existing **Supabase Auth**, which uses email + password. Supabase stores and checks the password as a hash. No second authentication system exists, and no page compares a password.
- **Admin role:** the existing server-side role.
  - It is `public.profiles.is_admin`, read through `public.is_admin()` (SECURITY DEFINER) by the row-level-security policies.
  - A signed-in user can only **read their own** profile row (`profiles: read own row`).
  - Only an existing admin can write any profile (`profiles: admin full access`).
  - Every admin operation is already enforced by RLS on `is_admin()`: sign-up approvals (`profiles`) and source publication reviews (`source_publication_reviews`).
- **Route:** `public/admin.html` + `public/admin.js`, served at `/admin` by Cloudflare Pages.
  - The page asks the server for the signed-in user's own `is_admin`, using the signed session token under RLS.
  - It shows the shell only when that answer is `true`.
  - No session, a normal user, or any error sends the visitor to `index.html`, the normal sign-in and application.
  - Browser storage, cookies and window state are never read for the role, so editing them grants nothing.
- **Identity:** the shell says **Admin**. No email address is shown.
- The account menu in the application shows an "Admin area" link only when the server-read profile says admin. This is visibility only: `/admin` checks the server again.
- **No migration was needed.** The role column, the `is_admin()` function and the policies already existed.

## Setting up the Admin account (owner, one time)

Supabase Auth signs people in by **email**, not by username. The Admin identity is therefore a Supabase user with an email address the owner controls, displayed in the app as "Admin". A Gmail plus-address (e.g. `rodzmodzllc+admin@gmail.com`) is a real, deliverable address.

1. **Create the user.** In Supabase Dashboard, go to **Authentication → Users → Add user → Create new user**. Enter the admin email and the admin password, and tick **Auto Confirm User**. The password is typed only there. It never enters this repository, CI or a chat.
2. **Grant the role.** Using the SQL editor or a maintainer:
   `update public.profiles set approved = true, is_admin = true where email = '<the admin email>';`
   The profile row is created automatically by the `handle_new_user` trigger.
3. **Verify.** Sign in with that email at the normal sign-in, open the account menu, then **Admin area**. The optional live check (below) confirms the same from the command line.
4. **Demote the owner's personal account, and only after step 3 succeeds.**
   `update public.profiles set is_admin = false where email = 'rodzmodzllc@gmail.com';`
   Nothing else on that account changes: `approved` stays true, and favorites, notes and watchlist are untouched.

## Optional live check

`scripts/admin_auth_smoke.py` reads `ADMIN_EMAIL` / `ADMIN_PASSWORD`, and optionally `NORMAL_EMAIL` / `NORMAL_PASSWORD`, from the environment (see `.env.example`, names only). It then checks against the real project:

- the admin authenticates;
- the server says `is_admin = true`;
- a wrong password is rejected;
- the normal account says `is_admin = false`.

It prints PASS / FAIL lines only and never an address, password or token.

## Tests

- `tests/python/test_admin_area.py` covers:
  - the page decides from the server only;
  - the shell is hidden until verified;
  - wiring;
  - `.env.example` holds names only;
  - no committed credential. When `ADMIN_PASSWORD` is set locally, its value is searched for in every tracked file.
- `tests/run_test.mjs` (`admin*` checks) uses the stub's `?stubauth=1` model of Supabase Auth and RLS: a server-held user table, a password check, a session, and own-row profile reads. It covers:
  - a normal sign-in;
  - a normal user refused at `/admin`;
  - storage tampering refused;
  - bad credentials rejected;
  - admin sign-in and shell;
  - "Admin" identity with no email;
  - sign-out removing access.
