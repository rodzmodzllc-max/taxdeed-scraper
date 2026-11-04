# Known limitations

Counts come from the repository on 2026-11-04. Re-check them with the commands given.

## Legal and source permissions

| Item | Detail | Where |
|---|---|---|
| Interim permissions expire **2027-04-12** | 380 of the 454 records in `data/source_permissions.csv` (108 sources) expire that day. Most are `OWNER_PERMISSION_REQUIRED` on `INTERNAL_RISK_ACCEPTANCE` or `GRANDFATHERED_PRACTICE`. The seller accepted that risk; it is **not** the source's permission and does not transfer as one. When a record expires, the code denies that operation and the source stops. A further 35 records expire between 2027-10-12 and 2027-11-04. | `python3 scripts/source_permission_check.py --due 180`; `docs/source-permissions.md`, `docs/interim-permissions.md` |
| Sources needing a legal opinion | 13 source ids carry `LEGAL_REVIEW_REQUIRED` records: `fl_realauction`, `fl_lienhub_certificates`, `fl_laft_html`, `fl_laft_pdfs`, `fl_laft_realtdm`, `fl_laft_osceola`, `fl_fdor_cadastral`, `fl_dor_statewide`, `tx_lgbs`, `tx_realauction`, `tx_pbfcm`, `tx_mvba`, `tx_govease`. | `docs/legal/pre-sale-blockers.md` items 1-4, 18 |
| A written prohibition | Orange County Comptroller (FL) prohibited automated collection and commercial use without written authorization; `fl_laft_orange` is `RESTRICTED`, out of the daily job, rows withheld from customers. | `data/office_replies.csv` |
| Pre-sale blockers | 18 items before selling or launch (legal opinions, Terms / Privacy, owner-name display, trade-name clearance for "TAXACQ", sub-processor list, and more), plus 6 post-launch items. None is marked resolved. | `docs/legal/pre-sale-blockers.md` |
| `tx_ctsa` | Hard-blocked (paywall); never harvested. | `harvesters/governance/permissions.py` |

## Product switches still in trial settings (root `config.js`)

| Setting | Today | Before selling to customers |
|---|---|---|
| `publicationMode` | `"preview"`: every signed-in tester also sees sources awaiting review (labelled) | set `"enforced"` so customers see approved sources only |
| `availableGate` | `"off"` | owner decision; `"enforce"` would withhold most Available rows today (`docs/acquisition-gate.md`) |
| `billing.enabled` | `false`; migration 027 not applied; no Stripe keys | build per `docs/commercial-layer.md` after the legal items |
| `googleMapsApiKey` | a Google **Demo Key** (testing-only, daily quota, not domain-restricted) | a production key on a billed project, restricted, or drop the Google basemap (blocker 7) |
| `legal.*` | blank, so the legal pages say "not configured" | the operating entity's details, counsel-reviewed text |

## Database

- Several written migrations are **not applied** (024, 027-032, 035, 036 per
  the records; 038 unrecorded). The app feature-detects each, so the related
  feature is simply off. Recorded states are in [runbook.md](runbook.md#apply-a-database-migration);
  verify in Supabase's migration list.
- Migration 034 was applied outside the migration history.
- Migration 015 (closing `anon` grants on legacy tables and customer writes to
  shared tables) is recorded as not applied. CLAUDE.md records a legacy table
  `auction_records` with RLS disabled and `anon` write grants; check it.
- Older open items recorded in CLAUDE.md, never confirmed closed: the
  `bid_list` table (schema-v7) missing in production, and revocation of the
  legacy long-lived Supabase JWT keys. Check both.

## Repository and operations

- **The repository is public, with full history.** Keys committed in the past
  (an early Google Maps key, rotated) remain in history. Workflow artifacts
  are evidence-only unless `ARTIFACT_PUBLIC_KEY` is set (then encrypted).
  Making the repository private, and whether to rewrite history, is open
  (blocker 11). Note the repository was made public to avoid an Actions
  billing block; going private means paying for Actions minutes.
- **GitHub cron is best effort.** Scheduled runs start late or are dropped
  under load; slots were moved off `:00` and `schedule-watchdog.yml`
  re-dispatches a missed slot once. A day can still be read late.
- **No machine runs outside GitHub Actions and Supabase.** The local
  `sync-config.local.json` is for manual runs only.
- **Live tiles and county sites cannot be reached from the AI sandbox** used to
  build this repository; several features were verified only on the deployed
  site or on Actions runners. Many `docs/` files say "PR open" for work since
  merged; trust the code and Supabase over a sprint document's status line.
- **Coverage gaps**: the registry has a production Lands Available source for
  56 of Florida's 67 counties; the rest publish behind portals no harvester
  reads, or publish nothing found. See
  `docs/source-coverage-florida.md` and `docs/state-coverage.md`.
- **How the code was written**: most recent commits carry a Claude co-author
  line; CLAUDE.md is the architecture map those sessions kept. Expect long
  comments and sprint-dated docs rather than a single design document.
