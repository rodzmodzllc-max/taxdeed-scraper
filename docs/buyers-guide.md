# Buyer's Guide - data (backend)

The published file follows `docs/buyers-guide-contract.md` (front end: `public/buyers-guide.js`).

## Files

| file | what |
|---|---|
| `data/buyers_guide_questions.csv` | the questions per ledger: `id`, `order`, `group`, `level`, `question`, default `where_to_look` |
| `data/buyers_guide_answers.csv` | researched answers, one row per (state, county, ledger, question) |
| `data/buyers_guide_captures.csv` | what a capture run read: answer key, quote hash, URL, result, run id, date |
| `harvesters/sources/buyers_guide.py` | rules (`problems()`), `build()` / `render()`, `answer_for()` |
| `scripts/build_buyers_guide.py` | writes `public/buyers-guide.json` and the root copy; `--check` is pinned by `tests/python/test_buyers_guide.py` |
| `scripts/capture_buyers_guide.py` | the capture (`job=evidence`, `evidence_scope=buyers_guide`, optional state codes in `evidence_counties`) |
| `scripts/record_buyers_guide_captures.py` | records a capture run's job log in `data/buyers_guide_captures.csv` |

## Answer rows

`state, county, ledger, question, status, answer, quote, source_url, source_title, citation, office, verified_on, where_to_look, note`

- `county` blank = statewide. A county row replaces the statewide row for that county only.
- `ledger` is `AUCTIONS`, `AVAILABLE` or `LIENS_CERTIFICATES`; `ALL` only for `office` / `due_diligence`, published
  under each ledger the state tracks unless the same county has a ledger-specific row.
- `status` is the research claim: `VERIFIED` / `PARTIALLY_VERIFIED` (with `answer`, `quote`, https `source_url`, and the
  research read date in `verified_on`), or `NOT_VERIFIED` / `SOURCE_RESTRICTED` (no answer or quote; `where_to_look`
  or `source_url` says where to check).
- Rules (`problems()`): every number in an answer appears in its quote or citation, written the same way; no advice
  wording; no 9+ digit run (parcel / account-like); quote at most 600 characters; one row per key.

## Verification

Research (agents, search engines, a person) only finds the page and drafts the answer. The published file says
`VERIFIED` only when a capture run fetched `source_url` and found every `" ... "`-separated piece of the quote on it
(`match_quote()`: entities decoded, NFKC, straight quotes, collapsed whitespace, lower case). Then `verified_on` is
the capture date. The latest capture per (answer, quote, URL) decides:

| capture | published |
|---|---|
| FOUND | VERIFIED (answer, quote, link, date) |
| PARTIAL | PARTIALLY_VERIFIED |
| BLOCKED (401 / 403 / 429 / challenge) | SOURCE_RESTRICTED, page named in `where_to_look` |
| NOT_FOUND, FETCH_FAILED, DENIED, none | NOT_VERIFIED, page named in `where_to_look` |

A changed quote or URL needs a new capture. A page that stops carrying the quote downgrades the answer on the next run.

### Running a capture

1. Dispatch `harvest-and-sync.yml` with `job=evidence`, `evidence_scope=buyers_guide` (optionally `evidence_counties=FL,TX`).
   It reads each cited page once (at least one second apart per host) through the discovery guard: the guide's pages
   map to `buyers_guide_<state>`, which holds a discover-only interim permission (owner request 2026-10-29, expires
   2027-04-12). Blocked pages are never retried or worked around.
2. Save the job log and run `python3 scripts/record_buyers_guide_captures.py --log job.log --run-id <run> --date <YYYY-MM-DD>`.
3. `python3 scripts/build_buyers_guide.py`, commit the CSV and the two JSON copies.

## Facts found during research that affect the rest of the product

- Louisiana (Acts 2024 No. 774, 2025 No. 411; constitutional amendment Acts 2024 No. 409): from 2026-01-01 the parish
  tax sale sells a tax lien certificate (bid down the monthly interest rate), not the property.
- Colorado SB 26-144 (effective 2026-06-01): treasurer's deeds replaced by a public auction; certificates issued from
  2026-01-01 expire after seven years.
- Oklahoma: tax certificate sections repealed in 2008; only the June resale.
- `kcmolandbank.org` now redirects to an unrelated site; never link it.
