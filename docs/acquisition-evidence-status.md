# Acquisition evidence status (2026-10-06)

Every AVAILABLE acquisition unit (state, source, county) now carries one
acquisition-evidence status. It comes from
`harvesters/sources/acquisition_evidence_status.py` and is generated into
`public/acquisition-evidence.json` under `"status"` by
`scripts/build_acquisition_evidence.py` (`--check` pinned).

| Status | Meaning | Where it comes from |
|---|---|---|
| VERIFIED | An official page or document describing the acquisition process was read and recorded | an applicable row of `data/purchase_path_evidence*.csv`, or a PRODUCTION_VERIFIED registry row naming the source's own purchase document |
| NEEDS_REVIEW | An authoritative process was identified but not verified by a capture | `data/acquisition_evidence_outcomes.csv` (`document_read` / `search_index` / a capture that could not see the wording), or official candidate pages with no capture yet |
| UNAVAILABLE | The official pages could not be read (for example HTTP 403) | a capture outcome. Never read as "no process" |
| NOT_FOUND | The official pages were read and describe no acquisition step, or no official page is known | a capture outcome, or no candidate |

## Rules

- A URL alone never makes evidence VERIFIED. An outcome row can never say
  VERIFIED, and a search-index finding is at most NEEDS_REVIEW.
- A capture outcome must cite its run id.
- Evidence is county / source-wide: one record per unit, shared by every
  property and never copied into rows. A property-specific purchase link
  stays on the row (`purchase_path_scope = 'property'`).
- Each unit names its acquisition authority (`authority_for()`): county
  clerk, treasurer, tax office, land bank, state agency, or other government
  office.
- Candidate pages (`data/acquisition_candidate_pages.csv`, now with
  `source_id` and `doc_kind`) are official government pages only.
  Aggregators, vendors, blogs and search engines are refused by a test.

## Measured status (generated file, 70 units)

| State | VERIFIED | NEEDS_REVIEW | UNAVAILABLE | NOT_FOUND |
|---|---|---|---|---|
| FL | 19 | 3 | 6 | 24 |
| LA | 1 | | | |
| TX | 1 | | | 8 |
| MI | 1 | 2 | | |
| MO | | 1 | | |
| PA | | 1 | | |
| MN | | 1 | | |
| OK | 1 | | | |
| SC | 2 | | | |

## What the customer sees

On an Available property with no verified path, "How to acquire" shows:

- **Evidence status:** the status and its reason, with the capture or
  discovery date;
- **Acquisition authority;**
- **Official pages to check:** document kind and host, each marked
  "not yet verified";
- for Detroit, the official policy document that was read.

A verified property also shows its acquisition authority under "What is the
official source?".

## Turning NEEDS_REVIEW into VERIFIED (needs authorization)

The capture path already exists, and no workflow change is needed.

1. Dispatch `harvest-and-sync.yml` with `job=evidence`,
   `evidence_scope=acquisition_candidates`, and
   `evidence_counties="St. Louis City,Fayette,Ramsey,Wayne"`.
   - It reads only the pages in `data/acquisition_candidate_pages.csv`.
   - It is value-free and writes nothing to the database.
2. Read the digest in the job log.
3. Record a `review_state=verified` row in
   `data/purchase_path_evidence_expansion.csv`, quoting the page.
4. Rebuild `public/acquisition-evidence.json`.

Network: every government host is blocked from the development sandbox
(`curl` returns 000; the fetch tool reports EGRESS_BLOCKED). The four new
NEEDS_REVIEW units were found through the search index only.
