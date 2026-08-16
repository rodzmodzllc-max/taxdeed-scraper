# Auction-closing-soon email digest

Emails each signed-in user a summary of their **favorited** auctions whose
sale date falls in the next N days (7 by default). Two pieces, both already
in this repo:

- `schema-v5-digest.sql` (repo root) - one Postgres function, `digest_candidates()`.
- `supabase/functions/send-digest/index.ts` - the Edge Function that calls it and sends the emails.

I can't deploy either of these myself - Edge Function deploys need your
Supabase CLI login, and email sending needs an API key only you should hold.
Everything below is copy/paste.

## 1. Run the SQL

Supabase Dashboard -> SQL Editor -> New query -> paste in `schema-v5-digest.sql`
from the repo root -> Run. It only adds one function; nothing existing is touched.

## 2. Get an email-sending API key

The function is written for [Resend](https://resend.com) (generous free
tier, dead-simple API, no domain verification needed if you send from
their shared `onboarding@resend.dev` sender while testing). Sign up, grab
an API key from the dashboard. If you'd rather use SendGrid, Postmark, SES,
or something else, everything in `index.ts` except the `sendEmail()`
function stays the same - swap that one function's `fetch()` call for your
provider's API.

## 3. Deploy the function

From a machine with the [Supabase CLI](https://supabase.com/docs/guides/cli)
installed and logged in (`supabase login`), from the repo root:

```bash
supabase link --project-ref <your-project-ref>   # once, if not already linked
supabase functions deploy send-digest
```

## 4. Set the function's secrets

```bash
supabase secrets set RESEND_API_KEY=re_your_key_here
supabase secrets set DIGEST_FROM_EMAIL="Tax Deed Watchlist <onboarding@resend.dev>"
supabase secrets set DIGEST_DAYS=7                      # optional, 7 is the default
supabase secrets set DIGEST_CRON_SECRET=$(openssl rand -hex 20)   # optional but recommended, see step 5
```

`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are injected automatically by
Supabase for every Edge Function - you don't set those yourself.

## 5. Schedule it

Easiest path, no SQL required: **Dashboard -> Edge Functions -> send-digest
-> Triggers -> Add cron trigger**, e.g. `0 13 * * *` for 1pm UTC daily (pick
whatever hour works for the timezone your household actually checks email
in). Supabase's own scheduler calls the function on that schedule.

If your project's dashboard doesn't have that Triggers tab yet, the
equivalent via `pg_cron` + `pg_net` (Database -> Extensions -> enable both,
then SQL Editor):

```sql
select cron.schedule(
  'send-digest-daily',
  '0 13 * * *',
  $$
  select net.http_post(
    url := 'https://<your-project-ref>.functions.supabase.co/send-digest',
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'X-Digest-Secret', '<same value as DIGEST_CRON_SECRET above>'
    )
  );
  $$
);
```

The `X-Digest-Secret` header (and `DIGEST_CRON_SECRET` from step 4) are
optional but close off the function's public URL from being invoked by
anyone who finds it - skip both if you'd rather keep this simpler and rely
on the URL being unguessable.

## 6. Try it once by hand before trusting the schedule

```bash
curl -X POST https://<your-project-ref>.functions.supabase.co/send-digest \
  -H "X-Digest-Secret: <your DIGEST_CRON_SECRET, if you set one>"
```

Returns `{"sent":0,"users":0,"reason":"no candidates"}` if nobody has a
favorite closing in the next `DIGEST_DAYS` days - favorite something with a
near-term sale date first if you want to see an actual email land. Check
`supabase functions logs send-digest` if it doesn't behave as expected.
