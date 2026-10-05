# Production configuration (settings that live outside this repository)

Everything in this file is configuration a person sets in a dashboard, a
repository setting or `config.js` - not code. The code in this repository
is written so that each item degrades honestly when it is missing (the
feature says it is not set up; nothing pretends to work), and this file is
the checklist for turning each one on. Dated 2026-09-29 (SaaS launch-
readiness hardening PR).

Nothing here is applied by CI or by an assistant session. Each item names
who can do it and where.

## 1. Database migrations in this PR (apply by hand, in order)

| File | What it does | Depends on |
|---|---|---|
| `scripts/migrations/015_customer_write_privileges_and_account_deletion.sql` | Approved customers can read shared `properties` / `county_calendar` but no longer INSERT/UPDATE/DELETE/TRUNCATE them (only `service_role` writes). Closes anon's grants on every customer table and the nine legacy tables the app never reads. Pins `search_path` on eight functions, revokes client EXECUTE on the two SECURITY DEFINER trigger functions, and adds `public.delete_my_account()`. | 005/005a/013 already live (they are) |
| `scripts/migrations/016_source_health.sql` | Adds `public.source_health` (one row per dataset, written by `scripts/source_health.py`, approved read). | nothing |
| `scripts/migrations/017_otc_inventory_provenance_lifecycle.sql` (2026-09-29, FL LAFT reliability + TX OTC foundation PR) | Adds the nullable OTC columns to `properties` - `inventory_type`, `source_authority`, `source_id`, `list_url` / `document_url` / `purchase_url` (+kind), `purchase_amount` + `purchase_amount_kind`, `first_seen_at` / `last_seen_at` / `delisted_at`, `source_published_at`, `list_as_of`, document hash/ETag/Last-Modified, `otc_provenance` - with check constraints, re-creates `get_properties()` with the customer-facing ones appended, and backfills deterministically (FL laft by county from `data/county_source_registry.csv`; TX by `harvester_source`; unresolved LGBS rows stay NULL). See `docs/otc-inventory-model.md`. | 006, 013 (015 in either order - 017 re-pins `search_path`) |
| `scripts/migrations/018_county_source_registry.sql` (same PR) | Adds `public.county_source_registry` (empty; the content is `data/county_source_registry.csv`, loaded later via `county_source_registry.to_db_rows()`), approved read, `service_role` write. | nothing |
| `scripts/migrations/019_laft_list_dates.sql` (2026-09-29, OTC/LAFT enrichment PR) | Adds `escheatment_date` / `available_date` (nullable dates the county Lands Available list publishes), re-creates `get_properties()` with them appended. No backfill: `scripts/laft_lifecycle.py` probes for the columns and writes them fill-blank from the next laft run's harvest. Until applied, the lifecycle logs a notice and skips them. | 017 |
| `scripts/migrations/020_state_extensible_vocabulary.sql` (2026-09-29, Alabama onboarding foundation PR) | Widens `properties`' inventory-type and purchase-amount-kind check constraints with `POST_SALE` / `STATE_HELD_TAX_LAND` / `ADJUDICATED_PROPERTY` and `QUOTED_ON_APPLICATION` (an amount-less kind); widens `county_source_registry`'s state check to any two-letter code and adds `publishing_unit` (default COUNTY), `publishing_unit_name`, `amount_kind`, `update_frequency`, `source_terminology`, allows `CSV` as a machine format and (2026-09-30, three ledgers) adds `ledgers` ("|"-joined AUCTIONS / AVAILABLE / LIENS_CERTIFICATES - which customer ledger(s) the source feeds). Inserts and changes nothing. **APPLIED to production 2026-09-30** (state-expansion sprint, with the owner's Louisiana publication decision); the storable sets in `harvesters/otc/model.py` / `county_source_registry.py` now include the 020 values. Not a prerequisite for anything FL or TX does. | 017, 018 |
| `scripts/migrations/021_inventory_status_provenance_freshness.sql` (2026-09-30, production-readiness PR) | Adds `properties.inventory_status` / `inventory_status_raw` / `inventory_status_basis` / `inventory_status_observed_at` (the normalized lifecycle state - sold / redeemed / withdrawn / cancelled / struck_off only from a status the source published, plus the four Liens & Certificates values `certificate_listed` / `certificate_redeemed` / `certificate_assigned` / `certificate_expired` added 2026-09-30, the last three likewise only from a source column; written by `scripts/inventory_status_writer.py`, which probes for the columns), the append-only `public.inventory_status_observations` (approved read, service-role insert), the five per-unit freshness columns on `county_source_registry` (written by `scripts/unit_freshness.py`, probed), and re-creates `get_properties()` from 019's exact list with six columns APPENDED: the four status columns plus `field_provenance` and `otc_provenance` (never projected before). Existing columns keep order and semantics; search_path re-pinned; grants restated. Until applied every writer plans only and the frontend omits the new rows. | 018, 019 |
| `scripts/migrations/022_available_publication_gate.sql` (2026-09-30, AVAILABLE commercialization PR) | Adds `county_source_registry.publication_status` (APPROVED / APPROVED_GRANDFATHERED / UNREVIEWED / RESTRICTED / BLOCKED, default UNREVIEWED) + `restrictions`, `properties.publication_status` (the SOURCE's decision, propagated by `scripts/publication_gate.py`; NULL = not yet classified), `inventory_status_observations.transition` (newly_observed / status_changed / removed / result_published), and re-creates `get_properties()` from 021's exact list with `publication_status` APPENDED; search_path re-pinned; grants restated. RLS unchanged - withholding restricted inventory from the customer Available ledger is done by the frontend from the column. Until applied the gate script reports and plans only, the writer omits `transition`, and the frontend treats every row as it does today. **Required before restricted inventory can be withheld in production** - the only new functionality that needs it. | 018, 021 |
| `scripts/migrations/023_available_commercial_release.sql` (2026-09-30, AVAILABLE commercial release PR) | Adds `properties.purchase_path_type` (ten evidence-backed types from `scripts/purchase_path_engine.py`; NULL = not yet evaluated) + `purchase_path_scope` (property / source) + `purchase_path_evidence` + `purchase_path_observed_on`, with check constraints that a stored type always names its evidence and only the four URL types carry `purchase_url`; `properties.result_amount` / `result_date` / `result_party` (a result the SOURCE published, written only through an enabled rule in `data/outcome_column_rules.csv` - none enabled); the same three result columns and the `reactivated` transition on `inventory_status_observations`; the append-only `public.source_publication_reviews` (admins read / insert via `is_admin()`, service_role reads, customers nothing - the admin publication panel writes it, `scripts/publication_gate.py` applies the latest VALID decision per source); and re-creates `get_properties()` from 022's exact list with the seven property columns APPENDED; search_path re-pinned; grants restated. Nothing backfilled. Until applied the lifecycle, the writer and the gate probe and skip the new columns, and the frontend shows "not yet evaluated" / "history unavailable" states. **Applied to production 2026-09-30 with the owner's sprint authorization** (Supabase migration name `023_available_commercial_release`). | 021, 022 |

All four are wrapped in `begin; ... commit;`. **None of them is applied.**
`scripts/laft_lifecycle.py` (the `laft` job's last step) probes for 017's
columns each run and, until they exist, writes `status` only and prints a
notice - so the workflow works before or after 017. Read each file's header before
running it: 015 lists the exact `pg_policies` state it expects. The
frontend and the workflows in this PR work before or after either
migration - `delete_my_account()` missing shows "not available on this
deployment yet", a missing `source_health` table shows "not recorded yet".

Verification after 015 (as an approved customer via the REST API):
`POST /rest/v1/properties` returns 42501; `GET /rest/v1/rpc/get_properties`
still returns rows; favorites/hidden/bid_list/notes still insert and delete
own rows; `POST /rest/v1/rpc/delete_my_account` on a throwaway account
removes it. As `service_role`: the next scheduled sync upserts normally.

## 2. Supabase Auth settings (dashboard: Authentication)

- **Site URL** = `https://rodz-taxdeeds.pages.dev`.
- **Redirect URLs** must include `https://rodz-taxdeeds.pages.dev/index.html`
  and `https://rodz-taxdeeds.pages.dev/tx.html` (and the bare origin). The
  password-reset e-mail links back to whichever page the request came from
  (`resetPasswordForEmail(..., { redirectTo: location.origin + location.pathname })`);
  a URL not on this list is refused by Supabase and the reset silently
  lands on the Site URL instead.
- **Email templates -> Reset password**: the default template is fine. The
  app handles the `PASSWORD_RECOVERY` event by opening a "Set a new password"
  form; the link must be opened in a browser, not in an app that strips the
  URL fragment.
- **Leaked password protection** (Authentication -> Providers -> Email ->
  "Prevent use of leaked passwords"): currently OFF (security advisor,
  2026-09-29). Turn it on. No code change.
- **Email confirmation** is on (all three existing users are confirmed).
  Keep it on for a paid product.
- **Auth e-mail sender (blocks sign-up until fixed, 2026-10-04).** The
  project uses Supabase's built-in e-mail service. Supabase limits it to a
  couple of auth e-mails per hour for the whole project, and it is meant for
  testing only.
  - **What happened.** During investor testing on 2026-10-04, an existing
    unconfirmed user signed up twice (21:29 and 21:31 UTC). Both attempts
    sent confirmation e-mails, which used up the hour's quota. A new
    investor's sign-ups at 22:11 and 22:14 then failed with `429 email rate
    limit exceeded`, and no account was created.
  - **What the app does now.** It says this plainly and keeps the form (see
    `signUpErrorText()`), but only configuration removes the limit:
    1. Authentication -> Emails -> **SMTP Settings** -> enable custom SMTP
       with a transactional provider. Resend, SendGrid, Postmark and Amazon
       SES all have free or low tiers. Use a sender on a domain you control,
       with SPF/DKIM set.
    2. Then Authentication -> **Rate Limits** -> raise "Rate limit for
       sending emails". Supabase only allows changing it once custom SMTP is
       on.
  - **Interim option** (owner's decision). Turning "Confirm email" off sends
    no e-mail at sign-up, so sign-up never hits the limit. Every account
    still waits for admin approval (`profiles.approved`) before it sees any
    data. The trade-off is that nobody verifies the address belongs to the
    person.
  - **Resolution chosen by the owner (2026-10-04): server-side sign-up.**
    The `self-signup` Edge Function (`supabase/functions/self-signup`,
    deployed with `verify_jwt` off) creates the account through the admin
    API, already confirmed, and sends no e-mail, so the hourly limit no
    longer applies to sign-up. The app signs the new user in, and they land
    on the pending-approval screen. Access is unchanged: `handle_new_user`
    creates the profile with `approved = false`, and nothing the caller sends
    can change that.
    - The function protects itself with an origin allowlist
      (`*.rodz-taxdeeds.pages.dev`), input validation, a 4 KB body cap, a
      honeypot field and a best-effort per-IP limit.
    - Trade-off: the address is not verified. Admin approval is the gate.
    - If the function cannot be reached, the app falls back to
      `auth.signUp`, which sends an e-mail.
    - CI (`playwright-test.yml` `deployed-login`, run by
      `scripts/check_self_signup.py`) checks the deployed function with
      refused payloads only.
    - Password reset and "Resend confirmation" still send e-mail, so custom
      SMTP is still worth configuring.
  - **Redirect URLs.** The confirmation link now returns to the page the
    visitor signed up on (`emailRedirectTo`). Every state page
    (`/<state>.html`) belongs on the Redirect URLs list; a URL not on the
    list falls back to the Site URL.
- **Public sign-up** (Authentication -> Sign In / Providers ->
  "Allow new users to sign up"): must be **ON** for visitors to create accounts. When it
  is off, Supabase refuses every sign-up with "Signups not allowed for this
  instance" (the app now says "New account registration is closed right
  now" instead). Turning it on does NOT let anyone in: every new account's
  `profiles` row is created by the `handle_new_user` trigger with
  `approved = false` and `is_admin = false`, row-level security returns no
  ledger data until an admin approves it, and there is no setting for
  automatic approval - leave it that way. See `docs/admin.md`.

## 3. Account deletion (`delete_my_account()`)

Self-service, from the account menu ("Delete my account"), after typing
DELETE. The function (migration 015) runs as its owner and deletes only the
caller's rows: `notes` (theirs), `favorites`, `hidden`, `bid_list`,
`profiles`, then `auth.users` - which cascades to `auth.identities`,
`auth.sessions`, `auth.mfa_factors` and the other auth tables that reference
`auth.users` with ON DELETE CASCADE (verified live). Shared property
intelligence is never touched: `properties`, `county_calendar`,
`auction_events` and `auction_event_observations` are not keyed by a user
and the function does not name them.

Not covered by the function, by design:

- **Storage objects**: the app stores nothing per user in Storage (the
  `property-photos` bucket is shared property imagery).
- **Backups**: an encrypted database backup (section 5) taken before the
  deletion still contains the user's notes until that artifact expires (90
  days). State this in the privacy terms.
- **Auth audit log**: Supabase keeps its own auth audit entries; those are
  Supabase's, not this schema's.
- **The last admin** can delete themselves. Add a guard if that matters.

## 3b. Customer publication mode (`config.js`)

`window.TDW_CONFIG.publicationMode` controls what non-admin users see:

- Absent or `"enforced"` (the default): customers see rows from APPROVED* sources only. Admins always see every collected row, labelled with its source review status.
- `"preview"`: every approved user sees every collected row (BLOCKED excepted), labelled "Source review: …". Use it to test the customer experience on sources still awaiting review.

It changes nothing in collection or in the database. Set it back to
`"enforced"` (or remove it) before any commercial release.

## 4. Support contact (`config.js`)

`window.TDW_CONFIG.supportEmail` - blank in the repository on purpose. When
blank, every "Contact support" entry point (account menu, footer, the
"Report a data problem" / "Report a source problem" buttons on a property
page) shows "No support address is configured for this deployment yet"
instead of an invented address. Set it to a mailbox the business actually
reads. It is a public, client-side value (it is a mailto: link); do not put a
personal address there if a shared one exists.

## 5. Artifact encryption key (repository variable + secret)

Artifacts of a public repository are public. Every workflow now uploads only
`out/public/` (an `*-evidence.json` per job: run id, timestamps, the
harvester's completeness file verbatim, SHA-256 per raw file, row counts,
field NAMES and counts by county/state/source - never a row value) and
`out/private/` (OpenPGP-encrypted copies of the raw files and of the
database backup). Without the key, `out/private/` is empty, the job prints
a warning and **no raw harvest and no restorable backup is retained
anywhere**. This is a launch dependency:

1. On a machine the owner controls: `gpg --quick-gen-key "taxdeed-artifacts <ops@yourdomain>" default default never`
2. `gpg --armor --export taxdeed-artifacts` -> paste into the repository
   **variable** `ARTIFACT_PUBLIC_KEY` (Settings -> Secrets and variables ->
   Actions -> Variables). A public key needs no secrecy; a variable keeps it
   visible and auditable.
3. Keep the private key offline. To open an artifact: download it, then
   `gpg --decrypt out/private/<file>.gpg`.
4. Only the FDOR backfill's *apply* mode needs the private key on GitHub
   (it reads the encrypted dry-run plan): put the armored private key in the
   **secret** `ARTIFACT_PRIVATE_KEY` only when running an apply, and remove
   it afterwards.

### What stays public

Per job, `<job>-evidence.json` and, for jobs that record it,
`source_health-<source>.json` and the job summary. Contents: run id/attempt/
workflow/commit, `generated_at`, the per-source completeness/status file
verbatim (county or vendor-source names, COMPLETE/INCOMPLETE, row counts,
transport-level reasons such as "curl exit 7"), per raw file: path, byte
size, SHA-256, kind, row count, field names, rows by county/state/source/
host/status. The backup manifest (table names, row counts, file hashes).
Nothing else. `tests/python/test_artifact_privacy.py` enforces the upload
paths on every workflow and the no-row-values property of the script.

## 6. Source health (`scripts/source_health.py`, migration 016)

After each job's sync step the workflow records one row per dataset:
`fl_deeds` (cadence 12 h), `fl_certificates` (24 h), `fl_laft` (24 h,
completeness UNKNOWN - the LAFT harvesters have no per-county gate),
`tx_sales` (manual, no cadence) and `db_backup` (24 h). The step is
`continue-on-error` and reads the sync step's outcome, so a failed sync is
recorded as FAILED rather than disappearing. It never retries anything and
never changes what was harvested.

The app derives HEALTHY / INCOMPLETE / FAILED / STALE / NOT_RUN at read
time (`healthOf()` in `public/app.js`, mirrored by `derive_health()` in the
script) and shows it on the Dashboard ("Data sources"), in Terms ("Where
the numbers come from") and on the Texas page's empty-ledger copy. STALE =
last success older than 2x cadence; a manual source is never STALE by the
clock, it is labelled manual with its last run date.

## 6b. Florida LAFT status file and lifecycle (2026-09-29)

Nothing to configure. Every LAFT harvester writes
`out/harvest_laft_status.json` (per county: COMPLETE / EMPTY / INCOMPLETE /
FAILED, transport/parse/empty-marker signals, error category, source URL),
the artifact evidence and `source_health.py` read it, and
`scripts/laft_lifecycle.py` closes out rows only for COMPLETE / EMPTY
counties. Expect INCOMPLETE for realTDM counties with nothing listed until
the platform's empty-result phrase is captured (see
`docs/otc-inventory-model.md` section 2) and for Brevard's procedural PDF -
both are honest, not failures. Hendry stays FAILED / TRANSPORT_HTTP_404
until its current Municode PDF link is found (the harvester tries the
clerk's node page first).

## 7. Change signals and notifications

The app now shows "Changes since this browser's last visit" for watchlist
and favorite rows (sale date, opening bid, status, disappearance), computed
from the rows it already loads against a snapshot kept in that browser's
localStorage. It is per browser and per device and says so. There are **no
e-mail or push notifications**: sending them needs (a) a queue table
written by the sync jobs when a watched row changes, (b) a sender with an
e-mail provider credential (Resend/Postmark/SES) or a Web Push VAPID key
pair, (c) a per-user opt-in and unsubscribe path, and (d) the
`schema-v5-digest.sql` / `supabase/functions/send-digest` path, which is
committed but **not deployed** (no Edge Function is deployed on the
project as of 2026-09-29). None of that was deployed for appearance's sake.

## 8. Map providers and imagery (launch dependencies, not code)

- `googleMapsApiKey` in `config.js` is a Google **Maps Demo Key**
  (testing/prototyping only per Google; daily quota; not domain-restricted).
  Production needs a real key on a billed project, restricted to HTTP
  referrers for this site and to the Maps JavaScript / Static APIs.
- `maptilerKey` is on MapTiler's free plan, origin-restricted to
  `rodz-taxdeeds.pages.dev`. Free-plan terms and attribution apply.
- OpenStreetMap embed (GIS card) and MapTiler/Google static images: the
  attribution baked into the images/embeds must stay visible.
- Stored property imagery is USDA NAIP aerial (`photo_source = usda_naip`)
  and is labelled as such everywhere; nothing is labelled Street View unless
  `photo_source` says so. Licensing/terms review of the map providers for a
  paid product is a counsel item; this repository makes no claim either way.

## 9. Known advisor items left as-is

- `spatial_ref_sys`, `geometry_columns`, `geography_columns` still grant
  anon/authenticated: PostGIS-owned (`supabase_admin`), `postgres` cannot
  revoke on them. No app data.
- Seven legacy tables keep "RLS on, zero policies" (inaccessible via the
  API) and, after 015, no client grants either. Dropping them is a cleanup
  decision, not a security one.
- `st_estimatedextent` SECURITY DEFINER executable by clients: PostGIS-owned.

## 10. Cloudflare Pages / CSP

Unchanged by this PR. `public/_headers` is the CSP; nothing in this PR adds
a host. `detectSessionInUrl` is now `true` in `app.js` so the password-
reset link can complete; that reads the URL fragment/query on load only.

## 11. Paid beta: billing, legal, support (2026-10-05)

Full design: `docs/commercial-layer.md`. Everything below is manual and
NOT done; the repository ships billing switched off.

| Item | Where | Value to supply |
|---|---|---|
| Stripe secret key | Supabase -> Edge Functions -> Secrets: `STRIPE_SECRET_KEY` | a restricted key (Customers write, Checkout Sessions write, Customer portal write, Subscriptions read) |
| Monthly price | Stripe product + recurring monthly price -> `STRIPE_PRICE_ID` | `price_...` |
| Webhook secret | Stripe webhook endpoint `https://cqnnnvpbocafuvpzfbzu.supabase.co/functions/v1/stripe-webhook` -> `STRIPE_WEBHOOK_SECRET` | `whsec_...` (events listed in docs/commercial-layer.md section 6) |
| Return URL | `APP_URL` secret (optional) | `https://rodz-taxdeeds.pages.dev/index.html` |
| Customer portal | Stripe dashboard -> Settings -> Billing -> Customer portal | allow payment-method update, invoices, cancel at period end |
| Plan display | root `config.js` `billing.planName`, `billing.priceDisplay`, then `billing.enabled: true` | must match the Stripe price |
| Migration | `scripts/migrations/027_commercial_billing_entitlements.sql` | apply only with explicit authorization |
| Support address | root `config.js` `supportEmail` | a shared mailbox the business reads |
| Legal details | root `config.js` `legal.operatorName`, `legal.governingLaw`, `legal.effectiveDate`, `legal.contactEmail` | the operating entity's real details; have counsel review the four pages |
| Password reset redirect | Supabase Auth -> URL Configuration (section 2 above) | Site URL `https://rodz-taxdeeds.pages.dev`; Redirect URLs `https://rodz-taxdeeds.pages.dev/**` (every state page), plus custom SMTP |
| Production maps key | root `config.js` `googleMapsApiKey` (section 8 above) | a key on a billed Google Cloud project, HTTP-referrer restricted to `https://rodz-taxdeeds.pages.dev/*`, API-restricted to Maps JavaScript API (+ Maps Static API if static imagery is kept) |
| Backup encryption | repository variable `ARTIFACT_PUBLIC_KEY` (section 5 above) | an OpenPGP public key; private key kept offline |
