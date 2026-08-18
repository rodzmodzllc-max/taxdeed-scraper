# Approval-confirmation email

Emails the user the moment you approve their account, so they don't have to remember to check back and try signing in again. Companion to `notify-signup` (which emails *you* when someone new signs up) — this one closes the loop back to *them* once you approve that sign-up.

- `schema-v6-approvals.sql` (repo root) — already adds `profiles.approved`; this function just reacts to that flag flipping to `true`, it doesn't change the gate itself.
- `supabase/functions/notify-approval/index.ts` — the Edge Function that emails the user once their `profiles` row is approved.

The email piece below is optional. Approving someone from the in-app "Pending sign-ups" panel or the Supabase table editor works fine without it — they just won't get a heads-up and will need to try signing in again on their own to discover they're in.

I can't deploy the Edge Function myself — deploys need your Supabase CLI login, and email sending needs an API key only you should hold. Everything below is copy/paste.

## 1. Confirm schema-v6-approvals.sql has already been run

If you already set up `notify-signup`, this is done. If not: Supabase Dashboard → SQL Editor → New query → paste in `schema-v6-approvals.sql` from the repo root → Run.

## 2. Reuse (or get) an email-sending API key

Same as `notify-signup` and `send-digest`: this function is written for Resend. If you already set `RESEND_API_KEY` and `NOTIFY_FROM_EMAIL` for either of those, reuse them here — no new key needed.

## 3. Deploy the function

From a machine with the Supabase CLI installed and logged in (`supabase login`), from the repo root:

```
supabase link --project-ref <your-project-ref>   # once, if not already linked
supabase functions deploy notify-approval
```

## 4. Set the function's secrets

```
supabase secrets set RESEND_API_KEY=re_your_key_here          # skip if already set for notify-signup
supabase secrets set NOTIFY_FROM_EMAIL="Tax Deed Watchlist <onboarding@resend.dev>"   # skip if already set
supabase secrets set NOTIFY_WEBHOOK_SECRET=$(openssl rand -hex 20)   # optional; reuse notify-signup's value if you set one there
supabase secrets set APP_URL=https://your-app-url.example.com   # optional - adds a sign-in link to the email
```

`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are injected automatically for every Edge Function — you don't set those yourself. Secrets are shared across all functions in a project, so if you already set `RESEND_API_KEY` / `NOTIFY_FROM_EMAIL` / `NOTIFY_WEBHOOK_SECRET` for `notify-signup`, this function picks up the same values automatically — you don't need to set them twice.

## 5. Wire it to fire on every approval

Dashboard → Database → Webhooks → Create a new webhook:

- Table: `public.profiles`
- Events: **Update**
- Type: HTTP Request
- Method: POST
- URL: `https://<your-project-ref>.functions.supabase.co/notify-approval`
- HTTP Headers: add `X-Notify-Secret: <same value as NOTIFY_WEBHOOK_SECRET above>` (skip this header, and the secret in step 4, if you'd rather keep this simpler and rely on the URL being unguessable)

This is a database-level webhook (Dashboard → Database → Webhooks), not an Edge Function cron trigger — it fires on the UPDATE itself instead of on a schedule. The function only sends an email when `approved` actually flips from `false` to `true` (so later edits, like toggling `is_admin`, won't re-trigger it).

## 6. Try it once by hand before trusting it

```
curl -X POST https://<your-project-ref>.functions.supabase.co/notify-approval \
  -H "X-Notify-Secret: <your NOTIFY_WEBHOOK_SECRET, if you set one>" \
  -H "Content-Type: application/json" \
  -d '{"type":"UPDATE","table":"profiles","record":{"id":"00000000-0000-0000-0000-000000000000","email":"test@example.com","approved":true,"approved_at":"2026-01-01T00:00:00Z"},"old_record":{"id":"00000000-0000-0000-0000-000000000000","email":"test@example.com","approved":false}}'
```

Returns `{"skipped":true,...}` for that fake ID since it won't match a real row — that's expected, it just confirms the function is reachable and secret-checked correctly. Check `supabase functions logs notify-approval` if it doesn't behave as expected. To see a real email, approve a real pending sign-up from the admin panel and watch that person's inbox.
