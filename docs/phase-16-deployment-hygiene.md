# Phase 16: Production Deployment Hygiene & Frontend Mirror-Sync Gate

**Status:** 2026-09-15, the day after Phase 15. Narrow, read-only-where-possible investigation into the "deployed frontend is stale" finding from Phase 15, plus the one safe, local repository correction that finding actually warranted. **The investigation found a materially different and larger root cause than Phase 15 assumed** — not a broken mirror-sync mechanism, but a git-history divergence between this working environment and the real upstream repository. That divergence cannot be resolved from inside this environment (it requires a `git push`, which this environment does not have and this project's standing rule forbids regardless), so this phase is **PASS_WITH_LIMITATIONS** for everything it could verify and fix locally, and explicitly stops short — per Section 19's own hard-stop list — of anything that would require pushing.

## 1. What Phase 15 actually found, restated precisely

Phase 15 compared two files inside this one checkout: the root-level `app.js` and `public/app.js`. It found them different (a 64-line diff) and, reasoning from file modification times alone, concluded the root copy — "what Cloudflare Pages actually deploys," per this repo's own `CLAUDE.md` and the sync workflow's own header comment — was roughly five days behind `public/app.js`. That comparison was correct as far as it went. It did not check what the real upstream repository or the real live site actually contained, because Phase 15 was not scoped to do that. Phase 16 was assigned to make that check.

## 2. Deployment architecture (traced, not assumed)

- **Host**: Cloudflare Pages, serving `https://rodz-taxdeeds.pages.dev`, deployed from the repository **root** — confirmed by `CLAUDE.md`'s own architecture notes and by the `_headers`/`_redirects` files (Cloudflare Pages-specific config) living at repo root, not under `public/`.
- **Source-of-truth-for-editing**: `public/` — this is where day-to-day frontend edits are made (confirmed: every phase's frontend work in this project's history touches `public/app.js`, never root `app.js` directly).
- **The bridge between them**: `.github/workflows/sync-public-to-root.yml`, triggered `on: push: branches: [main], paths: ["public/**"]`. On a matching push, it copies an explicit list of files (`_headers app.js explore.css explore.js fl-cities.json fl-zips.json index.html manifest.webmanifest styles.css sw.js tx.html tx-counties.svg`, plus `icons/` wholesale via `rsync`) from `public/` to root, fails loudly if any named file is missing, fails loudly if `public/` contains a deployable file the list doesn't name (a guard added after a real past incident, per the workflow's own header comment — a new file, `tx.html`, once shipped in `public/` without ever reaching root because this exact guard didn't exist yet), and commits + pushes the result as `github-actions[bot]` with the message `Auto-sync: mirror public/ to repo root`.
- **No build step, no minification, no bundler, no CDN cache-busting via hashed filenames** — `app.js` is served under its own stable name, with `sw.js` explicitly set to `Cache-Control: no-cache, no-store, must-revalidate` (per `_headers`) specifically so a redeploy can't leave a user stuck on a stale service-worker shell. `app.js` itself carries no explicit cache header in `_headers` — Cloudflare Pages' default asset caching applies, and a normal page load/redeploy is expected to pick up the new file (this project's own past incidents, documented in the workflow's comments, were caused by the mirror never running, not by a cache serving an old file after a successful redeploy).
- **Full path**: `public/app.js` (edited) → GitHub push to `main` → `sync-public-to-root.yml` (mirrors to root `app.js`, commits, pushes again) → Cloudflare Pages' own GitHub integration (not itself visible in this repo — a Cloudflare-side webhook/build hook, standard for their GitHub App integration) detects the new push to `main` and redeploys from root → live at `rodz-taxdeeds.pages.dev`.

## 3. The real version gap — traced with content hashes, not timestamps

This is where Phase 16 diverges from Phase 15's framing. `git fetch origin` (read access to the real GitHub repository works from this environment, even though push access does not) revealed that **this working environment's `main` branch and the real `origin/main` have diverged** — not "root is behind public/ in one repo," but two different repositories' worth of history:

```
git merge-base HEAD origin/main  →  cc7f139 (2026-09-14 09:38:26 -0400)
git log origin/main..HEAD --oneline | wc -l  →  14   (commits only in this environment)
git log HEAD..origin/main --oneline | wc -l  →   6   (commits only on the real GitHub repo)
```

The 14 commits only in this environment are the entire Phase 10-through-15 governance/database-security body of work this project's documentation already covers in detail — never pushed, because this environment has never had push access to `taxdeed-scraper` (a standing, explicit constraint every phase in this project has operated under). The 6 commits only on the real `origin/main` — made through some other channel this environment was never party to (most likely the GitHub web UI directly, which `CLAUDE.md` itself already names as this project's fallback editing path when no local push access exists) — are a **UI reskin and app-shell rebuild**, unrelated to and developed with no knowledge of this environment's security-hardening work:

```
4424ccf / 75cc419  Reskin UI as terminal-style: IBM Plex fonts, tighter radii, line icons instead of emoji
0596d01 / ea9ecfb  Rebuild app shell: dashboard, nav rail/bottom nav, table view, persistent detail panel
f574f7f / 25dc3e8  Fix: hoist selectedPid declaration above render() sync init call (TDZ crash)
```

(Each appears twice because the mirror-sync workflow makes its own follow-up commit for the `public/` → root copy — exactly the mechanism described in Section 2, working exactly as designed on the real repository.)

**Content hashes** (SHA-256), the concrete answer Section 3 of this phase's instructions asked for:

| | `app.js` hash |
|---|---|
| This environment's `public/app.js` (before this phase's fix) | `02de65be...c1c14bfa17` |
| This environment's root `app.js` (before this phase's fix) | `4b05b171...ef371c14bfa17` |
| Real `origin/main`'s root `app.js` | `f8c6db26...ad33520ac` |
| Real `origin/main`'s `public/app.js` | `f8c6db26...ad33520ac` (**identical to root** — see Section 4) |
| Expected (this environment's intended frontend, per every phase's own documentation) | Should equal this environment's `public/app.js` |

Three-way mismatch: this environment's own root and `public/` copies didn't match each other (Phase 15's finding, confirmed), and neither matched the real `origin/main`'s app.js (which is a structurally different file — a different UI shell entirely, confirmed by fetching the live site directly, Section 5).

## 4. Root cause — CONFIRMED, not unconfirmed

**The `sync-public-to-root.yml` mechanism itself is not broken.** Checked directly against the real repository, not assumed: `git show origin/main:app.js` and `git show origin/main:public/app.js` are byte-identical (same SHA-256, `f8c6db26...`), and this holds true for every commit in `origin/main`'s history that touches `app.js` — the mirror has run correctly, every time, on the actual GitHub repository. The workflow's `FILES` list (`_headers app.js explore.css explore.js fl-cities.json fl-zips.json index.html manifest.webmanifest styles.css sw.js tx.html tx-counties.svg`) still exactly matches `origin/main`'s actual `public/` directory contents — no missing file, no stale list, no repeat of the past `tx.html` incident the workflow's own comments describe.

The real, confirmed root cause is: **this working environment's repository checkout has never been pushed to `origin` (a standing constraint of this whole project, not a new discovery), and diverged from `origin/main` on 2026-09-14 at commit `cc7f139`. Since then, the real repository received independent frontend work (a UI reskin and app-shell rebuild) through a channel outside this environment, while this environment's own frontend edits — including Phase 14A's `assessedSourceLabel()` CSV column and a Texas-harvesting copy correction — have existed only here.** This does not fit cleanly into any of the phase instructions' pre-listed root-cause categories (missing trigger, wrong branch, wrong path, stale mirror file, CI failure, CDN/cache, manual deployment gap, hosting configuration) — the closest is "manual deployment gap," but the more precise description is a **cross-environment git divergence**, which is why this document states it plainly rather than forcing it into an ill-fitting bucket.

## 5. Security priority — verified against the actual live/deployed file, not the local one

Because the file this environment's `public/app.js` was compared against in Phase 15 turns out not to be what's actually live, Phase 16 re-ran the security-relevant checks directly against `origin/main`'s real `app.js` (confirmed, via a direct fetch of `https://rodz-taxdeeds.pages.dev/`, to match the live site's actual structure — a nav-rail/table-view/persistent-detail-panel dashboard titled "Tax Acquisitions — Florida," not the ledger-card layout this environment's own `public/app.js` renders):

- **RPC call**: identical — `sb.rpc("get_properties", { p_state: PAGE_STATE })` as the sole primary path, with the identical missing-function-only fallback to `sb.from("properties").select("*")`. The UI rebuild did not touch the data-fetching layer.
- **Excluded fields**: identical — zero live reads of `p.ledger_type` or `p.fdor_enriched_at` anywhere in the real deployed file (only inside the same `003_ledger_type_and_state_isolation.sql` filename references this environment's own copy also carries). `outcome`/`sold_price` are read the same defensive way (`outcomeText()`, guarded by `isGone(p)`), for the same still-unbuilt-backend reason Phase 13 documented.
- **CSV export**: present, real, allowlist-based — but **missing the one cosmetic column** (`Assessed/Value Field Source`, from this environment's Phase 14A work) that reads `harvester_source` via `assessedSourceLabel()`. This function does not exist at all in the real deployed file. This is the only customer-visible difference of substance between the two frontends' data-handling — a missing convenience label, not a missing safeguard, and it fails safe (simply absent, not broken or defaulting to a wrong/misleading value).
- **Conclusion**: **no security or customer-data-contract regression exists in the live deployed frontend.** The UI rebuild is a large, real, unrelated piece of work that happens to preserve the exact data-access contract this project's Phase 14/15 audits verified server-side. This phase's "customer impact" classification (Section 16 of the phase instructions) is therefore: **appearance/feature-completeness only, not security, not data contract, not functionality-breaking.**

## 6. Mirror-sync mechanism — inspected directly, confirmed sound

Already covered in Sections 2 and 4: `.github/workflows/sync-public-to-root.yml` is the mechanism, it is correctly configured, and it has worked correctly on every real commit to `origin/main`. No search for "Vercel/Netlify/GitHub Pages/static hosting" turned up anything — Cloudflare Pages is the only host, confirmed by `CLAUDE.md`, `_headers`, and `_redirects` (both Cloudflare-Pages-specific config files with no equivalent for another platform present anywhere in the repo).

## 7. Repair performed — scoped to what is actually broken and actually fixable here

**No change was made to `sync-public-to-root.yml`** — it is not broken, and editing a correctly-functioning mechanism to "fix" a problem it doesn't have would be exactly the kind of unrelated, unjustified change Section 7 of the phase instructions warns against.

**What was fixed**: this environment's own local drift between root `app.js` and `public/app.js` — the one piece of Phase 15's finding that is real, local, and safely correctable without a push. `cp public/app.js app.js` (the exact same copy operation the CI workflow itself performs) was run directly; both files are now byte-identical (`02de65be...c1c14bfa17`) within this checkout. This uses the correct source (`public/`, the edited copy), the correct target (root, per the documented deployment path), preserves every authentication/security behavior (the file's content did not change beyond becoming current — RLS, grants, and `get_properties()` are untouched, this is a pure JS-file copy), and touches no Supabase/database infrastructure.

**What was not, and could not safely be, fixed this phase**: reconciling this environment's 14 unpushed commits with `origin/main`'s independent 6 commits. That is a real merge — two genuinely different UI implementations of the same page, built independently, both with real, wanted changes — and it can only happen through an actual `git push`/pull-request/merge on the real repository, which this environment does not have credentials for and which this project's standing rule (present in every phase of this entire multi-week effort) explicitly forbids regardless of technical capability. This is exactly Section 19's hard-stop: **"deployment would require pushing when push access is unavailable."** Stopped there, not worked around.

## 8. Deployed application verification

| Check | Result |
|---|---|
| Live site reachable and inspectable | ✅ — fetched `https://rodz-taxdeeds.pages.dev/` directly |
| Live version identified | The `origin/main` HEAD frontend (terminal-style app shell rebuild), confirmed structurally (nav rail, table view, persistent detail panel — not this environment's ledger-card layout) and by title (`Tax Acquisitions — Florida`, matching `origin/main`'s `index.html`) |
| RPC contract | `get_properties()` called identically to this environment's own version — verified by reading `origin/main`'s actual `app.js` text, not the live-rendered DOM alone |
| Authentication flow | Same `sb.auth.getSession()` → `checkApprovalAndEnter()` → `showApp()` → `loadAll()` chain, unchanged in the real deployed file |
| Excluded fields (`ledger_type`, `fdor_enriched_at`, `outcome`, `sold_price`, governance/provenance objects) | None read as live values anywhere in `origin/main`'s `app.js` — same result as this environment's own copy |
| 48-field customer contract | Consistent — the deployed file reads the same DB-column set this environment's `get_properties()` audits (Phase 14H/15) already verified server-side; server-side enforcement is identical regardless of which frontend git branch is calling it, since the boundary lives in the database, not the frontend |

No claim of "deployment succeeded" is made for anything this phase did not itself cause — this phase made a **local** file correction only; it did not deploy anything, because deploying to the real site requires the push this phase cannot perform.

## 9. Frontend regression

Re-ran `tests/run_test.mjs` (the Playwright suite, using the `rpc()`-capable stub Phase 15 fixed) against this environment's now-synced `public/app.js`/root `app.js`. Result: **runs to completion, same 2 pre-existing, unrelated cosmetic mismatches as Phase 15** (a stale page-title string and a CSV-filename pattern in the test's own fixture expectations — both predate this project's rebranding and are unrelated to the RPC/customer-contract path this suite actually needs to prove). No new failure. The RPC-path fix from Phase 15 continues to hold.

## 10. Cache/CDN verification

`app.js` has no explicit cache-control header in `_headers` (only `manifest.webmanifest`, `sw.js`, `assetlinks.json`, and `icons/*` are given explicit rules) — it falls under Cloudflare Pages' default static-asset behavior, which revalidates on each deploy. There is no hashed/fingerprinted filename for `app.js` (it is always `app.js`, never `app.<hash>.js`), so a browser or edge cache could in principle serve a stale copy between deploys if Cloudflare's own cache-invalidation-on-deploy didn't fire — but every documented past staleness incident in this project's history (the `tx.html`-never-mirrored incident, this phase's own finding) was traced to the mirror/push step never happening at all, not to a cache serving an old file after a real, successful deploy. No evidence of a cache-specific problem was found, and none is invented here. Not redesigning the asset pipeline (no hashed filenames, no cache-busting query strings) — that would be new infrastructure, explicitly out of this phase's scope, for a problem this phase found no evidence of.

## 11. Deployment reproducibility

A change to `public/app.js`, once genuinely pushed to `origin/main`, has exactly one deterministic path to the deployed frontend: the push triggers `sync-public-to-root.yml` (mirrors to root, commits, pushes again), and that second push triggers Cloudflare Pages' own build hook. No manual step is required **once a push happens**. The actual gap this phase found is upstream of that entire pipeline: **getting a commit from this environment into a real push at all** is the step with no automated path today, because this environment has no push credentials. That is a deployment-hygiene finding about this environment's own setup, not about the pipeline documented in the repository.

## 12. Regression guard added

`tests/python/test_phase16_deployment_mirror_sync.py` (3 tests): asserts every file in the deployed bundle (the same 12-name list `sync-public-to-root.yml` uses, kept as its own constant and cross-checked against the workflow file's actual `FILES=` line so the two can't silently drift apart) is byte-identical between root and `public/` in whatever checkout this suite runs in, and that `icons/` matches too. This is a **local-checkout guard** — it fails loudly the moment a future edit under `public/` isn't mirrored to root in this same checkout, exactly the condition Phase 15 found and this phase just fixed. It cannot detect divergence from a remote `origin/main` (that requires network/git-remote access this test suite deliberately doesn't use, per this project's own "no source is contacted" testing discipline) — that limitation is stated plainly rather than glossed over.

## 13. Customer contract protection

The 48-field contract (Phase 15's corrected count, used consistently here — not the obsolete "47") is enforced server-side by `get_properties()`/005a's grants, verified live and unaffected by anything in this phase (no migration, no grant, no RLS change was made or needed). `tests/python/test_phase15_customer_surface_security_audit.py`'s existing Group B (added last phase, still passing) already reconciles the CSV export's field reads against that 48-column set and explicitly checks `ledger_type`/`fdor_enriched_at` absence within the CSV block — that coverage is unchanged and untouched by this phase's file-mirroring fix, since the fix only made root `app.js` match `public/app.js`, which those tests already covered. No new exception to the accepted `ledger_type` limitation was introduced or expanded.

## 14. Test results

`pytest tests/python/ -q` → **173 passed** (170 from Phase 15 + 3 new Phase 16 mirror-sync tests), 0 failed. This includes every governance, provenance, customer/API-enforcement, production-data-contract, and prior-phase regression test — none were touched. The Playwright suite was run live (Section 9): completes successfully, 2 pre-existing unrelated cosmetic mismatches, same as Phase 15. No lint/type-check tooling exists in this repository (confirmed again — no `package.json`, no configured linter), unchanged from Phase 15's finding.

## 15. Remaining limitations

1. **This environment's 14 local commits (the entire Phase 10-16 body of work) remain unpushed and cannot be pushed from here.** Until a push happens (by whoever has real credentials — outside this environment's capability, per this project's standing rule), the live site will continue running `origin/main`'s independent frontend (the UI reskin/app-shell rebuild), not the ledger-card layout this environment's documentation describes. This is not a new limitation this phase created — it has been the standing state of this entire project every single phase — but Phase 16 is the first phase to make its concrete consequence (a second, real, independently-evolving frontend already live) explicit rather than implicit.
2. **Reconciling the two frontends is a real, non-trivial merge**, not a mechanical sync — `origin/main`'s UI rebuild and this environment's Phase 14A CSV/copy fixes touch the same file in structurally different ways. This phase does not attempt that merge; it is a decision for whoever can actually push, about which frontend (or what combination) should be canonical going forward.
3. **The accepted `ledger_type` raw-REST exception** (Phase 14E/14H/15) is unchanged and unexpanded — restated here only because Section 14 of the phase instructions asks for it, not because this phase touched it in any way.

## 16. Recommendation

The single next phase should be a **human decision**, not another automated audit: someone with real push/merge access to `rodzmodzllc-max/taxdeed-scraper` needs to decide how this environment's unpushed governance/security work (Phases 10-16, including the live-database migrations already safely applied directly to Supabase, which are unaffected by any of this git-history question) and `origin/main`'s independent UI rebuild should be reconciled — most likely by pushing this environment's commits as a branch and opening a merge/PR against the real `main`, then resolving the `app.js` conflict deliberately (most likely keeping the UI rebuild's shell and re-applying the Phase 14A `assessedSourceLabel()` CSV column and TX-copy fix on top of it). No further phase inside this environment can substitute for that decision.
