# Account e-mails (`notify-approval`)

One outbox (migration 030, `public.account_notifications`), one processor, two kinds:

| Kind | Queued by | Sent to | Subject |
|---|---|---|---|
| `account_approved` | trigger on `profiles.approved` false → true | the approved person (`profiles.email`) | "Your TAXACQ account has been approved" |
| `admin_new_signup` | trigger on `profiles` INSERT (a committed `auth.users` row) | `info@taxacq.com` only, a constant in `_shared/approval_notify_core.js` (`SIGNUP_ALERT`) | "New TAXACQ account created" |

Password-reset e-mails are not part of this: Supabase Auth sends them.

The operator alert lists the sign-up time (UTC), the account e-mail, the email-confirmation status and the approval status, all read from `auth.users` / `profiles` when the alert is sent. It links to `https://taxacq.com/admin.html#pending`, the admin page's "Pending sign-ups" section.
- A failed sign-up creates no account, so nothing is queued.
- `unique (user_id, kind)` means one alert per account, ever.
- A failure to queue is caught (a WARNING), so it never blocks account creation.
- `self-signup` sends due rows right after it creates an account, using `EdgeRuntime.waitUntil` so the response is not delayed. Retries happen on any later sweep.

## Account-approval e-mail

Sends **"Your TAXACQ account has been approved"** once, to the approved person's own address, after an administrator approves them.

**Status (2026-10-09): written and tested, NOT live.** Migration 030 is not applied and this function is not deployed. Until both happen, approving works exactly as before and no e-mail is sent.

## How approval works (traced)

1. Sign-up (`self-signup` function, or `auth.signUp`) creates `auth.users`; `handle_new_user()` inserts `public.profiles` with `approved = false`.
2. The app gates entry on `profiles.approved` (`checkApprovalAndEnter()` in `app.js`; `is_approved()` in RLS).
3. An administrator clicks **Approve**, either in the app's pending list (`app.js`) or on `/admin` (`admin.js`).
   - The click runs `UPDATE profiles SET approved = true, approved_at = now()` with the admin's own session.
   - RLS allows it only through `"profiles: admin full access"` (`is_admin()`).
   - Users can only read their own row, so nobody can approve themselves.

## How the e-mail is sent

| Step | Where | Guarantee |
|---|---|---|
| Queue | Migration 030 trigger on `profiles`, `approved` false → true, same transaction | No approval, no row. One row per account for ever (`unique (user_id, kind)`): re-approving, editing, or two admins clicking at once never queues a second one. Accounts approved before 030 get nothing. |
| Trigger | `app.js` / `admin.js` call this function after a successful approve (fire-and-forget); `/admin` also calls it on load as a retry sweep | Never blocks or undoes the approval. The request has no body and names no recipient. |
| Authorize | This function | Admin JWT (checked against `profiles.is_admin`), or the service-role key. Anything else is refused with 401/403. |
| Claim | `claim_account_notifications()` (service role only) | `FOR UPDATE SKIP LOCKED` and a 5-minute lease mean concurrent senders never take the same row. The address comes from `profiles`, never from the caller. |
| Send | Resend, `Idempotency-Key: account_approved/<row id>` | A retry after a lost response is the same delivery. |
| Record | `finish_account_notification()` | Outcome is `sent` (provider message id) or `failed` (short code such as `HTTP_503` or `NETWORK`, back-off 5 min → 12 h, at most 8 attempts) or `skipped` (approval revoked, no valid address). A stale attempt cannot overwrite a newer one. |
| Monitor / retry | `/admin` pending card | Shows how many approval e-mails are waiting or failed (counts only). `requeue_account_notification(id)` is admin-only and resets a failed row; a sent row is never re-queued. |

The content is in `_shared/approval_notify_core.js` (`renderApprovalEmail`), as HTML plus plain text:
- **From:** `TAXACQ <info@taxacq.com>`; **reply-to:** `info@taxacq.com`.
- **Button:** "Access TAXACQ", linking to `https://taxacq.com`.
- **Footer:** the mailing address.

The e-mail says the account is approved. It makes no claim about a subscription or paid access.

Logs carry counts and codes only: never an address, a body or a key.

## To activate (owner)

1. Apply `scripts/migrations/030_account_approval_notifications.sql`.
2. `supabase functions deploy notify-approval`. Keep JWT verification on, which is the default.
3. Secret `RESEND_API_KEY`: the existing key, with `taxacq.com` verified in Resend. Nothing else is needed; the sender and reply-to are fixed in code.
4. Redeploy `self-signup` (it now sends the new-sign-up alert and enforces the shared password rule).
5. Optional: point a scheduled job at this function with the service-role key, so retries happen even when no admin opens `/admin`.

Test delivery only to a designated test account: approve it from `/admin`, then read `account_notifications` (as an admin) for its status.

Tests:
- `tests/billing/approval_notify.test.mjs`: content, authorization, idempotency, retries, mocked Resend, and the operator alert (fixed recipient, one per account, escaping, retry).
- `tests/python/test_migration_030_approval_notifications.py`: trigger, RLS and claim/finish, run against PostgreSQL.
