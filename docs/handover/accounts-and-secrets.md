# Accounts and secrets

Names only. No value of any secret appears in this repository's docs, and none
should be added. Where a value must be set, the column says where.

## External accounts

| Account | Used for | Where it is referenced |
|---|---|---|
| GitHub repository `rodzmodzllc-max/taxdeed-scraper` (public) | Code, Actions (harvest, CI, mirror), secrets and variables | `.github/workflows/` |
| Supabase project `cqnnnvpbocafuvpzfbzu` | Postgres, Auth, Storage (`property-photos` bucket), Edge Functions | root `config.js` `supabaseUrl`, workflows, `supabase/functions/` |
| Cloudflare Pages project serving `rodz-taxdeeds.pages.dev` | Static hosting of the repo root, branch previews | Git integration on the GitHub repo; `_headers` (CSP, cache) |
| Domain `taxacq.com` (registrar + DNS) | Custom domain for the app and e-mail | `docs/production-configuration.md` "Custom domain" |
| Resend (sending domain `taxacq.com`, sender `info@taxacq.com`) | Account e-mails from Edge Functions; Supabase Auth e-mails via custom SMTP | `supabase/functions/_shared/approval_notify_core.js`, `docs/auth-email.md` |
| MapTiler Cloud | Satellite basemap and static images | root `config.js` `maptilerKey` |
| Google Cloud (Maps) | Google basemap (admins only since `sw.js` v156); a Street View step that the permission register blocks | root `config.js` `googleMapsApiKey`; Actions secret `GOOGLE_MAPS_API_KEY` |
| ScraperAPI | Proxy fallback for three Florida LAFT counties when blocked directly | Actions secret `SCRAPERAPI_KEY` |
| Stripe | Billing. **Off**: `config.js` `billing.enabled: false`, migration 027 not applied | `supabase/functions/billing-*`, `stripe-webhook` |
| OAuth providers (Google / Apple / Microsoft) | Optional sign-in. **None enabled**: `config.js` `oauthProviders: []` | `docs/social-sign-in.md` |

## GitHub Actions secrets and variables

Found by searching `.github/workflows/*.yml` for `secrets.` and `vars.`.

| Name | Kind | Used by | Breaks without it | Rotate |
|---|---|---|---|---|
| `SUPABASE_URL` | secret | every job that reads or writes Supabase (harvest-and-sync, source-link-check, parcel-boundaries-*, geocode-dry-run, probe-fdor-starvation, backfill-fdor-phase52) | every sync and enrichment step | Only changes if the project moves. Update the secret. |
| `SUPABASE_SERVICE_KEY` | secret | same jobs | same; this key bypasses RLS, so treat as the most sensitive secret | Supabase dashboard -> Project Settings -> API keys: create a new secret key, update the secret, run one job, then revoke the old key. |
| `SCRAPERAPI_KEY` | secret | `laft` job (`harvest_laft_html.py`) | the proxy fallback only; the counties it covers read as failed when directly blocked | Regenerate in ScraperAPI, update the secret. Whether to keep using it is open (pre-sale blocker 4). |
| `GOOGLE_MAPS_API_KEY` | secret | `deeds` job, Street View photo step (`scripts/fetch_property_photos.py`) | nothing; Street View is `BLOCKED` in `data/source_permissions.csv`, so the step is inert even with the key. Not needed while that block stands. | Google Cloud Console -> Credentials. |
| `ARTIFACT_PRIVATE_KEY` | secret | `backfill-fdor-phase52.yml` apply mode only | that apply mode stops | Generate a new OpenPGP key pair; see `docs/production-configuration.md` section 5. |
| `ARTIFACT_PUBLIC_KEY` | variable | harvest jobs that upload artifacts | raw harvests and backups are not kept anywhere (only value-free evidence is uploaded) | Replace with the new public key; keep the private key offline. |
| `AUCTION_OFFLIST_CLOSE` | variable | `deeds` job | nothing; unset means ON. `'0'` makes the off-list close-out plan-only | - |
| `GITHUB_TOKEN` | automatic | schedule watchdog, schedule guard, mirror push | provided by GitHub; nothing to set | - |

## Supabase Edge Function secrets

Found by searching `supabase/functions/` for `Deno.env.get(...)`. Set in
Supabase dashboard -> Edge Functions -> Secrets.

| Name | Functions | Breaks without it | Rotate |
|---|---|---|---|
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | all except billing-checkout / billing-portal (which read them through `_shared/billing_http.ts`) | everything; provided by Supabase automatically | rotates with the project's secret key |
| `RESEND_API_KEY` | self-signup, notify-approval, notify-signup, send-digest | approval and new-sign-up e-mails are not sent (accounts are still created and approved) | Resend dashboard -> API keys: create, update the secret, revoke the old one. Use a separate key for Supabase Auth SMTP so each can be revoked alone. |
| `OWNER_EMAIL`, `NOTIFY_FROM_EMAIL`, `NOTIFY_WEBHOOK_SECRET` | notify-signup (older, webhook-driven alert) | that alert; the newer outbox alert (migration 030) uses a fixed address in code | change the values; the webhook secret must match the database webhook header |
| `DIGEST_FROM_EMAIL`, `DIGEST_DAYS`, `DIGEST_CRON_SECRET` | send-digest | the digest. It is **not deployed** (pre-sale blocker 13) | - |
| `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`, `APP_URL` (optional) | billing-checkout, billing-portal, stripe-webhook | billing (off today) | Stripe dashboard; see `docs/production-configuration.md` section 11 |

Which functions are actually deployed is visible only in the Supabase
dashboard (Edge Functions). The repository records `self-signup` as deployed;
`notify-approval` was written and not deployed as of its README
(`supabase/functions/notify-approval/README.md`). Check before relying on either.

## Client-side settings in root `config.js`

`config.js` lives only at the repo root, ships to every browser, and is not
mirrored from `public/`. Its keys are **client-side keys**: they are public by
design and are only as safe as the restrictions set in each provider's console.

| Field | What it is | Restriction to check |
|---|---|---|
| `supabaseUrl`, `supabasePublishableKey` | Supabase publishable key; RLS enforces access | none needed beyond RLS. The service-role key must never appear here. |
| `googleMapsApiKey` | A Google Maps **Demo Key** (testing-only per Google) | HTTP referrers + Maps JavaScript API only; not yet done (see known-limitations) |
| `maptilerKey` | MapTiler key | "Allowed HTTP Origins" in MapTiler Cloud. The file's comment says it is restricted to `rodz-taxdeeds.pages.dev`; `taxacq.com` must be on the list too. |
| `supportEmail` | Support mailbox shown to users | - |
| `legal.*` (`operatorName`, `governingLaw`, `effectiveDate`, `contactEmail`) | Shown on the legal pages; blank today, so the pages say "not configured" | - |
| `billing.*` | Billing switch and plan display; `enabled: false` | - |
| `oauthProviders` | Social sign-in buttons; empty | - |
| `publicationMode` | `"preview"` today: testers see sources awaiting review, labelled | set to `"enforced"` before selling (see known-limitations) |
| `availableGate`, `defaultLook` | Product switches (`"off"`, `"merged"`) | - |

## Dashboard-only settings (not in the repository)

- Supabase Auth: Site URL, Redirect URLs allowlist, custom SMTP (Resend),
  e-mail templates, OAuth providers. Exact values: `docs/production-configuration.md`
  section 2 and `docs/auth-email.md`.
- Resend: domain verification DNS records for `taxacq.com`.
- Cloudflare Pages: production branch (`main`, per CLAUDE.md), custom domain,
  build settings (the repository has no build step; the site is the repo root).
  Verify in the Cloudflare dashboard.
- Local development only: `sync-config.local.json` (gitignored) may hold a
  service-role key for manual runs. Never commit it.
