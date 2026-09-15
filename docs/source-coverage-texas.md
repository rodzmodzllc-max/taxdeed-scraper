# Texas source coverage — 254 counties

**Status:** Phase 33, 2026-09-15. Machine-readable matrix: `data/tx_county_coverage_matrix.csv` (254 rows, one per county, sourced from the app's own authoritative county list — `public/tx-counties.svg`'s `data-county` attributes — cross-referenced against `data/tx_realauction_counties.csv` and the named county lists already recorded in `harvesters/governance/registry.py`'s `jurisdiction` fields). This page is the narrative summary; the CSV is the source of truth for per-county detail.

## Real counts (from the matrix, not estimated)

- **254/254 Texas counties** have a row in the matrix.
- **42/254 counties** have a known auction/tax-sale source of any kind (`APPROVED`, `BLOCKED`, or `LEGAL_REVIEW_REQUIRED` — status is tracked, not collapsed). That breaks down as:
  - **24 counties** via `tx_realauction` (`APPROVED`, production-verified, robots.txt question open — `data/tx_realauction_counties.csv`).
  - **8 counties** via `tx_lgbs`, named explicitly in prior reconnaissance docs (Bexar, Dallas, El Paso, Galveston, Harris, Hidalgo, Tarrant, Hardin) out of a vendor total described as "45+ counties confirmed" — **the full LGBS roster was never re-extracted into a CSV this phase**, so the true number of LGBS-covered counties is understated here on purpose rather than guessed at.
  - **4 counties** via `tx_govease` (`BLOCKED` — Denton, Parker, Wichita, Wise).
  - **9 counties** via `tx_mvba` (`BLOCKED` — Bandera, Freestone, Hill, Lampasas, Mason, Midland, Newton, Burnet, Harrison).
  - **Harris County** additionally via `tx_hctax` (`LEGAL_REVIEW_REQUIRED`) and `tx_ctsa` (`BLOCKED`) — already counted under LGBS above, not double-counted in the 42.
  - `tx_pbfcm` (`BLOCKED`, 11 counties + Harris + 2 ISDs per `claude/pbfcm-source-reconnaissance-blocked.md`) is **not reflected in the 42-county figure** — that document did not enumerate the 11 county names in a form this phase could safely transcribe without risking a wrong name, so it is cited but not merged into the matrix. This is a known, explicit gap, not an omission.
- **212/254 counties** have no known auction/tax-sale source at all — genuinely `UNKNOWN`, not `NOT_AVAILABLE` (Texas has 254 counties and this project's own reconnaissance has only ever looked closely at a few dozen of them).
- **0/254 counties** have a verified, extracted per-county appraisal-district URL — the mechanism (`tx_comptroller_directory`, the Texas Comptroller's official county-directory pages) was confirmed to exist this phase but not extracted for any individual county.
- **0/254 counties** have a verified GIS source — the Texas Comptroller's Property Tax Data Reports and TNRIS/StratMap's statewide "Land Parcels" layer were both found as candidates this phase but neither was reviewed for licensing or extracted.

## Legal status of what IS known

| Status | Counties (approx., see notes above on overlap/undercounting) |
|---|---|
| `APPROVED` (production-practice, not formally rights-cleared) | 24 (RealAuction) + 8 named (LGBS, undercount of the true ~45+) |
| `BLOCKED` | 4 (GovEase) + 9 (MVBA) + Harris (CTSA, additional to hctax) + 11-plus-Harris-plus-2-ISDs (PBFCM, not merged into the per-county matrix — see above) |
| `LEGAL_REVIEW_REQUIRED` | Harris (hctax.net) |
| `DISCOVERED` | statewide mechanism only (`tx_comptroller_directory`) — no county rows yet |
| `UNKNOWN` | the remaining ~212 counties, for auction sources specifically |

## The dominant Texas finding, carried into the Phase 33 report

**No Texas harvest — LGBS, RealAuction, or any other — has ever synced a single row into production**, regardless of any county's legal status. `scripts/migrations/002_add_texas_support.sql`, `003_ledger_type_and_state_isolation.sql`, and `004_widen_unique_constraint_for_state.sql` have never been run against the live Supabase project (`claude/migration-002-003-004-execution-plan.md`). This means Texas's real bottleneck today is an infrastructure/migration gap, not primarily a legal-compliance gap — even the two cleanest, `APPROVED` sources (LGBS, RealAuction) are blocked from reaching customers by this, independent of any source's rights status. Phase 33 did not run these migrations (Section 58 forbids it without explicit authorization and a demonstrated-necessary, additive, non-production-data-touching change — this migration touches live schema and must be run by a human, per `docs/source-registry.md`'s own note that this project's tooling cannot type raw DDL into the Supabase SQL Editor).

## What Phase 33 did not attempt

Extracting the true LGBS county roster (45+, not just the 8 named), the PBFCM 11-county list, or any of the 212 fully-unknown counties' appraisal district / GIS / auction sources. Each of those requires either re-running Phase 33-style reconnaissance against a specific vendor page (LGBS/PBFCM) or 200+ individual government-site lookups (per-county appraisal districts) — real work, correctly out of scope for one phase per Phase 33's own Rule 11 ("do not build 321 county scrapers during Phase 33") and Rule 20 ("do not claim all counties are covered unless every county actually has a documented source entry").
