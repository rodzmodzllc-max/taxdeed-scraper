# Backend handoff (front end -> backend), 2026-10-29

Paste the prompt at the bottom into the backend session. Everything it references is on branch
`feat/audit-and-folders` (and on `main` once that branch's PR merges).

## 1. Buyer's Guide data (new)

The front end ships the page `#/guide` (`public/buyers-guide.js`). It reads `public/buyers-guide.json`; the contract
is `docs/buyers-guide-contract.md`. Until the file exists it falls back to the verified rules in `state-rules.json`
(today: Florida Leon Available answers 3 of 4 questions; Texas and Colorado statewide answer 0 - the gap).

Backend scope:
- `data/buyers_guide_questions.csv` (catalog per ledger, from the contract) and `data/buyers_guide_answers.csv`
  (state / county / ledger / question / status / answer / quote / source_url / source_title / citation / office /
  verified_on / where_to_look).
- Research per state x ledger x question (13 states, county overrides where the procedure is county-run). Use web
  search only to FIND official pages; an answer is VERIFIED only after the page is read in a capture job (e.g. a new
  `job=evidence`, `evidence_scope=buyers_guide` reading the candidate pages, discover permission records for those
  government hosts), quoting the sentence it rests on. Statute text may keep its digits (no personal data).
- Reuse what is already verified (`data/state_rules.csv`, both purchase-path evidence tables,
  `data/available_financial_terms.csv`, `public/acquisition-evidence.json`).
- `scripts/build_buyers_guide.py` (`--check`, test-pinned) -> `public/buyers-guide.json`, mirrored to the root,
  added to the mirror `FILES` list, `DEPLOYED_BUNDLE_FILES` and the sw.js SHELL (ask the front end to bump the
  CACHE version when it ships).

## 2. Audit findings for the backend

`docs/review/audit-2026-10-28.md`, section BACKEND (44 findings), plus these from the FRONT END section that are
data or deployment work: F2 (self-signup function must be redeployed - owner), F4 (production
county_source_registry has no TN / OK rows; 121 rows vs 380 in the repo), F34 (Wayne land bank 120 parcels on 5
shared points), F38 (Dane WI rows hidden after Bid Due date), F40 / F67 (link checker never covers url_appraiser /
url_taxcoll), F69 (TX LGBS document links 404), F78 (verified Redeemed result still active), F80 (LGBS points
outside Texas), F84 (verified evidence pages now 404). The findings are NOT judged: reproduce each before fixing.

## Prompt for the backend session

> You are the backend for TAXACQ (repo rodzmodzllc-max/taxdeed-scraper). The front end has shipped the Buyer's Guide
> page and a full audit. Read, on branch `feat/audit-and-folders` (or main once merged):
> `docs/review/backend-handoff-2026-10-29.md`, `docs/buyers-guide-contract.md` and `docs/review/audit-2026-10-28.md`.
>
> 1. Build the Buyer's Guide data for every state, ledger and county we carry, per the contract:
>    `data/buyers_guide_questions.csv`, `data/buyers_guide_answers.csv`, `scripts/build_buyers_guide.py --check` ->
>    `public/buyers-guide.json`. Use as many research agents as you need (one per state x ledger) to find the
>    official pages; mark an answer VERIFIED only after a capture job has read the page, with the quote, URL and
>    date; everything else NOT_VERIFIED with where to look. Never a number that is not in the quote; no legal advice
>    wording; no property data. Add the discover permission records and an `evidence_scope=buyers_guide` capture.
> 2. Work through the backend findings in the audit (section BACKEND plus F2, F4, F34, F38, F40/F67, F69, F78,
>    F80, F84). Reproduce each with read-only SQL / logs first; fix the real ones with tests; list anything that
>    needs my decision or a production write.
> 3. When done, tell me which files changed so the front end can bump the service-worker cache and wire anything new.
