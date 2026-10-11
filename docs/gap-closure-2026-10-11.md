# Final backend completion sprint: gap closure (2026-10-11)

Backend only; no migration, no production write, no dispatch, no schedule or
secret change, no frontend edit. Branch `claude/hopeful-feynman-ykxl7y-gap-closure`,
stacked on #139 (which stacks on #136 → … → #132). The generated queue is
`docs/gap-queue.md` + `data/current_state/gap-queue.json`
(`scripts/build_gap_queue.py --check`, pinned by `tests/python/test_gap_closure.py`).

## 1. What the sandbox could and could not reach

Every county, land-bank and statute host answers HTTP 403 from the session's
egress proxy, and the fetch tool cannot resolve them (DNS). The only approved
mechanism that reads those pages is the manual `job=evidence` capture of the
harvest workflow, and dispatching a production workflow was out of scope. So
no new official page was read this sprint; everything below was closed from
records already in the repository, or is pipeline code.

## 2. Production facts established read-only (2026-10-11)

| Fact | Value |
|---|---|
| FL auction rows (active) with `certificate_no` | 0 of 1,185, although every RealAuction 'Waiting' row publishes the certificate number (`harvest_all.json` key `cert`, never synced) |
| FL certificate rows (active) with `legal_desc` | 525 of 1,611, although LienHub publishes a legal description per certificate (`harvest_certificates.json` key `legal_desc`, never synced) |
| LA Available rows last read | 4,000 on 2026-10-06, 6,334 on 2026-10-03: the LA sync has failed on HTTP 500 at `sync_state_inventory.stored_provenance` on every run since (run 38070616741, 2026-10-10 17:13 UTC); the keyset-read fix is in PR #132's stack, not on `main` |
| WY sync, 2026-10-10 | same HTTP 500 (offset read); `detect_property_changes.py` hit it too |
| LienHub | HTTP 403 for all 32 counties since 2026-10-01 (unchanged) |

## 3. Closed from repository data

- **B1 keyset reads.** `scripts/detect_property_changes.py` (`Api.population`),
  `scripts/inventory_status_writer.py` and `scripts/publication_gate.py`
  (`fetch_rows`) read a state's population through `scripts/rest_pages.read_all`
  (keyset pages, bounded retry) instead of `limit/offset`. These are the
  per-state steps that run after every sync for every state (Michigan: 30,801
  rows). A test forbids offset paging in them.
- **B2 carried list columns.** `scripts/stamp_seen.py --provenance` (both FL
  stamp steps) now also carries `CARRY_COLUMNS` fill-blank under the provenance
  precedence (`field_provenance.may_write`): the RealAuction certificate number
  → `certificate_no` on auction rows, the LienHub legal description →
  `legal_desc` on certificate rows, each with a `vendor_listing` entry naming
  the source id. A stored FDOR or hand-researched value is never replaced; the
  pass is idempotent; one PATCH per changed row. Takes effect at the next
  scheduled deeds run (auction) and the next successful LienHub read
  (certificate). Expected gain: certificate_no on up to 1,185 auction rows;
  legal_desc on up to 1,086 certificate rows once LienHub answers again.
- **A1 DLBA Vacant Land Policy.** The official policy PDF was read on
  2026-10-03 (URL, SHA-256 and quotes in `docs/available-publication-evidence.md`).
  It is now a verified `county_instructions` evidence row in
  `data/purchase_path_evidence_expansion.csv` (process, policy prices, buyer
  eligibility; `does_not_prove`: currency of the 2023 policy, Marketed Lots,
  any record price, a licence). MI Wayne `mi_detroit_landbank_lots`:
  NEEDS_REVIEW → VERIFIED. The source's publication review is unchanged
  (UNREVIEWED): verified evidence never approves a source.
- **A2 county procedure rules.** `harvesters/governance/procedure_rules.py` +
  `scripts/build_procedure_rules.py` derive one VERIFIED PROCEDURE rule per
  applicable evidence row and ledger (`acquisition_procedure_<ledger>`:
  statement = the reviewer's quoted evidence, source_url = the evidence page,
  verified_on = the observation date). 30 rules appended to
  `data/state_rules.csv` (FL 19, CO 3, MI 3, WI 2, LA 1, SC 1, TX 1); rules
  37 → 67; the engine's county coverage now lists those counties with their
  procedure; `--check` fails on a missing or drifted rule (a drift is fixed by
  hand with a history row, never by the builder).

## 4. Numbers

| Measure | Before | After |
|---|---|---|
| Acquisition-path units VERIFIED | 25 of 72 | 26 of 72 (NEEDS_REVIEW 9 → 8) |
| County PROCEDURE rules (VERIFIED) | 6 | 36 |
| Rules total | 37 | 67 (VERIFIED 17 → 47) |
| Scheduled per-state population readers paging by offset | 3 (change detection, inventory status, publication gate) | 0 |
| List columns dropped by the FL syncs | 2 | 0 (carried at the next run) |
| State × ledger classification | unchanged: CURRENT 6, SOURCE_FAILED_OR_STALE 4, APPROVAL_UNRESOLVED 7, RULES_NOT_VERIFIED 19, OFFERED_VERIFIED_EMPTY 1, OFFERED_SOURCE_NOT_IMPLEMENTED 1, SOURCE_IMPLEMENTED_NEVER_READ 1 (of 39) | same (a classification moves only when a read or a review happens) |

## 5. Still open, by category (see docs/gap-queue.md)

- **A (2)**: LA Available (deploy the keyset fix = merge PR #132's stack);
  WI Auctions verified empty (nothing to do).
- **B (4)**: Indian River / St. Lucie script-rendered process pages (browser
  capture), TN Shelby scanned packet (OCR), WY liens source adapter.
- **C (29)**: 19 RULES_NOT_VERIFIED ledgers (statutes: unreachable from the
  sandbox), 7 NEEDS_REVIEW / candidate-page units (job=evidence), CO auctions
  first read, FL Hillsborough contact page.
- **D (7)**: six FL counties whose official pages answer HTTP 403 to the
  runner; FL certificates (LienHub 403).
- **E (10)**: seven APPROVAL_UNRESOLVED ledgers (owner review), TX Harris
  (legal review), TX auctions / TX Available (manual-only by owner decision).
- **F (27)**: 20 FL counties whose official pages describe the auction only
  or name no Lands Available purchase page, 7 TX LGBS counties with no
  official resale process.
