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

## Public sign-up, mandatory approval

Public sign-up is ON; automatic approval is OFF; admin approval is required.

1. **Sign up.** A visitor chooses "Need an account? Create one" on the normal sign-in page. The app calls Supabase Auth's own `signUp` with the profile details only. It never sends `approved` or `is_admin`.
2. **Pending.** The `on_auth_user_created` trigger (`handle_new_user()`) inserts the `profiles` row with `id` and `email` only, so `approved` and `is_admin` take their column defaults (`false`, `NOT NULL`). Any metadata a client sends is ignored.
   - If email confirmation is on, the visitor first confirms the address and then signs in.
   - The app reads the profile and shows **"Account created — awaiting approval"**, never the ledgers.
   - Row-level security returns no ledger row to an unapproved account: `properties` and `get_properties()` gate on `is_approved()`, and notes, favorites, hidden and bid list add a RESTRICTIVE `is_approved()` policy.
   - `/admin` sends a pending user to the application.
3. **Approve.** The admin signs in, then goes to account menu → **Admin area** (or opens `/admin`). The **Pending sign-ups** card lists every account with `approved = false`, by email and request date. **Approve** sets `approved = true` and `approved_at`.
   - This is the same query and update as the application's own admin panel.
   - Both are allowed by the server only for an admin (`profiles: admin full access`, on `is_admin()`).
   - There is no reject. An account the admin does not approve simply stays pending.
4. **Active.** The approved user signs in and uses the application normally. `is_admin` stays `false`, so `/admin` still refuses them.

A user cannot approve or promote themselves. `profiles` has no INSERT or UPDATE policy for non-admins, so such an update changes zero rows. Browser storage, URL parameters and window state are never read for approval or role.

**Manual Dashboard setting:** Supabase Dashboard → Authentication → Sign In / Providers → **Allow new users to sign up** must be ON. While it is off, every sign-up is refused with Supabase's "Signups not allowed for this instance". The app shows "New account registration is closed right now, so this account was not created" instead of that raw text. No code can change this setting. See `docs/production-configuration.md` section 2.

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
- The `signup*` checks run the whole lifecycle in one browser context, so that a sign-up in one tab is visible to the admin in another:
  - an anonymous visitor gets the sign-up form, and `/admin` refuses them;
  - sign-up leads to the pending screen, with the profile at `approved = false` and `is_admin = false`, and `/admin` refused;
  - self-promotion through the API changes 0 rows;
  - `is_admin` and `approved` sent in sign-up metadata are ignored;
  - storage and URL tampering leave the account pending;
  - the admin sees both pending accounts, and approving one changes 1 row;
  - the approved user reaches the ledgers, and `/admin` still refuses them;
  - "Signups not allowed for this instance" shows the clear message and creates no session.
- `tests/python/test_admin_area.py` `test_s0*` pins the following:
  - one approval mechanism;
  - sign-up sends no role;
  - the error mapping;
  - the documented Dashboard setting.
