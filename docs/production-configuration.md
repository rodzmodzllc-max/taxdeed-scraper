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
