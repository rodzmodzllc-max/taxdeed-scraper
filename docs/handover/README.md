# Handover: start here

This folder is for the engineer who takes over the system. Every fact here was
checked against the repository on 2026-11-04. Where a fact lives outside the
repository (dashboards, live database), the page says so and tells you where to
verify it.

| Page | What it answers |
|---|---|
| [README.md](README.md) (this page) | What the product is, how it is built, when it runs, where the data comes from |
| [accounts-and-secrets.md](accounts-and-secrets.md) | Every external account and secret, by name, what breaks without it, how to rotate it |
| [runbook.md](runbook.md) | Running jobs by hand, migrations, adding a source, deploying, tests, common failures |
| [transfer-checklist.md](transfer-checklist.md) | The ordered steps to move the system to a new owner |
| [known-limitations.md](known-limitations.md) | What is unfinished, interim or legally open |

## What the product is

**TAXACQ - Tax Acquisition Intelligence** (repository name `taxdeed-scraper`).
A private, sign-in-and-approval web app that lists public tax-sale property
in three customer ledgers:

| Ledger | `properties.source` | What it holds |
|---|---|---|
| Auctions | `auction` | Upcoming county tax-deed / tax-sale auctions |
| Available | `laft` | Property a government body offers after the sale (Florida "Lands Available for Taxes", land banks, county-held lists, Louisiana adjudicated property) |
| Liens & Certificates | `certificate` | Tax-lien certificates (Florida LienHub, Colorado) |

Each record carries its source, when it was last read, and, where verified,
how to acquire it. The project rule throughout the code is: never invent a
value. A missing fact is shown as missing.

Live at `https://rodz-taxdeeds.pages.dev` and the custom domain `taxacq.com`.

## Architecture (one page)

```
 County / vendor sites ──► GitHub Actions harvest jobs ──► Supabase Postgres ◄── Browser (static app)
   (HTML, PDF, CSV,          (harvesters/, scripts/,          (RLS on every table,      served by
    ArcGIS, JSON APIs)        data/ registries)                Edge Functions)           Cloudflare Pages
```

| Layer | Where | Notes |
|---|---|---|
| Front end | `public/` (vanilla JS/HTML/CSS, no build step) | `index.html` (Florida) plus one page per state (`tx.html`, `la.html`, `mi.html` ...), `admin.html` for operators. `sw.js` is a service worker; bump its `CACHE` name on every front-end change. |
| Mirror | `.github/workflows/sync-public-to-root.yml` | On every push to `main` that touches `public/`, copies the files in its `FILES` list to the repo root. Cloudflare Pages deploys the **root**, not `public/`. |
| Root-only files | `config.js`, `fl-counties.svg` | Never mirrored. `config.js` holds the client-side settings and keys (see [accounts-and-secrets.md](accounts-and-secrets.md)). |
| Database | Supabase project `cqnnnvpbocafuvpzfbzu` | Postgres with Row Level Security on every table. Main table `properties`, unique on `(state, source, county, case_no)`. The browser reads through RPCs such as `get_properties()` / `get_properties_list()`. Migrations: `scripts/migrations/` (newer) and `schema*.sql` (older). |
| Edge Functions | `supabase/functions/` | `self-signup`, `notify-approval`, `notify-signup`, `send-digest`, `billing-checkout`, `billing-portal`, `stripe-webhook`. Shared code in `_shared/`. |
| Harvest pipeline | `.github/workflows/harvest-and-sync.yml` | PowerShell (Florida auctions / certificates) and Python harvesters, then syncs that write to Supabase with the service-role key. |
| Code | `harvesters/` (Python packages: governance, adapters, enrichment, ledgers, sources, boundary) and `scripts/` (entry points, syncs, PowerShell) | |
| Registries | `data/` | `county_source_registry.csv` (every source per county), `source_permissions.csv` (per-operation permission records), `office_replies.csv`, `state_rules.csv`, `state_ledgers.csv`, evidence tables, harvester CSVs. Several JSON files in `public/` are generated from these and pinned by tests. |
| Tests | `tests/python/` (pytest), `tests/run_test.mjs` + `tests/audit/*.mjs` (Playwright against a stubbed Supabase), `tests/billing/`, `tests/boundary/` | See [runbook.md](runbook.md#tests). |

Permissions are enforced in code: every harvester, sync and enrichment step
asks `harvesters/governance/permissions.authorize()` (or the command-line
`scripts/source_permission_check.py`) before it fetches, stores or displays a
source. See `docs/source-permissions.md`.

## Daily schedule (UTC)

GitHub may start a scheduled run late or drop it. `schedule-watchdog.yml`
checks hourly and re-dispatches a missed slot once.

| Time (UTC) | Workflow | Jobs |
|---|---|---|
| 03:37 | harvest-and-sync | certificates, laft (Available), expansion (other states) |
| 04:13 | harvest-and-sync | deeds (Florida auctions incl. Okaloosa) |
| 10:13 | harvest-and-sync | deeds |
| 11:37 | harvest-and-sync | certificates, laft, expansion, **texas**, backup |
| 11:50 | source-link-check | checks every customer-clickable source link |
| hh:49 hourly | schedule-watchdog | re-dispatches a missed harvest slot |

Everything else in `.github/workflows/` is manual (`workflow_dispatch`) or CI
(`playwright-test.yml`, `python-governance-test.yml` on pushes and PRs).

## Where each state's data comes from

Counts are rows of `data/county_source_registry.csv` (one row per source per
county) with `verification_status = PRODUCTION_VERIFIED`, and the number of
distinct source ids behind them. Production states are listed in
`harvesters/governance/states.py` (`PRODUCTION_STATES`): FL, TX, LA, MI, WY,
SC, CO, WI, MO, OK, PA, MN, TN.

| State | Auctions (rows / sources) | Available (rows / sources) | Liens & Certificates (rows / sources) |
|---|---|---|---|
| FL | 47 / 2 (RealAuction, Okaloosa Bid4Assets) | 56 / 10 (county LAFT lists on several platforms; Orange is restricted, see known-limitations) | 33 / 2 (LienHub, Sarasota Tax Collector) |
| TX | 95 / 7 (LGBS, RealAuction, PBFCM, MVBA, GovEase, Harris tax office, Jefferson sheriff) | 69 / 9 (vendor struck-off lists, county trust / resale lists) | - |
| LA | - | 1 / 1 (East Baton Rouge adjudicated property, open data) | - |
| MI | 77 / 3 (incl. Tax-Sale.info catalogs) | 14 / 7 (Detroit Land Bank, other land banks) | - |
| CO | 3 / 3 | - | 2 / 2 |
| SC | 3 / 3 | 2 / 2 (Forfeited Land Commission lists) | - |
| WI | 2 / 2 | - | - |
| WY | 1 / 1 | - | - |
| MN | 1 / 1 | 3 / 3 | - |
| MO | - | 2 / 2 (St. Louis LRA, Kansas City land bank) | - |
| OK | - | 1 / 1 (Oklahoma County) | - |
| PA | - | 2 / 2 (Fayette repository, Pittsburgh land bank) | - |
| TN | - | 1 / 1 (Shelby County Land Bank) | - |

Registered but not activated (no data synced): AL, AR, AZ (one
`SEARCH_EVIDENCE_ONLY` row each), WV, UT. The registry also holds
non-production candidate rows for FL (11) and TX (14). Live row counts change with every
run; read them from Supabase, not from this page. Per-state detail:
`docs/state-coverage.md`, `docs/source-coverage-florida.md`,
`docs/source-coverage-texas.md`.

## Reading order for the rest of `docs/`

`docs/` holds one file per sprint, written at the time. Read these first:

1. `CLAUDE.md` (repo root) - the long architecture map and history. Its
   "Where to look for more" points to a claude.ai Project you will not have;
   everything else is in this repository.
2. `docs/production-configuration.md` - every setting that lives outside the repository.
3. `docs/three-ledgers.md`, `docs/otc-inventory-model.md` - the data model.
4. `docs/source-permissions.md`, `docs/legal/pre-sale-blockers.md` - what you may and may not do with each source.
5. `docs/publication-gate.md`, `docs/acquisition-gate.md` - what customers see.
6. `docs/state-launch-playbook.md`, `docs/source-registry.md` - adding states and sources.
7. `docs/admin.md` - the operator pages.

The remaining files are sprint records; search them when a code comment
points to one.
