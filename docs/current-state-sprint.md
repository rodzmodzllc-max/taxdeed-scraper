# Current-state data sprint (2026-10-10)

Baseline: `main` at `77688dc` (PR #129 merged). Evidence: read-only production
queries at 2026-10-10T10:26Z (`scripts/sql/current_state_coverage.sql`,
rendered in `docs/current-state-coverage.md`) and the job logs of the three
most recent scheduled `harvest-and-sync` runs (37826062795, 37971480332,
38013151217). No workflow was dispatched, no migration applied and no row
written to produce this.

## What the baseline showed

| Where | Active rows | Measured | Cause (from the job logs) |
|---|---|---|---|
| MI Available, Detroit Land Bank lots | 30,758 | last read 2026-10-06, though MI's job succeeded on 10-09 | `harvest_expansion.py` merged every source of a county into ONE status. Lots read COMPLETE (30,706 rows) but Detroit's programs layer (same county, Wayne) FAILED, so Wayne was FAILED and the sync skipped all 30,706 lot rows (`skipped_unit_not_read=30706`). |
| LA Available, East Baton Rouge | 10,334 | last read 2026-10-03 / 10-06; harvest COMPLETE on 10-09 | The sync's read of stored rows (`stored_provenance`, offset pages with two jsonb columns) returned HTTP 500, the sync step failed, and the lifecycle step after it was skipped. |
| SC (2026-10-08 run) | 905 | sync failed | Same HTTP 500 on the same read. |
| FL deeds job (2026-10-10 01:25 run) | - | FDOR / FEMA / NAIP / photo steps never ran | The geocoding read (`latitude=is.null` + address regex) returned HTTP 500 and the job stopped at that step. |
| Expansion units in the registry | - | `registry: 0 unit row(s) patched` on every expansion run | Status entries carried `source_id = expansion_<st>`, which no registry row has. |

Why the reads failed: an `order=id&limit=1000&offset=N` page makes Postgres
sort the state's whole filtered set before skipping N rows. Measured
read-only on 2026-10-10: East Baton Rouge took 1.3 s per page with an
external merge sort on disk; eleven state jobs start together, and a page
crossed the statement timeout. A keyset page (`id=gt.<last>`) walks the
primary-key index with no sort (measured on the MI population: no sort, no
spill, constant per page).

## What changed

1. **`scripts/rest_pages.py`**: keyset paging plus a bounded retry. The
   retry applies to GETs only, and only on 500 / 502 / 503 / 504 / 520-524
   or a connection error (4 attempts: 2 s, 4 s, 8 s). A 4xx is raised at
   once and unchanged. Used by:
   - `sync_state_inventory.stored_provenance` / `stored_active`;
   - `laft_lifecycle.Api.get` / `get_all`;
   - `geocode_properties._fetch` (same retry rule, via `requests`).
2. **Per-source status.** `StatusRecorder` keeps one entry per (county,
   source). `harvest_expansion.py` records each source's own read.
   `sync_state_inventory` gates upserts and close-out per (source_id,
   county) through `unit_status()`. A county-only key remains the
   fallback, and it is now the worst read of that county
   (FAILED > INCOMPLETE > COMPLETE > EMPTY). The old map kept whichever
   entry came last, which could have closed a failed source's rows after a
   sibling's COMPLETE read. The same entries now match registry rows, so
   unit freshness patches them.
3. **Geocoding reads only listed rows**:
   `status in (active, available, scheduled)` and `delisted_at is null`.
   A closed row never spends the run's budget, matching
   `harvesters/enrichment/priority.py`.
4. **Enrichment isolation in the deeds job.** Geocoding, FDOR, FEMA and
   NAIP each run `if: !cancelled()` with `continue-on-error: true`. One
   failing never skips the others.
5. **Reproducible coverage matrix**: `scripts/sql/current_state_coverage.sql`
   (read-only, counts only), `data/current_state/coverage-2026-10-10.json`
   (the baseline result) and `scripts/current_state_report.py` →
   `docs/current-state-coverage.md` (pinned by a test).

Tests: `tests/python/test_current_state_sprint.py` covers keyset paging,
retry / no-retry, bounded attempts, the Wayne case in both entry orders
(upsert and close-out), the worst-read fallback, recorder entries per
source, the geocode filter and retry, workflow isolation and the matrix.
Two existing fakes learned PostgREST's `id=gt.` (assertions unchanged).

## Before / after

Production "after" figures need the next scheduled runs on merged code.
No run was dispatched in this sprint, so none is claimed. What is measured:

| Metric | Baseline (2026-10-10 10:26Z) | After this change | Evidence |
|---|---|---|---|
| MI Detroit lots rows a COMPLETE read could not refresh | 30,706 per run | 0 (the per-source test case) | job 113958930433 log; `test_a_failed_sibling_source_does_not_hide_a_complete_read` |
| LA rows left unrefreshed by a failed sync read | 10,334 | read retried; keyset pages | job 113958930202 log; retry tests |
| Enrichment steps skipped by one failure (deeds job) | 4 (FDOR, FEMA, NAIP, photos) | 0 among the four isolated steps | job 114097476373; workflow test |
| Active rows read within 36 h, all states | 14,718 of 58,312 | next scheduled run | `docs/current-state-coverage.md` |

## Not changed, and why

- **FL certificates (1,611 never stamped).** Every one of the 32 LienHub
  counties read INCOMPLETE on the last run (annotation of job 113958930186).
  Not stamping an incomplete read is correct. LienHub is not retried
  harder.
- **Texas (122 auctions, 421 Available).** The `texas` job is manual-only
  by design, and LGBS is not retried. The rows read stale and say so
  (`unit_freshness.MANUAL_ONLY_SOURCES`).
- **Past sale dates still `active`** (MI Lenawee 35, TX 122, FL 4).
  `isPastDue()` already keeps them out of every count and upcoming view.
  Closing on the calendar alone, without the source's own word, is not done.
- **Missing coordinates / flood** (MO, OK, PA, SC Available; TN flood).
  These need the manual `enrich` / `geocode` jobs (owner dispatch) or
  coordinate sources not yet approved (`docs/authoritative-coordinates.md`).
- **Unreviewed AVAILABLE sources** (Detroit, Oceana, Horry, Georgetown,
  St. Louis, Oklahoma County, Fayette, Ramsey, Shelby). They are collected
  and shown to admins, but customers see them only after an admin review.
  No source was approved here.
