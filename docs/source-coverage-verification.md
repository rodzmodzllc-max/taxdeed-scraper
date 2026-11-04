# State-by-state source coverage, regulatory verification and acquisition-path completion (2026-10-11)

Backend only. No migration, no production write, no dispatch, no frontend
change. The generated report is `docs/state-coverage.md` +
`data/current_state/state-coverage.json` (builder
`scripts/build_state_coverage.py`, `--check` pinned by
`tests/python/test_state_coverage.py`).

## 1. What the report answers

For every production state x ledger (13 states x 3 ledgers = 39 units) the
builder reads only repository records - the registry
(`data/county_source_registry.csv`), the rules registry
(`data/state_rules.csv`), the ledger declarations (`data/state_ledgers.csv`),
the counts-only production snapshots (`data/current_state/coverage-*.json`,
`source-quality-*.json`, read-only on 2026-10-10) and the acquisition
evidence status file (`public/acquisition-evidence.json`) - and classifies the
unit into exactly one concept, in this precedence:

| Concept | Meaning |
|---|---|
| PRODUCT_NOT_OFFERED | the ledger's eligibility is NOT_OFFERED with authoritative evidence |
| RULES_NOT_VERIFIED | no production source and eligibility NOT_VERIFIED; or a zero whose eligibility is not evidenced |
| SOURCE_RESTRICTED | only restricted sources are known, or eligibility SOURCE_RESTRICTED |
| OFFERED_SOURCE_NOT_IMPLEMENTED | eligibility evidenced, known sources, none in production |
| APPROVAL_UNRESOLVED | production sources exist, none is APPROVED for customers |
| SOURCE_IMPLEMENTED_NEVER_READ | no row and no read in the snapshot |
| SOURCE_FAILED_OR_STALE | every active row is unstamped or read more than 36 h before the snapshot |
| RECORDS_WITHHELD_NO_PATH | AVAILABLE rows with acquisition units, none VERIFIED |
| OFFERED_VERIFIED_EMPTY | eligibility OFFERED / COUNTY_DEPENDENT, a recorded read, 0 active rows |
| CURRENT | active rows, read within the window |

Every unit carries its denominators (known / implemented / approved
sources, active rows, field fill `n/N`, acquisition units by status, withheld
count where the snapshot can state it) and the next action for its concept.
A zero with eligibility NOT_VERIFIED is never "verified empty". Manual-only
sources (`tx_lgbs`, `tx_realauction`, pinned equal to
`unit_freshness.MANUAL_ONLY_SOURCES`) are named as such in the reasons.

Result on the 2026-10-10 snapshots: CURRENT 6, SOURCE_FAILED_OR_STALE 4,
APPROVAL_UNRESOLVED 7, RULES_NOT_VERIFIED 19, OFFERED_VERIFIED_EMPTY 1,
OFFERED_SOURCE_NOT_IMPLEMENTED 1, SOURCE_IMPLEMENTED_NEVER_READ 1,
PRODUCT_NOT_OFFERED 0, SOURCE_RESTRICTED 0, RECORDS_WITHHELD_NO_PATH 0 (of 39).

## 2. Registry: metadata completed for every production row

Before: 163 of the 185 PRODUCTION_VERIFIED rows carried no
`publishing_unit_name`, `amount_kind`, `update_frequency` or
`source_terminology`. After: 0 of 185, filled in
`scripts/build_county_source_registry.py` from repository evidence only
(the harvesters' own CSVs, the workflow schedule, the financial-terms table
and the harvest status files):

- FL auctions (47): Clerk of the Circuit Court on RealAuction (Okaloosa:
  Bid4Assets); `OPENING_BID`; twice-daily deeds job.
- FL Available (52): Clerk (Orange: Comptroller); realTDM rows
  `PUBLISHED_AMOUNT_KIND_UNSPECIFIED` (its "base purchase price"), the rest
  `OPENING_BID` under F.S. 197.502(7); daily laft job.
- FL certificates (32): Tax Collector on LienHub;
  `PUBLISHED_AMOUNT_KIND_UNSPECIFIED`; daily certificates job; `restrictions`
  records `SOURCE_UNAVAILABLE since 2026-10-01` (HTTP 403 for all 32 counties).
- TX RealAuction (24): county on RealAuction, sale authority not verified per
  county; manual-only.
- TX LGBS (8): publishing unit stays `COUNTY` (the taxing unit); the
  publisher name is the delinquent-tax counsel, a vendor listing; manual-only.

`publishing_unit` is always a government unit (`states.PublishingUnit`);
the platform or vendor is named in `publishing_unit_name`. The derived
`public/county-intelligence.json` and `public/source-inventory.json` were
rebuilt (the admin Sources panel now names publishers instead of source ids).

## 3. Rules registry vocabulary

`harvesters/governance/state_rules.py` statuses now include
`PARTIALLY_VERIFIED` (a read source with a stated `ambiguity`) and
`SOURCE_RESTRICTED` (a source the project may not use; `evidence` names the
restriction, no verification date). `READ_STATUSES` = VERIFIED,
PARTIALLY_VERIFIED. The verification engine still passes only `VERIFIED`;
nothing partial ever passes a check. The labels ship in
`public/state-rules.json` `statuses`, which the frontend already reads.

One row added: TX / Harris / `tax_sale_list_source`, SOURCE_RESTRICTED,
citing registry row `tx_hctax` (LEGAL_REVIEW_REQUIRED: hctax.net terms not
cleared for redistribution). No LAW row was added: statute sites
(legislature.mi.gov, legis.la.gov, scstatehouse.gov,
statutes.capitol.texas.gov) are unreachable from the sandbox, and a citation
is never invented. Rules: 37 (VERIFIED 17, NOT_VERIFIED 19,
SOURCE_RESTRICTED 1); engine findings PASS 219, NOT_VERIFIED 52,
NOT_APPLICABLE 25, FAIL 0.

## 4. Field provenance for FL auction and certificate rows

`properties.field_provenance` was never written for FL auction / certificate
rows by the PowerShell syncs (snapshot: 243 of 1,185 active auction rows and
25 of 1,611 certificate rows carried any entry). `scripts/stamp_seen.py
--provenance` (both FL stamp steps in `harvest-and-sync.yml`) now records, for
every county the run read, one `vendor_listing` entry per non-blank list
column (`PROVENANCE_COLUMNS`) with the source id (`fl_realauction` /
`fl_bid4assets_okaloosa` / `fl_lienhub_certificates`) - only where no entry
exists, never replacing one, keyset reads, one PATCH per changed row,
idempotent. It takes effect at the next scheduled run; nothing was written
from this branch.

## 5. Not done, and why

- No statute verification (sites unreachable); no eligibility moved to
  OFFERED / NOT_OFFERED outside Florida.
- No publication review changed: the seven APPROVAL_UNRESOLVED units are the
  owner's decision.
- LienHub (403), LGBS / TX RealAuction (manual-only) were not retried.
- Texas tax-sale authority per county is unverified; the registry says so.
