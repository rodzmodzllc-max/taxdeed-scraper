# Phase 17 — Origin/Local Reconciliation & Merge-Readiness Gate

Status date: 2026-09-15. This is a read-only reconciliation *audit*, not a merge, push, or deployment. No repository content was changed except the addition of this document. No database, workflow, or production system was touched.

## 1. Executive Summary

Phase 16 established that this sandbox's entire git history (the Phase 10–16 governance/security/data-contract body of work) has never been pushed to `origin`, and that `origin/main` independently advanced through a separate channel with a genuine, hand-built UI rebuild (terminal-style reskin + a new dashboard/nav-rail/table-view/persistent-detail-panel app shell). This phase performed the full three-way investigation the divergence demands.

**The headline finding is good news, verified rather than assumed:** the two histories touch almost entirely disjoint files. Every local-only (Phase 10–16) commit touches backend/governance/docs/tests plus one small, additive `app.js` change (Phase 14A's `assessedSourceLabel()` fix). Every origin-only commit touches only five frontend files (`app.js`, `explore.css`, `index.html`, `styles.css`, `tx.html`, each mirrored to `public/`) and nothing else — no SQL, no harvesters, no workflows, no tests. A real `git merge-tree` computation (read-only, no working-tree or ref changes) of `HEAD` against `origin/main` produced a **fully clean merge with zero conflicts anywhere in the repository**, correctly combining both sides' independent `app.js` changes. This is not a projection — it is the literal 3-way-merged tree, inspected directly.

The reconciliation is therefore **technically straightforward** (a real `git merge` of `origin/main` into this branch, or the reverse, should apply without manual conflict resolution). What remains are **product and process decisions a human must make**: which UI direction to ship (this checkout's untouched mobile-first ledger UI vs. origin's new desktop app shell — the merge keeps both harmlessly, but shipping both indefinitely is not a real product state), whether to keep the one CSV column local added (`Assessed/Value Field Source`), and updating this repo's own Playwright regression suite, which currently only knows the old DOM and cannot exercise origin's new nav-rail/table-view chrome (confirmed by actually running it against a built copy of origin's frontend — it progressed through roughly 50 assertions, including property loading, filtering, sorting, and CSV export, before failing on a `#mapBtn` locator that origin's rebuild replaced with a page router).

Final status: **READY_WITH_HUMAN_DECISIONS**.

## 2. Current Deployment State

- Cloudflare Pages deploys from the repository root (unchanged architecture, confirmed again this phase).
- The live site (`rodz-taxdeeds.pages.dev`) was confirmed in Phase 16 to be serving `origin/main`'s HEAD content, not this checkout's.
- `origin/main` HEAD as of this phase: `f574f7fbf21d60ac4561bd1ae17bd23c9b822f4a` ("Fix: hoist selectedPid declaration above render() sync init call (TDZ crash)"), fetched fresh via `git fetch origin` this phase — one commit further than Phase 16 observed only in that it's the same commit Phase 16 already recorded as origin's HEAD; no new origin activity occurred between Phase 16 and Phase 17.
- This checkout's HEAD: `5a810fae076e6b735358bbc4cf0f291fa5099516` (Phase 16's commit).
- No push, merge, or deploy has occurred. The live application is unchanged by this phase.

## 3. Local vs Origin History

```
LOCAL HEAD:          5a810fae076e6b735358bbc4cf0f291fa5099516
ORIGIN/MAIN:         f574f7fbf21d60ac4561bd1ae17bd23c9b822f4a
MERGE BASE:          cc7f13959aa651b53e4ed860a1915be8b96a693c  (2026-09-14 09:38:26 -0400)
LOCAL COMMITS AHEAD: 15
ORIGIN COMMITS AHEAD: 6
LIVE DEPLOYED COMMIT: origin/main HEAD (f574f7f), per Phase 16's direct fetch of rodz-taxdeeds.pages.dev
                       and structural comparison of its rendered UI (nav-rail/table-view/detail-panel),
                       which only exists in origin/main's app-shell-rebuild commits — not assumed from
                       repository metadata alone.
```

`git fetch origin` continues to succeed (read access) despite this sandbox having no push access, which is what makes every claim in this document independently checkable rather than assumed.

## 4. Merge Base

`cc7f13959aa651b53e4ed860a1915be8b96a693c`, dated 2026-09-14 09:38:26 -0400 — the last commit both histories share. Everything after this point diverged into two independent lines of work on the same day.

## 5. Local-Only Commits (Phase 10–16)

| Phase | Commit | Purpose | Files changed | Production impact | Must preserve? | Merge risk |
|---|---|---|---|---|---|---|
| 10A | `3515893` | Commercial source governance infrastructure (registry/gate/restrictions/provenance modules) | 15 files (harvesters/governance/*, docs, tests) | None directly — infrastructure, not yet wired to ingestion at this commit | MUST PRESERVE | None — no origin overlap |
| 10B | `11be6b6` | Wire governance tests into CI; formal LGBS/RealAuction rights audit | 6 files (.github/workflows/python-governance-test.yml, docs, tests) | None directly | MUST PRESERVE | None — no origin overlap |
| 11 | `320a83c` | Customer API data restriction enforcement | 7 files (docs, tests) | Documents/tests the enforcement boundary later implemented in migrations | MUST PRESERVE | None — no origin overlap |
| 12 | `7e95fce` | Production provenance and data lineage integration | 7 files (harvesters/governance/provenance.py, docs, tests) | None directly — provenance objects never persisted to Supabase | MUST PRESERVE | None — no origin overlap |
| 13 | `e17f814` | Production data contract established | 4 files (docs, tests) | Documentation baseline for the customer-safe column set | MUST PRESERVE | None — no origin overlap |
| 14A | `cacd1b1` | Harden customer data boundaries; `assessedSourceLabel()` fix | 7 files, **including `app.js`/`public/app.js`** | Real frontend fix: corrects a mislabeled value-source string for Texas rows | MUST PRESERVE | **Only local commit touching a file origin also touches** — see §7, confirmed non-conflicting |
| 14B | `b743f28` | Customer-safe database/API boundary design (readiness gate) | 7 files (docs, tests) | Design/readiness doc for 005/005a | MUST PRESERVE | None |
| 14C | `07e4626` | Execute/verify customer boundary migration (initial attempt) | 2 files (docs) | Documentation of a migration attempt | SHOULD PRESERVE | None |
| 14D | `76ee5e8` | Reconcile migration column references with live schema | 7 files (docs, tests) | Corrective documentation | SHOULD PRESERVE | None |
| 14E | `eec477b` | Gate A re-verification; Gate B blocked | 3 files (docs) | Verification record | SHOULD PRESERVE | None |
| 14F | `5c755d8` | schema-v9 applied to production; 005 failed | 2 files (docs) | Historical record of a real production migration attempt | SHOULD PRESERVE | None |
| 14E/14G | `e446504` | Fix 005's DROP FUNCTION defect and 005a's ledger_type gap | 8 files (scripts/migrations/005*.sql, docs, tests) | The corrected migration SQL later run live | MUST PRESERVE | None |
| 14H | `de93556` | Production retry succeeds — 005/005a live | 3 files (docs) | Record of the live migration success and Gate B closure | MUST PRESERVE | None |
| 15 | `bf021fc` | Customer surface security audit; Playwright stub `rpc()` fix | 5 files (tests/vendor/supabase-stub.js, docs, tests) | Fixed a real 6-day-silent regression-test gap | MUST PRESERVE | None — origin never touches `tests/` |
| 16 | `5a810fa` | Frontend deployment mirror-sync fix and root-cause documentation | 3 files (`app.js` restored to match `public/app.js`, docs, tests) | Local-only drift repair; superseded by whatever `app.js` reconciliation Phase 17/18 produces | MUST PRESERVE (docs/tests); the `app.js` content itself is moot once merged, since the merge produces a new combined `app.js` (§7) | None — the specific bytes this commit wrote to `app.js` don't need to survive a merge, only the underlying Phase 14A fix they carried forward does, and it does (§7) |

No local commit touches `index.html`, `tx.html`, `styles.css`, or `explore.css` at any point since the merge base (verified: `git diff --stat cc7f139 HEAD -- index.html tx.html styles.css explore.css public/index.html public/tx.html public/styles.css public/explore.css` is empty).

## 6. Origin-Only Commits

| Commit | Date | Subject | Files changed | Backend/DB impact | UI impact |
|---|---|---|---|---|---|
| `4424ccf` | 09-14 10:28 | Reskin UI as terminal-style: IBM Plex fonts, tighter radii, line icons instead of emoji | `app.js`, `explore.css`, `index.html`, `styles.css`, `tx.html` | None | Visual only: font, radius, and icon-rendering changes |
| `75cc419` | 09-14 10:29 | Same reskin, `public/` mirror | same 5 files under `public/` | None | Mirror of the above |
| `0596d01` | 09-14 13:06 | Rebuild app shell: dashboard, nav rail/bottom nav, table view, persistent detail panel | `app.js`, `index.html`, `styles.css`, `tx.html` | None | Structural: new page router, dashboard stats, sortable table view, persistent detail panel — all additive, reading only from the same client-side `ALL[]` array the existing ledger view already populates |
| `ea9ecfb` | 09-14 13:07 | Same app-shell rebuild, `public/` mirror | same 4 files under `public/` | None | Mirror of the above |
| `25dc3e8` | 09-14 13:18 | Fix: hoist `selectedPid` declaration above `render()`'s sync init call (TDZ crash) | `app.js` | None | Bugfix for a real bug the previous commit introduced (a `let` declared too late caused a `ReferenceError` on first page load) |
| `f574f7f` | 09-14 13:19 | Same TDZ fix, `public/` mirror | `public/app.js` | None | Mirror of the above |

Each origin change was hand-made to root first, then mirrored to `public/` in a paired follow-up commit — the reverse of this project's documented convention (edit `public/`, let CI mirror to root) — but the two copies are byte-identical at every commit, so the mirror invariant was never actually broken by this pattern; it's a process observation, not a defect (see §11).

No origin-only commit touches `.github/workflows/`, `scripts/`, `harvesters/`, `supabase/`, or any `schema*.sql` file (verified: both diffstats are empty).

## 7. Three-Way Frontend Analysis

**`app.js` / `public/app.js`** is the only file both histories touch. A full diff of base→local and base→origin, read in full (not sampled), shows:

- **Local's change** (Phase 14A only): corrects two Texas-ledger empty-state strings, and adds `assessedSourceLabel(p)` — a small pure function reading `p.harvester_source` (already part of the 48-field customer contract) to produce an honest per-row label for where a Texas "assessed value" figure actually came from (LGBS CAD vs. RealAuction adjudged value) instead of a borrowed Florida label. This function is called from two places: the property detail view's value label, and one new CSV column, `["Assessed/Value Field Source", p => assessedSourceLabel(p)]`, appended after the existing `County Assessed Value` column (never renaming or removing it).
- **Origin's change**: introduces `ICON_PATHS`/`svgIcon()` (SVG line icons replacing emoji), a `selectedPid` module-level variable, and an entire new "APP SHELL" section (page router, dashboard stats, sortable data table, persistent detail panel) appended at the end of the file. Every new function is additive and guarded (`if (typeof renderShellExtras === "function") ...`), and none of it touches Supabase, authentication, or the property-fetch path.
- **No line-range overlap between the two changes.** Local's edits sit in the ledger-copy strings (~line 384), the assessed-value label function (~line 680–700), and the CSV `cols` array (~line 2925). Origin's edits sit in the icon/shell code (~line 369–450, ~2107–2400) and an entirely new block appended after the file's existing end (~line 3734+).

A literal `git merge-tree --write-tree HEAD origin/main` (read-only; creates an orphaned tree object, changes no ref, no working-tree file — confirmed via `git status`/`git rev-parse HEAD` before and after) resolved with **exit code 0 and zero conflicts across the entire repository**, not just `app.js`. Inspecting the resulting tree directly:

- The merged `app.js` contains **both** `assessedSourceLabel()`/the CSV column **and** `ICON_PATHS`/`selectedPid`/the full APP SHELL section, correctly interleaved, no duplication, no `<<<<<<<` markers.
- The merged tree's `index.html`, `tx.html`, `styles.css`, `explore.css` are byte-identical to `origin/main`'s versions (expected: local never touched them).
- The merged tree's root and `public/` copies of `app.js` remain byte-identical to each other (the mirror invariant survives the hypothetical merge).

This is not a prediction — it is the actual output of git's three-way merge algorithm, inspected directly. **A real merge in either direction is expected to be conflict-free at the git level.**

**HTML/CSS structural changes (origin only):** the app-shell rebuild adds new markup — `#pageDashboard`, `#pageAuctions`, `#pageMap` (page containers), `.nav-item`/`.nav-bottom-item` (nav rail/bottom nav), `#dataTableBody` (table view), `#detailPanel` (persistent detail panel) — and CSS scoped to desktop widths for the new components. None of it renames or removes an existing element ID that local's untouched `app.js` Phase-14A code depends on (local's change touches only ledger-copy strings and the CSV array, neither of which reads any DOM element by ID).

## 8. Database Compatibility

Searched both `merge-base..HEAD` and `merge-base..origin/main` for every backend/contract-sensitive term (`get_properties`, `properties`, `ledger_type`, `fdor_enriched_at`, `harvester_source`, `dor_use_code`, `outcome`, `sold_price`, RPC calls):

- **`origin/main`'s `fetchProperties()` is byte-identical to the merge base's**, including its fallback: `sb.rpc("get_properties", { p_state: PAGE_STATE })`, with a fallback to unscoped `sb.from("properties").select("*")` only if the RPC itself is reported missing (`PGRST202` or a "does not exist" message). This fallback function is **unmodified by either branch** — it predates the divergence and is not a new risk introduced by origin's UI rebuild.
- The 005/005a-corrected `get_properties()` RPC is live in production (established in Phase 14H) and is what both branches' identical `fetchProperties()` call. Since 005a narrows `authenticated`'s direct column-level grants on `properties`, the pre-existing fallback path (which neither branch changed) is bounded by those grants exactly the same way regardless of which frontend triggers it.
- **Origin/main's current frontend can run safely against the production database after 005/005a.** This is not uncertain: origin's `app.js` calls the identical RPC with the identical arguments as this checkout's version, reads the identical set of `p.<field>` names in its (near-identical) CSV export, and introduces no new direct-table query, no new RPC, and no schema assumption anywhere in its diff from the merge base.
- schema-v9, 005, and 005a are documented here explicitly as **LIVE** in production (per Phase 14F and Phase 14H's live verification). No local migration file is pending; none should be re-run (see §14).

## 9. Security Boundary Preservation

Re-verified this phase directly against `origin/main`'s actual deployed `app.js` (not assumed from Phase 16's summary):

- `ledger_type` and `fdor_enriched_at` do not appear anywhere in origin's `app.js` (`grep` returned zero direct-field matches; the only occurrences of `ledger_type` are in comments referencing the migration file name).
- Origin's CSV `cols` array reads the exact same `p.<field>` set as this checkout's, minus the one `assessedSourceLabel()`-derived column (§10) — every field it reads is already covered by 005's 48-column customer-safe output (verified in Phase 15 for this checkout's identical superset).
- Origin's frontend contains no raw query that conflicts with the production security boundary. The one pre-existing `select("*")` fallback (§8) is identical on both branches, bounded by the same 005a grants either way, and is not a merge blocker — it is a pre-existing, equally-present condition on both sides of the divergence, not something origin introduced.
- **No merge blocker found in this category.**

## 10. 48-Field Customer Contract Reconciliation

The 48-field figure (established authoritative in Phase 15, correcting an earlier "47" miscount) is unaffected by this reconciliation:

- Production RPC (`get_properties()`, live since Phase 14H): 48 columns, unchanged by anything in this phase.
- Local's CSV export: reads a subset of those 48 fields directly, plus derived/helper-function columns (see Phase 15's `CSV_HELPER_FUNCTIONS_NOT_DIRECT_COLUMN_READS` allowlist), all reconciled and tested.
- Origin's CSV export: identical to local's, **minus exactly one column**: `["Assessed/Value Field Source", p => assessedSourceLabel(p)]`. Every other column, in the same order, with the same accessor logic, is present in both.
- **The `assessedSourceLabel()` difference, evaluated directly:**
  - It is a presentation/labeling enhancement only — it does not change which underlying database column is read (`p.harvester_source`, already part of the 48-field contract) and does not add or remove a customer-visible field from the RPC or grants.
  - It changes the CSV contract by exactly one additional column header. A spreadsheet consumer who already parses the export by column position (not header name) would see one extra trailing-ish column; one who parses by header name is unaffected.
  - It does not change customer data-boundary semantics — no new column exposes anything beyond the 48-field grant.
  - It does not structurally conflict with origin's UI — it is a CSV-export-only change with no DOM dependency, and the merge-tree result (§7) shows it survives a merge intact alongside all of origin's shell work.
  - **This is a product decision, not a technical one: whether to keep the extra CSV column when the two frontends are unified.** Documented here for a human to decide (§15) — not decided in this phase.

## 11. Root/Public Mirror Analysis

Re-verified directly (not assumed) for every deployed-bundle file, on both branches and in the hypothetical merged tree:

| File | Local root==public? | Origin root==public? | Merged-tree root==public? |
|---|---|---|---|
| app.js | YES (`02de65be...`) | YES (`f8c6db26...`) | YES |
| explore.css | YES | YES | YES |
| index.html | YES | YES | YES |
| styles.css | YES | YES | YES |
| tx.html | YES | YES | YES |

The `sync-public-to-root.yml` mirror mechanism (confirmed functional in Phase 16, re-confirmed here) is not implicated by anything in this reconciliation. Origin's habit of committing root and `public/` by hand in paired commits (§6) rather than letting CI do it is a process quirk, not a defect — every commit examined kept the two copies identical. Worth a note to whoever performs the eventual push/merge: after the merge lands and is pushed, the very next `public/**`-touching push will trigger `sync-public-to-root.yml` normally, so no special handling is needed there.

## 12. File-Level Merge Matrix

| File | Local version | Origin version | Production relevance | Recommended action | Reason |
|---|---|---|---|---|---|
| `app.js` / `public/app.js` | Base + Phase 14A label fix | Base + reskin + app-shell rebuild | High (customer-facing data display) | MAY BE RECONCILED — merge automatically via git 3-way merge | Confirmed conflict-free (§7); combines cleanly |
| `index.html` / `public/index.html`, `tx.html` / `public/tx.html`, `styles.css` / `public/styles.css`, `explore.css` / `public/explore.css` | Unchanged since merge base | Reskinned + app-shell markup/styles | Medium (UI only, no data contract) | MAY BE RECONCILED — take origin's version (local made no changes, so this is a fast-forward for these files, not a real merge) | No local edits to reconcile against |
| `harvesters/governance/*.py`, `docs/*governance*`, `docs/*provenance*`, `tests/test_source_governance.py`, `tests/test_provenance_integration.py`, `tests/test_customer_api_enforcement.py` | Full Phase 10A/10B/11/12 implementation | Does not exist | High (security/legal) | MUST PRESERVE | Origin has no competing version; pure addition |
| `scripts/migrations/005_customer_safe_properties_projection.sql`, `005a_close_direct_properties_grant.sql`, `schema-v9-dor-use-code.sql` | Live-verified production migrations | Does not exist | Critical (already applied to production) | MUST PRESERVE (as historical record — do not re-run, see §13) | Origin has no competing version |
| `docs/production-data-contract.md`, `docs/phase-13` through `phase-16` docs | Full audit trail | Does not exist | High (institutional record) | SHOULD PRESERVE | Origin has no competing version |
| `tests/vendor/supabase-stub.js` | Fixed (Phase 15's `rpc()` addition) | Does not exist (origin doesn't touch `tests/` at all) | High (regression-test integrity) | MUST PRESERVE | Origin has no competing version |
| `tests/run_test.mjs` | Unchanged since merge base; asserts against the OLD DOM (`#mapBtn`, single-page layout) | Does not exist as a competing version, but is now **incompatible** with origin's new DOM | Medium (test coverage, not production) | HUMAN DECISION | See §17: this suite needs updating to exercise whichever UI ships, and that update is coupled to the product decision in §15 |
| `.github/workflows/python-governance-test.yml` | Added (Phase 10B) | Does not exist | Medium (CI) | MUST PRESERVE | Origin has no competing version |
| `.github/workflows/sync-public-to-root.yml`, `.github/workflows/playwright-test.yml`, `.github/workflows/harvest-and-sync.yml` | Unchanged since merge base | Unchanged since merge base | Medium (CI/deployment) | MAY BE RECONCILED (no-op — identical on both sides) | No divergence |
| `harvesters/texas_harvester.py`, `scripts/sync-texas-to-supabase.py` | Extended (pre-existing local work, not part of Phase 10-16's headline scope but included in the local-only diff) | Does not exist | Medium (backend feature) | MUST PRESERVE | Origin has no competing version |

No file exists where both branches wrote materially different, competing implementations of the same functionality — the one near-miss (`app.js`) is additive on both sides, not competing.

## 13. Database Migration Status

Explicitly documented, per this phase's instructions, to prevent a human from re-running anything already live:

- **schema-v9-dor-use-code.sql: LIVE** (applied per Phase 14F).
- **005_customer_safe_properties_projection.sql: LIVE** (applied and Gate-B-verified per Phase 14H).
- **005a_close_direct_properties_grant.sql: LIVE** (applied and Gate-B-verified per Phase 14H).

**Do not rerun any of these against production.** They are preserved in the repository as the historical record of what was applied and how, not as pending work. No local migration file is dangerous to replay in the sense of being stale-but-committed (unlike the historical `bid_list`/certificate incidents CLAUDE.md documents) — these three are confirmed live via direct role-simulation queries in Phase 14H, not merely "committed and assumed run." `origin/main` contains no migration files at all, so there is nothing on that side to reconcile against.

## 14. Production Deployment Plan (human-executable, not executed here)

1. Preserve current `origin/main` (no action needed — it already exists and is untouched by this phase).
2. From a machine/session with real push credentials, create a reconciliation branch off `origin/main` (e.g., `reconcile-phase10-16`).
3. Merge this sandbox's local `main` (HEAD `5a810fa`) into that branch — or the reverse — using a real `git merge` (not `--squash`, to preserve the phase-by-phase commit history documented in §5). Given §7's `git merge-tree` result, this is expected to apply without manual conflict resolution; if the live merge disagrees with that computed result (e.g., because further origin commits landed after this phase's fetch), re-run the same `git merge-tree` check first.
4. Resolve the one product decision from §15 (keep or drop `assessedSourceLabel()`'s CSV column) as part of the merge commit, not silently.
5. Run the full local test suite (`pytest tests/python/ -q`) — expect 173/173 (this phase's number; verify it hasn't regressed).
6. Verify the root/`public/` mirror invariant still holds post-merge for all files in the `sync-public-to-root.yml` `FILES` list (this phase's `git merge-tree` inspection already shows it does, at the tree level).
7. Update `tests/run_test.mjs` (and any fixtures it depends on) to exercise the merged DOM — specifically the `#mapBtn` → page-router change and any other shell-structural difference not yet inventoried by a test — before trusting the Playwright suite's result on the merged code. Do not delete or weaken existing assertions to make this pass; extend them to cover the new shell.
8. Re-run the (now-updated) Playwright suite against the merged frontend, built the same way `.github/workflows/playwright-test.yml` builds its throwaway serve directory.
9. Verify the RPC path (`get_properties`), the 48-field contract, and the absence of `ledger_type`/`fdor_enriched_at` from any customer-facing surface, on the merged code — mechanically the same checks Phase 15 already automated.
10. Verify the CSV export contract end to end, including whatever was decided on `assessedSourceLabel()` in step 4.
11. Push the reconciliation branch and open it for review (do not push directly to `main` without review, given the scale of both sides' changes).
12. After merge to `main`, a normal push-triggered `sync-public-to-root.yml` run (or the merge itself, if it already updated both root and `public/`) keeps the two in sync — no special-casing needed.
13. Deploy via Cloudflare Pages' normal push-triggered flow (no manual deploy step exists in this project's architecture).
14. Verify the live app.js hash matches the merged commit's `app.js` content-hash.
15. Verify live authentication behavior (sign-up/approval gate) is unaffected — neither branch touched `checkApprovalAndEnter()` or the `profiles`/RLS flow.
16. Verify Florida and Texas regression manually or via the updated Playwright suite (both ledgers, both states).
17. Re-verify the security boundary live (the same role-simulation queries Phase 14H used).
18. Only after all of the above, resume normal phase-based development (e.g., a hypothetical Phase 18).

This plan intentionally does not fabricate exact CLI commands dependent on unknown branch names, remote URLs, or credentials this sandbox does not have — those specifics belong to whoever executes it with real push access.

## 15. Human Decision Points

Separated explicitly by kind, per this phase's instructions:

**Mechanical reconciliation** (no product/security judgment needed — git already proved these merge cleanly):
- Merging `app.js`/`public/app.js`'s two independent change sets.
- Taking origin's `index.html`/`tx.html`/`styles.css`/`explore.css` wholesale (local made no competing edits).
- Carrying forward every local-only backend/governance/docs/tests file unchanged (origin has no competing version of any of them).

**Product decisions:**
- Which UI direction ships: this checkout's untouched mobile-first ledger UI, or origin's new desktop dashboard/nav-rail/table-view/persistent-detail-panel app shell. The merge preserves both code paths harmlessly (origin's shell code is guarded and additive), but a human should decide whether the new shell becomes the actual default experience, stays behind a toggle, or something else — this is a UX call, not a technical one.
- Whether to retain `assessedSourceLabel()`'s CSV column (`Assessed/Value Field Source`) now that the two frontends are being unified (§10).
- Whether origin's app-shell changes (dashboard stats, table view) should be exposed on every account or gated somehow — no gating exists in either branch today; this is worth a conscious decision rather than defaulting to "on for everyone" by merge accident.

**Security decisions:**
- None identified as open. The security boundary (grants/RLS/RPC/provenance) is untouched by origin's changes and is not implicated by anything origin added. The one item that looks security-adjacent — the pre-existing `select("*")` RPC-missing fallback — is unchanged by either branch and was already a known, accepted, documented limitation before this divergence existed; it is not a new decision this reconciliation introduces.

## 16. Do Not Change the Live Product

Confirmed: no deployment, no Supabase change, no Cloudflare change, no GitHub push, no workflow dispatch, and no production database write occurred during this phase. The one write this phase performed was `git merge-tree --write-tree`, which creates an orphaned tree object in the local object database — it does not move any ref, does not touch the working tree, and has no effect on `origin` (confirmed via `git status` and `git rev-parse HEAD` immediately after, both unchanged).

## 17. Tests

- `pytest tests/python/ -q`: **173 passed**, 0 failed — full suite, including every governance/provenance/customer-API-enforcement/production-data-contract/Phase-15/Phase-16 test. No test was modified, weakened, or deleted this phase.
- Playwright regression suite (`tests/run_test.mjs`) run against **this checkout's** built frontend (the same throwaway-serve-directory build `.github/workflows/playwright-test.yml` performs): same 2 pre-existing cosmetic mismatches as Phases 15/16 (`ledgerTitles` branding string, `csvDownloadFilename` prefix) — no new failures.
- Playwright regression suite run against **`origin/main`'s** built frontend (same build process, pointed at a fetched copy of `origin/main`'s `public/` tree): progressed through roughly 50 assertions — property loading, county grouping/expand-collapse, bid-amount filtering, sort options, the "gone" status chip, theme toggle, property-type filter chips — all consistent with a working, data-correct frontend, before failing on `page.click('#mapBtn')`, a locator origin's app-shell rebuild replaced with a nav-rail page router (`showPage("map")`). **Classified, not silently patched around:** this is a real test/DOM incompatibility between this repo's existing Playwright suite and origin's new shell, not a defect in origin's frontend and not something to paper over by modifying the test to fit an unmerged branch. It confirms the deployment plan's step 7 (§14) is necessary before the suite can be trusted against the merged/shipped result.

## 18. Risks

- The one substantive open risk is process, not technical: whoever performs the real merge must actually run `git merge-tree` (or a real trial merge) against the *current* `origin/main` at push time, since further origin-side commits could in principle land between this audit and the actual push. Nothing in this phase's evidence expires, but it is a snapshot as of `origin/main` HEAD `f574f7f`.
- The Playwright suite gap (§17) means a merged/shipped frontend cannot be trusted as regression-tested by this suite until it's updated for the new DOM — a real but bounded and already-scoped risk, not a blocker to reconciliation itself.
- The pre-existing `select("*")` RPC-fallback path (§8), while unchanged and equally present on both branches, remains a standing (not new) latent risk worth someone's attention independent of this reconciliation.

## 19. Hard Blockers

None found. No technical incompatibility exists between the two histories at the file, git-merge, or database-contract level.

## 20. Tests

(See §17 — included here per the requested section list; not duplicated with different content.)

## 21. Final Readiness Decision

**READY_WITH_HUMAN_DECISIONS.** The merge is technically clean and verified (not assumed) at the git and database-contract level. What remains before a human should actually execute the push/merge is: (1) the UI-direction and CSV-column product decisions in §15, and (2) updating the Playwright suite for origin's new DOM before trusting it as a post-merge regression gate (§14 step 7, §17). Neither is a technical blocker to the merge itself — both are decisions and follow-up work a human should make deliberately rather than have decided implicitly by whichever way an automated merge happens to fall.

---

PHASE 17 RESULT

Status: READY_WITH_HUMAN_DECISIONS
Deployment: NOT_SYNCHRONIZED (unchanged from Phase 16 — origin/main remains what's live; this phase performed no deployment action)
Local HEAD: 5a810fae076e6b735358bbc4cf0f291fa5099516
Origin/main: f574f7fbf21d60ac4561bd1ae17bd23c9b822f4a
Merge Base: cc7f13959aa651b53e4ed860a1915be8b96a693c
Local-only commits: 15
Origin-only commits: 6

Security boundary: PRESERVED — origin's changes do not touch RPC calls, grants, RLS, authentication, or any internal-field exposure; verified directly against origin's actual app.js content, not assumed
48-field contract: PRESERVED — origin's CSV export is a strict subset of local's (missing one presentation-only column, `Assessed/Value Field Source`); no field outside the 48-column contract is read by either branch
Database compatibility: COMPATIBLE — origin/main's frontend calls the identical, unmodified get_properties() RPC and can run against the post-005/005a production database with no changes
Frontend compatibility: MERGEABLE — a real `git merge-tree` computation resolved all files, including the one file both sides touch (app.js), with zero conflicts
Mirror compatibility: INTACT — root/public byte-identity holds on local, on origin, and in the hypothetical merged tree, for every deployed-bundle file

Recommended strategy: Option A (merge origin/main into a new reconciliation branch built from local's history, preserving the full Phase 10-16 commit sequence) — confirmed conflict-free by git merge-tree; preferred over cherry-picking (unnecessary given zero conflicts) or a from-scratch manual reconciliation (unnecessary given git's clean automatic result)

Human decisions required:
- Which UI ships as the default experience: this checkout's mobile-first ledger UI, origin's new desktop app shell, or both (the merge preserves both harmlessly, but indefinite duplication is not a real end state)
- Whether to keep the assessedSourceLabel() CSV column now that the two frontends are being unified
- Whether origin's new dashboard/table-view features should be gated or on for everyone

Technical blockers: NONE

Tests: 173/173 (pytest); Playwright suite unchanged-pass against local build (2 known pre-existing cosmetic mismatches, no new failures); Playwright suite run against a built copy of origin/main's frontend progressed through ~50 assertions before hitting a DOM-structural incompatibility (#mapBtn removed by origin's page router) — classified as a test-suite update needed before merge, not a defect in either branch
Commit: (this phase's commit hash — see below)
Push: NO
Production mutations: NONE

NEXT RECOMMENDED ACTION: A human with real push/merge credentials should create a reconciliation branch, perform the merge (expected conflict-free per §7's verified git merge-tree result), decide the three product questions in §15, update tests/run_test.mjs for origin's new DOM before trusting it as a post-merge gate, and only then push and let the existing Cloudflare Pages deployment pipeline take over. No further automated phase should attempt the merge itself.

HARD STOP
