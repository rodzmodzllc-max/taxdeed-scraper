# State rules, verification engine, and the customer State rules page (2026-10-10)

This PR is stacked on #132. Nothing in it writes to production, applies a
migration, dispatches a workflow or approves a source.

## What was built

| Piece | File | What it does |
|---|---|---|
| Rules registry | `data/state_rules.csv`, `harvesters/governance/state_rules.py` | One row per rule. `kind` keeps four kinds of information apart: **LAW** (a statute that was read), **PROCEDURE** (a government page or document that was read), **SOURCE** (how a data source behaves) and **UNRESOLVED**. `status` is VERIFIED / NOT_VERIFIED / NOT_PUBLISHED / NOT_APPLICABLE / NOT_YET_IMPLEMENTED / CONFLICT. A VERIFIED row must carry an https source, its title, a verification date and the repository evidence of the read; a VERIFIED LAW row must also carry its citation. An unverified row has no verification date, and a "lead only" citation is never VERIFIED. A county row replaces the statewide row of the same topic **for that county only** (`rules_for`). |
| Ledger support | `data/state_ledgers.csv` | Each of the three ledgers, per state: TRACKED / NOT_TRACKED / NOT_OFFERED / NOT_VERIFIED. NOT_OFFERED ("this state has no such product") needs evidence; none is claimed today, so every untracked ledger reads "Not tracked by TAXACQ". |
| Verification engine | `harvesters/governance/state_verification.py` | For each production state it compares the records with the code and the customer files. Each finding is PASS / FAIL / BLOCKED / NOT_APPLICABLE / NOT_VERIFIED. A missing record is a FAIL. There is no score. |
| Builder | `scripts/build_state_rules.py` (`--check` pinned by a test) | Writes `public/state-rules.json` (the page data, mirrored to the root) and `data/state_verification.json` (the findings). |
| Customer page | `#/rules`, `#/rules?county=<name>` (app.js `renderRulesPage`, identity.css) | Shows what TAXACQ tracks in the state, the statewide rules grouped by kind, the county's own rules and verified county procedures, and the open items. Every statement links its source; anything not read from that source reads "Not verified - check the official source". It is linked from the state picker and from every property's Source truth ("State rules"), which opens the property's county. |

## Engine checks

| Check | FAIL when |
|---|---|
| `rules_valid` | A rule breaks the evidence rules, or the state has no rule at all. |
| `state_law_recorded` | Never fails. It reads NOT_VERIFIED, with the unresolved topics listed, when no statute has been read. |
| `ledger_declared` / `ledger_tracking` | A ledger is not declared, or its declared tracking disagrees with the production sources, in either direction. |
| `ledger_copy` | The customer copy says "no source is tracked" for a ledger that a source feeds, or describes a source for a ledger that nothing feeds. |
| `copy_law_claims` | A customer ledger string cites a statute that no VERIFIED LAW rule records, and does not itself say "not verified". |
| `source_classification` | The registry's ledgers for a source differ from `harvesters/ledgers.SOURCE_LEDGERS`. |
| `publication_gate` | A source awaiting review is in the paid-beta scope. |
| `available_terms` | An AVAILABLE source has no financial-terms row. |
| `acquisition_path` | Never fails. It reads PASS only when every AVAILABLE unit has a verified official process, NOT_VERIFIED otherwise (with the count). |
| `state_page` / `customer_rules` | The state's page or its rules data is missing. |
| `rule_links` | Never fails. It reads NOT_VERIFIED when an unresolved rule's link was not opened from this environment. |

## Defects the engine found, and the fixes

| State | Defect | Fix |
|---|---|---|
| MI | The Available copy said "No Michigan post-sale available source is tracked". The Detroit Land Bank and Oceana inventories are collected. | The copy now names both land banks and their review status. |
| SC | The Available copy said "No South Carolina post-sale available source is tracked". Horry and Georgetown are collected. | The copy now names both Commissions, the redemption-period rule and each county's own process. |
| TN | The certificate copy stated "Tennessee sells no tax-lien certificates" and "Tennessee tax sales sell redeemable deeds" as facts. They come from a survey, not a statute read. | It now says no certificate source is tracked and that the question is not verified. |
| TX | The struck-off copy asserted "the same statutory redemption rights", and the redeemable-deed copy summarised Tex. Tax Code §34.21 as fact. Counsel review of that summary is still open. | Both now say the redemption terms are not verified against the statute's text. |

## State verification matrix

The figures are from `data/state_verification.json` at this PR's head.

- **Tax-sale model**: "statute read" means a statute was read and recorded. "Not verified" means no statute has been read; the county or source facts that were verified are still listed.
- **Acquisition path**: AVAILABLE units with a verified official process, out of all AVAILABLE units in the state.
- **Customer rules UI**: the `#/rules` page.

| State | Tax-sale model | Ledgers tracked (Auctions / Available / Liens) | Rules documented | Acquisition path | Data gaps fixed in this stack | Customer rules UI | Tests |
|---|---|---|---|---|---|---|---|
| FL | statute read (F.S. 197.502(6),(7); 197.542(1)) | tracked / tracked / tracked | 3 LAW verified; 4 unresolved (escheat, certificate term, redemption, registration) | 19/52 units verified | none new | yes | `test_state_rules.py` |
| TX | not verified (34.21 open with counsel) | tracked / tracked / not tracked | 2 SOURCE verified; 2 unresolved | 1/8 (Galveston) | Cause numbers are no longer used as parcels (#132). Copy no longer states redemption law as fact. | yes | yes |
| LA | not verified | not tracked / tracked / not tracked | 1 SOURCE verified (dated Public Domain list); law unresolved | 1/1 | none new | yes | yes |
| MI | not verified | tracked / tracked / not tracked | 1 SOURCE verified; law unresolved | 1/3 | Available copy corrected | yes | yes |
| WY | not verified | tracked / not tracked / not tracked | Albany procedure verified (the sale sells certificates) | n/a | none | yes | yes |
| SC | not verified (12-51-90 lead) | tracked / tracked / not tracked | Georgetown procedures verified (2) | 2/2 | Available copy corrected | yes | yes |
| CO | not verified | tracked / not tracked / tracked | Douglas procedure verified (a lien sale) | n/a | none | yes | yes |
| WI | not verified (75.35 / 75.69 leads) | tracked / not tracked / not tracked | law unresolved; Green procedure in the verified evidence | n/a | none | yes | yes |
| MO | not verified | not tracked / tracked / not tracked | process unresolved | 0/1 | none | yes | yes |
| OK | not verified | not tracked / tracked / not tracked | Oklahoma County procedure verified | 1/1 | none | yes | yes |
| PA | not verified | not tracked / tracked / not tracked | Fayette procedure verified | 0/1 | none | yes | yes |
| MN | not verified | not tracked / tracked / not tracked | Ramsey source verified | 0/1 | none | yes | yes |
| TN | not verified | not tracked / tracked / not tracked | Shelby source verified; offer packet unresolved | 0/1 (NEEDS_REVIEW: packet not read) | semantics, rejected-ID read, geocode exclusion, flood budget (#132); certificate copy corrected | yes | yes |

## Blocker: statutes cannot be read from this environment

The sandbox's network policy refuses the official statute hosts, for example
`statutes.capitol.texas.gov`, `www.scstatehouse.gov` and `law.justia.com`. The
page-fetch tool cannot resolve `www.flsenate.gov` either. So no new statute was
read in this sprint:

- every legal rule other than the three Florida provisions read on 2026-10-05 is UNRESOLVED / NOT_VERIFIED, with its citation kept as a lead;
- the official links on those rows were not opened from here, and the engine reports that (`rule_links`).

To verify them, allow the official statute hosts in the environment's network
settings, or run a read-only capture. Then change each row to VERIFIED with
its evidence; the validator refuses a VERIFIED row without it.

## Not done, on purpose

- No ledger tab is hidden or added. An untracked ledger says so on the rules page and in its own copy.
- Nothing is asserted as NOT_OFFERED: that is a legal claim, and no evidence for it has been read.
- No source was activated, approved or retried. GovEase and LGBS were not touched.
