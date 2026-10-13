# Launch readiness: baseline (2026-10-13)

Read-only audit of `main` and the open PRs. No migration applied, no production
data written, no Stripe configured, no source enabled, nothing merged or deployed.

## Repository and PRs

- `main`: `e617364` at the time of audit (`origin/main`).
- PR #129 (auth: Google / Apple / Microsoft, token_hash links): **merged** 2026-10-10 (head `41e6fc8`).
- PR #86 (controlled paid beta: entitlements, Stripe functions, paid-beta scope): **merged** 2026-10-05 (head `aff9366`).
  The brief's premise that these are open is stale.
- Open PRs at audit time: #144 (parcel boundary, dormant; head `b4f638d`, CI green),
  #143 (topbar / countdown hotfix), #141 (filter drawer), #130 (record trust benchmark, head `610002f`),
  #121, #92, #89, #83, #81, #66, #22, #21, #20, #19, #18, #17, #16, #15. Several are older than the current
  product and should be triaged, not merged blind.

## Production migrations (Supabase migration list, read-only)

Applied: 009 through 014 (as `schema_v9_dor_use_code` onward), 017, 018, 019, 020, 021, 022, 023, 025, 026.

**Not applied:** 015 (customer write privileges, account deletion), 016 (source health), 024 (customer
monitoring), 027 (commercial billing / entitlements), 028 (list payload), 029 (research workspace),
030 (approval notifications), 031 (publication gate), 032 (parcel boundaries, PR #144).

Consequences for launch: without 031 customers see the pre-gate read path; without 027 billing has no
tables; without 030 approval e-mails do not queue. Each needs an explicit owner decision.

## Test status on `main` (`origin/main`, clean extract)

- Node billing / approval / signup-password: **76 / 76 pass**.
- Python full suite, live PostgreSQL attached: **2544 passed, 107 skipped, 1 failed** (`test_c02`,
  which runs `git ls-files` and cannot run from an extracted archive; it passes inside the repository).
- Browser suite: last full run on the parcel branch was 1246 / 1246 checks with the same 8 pre-existing
  404 console errors (per-state ZIP / city label files). Not re-run on `main` in this audit.

## Unfinished or mismatched front-end flows (verified in code, not yet in a browser)

1. **Feedback loop does not exist.** No feedback form, no feedback table, no feedback endpoint on `main`.
   There is no approved write path for tester feedback. Needs an owner decision on storage and destination.
2. **Support e-mail is blank** in `config.js` (`supportEmail: ""`), so every "contact us" path has no destination.
3. **Billing is off** (`config.js` `billing.enabled: false`, `planName` and `priceDisplay` blank). The
   checkout and portal buttons therefore have no price to sell.
4. **Available gate is off** (`availableGate: "off"`): the acquisition-path gate is staged, not enforced.
5. **Publication mode is `preview`** in `config.js`: testers see records that customers would not.
6. **OAuth providers are empty** (`oauthProviders: []`): the Google / Apple / Microsoft buttons never render.
7. **Tester invitations cannot be counted from this session.** The Gmail connector returned Forbidden on
   the sent-mail search, so delivered / bounced / suppressed counts are unknown. No conversion is claimed.

## Safety constraints (unchanged)

- Do not apply migrations 015, 016, 024, 027–032.
- Stripe live mode, paid access, production feature flags, restricted sources and new harvests stay off.
- Source approval decisions are not altered by this work.
