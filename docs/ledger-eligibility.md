# Ledger eligibility, county coverage and zero-count semantics (2026-10-10)

Stacked on `docs/state-rules.md` (PR #133). Nothing here writes to production,
applies a migration, dispatches a workflow, approves a source or activates
anything. No migration was needed: eligibility and coverage are repository
records rendered into `public/state-rules.json`.

## The seven separate facts behind every ledger count

| Fact | Where it comes from | Never derived from |
|---|---|---|
| **Ledger eligibility** - does this state offer the product | `data/state_ledgers.csv` `eligibility` (+ basis, official source, verification date) | a count, a harvest result, a vendor page |
| **County eligibility / coverage** - which counties have a tracked source or a verified procedure | the registry rows that feed the ledger (`county_coverage()`), plus county-scoped VERIFIED PROCEDURE / SOURCE rules | inventory rows |
| **Tracking** - does TAXACQ read a source for it | `data/state_ledgers.csv` `status` (TRACKED / NOT_TRACKED) | eligibility |
| **Current qualifying count** | the rows loaded for this viewer (after the publication gate) | the last known count |
| **Last successfully observed count** | `county_source_registry.last_success_row_count` summed over the ledger's units | the loaded rows |
| **Harvest completeness and health** | `sourceHealthState()` per unit (CURRENT / RECENT / STALE / PARTIAL / SOURCE_UNAVAILABLE / …) | the count |
| **Verification status** | the rule and ledger records (VERIFIED / NOT_VERIFIED …) | any of the above |

### Eligibility classes (`state_rules.ELIGIBILITIES`)

| Class | Means | What the record must carry | Engine (`ledger_eligibility`) |
|---|---|---|---|
| OFFERED | a statute read establishes the product statewide | basis, https source, verified_on | FAIL unless a VERIFIED LAW rule covers the ledger |
| NOT_OFFERED | a statute read establishes the state has no such product | basis, https source, verified_on, evidence | FAIL unless a VERIFIED LAW rule covers the ledger; never TRACKED |
| COUNTY_DEPENDENT | established county by county from a county's own published list or procedure | basis, https source, verified_on | FAIL unless a production source feeds the ledger (with a government publication read) or a verified county procedure exists |
| NOT_VERIFIED | the evidence is insufficient either way | basis; no date | FAIL if a VERIFIED LAW rule or a government source + procedure says more |
| SOURCE_RESTRICTED | the only relevant source cannot be used under the approved access rules | basis; no date | BLOCKED when supported; FAIL if an approved source feeds the ledger |

A BLOCKED finding is never permission to activate a source. Today no state is
NOT_OFFERED (no statute establishing absence was read) and none is
SOURCE_RESTRICTED in production (Texas's restricted Harris County list sits
beside an approved LGBS source, so Texas Available is NOT_VERIFIED with the
restriction named in its basis).

### The zero cases (`app.js ZERO_CASE_COPY`, checked by `zero_state_cases`)

`ledgerZeroState(kind)` decides, in this order:

1. the browser load of the ledger failed → **SOURCE_FAILURE** (whatever the count: "N loaded - load failed, may be incomplete", or "Count unavailable");
2. eligibility NOT_OFFERED → **NOT_OFFERED** (A);
3. rows present, or still loading → no zero case;
4. every unit's last read unavailable / partial / stale and none current → **SOURCE_FAILURE** (F) - the last known count is shown, labelled "Last known count", and the copy says nothing was closed;
5. ledger not TRACKED → **NOT_IMPLEMENTED** (E);
6. rows withheld or awaiting review, or eligibility SOURCE_RESTRICTED → **SOURCE_RESTRICTED** (E);
7. eligibility NOT_VERIFIED → **NOT_VERIFIED** (D) - "not a statement that the state does not offer it";
8. eligibility COUNTY_DEPENDENT → **COUNTY_DEPENDENT** (C) - names the covered counties;
9. otherwise → **NO_CURRENT_INVENTORY** (B) - "this product exists … no qualifying record in the last successful source read".

Every ledger head carries the strip (`.ledger-status`: Offered here / Tracked /
Current count / Source read, the zero explanation, the ledger's meaning, a
"State rules and sources" link and the official reference). The rules page
(`#/rules`) shows the same strip inside each ledger block, with the
classification basis, the responsible office, county coverage (and whether
the selected county is covered), that ledger's rules, the general rules, the
verified county procedures, the rule history and the open items.

### No false zero

- A failed or incomplete read closes nothing: `sync_state_inventory.CLOSEABLE`
  is exactly `{COMPLETE, EMPTY}` and `laft_lifecycle` closes only after a
  COMPLETE or EMPTY read (`no_false_zero_lifecycle`).
- A failed load or read never prints a bare zero (`no_false_zero_copy`, the
  Playwright checks `zeroLoadFailure` / `zeroPartialRead`).
- A missing eligibility record reads NOT_VERIFIED, never NOT_OFFERED.

## Rules registry: versions and dependents

`data/state_rules.csv` gained `ledger` (AUCTIONS / AVAILABLE /
LIENS_CERTIFICATES, `|`-joined, or ALL), `office`, `related_sources`,
`depends_on`, `implementation_status` (IMPLEMENTED / DISPLAY_ONLY /
NOT_IMPLEMENTED / NOT_APPLICABLE), `test_ref`, `version`, `changed_on`. An
IMPLEMENTED rule names the code that depends on it and the test that pins it
(the file must exist). `data/state_rules_history.csv` is append-only: one row
per superseded version with the prior status and statement, the change and
what it affects; a rule at version N must have history rows 1..N-1
(`history_problems`, engine check `rule_history`).

First recorded change: Texas `tax_sale_model` v2 separates the sale (34.01),
the strike-off and the taxing unit's resale (34.05) and records that
struck-off property is not automatically for sale at a fixed price; v1 is
kept in the history table. The Texas Available copy in app.js was corrected to
say the same (`tx_struck_off_copy`).

New VERIFIED LAW row: Florida `certificate_instrument` (F.S. 197.502(6)(a)-(b),
read 2026-10-05, the same read as the opening-bid rule): the certificate is a
lien instrument, not ownership - the basis for Florida Liens & Certificates
being OFFERED.

## Texas and Florida

- **Texas** (`tx_classification`, `tx_struck_off_copy`): `tx_realauction`
  feeds sale rows only; `tx_lgbs` feeds sale and struck-off rows by its own
  status; the blocked vendors feed nothing; no copy claims a fixed price.
  Auctions is COUNTY_DEPENDENT (31 counties fed; Galveston's Sheriff
  procedures verified); Available is NOT_VERIFIED (the taxing-unit resale
  process is unverified, Harris's list restricted); Liens is NOT_VERIFIED.
  LGBS was not retried, GovEase not implemented, blocked vendors untouched.
- **Florida** (`fl_separation`): certificates, deed auctions and Lands
  Available have disjoint source sets and the certificate copy says the lien
  is never the land. All three ledgers are OFFERED on the 2026-10-05 statute
  read.

## State × ledger eligibility matrix

Engine result for `ledger_eligibility` in parentheses.

| State | Auctions | Available | Liens & Certificates |
|---|---|---|---|
| FL | OFFERED, tracked (PASS) | OFFERED, tracked (PASS) | OFFERED, tracked (PASS) |
| TX | COUNTY_DEPENDENT, tracked (PASS) | NOT_VERIFIED, tracked (NOT_VERIFIED) | NOT_VERIFIED, not tracked (NOT_VERIFIED) |
| LA | NOT_VERIFIED, not tracked | COUNTY_DEPENDENT (East Baton Rouge), tracked (PASS) | NOT_VERIFIED, not tracked |
| MI | COUNTY_DEPENDENT (Eaton, Lenawee), tracked (PASS) | COUNTY_DEPENDENT (Detroit, Oceana; review pending), tracked (PASS) | NOT_VERIFIED, not tracked |
| WY | COUNTY_DEPENDENT (Albany; a lien sale), tracked (PASS) | NOT_VERIFIED, not tracked | COUNTY_DEPENDENT (Albany, by verified procedure; no inventory source), not tracked (PASS) |
| SC | COUNTY_DEPENDENT (York; Oconee unreviewed), tracked (PASS) | COUNTY_DEPENDENT (Horry, Georgetown; review pending), tracked (PASS) | NOT_VERIFIED, not tracked |
| CO | COUNTY_DEPENDENT (Douglas lien sale; Morgan deed auctions unreviewed), tracked (PASS) | NOT_VERIFIED, not tracked | COUNTY_DEPENDENT (Morgan, Douglas), tracked (PASS) |
| WI | COUNTY_DEPENDENT (Green; Dane unreviewed), tracked (PASS) | NOT_VERIFIED, not tracked | NOT_VERIFIED, not tracked |
| MO | NOT_VERIFIED, not tracked | COUNTY_DEPENDENT (St. Louis City; review pending), tracked (PASS) | NOT_VERIFIED, not tracked |
| OK | NOT_VERIFIED, not tracked | COUNTY_DEPENDENT (Oklahoma; review pending), tracked (PASS) | NOT_VERIFIED, not tracked |
| PA | NOT_VERIFIED, not tracked | COUNTY_DEPENDENT (Fayette; review pending), tracked (PASS) | NOT_VERIFIED, not tracked |
| MN | NOT_VERIFIED, not tracked | COUNTY_DEPENDENT (Ramsey; review pending), tracked (PASS) | NOT_VERIFIED, not tracked |
| TN | NOT_VERIFIED, not tracked | COUNTY_DEPENDENT (Shelby; review pending), tracked (PASS) | NOT_VERIFIED, not tracked |

Verified as offered: FL × 3. Not offered: none. County-dependent: 19
state/ledger pairs. Not verified: 17. Engine totals at this head: PASS 219,
FAIL 0, BLOCKED 0, NOT_APPLICABLE 25, NOT_VERIFIED 52.

## Blocker

Unchanged from `docs/state-rules.md`: the sandbox's network policy refuses
the official statute hosts (CONNECT 403 from the proxy, re-checked
2026-10-10), so no statute beyond the 2026-10-05 Florida read could be read.
Every NOT_VERIFIED cell above stays so until a statute is read from an
environment that can reach it; the record then changes in
`data/state_ledgers.csv` with its basis, source and date, and the engine
re-checks it.

## Tests

- `tests/python/test_ledger_eligibility.py` (24): record validity, eligibility
  evidence rules, engine refusals (OFFERED without law, COUNTY_DEPENDENT
  without a government read, SOURCE_RESTRICTED beside an approved source,
  NOT_VERIFIED contradicted by the record), county coverage, rule history and
  versions, page data, the app's zero-case copy and precedence, no false zero
  on a failed read, Texas / Florida separation.
- Playwright (`tests/run_test.mjs`): `zeroOfferedNoInventory`,
  `zeroNoneWhenRows`, `zeroLoadFailure`, `zeroPartialRead`, `zeroNotVerified`,
  `zeroNotImplemented`, `zeroEligibleButUntracked`, `zeroPendingReview`,
  `zeroCountyDependent`, `zeroNotOfferedUnclaimed`, `zeroStripToRules`,
  `rulesCoverage`, `rulesHistory`. Stub knobs: `?emptyledger=<type>`,
  `?unitstatus=<source_id>:<STATUS>[:<count>]`, `?certunit=1` (a complete
  `fl_lienhub_certificates` read for Walton).
- `sw.js` → `tdw-shell-v118`.
