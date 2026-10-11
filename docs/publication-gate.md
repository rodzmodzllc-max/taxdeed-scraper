# Mandatory acquisition-path gate for customer publication (2026-10-10)

Stacked on `docs/ledger-eligibility.md` (PR #134). Nothing in this PR
writes to production, applies a migration, dispatches a workflow, approves a
source, activates a vendor, retries LGBS or touches a blocked vendor.
Migration 031 is written, live-tested on a scratch PostgreSQL, and **NOT
applied**.

## The rule

Harvested data is not customer inventory. A record reaches a customer only
when every gate passes, in this order, and the first failing gate names the
state the record is left in:

| # | Gate | Passes when | Fails into |
|---|---|---|---|
| 1 | **Source** | the registry's publication decision for the row's source is APPROVED or APPROVED_GRANDFATHERED (after the admin reviews `publication_gate.py` applies) | `ADMIN_ONLY_SOURCE_REVIEW` (SOURCE_UNREVIEWED / SOURCE_RESTRICTED / SOURCE_BLOCKED / SOURCE_UNKNOWN) |
| 2 | **Rules** | `data/state_ledgers.csv` eligibility for (state, ledger) is OFFERED, or COUNTY_DEPENDENT with the row's county in the ledger's coverage (`state_verification.county_coverage`) | `ADMIN_ONLY_SOURCE_REVIEW` (RULES_NOT_VERIFIED / RULES_NOT_OFFERED / COUNTY_NOT_COVERED) |
| 3 | **Validation** | state, county, ledger and an identifier (case / parcel / certificate) are present | `ADMIN_ONLY_SOURCE_REVIEW` (RECORD_INVALID) |
| 4 | **Path** | a credible acquisition path is documented (below) | `ADMIN_ONLY_NO_PATH` (PATH_MISSING / PATH_UNTRUSTED / PATH_NEEDS_REVIEW / PATH_UNAVAILABLE / PATH_NOT_FOUND) |
| 5 | **Freshness** | observed within the ledger's window (AUCTIONS 7 d, AVAILABLE 14 d, LIENS 7 d on `last_seen_at` else `updated_at`), the auction's sale date has not passed, county-level path evidence is at most 180 days old | `ADMIN_ONLY_STALE` (OBSERVATION_STALE / SALE_DATE_PASSED / PATH_STALE) |
| | all | | `CUSTOMER_PUBLISHED` |

A row whose lifecycle status is not `active` is `CLOSED` (reason NOT_ACTIVE).
`publication_progress` keeps the milestone reached - DISCOVERED,
RULES_VERIFIED, PATH_VERIFIED or CUSTOMER_PUBLISHED - beside the state, so an
admin sees how far a withheld row got. These eight states never replace the
lifecycle status (`status`, `inventory_status`): CLOSED follows the
lifecycle, it never drives it.

### What counts as a path, per ledger

- **AUCTIONS** - the record's own sale listing (`url_auction_kind = sale`,
  record scope) or the county's auction site (`county`, county scope): an
  https page that is not a bare homepage and not a search engine. A
  `property` / `info` link is not a path.
- **AVAILABLE** - the verified acquisition evidence for the row's (state,
  source, county) unit (`public/acquisition-evidence.json`, status VERIFIED:
  the evidence page, the application / bid form, the published steps), or a
  record-level typed path with an https process URL. A captured-but-unverified
  process is PATH_NEEDS_REVIEW; an unreadable page PATH_UNAVAILABLE; no page
  found PATH_NOT_FOUND.
- **LIENS & CERTIFICATES** - a record-level typed path, or the county's own
  certificate purchase page recorded in the registry for that county
  (`purchase_url`, else the PRODUCTION_VERIFIED `canonical_url` of the
  county-held list).

A county-level portal or published procedure is sufficient. A homepage, a
search page or an http link never is.

### The evidence record

Every decision stores `publication_path` (`PathEvidence`): ledger, inventory
type, state, county, authority, official source URL and type, destination URL
or documented procedure, path type (`auction_bidding` / `direct_purchase` /
`application` / `certificate_purchase` / `other_verified_process`),
instructions, eligibility, verification status, last-verified date, notes,
scope (`record` / `county` / `source`) and, when withheld, the missing /
stale / untrusted / review reason. Beside it: `publication_reasons` (the
codes), `publication_remediation` (the exact step that publishes the row)
and `publication_state_at`.

## Where it is enforced

- **Engine:** `harvesters/governance/publication_state.py` (`decide`,
  `build_context`, `REASONS`, `REMEDIATION`). No network; context from the
  registry, the ledgers file, the rules and the generated evidence JSON.
- **Writer:** `scripts/publication_state_writer.py --state XX` reads every
  active row by keyset pages, decides, PATCHes only changed rows (grouped per
  identical decision), appends one `publication_decisions` row per change
  (prior state, new state, reasons, remediation, path evidence, run id) and
  writes a counts-only report. Plan-only when 031 is absent. It never
  closes a row and never writes a lifecycle status.
- **Workflow:** the writer runs after every sync (FL deeds / certificates /
  laft; LA; TX; the expansion matrix) and as the manual `job=publication`.
- **Server (migration 031):** the `properties` access policy is ALTERED (never
  dropped; it stays the table's single PERMISSIVE / ALL / PUBLIC policy):
  `USING (is_approved() AND (publication_state = 'CUSTOMER_PUBLISHED' OR is_admin()))`.
  Every customer surface - `get_properties`, `get_properties_list`, counts,
  the Map, exports, search, the property page, any direct REST read - sees
  the same inventory. **NULL (no decision yet) is not customer-visible**, so
  the apply order is: apply 031, then run the writer for every production
  state (`job=publication`). Two RPCs: `count_publication_states(p_state,
  p_ledger_type)` (SECURITY DEFINER, counts only, every approved account) and
  `get_withheld_states(p_state)` (SECURITY INVOKER: empty for customers,
  the withheld rows' decisions for admins). `publication_decisions`:
  service-role write, admin read.
- **Frontend (defence in depth, labels, counts):** `app.js` reads both RPCs
  in `loadAll` (PGRST202 = not enforced, today's behaviour). Every ledger
  strip gains "Withheld from customers: N records withheld pending
  verification (a no verified acquisition path, b source or rules under
  review, c stale ...)"; the Home tile and the dashboard rows carry the same
  count; a zero ledger with withheld rows reads **WITHHELD** ("Records
  withheld pending verification ... not proof that no properties exist"),
  or SOURCE_RESTRICTED when every withheld row is withheld for its source.
  Admins see each withheld row labelled "Not customer-published: ..." on the
  card and, on the property page, the state, the milestone reached, every
  reason, the path evidence and "To publish: ...". `isPublishable()` refuses
  any non-published state to a non-admin even if the server returned it.

## Fail-safe behaviours

| Situation | Behaviour |
|---|---|
| No path | `ADMIN_ONLY_NO_PATH`; admin sees the reason and the capture step |
| Rules not verified / county not covered | `ADMIN_ONLY_SOURCE_REVIEW`; the zero case names it |
| Source terms unresolved | `ADMIN_ONLY_SOURCE_REVIEW` (SOURCE_RESTRICTED / SOURCE_UNREVIEWED) |
| Stale observation / passed sale / old evidence | `ADMIN_ONLY_STALE`; the row and its path evidence are kept |
| Source read failed | nothing changes: the writer reads active rows, a failed read raises and writes nothing, no row is closed |
| Not offered | RULES_NOT_OFFERED; the ledger shows the verified rules explanation and a zero |
| No customer-visible records | the strip distinguishes "No current inventory" from "N records withheld pending verification" |
| 031 not applied | the RPCs do not exist; the frontend shows no gate and the source-level rule decides, as today |

Tester "preview" mode (`config.js publicationMode`) is a frontend convenience;
once 031 is applied the server withholds the same rows from every non-admin,
preview included. Only admins read withheld rows.

## Tests

- `tests/python/test_publication_state_gate.py` (38): engine per ledger
  (record and county-level paths, homepage / search / http refused, verified
  evidence, needs-review, registry certificate page), source / rules /
  validation / freshness / stale evidence / closed, vocabulary and remediation,
  the writer (changed rows only, grouped PATCH bodies without a lifecycle
  status, the log with prior state), the workflow wiring, static 031 checks
  (ALTER not DROP, CHECK = the engine states, revoke before grant, RPC
  grants, no RPC recreation), the app.js / stub mirrors, and the LIVE layer
  (026 fixture + 025 + 026 + `is_admin()` + 031 applied twice): customer
  reads CUSTOMER_PUBLISHED rows only through `get_properties()` and a direct
  select, NULL never visible, admin reads every row, pending / unknown / anon
  read nothing, counts RPC for every approved account, withheld RPC empty for
  customers, the decision log, the single permissive policy, the CHECK.
- Playwright (`tests/run_test.mjs`, stub knob `?pubgate=1`): `gateCustomer`,
  `gateAdmin`, `gateOff`, `gatePageAdminWithheld`,
  `gatePageCustomerPublished`, `gatePageCustomerWithheldDeepLink`,
  `gatePageOff` - per ledger cards, counts, withheld text and chips; search,
  Map, Home tile and the CSV export for a customer versus an admin; the
  property page's decision block; a customer deep link to a withheld row.
- `sw.js` → `tdw-shell-v119`.

## What the first Florida run would decide (read-only preview, 2026-10-10)

Decided offline with `--rows` against a read-only export of the active
Florida rows (counts only; the export was deleted after the run):

| Ledger | Rows | Customer-published | Withheld | Why |
|---|---|---|---|---|
| Auctions | 1,185 | 921 | 264 `ADMIN_ONLY_STALE` | 264 not observed in 7 days (the rows off the county's current sale list), 4 of them also past their sale date |
| Available | 153 | 44 | 109 `ADMIN_ONLY_NO_PATH` | 73 no official acquisition page found, 28 page could not be read, 8 captured but not verified |
| Liens & Certificates | 1,611 | 1 | 1,610 `ADMIN_ONLY_STALE` | not observed in 7 days: LienHub has answered 403 on every run since stamping shipped, so `last_seen_at` is NULL and `updated_at` is older than the window |

No row fails the source or rules gate in Florida (every production source is
APPROVED*, all three ledgers OFFERED). The lien column is the gate doing its
job: an inventory nobody has been able to re-read for weeks is not customer
inventory until a successful read says so.

## Blocker

Nothing here changes production. Applying 031 and the first writer run are
the owner's decision, in that order, in one maintenance window: between the
two steps customers see no inventory (NULL is withheld by design). The
expected first-run counts can be previewed without writing anything:
`python3 scripts/publication_state_writer.py --state FL --dry-run` with the
service key, or `--rows <file>` against an exported rows file.
