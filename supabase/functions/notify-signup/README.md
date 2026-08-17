## New sign-up approval email

Emails you the moment someone creates an account, so you're not relying on remembering to check the app. Three pieces, all already in this repo:

- `schema-v6-approvals.sql` (repo root) — adds `profiles.approved`, and blocks every ledger table for accounts that aren't approved yet. **This is the part that actually gates access.**
- `supabase/functions/notify-signup/index.ts` — the Edge Function that emails you when a new `profiles` row shows up.
- The in-app "Pending sign-ups" admin panel — appears automatically once your own account is marked `is_admin = true` (the bootstrap step in schema-v6 does this for you) and someone is waiting.

The email piece below is **optional**. Sign-up approval works without it — you just have to notice the pending-approvals panel yourself next time you open the app. Set this up if you'd rather get pinged immediately.

I can't deploy the Edge Function myself — deploys need your Supabase CLI login, and email sending needs an API key only you should hold. Everything below is copy/paste.

### 1. Run the SQL

Supabase Dashboard → SQL Editor → New query → paste in `schema-v6-approvals.sql` from the repo root → Run. It only adds a table, a trigger, two helper functions, and access-narrowing policies; nothing existing is touched. It also approves + admins your own account (`rodzmodzllc@gmail.com`) in the same script, so you won't be locked out.

### 2. Get an email-sending API key

Same as `send-digest`: this function is written for [Resend](https://resend.com) (generous free tier, no domain verification needed if you send from their shared `onboarding@resend.dev` sender while testing). If you already set up `RESEND_API_KEY` for the digest function, reuse it here.

### 3. Deploy the function

From a machine with the Supabase CLI installed and logged in (`supabase login`), from the repo root:

```
supabase link --project-ref <your-project-ref>   # once, if not already linked
supabase functions deploy notify-signup
```

### 4. Set the function's secrets

```
supabase secrets set RESEND_API_KEY=re_your_key_here
supabase secrets set OWNER_EMAIL=rodzmodzllc@gmail.com
supabase secrets set NOTIFY_FROM_EMAIL="Tax Deed Watchlist <onboarding@resend.dev>"
supabase secrets set NOTIFY_WEBHOOK_SECRET=$(openssl rand -hex 20)   # optional but recommended, see step 5
```

`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are injected automatically for every Edge Function — you don't set those yourself.

### 5. Wire it to fire on every new sign-up

Dashboard → Database → Webhooks → Create a new webhook:

- Table: `public.profiles`
- Events: `Insert`
- Type: `HTTP Request`
- Method: `POST`
- URL: `https://<your-project-ref>.functions.supabase.co/notify-signup`
- HTTP Headers: add `X-Notify-Secret: <same value as NOTIFY_WEBHOOK_SECRET above>` (skip this header, and the secret in step 4, if you'd rather keep this simpler and rely on the URL being unguessable)

This is a database-level webhook (Dashboard → Database → Webhooks), not an Edge Function cron trigger — it fires on the INSERT itself instead of on a schedule.

### 6. Try it once by hand before trusting it

```
curl -X POST https://<your-project-ref>.functions.supabase.co/notify-signup \
  -H "X-Notify-Secret: <your NOTIFY_WEBHOOK_SECRET, if you set one>" \
  -H "Content-Type: application/json" \
  -d '{"type":"INSERT","table":"profiles","record":{"id":"00000000-0000-0000-0000-000000000000","email":"test@example.com","requested_at":"2026-01-01T00:00:00Z"}}'
```

Returns `{"skipped":true,...}` for that fake ID since it won't match a real row — that's expected, it just confirms the function is reachable and secret-checked correctly. Check `supabase functions logs notify-signup` if it doesn't behave as expected. To see a real email, sign up for a new account through the app's "Create one" toggle and watch your inbox.
