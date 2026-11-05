# Runbook

## Run a job by hand

GitHub -> Actions -> "Harvest FL tax deed data and sync to Supabase"
(`harvest-and-sync.yml`) -> Run workflow. A manual run writes to production,
the same as a scheduled one.

| Input | Default | Meaning |
|---|---|---|
| `job` | `all` | Which job runs. `all` runs every scheduled job **including `texas`**. Pick one job to run only that path. |
| `force_harvest` | false | Ignore the LAFT change-detection cache and re-fetch every source |
| `enrich_states`, `enrich_kinds`, `enrich_limit` | blank | `job=enrich` only: states, kinds (e.g. `parcels`), row limit |
| `available_mode` | `plan` | `job=available`: `plan`, `metadata`, `probe`, `discover`, `apply`, `acquisition`, `imagery` |
| `geocode_mode`, `geocode_states`, `geocode_limit`, `geocode_allow_upgrade` | `plan` | `job=geocode`: `plan`, `dry-run`, `apply`, `address` |
| `storage_mode`, `storage_max` | `analyze` | `job=storage`: `analyze`, `apply`, `apply_consolidate` (image re-encoding) |
| `registry_mode` | `plan` | `job=registry`: `plan` or `apply` (load the registry CSV into the database) |
| `evidence_scope`, `evidence_counties`, `evidence_realauction_dates` | `available` | `job=evidence`: value-free captures of source pages, printed in the job log |

`job` options: `all`, `deeds`, `certificates`, `laft`, `texas`, `backup`
(the scheduled jobs) and `evidence`, `outcomes`, `expansion`, `enrich`,
`storage`, `available`, `geocode`, `publication`, `registry` (manual; `expansion`
is also scheduled). Read the comment above each job in the workflow before
running it; most manual modes default to plan-only.

Other manual workflows: `parcel-boundaries-broward.yml` and
`parcel-boundaries-florida-available.yml` (dry run by default; `confirm=APPLY`
to write), `backfill-fdor-phase52.yml`, `geocode-dry-run.yml`,
`lgbs-acquisition-validation.yml`, `probe-*.yml` (read-only evidence).

Capture and probe scripts are gated by `harvesters/governance/discovery_guard.py`:
a source needs an in-date `discover` record in `data/source_permissions.csv`,
or the request is refused before it is sent.

## Apply a database migration

Migrations are applied **by hand** by the owner (Supabase SQL editor or CLI),
never by CI. Files: `scripts/migrations/NNN_*.sql` (newer) and
`schema*.sql` / `schema-v*.sql` at the root (older).

The file headers say "NOT APPLIED" when written; several were applied later
without the header being updated. **The only source of truth is Supabase:**
Database -> Migrations, or `select version, name from
supabase_migrations.schema_migrations order by version;`. Some were applied
outside that history (034), so also check for the objects themselves.

What the repository records (verify each):

| Migration | Recorded state |
|---|---|
| 002-014, `schema-v4`..`schema-v10` | Live (the app depends on them) |
| 015-019 | Headers say not applied; 021 requires 019, and 021 is recorded applied, so check |
| 020, 021, 022, 023 | Applied 2026-09-30 (CLAUDE.md) |
| 024 | Not applied (customer monitoring; app feature-detects) |
| 025 | Not applied per CLAUDE.md; check |
| 026 | Applied 2026-10-04 as `20261004180726` |
| 027 | Not applied (billing) |
| 028, 029, 030 | Not applied (list payload, research workspace, approval e-mails) |
| 031, 032 | Not applied. Order matters: 031, then `job=publication` for every state, then 032. Between 031 and the writer, customers see nothing. See `docs/publication-gate.md`. |
| 033 | Number held by an unmerged billing PR; no file |
| 034 | In production, applied outside the migration history (2026-10-21) |
| 035, 036 | Not applied per headers / CLAUDE.md; check |
| 038 | Header does not say; check |
| 037 | Applied 2026-10-27 |

The code probes for columns and tables before using them, so an unapplied
migration means a feature stays off, not a crash. Rules before any RLS change:
read `docs/production-configuration.md` and the RESTRICTIVE / PERMISSIVE lesson
in CLAUDE.md (dropping a table's only PERMISSIVE policy hides every row).

## Add a county or source

1. Read `docs/state-launch-playbook.md` (new state) or `docs/source-registry.md`
   and `docs/source-adapters.md` (new source). Evidence first: capture the page
   with `job=evidence` before mapping a field.
2. Configure the harvester: a row in the harvester's CSV under `data/`
   (Florida LAFT: `laft_pdf_sources.csv`, `laft_html_sources.csv`,
   `laft_realtdm_counties.csv`, `laft_pioneer_counties.csv`,
   `laft_portal_sources.csv`), or a configuration in
   `harvesters/otc/adapters/expansion.py` for other states.
3. Record permissions in `data/source_permissions.csv` (one row per operation;
   `scripts/add_owner_interim_permissions.py` writes interim rows). Check with
   `python3 scripts/source_permission_check.py --source <id> --operation fetch --state XX`.
4. Regenerate: `python3 scripts/build_county_source_registry.py`, then the
   generated JSON files (`scripts/build_*.py`; run each with `--check` to see
   which are stale), then `python3 scripts/state_launch_check.py --state XX`.
5. Run `python3 -m pytest -q tests/python`. Many tests pin counts; update a
   pinned count only when the change is intended.

## Record a reply from a county office

1. Add a row to `data/office_replies.csv` with the question it actually
   answered (`ROUTING_ONLY` / `TECHNICAL_ONLY` / `COMMERCIAL_USE`) and the
   commercial-use answer.
2. A reply that grants something also needs the matching record in
   `harvesters/governance/authorization.py` and the permission rows in
   `data/source_permissions.csv`. A prohibition the owner has not yet decided
   to enforce is `owner_decision=PENDING` and is listed under "Open owner
   decisions" in `docs/source-permissions.md`.
3. Run `python3 -m pytest -q tests/python/test_office_replies.py`.

Rules and the replies on file: `docs/source-permissions.md` "Office replies".
A permission to link is never a permission to collect or reuse.

## Deploy the front end

1. Edit files under `public/` only (exception: root `config.js`).
2. Bump `CACHE` in `public/sw.js` (the comment there keeps the history).
3. A new top-level file must be added to the `FILES` list in
   `.github/workflows/sync-public-to-root.yml`, to `DEPLOYED_BUNDLE_FILES` in
   `tests/python/test_phase16_deployment_mirror_sync.py`, and to the `SHELL`
   precache list in `sw.js`.
4. Merge to `main`. The mirror workflow copies the files to the root and
   commits ("Auto-sync: mirror public/ to repo root [skip ci]"); Cloudflare
   Pages deploys the root. PRs get a branch preview, which the
   `deployed-login` job in `playwright-test.yml` checks.

## Tests

As CI runs them:

```bash
# python-governance-test.yml
pip install pytest pyyaml requests beautifulsoup4 pdfplumber openpyxl pyshp pyproj
pytest tests/python/
node --test tests/billing/billing_core.test.mjs tests/billing/approval_notify.test.mjs
node --test tests/billing/signup_password.test.mjs
node --test tests/boundary/parcel_boundary.test.mjs

# playwright-test.yml: serve public/ with the stub, then
npm install --no-save playwright && npx playwright install --with-deps chromium
# build /tmp/serve exactly as the workflow's "Build a throwaway serve directory" step does
python3 -m http.server 8934 --directory /tmp/serve &
node tests/run_test.mjs
for f in tests/audit/*.mjs; do BASE_URL=http://localhost:8934/index.html node "$f"; done
BASE_URL=http://localhost:8934/index.html node tests/recovery_flow_test.mjs
```

The Playwright tests never reach Supabase: `tests/vendor/supabase-stub.js`
replaces the client and `tests/config.js` carries no keys.

## Common failures and where to look

| Symptom | Look at |
|---|---|
| A county shows stale or no data | Admin area (`/admin`) "Needs attention": every failing or stale county read, broken source link and withheld unconfirmed record, with the recorded reason. Then the job log for that county. |
| A source link shows "Link broken at source" | `source-link-check.yml` log and `public.source_link_checks` (needs migration 036); a link is broken only after two daily failures |
| `deeds` job fails at the sanity check | `scripts/sanity_check_deeds.ps1`: fewer than the minimum counties had fresh data. Usually a RealAuction change or a block. |
| A scheduled run never started | `schedule-watchdog.yml` log; it re-dispatches once |
| A harvester exits 3 | A permission check denied it (`scripts/source_permission_check.py`); see the reason code. Expired interim records deny. |
| Sync fails with HTTP 500 | Statement timeout on a large read; population reads must page by keyset (`scripts/rest_pages.py`) |
| App shows a blank page or boot failure | `public/boot.js` failure panel; the Supabase client loader falls back to the bundled `supabase-js.umd.js` |
| Users get no approval e-mail | `notify-approval` deployed? migration 030 applied? `RESEND_API_KEY` set? |
