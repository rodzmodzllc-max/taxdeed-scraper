# TAXACQ launch-readiness matrix

Status date: 2026-10-13. Evidence is cited from this repository, the GitHub
PRs, or a read-only database query. Nothing here is a claim about production
beyond what those sources show.

Four approval gates are kept apart:

- **Code readiness:** the branch passes its tests and the behaviour is reviewed.
- **Source permission:** written or licence-level permission to store, display, or use a source.
- **Production configuration:** keys, domains, redirect URLs, price IDs, migrations applied.
- **Authorization to launch:** the owner's decision to open a tier to people.

| # | Category | Current status | Evidence | Remaining work | Decision or approval needed | Blocks closed beta? | Blocks paid beta? | Blocks general launch? |
|---|---|---|---|---|---|---|---|---|
| 1 | Customer-facing frontend | Landing on the List is in place (PR #155). Info bubbles cover the ledger headers only. Property-page questions still inline. | PR #155 browser suite on 3b4c81d (see report); Python 2,621 passed | Bubbles for property-page notes; full narrow-width pass; accessibility audit (not run this sprint) | Owner review of PR #155 | Partly (test with the existing pages is possible) | No | Yes |
| 2 | Authentication and account security | Sign-up, sign-in, reset flow tests exist (`tests/recovery_flow_test.mjs`). OAuth buttons show only for providers listed in `config.js`, which ships empty. | Repository tests; `config.js` `oauthProviders` empty | Browser pass of reset-link completion; provider setup if OAuth is wanted; custom domain verification | Owner: enable OAuth providers or not; confirm the domain | No, if OAuth stays off | No | Yes |
| 3 | Property accuracy and data trust | Record-origin labels are in PR #130 (not merged). Bid-bound fix in PR #153 (not merged). | PR #130 and #153 diffs; PR #130 reports a 2,230-pass Python run on its own base | Merge decisions for #130 and #153; production read-only sample check | Owner: which of #130's protections to keep | Partly | Yes | Yes |
| 4 | Official acquisition links | Links come from the data; none is constructed. Texas and other sources are per source. | `app.js` uses only harvested URLs (repository note) | Per-county verification of the link classification; no new links added in this sprint | Source review per county | Partly | Yes | Yes |
| 5 | Source permissions and legal | Permission gate on `main`. Interim permissions (#149, #150) merged. Paid-beta source set limited to five sources. Polygon storage for FDOR and Santa Rosa is not permitted by current terms (not read). | `docs/source-permissions.md`, `docs/interim-permissions.md`; main merge history | Written approvals for each paid-beta source; FDOR / Santa Rosa terms read; trade-name clearance | Owner and counsel, per source | Partly (closed beta on approved sources only) | Yes | Yes |
| 6 | Billing and Stripe | Billing is off. Refund and dispute handling is in PR #154 (not merged). Migration 033 drafted. Migration 027's SQL does not yet read refund or dispute holds. One monthly price is wired; no annual plan; no trial. | PR #154 Node suites: 45, 30, 22, 9 passed; `docs/billing-refund-dispute.md` | Update the SQL entitlement mirror; Stripe test-mode run; apply 027 and 033 only with approval; price decision | Owner: price, trial, and billing activation | No | Yes | Yes |
| 7 | Feedback and tester recruitment | Design written (`docs/tester-feedback-design.md`). No storage. Support dialog exists but its address is blank. | The design document | Destination decision; migration 034 drafting; panel | Owner: destination and triage owner | Partly | Yes | Yes |
| 8 | Database migrations | Applied in production (read-only `list_migrations`, by listed name): 005, 005a, 006, add_property_photo_url, create_property_photos_bucket, fdor_verified_field_expansion_009, flood_hazard_010, photo_provenance_011, expose_enrichment_in_get_properties_012, 013, 014, 017 to 023, 025, 026, plus schema_v9_dor_use_code. Not applied: 015, 016, 024, 027, 028, 029, 030, 031, 032 (publication side tables, on main), 033 (draft). | `list_migrations` (read-only), 2026-10-13 | Decide each unapplied migration; a dedicated decision for 027 | Owner approval per migration, after a scratch-database test | Partly | Yes | Yes |
| 9 | Production configuration and domain | `config.js` ships the Demo Google key without a domain restriction (documented) and a live MapTiler key. Custom domain not verified in this sprint. | `config.js`; CLAUDE.md notes | Restrict or replace the Google key; verify the domain and redirect URLs | Owner | Partly | Yes | Yes |
| 10 | Automated tests and manual verification | Final branches: landing 3b4c81d (browser and Python run; see report). Billing 27ddf26 (Node 106 passed; Python 2,692 passed, 116 skipped). `test_c02` passes in a real Git checkout (12 of 12). | Test output in this report | Manual device checks; screen-reader pass; accessibility audit | Owner decision on what counts as manual sign-off | No | Yes | Yes |
| 11 | Monitoring, error recovery, and support | Failed webhook events are recorded (`billing_events`). No alerting, no on-call route, no support queue. | `billing_events` design; no alert configured in repository | Alert on failed events; support route | Owner: support owner and response time | Partly | Yes | Yes |

## Counts this sprint could verify

- Accounts (read-only, production): 8 total, 8 approved, 1 admin, 0 pending.
  This is account-level. It cannot separate testers from customers, because
  `access_grant` is not in production until migration 027 is applied.
- Invitations sent, delivered, bounced, suppressed, and completed sessions: not
  available. The one Gmail search attempted in this sprint returned Forbidden.

## Not verified in this sprint

- Production property data, sale outcomes, and links.
- Any live Stripe configuration (none was touched).
- The custom domain, redirect URLs, and OAuth provider setup.
